"""
codegraph — 代码语义索引与查询引擎。

Python ast 解析 + SQLite 存储 + FTS5 全文检索。
tree-sitter 多语言支持（可选依赖：tree-sitter-{go,rust,java,c,cpp,javascript,typescript}）。
"""

from __future__ import annotations

import ast as py_ast
import concurrent.futures
import json
import logging
import multiprocessing
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path

from ._file_utils import detect_encoding as _detect_file_encoding

logger = logging.getLogger(__name__)

# ── optional deps ────────────────────────────────────

try:
    import tree_sitter
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


def _try_import_grammar(pkg: str):
    try:
        return __import__(pkg)
    except ImportError:
        return None

# ── constants ────────────────────────────────────────

_FTS_MIN_LENGTH = 2
_SOURCE_FULL_LINES = 30
_SOURCE_HEAD_LINES = 15
_SOURCE_TAIL_LINES = 5
_PACK_MAX_LINES = 2000
_PROGRESS_INTERVAL_FILES = 50
_STREAM_BATCH_SIZE = 50  # Write to DB every N files to limit memory

# 为搜索结果 TOP 符号展示完整源码时的兜底截断
_TOP_SOURCE_FULL_LINES = 100
_TOP_SOURCE_HEAD_LINES = 40
_TOP_SOURCE_TAIL_LINES = 20

# Worker count for parallel parsing
_MAX_WORKERS = max(1, min(multiprocessing.cpu_count() // 2, 8))

# 触发注册/回调关系的方法名（用于 _py_calls 生成 triggers 边）
_TRIGGER_METHODS = {"register", "add_tool", "add_handler", "on_event", "subscribe", "listen"}

_LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
}

_GRAMMAR_IMPORTS: dict[str, tuple[str, str]] = {
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
}

_DEFAULT_IGNORE = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".eggs", "build", "dist", "target", ".codegraph",
}

_MAX_FILE_SIZE = 1_000_000  # 1 MB，超大文件（测试数据/json fixture）跳过

_QUERY_ROUTES = [
    (re.compile(r"从\s+(\S+)\s+到\s+(\S+)"), "trace_closed"),
    (re.compile(r"from\s+(\S+)\s+to\s+(\S+)", re.IGNORECASE), "trace_closed"),
    (re.compile(r"(\S+)\s*→\s*(\S+)"), "trace_closed"),
    (re.compile(r"调用链|calls?\s*chain|trace|怎么走|how.*call|who.*calls?", re.IGNORECASE), "trace_open"),
    (re.compile(r"在哪|哪里|定义了?|定义在|where.*(?:is|defined)|locate|find.*symbol", re.IGNORECASE), "symbol_search"),
]

_SEARCH_NOISE = {"在哪", "哪里", "定义了", "定义在", "where", "is", "find", "locate", "的", "怎么"}

# ── tree-sitter node kind mappings ───────────────────

_TS_FUNCTION_TYPES = {
    "function_declaration", "function_definition",
    "method_declaration", "method_definition",
    "arrow_function", "function_expression",
    "constructor_declaration", "destructor_declaration",
}
_TS_CLASS_TYPES = {
    "class_declaration", "class_definition", "class_specifier",
    "struct_declaration", "struct_specifier",
    "interface_declaration", "interface_definition",
    "trait_declaration", "enum_declaration", "enum_specifier",
    "impl_item",
}
_TS_IMPORT_TYPES = {
    "import_declaration", "import_statement",
    "import_specification", "import_spec_list",
    "use_declaration", "mod_item",
}

# ── query tokenizer ──────────────────────────────────

def _tokenize_query(query: str) -> list[str]:
    tokens: set[str] = set()
    for word in re.split(r"\s+", query):
        word = word.strip()
        if len(word) < _FTS_MIN_LENGTH:
            continue
        tokens.add(word)
        # CamelCase / snake_case split
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\s|$)|[A-Z]+|\d+", word)
        tokens.update(p for p in parts if len(p) >= _FTS_MIN_LENGTH)
        sub = word.replace("_", " ").split()
        tokens.update(s for s in sub if len(s) >= _FTS_MIN_LENGTH)
    # Chinese 2-gram
    cjk_chars = re.findall(r"[\u4e00-\u9fff]+", query)
    for segment in cjk_chars:
        for i in range(len(segment) - 1):
            tokens.add(segment[i:i + 2])
        if len(segment) == 1:
            tokens.add(segment)
    return sorted(tokens)


