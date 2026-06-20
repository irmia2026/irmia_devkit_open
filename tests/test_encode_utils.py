"""Tests for encode_utils."""

import base64
import binascii
import urllib.parse

from tools import encode_utils as eu


class TestBase64:
    def test_b64_encode(self):
        r = eu.b64_encode("hello")
        assert r["ok"] is True
        assert r["result"] == base64.b64encode(b"hello").decode("ascii")

    def test_b64_encode_uri(self):
        r = eu.b64_encode("hello", as_uri=True)
        assert r["ok"] is True
        assert r["result"] == "data:text/plain;base64," + base64.b64encode(b"hello").decode("ascii")

    def test_b64_decode(self):
        encoded = base64.b64encode(b"hello").decode("ascii")
        r = eu.b64_decode(encoded)
        assert r["ok"] is True
        assert r["result"] == "hello"

    def test_b64_decode_uri(self):
        encoded = "data:text/plain;base64," + base64.b64encode(b"hello").decode("ascii")
        r = eu.b64_decode(encoded, strip_uri=True)
        assert r["ok"] is True
        assert r["result"] == "hello"

    def test_b64_decode_invalid(self):
        r = eu.b64_decode("not-base64!!!")
        assert r["ok"] is False
        assert "error" in r


class TestUrl:
    def test_url_encode(self):
        r = eu.url_encode("hello world")
        assert r["ok"] is True
        assert r["result"] == urllib.parse.quote("hello world", safe="")

    def test_url_encode_special_chars(self):
        r = eu.url_encode("a=1&b=2")
        assert r["ok"] is True
        assert "=" not in r["result"]
        assert "&" not in r["result"]

    def test_url_decode(self):
        r = eu.url_decode("hello%20world")
        assert r["ok"] is True
        assert r["result"] == "hello world"


class TestHex:
    def test_hex_encode(self):
        r = eu.hex_encode("hello")
        assert r["ok"] is True
        assert r["result"] == "68656c6c6f"

    def test_hex_decode(self):
        r = eu.hex_decode("68656c6c6f")
        assert r["ok"] is True
        assert r["result"] == "hello"

    def test_hex_decode_invalid(self):
        r = eu.hex_decode("zz")
        assert r["ok"] is False
        assert "error" in r

    def test_hex_encode_unicode(self):
        r = eu.hex_encode("中文")
        assert r["ok"] is True
        assert r["result"] == binascii.hexlify("中文".encode("utf-8")).decode("ascii")

    def test_hex_round_trip(self):
        original = "round-trip string 中文"
        encoded = eu.hex_encode(original)
        decoded = eu.hex_decode(encoded["result"])
        assert decoded["result"] == original


class TestBase64RoundTrip:
    def test_round_trip(self):
        original = "hello world 中文"
        encoded = eu.b64_encode(original)
        decoded = eu.b64_decode(encoded["result"])
        assert decoded["result"] == original


class TestUrlRoundTrip:
    def test_round_trip(self):
        original = "hello world=a+b"
        encoded = eu.url_encode(original)
        decoded = eu.url_decode(encoded["result"])
        assert decoded["result"] == original
