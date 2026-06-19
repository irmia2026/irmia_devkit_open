"""
file_remove — 文件/目录删除工具。
自带路径沙箱和批量确认，防误删。
"""
import os
from pathlib import Path

from ._helpers import proposal_reply
from ._file_utils import human_size

_FORBIDDEN_PREFIXES = [
    "C:/Windows/System32", "C:/Windows/SysWOW64",
    "C:/Program Files", "C:/Program Files (x86)",
    "C:/Users/All Users",
    "/bin", "/boot", "/dev", "/etc", "/lib", "/proc", "/root", "/sbin", "/sys", "/usr", "/var",
]



def remove(path: str, confirm: bool = False, max_items: int = 50) -> dict:
    """删除文件或目录，自带沙箱和批量确认。

    Args:
        path: 文件或目录路径
        confirm: 目录删除需显式确认
        max_items: 目录超过此文件数时返回提案不执行
    """
    p = Path(path).resolve()

    raw = str(Path(path))
    if any(part == ".." for part in raw.replace("\\", "/").split("/")):
        return {"ok": False, "error": "路径包含 .. 穿越，已被拒绝"}

    if not p.exists():
        return {"ok": False, "error": f"路径不存在: {path}"}

    path_str = str(p).replace("\\", "/")
    for forbidden in _FORBIDDEN_PREFIXES:
        if path_str.lower().startswith(forbidden.lower() + "/") or path_str.lower() == forbidden.lower():
            return {"ok": False, "error": f"禁止操作系统目录: {path}",
                    "proposal": "路径位于受保护的系统目录中，删除操作已被拦截。",
                    "evidence": {"path": path, "blocked_by": forbidden}}

    if p.is_file():
        try:
            size = p.stat().st_size
            os.remove(p)
            return {"ok": True, "deleted": 1, "freed": human_size(size), "errors": []}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    if p.is_dir():
        if not confirm:
            return proposal_reply(False,
                f"确认删除目录？目录路径: {path}。请设置 confirm=true。",
                error="目录删除需二次确认",
                options=["confirm_delete", "cancel"])

        # 单次遍历：计数 + 累加大小
        file_count = 0
        total_size = 0
        for f in p.rglob("*"):
            if f.is_file():
                file_count += 1
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass
        if file_count > max_items:
            return proposal_reply(False,
                f"目录含 {file_count} 个文件，超过上限 {max_items}。确认删除？",
                error=f"目录含 {file_count} 个文件，超过批量限制 ({max_items})",
                evidence={"file_count": file_count, "directory": str(p)},
                options=["confirm_batch_delete", "cancel"])

        errors = []

        try:
            for root, dirs, files in os.walk(p, topdown=False):
                for name in files:
                    fp = os.path.join(root, name)
                    try:
                        os.remove(fp)
                    except OSError as e:
                        errors.append({"path": fp, "reason": str(e)})
                for name in dirs:
                    dp = os.path.join(root, name)
                    try:
                        os.rmdir(dp)
                    except OSError as e:
                        errors.append({"path": dp, "reason": str(e)})
            try:
                os.rmdir(p)
            except OSError as e:
                errors.append({"path": str(p), "reason": str(e)})

            return {
                "ok": True,
                "deleted": file_count - len(errors),
                "freed": human_size(total_size),
                "errors": errors[:10],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"不是文件也不是目录: {path}"}
