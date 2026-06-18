"""Tests for op_log local audit trail."""

import json

from tools import config as _tool_config
from tools import op_log


class TestOpLog:
    def test_record_and_recent_query(self, tmp_dir):
        import os
        db_path = f"{tmp_dir}/op_log_test1.db"
        # 确保使用新数据库
        if os.path.exists(db_path):
            os.remove(db_path)
        _tool_config.set_config({"op_log_db": db_path}, plugin_dir=tmp_dir)
        # 重置 session 避免之前测试的残留
        op_log.reset_session()
        # 强制刷新之前的 batch
        op_log._flush(force=True)
        # 重置计数
        op_log._BATCH.clear()
        # 重置初始化标记，确保使用新数据库
        op_log._INITIALIZED_DB = None
        # 关闭可能存在的旧连接
        if hasattr(op_log._CONN_LOCAL, 'conn') and op_log._CONN_LOCAL.conn is not None:
            try:
                op_log._CONN_LOCAL.conn.close()
            except Exception:
                pass
            op_log._CONN_LOCAL.conn = None

        op_log.record(
            "safe_edit",
            {"filepath": "a.py", "token": "secret-value"},
            json.dumps({"ok": True}),
            12,
        )
        # 强制刷新确保写入
        op_log._flush(force=True)
        result = op_log.query("recent", limit=5)

        assert result["ok"] is True
        assert result["total_entries"] >= 1
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
