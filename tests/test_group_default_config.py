import importlib.util
import sys
import types
from pathlib import Path


def _load_main_class():
    root = Path(__file__).resolve().parent.parent
    pkg = types.ModuleType("astrbot_plugin_irmia_devkit")
    pkg.__path__ = [str(root)]
    sys.modules.setdefault("astrbot_plugin_irmia_devkit", pkg)
    spec = importlib.util.spec_from_file_location(
        "astrbot_plugin_irmia_devkit.main",
        root / "main.py",
        submodule_search_locations=[str(root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Main


Main = _load_main_class()


class DummyEvent:
    def __init__(self, group_id="1001", sender_id="u1", admin=False):
        self._group_id = group_id
        self._sender_id = sender_id
        self._admin = admin

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id

    def is_admin(self):
        return self._admin


def _main_with_configs(configs):
    obj = object.__new__(Main)
    obj._group_config_enabled = True
    obj._group_configs_cache = configs
    obj._allowed_ids_cache = set()
    return obj


class TestGroupDefaultConfig:
    def test_default_config_applies_when_group_has_no_override(self):
        plugin = _main_with_configs(
            {
                "__default__": {
                    "extra_admin_ids": "u1",
                    "tool_groups": {"Git & GitHub": False},
                    "disabled_tools": ["safe_edit"],
                }
            }
        )
        event = DummyEvent(group_id="1001", sender_id="u1")

        assert plugin._is_group_extra_admin(event) is True
        assert plugin._is_tool_group_enabled_for_event(event, "git_status") is False
        assert plugin._is_tool_group_enabled_for_event(event, "safe_edit") is False

    def test_group_config_overrides_default_group_switches_and_disabled_tools(self):
        plugin = _main_with_configs(
            {
                "__default__": {
                    "extra_admin_ids": "u1",
                    "tool_groups": {"Git & GitHub": False},
                    "disabled_tools": ["safe_edit"],
                },
                "1001": {
                    "extra_admin_ids": "u2",
                    "tool_groups": {"Git & GitHub": True},
                    "disabled_tools": ["git_push"],
                },
            }
        )
        event = DummyEvent(group_id="1001", sender_id="u2")

        assert plugin._is_group_extra_admin(event) is True
        assert plugin._is_tool_group_enabled_for_event(event, "git_status") is True
        assert plugin._is_tool_group_enabled_for_event(event, "safe_edit") is True
        assert plugin._is_tool_group_enabled_for_event(event, "git_push") is False

    def test_admin_still_bypasses_group_restrictions(self):
        plugin = _main_with_configs(
            {
                "__default__": {
                    "tool_groups": {"Git & GitHub": False},
                    "disabled_tools": ["git_status"],
                }
            }
        )
        event = DummyEvent(group_id="1001", sender_id="admin", admin=True)

        assert plugin._is_tool_allowed_for_event(event, "git_status") is True
