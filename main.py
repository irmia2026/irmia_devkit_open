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
from .tools.permission_guard import protect_tool

from .tools._registry import TOOL_GROUPS, _ALL_TOOLS

_DEFAULT_CONFIG = {
    "tool_groups": {g: True for g in TOOL_GROUPS},
    "disabled_tools": [],
    "access_control": {
        "require_admin": True,
        "allowed_users": [],
        "allowed_sessions": [],
    },
    "es_path": "",
    "gh_path": "",
    "state_dir": "",
    "lock_dirs": [],
    "backup_dir": "",
}


def _split_csv(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _merge_defaults(config: dict) -> dict:
    merged = copy.deepcopy(_DEFAULT_CONFIG)
    merged.update(config or {})
    merged["tool_groups"] = {
        **_DEFAULT_CONFIG["tool_groups"],
        **(config or {}).get("tool_groups", {}),
    }
    merged["access_control"] = {
        **_DEFAULT_CONFIG["access_control"],
        **(config or {}).get("access_control", {}),
    }
    merged["access_control"]["allowed_users"] = _split_csv(
        merged["access_control"].get("allowed_users", [])
    )
    merged["access_control"]["allowed_sessions"] = _split_csv(
        merged["access_control"].get("allowed_sessions", [])
    )
    return merged


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

        _config = _merge_defaults(_config)

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
            web_disabled = config.get("disabled_tools", "")
            if web_disabled:
                _config["disabled_tools"] = [t.strip() for t in web_disabled.split(",") if t.strip()]
                changed = True

            web_access_control = config.get("access_control", {})
            if web_access_control and isinstance(web_access_control, dict):
                access_control = _config.setdefault("access_control", {})
                if "require_admin" in web_access_control:
                    access_control["require_admin"] = bool(web_access_control["require_admin"])
                    changed = True
                if "allowed_users" in web_access_control:
                    access_control["allowed_users"] = _split_csv(web_access_control.get("allowed_users"))
                    changed = True
                if "allowed_sessions" in web_access_control:
                    access_control["allowed_sessions"] = _split_csv(web_access_control.get("allowed_sessions"))
                    changed = True

            _config = _merge_defaults(_config)
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
        disabled = _config.get("disabled_tools", [])
        enabled = set()
        for group, tool_names in TOOL_GROUPS.items():
            if tool_groups.get(group, True):
                enabled.update(tool_names)
        for t in disabled:
            enabled.discard(t)

        tools = [
            protect_tool(_ALL_TOOLS[name](), _config)
            for name in enabled
            if name in _ALL_TOOLS
        ]
        context.add_llm_tools(*tools)
        logger.info(f"🔧 弥亚开发工具箱已就绪 — {len(tools)} 个工具注册完毕")
