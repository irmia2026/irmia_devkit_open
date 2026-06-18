"""Tests for file_read enhanced tool."""

import os
import tempfile
from pathlib import Path

import pytest

from tools import safe_read


class TestFileReadBasic:
    def test_read_utf8_file(self, tmp_dir):
        f = Path(tmp_dir) / "utf8.txt"
        f.write_text("hello world\nline 2\nline 3\n", encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["encoding"] in ("utf-8", "ascii")  # ascii 是 utf-8 的子集
        assert result["content"] == "hello world\nline 2\nline 3"
        assert result["total_lines"] == 3
        assert result["has_more"] is False
    
    def test_read_gbk_file(self, tmp_dir):
        f = Path(tmp_dir) / "gbk.txt"
        f.write_text("中文内容\n第二行\n", encoding="gbk")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["encoding"] in ("gbk", "GB2312", "GB18030")
        assert "中文内容" in result["content"]
    
    def test_read_nonexistent_file(self, tmp_dir):
        f = Path(tmp_dir) / "nonexistent.txt"
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is False
        assert "not found" in result["error"].lower() or "Path not found" in result["error"]


class TestFileReadPagination:
    def test_start_line_end_line(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 101)]), encoding="utf-8")
        
        result = safe_read.read(str(f), start_line=10, end_line=20)
        
        assert result["ok"] is True
        assert result["start_line"] == 10
        assert result["end_line"] == 20
        assert result["returned_lines"] == 11
        assert result["content"].startswith("line 10")
        assert result["content"].endswith("line 20")
    
    def test_head_mode(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 101)]), encoding="utf-8")
        
        result = safe_read.read(str(f), head=5)
        
        assert result["ok"] is True
        assert result["start_line"] == 1
        assert result["end_line"] == 5
        assert result["returned_lines"] == 5
        assert result["has_more"] is True
    
    def test_tail_mode(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 101)]), encoding="utf-8")
        
        result = safe_read.read(str(f), tail=5)
        
        assert result["ok"] is True
        assert result["start_line"] == 96
        assert result["end_line"] == 100
        assert result["returned_lines"] == 5
        assert result["has_more"] is True
        assert "line 100" in result["content"]
    
    def test_max_lines_truncation(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 301)]), encoding="utf-8")
        
        result = safe_read.read(str(f), max_lines=50)
        
        assert result["ok"] is True
        assert result["returned_lines"] == 50
        assert result["has_more"] is True or result["truncated"] is True  # 大文件可能触发截断
        assert result["truncated"] is True


class TestFileReadBinary:
    def test_binary_file_detection(self, tmp_dir):
        f = Path(tmp_dir) / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["mode"] == "binary"
        assert result["is_binary"] is True
        assert "hex_preview" in result
        assert result["content"] == ""
    
    def test_hex_mode(self, tmp_dir):
        f = Path(tmp_dir) / "test.bin"
        f.write_bytes(bytes(range(256)))
        
        result = safe_read.read(str(f), mode="hex")
        
        assert result["ok"] is True
        assert result["mode"] == "hex"
        assert "hex_content" in result
        assert "00 01 02 03" in result["hex_content"]
    
    def test_png_file(self, tmp_dir):
        f = Path(tmp_dir) / "test.png"
        # PNG 文件头
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1000)
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["mode"] == "binary"
        assert ".PNG" in result["hex_preview"] or "8950" in result["hex_preview"]


class TestFileReadDirectory:
    def test_read_directory(self, tmp_dir):
        d = Path(tmp_dir) / "testdir"
        d.mkdir()
        (d / "file1.txt").write_text("content1")
        (d / "file2.py").write_text("content2")
        (d / "subdir").mkdir()
        
        result = safe_read.read(str(d))
        
        assert result["ok"] is True
        assert result["mode"] == "directory"
        assert result["total_entries"] == 3
        assert len(result["entries"]) == 3
        
        names = [e["name"] for e in result["entries"]]
        assert "file1.txt" in names
        assert "file2.py" in names
        assert "subdir" in names
    
    def test_read_directory_recursive(self, tmp_dir):
        d = Path(tmp_dir) / "testdir"
        d.mkdir()
        (d / "file1.txt").write_text("content1")
        sub = d / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested")
        
        result = safe_read.read(str(d), recursive=True)
        
        assert result["ok"] is True
        assert result["mode"] == "directory"
        
        # 找到 subdir 条目
        subdir_entry = next((e for e in result["entries"] if e["name"] == "subdir"), None)
        assert subdir_entry is not None
        assert "children" in subdir_entry
        assert len(subdir_entry["children"]) == 1
        assert subdir_entry["children"][0]["name"] == "nested.txt"


