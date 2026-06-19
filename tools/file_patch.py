"""
file_patch — 精确文本替换工具。
用于修改代码、修bug、调整逻辑。不要用 file_write 改已有代码——用 file_patch。
支持单次替换和全局替换。
"""

import difflib
from pathlib import Path

from ._file_utils import read_file, read_file_with_encoding, find_closest_line, align_whitespace


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

    if old not in content:
        # P0-1: whitespace-tolerant fallback before giving up
        aligned = align_whitespace(content, old, new)
        if aligned:
            aligned_old, aligned_new = aligned
            count = content.count(aligned_old)
            new_content = content.replace(aligned_old, aligned_new) if replace_all else content.replace(aligned_old, aligned_new, 1)
            actual_replaced = 1 if not replace_all else count
            p.write_text(new_content, encoding=encoding, newline="")
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
        closest = find_closest_line(content, old)
        hint = f" 最接近的行 #{closest['line']}: {closest['text']}" if closest else ""
        return {
            "ok": False,
            "error": f"旧文本在文件中未找到。{hint}",
            "hint": "检查 old 参数是否包含完整且精确的文本片段。",
        }

    count = content.count(old)
    new_content = (
        content.replace(old, new) if replace_all else content.replace(old, new, 1)
    )
    actual_replaced = 1 if not replace_all else count

    p.write_text(new_content, encoding=encoding, newline="")

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


def preview(filepath: str, old: str, new: str, replace_all: bool = False) -> dict:
    """预览替换效果，不实际修改文件。返回 diff。"""
    p = Path(filepath)
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    try:
        content = read_file(p)
    except Exception as e:
        return {"ok": False, "error": f"无法读取文件: {e}"}

    if old not in content:
        return {"ok": False, "error": "旧文本在文件中未找到"}

    new_content = (
        content.replace(old, new) if replace_all else content.replace(old, new, 1)
    )
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
