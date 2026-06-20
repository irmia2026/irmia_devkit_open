"""Tests for text_filter — text line filtering operations."""

import pytest

from tools.text_filter import filter_lines


class TestTextFilter:
    @pytest.mark.parametrize("text,pattern,regex,case_sensitive,expected_matched", [
        ("apple\nbanana\ncherry\napple pie\n", "apple", False, False, 2),
        ("foo123\nbar\nfoo456\nbaz\n", r"foo\d+", True, False, 2),
        ("Apple\napple\nAPPLE\n", "apple", True, True, 1),
        ("abc\ndef\n", "xyz", False, False, 0),
    ])
    def test_grep(self, text: str, pattern: str, regex: bool, case_sensitive: bool, expected_matched: int) -> None:
        r = filter_lines(text, action="grep", pattern=pattern, regex=regex, case_sensitive=case_sensitive)
        assert r["ok"] is True
        assert r["matched"] == expected_matched

    @pytest.mark.parametrize("text,pattern,expected_matched", [
        ("apple\nbanana\ncherry", "apple", 2),
    ])
    def test_invert(self, text: str, pattern: str, expected_matched: int) -> None:
        r = filter_lines(text, action="invert", pattern=pattern)
        assert r["ok"] is True
        assert r["matched"] == expected_matched
        assert "apple" not in r["result"]

    @pytest.mark.parametrize("text,n,expected_matched", [
        ("line1\nline2\nline3\nline4\nline5\n", 3, 3),
        ("a\nb", 100, 2),
    ])
    def test_head(self, text: str, n: int, expected_matched: int) -> None:
        r = filter_lines(text, action="head", n=n)
        assert r["ok"] is True
        assert r["matched"] == expected_matched

    @pytest.mark.parametrize("text,n,expected_matched", [
        ("line1\nline2\nline3", 2, 2),
        ("a\nb", 100, 2),
    ])
    def test_tail(self, text: str, n: int, expected_matched: int) -> None:
        r = filter_lines(text, action="tail", n=n)
        assert r["ok"] is True
        assert r["matched"] == expected_matched

    def test_count(self) -> None:
        text = "a\nb\nc\n\n\n"
        r = filter_lines(text, action="count")
        assert r["ok"] is True
        assert r["total"] == 6
        assert r["non_empty"] == 3

    def test_invalid_regex(self) -> None:
        r = filter_lines("test", action="grep", pattern=r"[invalid", regex=True)
        assert r["ok"] is False
        assert "error" in r

    def test_unknown_action(self) -> None:
        r = filter_lines("test", action="unknown")
        assert r["ok"] is False
        assert "error" in r

    def test_empty_text(self) -> None:
        r = filter_lines("", action="grep", pattern="x")
        assert r["ok"] is True
        assert r["matched"] == 0

    def test_no_match_proposal(self) -> None:
        r = filter_lines("abc\ndef\n", action="grep", pattern="xyz")
        assert r["ok"] is True
        assert r["matched"] == 0
        assert "proposal" in r

    def test_fnmatch_wildcard(self) -> None:
        text = "foo.py\nfoo.txt\nbar.py\n"
        r = filter_lines(text, action="grep", pattern=".py")
        assert r["ok"] is True
        assert r["matched"] == 2

    # --- Boundary / edge cases ---

    def test_empty_pattern(self) -> None:
        r = filter_lines("abc", action="grep", pattern="")
        assert r["ok"] is True

    def test_very_long_line(self) -> None:
        long_line = "x" * 100_000 + "\ny\n"
        r = filter_lines(long_line, action="grep", pattern="y")
        assert r["ok"] is True
        assert r["matched"] == 1

    @pytest.mark.parametrize("n,expected_matched", [
        (0, 0),   # 0 lines requested → empty result
        (-1, 3),  # negative → returns all lines
    ])
    def test_edge_n(self, n: int, expected_matched: int) -> None:
        r = filter_lines("a\nb\nc\n", action="head", n=n)
        assert r["ok"] is True
        assert r["matched"] == expected_matched
