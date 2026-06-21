"""
devkit_web — 弥亚开发工具箱前端配置页 Web API。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from astrbot.api import logger
from astrbot.api.star import Context

try:
    from quart import jsonify as quart_jsonify
    from quart import request as quart_request_obj
except ImportError:
    quart_jsonify = None
    quart_request_obj = None

PLUGIN_NAME = "astrbot_plugin_irmia_devkit"


class DevkitWebController:
    """弥亚开发工具箱 Web 配置页控制器。"""

    def __init__(self, context: Context, plugin: Any) -> None:
        self.context = context
        self.plugin = plugin

    def register_routes(self) -> None:
        if quart_jsonify is None:
            logger.info("Quart 不可用，跳过 devkit Web 配置页注册")
            return
        routes = [
            ("/ping", self.page_ping, ["GET"], "Devkit ping"),
            ("/tool_groups", self.page_tool_groups, ["GET"], "Tool group definitions"),
            ("/groups", self.page_list_groups, ["GET"], "QQ group list"),
            ("/contacts", self.page_list_contacts, ["GET"], "QQ private contact list"),
            ("/group_config", self.page_get_group_config, ["GET"], "Get one group config"),
            ("/group_config/save", self.page_save_group_config, ["POST"], "Save one group config"),
            ("/global_admin_ids", self.page_global_admin_ids, ["GET"], "Global admin IDs"),
            ("/ui_preferences", self.page_ui_preferences, ["GET"], "UI preferences"),
            ("/ui_preferences/save", self.page_save_ui_preferences, ["POST"], "Save UI preferences"),
            ("/path_options", self.page_path_options, ["GET"], "Optional external paths"),
            ("/path_options/save", self.page_save_path_options, ["POST"], "Save optional external paths"),
        ]
        for path, handler, methods, desc in routes:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}{path}",
                self._wrap_handler(handler),
                methods,
                desc,
            )

    @staticmethod
    def _jsonify(payload: dict[str, Any]):
        return cast(Callable[[dict[str, Any]], Any], quart_jsonify)(payload)

    @staticmethod
    def _request():
        return cast(Any, quart_request_obj)

    def _wrap_handler(self, handler: Callable[[], Awaitable]) -> Callable[[], Awaitable]:
        async def wrapped():
            try:
                return await handler()
            except Exception as exc:
                logger.exception("[DevkitWeb] request failed")
                return self._jsonify({"ok": False, "error": str(exc)}), 500
        wrapped.__name__ = handler.__name__
        return wrapped

    def _group_config_file(self) -> str:
        return str(getattr(self.plugin, "_group_configs_path", ""))

    def _config_file(self) -> str:
        return str(getattr(self.plugin, "_config_path", ""))

    def _ui_preferences_file(self) -> str:
        group_config_file = self._group_config_file()
        if group_config_file:
            return os.path.join(os.path.dirname(group_config_file), "ui_preferences.json")
        return ""

    @staticmethod
    def _normalize_group_id(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _valid_group_id(group_id: str) -> bool:
        if group_id == "__default__":
            return True
        if group_id.startswith("private:"):
            return 8 < len(group_id) <= 80
        return bool(group_id) and len(group_id) <= 64

    def _apply_runtime_group_configs(self, configs: dict[str, Any]) -> None:
        if hasattr(self.plugin, "_group_config_enabled"):
            self.plugin._group_config_enabled = True
        if hasattr(self.plugin, "_group_configs_cache"):
            self.plugin._group_configs_cache = configs
        else:
            logger.warning("plugin 缺少 _group_configs_cache 属性，缓存未更新")
        self._persist_group_config_enabled()

    def _persist_group_config_enabled(self) -> None:
        config_file = self._config_file()
        if not config_file:
            return
        try:
            config_data = self._read_main_config()
            config_data["group_config_enabled"] = True
            self._write_main_config(config_data)
        except Exception as exc:
            logger.warning("devkit: group_config_enabled 持久化失败: %s", exc)

    def _read_main_config(self) -> dict[str, Any]:
        config_file = self._config_file()
        if not config_file or not os.path.exists(config_file):
            return {}
        try:
            with open(config_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("devkit: config.json 读取失败，已使用空配置")
            return {}

    def _write_main_config(self, data: dict[str, Any]) -> None:
        config_file = self._config_file()
        if not config_file:
            raise RuntimeError("config path is unavailable")
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        tmp = f"{config_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_file)

    def _ensure_default_config(self, configs: dict[str, Any]) -> bool:
        if isinstance(configs.get("__default__"), dict):
            return False
        configs["__default__"] = self._default_group_config("__default__")
        return True

    # ── API ──

    async def page_ping(self):
        return self._jsonify({"ok": True, "message": "pong"})

    async def page_tool_groups(self):
        from .tools._registry import TOOL_GROUPS
        return self._jsonify({"ok": True, "groups": {k: v for k, v in TOOL_GROUPS.items()}})

    async def page_list_groups(self):
        configs = self._read_group_configs()
        if self._ensure_default_config(configs):
            self._write_group_configs(configs)
            self._apply_runtime_group_configs(configs)
        groups = await self._get_all_groups()
        return self._jsonify({"ok": True, "groups": groups})

    async def page_list_contacts(self):
        contacts = await self._get_all_private_contacts()
        return self._jsonify({"ok": True, "contacts": contacts})

    async def page_get_group_config(self):
        group_id = self._normalize_group_id(self._request().args.get("group_id", ""))
        if not self._valid_group_id(group_id):
            return self._jsonify({"ok": False, "error": "invalid group_id"}), 400
        configs = self._read_group_configs()
        cfg = configs.get(group_id)
        if not isinstance(cfg, dict):
            cfg = self._default_group_config(group_id)
            if group_id == "__default__":
                configs[group_id] = cfg
                self._write_group_configs(configs)
                self._apply_runtime_group_configs(configs)
        return self._jsonify({"ok": True, "config": cfg})

    async def page_save_group_config(self):
        data = await self._request().get_json(force=True, silent=True) or {}
        group_id = self._normalize_group_id(data.get("group_id", ""))
        if not self._valid_group_id(group_id):
            return self._jsonify({"ok": False, "error": "invalid group_id"}), 400
        raw_tool_groups = data.get("tool_groups", {})
        if not isinstance(raw_tool_groups, dict):
            raw_tool_groups = {}
        raw_disabled_tools = data.get("disabled_tools", [])
        if not isinstance(raw_disabled_tools, list):
            raw_disabled_tools = []
        clean = {
            "group_id": group_id,
            "extra_admin_ids": str(data.get("extra_admin_ids", "")).strip(),
            "tool_groups": {str(k): bool(v) for k, v in raw_tool_groups.items()},
            "disabled_tools": [str(item).strip() for item in raw_disabled_tools if str(item).strip()],
            "updated_at": int(time.time()),
        }
        configs = self._read_group_configs()
        configs[group_id] = clean
        self._write_group_configs(configs)
        self._apply_runtime_group_configs(configs)
        return self._jsonify({"ok": True})

    async def page_path_options(self):
        keys = ("es_path", "gh_path", "backup_dir")
        data = self._read_main_config()
        return self._jsonify({"ok": True, "paths": {k: str(data.get(k, "") or "") for k in keys}})

    async def page_save_path_options(self):
        payload = await self._request().get_json(force=True, silent=True) or {}
        keys = ("es_path", "gh_path", "backup_dir")
        data = self._read_main_config()
        for key in keys:
            data[key] = str(payload.get(key, "") or "").strip()
        self._write_main_config(data)
        return self._jsonify({"ok": True, "paths": {k: data[k] for k in keys}})

    async def page_global_admin_ids(self):
        try:
            cfg = self.context.get_config()
            admins = cfg.get("admins_id", [])
        except Exception:
            admins = []
        return self._jsonify({"ok": True, "admin_ids": admins})

    async def page_ui_preferences(self):
        prefs = self._read_ui_preferences()
        return self._jsonify({"ok": True, "preferences": prefs})

    async def page_save_ui_preferences(self):
        data = await self._request().get_json(force=True, silent=True) or {}
        palette_mode = str(data.get("palette_mode", "luxury")).strip().lower()
        if palette_mode not in {"luxury", "bluewhite", "vivid", "void"}:
            palette_mode = "luxury"
        appearance_mode = str(data.get("appearance_mode", "auto")).strip().lower()
        if appearance_mode not in {"auto", "light", "dark"}:
            appearance_mode = "auto"
        prefs = self._read_ui_preferences()
        previous_appearance_mode = str(data.get("previous_appearance_mode", prefs.get("previous_appearance_mode", "auto"))).strip().lower()
        if previous_appearance_mode not in {"auto", "light", "dark"}:
            previous_appearance_mode = "auto"
        prefs["palette_mode"] = palette_mode
        prefs["appearance_mode"] = appearance_mode
        prefs["previous_appearance_mode"] = previous_appearance_mode
        prefs["updated_at"] = int(time.time())
        self._write_ui_preferences(prefs)
        return self._jsonify({"ok": True, "preferences": prefs})

    # ── 群/私聊列表 ──

    @staticmethod
    def _items_from_result(result: Any) -> list[Any]:
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            data = result.get("data", [])
            return data if isinstance(data, list) else []
        return []

    async def _get_all_groups(self) -> list[dict[str, str]]:
        groups: dict[str, dict[str, str]] = {}
        try:
            platform_insts = self.context.platform_manager.platform_insts
        except Exception:
            platform_insts = []
        for inst in platform_insts:
            try:
                client = inst.get_client()
            except Exception:
                continue
            if client is None:
                continue
            try:
                result = await client.call_action("get_group_list")
                for item in self._items_from_result(result):
                    if not isinstance(item, dict):
                        continue
                    gid = self._normalize_group_id(item.get("group_id", ""))
                    if not gid or gid in groups:
                        continue
                    name = str(item.get("group_name") or item.get("name") or f"群{gid}")
                    avatar = str(item.get("avatar") or item.get("avatar_url") or item.get("group_avatar") or "")
                    member_count = item.get("member_count") or item.get("member_num") or item.get("member_total") or item.get("max_member_count") or ""
                    groups[gid] = {"id": gid, "name": name, "avatar": avatar, "member_count": str(member_count or "")}
            except AttributeError as exc:
                logger.debug("devkit: 当前平台不支持 get_group_list: %s", exc)
            except Exception as exc:
                logger.warning("devkit: 获取群列表失败: %s", exc)
        configs = self._read_group_configs()
        for gid, cfg in configs.items():
            if gid == "__default__":
                continue
            if gid not in groups:
                continue
            updated_at = int(cfg.get("updated_at", 0)) if isinstance(cfg, dict) else 0
            groups[gid]["updated_at"] = updated_at
        return sorted(groups.values(), key=lambda item: (-int(item.get("updated_at", 0)), str(item.get("name") or item.get("id") or "")))

    @staticmethod
    def _qq_avatar_url(user_id: str) -> str:
        return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=100" if user_id.isdigit() else ""

    async def _get_all_private_contacts(self) -> list[dict[str, str]]:
        contacts: dict[str, dict[str, str]] = {}
        try:
            platform_insts = self.context.platform_manager.platform_insts
        except Exception:
            platform_insts = []
        for inst in platform_insts:
            try:
                client = inst.get_client()
            except Exception:
                continue
            if client is None:
                continue
            try:
                result = await client.call_action("get_friend_list")
                for item in self._items_from_result(result):
                    if not isinstance(item, dict):
                        continue
                    uid = self._normalize_group_id(item.get("user_id") or item.get("id") or item.get("uin") or "")
                    if not uid:
                        continue
                    cid = f"private:{uid}"
                    name = str(item.get("nickname") or item.get("remark") or item.get("name") or f"用户{uid}")
                    avatar = str(item.get("avatar") or item.get("avatar_url") or item.get("user_avatar") or self._qq_avatar_url(uid))
                    contacts[cid] = {"id": cid, "name": name, "avatar": avatar, "user_id": uid, "kind": "private"}
            except AttributeError as exc:
                logger.debug("devkit: 当前平台不支持 get_friend_list: %s", exc)
            except Exception as exc:
                logger.warning("devkit: 获取私聊列表失败: %s", exc)
        configs = self._read_group_configs()
        for cid, cfg in configs.items():
            if not cid.startswith("private:") or not isinstance(cfg, dict):
                continue
            uid = cid.split(":", 1)[1]
            contacts.setdefault(cid, {"id": cid, "name": f"用户{uid}", "avatar": self._qq_avatar_url(uid), "user_id": uid, "kind": "private"})
            contacts[cid]["updated_at"] = int(cfg.get("updated_at", 0))
        return sorted(contacts.values(), key=lambda item: (-int(item.get("updated_at", 0)), str(item.get("name") or item.get("user_id") or "")))

    # ── 群配置 ──

    @staticmethod
    def _default_group_config(group_id: str) -> dict[str, Any]:
        from .tools._registry import TOOL_GROUPS
        return {
            "group_id": group_id,
            "extra_admin_ids": "",
            "tool_groups": {g: True for g in TOOL_GROUPS},
            "disabled_tools": [],
        }

    def _read_group_configs(self) -> dict[str, Any]:
        config_file = self._group_config_file()
        if not config_file:
            return {}
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except Exception:
                logger.warning("group_configs.json 读取失败，已重置为空")
                return {}
        return {}

    def _write_group_configs(self, configs: dict[str, Any]) -> None:
        config_file = self._group_config_file()
        if not config_file:
            raise RuntimeError("group config path is unavailable")
        if configs and os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8-sig") as f:
                    existing = json.load(f)
                if isinstance(existing, dict):
                    merged = dict(existing)
                    merged.update(configs)
                    configs = merged
            except Exception:
                logger.warning("group_configs.json 合并失败，将直接写入新配置")
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        tmp = f"{config_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_file)

    def _read_ui_preferences(self) -> dict[str, Any]:
        prefs_file = self._ui_preferences_file()
        if not prefs_file or not os.path.exists(prefs_file):
            return {"palette_mode": "luxury"}
        try:
            with open(prefs_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"palette_mode": "luxury"}
            palette_mode = str(data.get("palette_mode", "luxury")).strip().lower()
            data["palette_mode"] = palette_mode if palette_mode in {"luxury", "bluewhite", "vivid", "void"} else "luxury"
            appearance_mode = str(data.get("appearance_mode", "auto")).strip().lower()
            data["appearance_mode"] = appearance_mode if appearance_mode in {"auto", "light", "dark"} else "auto"
            previous_appearance_mode = str(data.get("previous_appearance_mode", data["appearance_mode"])).strip().lower()
            data["previous_appearance_mode"] = previous_appearance_mode if previous_appearance_mode in {"auto", "light", "dark"} else data["appearance_mode"]
            return data
        except Exception:
            logger.warning("ui_preferences.json 读取失败，已使用默认偏好")
            return {"palette_mode": "luxury"}

    def _write_ui_preferences(self, prefs: dict[str, Any]) -> None:
        prefs_file = self._ui_preferences_file()
        if not prefs_file:
            raise RuntimeError("ui preferences path is unavailable")
        os.makedirs(os.path.dirname(prefs_file), exist_ok=True)
        tmp = f"{prefs_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, prefs_file)
