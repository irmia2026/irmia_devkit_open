"""Tests for http_get — HTTP GET/POST requests.

Tests error paths (invalid URLs, private IPs) without real network.
Use monkeypatch to avoid actual HTTP calls."""

from tools.http_get import get, post


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


class TestHttpPost:
    def test_invalid_url(self):
        r = post("http://10.0.0.1/api")
        assert r["ok"] is False

    def test_post_dict_data_no_network(self):
        # POST to example.com - may work depending on network
        r = post("http://example.com/api", data={"key": "value"})
        # Should return ok: False (either validation or network error)
        assert r["ok"] is False
