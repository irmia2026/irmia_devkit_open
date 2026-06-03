"""
_auth — 工具 call() 层权限守卫。

在工具注册时包裹 call()，注入管理员鉴权。
与 main.py 的 on_llm_request 钩子形成双层防线，互不依赖。
"""

import json
import logging

logger = logging.getLogger(__name__)


def protect_tool(tool, allowed_ids, access_checker=None):
    """原地包裹 tool.call，注入管理员鉴权。"""
    original_call = tool.call

    async def guarded_call(context, **kwargs):
        try:
            event = context.context.event
            sender_id = str(event.get_sender_id() or "").strip()
            tool_name = tool.name

            allowed = False
            if access_checker is not None:
                try:
                    allowed = bool(access_checker(event, tool_name))
                except Exception:
                    allowed = False
            else:
                allowed = event.is_admin() or sender_id in allowed_ids
            if allowed:
                return await original_call(context, **kwargs)

            logger.warning(
                "devkit auth blocked: tool=%s sender=%s", tool_name, sender_id
            )
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"权限不足：你（{sender_id}）不是管理员，无法使用 {tool_name}。"
                        "请在 AstrBot WebUI → 配置 → 常规配置 → 管理员 ID 中添加你的用户 ID。"
                    ),
                    "tool": tool_name,
                    "sender_id": sender_id,
                },
                ensure_ascii=False,
            )
        except Exception:
            logger.error(
                "devkit auth error for %s", getattr(tool, "name", "unknown"), exc_info=True
            )
            return json.dumps(
                {
                    "ok": False,
                    "error": "工具鉴权内部异常，已拒绝调用",
                    "tool": getattr(tool, "name", "unknown"),
                },
                ensure_ascii=False,
            )

    tool.call = guarded_call
    return tool


def build_allowed_ids(context, plugin_config):
    """构建允许使用工具的用户 ID 集合。

    来源：
      1. 本插件 config.json 中的 allowed_ids（额外允许的用户）
      2. AstrBot 全局配置中的 admins_id（自动读取，无需重复配置）
    """
    ids = set()

    raw = plugin_config.get("allowed_ids", "")
    if raw:
        if isinstance(raw, str):
            ids.update(
                x.strip() for x in raw.replace("，", ",").split(",") if x.strip()
            )
        elif isinstance(raw, list):
            ids.update(str(x).strip() for x in raw if str(x).strip())

    try:
        astrbot_cfg = context.get_config()
        admins = astrbot_cfg.get("admins_id", [])
        if isinstance(admins, list):
            ids.update(str(x).strip() for x in admins if str(x).strip())

        # 也读取非默认配置中的 admins_id（多配置场景）
        try:
            acm = getattr(context, "astrbot_config_mgr", None)
            if acm:
                for conf in getattr(acm, "confs", {}).values():
                    other_admins = conf.get("admins_id", [])
                    if isinstance(other_admins, list):
                        ids.update(str(x).strip() for x in other_admins if str(x).strip())
        except Exception:
            pass
    except Exception:
        logger.debug("devkit: failed to read AstrBot admins_id from context")

    return ids
