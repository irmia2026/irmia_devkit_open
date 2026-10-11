"""Tests for custom_workspace — 自定义工作区目录定向放行（默认关闭，零行为变化）。

平台无关设计：用 monkeypatch 把临时目录注入 _FORBIDDEN_PREFIXES，
模拟"工作区位于系统目录等危险区域"的场景，不依赖真实 /etc 等路径。
注意 safe_write 在模块级 from-import 了黑名单，需单独 patch 其命名空间副本。
"""

import os
import sys
from pathlib import Path

import pytest

from tools import config as _tool_config
from tools import file_remove as _file_remove_mod
from tools import safe_write as _safe_write_mod
from tools._file_utils import (
    check_path_allowed,
    custom_workspace_allows,
    _custom_workspace_root,
)
from tools.file_diff import compare as file_diff
from tools.file_hash import compute as file_hash
from tools.file_patch import patch as file_patch, preview as file_preview
from tools.file_remove import move as file_move
from tools.file_remove import remove as file_remove
from tools.multi_edit import run as multi_edit
from tools.safe_edit import edit as safe_edit, rollback as safe_rollback
from tools.safe_read import read as safe_read
from tools.safe_write import write as safe_write


@pytest.fixture
def danger_dirs(tmp_path_factory):
    """两个同被拉黑的兄弟目录，兼验前缀边界：

    - ws_dir   名为 workspace，将配置为自定义工作区
    - evil_dir 名为 workspace-evil，与 ws_dir 共享字符串前缀但必须仍被拦截
    """
    root = tmp_path_factory.mktemp("custom_ws")
    ws_dir = root / "workspace"
    evil_dir = root / "workspace-evil"
    ws_dir.mkdir()
    evil_dir.mkdir()
    return ws_dir, evil_dir


@pytest.fixture
def blacklist(danger_dirs, monkeypatch):
    """把两个临时目录追加进黑名单，平台无关地模拟"工作区位于危险区域"。

    保留原始 _FORBIDDEN_PREFIXES —— 真实系统目录（/etc 等）在测试中同样生效。
    """
    ws_dir, evil_dir = danger_dirs
    fake = [str(ws_dir.resolve()), str(evil_dir.resolve())] + list(_file_remove_mod._FORBIDDEN_PREFIXES)
    # _file_utils._check_path_safety 在函数内 import、file_remove 走模块全局，
    # patch 模块属性即可；safe_write 是模块级 from-import，需单独 patch。
    monkeypatch.setattr(_file_remove_mod, "_FORBIDDEN_PREFIXES", fake)
    monkeypatch.setattr(_safe_write_mod, "_FORBIDDEN_PREFIXES", fake)
    return ws_dir, evil_dir


def _configure_workspace(ws_dir: Path) -> None:
    """配置自定义工作区 + 隔离备份目录。"""
    _tool_config.set_config({
        "custom_workspace": str(ws_dir),
        "backup_dir": str(ws_dir.parent / "backups"),
    })


