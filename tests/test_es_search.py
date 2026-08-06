"""Tests for es_search — file search engine.

Tests the Python fallback search path (no es.exe dependency)."""

import os
from pathlib import Path

from tools.es_search import search


class TestEsSearch:
    def test_basic_search_in_project(self):
        """Search for a known file in this project directory."""
        r = search(query="*.py", path=".", max_results=5)
        assert r["ok"] is True
        assert r["count"] >= 1
        assert len(r["items"]) >= 1
        first = r["items"][0]
        assert "name" in first
        assert "path" in first
        assert "size" in first

    def test_non_existent_pattern(self):
        r = search(query="zzz_nonexistent_file_xyz_123", path=".", max_results=5)
        assert r["ok"] is True
        assert r["count"] == 0

    def test_search_with_ext_filter(self):
        r = search(query="test", path=".", ext="py", max_results=5)
        assert r["ok"] is True
        # Should find .py files, may or may not match query
        assert isinstance(r["count"], int)
        for item in r["items"]:
            assert item["name"].endswith(".py") or item["name"].endswith("test")

    def test_search_file_type(self):
        r = search(query="test_*", path=".", file_type="file", max_results=5)
        assert r["ok"] is True
        assert isinstance(r["count"], int)

    def test_max_results_zero(self):
        # max_results=0 behavior varies by search engine; just verify it doesn't crash
        r = search(query="*.py", path=".", max_results=0)
        assert "ok" in r

    def test_invalid_path(self):
        r = search(query="test", path="/nonexistent_path_xyz")
        assert r["ok"] is True  # Returns empty results, not error
        assert r["count"] == 0

    def test_search_by_folder(self):
        r = search(query="tools", path=".", file_type="folder", max_results=5)
        assert r["ok"] is True
        # Should find the 'tools' directory
        assert isinstance(r["count"], int)

    def test_posix_fallback_note_on_regex(self):
        """POSIX fallback 下传 regex=True 应在 note 中说明不支持。"""
        r = search(query="test", path=".", regex=True, max_results=5)
        assert r["ok"] is True
        assert "POSIX fallback 不支持 regex/whole_word/sort_by" in r.get("note", "")

    def test_posix_fallback_note_on_sort_by(self):
        r = search(query="test", path=".", sort_by="size", max_results=5)
        assert r["ok"] is True
        assert "POSIX fallback 不支持 regex/whole_word/sort_by" in r.get("note", "")

    def test_posix_fallback_windows_default_home(self):
        """Windows 且未传 path 时默认搜索用户主目录并在 note 中说明。"""
        r = search(query="test", max_results=5)
        assert r["ok"] is True
        if os.name == "nt":
            assert "用户主目录" in r.get("note", "")
