"""
astrbot_plugin_irmia_devkit — 弥亚开发工具箱
为弥亚提供安全、精确的代码开发工具：safe_edit、git_smart、syntax_check、file_patch。
"""

from __future__ import annotations

import json
import os
import copy

from astrbot.api import logger, star
from astrbot.api.star import StarTools

from .tools import config as _tool_config

from .tools._registry import TOOL_GROUPS, _ALL_TOOLS

_DEFAULT_CONFIG = {
    "tool_groups": {g: True for g in TOOL_GROUPS},
    "es_path": "",
    "gh_path": "",
    "state_dir": "",
    "lock_dirs": [],
    "backup_dir": "",
}


class Main(star.Star):
    """弥亚开发工具箱插件"""

    def __init__(self, context: star.Context, config: dict = None) -> None:
        super().__init__(context)
        self.context = context

        plug_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            data_dir = StarTools.get_data_dir()
            if not data_dir:
                raise ValueError("get_data_dir() returned falsy")
            config_path = os.path.join(str(data_dir), "config.json")
        except Exception:
            config_path = os.path.join(plug_dir, "config.json")
        legacy_path = os.path.join(plug_dir, "config.json")
        if not os.path.exists(config_path) and os.path.exists(legacy_path):
            config_path = legacy_path

        _config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    _config = json.load(f)
            except Exception:
                logger.warning("配置文件 config.json 读取失败，使用默认值")
        else:
            _config = copy.deepcopy(_DEFAULT_CONFIG)
            try:
                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(_config, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # AstrBot WebUI 配置优先于 config.json
        if config:
            changed = False
            paths = config.get("paths", {})
            for key in ("es_path", "gh_path", "backup_dir"):
                if paths.get(key):
                    _config[key] = paths[key]
                    changed = True
            if paths.get("lock_dirs"):
                _config["lock_dirs"] = [d.strip() for d in paths["lock_dirs"].split(",") if d.strip()]
                changed = True
            web_groups = config.get("tool_groups", {})
            if web_groups and isinstance(web_groups, dict):
                stored = _config.setdefault("tool_groups", {})
                for g, v in web_groups.items():
                    stored[g] = v
                changed = True
            if changed:
                try:
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(_config, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        _tool_config.set_config(_config, plug_dir)

        # 过滤已启用的工具并注册
        tool_groups = _config.get("tool_groups", {})
        enabled = set()
        for group, tool_names in TOOL_GROUPS.items():
            if tool_groups.get(group, True):
                enabled.update(tool_names)

        tools = [_ALL_TOOLS[name]() for name in enabled if name in _ALL_TOOLS]
        allowed_ids = set()
        try:
            astrbot_config = self.context.get_config()
            allowed_ids.update(
                str(x).strip()
                for x in astrbot_config.get("admins_id", [])
                if str(x).strip()
            )
        except Exception as exc:
            logger.warning("弥亚开发工具箱读取 AstrBot 管理员列表失败：%s", exc)
        for tool in tools:
            original_call = tool.call

            async def guarded_call(context, *args, _original_call=original_call, _tool=tool, **kwargs):
                try:
                    event = context.context.event
                    sender_id = str(event.get_sender_id() or "").strip()
                    is_admin = getattr(event, "role", "") == "admin"
                    if not is_admin and sender_id not in allowed_ids:
                        logger.warning(
                            "弥亚开发工具箱拒绝未授权用户调用工具：sender=%s tool=%s",
                            sender_id or "unknown",
                            getattr(_tool, "name", "unknown"),
                        )
                        return "权限不足：弥亚开发工具箱仅允许配置的管理员 ID 或 AstrBot 管理员使用。"
                except Exception as exc:
                    logger.warning("弥亚开发工具箱权限检查失败，已拒绝工具调用：%s", exc)
                    return "权限不足：弥亚开发工具箱权限检查失败，已拒绝工具调用。"
                return await _original_call(context, *args, **kwargs)

            tool.call = guarded_call
        context.add_llm_tools(*tools)
        logger.info(f"🔧 弥亚开发工具箱已就绪 — {len(tools)} 个工具注册完毕")
