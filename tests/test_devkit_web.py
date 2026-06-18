"""Tests for devkit_web group list behavior."""

import asyncio
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
