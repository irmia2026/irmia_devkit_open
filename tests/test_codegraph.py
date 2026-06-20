"""Tests for codegraph — semantic indexing and query engine."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tools.codegraph import (
    CodeGraph,
    _tokenize_query,
    _extract_python,
    _resolve_references,
    _bfs_path,
)


@pytest.fixture
def tmp_project():
    """临时项目目录：含多个 .py 文件。"""
    d = tempfile.mkdtemp()
    root = Path(d) / "project"
    root.mkdir()
    (root / "main.py").write_text("""
from .utils import helper

def main():
    x = helper(42)
    return x
""", encoding="utf-8")
    (root / "utils.py").write_text("""
def helper(n: int) -> int:
    return n + 1

class Calculator:
    def add(self, a, b):
        return a + b

    def sub(self, a, b):
        return a - b
""", encoding="utf-8")
    (root / "empty.py").write_text("# just a comment\n", encoding="utf-8")
    yield str(root)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_db(tmp_project):
    """建好索引的临时数据库。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cg = CodeGraph(path)
    cg.index(tmp_project)
    yield path
    cg.close()
    for f in [path, path + "-shm", path + "-wal"]:
        try:
            os.unlink(f)
        except OSError:
            pass


# ── _tokenize_query ───────────────────────────────────


class TestTokenizeQuery:
    def test_simple_word(self):
        tokens = _tokenize_query("safe_edit")
        assert "safe_edit" in tokens
        assert "safe" in tokens
        assert "edit" in tokens

    def test_camelcase(self):
        tokens = _tokenize_query("SafeEditTool")
        assert "Safe" in tokens or "safe" in tokens

    def test_chinese_2gram(self):
        tokens = _tokenize_query("工具注册")
        assert "工具" in tokens
        assert "注册" in tokens

    def test_empty(self):
        tokens = _tokenize_query("")
        assert tokens == []

    def test_short_tokens(self):
        tokens = _tokenize_query("a b")
        assert "a" not in tokens
        assert "b" not in tokens


# ── _extract_python ───────────────────────────────────


class TestExtractPython:
    def test_finds_function(self, tmp_project):
        symbols, edges = _extract_python(os.path.join(tmp_project, "utils.py"))
        names = {s["name"] for s in symbols}
        assert "helper" in names

    def test_finds_class_methods(self, tmp_project):
        symbols, edges = _extract_python(os.path.join(tmp_project, "utils.py"))
        names = {s["name"] for s in symbols}
        assert "Calculator" in names or any("Calculator" in n for n in names)

    def test_empty_file(self, tmp_project):
        symbols, edges = _extract_python(os.path.join(tmp_project, "empty.py"))
        assert isinstance(symbols, list)

    def test_calls_edge(self, tmp_project):
        symbols, edges = _extract_python(os.path.join(tmp_project, "main.py"))
        call_targets = {e["to"] for e in edges if e["kind"] == "calls"}
        assert "helper" in call_targets

    def test_imports_edge(self, tmp_project):
        symbols, edges = _extract_python(os.path.join(tmp_project, "main.py"))
        imports = [e for e in edges if e["kind"] == "imports"]
        assert len(imports) >= 1


# ── CodeGraph index ───────────────────────────────────


class TestCodeGraphIndex:
    def test_index_success(self, tmp_project):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            r = cg.index(tmp_project)
            assert r["ok"] is True
            assert r["stats"]["files"] >= 2  # main.py + utils.py + models.py (minus test_ filter)
            assert r["stats"]["symbols"] > 0
            assert r["stats"]["edges"] > 0
        finally:
            cg.close()
            for f in [path, path + "-shm", path + "-wal"]:
                try: os.unlink(f)
                except OSError: pass

    def test_index_invalid_dir(self, tmp_project):
        cg = CodeGraph(os.path.join(tmp_project, "nonexistent.db"))
        r = cg.index("/nonexistent/path")
        assert r["ok"] is False
        cg.close()

    def test_incremental_second_run(self, tmp_project):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            cg.index(tmp_project)
            r2 = cg.index(tmp_project, incremental=True)
            assert r2["ok"] is True
        finally:
            cg.close()
            for f in [path, path + "-shm", path + "-wal"]:
                try: os.unlink(f)
                except OSError: pass


# ── CodeGraph explore ─────────────────────────────────


