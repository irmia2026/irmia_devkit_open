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
        from tools import _http_utils as hu

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hu, "make_opener", lambda: _fake_opener(fake_open))
        r = get("http://example.com", format="pdf")
        assert r["ok"] is False
        assert "format" in r["error"]

    def test_format_html_default(self, monkeypatch):
        """默认 format=html 保持向后兼容。"""
        from tools import _http_utils as hu

        def fake_open(self, req, timeout=None):
            return FakeResponse(SAMPLE_HTML.encode("utf-8"))

        monkeypatch.setattr(hu, "make_opener", lambda: _fake_opener(fake_open))
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
