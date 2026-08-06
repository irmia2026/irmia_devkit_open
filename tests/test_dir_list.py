"""Tests for dir_list."""

from datetime import datetime
from pathlib import Path

import pytest

from tools import dir_list as dl


class TestListDir:
    def test_empty_directory(self, tmp_dir):
        r = dl.list_dir(tmp_dir)
        assert r["ok"] is True
        assert r["count"] == 0
        assert r["files"] == 0
        assert r["dirs"] == 0
        assert r["entries"] == []
        assert r["truncated"] is False
        assert r["path"] == str(Path(tmp_dir).resolve())

    def test_lists_files_and_dirs(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "b.txt").write_text("b", encoding="utf-8")
        (root / "sub").mkdir()
        (root / "sub" / "c.py").write_text("c", encoding="utf-8")

        r = dl.list_dir(tmp_dir)
        assert r["ok"] is True
        names = [e["name"] for e in r["entries"]]
        assert "a.py" in names
        assert "b.txt" in names
        assert "sub" in names
        assert "c.py" not in names
        assert r["files"] == 2
        assert r["dirs"] == 1

    def test_depth_two(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "sub").mkdir()
        (root / "sub" / "nested.txt").write_text("x", encoding="utf-8")
        r = dl.list_dir(tmp_dir, max_depth=2)
        names = [e["name"] for e in r["entries"]]
        assert "nested.txt" in names

    def test_pattern_filter(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "b.txt").write_text("b", encoding="utf-8")
        r = dl.list_dir(tmp_dir, pattern="*.py")
        names = [e["name"] for e in r["entries"]]
        assert names == ["a.py"]

    def test_show_hidden(self, tmp_dir):
        root = Path(tmp_dir)
        (root / ".hidden").write_text("x", encoding="utf-8")
        (root / "visible").write_text("y", encoding="utf-8")
        r = dl.list_dir(tmp_dir, show_hidden=False)
        names = [e["name"] for e in r["entries"]]
        assert ".hidden" not in names
        assert "visible" in names

        r2 = dl.list_dir(tmp_dir, show_hidden=True)
        names2 = [e["name"] for e in r2["entries"]]
        assert ".hidden" in names2

    def test_nonexistent_path(self, tmp_dir):
        r = dl.list_dir(str(Path(tmp_dir) / "missing"))
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_file_not_directory(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        p.write_text("x", encoding="utf-8")
        r = dl.list_dir(str(p))
        assert r["ok"] is False
        assert "不是目录" in r["error"]

    def test_truncate_over_200(self, tmp_dir):
        root = Path(tmp_dir)
        for i in range(210):
            (root / f"f{i}.txt").write_text("x", encoding="utf-8")
        r = dl.list_dir(tmp_dir)
        assert r["truncated"] is True
        assert len(r["entries"]) == 200
        assert r["count"] == 210

    def test_symlink_cycle_is_skipped(self, tmp_dir):
        # Symlink cycles require platform support; skip on Windows if needed.
        root = Path(tmp_dir)
        sub = root / "sub"
        sub.mkdir()
        try:
            (sub / "loop").symlink_to(sub, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported")
        r = dl.list_dir(tmp_dir, max_depth=3)
        assert r["ok"] is True

    def test_entries_have_mtime(self, tmp_dir):
        """S3: 文件和目录 entry 都带 ISO 格式 mtime。"""
        root = Path(tmp_dir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "sub").mkdir()

        r = dl.list_dir(tmp_dir)
        assert r["ok"] is True
        by_name = {e["name"]: e for e in r["entries"]}
        for name in ("a.py", "sub"):
            assert "mtime" in by_name[name]
            # ISO 格式可被 fromisoformat 解析
            datetime.fromisoformat(by_name[name]["mtime"])