class TestCodeGraphExplore:
    def test_symbol_search_found(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.explore("helper")
            assert r["ok"] is True
            assert r["found"] is True
            assert len(r["symbols"]) >= 1
        finally:
            cg.close()

    def test_symbol_search_not_found(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.explore("nonexistent_xyz_123")
            assert r["found"] is False
        finally:
            cg.close()

    def test_trace_closed(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.explore("从 main 到 helper")
            assert r["ok"] is True
        finally:
            cg.close()

    def test_no_index(self, tmp_project):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            r = cg.explore("helper")
            assert r["ok"] is False
            assert r["error"] == "no_index"
        finally:
            cg.close()
            os.unlink(path)


# ── CodeGraph explore top-source truncation ───────────


class TestCodeGraphTopSource:
    def test_top_symbol_full_source_when_short(self):
        d = tempfile.mkdtemp()
        root = Path(d) / "proj"
        root.mkdir()
        (root / "small.py").write_text("def small():\n    a = 1\n    b = 2\n    c = 3\n    return a + b + c\n")
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(db)
        try:
            cg.index(str(root))
            r = cg.explore("small")
            assert r["found"] is True
            sym = r["symbols"][0]
            assert sym["name"] == "small"
            assert sym["source_truncated"] is False
            assert sym["total_lines"] == 5
            assert "next_call" not in sym
        finally:
            cg.close()
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            for f in [db, db + "-shm", db + "-wal"]:
                try: os.unlink(f)
                except OSError: pass

    def test_top_symbol_truncated_with_code_pack_hint(self):
        d = tempfile.mkdtemp()
        root = Path(d) / "proj"
        root.mkdir()
        lines = ["def big():"] + [f"    x{i} = {i}" for i in range(120)] + ["    return x0"]
        (root / "big.py").write_text("\n".join(lines))
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(db)
        try:
            cg.index(str(root))
            r = cg.explore("big")
            assert r["found"] is True
            sym = r["symbols"][0]
            assert sym["name"] == "big"
            assert sym["source_truncated"] is True
            assert sym["total_lines"] == 122
            returned_lines = len(sym["source"].splitlines())
            assert returned_lines <= 65  # head 40 + tail 20 + 2 marker + 1
            assert sym.get("next_call") == {"tool": "code_pack", "args": {"target": "big"}}
            assert "code_pack('big')" in sym.get("options", [])
            assert "code_pack" in sym.get("footer", "")
        finally:
            cg.close()
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            for f in [db, db + "-shm", db + "-wal"]:
                try: os.unlink(f)
                except OSError: pass


# ── CodeGraph pack ────────────────────────────────────


class TestCodeGraphPack:
    def test_pack_found(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_pack("helper", depth=1)
            assert r["ok"] is True
            assert r["target"]["name"] is not None
            assert r["target"]["kind"] == "function"
        finally:
            cg.close()

    def test_pack_not_found(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_pack("nonexistent_xyz")
            assert r["ok"] is False
        finally:
            cg.close()

    def test_pack_caller_mode(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_pack("helper", depth=1, mode="callers")
            assert r["ok"] is True
            assert r["target"]["name"] is not None
        finally:
            cg.close()


# ── CodeGraph diff_impact ─────────────────────────────


class TestCodeGraphDiffImpact:
    def test_impact_on_changed_file(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_diff_impact(["main.py"], max_depth=1)
            assert r["ok"] is True
            assert isinstance(r["affected_symbols"], list)
            assert isinstance(r["affected_files"], list)
        finally:
            cg.close()

    def test_impact_empty_file_list(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_diff_impact([], max_depth=1)
            assert r["ok"] is True
        finally:
            cg.close()


# ── CodeGraph status ──────────────────────────────────


class TestCodeGraphStatus:
    def test_status_after_index(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.code_status()
            assert r["ok"] is True
            assert r["files_indexed"] > 0
            assert r["symbols_total"] > 0
            assert r["edges_total"] > 0
        finally:
            cg.close()


# ── CodeGraph close / reopen ──────────────────────────


class TestCodeGraphClose:
    def test_close_and_reopen(self, test_db):
        cg = CodeGraph(test_db)
        r1 = cg.explore("helper")
        cg.close()
        cg2 = CodeGraph(test_db)
        try:
            r2 = cg2.explore("helper")
            assert r2["found"] is True
        finally:
            cg2.close()


# ── _resolve_references ───────────────────────────────


class TestResolveReferences:
    def test_resolves_unique_short_name(self, tmp_project):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            cg.index(tmp_project)
            conn = sqlite3.connect(path)
            resolved = conn.execute(
                "SELECT COUNT(*) FROM edges WHERE kind='calls' AND resolved=1"
            ).fetchone()[0]
            assert resolved > 0
            conn.close()
        finally:
            cg.close()
            for f in [path, path + "-shm", path + "-wal"]:
                try: os.unlink(f)
                except OSError: pass


# ── _bfs_path ─────────────────────────────────────────


class TestBfsPath:
    def test_direct_call_path(self, test_db):
        cg = CodeGraph(test_db)
        conn = cg._conn_get()
        try:
            path = _bfs_path(conn, "main", "helper", max_depth=3)
            assert path is not None
            assert "helper" in path
        finally:
            cg.close()

    def test_no_path(self, test_db):
        cg = CodeGraph(test_db)
        conn = cg._conn_get()
        try:
            path = _bfs_path(conn, "helper", "nonexistent", max_depth=3)
            assert path is None
        finally:
            cg.close()
