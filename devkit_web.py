"""
devkit_web — 弥亚开发工具箱前端配置页 Web API。
"""

from __future__ import annotations

import base64
import inspect
import json
import mimetypes
import os
import re
import time
import uuid
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

_DATA_URL_RE = re.compile(r"^data:([^;,]+);base64,", re.IGNORECASE)
_SUPPORTED_MEDIA_MIME_KINDS: dict[str, str] = {
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/png": "image",
    "image/webp": "image",
    "image/gif": "image",
    "image/bmp": "image",
    "image/x-icon": "image",
    "image/vnd.microsoft.icon": "image",
    "video/mp4": "video",
    "video/webm": "video",
    "video/ogg": "video",
    "video/quicktime": "video",
    "audio/mpeg": "audio",
    "audio/mp3": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/ogg": "audio",
    "audio/mp4": "audio",
    "audio/aac": "audio",
    "audio/flac": "audio",
    "audio/webm": "audio",
}
_MEDIA_EXTENSIONS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/webm": ".webm",
}
_MEDIA_MAX_BYTES = {
    "image": 24 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "audio": 30 * 1024 * 1024,
}
_MEDIA_CHUNK_MAX_BYTES = 768 * 1024


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
            ("/media/background/upload", self.page_upload_background_media, ["POST"], "Upload background media"),
            ("/media/background/chunk/init", self.page_init_background_media_upload, ["POST"], "Init background media upload"),
            ("/media/background/chunk/append", self.page_append_background_media_upload, ["POST"], "Append background media upload chunk"),
            ("/media/background/chunk/complete", self.page_complete_background_media_upload, ["POST"], "Complete background media upload"),
            ("/media/background/chunk/read", self.page_read_background_media_chunk, ["POST"], "Read background media chunk"),
            ("/media/audio/upload", self.page_upload_background_audio, ["POST"], "Upload background audio"),
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

    def _media_storage_dir(self) -> str:
        group_config_file = self._group_config_file()
        if group_config_file:
            return os.path.join(os.path.dirname(group_config_file), "media")
        return ""

    def _media_upload_dir(self) -> str:
        media_dir = self._media_storage_dir()
        return os.path.join(media_dir, ".uploads") if media_dir else ""

    @staticmethod
    def _clamp_card_transparency(value: Any) -> int:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            number = 18
        return max(0, min(95, number))

    @staticmethod
    def _clean_mime(mime: Any) -> str:
        return str(mime or "").split(";", 1)[0].strip().lower()

    @classmethod
    def _media_kind_for_mime(cls, mime: Any) -> str:
        return _SUPPORTED_MEDIA_MIME_KINDS.get(cls._clean_mime(mime), "")

    @staticmethod
    def _safe_original_filename(filename: Any) -> str:
        value = os.path.basename(str(filename or "media").replace("\\", "/")).strip()
        value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
        return value[:120] or "media"

    def _safe_storage_name(self, slot: str, mime: str, filename: str) -> str:
        ext = _MEDIA_EXTENSIONS.get(mime)
        if not ext:
            guessed = os.path.splitext(filename)[1].lower()
            ext = guessed if guessed in set(_MEDIA_EXTENSIONS.values()) else ".bin"
        safe_slot = re.sub(r"[^a-z0-9-]+", "-", slot.lower()).strip("-") or "media"
        return f"{safe_slot}-{int(time.time())}-{uuid.uuid4().hex[:10]}{ext}"

    def _media_path(self, storage: Any) -> str:
        media_dir = self._media_storage_dir()
        name = str(storage or "").strip()
        if not media_dir or not name or os.path.basename(name) != name:
            return ""
        return os.path.join(media_dir, name)

    def _media_upload_meta_path(self, upload_id: Any) -> str:
        upload_dir = self._media_upload_dir()
        name = str(upload_id or "").strip()
        if not upload_dir or not re.fullmatch(r"[a-f0-9]{32}", name):
            return ""
        return os.path.join(upload_dir, f"{name}.json")

    def _media_upload_part_path(self, upload_id: Any) -> str:
        upload_dir = self._media_upload_dir()
        name = str(upload_id or "").strip()
        if not upload_dir or not re.fullmatch(r"[a-f0-9]{32}", name):
            return ""
        return os.path.join(upload_dir, f"{name}.part")

    @staticmethod
    def _data_url_mime(data_url: Any) -> str:
        match = _DATA_URL_RE.match(str(data_url or ""))
        return match.group(1).lower() if match else ""

    def _media_from_data_url(self, data_url: Any, allowed_kinds: set[str]) -> dict[str, Any] | None:
        value = str(data_url or "").strip()
        mime = self._data_url_mime(value)
        kind = self._media_kind_for_mime(mime)
        if not kind or kind not in allowed_kinds:
            return None
        return {
            "kind": kind,
            "mime": mime,
            "filename": "legacy-background",
            "data_url": value,
        }

    def _normalise_media_pref(self, media: Any, *, allowed_kinds: set[str]) -> dict[str, Any] | None:
        if not isinstance(media, dict):
            return None
        data_url = str(media.get("data_url") or media.get("url") or "").strip()
        if data_url:
            parsed = self._media_from_data_url(data_url, allowed_kinds)
            if parsed is None:
                return None
            parsed["filename"] = self._safe_original_filename(media.get("filename") or parsed["filename"])
            if "enabled" in media:
                parsed["enabled"] = bool(media.get("enabled"))
            return parsed

        mime = self._clean_mime(media.get("mime"))
        kind = self._media_kind_for_mime(mime)
        if not kind or kind not in allowed_kinds:
            return None
        expected_kind = str(media.get("kind") or kind).strip().lower()
        if expected_kind and expected_kind != kind:
            return None
        local_id = str(media.get("local_id") or "").strip()
        if local_id:
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", local_id):
                return None
            clean = {
                "kind": kind,
                "mime": mime,
                "local_id": local_id,
                "filename": self._safe_original_filename(media.get("filename") or local_id),
            }
            if "size" in media:
                try:
                    clean["size"] = max(0, int(media.get("size") or 0))
                except (TypeError, ValueError):
                    pass
            if "last_modified" in media:
                try:
                    clean["last_modified"] = max(0, int(media.get("last_modified") or 0))
                except (TypeError, ValueError):
                    pass
            if "playback_time" in media:
                try:
                    clean["playback_time"] = max(0.0, float(media.get("playback_time") or 0))
                except (TypeError, ValueError):
                    pass
            if "enabled" in media:
                clean["enabled"] = bool(media.get("enabled"))
            return clean
        storage = str(media.get("storage") or "").strip()
        if not storage or os.path.basename(storage) != storage:
            return None
        clean = {
            "kind": kind,
            "mime": mime,
            "storage": storage,
            "filename": self._safe_original_filename(media.get("filename") or storage),
        }
        if "size" in media:
            try:
                clean["size"] = max(0, int(media.get("size") or 0))
            except (TypeError, ValueError):
                pass
        if "playback_time" in media:
            try:
                clean["playback_time"] = max(0.0, float(media.get("playback_time") or 0))
            except (TypeError, ValueError):
                pass
        if "enabled" in media:
            clean["enabled"] = bool(media.get("enabled"))
        return clean

    @staticmethod
    def _strip_media_data(media: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in media.items() if k not in {"data_url", "url"}}

    def _merge_media_state_update(
        self,
        existing: Any,
        update: Any,
        *,
        allowed_kinds: set[str],
    ) -> dict[str, Any] | None:
        if not isinstance(existing, dict) or not isinstance(update, dict):
            return None
        if update.get("storage") or update.get("local_id") or update.get("data_url") or update.get("url"):
            return None
        merged = dict(existing)
        if "playback_time" in update or "current_time" in update or "currentTime" in update:
            try:
                merged["playback_time"] = max(
                    0.0,
                    float(update.get("playback_time", update.get("current_time", update.get("currentTime", 0))) or 0),
                )
            except (TypeError, ValueError):
                pass
        if "enabled" in update:
            merged["enabled"] = bool(update.get("enabled"))
        return self._normalise_media_pref(merged, allowed_kinds=allowed_kinds)

    def _hydrate_media_pref(self, media: dict[str, Any] | None) -> dict[str, Any] | None:
        if not media:
            return None
        if media.get("data_url"):
            return media
        if media.get("local_id"):
            return media
        path = self._media_path(media.get("storage"))
        if not path or not os.path.exists(path):
            return None
        mime = self._clean_mime(media.get("mime"))
        kind = self._media_kind_for_mime(mime)
        if not kind:
            return None
        if kind == "video":
            path = self._media_path(media.get("storage"))
            if not path or not os.path.exists(path):
                return None
            hydrated = dict(media)
            hydrated["size"] = os.path.getsize(path)
            return hydrated
        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return None
        hydrated = dict(media)
        hydrated["data_url"] = f"data:{mime};base64,{encoded}"
        hydrated["size"] = os.path.getsize(path)
        return hydrated

    async def _uploaded_file_payload(self) -> tuple[str, str, bytes]:
        files_obj = self._request().files
        files = await files_obj if inspect.isawaitable(files_obj) else files_obj
        upload = files.get("file") if hasattr(files, "get") else None
        if upload is None:
            raise ValueError("missing uploaded file")
        filename = self._safe_original_filename(getattr(upload, "filename", "media"))
        mime = self._clean_mime(getattr(upload, "content_type", "") or mimetypes.guess_type(filename)[0])
        reader = getattr(upload, "read", None)
        if callable(reader):
            content = reader()
            content = await content if inspect.isawaitable(content) else content
        else:
            stream = getattr(upload, "stream", None)
            content = stream.read() if stream is not None else b""
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("uploaded file is unreadable")
        return filename, mime, bytes(content)

    async def _store_uploaded_media(self, *, slot: str, allowed_kinds: set[str]) -> dict[str, Any]:
        filename, mime, content = await self._uploaded_file_payload()
        kind = self._media_kind_for_mime(mime)
        if not kind or kind not in allowed_kinds:
            raise ValueError("unsupported media type")
        max_bytes = _MEDIA_MAX_BYTES.get(kind, 12 * 1024 * 1024)
        if not content:
            raise ValueError("empty media file")
        if len(content) > max_bytes:
            raise ValueError(f"{kind} file is too large")
        media_dir = self._media_storage_dir()
        if not media_dir:
            raise RuntimeError("media storage path is unavailable")
        os.makedirs(media_dir, exist_ok=True)
        storage = self._safe_storage_name(slot, mime, filename)
        path = self._media_path(storage)
        with open(path, "wb") as f:
            f.write(content)
        media = {
            "kind": kind,
            "mime": mime,
            "storage": storage,
            "filename": filename,
            "size": len(content),
        }
        if kind == "video":
            return media
        return cast(dict[str, Any], self._hydrate_media_pref(media) or media)

    def _start_chunked_media_upload(self, payload: dict[str, Any], *, allowed_kinds: set[str]) -> dict[str, Any]:
        filename = self._safe_original_filename(payload.get("filename") or "media")
        mime = self._clean_mime(payload.get("mime") or mimetypes.guess_type(filename)[0])
        kind = self._media_kind_for_mime(mime)
        if not kind or kind not in allowed_kinds:
            raise ValueError("unsupported media type")
        try:
            size = int(payload.get("size") or 0)
        except (TypeError, ValueError):
            raise ValueError("invalid media size") from None
        max_bytes = _MEDIA_MAX_BYTES.get(kind, 12 * 1024 * 1024)
        if size <= 0:
            raise ValueError("empty media file")
        if size > max_bytes:
            raise ValueError(f"{kind} file is too large")
        upload_dir = self._media_upload_dir()
        if not upload_dir:
            raise RuntimeError("media storage path is unavailable")
        os.makedirs(upload_dir, exist_ok=True)
        upload_id = uuid.uuid4().hex
        meta = {
            "upload_id": upload_id,
            "kind": kind,
            "mime": mime,
            "filename": filename,
            "size": size,
            "received": 0,
            "next_index": 0,
            "created_at": int(time.time()),
        }
        with open(self._media_upload_meta_path(upload_id), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        with open(self._media_upload_part_path(upload_id), "wb"):
            pass
        return {"upload_id": upload_id, "chunk_bytes": _MEDIA_CHUNK_MAX_BYTES}

    def _read_chunked_media_meta(self, upload_id: Any) -> dict[str, Any]:
        meta_path = self._media_upload_meta_path(upload_id)
        if not meta_path or not os.path.exists(meta_path):
            raise ValueError("upload session not found")
        try:
            with open(meta_path, "r", encoding="utf-8-sig") as f:
                meta = json.load(f)
        except Exception as exc:
            raise ValueError("upload session is invalid") from exc
        if not isinstance(meta, dict):
            raise ValueError("upload session is invalid")
        return meta

    def _write_chunked_media_meta(self, meta: dict[str, Any]) -> None:
        meta_path = self._media_upload_meta_path(meta.get("upload_id"))
        if not meta_path:
            raise ValueError("upload session is invalid")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

    def _append_chunked_media_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(payload.get("upload_id") or "").strip()
        meta = self._read_chunked_media_meta(upload_id)
        try:
            index = int(payload.get("index"))
        except (TypeError, ValueError):
            raise ValueError("invalid chunk index") from None
        expected_index = int(meta.get("next_index") or 0)
        if index != expected_index:
            raise ValueError("unexpected chunk index")
        encoded = str(payload.get("data") or "")
        try:
            chunk = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("invalid chunk data") from exc
        if not chunk:
            raise ValueError("empty chunk")
        if len(chunk) > _MEDIA_CHUNK_MAX_BYTES:
            raise ValueError("chunk is too large")
        received = int(meta.get("received") or 0)
        size = int(meta.get("size") or 0)
        if received + len(chunk) > size:
            raise ValueError("chunk exceeds declared size")
        part_path = self._media_upload_part_path(upload_id)
        if not part_path:
            raise ValueError("upload session is invalid")
        with open(part_path, "ab") as f:
            f.write(chunk)
        meta["received"] = received + len(chunk)
        meta["next_index"] = expected_index + 1
        self._write_chunked_media_meta(meta)
        return {"received": meta["received"], "next_index": meta["next_index"], "done": meta["received"] >= size}

    def _complete_chunked_media_upload(
        self,
        payload: dict[str, Any],
        *,
        slot: str,
        allowed_kinds: set[str],
    ) -> dict[str, Any]:
        upload_id = str(payload.get("upload_id") or "").strip()
        meta = self._read_chunked_media_meta(upload_id)
        kind = str(meta.get("kind") or "")
        mime = self._clean_mime(meta.get("mime"))
        if not kind or kind not in allowed_kinds or self._media_kind_for_mime(mime) != kind:
            raise ValueError("upload session media type is invalid")
        size = int(meta.get("size") or 0)
        received = int(meta.get("received") or 0)
        if received != size:
            raise ValueError("upload is incomplete")
        media_dir = self._media_storage_dir()
        part_path = self._media_upload_part_path(upload_id)
        meta_path = self._media_upload_meta_path(upload_id)
        if not media_dir or not part_path or not os.path.exists(part_path):
            raise ValueError("upload session data is missing")
        os.makedirs(media_dir, exist_ok=True)
        filename = self._safe_original_filename(meta.get("filename") or "media")
        storage = self._safe_storage_name(slot, mime, filename)
        final_path = self._media_path(storage)
        os.replace(part_path, final_path)
        if meta_path and os.path.exists(meta_path):
            os.remove(meta_path)
        media = {
            "kind": kind,
            "mime": mime,
            "storage": storage,
            "filename": filename,
            "size": size,
        }
        if kind == "video":
            return media
        return cast(dict[str, Any], self._hydrate_media_pref(media) or media)

    def _read_stored_media_chunk(self, payload: dict[str, Any], *, allowed_kinds: set[str]) -> dict[str, Any]:
        storage = str(payload.get("storage") or "").strip()
        mime = self._clean_mime(payload.get("mime"))
        kind = self._media_kind_for_mime(mime)
        if not kind or kind not in allowed_kinds:
            raise ValueError("unsupported media type")
        path = self._media_path(storage)
        if not path or not os.path.exists(path):
            raise ValueError("media file not found")
        try:
            offset = max(0, int(payload.get("offset") or 0))
            length = int(payload.get("length") or _MEDIA_CHUNK_MAX_BYTES)
        except (TypeError, ValueError):
            raise ValueError("invalid chunk range") from None
        length = min(max(1, length), _MEDIA_CHUNK_MAX_BYTES)
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(length)
        next_offset = offset + len(chunk)
        return {
            "chunk_data": base64.b64encode(chunk).decode("ascii"),
            "offset": offset,
            "next_offset": next_offset,
            "size": size,
            "done": next_offset >= size,
        }

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

    async def page_upload_background_media(self):
        try:
            media = await self._store_uploaded_media(slot="background", allowed_kinds={"image", "video"})
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        return self._jsonify({"ok": True, "media": media})

    async def page_init_background_media_upload(self):
        payload = await self._request().get_json(force=True, silent=True) or {}
        try:
            upload = self._start_chunked_media_upload(payload, allowed_kinds={"image", "video"})
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        return self._jsonify({"ok": True, **upload})

    async def page_append_background_media_upload(self):
        payload = await self._request().get_json(force=True, silent=True) or {}
        try:
            status = self._append_chunked_media_upload(payload)
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        return self._jsonify({"ok": True, **status})

    async def page_complete_background_media_upload(self):
        payload = await self._request().get_json(force=True, silent=True) or {}
        try:
            media = self._complete_chunked_media_upload(
                payload,
                slot="background",
                allowed_kinds={"image", "video"},
            )
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        return self._jsonify({"ok": True, "media": media})

    async def page_read_background_media_chunk(self):
        payload = await self._request().get_json(force=True, silent=True) or {}
        try:
            chunk = self._read_stored_media_chunk(payload, allowed_kinds={"image", "video"})
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        return self._jsonify({"ok": True, **chunk})

    async def page_upload_background_audio(self):
        try:
            media = await self._store_uploaded_media(slot="background-audio", allowed_kinds={"audio"})
        except ValueError as exc:
            return self._jsonify({"ok": False, "error": str(exc)}), 400
        media["enabled"] = True
        return self._jsonify({"ok": True, "media": media})

    async def page_save_ui_preferences(self):
        data = await self._request().get_json(force=True, silent=True) or {}
        palette_mode = str(data.get("palette_mode", "luxury")).strip().lower()
        if palette_mode not in {"luxury", "bluewhite", "vivid", "void"}:
            palette_mode = "luxury"
        appearance_mode = str(data.get("appearance_mode", "auto")).strip().lower()
        if appearance_mode not in {"auto", "light", "dark"}:
            appearance_mode = "auto"
        background_mode = str(data.get("background_mode", "preset")).strip().lower()
        if background_mode not in {"preset", "custom"}:
            background_mode = "preset"
        custom_background_url = str(data.get("custom_background_url", "") or "").strip()
        prefs = self._read_ui_preferences()
        background_media = self._normalise_media_pref(
            data.get("background_media"),
            allowed_kinds={"image", "video"},
        )
        if not background_media:
            background_media = self._merge_media_state_update(
                prefs.get("background_media"),
                data.get("background_media"),
                allowed_kinds={"image", "video"},
            )
        legacy_background = None
        if not background_media and custom_background_url:
            legacy_background = self._media_from_data_url(custom_background_url, {"image"})
        if background_mode == "custom" and not background_media:
            if legacy_background is None:
                return self._jsonify({"ok": False, "error": "invalid custom background"}), 400
            if len(custom_background_url) > 3_000_000:
                return self._jsonify({"ok": False, "error": "custom background is too large"}), 400
        background_audio = self._normalise_media_pref(
            data.get("background_audio"),
            allowed_kinds={"audio"},
        )
        if not background_audio:
            background_audio = self._merge_media_state_update(
                prefs.get("background_audio"),
                data.get("background_audio"),
                allowed_kinds={"audio"},
            )
        prefs["palette_mode"] = palette_mode
        prefs["appearance_mode"] = appearance_mode
        prefs["background_mode"] = background_mode
        prefs["background_media_enabled"] = bool(data.get("background_media_enabled", background_mode == "custom"))
        prefs["ui_sound_enabled"] = bool(data.get("ui_sound_enabled", True))
        prefs["video_sound_enabled"] = bool(data.get("video_sound_enabled", False))
        prefs["video_sound_user_set"] = bool(data.get("video_sound_user_set", False))
        prefs["card_transparency"] = self._clamp_card_transparency(data.get("card_transparency", 18))
        if background_mode == "custom" and background_media:
            prefs["background_media"] = self._strip_media_data(background_media)
            prefs.pop("custom_background_url", None)
        elif background_mode == "custom" and legacy_background:
            prefs["custom_background_url"] = custom_background_url
            prefs.pop("background_media", None)
        elif "custom_background_url" in prefs and not custom_background_url:
            prefs.pop("custom_background_url", None)
            if "background_media" in data:
                prefs.pop("background_media", None)
        if background_audio:
            prefs["background_audio"] = self._strip_media_data(background_audio)
        elif "background_audio" in data:
            prefs.pop("background_audio", None)
        media_audio_mode = str(data.get("media_audio_mode", prefs.get("media_audio_mode", "video")) or "video").strip().lower()
        if media_audio_mode not in {"video", "audio", "both", "off"}:
            media_audio_mode = "video"
        prefs["media_audio_mode"] = media_audio_mode
        for media_key in ("background_media", "background_audio"):
            existing_media = prefs.get(media_key)
            if isinstance(existing_media, dict):
                stripped_media = self._strip_media_data(existing_media)
                if stripped_media.get("storage") or stripped_media.get("local_id"):
                    prefs[media_key] = stripped_media
                else:
                    prefs.pop(media_key, None)
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
            return {
                "palette_mode": "luxury",
                "appearance_mode": "auto",
                "background_mode": "preset",
                "background_media_enabled": True,
                "media_audio_mode": "video",
                "ui_sound_enabled": True,
                "video_sound_enabled": False,
                "video_sound_user_set": False,
                "card_transparency": 18,
            }
        try:
            with open(prefs_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {
                    "palette_mode": "luxury",
                    "appearance_mode": "auto",
                    "background_mode": "preset",
                    "background_media_enabled": True,
                    "media_audio_mode": "video",
                    "ui_sound_enabled": True,
                    "video_sound_enabled": False,
                    "video_sound_user_set": False,
                    "card_transparency": 18,
                }
            palette_mode = str(data.get("palette_mode", "luxury")).strip().lower()
            data["palette_mode"] = palette_mode if palette_mode in {"luxury", "bluewhite", "vivid", "void"} else "luxury"
            appearance_mode = str(data.get("appearance_mode", "auto")).strip().lower()
            data["appearance_mode"] = appearance_mode if appearance_mode in {"auto", "light", "dark"} else "auto"
            background_mode = str(data.get("background_mode", "preset")).strip().lower()
            data["background_mode"] = background_mode if background_mode in {"preset", "custom"} else "preset"
            data["background_media_enabled"] = bool(data.get("background_media_enabled", True))
            custom_background_url = str(data.get("custom_background_url", "") or "").strip()
            background_media = self._normalise_media_pref(
                data.get("background_media"),
                allowed_kinds={"image", "video"},
            )
            background_media = self._hydrate_media_pref(background_media)
            if background_media:
                data["background_media"] = background_media
                data.pop("custom_background_url", None)
            elif data["background_mode"] == "custom" and custom_background_url:
                legacy_media = self._media_from_data_url(custom_background_url, {"image"})
                if legacy_media:
                    data["custom_background_url"] = custom_background_url
                    data["background_media"] = legacy_media
                else:
                    data.pop("custom_background_url", None)
                    data.pop("background_media", None)
            else:
                data.pop("custom_background_url", None)
                data.pop("background_media", None)

            background_audio = self._normalise_media_pref(
                data.get("background_audio"),
                allowed_kinds={"audio"},
            )
            background_audio = self._hydrate_media_pref(background_audio)
            if background_audio:
                background_audio["enabled"] = bool(background_audio.get("enabled", False))
                data["background_audio"] = background_audio
            else:
                data.pop("background_audio", None)

            data["ui_sound_enabled"] = bool(data.get("ui_sound_enabled", True))
            media_audio_mode = str(data.get("media_audio_mode", "video") or "video").strip().lower()
            data["media_audio_mode"] = media_audio_mode if media_audio_mode in {"video", "audio", "both", "off"} else "video"
            data["video_sound_enabled"] = bool(data.get("video_sound_enabled", False))
            data["video_sound_user_set"] = bool(data.get("video_sound_user_set", False))
            data["card_transparency"] = self._clamp_card_transparency(data.get("card_transparency", 18))
            return data
        except Exception:
            logger.warning("ui_preferences.json 读取失败，已使用默认偏好")
            return {
                "palette_mode": "luxury",
                "appearance_mode": "auto",
                "background_mode": "preset",
                "background_media_enabled": True,
                "media_audio_mode": "video",
                "ui_sound_enabled": True,
                "video_sound_enabled": False,
                "video_sound_user_set": False,
                "card_transparency": 18,
            }

    def _write_ui_preferences(self, prefs: dict[str, Any]) -> None:
        prefs_file = self._ui_preferences_file()
        if not prefs_file:
            raise RuntimeError("ui preferences path is unavailable")
        os.makedirs(os.path.dirname(prefs_file), exist_ok=True)
        tmp = f"{prefs_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, prefs_file)