def _like_escape(s: str) -> str:
    """为 SQLite LIKE 转义 %、_ 和转义符自身。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_escape_token(s: str) -> str:
    """把 token 用双引号包裹，内部双引号转义，避免 FTS5 语法错误。"""
    return '"' + s.replace('"', '""') + '"'


# ── code graph engine ─────────────────────────────────

# 已完成 DDL 初始化的 db_path 集合：二次打开同一库时跳过建表，仅做每连接的 PRAGMA。
# 注意：只有 DDL 全部成功才会写入，DDL 失败不会把 path 留在集合里。
_ENSURED: set[str] = set()


class CodeGraph:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        key = os.path.abspath(self._db_path)
        if key in _ENSURED:
            # DDL 已在首次打开时执行过，直接复用（PRAGMA 是每连接的，仍需执行）
            self._conn = conn
            return
        try:
            self._create_schema(conn)
        except Exception:
            conn.close()
            raise
        _ENSURED.add(key)
        self._conn = conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute("""CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            file TEXT NOT NULL,
            line INTEGER,
            signature TEXT,
            source TEXT,
            doc TEXT,
            visibility TEXT,
            is_async INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_sym TEXT NOT NULL,
            to_sym TEXT NOT NULL,
            kind TEXT NOT NULL,
            file TEXT,
            line INTEGER,
            resolved INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_file ON symbols(file)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_kind ON symbols(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sym_vis ON symbols(visibility)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edge_from ON edges(from_sym)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edge_to ON edges(to_sym)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edge_kind ON edges(kind)")
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS sym_fts USING fts5(name, file, signature)")
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
        conn.commit()

    def _conn_get(self) -> sqlite3.Connection:
        if self._conn is None:
            self._ensure_db()
        return self._conn

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception as exc:
                logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
            self._conn = None

    # ── index ─────────────────────────────────────────

    def index(self, project_dir: str, incremental: bool = False) -> dict:
        root = Path(project_dir).resolve()
        if not root.is_dir():
            return {"ok": False, "error": f"不是有效目录: {project_dir}"}

        start = time.time()
        conn = self._conn_get()
        if not incremental:
            conn.execute("DELETE FROM symbols")
            conn.execute("DELETE FROM edges")
            try:
                conn.execute("DELETE FROM sym_fts")
            except Exception as exc:
                logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        stats = {"files": 0, "symbols": 0, "edges": 0, "skipped": 0}
        mtimes: dict[str, float] = {}
        if incremental:
            row = conn.execute("SELECT value FROM meta WHERE key='mtimes'").fetchone()
            if row:
                mtimes = json.loads(row[0]) if row[0] else {}

        progress_log: list[dict] = []
        files_scanned = 0

        all_files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # 剪枝忽略目录，避免进入 node_modules/.git 等大目录
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_IGNORE]
            for fname in filenames:
                suffix = Path(fname).suffix.lower()
                if suffix not in _LANG_MAP:
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size <= _MAX_FILE_SIZE:
                        all_files.append(fpath)
                except OSError:
                    pass
        
        # P0-3 fix: clean up deleted files in incremental mode
        changed_files: list[Path] = []
        if incremental and mtimes:
            indexed_files = set(mtimes.keys())
            current_files = {str(f.relative_to(root)).replace("\\", "/") for f in all_files}
            deleted = indexed_files - current_files
            for dp in deleted:
                conn.execute("DELETE FROM symbols WHERE file=?", (dp,))
                conn.execute("DELETE FROM edges WHERE file=?", (dp,))
                try:
                    conn.execute("DELETE FROM sym_fts WHERE file=?", (dp,))
                except Exception:
                    pass
                del mtimes[dp]
            # Filter to only changed files
            for fpath in all_files:
                rp = str(fpath.relative_to(root)).replace("\\", "/")
                if rp not in mtimes or mtimes[rp] < fpath.stat().st_mtime:
                    changed_files.append(fpath)
        else:
            changed_files = all_files

        total_files = len(all_files)
        changed_count = len(changed_files)

        # ── Parallel parsing + single-threaded batch write ──
        fts_need_rebuild = False
        if changed_count > 0:
            worker_args = [(str(f), f.suffix.lower(), str(root)) for f in changed_files]

            results: list = []
            if len(worker_args) == 1:
                # 单文件避免线程池开销
                try:
                    results.append(_extract_file_worker(worker_args[0]))
                except Exception:
                    stats["skipped"] += 1
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                    futures = {executor.submit(_extract_file_worker, args): args for args in worker_args}
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception:
                            stats["skipped"] += 1

            # Batch write (SQLite 写入仍单线程以避免锁竞争)
            for rp, suffix, mtime_val, symbols, edges in results:
                if incremental:
                    conn.execute("DELETE FROM symbols WHERE file=?", (rp,))
                    conn.execute("DELETE FROM edges WHERE file=?", (rp,))
                    try:
                        conn.execute("DELETE FROM sym_fts WHERE file=?", (rp,))
                    except Exception:
                        pass
                    mtimes[rp] = mtime_val
                
                if symbols:
                    conn.executemany(
                        "INSERT INTO symbols(name,kind,file,line,signature,source,doc,visibility,is_async) "
                        "VALUES(:name,:kind,:file,:line,:signature,:source,:doc,:visibility,:is_async)",
                        [{"name": s["name"], "kind": s["kind"], "file": rp,
                          "line": s.get("line"), "signature": s.get("signature"),
                          "source": s.get("source"), "doc": s.get("doc"),
                          "visibility": s.get("visibility", "public"),
                          "is_async": s.get("is_async", 0)} for s in symbols],
                    )
                if edges:
                    conn.executemany(
                        "INSERT INTO edges(from_sym,to_sym,kind,file,line) VALUES(:from,:to,:kind,:file,:line)",
                        [{"from": e["from"], "to": e["to"], "kind": e["kind"],
                          "file": rp, "line": e.get("line")} for e in edges],
                    )
                if incremental and symbols:
                    try:
                        conn.executemany(
                            "INSERT INTO sym_fts(name, file, signature) VALUES(?, ?, ?)",
                            [(s["name"], rp, s.get("signature", "")) for s in symbols],
                        )
                    except Exception as exc:
                        # 不再静默吞掉：标记后于收尾处全量重建 FTS，
                        # 否则增量只删不补会让 FTS 与 symbols 表永久脱节、搜索漏结果。
                        fts_need_rebuild = True
                        logger.warning("codegraph: incremental FTS insert failed for %s, will rebuild FTS: %s", rp, exc)

                stats["symbols"] += len(symbols)
                stats["edges"] += len(edges)
                stats["files"] += 1
                
                files_scanned += 1
                if files_scanned % _PROGRESS_INTERVAL_FILES == 0:
                    progress_log.append({"phase": "indexing", "file": rp,
                                       "progress": f"{stats['files']}/{total_files}",
                                       "elapsed_s": round(time.time() - start, 1)})
            
            # Full FTS5 rebuild if not incremental or too many changes,
            # or an incremental FTS insert failed (consistency fallback).
            if not incremental or fts_need_rebuild or changed_count >= total_files * 0.5:
                try:
                    conn.execute("DELETE FROM sym_fts")
                    conn.execute("INSERT INTO sym_fts(name, file, signature) SELECT name, file, signature FROM symbols")
                except Exception as exc:
                    # 重建失败必须可见：FTS 已与 symbols 脱节，后续搜索不可靠。
                    logger.error("codegraph: FTS rebuild failed, full-text search may be inconsistent: %s", exc, exc_info=True)

        try:
            _resolve_references(conn)
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        if incremental:
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('mtimes',?)", (json.dumps(mtimes),))
        conn.commit()
        
        elapsed = round(time.time() - start, 2)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", ("project_dir", str(root)))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", ("last_index", str(time.time())))
        conn.commit()

        summary = f"索引完成：{stats['files']} 文件, {stats['symbols']} 符号, {stats['edges']} 边, 耗时 {elapsed}s"
        if stats["skipped"]:
            summary += f", {stats['skipped']} 跳过"
        if incremental and changed_count < total_files:
            summary += f" (增量: {changed_count}/{total_files} 文件变更)"
        result: dict = {"ok": True, "summary": summary, "stats": stats}
        if progress_log:
            result["progress_log"] = progress_log
        return result

    # ── explore ───────────────────────────────────────

    def explore(self, query: str, project_dir: str = ".") -> dict:
        conn = self._conn_get()
        row = conn.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
        if not row:
            return {"ok": False, "error": "no_index",
                    "proposal": f"先运行 code_index('{os.path.abspath(project_dir)}') 建索引（首次 ~0.5-5s）。",
                    "options": ["建索引", "用 rg_search 搜索原始文本"]}

        qtype, match = _route_query(query)

        if qtype == "trace_closed" and match and match.re.groups >= 2:
            return self._trace_path(conn, match.group(1).strip(), match.group(2).strip())
        if qtype == "trace_open":
            result = self._trace_open(conn, query)
        elif qtype == "symbol_search":
            target = query
            for kw in _SEARCH_NOISE:
                target = target.replace(kw, " ")
            target = re.sub(r"\s+", " ", target).strip()
            result = self._search_symbol(conn, target)
        else:
            result = self._explore_fallback(conn, query)
        # 索引新鲜度：索引后被修改的文件会让返回的行号/位置漂移
        if isinstance(result, dict) and result.get("ok"):
            stale = self._staleness(conn, _result_files(result))
            if stale:
                result["index_stale"] = True
                result["stale_warning"] = (
                    f"{stale} 个文件在索引后被修改，行号/调用位置可能已漂移，"
                    "建议 code_index(incremental=true) 后重查"
                )
        return result

    def _staleness(self, conn, files: list[str], limit: int = 50) -> int:
        """统计 files 中 mtime 晚于 last_index 的数量（索引过期探测）。"""
        row = conn.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
        if not row:
            return 0
        try:
            last_index = float(row[0])
        except (TypeError, ValueError):
            return 0
        root = Path(self._db_path).resolve().parent.parent
        stale = 0
        seen: set[str] = set()
        for f in files:
            if not f or f in seen:
                continue
            seen.add(f)
            if len(seen) > limit:
                break
            try:
                if (root / f).resolve().stat().st_mtime > last_index:
                    stale += 1
            except OSError:
                continue
        return stale

    # ── search ────────────────────────────────────────

    def _search_symbol(self, conn, target: str) -> dict:
        symbols, strategy = self._search(conn, target)
        if not symbols:
            candidates = self._get_candidates(conn, target)
            result: dict = {"ok": True, "found": False, "query_type": "symbol_search",
                   "summary": f"未找到符号 '{target}'。",
                   "search_strategy": strategy}
            if candidates:
                result["candidates"] = candidates
                result["hint"] = f"上述候选中有你要找的吗？用精确名重试 code_explore。否则 fallback 到 rg_search。"
            else:
                result["hint"] = "该符号不在索引中。用 rg_search 搜索原始文本。"
            return result

        symbols = self._sort_symbols(conn, symbols)
        for i in range(min(3, len(symbols))):
            name = symbols[i]["name"]
            sr = conn.execute("SELECT source FROM symbols WHERE name=? LIMIT 1", (name,)).fetchone()
            if sr and sr[0]:
                top = self._top_source_or_hint(sr[0], name)
                symbols[i].update(top)
        rmap = self._build_relationship_map(conn, [s["name"] for s in symbols])
        blast = self._build_blast_radius(conn, [s["name"] for s in symbols[:3]])
        grouped = self._build_grouped_by_file(conn, symbols)
        related = self._get_related(conn, symbols[0]["name"]) if symbols else {}

        return {"ok": True, "found": True, "query_type": "symbol_search",
                "summary": f"找到 {len(symbols)} 个匹配 '{target}' 的符号。",
                "symbols": symbols[:10], "relationship_map": rmap, "blast_radius": blast,
                "grouped_by_file": grouped, "related_symbols": related,
                "search_strategy": strategy,
                "hint": "需要调用链？用 code_explore('从 X 到 Y') 精确追踪。"}

    def _trace_path(self, conn, from_sym: str, to_sym: str) -> dict:
        path = _bfs_path(conn, from_sym, to_sym, max_depth=6)
        if path:
            return {"ok": True, "found": True, "query_type": "trace",
                    "summary": f"从 {from_sym} 到 {to_sym} 的调用链 ({len(path)-1} 跳): {' → '.join(path)}",
                    "path": path}
        fwd = _bfs_path(conn, from_sym, to_sym, max_depth=10)
        if fwd:
            return {"ok": True, "found": True, "query_type": "trace",
                    "summary": f"(长路径 {len(fwd)-1} 跳) {' → '.join(fwd)}", "path": fwd}
        # partial path
        partial = _bfs_partial(conn, from_sym, to_sym, max_depth=8)
        result: dict = {"ok": True, "found": False, "query_type": "trace",
               "summary": f"从 {from_sym} 到 {to_sym} 未找到完整静态调用链。"}
        if partial:
            result["partial_path"] = partial["path"]
            result["break_at"] = partial["break_at"]
            result["break_reason"] = partial.get("reason", "BFS 未找到路径")
            result["hint"] = f"断在 {partial['break_at']}——可能通过回调、动态调用或 AstrBot 框架路由连接。用 rg_search 确认。"
        else:
            result["hint"] = f"用 rg_search 搜索 {to_sym} 确认是否通过动态调用连接。"
        return result

    def _trace_open(self, conn, query: str) -> dict:
        tokens = _tokenize_query(query)
        fts_query = " OR ".join(tokens) if tokens else query
        try:
            rows = conn.execute("SELECT name, file, signature FROM sym_fts WHERE sym_fts MATCH ? ORDER BY rank LIMIT 4",
                                (fts_query,)).fetchall()
        except Exception:
            rows = conn.execute("SELECT name,file,signature FROM symbols WHERE name LIKE ? LIMIT 4",
                                (f"%{query}%",)).fetchall()
        if not rows:
            return {"ok": True, "found": False, "query_type": "trace",
                    "summary": f"未找到与 '{query}' 相关的符号。"}
        sname = rows[0][0]
        caller_rows = conn.execute("SELECT from_sym, file, line FROM edges WHERE to_sym=? AND kind='calls' LIMIT 50", (sname,)).fetchall()
        callee_rows = conn.execute("SELECT to_sym, file, line FROM edges WHERE from_sym=? AND kind='calls' LIMIT 50", (sname,)).fetchall()
        callers = [r[0] for r in caller_rows[:8]]
        callees = [r[0] for r in callee_rows[:8]]
        caller_locations = [{"name": r[0], "file": r[1], "line": r[2]} for r in caller_rows]
        callee_locations = [{"name": r[0], "file": r[1], "line": r[2]} for r in callee_rows]
        sym_info = {"name": rows[0][0], "signature": rows[0][2], "file": rows[0][1]}
        return {"ok": True, "found": True, "query_type": "trace",
                "summary": f"{sname} 的调用关系：{len(callers)} 调用者, {len(callees)} 被调用者。",
                "symbol": sym_info, "callers": callers, "callees": callees,
                "caller_locations": caller_locations, "callee_locations": callee_locations}

    def _explore_fallback(self, conn, query: str) -> dict:
        symbols, strategy = self._search(conn, query)
        if not symbols:
            candidates = self._get_candidates(conn, query)
            result: dict = {"ok": True, "found": False, "query_type": "explore",
                   "summary": f"自然语言探索 '{query}'：未找到相关符号。", "search_strategy": strategy}
            if candidates:
                result["candidates"] = candidates
            return result
        symbols = self._sort_symbols(conn, symbols)
        for i in range(min(3, len(symbols))):
            name = symbols[i]["name"]
            sr = conn.execute("SELECT source FROM symbols WHERE name=? LIMIT 1", (name,)).fetchone()
            if sr and sr[0]:
                top = self._top_source_or_hint(sr[0], name)
                symbols[i].update(top)
        rmap = self._build_relationship_map(conn, [s["name"] for s in symbols])
        grouped = self._build_grouped_by_file(conn, symbols)

        return {"ok": True, "found": True, "query_type": "explore",
                "summary": f"自然语言探索 '{query}'：找到 {len(symbols)} 个相关符号。",
                "symbols": symbols, "relationship_map": rmap, "grouped_by_file": grouped,
                "search_strategy": strategy}

    # ── search engine ─────────────────────────────────
    def _search(self, conn, query: str, limit: int = 10) -> tuple[list[dict], str]:
        """三级搜索：LIKE → FTS5 → 无结果提示。支持 kind: 过滤（如 kind:function）。"""
        kind_filter = ""
        m = re.search(r"kind:(\w+)", query)
        if m:
            kind_filter = m.group(1)
            query = query.replace(m.group(0), "").strip()
        base_where = f"WHERE name LIKE ? ESCAPE '\\'{' AND kind=?' if kind_filter else ''}"
        base_params: list = [f"%{_like_escape(query)}%"]
        if kind_filter:
            base_params.append(kind_filter)
        try:
            rows = conn.execute(
                f"SELECT name,kind,file,line,signature,source,visibility,is_async FROM symbols {base_where} LIMIT ?",
                base_params + [limit],
            ).fetchall()
            if rows:
                return [_row_to_dict(r) for r in rows], "like"
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        tokens = _tokenize_query(query)
        if tokens:
            try:
                fts_query = " OR ".join(_fts_escape_token(t) for t in tokens)
                rows = conn.execute(
                    "SELECT name, file, signature FROM sym_fts WHERE sym_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_query, limit * 3),
                ).fetchall()
                if rows:
                    result = []
                    seen = set()
                    fts_names = [r[0] for r in rows if r[0] not in seen and not seen.add(r[0])]
                    for name in fts_names[:limit]:
                        sr = conn.execute("SELECT name,kind,file,line,signature,source,visibility,is_async FROM symbols WHERE name=? LIMIT 1", (name,)).fetchone()
                        if sr:
                            result.append(_row_to_dict(sr))
                    if result:
                        return result, "fts5"
            except Exception as exc:
                logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        # try LIKE on wider field
        try:
            like_pat = f"%{_like_escape(query)}%"
            rows = conn.execute(
                "SELECT name,kind,file,line,signature,source,visibility,is_async FROM symbols WHERE signature LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\' LIMIT ?",
                (like_pat, like_pat, limit),
            ).fetchall()
            if rows:
                return [_row_to_dict(r) for r in rows], "like_wide"
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        return [], "none"

    # ── sorting ───────────────────────────────────────

    def _sort_symbols(self, conn, symbols: list[dict]) -> list[dict]:
        if len(symbols) <= 1:
            return symbols
        counts: dict[str, int] = {}
        names = [s["name"] for s in symbols]
        placeholders = ",".join(["?"] * len(names))
        rows = conn.execute(
            f"SELECT to_sym, COUNT(*) FROM edges WHERE to_sym IN ({placeholders}) AND kind='calls' GROUP BY to_sym",
            names,
        ).fetchall()
        for name, cnt in rows:
            counts[name] = cnt

        def _score(s: dict) -> tuple[int, int, int, int]:
            vis = 0 if s.get("visibility") == "public" else 1
            is_def = 0 if s.get("kind") in ("function", "method", "class") else 1
            cnt = -(counts.get(s["name"], 0))
            return (vis, is_def, cnt, 0)

        return sorted(symbols, key=_score)

    # ── candidates ────────────────────────────────────

    def _get_candidates(self, conn, query: str, limit: int = 3) -> list[dict]:
        try:
            rows = conn.execute(
                "SELECT name,kind,file,line FROM symbols WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit * 2),
            ).fetchall()
            if rows:
                result = []
                for r in rows:
                    result.append({"name": r[0], "kind": r[1], "file": r[2], "line": r[3]})
                return result[:limit]
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
        return []

    # ── relationship map ──────────────────────────────

    def _build_relationship_map(self, conn, names: list[str]) -> dict:
        rmap: dict = {}
        limit = min(len(names), 5)
        targets = names[:limit]
        if not targets:
            return rmap
        placeholders = ",".join(["?"] * len(targets))
        calls_map: dict[str, list] = defaultdict(list)
        called_by_map: dict[str, list] = defaultdict(list)
        for row in conn.execute(f"SELECT from_sym,to_sym FROM edges WHERE kind='calls' AND (from_sym IN ({placeholders}) OR to_sym IN ({placeholders}))", targets + targets).fetchall():
            if row[0] in targets:
                calls_map[row[0]].append(row[1])
            if row[1] in targets:
                called_by_map[row[1]].append(row[0])
        for name in targets:
            rmap[name] = {
                "calls": calls_map.get(name, [])[:5],
                "called_by": called_by_map.get(name, [])[:5],
            }
        return rmap

    # ── blast radius ──────────────────────────────────

    def _build_blast_radius(self, conn, names: list[str], depth: int = 1) -> dict:
        affected: dict[str, dict] = {}
        for name in names[:3]:
            callers = _bfs_all_callers(conn, name, depth)
            files: set[str] = set()
            for c in callers:
                sr = conn.execute("SELECT file FROM symbols WHERE name=? LIMIT 1", (c,)).fetchone()
                if sr:
                    files.add(sr[0])
            affected[name] = {"callers": callers, "affected_files": sorted(files)[:10], "total_callers": len(callers)}
        return affected

    # ── grouped by file ───────────────────────────────

    def _build_grouped_by_file(self, conn, symbols: list[dict]) -> dict:
        groups: dict[str, dict] = {}
        for s in symbols:
            f = s.get("file", "unknown")
            if f not in groups:
                groups[f] = {"symbols": [], "count": 0}
            groups[f]["symbols"].append({"name": s.get("name"), "kind": s.get("kind"), "line": s.get("line")})
            groups[f]["count"] += 1
        for f in groups:
            kinds = defaultdict(int)
            for sym in groups[f]["symbols"]:
                kinds[sym["kind"]] += 1
            parts = [f"{v} {k}" for k, v in sorted(kinds.items()) if v]
            groups[f]["summary"] = ", ".join(parts) if parts else "0 symbols"
        return dict(sorted(groups.items(), key=lambda x: -x[1]["count"])) if len(groups) <= 8 else dict(sorted(list(groups.items()), key=lambda x: -x[1]["count"])[:8])

    # ── related symbols ───────────────────────────────

    def _get_related(self, conn, name: str) -> dict:
        caller_rows = conn.execute("SELECT from_sym, file, line FROM edges WHERE to_sym=? AND kind='calls' LIMIT 50", (name,)).fetchall()
        callee_rows = conn.execute("SELECT to_sym, file, line FROM edges WHERE from_sym=? AND kind='calls' LIMIT 50", (name,)).fetchall()
        return {
            "callers": [r[0] for r in caller_rows[:5]],
            "callees": [r[0] for r in callee_rows[:5]],
            "caller_locations": [{"name": r[0], "file": r[1], "line": r[2]} for r in caller_rows],
            "callee_locations": [{"name": r[0], "file": r[1], "line": r[2]} for r in callee_rows],
        }

    # ── smart source truncation ───────────────────────

    @staticmethod
    def _smart_truncate(source: str) -> dict:
        if not source:
            return {"source": "", "source_truncated": False, "total_lines": 0}
        lines = source.split("\n")
        total = len(lines)
        if total <= _SOURCE_FULL_LINES:
            return {"source": source, "source_truncated": False, "total_lines": total}
        head = lines[:_SOURCE_HEAD_LINES]
        tail = lines[-_SOURCE_TAIL_LINES:]
        skipped = total - _SOURCE_HEAD_LINES - _SOURCE_TAIL_LINES
        truncated = "\n".join(head) + f"\n... ({skipped} lines skipped) ...\n" + "\n".join(tail)
        return {"source": truncated, "source_truncated": True, "total_lines": total}

    @staticmethod
    def _top_source_or_hint(source: str, name: str) -> dict:
        """搜索结果 TOP 符号展示完整源码时的兜底截断，超长时引导 code_pack。"""
        if not source:
            return {"source": "", "source_truncated": False, "total_lines": 0}
        lines = source.split("\n")
        total = len(lines)
        if total <= _TOP_SOURCE_FULL_LINES:
            return {"source": source, "source_truncated": False, "total_lines": total}
        head = lines[:_TOP_SOURCE_HEAD_LINES]
        tail = lines[-_TOP_SOURCE_TAIL_LINES:]
        skipped = total - _TOP_SOURCE_HEAD_LINES - _TOP_SOURCE_TAIL_LINES
        truncated = "\n".join(head) + f"\n... ({skipped} lines skipped) ...\n" + "\n".join(tail)
        return {
            "source": truncated,
            "source_truncated": True,
            "total_lines": total,
            "header": f"符号 '{name}' 源码共 {total} 行，超过 {_TOP_SOURCE_FULL_LINES} 行，已展示 {_TOP_SOURCE_HEAD_LINES} 行头 + {_TOP_SOURCE_TAIL_LINES} 行尾。",
            "footer": "需要完整源码请调用 code_pack。",
            "next_call": {"tool": "code_pack", "args": {"target": name}},
            "options": [f"code_pack('{name}')"],
        }

    # ── code_diff_impact ──────────────────────────────

    def _impact_file_candidates(self, conn, fp: str) -> list[str]:
        """把用户传入的文件路径归一化为数据库中存储的相对 POSIX 路径的多个候选。"""
        if not fp:
            return []
        candidates = {fp, fp.replace("/", "\\"), fp.replace("\\", "/")}
        if os.path.isabs(fp):
            row = conn.execute("SELECT value FROM meta WHERE key='project_dir'").fetchone()
            if row:
                try:
                    rel = Path(fp).relative_to(Path(row[0]))
                    posix = rel.as_posix()
                    candidates.add(posix)
                    candidates.add(posix.replace("/", "\\"))
                except ValueError:
                    pass
        return [c for c in candidates if c]

    def code_diff_impact(self, filepaths: list[str], max_depth: int = 3) -> dict:
        conn = self._conn_get()
        affected_symbols: list[dict] = []
        affected_files: set[str] = set()
        for fp in filepaths:
            candidates = self._impact_file_candidates(conn, fp)
            if not candidates:
                continue
            placeholders = ",".join(["?"] * len(candidates))
            rows = conn.execute(
                f"SELECT name,kind,line,file FROM symbols WHERE file IN ({placeholders}) LIMIT 50",
                candidates,
            ).fetchall()
            for r in rows:
                name, kind, line, matched_fp = r[0], r[1], r[2], r[3]
                callers = _bfs_all_callers(conn, name, max_depth)
                depth_map = {c: i + 1 for i, c in enumerate(callers)}
                for c in callers:
                    sr = conn.execute("SELECT file,kind,line FROM symbols WHERE name=? LIMIT 1", (c,)).fetchone()
                    if sr:
                        affected_symbols.append({"name": c, "file": sr[0], "kind": sr[1], "depth": depth_map[c]})
                        affected_files.add(sr[0])
                if callers:
                    affected_symbols.append({"name": name, "file": matched_fp, "kind": kind, "depth": 0})
                    affected_files.add(matched_fp)
        return {"ok": True, "affected_symbols": affected_symbols[:30], "affected_files": sorted(affected_files)[:20], "blast_depth": max_depth}

    # ── code_pack ─────────────────────────────────────

    def code_pack(self, target: str, depth: int = 2, mode: str = "both") -> dict:
        conn = self._conn_get()
        sr = conn.execute("SELECT name,kind,file,line,signature,source FROM symbols WHERE name=? LIMIT 1", (target,)).fetchone()
        if not sr:
            sr = conn.execute("SELECT name,kind,file,line,signature,source FROM symbols WHERE name LIKE ? LIMIT 1", (f"%{target}%",)).fetchone()
        if not sr:
            return {"ok": False, "error": f"符号 '{target}' 未找到",
                    "proposal": "先运行 code_index 建立索引，或用 code_explore 搜索近似符号",
                    "options": ["用 code_explore 搜索", "用 rg_search 搜索原始文本"]}
        target_info = {"name": sr[0], "kind": sr[1], "file": sr[2], "line": sr[3], "signature": sr[4]}
        trunc = self._smart_truncate(sr[5] or "")
        target_info.update(trunc)

        deps: list[dict] = []
        visited: set[str] = {target}
        queue = deque([(target, 0, "target")])
        total_lines = len((sr[5] or "").split("\n")) if sr[5] else 0

        while queue:
            node, d, relation = queue.popleft()
            if d >= depth:
                continue
            if mode in ("callees", "both"):
                rows = conn.execute("SELECT to_sym,kind FROM edges WHERE from_sym=? AND kind='calls' LIMIT 20", (node,)).fetchall()
                for callee_name, _ in rows:
                    if callee_name in visited:
                        continue
                    visited.add(callee_name)
                    ds = conn.execute("SELECT name,kind,file,line,signature,source FROM symbols WHERE name=? LIMIT 1", (callee_name,)).fetchone()
                    if ds:
                        trunc = self._smart_truncate(ds[5] or "")
                        entry = {"name": ds[0], "kind": ds[1], "file": ds[2], "line": ds[3], "signature": ds[4],
                                 "relation": "callee", "depth": d + 1}
                        entry.update(trunc)
                        deps.append(entry)
                        total_lines += trunc["total_lines"]
                        if total_lines > _PACK_MAX_LINES:
                            break
                        queue.append((callee_name, d + 1, "callee"))
            if mode in ("callers", "both"):
                rows = conn.execute("SELECT from_sym,kind FROM edges WHERE to_sym=? AND kind='calls' LIMIT 20", (node,)).fetchall()
                for caller_name, _ in rows:
                    if caller_name in visited:
                        continue
                    visited.add(caller_name)
                    ds = conn.execute("SELECT name,kind,file,line,signature,source FROM symbols WHERE name=? LIMIT 1", (caller_name,)).fetchone()
                    if ds:
                        trunc = self._smart_truncate(ds[5] or "")
                        entry = {"name": ds[0], "kind": ds[1], "file": ds[2], "line": ds[3], "signature": ds[4],
                                 "relation": "caller", "depth": d + 1}
                        entry.update(trunc)
                        deps.append(entry)
                        total_lines += trunc["total_lines"]
                        if total_lines > _PACK_MAX_LINES:
                            break
                        queue.append((caller_name, d + 1, "caller"))
            if total_lines > _PACK_MAX_LINES:
                break

        result = {"ok": True, "target": target_info, "dependencies": deps, "total_lines": total_lines,
                "truncated": total_lines > _PACK_MAX_LINES}
        # 索引新鲜度：打包的源码/行号来自索引，索引后修改的文件内容会漂移
        stale = self._staleness(conn, [target_info["file"]] + [d["file"] for d in deps])
        if stale:
            result["index_stale"] = True
            result["stale_warning"] = (
                f"{stale} 个文件在索引后被修改，打包的源码/行号可能已漂移，"
                "建议 code_index(incremental=true) 后重查"
            )
        return result

    # ── code_status ───────────────────────────────────

    def code_status(self) -> dict:
        conn = self._conn_get()
        files = conn.execute("SELECT COUNT(DISTINCT file) FROM symbols").fetchone()[0]
        symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        last = conn.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
        last_str = ""
        if last:
            try:
                last_str = str(last[0])
            except Exception:
                last_str = str(last[0])

        try:
            db_size = os.path.getsize(self._db_path)
            size_str = f"{db_size / 1024 / 1024:.1f}MB" if db_size > 1024 * 1024 else f"{db_size / 1024:.0f}KB"
        except OSError:
            size_str = "unknown"

        fts_ok = False
        try:
            conn.execute("SELECT count(*) FROM sym_fts").fetchone()
            fts_ok = True
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)

        missing: list[str] = []
        if HAS_TREE_SITTER:
            for lang, (pkg, _) in _GRAMMAR_IMPORTS.items():
                if _try_import_grammar(pkg) is None:
                    missing.append(lang)

        hint = ""
        if missing:
            hint = f"缺失 grammar: pip install {' '.join(f'tree-sitter-{l}' for l in missing)}"
        elif not HAS_TREE_SITTER:
            hint = "tree-sitter 未安装: pip install tree-sitter tree-sitter-python（可选，仅 Python 可用）"

        return {"ok": True, "files_indexed": files, "symbols_total": symbols, "edges_total": edges,
                "last_index_at": last_str, "db_size": size_str, "fts5_ok": fts_ok,
                "missing_grammars": missing, "install_hint": hint,
                "language_support": "python ✅ | " + ", ".join(f"{l} ⚠️" if l in missing else f"{l} ✅" if HAS_TREE_SITTER and _try_import_grammar(pkg) is not None else f"{l} ❌" for l, (pkg, _) in _GRAMMAR_IMPORTS.items())}


