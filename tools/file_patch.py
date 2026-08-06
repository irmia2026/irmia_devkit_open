"""
file_patch — 精确文本替换工具。
用于修改代码、修bug、调整逻辑。不要用 file_write 改已有代码——用 file_patch。
支持单次替换和全局替换。
"""

import difflib
from pathlib import Path

from ._file_utils import read_file, read_file_with_encoding, find_closest_line, align_whitespace, atomic_write_text
from ._file_utils import check_path_allowed


def _normalize_line_endings(s: str) -> str:
    """统一把 \\r\\n 转成 \\n，方便跨换行风格匹配。"""
    return s.replace("\r\n", "\n")


def _restore_line_endings(s: str, has_crlf: bool) -> str:
    """如果原文件是 CRLF，把结果再转回 CRLF。"""
    return s.replace("\n", "\r\n") if has_crlf else s


def _positions(content: str, old: str) -> list[int]:
    """收集 old 在 content 中所有非重叠匹配的起始索引。"""
    positions = []
    pos = 0
    while True:
        idx = content.find(old, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + len(old)
    return positions


def _match_previews(content: str, old: str, limit: int = 20) -> list[dict]:
    """返回所有匹配位置的 {line, col, preview} 证据（上限 limit 条）。"""
    previews = []
    for idx in _positions(content, old)[:limit]:
        line = content[:idx].count("\n") + 1
        line_start = content.rfind("\n", 0, idx) + 1
        line_end = content.find("\n", idx)
        if line_end == -1:
            line_end = len(content)
        previews.append({"line": line, "col": idx - line_start + 1, "preview": content[line_start:line_end].strip()[:80]})
    return previews


def _occurrence_out_of_range(occurrence: int, count: int, content: str, old: str) -> dict:
    """occurrence 超出匹配总数时的结构化错误（附所有匹配位置）。"""
    return {
        "ok": False,
        "error": f"occurrence={occurrence} 超过匹配总数 {count}",
        "occurrence_count": count,
        "matches": _match_previews(content, old),
        "options": [f"occurrence={i+1}" for i in range(min(count, 5))],
    }


def patch(
    filepath: str,
    old: str,
    new: str,
    replace_all: bool = False,
    preserve_inner_indent: bool = True,
    occurrence: int = 0,
) -> dict:
    """
    精确替换文件中的文本。

    Args:
        filepath: 文件路径
        old: 要被替换的旧文本（精确匹配）
        new: 替换后的新文本
        replace_all: 是否替换所有匹配项（默认只替换第一个）
        preserve_inner_indent: 缩进对齐时保留嵌套结构的内部缩进（默认 True）
        occurrence: 替换第 N 次出现（0=未指定，默认替换第一处；多匹配时第 2 次起请传 occurrence=N）

    Returns:
        {"ok": true, "replaced": 1, "file": "..."} 或 {"ok": false, "error": "..."}
    """
    # C2: 拦截空 old 字符串
    if not old:
        return {"ok": False, "error": "old 参数不能为空字符串"}

    p = Path(filepath)
    err = check_path_allowed(p)
    if err:
        return err
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    try:
        content, encoding = read_file_with_encoding(p)
    except Exception as e:
        return {"ok": False, "error": f"无法读取文件: {e}"}

    try:
        has_crlf = "\r\n" in content
        norm_content = _normalize_line_endings(content)
        norm_old = _normalize_line_endings(old)
        norm_new = _normalize_line_endings(new)

        aligned_old = None
        if norm_old not in norm_content:
            # P0-1: whitespace-tolerant fallback before giving up
            aligned = align_whitespace(norm_content, norm_old, norm_new, preserve_inner_indent)
            if aligned:
                norm_old, norm_new = aligned
                aligned_old = aligned[0]
            else:
                # Still not found — give closest line hint
                closest = find_closest_line(norm_content, norm_old)
                hint = f" 最接近的行 #{closest['line']}: {closest['text']}" if closest else ""
                return {
                    "ok": False,
                    "error": f"旧文本在文件中未找到。{hint}",
                    "hint": "检查 old 参数是否包含完整且精确的文本片段。",
                }

        if occurrence < 0:
            return {"ok": False, "error": "occurrence 不能为负数"}
        if occurrence > 0 and replace_all:
            return {
                "ok": False,
                "error": "occurrence 与 replace_all 不能同时使用，请只选其一",
                "options": ["occurrence=N", "replace_all=True"],
            }

        count = norm_content.count(norm_old)
        if occurrence > 0:
            if occurrence > count:
                return _occurrence_out_of_range(occurrence, count, norm_content, norm_old)
            idx = _positions(norm_content, norm_old)[occurrence - 1]
            new_norm_content = norm_content[:idx] + norm_new + norm_content[idx + len(norm_old):]
            actual_replaced = 1
        else:
            new_norm_content = (
                norm_content.replace(norm_old, norm_new) if replace_all else norm_content.replace(norm_old, norm_new, 1)
            )
            actual_replaced = count if replace_all else 1
        new_content = _restore_line_endings(new_norm_content, has_crlf)

        atomic_write_text(p, new_content, encoding)

        result = {
            "ok": True,
            "replaced": actual_replaced,
            "total_occurrences": count,
            "replace_all": replace_all,
            "file": str(p.absolute()),
        }
        if aligned_old is not None:
            result["whitespace_aligned"] = True
            result["aligned_old"] = aligned_old[:80]
        if occurrence > 0:
            result["occurrence"] = occurrence
        elif not replace_all and count > 1:
            result["proposal"] = (
                f"仅替换了第1次出现(共{count}处)。设 replace_all=True 替换全部；第 2 次起请传 occurrence=N 指定目标。"
            )
            result["options"] = ["replace_all=True", "occurrence=N"]
        return result
    except (OSError, UnicodeError) as e:
        return {"ok": False, "error": f"无法写入文件: {e}"}


def preview(
    filepath: str,
    old: str,
    new: str,
    replace_all: bool = False,
    preserve_inner_indent: bool = True,
    occurrence: int = 0,
) -> dict:
    """预览替换效果，不实际修改文件。返回 diff。occurrence=N 时预览第 N 次出现的替换。"""
    if not old:
        return {"ok": False, "error": "old 参数不能为空字符串"}

    p = Path(filepath)
    err = check_path_allowed(p)
    if err:
        return err
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    try:
        content = read_file(p)
    except Exception as e:
        return {"ok": False, "error": f"无法读取文件: {e}"}

    has_crlf = "\r\n" in content
    norm_content = _normalize_line_endings(content)
    norm_old = _normalize_line_endings(old)
    norm_new = _normalize_line_endings(new)

    if norm_old not in norm_content:
        aligned = align_whitespace(norm_content, norm_old, norm_new, preserve_inner_indent)
        if aligned:
            norm_old, norm_new = aligned
        else:
            closest = find_closest_line(norm_content, norm_old)
            hint = f" 最接近的行 #{closest['line']}: {closest['text']}" if closest else ""
            return {
                "ok": False,
                "error": f"旧文本在文件中未找到。{hint}",
                "hint": "检查 old 参数是否包含完整且精确的文本片段。",
            }

    if occurrence < 0:
        return {"ok": False, "error": "occurrence 不能为负数"}
    if occurrence > 0 and replace_all:
        return {
            "ok": False,
            "error": "occurrence 与 replace_all 不能同时使用，请只选其一",
            "options": ["occurrence=N", "replace_all=True"],
        }

    if occurrence > 0:
        positions = _positions(norm_content, norm_old)
        if occurrence > len(positions):
            return _occurrence_out_of_range(occurrence, len(positions), norm_content, norm_old)
        idx = positions[occurrence - 1]
        new_norm_content = norm_content[:idx] + norm_new + norm_content[idx + len(norm_old):]
    else:
        new_norm_content = (
            norm_content.replace(norm_old, norm_new) if replace_all else norm_content.replace(norm_old, norm_new, 1)
        )
    new_content = _restore_line_endings(new_norm_content, has_crlf)

    diff = "\n".join(
        difflib.unified_diff(
            content.split("\n"),
            new_content.split("\n"),
            fromfile=filepath,
            tofile=filepath + " (preview)",
            lineterm="",
        )
    )

    return {"ok": True, "diff": diff}
