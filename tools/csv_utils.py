"""
csv_utils — CSV/TSV 解析与生成。
纯 csv 标准库，自动检测分隔符，返回结构化数据。
"""

import csv
import io

from ._helpers import proposal_reply


def parse(text: str, delimiter: str = "auto", has_header: bool = True) -> dict:
    """
    解析 CSV/TSV 文本为结构化数据。

    Args:
        text: CSV 文本
        delimiter: 分隔符，'auto' 自动检测（, 或 \\t），也可手动指定
        has_header: 首行是否为表头
    """
    if delimiter == "auto":
        # 检测：第一行 tab 多则 TSV，否则 CSV
        first_line = text.split("\n")[0] if text else ""
        delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","

    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
    except Exception as e:
        return proposal_reply(
            False,
            "CSV/TSV 解析失败——检查分隔符或是否含 malformed 引号",
            error=f"CSV 解析失败: {e}",
            evidence={"delimiter": delimiter},
            options=["指定 delimiter 如 '\\t' 或 ',' 试试", "用 text_filter 预处理"],
        )

    if not rows:
        return proposal_reply(
            True,
            "CSV 解析成功但 0 行数据——可能是空输入或只有表头",
            evidence={"delimiter": delimiter},
            options=["确认输入文本非空", "检查 has_header 是否正确"],
            headers=[],
            rows=[],
            count=0,
        )

    headers = []
    data_start = 0
    if has_header and len(rows) > 0:
        headers = [h.strip() for h in rows[0]]
        data_start = 1

    data_rows = []
    _MAX_ROWS = 50000
    truncated = False
    for r in rows[data_start:]:
        if len(data_rows) >= _MAX_ROWS:
            truncated = True
            break
        row_data = {}
        for i, val in enumerate(r):
            key = headers[i] if i < len(headers) else f"col_{i}"
            row_data[key] = val.strip()
        data_rows.append(row_data)

    r = {
        "ok": True,
        "delimiter": "tab" if delimiter == "\t" else "comma",
        "headers": headers,
        "rows": data_rows[:200],
        "count": len(data_rows),
        "truncated": truncated or len(data_rows) > 200,
    }
    if len(data_rows) > 200:
        r["proposal"] = f"CSV 解析成功，{len(data_rows)} 行数据，已截断至200行"
    return r


def generate(rows: list[dict], delimiter: str = ",") -> dict:
    """
    将 dict 列表生成为 CSV 文本。

    Args:
        rows: [{"name": "a", "age": "1"}, ...]
        delimiter: 分隔符，默认逗号
    """
    if not rows:
        return proposal_reply(
            False,
            "无法生成 CSV——输入 rows 为空列表",
            error="rows 为空",
            options=["检查上游数据源", "至少提供一行数据"],
        )

    headers = list(rows[0].keys())
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=headers, delimiter=delimiter, lineterminator="\n"
    )
    writer.writeheader()
    try:
        writer.writerows(rows)
    except ValueError as e:
        return {"ok": False, "error": f"CSV 生成失败（键不一致或无数据）: {e}"}

    return {
        "ok": True,
        "result": output.getvalue(),
        "delimiter": "tab" if delimiter == "\t" else "comma",
        "headers": headers,
        "row_count": len(rows),
    }
