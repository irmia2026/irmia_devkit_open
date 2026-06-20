"""Tests for sys_snapshot — system snapshot."""

from tools.sys_snapshot import snapshot


class TestSysSnapshot:
    def test_returns_basic_info(self, mock_platform, mock_snapshot_cmds) -> None:
        r = snapshot()
        assert r["ok"] is True
        info = r["info"]
        assert info["hostname"] == "test-host"
        assert info["platform"] == "Windows-10-10.0.19045"
        assert info["python"] == "3.12.12"
        assert "time" in info
        assert info["cpu_cores"] == 8

    def test_windows_fields_present(self, mock_platform, mock_snapshot_cmds) -> None:
        r = snapshot()
        info = r["info"]
        assert "total_memory_mb" in info
        assert "available_memory_mb" in info
        assert "process_count" in info

    def test_hostname_not_empty(self, mock_platform, mock_snapshot_cmds) -> None:
        r = snapshot()
        assert len(r["info"]["hostname"]) > 0