# ── helpers ───────────────────────────────────────────

def _row_to_dict(r) -> dict:
    raw_source = (r[5] or "") if len(r) > 5 else ""
    truncated = CodeGraph._smart_truncate(raw_source)
    d = {"name": r[0], "kind": r[1], "file": r[2], "line": r[3],
         "signature": r[4], "source": truncated["source"],
         "source_truncated": truncated["source_truncated"],
         "total_lines": truncated["total_lines"]}
    if len(r) > 6 and r[6]:
        d["visibility"] = r[6]
    if len(r) > 7 and r[7]:
        d["is_async"] = bool(r[7])
    return d


# ── file extraction ──────────────────────────────────

def _extract_file(filepath: str, suffix: str) -> tuple[list[dict], list[dict]]:
    lang = _LANG_MAP.get(suffix, "")
    if lang == "python":
        return _extract_python(filepath)
    if HAS_TREE_SITTER:
        try:
            return _extract_ts(filepath, lang)
        except Exception as exc:
            logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
    return [], []


def _extract_file_worker(args: tuple) -> tuple[str, str, float, list[dict], list[dict]]:
    """Worker function for parallel parsing."""
    fpath_str, suffix, root_str = args
    fpath = Path(fpath_str)
    try:
        symbols, edges = _extract_file(fpath_str, suffix)
        try:
            rp = str(fpath.relative_to(root_str)).replace("\\", "/")
        except ValueError:
            rp = str(fpath)
        return (rp, suffix, fpath.stat().st_mtime, symbols, edges)
    except Exception:
        try:
            rp = str(fpath.relative_to(root_str)).replace("\\", "/")
        except ValueError:
            rp = str(fpath)
        return (rp, suffix, fpath.stat().st_mtime, [], [])


