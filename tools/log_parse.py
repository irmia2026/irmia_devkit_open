"""
log_parse — 日志解析器。
支持 Nginx/Apache 访问日志、syslog、JSON Lines。
"""

import re
import json


def parse(text: str, format: str = "auto", max_lines: int = 200) -> dict:
    """解析日志文本为结构化数据。

    Args:
        text: 日志文本
        format: auto / nginx / apache / syslog / jsonl
        max_lines: 最大处理行数，默认 200
    """
    if len(text) > 50000:
        text = text[:50000]
        text_truncated = True
    else:
        text_truncated = False
    lines = text.strip().split("\n")
    if format == "auto":
        format = _detect(lines[0] if lines else "")

    parsers = {
        "nginx": _parse_nginx,
        "apache": _parse_apache,
        "syslog": _parse_syslog,
        "jsonl": _parse_jsonl,
    }
    parser = parsers.get(format)
    if not parser:
        return {
            "ok": False,
            "error": f"不支持的格式: {format}，可选: {list(parsers.keys())}",
        }

    results = []
    errors = 0
    for line in lines[:max_lines]:
        if not line.strip():
            continue
        try:
            results.append(parser(line))
        except Exception:
            errors += 1

    r = {
        "ok": True,
        "format": format,
        "parsed": len(results),
        "total_lines": min(len(lines), max_lines),
        "errors": errors,
        "entries": results,
    }
    if text_truncated:
        r["truncated_input"] = True
    if errors > 0:
        r["proposal"] = (
            f"解析完成：{len(results)}条成功/{errors}条失败——格式={format}。尝试切换 format 参数。"
        )
        r["options"] = ["尝试其他 format (nginx/apache/syslog/jsonl)"]
    return r


_NGINX_RE = re.compile(
    r"^(?P<ip>\S+) - (?P<user>\S+) \[(?P<time>[^\]]+)\] "
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r'(?P<status>\d+) (?P<size>[0-9-]+) "(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'
)


def _parse_nginx(line: str) -> dict:
    m = _NGINX_RE.match(line)
    if m:
        return m.groupdict()
    raise ValueError("nginx 格式不匹配")


_APACHE_RE = re.compile(
    r"^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r"(?P<status>\d+) (?P<size>[0-9-]+)"
)


def _parse_apache(line: str) -> dict:
    m = _APACHE_RE.match(line)
    if m:
        return m.groupdict()
    raise ValueError("apache 格式不匹配")


_SYSLOG_RE = re.compile(
    r"^(?P<timestamp>\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<app>\S+?)(?:\[(?P<pid>\d+)\])?:\s+(?P<message>.*)"
)


def _parse_syslog(line: str) -> dict:
    m = _SYSLOG_RE.match(line)
    if m:
        return m.groupdict()
    raise ValueError("syslog 格式不匹配")


def _parse_jsonl(line: str) -> dict:
    parsed = json.loads(line)
    if isinstance(parsed, dict):
        return parsed
    return {"_value": parsed}


def _detect(first_line: str) -> str:
    if not first_line:
        return "syslog"
    if first_line.strip().startswith("{"):
        return "jsonl"
    if re.match(r'^\S+\s+\S+\s+\S+\s+\[', first_line):
        return "nginx"
    if re.match(r"\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}", first_line):
        return "syslog"
    return "syslog"
