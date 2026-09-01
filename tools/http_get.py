"""
http_get — 纯标准库 HTTP 客户端。
快速 GET/POST，默认 15s 超时（可调），返回 status + body + size。
用于取 raw GitHub 内容、API 调用等场景。
"""
from __future__ import annotations

from collections import OrderedDict
import threading
import time

import http.client
import json
import math
import re
import socket
import urllib.error
import urllib.request
import zlib
from typing import Any

from ._http_utils import SsrfBlocked, check_url, make_opener


_MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB：超过此大小截断
_MAX_RESPONSE_BODY = 5000  # format=html 返回给 LLM 的最大字符数
_MAX_CONTENT_LENGTH = 8000  # format=markdown/text 每页最大字符数
_PAGE_CACHE_SIZE = 10  # 最多缓存的页面数（LRU 淘汰）
_PAGE_CACHE_TTL = 300  # 页面缓存有效期（秒），过期重新请求
_DEFAULT_TIMEOUT = 15  # 默认超时秒数
_MAX_RETRIES = 2  # GET 失败重试次数（仅 5xx / 连接错误；POST 非幂等不重试）
_RETRY_BACKOFF = 0.5  # 重试退避基数（秒），按 2^attempt 指数增长
_TOTAL_BUDGET_CAP = 180  # 重试总耗时预算上限（秒），防大 timeout × 重试放大阻塞


# ── 翻页缓存：key=(url, format, extract, headers指纹) → 完整转换结果 ──
_page_cache: OrderedDict = OrderedDict()
_page_cache_lock = threading.Lock()

# headers 无法规范化时的哨兵：跳过缓存读写（绝不退化到无头共享 key，防跨凭据泄露）
_NO_CACHE = object()


def _headers_fingerprint(headers: dict | None):
    """请求头规范化指纹（小写键排序）。None=无自定义头；_NO_CACHE=不可缓存。"""
    if not headers:
        return None
    try:
        return tuple(sorted((str(k).lower(), str(v)) for k, v in headers.items()))
    except Exception:
        return _NO_CACHE


def _cache_key(url: str, format: str, extract: bool, headers_fp=None) -> tuple:
    return (url, format, extract, headers_fp)


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


_BINARY_CT_EXACT = frozenset({
    "application/pdf",
    "application/octet-stream",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-bzip2",
    "application/x-xz",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/msword",
    "application/wasm",
})
_BINARY_CT_PREFIXES = ("image/", "audio/", "video/", "font/", "application/vnd.")


def _resp_content_type(resp) -> str:
    """取响应 Content-Type 主类型（小写、去参数），取不到返回空串。"""
    headers = getattr(resp, "headers", None)
    if headers is None:
        return ""
    ct = headers.get("Content-Type", "") or ""
    return ct.split(";")[0].strip().lower()


def _resp_final_url(resp, url: str) -> str:
    """取重定向后的落地 URL，取不到回退为原始 url。"""
    geturl = getattr(resp, "geturl", None)
    if callable(geturl):
        try:
            return geturl() or url
        except Exception:
            pass
    return url


def _is_binary_content_type(content_type: str) -> bool:
    """判断 Content-Type 是否为不可文本化的二进制内容。"""
    if not content_type:
        return False
    if content_type in _BINARY_CT_EXACT:
        return True
    return any(content_type.startswith(p) for p in _BINARY_CT_PREFIXES)


def _detect_charset(resp, raw: bytes) -> str:
    """编码嗅探：Content-Type charset → charset_normalizer/chardet（可选依赖）→ utf-8。"""
    headers = getattr(resp, "headers", None)
    if headers is not None:
        ct = headers.get("Content-Type", "") or ""
        m = re.search(r'charset=["\']?([\w.\-]+)', ct, re.IGNORECASE)
        if m:
            return m.group(1)
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best is not None:
            return best.encoding
    except Exception:
        pass
    try:
        import chardet
        result = chardet.detect(raw)
        if result and result.get("encoding"):
            return result["encoding"]
    except Exception:
        pass
    return "utf-8"


