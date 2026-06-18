"""
op_log - local SQLite audit trail for tool calls.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import get_config, get_plugin_dir


_SESSION_ID = uuid.uuid4().hex


def reset_session() -> str:
    """Rotate the session ID. Called on plugin (re)load so each reload gets its own audit segment."""
    global _SESSION_ID
    _SESSION_ID = uuid.uuid4().hex
    return _SESSION_ID


_SENSITIVE_KEYS = ("token", "secret", "password", "passwd", "pwd", "key", "private_key", "credential", "api_key", "authorization", "cookie")


def _db_path() -> Path:
    cfg = get_config()
    explicit = cfg.get("op_log_db", "")
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = get_plugin_dir() or Path.cwd()
    return Path(root).expanduser().resolve() / ".irmia" / "op_log.db"


_INITIALIZED_DB: str | None = None
_INIT_LOCK = threading.Lock()


def _ensure_db() -> None:
    """Create tables and indexes for the current database path.
    Tracks the last-initialized path so tests can safely switch DBs.
    """
    global _INITIALIZED_DB
    path = _db_path()
    if _INITIALIZED_DB == str(path):
        return
    with _INIT_LOCK:
        if _INITIALIZED_DB == str(path):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS op_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                params_summary TEXT,
                file_paths TEXT,
                result TEXT NOT NULL,
                error_msg TEXT,
                duration_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_op_log_session ON op_log(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_op_log_tool ON op_log(tool_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_op_log_created ON op_log(created_at)")
            conn.commit()
        finally:
            conn.close()
        _INITIALIZED_DB = str(path)


# 连接池：线程级复用 + 单例管理
_CONN_LOCAL = threading.local()
_CONN_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    _ensure_db()
    # 检查当前线程是否已有连接
    if hasattr(_CONN_LOCAL, 'conn') and _CONN_LOCAL.conn is not None:
        try:
            _CONN_LOCAL.conn.execute("SELECT 1")
            return _CONN_LOCAL.conn
        except sqlite3.Error:
            pass  # 连接已失效，重新创建
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    _CONN_LOCAL.conn = conn
    return conn


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    parts = lowered.replace("-", "_").split("_")
    if any(marker in parts for marker in _SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, str):
        return value if len(value) <= 160 else value[:157] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


def _params_summary(params: dict[str, Any]) -> str:
    if not isinstance(params, dict):
        return ""
    safe = {str(k): _redact_value(str(k), v) for k, v in params.items()}
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:2000]


def _extract_file_paths(params: dict[str, Any]) -> str:
    if not isinstance(params, dict):
        return ""
    paths: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value:
            paths.append(value[:260])
        elif isinstance(value, list):
            for item in value:
                add(item)

    for key, value in params.items():
        lowered = str(key).lower()
        if "file" in lowered or "path" in lowered or lowered in ("cwd", "project_dir"):
            add(value)
    return ",".join(paths[:10])


def _result_status(result: Any) -> tuple[str, str]:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            return "error", str(result)[:500]
    if isinstance(result, dict):
        if result.get("timeout"):
            return "timeout", str(result.get("error", ""))[:500]
        if result.get("ok") is False:
            return "error", str(result.get("error", ""))[:500]
        return "ok", ""
    return "ok", ""


import atexit


# 批量写入缓冲
_BATCH: list[tuple] = []
_BATCH_LOCK = threading.Lock()
_BATCH_SIZE = 10
_BATCH_FLUSH_INTERVAL = 5.0
_LAST_FLUSH = 0.0


# 注册 atexit 确保进程退出时刷盘
atexit.register(lambda: _flush(force=True))


def _flush(force: bool = False) -> None:
    """将缓冲的日志写入数据库。"""
    global _BATCH, _LAST_FLUSH
    with _BATCH_LOCK:
        if not _BATCH:
            return
        if not force and len(_BATCH) < _BATCH_SIZE:
            now = time.time()
            if now - _LAST_FLUSH < _BATCH_FLUSH_INTERVAL:
                return
        
        batch_copy = _BATCH[:]
        _BATCH = []
        _LAST_FLUSH = time.time()
    
    conn = None
    try:
        conn = _connect()
        conn.executemany(
            "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) "
            "VALUES(?,?,?,?,?,?,?)",
            batch_copy,
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            if hasattr(_CONN_LOCAL, 'conn'):
                _CONN_LOCAL.conn = None


def record(tool_name: str, params: dict[str, Any], result: Any, duration_ms: int, *, sync: bool = False) -> None:
    """Best-effort insert. Never raise to callers.
    
    sync=True: 强制立即刷盘（用于关键操作如 safe_edit/safe_write）。
    """
    try:
        status, error_msg = _result_status(result)
        row = (
            _SESSION_ID,
            tool_name,
            _params_summary(params),
            _extract_file_paths(params),
            status,
            error_msg,
            int(duration_ms),
        )
        with _BATCH_LOCK:
            _BATCH.append(row)
        _flush(force=sync)
    except Exception:
        pass


def record_exception(tool_name: str, params: dict[str, Any], exc: Exception, duration_ms: int) -> None:
    try:
        row = (
            _SESSION_ID,
            tool_name,
            _params_summary(params),
            _extract_file_paths(params),
            "error",
            str(exc)[:500],
            int(duration_ms),
        )
        with _BATCH_LOCK:
            _BATCH.append(row)
        _flush()
    except Exception:
        pass


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _clamp_limit(limit: int) -> int:
    try:
        limit = int(limit)
    except Exception:
        limit = 10
    return max(1, min(limit, 100))


def query(action: str = "recent", limit: int = 10, file: str = "", tool: str = "", session_id: str = "") -> dict:
    action = (action or "recent").strip().lower()
    limit = _clamp_limit(limit)
    start = time.monotonic()
    
    # 查询前先刷新缓冲
    _flush(force=True)
    
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM op_log").fetchone()[0]
        if action == "recent":
            clauses = []
            params: list[Any] = []
            if tool:
                clauses.append("tool_name=?")
                params.append(tool)
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            where = "WHERE " + " AND ".join(clauses) if clauses else ""
            rows = conn.execute(
                f"SELECT id, created_at, session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms "
                f"FROM op_log {where} ORDER BY id DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return {"ok": True, "total_entries": total, "sessions": sessions, "recent": _rows_to_dicts(rows)}
        if action == "errors":
            rows = conn.execute(
                "SELECT id, created_at, session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms "
                "FROM op_log WHERE result IN ('error','timeout') ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return {"ok": True, "total_entries": total, "sessions": sessions, "errors": _rows_to_dicts(rows)}
        if action == "file":
            if not file:
                return {"ok": False, "error": "file is required for action=file"}
            rows = conn.execute(
                "SELECT id, created_at, session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms "
                "FROM op_log WHERE file_paths LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{file}%", limit),
            ).fetchall()
            return {"ok": True, "total_entries": total, "sessions": sessions, "file": file, "entries": _rows_to_dicts(rows)}
        if action == "stats":
            rows = conn.execute(
                "SELECT tool_name, result, COUNT(*) AS count, AVG(duration_ms) AS avg_duration_ms "
                "FROM op_log GROUP BY tool_name, result ORDER BY count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return {
                "ok": True,
                "total_entries": total,
                "sessions": sessions,
                "stats": _rows_to_dicts(rows),
                "duration_s": round(time.monotonic() - start, 3),
            }
        return {"ok": False, "error": f"unknown action: {action}"}
    finally:
        conn.close()
        if hasattr(_CONN_LOCAL, 'conn'):
            _CONN_LOCAL.conn = None
