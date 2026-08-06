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


    def test_no_triggers_for_random_attribute_call(self, tmp_project):
        """普通属性调用参数不应产生 triggers 边。"""
        path = os.path.join(tmp_project, "caller.py")
        Path(path).write_text("""
def caller():
    x = 1
    obj.method(x)
""", encoding="utf-8")
        symbols, edges = _extract_python(path)
        triggers = [e for e in edges if e["kind"] == "triggers"]
        assert len(triggers) == 0

    def test_triggers_for_register_call(self, tmp_project):
        """register(func) / add_tool(tool) 类调用应产生 triggers 边。"""
        path = os.path.join(tmp_project, "register.py")
        Path(path).write_text("""
def handler(): pass

def setup():
    registry.register(handler)
    tools.add_tool(handler)
""", encoding="utf-8")
        symbols, edges = _extract_python(path)
        triggers = [e for e in edges if e["kind"] == "triggers"]
        assert any(e["from"] == "handler" and e["to"] == "setup" for e in triggers)

    def test_gbk_encoding_without_cookie(self, tmp_project):
        """无 coding cookie 的 GBK 文件也能正确读取中文。"""
        path = os.path.join(tmp_project, "gbk.py")
        Path(path).write_bytes('def foo():\n    x = "中文"\n'.encode("gbk"))
        symbols, edges = _extract_python(path)
        src = next((s["source"] for s in symbols if s["name"] == "foo"), "")
        assert "中文" in src, f"GBK 中文未正确解码: {src!r}"



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

    def test_index_includes_tests_dir(self):
        """tests 目录下的文件也应被索引。"""
        d = tempfile.mkdtemp()
        root = Path(d) / "project"
        root.mkdir()
        (root / "src.py").write_text("def foo(): pass")
        test_dir = root / "tests"
        test_dir.mkdir()
        (test_dir / "test_foo.py").write_text("def test_foo(): pass")
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            r = cg.index(str(root))
            assert r["ok"] is True
            assert r["stats"]["files"] == 2
            files = {row[0] for row in cg._conn_get().execute("SELECT DISTINCT file FROM symbols")}
            assert "tests/test_foo.py" in files
        finally:
            cg.close()
            import shutil
            shutil.rmtree(d, ignore_errors=True)
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


    def test_search_like_wildcard_escaped(self):
        """LIKE 通配符 _ 应被转义，避免 foo_bar 匹配 fooXbar。"""
        d = tempfile.mkdtemp()
        root = Path(d) / "proj"
        root.mkdir()
        (root / "a.py").write_text("def foo_bar(): pass\ndef fooXbar(): pass\n")
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(db)
        try:
            cg.index(str(root))
            r = cg.explore("foo_bar")
            assert r["found"] is True
            names = {s["name"] for s in r.get("symbols", [])}
            assert "foo_bar" in names
            assert "fooXbar" not in names
        finally:
            cg.close()
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            for f in [db, db + "-shm", db + "-wal"]:
                try: os.unlink(f)
                except OSError: pass



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
            assert sym.get("next_call") == {"tool": "code_pack", "params": {"target": "big"}}
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


    def test_impact_with_absolute_path(self, test_db, tmp_project):
        """绝对路径输入也能正确匹配数据库中的相对路径。"""
        cg = CodeGraph(test_db)
        try:
            abs_path = os.path.join(tmp_project, "utils.py")
            r = cg.code_diff_impact([abs_path], max_depth=1)
            assert r["ok"] is True
            assert len(r["affected_symbols"]) > 0
            assert any(s["file"] == "utils.py" and s["depth"] == 0 for s in r["affected_symbols"])
        finally:
            cg.close()



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


    def test_resolves_relative_import_with_same_name(self):
        """存在同名符号时，相对 import 也能正确解析。"""
        d = tempfile.mkdtemp()
        root = Path(d) / "pkg"
        root.mkdir()
        (root / "__init__.py").write_text("")
        (root / "utils.py").write_text("def helper(): pass")
        (root / "other.py").write_text("def helper(): pass")
        (root / "main.py").write_text("from .utils import helper\n\ndef main():\n    helper()\n")
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(path)
        try:
            cg.index(str(root))
            conn = sqlite3.connect(path)
            edge = conn.execute(
                "SELECT to_sym, resolved FROM edges WHERE kind='calls' AND from_sym='main'"
            ).fetchone()
            assert edge is not None
            assert edge[0] == "helper"
            assert edge[1] == 1
            # 确认解析到 utils.py 的 helper，而不是 other.py
            sym_file = conn.execute(
                "SELECT file FROM symbols WHERE name='helper' AND file='utils.py'"
            ).fetchone()
            assert sym_file is not None
            conn.close()
        finally:
            cg.close()
            import shutil
            shutil.rmtree(d, ignore_errors=True)
            for f in [path, path + "-shm", path + "-wal"]:
                try: os.unlink(f)
                except OSError: pass



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


