"""Tests for _helpers — proposal_reply factory and helpers."""

import json
from tools._helpers import proposal_reply, err_json, unwrap


class TestProposalReply:
    def test_basic_error(self):
        r = proposal_reply(False, "something went wrong", error="read failed")
        assert r["ok"] is False
        assert r["proposal"] == "something went wrong"
        assert r["error"] == "read failed"
        assert "evidence" not in r
        assert "options" not in r

    def test_with_evidence_and_options(self):
        r = proposal_reply(
            False,
            "port not listening",
            error="connection refused",
            evidence={"host": "127.0.0.1", "port": 7860},
            options=["check service", "verify port"],
        )
        assert r["evidence"] == {"host": "127.0.0.1", "port": 7860}
        assert r["options"] == ["check service", "verify port"]

    def test_with_next_call(self):
        r = proposal_reply(
            False,
            "es not found",
            error="es.exe missing",
            next_call={"tool": "dir_list", "params": {"path": "."}},
        )
        assert r["next_call"]["tool"] == "dir_list"

    def test_extra_kwargs_flattened(self):
        r = proposal_reply(
            True, "found 3 issues", language="python", errors=[{"msg": "x"}]
        )
        assert r["language"] == "python"
        assert r["errors"] == [{"msg": "x"}]

    def test_falsy_options_not_added(self):
        r = proposal_reply(True, "all ok", options=[])
        assert "options" not in r

    def test_empty_evidence_not_added(self):
        r = proposal_reply(True, "ok", evidence={})
        assert "evidence" not in r

    def test_ok_true_no_error_field(self):
        r = proposal_reply(True, "ok")
        assert "error" not in r


class TestHelpers:
    def test_err_json(self):
        result = err_json("test error")
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"] == "test error"

    def test_unwrap_nested_error(self):
        result = unwrap({"ok": False, "error": "inner error"})
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"] == "inner error"

    def test_unwrap_error_preserves_extra_fields(self):
        """HTTP 错误保留 status/body：ok:false 且有其他字段时原样透传，不压扁。"""
        result = unwrap({"ok": False, "error": "HTTP 404: Not Found", "status": 404, "body": "missing"})
        data = json.loads(result)
        assert data["ok"] is False
        assert data["error"] == "HTTP 404: Not Found"
        assert data["status"] == 404
        assert data["body"] == "missing"

    def test_unwrap_success(self):
        result = unwrap({"ok": True, "data": [1, 2, 3]})
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"] == {"ok": True, "data": [1, 2, 3]}

    def test_unwrap_ok_true_with_proposal_pass_through(self):
        """ok=True 含 proposal→直接透传，不包 data 层（防 data.data 嵌套）"""
        result = unwrap({"ok": True, "proposal": "found 3 files", "count": 3})
        data = json.loads(result)
        assert data["ok"] is True
        assert data["proposal"] == "found 3 files"
        assert data["count"] == 3
        assert "data" not in data  # 不嵌套

    def test_unwrap_ok_false_with_proposal_pass_through(self):
        """ok=False 含 proposal→直接透传（已有行为，确保不倒退）"""
        result = unwrap({"ok": False, "proposal": "retry", "error": "timeout"})
        data = json.loads(result)
        assert data["ok"] is False
        assert data["proposal"] == "retry"
        assert data["error"] == "timeout"

    def test_unwrap_proposal_priority_over_ok(self):
        """proposal 字段优先级高于 ok 值——先检查 proposal"""
        # ok=True + proposal → pass through
        r1 = unwrap({"ok": True, "proposal": "x", "data": [1,2]})
        d1 = json.loads(r1)
        assert d1["data"] == [1,2]
        assert d1["ok"] is True
        # ok=False + proposal → pass through
        r2 = unwrap({"ok": False, "proposal": "x", "error": "y"})
        d2 = json.loads(r2)
        assert d2["proposal"] == "x"

    def test_unwrap_ok_true_plain_wraps_in_data(self):
        """纯 ok=True 无 proposal→正常包入 data"""
        result = unwrap({"ok": True, "count": 5})
        data = json.loads(result)
        assert data["ok"] is True
        assert data["data"]["count"] == 5
