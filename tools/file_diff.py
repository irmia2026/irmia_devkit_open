"""
file_diff — 文件差异比较。
逐行比较两个文件，返回结构化的 added/removed/changed。
纯 difflib 标准库，不依赖外部 diff 命令。
"""

import difflib
from pathlib import Path

from ._file_utils import read_file, FILE_DIFF_MAX_SIZE, check_path_allowed


def compare(file_a: str, file_b: str) -> dict:
    """比较两个文件，返回结构化差异。"""
    pa = Path(file_a)
    pb = Path(file_b)

    err = check_path_allowed(pa)
    if err:
        return err
    err = check_path_allowed(pb)
    if err:
        return err

    if not pa.exists():
        return {"ok": False, "error": f"文件不存在: {file_a}"}
    if not pb.exists():
        return {"ok": False, "error": f"文件不存在: {file_b}"}

    # C5: 大小检查
    if pa.stat().st_size > FILE_DIFF_MAX_SIZE or pb.stat().st_size > FILE_DIFF_MAX_SIZE:
        return {
            "ok": False,
            "error": f"文件过大（上限 {FILE_DIFF_MAX_SIZE // 1024 // 1024}MB），请使用外部 diff 工具",
        }

    try:
        a_text = read_file(pa)
    except Exception as e:
        return {"ok": False, "error": f"无法读取 {file_a}: {e}"}

    try:
        b_text = read_file(pb)
    except Exception as e:
        return {"ok": False, "error": f"无法读取 {file_b}: {e}"}

    lines_a = a_text.splitlines()
    lines_b = b_text.splitlines()
    total_lines = len(lines_a) + len(lines_b)

    diff = list(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=file_a,
            tofile=file_b,
            lineterm="",
        )
    )

    full_count = len(diff)
    displayed = diff[:100]
    # C5: added/removed 基于完整 diff，而非仅前100行
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))

    return {
        "ok": True,
        "file_a": file_a,
        "file_b": file_b,
        "added": added,
        "removed": removed,
        "total_changes": added + removed,
        "diff": "\n".join(displayed),
        "diff_lines_shown": len(displayed),
        "diff_lines_total": full_count,
        "truncated": full_count > 100,
        "identical": full_count == 0,
        "total_lines": total_lines,
    }