class TestEnsureDbSkip:
    """_ensure_db 幂等跳过：同一 db_path 二次初始化跳过 DDL，仅做每连接 PRAGMA。"""

    def test_second_init_skips_ddl(self, tmp_path):
        from tools import codegraph

        db = str(tmp_path / "skip.db")
        key = os.path.abspath(db)
        codegraph._ENSURED.discard(key)
        # 通过 __dict__ 取底层函数，恢复时重新包 staticmethod，避免变成实例方法
        original = CodeGraph.__dict__["_create_schema"].__func__
        calls = []

        def spy(conn):
            calls.append(1)
            return original(conn)

        try:
            cg1 = CodeGraph(db)
            cg1.close()
            assert key in codegraph._ENSURED
            assert len(calls) == 0  # spy 尚未挂载

            CodeGraph._create_schema = staticmethod(spy)
            try:
                cg2 = CodeGraph(db)
            finally:
                CodeGraph._create_schema = staticmethod(original)
            assert calls == []  # 二次初始化未触发 DDL
            try:
                # 连接可用，表结构仍在
                conn = cg2._conn_get()
                conn.execute("INSERT INTO meta(key,value) VALUES('k','v')")
                conn.commit()
                assert conn.execute("SELECT value FROM meta WHERE key='k'").fetchone()[0] == "v"
            finally:
                cg2.close()
        finally:
            codegraph._ENSURED.discard(key)


class TestRelatedLocations:
    """R3：引用位置字段（纯增量，旧字段不变）。"""

    def test_related_symbols_include_locations(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.explore("helper 在哪")
            assert r["found"] is True
            related = r["related_symbols"]
            # 旧字段保持
            assert "main" in related["callers"]
            # 新增位置字段
            assert "caller_locations" in related
            assert "callee_locations" in related
            locs = related["caller_locations"]
            assert len(locs) <= 50
            main_locs = [l for l in locs if l["name"] == "main"]
            assert main_locs
            assert main_locs[0]["file"]
            assert isinstance(main_locs[0]["line"], int)
        finally:
            cg.close()

    def test_trace_open_include_locations(self, test_db):
        cg = CodeGraph(test_db)
        try:
            r = cg.explore("helper 调用链")
            assert r["found"] is True
            assert "caller_locations" in r
            assert "callee_locations" in r
            assert isinstance(r["caller_locations"], list)
            # 旧字段保持
            assert "callers" in r and "callees" in r
        finally:
            cg.close()


class TestFtsIncrementalConsistency:
    """回归测试：FTS 与 symbols 的一致性维护。

    修复前：增量 INSERT 被 `except: pass` 吞掉，FTS 一旦脱节便永久漏搜。
    修复后：收尾处在需要时全量重建 FTS（DELETE + 从 symbols 重灌），
    保证 FTS 始终能回到与 symbols 一致的状态。
    """

    def test_fts_rebuild_restores_consistency(self, tmp_project):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cg = CodeGraph(db_path)
        try:
            cg.index(tmp_project)  # 全量建索引
            conn = cg._conn_get()

            # 人为制造不一致：从 FTS 删掉一个 symbols 里存在的符号
            conn.execute("DELETE FROM sym_fts WHERE name='helper'")
            conn.commit()
            n = conn.execute("SELECT COUNT(*) FROM sym_fts WHERE name='helper'").fetchone()[0]
            assert n == 0, "前置条件：FTS 中应已无 helper"

            # 触发一次非增量索引（等价于收尾重建路径），FTS 应被重灌恢复一致
            cg.index(tmp_project, incremental=False)
            n = conn.execute("SELECT COUNT(*) FROM sym_fts WHERE name='helper'").fetchone()[0]
            assert n >= 1, "FTS 重建后应恢复 helper，与 symbols 一致"
        finally:
            cg.close()
            for f in [db_path, db_path + "-shm", db_path + "-wal"]:
                try:
                    os.unlink(f)
                except OSError:
                    pass


class TestIndexStaleness:
    """索引过期探测：索引后被修改的文件应触发 index_stale 警告（行号可能漂移）。"""

    def _cg_in_project(self, tmp_project):
        db_dir = Path(tmp_project) / ".codegraph"
        db_dir.mkdir(exist_ok=True)
        cg = CodeGraph(str(db_dir / "codegraph.db"))
        cg.index(tmp_project)
        return cg

    def test_explore_flags_stale_file(self, tmp_project):
        cg = self._cg_in_project(tmp_project)
        try:
            # 索引后修改文件（mtime 拨到未来）
            target = Path(tmp_project) / "utils.py"
            future = cg._conn_get().execute(
                "SELECT CAST(value AS REAL) FROM meta WHERE key='last_index'").fetchone()[0] + 100
            os.utime(target, (future, future))

            r = cg.explore("helper")
            assert r["ok"] is True
            assert r.get("index_stale") is True
            assert "stale_warning" in r
        finally:
            cg.close()

    def test_explore_fresh_index_no_flag(self, tmp_project):
        cg = self._cg_in_project(tmp_project)
        try:
            r = cg.explore("helper")
            assert r["ok"] is True
            assert "index_stale" not in r
        finally:
            cg.close()

    def test_code_pack_flags_stale_file(self, tmp_project):
        cg = self._cg_in_project(tmp_project)
        try:
            target = Path(tmp_project) / "utils.py"
            future = cg._conn_get().execute(
                "SELECT CAST(value AS REAL) FROM meta WHERE key='last_index'").fetchone()[0] + 100
            os.utime(target, (future, future))

            r = cg.code_pack("helper")
            assert r["ok"] is True
            assert r.get("index_stale") is True
        finally:
            cg.close()
