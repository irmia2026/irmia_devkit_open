"""
disk_info — 磁盘空间查询。
Windows: 遍历 A-Z 盘符。Linux/macOS: 从 /proc/mounts 或 mount 命令枚举挂载点。
"""

import os
import shutil
import subprocess


def info() -> dict:
    """返回所有磁盘分区信息。"""
    drives = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            try:
                usage = shutil.disk_usage(path)
                drives.append(_fmt_drive(path, usage))
            except (FileNotFoundError, OSError):
                continue
    else:
        drives = _posix_mounts()

    if not drives:
        return {"ok": False, "error": "无法获取磁盘信息"}

    return {"ok": True, "drives": drives}


def _posix_mounts() -> list[dict]:
    """枚举 Linux/macOS 所有挂载点的磁盘使用情况。"""
    mounts = []
    seen = set()
    mount_points = _get_mount_points()
    for mp in mount_points:
        try:
            usage = shutil.disk_usage(mp)
            key = mp  # 按挂载点路径去重，避免同容量不同挂载点被误跳过
            if key in seen:
                continue
            seen.add(key)
            mounts.append(_fmt_drive(mp, usage))
        except (FileNotFoundError, OSError):
            continue
    return mounts


def _get_mount_points() -> list[str]:
    """从 /proc/mounts 或 mount 命令获取挂载点列表。过滤伪文件系统。"""
    # 过滤掉的伪文件系统
    _SKIP_FS = {"proc", "sysfs", "devfs", "devtmpfs", "tmpfs", "devpts",
                "cgroup", "cgroup2", "pstore", "bpf", "debugfs", "tracefs",
                "fusectl", "configfs", "securityfs", "hugetlbfs", "mqueue",
                "autofs", "rpc_pipefs", "binfmt_misc"}

    mount_points = []
    # Layer 1: /proc/mounts (Linux)
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    device, mp, fstype = parts[0], parts[1], parts[2]
                    if fstype in _SKIP_FS:
                        continue
                    if mp.startswith("/snap/") or mp.startswith("/var/lib/docker/"):
                        continue
                    mount_points.append(mp)
    except (FileNotFoundError, PermissionError):
        pass

    if not mount_points:
        # Layer 2: mount 命令 (macOS/BSD)
        try:
            r = subprocess.run(["mount"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.split("\n"):
                if " on " not in line:
                    continue
                parts = line.split(" on ", 1)
                if len(parts) >= 2:
                    mp = parts[1].split(" (", 1)[0].strip()
                    mount_points.append(mp)
        except Exception:
            pass

    # 至少要有 /
    if "/" not in mount_points:
        mount_points.append("/")

    return mount_points


def _fmt_drive(path: str, usage) -> dict:
    return {
        "drive": path,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(usage.used / usage.total * 100, 1) if usage.total > 0 else 0,
    }
