"""
safe_read — 增强版安全文件读取工具。

比 AstrBot 原生 file_read 更强大，但边界清晰：
- 只做"安全读取"，不做搜索（搜索交给 rg_search）
- 编码自动检测（chardet + UTF-8/GBK/Latin-1 fallback）
- 二进制文件检测 + hex preview
- 行号范围（start_line / end_line）
- Head / Tail 模式
- 大文件截断（truncate）+ has_more 提示 + next_call 导航
- 文件元信息（大小、编码、行数、修改时间）
- Skeleton 模式（代码结构提取）

依赖：
- 必需：标准库
- 可选：chardet（编码检测更准确）
- 可选：python-magic（MIME 类型检测）
"""

from __future__ import annotations

import codecs
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._file_utils import (
    detect_encoding,
    human_size,
    is_binary_file,
    check_path_allowed,
)
from ._helpers import proposal_reply


# ── 配置阈值 ──

MAX_FILE_SIZE = 10 * 1024 * 1024       # 10MB：硬拒绝读取内容
LARGE_FILE_THRESHOLD = 100 * 1024         # 100KB：自动截断提示
MAX_LINES_PER_CALL = 200                 # 每次最多返回 200 行
MAX_BYTES_PER_CALL = 128 * 1024          # 每次返回内容上限 128KB（约 25K tokens）
MAX_HEX_BYTES = 1024                     # hex preview 最多 1KB
MAX_HEX_LINES = 64                       # hex preview 最多 64 行
SKELETON_MAX_SIZE = 512 * 1024           # skeleton 模式最大处理 512KB
SKELETON_MAX_LINES = 5000                # skeleton 模式最多处理 5000 行
_SMALL_FILE_THRESHOLD = 1024 * 1024      # 小文件阈值：小于此值精确统计总行数

# 向后兼容别名
MAX_RETURN_BYTES = MAX_BYTES_PER_CALL


# ── 内容截断辅助 ──

def _truncate_content_by_bytes(lines: list[str], max_bytes: int) -> tuple[list[str], bool]:
    """按字节数截断行列表，在完整行边界截断，返回 (截断后的行, 是否被截断)。"""
    if not lines:
        return lines, False
    result = []
    total = 0
    for line in lines:
        # 每行在返回时占用 line + '\n' 的字节数
        line_bytes = len(line.encode("utf-8")) + 1
        if result and total + line_bytes > max_bytes:
            return result, True
        result.append(line)
        total += line_bytes
        if total >= max_bytes:
            return result, True
    return result, False


def _truncate_string_to_byte_limit(text: str, max_bytes: int, encoding: str) -> str:
    """在字符边界安全截断字符串，使其编码后不超过 max_bytes 字节。"""
    if not text:
        return text
    encoded = text.encode(encoding, errors="replace")
    if len(encoded) <= max_bytes:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(text[:mid].encode(encoding, errors="replace")) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _apply_byte_limit(content: str, encoding: str) -> tuple[str, bool]:
    """对拼接后的 content 应用 128KB 字节硬上限。"""
    encoded = content.encode(encoding, errors="replace")
    if len(encoded) <= MAX_BYTES_PER_CALL:
        return content, False
    return _truncate_string_to_byte_limit(content, MAX_BYTES_PER_CALL, encoding), True


def _format_content(lines: list[str], start_line: int, line_numbers: bool) -> str:
    """拼接文本内容；line_numbers=True 时带真实行号前缀（右对齐 6 位 + "│ "）。"""
    if not line_numbers:
        return '\n'.join(lines)
    return '\n'.join(
        f"{n:>6}│ {line}" for n, line in enumerate(lines, start=start_line)
    )


def _build_header(
    path: Path,
    total_lines: int,
    file_size: int,
    encoding: str,
    human_size_str: str | None = None,
) -> str:
    """合成 header 一行提示。"""
    hs = human_size_str or human_size(file_size)
    return f"[{path.name} · {total_lines} lines · {hs} · {encoding}]"


