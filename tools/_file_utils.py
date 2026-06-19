"""
_file_utils — 文件读取共享代码。
提供 UTF-8 → GBK fallback 读取，供 safe_edit / file_patch / file_diff 内部使用。
"""

import difflib
import os
from pathlib import Path


SAFE_EDIT_MAX_SIZE = 20 * 1024 * 1024
FILE_DIFF_MAX_SIZE = 50 * 1024 * 1024


def _detect_encoding(path: str | Path) -> str:
    """检测文件编码：优先 UTF-8，失败回退 GBK。"""
    p = Path(path)
    try:
        p.read_text(encoding="utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "gbk"


def read_file(path: str | Path) -> str:
    """读取文件内容。先试 UTF-8，失败回退 GBK。"""
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="gbk")


def read_file_with_encoding(path: str | Path) -> tuple[str, str]:
    """读取文件内容，同时返回检测到的编码。"""
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8"), "utf-8"
    except UnicodeDecodeError:
        return p.read_text(encoding="gbk"), "gbk"


def human_size(n: int) -> str:
    """字节数 → 人类可读大小（保留一位小数，整数则省略小数）。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            s = f"{n:.1f}{unit}"
            return s.replace(".0", "") if ".0" in s else s
        n /= 1024
    return f"{n:.1f}PB"


def find_closest_line(content: str, old: str, threshold: float = 0.3) -> dict | None:
    """在 content 中找与 old 首行最接近的匹配行，返回行号和文本。"""
    lines = content.split("\n")
    best = None
    best_ratio = 0
    first_line = old.split("\n")[0]
    for i, line in enumerate(lines):
        ratio = difflib.SequenceMatcher(None, first_line, line).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = (i + 1, line.strip()[:80])
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
