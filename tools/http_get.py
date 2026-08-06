"""
http_get — 纯标准库 HTTP 客户端。
快速 GET/POST，10s 超时，返回 status + body + size。
用于取 raw GitHub 内容、API 调用等场景。
"""
from __future__ import annotations

from collections import OrderedDict
import threading
import time

import re
import urllib.request
import urllib.error
import json
from typing import Any

from ._http_utils import check_url, make_opener


_MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB：超过此大小截断
_MAX_RESPONSE_BODY = 5000  # format=html 返回给 LLM 的最大字符数
_MAX_CONTENT_LENGTH = 8000  # format=markdown/text 每页最大字符数
_PAGE_CACHE_SIZE = 10  # 最多缓存的页面数（LRU 淘汰）
_PAGE_CACHE_TTL = 300  # 页面缓存有效期（秒），过期重新请求
_DEFAULT_TIMEOUT = 15  # 默认超时秒数

# ── 翻页缓存：key=(url, format, extract) → 完整转换结果 ──
_page_cache: OrderedDict = OrderedDict()
_page_cache_lock = threading.Lock()


def _cache_key(url: str, format: str, extract: bool) -> tuple:
    return (url, format, extract)


def _get_cached(key: tuple) -> dict | None:
    """命中缓存且未过期时返回并移到末尾（LRU）；未命中或过期返回 None。"""
    with _page_cache_lock:
        if key in _page_cache:
            entry = _page_cache[key]
            if time.monotonic() - entry.get("_cached_at", 0.0) > _PAGE_CACHE_TTL:
                del _page_cache[key]
                return None
            _page_cache.move_to_end(key)
            return entry
    return None


def _set_cache(key: tuple, entry: dict) -> None:
    """写入缓存，超过上限踢最旧的。"""
    entry["_cached_at"] = time.monotonic()
    with _page_cache_lock:
        if key in _page_cache:
            _page_cache.move_to_end(key)
        else:
            while len(_page_cache) >= _PAGE_CACHE_SIZE:
                _page_cache.popitem(last=False)
        _page_cache[key] = entry


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
    return body, total >= max_bytes


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
    except ImportError:
        return {"title": title, "description": description}
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return {"title": title, "description": description}
    if soup.title and soup.title.string:
        title = soup.title.string.strip()[:200]
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()[:500]
    return {"title": title, "description": description}


