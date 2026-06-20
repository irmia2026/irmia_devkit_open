"""Tests for config — plugin configuration module."""

from pathlib import Path

from tools import config as cfg


class TestConfig:
    def setup_method(self):
        cfg.set_config({})

    def test_get_config_defaults(self):
        c = cfg.get_config()
        assert isinstance(c, dict)
        assert "backup_dir" in c  # set by set_config defaults

    def test_set_and_get(self):
        cfg.set_config({"owner_sid": "test_sid", "custom_key": "custom_val"})
        c = cfg.get_config()
        assert c["owner_sid"] == "test_sid"
        assert c["custom_key"] == "custom_val"

    def test_get_owner_sid(self):
        cfg.set_config({"owner_sid": "abc123"})
        assert cfg.get_owner_sid() == "abc123"

    def test_get_owner_sid_default(self):
        cfg.set_config({})
        assert cfg.get_owner_sid() == ""

    def test_get_plugin_dir_none(self):
        cfg.set_config({})
        assert cfg.get_plugin_dir() is None

    def test_get_plugin_dir_set(self):
        cfg.set_config({}, plugin_dir="/tmp/test_plugin")
        assert cfg.get_plugin_dir() is not None

    def test_default_keys_present(self):
        cfg.set_config({})
        c = cfg.get_config()
        assert "backup_dir" in c
        assert "gh_path" in c
        assert "es_path" in c
        assert "op_log_db" in c

    def test_config_immutable_across_calls(self):
        cfg.set_config({"my_key": "my_val"})
        c1 = cfg.get_config()
        cfg.set_config({"my_key": "updated"})
        c2 = cfg.get_config()
        assert c2["my_key"] == "updated"
