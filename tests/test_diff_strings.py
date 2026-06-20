"""Tests for diff_strings — string diff comparison."""

import pytest

from tools.diff_strings import diff


class TestDiffStrings:
    @pytest.mark.parametrize("a,b,expected", [
        ("hello\nworld\n", "hello\nworld\n", True),
        ("", "", True),
        ("你好\n世界\n", "你好\n世界\n", True),
    ])
    def test_identical(self, a: str, b: str, expected: bool) -> None:
        r = diff(a, b)
        assert r["ok"] is True
        assert r["identical"] is expected

    @pytest.mark.parametrize("a,b,added,removed,total", [
        ("foo\nbar\n", "foo\nbaz\nqux\n", 2, 1, 3),
        ("hello", "", 0, 1, 1),
        ("abc\n123\n", "xyz\n789\n", 2, 2, 4),
    ])
    def test_different(self, a: str, b: str, added: int, removed: int, total: int) -> None:
        r = diff(a, b)
        assert r["ok"] is True
        assert r["identical"] is False
        assert r["added"] == added
        assert r["removed"] == removed
        assert r["total_changes"] == total

    def test_trailing_newline_matters(self) -> None:
        r = diff("hello", "hello\n")
        assert r["identical"] is False

    def test_context_lines_param(self) -> None:
        r = diff("a\nb\nc\nd\ne\n", "a\nb\nx\nd\ne\n", context_lines=0)
        assert r["ok"] is True
        assert r["identical"] is False
        assert r["diff"] is not None

    def test_max_lines_truncation(self) -> None:
        a = "\n".join(f"line {i}" for i in range(50))
        b = "\n".join(f"LINE {i}" for i in range(50))
        r = diff(a, b, max_lines=5)
        assert r["ok"] is True
        assert r["truncated"] is True
        assert r["diff_lines_shown"] <= 5

    # --- Boundary / edge cases ---

    def test_none_input(self) -> None:
        r = diff(None, "hello")
        assert r["ok"] is False

    def test_whitespace_diff(self) -> None:
        r = diff("hello", "hello   ")
        assert r["identical"] is False

    def test_crlf_vs_lf(self) -> None:
        r = diff("line1\r\nline2\r\n", "line1\nline2\n")
        assert r["ok"] is True  # line endings treated as content by difflib

    def test_large_diff_not_crashing(self) -> None:
        a = "\n".join(f"line_{i}_abcdefgh" for i in range(10000))
        b = "\n".join(f"line_{i}_ZYXWVUTS" for i in range(10000))
        r = diff(a, b)
        assert r["ok"] is True
        assert r["total_changes"] > 0

    def test_special_unicode(self) -> None:
        r = diff("emoji: 😀🔥", "emoji: 😀🔥")
        assert r["identical"] is True
        r2 = diff("emoji: 😀", "emoji: 😢")
        assert r2["identical"] is False
