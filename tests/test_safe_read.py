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
        assert result["encoding"] in ("gbk", "GB2312", "GB18030", "gb18030")
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


class TestFileReadNavigation:
    """safe_read 截断导航字段验证。"""

    def test_header_footer_in_range_mode(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 301)]), encoding="utf-8")

        result = safe_read.read(str(f), start_line=10, end_line=20)

        assert result["ok"] is True
        assert "header" in result
        assert "footer" in result
        assert "lines.txt" in result["header"]
        assert "lines 10-20 of 300" in result["footer"]

    def test_next_call_and_options_on_truncation(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 301)]), encoding="utf-8")

        result = safe_read.read(str(f), max_lines=50)

        assert result["ok"] is True
        assert result["truncated"] is True
        assert result["next_call"]["tool"] == "safe_read"
        assert result["next_call"]["args"]["start_line"] == 51
        assert "Continue reading from line 51" in result["options"]
        assert any("tail=50" in opt for opt in result["options"])

    def test_head_mode_navigation(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 101)]), encoding="utf-8")

        result = safe_read.read(str(f), head=5)

        assert result["ok"] is True
        assert result["header"]
        assert "lines 1-5 of 100" in result["footer"]
        assert "95 more below" in result["footer"]
        assert result["next_call"]["args"]["start_line"] == 6

    def test_tail_mode_navigation(self, tmp_dir):
        f = Path(tmp_dir) / "lines.txt"
        f.write_text("\n".join([f"line {i}" for i in range(1, 101)]), encoding="utf-8")

        result = safe_read.read(str(f), tail=5)

        assert result["ok"] is True
        assert result["header"]
        assert "lines 96-100 of 100" in result["footer"]
        assert "95 more above" in result["footer"]
        assert result["next_call"]["args"]["end_line"] == 95

    def test_no_footer_when_complete_file(self, tmp_dir):
        f = Path(tmp_dir) / "small.txt"
        f.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

        result = safe_read.read(str(f))

        assert result["ok"] is True
        assert result["header"]
        assert result["footer"] == ""
        assert result["next_call"] is None
        assert result["options"] == []

    def test_byte_limit_truncation_footer(self, tmp_dir):
        f = Path(tmp_dir) / "longline.txt"
        f.write_text("\n".join(f"line {i}: {'x' * 1000}" for i in range(200)), encoding="utf-8")

        result = safe_read.read(str(f), max_lines=200)

        assert result["ok"] is True
        assert result["truncated"] is True
        assert "truncated at 128KB" in result["footer"] or "128KB" in result["truncation_reason"]
        # 本例已读到文件末尾，字节截断是因为单行过长，没有更多行可供 next_call


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
    def test_read_directory_returns_guidance(self, tmp_dir):
        d = Path(tmp_dir) / "testdir"
        d.mkdir()
        (d / "file1.txt").write_text("content1")
        (d / "file2.py").write_text("content2")
        (d / "subdir").mkdir()

        result = safe_read.read(str(d))

        assert result["ok"] is False
        assert "proposal" in result
        assert "dir_list" in result["options"]
        assert "dir_tree" in result["options"]
        assert result["next_call"]["tool"] == "dir_list"
        assert Path(result["next_call"]["args"]["path"]).resolve() == d.resolve()

    def test_read_directory_with_metadata(self, tmp_dir):
        d = Path(tmp_dir) / "testdir"
        d.mkdir()

        result = safe_read.read(str(d), include_metadata=True)

        assert result["ok"] is False
        assert "metadata" in result["evidence"]
        assert result["evidence"]["metadata"]["is_dir"] is True


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

    def test_utf8_bom_detection(self, tmp_dir):
        f = Path(tmp_dir) / "bom.txt"
        f.write_bytes(b"\xef\xbb\xbfhello world\n")
        
        result = safe_read.read(str(f))
        
        assert result["ok"] is True
        assert result["encoding"] == "utf-8-sig"
        assert "hello world" in result["content"]

    def test_byte_limit_truncation(self, tmp_dir):
        """超长单行文件应被字节上限截断。"""
        f = Path(tmp_dir) / "longline.txt"
        # 每行 1000 个 'x'，200 行 = 200KB+，超过 MAX_RETURN_BYTES=128KB
        f.write_text("\n".join(f"line {i}: {"x" * 1000}" for i in range(200)), encoding="utf-8")
        
        result = safe_read.read(str(f), max_lines=200)
        
        assert result["ok"] is True
        assert result["truncated"] is True
        assert result["returned_lines"] < 200
        # 返回内容字节数应不超过上限（允许少量余量）
        assert len(result["content"].encode("utf-8")) <= 128 * 1024 + 1024


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


class TestFileReadProposal:
    """safe_read 错误路径应返回 proposal 协议字段。"""

    def test_nonexistent_returns_proposal(self, tmp_dir):
        f = Path(tmp_dir) / "missing.txt"
        result = safe_read.read(str(f))
        assert result["ok"] is False
        assert "proposal" in result
        assert "options" in result
        assert "next_call" in result

    def test_too_large_returns_proposal(self, tmp_dir):
        f = Path(tmp_dir) / "huge.txt"
        f.write_text("x" * (11 * 1024 * 1024), encoding="utf-8")
        result = safe_read.read(str(f))
        assert result["ok"] is False
        assert "proposal" in result
        assert "next_call" in result
        assert result["next_call"]["tool"] == "safe_read"
        assert result["next_call"]["args"]["mode"] == "skeleton"

    def test_directory_returns_proposal(self, tmp_dir):
        d = Path(tmp_dir) / "testdir"
        d.mkdir()
        result = safe_read.read(str(d), mode="text")
        assert result["ok"] is False
        assert "proposal" in result
        assert result["next_call"]["tool"] == "dir_list"
        assert Path(result["next_call"]["args"]["path"]).resolve() == d.resolve()

    def test_forbidden_path_returns_proposal(self):
        result = safe_read.read("C:/Windows/System32/kernel32.dll")
        assert result["ok"] is False
        assert "proposal" in result
        assert "options" in result

    def test_tail_performance_on_large_file(self, tmp_dir):
        """tail 模式不应扫描整个大文件。"""
        f = Path(tmp_dir) / "big.log"
        f.write_text("\n".join(f"line {i}" for i in range(1, 10001)), encoding="utf-8")
        result = safe_read.read(str(f), tail=3)
        assert result["ok"] is True
        assert result["returned_lines"] == 3
        assert "9998" in result["content"]
        assert "10000" in result["content"]


