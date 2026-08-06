"""Tests for safe_edit — backup/patch/syntax/rollback pipeline."""

import os
import sys
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

    def test_crlf_file_multi_line_lf_old_default(self, python_file):
        """CRLF 文件 + LF 多行 old → 默认单次替换成功（回归 Bug A）。"""
        Path(python_file).write_bytes(b"x = 1\r\ny = 2\r\nprint(x + y)\r\n")
        result = edit(python_file, "x = 1\ny = 2", "x = 10\ny = 20")
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert content == b"x = 10\r\ny = 20\r\nprint(x + y)\r\n"

    def test_crlf_file_multi_line_lf_old_occurrence(self, python_file):
        """CRLF 文件 + LF 多行 old + occurrence=N。"""
        Path(python_file).write_bytes(b"a = 1\r\nb = 2\r\na = 1\r\nb = 2\r\n")
        result = edit(python_file, "a = 1\nb = 2", "a = 9\nb = 9", occurrence=2)
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert content == b"a = 1\r\nb = 2\r\na = 9\r\nb = 9\r\n"

    def test_crlf_file_multi_line_lf_old_replace_all(self, python_file):
        """CRLF 文件 + LF 多行 old + replace_all=True。"""
        Path(python_file).write_bytes(b"a = 1\r\nb = 2\r\na = 1\r\nb = 2\r\n")
        result = edit(python_file, "a = 1\nb = 2", "a = 9\nb = 9", replace_all=True)
        assert result["ok"] is True
        content = Path(python_file).read_bytes()
        assert content == b"a = 9\r\nb = 9\r\na = 9\r\nb = 9\r\n"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows 系统路径测试")
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

    def test_trailing_whitespace_tolerance(self, python_file):
        """文件有尾随空格 + old 不带尾随空格 → align_whitespace 应容错匹配。"""
        from pathlib import Path
        Path(python_file).write_text("x = 1   \ny = 2\nprint(x + y)\n")
        # old 无尾随空格
        result = edit(python_file, "x = 1\ny = 2", "x = 10\ny = 20")
        assert result["ok"] is True
        content = Path(python_file).read_text()
        assert "x = 10" in content

    def test_trailing_whitespace_occurrence(self, python_file):
        """尾随空格 + occurrence=N 也应容错匹配。
        old 的对齐行尾空格会被替换掉（属于被替换的旧内容）。"""
        from pathlib import Path
        Path(python_file).write_text("a = 1   \nb = 2\na = 1   \nb = 2\n")
        result = edit(python_file, "a = 1\nb = 2", "a = 9\nb = 9", occurrence=2)
        assert result["ok"] is True
        content = Path(python_file).read_text()
        # 第 1 组不动，行尾空格保留；第 2 组被替换，行尾空格不保留
        assert content == "a = 1   \nb = 2\na = 9\nb = 9\n"

    def test_trailing_whitespace_replace_all(self, python_file):
        """尾随空格 + replace_all=True 也应容错匹配。
        old 的对齐行尾空格会被替换掉。"""
        from pathlib import Path
        Path(python_file).write_text("a = 1   \nb = 2\na = 1   \nb = 2\n")
        result = edit(python_file, "a = 1\nb = 2", "a = 9\nb = 9", replace_all=True)
        assert result["ok"] is True
        content = Path(python_file).read_text()
        assert content == "a = 9\nb = 9\na = 9\nb = 9\n"

    def test_rollback_nonexistent_file(self, tmp_dir):
        """rollback 不存在的文件应返回友好错误。"""
        from tools.safe_edit import rollback
        result = rollback(str(Path(tmp_dir) / "no_such_file.py"))
        assert result["ok"] is False
        assert "不存在" in result["error"]


