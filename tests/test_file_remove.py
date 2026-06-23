"""Tests for file_remove / file_move — path sandbox, batch move, overwrite, cross-partition routing."""

import os
import sys
from pathlib import Path

import pytest

from tools.file_remove import remove, move, _find_fast_copy

# 用例使用 pytest 内置 tmp_path fixture，不依赖 sandbox_dir 的持久化目录


class TestFileRemove:
    """remove() — 删除文件/目录"""

    def test_remove_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x", encoding="utf-8")
        r = remove(str(f))
        assert r["ok"] is True
        assert r["deleted"] == 1
        assert not f.exists()

    def test_remove_file_not_found(self):
        r = remove("/nonexistent/path/xyz.txt")
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_dir_requires_confirm(self, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        r = remove(str(d))
        assert r["ok"] is False
        assert "确认" in r.get("error", "") or "confirm" in r.get("proposal", "").lower()

    def test_dir_with_confirm(self, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        (d / "f.txt").write_text("x", encoding="utf-8")
        r = remove(str(d), confirm=True)
        assert r["ok"] is True
        assert r["deleted"] >= 1
        assert not d.exists()

    def test_blocks_dotdot_traversal(self):
        r = remove("../etc/passwd")
        assert r["ok"] is False
        assert ".." in r["error"]

    def test_three_dot_path_not_blocked(self):
        """... 开头的合法目录名不应被 .. 检测误杀"""
        r = remove(".../temp/something.py")
        assert r["ok"] is False
        assert "不存在" in r["error"]


class TestFileMove:
    """move() — 批量移动文件/目录"""

    def test_single_file(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.py").write_text("x=1", encoding="utf-8")
        r = move([str(src / "a.py")], str(dst))
        assert r["ok"] is True
        assert r["moved"] == 1
        assert (dst / "a.py").read_text(encoding="utf-8") == "x=1"
        assert not (src / "a.py").exists()

    def test_batch_files(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        for i in range(5):
            (src / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        r = move([str(src / f"f{i}.txt") for i in range(5)], str(dst))
        assert r["ok"] is True
        assert r["moved"] == 5
        for i in range(5):
            assert (dst / f"f{i}.txt").read_text(encoding="utf-8") == str(i)
            assert not (src / f"f{i}.txt").exists()

    def test_directory(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir()
        sub = src / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("z=3", encoding="utf-8")
        r = move([str(sub)], str(dst))
        assert r["ok"] is True
        assert r["moved"] == 1
        assert (dst / "sub" / "c.py").read_text(encoding="utf-8") == "z=3"
        assert not sub.exists()

    def test_overwrite_false_blocks(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.txt").write_text("new", encoding="utf-8")
        (dst / "a.txt").write_text("old", encoding="utf-8")
        r = move([str(src / "a.txt")], str(dst))
        assert r["ok"] is True
        assert r["moved"] == 0
        assert len(r["errors"]) == 1
        assert "目标已存在" in r["errors"][0]["error"]
        assert (dst / "a.txt").read_text(encoding="utf-8") == "old"

    def test_overwrite_true_replaces(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.txt").write_text("new", encoding="utf-8")
        (dst / "a.txt").write_text("old", encoding="utf-8")
        r = move([str(src / "a.txt")], str(dst), overwrite=True)
        assert r["ok"] is True
        assert r["moved"] == 1
        assert (dst / "a.txt").read_text(encoding="utf-8") == "new"

    def test_creates_dest_dir(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir()
        (src / "f.txt").write_text("x", encoding="utf-8")
        r = move([str(src / "f.txt")], str(dst))  # dst 不存在
        assert r["ok"] is True
        assert (dst / "f.txt").exists()

    def test_dest_not_directory(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.write_text("x", encoding="utf-8")
        (src / "f.txt").write_text("x", encoding="utf-8")
        r = move([str(src / "f.txt")], str(dst))
        assert r["ok"] is False
        assert "不是目录" in r["error"]

    def test_nonexistent_source(self, tmp_path):
        r = move(["/nonexistent/a.py"], str(tmp_path / "dst"))
        assert r["ok"] is False
        assert "没有可移动" in r["error"]

    def test_mixed_exist_and_missing(self, tmp_path):
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.txt").write_text("x", encoding="utf-8")
        r = move([str(src / "a.txt"), str(src / "missing.txt")], str(dst))
        assert r["ok"] is True
        assert r["moved"] == 1
        assert len(r["errors"]) == 1

    def test_empty_sources(self):
        r = move([], "/tmp")
        assert r["ok"] is False
        assert "非空" in r["error"]

    def test_path_traversal_blocked(self):
        r = move(["../etc/passwd"], "/tmp")
        assert r["ok"] is False
        assert "穿越" in r["error"]

    def test_system_prefix_blocked(self):
        # 跨平台：Windows 用 C:/Windows/System32，Linux 用 /etc
        bad_path = "C:/Windows/System32/kernel32.dll" if sys.platform == "win32" else "/etc/shadow"
        r = move([bad_path], "/tmp")
        assert r["ok"] is False
        assert any(kw in r.get("error", "") or kw in r.get("proposal", "")
                   for kw in ("禁止", "系统目录"))

    def test_large_batch_hint(self, tmp_path):
        """>1000 个文件且共父目录时返回 hint"""
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir()
        sources = [str(src / f"f{i}.txt") for i in range(1001)]
        # 创建几个样本文件让路径解析成立
        for s in sources[:10]:
            Path(s).write_text("x", encoding="utf-8")
        r = move(sources, str(dst))
        assert r["ok"] is True
        assert "hint" in r

    def test_already_moved_files_not_double_counted(self, tmp_path):
        """同批次内不因 dest_contents 更新不及时导致双计数"""
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.txt").write_text("1", encoding="utf-8")
        (src / "b.txt").write_text("2", encoding="utf-8")
        r = move([str(src / "a.txt"), str(src / "b.txt")], str(dst))
        assert r["moved"] == 2

    def test_cross_partition_detection(self, tmp_path):
        """同分区应返回 cross_partition=False 且 engine 为空"""
        src = tmp_path / "src"; dst = tmp_path / "dst"
        src.mkdir(); dst.mkdir()
        (src / "a.txt").write_text("x", encoding="utf-8")
        r = move([str(src / "a.txt")], str(dst))
        assert r.get("cross_partition") is None or r["cross_partition"] is False
        assert "engine" not in r  # 同分区不暴露 engine
