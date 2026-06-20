"""
http_get — 纯标准库 HTTP 客户端。
快速 GET/POST，10s 超时，返回 status + body + size。
用于取 raw GitHub 内容、API 调用等场景。
"""
from __future__ import annotations

import urllib.request
import urllib.error
import json
from typing import Any

from ._http_utils import check_url, make_opener


_MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB：超过此大小截断
_MAX_RESPONSE_BODY = 5000  # 返回给 LLM 的最大字符数


def _read_limited(resp, max_bytes: int = _MAX_RESPONSE_SIZE) -> str:
    """分块读取响应体，超过 max_bytes 时截断。"""
    chunks = []
    total = 0
    while True:
        chunk = resp.read(8192)
        if not chunk:
            break
        total += len(chunk)
        chunks.append(chunk)
        if total >= max_bytes:
            break
    body = b"".join(chunks).decode("utf-8", errors="replace")
    return body, total > max_bytes


def _build_response(resp) -> dict:
    body, was_truncated = _read_limited(resp)
    return {
        "ok": True,
        "status": resp.status,
        "size": len(body),
        "body": body[:_MAX_RESPONSE_BODY],
        "truncated": was_truncated or len(body) > _MAX_RESPONSE_BODY,
    }


def _add_ua(req, headers: dict | None):
    if not headers or "User-Agent" not in headers:
        req.add_header("User-Agent", "IrmiaDevKit/2.3")


def get(url: str, headers: dict | None = None, timeout: int = 10) -> dict:
    """HTTP GET 请求。"""
    err = check_url(url)
    if err:
        return err

    try:
        req = urllib.request.Request(url, headers=headers or {})
        _add_ua(req, headers)
        with make_opener().open(req, timeout=timeout) as resp:
            return _build_response(resp)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}", "status": e.code, "body": body}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"连接失败: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def post(
    url: str, data: Any = None, headers: dict | None = None, timeout: int = 10
) -> dict:
    """HTTP POST 请求。data 可以是 dict（自动 JSON）或 str。"""
    err = check_url(url)
    if err:
        return err

    if data is None:
        return {"ok": False, "error": "POST 请求必须提供 data 参数"}

    try:
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
            hdrs = {"Content-Type": "application/json"}
            if headers:
                hdrs.update(headers)
            headers = hdrs
        elif isinstance(data, str):
            data = data.encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers or {})
        _add_ua(req, headers)
        with make_opener().open(req, timeout=timeout) as resp:
            return _build_response(resp)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}", "status": e.code, "body": body}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"连接失败: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
