"""Tests for _registry — TOOL_GROUPS ↔ _ALL_TOOLS consistency."""

import sys
import pytest


# _registry 依赖 astrbot.api，本地测试环境可能没有安装
try:
    from tools._registry import TOOL_GROUPS, _ALL_TOOLS
    HAS_ASTRBOT = True
except (ModuleNotFoundError, ImportError):
    HAS_ASTRBOT = False


@pytest.mark.skipif(not HAS_ASTRBOT, reason="astrbot 未安装，跳过注册表校验")
class TestRegistryConsistency:

    def test_no_orphan_in_tool_groups(self):
        """TOOL_GROUPS 中每个名字都必须在 _ALL_TOOLS 里"""
        for group, names in TOOL_GROUPS.items():
            for name in names:
                assert name in _ALL_TOOLS, (
                    f"TOOL_GROUPS['{group}'] 中的 '{name}' 不在 _ALL_TOOLS 里"
                )

    def test_no_orphan_in_all_tools(self):
        """_ALL_TOOLS 中每个名字都必须在 TOOL_GROUPS 的某个组里"""
        all_group_names = set()
        for names in TOOL_GROUPS.values():
            all_group_names.update(names)
        for name in _ALL_TOOLS:
            assert name in all_group_names, (
                f"_ALL_TOOLS 中的 '{name}' 不在任何 TOOL_GROUPS 组里"
            )

    def test_tool_group_counts_match_readme(self):
        """组计数与 README 声明一致"""
        expected = {
            "安全编辑链": 10,
            "Git & GitHub": 11,
            "文件系统": 13,
            "系统信息": 4,
            "执行与审计": 2,
            "网络": 3,
            "文本处理": 8,
            "编码/时间（合并）": 2,
            "扩展": 6,
            "代码理解": 6,
        }
        for group, expected_count in expected.items():
            actual = len(TOOL_GROUPS.get(group, []))
            assert actual == expected_count, (
                f"组 '{group}' 应为 {expected_count} 个工具，实际 {actual} 个"
            )

    def test_total_tool_count(self):
        """_ALL_TOOLS 总数应为 65（v2.6.4 全量 review 修复，工具数不变）"""
        assert len(_ALL_TOOLS) == 65

    def test_no_duplicate_tool_names(self):
        """TOOL_GROUPS 中跨组不得重名"""
        seen = {}
        for group, names in TOOL_GROUPS.items():
            for name in names:
                assert name not in seen, (
                    f"'{name}' 同时出现在 TOOL_GROUPS['{seen[name]}'] 和 TOOL_GROUPS['{group}']"
                )
                seen[name] = group

    def test_all_tool_names_have_class(self):
        """_ALL_TOOLS 中的每个值都必须是 class（非 None/非 str 等）"""
        for name, cls in _ALL_TOOLS.items():
            assert isinstance(cls, type), (
                f"_ALL_TOOLS['{name}'] = {cls!r} 不是 class"
            )

    def test_all_classes_have_name_attribute(self):
        """每个工具类的 name 字段必须与 _ALL_TOOLS 的 key 一致"""
        for key, cls in _ALL_TOOLS.items():
            instance = cls()
            assert instance.name == key, (
                f"class {cls.__name__}.name='{instance.name}' 但 _ALL_TOOLS key='{key}'"
            )

    def test_codegraph_wrappers_close_connections(self, monkeypatch, tmp_dir):
        """5 个 codegraph 注册层包装函数必须关闭 CodeGraph 连接。"""
        import tools._registry as registry

        calls = []

        class FakeCodeGraph:
            def __init__(self, db_path):
                self.db_path = db_path
                self.closed = False

            def close(self):
                self.closed = True
                calls.append(("close", self.db_path))

            def index(self, project_dir, incremental=False):
                calls.append(("index", project_dir, incremental))
                return {"ok": True}

            def explore(self, query, project_dir="."):
                calls.append(("explore", query, project_dir))
                return {"ok": True}

            def code_diff_impact(self, filepaths, max_depth=3, project_dir="."):
                calls.append(("impact", filepaths, max_depth, project_dir))
                return {"ok": True}

            def code_pack(self, target, depth=2, mode="both", project_dir="."):
                calls.append(("pack", target, depth, mode, project_dir))
                return {"ok": True}

            def code_status(self, project_dir="."):
                calls.append(("status", project_dir))
                return {"ok": True}

        monkeypatch.setattr(registry, "_CodeGraph", FakeCodeGraph)

        registry._code_index(tmp_dir)
        registry._code_explore("helper", tmp_dir)
        registry._code_diff_impact(["a.py"])
        registry._code_pack("helper")
        registry._code_status()

        assert len([c for c in calls if c[0] == "close"]) == 5
