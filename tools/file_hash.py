"""
file_hash — 文件哈希计算。
md5/sha1/sha256，纯 hashlib 标准库。
"""

import hashlib
from pathlib import Path

ALGOS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
}


def compute(filepath: str, algo: str = "sha256") -> dict:
    """计算文件哈希值。算法: md5/sha1/sha256（默认）。"""
    p = Path(filepath)
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    if algo not in ALGOS:
        return {
            "ok": False,
            "error": f"不支持的算法: {algo}，可选: {list(ALGOS.keys())}",
        }

    try:
        h = ALGOS[algo]()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return {
            "ok": True,
            "file": str(p.resolve()),
            "algo": algo,
            "hash": h.hexdigest(),
            "size": p.stat().st_size,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
