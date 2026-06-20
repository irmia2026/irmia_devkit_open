"""
_file_utils — 文件读取共享代码。
提供 UTF-8 → GBK fallback 读取，供 safe_edit / file_patch / file_diff 内部使用。
"""

import difflib
import hashlib
import os
from pathlib import Path


SAFE_EDIT_MAX_SIZE = 20 * 1024 * 1024
FILE_DIFF_MAX_SIZE = 50 * 1024 * 1024

# 扩展名黑名单（二进制），供 safe_read 兼容使用
_BINARY_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".db", ".sqlite", ".sqlite3",
})

# 文本文件扩展名白名单（即使内容像二进制也强制按文本）
_TEXT_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".clj",
    ".html", ".htm", ".css", ".scss", ".less", ".xml", ".json", ".yaml", ".yml",
    ".md", ".txt", ".rst", ".log", ".ini", ".cfg", ".conf", ".sh", ".bash", ".zsh",
    ".sql", ".vim", ".emacs", ".el", ".lisp", ".scm", ".rkt",
    ".nim", ".nims", ".nimble", ".svg",
})


# 文本编码探测相关常量
_PROBE_BYTES = 512  # 文件探针字节数
_TEXT_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "gb18030",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "utf-32",
    "utf-32-le",
    "utf-32-be",
)
_UTF_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def _has_chardet() -> bool:
    """检查是否安装了 chardet。"""
    try:
        import chardet  # noqa: F401
        return True
    except ImportError:
        return False


def _looks_like_text(s: str) -> bool:
    """文本特征验证：控制字符 <2% 且可打印字符 >=85%。"""
    if not s:
        return True
    total = max(len(s), 1)
    disallowed = sum(1 for c in s if ord(c) < 32 and c not in "\t\n\r")
    printable = sum(1 for c in s if c.isprintable() or c in "\t\n\r")
    return disallowed / total <= 0.02 and printable / total >= 0.85


def _looks_like_utf16_or_32(raw: bytes) -> bool:
    """通过奇偶字节零值比例判断是否可能是 UTF-16/32。

    UTF-16/32 编码 ASCII 字符时隔字节为 \x00；若两侧零值比例都 <80%，
    则大概率不是 UTF-16/32，跳过尝试避免在二进制上浪费时间。
    """
    if len(raw) < 4:
        return False
    odd_bytes = raw[1::2]
    even_bytes = raw[0::2]
    odd_zero_ratio = odd_bytes.count(0) / max(len(odd_bytes), 1)
    even_zero_ratio = even_bytes.count(0) / max(len(even_bytes), 1)
    return odd_zero_ratio >= 0.8 or even_zero_ratio >= 0.8


def detect_encoding(path: str | Path, sample_size: int = _PROBE_BYTES) -> str:
    """确定性文本编码检测。

    策略（按优先级）：
    1. BOM 前置匹配
    2. 排除非 UTF-16/32 的二进制样本（零值分布分析）
    3. 按序尝试 9 种编码，解码成功且通过文本验证即返回
    4. 样本末尾截断重试（变长编码末尾可能被截断）
    5. chardet 统计模型兜底
    6. Latin-1 无损 fallback
    """
    p = Path(path)
    file_size = p.stat().st_size
    read_size = min(sample_size, file_size)
    if read_size == 0:
        return "utf-8"

    with p.open("rb") as f:
        raw = f.read(read_size)

    # 1) BOM 前置匹配
    for bom, enc in _UTF_BOMS:
        if raw.startswith(bom):
            return enc

    # 2) 是否像 UTF-16/32？不像则跳过这些编码尝试
    #    utf-8-sig 已在 BOM 检测中处理，这里不再尝试
    has_null = b"\x00" in raw
    try_utf16_32 = has_null and _looks_like_utf16_or_32(raw)
    encodings_to_try = tuple(
        e for e in _TEXT_ENCODINGS
        if e != "utf-8-sig"
        and (try_utf16_32 or (not e.startswith(("utf-16", "utf-32"))))
    )

    # 3) 按序尝试编码
    for enc in encodings_to_try:
        try:
            decoded = raw.decode(enc)
            if _looks_like_text(decoded):
                return enc
        except UnicodeDecodeError as exc:
            # 4) 末尾截断重试：变长编码样本末尾可能切到多字节中间
            if exc.start >= len(raw) - 4 and exc.start > 0:
                for trim in range(1, min(4, len(raw)) + 1):
                    try:
                        decoded = raw[:-trim].decode(enc)
                        if _looks_like_text(decoded):
                            return enc
                    except UnicodeDecodeError:
                        continue
        except Exception:
            continue

    # 5) chardet 兜底
    if _has_chardet():
        import chardet
        result = chardet.detect(raw)
        if result and result.get("confidence", 0) > 0.7:
            detected = result.get("encoding")
            if detected:
                try:
                    raw.decode(detected)
                    return detected.lower()
                except (UnicodeDecodeError, LookupError):
                    pass

    # 6) Latin-1 无损 fallback
    return "latin-1"


