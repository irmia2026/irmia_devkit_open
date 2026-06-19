"""
file_zip — ZIP 打包/解压。
纯 zipfile 标准库，压缩率可选。
"""

import os
import zipfile
from pathlib import Path

from ._file_utils import SymlinkGuard


def compress(files_or_dir: list[str], output: str) -> dict:
    """打包文件/目录到 ZIP。"""
    output_path = Path(output)
    guard = SymlinkGuard()
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files_or_dir:
                p = Path(path)
                if p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file() and not guard.is_seen(str(f)):
                            zf.write(f, f.relative_to(p))
                elif p.is_file():
                    zf.write(p, p.name)
                else:
                    return {"ok": False, "error": f"路径不存在: {path}"}

        return {
            "ok": True,
            "output": str(output_path.resolve()),
            "size": output_path.stat().st_size,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def extract(zip_file: str, output_dir: str) -> dict:
    """解压 ZIP 到指定目录。"""
    p = Path(zip_file)
    if not p.exists():
        return {"ok": False, "error": f"ZIP 文件不存在: {zip_file}"}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(p, "r") as zf:
            names = zf.namelist()
            # Zip-slip 防护：确保所有成员在目标目录内
            safe_out = out.resolve()
            for name in names:
                member_path = (safe_out / name).resolve()
                if (
                    not str(member_path).startswith(str(safe_out) + os.sep)
                    and member_path != safe_out
                ):
                    return {
                        "ok": False,
                        "error": f"安全拦截：ZIP 条目试图逃逸目录 — {name}",
                    }
            zf.extractall(out)

        return {
            "ok": True,
            "output_dir": str(out.resolve()),
            "files_extracted": len(names),
            "files": names[:50],
            "truncated": len(names) > 50,
        }
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是有效的 ZIP 文件"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
