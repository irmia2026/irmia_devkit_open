"""Permission guard for Irmia DevKit LLM tools.

AstrBot's LLM tool registration exposes tools to the agent loop. This module adds
an execution-time access check so dangerous developer tools cannot be invoked by
non-admin users simply because the model decided to call them.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult


def _as_str_set(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _get_agent_context(context: ContextWrapper) -> Any:
    return getattr(context, "context", None)


def _get_event(context: ContextWrapper) -> Any:
    agent_context = _get_agent_context(context)
    return getattr(agent_context, "event", None)


def _get_sender_id(context: ContextWrapper) -> str:
    event = _get_event(context)
    if event is None:
        return ""
    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            logger.debug("devkit permission guard: failed to read sender id", exc_info=True)
    return str(getattr(event, "sender_id", "") or "")


def _get_session_id(context: ContextWrapper) -> str:
    event = _get_event(context)
    if event is None:
        return ""
    return str(
        getattr(event, "unified_msg_origin", "")
        or getattr(event, "session_id", "")
        or ""
    )


def _get_astrbot_context(context: ContextWrapper) -> Any:
    agent_context = _get_agent_context(context)
    return getattr(agent_context, "context", None)


def _is_astrbot_admin(context: ContextWrapper, sender_id: str) -> bool:
    if not sender_id:
        return False

    event = _get_event(context)
    if getattr(event, "role", "") == "admin":
        return True

    astrbot_context = _get_astrbot_context(context)
    if astrbot_context is None or not hasattr(astrbot_context, "get_config"):
        return False

    try:
        umo = getattr(event, "unified_msg_origin", None) if event is not None else None
        conf = astrbot_context.get_config(umo)
        admins = conf.get("admins_id", []) if hasattr(conf, "get") else []
        return sender_id in {str(admin) for admin in admins}
    except Exception:
        logger.warning("devkit permission guard: failed to read AstrBot admins", exc_info=True)
        return False


def _is_allowed(context: ContextWrapper, config: dict) -> bool:
    access_control = config.get("access_control", {}) or {}

    # Fail closed by default: these tools are high-risk developer tools.
    require_admin = bool(access_control.get("require_admin", True))
    allowed_users = _as_str_set(access_control.get("allowed_users", []))
    allowed_sessions = _as_str_set(access_control.get("allowed_sessions", []))

    sender_id = _get_sender_id(context)
    session_id = _get_session_id(context)

    if sender_id and sender_id in allowed_users:
        return True
    if session_id and session_id in allowed_sessions:
        return True
    if require_admin and _is_astrbot_admin(context, sender_id):
        return True

    # Explicitly allow open mode only when no whitelist is configured.
    return not require_admin and not allowed_users and not allowed_sessions


def _permission_denied(tool_name: str, context: ContextWrapper) -> str:
    sender_id = _get_sender_id(context) or "unknown"
    session_id = _get_session_id(context) or "unknown"
    logger.warning(
        "devkit tool permission denied: tool=%s sender=%s session=%s",
        tool_name,
        sender_id,
        session_id,
    )
    return json.dumps(
        {
            "ok": False,
            "error": "权限不足：Irmia DevKit 工具仅允许 AstrBot 管理员或白名单用户/会话调用",
            "tool": tool_name,
            "sender_id": sender_id,
            "session_id": session_id,
        },
        ensure_ascii=False,
    )


def protect_tool(tool: FunctionTool, config: dict) -> FunctionTool:
    """Wrap a FunctionTool instance with an execution-time permission check.

    The original tool object is kept, including its name, description, parameters,
    active flag and handler_module_path. Only its call method is guarded.
    """
    original_call: Callable[..., Awaitable[ToolExecResult]] = tool.call

    async def guarded_call(context: ContextWrapper, **kwargs: Any) -> ToolExecResult:
        if not _is_allowed(context, config):
            return _permission_denied(tool.name, context)
        return await original_call(context, **kwargs)

    tool.call = guarded_call  # type: ignore[method-assign]
    return tool