class TestUnconfiguredByDefault:
    """未配置 custom_workspace：所有行为与引入本功能前完全一致。"""

    def test_check_path_allowed_blocks(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "app.py"
        result = check_path_allowed(target)
        assert result is not None
        assert result["ok"] is False
        assert "系统目录" in result["error"]

    def test_safe_edit_blocked_file_intact(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "app.py"
        target.write_text("x = 1\ny = 2\n", encoding="utf-8")
        result = safe_edit(str(target), "x = 1", "x = 42")
        assert result["ok"] is False
        assert "系统目录" in result["error"]
        assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\n"

    def test_safe_write_blocked_no_file(self, blacklist):
        ws_dir, _ = blacklist
        result = safe_write(str(ws_dir / "new.py"), "x = 1\n")
        assert result["ok"] is False
        assert "系统目录" in result["error"]
        assert not (ws_dir / "new.py").exists()

    def test_safe_write_overwrite_blocked(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = safe_write(str(target), "x = 2\n", overwrite=True)
        assert result["ok"] is False
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    def test_multi_edit_blocked(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = multi_edit([{"file": str(target), "old": "x = 1", "new": "x = 2"}])
        assert result["ok"] is False
        assert target.read_text(encoding="utf-8") == "x = 1\n"

    def test_file_patch_and_preview_blocked(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "note.txt"
        target.write_text("hello\n", encoding="utf-8")
        assert file_patch(str(target), "hello", "hi")["ok"] is False
        assert file_preview(str(target), "hello", "hi")["ok"] is False
        assert target.read_text(encoding="utf-8") == "hello\n"

    def test_read_side_blocked(self, blacklist):
        ws_dir, _ = blacklist
        target = ws_dir / "note.txt"
        target.write_text("hello\n", encoding="utf-8")
        assert safe_read(str(target))["ok"] is False
        assert file_diff(str(target), str(target))["ok"] is False
        assert file_hash(str(target))["ok"] is False


class TestConfiguredWorkspace:
    """配置 custom_workspace 后：安全编辑链与配套读取在工作区内恢复可用。"""

    def test_check_path_allows_inside(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        deep = ws_dir / "sub" / "deep" / "app.py"  # 深层子目录同样放行
        deep.parent.mkdir(parents=True)
        assert check_path_allowed(deep) is None
        assert check_path_allowed(ws_dir) is None  # 目录本身也放行
        assert custom_workspace_allows(str(deep.resolve()).replace("\\", "/")) is True

    def test_safe_edit_and_rollback(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        target = ws_dir / "app.py"
        target.write_text("x = 1\ny = 2\n", encoding="utf-8")
        result = safe_edit(str(target), "x = 1", "x = 42")
        assert result["ok"] is True
        assert "x = 42" in target.read_text(encoding="utf-8")
        rb = safe_rollback(str(target))
        assert rb["ok"] is True
        assert target.read_text(encoding="utf-8") == "x = 1\ny = 2\n"

    def test_safe_write_create_and_overwrite(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        result = safe_write(str(ws_dir / "new.py"), "x = 1\n")
        assert result["ok"] is True and result["created"] is True
        result2 = safe_write(str(ws_dir / "new.py"), "x = 2\n", overwrite=True)
        assert result2["ok"] is True
        assert (ws_dir / "new.py").read_text(encoding="utf-8") == "x = 2\n"

    def test_multi_edit_atomic(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        a = ws_dir / "a.py"
        a.write_text("x = 1\n", encoding="utf-8")
        b = ws_dir / "b.py"
        b.write_text("y = 1\n", encoding="utf-8")
        result = multi_edit([
            {"file": str(a), "old": "x = 1", "new": "x = 2"},
            {"file": str(b), "old": "y = 1", "new": "y = 2"},
        ])
        assert result["ok"] is True
        assert "x = 2" in a.read_text(encoding="utf-8")
        assert "y = 2" in b.read_text(encoding="utf-8")

    def test_file_patch_and_preview(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        target = ws_dir / "note.txt"
        target.write_text("hello world\n", encoding="utf-8")
        assert file_preview(str(target), "hello", "hi")["ok"] is True
        assert file_patch(str(target), "hello", "hi")["ok"] is True
        assert target.read_text(encoding="utf-8") == "hi world\n"

    def test_read_side_allowed(self, blacklist):
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        target = ws_dir / "note.txt"
        target.write_text("hello\nworld\n", encoding="utf-8")
        assert safe_read(str(target))["ok"] is True
        assert file_diff(str(target), str(target))["ok"] is True
        assert file_hash(str(target))["ok"] is True


class TestSafetyBoundaries:
    """配置 custom_workspace 后依然保持的安全边界。"""

    def test_sibling_prefix_dir_still_blocked(self, blacklist):
        """workspace-evil 与 workspace 共享字符串前缀，但绝不能被误放行。"""
        ws_dir, evil_dir = blacklist
        _configure_workspace(ws_dir)
        result = check_path_allowed(evil_dir / "app.py")
        assert result is not None
        assert result["ok"] is False

    def test_dotdot_traversal_still_blocked(self, blacklist):
        """.. 穿越永远拦截 —— 即使从工作区内部发起。"""
        ws_dir, evil_dir = blacklist
        _configure_workspace(ws_dir)
        evil_file = evil_dir / "app.py"
        evil_file.write_text("x = 1\n", encoding="utf-8")
        traversal = str(ws_dir / ".." / "workspace-evil" / "app.py")
        result = check_path_allowed(traversal)
        assert result is not None
        assert ".." in result["error"]
        assert safe_edit(traversal, "x = 1", "x = 2")["ok"] is False
        assert evil_file.read_text(encoding="utf-8") == "x = 1\n"

    def test_file_remove_still_blocked(self, blacklist):
        """删除不享受放行 —— 黑名单区域内的文件始终不可删。"""
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        target = ws_dir / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        result = file_remove(str(target))
        assert result["ok"] is False
        assert "系统目录" in result["error"]
        assert target.exists()

    def test_file_move_still_blocked(self, blacklist):
        """移出不享受放行 —— 黑名单区域内的文件始终不可移动。"""
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        target = ws_dir / "app.py"
        target.write_text("x = 1\n", encoding="utf-8")
        dest = ws_dir.parent / "dest"
        result = file_move([str(target)], str(dest))
        assert result["ok"] is False
        assert target.exists()

    def test_filesystem_root_ignored(self, blacklist):
        """/ 或盘符根会被忽略 —— 防止配置成根目录变相放行整盘。"""
        ws_dir, _ = blacklist
        fs_root = os.path.abspath(os.sep)
        _tool_config.set_config({"custom_workspace": fs_root})
        assert _custom_workspace_root() is None
        result = check_path_allowed(ws_dir / "app.py")
        assert result is not None
        assert result["ok"] is False

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX 真实黑名单路径 /etc")
    def test_real_system_prefix_still_blocked_posix(self, blacklist):
        """配置工作区后，真实系统目录（/etc）仍然拦截。"""
        ws_dir, _ = blacklist
        _configure_workspace(ws_dir)
        result = check_path_allowed("/etc/passwd")
        assert result is not None
        assert result["ok"] is False


class TestWorkspaceHelpers:
    """_custom_workspace_root / custom_workspace_allows 单元行为。"""

    def test_default_config_value(self):
        """set_config({}) 后 custom_workspace 默认为空串，放行恒为 False。"""
        _tool_config.set_config({})
        assert _tool_config.get_config().get("custom_workspace", "unset") == ""
        assert _custom_workspace_root() is None
        assert custom_workspace_allows("/etc/passwd") is False
        assert custom_workspace_allows("C:/Windows/System32/x.dll") is False

    def test_trailing_slash_normalized(self, danger_dirs):
        ws_dir, _ = danger_dirs
        _tool_config.set_config({"custom_workspace": str(ws_dir) + os.sep + os.sep})
        expected = str(ws_dir.resolve()).replace("\\", "/")
        assert _custom_workspace_root() == expected
        assert custom_workspace_allows(expected + "/a.py") is True

    def test_case_insensitive_and_boundary(self, danger_dirs):
        ws_dir, evil_dir = danger_dirs
        _tool_config.set_config({"custom_workspace": str(ws_dir)})
        ws_norm = str(ws_dir.resolve()).replace("\\", "/")
        assert custom_workspace_allows(ws_norm) is True
        assert custom_workspace_allows(ws_norm + "/a.py") is True
        assert custom_workspace_allows(ws_norm.upper() + "/A.PY") is True
        evil_norm = str(evil_dir.resolve()).replace("\\", "/")
        assert custom_workspace_allows(evil_norm + "/a.py") is False
