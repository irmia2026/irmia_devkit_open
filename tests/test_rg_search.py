"""Tests for rg_search."""

import os
import tempfile
from pathlib import Path

import pytest

from tools import rg_search


@pytest.fixture
def tmp_project():
    d = tempfile.mkdtemp()
    root = Path(d) / "project"
    root.mkdir()
    (root / "a.py").write_text("def hello():\n    print('hello world')\n", encoding="utf-8")
    (root / "b.py").write_text("def hello_again():\n    pass\n", encoding="utf-8")
    (root / "readme.txt").write_text("hello text\n", encoding="utf-8")
    yield str(root)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestRgSearchHelpers:
    def test_parse_rg_output(self):
        stdout = "a.py:2:    print('hello world')\nb.py:1:def hello_again():"
        matches = rg_search._parse_rg_output(stdout)
        assert len(matches) == 2
        assert matches[0] == {"file": "a.py", "line": 2, "content": "    print('hello world')"}

    def test_parse_rg_with_context(self):
        stdout = "a.py-1-def hello():\na.py:2:    print('hello world')\na.py-3-\n--\nb.py-1-def hello_again():\nb.py:2:    pass"
        matches = rg_search._parse_rg_with_context(stdout)
        assert len(matches) == 2
        assert matches[0]["file"] == "a.py"
        assert matches[0]["line"] == 2
        assert len(matches[0]["context"]) == 2
        assert matches[1]["file"] == "b.py"
        assert matches[1]["line"] == 2
        assert len(matches[1]["context"]) == 1

    def test_has_nested_quantifiers(self):
        assert rg_search._has_nested_quantifiers("(a+)+") is True
        assert rg_search._has_nested_quantifiers("(a*)*") is True
        assert rg_search._has_nested_quantifiers("(a?)+") is True
        assert rg_search._has_nested_quantifiers("a+") is False

    def test_parse_rg_output_truncates_long_lines(self):
        """B7: rg 解析路径与 Python fallback 一致截断到 200 字符。"""
        long_line = "x" * 500
        stdout = f"a.py:1:{long_line}"
        matches = rg_search._parse_rg_output(stdout)
        assert len(matches) == 1
        assert len(matches[0]["content"]) == 200

    def test_parse_rg_with_context_truncates_long_lines(self):
        long_line = "y" * 500
        stdout = f"a.py-1-{long_line}\na.py:2:{long_line}\na.py-3-{long_line}"
        matches = rg_search._parse_rg_with_context(stdout)
        assert len(matches) == 1
        assert len(matches[0]["content"]) == 200
        for ctx in matches[0]["context"]:
            assert len(ctx["content"]) == 200


class TestContextLinesClamp:
    def test_context_lines_clamped_to_10(self, tmp_project, monkeypatch):
        """context_lines 超出 [0, 10] 时被 clamp，不报错。"""
        monkeypatch.setattr(rg_search, "_find_rg", lambda: None)
        r = rg_search.search("hello", path=tmp_project, context_lines=999)
        assert r["ok"] is True
        for m in r["matches"]:
            # clamp 到 10：上下文行号距离匹配行不超过 10
            for ctx in m.get("context", []):
                assert abs(ctx["line"] - m["line"]) <= 10

    def test_context_lines_negative_clamped_to_0(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", lambda: None)
        r = rg_search.search("hello", path=tmp_project, context_lines=-5)
        assert r["ok"] is True
        for m in r["matches"]:
            assert "context" not in m


class TestRgSearchPythonFallback:
    def _force_python(self):
        """强制走 Python fallback。"""
        return None

    def test_empty_pattern_rejected(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("", path=tmp_project)
        assert r["ok"] is False
        assert "empty_pattern" in r.get("error", "")

    def test_basic_search(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("hello", path=tmp_project)
        assert r["ok"] is True
        assert r["engine"] == "python"
        assert r["count"] >= 2

    def test_file_ext_filter(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("hello", path=tmp_project, file_exts="py")
        assert r["ok"] is True
        for m in r["matches"]:
            assert m["file"].endswith(".py")

    def test_case_sensitive(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("HELLO", path=tmp_project, case_sensitive=True)
        assert r["ok"] is True
        assert r["count"] == 0

    def test_whole_word(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search(r"hello_again", path=tmp_project, whole_word=True)
        assert r["ok"] is True
        assert any("hello_again" in m.get("content", "") for m in r["matches"])

    def test_list_files(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("hello", path=tmp_project, list_files=True)
        assert r["ok"] is True
        assert all("content" not in m for m in r["matches"])

    def test_max_results_truncation(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("hello", path=tmp_project, max_results=1)
        assert r["ok"] is True
        assert r["truncated"] is True
        assert len(r["matches"]) == 1

    def test_redos_pattern_too_long(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("a" * 2000, path=tmp_project)
        assert r["ok"] is False
        assert "pattern_too_long" in r.get("error", "")

    def test_redos_nested_quantifiers(self, tmp_project, monkeypatch):
        monkeypatch.setattr(rg_search, "_find_rg", self._force_python)
        r = rg_search.search("(a+)+", path=tmp_project)
        assert r["ok"] is False
        assert "nested_quantifiers" in r.get("error", "")


class TestRgSearchTopLevel:
    def test_invalid_path(self):
        r = rg_search.search("hello", path="/nonexistent/path/xyz")
        assert r["ok"] is False
        assert "目录不存在" in r["error"]
