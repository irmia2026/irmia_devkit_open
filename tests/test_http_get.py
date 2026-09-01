"""Tests for http_get — HTTP GET/POST requests.

Tests error paths (invalid URLs, private IPs) without real network.
Use monkeypatch to avoid actual HTTP calls.
"""

import socket
import urllib.error
import urllib.request
from io import BytesIO

import pytest

from tools.http_get import get, post


SAMPLE_HTML = (
    "<html><head><title>Test Page</title>"
    '<meta name="description" content="A test page for unit tests.">'
    "</head><body><h1>Hello World</h1><p>This is a test paragraph.</p>"
    "<nav>Skip this nav</nav><footer>Footer</footer></body></html>"
)

# 构造超过 8000 字符的长 HTML，用于测试分页
_LONG_BODY = "<p>" + ("long text. " * 5000) + "</p>"
SAMPLE_HTML_LONG = (
    "<html><head><title>Long Page</title>"
    '<meta name="description" content="A very long page for pagination tests.">'
    f"</head><body><h1>Start</h1>{_LONG_BODY}<h2>End</h2></body></html>"
)


def _clear_cache():
    """清除 http_get 模块级缓存，避免测试间互相干扰。"""
    from tools.http_get import _page_cache
    _page_cache.clear()


class FakeResponse:
    """模拟 urllib response 对象。"""

    def __init__(self, body: bytes, status: int = 200,
                 headers: dict | None = None, url: str = ""):
        self._body = BytesIO(body)
        self.status = status
        self.headers = headers if headers is not None else {}
        self._url = url

    def read(self, n=-1):
        return self._body.read(n)

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _fake_opener(fake_open_fn):
    """创建一个假的 opener，其 open 方法是 fake_open_fn。"""
    return type("FakeOpener", (), {"open": fake_open_fn})()


