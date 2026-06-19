"""
db_query — SQLite 只读查询。
参数化防注入，仅允许 SELECT/PRAGMA，只读模式打开。
"""

import sqlite3
from pathlib import Path

from ._helpers import proposal_reply


def query(db_path: str, sql: str, params: list = None) -> dict:
    """只读查询 SQLite 数据库，不修改数据。

    Args:
        db_path: SQLite 数据库文件路径
        sql: SELECT 或 PRAGMA 查询语句
        params: 查询参数列表，如 [42, "active"]
    """
    p = Path(db_path)
    if not p.exists():
        return {"ok": False, "error": f"数据库不存在: {db_path}"}

    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("PRAGMA"):
        return {"ok": False, "error": "仅允许 SELECT 和 PRAGMA 语句（只读查询）"}

    params = params or []
    try:
        uri_path = str(p.resolve()).replace("\\", "/")
        with sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(r) for r in cur.fetchall()]
        return {
            "ok": True,
            "columns": columns,
            "rows": rows[:200],
            "count": len(rows),
            "truncated": len(rows) > 200,
        }
    except sqlite3.Error as e:
        return proposal_reply(
            False,
            "SQLite 查询错误——检查表名/列名是否正确",
            error=f"SQLite 错误: {e}",
            evidence={"sql": sql[:200], "params": params},
            options=["用 PRAGMA table_info 确认 schema", "检查表名和列名"],
            next_call={
                "tool": "db_query",
                "params": {
                    "db_path": db_path,
                    "sql": "SELECT name FROM sqlite_master WHERE type='table'",
                },
            },
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}
