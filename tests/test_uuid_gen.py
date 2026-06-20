"""Tests for uuid_gen."""

import re

from tools import uuid_gen as ug


class TestGenUuid4:
    def test_returns_valid_uuid(self):
        r = ug.gen("uuid4")
        assert r["ok"] is True
        assert r["kind"] == "uuid4"
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            r["value"],
        )

    def test_unique(self):
        values = {ug.gen("uuid4")["value"] for _ in range(100)}
        assert len(values) == 100


class TestGenHex:
    def test_default_length(self):
        r = ug.gen("hex")
        assert r["ok"] is True
        assert r["kind"] == "hex"
        assert len(r["value"]) == 16
        assert re.fullmatch(r"[0-9a-f]+", r["value"])

    def test_custom_length(self):
        r = ug.gen("hex", length=8)
        assert r["ok"] is True
        assert len(r["value"]) == 8

    def test_odd_length(self):
        r = ug.gen("hex", length=7)
        assert r["ok"] is True
        assert len(r["value"]) == 7


class TestGenToken:
    def test_default_length(self):
        r = ug.gen("token")
        assert r["ok"] is True
        assert r["kind"] == "token"
        assert len(r["value"]) == 16
        assert re.fullmatch(r"[A-Za-z0-9]+", r["value"])

    def test_custom_length(self):
        r = ug.gen("token", length=32)
        assert r["ok"] is True
        assert len(r["value"]) == 32


class TestGenInvalid:
    def test_unknown_kind(self):
        r = ug.gen("unknown")
        assert r["ok"] is False
        assert "未知 kind" in r["error"]

    def test_length_zero(self):
        r = ug.gen("hex", length=0)
        assert r["ok"] is False
        assert "error" in r

    def test_token_length_zero(self):
        r = ug.gen("token", length=0)
        assert r["ok"] is False
        assert "error" in r
