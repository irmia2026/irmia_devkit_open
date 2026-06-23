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
        op_log.record("shell_exec", {}, {"ok": False, "error": "fail"}, 50)
        result = op_log.query("stats")

        assert result["ok"] is True
        assert result["total_calls"] == 2
        assert result["ok_count"] == 1
        assert result["error_count"] == 1
        assert result["success_rate"] == 50.0
        assert result["avg_duration_ms"] == 35.0
        assert result["stats"][0]["tool_name"] == "shell_exec"

    def test_content_keys_truncated(self, tmp_dir):
        """old/new/content 等大文本参数应存为长度摘要，不存原文。"""
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        long_code = "def hello():\n    print('hello world')\n    return 42\n" * 5
        op_log.record(
            "safe_edit",
            {
                "filepath": "a.py",
                "old": long_code,
                "new": long_code.replace("hello", "goodbye"),
                "url": "https://example.com",
            },
            json.dumps({"ok": True}),
            12,
        )
        result = op_log.query("recent", limit=5)
        summary = result["recent"][0]["params_summary"]
        # old/new 应被截断为长度摘要
        assert "<str" in summary
        assert "def hello" not in summary
        # 短的非内容型值仍保留原文
        assert "https://example.com" in summary

    def test_short_content_keys_preserved(self, tmp_dir):
        """短于 80 字符的内容型参数仍保留原文。"""
        db_path = f"{tmp_dir}/op_log.db"
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)

        op_log.record(
            "file_patch",
            {"filepath": "b.py", "old": "x = 1", "new": "x = 2"},
            json.dumps({"ok": True}),
            5,
        )
        result = op_log.query("recent", limit=5)
        summary = result["recent"][0]["params_summary"]
        # 短文本保留
        assert '"x = 1"' in summary or "x = 1" in summary
        assert '"x = 2"' in summary or "x = 2" in summary
