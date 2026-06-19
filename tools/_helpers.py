"""
_helpers — main.py 和 registry 共用的辅助函数。
"""

import asyncio
import json
import subprocess


def _run_cmd(
    cmd_args: list[str],
    cwd: str = "",
    timeout: int = 15,
    encoding: str = "utf-8",
) -> dict:
    """统一 subprocess.run 封装。返回 {"ok": bool, "stdout": str, "stderr": str, "code": int}"""
    if not cwd:
        cwd = "."
    try:
        result = subprocess.run(
            cmd_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding=encoding,
            errors="replace",
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "code": result.returncode,
        }
    except FileNotFoundError:
        cmd_name = cmd_args[0] if cmd_args else "command"
        return {"ok": False, "error": f"{cmd_name} 未安装或不在 PATH 中"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"命令超时 ({timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def err_json(error: str) -> str:
    return json.dumps({"ok": False, "error": error}, ensure_ascii=False)


def unwrap(result: dict) -> str:
    """检测嵌套 ok:false 并展开；成功则正常包装。
    若结果已含 proposal/options/evidence/stdout/stderr 等协议或诊断字段，则直接透传——
    无论 ok 值，避免丢失 LLM 需要的诊断信息。
    纯 ok:true 的无协议结果正常包入 data 字段。
    """
    if not isinstance(result, dict):
        return err_json(f"工具返回了非预期类型: {type(result).__name__}")
    if any(k in result for k in ("proposal", "options", "evidence", "next_call", "stdout", "stderr", "cmd")):
        return json.dumps(result, ensure_ascii=False)
    if result.get("ok") is False:
        return err_json(result.get("error", "未知错误"))
    return json.dumps({"ok": True, "data": result}, ensure_ascii=False)


async def run_sync(func, *args, **kwargs):
    """在默认线程池中运行同步函数，避免阻塞 AstrBot 事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def proposal_reply(
    ok: bool,
    proposal: str,
    *,
    error: str = "",
    evidence: dict = None,
    options: list = None,
    next_call: dict = None,
    **extra,
) -> dict:
    """构建统一提案协议返回。

    仅用于需要 LLM 做出选择或理解歧义的场景。
    ok:true 的正常路径不启用，保持精简。

    WARNING: next_call 是建议，LLM 应自行判断而非盲从。

    extra 中的键值平铺合并到返回 dict。
    """
    result = {"ok": ok, "proposal": proposal, **extra}
    if error:
        result["error"] = error
    if evidence:
        result["evidence"] = evidence
    if options:
        result["options"] = options
    if next_call:
        result["next_call"] = next_call
    return result
