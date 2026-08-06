"""Tests for lint_runner — linter auto-detection and fallback."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools.lint_runner import run, _detect


@pytest.fixture
def py_file():
    """临时 Python 文件"""
    fd, path = tempfile.mkstemp(suffix=".py", text=True)
    with os.fdopen(fd, "w") as f:
        f.write("x = 1\ny = 2\nprint(x + y)\n")
    yield path
    os.unlink(path)


@pytest.fixture
def js_file():
    """临时 JS 文件"""
    fd, path = tempfile.mkstemp(suffix=".js", text=True)
    with os.fdopen(fd, "w") as f:
        f.write("const x = 1;\nconsole.log(x);\n")
    yield path
    os.unlink(path)


class TestLintRunnerBasic:
    def test_file_not_found(self):
        result = run("/nonexistent/file.py")
        assert result["ok"] is False
        assert "不存在" in result["error"]

    def test_unsupported_linter(self, py_file):
        result = run(py_file, linter="madeup_linter")
        assert result["ok"] is False
        assert "不支持" in result["error"]

    def test_explicit_ruff(self, py_file):
        result = run(py_file, linter="ruff")
        assert "ok" in result
        # ruff 可能未安装，但至少要返回 ok 或 error
        if not result["ok"]:
            assert "未安装" in result["error"]

    def test_explicit_pylint(self, py_file):
        result = run(py_file, linter="pylint")
        assert "ok" in result
        if not result["ok"]:
            assert "未安装" in result["error"]

    def test_eslint_on_js(self, js_file):
        result = run(js_file, linter="eslint")
        assert "ok" in result
        if not result["ok"]:
            assert "未安装" in result["error"]


class TestLinterDetect:
    def test_js_detects_eslint(self, js_file):
        linter = _detect(Path(js_file))
        assert linter == "eslint"

    def test_python_detects_valid_linter(self, py_file):
        linter = _detect(Path(py_file))
        assert linter in ("ruff", "pylint")

    def test_js_always_returns_eslint(self):
        """JS 文件只有一个 eslint 选项"""
        p = Path("/tmp/test.jsx")
        assert _detect(p) == "eslint"
        p = Path("/tmp/test.ts")
        assert _detect(p) == "eslint"
        p = Path("/tmp/test.mjs")
        assert _detect(p) == "eslint"


class TestLinterFallback:
    def test_ruff_fallback_signal(self, py_file):
        """当 ruff 未安装且 pylint 可用时，_run_ruff 返回 fallback"""
        from tools.lint_runner import _run_ruff
        result = _run_ruff(Path(py_file))
        if not result["ok"]:
            assert "未安装" in result["error"]
            if "fallback" in result:
                assert result["fallback"] in ("pylint",)

    def test_pylint_fallback_signal(self, py_file):
        """当 pylint 未安装且 ruff 可用时，_run_pylint 返回 fallback"""
        from tools.lint_runner import _run_pylint
        result = _run_pylint(Path(py_file))
        if not result["ok"]:
            assert "未安装" in result["error"]

    def test_auto_fallback_chain(self, py_file):
        """linter=auto 时即使首选未安装也会尝试 fallback"""
        result = run(py_file, linter="auto")
        assert "ok" in result
        # 如果返回的 linter 不是安装的，说明 fallback 生效
        # 至少不能直接返回 "ruff 未安装" 的错误而不尝试 pylint
        if not result["ok"] and "未安装" in result.get("error", ""):
            # 两个都没装
            assert "均未安装" in result["error"]


class TestProbeCache:
    """_find_ruff / _detect 的探测结果模块级缓存（TTL 300 秒）。"""

    def test_find_ruff_result_cached(self, monkeypatch):
        import tools.lint_runner as lr

        lr._find_ruff_cache = None
        lr._which_cache.clear()
        first = lr._find_ruff()
        # TTL 内篡改 which/subprocess，第二次应仍返回缓存结果而不重新探测
        monkeypatch.setattr(lr.shutil, "which", lambda cmd: None)

        def boom(*a, **k):
            raise RuntimeError("should not be called")

        monkeypatch.setattr(lr.subprocess, "run", boom)
        assert lr._find_ruff() == first
        lr._find_ruff_cache = None
        lr._which_cache.clear()

    def test_detect_which_probe_cached(self, monkeypatch):
        import shutil as _shutil

        import tools.lint_runner as lr

        lr._which_cache.clear()
        calls = []
        real_which = _shutil.which

        def counting_which(cmd):
            calls.append(cmd)
            return real_which(cmd)

        monkeypatch.setattr(lr.shutil, "which", counting_which)
        p = Path("some_file.py")
        lr._detect(p)
        lr._detect(p)
        assert calls.count("ruff") == 1
        lr._which_cache.clear()