class _BodyReadError(Exception):
    """响应体读取/解压失败，消息可直接作为 error 返回给调用方。"""


def _decompress_limited(raw: bytes, content_encoding: str, max_bytes: int) -> tuple:
    """流式解压并限长（内存峰值有界，防压缩炸弹）。返回 (data, hit_limit)。

    下载截断的压缩流不抛错——返回已解压的部分内容（以 hit_limit 标记）；
    数据损坏或编码声明不实时抛 _BodyReadError。
    """
    if content_encoding in ("gzip", "x-gzip"):
        wbits_list = (16 + zlib.MAX_WBITS,)
    else:  # deflate：先按 zlib 头解析，失败回退 raw deflate
        wbits_list = (zlib.MAX_WBITS, -zlib.MAX_WBITS)
    last_err = None
    for wbits in wbits_list:
        d = zlib.decompressobj(wbits)
        try:
            out = d.decompress(raw, max_bytes + 1)
        except zlib.error as e:
            last_err = e
            continue
        hit_limit = len(out) > max_bytes or bool(d.unconsumed_tail) or not d.eof
        return out[:max_bytes], hit_limit
    raise _BodyReadError(f"{content_encoding} 解压失败（数据损坏或编码声明不实）: {last_err}")


def _read_limited(resp, max_bytes: int = _MAX_RESPONSE_SIZE) -> tuple:
    """分块读取响应体（上限 max_bytes），按嗅探到的编码解码。返回 (body, truncated)。"""
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
    # 多读 1 字节确认是否真截断（避免恰好 max_bytes 时误报）
    truncated = total >= max_bytes and bool(resp.read(1))
    raw = b"".join(chunks)

    # 解压：Accept-Encoding 协商或服务器强制压缩的结果（流式限长，防压缩炸弹）
    headers = getattr(resp, "headers", None)
    content_encoding = ""
    if headers is not None:
        content_encoding = (headers.get("Content-Encoding", "") or "").strip().lower()
    if content_encoding in ("gzip", "x-gzip", "deflate"):
        raw, hit_limit = _decompress_limited(raw, content_encoding, max_bytes)
        truncated = truncated or hit_limit
    elif content_encoding and content_encoding != "identity":
        raise _BodyReadError(
            f"服务器返回了不支持的压缩编码 ({content_encoding})，本工具仅支持 gzip/deflate"
        )

    charset = _detect_charset(resp, raw[:65536])  # 嗅探前 64KB 足够
    try:
        body = raw.decode(charset, errors="replace")
    except (LookupError, ValueError):
        body = raw.decode("utf-8", errors="replace")
    return body, truncated


def _build_response(resp, url: str = "") -> dict:
    body, was_truncated = _read_limited(resp)
    return {
        "ok": True,
        "status": resp.status,
        "size": len(body),
        "body": body,
        "truncated": was_truncated,
        "final_url": _resp_final_url(resp, url),
        "content_type": _resp_content_type(resp),
    }


def _open_with_retry(req, timeout: int, max_retries: int = _MAX_RETRIES):
    """带指数退避的请求执行。

    - 重试对象：5xx、连接层错误（URLError 及 RemoteDisconnected/ConnectionReset 等 OSError/HTTPException）
    - 不重试：4xx（客户端错误）、SSRF 拦截（安全决策，按异常类型识别）
    - 总耗时预算 min(timeout×尝试数, max(timeout, _TOTAL_BUDGET_CAP))，防大 timeout × 重试放大
    - 抛出时给异常挂上 _retries 属性（已重试次数），供错误消息透传
    """
    budget = min(timeout * (max_retries + 1), max(timeout, _TOTAL_BUDGET_CAP))
    start = time.monotonic()
    for attempt in range(max_retries + 1):
        remaining = budget - (time.monotonic() - start)
        if remaining <= 0:
            err = urllib.error.URLError(TimeoutError("重试总耗时预算耗尽"))
            err._retries = attempt
            raise err
        try:
            return make_opener().open(req, timeout=min(timeout, max(1, math.ceil(remaining))))
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt >= max_retries:
                e._retries = attempt
                raise
            try:
                e.close()  # 释放失败响应占用的套接字资源
            except Exception:
                pass
        except SsrfBlocked:
            raise  # SSRF 安全拦截：绝不重试
        except urllib.error.URLError as e:
            if attempt >= max_retries:
                e._retries = attempt
                raise
        except (http.client.HTTPException, OSError) as e:
            # RemoteDisconnected/ConnectionResetError 等非 URLError 的瞬时连接错误
            if attempt >= max_retries:
                e._retries = attempt
                raise
        time.sleep(_RETRY_BACKOFF * (2 ** attempt))


