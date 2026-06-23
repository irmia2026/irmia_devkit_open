"""Tests for multi_edit."""

import os
import tempfile
from pathlib import Path

import pytest

from tools.multi_edit import run


@pytest.fixture
def tmp_file():
    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestMultiEdit:
    def test_single_edit(self, tmp_file):
        Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 2"}])
        assert r["ok"] is True
        assert Path(tmp_file).read_text(encoding="utf-8") == "x = 2\n"

    def test_replace_all(self, tmp_file):
        Path(tmp_file).write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 2", "replace_all": True}])
        assert r["ok"] is True
        assert r["replacements_made"] == 2
        assert Path(tmp_file).read_text(encoding="utf-8") == "x = 2\nx = 2\n"

    def test_occurrence(self, tmp_file):
        Path(tmp_file).write_text("x = 1\nx = 1\nx = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 9", "occurrence": 2}])
        assert r["ok"] is True
        lines = Path(tmp_file).read_text(encoding="utf-8").splitlines()
        assert lines == ["x = 1", "x = 9", "x = 1"]

    def test_empty_old_rejected(self, tmp_file):
        r = run([{"file": tmp_file, "old": "", "new": "x"}])
        assert r["ok"] is False
        assert "old must not be empty" in r["error"]

    def test_negative_occurrence_rejected(self, tmp_file):
        Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 2", "occurrence": -1}])
        assert r["ok"] is False
        assert "occurrence" in r["error"]

    def test_replace_all_and_occurrence_mutual_exclusion(self, tmp_file):
        Path(tmp_file).write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 2", "replace_all": True, "occurrence": 1}])
        assert r["ok"] is False
        assert "mutually exclusive" in r["error"]

    def test_multiple_matches_require_occurrence(self, tmp_file):
        Path(tmp_file).write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x = 2"}])
        assert r["ok"] is False
        assert "appears 2 times" in r["error"]

    def test_crlf_file_with_lf_old(self, tmp_file):
        """文件 CRLF，old 用 LF 也能匹配，并保留 CRLF。"""
        Path(tmp_file).write_bytes(b"def foo():\r\n    x = 1\r\n    y = 2\r\n")
        r = run([{"file": tmp_file, "old": "x = 1\ny = 2", "new": "x = 9\ny = 8"}])
        assert r["ok"] is True
        data = Path(tmp_file).read_bytes()
        assert b"\r\n" in data
        assert b"    x = 9\r\n    y = 8" in data

    def test_syntax_error_rolls_back(self, tmp_file):
        Path(tmp_file).write_text("x = 1\n", encoding="utf-8")
        r = run([{"file": tmp_file, "old": "x = 1", "new": "x ="}])
        assert r["ok"] is False
        assert Path(tmp_file).read_text(encoding="utf-8") == "x = 1\n"

    def test_sequential_edits_same_file(self, tmp_file):
        Path(tmp_file).write_text("foo\n", encoding="utf-8")
        r = run([
            {"file": tmp_file, "old": "foo", "new": "bar"},
            {"file": tmp_file, "old": "bar", "new": "baz"},
        ])
        assert r["ok"] is True
        assert Path(tmp_file).read_text(encoding="utf-8") == "baz\n"

    def test_nonexistent_file(self, tmp_file):
        os.unlink(tmp_file)
        r = run([{"file": tmp_file, "old": "x", "new": "y"}])
        assert r["ok"] is False
        assert "does not exist" in r["error"]

    def test_not_a_dict_edit(self):
        r = run(["not-a-dict"])
        assert r["ok"] is False
        assert "must be an object" in r["error"]

    def test_empty_edits_list(self):
        r = run([])
        assert r["ok"] is False
        assert "non-empty list" in r["error"]

    def test_path_traversal_blocked(self, tmp_file):
        """.. 穿越应在 resolve 之前被 check_path_allowed 拦截。"""
        from pathlib import Path
        base = Path(tmp_file).parent
        traversal = f"{base}/subdir/../../{base.name}/target.txt"
        r = run([{"file": traversal, "old": "x", "new": "y"}])
        assert r["ok"] is False
        assert "穿越" in r["error"]