def _build_footer(
    start_line: int,
    end_line: int,
    total_lines: int,
    has_more: bool,
    byte_truncated: bool = False,
    mode: str = "range",
) -> str:
    """合成 footer；无后续内容且未字节截断时返回空字符串。"""
    if not has_more and not byte_truncated:
        return ""
    parts = []
    if total_lines > 0:
        parts.append(f"lines {start_line}-{end_line} of {total_lines}")
    else:
        parts.append(f"lines {start_line}-{end_line}")
    if byte_truncated:
        parts.append(f"truncated at {human_size(MAX_BYTES_PER_CALL)}")
    if has_more:
        if mode == "tail":
            remaining = max(0, start_line - 1)
            if remaining:
                parts.append(f"{remaining} more above")
        else:
            remaining = max(0, total_lines - end_line)
            if remaining:
                parts.append(f"{remaining} more below")
    return "[" + " —— ".join(parts) + "]"


def _build_next_call_and_options(
    path: str,
    start_line: int,
    end_line: int,
    total_lines: int,
    mode: str = "range",
) -> tuple[dict[str, Any] | None, list[str]]:
    """截断时返回 next_call 与 options。"""
    if mode == "tail":
        if start_line <= 1:
            return None, []
        next_end = start_line - 1
        next_start = max(1, next_end - MAX_LINES_PER_CALL + 1)
        next_call = {
            "tool": "safe_read",
            "params": {"path": path, "start_line": next_start, "end_line": next_end},
        }
        options = [
            f"Continue reading previous chunk (lines {next_start}-{next_end})",
            "head=50 — reread from start",
        ]
    else:
        if end_line >= total_lines:
            return None, []
        next_start = end_line + 1
        next_call = {
            "tool": "safe_read",
            "params": {"path": path, "start_line": next_start, "max_lines": MAX_LINES_PER_CALL},
        }
        options = [
            f"Continue reading from line {next_start}",
            "tail=50 — jump to file end",
            "head=50 — reread from start",
        ]
    return next_call, options


# ── Hex Preview ──

def _hex_preview(path: str | Path, max_bytes: int = MAX_HEX_BYTES, offset: int = 0) -> str:
    """生成 hex dump（类似 xxd），支持字节偏移。"""
    p = Path(path)
    file_size = p.stat().st_size
    start = min(offset, file_size)
    read_size = min(max_bytes, file_size - start)

    with p.open('rb') as f:
        f.seek(start)
        data = f.read(read_size)

    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        addr = start + i
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        hex_part = hex_part.ljust(48)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{addr:08x}: {hex_part}  {ascii_part}')
        if len(lines) >= MAX_HEX_LINES:
            break

    result = '\n'.join(lines)
    remaining = file_size - start - len(data)
    if remaining > 0:
        result += f'\n... ({remaining} more bytes)'
    return result


# ── 文件元信息 ──

def _get_metadata(path: str | Path) -> dict[str, Any]:
    """获取文件元信息。"""
    p = Path(path)
    stat = p.stat()
    return {
        'size': stat.st_size,
        'human_size': human_size(stat.st_size),
        'mtime': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        'ctime': datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        'is_file': p.is_file(),
        'is_dir': p.is_dir(),
        'is_symlink': p.is_symlink(),
        'permissions': oct(stat.st_mode)[-3:],
    }


# python-magic 可用性惰性缓存：None=未探测，True/False=探测结果
_HAS_MAGIC: bool | None = None