_STATUS_HINTS = {
    400: "请求格式有误——检查 URL 是否完整",
    401: "需要认证——如需登录态，请在 headers 中携带 Authorization/Cookie",
    403: "访问被拒——可能是反爬/WAF 拦截（本工具无浏览器指纹），可换地址、稍后重试，或寻找官方 API",
    404: "页面不存在——检查 URL 拼写，链接可能已失效",
    405: "方法不允许——该地址可能只接受 POST（http_post）等方法",
    429: "触发限流——自动重试对限流无效（未执行），请等待一段时间后再手动重试",
}


def _http_error_dict(e, retried: int = 0) -> dict:
    """HTTP 错误结构化：状态码 + 可操作 hint + 重试次数。"""
    body = ""
    try:
        body = e.read(4096).decode("utf-8", errors="replace")[:500]
    except Exception:
        pass
    error = f"HTTP {e.code}: {e.reason}"
    if retried:
        error += f"（已自动重试 {retried} 次）"
    if e.code >= 500:
        hint = "服务端错误——自动重试后仍失败，可稍后再试"
    else:
        hint = _STATUS_HINTS.get(e.code, "")
    result = {"ok": False, "error": error, "status": e.code, "body": body}
    if retried:
        result["retries"] = retried
    if hint:
        result["hint"] = hint
    return result


def _url_error_dict(e, timeout: int, retried: int = 0) -> dict:
    """连接层错误结构化：区分 DNS/超时/拒连，附可操作 hint。"""
    if isinstance(e, SsrfBlocked):
        # SSRF 安全拦截：原样透出，不伪装成网络故障
        return {"ok": False, "error": str(getattr(e, "reason", e))}
    reason = getattr(e, "reason", e)
    reason_s = str(reason)
    error = f"连接失败: {reason_s}"
    if retried:
        error += f"（已自动重试 {retried} 次）"
    hint = ""
    if isinstance(reason, socket.gaierror) or "Name or service not known" in reason_s or "Temporary failure in name resolution" in reason_s:
        hint = "域名解析失败——检查 URL 拼写，或本机 DNS/网络是否正常"
    elif isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in reason_s.lower():
        hint = f"连接超时（当前 timeout={timeout}s）——可调大 timeout 后重试"
    elif "refused" in reason_s.lower():
        hint = "连接被拒——目标服务可能未启动或端口不通"
    result = {"ok": False, "error": error}
    if retried:
        result["retries"] = retried
    if hint:
        result["hint"] = hint
    return result


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


