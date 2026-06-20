"""Tests for _file_utils helpers."""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from tools import _file_utils as fu


class TestReadFile:
    def test_read_utf8(self, tmp_dir):
        p = Path(tmp_dir) / "utf8.txt"
        p.write_text("hello world\n中文\n", encoding="utf-8")
        assert fu.read_file(p).replace("\r\n", "\n") == "hello world\n中文\n"

    def test_read_gbk(self, tmp_dir):
        p = Path(tmp_dir) / "gbk.txt"
        content = "中文测试\n"
        p.write_bytes(content.encode("gb18030"))
        assert fu.read_file(p) == content

    def test_read_utf8_bom(self, tmp_dir):
        p = Path(tmp_dir) / "bom.txt"
        p.write_bytes(b"\xef\xbb\xbfhello\n")
        assert fu.read_file(p) == "hello\n"

    def test_read_explicit_encoding(self, tmp_dir):
        p = Path(tmp_dir) / "latin.txt"
        p.write_bytes("café\n".encode("latin-1"))
        assert fu.read_file(p, encoding="latin-1") == "café\n"

    def test_read_missing_file(self, tmp_dir):
        p = Path(tmp_dir) / "missing.txt"
        with pytest.raises(FileNotFoundError):
            fu.read_file(p)


class TestReadFileWithEncoding:
    def test_returns_detected_encoding(self, tmp_dir):
        p = Path(tmp_dir) / "detect.txt"
        p.write_bytes("中文\n".encode("gb18030"))
        text, enc = fu.read_file_with_encoding(p)
        assert text == "中文\n"
        assert enc.lower() in ("gb18030", "gbk")

    def test_max_bytes(self, tmp_dir):
        p = Path(tmp_dir) / "long.txt"
        p.write_text("1234567890" * 100, encoding="utf-8")
        text, enc = fu.read_file_with_encoding(p, max_bytes=20)
        assert len(text) == 20
        assert enc == "utf-8"


class TestDetectEncoding:
    def test_empty_file(self, tmp_dir):
        p = Path(tmp_dir) / "empty.txt"
        p.write_text("", encoding="utf-8")
        assert fu.detect_encoding(p) == "utf-8"

    def test_utf8(self, tmp_dir):
        p = Path(tmp_dir) / "u.txt"
        p.write_text("hello", encoding="utf-8")
        assert fu.detect_encoding(p) == "utf-8"

    def test_utf8_bom(self, tmp_dir):
        p = Path(tmp_dir) / "bom.txt"
        p.write_bytes(b"\xef\xbb\xbfno problem")
        assert fu.detect_encoding(p) == "utf-8-sig"

    def test_latin1_fallback(self, tmp_dir):
        p = Path(tmp_dir) / "binaryish.txt"
        p.write_bytes(bytes(range(1, 128)))
        assert fu.detect_encoding(p) == "latin-1"

    def test_missing_file(self, tmp_dir):
        p = Path(tmp_dir) / "missing.txt"
        with pytest.raises(FileNotFoundError):
            fu.detect_encoding(p)


class TestHumanSize:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (0, "0B"),
            (512, "512B"),
            (1024, "1KB"),
            (1536, "1.5KB"),
            (1024 * 1024, "1MB"),
            (1024 * 1024 * 1024, "1GB"),
            (1024 ** 4, "1TB"),
            (1024 ** 5, "1PB"),
        ],
    )
    def test_units(self, n, expected):
        assert fu.human_size(n) == expected


class TestFindClosestLine:
    def test_exact_match(self):
        content = "foo\nbar\nbaz\n"
        result = fu.find_closest_line(content, "bar\nnew", threshold=0.5)
        assert result == {"line": 2, "text": "bar"}

    def test_no_close_match_below_threshold(self):
        content = "foo\nbar\nbaz\n"
        result = fu.find_closest_line(content, "xyz")
        assert result is None

    def test_empty_content(self):
        assert fu.find_closest_line("", "foo") is None