def _get_mime_type(path: str | Path) -> str:
    """获取文件 MIME 类型。"""
    global _HAS_MAGIC
    p = Path(path)
    mime, _ = mimetypes.guess_type(str(p))
    if mime:
        return mime

    if _HAS_MAGIC is None:
        try:
            import magic  # noqa: F401
            _HAS_MAGIC = True
        except Exception:
            _HAS_MAGIC = False
    if _HAS_MAGIC:
        try:
            import magic
            return magic.from_file(str(p), mime=True)
        except Exception:
            pass
    
    ext = p.suffix.lower()
    mime_map = {
        '.py': 'text/x-python',
        '.js': 'text/javascript',
        '.ts': 'text/typescript',
        '.go': 'text/x-go',
        '.rs': 'text/x-rust',
        '.java': 'text/x-java',
        '.c': 'text/x-c',
        '.cpp': 'text/x-c++',
        '.h': 'text/x-c',
        '.hpp': 'text/x-c++',
        '.nim': 'text/x-nim',
        '.md': 'text/markdown',
        '.json': 'application/json',
        '.yaml': 'text/yaml',
        '.yml': 'text/yaml',
        '.xml': 'text/xml',
        '.sql': 'text/x-sql',
        '.sh': 'text/x-shellscript',
        '.bash': 'text/x-shellscript',
        '.zsh': 'text/x-shellscript',
        '.vim': 'text/x-vim',
        '.el': 'text/x-emacs-lisp',
        '.lisp': 'text/x-common-lisp',
        '.scm': 'text/x-scheme',
        '.rkt': 'text/x-racket',
    }
    return mime_map.get(ext, 'application/octet-stream')


# ── 行号范围读取 ──

def _read_lines_range(
    path: str | Path,
    encoding: str,
    start_line: int = 1,
    end_line: int = 0,
    max_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, int, bool]:
    """读取指定行号范围的内容。

    返回：(lines, actual_start, actual_end, total_lines, has_more, estimated)
    estimated=True 表示 total_lines 为采样估算值（仅大文件且 max_lines 截断时）。

    小文件（<=1MB）精确统计 total_lines；大文件在 max_lines 命中后停止扫描，
    total_lines 按已读行数 + has_more 估算，避免全文件遍历。
    """
    p = Path(path)
    file_size = p.stat().st_size
    lines = []
    current_line = 0
    total_lines = 0
    hit_limit = False
    estimated = False

    start = max(1, start_line)
    end = end_line if end_line > 0 else float('inf')

    with p.open("r", encoding=encoding, errors="replace", newline="") as f:
        for line in f:
            total_lines += 1

            if current_line + 1 < start:
                current_line += 1
                continue

            if current_line + 1 > end:
                # 小文件继续精确统计总行数；大文件保持已计数值
                if file_size <= _SMALL_FILE_THRESHOLD:
                    for _ in f:
                        total_lines += 1
                break

            lines.append(line.rstrip('\n').rstrip('\r'))
            current_line += 1

            if len(lines) >= max_lines:
                hit_limit = True
                # 大文件不再扫描剩余行，直接估算；小文件继续精确统计
                if file_size > _SMALL_FILE_THRESHOLD:
                    break
                # 小文件：继续扫描统计总行数
                for _ in f:
                    total_lines += 1
                break

    # 大文件因 max_lines 截断时，total_lines 只统计了已遍历行数，
    # 用估算补全，避免 _build_next_call_and_options 误判 end>=total
    # 导致 next_call 消失（此时文件可能还有大量未读行）。
    if hit_limit and file_size > _SMALL_FILE_THRESHOLD:
        est = _estimate_line_count(p, file_size, encoding)
        if est > total_lines:
            total_lines = est
            estimated = True

    actual_start = start if start <= total_lines or (hit_limit and lines) else 0
    actual_end = actual_start + len(lines) - 1 if lines else 0
    has_more = actual_end < total_lines or hit_limit

    return lines, actual_start, actual_end, total_lines, has_more, estimated


