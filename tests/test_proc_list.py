"""Tests for proc_list — process listing."""

from tools.proc_list import list_processes


class TestProcList:
    def test_returns_processes(self, mock_processes) -> None:
        r = list_processes()
        assert r["ok"] is True
        assert r["count"] >= 1
        assert len(r["processes"]) >= 1

    def test_expected_fields(self, mock_processes) -> None:
        r = list_processes()
        proc = r["processes"][0]
        assert "name" in proc
        assert "pid" in proc
        assert "memory_kb" in proc
        assert isinstance(proc["pid"], int)
        assert proc["pid"] > 0

    def test_filter_by_name(self, mock_processes) -> None:
        r = list_processes(filter_name="python")
        assert r["ok"] is True
        assert r["filter"] == "python"
        # Should find the mocked python.exe process
        assert r["count"] >= 1

    def test_filter_no_match(self, mock_processes) -> None:
        r = list_processes(filter_name="zzz_nonexistent_process_xyz")
        assert r["ok"] is True
        assert r["count"] == 0

    def test_processes_sorted_by_memory(self, mock_processes) -> None:
        r = list_processes()
        if r["count"] >= 2:
            mems = [p["memory_kb"] for p in r["processes"]]
            assert mems == sorted(mems, reverse=True)
