"""pytest fixtures for irmia_devkit tests."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import config as _tool_config
from tools.tool_stats import reset as _reset_stats_fn


@pytest.fixture(autouse=True)
def _reset_config():
    """每个测试前重置全局配置，防止测试间互扰。"""
    _tool_config.set_config({}, plugin_dir="")


@pytest.fixture(autouse=True)
def _auto_reset_stats():
    """每个测试前重置工具统计，确保测试隔离。"""
    _reset_stats_fn()


@pytest.fixture
def tmp_dir():
    """临时目录，测试后自动清理。"""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def tmp_py_file(tmp_dir):
    """临时 Python 文件，写入简短示例代码。"""
    p = Path(tmp_dir) / "test.py"
    p.write_text("x = 1\ny = 2\nprint(x + y)\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def tmp_txt_file(tmp_dir):
    """临时文本文件。"""
    p = Path(tmp_dir) / "test.txt"
    p.write_text("hello world\nfoo bar\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def tmp_json_file(tmp_dir):
    """临时 JSON 配置文件。"""
    p = Path(tmp_dir) / "config.json"
    p.write_text('{"name": "test", "version": "1.0"}', encoding="utf-8")
    return str(p)


@pytest.fixture
def project_dir(tmp_dir):
    """迷你项目目录：含多个 .py 文件和 __pycache__。"""
    root = Path(tmp_dir) / "project"
    root.mkdir()
    (root / "main.py").write_text("from .utils import helper\ndef main(): pass\n", encoding="utf-8")
    (root / "utils.py").write_text("def helper(): return 42\n", encoding="utf-8")
    (root / "models.py").write_text("class User:\n    pass\n", encoding="utf-8")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-312.pyc").write_text("", encoding="utf-8")
    return str(root)


@pytest.fixture
def git_repo(tmp_dir):
    """带多个提交的临时 Git 仓库。"""
    root = Path(tmp_dir) / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=str(root), capture_output=True, timeout=10)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(root), capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=str(root), capture_output=True, timeout=10,
    )
    commits = [
        ("feat: add login feature", "login.py", "def login(): pass"),
        ("fix: fix crash on empty input", "bug.py", "def fix(): pass"),
        ("refactor: clean up auth module", "auth.py", "def auth(): pass"),
        ("docs: update readme", "README.md", "# Readme"),
        ("chore: bump version", "version.py", "v=2"),
    ]
    for msg, fname, content in commits:
        p = root / fname
        p.write_text(content)
        subprocess.run(["git", "add", "."], cwd=str(root), capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", msg], cwd=str(root), capture_output=True, timeout=10)
    return str(root)


# ── Mock fixtures for Phase 3 ──────────────────────────


@pytest.fixture
def mock_platform(monkeypatch):
    """Mock platform & os calls for sys_snapshot tests."""
    monkeypatch.setattr("platform.node", lambda: "test-host")
    monkeypatch.setattr("platform.platform", lambda: "Windows-10-10.0.19045")
    monkeypatch.setattr("platform.python_version", lambda: "3.12.12")
    monkeypatch.setattr("os.cpu_count", lambda: 8)


@pytest.fixture
def mock_processes(monkeypatch):
    """Mock psutil.process_iter for proc_list tests."""
    import psutil

    class FakeProc:
        def __init__(self, pid, name, memory_kb):
            self.info = {"pid": pid, "name": name, "memory_info": type("mi", (), {"rss": memory_kb * 1024})()}

    fake_procs = [
        FakeProc(1, "System Idle Process", 4),
        FakeProc(1234, "python.exe", 45_000),
        FakeProc(5678, "chrome.exe", 320_000),
        FakeProc(9012, "Code.exe", 180_000),
    ]
    monkeypatch.setattr("psutil.process_iter", lambda attrs=None: fake_procs)


@pytest.fixture
def mock_disk_usage(monkeypatch):
    """Mock shutil.disk_usage for disk_info tests."""
    DU = type("du", (), {"total": 512_000_000_000, "used": 256_000_000_000, "free": 256_000_000_000})
    monkeypatch.setattr("shutil.disk_usage", lambda path: DU())


@pytest.fixture
def mock_snapshot_cmds(monkeypatch):
    """Mock _run_cmd for sys_snapshot tests (avoids 4-6s systeminfo/tasklist)."""
    def _fake_run_cmd(cmd, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "systeminfo" in cmd_str:
            return {"ok": True, "stdout": "Total Physical Memory:     16,345 MB\nAvailable Physical Memory:  8,234 MB\n", "stderr": "", "code": 0}
        if "tasklist" in cmd_str:
            return {"ok": True, "stdout": "\"chrome.exe\",\"1234\",\"Console\",\"1\",\"320,000 K\"\n\"python.exe\",\"5678\",\"Console\",\"1\",\"45,000 K\"\n", "stderr": "", "code": 0}
        return {"ok": False, "stdout": "", "stderr": "", "code": 1}
    monkeypatch.setattr("tools.sys_snapshot._run_cmd", _fake_run_cmd)