class TestPruneBackups:
    """prune_backups 保留策略：按文件前缀保留最近 N 份 + 总大小 LRU。"""

    def _make_backup(self, backup_dir: Path, stem: str, ts: str, mtime: float, size: int = 4) -> Path:
        f = backup_dir / f"{stem}.{ts}.bak"
        f.write_bytes(b"x" * size)
        os.utime(f, (mtime, mtime))
        return f

    def test_keep_per_file_10_of_12(self, tmp_dir):
        """同一文件造 12 份备份，应只剩最近 10 份。"""
        from tools._file_utils import prune_backups

        bdir = Path(tmp_dir) / "backups"
        bdir.mkdir()
        stem = "foo.py.1234abcd"
        for i in range(12):
            self._make_backup(bdir, stem, f"202601{i:02d}_120000_000000", mtime=1000 + i)
        prune_backups(str(bdir))
        remaining = sorted(bdir.glob("*.bak"))
        assert len(remaining) == 10
        # 最旧的两份（i=0,1）应被删除
        names = [f.name for f in remaining]
        assert not any("20260100_" in n or "20260101_" in n for n in names)

    def test_keep_per_file_does_not_touch_other_files(self, tmp_dir):
        """其他文件的备份不受影响。"""
        from tools._file_utils import prune_backups

        bdir = Path(tmp_dir) / "backups"
        bdir.mkdir()
        for i in range(12):
            self._make_backup(bdir, "foo.py.1234abcd", f"202601{i:02d}_120000_000000", mtime=1000 + i)
        for i in range(3):
            self._make_backup(bdir, "bar.py.5678efab", f"202602{i:02d}_120000_000000", mtime=2000 + i)
        prune_backups(str(bdir))
        assert len(list(bdir.glob("bar.py.*.bak"))) == 3
        assert len(list(bdir.glob("foo.py.*.bak"))) == 10

    def test_lru_max_total_mb(self, tmp_dir):
        """总大小超限时从最旧开始删除直到达标。"""
        from tools._file_utils import prune_backups

        bdir = Path(tmp_dir) / "backups"
        bdir.mkdir()
        stem = "big.py.aaaa0000"
        for i in range(5):
            self._make_backup(bdir, stem, f"202603{i:02d}_120000_000000", mtime=1000 + i, size=1024)
        prune_backups(str(bdir), keep_per_file=10, max_total_mb=0)
        assert list(bdir.glob("*.bak")) == []

    def test_silent_on_nonexistent_dir(self, tmp_dir):
        """目录不存在等异常应静默吞掉，绝不抛出。"""
        from tools._file_utils import prune_backups

        prune_backups(str(Path(tmp_dir) / "no_such_dir"))  # 不应抛异常

    def test_recognizes_write_and_multi_suffixes(self, tmp_dir):
        """safe_write(.write.bak)/multi_edit(.multi.bak) 的备份也参与同一前缀计数。"""
        from tools._file_utils import prune_backups

        bdir = Path(tmp_dir) / "backups"
        bdir.mkdir()
        stem = "mix.py.bbbb1111"
        for i in range(6):
            self._make_backup(bdir, stem, f"202604{i:02d}_120000_000000", mtime=1000 + i)
        for i in range(6):
            f = bdir / f"{stem}.202604{i:02d}_130000_000000.write.bak"
            f.write_bytes(b"x")
            os.utime(f, (2000 + i, 2000 + i))
        prune_backups(str(bdir))
        assert len(list(bdir.glob("*.bak"))) == 10


class TestPatchFailureNoBackupResidue:
    """P7: patch() 失败且文件未被修改时，刚创建的备份应被删除。"""

    def test_patch_failure_removes_backup(self, python_file, tmp_dir, monkeypatch):
        from tools import config as _cfg
        from tools import safe_edit as se

        bdir = Path(tmp_dir) / "backups"
        _cfg.set_config({"backup_dir": str(bdir)})
        monkeypatch.setattr(se, "patch", lambda *a, **k: {"ok": False, "error": "boom"})

        result = se.edit(python_file, "x = 1", "x = 2")
        assert result["ok"] is False
        assert "备份保留" not in str(result.get("proposal", ""))
        assert result.get("backup_deleted") is True
        # 备份目录不应有残留
        leftover = list(bdir.glob("*.bak")) if bdir.exists() else []
        assert leftover == []
        # 文件未被修改
        assert Path(python_file).read_text() == "x = 1\ny = 2\nprint(x + y)\n"


