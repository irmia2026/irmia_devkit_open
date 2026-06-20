"""
uuid_gen — ID / 随机字符串生成。
纯 uuid + secrets 标准库。
"""

import uuid
import secrets
import string


def gen(kind: str = "uuid4", length: int = 16) -> dict:
    """
    生成唯一标识符或随机字符串。

    Args:
        kind: uuid4 / hex / token
        length: hex/token 时的长度，默认 16
    """
    if kind == "uuid4":
        return {"ok": True, "kind": "uuid4", "value": str(uuid.uuid4())}

    if length < 1:
        return {"ok": False, "error": "length 必须大于 0"}

    if kind == "hex":
        return {
            "ok": True,
            "kind": "hex",
            "value": secrets.token_hex(length // 2 + 1)[:length],
        }

    if kind == "token":
        alphabet = string.ascii_letters + string.digits
        return {
            "ok": True,
            "kind": "token",
            "value": "".join(secrets.choice(alphabet) for _ in range(length)),
        }

    return {"ok": False, "error": f"未知 kind: {kind}，可选: uuid4 / hex / token"}
