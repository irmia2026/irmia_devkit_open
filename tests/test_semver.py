"""Tests for semver."""

from tools import semver as sv


class TestCompare:
    def test_equal(self):
        r = sv.compare("1.2.3", "1.2.3")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_greater(self):
        r = sv.compare("2.0.0", "1.9.9")
        assert r["ok"] is True
        assert r["result"] == ">"

    def test_less(self):
        r = sv.compare("1.0.0", "1.0.1")
        assert r["ok"] is True
        assert r["result"] == "<"

    def test_with_v_prefix(self):
        r = sv.compare("v1.2.3", "1.2.3")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_major_minor_only(self):
        r = sv.compare("1.2", "1.2.0")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_pre_release_lower(self):
        r = sv.compare("1.0.0-alpha", "1.0.0")
        assert r["ok"] is True
        assert r["result"] == "<"

    def test_pre_release_numeric(self):
        r = sv.compare("1.0.0-2", "1.0.0-10")
        assert r["ok"] is True
        assert r["result"] == "<"

    def test_pre_release_mixed(self):
        r = sv.compare("1.0.0-alpha", "1.0.0-beta")
        assert r["ok"] is True
        assert r["result"] == "<"

    def test_build_metadata_ignored(self):
        r = sv.compare("1.0.0+build1", "1.0.0+build2")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_parsed_fields_present(self):
        r = sv.compare("1.2.3-beta.1", "1.0.0")
        assert r["ok"] is True
        assert r["v1_parsed"]["major"] == 1
        assert r["v1_parsed"]["minor"] == 2
        assert r["v1_parsed"]["patch"] == 3
        assert r["v1_parsed"]["pre"] == ["beta", 1]

    def test_invalid_version(self):
        r = sv.compare("not.a.version", "1.0.0")
        assert r["ok"] is False
        assert "格式无效" in r["error"]

    def test_both_invalid(self):
        r = sv.compare("abc", "def")
        assert r["ok"] is False

    def test_whitespace_trimmed(self):
        r = sv.compare("  1.0.0  ", "1.0.0")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_zero_versions(self):
        r = sv.compare("0.0.0", "0.0.0")
        assert r["ok"] is True
        assert r["result"] == "="

    def test_large_versions(self):
        r = sv.compare("999.999.999", "999.999.998")
        assert r["ok"] is True
        assert r["result"] == ">"