def _read_head(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, bool]:
    """读取文件头部 n 行。

    小文件（<=1MB）精确统计 total_lines；大文件读到 n_lines+1 后即停止，
    total_lines 使用估算值，避免扫描整个大文件。

    返回：(lines, total_lines, has_more, estimated)
    estimated=True 表示 total_lines 为采样估算值（仅大文件且截断时）。
    """
    p = Path(path)
    file_size = p.stat().st_size
    lines = []
    total_lines = 0
    has_more = False
    estimated = False

    with p.open("r", encoding=encoding, errors="replace", newline="") as f:
        for line in f:
            total_lines += 1
            if len(lines) < n_lines:
                lines.append(line.rstrip("\n").rstrip("\r"))
            else:
                has_more = True
                if file_size > _SMALL_FILE_THRESHOLD:
                    break

    if has_more and file_size > _SMALL_FILE_THRESHOLD:
        total_lines = max(n_lines + 1, _estimate_line_count(p, file_size, encoding))
        estimated = True

    return lines, total_lines, has_more, estimated


def _read_tail(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, bool]:
    """读取文件尾部 n 行，使用从尾部倒读字节块的方式，避免扫描整个大文件。

    返回：(lines, total_lines, start_line, has_more)
    """
    from collections import deque

    p = Path(path)
    chunk_size = 8192
    buffer = deque(maxlen=n_lines)
    partial = b""
    total_lines = 0

    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        if size == 0:
            return [], 0, 1, False

        offset = size
        while offset > 0 and len(buffer) < n_lines:
            read_size = min(chunk_size, offset)
            offset -= read_size
            f.seek(offset)
            chunk = f.read(read_size)
            # 按换行分割，保留最后一个不完整的行到 partial
            lines = chunk.split(b"\n")
            # 第一个片段与之前累积的不完整行拼接
            lines[-1] += partial
            partial = lines.pop(0)
            # 从后向前收集完整行
            for line in reversed(lines):
                if line.endswith(b"\r"):
                    line = line[:-1]
                decoded = line.decode(encoding, errors="replace")
                buffer.appendleft(decoded)
                if len(buffer) >= n_lines:
                    break
            if len(buffer) >= n_lines:
                break

        # 处理文件开头的不完整行
        if partial and len(buffer) < n_lines:
            if partial.endswith(b"\r"):
                partial = partial[:-1]
            buffer.appendleft(partial.decode(encoding, errors="replace"))

        # 统计总行数：必须精确——start_line 由 total_lines 推导，
        # 估算值会导致 tail 显示的行号整体漂移（文件有 10MB 上限，精确统计成本低）
        total_lines = _count_lines_exact(p, encoding)

    lines = list(buffer)
    start_line = max(1, total_lines - len(lines) + 1)
    has_more = start_line > 1
    return lines, total_lines, start_line, has_more


def _estimate_line_count(path: str | Path, size: int, encoding: str = "utf-8") -> int:
    """基于文件大小和采样估算行数（用于超大文件 tail/head）。"""
    p = Path(path)
    sample_size = min(8192, size)
    if sample_size == 0:
        return 0
    with p.open("rb") as f:
        sample_bytes = f.read(sample_size)
    sample = sample_bytes.decode(encoding, errors="replace")
    lines_in_sample = len(sample.splitlines())
    if lines_in_sample == 0:
        return 1
    return max(1, int(size * lines_in_sample / sample_size))


def _count_lines_exact(path: str | Path, encoding: str) -> int:
    """精确统计文件行数。"""
    total = 0
    with Path(path).open("r", encoding=encoding, errors="replace", newline="") as f:
        for _ in f:
            total += 1
    return total


# ── Skeleton 模式 ──