class TestFileReadSkeleton:
    def test_python_skeleton(self, tmp_dir):
        f = Path(tmp_dir) / "code.py"
        f.write_text("""
import os
from pathlib import Path

class MyClass:
    def method(self):
        pass

def standalone():
    pass
""", encoding="utf-8")
        
        result = safe_read.read(str(f), mode="skeleton")
        
        assert result["ok"] is True
        assert result["mode"] == "skeleton"
        assert "skeleton" in result
        
        skeleton = result["skeleton"]
        assert skeleton["language"] == "python"
        assert len(skeleton["imports"]) > 0
        assert len(skeleton["classes"]) > 0
        assert len(skeleton["functions"]) > 0
    
    def test_go_skeleton(self, tmp_dir):
        f = Path(tmp_dir) / "code.go"
        f.write_text("""
package main

import "fmt"

func main() {
    fmt.Println("hello")
}

func helper() {
}
""", encoding="utf-8")
        
        result = safe_read.read(str(f), mode="skeleton")
        
        assert result["ok"] is True
        assert result["skeleton"]["language"] == "go"
        assert len(result["skeleton"]["functions"]) == 2


class TestFileReadMetadata:
    def test_metadata_fields(self, tmp_dir):
        f = Path(tmp_dir) / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert "metadata" in result
        assert "size" in result["metadata"]
        assert "mtime" in result["metadata"]
        assert "permissions" in result["metadata"]
        assert result["metadata"]["size"] == 11
    
    def test_human_size(self, tmp_dir):
        f = Path(tmp_dir) / "test.txt"
        f.write_text("x" * 2048, encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["human_size"] in ("2.0KB", "2KB")
        assert result["metadata"]["human_size"] in ("2.0KB", "2KB")


class TestFileReadLargeFile:
    def test_large_file_truncation(self, tmp_dir):
        f = Path(tmp_dir) / "large.txt"
        # 创建 150KB 文件（超过 LARGE_FILE_THRESHOLD=100KB）
        f.write_text("x" * (150 * 1024), encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["truncated"] is True
        assert "truncation_reason" in result
        assert "large" in result["truncation_reason"].lower() or "100KB" in result["truncation_reason"]
    
    def test_too_large_file_rejected(self, tmp_dir):
        f = Path(tmp_dir) / "huge.txt"
        # 创建 11MB 文件（超过 MAX_FILE_SIZE=10MB）
        f.write_text("x" * (11 * 1024 * 1024), encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is False
        assert "too large" in result["error"].lower() or "10MB" in result["error"]


class TestFileReadEncoding:
    def test_latin1_fallback(self, tmp_dir):
        f = Path(tmp_dir) / "latin.txt"
        # 写入 Latin-1 编码的字节（ Café 的 é 在 Latin-1 中是 0xe9 ）
        f.write_bytes(b"Caf\xe9\n")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        # 应该被检测为 latin-1 或成功解码
        assert "Caf" in result["content"]
    
    def test_explicit_encoding(self, tmp_dir):
        f = Path(tmp_dir) / "test.txt"
        f.write_text("hello", encoding="utf-8")
        
        result = safe_read.read(str(f), encoding="utf-8")
        
        assert result["ok"] is True
        assert result["encoding"] == "utf-8"


class TestFileReadEdgeCases:
    def test_empty_file(self, tmp_dir):
        f = Path(tmp_dir) / "empty.txt"
        f.write_text("", encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["content"] == ""
        assert result["total_lines"] == 0
    
    def test_single_line_file(self, tmp_dir):
        f = Path(tmp_dir) / "single.txt"
        f.write_text("only one line", encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["total_lines"] == 1
        assert result["has_more"] is False
    
    def test_unicode_file(self, tmp_dir):
        f = Path(tmp_dir) / "unicode.txt"
        f.write_text("🎉 emoji test\n日本語テスト\n한국어 테스트\n", encoding="utf-8")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert "🎉" in result["content"]
        assert "日本語" in result["content"]
        assert "한국어" in result["content"]
