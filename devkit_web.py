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
            ("/group_config", self.page_get_group_config, ["GET"], "Get one group config"),
            ("/group_config/save", self.page_save_group_config, ["POST"], "Save one group config"),
            ("/global_admin_ids", self.page_global_admin_ids, ["GET"], "Global admin IDs"),
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

    @staticmethod
    def _normalize_group_id(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _valid_group_id(group_id: str) -> bool:
        return bool(group_id) and len(group_id) <= 64

    # ── API ──

    async def page_ping(self):
        return self._jsonify({"ok": True, "message": "pong"})

    async def page_tool_groups(self):
        from .tools._registry import TOOL_GROUPS
        return self._jsonify({"ok": True, "groups": {k: v for k, v in TOOL_GROUPS.items()}})

    async def page_list_groups(self):
        groups = await self._get_all_groups()
        return self._jsonify({"ok": True, "groups": groups})

    async def page_get_group_config(self):
        group_id = self._normalize_group_id(self._request().args.get("group_id", ""))
        if not self._valid_group_id(group_id):
            return self._jsonify({"ok": False, "error": "invalid group_id"}), 400
        configs = self._read_group_configs()
        cfg = configs.get(group_id, self._default_group_config(group_id))
        return self._jsonify({"ok": True, "config": cfg})

    async def page_save_group_config(self):
        data = await self._request().get_json(force=True, silent=True) or {}
        group_id = self._normalize_group_id(data.get("group_id", ""))
        if not self._valid_group_id(group_id):
            return self._jsonify({"ok": False, "error": "invalid group_id"}), 400
        raw_tool_groups = data.get("tool_groups", {})
        if not isinstance(raw_tool_groups, dict):
            raw_tool_groups = {}
        clean = {
            "group_id": group_id,
            "extra_admin_ids": str(data.get("extra_admin_ids", "")).strip(),
            "tool_groups": {str(k): bool(v) for k, v in raw_tool_groups.items()},
            "updated_at": int(time.time()),
        }
        configs = self._read_group_configs()
        configs[group_id] = clean
        self._write_group_configs(configs)
        if hasattr(self.plugin, "_group_configs_cache"):
            self.plugin._group_configs_cache = configs
        else:
            logger.warning("plugin 缺少 _group_configs_cache 属性，缓存未更新")
        return self._jsonify({"ok": True})

    async def page_global_admin_ids(self):
        try:
            cfg = self.context.get_config()
            admins = cfg.get("admins_id", [])
        except Exception:
            admins = []
        return self._jsonify({"ok": True, "admin_ids": admins})

    # ── 群列表 ──

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
                items = result if isinstance(result, list) else result.get("data", []) if isinstance(result, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    gid = self._normalize_group_id(item.get("group_id", ""))
                    if not gid or gid in groups:
                        continue
                    name = str(item.get("group_name") or item.get("name") or f"群{gid}")
                    avatar = str(item.get("avatar") or item.get("avatar_url") or item.get("group_avatar") or "")
                    groups[gid] = {"id": gid, "name": name, "avatar": avatar}
            except AttributeError as exc:
                logger.debug("devkit: 当前平台不支持 get_group_list: %s", exc)
            except Exception as exc:
                logger.warning("devkit: 获取群列表失败: %s", exc)
        configs = self._read_group_configs()
        for gid, cfg in configs.items():
            updated_at = int(cfg.get("updated_at", 0)) if isinstance(cfg, dict) else 0
            if gid not in groups:
                groups[gid] = {"id": gid, "name": f"群{gid}", "avatar": ""}
            groups[gid]["updated_at"] = updated_at
        return sorted(groups.values(), key=lambda item: (-int(item.get("updated_at", 0)), str(item.get("name") or item.get("id") or "")))

    # ── 群配置 ──

    @staticmethod
    def _default_group_config(group_id: str) -> dict[str, Any]:
        from .tools._registry import TOOL_GROUPS
        return {"group_id": group_id, "extra_admin_ids": "", "tool_groups": {g: True for g in TOOL_GROUPS}}

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
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        tmp = f"{config_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config_file)
