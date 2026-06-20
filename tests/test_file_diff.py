"""Tests for file_diff."""

from pathlib import Path

from tools import file_diff as fd
from tools._file_utils import FILE_DIFF_MAX_SIZE


class TestCompare:
    def test_identical_files(self, tmp_dir):
        p = Path(tmp_dir) / "a.txt"
        p.write_text("hello\nworld\n", encoding="utf-8")
        r = fd.compare(str(p), str(p))
        assert r["ok"] is True
        assert r["identical"] is True
        assert r["added"] == 0
        assert r["removed"] == 0
        assert r["total_changes"] == 0

    def test_different_files(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        a.write_text("foo\nbar\n", encoding="utf-8")
        b.write_text("foo\nbaz\nqux\n", encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is True
        assert r["identical"] is False
        assert r["added"] == 2
        assert r["removed"] == 1
        assert r["total_changes"] == 3
        assert "baz" in r["diff"]

    def test_missing_file_a(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        b.write_text("x", encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_missing_file_b(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        a.write_text("x", encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_file_too_large(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        a.write_bytes(b"x" * (FILE_DIFF_MAX_SIZE + 1))
        b.write_text("x", encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is False
        assert "过大" in r["error"]

    def test_many_lines_truncated(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        a.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
        b.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is True
        assert r["diff_lines_total"] == 0

    def test_diff_lines_counted_across_truncation(self, tmp_dir):
        a = Path(tmp_dir) / "a.txt"
        b = Path(tmp_dir) / "b.txt"
        a.write_text("\n".join(f"a{i}" for i in range(150)), encoding="utf-8")
        b.write_text("\n".join(f"b{i}" for i in range(150)), encoding="utf-8")
        r = fd.compare(str(a), str(b))
        assert r["ok"] is True
        assert r["added"] == 150
        assert r["removed"] == 150
        assert r["diff_lines_shown"] <= 100
        assert r["truncated"] is True

    def test_binary_files_unreadable(self, tmp_dir):
        a = Path(tmp_dir) / "a.bin"
        b = Path(tmp_dir) / "b.bin"
        a.write_bytes(bytes(range(256)))
        b.write_bytes(bytes(range(256)))
        r = fd.compare(str(a), str(b))
        # read_file uses errors='replace', so binary should still be readable.
        assert r["ok"] is True
        assert r["identical"] is True