class TestHttpGet:
    def test_invalid_url_scheme(self):
        r = get("ftp://example.com")
        assert r["ok"] is False
        assert "error" in r

    def test_missing_hostname(self):
        r = get("http://")
        assert r["ok"] is False

    def test_private_ip_blocked(self):
        r = get("http://127.0.0.1/test")
        assert r["ok"] is False

    def test_private_ip_10_dot(self):
        r = get("http://10.0.0.1/test")
        assert r["ok"] is False

    def test_private_ip_192_168(self):
        r = get("http://192.168.1.1/test")
        assert r["ok"] is False

    def test_invalid_url_format(self):
        r = get("not a url")
        assert r["ok"] is False

    def test_empty_url(self):
        r = get("")
        assert r["ok"] is False

    def test_post_without_url(self):
        r = post("")
        assert r["ok"] is False

    def test_invalid_format(self, monkeypatch):
        """格式参数无效时应返回错误。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="pdf")
        assert r["ok"] is False
        assert "format" in r["error"]

    def test_format_default_is_markdown(self, monkeypatch):
        """默认 format=markdown，返回转换后内容和 converter 字段。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is True
        assert r["status"] == 200
        assert r["format"] == "markdown"
        assert "content" in r
        assert r["converter"] in ("trafilatura", "markdownify", "bs4")

    def test_format_html_passthrough(self, monkeypatch):
        """format=html 返回原始 body，converter 为 none。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="html")
        assert r["ok"] is True
        assert "body" in r
        assert "truncated" in r
        assert r["converter"] == "none"

    def test_format_html_truncated_hint(self, monkeypatch):
        """html 模式截断时附 hint 引导改用可分页格式。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML_LONG.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="html")
        assert r["ok"] is True
        assert r["truncated"] is True
        assert "hint" in r
        assert "markdown" in r["hint"]

    def test_format_markdown(self, monkeypatch):
        """format=markdown 应返回 Markdown 内容和元数据。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert r["format"] == "markdown"
        assert r["extracted"] is False
        assert "content" in r
        assert "title" in r
        assert "description" in r
        assert isinstance(r["content_length"], int)

    def test_format_markdown_extract(self, monkeypatch):
        """format=markdown + extract=true 应标记 extracted。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown", extract=True)
        assert r["ok"] is True
        assert r["format"] == "markdown"
        assert r["extracted"] is True
        assert "content" in r

    def test_format_text(self, monkeypatch):
        """format=text + extract=true 应返回纯文本。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="text", extract=True)
        assert r["ok"] is True
        assert r["format"] == "text"
        assert r["extracted"] is True
        assert "content" in r

    def test_format_markdown_has_more(self, monkeypatch):
        """长内容应标记 has_more=true 并包含 next_call。"""
        _clear_cache()
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML_LONG.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert r["has_more"] is True
        assert r["next_call"] is not None
        assert r["next_call"]["tool"] == "http_get"
        assert "offset" in r["next_call"]["params"]
        assert "format" in r["next_call"]["params"]
        assert "extract" in r["next_call"]["params"]
        assert r["content_length"] <= 8000

    def test_format_markdown_pagination(self, monkeypatch):
        """分页翻页：第二页内容应与第一页不同。"""
        _clear_cache()
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML_LONG.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))

        # 第一页
        r1 = get("http://example.com", format="markdown")
        assert r1["ok"] is True
        assert r1["has_more"] is True
        page1 = r1["content"]
        next_offset = r1["next_call"]["params"]["offset"]

        # 第二页
        r2 = get("http://example.com", format="markdown", offset=next_offset)
        assert r2["ok"] is True
        page2 = r2["content"]
        assert page1 != page2  # 内容不应相同
        assert page2.startswith(page1[next_offset:next_offset + 20])  # 衔接正确

    def test_format_markdown_no_has_more(self, monkeypatch):
        """短内容不应标记 has_more。"""
        _clear_cache()
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert r["has_more"] is False
        assert r["next_call"] is None

    def test_format_html_ignores_offset(self, monkeypatch):
        """format=html 不受 offset 影响，保持向后兼容。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="html", offset=100)
        assert r["ok"] is True
        assert "body" in r
        assert "has_more" not in r

    def test_page_cache_ttl_expires(self, monkeypatch):
        """缓存命中但超过 TTL 时应视为未命中，重新请求。"""
        import time as _time
        from tools import http_get as hg

        _clear_cache()
        key = hg._cache_key("http://example.com", "markdown", False)
        hg._set_cache(key, {
            "status": 200, "size": 10, "title": "", "description": "",
            "content": "stale content", "converter": "markdownify",
        })
        # 人为把缓存时间拨到 TTL 之前
        hg._page_cache[key]["_cached_at"] = _time.monotonic() - hg._PAGE_CACHE_TTL - 1
        assert hg._get_cached(key) is None
        assert key not in hg._page_cache  # 过期条目被清除

    def test_page_cache_ttl_fresh_hit(self):
        """未过期的缓存正常命中。"""
        from tools import http_get as hg

        _clear_cache()
        key = hg._cache_key("http://example.com", "markdown", False)
        hg._set_cache(key, {
            "status": 200, "size": 10, "title": "", "description": "",
            "content": "fresh content", "converter": "markdownify",
        })
        hit = hg._get_cached(key)
        assert hit is not None
        assert hit["content"] == "fresh content"


class TestHttpPost:
    def test_invalid_url(self):
        r = post("http://10.0.0.1/api")
        assert r["ok"] is False

    def test_post_dict_data_no_network(self, monkeypatch):
        # 使用 monkeypatch 避免实际网络请求，确保测试稳定
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = post("http://example.com/api", data={"key": "value"})
        # mock 返回 200 响应
        assert r["ok"] is True


# GBK 编码的中文页面，用于测试编码嗅探
GBK_HTML = (
    "<html><head><title>中文标题</title></head><body><p>"
    + "这是一段用于测试编码嗅探的中文内容。" * 10
    + "</p></body></html>"
).encode("gbk")


