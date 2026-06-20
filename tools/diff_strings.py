"""
diff_strings — 字符串差异比较。
纯 difflib 标准库，不需写文件。
"""

import difflib


def diff(a: str, b: str, context_lines: int = 3, max_lines: int = 100) -> dict:
    """
    比较两个字符串，返回 unified diff。

    Args:
        a, b: 要比较的两个字符串
        context_lines: 差异周围的上下文行数
        max_lines: 最大输出 diff 行数（超过截断）
    """
    if not isinstance(a, str) or not isinstance(b, str):
        return {"ok": False, "error": "输入必须是字符串"}
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile="a",
            tofile="b",
            n=context_lines,
        )
    )

    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(
        1 for l in diff_lines if l.startswith("-") and not l.startswith("---")
    )
    diff_total = len(diff_lines)

    full_diff = "".join(diff_lines)
    truncated = False
    if diff_total > max_lines:
        diff_lines = diff_lines[:max_lines]
        full_diff = (
            "".join(diff_lines)
            + f"\n... (截断，共 {diff_total} 行差异，显示前 {max_lines} 行)"
        )
        truncated = True

    return {
        "ok": True,
        "added": added,
        "removed": removed,
        "total_changes": added + removed,
        "identical": added + removed == 0,
        "diff_lines_shown": len(diff_lines),
        "diff_lines_total": diff_total,
        "truncated": truncated,
        "diff": full_diff,
    }