def _convert_html(html: str, format: str, extract: bool) -> tuple[str, str]:
    """将 HTML 转换为 markdown 或 text，返回 (内容, 实际使用的转换器)。

    降级链：trafilatura → markdownify → BeautifulSoup → html截断。
    extract=True 先走 trafilatura 正文提取，False 直接从 markdownify 开始。
    转换器取值：trafilatura / markdownify / bs4。
    """

    def _markdown_convert(h):
        """markdownify 转换 + format=text 时去标记，失败返回 None。"""
        try:
            from markdownify import markdownify as md
            text = md(h, heading_style="ATX", strip=["script", "style"])
            if format == "text":
                text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
                text = re.sub(r"\*(.+?)\*", r"\1", text)
                text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
                text = re.sub(r"```[\s\S]*?```", "", text)
                text = re.sub(r"`(.+?)`", r"\1", text)
            return text.strip()
        except Exception:
            return None

    def _bs4_plain(h):
        """BeautifulSoup 纯文本兜底，BS4 不可用时返回截断原文。"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(h, "lxml")
        except Exception:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(h, "html.parser")
            except Exception:
                return h[:_MAX_CONTENT_LENGTH * 3]
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return "\n".join(lines)

    if extract:
        try:
            import trafilatura
            extracted = trafilatura.extract(
                html,
                output_format="markdown" if format == "markdown" else "text",
                include_comments=False,
                include_tables=True,
            )
            if extracted and len(extracted.strip()) > 50:
                return extracted.strip(), "trafilatura"
        except Exception:
            pass

    text = _markdown_convert(html)
    if text:
        return text, "markdownify"
    return _bs4_plain(html), "bs4"


def _paginate(entry: dict, offset: int, url: str, format: str, extract: bool) -> dict:
    """从缓存的完整内容中切出一页，附 has_more / next_call / options。"""
    content = entry["content"]
    total = len(content)
    page = content[offset:offset + _MAX_CONTENT_LENGTH]
    has_more = offset + len(page) < total

    next_call = None
    options = []
    if has_more:
        next_offset = offset + len(page)
        next_call = {
            "tool": "http_get",
            "params": {
                "url": url,
                "format": format,
                "extract": extract,
                "offset": next_offset,
            },
        }
        options = [
            f"继续阅读下一页 (offset={next_offset})",
            "换个更精确的 URL 或减小范围",
        ]

    return {
        "ok": True,
        "status": entry["status"],
        "url": url,
        "title": entry["title"],
        "description": entry["description"],
        "content": page,
        "content_length": len(page),
        "format": format,
        "extracted": extract,
        "converter": entry.get("converter", "none"),
        "offset": offset,
        "has_more": has_more,
        "next_call": next_call,
        "options": options,
        "truncated": total > _MAX_CONTENT_LENGTH,
        "truncation_reason": f"共 {total} 字符，当前展示 offset={offset}~{offset + len(page)}" if has_more else "",
        "size": entry["size"],
    }


def _add_ua(req, headers: dict | None):
    if not headers or "User-Agent" not in headers:
        req.add_header("User-Agent", "IrmiaDevKit/2.3")


def get(
    url: str,
    headers: dict | None = None,
    format: str = "markdown",
    extract: bool = False,
    timeout: int = _DEFAULT_TIMEOUT,
    offset: int = 0,
) -> dict:
    """HTTP GET 请求。

    Args:
        url: 目标 URL
        headers: 自定义请求头（可选）
        format: 输出格式 — "html" | "markdown" | "text"，默认 "markdown"
        extract: True=先提取正文再转换（去广告/导航/页脚），False=全页转换，默认 False
        timeout: 超时秒数，默认 15
        offset: 分页偏移量（字符数），0=从头读取。首次调用不传，后续通过 next_call 透传

    Returns:
        format="html" 时返回 {"ok", "status", "body", "truncated", "size", "converter"}
        format≠"html" 时返回 {"ok", "status", "url", "title", "description",
                         "content", "content_length", "format", "extracted", "converter",
                         "offset", "has_more", "next_call", "options", "truncated", "size"}
    """
    err = check_url(url)
    if err:
        return err

    # 校验 format 值
    valid_formats = ("html", "markdown", "text")
    if format not in valid_formats:
        return {"ok": False, "error": f"format 无效: {format}，可选 {valid_formats}"}

    if offset < 0:
        return {"ok": False, "error": f"offset 不能为负数: {offset}"}

    try:
        req = urllib.request.Request(url, headers=headers or {})
        _add_ua(req, headers)
        with make_opener().open(req, timeout=timeout) as resp:
            raw = _build_response(resp)
            if not raw["ok"]:
                return raw

            if format == "html":
                # 向后兼容：5000 字符截断，无分页
                was_body_truncated = len(raw["body"]) > _MAX_RESPONSE_BODY
                raw["body"] = raw["body"][:_MAX_RESPONSE_BODY]
                raw["truncated"] = raw["truncated"] or was_body_truncated
                raw["converter"] = "none"
                if raw["truncated"]:
                    raw["hint"] = "HTML 已截断且无分页；改用 format='markdown' 或 'text' 可分页读取全文"
                return raw

            # format ∈ {"markdown", "text"}
            key = _cache_key(url, format, extract)

            # offset > 0：尝试从缓存翻页
            if offset > 0:
                cached = _get_cached(key)
                if cached is not None and offset < len(cached["content"]):
                    return _paginate(cached, offset, url, format, extract)
                # 缓存未命中、已过期或 offset 越界：从头下载
                offset = 0

            # 首次请求：下载 + 转换 + 缓存
            meta = _extract_metadata(raw["body"])
            content, converter = _convert_html(raw["body"], format, extract)
            entry = {
                "status": raw["status"],
                "size": raw["size"],
                "title": meta["title"],
                "description": meta["description"],
                "content": content,
                "converter": converter,
            }
            _set_cache(key, entry)
            return _paginate(entry, offset, url, format, extract)
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