class TestAlignWhitespace:
    def test_simple_alignment(self):
        content = "    print(a)\n    print(b)\n"
        old = "print(a)\nprint(b)\n"
        new = "echo(a)\necho(b)\n"
        aligned = fu.align_whitespace(content, old, new)
        assert aligned is not None
        aligned_old, aligned_new = aligned
        assert aligned_old.rstrip("\n") == "    print(a)\n    print(b)"
        assert aligned_new.rstrip("\n") == "    echo(a)\n    echo(b)"

    def test_no_match_returns_none(self):
        content = "    print(a)\n"
        old = "missing()\n"
        new = "other()\n"
        assert fu.align_whitespace(content, old, new) is None

    def test_empty_old_returns_none(self):
        assert fu.align_whitespace("x", "", "y") is None


class TestAtomicWriteText:
    def test_writes_content(self, tmp_dir):
        p = Path(tmp_dir) / "out.txt"
        fu.atomic_write_text(p, "hello\nworld\n")
        assert p.read_text(encoding="utf-8") == "hello\nworld\n"

    def test_overwrites_existing(self, tmp_dir):
        p = Path(tmp_dir) / "out.txt"
        p.write_text("old", encoding="utf-8")
        fu.atomic_write_text(p, "new", encoding="utf-8")
        assert p.read_text(encoding="utf-8") == "new"

    def test_custom_encoding(self, tmp_dir):
        p = Path(tmp_dir) / "out.txt"
        fu.atomic_write_text(p, "café", encoding="latin-1")
        assert p.read_bytes() == "café".encode("latin-1")


class TestBackupNameStem:
    def test_contains_name_and_hash(self, tmp_dir):
        p = Path(tmp_dir) / "sub" / "file.txt"
        p.parent.mkdir()
        p.write_text("x", encoding="utf-8")
        stem = fu.backup_name_stem(p)
        assert stem.startswith("file.txt.")
        assert len(stem) > len("file.txt.")

    def test_different_parents_different_hash(self, tmp_dir):
        p1 = Path(tmp_dir) / "a" / "file.txt"
        p2 = Path(tmp_dir) / "b" / "file.txt"
        p1.parent.mkdir()
        p2.parent.mkdir()
        assert fu.backup_name_stem(p1) != fu.backup_name_stem(p2)

    def test_same_parent_same_hash(self, tmp_dir):
        p1 = Path(tmp_dir) / "a" / "file.txt"
        p2 = Path(tmp_dir) / "a" / "file.txt"
        p1.parent.mkdir()
        assert fu.backup_name_stem(p1) == fu.backup_name_stem(p2)


class TestCheckPathAllowed:
    def test_allowed_path(self, tmp_dir):
        assert fu.check_path_allowed(tmp_dir) is None

    def test_dotdot_traversal(self):
        result = fu.check_path_allowed("/tmp/../etc/passwd")
        assert result is not None
        assert result["ok"] is False
        assert ".." in result["error"]

    def test_forbidden_system_prefix(self):
        import sys
        if sys.platform == "win32":
            # Windows: /etc 解析为 C:\etc，不在黑名单中
            result = fu.check_path_allowed("/etc/passwd")
            assert result is None
        else:
            result = fu.check_path_allowed("/etc/passwd")
            assert result is not None
            assert result["ok"] is False


class TestIsBinaryFile:
    def test_binary_extension(self, tmp_dir):
        p = Path(tmp_dir) / "x.png"
        p.write_text("text", encoding="utf-8")
        is_bin, reason = fu.is_binary_file(p)
        assert is_bin is True
        assert reason == "extension"

    def test_text_extension(self, tmp_dir):
        p = Path(tmp_dir) / "x.py"
        p.write_bytes(b"\x00" * 100)
        is_bin, reason = fu.is_binary_file(p)
        assert is_bin is False
        assert reason == "text_extension"

    def test_binary_content(self, tmp_dir):
        p = Path(tmp_dir) / "data"
        p.write_bytes(b"\x00" * 100)
        is_bin, reason = fu.is_binary_file(p)
        assert is_bin is True
        assert reason == "content"


class TestSymlinkGuard:
    def test_detects_cycle(self, tmp_dir):
        guard = fu.SymlinkGuard()
        assert guard.is_seen(tmp_dir) is False
        assert guard.is_seen(tmp_dir) is True

    def test_missing_path(self, tmp_dir):
        guard = fu.SymlinkGuard()
        assert guard.is_seen(str(Path(tmp_dir) / "missing")) is False
