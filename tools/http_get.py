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
_MAX_RESPONSE_BODY = 5000  # format=html 返回给 LLM 的最大字符数
_MAX_CONTENT_LENGTH = 20000  # format=markdown/text 返回给 LLM 的最大字符数
_DEFAULT_TIMEOUT = 15  # 默认超时秒数


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
        "body": body,
        "truncated": was_truncated,
    }


def _extract_metadata(html: str) -> dict:
    """从 HTML 中提取 title 和 meta description。"""
    title = ""
    description = ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()[:200]
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()[:500]
    except Exception:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                title = soup.title.string.strip()[:200]
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"].strip()[:500]
        except Exception:
            pass
    return {"title": title, "description": description}


def _convert_html(html: str, format: str, extract: bool) -> str:
    """将 HTML 转换为 markdown 或 text。
    
    如果 extract=True：用 trafilatura 先提取正文再转换。
    如果 extract=False：用 markdownify 全页转换。
    安装失败时自动降级。
    """
    if extract:
        # 尝试 trafilatura 正文提取
        try:
            import trafilatura
            extracted = trafilatura.extract(
                html,
                output_format="markdown" if format == "markdown" else "text",
                include_comments=False,
                include_tables=True,
            )
            if extracted and len(extracted.strip()) > 50:
                return extracted.strip()
        except Exception:
            pass

        # trafilatura 不可用或提取失败 → 降级到 markdownify
        try:
            from markdownify import markdownify as md
            text = md(html, heading_style="ATX", strip=["script", "style"])
            if format == "text":
                # 简单去 Markdown 标记
                import re
                text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
                text = re.sub(r"\*(.+?)\*", r"\1", text)
                text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
                text = re.sub(r"```[\s\S]*?```", "", text)
                text = re.sub(r"`(.+?)`", r"\1", text)
            return text.strip()
        except Exception:
            pass

        # 最终降级：纯文本提取
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                return html[:2000]
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)[:20000]
    else:
        # extract=False：全页 markdownify 转换
        try:
            from markdownify import markdownify as md
            text = md(html, heading_style="ATX", strip=["script", "style"])
            if format == "text":
                import re
                text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
                text = re.sub(r"\*(.+?)\*", r"\1", text)
                text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
                text = re.sub(r"```[\s\S]*?```", "", text)
                text = re.sub(r"`(.+?)`", r"\1", text)
            return text.strip()
        except Exception:
            pass

        # 降级：纯文本提取
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
            except Exception:
                return html[:2000]
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)[:20000]


def _add_ua(req, headers: dict | None):
    if not headers or "User-Agent" not in headers:
        req.add_header("User-Agent", "IrmiaDevKit/2.3")


def get(
    url: str,
    headers: dict | None = None,
    format: str = "html",
    extract: bool = False,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict:
    """HTTP GET 请求。

    Args:
        url: 目标 URL
        headers: 自定义请求头（可选）
        format: 输出格式 — "html" | "markdown" | "text"，默认 "html"
        extract: True=先提取正文再转换（去广告/导航/页脚），False=全页转换，默认 False
        timeout: 超时秒数，默认 15

    Returns:
        format="html" 时返回 {"ok", "status", "body", "truncated", "size"}
        format≠"html" 时返回 {"ok", "status", "url", "title", "description",
                         "content", "content_length", "format", "extracted", "truncated", "size"}
    """
    err = check_url(url)
    if err:
        return err

    # 校验 format 值
    valid_formats = ("html", "markdown", "text")
    if format not in valid_formats:
        return {"ok": False, "error": f"format 无效: {format}，可选 {valid_formats}"}

    try:
        req = urllib.request.Request(url, headers=headers or {})
        _add_ua(req, headers)
        with make_opener().open(req, timeout=timeout) as resp:
            raw = _build_response(resp)
            if not raw["ok"]:
                return raw

            if format == "html":
                # 向后兼容：默认行为不变，5000 字符截断
                was_body_truncated = len(raw["body"]) > _MAX_RESPONSE_BODY
                raw["body"] = raw["body"][:_MAX_RESPONSE_BODY]
                raw["truncated"] = raw["truncated"] or was_body_truncated
                return raw

            # format ∈ {"markdown", "text"}
            meta = _extract_metadata(raw["body"])
            content = _convert_html(raw["body"], format, extract)
            content_length = len(content)

            return {
                "ok": True,
                "status": raw["status"],
                "url": url,
                "title": meta["title"],
                "description": meta["description"],
                "content": content[:_MAX_CONTENT_LENGTH],
                "content_length": min(content_length, _MAX_CONTENT_LENGTH),
                "format": format,
                "extracted": extract,
                "truncated": raw["truncated"] or content_length > _MAX_CONTENT_LENGTH,
                "size": raw["size"],
            }
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