def _strip_tag_blocks(html: str, tag: str) -> str:
    """线性时间剔除 <tag>...</tag> 块（含内容）。

    替代正则剔除：正则 <tag[\\s\\S]*?</tag> 在大量无闭合标签时退化为 O(n·m)（DoS 面）。
    未闭合的开标签只去掉标签本身并保留后续内容，避免误删正文。
    """
    lower = html.lower()
    open_pat = "<" + tag
    close_pat = "</" + tag
    out = []
    i = 0
    n = len(html)
    while i < n:
        j = lower.find(open_pat, i)
        if j == -1:
            out.append(html[i:])
            break
        after = j + len(open_pat)
        # 确认是标签起始（<scriptx 之类的误命中跳过）
        if after < n and lower[after] not in " \t\r\n>/":
            out.append(html[i:after])
            i = after
            continue
        gt = lower.find(">", after)
        if gt == -1:
            out.append(html[i:j])  # 开标签未闭合：丢弃标签残余，收尾
            break
        k = lower.find(close_pat, gt)
        if k == -1:
            # 全文已无闭合标签：只丢开标签，保留其余内容（防误删正文），线性收尾
            out.append(html[i:j])
            out.append(html[gt + 1:])
            break
        gt2 = lower.find(">", k + len(close_pat))
        out.append(html[i:j])
        i = (gt2 + 1) if gt2 != -1 else n
    return "".join(out)


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
            # 先剔除 script/style 整块（含内容）——markdownify 的 strip 只去标签不去文本
            h = _strip_tag_blocks(h, "script")
            h = _strip_tag_blocks(h, "style")
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


