"""Tests for safe_edit — backup/patch/syntax/rollback pipeline."""

import os
import tempfile
from pathlib import Path
import pytest
from tools.safe_edit import edit, _backup_dir


@pytest.fixture
def python_file():
    """Create a temp .py file for testing."""
    fd, path = tempfile.mkstemp(suffix=".py", text=True)
    with os.fdopen(fd, "w") as f:
        f.write("x = 1\ny = 2\nprint(x + y)\n")
    yield path
    os.unlink(path)


class TestSafeEdit:
    def test_simple_replace(self, python_file):
        result = edit(python_file, "x = 1", "x = 42")
        assert result["ok"] is True
        assert result["replaced"] == 1
        content = Path(python_file).read_text()
        assert "x = 42" in content

    def test_multiple_matches_without_occurrence(self, python_file):
        Path(python_file).write_text("x = 1\ny = 1\nz = 1\n")
        result = edit(python_file, "= 1", "= 2")
        assert result["ok"] is False
        assert result["occurrence_count"] == 3
        assert len(result["matches"]) == 3

    def test_multiple_matches_with_occurrence(self, python_file):
        Path(python_file).write_text("x = 1\ny = 1\nz = 1\n")
        result = edit(python_file, "= 1", "= 2", occurrence=2)
        assert result["ok"] is True
        content = Path(python_file).read_text()
        assert "x = 1" in content
        assert "y = 2" in content
        assert "z = 1" in content

    def test_replace_all(self, python_file):
        Path(python_file).write_text("x = 1\ny = 1\nz = 1\n")
        result = edit(python_file, "= 1", "= 2", replace_all=True)
        assert result["ok"] is True
        content = Path(python_file).read_text()
        assert "= 1" not in content
        assert "= 2" in content

    def test_blocks_empty_old(self, python_file):
        result = edit(python_file, "", "anything")
        assert result["ok"] is False
        assert "空" in result["error"]

    def test_not_found(self, python_file):
        result = edit(python_file, "nonexistent_text_xyz", "new")
        assert result["ok"] is False
        assert "未找到" in result["error"]

    def test_rollback_on_syntax_error(self, python_file):
        original = Path(python_file).read_text()
        result = edit(python_file, "x = 1", "x =")
        assert result["ok"] is False
        assert result["rolled_back"] is True
        assert Path(python_file).read_text() == original

    def test_backup_dir_config(self):
        """Verify backup_dir defaults to ~/.irmia/backups."""
        d = _backup_dir()
        assert d.name == "backups"
        assert ".irmia" in str(d)

    def test_occurrence_exceeds_count(self, python_file):
        Path(python_file).write_text("a b c\n")
        result = edit(python_file, "a", "x", occurrence=5)
        assert result["ok"] is False
        assert "超过" in result["error"]

    def test_preserves_crlf(self, python_file):
        """编辑后应保留原始 CRLF 换行符。"""
        Path(python_file).write_bytes(b"x = 1\r\ny = 2\r\n")
        result = edit(python_file, "x = 1", "x = 42")
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert b"\r\n" in content
        assert b"\n" not in content.replace(b"\r\n", b"")

    def test_replace_all_preserves_crlf(self, python_file):
        Path(python_file).write_bytes(b"x = 1\r\ny = 1\r\n")
        result = edit(python_file, "= 1", "= 2", replace_all=True)
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert content == b"x = 2\r\ny = 2\r\n"

    def test_occurrence_preserves_crlf(self, python_file):
        Path(python_file).write_bytes(b"x = 1\r\ny = 1\r\nz = 1\r\n")
        result = edit(python_file, "= 1", "= 2", occurrence=2)
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert content == b"x = 1\r\ny = 2\r\nz = 1\r\n"

    def test_path_sandbox_rejects_system(self, python_file):
        """尝试编辑系统目录文件应被沙箱拒绝。"""
        result = edit("C:/Windows/System32/notepad.exe", "old", "new")
        assert result["ok"] is False
        assert "禁止" in result["error"] or "系统目录" in result["error"]

    def test_path_sandbox_rejects_traversal(self, python_file):
        """路径穿越应被拒绝。"""
        base = Path(python_file).parent
        traversal = f"{base}/subdir/../../{base.name}/secret.txt"
        result = edit(traversal, "secret", "leaked")
        assert result["ok"] is False
        assert "穿越" in result["error"]

    def test_occurrence_negative_rejected(self, python_file):
        """occurrence 为负数应被拒绝。"""
        result = edit(python_file, "x = 1", "x = 42", occurrence=-1)
        assert result["ok"] is False
        assert "负数" in result["error"]

    def test_occurrence_replace_all_mutual_exclusive(self, python_file):
        """occurrence 与 replace_all 不能同时指定。"""
        result = edit(python_file, "x = 1", "x = 42", occurrence=1, replace_all=True)
        assert result["ok"] is False
        assert "不能同时" in result["error"]

    def test_align_whitespace_with_replace_all(self, python_file):
        """replace_all=True 时也应触发空白对齐 fallback。"""
        from pathlib import Path
        import tempfile, os

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            Path(path).write_bytes(b"    a = 1\n    b = 1\n")
            # old 缩进故意少一级
            result = edit(path, "a = 1\n    b = 1", "a = 2\n    b = 2", replace_all=True)
            assert result["ok"] is True
            assert Path(path).read_bytes() == b"    a = 2\n    b = 2\n"
        finally:
            os.unlink(path)
