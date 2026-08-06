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

    def test_large_value_truncated(self, tmp_dir):
        """P12: value 序列化后超过 500 字符时截断。"""
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        big_value = "v" * 1000
        a.write_text(json.dumps({"big": big_value, "small": 1}))
        b.write_text(json.dumps({"big": "short", "small": 1}))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        old = r["changed"]["big"]["old"]
        assert isinstance(old, str)
        assert old.startswith("<截断: ")
        assert old.endswith("...>")
        assert len(old) <= 500 + 16  # "<截断: " + 500 + "...>"
        assert r["changed"]["big"]["new"] == "short"
        # 未变化的小值不受影响
        assert r["unchanged"] == 1

    def test_added_large_value_truncated(self, tmp_dir):
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        a.write_text(json.dumps({}))
        b.write_text(json.dumps({"new_big": list(range(500))}))
        r = diff(str(a), str(b))
        assert r["ok"] is True
        assert r["added"]["new_big"].startswith("<截断: ")

    def test_file_over_10mb_rejected(self, tmp_dir):
        """P12: 单文件超过 10MB 返回结构化错误。"""
        a = Path(tmp_dir) / "a.json"
        b = Path(tmp_dir) / "b.json"
        # 10MB+ 的有效 JSON（单 key 大字符串）
        a.write_text(json.dumps({"pad": "x" * (10 * 1024 * 1024)}))
        b.write_text(json.dumps({"pad": "y"}))
        r = diff(str(a), str(b))
        assert r["ok"] is False
        assert "10MB" in r["error"]
        assert r["max_size"] == 10 * 1024 * 1024