class TestLineModes:
    """M2: safe_edit 行号寻址模式 insert_at_line / delete_lines。"""

    def _txt(self, tmp_dir, name="m.txt", content="l1\nl2\nl3\nl4\n"):
        p = Path(tmp_dir) / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_insert_at_line_middle(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="insert_at_line", line=2, new="NEW")
        assert result["ok"] is True
        assert result["inserted_after_line"] == 2
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl2\nNEW\nl3\nl4\n"

    def test_insert_at_line_zero_means_beginning(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="insert_at_line", line=0, new="HEAD")
        assert result["ok"] is True
        assert Path(fp).read_text(encoding="utf-8") == "HEAD\nl1\nl2\nl3\nl4\n"

    def test_insert_at_line_end(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="insert_at_line", line=4, new="TAIL")
        assert result["ok"] is True
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl2\nl3\nl4\nTAIL\n"

    def test_insert_at_line_out_of_range(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="insert_at_line", line=99, new="X")
        assert result["ok"] is False
        assert result["total_lines"] == 4
        assert result["next_call"]["tool"] == "safe_read"
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl2\nl3\nl4\n"

    def test_insert_preserves_crlf(self, tmp_dir):
        p = Path(tmp_dir) / "crlf.txt"
        p.write_bytes(b"a\r\nb\r\n")
        result = edit(str(p), mode="insert_at_line", line=1, new="X")
        assert result["ok"] is True
        assert Path(p).read_bytes() == b"a\r\nX\r\nb\r\n"

    def test_delete_lines_middle(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="delete_lines", start_line=2, end_line=3)
        assert result["ok"] is True
        assert result["deleted_lines"] == [2, 3]
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl4\n"

    def test_delete_lines_single(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="delete_lines", start_line=1, end_line=1)
        assert result["ok"] is True
        assert Path(fp).read_text(encoding="utf-8") == "l2\nl3\nl4\n"

    def test_delete_lines_out_of_range(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="delete_lines", start_line=3, end_line=99)
        assert result["ok"] is False
        assert "越界" in result["error"]
        assert result["total_lines"] == 4
        assert result["next_call"]["tool"] == "safe_read"
        assert result["next_call"]["params"]["path"].endswith("m.txt")
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl2\nl3\nl4\n"

    def test_delete_lines_reversed_range_rejected(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, mode="delete_lines", start_line=3, end_line=2)
        assert result["ok"] is False
        assert "越界" in result["error"]

    def test_invalid_mode_rejected(self, tmp_dir):
        fp = self._txt(tmp_dir)
        result = edit(fp, "l1", "l2", mode="bogus")
        assert result["ok"] is False
        assert "mode" in result["error"]
        assert Path(fp).read_text(encoding="utf-8") == "l1\nl2\nl3\nl4\n"

    def test_insert_syntax_error_rolls_back(self, tmp_dir):
        """行号模式同样走 语法检查→失败回滚 链路。"""
        p = Path(tmp_dir) / "m.py"
        p.write_text("x = 1\n", encoding="utf-8")
        result = edit(str(p), mode="insert_at_line", line=1, new="def bad(")
        assert result["ok"] is False
        assert result["rolled_back"] is True
        assert p.read_text(encoding="utf-8") == "x = 1\n"


class TestFilePatchOccurrence:
    """U2: file_patch 的 occurrence 消歧参数。"""

    def _txt(self, tmp_dir, content):
        p = Path(tmp_dir) / "fp.txt"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_occurrence_second(self, tmp_dir):
        from tools.file_patch import patch

        fp = self._txt(tmp_dir, "a = 1\nb = 1\nc = 1\n")
        r = patch(fp, "= 1", "= 9", occurrence=2)
        assert r["ok"] is True
        assert r["replaced"] == 1
        assert r["occurrence"] == 2
        assert Path(fp).read_text(encoding="utf-8") == "a = 1\nb = 9\nc = 1\n"

    def test_occurrence_out_of_range(self, tmp_dir):
        from tools.file_patch import patch

        fp = self._txt(tmp_dir, "a = 1\nb = 1\n")
        r = patch(fp, "= 1", "= 9", occurrence=5)
        assert r["ok"] is False
        assert r["occurrence_count"] == 2
        assert len(r["matches"]) == 2
        assert r["matches"][0]["line"] == 1
        assert Path(fp).read_text(encoding="utf-8") == "a = 1\nb = 1\n"  # 未修改

    def test_default_first_proposal_mentions_occurrence(self, tmp_dir):
        from tools.file_patch import patch

        fp = self._txt(tmp_dir, "a = 1\nb = 1\n")
        r = patch(fp, "= 1", "= 9")
        assert r["ok"] is True
        assert r["replaced"] == 1
        assert "occurrence=N" in r["proposal"]
        assert Path(fp).read_text(encoding="utf-8") == "a = 9\nb = 1\n"

    def test_occurrence_and_replace_all_mutual_exclusive(self, tmp_dir):
        from tools.file_patch import patch

        fp = self._txt(tmp_dir, "a = 1\nb = 1\n")
        r = patch(fp, "= 1", "= 9", replace_all=True, occurrence=1)
        assert r["ok"] is False
        assert "不能同时" in r["error"]

    def test_preview_occurrence(self, tmp_dir):
        from tools.file_patch import preview

        fp = self._txt(tmp_dir, "a = 1\nb = 1\n")
        r = preview(fp, "= 1", "= 9", occurrence=2)
        assert r["ok"] is True
        assert "b = 9" in r["diff"]
        # 预览不修改文件
        assert Path(fp).read_text(encoding="utf-8") == "a = 1\nb = 1\n"
