"""Tests for op_log local audit trail."""

import json

from tools import config as _tool_config
from tools import op_log


class TestOpLog:
    def test_record_and_recent_query(self, tmp_dir):
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        op_log.record(
            "safe_edit",
            {"filepath": "a.py", "token": "secret-value"},
            json.dumps({"ok": True}),
            12,
        )
        result = op_log.query("recent", limit=5)

        assert result["ok"] is True
        assert result["total_entries"] == 1
        assert result["recent"][0]["tool_name"] == "safe_edit"
        assert result["recent"][0]["file_paths"] == "a.py"
        assert "<redacted>" in result["recent"][0]["params_summary"]

    def test_redacts_api_key_and_private_key(self, tmp_dir):
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        op_log.record(
            "http_get",
            {"url": "https://api.example.com", "api_key": "AKIAEXAMPLE", "private_key": "-----BEGIN RSA PRIVATE KEY-----"},
            json.dumps({"ok": True}),
            8,
        )
        result = op_log.query("recent", limit=5)
        summary = result["recent"][0]["params_summary"]
        assert "<redacted>" in summary
        assert "AKIAEXAMPLE" not in summary
        assert "BEGIN RSA PRIVATE KEY" not in summary

    def test_error_query(self, tmp_dir):
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        op_log.record("test_runner", {}, {"ok": False, "error": "boom"}, 5)
        result = op_log.query("errors")

        assert result["ok"] is True
        assert result["errors"][0]["tool_name"] == "test_runner"
        assert result["errors"][0]["result"] == "error"
        assert result["errors"][0]["error_msg"] == "boom"

    def test_file_query_requires_file(self, tmp_dir):
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        result = op_log.query("file")

        assert result["ok"] is False
        assert "file is required" in result["error"]

    def test_stats_query(self, tmp_dir):
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        op_log.record("shell_exec", {}, {"ok": True}, 20)
        result = op_log.query("stats")

        assert result["ok"] is True
        assert result["stats"][0]["tool_name"] == "shell_exec"
