"""Static registry checks that do not require AstrBot to be installed."""

import ast
from pathlib import Path


def _dict_keys(node: ast.Dict) -> list[str]:
    result = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            result.append(key.value)
    return result


def _string_list(node: ast.List) -> list[str]:
    result = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            result.append(item.value)
    return result


def _load_registry_literals():
    source = Path("tools/_registry.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    groups = {}
    all_tools = []
    for node in module.body:
        value = None
        target_name = ""
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        if target_name == "TOOL_GROUPS" and isinstance(value, ast.Dict):
            for key, val in zip(value.keys, value.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    groups[key.value] = _string_list(val)
        if target_name == "_ALL_TOOLS" and isinstance(value, ast.Dict):
            all_tools = _dict_keys(value)
    return groups, all_tools


class TestRegistryStatic:
    def test_tool_groups_and_all_tools_match(self):
        groups, all_tools = _load_registry_literals()
        grouped = {name for names in groups.values() for name in names}

        assert grouped == set(all_tools)
        assert len(groups) == 10
        assert len(all_tools) == 65
        assert sum(len(names) for names in groups.values()) == 65

    def test_new_v250_tools_registered(self):
        groups, all_tools = _load_registry_literals()

        assert "test_runner" in groups["安全编辑链"]
        assert "multi_edit" in groups["安全编辑链"]
        assert "safe_write" in groups["安全编辑链"]
        assert groups["执行与审计"] == ["shell_exec", "op_log"]
        assert "symbol_rename" in groups["代码理解"]
        assert "encode_decode" in all_tools
        assert "time" in all_tools
        for name in ("test_runner", "multi_edit", "safe_write", "shell_exec", "op_log", "symbol_rename", "encode_decode", "time"):
            assert name in all_tools
