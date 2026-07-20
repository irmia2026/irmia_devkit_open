"""Tests for http_get — HTTP GET/POST requests.

Tests error paths (invalid URLs, private IPs) without real network.
Use monkeypatch to avoid actual HTTP calls.
"""

import urllib.request
from io import BytesIO
from tools.http_get import get, post


SAMPLE_HTML = (
    "<html><head><title>Test Page</title>"
    '<meta name="description" content="A test page for unit tests.">'
    "</head><body><h1>Hello World</h1><p>This is a test paragraph.</p>"
    "<nav>Skip this nav</nav><footer>Footer</footer></body></html>"
)

# 构造超过 8000 字符的长 HTML，用于测试分页
_LONG_BODY = "<p>" + ("long text. " * 3000) + "</p>"
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

    def __init__(self, body: bytes, status: int = 200):
        self._body = BytesIO(body)
        self.status = status

    def read(self, n=-1):
        return self._body.read(n)

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

    def test_format_html_default(self, monkeypatch):
        """默认 format=html 保持向后兼容。"""
        from tools import http_get as hg

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hg, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com")
        assert r["ok"] is True
        assert r["status"] == 200
        assert "body" in r
        assert "truncated" in r

    def test_format_markdown(self, monkeypatch):
        """format=markdown 应返回 Markdown 内容和元数据。"""
        from tools import _http_utils as hu

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hu, "make_opener", lambda: _fake_opener(fake_open))
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
        from tools import _http_utils as hu

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hu, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="markdown", extract=True)
        assert r["ok"] is True
        assert r["format"] == "markdown"
        assert r["extracted"] is True
        assert "content" in r

    def test_format_text(self, monkeypatch):
        """format=text + extract=true 应返回纯文本。"""
        from tools import _http_utils as hu

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hu, "make_opener", lambda: _fake_opener(fake_open))
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
        assert "offset" in r["next_call"]["args"]
        assert "format" in r["next_call"]["args"]
        assert "extract" in r["next_call"]["args"]
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
        next_offset = r1["next_call"]["args"]["offset"]

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
        r = get("http://example.com", offset=100)
        assert r["ok"] is True
        assert "body" in r
        assert "has_more" not in r


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
