"""Tests for _auth — protect_tool, build_allowed_ids, and Layer 1 filtering."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from tools._auth import protect_tool, build_allowed_ids

_DEVKIT_TOOL_NAMES = {
    # 安全编辑链
    "safe_edit", "safe_rollback", "safe_backups", "file_patch", "file_preview",
    "safe_write", "syntax_check", "lint_runner", "test_runner", "multi_edit",
    # Git & GitHub
    "git_status", "git_diff", "git_log", "git_commit", "git_branch",
    "git_remote", "git_push", "gh_pr", "gh_issue", "gh_release", "gh_repo",
    # 文件系统
    "es_search", "rg_search", "dir_tree", "dir_list", "file_diff",
    "file_hash", "file_zip", "file_unzip", "disk_info",
    "file_remove", "config_diff",
    # 系统信息
    "proc_list", "sys_snapshot", "port_check", "tool_stats",
    # 执行与审计
    "shell_exec", "op_log",
    # 网络
    "http_get", "http_post", "http_download",
    # 文本处理
    "html_extract", "text_filter", "json_query",
    "csv_parse", "csv_gen", "diff_strings",
    "md_strip", "log_parse",
    # 编码与时间（合并）
    "encode_decode", "time",
    # 扩展
    "uuid_gen", "semver_compare", "project_init",
    "git_changelog", "db_query", "dep_scan",
    # 代码理解
    "code_index", "code_explore", "code_diff_impact", "code_pack",
    "code_status", "symbol_rename",
}


class MockTool:
    def __init__(self, name="test_tool"):
        self.name = name
        self.description = "test tool"
        self.parameters = {"type": "object", "properties": {}}
        self.handler_module_path = ""
        self.call_count = 0

    async def call(self, context, **kwargs):
        self.call_count += 1
        return json.dumps({"ok": True, "called": True})


def _make_context(role="member", sender_id="999"):
    ctx = MagicMock()
    event = MagicMock()
    event.role = role
    event.is_admin.return_value = (role == "admin")
    event.get_sender_id.return_value = sender_id
    ctx.context = MagicMock()
    ctx.context.event = event
    return ctx


# ── build_allowed_ids ──────────────────────────────────


class TestBuildAllowedIds:
    def test_from_plugin_config_string(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {}
        result = build_allowed_ids(ctx, {"allowed_ids": "123, 456, 789"})
        assert result == {"123", "456", "789"}

    def test_from_plugin_config_chinese_comma(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {}
        result = build_allowed_ids(ctx, {"allowed_ids": "111，222"})
        assert result == {"111", "222"}

    def test_from_plugin_config_list(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {}
        result = build_allowed_ids(ctx, {"allowed_ids": ["alice", "bob"]})
        assert result == {"alice", "bob"}

    def test_from_astrbot_admins(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {"admins_id": ["111", "222"]}
        result = build_allowed_ids(ctx, {})
        assert result == {"111", "222"}

    def test_combined(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {"admins_id": ["111"]}
        result = build_allowed_ids(ctx, {"allowed_ids": "333"})
        assert result == {"111", "333"}

    def test_astrbot_config_exception_graceful(self):
        ctx = MagicMock()
        ctx.get_config.side_effect = RuntimeError("boom")
        result = build_allowed_ids(ctx, {"allowed_ids": "123"})
        assert result == {"123"}

    def test_empty_all(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {}
        result = build_allowed_ids(ctx, {})
        assert result == set()

    def test_filters_empty_strings(self):
        ctx = MagicMock()
        ctx.get_config.return_value = {}
        result = build_allowed_ids(ctx, {"allowed_ids": "123,, , 456,"})
        assert result == {"123", "456"}


# ── protect_tool ───────────────────────────────────────


class TestProtectTool:
    def test_admin_passthrough(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123"})
        result = asyncio.run(wrapped.call(_make_context(role="admin", sender_id="999")))
        assert tool.call_count == 1
        data = json.loads(result)
        assert data["ok"] is True

    def test_allowed_id_passthrough(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123", "456"})
        result = asyncio.run(wrapped.call(_make_context(role="member", sender_id="123")))
        assert tool.call_count == 1
        data = json.loads(result)
        assert data["ok"] is True

    def test_unauthorized_blocked(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123"})
        result = asyncio.run(wrapped.call(_make_context(role="member", sender_id="999")))
        assert tool.call_count == 0
        data = json.loads(result)
        assert data["ok"] is False
        assert "权限不足" in data["error"]
        assert data["tool"] == "test_tool"
        assert data["sender_id"] == "999"

    def test_unauthorized_returns_structured_json(self):
        tool = MockTool(name="safe_edit")
        wrapped = protect_tool(tool, set())
        result = asyncio.run(wrapped.call(_make_context(role="member", sender_id="888")))
        data = json.loads(result)
        assert "ok" in data
        assert "error" in data
        assert "tool" in data
        assert "sender_id" in data

    def test_exception_in_guard_denies_access(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123"})
        ctx = MagicMock()
        ctx.context = MagicMock()
        broken_event = MagicMock()
        broken_event.get_sender_id.side_effect = RuntimeError("boom")
        broken_event.role = "member"
        ctx.context.event = broken_event
        result = asyncio.run(wrapped.call(ctx))
        assert tool.call_count == 0
        data = json.loads(result)
        assert data["ok"] is False
        assert "内部异常" in data["error"]

    def test_access_checker_passthrough(self):
        tool = MockTool()

        def checker(event, tool_name):
            return event.get_sender_id() == "extra" and tool_name == "test_tool"

        wrapped = protect_tool(tool, set(), checker)
        result = asyncio.run(wrapped.call(_make_context(role="member", sender_id="extra")))
        assert tool.call_count == 1
        data = json.loads(result)
        assert data["ok"] is True

    def test_access_checker_false_blocks(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123"}, lambda event, tool_name: False)
        result = asyncio.run(wrapped.call(_make_context(role="admin", sender_id="123")))
        assert tool.call_count == 0
        data = json.loads(result)
        assert data["ok"] is False

    def test_access_checker_exception_blocks(self):
        tool = MockTool()

        def checker(event, tool_name):
            raise RuntimeError("boom")

        wrapped = protect_tool(tool, {"123"}, checker)
        result = asyncio.run(wrapped.call(_make_context(role="admin", sender_id="123")))
        assert tool.call_count == 0
        data = json.loads(result)
        assert data["ok"] is False

    def test_protect_tool_returns_same_object(self):
        tool = MockTool()
        wrapped = protect_tool(tool, {"123"})
        assert wrapped is tool

    def test_protect_tool_preserves_metadata(self):
        tool = MockTool(name="safe_edit")
        tool.description = "desc"
        tool.parameters = {"type": "object"}
        wrapped = protect_tool(tool, set())
        assert wrapped.name == "safe_edit"
        assert wrapped.description == "desc"
        assert wrapped.parameters == {"type": "object"}


# ── Layer 1 filtering logic ───────────────────────────


class TestLayer1Filtering:
    """验证 _auth_guard 中按 handler_module_path 过滤插件的逻辑。"""

    @staticmethod
    def _filter(tools: list[MockTool]) -> tuple[list[str], list[MockTool]]:
        removed = []
        kept = []
        for tool in tools:
            if tool.name in _DEVKIT_TOOL_NAMES:
                removed.append(tool.name)
            else:
                kept.append(tool)
        return removed, kept

    def test_removes_own_plugin_tools(self):
        tools = [
            MockTool(name="safe_edit"),
            MockTool(name="git_status"),
            MockTool(name="sandbox_tool"),
        ]
        removed, kept = self._filter(tools)
        assert removed == ["safe_edit", "git_status"]
        assert len(kept) == 1
        assert kept[0].name == "sandbox_tool"

    def test_preserves_tools_not_in_names(self):
        tools = [
            MockTool(name="safe_edit"),
            MockTool(name="mcp_search"),
        ]
        removed, kept = self._filter(tools)
        assert removed == ["safe_edit"]
        assert len(kept) == 1
        assert kept[0].name == "mcp_search"

    def test_preserves_unknown_tools(self):
        tools = [
            MockTool(name="devkit_tool"),
            MockTool(name="unknown_tool"),
        ]
        removed, kept = self._filter(tools)
        assert removed == []  # "devkit_tool" not in _DEVKIT_TOOL_NAMES
        assert len(kept) == 2

    def test_no_devkit_tools_nothing_removed(self):
        tools = [
            MockTool(name="web_search"),
            MockTool(name="unknown_shell_exec"),
        ]
        removed, kept = self._filter(tools)
        assert removed == []
        assert len(kept) == 2

    def test_all_devkit_tools_all_removed(self):
        tools = [MockTool(name=f"tool_{i}") for i in range(5)]
        removed, kept = self._filter(tools)
        assert len(removed) == 0  # tool_0, tool_1, ... not in _DEVKIT_TOOL_NAMES
        assert len(kept) == 5