def _detect_encoding(path: str | Path) -> str:
    """兼容旧内部名。"""
    return detect_encoding(path)


def is_binary_file(path: str | Path, sample_size: int = 8192) -> tuple[bool, str]:
    """检测文件是否为二进制文件，返回 (is_binary, reason)。"""
    p = Path(path)
    ext = p.suffix.lower()

    if ext in _BINARY_EXTENSIONS:
        return True, "extension"
    if ext in _TEXT_EXTENSIONS:
        return False, "text_extension"

    file_size = p.stat().st_size
    if file_size == 0:
        return False, "unknown"

    read_size = min(sample_size, file_size)
    with p.open("rb") as f:
        chunk = f.read(read_size)

    if not chunk:
        return False, "unknown"

    null_ratio = chunk.count(b"\x00") / len(chunk)
    if null_ratio > 0.3:
        return True, "content"

    control_chars = sum(1 for b in chunk if b < 32 and b not in (9, 10, 13))
    control_ratio = control_chars / len(chunk)
    if control_ratio > 0.1:
        return True, "content"

    return False, "unknown"


def _check_path_safety(path: str | Path, *, read: bool = True) -> dict | None:
    """统一路径安全校验：拒绝 .. 穿越和系统目录访问。"""
    raw = str(path).replace("\\", "/")
    if ".." in raw.split("/"):
        return {"ok": False, "error": "路径包含 .. 穿越，已被拒绝"}

    p = Path(path).resolve()
    path_str = str(p).replace("\\", "/")
    from .file_remove import _FORBIDDEN_PREFIXES

    for forbidden in _FORBIDDEN_PREFIXES:
        forbidden_norm = forbidden.replace("\\", "/")
        if path_str.lower().startswith(forbidden_norm.lower() + "/") or path_str.lower() == forbidden_norm.lower():
            return {
                "ok": False,
                "error": f"禁止访问系统目录: {p}",
                "proposal": "路径位于受保护的系统目录中，读取操作已被拦截。",
                "evidence": {"path": str(p), "blocked_by": forbidden},
            }
    return None


def check_path_allowed(path: str | Path) -> dict | None:
    """safe_read 专用入口：检查路径是否允许访问。"""
    return _check_path_safety(path, read=True)


def read_file(path: str | Path, *, encoding: str = "auto") -> str:
    """读取文件内容。编码 auto 时自动检测，否则使用指定编码。保留原始换行符。"""
    p = Path(path)
    enc = detect_encoding(p) if encoding == "auto" else encoding
    with p.open("r", encoding=enc, errors="replace", newline="") as f:
        return f.read()


def read_file_with_encoding(
    path: str | Path,
    *,
    encoding: str = "auto",
    max_bytes: int | None = None,
) -> tuple[str, str]:
    """读取文件内容，同时返回检测到的编码。保留原始换行符。"""
    p = Path(path)
    enc = detect_encoding(p) if encoding == "auto" else encoding
    with p.open("r", encoding=enc, errors="replace", newline="") as f:
        if max_bytes is None:
            return f.read(), enc
        return f.read(max_bytes), enc


