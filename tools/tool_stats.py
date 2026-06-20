"""
tool_stats — 工具调用统计。
纯内存计数器，零依赖。record() 静默失败，不影响工具调用。
"""

from collections import defaultdict
import time

_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "last": 0.0})


def record(name: str) -> None:
    try:
        entry = _stats[name]
        entry["count"] += 1
        entry["last"] = time.time()
    except Exception:
        pass


def reset() -> None:
    """清空所有统计数据（用于测试隔离）。"""
    _stats.clear()


def snapshot() -> dict:
    return {
        "ok": True,
        "tools": dict(_stats),
        "total_calls": sum(v["count"] for v in _stats.values()),
    }