def _extract_skeleton(path: str | Path, encoding: str) -> dict[str, Any]:
    """提取代码文件的骨架结构（类、函数、导入）。"""
    p = Path(path)
    ext = p.suffix.lower()
    file_size = p.stat().st_size

    if file_size > SKELETON_MAX_SIZE:
        return {
            "language": ext.lstrip(".") if ext else "unknown",
            "total_lines": None,
            "imports": [],
            "classes": [],
            "functions": [],
            "import_count": 0,
            "class_count": 0,
            "function_count": 0,
            "note": f"文件超过 skeleton 处理上限 {human_size(SKELETON_MAX_SIZE)}，建议用 rg_search 或 safe_read head/tail",
        }

    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.nim': 'nim',
    }
    language = language_map.get(ext, 'unknown')

    imports = []
    classes = []
    functions = []

    with p.open('r', encoding=encoding, errors='replace') as f:
        # 只读取前 SKELETON_MAX_LINES 行，避免大文件全量读入
        content_lines = []
        for i, line in enumerate(f):
            if i >= SKELETON_MAX_LINES:
                break
            content_lines.append(line)
        content = ''.join(content_lines)

    lines = content.split('\n')
    
    if language == 'python':
        import_pattern = re.compile(r'^(import\s+\S+|from\s+\S+\s+import\s+\S+)')
        class_pattern = re.compile(r'^class\s+(\w+)')
        func_pattern = re.compile(r'^(?:async\s+)?def\s+(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language in ('javascript', 'typescript'):
        import_pattern = re.compile(r'^(import|export)\s+')
        class_pattern = re.compile(r'^class\s+(\w+)')
        func_pattern = re.compile(r'^(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                name = match.group(1) or match.group(2)
                functions.append({'line': i + 1, 'name': name, 'content': line_stripped})
    
    elif language == 'go':
        import_pattern = re.compile(r'^import\s+')
        func_pattern = re.compile(r'^func\s+(?:\([^)]*\)\s+)?(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'rust':
        import_pattern = re.compile(r'^use\s+')
        func_pattern = re.compile(r'^(?:pub\s+)?fn\s+(\w+)')
        struct_pattern = re.compile(r'^(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := struct_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'java':
        import_pattern = re.compile(r'^import\s+')
        class_pattern = re.compile(r'^(?:public\s+|private\s+|protected\s+)?(?:class|interface|enum)\s+(\w+)')
        func_pattern = re.compile(r'^(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'nim':
        import_pattern = re.compile(r'^import\s+')
        func_pattern = re.compile(r'^(?:proc|func|macro|template|iterator|converter)\s+(\w+)')
        type_pattern = re.compile(r'^type\s+')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif type_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': 'type_block', 'content': line_stripped})
    
    else:
        func_pattern = re.compile(r'^(?:def|function|func|fn|proc|method|sub)\s+(\w+)')
        class_pattern = re.compile(r'^class\s+(\w+)')
        import_pattern = re.compile(r'^(import|include|require|using|use|from|#include)\s+')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    return {
        'language': language,
        'total_lines': len(lines),
        'imports': imports[:50],
        'classes': classes[:50],
        'functions': functions[:50],
        'import_count': len(imports),
        'class_count': len(classes),
        'function_count': len(functions),
    }


# ── 主函数 ──

def read(
    path: str,
    *,
    start_line: int = 0,
    end_line: int = 0,
    max_lines: int = MAX_LINES_PER_CALL,
    offset: int = 0,
    limit_bytes: int = 0,
    encoding: str = 'auto',
    mode: str = 'auto',
    head: int = 0,
    tail: int = 0,
    line_numbers: bool = True,
    include_metadata: bool = False,
) -> dict:
    """增强版安全文件读取工具。

    Args:
        path: 文件路径（目录请使用 dir_list / dir_tree）
        start_line: 起始行号（1-based，0 表示从头）
        end_line: 结束行号（0 表示到末尾）
        max_lines: 最大返回行数
        offset: 字节偏移（hex 模式）
        limit_bytes: 字节限制（hex 模式）
        encoding: 编码：auto / utf-8 / gbk / latin-1
        mode: 模式：auto / text / binary / hex / skeleton
        head: 读取前 N 行（优先级高于 start_line/end_line）
        tail: 读取后 N 行（优先级高于 start_line/end_line）
        line_numbers: 文本模式输出是否带行号前缀（默认 True，hex/binary/skeleton 不受影响）
        include_metadata: 是否包含文件元信息
    """
    # 0. 参数校验
    if not path or not isinstance(path, (str, os.PathLike)):
        return proposal_reply(
            False,
            "path 参数不能为空",
            error="path is required",
            evidence={"path": path},
            options=["提供有效的文件路径"],
        )
    if head < 0:
        return proposal_reply(False, "head 不能为负数", error="head must be >= 0")
    if tail < 0:
        return proposal_reply(False, "tail 不能为负数", error="tail must be >= 0")
    if max_lines <= 0:
        return proposal_reply(False, "max_lines 必须大于 0", error="max_lines must be > 0")
    if offset < 0:
        return proposal_reply(False, "offset 不能为负数", error="offset must be >= 0")
    if encoding != "auto":
        try:
            codecs.lookup(encoding)
        except LookupError:
            return proposal_reply(False, f"不支持的编码: {encoding}", error=f"unknown encoding: {encoding}")
    if mode not in {"auto", "text", "binary", "hex", "skeleton"}:
        return proposal_reply(
            False,
            f"不支持的 mode: {mode}",
            error=f"mode must be one of auto/text/binary/hex/skeleton",
            options=["mode=text", "mode=binary", "mode=hex"],
        )

    # 0. 路径安全校验（与 safe_write/file_remove 同级）
    forbidden = check_path_allowed(path)
    if forbidden:
        return proposal_reply(
            False,
            "路径受保护或包含目录穿越，读取被拦截。",
            error=forbidden.get("error", "路径不允许"),
            evidence={"path": path},
            options=["dir_list", "rg_search"],
        )

    # 1. symlink 控制：不自动跟随 symlink 跳出工作目录/进入系统目录
    #    必须在 resolve() 之前检查，因为 resolve() 会跟随 symlink。
    raw_path = Path(path).expanduser()
    try:
        if raw_path.is_symlink():
            target = os.readlink(raw_path)
            resolved_target = Path(target)
            if not resolved_target.is_absolute():
                resolved_target = (raw_path.parent / resolved_target).resolve()
            forbidden_target = check_path_allowed(resolved_target)
            if forbidden_target:
                return proposal_reply(
                    False,
                    f"Symlink 指向受保护路径，读取被拦截。",
                    error=f"Symlink 指向受保护路径: {resolved_target}",
                    evidence={"path": str(raw_path), "symlink_target": str(resolved_target)},
                    options=["dir_list", "rg_search"],
                )
    except OSError:
        pass

    p = raw_path.resolve()

    if not p.exists():
        return proposal_reply(
            False,
            f"路径不存在: {path}",
            error=f'Path not found: {path}',
            evidence={"path": str(p)},
            options=["dir_list", "safe_write"],
            next_call={"tool": "dir_list", "params": {"path": str(p.parent) if p.parent else "."}},
        )
    
    # 目录读取：不再展开条目，引导到专用工具
    if p.is_dir():
        if mode in ('binary', 'hex', 'skeleton'):
            return proposal_reply(
                False,
                f'路径是目录，无法用 {mode} 模式读取。',
                error=f'Path is a directory, cannot read as {mode}',
                evidence={"path": str(p), "mode": mode},
                options=["dir_list", "dir_tree"],
            )

        evidence = {"path": str(p), "mode": mode}
        if include_metadata:
            evidence["metadata"] = _get_metadata(p)
        return proposal_reply(
            False,
            '路径是目录。使用 dir_list 或 dir_tree 浏览目录内容。',
            error='Path is a directory',
            evidence=evidence,
            options=["dir_list", "dir_tree"],
            next_call={"tool": "dir_list", "params": {"path": str(p)}},
        )
    
    if not p.is_file():
        return proposal_reply(
            False,
            f'路径不是普通文件，无法用 {mode} 模式读取。',
            error=f'Path is not a file: {path}',
            evidence={"path": str(p)},
            options=["dir_list", "safe_write"],
        )
    
    metadata = _get_metadata(p) if include_metadata else {}
    file_size = metadata.get('size', p.stat().st_size)
    
    if file_size > MAX_FILE_SIZE:
        return proposal_reply(
            False,
            f'文件过大（{metadata.get("human_size", file_size)} > {human_size(MAX_FILE_SIZE)}），直接读取会超出限额。',
            error=f'File too large ({metadata.get("human_size", file_size)} > {human_size(MAX_FILE_SIZE)})',
            evidence={"path": str(p), "size": file_size, "human_size": metadata.get("human_size", human_size(file_size))},
            options=["skeleton", "rg_search", "head", "tail"],
            next_call={"tool": "safe_read", "params": {"path": str(p), "mode": "skeleton"}},
        )
    
    detected_encoding = encoding if encoding != 'auto' else detect_encoding(p)
    is_binary, binary_reason = is_binary_file(p)
    mime_type = _get_mime_type(p)
    
    actual_mode = mode
    if mode == 'auto':
        actual_mode = 'binary' if is_binary else 'text'
    
    if actual_mode == 'binary':
        return {
            'ok': True,
            'path': str(p),
            'mode': 'binary',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'is_binary': True,
            'binary_reason': binary_reason,
            'hex_preview': _hex_preview(p, MAX_HEX_BYTES, offset=offset),
            'metadata': metadata,
            'content': '',
            'truncated': False,
            'truncation_reason': 'Binary file - hex preview only',
        }
    
    if actual_mode == 'hex':
        max_bytes = limit_bytes if limit_bytes > 0 else MAX_HEX_BYTES
        hex_content = _hex_preview(p, max_bytes, offset=offset)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'hex',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'hex_content': hex_content,
            'metadata': metadata,
            'content': '',
            'truncated': file_size > max_bytes,
            'truncation_reason': f'Hex preview limited to {max_bytes} bytes' if file_size > max_bytes else '',
        }
    
    if actual_mode == 'skeleton':
        skeleton = _extract_skeleton(p, detected_encoding)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'skeleton',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'skeleton': skeleton,
            'metadata': metadata,
            'content': '',
            'truncated': False,
        }
    
    # 文本模式
    if head > 0:
        lines, total_lines, has_more, estimated = _read_head(p, detected_encoding, head)
        lines, byte_truncated = _truncate_content_by_bytes(lines, MAX_RETURN_BYTES)
        has_more = has_more or byte_truncated

        start_line = 1
        end_line = len(lines)
        content = _format_content(lines, start_line, line_numbers)
        content, byte_truncated_after = _apply_byte_limit(content, detected_encoding)
        byte_truncated = byte_truncated or byte_truncated_after

        has_more = has_more or byte_truncated
        next_call, options = _build_next_call_and_options(str(p), start_line, end_line, total_lines, mode="head")
        header = _build_header(p, total_lines, file_size, detected_encoding, metadata.get('human_size'))
        footer = _build_footer(start_line, end_line, total_lines, has_more, byte_truncated, mode="head")

        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'total_lines': total_lines,
            'total_lines_estimated': estimated,
            'returned_lines': len(lines),
            'start_line': start_line,
            'end_line': end_line,
            'has_more': has_more,
            'content': content,
            'header': header,
            'footer': footer,
            'metadata': metadata,
            'truncated': has_more,
            'truncation_reason': f'Showing first {len(lines)} of {total_lines} lines' if has_more else '',
            'next_call': next_call,
            'options': options,
        }
    
    if tail > 0:
        lines, total_lines, start_line, has_more = _read_tail(p, detected_encoding, tail)
        lines, byte_truncated = _truncate_content_by_bytes(lines, MAX_RETURN_BYTES)
        has_more = has_more or byte_truncated

        content = _format_content(lines, start_line, line_numbers)
        content, byte_truncated_after = _apply_byte_limit(content, detected_encoding)
        byte_truncated = byte_truncated or byte_truncated_after

        end_line = total_lines
        has_more = has_more or byte_truncated
        next_call, options = _build_next_call_and_options(str(p), start_line, end_line, total_lines, mode="tail")
        header = _build_header(p, total_lines, file_size, detected_encoding, metadata.get('human_size'))
        footer = _build_footer(start_line, end_line, total_lines, has_more, byte_truncated, mode="tail")

        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'total_lines': total_lines,
            'total_lines_estimated': False,
            'returned_lines': len(lines),
            'start_line': start_line,
            'end_line': end_line,
            'has_more': has_more,
            'content': content,
            'header': header,
            'footer': footer,
            'metadata': metadata,
            'truncated': has_more,
            'truncation_reason': f'Showing last {len(lines)} of {total_lines} lines' if has_more else '',
            'next_call': next_call,
            'options': options,
        }
    
    # 行号范围模式
    if end_line > 0 and start_line > 0 and end_line < start_line:
        return proposal_reply(
            False,
            f"end_line({end_line}) 不能小于 start_line({start_line})",
            error=f"行号范围非法: end_line({end_line}) < start_line({start_line})",
            evidence={"start_line": start_line, "end_line": end_line},
            options=["检查行号范围"],
        )

    lines, actual_start, actual_end, total_lines, has_more, estimated = _read_lines_range(
        p, detected_encoding, start_line, end_line, max_lines
    )
    lines, byte_truncated = _truncate_content_by_bytes(lines, MAX_RETURN_BYTES)
    has_more = has_more or byte_truncated

    # start_line 超过 EOF 时给出明确错误与导航
    if start_line > 0 and actual_start == 0 and total_lines > 0 and not lines:
        tail_n = min(MAX_LINES_PER_CALL, total_lines)
        return proposal_reply(
            False,
            f"start_line={start_line} 超过文件总行数 {total_lines}，无法读取。",
            error="start_line 超过文件总行数",
            evidence={"start_line": start_line, "total_lines": total_lines},
            options=[f"tail={tail_n}", "head=50"],
            next_call={"tool": "safe_read", "params": {"path": str(p), "tail": tail_n}},
        )

    content = _format_content(lines, actual_start, line_numbers)
    content, byte_truncated_after = _apply_byte_limit(content, detected_encoding)
    byte_truncated = byte_truncated or byte_truncated_after
    has_more = has_more or byte_truncated

    truncated = has_more or (file_size > LARGE_FILE_THRESHOLD) or byte_truncated
    truncation_reason = ''
    if truncated:
        if file_size > LARGE_FILE_THRESHOLD:
            hs = metadata.get('human_size', human_size(file_size))
            truncation_reason = f'File is large ({hs}). Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
        else:
            truncation_reason = f'Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
        if byte_truncated:
            truncation_reason += f' Content truncated to {human_size(MAX_BYTES_PER_CALL)}.'

    next_call, options = _build_next_call_and_options(str(p), actual_start, actual_end, total_lines, mode="range")
    header = _build_header(p, total_lines, file_size, detected_encoding, metadata.get('human_size'))
    footer = _build_footer(actual_start, actual_end, total_lines, has_more, byte_truncated, mode="range")

    return {
        'ok': True,
        'path': str(p),
        'mode': 'text',
        'encoding': detected_encoding,
        'size': file_size,
        'human_size': metadata.get('human_size', human_size(file_size)),
        'mime_type': mime_type,
        'total_lines': total_lines,
        'total_lines_estimated': estimated,
        'returned_lines': len(lines),
        'start_line': actual_start,
        'end_line': actual_end,
        'has_more': has_more,
        'content': content,
        'header': header,
        'footer': footer,
        'metadata': metadata,
        'truncated': truncated,
        'truncation_reason': truncation_reason,
        'next_call': next_call,
        'options': options,
    }
