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

    def test_admin_bypasses_identity_but_respects_tool_restrictions(self):
        plugin = _main_with_configs(
            {
                "__default__": {
                    "tool_groups": {"Git & GitHub": False},
                    "disabled_tools": ["git_status"],
                }
            }
        )
        event = DummyEvent(group_id="1001", sender_id="admin", admin=True)

        assert plugin._is_tool_allowed_for_event(event, "git_status") is False
        assert plugin._is_tool_allowed_for_event(event, "safe_edit") is True

    def test_policy_cache_reuses_normalized_policy_and_invalidates(self):
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

        first = plugin._group_policy_for_event(event)
        second = plugin._group_policy_for_event(event)
        assert first is second
        assert len(plugin._group_policy_cache) == 1

        plugin._group_configs_cache["__default__"]["disabled_tools"] = []
        plugin._invalidate_group_policy_cache()
        refreshed = plugin._group_policy_for_event(event)
        assert refreshed is not first
        assert plugin._is_tool_group_enabled_for_event(event, "safe_edit") is True

    def test_default_policy_is_shared_by_unconfigured_chats(self):
        plugin = _main_with_configs(
            {"__default__": {"disabled_tools": ["safe_edit"]}}
        )
        default_policy = plugin._group_policy_for_event(DummyEvent())

        for index in range(200):
            assert plugin._group_policy_for_event(
                DummyEvent(group_id=str(index))
            ) is default_policy
        assert plugin._group_policy_for_event(
            DummyEvent(group_id="", sender_id="private-user")
        ) is default_policy
        assert list(plugin._group_policy_cache) == ["__default__"]

    def test_private_override_stays_separate_from_group_and_default(self):
        plugin = _main_with_configs(
            {
                "__default__": {"disabled_tools": ["safe_edit"]},
                "private:u1": {"extra_admin_ids": "u1", "disabled_tools": []},
            }
        )
        private_event = DummyEvent(group_id="", sender_id="u1")

        assert plugin._is_tool_allowed_for_event(private_event, "safe_edit") is True
        assert plugin._is_tool_group_enabled_for_event(
            DummyEvent(group_id="u1"), "safe_edit"
        ) is False
        assert plugin._is_tool_group_enabled_for_event(
            DummyEvent(group_id="", sender_id="u2"), "safe_edit"
        ) is False

    def test_policy_cache_evicts_least_recently_used_override(self):
        plugin = _main_with_configs({"__default__": {"tool_groups": {}}})

        for index in range(128):
            plugin._group_configs_cache[str(index)] = {"tool_groups": {}}
            plugin._group_policy_for_event(DummyEvent(group_id=str(index)))

        first = plugin._group_policy_for_event(DummyEvent(group_id="0"))
        plugin._group_configs_cache["128"] = {"tool_groups": {}}
        plugin._group_policy_for_event(DummyEvent(group_id="128"))

        assert len(plugin._group_policy_cache) == 128
        assert "1" not in plugin._group_policy_cache
        assert plugin._group_policy_for_event(DummyEvent(group_id="0")) is first

    def test_disabling_group_config_bypasses_cached_policy(self):
        plugin = _main_with_configs(
            {"__default__": {"disabled_tools": ["safe_edit"]}}
        )
        event = DummyEvent()
        assert plugin._is_tool_group_enabled_for_event(event, "safe_edit") is False
        plugin._group_config_enabled = False
        assert plugin._is_tool_group_enabled_for_event(event, "safe_edit") is True
