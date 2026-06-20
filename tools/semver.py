"""
semver — 语义版本号比较。
纯 Python，无依赖。
"""

import re


def compare(v1: str, v2: str) -> dict:
    """
    比较两个语义版本号。

    Args:
        v1, v2: 版本字符串，如 "1.2.3" "2.0.0-beta.1"

    Returns:
        含 result: ">" / "<" / "="，以及解析后的各段
    """
    p1 = _parse(v1)
    p2 = _parse(v2)

    if p1 is None or p2 is None:
        return {"ok": False, "error": "版本号格式无效"}

    # 比较 major.minor.patch（数字直接比较）
    if p1[:3] > p2[:3]:
        result = ">"
    elif p1[:3] < p2[:3]:
        result = "<"
    else:
        # 相同版本号，比较预发布字段
        c = _cmp_pre(p1[3], p2[3])
        if c > 0:
            result = ">"
        elif c < 0:
            result = "<"
        else:
            result = "="

    return {
        "ok": True,
        "v1": v1,
        "v2": v2,
        "result": result,
        "v1_parsed": _fmt_parsed(p1),
        "v2_parsed": _fmt_parsed(p2),
    }


def _fmt_parsed(p: tuple) -> dict:
    return {
        "major": p[0], "minor": p[1], "patch": p[2],
        "pre": [x for x in p[3] if x != chr(127)] or None,
    }


def _parse(v: str) -> tuple | None:
    """解析 semver 为可比较元组。"""
    v = v.strip().lstrip("v")
    # 剥离 build metadata (+xxx)，不影响优先级
    build_split = v.split("+", 1)
    v = build_split[0]

    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$", v)
    if not m:
        # 尝试容忍只有 major.minor
        m = re.match(r"^(\d+)\.(\d+)$", v)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), 0, (chr(127),))

    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre_raw = m.group(4) or ""
    if pre_raw:
        pre_parts = []
        for field in pre_raw.split("."):
            if field.isdigit():
                pre_parts.append(int(field))
            else:
                pre_parts.append(field)
        pre = tuple(pre_parts)
    else:
        # 正式版应排在任何预发布之后，用 DEL(127) 哨兵
        pre = (chr(127),)
    return (major, minor, patch, pre)


def _cmp_pre(a: tuple, b: tuple) -> int:
    """比较两个预发布标识符元组，按 semver 2.0.0 规范。
    
    数值标识符按数值比较，字母标识符按 ASCII 字典序比较，
    数值优先级低于字母。
    
    返回值：-1 (a < b), 0 (a == b), 1 (a > b)
    """
    for i in range(min(len(a), len(b))):
        af, bf = a[i], b[i]
        # 判断是否为数值
        a_is_num = isinstance(af, (int, float))
        b_is_num = isinstance(bf, (int, float))
        if a_is_num and not b_is_num:
            return -1
        if not a_is_num and b_is_num:
            return 1
        if a_is_num and b_is_num:
            if af < bf:
                return -1
            if af > bf:
                return 1
        else:
            if str(af) < str(bf):
                return -1
            if str(af) > str(bf):
                return 1
    # 公共部分相等，较短者优先级更低
    if len(a) < len(b):
        return -1
    if len(a) > len(b):
        return 1
    return 0
