"""
dir_list — 目录列表。
纯 os.scandir，结构化返回，比 shell dir 快 10 倍。
"""

import os
from datetime import datetime, timezone
from pathlib import Path


def list_dir(
    path: str, pattern: str = "*", max_depth: int = 1, show_hidden: bool = False
) -> dict:
    """
    列出目录内容。

    Args:
        path: 目录路径
        pattern: 文件名匹配（支持 * ? [seq]），如 "*.py" "test_*"
        max_depth: 最大深度，1=仅当前目录，2=含一级子目录
        show_hidden: 是否显示隐藏文件（. 开头）
    """
    p = Path(path).resolve()
    if not p.exists():
        return {"ok": False, "error": f"路径不存在: {path}"}
    if not p.is_dir():
        return {"ok": False, "error": f"不是目录: {path}"}

    import fnmatch

    entries = []
    # H9: symlink 循环检测
    visited_inodes: set[int] = set()

    def _scan(dirpath: Path, depth: int):
        if depth > max_depth:
            return
        # H9: 检测并跳过循环
        try:
            st = dirpath.stat()
            inode_key = (st.st_dev, st.st_ino)
            if inode_key in visited_inodes:
                return
            visited_inodes.add(inode_key)
        except OSError:
            pass
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith(".") and not show_hidden:
                        continue
                    full = Path(entry.path)
                    info = {
                        "name": name,
                        "path": str(full),
                        "type": "dir" if entry.is_dir() else "file",
                    }
                    try:
                        st = entry.stat()
                        info["mtime"] = datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc
                        ).isoformat()
                        if entry.is_file():
                            info["size"] = st.st_size
                    except OSError:
                        if entry.is_file():
                            info["size"] = 0
                    entries.append(info)

                    if entry.is_dir() and depth < max_depth:
                        _scan(full, depth + 1)
        except PermissionError:
            pass

    _scan(p, 1)

    # 过滤 pattern
    if pattern != "*":
        entries = [e for e in entries if fnmatch.fnmatch(e["name"], pattern)]

    # 排序：目录优先，然后按名称
    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))

    file_count = sum(1 for e in entries if e["type"] == "file")
    dir_count = sum(1 for e in entries if e["type"] == "dir")

    return {
        "ok": True,
        "path": str(p),
        "count": len(entries),
        "files": file_count,
        "dirs": dir_count,
        "entries": entries[:200],
        "truncated": len(entries) > 200,
    }