def human_size(n: int) -> str:
    """字节数 → 人类可读大小（保留一位小数，整数则省略小数）。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            s = f"{n:.1f}{unit}"
            return s.replace(".0", "") if ".0" in s else s
        n /= 1024
    s = f"{n:.1f}PB"
    return s.replace(".0PB", "PB")


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """原子写入文本文件：先写同目录临时文件，再 os.replace 替换目标文件。

    保留原始换行符（调用方需确保 content 中的换行符已是期望形式）。
    """
    import os as _os
    import tempfile as _tmp

    target = Path(path)
    fd, tmp_path = _tmp.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_path)
    try:
        with _os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
        _os.replace(str(tmp), str(target))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _first_existing_parent(path: Path) -> Path:
    """向上查找第一个存在的父目录。"""
    cur = path
    while cur and not cur.exists():
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return cur if cur and cur.exists() else Path.home()


def backup_name_stem(p: Path) -> str:
    """生成包含父目录哈希的备份文件名主干，避免同名不同目录文件混淆。"""
    parent_str = str(p.parent.resolve()).replace("\\", "/")
    dir_hash = hashlib.sha256(parent_str.encode("utf-8")).hexdigest()[:8]
    return f"{p.name}.{dir_hash}"


def find_closest_line(content: str, old: str, threshold: float = 0.5) -> dict | None:
    """在 content 中找与 old 首行最接近的匹配行，返回行号和文本。保留缩进。"""
    lines = content.split("\n")
    best = None
    best_ratio = 0
    first_line = old.split("\n")[0]
    for i, line in enumerate(lines):
        ratio = difflib.SequenceMatcher(None, first_line, line).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = (i + 1, line.rstrip("\r")[:80])
    if best and best_ratio > threshold:
        return {"line": best[0], "text": best[1]}
    return None


def align_whitespace(content: str, old: str, new: str) -> tuple[str, str] | None:
    """Whitespace-tolerant fallback matching (P0-1).
    当精确匹配失败时，尝试对齐 old/new 的行首空白与 content 中匹配的位置。
    返回 (aligned_old, aligned_new) 或 None。
    对标 Aider 的 replace_part_with_missing_leading_whitespace()。
    """
    old_lines = old.split("\n")
    content_lines = content.split("\n")
    # 去掉行首空白后的 old 文本
    old_stripped = [l.lstrip() for l in old_lines]
    if not old_stripped or not old_stripped[0]:
        return None
    # 在 content 中逐行查找匹配的第一个 stripped 行
    for i, cl in enumerate(content_lines):
        if cl.lstrip() == old_stripped[0]:
            # 检查后续行是否匹配
            if i + len(old_lines) > len(content_lines):
                continue
            match = True
            for j in range(1, len(old_lines)):
                if content_lines[i + j].lstrip() != old_stripped[j]:
                    match = False
                    break
            if match:
                # 对齐 new 的行首空白到 content 中匹配位置
                aligned_old = "\n".join(content_lines[i:i + len(old_lines)])
                new_lines = new.split("\n")
                aligned_new_lines = []
                for j, nl in enumerate(new_lines):
                    content_idx = i + j if j < len(old_lines) else i + len(old_lines) - 1
                    content_indent = content_lines[content_idx][:len(content_lines[content_idx]) - len(content_lines[content_idx].lstrip())]
                    new_stripped = nl.lstrip()
                    aligned_new_lines.append(content_indent + new_stripped)
                aligned_new = "\n".join(aligned_new_lines)
                return (aligned_old, aligned_new)
    return None


class SymlinkGuard:
    """Symlink 循环检测复用组件。供 dir_tree / dir_list 共享。"""

    def __init__(self):
        self._visited: set[tuple[int, int]] = set()

    def is_seen(self, path: str) -> bool:
        try:
            st = os.stat(path)
            key = (st.st_dev, st.st_ino)
            if key in self._visited:
                return True
            self._visited.add(key)
            return False
        except OSError:
            return False
