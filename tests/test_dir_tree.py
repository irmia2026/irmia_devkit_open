"""Tests for dir_tree."""

import os
from pathlib import Path

import pytest

from tools import dir_tree as dt


class TestTree:
    def test_empty_directory(self, tmp_dir):
        r = dt.tree(tmp_dir)
        assert r["ok"] is True
        root_name = os.path.basename(os.path.abspath(tmp_dir))
        assert r["tree"] == root_name
        assert r["stats"] == {"dirs": 0, "files": 0}

    def test_tree_with_files_and_dirs(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "b").mkdir()
        (root / "b" / "c.txt").write_text("c", encoding="utf-8")

        r = dt.tree(tmp_dir, max_depth=3)
        assert r["ok"] is True
        lines = r["tree"].splitlines()
        assert any("a.py" in line for line in lines)
        assert any("b/" in line for line in lines)
        assert any("c.txt" in line for line in lines)
        assert r["stats"]["dirs"] == 1
        assert r["stats"]["files"] == 2

    def test_max_depth(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "d1").mkdir()
        (root / "d1" / "d2").mkdir()
        (root / "d1" / "d2" / "deep.txt").write_text("x", encoding="utf-8")

        r = dt.tree(tmp_dir, max_depth=2)
        assert "d1" in r["tree"]
        assert "deep.txt" not in r["tree"]

    def test_show_hidden(self, tmp_dir):
        root = Path(tmp_dir)
        (root / ".hidden").write_text("x", encoding="utf-8")
        r1 = dt.tree(tmp_dir)
        r2 = dt.tree(tmp_dir, show_hidden=True)
        assert ".hidden" not in r1["tree"]
        assert ".hidden" in r2["tree"]

    def test_pattern_filter(self, tmp_dir):
        root = Path(tmp_dir)
        (root / "a.py").write_text("a", encoding="utf-8")
        (root / "b.txt").write_text("b", encoding="utf-8")
        r = dt.tree(tmp_dir, pattern="*.py")
        assert "a.py" in r["tree"]
        assert "b.txt" not in r["tree"]

    def test_max_items(self, tmp_dir):
        root = Path(tmp_dir)
        for i in range(5):
            (root / f"f{i}.txt").write_text("x", encoding="utf-8")
        r = dt.tree(tmp_dir, max_items=2)
        assert "... 还有" in r["tree"]

    def test_not_a_directory(self, tmp_dir):
        p = Path(tmp_dir) / "file.txt"
        p.write_text("x", encoding="utf-8")
        r = dt.tree(str(p))
        assert r["ok"] is False
        assert "不是目录" in r["error"]

    def test_nonexistent_path(self, tmp_dir):
        r = dt.tree(str(Path(tmp_dir) / "missing"))
        assert r["ok"] is False
        assert "不是目录" in r["error"]

    def test_symlink_cycle(self, tmp_dir):
        root = Path(tmp_dir)
        sub = root / "sub"
        sub.mkdir()
        try:
            (sub / "loop").symlink_to(sub, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported")
        r = dt.tree(tmp_dir, max_depth=5)
        assert r["ok"] is True
        assert "循环链接" in r["tree"]
