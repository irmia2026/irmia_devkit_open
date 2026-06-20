"""Tests for file_patch."""

import os
import tempfile
from pathlib import Path

import pytest

from tools.file_patch import patch, preview


@pytest.fixture
def tmp_file():
    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestPatch:
    def test_simple_replace(self, tmp_file):
        Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
        r = patch(tmp_file, "x = 1", "x = 2")
        assert r["ok"] is True
        assert r["replaced"] == 1
        assert Path(tmp_file).read_text(encoding="utf-8") == "x = 2\n"

    def test_replace_all(self, tmp_file):
        Path(tmp_file).write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = patch(tmp_file, "x = 1", "x = 2", replace_all=True)
        assert r["ok"] is True
        assert r["replaced"] == 2
        assert Path(tmp_file).read_text(encoding="utf-8") == "x = 2\nx = 2\n"

    def test_empty_old_rejected(self, tmp_file):
        r = patch(tmp_file, "", "x")
        assert r["ok"] is False
        assert "old" in r["error"]

    def test_not_found_gives_hint(self, tmp_file):
        Path(tmp_file).write_text("hello world\n", encoding="utf-8")
        r = patch(tmp_file, "nonexistent", "x")
        assert r["ok"] is False
        assert "未找到" in r["error"]
        assert "hint" in r

    def test_align_whitespace_fallback(self, tmp_file):
        """old 不带缩进时，应对齐到文件中的缩进。"""
        Path(tmp_file).write_text("def foo():\n    x = 1\n    y = 2\n", encoding="utf-8")
        r = patch(tmp_file, "x = 1\ny = 2", "x = 9\ny = 8")
        assert r["ok"] is True
        assert r.get("whitespace_aligned") is True
        content = Path(tmp_file).read_text(encoding="utf-8")
        assert "    x = 9" in content
        assert "    y = 8" in content

    def test_crlf_file_with_lf_old(self, tmp_file):
        """文件是 CRLF，old 用 LF 也能正确替换并保留 CRLF。"""
        Path(tmp_file).write_bytes(b"x = 1\r\ny = 2\r\n")
        r = patch(tmp_file, "x = 1\ny = 2", "a = 1\nb = 2")
        assert r["ok"] is True
        data = Path(tmp_file).read_bytes()
        assert b"\r\n" in data
        assert b"a = 1\r\nb = 2" in data


class TestPreview:
    def test_preview_simple(self, tmp_file):
        Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
        r = preview(tmp_file, "x = 1", "x = 2")
        assert r["ok"] is True
        assert "x = 2" in r["diff"]

    def test_preview_empty_old_rejected(self, tmp_file):
        r = preview(tmp_file, "", "x")
        assert r["ok"] is False
        assert "old" in r["error"]

    def test_preview_align_whitespace_fallback(self, tmp_file):
        Path(tmp_file).write_text("def foo():\n    x = 1\n    y = 2\n", encoding="utf-8")
        r = preview(tmp_file, "x = 1\ny = 2", "x = 9\ny = 8")
        assert r["ok"] is True
        assert "x = 9" in r["diff"]

    def test_preview_crlf_preserved(self, tmp_file):
        Path(tmp_file).write_bytes(b"x = 1\r\n")
        r = preview(tmp_file, "x = 1", "x = 2")
        assert r["ok"] is True
        # diff 中应保留 CRLF 表现（行尾有 \r）
        assert "\r" in r["diff"]