# ── Python AST ───────────────────────────────────────

def _extract_python(filepath: str) -> tuple[list[dict], list[dict]]:
    try:
        enc = _detect_file_encoding(filepath)
        with open(filepath, "r", encoding=enc, errors="replace") as f:
            source = f.read()
    except Exception:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    tree = py_ast.parse(source)
    symbols: list[dict] = []
    edges: list[dict] = []

    class Visitor(py_ast.NodeVisitor):
        def __init__(self):
            self._scope: list[str] = []
            self._current_cls = ""

        def _full_name(self, name: str) -> str:
            return ".".join(self._scope + [name]) if self._scope else name

        def visit_FunctionDef(self, node):
            fn = self._full_name(node.name)
            sig = f"def {node.name}(...)"
            try:
                args = []
                for a in node.args.args:
                    arg = a.arg
                    if a.annotation:
                        arg += f": {py_ast.unparse(a.annotation)}"
                    args.append(arg)
                sig = f"def {node.name}({', '.join(args)})"
            except Exception as exc:
                logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
            symbols.append({"name": fn, "kind": "method" if self._current_cls else "function",
                           "line": node.lineno, "signature": sig,
                           "source": (py_ast.get_source_segment(source, node) or "")[:6000],
                           "doc": py_ast.get_docstring(node) or "",
                           "visibility": "public" if not node.name.startswith("_") else "private"})
            edges.extend(_py_calls(node, source, fn))
            edges.extend(_py_refs(node, source, fn))
            self._scope.append(node.name)
            self.generic_visit(node)
            self._scope.pop()

        def visit_AsyncFunctionDef(self, node):
            fn = self._full_name(node.name)
            sig = f"async def {node.name}(...)"
            try:
                args = []
                for a in node.args.args:
                    arg = a.arg
                    if a.annotation:
                        arg += f": {py_ast.unparse(a.annotation)}"
                    args.append(arg)
                sig = f"async def {node.name}({', '.join(args)})"
            except Exception as exc:
                logger.debug("codegraph suppressed error: %s", exc, exc_info=True)
            symbols.append({"name": fn, "kind": "method" if self._current_cls else "function",
                           "line": node.lineno, "signature": sig,
                           "source": (py_ast.get_source_segment(source, node) or "")[:6000],
                           "doc": py_ast.get_docstring(node) or "",
                           "visibility": "public" if not node.name.startswith("_") else "private",
                           "is_async": 1})
            edges.extend(_py_calls(node, source, fn))
            edges.extend(_py_refs(node, source, fn))
            self._scope.append(node.name)
            self.generic_visit(node)
            self._scope.pop()

        def visit_ClassDef(self, node):
            cls = self._full_name(node.name)
            bases = [".".join(_unparse_attr(b)) for b in getattr(node, "bases", []) if isinstance(b, (py_ast.Name, py_ast.Attribute))]
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
            symbols.append({"name": cls, "kind": "class", "line": node.lineno, "signature": sig,
                           "source": (py_ast.get_source_segment(source, node) or "").split("\n")[0],
                           "doc": py_ast.get_docstring(node) or "",
                           "visibility": "public" if not node.name.startswith("_") else "private"})
            for bn in bases:
                edges.append({"from": cls, "to": bn, "kind": "extends", "line": node.lineno})
            prev = self._current_cls
            self._current_cls = node.name
            self._scope.append(node.name)
            self.generic_visit(node)
            self._scope.pop()
            self._current_cls = prev

        def visit_Import(self, node):
            scope = self._scope[-1] if self._scope else "(module)"
            for a in node.names:
                edges.append({"from": scope, "to": a.name, "kind": "imports", "line": node.lineno})

        def visit_ImportFrom(self, node):
            scope = self._scope[-1] if self._scope else "(module)"
            mod = node.module or ""
            for a in node.names:
                edges.append({"from": scope, "to": f"{mod}.{a.name}" if mod else a.name, "kind": "imports", "line": node.lineno})

    Visitor().visit(tree)
    return symbols, edges


