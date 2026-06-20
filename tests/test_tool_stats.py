"""Tests for tool_stats — tool usage statistics.

Note: tool_stats uses global module-level state that persists across tests.
Tests in this class assume they run in order and state accumulates."""

from tools.tool_stats import record, snapshot


class TestToolStats:
    def test_empty_snapshot(self):
        r = snapshot()
        assert r["ok"] is True
        assert isinstance(r["tools"], dict)
        assert isinstance(r["total_calls"], int)

    def test_record_one_tool(self):
        record("test_tool_1")
        r = snapshot()
        assert "test_tool_1" in r["tools"]
        assert r["tools"]["test_tool_1"]["count"] >= 1

    def test_record_multiple_tools(self):
        record("tool_a_multi")
        record("tool_b_multi")
        record("tool_a_multi")
        r = snapshot()
        # These are unique names so we can assert exact counts
        assert r["tools"]["tool_a_multi"]["count"] == 2
        assert r["tools"]["tool_b_multi"]["count"] == 1

    def test_record_increments_count(self):
        record("counter_tool")
        r1 = snapshot()
        c1 = r1["tools"]["counter_tool"]["count"]
        record("counter_tool")
        r2 = snapshot()
        assert r2["tools"]["counter_tool"]["count"] == c1 + 1

    def test_record_has_timestamp(self):
        record("timestamp_test_ts")
        r = snapshot()
        assert r["tools"]["timestamp_test_ts"]["last"] > 0

    def test_record_empty_name(self):
        record("empty_name_test")
        r = snapshot()
        assert "empty_name_test" in r["tools"]
