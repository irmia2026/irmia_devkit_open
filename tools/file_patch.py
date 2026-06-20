"""
file_patch — 精确文本替换工具。
用于修改代码、修bug、调整逻辑。不要用 file_write 改已有代码——用 file_patch。
支持单次替换和全局替换。
"""

import difflib
from pathlib import Path

from ._file_utils import read_file, read_file_with_encoding, find_closest_line, align_whitespace, atomic_write_text


def _normalize_line_endings(s: str) -> str:
    """统一把 \\r\\n 转成 \\n，方便跨换行风格匹配。"""
    return s.replace("\r\n", "\n")


def _restore_line_endings(s: str, has_crlf: bool) -> str:
    """如果原文件是 CRLF，把结果再转回 CRLF。"""
    return s.replace("\n", "\r\n") if has_crlf else s


def patch(filepath: str, old: str, new: str, replace_all: bool = False) -> dict:
    """
    精确替换文件中的文本。

    Args:
        filepath: 文件路径
        old: 要被替换的旧文本（精确匹配）
        new: 替换后的新文本
        replace_all: 是否替换所有匹配项（默认只替换第一个）

    Returns:
        {"ok": true, "replaced": 1, "file": "..."} 或 {"ok": false, "error": "..."}
    """
    # C2: 拦截空 old 字符串
    if not old:
        return {"ok": False, "error": "old 参数不能为空字符串"}

    p = Path(filepath)
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

        if norm_old not in norm_content:
            # P0-1: whitespace-tolerant fallback before giving up
            aligned = align_whitespace(norm_content, norm_old, norm_new)
            if aligned:
                aligned_old, aligned_new = aligned
                count = norm_content.count(aligned_old)
                new_norm_content = (
                    norm_content.replace(aligned_old, aligned_new)
                    if replace_all
                    else norm_content.replace(aligned_old, aligned_new, 1)
                )
                actual_replaced = count if replace_all else 1
                new_content = _restore_line_endings(new_norm_content, has_crlf)
                atomic_write_text(p, new_content, encoding)
                return {
                    "ok": True,
                    "replaced": actual_replaced,
                    "total_occurrences": count,
                    "replace_all": replace_all,
                    "file": str(p.absolute()),
                    "whitespace_aligned": True,
                    "aligned_old": aligned_old[:80],
                }
            # Still not found — give closest line hint
            closest = find_closest_line(norm_content, norm_old)
            hint = f" 最接近的行 #{closest['line']}: {closest['text']}" if closest else ""
            return {
                "ok": False,
                "error": f"旧文本在文件中未找到。{hint}",
                "hint": "检查 old 参数是否包含完整且精确的文本片段。",
            }

        count = norm_content.count(norm_old)
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
        if not replace_all and count > 1:
            result["proposal"] = (
                f"仅替换了第1次出现(共{count}处)。设 replace_all=True 替换全部。"
            )
            result["options"] = ["replace_all=True", "逐个替换"]
        return result
    except (OSError, UnicodeError) as e:
        return {"ok": False, "error": f"无法写入文件: {e}"}


def preview(filepath: str, old: str, new: str, replace_all: bool = False) -> dict:
    """预览替换效果，不实际修改文件。返回 diff。"""
    if not old:
        return {"ok": False, "error": "old 参数不能为空字符串"}

    p = Path(filepath)
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
        aligned = align_whitespace(norm_content, norm_old, norm_new)
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
