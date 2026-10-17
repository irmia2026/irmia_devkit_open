"""Tests for devkit_web group list behavior."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

quart = pytest.importorskip("quart")

import devkit_web  # noqa: E402
from devkit_web import DevkitWebController  # noqa: E402


class MockClient:
    async def call_action(self, action):
        assert action == "get_group_list"
        return {"data": [{"group_id": "1001", "group_name": "当前群"}]}


class MockPlatform:
    def get_client(self):
        return MockClient()


class TestDevkitWebGroups:
    def test_runtime_config_update_invalidates_normalized_policy_cache(self):
        plugin = SimpleNamespace(
            _group_config_enabled=False,
            _group_configs_cache={},
            _invalidate_group_policy_cache=MagicMock(),
        )
        controller = DevkitWebController(MagicMock(), plugin)
        controller._persist_group_config_enabled = MagicMock()
        configs = {"__default__": {"disabled_tools": ["safe_edit"]}}

        controller._apply_runtime_group_configs(configs)

        assert plugin._group_config_enabled is True
        assert plugin._group_configs_cache is configs
        plugin._invalidate_group_policy_cache.assert_called_once_with()
        controller._persist_group_config_enabled.assert_called_once_with()

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


class TestDevkitWebPreferences:
    def test_read_ui_preferences_forces_dark_and_preserves_sound(self, tmp_path):
        prefs_path = Path(tmp_path) / "ui_preferences.json"
        prefs_path.write_text(
            json.dumps(
                {
                    "palette_mode": "vivid",
                    "appearance_mode": "light",
                    "previous_appearance_mode": "auto",
                    "ui_sound_enabled": False,
                }
            ),
            encoding="utf-8",
        )

        controller = DevkitWebController(MagicMock(), MagicMock())
        controller.plugin._group_configs_path = str(
            Path(tmp_path) / "group_configs.json"
        )

        preferences = controller._read_ui_preferences()

        assert preferences["palette_mode"] == "vivid"
        assert preferences["appearance_mode"] == "dark"
        assert preferences["ui_sound_enabled"] is False

    def test_save_ui_preferences_persists_sound_setting(self, tmp_path, monkeypatch):
        prefs_path = Path(tmp_path) / "ui_preferences.json"
        controller = DevkitWebController(MagicMock(), MagicMock())
        controller.plugin._group_configs_path = str(
            Path(tmp_path) / "group_configs.json"
        )
        controller._jsonify = lambda payload: payload

        async def get_json(**_kwargs):
            return {
                "palette_mode": "bluewhite",
                "appearance_mode": "light",
                "ui_sound_enabled": False,
            }

        monkeypatch.setattr(
            devkit_web, "quart_request_obj", SimpleNamespace(get_json=get_json)
        )

        result = asyncio.run(controller.page_save_ui_preferences())

        assert result["preferences"]["ui_sound_enabled"] is False
        assert result["preferences"]["appearance_mode"] == "dark"
        assert (
            json.loads(prefs_path.read_text(encoding="utf-8"))["ui_sound_enabled"]
            is False
        )

    def test_invalid_ui_preferences_use_dark_defaults(self, tmp_path):
        prefs_path = Path(tmp_path) / "ui_preferences.json"
        prefs_path.write_text("[]", encoding="utf-8")
        controller = DevkitWebController(MagicMock(), MagicMock())
        controller.plugin._group_configs_path = str(
            Path(tmp_path) / "group_configs.json"
        )

        assert controller._read_ui_preferences() == {
            "palette_mode": "luxury",
            "appearance_mode": "dark",
            "ui_sound_enabled": True,
        }