def _py_calls(node, source, caller):
    edges = []
    class CV(py_ast.NodeVisitor):
        def visit_Call(self, node):
            if isinstance(node.func, py_ast.Name):
                edges.append({"from": caller, "to": node.func.id, "kind": "calls", "line": getattr(node, "lineno", None)})
            elif isinstance(node.func, py_ast.Attribute):
                edges.append({"from": caller, "to": ".".join(_unparse_attr(node.func)), "kind": "calls", "line": getattr(node, "lineno", None)})
            # triggers: register(func) / add_tool(tool) → func ─triggers→ caller
            if isinstance(node.func, py_ast.Attribute):
                attr_name = node.func.attr
                if attr_name in _TRIGGER_METHODS or attr_name.startswith("register_"):
                    for arg in node.args:
                        if isinstance(arg, py_ast.Name):
                            edges.append({"from": arg.id, "to": caller, "kind": "triggers", "line": getattr(node, "lineno", None)})
                        elif isinstance(arg, py_ast.Attribute):
                            edges.append({"from": ".".join(_unparse_attr(arg)), "to": caller, "kind": "triggers", "line": getattr(node, "lineno", None)})
            self.generic_visit(node)
    CV().visit(node)
    return edges


def _py_refs(node, source, caller):
    edges = []
    class RV(py_ast.NodeVisitor):
        def visit_Attribute(self, n):
            parts = _unparse_attr(n)
            if len(parts) >= 2 and parts[-2] != "self":
                edges.append({"from": caller, "to": ".".join(parts), "kind": "references", "line": getattr(n, "lineno", None)})
            self.generic_visit(n)
    RV().visit(node)
    for d in getattr(node, "decorator_list", []):
        target = None
        if isinstance(d, py_ast.Name):
            target = d.id
        elif isinstance(d, py_ast.Attribute):
            target = ".".join(_unparse_attr(d))
        elif isinstance(d, py_ast.Call):
            if isinstance(d.func, py_ast.Name):
                target = d.func.id
            elif isinstance(d.func, py_ast.Attribute):
                target = ".".join(_unparse_attr(d.func))
        if target:
            edges.append({"from": caller, "to": target, "kind": "overrides", "line": getattr(node, "lineno", None)})
            edges.append({"from": target, "to": caller, "kind": "triggers", "line": getattr(node, "lineno", None)})
    return edges