class TestFileReadValidation:
    """参数校验。"""

    def test_path_none_rejected(self, tmp_dir):
        result = safe_read.read(None)
        assert result["ok"] is False
        assert "path" in result["error"].lower()

    def test_tail_negative_rejected(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("x")
        result = safe_read.read(str(f), tail=-1)
        assert result["ok"] is False
        assert "tail" in result["error"].lower()

    def test_head_negative_rejected(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("x")
        result = safe_read.read(str(f), head=-1)
        assert result["ok"] is False
        assert "head" in result["error"].lower()

    def test_invalid_encoding_rejected(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("x")
        result = safe_read.read(str(f), encoding="not-a-codec")
        assert result["ok"] is False
        assert "编码" in result["error"] or "encoding" in result["error"].lower()

    def test_invalid_mode_rejected(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("x")
        result = safe_read.read(str(f), mode="foobar")
        assert result["ok"] is False
        assert "mode" in result["error"].lower()

    def test_start_line_beyond_eof(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("line1\nline2\nline3\n")
        result = safe_read.read(str(f), start_line=100)
        assert result["ok"] is False
        assert "超过" in result["error"]
        assert result["next_call"]["args"]["tail"] == 3

    def test_invalid_line_range(self, tmp_dir):
        f = Path(tmp_dir) / "a.txt"
        f.write_text("line1\nline2\nline3\n")
        result = safe_read.read(str(f), start_line=10, end_line=5)
        assert result["ok"] is False
        assert "end_line" in result["error"]


class TestFileReadHeadPerformance:
    """head 模式不应扫描整个大文件。"""

    def test_head_stops_early_on_large_file(self, tmp_dir):
        f = Path(tmp_dir) / "big.log"
        # 超过 1MB 的大文件，多行
        line = "x" * 100
        # 约 2MB 内容
        f.write_text("\n".join([line] * 21000), encoding="utf-8")
        result = safe_read.read(str(f), head=5)
        assert result["ok"] is True
        assert result["returned_lines"] == 5
        assert result["has_more"] is True
        # 大文件行数估算应接近真实值（21000），而不是 2 之类的离谱数字
        assert result["total_lines"] > 10000


class TestLargeFilePaginationNextCall:
    """回归 Bug：大文件 range 模式 next_call 不应消失。"""

    def test_default_range_on_large_file_has_next_call(self, tmp_dir):
        """大文件从开头用 max_lines 读取时 next_call 不能为 None。"""
        f = Path(tmp_dir) / "big.txt"
        # ~1.6MB, ~10000 lines
        f.write_text("\n".join(f"line {i:05d} " + "x" * 130 for i in range(10000)), encoding="utf-8")
        assert f.stat().st_size > 1024 * 1024  # >1MB threshold

        result = safe_read.read(str(f), max_lines=200)
        assert result["ok"] is True
        assert result["has_more"] is True
        assert result["next_call"] is not None, \
            "大文件截断时 next_call 不应为 None（否则 LLM 无法继续读取）"
        assert result["next_call"]["tool"] == "safe_read"
        assert result["next_call"]["args"]["start_line"] == 201

    def test_mid_file_range_on_large_file_has_next_call(self, tmp_dir):
        """大文件从中间用 max_lines 读取时 next_call 不能为 None。"""
        f = Path(tmp_dir) / "big.txt"
        f.write_text("\n".join(f"line {i:05d} " + "x" * 130 for i in range(10000)), encoding="utf-8")
        assert f.stat().st_size > 1024 * 1024

        result = safe_read.read(str(f), start_line=5000, max_lines=50)
        assert result["ok"] is True
        assert result["has_more"] is True
        assert result["next_call"] is not None, \
            "大文件中间截断时 next_call 不应为 None"
        assert result["next_call"]["args"]["start_line"] == 5050


class TestFindClosestLineIndent:
    """find_closest_line 应保留缩进提示。"""

    def test_closest_line_keeps_indent(self, tmp_dir):
        from tools._file_utils import find_closest_line

        content = "    def foo():\n        pass\n"
        closest = find_closest_line(content, "def foo")
        assert closest["text"].startswith("    ")


@pytest.mark.slow
class TestPerf:
    """性能回归测试（默认跳过，用 -m slow 运行）。"""

    def test_large_file_head_fast(self, tmp_dir) -> None:
        """~9MB 文件的读取应在 1s 内完成。"""
        import time
        f = Path(tmp_dir) / "large.log"
        # Write ~7MB of text
        with open(f, "w", encoding="utf-8") as fh:
            for i in range(200_000):
                fh.write(f"line {i}\n")
        t0 = time.time()
        result = safe_read.read(str(f), mode="auto", max_lines=10)
        elapsed = time.time() - t0
        assert result["ok"] is True, f"result={result.get('error')}"
        assert elapsed < 1.0, f"read took {elapsed:.2f}s"
