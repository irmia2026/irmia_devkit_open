"""
json_query — jq 式 JSON 查询。
纯 Python dict/list 遍历，支持点路径和数组索引。
"""

import json

from ._helpers import proposal_reply


def query(data: str, path: str) -> dict:
    """
    用点路径查询 JSON 字符串。

    路径语法:
        key.subkey        → 嵌套对象
        key[0]            → 数组索引
        key[0].name       → 数组中对象的字段
        [*].name          → 数组所有元素的 name 字段（返回列表）
        [-1]              → 最后一个元素

    Examples:
        "data.items[0].name"   → 取第一个 item 的 name
        "users[*].email"       → 取所有用户的 email
    """
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        return proposal_reply(
            False,
            f"JSON 语法错误 (pos {e.pos}): {e.msg}",
            error=f"JSON 解析失败: {e.msg} (pos {e.pos})",
            evidence={"pos": e.pos, "msg": e.msg},
            options=["修正 JSON 语法", "查看 pos 附近的字符"],
        )

    try:
        result = _resolve(obj, path, 0)
        return {"ok": True, "path": path, "result": result}
    except (KeyError, IndexError, TypeError, ValueError, RecursionError) as e:
        return proposal_reply(
            False,
            f"路径 '{path}' 解析失败——对象结构不匹配路径",
            error=f"路径 {path} 解析失败: {e}",
            evidence={"path": path, "error_type": type(e).__name__},
            options=["检查路径中对象的实际类型(对象/数组)", "用 [*] 或 [0] 调整"],
        )


def _resolve(obj, path: str, depth: int = 0):
    if depth > 50:
        raise RecursionError("JSON 路径深度超过上限 (50)")
    if not path:
        return obj
    if not isinstance(path, str):
        raise ValueError(f"路径必须是字符串")
    import re

    if path.startswith("["):
        m = re.match(r'^\[(-?\d+|\*)\]', path)
        if not m:
            raise ValueError(f"无法解析路径段: {path}")
        seg = m.group(0)
        rest = path[len(seg):]
        if rest.startswith("."):
            rest = rest[1:]
        inner = m.group(1)
        if inner == "*":
            if not isinstance(obj, list):
                raise TypeError(f"不能对非数组使用 [*]")
            if not rest:
                return obj
            return [_resolve(item, rest, depth + 1) for item in obj]
        else:
            idx = int(inner)
            if not isinstance(obj, list):
                raise TypeError(f"不能对非数组使用索引")
            return _resolve(obj[idx], rest, depth + 1)
    else:
        m = re.match(r'^(\w+)', path)
        if not m:
            raise ValueError(f"无法解析路径段: {path}")
        seg = m.group(0)
        rest = path[len(seg):]
        if rest.startswith("."):
            rest = rest[1:]
        if not isinstance(obj, dict):
            raise TypeError(f"不能对非对象使用 .key")
        return _resolve(obj[seg], rest, depth + 1)
