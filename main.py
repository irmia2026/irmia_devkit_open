"""
astrbot_plugin_irmia_devkit — 弥亚开发工具箱
为弥亚提供安全、精确的代码开发工具：safe_edit、git_smart、syntax_check、file_patch。
"""

from __future__ import annotations

import json
import os
import copy
import sqlite3

from astrbot.api import logger, star
from astrbot.api.star import StarTools
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest

from .tools import config as _tool_config

from .tools._registry import TOOL_GROUPS, _ALL_TOOLS
from .tools._auth import protect_tool, build_allowed_ids

_DEFAULT_CONFIG = {
    "owner_sid": "",
    "allowed_ids": "",
    "group_config_enabled": False,
    "tool_groups": {g: True for g in TOOL_GROUPS},
    "disabled_tools": [],
    "es_path": "",
    "gh_path": "",
    "state_dir": "",
    "lock_dirs": [],
    "backup_dir": "",
}


_PLUGIN_MODULE_PREFIX = "data.plugins.astrbot_plugin_irmia_devkit"

_NATIVE_REPLACEMENTS: dict[str, str] = {
    "astrbot_file_edit_tool": "safe_edit",
    "astrbot_grep_tool": "rg_search",
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
            data_dir = plug_dir
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
            sectioned = {}
            for section_name in ("权限管理", "工具权限", "外部路径", "兼容保留"):
                value = config.get(section_name, {})
                if isinstance(value, dict):
                    sectioned.update(value)
            web_config = {**config, **sectioned}
            changed = False
            web_owner = web_config.get("owner_sid", "")
            if web_owner:
                _config["owner_sid"] = web_owner
                changed = True
            web_allowed = web_config.get("allowed_ids", "")
            if web_allowed:
                _config["allowed_ids"] = web_allowed
                changed = True
            web_group_enabled = web_config.get("group_config_enabled", None)
            if isinstance(web_group_enabled, bool):
                _config["group_config_enabled"] = web_group_enabled
                changed = True
            paths = web_config.get("paths", {})
            if not isinstance(paths, dict):
                paths = {}
            for key in ("es_path", "gh_path", "backup_dir"):
                value = paths.get(key) or web_config.get(key, "")
                if value:
                    _config[key] = value
                    changed = True
            lock_dirs_value = paths.get("lock_dirs") or web_config.get("lock_dirs", "")
            if lock_dirs_value:
                _config["lock_dirs"] = [d.strip() for d in str(lock_dirs_value).split(",") if d.strip()]
                changed = True
            web_groups = web_config.get("tool_groups", {})
            if web_groups and isinstance(web_groups, dict):
                stored = _config.setdefault("tool_groups", {})
                for g, v in web_groups.items():
                    stored[g] = v
                changed = True
            web_disabled = web_config.get("disabled_tools", "")
            if web_disabled:
                if isinstance(web_disabled, str):
                    _config["disabled_tools"] = [t.strip() for t in web_disabled.replace("，", ",").split(",") if t.strip()]
                elif isinstance(web_disabled, list):
                    _config["disabled_tools"] = [str(t).strip() for t in web_disabled if str(t).strip()]
                changed = True
            if changed:
                try:
                    os.makedirs(os.path.dirname(config_path), exist_ok=True)
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(_config, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        _tool_config.set_config(_config, plug_dir)

        # 构建允许列表 + 注册工具
        allowed_ids = build_allowed_ids(context, _config)
        self._allowed_ids_cache = allowed_ids

        self._group_config_enabled = bool(_config.get("group_config_enabled", False))
        self._group_configs_path = os.path.join(str(data_dir), "group_configs.json")
        self._group_configs_cache = self._load_group_configs() if self._group_config_enabled else {}

        tool_groups = _config.get("tool_groups", {})
        disabled = _config.get("disabled_tools", [])
        enabled = set()
        for group, tool_names in TOOL_GROUPS.items():
            if tool_groups.get(group, True):
                enabled.update(tool_names)
        for t in disabled:
            enabled.discard(t)

        tools = [_ALL_TOOLS[name]() for name in enabled if name in _ALL_TOOLS]
        tools = [protect_tool(t, allowed_ids, self._is_tool_allowed_for_event) for t in tools]
        context.add_llm_tools(*tools)

        # Rotate op_log session on each plugin init/reload
        try:
            from .tools import op_log as _op_log
            _op_log.reset_session()
        except Exception:
            pass

        self._tool_names = {t.name for t in tools}
        # handler_module_path 设为 plugin.module_path 的真前缀：
        #   turn_off_plugin: "data.plugins...main".startswith("data.plugins...irmia_devkit") → TRUE  ✅
        #   _unbind_plugin:  "data.plugins...irmia_devkit".startswith("data.plugins...main") → FALSE ✅
        # 利用上游 P1 #2（startswith 方向反）的 bug 来避开 P0（停用时误删工具）的 bug。
        for tool in tools:
            tool.handler_module_path = _PLUGIN_MODULE_PREFIX
        # 刷掉 llm_tools.func_list 中可能残留的旧工具实例（它们带着老 handler_module_path）
        for tool in self.context.provider_manager.llm_tools.func_list:
            if tool.name in self._tool_names:
                tool.handler_module_path = _PLUGIN_MODULE_PREFIX
        # WebUI 来源显示靠 star_map.get(handler_module_path)。截断路径不匹配
        # plugin.module_path，所以手动注入一条 alias 映射。
        try:
            from astrbot.core.star.star import star_map
            _FULL = "data.plugins.astrbot_plugin_irmia_devkit.main"
            if _FULL in star_map and _PLUGIN_MODULE_PREFIX not in star_map:
                star_map[_PLUGIN_MODULE_PREFIX] = star_map[_FULL]
        except Exception:
            pass
        self._heal_inactivated_tools(tools)
        allowed_count = len(allowed_ids)
        logger.info(f"devkit ready — {len(tools)} tools registered, {allowed_count} allowed user{'s' if allowed_count != 1 else ''}")

        if self._group_config_enabled:
            self._register_web_page()

    def _register_web_page(self) -> None:
        try:
            from .devkit_web import DevkitWebController
            web = DevkitWebController(self.context, self)
            web.register_routes()
            logger.info("devkit Web 配置页已注册")
        except Exception as exc:
            logger.warning("devkit Web 配置页注册失败：%s", exc)

    def _load_group_configs(self) -> dict:
        try:
            if os.path.exists(self._group_configs_path):
                with open(self._group_configs_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("devkit group config 读取失败，已忽略")
        return {}

    @staticmethod
    def _event_group_id(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_group_id() or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_ids(raw) -> set[str]:
        if isinstance(raw, str):
            return {x.strip() for x in raw.replace("，", ",").split(",") if x.strip()}
        if isinstance(raw, list):
            return {str(x).strip() for x in raw if str(x).strip()}
        return set()

    def _group_config_for_event(self, event: AstrMessageEvent) -> dict:
        if not self._group_config_enabled:
            return {}
        configs = self._group_configs_cache if isinstance(self._group_configs_cache, dict) else {}
        group_id = self._event_group_id(event)
        default_cfg = configs.get("__default__", {})
        group_cfg = configs.get(group_id, {}) if group_id else {}
        if not isinstance(default_cfg, dict):
            default_cfg = {}
        if not isinstance(group_cfg, dict):
            group_cfg = {}
        if not default_cfg and not group_cfg:
            return {}
        default_disabled = default_cfg.get("disabled_tools", [])
        if isinstance(default_disabled, str):
            default_disabled = [x.strip() for x in default_disabled.replace("，", ",").split(",") if x.strip()]
        elif not isinstance(default_disabled, list):
            default_disabled = []
        merged = {
            "extra_admin_ids": default_cfg.get("extra_admin_ids", ""),
            "tool_groups": dict(default_cfg.get("tool_groups", {}) if isinstance(default_cfg.get("tool_groups", {}), dict) else {}),
            "disabled_tools": [str(x).strip() for x in default_disabled if str(x).strip()],
        }
        if group_cfg:
            merged["extra_admin_ids"] = group_cfg.get("extra_admin_ids", merged["extra_admin_ids"])
            raw_groups = group_cfg.get("tool_groups", {})
            if isinstance(raw_groups, dict):
                merged["tool_groups"].update(raw_groups)
            raw_disabled = group_cfg.get("disabled_tools", [])
            if isinstance(raw_disabled, str):
                raw_disabled = [x.strip() for x in raw_disabled.replace("，", ",").split(",") if x.strip()]
            if isinstance(raw_disabled, list):
                merged["disabled_tools"] = [str(x).strip() for x in raw_disabled if str(x).strip()]
        return merged

    def _is_group_extra_admin(self, event: AstrMessageEvent) -> bool:
        sender_id = str(event.get_sender_id() or "").strip()
        cfg = self._group_config_for_event(event)
        return sender_id in self._parse_ids(cfg.get("extra_admin_ids", ""))

    def _is_tool_group_enabled_for_event(self, event: AstrMessageEvent, tool_name: str) -> bool:
        cfg = self._group_config_for_event(event)
        if not cfg:
            return True
        disabled_tools = cfg.get("disabled_tools", [])
        if isinstance(disabled_tools, str):
            disabled_tools = [x.strip() for x in disabled_tools.replace("，", ",").split(",") if x.strip()]
        if tool_name in {str(x).strip() for x in disabled_tools if str(x).strip()}:
            return False
        group_switches = cfg.get("tool_groups", {})
        if not isinstance(group_switches, dict):
            return True
        for group_name, tool_names in TOOL_GROUPS.items():
            if tool_name in tool_names:
                return bool(group_switches.get(group_name, True))
        return True

    def _is_tool_allowed_for_event(self, event: AstrMessageEvent, tool_name: str) -> bool:
        if event.is_admin():
            return True
        if not self._is_tool_group_enabled_for_event(event, tool_name):
            return False
        return str(event.get_sender_id() or "").strip() in self._allowed_ids or self._is_group_extra_admin(event)

    def _heal_inactivated_tools(self, tools: list) -> None:
        """__init__ 阶段：强启所有 devkit 工具 + DB 清理。"""
        for tool in tools:
            tool.active = True
        self._heal_inactivated_tools_db()

    def _heal_inactivated_tools_db(self) -> None:
        """清理 inactivated_llm_tools 中本插件的幽灵条目，为下次重启铺路。"""
        names = getattr(self, "_tool_names", set())
        if not names:
            return
        try:
            plug_data = str(StarTools.get_data_dir())
            data_root = os.path.dirname(os.path.dirname(plug_data))
            db_path = os.path.join(data_root, "data_v4.db")
            if not os.path.exists(db_path):
                db_path = os.path.join(data_root, "data.db")
            db = sqlite3.connect(db_path)
            rows = db.execute("SELECT value FROM preferences WHERE key='inactivated_llm_tools'").fetchall()
            if not rows:
                db.close()
                return
            v = json.loads(rows[0][0])
            old_list = v.get("val", [])
            new_list = [x for x in old_list if x not in names]
            removed = len(old_list) - len(new_list)
            if removed:
                v["val"] = new_list
                db.execute("UPDATE preferences SET value=? WHERE key='inactivated_llm_tools'", (json.dumps(v),))
                db.commit()
                logger.info(f"healed: removed {removed} ghost entries from inactivated_llm_tools ({len(new_list)} remain)")
            db.close()
        except Exception as e:
            logger.warning(f"heal_inactivated_tools DB cleanup failed: {e}")

    @filter.on_llm_request()
    async def _auth_guard(self, event: AstrMessageEvent, req: ProviderRequest):
        sender_id = str(event.get_sender_id() or "").strip()
        if req.func_tool:
            # 兜底自愈：star_manager 的 load L1091 可能在 __init__ 之后
            # 用本地 inactivated_llm_tools 副本覆盖了 active=False。
            healed = 0
            for tool in req.func_tool.tools:
                mp = getattr(tool, "handler_module_path", "")
                if mp and mp.startswith(_PLUGIN_MODULE_PREFIX) and not tool.active:
                    tool.active = True
                    healed += 1
            if healed:
                logger.info(f"devkit self-heal: re-activated {healed} tools suppressed by stale inactivated_llm_tools cache")

            removed = []
            kept = []
            for tool in req.func_tool.tools:
                mp = getattr(tool, "handler_module_path", "")
                if mp and mp.startswith(_PLUGIN_MODULE_PREFIX) and not self._is_tool_allowed_for_event(event, tool.name):
                    removed.append(tool.name)
                    continue
                kept.append(tool)

            # L2: 授权用户有 devkit 替代品时，摘掉对应的原生工具
            devkit_names = {t.name for t in kept if (getattr(t, "handler_module_path", None) or "").startswith(_PLUGIN_MODULE_PREFIX)}
            if devkit_names:
                kept2 = []
                for tool in kept:
                    devkit_alt = _NATIVE_REPLACEMENTS.get(tool.name)
                    if devkit_alt and devkit_alt in devkit_names:
                        removed.append(f"{tool.name}→{devkit_alt}")
                        continue
                    kept2.append(tool)
                kept = kept2

            if removed:
                self._rebuild_func_tool(req, kept)
                logger.info(
                    "devkit L1 auth: removed %d tools for sender=%s: %s",
                    len(removed), sender_id, ", ".join(removed),
                )

    @staticmethod
    def _rebuild_func_tool(req, kept: list) -> None:
        try:
            from astrbot.core.agent.tool import ToolSet
            new_set = ToolSet()
            for tool in kept:
                new_set.add_tool(tool)
            req.func_tool = new_set
        except ImportError:
            logger.warning(
                "devkit L1 auth: failed to import ToolSet — tool removal skipped, "
                "non-admin may retain access to plugin tools"
            )

    @property
    def _allowed_ids(self) -> set:
        return self._allowed_ids_cache
