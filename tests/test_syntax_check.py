"""Tests for syntax_check — multi-language syntax validation."""

import os
import tempfile
from pathlib import Path

import pytest

from tools.syntax_check import check


def _write_temp(suffix, content):
    fd, path = tempfile.mkstemp(suffix=suffix, text=True)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestSyntaxCheckPython:

    def test_valid_python(self):
        path = _write_temp(".py", "x = 1\ny = 2\nprint(x + y)\n")
        try:
            result = check(path)
            assert result["ok"] is True
            assert result["language"] == "python"
        finally:
            os.unlink(path)

    def test_syntax_error(self):
        path = _write_temp(".py", "x = \ny = 2\n")
        try:
            result = check(path)
            assert result["ok"] is False
            assert "errors" in result
            assert len(result["errors"]) >= 1
        finally:
            os.unlink(path)

    def test_syntax_error_has_context(self):
        """P0 feature: 语法错误返回上下文代码片段"""
        path = _write_temp(".py", "def foo():\n    x = \n    return x\n")
        try:
            result = check(path)
            assert result["ok"] is False
            err = result["errors"][0]
            assert "context" in err, "错误应包含 context 字段"
            assert len(err["context"]) >= 1
            # 至少有一行带 → 标记（错误行）
            assert any("→" in line for line in err["context"])
        finally:
            os.unlink(path)

    def test_syntax_error_has_line_and_col(self):
        path = _write_temp(".py", "x = \ny = 2\n")
        try:
            result = check(path)
            assert result["ok"] is False
            err = result["errors"][0]
            assert "line" in err
            assert err["line"] > 0
        finally:
            os.unlink(path)

    def test_file_not_found(self):
        result = check("/nonexistent/file.py")
        assert result["ok"] is False
        assert "不存在" in result["error"]

    def test_unknown_extension(self):
        path = _write_temp(".xyz", "some content")
        try:
            result = check(path)
            assert result["ok"] is True
            assert "note" in result
        finally:
            os.unlink(path)

    def test_gbk_fallback(self):
        """UTF-8 失败时回退 GBK"""
        path = _write_temp(".py", "x = '中文'\n")
        try:
            result = check(path)
            assert result["ok"] is True
        finally:
            os.unlink(path)


class TestSyntaxCheckOther:

    def test_go_skipped_if_not_installed(self):
        path = _write_temp(".go", "package main\nfunc main() {}\n")
        try:
            result = check(path)
            # go 可能未安装 → skipped:true 或 ok:true
            assert result["ok"] is True
        finally:
            os.unlink(path)

    def test_nim_skipped_if_not_installed(self):
        path = _write_temp(".nim", "echo 1\n")
        try:
            result = check(path)
            assert result["language"] == "nim"
            if result["ok"] is False:
                assert "skipped" not in result.get("error", "")
        finally:
            os.unlink(path)

    def test_js_node_skipped_if_not_installed(self):
        path = _write_temp(".js", "console.log('hi');\n")
        try:
            result = check(path)
            assert result["ok"] is True
        finally:
            os.unlink(path)


def _check_or_skip(path):
    """工具链不可用时跳过，可用时返回结果供严格断言。"""
    result = check(path)
    if result.get("skipped"):
        pytest.skip(f"工具链不可用: {result.get('language')}")
    return result


class TestSyntaxCheckRust:

    def test_valid_rust(self):
        path = _write_temp(".rs", "fn main() { let x = 1; }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "rust"
        finally:
            os.unlink(path)

    def test_invalid_rust(self):
        path = _write_temp(".rs", "fn main() { let x = ; }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
            assert "errors" in result
        finally:
            os.unlink(path)


class TestSyntaxCheckCCpp:

    def test_valid_c(self):
        path = _write_temp(".c", "int main(void) { return 0; }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "c"
        finally:
            os.unlink(path)

    def test_invalid_c(self):
        path = _write_temp(".c", "int main(void) { return }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
            assert "errors" in result
        finally:
            os.unlink(path)

    def test_valid_cpp(self):
        path = _write_temp(
            ".cpp", "#include <vector>\nint main() { std::vector<int> v; return 0; }\n"
        )
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "c++"
        finally:
            os.unlink(path)

    def test_invalid_cpp(self):
        path = _write_temp(".cpp", "int main() { return 0 }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
        finally:
            os.unlink(path)

    def test_hpp_routes_to_cpp(self):
        """惯例：.hpp 归 C++"""
        path = _write_temp(".hpp", "#pragma once\ntemplate<typename T> struct S {};\n")
        try:
            result = _check_or_skip(path)
            assert result["language"] == "c++"
        finally:
            os.unlink(path)


class TestSyntaxCheckJava:

    def test_java_checked_or_skipped(self):
        path = _write_temp(".java", "class Foo { }\n")
        try:
            result = _check_or_skip(path)
            # -XDshould-stop.at=PARSE 规避 public 类名与临时文件名不匹配的误报
            assert result["ok"] is True
            assert result["language"] == "java"
        finally:
            os.unlink(path)

    def test_invalid_java(self):
        path = _write_temp(".java", "class { }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
        finally:
            os.unlink(path)


class TestSyntaxCheckConfigFormats:

    def test_valid_json(self):
        path = _write_temp(".json", '{"a": 1}\n')
        try:
            result = check(path)
            assert result["ok"] is True
            assert result["language"] == "json"
        finally:
            os.unlink(path)

    def test_invalid_json_has_line_col(self):
        path = _write_temp(".json", '{"a": }\n')
        try:
            result = check(path)
            assert result["ok"] is False
            err = result["errors"][0]
            assert err["line"] == 1
            assert err["col"] > 0
        finally:
            os.unlink(path)

    def test_valid_toml(self):
        path = _write_temp(".toml", '[pkg]\nname = "x"\n')
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "toml"
        finally:
            os.unlink(path)

    def test_invalid_toml(self):
        path = _write_temp(".toml", "[pkg\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
            assert "errors" in result
        finally:
            os.unlink(path)

    def test_valid_yaml(self):
        path = _write_temp(".yaml", "a: 1\nb:\n  - x\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "yaml"
        finally:
            os.unlink(path)

    def test_invalid_yaml(self):
        path = _write_temp(".yml", "a: [1, 2\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
        finally:
            os.unlink(path)


class TestSyntaxCheckPhpPwshShell:

    def test_php_checked_or_skipped(self):
        path = _write_temp(".php", "<?php echo 1; ?>\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "php"
        finally:
            os.unlink(path)

    def test_valid_pwsh(self):
        path = _write_temp(".ps1", "Get-Process | Select-Object -First 1\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "powershell"
        finally:
            os.unlink(path)

    def test_invalid_pwsh(self):
        path = _write_temp(".ps1", "if ($x { }\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
            assert "errors" in result
        finally:
            os.unlink(path)

    def test_shell_checked_or_skipped(self):
        """bash 存在但不可用（WSL 启动器损坏）时应 skipped 而非误报语法错误"""
        path = _write_temp(".sh", "echo hi\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is True
            assert result["language"] == "shell"
        finally:
            os.unlink(path)

    def test_invalid_shell(self):
        path = _write_temp(".sh", "if then\n")
        try:
            result = _check_or_skip(path)
            assert result["ok"] is False
        finally:
            os.unlink(path)