def _unparse_attr(node) -> list[str]:
    if isinstance(node, py_ast.Attribute):
        return _unparse_attr(node.value) + [node.attr]
    if isinstance(node, py_ast.Name):
        return [node.id]
    if isinstance(node, py_ast.Call):
        return _unparse_attr(node.func)
    return ["?"]


# ── tree-sitter ───────────────────────────────────────

_TS_PARSERS: dict[str, "tree_sitter.Parser"] = {}

def _get_ts_parser(lang: str):
    if lang in _TS_PARSERS:
        return _TS_PARSERS[lang]
    if lang not in _GRAMMAR_IMPORTS:
        return None
    pkg_name, attr = _GRAMMAR_IMPORTS[lang]
    mod = _try_import_grammar(pkg_name)
    if mod is None:
        return None
    try:
        lang_fn = getattr(mod, attr)
        parser = tree_sitter.Parser(tree_sitter.Language(lang_fn()))
        _TS_PARSERS[lang] = parser
        return parser
    except Exception:
        return None


def _extract_ts(filepath: str, lang: str) -> tuple[list[dict], list[dict]]:
    parser = _get_ts_parser(lang)
    if parser is None:
        return [], []
    with open(filepath, "rb") as f:
        source = f.read()
    tree = parser.parse(source)
    symbols = []
    edges = []
    _walk_ts(tree.root_node, source, symbols, edges, scope="")
    return symbols, edges


