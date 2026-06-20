"""Tests for config_diff — Configuration file comparison."""

import json
from pathlib import Path

from tools.config_diff import diff


class TestConfigDiff:
    def test_identical_configs(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        data = {"name": "test", "version": "1.0", "debug": True}
        a.write_text(json.dumps(data))
        b.write_text(json.dumps(data))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["unchanged"] == 3
        assert r["added_count"] == 0
        assert r["removed_count"] == 0
        assert r["changed_count"] == 0
        assert "完全相同" in r.get("proposal", "")

    def test_added_and_removed_keys(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text(json.dumps({"a": 1, "b": 2}))
        b.write_text(json.dumps({"a": 1, "c": 3}))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["removed"] == {"b": 2}
        assert r["added"] == {"c": 3}

    def test_changed_values(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text(json.dumps({"key": "old"}))
        b.write_text(json.dumps({"key": "new"}))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["changed"]["key"]["old"] == "old"
        assert r["changed"]["key"]["new"] == "new"

    def test_file_a_not_found(self, tmp_dir):
        b = Path(tmp_dir) / "b.json"
        b.write_text("{}")
        r = diff(str(Path(tmp_dir) / "nonexistent.json"), str(b))
        assert r["ok"] is False
        assert "不存在" in r.get("error", "")

    def test_file_b_not_found(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        a.write_text("{}")
        r = diff(str(a), str(Path(tmp_dir) / "nonexistent.json"))
        assert r["ok"] is False

    def test_invalid_json(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text("{invalid}")
        b.write_text("{}")
        r = diff(str(a), str(b))
        assert r["ok"] is False
        assert "无法解析" in r.get("error", "")

    def test_empty_objects(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text("{}")
        b.write_text("{}")
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["unchanged"] == 0  # no keys at all
        assert r["added_count"] == 0

    def test_mixed_changes(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text(json.dumps({"stable": 1, "removed_key": 2, "changed_key": "old"}))
        b.write_text(json.dumps({"stable": 1, "added_key": 3, "changed_key": "new"}))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["unchanged"] == 1
        assert "removed_key" in r["removed"]
        assert "added_key" in r["added"]
        assert "changed_key" in r["changed"]