class TestCharsetDetection:
    def test_gbk_via_content_type_header(self, monkeypatch):
        """Content-Type 声明 charset=gbk 时应按 GBK 解码，不产生乱码。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                GBK_HTML, headers={"Content-Type": "text/html; charset=gbk"}
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "中文内容" in r["content"]
        assert "\ufffd" not in r["content"]

    def test_gbk_sniffed_without_charset_header(self, monkeypatch):
        """无 charset 声明时由 chardet/charset_normalizer 嗅探兜底。"""
        pytest.importorskip("chardet")
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(GBK_HTML, headers={"Content-Type": "text/html"})

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "中文内容" in r["content"]

    def test_invalid_charset_falls_back_to_utf8(self, monkeypatch):
        """无法识别的 charset 名不应崩溃，回退 utf-8。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                SAMPLE_HTML.encode("utf-8"),
                headers={"Content-Type": "text/html; charset=not-a-real-charset"},
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "Hello World" in r["content"]


class TestBinaryContent:
    def test_pdf_rejected_with_hint(self, monkeypatch):
        """PDF 应返回明确错误并引导改用 http_download。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                b"%PDF-1.4 fake", headers={"Content-Type": "application/pdf"}
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/doc.pdf")
        assert r["ok"] is False
        assert r["status"] == 200
        assert r["content_type"] == "application/pdf"
        assert "http_download" in r["hint"]
        assert "final_url" in r

    def test_image_rejected(self, monkeypatch):
        """图片 Content-Type 同样分流。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                b"\x89PNG\r\n", headers={"Content-Type": "image/png"}
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/pic.png")
        assert r["ok"] is False
        assert "http_download" in r["hint"]

    def test_json_not_treated_as_binary(self, monkeypatch):
        """application/json 是文本 API 响应，不应被分流。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                b'{"a": 1}',
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/api", format="text")
        assert r["ok"] is True
        assert '"a"' in r["content"]


class TestFinalUrl:
    def test_final_url_from_redirect(self, monkeypatch):
        """重定向后应返回落地 URL。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(
                SAMPLE_HTML.encode("utf-8"), url="http://example.com/landing"
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/start")
        assert r["ok"] is True
        assert r["final_url"] == "http://example.com/landing"

    def test_final_url_fallback_to_request_url(self, monkeypatch):
        """取不到落地 URL 时回退为原始请求 URL。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/page")
        assert r["ok"] is True
        assert r["final_url"] == "http://example.com/page"


class TestRetry:
    @staticmethod
    def _no_sleep(monkeypatch, hg):
        """跳过退避等待，加速测试。"""
        monkeypatch.setattr(hg, "_RETRY_BACKOFF", 0)

    def test_retry_on_5xx_then_success(self, monkeypatch):
        """首次 503 应重试并最终成功。"""
        from tools import http_get as hg
        self._no_sleep(monkeypatch, hg)
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    "http://example.com", 503, "Service Unavailable", None, None
                )
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is True
        assert calls["n"] == 2

    def test_retry_exhausted_on_persistent_5xx(self, monkeypatch):
        """持续 503 重试耗尽后返回错误，请求次数 = 1 + _MAX_RETRIES。"""
        from tools import http_get as hg
        self._no_sleep(monkeypatch, hg)
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "http://example.com", 503, "Service Unavailable", None, None
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert r["status"] == 503
        assert calls["n"] == 1 + hg._MAX_RETRIES

    def test_no_retry_on_4xx(self, monkeypatch):
        """404 属客户端错误，不应重试。"""
        from tools import http_get as hg
        self._no_sleep(monkeypatch, hg)
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "http://example.com", 404, "Not Found", None, None
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert r["status"] == 404
        assert calls["n"] == 1

    def test_retry_on_connection_error(self, monkeypatch):
        """连接超时属瞬时错误，应重试。"""
        from tools import http_get as hg
        self._no_sleep(monkeypatch, hg)
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("timed out")
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is True
        assert calls["n"] == 2

    def test_no_retry_on_ssrf_redirect_block(self, monkeypatch):
        """SSRF 重定向拦截是安全决策，绝不能重试。"""
        from tools import http_get as hg
        self._no_sleep(monkeypatch, hg)
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            raise urllib.error.URLError(
                "重定向目标被拦截: 禁止访问内网地址: 127.0.0.1"
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert calls["n"] == 1


class TestPaginationCache:
    def test_pagination_serves_from_cache_without_redownload(self, monkeypatch):
        """翻页命中缓存时不应再次发起网络请求（整个翻页周期只下载一次）。"""
        _clear_cache()
        from tools import http_get as hg
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            return FakeResponse(SAMPLE_HTML_LONG.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r1 = get("http://example.com", format="markdown")
        assert r1["has_more"] is True
        next_offset = r1["next_call"]["params"]["offset"]

        r2 = get("http://example.com", format="markdown", offset=next_offset)
        assert r2["ok"] is True
        assert r2["content"] != r1["content"]
        assert calls["n"] == 1  # 关键断言：翻页零网络请求

    def test_pagination_cache_survives_network_failure(self, monkeypatch):
        """翻页时对端宕机/网络断开，缓存命中仍应正常返回。"""
        _clear_cache()
        from tools import http_get as hg
        calls = {"n": 0}

        def fake_open(self, req, timeout=None):
            calls["n"] += 1
            if calls["n"] > 1:
                raise urllib.error.URLError("connection refused")
            return FakeResponse(SAMPLE_HTML_LONG.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        monkeypatch.setattr(hg, "_RETRY_BACKOFF", 0)
        r1 = get("http://example.com", format="markdown")
        next_offset = r1["next_call"]["params"]["offset"]

        r2 = get("http://example.com", format="markdown", offset=next_offset)
        assert r2["ok"] is True  # 网络已"断"，但缓存兜底
        assert r2["offset"] == next_offset
        assert len(r2["content"]) > 0
        assert calls["n"] == 1  # 缓存命中，未触发第二次（必失败的）请求


# 模拟 SPA 页面：大量脚本 + 几乎无文本
SPA_HTML = (
    '<html><head><title>SPA</title></head><body><div id="app"></div>'
    "<script>" + "var x = 1; " * 400 + "</script></body></html>"
)


class TestCompression:
    def test_gzip_body_decompressed(self, monkeypatch):
        """Content-Encoding: gzip 的响应应自动解压。"""
        import gzip as gz
        from tools import http_get as hg

        payload = gz.compress(SAMPLE_HTML.encode("utf-8"))

        def fake_open(self, req, timeout=None):
            return FakeResponse(payload, headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Encoding": "gzip",
            })

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="html")
        assert r["ok"] is True
        assert "<h1>Hello World</h1>" in r["body"]

    def test_deflate_body_decompressed(self, monkeypatch):
        """Content-Encoding: deflate 的响应应自动解压。"""
        import zlib
        from tools import http_get as hg

        payload = zlib.compress(SAMPLE_HTML.encode("utf-8"))

        def fake_open(self, req, timeout=None):
            return FakeResponse(payload, headers={
                "Content-Type": "text/html; charset=utf-8",
                "Content-Encoding": "deflate",
            })

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="html")
        assert r["ok"] is True
        assert "<h1>Hello World</h1>" in r["body"]

    def test_gzip_requested_via_accept_encoding(self, monkeypatch):
        """未自定义 headers 时应自动广告 Accept-Encoding: gzip。"""
        from tools import http_get as hg
        captured = {}

        def fake_open(self, req, timeout=None):
            captured["ae"] = req.headers.get("Accept-encoding")  # urllib 首字母大写
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        get("http://example.com", format="html")
        assert captured["ae"] is not None
        assert "gzip" in captured["ae"]


class TestErrorHints:
    def test_404_hint(self, monkeypatch):
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            raise urllib.error.HTTPError(
                "http://example.com", 404, "Not Found", None, None
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com/missing")
        assert r["ok"] is False
        assert r["status"] == 404
        assert "不存在" in r["hint"]
        assert "retries" not in r  # 4xx 不重试

    def test_403_hint_mentions_antibot(self, monkeypatch):
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            raise urllib.error.HTTPError(
                "http://example.com", 403, "Forbidden", None, None
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert "反爬" in r["hint"]

    def test_5xx_exhausted_reports_retries(self, monkeypatch):
        from tools import http_get as hg
        monkeypatch.setattr(hg, "_RETRY_BACKOFF", 0)

        def fake_open(self, req, timeout=None):
            raise urllib.error.HTTPError(
                "http://example.com", 503, "Service Unavailable", None, None
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert r["retries"] == hg._MAX_RETRIES
        assert "已自动重试" in r["error"]
        assert "服务端错误" in r["hint"]

    def test_timeout_hint(self, monkeypatch):
        from tools import http_get as hg
        monkeypatch.setattr(hg, "_RETRY_BACKOFF", 0)

        def fake_open(self, req, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", timeout=7)
        assert r["ok"] is False
        assert "timeout=7" in r["hint"]
        assert r["retries"] == hg._MAX_RETRIES

    def test_dns_hint(self, monkeypatch):
        from tools import http_get as hg
        monkeypatch.setattr(hg, "_RETRY_BACKOFF", 0)

        def fake_open(self, req, timeout=None):
            raise urllib.error.URLError(
                socket.gaierror(-2, "Name or service not known")
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert "域名解析失败" in r["hint"]

    def test_ssrf_redirect_message_not_disguised(self, monkeypatch):
        """SSRF 拦截不应伪装成'连接失败'。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            raise urllib.error.URLError(
                "重定向目标被拦截: 禁止访问内网地址: 127.0.0.1"
            )

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is False
        assert r["error"].startswith("重定向目标被拦截")
        assert "连接失败" not in r["error"]


class TestJsRenderedHint:
    def test_script_content_not_leaked(self, monkeypatch):
        """内联脚本源码不应泄漏进转换结果（markdownify strip 只去标签）。"""
        _clear_cache()
        from tools import http_get as hg
        html = (
            "<html><body><p>真正的正文内容在这里。</p>"
            "<script>var tracker = 'x'; " * 100 + "</script></body></html>"
        )

        def fake_open(self, req, timeout=None):
            return FakeResponse(html.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "真正的正文内容" in r["content"]
        assert "tracker" not in r["content"]

    def test_spa_page_gets_hint(self, monkeypatch):
        """大量脚本 + 几乎无文本的页面应提示疑似 JS 渲染。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SPA_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "hint" in r
        assert "JS" in r["hint"]

    def test_normal_page_no_hint(self, monkeypatch):
        """正常文本页面不应误报。"""
        _clear_cache()
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown")
        assert r["ok"] is True
        assert "hint" not in r


class TestTimeoutClamp:
    def test_timeout_clamped_to_600(self, monkeypatch):
        from tools import http_get as hg
        captured = {}

        def fake_open(self, req, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        get("http://example.com", timeout=9999)
        assert captured["timeout"] == 600

    def test_timeout_floor_is_1(self, monkeypatch):
        from tools import http_get as hg
        captured = {}

        def fake_open(self, req, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        get("http://example.com", timeout=-3)
        assert captured["timeout"] == 1

    def test_timeout_invalid_uses_default(self, monkeypatch):
        from tools import http_get as hg
        captured = {}

        def fake_open(self, req, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        get("http://example.com", timeout="abc")
        assert captured["timeout"] == 15
