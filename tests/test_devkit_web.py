"""Tests for devkit_web group list behavior."""

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

quart = pytest.importorskip("quart")

from devkit_web import DevkitWebController  # noqa: E402


class MockClient:
    async def call_action(self, action):
        assert action == "get_group_list"
        return {"data": [{"group_id": "1001", "group_name": "当前群"}]}


class MockPlatform:
    def get_client(self):
        return MockClient()


class TestDevkitWebGroups:
    def test_group_list_ignores_config_only_left_groups(self, tmp_path):
        cfg_path = Path(tmp_path) / "group_configs.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "1001": {"group_id": "1001", "updated_at": 10},
                    "9999": {"group_id": "9999", "updated_at": 99},
                }
            ),
            encoding="utf-8",
        )

        ctx = MagicMock()
        ctx.platform_manager.platform_insts = [MockPlatform()]
        plugin = MagicMock()
        plugin._group_configs_path = str(cfg_path)
        controller = DevkitWebController(ctx, plugin)

        groups = asyncio.run(controller._get_all_groups())

        assert [g["id"] for g in groups] == ["1001"]
        assert groups[0]["name"] == "当前群"
        assert groups[0]["updated_at"] == 10


class TestDevkitWebMediaPreferences:
    def _controller(self, tmp_path):
        cfg_path = Path(tmp_path) / "group_configs.json"
        cfg_path.write_text("{}", encoding="utf-8")
        ctx = MagicMock()
        plugin = MagicMock()
        plugin._group_configs_path = str(cfg_path)
        return DevkitWebController(ctx, plugin)

    def test_detects_common_background_media_types(self, tmp_path):
        controller = self._controller(tmp_path)

        assert controller._media_kind_for_mime("image/gif") == "image"
        assert controller._media_kind_for_mime("video/mp4") == "video"
        assert controller._media_kind_for_mime("video/webm") == "video"
        assert controller._media_kind_for_mime("audio/mpeg") == "audio"
        assert controller._media_kind_for_mime("audio/flac") == "audio"

    def test_rejects_unsupported_media_type(self, tmp_path):
        controller = self._controller(tmp_path)

        assert controller._media_kind_for_mime("application/x-msdownload") == ""
        assert controller._normalise_media_pref(
            {"kind": "video", "mime": "application/x-msdownload", "storage": "bad.exe"},
            allowed_kinds={"image", "video"},
        ) is None

    def test_read_preferences_preserves_legacy_custom_image_data_url(self, tmp_path):
        controller = self._controller(tmp_path)
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps(
                {
                    "background_mode": "custom",
                    "custom_background_url": "data:image/gif;base64,R0lGODlhAQABAIAAAAUEBA==",
                }
            ),
            encoding="utf-8",
        )

        prefs = controller._read_ui_preferences()

        assert prefs["background_mode"] == "custom"
        assert prefs["background_media"]["kind"] == "image"
        assert prefs["background_media"]["mime"] == "image/gif"
        assert prefs["background_media"]["data_url"].startswith("data:image/gif;base64,")

    def test_read_preferences_loads_saved_audio_media_data_url(self, tmp_path):
        controller = self._controller(tmp_path)
        media_dir = Path(controller._media_storage_dir())
        media_dir.mkdir(parents=True)
        audio_file = media_dir / "background-audio.mp3"
        audio_file.write_bytes(b"ID3test")
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps(
                {
                    "background_audio": {
                        "kind": "audio",
                        "mime": "audio/mpeg",
                        "storage": "background-audio.mp3",
                        "filename": "music.mp3",
                        "enabled": True,
                    }
                }
            ),
            encoding="utf-8",
        )

        prefs = controller._read_ui_preferences()

        assert prefs["background_audio"]["kind"] == "audio"
        assert prefs["background_audio"]["enabled"] is True
        assert prefs["background_audio"]["data_url"].startswith("data:audio/mpeg;base64,")

    def test_video_upload_response_uses_stored_reference(self, tmp_path):
        controller = self._controller(tmp_path)

        async def fake_upload():
            return "clip.mp4", "video/mp4", b"video-bytes"

        controller._uploaded_file_payload = fake_upload

        media = asyncio.run(controller._store_uploaded_media(slot="background", allowed_kinds={"image", "video"}))

        assert media["kind"] == "video"
        assert media["storage"].endswith(".mp4")
        assert "data_url" not in media

    def test_chunked_video_upload_writes_stored_reference(self, tmp_path):
        controller = self._controller(tmp_path)
        content = b"video-data" * 128

        upload = controller._start_chunked_media_upload(
            {
                "filename": "local.mp4",
                "mime": "video/mp4",
                "size": len(content),
            },
            allowed_kinds={"image", "video"},
        )
        midpoint = len(content) // 2
        controller._append_chunked_media_upload(
            {
                "upload_id": upload["upload_id"],
                "index": 0,
                "data": base64.b64encode(content[:midpoint]).decode("ascii"),
            }
        )
        controller._append_chunked_media_upload(
            {
                "upload_id": upload["upload_id"],
                "index": 1,
                "data": base64.b64encode(content[midpoint:]).decode("ascii"),
            }
        )
        media = controller._complete_chunked_media_upload(
            {"upload_id": upload["upload_id"]},
            slot="background",
            allowed_kinds={"image", "video"},
        )

        assert media["kind"] == "video"
        assert media["storage"].endswith(".mp4")
        assert "data_url" not in media
        assert Path(controller._media_path(media["storage"])).read_bytes() == content

    def test_read_stored_video_chunk_uses_non_conflicting_payload_field(self, tmp_path):
        controller = self._controller(tmp_path)
        media_dir = Path(controller._media_storage_dir())
        media_dir.mkdir(parents=True)
        video_file = media_dir / "background-video.mp4"
        video_file.write_bytes(b"0123456789")

        chunk = controller._read_stored_media_chunk(
            {
                "storage": "background-video.mp4",
                "mime": "video/mp4",
                "offset": 2,
                "length": 4,
            },
            allowed_kinds={"image", "video"},
        )

        assert "data" not in chunk
        assert chunk["chunk_data"] == base64.b64encode(b"2345").decode("ascii")
        assert chunk["next_offset"] == 6
        assert chunk["done"] is False

    def test_read_preferences_keeps_video_storage_lightweight(self, tmp_path):
        controller = self._controller(tmp_path)
        media_dir = Path(controller._media_storage_dir())
        media_dir.mkdir(parents=True)
        video_file = media_dir / "background-video.mp4"
        video_file.write_bytes(b"video-bytes")
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps(
                {
                    "background_mode": "custom",
                    "background_media": {
                        "kind": "video",
                        "mime": "video/mp4",
                        "storage": "background-video.mp4",
                        "filename": "video.mp4",
                    },
                }
            ),
            encoding="utf-8",
        )

        prefs = controller._read_ui_preferences()

        assert prefs["background_media"]["kind"] == "video"
        assert prefs["background_media"]["storage"] == "background-video.mp4"
        assert "data_url" not in prefs["background_media"]
        assert prefs["background_media_enabled"] is True

    def test_read_preferences_preserves_explicit_background_disable(self, tmp_path):
        controller = self._controller(tmp_path)
        media_dir = Path(controller._media_storage_dir())
        media_dir.mkdir(parents=True)
        video_file = media_dir / "background-video.mp4"
        video_file.write_bytes(b"video-bytes")
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps(
                {
                    "background_mode": "preset",
                    "background_media_enabled": False,
                    "background_media": {
                        "kind": "video",
                        "mime": "video/mp4",
                        "storage": "background-video.mp4",
                        "filename": "video.mp4",
                    },
                }
            ),
            encoding="utf-8",
        )

        prefs = controller._read_ui_preferences()

        assert prefs["background_mode"] == "preset"
        assert prefs["background_media"]["kind"] == "video"
        assert prefs["background_media_enabled"] is False

    def test_background_picker_lists_common_video_extensions(self):
        html = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "index.html").read_text(encoding="utf-8")

        for extension in (".mp4", ".webm", ".ogg", ".ogv", ".mov"):
            assert extension in html

    def test_frontend_uses_chunked_video_background_upload_without_large_body(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")

        assert "indexedDB" not in app_js
        assert 'uploadChunkedMedia("background", file)' in app_js
        assert 'createLocalBackgroundVideoMedia(file)' not in app_js
        assert "saveVideoPlaybackProgress" in app_js
        assert "restoreVideoPlaybackProgress" in app_js
        assert "isVideoFile(file)" in app_js

    def test_frontend_uses_small_chunks_for_stored_video_hydration(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")

        assert "const MEDIA_READ_CHUNK_BYTES = 128 * 1024;" in app_js
        assert "result?.chunk_data" in app_js
        assert "stored media chunk read was incomplete" in app_js
        assert "hasStoredVideoBackground(media)" in app_js
        assert "backgroundMedia = (source || storedVideo) ? { ...media } : null" in app_js

    def test_frontend_uses_blob_url_for_uploaded_background_video(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")

        assert "URL.createObjectURL(file)" in app_js
        assert "URL.revokeObjectURL" in app_js

    def test_frontend_exposes_video_sound_and_card_transparency_controls(self):
        root = Path(__file__).resolve().parents[1] / "pages" / "settings"
        html = (root / "index.html").read_text(encoding="utf-8")
        app_js = (root / "app.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")

        assert "styles.css?v=20260630_video_progress_persist_fix" in html
        assert "app.js?v=20260630_video_progress_persist_fix" in html
        assert 'id="videoSoundBtn"' not in html
        assert 'id="mediaAudioModeLabel"' in html
        assert 'id="soundFeedbackBtn" class="toolbar-button"' in html
        assert 'id="soundFeedbackLabel"' in html
        assert 'id="cardTransparencyInput"' in html
        assert "MEDIA_AUDIO_MODES" in app_js
        assert 'const MEDIA_AUDIO_MODES = ["video", "audio", "both", "off"];' in app_js
        assert 'off: "全关"' in app_js
        assert 'mediaAudioMode === "off"' in app_js
        assert "cycleMediaAudioMode" in app_js
        assert "media_audio_mode" in app_js
        assert "getEffectiveVideoSoundEnabled" in app_js
        assert "video_sound_user_set" in app_js
        assert "card_transparency" in app_js
        assert "scheduleCardTransparencySave" in app_js
        assert "CARD_TRANSPARENCY_KEY" in app_js
        assert "saveCardTransparencyLocally" in app_js
        assert "getStoredCardTransparency" in app_js
        assert "flushCardTransparencySave" in app_js
        assert "videoProgressRestoring" in app_js
        assert "flushVideoPlaybackProgressSave" in app_js
        assert "startVideoProgressHeartbeat" in app_js
        assert "stopVideoProgressHeartbeat" in app_js
        assert 'window.addEventListener("pagehide", flushVideoPlaybackProgressSave)' in app_js
        assert 'document.addEventListener("visibilitychange"' in app_js
        assert 'window.addEventListener("beforeunload", flushVideoPlaybackProgressSave)' in app_js
        assert 'window.addEventListener("beforeunload", flushCardTransparencySave)' in app_js
        assert "background_media_enabled" in app_js
        assert 'backgroundMediaEnabled ? "custom" : "preset"' in app_js
        assert "--card-alpha" in styles
        assert 'data-card-transparency="high"' in styles
        assert "backdrop-filter: none" in styles

    def test_frontend_labels_background_type_and_distinct_button_sounds(self):
        root = Path(__file__).resolve().parents[1] / "pages" / "settings"
        html = (root / "index.html").read_text(encoding="utf-8")
        app_js = (root / "app.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")

        for label in ("背景类型", "媒体音效", "按钮音效"):
            assert f"<span>{label}</span>" in html
        assert "<span>视频音效</span>" not in html
        assert 'const BACKGROUND_KIND_LABELS = { image: "图片", gif: "动图", video: "视频" };' in app_js
        assert "function backgroundTypeForMedia" in app_js
        assert 'mime.startsWith("video/")' in app_js
        assert 'mime.startsWith("image/")' in app_js
        assert 'mime === "image/gif"' in app_js
        assert 'value.startsWith("data:video/") || value.startsWith("blob:")' in app_js
        assert "backgroundTypeForSource(customBackgroundUrl)" in app_js
        assert "function buttonSoundKind" in app_js
        for sound_kind in ('"switch-on"', '"switch-off"', '"confirm"', '"save"', '"reset"', '"error"'):
            assert sound_kind in app_js
        assert 'id === "saveConfigBtn" || id === "savePathOptionsBtn") return "confirm"' in app_js
        assert ".toolbar-button {\n  min-width: 62px;" in styles
        assert "white-space: nowrap;" in styles

    def test_frontend_fast_starts_background_video_playback(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")
        html = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "index.html").read_text(encoding="utf-8")

        assert '<video id="customBackgroundVideo" class="media-background-video" aria-hidden="true" muted loop playsinline preload="auto"></video>' in html
        assert "function primeBackgroundVideo" in app_js
        assert "function startBackgroundVideoPlayback" in app_js
        assert "video.defaultPlaybackRate = 1;" in app_js
        assert "video.playbackRate = 1;" in app_js
        assert "video.muted = true;" in app_js
        assert "playResult?.then?.(() => applyBackgroundVideoAudioState(video, shouldPlaySound))" in app_js

    def test_frontend_preserves_saved_video_progress_during_initial_zero_events(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")

        assert "function shouldSaveVideoPlaybackProgress" in app_js
        assert "const id = media?.local_id || media?.progress_key || media?.storage || media?.filename || \"\";" in app_js
        assert "const VIDEO_PROGRESS_RESET_GUARD_SECONDS = 2;" in app_js
        assert "const previousTime = readSavedVideoPlaybackTime(media);" in app_js
        assert "if (!allowReset && previousTime > VIDEO_PROGRESS_RESET_GUARD_SECONDS && time < VIDEO_PROGRESS_RESET_GUARD_SECONDS) return false;" in app_js
        assert "let videoProgressRestoreTarget = 0;" in app_js
        assert "if (!allowReset && videoProgressRestoreTarget > 0 && time < Math.max(0.25, videoProgressRestoreTarget - 0.5)) return false;" in app_js
        assert "function hasReachedVideoRestoreTarget" in app_js
        assert "markVideoProgressRestored(backgroundVideo)" in app_js
        assert "saveVideoPlaybackProgress({ syncPreferences: true })" in app_js
        assert "allowReset: canResetProgress" not in app_js
        assert "saveVideoPlaybackProgress({ syncPreferences: true, allowReset: true })" not in app_js

    def test_frontend_restores_local_video_metadata_after_refresh(self):
        app_js = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "app.js").read_text(encoding="utf-8")

        assert "function hasRestorableLocalVideo" in app_js
        assert "media?.kind === \"video\" && media.local_id && !mediaSource(media)" in app_js
        assert "const storedVideo = hasStoredVideoBackground(media) || hasRestorableLocalVideo(media);" in app_js
        assert "const hasRestorableLocal = hasRestorableLocalVideo(backgroundMedia);" in app_js
        assert "hasPlayableLocalVideo || hasRestorableLocal || backgroundMedia.storage" in app_js
        assert "hasStoredVideoBackground(backgroundMedia) || hasRestorableLocalVideo(backgroundMedia)" in app_js

    def test_frontend_has_dynamic_loading_animation_for_config_and_video_cache(self):
        root = Path(__file__).resolve().parents[1] / "pages" / "settings"
        html = (root / "index.html").read_text(encoding="utf-8")
        app_js = (root / "app.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")

        assert 'id="startupLoader"' in html
        assert 'id="startupLoaderTitle"' in html
        assert 'id="startupLoaderDetail"' in html
        assert "function setStartupLoading" in app_js
        assert "function hideStartupLoading" in app_js
        assert 'setStartupLoading("读取配置", "正在加载工具与权限配置")' in app_js
        assert 'setStartupLoading("缓存视频", "正在准备本地视频背景")' in app_js
        assert 'video.addEventListener("loadeddata", hideStartupLoading, { once: true })' in app_js
        assert ".startup-loader" in styles
        assert ".startup-loader::before" in styles
        assert ".startup-loader::after" in styles
        assert "@keyframes devkit-loader-ring" in styles
        assert "@keyframes devkit-loader-dot" in styles
        assert "@keyframes devkit-open-panel" in styles
        assert "@keyframes devkit-open-scan" in styles

    def test_frontend_full_bleed_layout_and_transparency_css(self):
        styles = (Path(__file__).resolve().parents[1] / "pages" / "settings" / "styles.css").read_text(encoding="utf-8")

        assert "body {\n  min-height: 100vh;\n  padding: 0;" in styles
        assert ".dashboard-shell {\n  position: relative;\n  z-index: 1;\n  width: 100%;" in styles
        assert "height: 100vh;\n  min-height: 100vh;\n  margin: 0;" in styles
        assert "border: 0;\n  border-radius: 0;" in styles
        assert "rgba(232, 234, 238, var(--card-alpha))" in styles
        assert "rgba(18, 39, 55, var(--card-alpha))" in styles
        assert ":root[data-background-mode=\"custom\"][data-card-transparency=\"high\"] .topbar" in styles

    def test_ui_preferences_include_video_sound_and_card_transparency(self):
        source = (Path(__file__).resolve().parents[1] / "devkit_web.py").read_text(encoding="utf-8")

        assert "media_audio_mode" in source
        assert "video_sound_enabled" in source
        assert "video_sound_user_set" in source
        assert "playback_time" in source
        assert "local_id" in source
        assert "card_transparency" in source
        assert "background_media_enabled" in source
        assert '{"video", "audio", "both", "off"}' in source

    def test_ui_preferences_accept_media_audio_off_mode(self, tmp_path):
        controller = self._controller(tmp_path)
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps({"media_audio_mode": "off"}),
            encoding="utf-8",
        )

        prefs = controller._read_ui_preferences()

        assert prefs["media_audio_mode"] == "off"

    def test_ui_preferences_save_accepts_media_audio_off_mode(self, tmp_path):
        controller = self._controller(tmp_path)
        app = quart.Quart(__name__)

        @app.post("/save")
        async def save():
            return await controller.page_save_ui_preferences()

        async def run_request():
            async with app.test_client() as client:
                response = await client.post(
                    "/save",
                    json={
                        "background_mode": "preset",
                        "background_media_enabled": False,
                        "media_audio_mode": "off",
                        "ui_sound_enabled": True,
                        "card_transparency": 18,
                    },
                )
                return response.status_code, await response.get_json()

        status_code, payload = asyncio.run(run_request())

        assert status_code == 200
        assert payload["preferences"]["media_audio_mode"] == "off"
        assert controller._read_ui_preferences()["media_audio_mode"] == "off"

    def test_ui_preferences_progress_only_update_keeps_existing_video_media(self, tmp_path):
        controller = self._controller(tmp_path)
        media_dir = Path(controller._media_storage_dir())
        media_dir.mkdir(parents=True)
        (media_dir / "background-video.mp4").write_bytes(b"video-bytes")
        prefs_file = Path(controller._ui_preferences_file())
        prefs_file.write_text(
            json.dumps(
                {
                    "background_mode": "custom",
                    "background_media_enabled": True,
                    "background_media": {
                        "kind": "video",
                        "mime": "video/mp4",
                        "storage": "background-video.mp4",
                        "filename": "motion.mp4",
                        "size": 4096,
                        "playback_time": 12.5,
                    },
                }
            ),
            encoding="utf-8",
        )

        app = quart.Quart(__name__)

        @app.post("/save")
        async def save():
            return await controller.page_save_ui_preferences()

        async def run_request():
            async with app.test_client() as client:
                response = await client.post(
                    "/save",
                    json={
                        "background_mode": "custom",
                        "background_media_enabled": True,
                        "background_media": {"playback_time": 42.25},
                        "media_audio_mode": "video",
                        "ui_sound_enabled": True,
                        "card_transparency": 33,
                    },
                )
                return response.status_code, await response.get_json()

        status_code, payload = asyncio.run(run_request())

        assert status_code == 200
        media = payload["preferences"]["background_media"]
        assert media["storage"] == "background-video.mp4"
        assert media["mime"] == "video/mp4"
        assert media["filename"] == "motion.mp4"
        assert media["playback_time"] == 42.25
