"""Tests for time_utils."""

from datetime import datetime

import pytest

from tools import time_utils as tu


class TestNow:
    def test_returns_ok_and_fields(self):
        r = tu.now()
        assert r["ok"] is True
        assert "iso" in r
        assert "timestamp" in r
        assert "timestamp_ms" in r
        assert isinstance(r["iso"], str)
        assert isinstance(r["timestamp"], int)
        assert isinstance(r["timestamp_ms"], int)

    def test_values_are_consistent(self):
        r = tu.now()
        parsed = datetime.fromisoformat(r["iso"])
        # Allow small drift due to separate datetime.now() calls.
        assert abs(parsed.timestamp() - r["timestamp"]) < 2
        assert r["timestamp_ms"] == r["timestamp"] * 1000


class TestTsToIso:
    def test_seconds(self):
        r = tu.ts_to_iso(0)
        assert r["ok"] is True
        assert r["iso"].startswith("1970-01-01")

    def test_milliseconds(self):
        r = tu.ts_to_iso(0, ms=True)
        assert r["ok"] is True
        assert r["iso"].startswith("1970-01-01")

    def test_invalid_timestamp(self):
        r = tu.ts_to_iso(float("inf"))
        assert r["ok"] is False
        assert "error" in r


class TestIsoToTs:
    def test_basic(self):
        r = tu.iso_to_ts("2026-05-20T23:00:00")
        assert r["ok"] is True
        assert isinstance(r["timestamp"], int)
        assert r["timestamp"] > 0

    def test_with_timezone(self):
        r = tu.iso_to_ts("2026-05-20T23:00:00+00:00")
        assert r["ok"] is True
        assert r["timestamp"] == 1776255600

    def test_invalid_iso(self):
        r = tu.iso_to_ts("not an iso string")
        assert r["ok"] is False
        assert "error" in r


class TestTimeDiff:
    def test_one_minute(self):
        r = tu.time_diff("2026-05-20T23:00:00", "2026-05-20T23:01:00")
        assert r["ok"] is True
        assert r["delta_seconds"] == 60
        assert r["delta_minutes"] == 1.0
        assert r["delta_hours"] == pytest.approx(0.0167, abs=0.0001)

    def test_negative_diff(self):
        r = tu.time_diff("2026-05-20T23:01:00", "2026-05-20T23:00:00")
        assert r["ok"] is True
        assert r["delta_seconds"] == -60

    def test_invalid_iso(self):
        r = tu.time_diff("bad", "2026-05-20T23:00:00")
        assert r["ok"] is False
        assert "error" in r