def _walk_ts(node, source: bytes, symbols: list, edges: list, scope: str = ""):
    text = lambda n: source[n.start_byte:n.end_byte].decode("utf-8", errors="replace") if n.start_byte < len(source) else "?"
    kind = node.type

    # function / method
    if kind in _TS_FUNCTION_TYPES:
        name_node = node.child_by_field_name("name")
        name = text(name_node) if name_node else "?"
        fn = f"{scope}.{name}" if scope else name
        symbols.append({"name": fn, "kind": "function", "line": node.start_point[0] + 1,
                       "signature": text(node).split("\n")[0][:200], "visibility": "public" if not name.startswith("_") else "private"})

    # class / struct / interface / enum
    elif kind in _TS_CLASS_TYPES:
        name_node = node.child_by_field_name("name")
        name = text(name_node) if name_node else "?"
        cls = f"{scope}.{name}" if scope else name
        symbols.append({"name": cls, "kind": "class", "line": node.start_point[0] + 1,
                       "signature": text(node).split("\n")[0][:200]})
        # extends / implements
        _ts_extends(node, source, cls, edges)
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                _walk_ts(child, source, symbols, edges, cls)

    # import / use / mod
    elif kind in _TS_IMPORT_TYPES and scope:
        _ts_imports(node, source, scope, edges)

    # call expression
    elif kind in ("call_expression", "call"):
        fn_node = node.child_by_field_name("function")
        if fn_node and scope:
            called = text(fn_node)
            if called and called != "?":
                edges.append({"from": scope, "to": called, "kind": "calls", "line": node.start_point[0] + 1})
            # triggers: router.GET(path, handler) → handler ─triggers→ scope
            args_node = node.child_by_field_name("arguments")
            if args_node:
                for arg in args_node.children:
                    if arg.type in ("identifier", "type_identifier"):
                        edges.append({"from": text(arg), "to": scope, "kind": "triggers",
                                     "line": node.start_point[0] + 1})

    # variable decl (for arrow functions assigned to vars)
    elif kind in ("variable_declaration", "lexical_declaration", "let_declaration", "const_declaration"):
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if value_node and value_node.type in _TS_FUNCTION_TYPES:
                    _walk_ts(value_node, source, symbols, edges, scope)
                elif name_node:
                    _walk_ts(child, source, symbols, edges, scope)

    # decorator / annotation → triggers
    name_node = node.child_by_field_name("name")
    deco = node.child_by_field_name("decorator") or node.child_by_field_name("decorators") or node.child_by_field_name("attribute")
    if deco and kind in _TS_FUNCTION_TYPES | _TS_CLASS_TYPES and name_node:
        deco_text = text(deco).lstrip("@#[").split("(")[0].split("\n")[0].strip()
        fn = f"{scope}.{text(name_node)}" if scope else text(name_node)
        if deco_text:
            edges.append({"from": deco_text, "to": fn, "kind": "triggers", "line": node.start_point[0] + 1})

    for child in node.children:
        if kind not in _TS_CLASS_TYPES:
            _walk_ts(child, source, symbols, edges, scope)


def _ts_extends(node, source, cls, edges):
    for child in node.children:
        if child.type in ("base_class_clause", "implements_clause", "extends_clause",
                          "base_class_list", "interface_list", "type_parameters"):
            for gc in child.children:
                if gc.type in ("type_identifier", "identifier", "scoped_identifier",
                               "scoped_type_identifier", "generic_type", "qualified_type"):
                    text = source[gc.start_byte:gc.end_byte].decode("utf-8", errors="replace")
                    if text:
                        edges.append({"from": cls, "to": text, "kind": "extends", "line": node.start_point[0] + 1})


def _ts_imports(node, source, scope, edges):
    seen = set()
    for child in node.children:
        path = _ts_extract_import_path(child, source)
        if path and path not in seen:
            seen.add(path)
            edges.append({"from": scope, "to": path, "kind": "imports", "line": node.start_point[0] + 1})


def _ts_extract_import_path(node, source) -> str | None:
    t = node.type
    text = lambda n: source[n.start_byte:n.end_byte].decode("utf-8", errors="replace") if n.start_byte < len(source) else ""
    # JS/TS: import 'foo' / import { x } from 'foo' / import x from 'foo'
    if t in ("string", "string_literal", "string_fragment"):
        raw = text(node).strip("\"'`")
        return raw if raw else None
    if t in ("import_specification", "import_statement"):
        for child in node.children:
            result = _ts_extract_import_path(child, source)
            if result:
                return result
    # Go: import "fmt" / import ( "fmt"; "os" )
    if t in ("import_spec", "import_spec_list"):
        for child in node.children:
            if child.type == "import_path":
                for gc in child.children:
                    if gc.type in ("string_literal", "interpreted_string_literal", "raw_string_literal"):
                        return text(gc).strip("\"'`")
    # Rust: use std::collections::HashMap
    if t == "use_declaration":
        parts = _ts_collect_identifiers(node)
        if parts:
            return "::".join(parts)
    # Rust: use foo::{bar, baz}
    if t == "scoped_use_list":
        path_node = node.child_by_field_name("path")
        prefix = _ts_collect_identifiers(path_node) if path_node else []
        for child in node.children:
            if child.type in ("identifier", "scoped_identifier"):
                sub = _ts_collect_identifiers(child)
                if prefix and sub:
                    return "::".join(prefix + sub)
    return None


def _ts_collect_identifiers(node) -> list[str]:
    parts = []
    for child in node.children:
        if child.type in ("identifier", "type_identifier"):
            text = child.text.decode("utf-8", errors="replace") if hasattr(child, "text") else ""
            if text:
                parts.append(text)
        elif child.type == "scoped_identifier":
            parts.extend(_ts_collect_identifiers(child))
    return parts