def _paginate(entry: dict, offset: int, url: str, format: str, extract: bool,
              headers: dict | None = None) -> dict:
    """从缓存的完整内容中切出一页，附 has_more / next_call / options。"""
    content = entry["content"]
    total = len(content)
    page = content[offset:offset + _MAX_CONTENT_LENGTH]
    has_more = offset + len(page) < total

    next_call = None
    options = []
    if has_more:
        next_offset = offset + len(page)
        params = {
            "url": url,
            "format": format,
            "extract": extract,
            "offset": next_offset,
        }
        if headers:
            params["headers"] = headers  # 翻页透传，保证缓存 key 的 headers 指纹一致
        next_call = {"tool": "http_get", "params": params}
        options = [
            f"继续阅读下一页 (offset={next_offset})",
            "换个更精确的 URL 或减小范围",
        ]

    result = {
        "ok": True,
        "status": entry["status"],
        "url": url,
        "final_url": entry.get("final_url", url),
        "content_type": entry.get("content_type", ""),
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
    if entry.get("hint"):
        result["hint"] = entry["hint"]
    return result


def _add_ua(req, headers: dict | None):
    lowered = {str(k).lower() for k in headers} if headers else set()
    if "user-agent" not in lowered:
        req.add_header("User-Agent", "IrmiaDevKit/2.3")
    if "accept-encoding" not in lowered:
        # 只广告内置可解压的编码；服务器强制压缩时也能正确处理
        req.add_header("Accept-Encoding", "gzip, deflate, identity")


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
        format="html" 时返回 {"ok", "status", "body", "truncated", "size", "converter",
                         "final_url", "content_type"}
        format≠"html" 时返回 {"ok", "status", "url", "final_url", "content_type",
                         "title", "description", "content", "content_length", "format",
                         "extracted", "converter", "offset", "has_more", "next_call",
                         "options", "truncated", "size"}
        目标为 PDF/图片等二进制内容时返回 {"ok": False, "error", "status",
                         "content_type", "final_url", "hint"}，提示改用 http_download
        5xx/连接错误自动指数退避重试（最多 _MAX_RETRIES 次）
    """
    err = check_url(url)
    if err:
        return err

    # 校验 format 值
    valid_formats = ("html", "markdown", "text")
    if format not in valid_formats:
        return {"ok": False, "error": f"format 无效: {format}，可选 {valid_formats}"}

    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"offset 必须为整数: {offset!r}"}
    if offset < 0:
        return {"ok": False, "error": f"offset 不能为负数: {offset}"}

    try:
        timeout = max(1, min(int(timeout), 600))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    # markdown/text 翻页：先查翻页缓存，命中直接切片返回——不重复下载，
    # 对端故障/限流时缓存内容依然可用。缓存 key 含 headers 指纹，防跨凭据串号/泄露
    headers_fp = _headers_fingerprint(headers)
    cacheable = headers_fp is not _NO_CACHE
    key = None
    if format in ("markdown", "text") and cacheable:
        key = _cache_key(url, format, extract, headers_fp)
        if offset > 0:
            cached = _get_cached(key)
            if cached is not None and offset < len(cached["content"]):
                return _paginate(cached, offset, url, format, extract, headers)
            # 缓存未命中、已过期或 offset 越界：回退为首次请求
            offset = 0

    try:
        req = urllib.request.Request(url, headers=headers or {})
        _add_ua(req, headers)
        with _open_with_retry(req, timeout) as resp:
            content_type = _resp_content_type(resp)
            if _is_binary_content_type(content_type):
                return {
                    "ok": False,
                    "error": f"目标是二进制内容 ({content_type})，无法作为文本读取",
                    "status": resp.status,
                    "content_type": content_type,
                    "final_url": _resp_final_url(resp, url),
                    "hint": "如需保存该文件，请改用 http_download 工具",
                }

            raw = _build_response(resp, url)
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

            # format ∈ {"markdown", "text"}：首次请求 = 下载 + 转换 + 缓存
            meta = _extract_metadata(raw["body"])
            content, converter = _convert_html(raw["body"], format, extract)
            # SPA 检测：原始 HTML 很大且含脚本，但转换后几乎无文本 → 疑似 JS 渲染
            hint = ""
            if (
                len(content) < 50
                and len(raw["body"]) > 2000
                and re.search(r"<script[\s>]", raw["body"], re.IGNORECASE)
            ):
                hint = (
                    "页面几乎无文本内容但包含脚本，疑似 JS 动态渲染（SPA）——"
                    "本工具不执行 JS；建议寻找该站的 API/RSS/打印版，或确认 URL 是否正确"
                )
            entry = {
                "status": raw["status"],
                "size": raw["size"],
                "final_url": raw["final_url"],
                "content_type": raw["content_type"],
                "title": meta["title"],
                "description": meta["description"],
                "content": content,
                "converter": converter,
                "hint": hint,
            }
            if cacheable:
                _set_cache(key, entry)
            return _paginate(entry, offset, url, format, extract, headers)
    except urllib.error.HTTPError as e:
        return _http_error_dict(e, getattr(e, "_retries", 0))
    except urllib.error.URLError as e:
        return _url_error_dict(e, timeout, getattr(e, "_retries", 0))
    except _BodyReadError as e:
        return {"ok": False, "error": str(e), "hint": "可改用 http_download 下载原始内容"}
    except (http.client.HTTPException, OSError) as e:
        result = {"ok": False, "error": f"连接中断: {e}"}
        retried = getattr(e, "_retries", 0)
        if retried:
            result["retries"] = retried
            result["error"] += f"（已自动重试 {retried} 次）"
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


def post(
    url: str, data: Any = None, headers: dict | None = None, timeout: int = 10
) -> dict:
    """HTTP POST 请求。data 可以是 dict（自动 JSON）或 str。

    注意：POST 非幂等，不做自动重试，避免重复提交。
    """
    err = check_url(url)
    if err:
        return err

    if data is None:
        return {"ok": False, "error": "POST 请求必须提供 data 参数"}

    try:
        timeout = max(1, min(int(timeout), 600))
    except (TypeError, ValueError):
        timeout = 10

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
            content_type = _resp_content_type(resp)
            if _is_binary_content_type(content_type):
                return {
                    "ok": False,
                    "error": f"目标是二进制内容 ({content_type})，无法作为文本读取",
                    "status": resp.status,
                    "content_type": content_type,
                    "final_url": _resp_final_url(resp, url),
                    "hint": "如需保存该文件，请改用 http_download 工具",
                }
            return _build_response(resp, url)
    except urllib.error.HTTPError as e:
        return _http_error_dict(e)
    except urllib.error.URLError as e:
        return _url_error_dict(e, timeout)
    except _BodyReadError as e:
        return {"ok": False, "error": str(e), "hint": "可改用 http_download 下载原始内容"}
    except (http.client.HTTPException, OSError) as e:
        return {"ok": False, "error": f"连接中断: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
