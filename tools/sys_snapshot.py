"""
sys_snapshot — 系统快照。
CPU/内存/进程数/开机时长。Windows: systeminfo+tasklist | Linux: /proc。
"""

import os
import platform
from datetime import datetime, timedelta

from ._helpers import _run_cmd


def snapshot() -> dict:
    """获取系统整体状态快照。"""
    info = {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "time": datetime.now().isoformat(),
    }

    try:
        info["cpu_cores"] = os.cpu_count()
    except Exception:
        info["cpu_cores"] = None

    if os.name == "nt":
        _windows_info(info)
    elif platform.system() == "Darwin":
        info["total_memory_mb"] = None
        info["available_memory_mb"] = None
        info["process_count"] = None
        info["_note"] = "macOS 不支持完整系统快照，欢迎提交 PR"
    else:
        _linux_info(info)

    return {"ok": True, "info": info}


def _windows_info(info: dict) -> None:
    result = _run_cmd(["systeminfo"], timeout=15, encoding="gbk")
    if result["ok"]:
        for line in result["stdout"].split("\n"):
            line = line.strip()
            if "物理内存总量" in line or "Total Physical Memory" in line:
                info["total_memory_mb"] = _extract_mb(line)
            if "可用的物理内存" in line or "Available Physical Memory" in line:
                info["available_memory_mb"] = _extract_mb(line)
            if "系统启动时间" in line or "System Boot Time" in line:
                info["boot_time"] = line.split(":", 1)[-1].strip()
    else:
        info["total_memory_mb"] = None
        info["available_memory_mb"] = None

    result = _run_cmd(["tasklist", "/FO", "CSV", "/NH"], timeout=10, encoding="gbk")
    if result["ok"]:
        info["process_count"] = len([l for l in result["stdout"].split("\n") if l.strip()])
    else:
        info["process_count"] = None


def _linux_info(info: dict) -> None:
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    info["total_memory_mb"] = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    info["available_memory_mb"] = int(line.split()[1]) // 1024

        with open("/proc/uptime", "r") as f:
            uptime_s = float(f.read().split()[0])
            info["boot_time"] = str(datetime.now() - timedelta(seconds=uptime_s))

        info["process_count"] = sum(1 for d in os.listdir("/proc") if d.isdigit())
    except Exception as e:
        info["total_memory_mb"] = None
        info["available_memory_mb"] = None
        info["process_count"] = None
        info["_linux_error"] = str(e)


def _extract_mb(line: str) -> int | None:
    """从 systeminfo 行提取内存 MB 数。"""
    try:
        parts = line.replace(",", "").split()
        for i, p in enumerate(parts):
            if "MB" in p:
                return int(parts[i - 1]) if i > 0 else None
        return None
    except Exception:
        return None