# ── reference resolution ─────────────────────────────

def _resolve_references(conn):
    name_index: dict[str, list[str]] = defaultdict(list)
    for (qn,) in conn.execute("SELECT name FROM symbols").fetchall():
        short = qn.rsplit(".", 1)[-1]
        name_index[short].append(qn)
    updates: list[tuple[str, int]] = []
    for eid, to_sym, _ in conn.execute("SELECT id, to_sym, kind FROM edges WHERE kind='calls' AND resolved=0").fetchall():
        if "." not in to_sym and to_sym in name_index:
            candidates = name_index[to_sym]
            if len(candidates) == 1:
                updates.append((candidates[0], eid))
    if updates:
        conn.executemany("UPDATE edges SET to_sym=?, resolved=1 WHERE id=?", updates)

    # Phase 2: cross-file import resolution (optimized: batch resolve)
    from collections import defaultdict as dd2

    file_imports: dict[str, list[str]] = dd2(list)
    all_imports = conn.execute("SELECT file, to_sym FROM edges WHERE kind='imports'").fetchall()
    for f, imp in all_imports:
        file_imports[f].append(imp)

    def _file_to_module(f: str) -> str:
        if f.endswith(".py"):
            f = f[:-3]
        return f.replace("/", ".")

    # (module_path, short_name) -> candidate full names
    module_map: dict[tuple[str, str], list[str]] = dd2(list)
    # (import_path, short_name) -> candidate full names (for dotted symbol names)
    symbol_prefix_map: dict[tuple[str, str], list[str]] = dd2(list)
    for qn, f in conn.execute("SELECT name, file FROM symbols").fetchall():
        short = qn.rsplit(".", 1)[-1]
        module_map[(_file_to_module(f), short)].append(qn)
        parts = qn.split(".")
        for i in range(1, len(parts)):
            prefix = ".".join(parts[:i])
            symbol_prefix_map[(prefix, short)].append(qn)

    unresolved = conn.execute(
        "SELECT e.id, e.from_sym, e.to_sym, s.file "
        "FROM edges e JOIN symbols s ON s.name=e.from_sym "
        "WHERE e.kind='calls' AND e.resolved=0"
    ).fetchall()

    updates = []
    for eid, from_sym, to_sym, from_file in unresolved:
        imports = file_imports.get(from_file)
        if not imports:
            continue
        candidates: set[str] = set()
        for imp in imports:
            if "." in imp:
                imp_module, imp_name = imp.rsplit(".", 1)
                # from module import name
                if to_sym == imp_name:
                    candidates.update(module_map.get((imp_module, to_sym), []))
                # import module; module.foo() 或 from module import Class; Class.method()
                candidates.update(module_map.get((imp_module, to_sym), []))
            else:
                # import module; module.foo()
                if to_sym.startswith(imp + ".") or "." in to_sym:
                    candidates.update(module_map.get((imp, to_sym), []))
            # fallback: original prefix matching on dotted symbol names
            candidates.update(symbol_prefix_map.get((imp, to_sym), []))
        if len(candidates) == 1:
            updates.append((candidates.pop(), eid))
    if updates:
        conn.executemany("UPDATE edges SET to_sym=?, resolved=1 WHERE id=?", updates)

    # Phase 3: self.method() / cls.method() resolution
    unresolved = conn.execute(
        "SELECT e.id, e.from_sym, e.to_sym FROM edges e "
        "WHERE e.kind='calls' AND e.resolved=0 AND e.to_sym NOT LIKE '%.%' AND e.to_sym NOT LIKE '%(%'"
    ).fetchall()
    updates = []
    for eid, from_sym, to_sym in unresolved:
        cls_prefix = _class_of(from_sym)
        if not cls_prefix:
            continue
        candidate = f"{cls_prefix}.{to_sym}"
        sr = conn.execute("SELECT name FROM symbols WHERE name=? LIMIT 1", (candidate,)).fetchone()
        if sr:
            updates.append((sr[0], eid))
    if updates:
        conn.executemany("UPDATE edges SET to_sym=?, resolved=1 WHERE id=?", updates)


# ── BFS ───────────────────────────────────────────────

def _class_of(qualified_name: str) -> str | None:
    if "." not in qualified_name:
        return None
    parts = qualified_name.rsplit(".", 1)
    return parts[0]

def _result_files(result: dict) -> list[str]:
    """从 explore 结果中收集涉及的文件路径（用于索引过期探测）。"""
    files: list[str] = []

    def _add(loc):
        if isinstance(loc, dict):
            f = loc.get("file")
            if f:
                files.append(f)

    for s in result.get("symbols") or []:
        _add(s)
    grouped = result.get("grouped_by_file")
    if isinstance(grouped, dict):
        files.extend(str(k) for k in grouped.keys())
    for container in (result, result.get("related_symbols")):
        if not isinstance(container, dict):
            continue
        for key in ("caller_locations", "callee_locations"):
            for loc in container.get(key) or []:
                _add(loc)
    return files


def _bfs_path(conn, start: str, end: str, max_depth: int = 6) -> list[str] | None:
    from collections import deque
    q = deque()
    q.append((start, [start], {start}))
    while q:
        node, path, visited = q.popleft()
        if len(path) > max_depth:
            continue
        for (nxt,) in conn.execute("SELECT to_sym FROM edges WHERE from_sym=? AND kind IN ('calls','extends','triggers','imports')", (node,)):
            if nxt == end:
                return path + [nxt]
            if nxt not in visited:
                visited.add(nxt)
                q.append((nxt, path + [nxt], visited))
    return None


def _bfs_partial(conn, start: str, end: str, max_depth: int = 8) -> dict | None:
    from collections import deque
    q = deque()
    q.append((start, [start], {start}))
    furthest = start
    furthest_path = [start]
    while q:
        node, path, visited = q.popleft()
        if len(path) > max_depth:
            continue
        if len(path) > len(furthest_path):
            furthest, furthest_path = node, path
        rows = conn.execute("SELECT to_sym FROM edges WHERE from_sym=? AND kind IN ('calls','extends','triggers','imports')", (node,)).fetchall()
        if not rows:
            return {"path": path, "break_at": node,
                    "reason": f"{node} 没有静态调用出边（可能通过回调、动态调用或 AstrBot 框架路由连接）"}
        for (nxt,) in rows:
            if nxt == end:
                return {"path": path + [nxt], "break_at": "", "reason": "found"}
            if nxt not in visited:
                visited.add(nxt)
                q.append((nxt, path + [nxt], visited))
    return {"path": furthest_path, "break_at": furthest,
            "reason": f"达到最大深度 {max_depth}，在 {furthest} 处中断"}


def _bfs_all_callers(conn, target: str, max_depth: int = 3) -> list[str]:
    from collections import deque
    callers: list[str] = []
    visited: set[str] = {target}
    q = deque([(target, 0)])
    while q:
        node, d = q.popleft()
        if d >= max_depth:
            continue
        for (caller,) in conn.execute("SELECT from_sym FROM edges WHERE to_sym=? AND kind IN ('calls','extends','triggers','imports')", (node,)):
            if caller not in visited:
                visited.add(caller)
                callers.append(caller)
                q.append((caller, d + 1))
    return callers


def _route_query(query: str) -> tuple[str, re.Match | None]:
    for pattern, qtype in _QUERY_ROUTES:
        m = pattern.search(query)
        if m:
            return qtype, m
    return "explore", None
