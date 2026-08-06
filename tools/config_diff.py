"""
config_diff — 配置文件结构化差异比较。
支持 JSON / YAML，按 key 比较而非逐行 diff。
"""

import json
from pathlib import Path

from ._file_utils import read_file

# 单文件大小上限
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# value 序列化后超过此长度则截断
MAX_VALUE_CHARS = 500


def _truncate_value(value):
    """value 序列化后超过 500 字符时截断为 "<截断: 前500字符...>" 形式。"""
    s = json.dumps(value, ensure_ascii=False, default=str)
    if len(s) > MAX_VALUE_CHARS:
        return f"<截断: {s[:MAX_VALUE_CHARS]}...>"
    return value


def diff(file_a: str, file_b: str) -> dict:
    """比较两个配置文件的结构化差异。

    Args:
        file_a: 第一个配置文件路径 (.json / .yaml / .yml)
        file_b: 第二个配置文件路径
    """
    pa, pb = Path(file_a), Path(file_b)
    if not pa.exists():
        return {"ok": False, "error": f"文件不存在: {file_a}"}
    if not pb.exists():
        return {"ok": False, "error": f"文件不存在: {file_b}"}

    for p, name in ((pa, file_a), (pb, file_b)):
        try:
            size = p.stat().st_size
        except OSError as e:
            return {"ok": False, "error": f"无法读取文件信息: {name}: {e}"}
        if size > MAX_FILE_SIZE:
            return {
                "ok": False,
                "error": f"文件过大: {name}（{size} 字节）超过 10MB 上限",
                "file": name,
                "size": size,
                "max_size": MAX_FILE_SIZE,
            }

    try:
        obj_a = _load(pa)
    except ImportError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"无法解析 {file_a}: {e}"}
    try:
        obj_b = _load(pb)
    except ImportError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"无法解析 {file_b}: {e}"}

    if not isinstance(obj_a, dict) or not isinstance(obj_b, dict):
        return {"ok": False, "error": "仅支持顶层为对象的配置文件"}

    all_keys = set(obj_a.keys()) | set(obj_b.keys())
    added = {}
    removed = {}
    changed = {}
    unchanged = 0

    for key in sorted(all_keys):
        in_a = key in obj_a
        in_b = key in obj_b
        if in_a and not in_b:
            removed[key] = _truncate_value(obj_a[key])
        elif not in_a and in_b:
            added[key] = _truncate_value(obj_b[key])
        elif obj_a[key] != obj_b[key]:
            changed[key] = {"old": _truncate_value(obj_a[key]), "new": _truncate_value(obj_b[key])}
        else:
            unchanged += 1

    result = {
        "ok": True,
        "file_a": file_a,
        "file_b": file_b,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
    }
    total = len(added) + len(removed) + len(changed) + unchanged
    if total == unchanged:
        result["proposal"] = "两个配置文件完全相同——无需合并/比较。"
    elif changed:
        result["proposal"] = (
            f"{len(changed)}个key变更, {len(added)}个新增, {len(removed)}个删除。"
        )
        result["options"] = ["逐个应用到目标文件", "仅查看有差别的 key"]
    else:
        result["proposal"] = f"{len(added)}个新增, {len(removed)}个删除。"
        result["options"] = ["查看全部差异"]
    return result


def _load(p: Path) -> dict:
    text = read_file(p)
    suffix = p.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("pyyaml 未安装，请运行: pip install pyyaml")
        return yaml.safe_load(text)
    raise ValueError(f"不支持的文件类型: {suffix}")
