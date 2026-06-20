"""Tests for safe_write — new file / overwrite tool."""

from pathlib import Path
from tools import config as _cfg
from tools.safe_write import write


class TestSafeWrite:
    # ══════════════════════════════════════════════════════════════════
    # happy path
    # ══════════════════════════════════════════════════════════════════
    def test_create_new_file(self, tmp_dir):
        """新建文件应成功"""
        fp = Path(tmp_dir) / "new.txt"
        result = write(str(fp), "hello world")
        assert result["ok"] is True
        assert result["created"] is True
        assert fp.read_text() == "hello world"

    def test_create_nested_dir(self, tmp_dir):
        """父目录不存在时自动创建"""
        fp = Path(tmp_dir) / "a" / "b" / "c.txt"
        result = write(str(fp), "nested")
        assert result["ok"] is True
        assert result["created"] is True
        assert fp.read_text() == "nested"
        expected_a = str((Path(tmp_dir) / "a").resolve())
        expected_ab = str((Path(tmp_dir) / "a" / "b").resolve())
        assert result.get("created_dirs") == [expected_a, expected_ab]

    def test_existing_no_overwrite(self, tmp_dir):
        """已存在文件且 overwrite=False 应返回 proposal"""
        fp = Path(tmp_dir) / "exist.txt"
        fp.write_text("original")
        result = write(str(fp), "new content")
        assert result["ok"] is False
        assert "文件已存在" in result.get("error", "")
        assert "proposal" in result
        assert fp.read_text() == "original"  # 未修改

    def test_existing_overwrite(self, tmp_dir):
        """overwrite=True 应覆盖并保留备份"""
        _cfg.set_config({"backup_dir": str(Path(tmp_dir) / "backups")})
        fp = Path(tmp_dir) / "overwrite.txt"
        fp.write_text("original content")
        result = write(str(fp), "new content", overwrite=True)
        assert result["ok"] is True
        assert result["overwritten"] is True
        assert fp.read_text() == "new content"
        assert "backup" in result
        # 备份文件应存在
        backup_path = Path(result["backup"])
        assert backup_path.exists()
        assert backup_path.read_text() == "original content"

    # ══════════════════════════════════════════════════════════════════
    # 安全边界
    # ══════════════════════════════════════════════════════════════════
    def test_path_traversal_blocked(self, tmp_dir):
        """路径穿越应被拒绝"""
        result = write(str(Path(tmp_dir) / ".." / "escape.txt"), "test")
        assert result["ok"] is False
        assert "穿越" in result.get("error", "")

    def test_none_content(self, tmp_dir):
        """content=None 应报错"""
        result = write(str(Path(tmp_dir) / "none.txt"), None)
        assert result["ok"] is False

    def test_system_dir_blocked(self, tmp_dir):
        """系统目录写入应被拒绝"""
        result = write("C:/Windows/System32/test.txt", "evil")
        assert result["ok"] is False
        assert "禁止" in result.get("error", "")
        assert "proposal" in result

    # ══════════════════════════════════════════════════════════════════
    # 语法检查分支
    # ══════════════════════════════════════════════════════════════════
    def test_new_code_file_syntax_error_keeps_file(self, tmp_dir):
        """新建代码文件语法错误不删除，保留文件 + 返回 proposal"""
        fp = Path(tmp_dir) / "bad.py"
        result = write(str(fp), "def foo(\n  invalid syntax here\n")
        assert result["ok"] is True  # 文件已创建
        assert result["created"] is True
        assert fp.exists()  # 文件保留（无旧版可回滚）
        assert result["syntax_ok"] is False
        assert "proposal" in result
        assert "options" in result

    def test_overwrite_syntax_error_rolls_back(self, tmp_dir):
        """overwrite=True 时语法错误应自动回滚到覆盖前内容"""
        _cfg.set_config({"backup_dir": str(Path(tmp_dir) / "backups")})
        fp = Path(tmp_dir) / "rollback.py"
        fp.write_text("x = 1\n")
        result = write(str(fp), "def bad(\n", overwrite=True)
        assert result["ok"] is False
        assert result["rolled_back"] is True
        assert fp.read_text() == "x = 1\n"  # 已回滚

    def test_overwrite_non_code_skips_syntax(self, tmp_dir):
        """overwrite=True 非代码文件跳过语法检查"""
        _cfg.set_config({"backup_dir": str(Path(tmp_dir) / "backups")})
        fp = Path(tmp_dir) / "config.yaml"
        fp.write_text("key: old\n")
        result = write(str(fp), "key: new\n", overwrite=True)
        assert result["ok"] is True
        assert result.get("syntax_ok") is None  # 非代码文件
        assert fp.read_text() == "key: new\n"

    def test_content_too_large(self, tmp_dir):
        """content 超过 20MB 应拒绝"""
        fp = Path(tmp_dir) / "huge.txt"
        result = write(str(fp), "x" * (21 * 1024 * 1024))
        assert result["ok"] is False
        assert "20MB" in result.get("error", "")

    def test_content_type_invalid(self, tmp_dir):
        """content 非 str 应友好报错"""
        fp = Path(tmp_dir) / "bytes.txt"
        result = write(str(fp), b"bytes content")
        assert result["ok"] is False
        assert "str" in result.get("error", "")

    def test_preserves_crlf(self, tmp_dir):
        """overwrite=True 时应保留已有 CRLF（读取阶段不再转换）。"""
        fp = Path(tmp_dir) / "crlf.txt"
        fp.write_bytes(b"line1\r\nline2\r\n")
        result = write(str(fp), "line1\r\nline2\r\nmodified\r\n", overwrite=True)
        assert result["ok"] is True
        assert fp.read_bytes() == b"line1\r\nline2\r\nmodified\r\n"

    def test_dotdot_in_filename_allowed(self, tmp_dir):
        """文件名中合法包含 .. 子串不应被拒绝。"""
        fp = Path(tmp_dir) / "foo..bar.txt"
        result = write(str(fp), "ok")
        assert result["ok"] is True
        assert fp.exists()

    def test_backup_includes_dir_hash(self, tmp_dir):
        """相同文件名不同目录的备份不应混淆。"""
        from tools.config import set_config
        from tools.safe_edit import edit, rollback

        set_config({"backup_dir": str(Path(tmp_dir) / "backups")})
        d1 = Path(tmp_dir) / "dir1"
        d2 = Path(tmp_dir) / "dir2"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "same.py"
        f2 = d2 / "same.py"
        f1.write_text("x = 1\n")
        f2.write_text("y = 2\n")

        result1 = edit(str(f1), "x = 1", "x = 10")
        assert result1["ok"] is True
        result2 = edit(str(f2), "y = 2", "y = 20")
        assert result2["ok"] is True

        # rollback f2 不应回滚到 f1 的备份
        rb = rollback(str(f2))
        assert rb["ok"] is True
        assert f2.read_text() == "y = 2\n"
        assert f1.read_text() == "x = 10\n"
