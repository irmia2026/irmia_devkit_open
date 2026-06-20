"""Tests for disk_info — disk space information."""

from tools.disk_info import info


class TestDiskInfo:
    def test_returns_drives(self, mock_disk_usage) -> None:
        r = info()
        assert "ok" in r
        if r["ok"]:
            assert "drives" in r
            assert len(r["drives"]) >= 1
            for drive in r["drives"]:
                assert "drive" in drive
                assert "total" in drive
                assert "used" in drive
                assert "free" in drive
                assert "percent" in drive
                assert isinstance(drive["total"], int)
                assert isinstance(drive["used"], int)
                assert isinstance(drive["free"], int)
                assert isinstance(drive["percent"], (float, int))
        else:
            assert "error" in r

    def test_drive_fields_present(self, mock_disk_usage) -> None:
        r = info()
        if r["ok"]:
            d = r["drives"][0]
            assert d["total"] > 0
            assert d["percent"] >= 0
