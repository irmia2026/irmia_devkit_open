"""
op_log - local SQLite audit trail for tool calls.
"""

from __future__ import annotations

import json
import sqlite3
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

# 内容型参数名标记：匹配到时，超过 80 字符的字符串值不存原文，
# 仅存长度摘要 <str N chars>，避免 safe_edit 的 old/new 等大量文本回流上下文。
_CONTENT_KEY_MARKERS = ("old", "new", "content", "text", "body", "source", "data", "patch", "diff", "stdin", "code", "snippet", "description", "message", "output", "input")


def _db_path() -> Path:
    cfg = get_config()
    explicit = cfg.get("op_log_db", "")
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = get_plugin_dir() or Path.cwd()
    return Path(root).expanduser().resolve() / ".irmia" / "op_log.db"


_INITIALIZED_DB: str | None = None


def _ensure_db() -> None:
    """Create tables and indexes for the current database path.
    Tracks the last-initialized path so tests can safely switch DBs.
    """
    global _INITIALIZED_DB
    path = _db_path()
    if _INITIALIZED_DB == str(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
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
    conn.close()
    _INITIALIZED_DB = str(path)


def _connect() -> sqlite3.Connection:
    _ensure_db()
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    # 拆分为下划线分隔的词，精确匹配防止 key→keyboard/monkey 过度脱敏
    parts = lowered.replace("-", "_").split("_")
    if any(marker in parts for marker in _SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, str):
        # 内容型参数：超过阈值后只存长度摘要，不存原文
        if len(value) > 80 and any(marker in parts for marker in _CONTENT_KEY_MARKERS):
            return f"<str {len(value)} chars>"
        return value if len(value) <= 160 else value[:157] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


_MAX_PATH_LOG_LEN = 4096  # 审计日志中路径字段长度上限


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
            paths.append(value[:_MAX_PATH_LOG_LEN])
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


def record(tool_name: str, params: dict[str, Any], result: Any, duration_ms: int) -> None:
    """Best-effort insert. Never raise to callers."""
    conn = None
    try:
        status, error_msg = _result_status(result)
        conn = _connect()
        conn.execute(
            "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                _SESSION_ID,
                tool_name,
                _params_summary(params),
                _extract_file_paths(params),
                status,
                error_msg,
                int(duration_ms),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()


def record_exception(tool_name: str, params: dict[str, Any], exc: Exception, duration_ms: int) -> None:
    conn = None
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO op_log(session_id, tool_name, params_summary, file_paths, result, error_msg, duration_ms) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                _SESSION_ID,
                tool_name,
                _params_summary(params),
                _extract_file_paths(params),
                "error",
                str(exc)[:500],
                int(duration_ms),
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]


def _clamp_limit(limit: int) -> int:
    try:
        limit = int(limit)
    except Exception:
        limit = 10
    return max(1, min(limit, 100))


def query(action: str = "recent", limit: int = 10, file: str = "", tool_name: str = "", session_id: str = "") -> dict:
    action = (action or "recent").strip().lower()
    limit = _clamp_limit(limit)
    start = time.monotonic()
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM op_log").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM op_log").fetchone()[0]
        if action == "recent":
            clauses = []
            params: list[Any] = []
            if tool_name:
                clauses.append("tool_name=?")
                params.append(tool_name)
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
            # 整体聚合
            agg = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN result='ok' THEN 1 ELSE 0 END) AS ok_count, "
                "SUM(CASE WHEN result='error' THEN 1 ELSE 0 END) AS error_count, "
                "SUM(CASE WHEN result='timeout' THEN 1 ELSE 0 END) AS timeout_count, "
                "AVG(duration_ms) AS avg_duration_ms "
                "FROM op_log"
            ).fetchone()
            total_calls = agg["total"]
            ok_count = agg["ok_count"] or 0
            error_count = agg["error_count"] or 0
            timeout_count = agg["timeout_count"] or 0
            # 按工具细分
            rows = conn.execute(
                "SELECT tool_name, result, COUNT(*) AS count, AVG(duration_ms) AS avg_duration_ms "
                "FROM op_log GROUP BY tool_name, result ORDER BY count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return {
                "ok": True,
                "total_entries": total,
                "sessions": sessions,
                "total_calls": total_calls,
                "ok_count": ok_count,
                "error_count": error_count,
                "timeout_count": timeout_count,
                "success_rate": round(ok_count / max(total_calls, 1) * 100, 1),
                "avg_duration_ms": round(agg["avg_duration_ms"] or 0, 1),
                "stats": _rows_to_dicts(rows),
                "duration_s": round(time.monotonic() - start, 3),
            }
        return {"ok": False, "error": f"unknown action: {action}"}
    finally:
        conn.close()
