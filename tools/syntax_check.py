"""
syntax_check — 语法检查工具。
改完代码后验证语法正确性。
支持 Python / Nim / Go / JS / TS / Rust / Java / C / C++ / JSON / TOML / YAML / PHP / PowerShell / Shell。
"""

import subprocess
import ast
import json
import shutil
import sys
import tempfile
import tokenize
from pathlib import Path

from ._helpers import proposal_reply
from ._file_utils import detect_encoding


def check(filepath: str) -> dict:
    """
    检查文件语法。

    Returns:
        {"ok": true, "language": "python"} 或 {"ok": false, "errors": [...], "language": "..."}
    """
    p = Path(filepath)
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}", "language": "unknown"}

    suffix = p.suffix.lower()
    handler = _HANDLERS.get(suffix)
    if handler is None:
        return {
            "ok": True,
            "language": f"text/{suffix}",
            "note": "无法语法检查此类型文件，仅确认文件存在",
        }
    return handler(p)


def _check_python(p: Path) -> dict:
    """Python 语法检查：先用 ast.parse（无副作用），失败则用 py_compile。"""
    try:
        with tokenize.open(p) as f:
            source = f.read()
    except (UnicodeDecodeError, SyntaxError):
        # tokenize.open 默认 UTF-8；若失败，尝试自动探测编码（兼容无 cookie 的 GBK 等）
        try:
            enc = detect_encoding(p)
            with p.open("r", encoding=enc, errors="replace", newline="") as f:
                source = f.read()
        except Exception as e:
            return {
                "ok": False,
                "language": "python",
                "error": f"无法读取或解码文件: {e}",
            }
    except Exception as e:
        return {
            "ok": False,
            "language": "python",
            "error": f"无法读取或解码文件: {e}",
        }

    try:
        ast.parse(source)
        return {"ok": True, "language": "python"}
    except SyntaxError as e:
        hint = ""
        msg = e.msg.lower() if e.msg else ""
        if "indent" in msg:
            hint = "缩进异常——检查 old 参数中的缩进是否与上下文一致。将缩进减少一级后重试 safe_edit。"
        elif "syntax" in msg or "invalid" in msg:
            hint = "语法错误——检查是否缺少冒号、括号未闭合、或关键字拼写错误。"
        elif "eof" in msg:
            hint = "文件末尾缺少闭合符号——检查是否有未闭合的引号、括号或三引号。"
        else:
            hint = f"第{e.lineno}行语法错误: {e.msg}"
        # 构建上下文：错误行前后各 2 行
        lines = source.split("\n")
        context = []
        start = max(0, e.lineno - 3)  # lineno 是 1-based
        end = min(len(lines), e.lineno + 2)
        for i in range(start, end):
            marker = "→" if i == e.lineno - 1 else " "
            context.append(f"{marker}{i + 1:>4}│ {lines[i].rstrip()[:120]}")
        errors = [
            {
                "line": e.lineno,
                "col": e.offset,
                "msg": e.msg,
                "text": e.text.strip() if e.text else "",
                "context": context,
            }
        ]
        return proposal_reply(
            False,
            hint,
            error=f"语法检查失败: {e.msg}",
            evidence={"line": e.lineno, "col": e.offset, "msg": e.msg},
            options=["修正后重试 safe_edit", "查看错误行上下文"],
            language="python",
            errors=errors,
        )
    except (TypeError, ValueError, UnicodeError):
        # ast.parse 可能因非语法问题失败（如编码/类型错误），回退到 py_compile
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", "--", str(p)],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return {"ok": True, "language": "python"}
        except subprocess.CalledProcessError as e:
            return _parse_py_compile_error(e.stderr, "python")
        except subprocess.TimeoutExpired:
            return {"ok": False, "language": "python", "error": "py_compile 超时 (10s)"}


def _check_nim(p: Path) -> dict:
    """Nim 语法检查：nim check。"""
    try:
        result = subprocess.run(
            ["nim", "check", "--verbosity:0", "--", str(p)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        stderr = result.stderr.strip()
        if result.returncode == 0 and not stderr:
            return {"ok": True, "language": "nim"}
        return {
            "ok": False,
            "language": "nim",
            "errors": [{"msg": stderr or result.stdout.strip()}],
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "language": "nim",
            "skipped": True,
            "error": "nim 未安装",
            "reason": "nim 编译器未安装，跳过语法检查。安装: winget install nim-lang.nim 或 scoop install nim",
        }
    except Exception as e:
        return {"ok": False, "language": "nim", "errors": [{"msg": str(e)}]}


def _check_go(p: Path) -> dict:
    """Go 语法检查：gofmt -e。"""
    try:
        result = subprocess.run(
            ["gofmt", "-e", str(p)], capture_output=True, text=True, timeout=15
        )
        stderr = result.stderr.strip()
        if result.returncode == 0 and not stderr:
            return {"ok": True, "language": "go"}
        return {"ok": False, "language": "go", "errors": [{"msg": stderr}]}
    except FileNotFoundError:
        return {
            "ok": False,
            "language": "go",
            "skipped": True,
            "error": "go 未安装",
            "reason": "go 未安装，跳过语法检查。安装: winget install GoLang.Go 或 scoop install go",
        }
    except Exception as e:
        return {"ok": False, "language": "go", "errors": [{"msg": str(e)}]}


def _check_node(p: Path) -> dict:
    """JS/TS 语法检查：node --check。"""
    try:
        result = subprocess.run(
            ["node", "--check", "--", str(p)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "language": "javascript/typescript"}
        return {
            "ok": False,
            "language": "javascript/typescript",
            "errors": [{"msg": result.stderr.strip()}],
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "language": "javascript/typescript",
            "skipped": True,
            "error": "node 未安装",
            "reason": "node 未安装，跳过语法检查。安装: winget install OpenJS.NodeJS 或 scoop install nodejs",
        }
    except Exception as e:
        return {
            "ok": False,
            "language": "javascript/typescript",
            "errors": [{"msg": str(e)}],
        }


def _skipped(language: str, reason: str) -> dict:
    return {
        "ok": False,
        "language": language,
        "skipped": True,
        "error": f"{language} 工具链不可用",
        "reason": reason,
    }


def _read_text(p: Path) -> str:
    """按探测编码读取文本（兼容 BOM / GBK），供 JSON/TOML/YAML/shell 使用。"""
    enc = detect_encoding(p)
    with p.open("r", encoding=enc, errors="replace", newline="") as f:
        return f.read()


def _check_rust(p: Path) -> dict:
    """Rust：rustfmt --emit stdout。不用 --check（它把格式差异也判失败），只取解析结果。"""
    try:
        result = subprocess.run(
            ["rustfmt", "--emit", "stdout", "--edition", "2021", "--", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            return {"ok": True, "language": "rust"}
        return {
            "ok": False,
            "language": "rust",
            "errors": [{"msg": result.stderr.strip()}],
        }
    except FileNotFoundError:
        return _skipped("rust", "rustfmt 未安装，跳过语法检查。安装: winget install Rustlang.Rustup 后 rustup component add rustfmt")
    except subprocess.TimeoutExpired:
        return {"ok": False, "language": "rust", "error": "rustfmt 超时 (20s)"}
    except Exception as e:
        return {"ok": False, "language": "rust", "errors": [{"msg": str(e)}]}


def _check_c_cpp(p: Path, lang: str) -> dict:
    """C/C++：gcc/clang -fsyntax-only，MSVC cl /Zs。只查语法不产物。"""
    if lang == "c":
        candidates = [
            ["gcc", "-fsyntax-only", "-x", "c"],
            ["clang", "-fsyntax-only", "-x", "c"],
            ["cl", "/Zs", "/nologo", "/TC"],
        ]
    else:
        candidates = [
            ["g++", "-fsyntax-only", "-x", "c++"],
            ["clang++", "-fsyntax-only", "-x", "c++"],
            ["cl", "/Zs", "/nologo", "/TP"],
        ]
    for cmd in candidates:
        exe = cmd[0]
        if not shutil.which(exe):
            continue
        # cl 不支持 GNU 风格终止符；实测 MinGW gcc 也不认 --，统一不加
        argv = [*cmd, str(p)]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0:
                return {"ok": True, "language": lang}
            # cl 诊断走 stdout，gcc/clang 走 stderr
            output = (result.stderr + "\n" + result.stdout).strip()
            return {"ok": False, "language": lang, "errors": [{"msg": output}]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "language": lang, "error": f"{exe} 超时 (20s)"}
        except Exception as e:
            return {"ok": False, "language": lang, "errors": [{"msg": str(e)}]}
    return _skipped(lang, "无可用 C/C++ 编译器（gcc/clang/cl），跳过语法检查")


def _check_java(p: Path) -> dict:
    """Java：javac 只解析。-XDshould-stop.at=PARSE 在 parse 后停止，规避语义误报
    （临时文件名与 public 类名不匹配、缺失依赖 import 都不会误伤）；
    不识该内部选项的老 JDK 回退常规编译。"""
    if not shutil.which("javac"):
        return _skipped("java", "javac 未安装，跳过语法检查。安装 JDK 后确保 javac 在 PATH")
    tmpdir = tempfile.mkdtemp(prefix="syntax_check_javac_")
    try:
        base = ["javac", "-proc:none", "-nowarn", "-d", tmpdir]
        result = subprocess.run(
            [*base, "-XDshould-stop.at=PARSE", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "invalid flag" in (result.stderr or ""):
            result = subprocess.run(
                [*base, str(p)], capture_output=True, text=True, timeout=30
            )
        if result.returncode == 0:
            return {"ok": True, "language": "java"}
        return {
            "ok": False,
            "language": "java",
            "errors": [{"msg": (result.stderr + "\n" + result.stdout).strip()}],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "language": "java", "error": "javac 超时 (30s)"}
    except Exception as e:
        return {"ok": False, "language": "java", "errors": [{"msg": str(e)}]}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _check_json(p: Path) -> dict:
    """JSON：标准库 json，JSONDecodeError 自带行列号。"""
    try:
        json.loads(_read_text(p))
        return {"ok": True, "language": "json"}
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "language": "json",
            "errors": [{"line": e.lineno, "col": e.colno, "msg": e.msg}],
        }
    except Exception as e:
        return {"ok": False, "language": "json", "errors": [{"msg": str(e)}]}


def _check_toml(p: Path) -> dict:
    """TOML：tomllib（Python 3.11+），3.10 回退第三方 tomli。"""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            return _skipped("toml", "tomllib 不可用（需 Python 3.11+）或 pip install tomli")
    try:
        tomllib.loads(_read_text(p))
        return {"ok": True, "language": "toml"}
    except Exception as e:
        return {"ok": False, "language": "toml", "errors": [{"msg": str(e)}]}


def _check_yaml(p: Path) -> dict:
    """YAML：PyYAML compose 只建节点树不构造对象，纯语法层校验。"""
    try:
        import yaml
    except ImportError:
        return _skipped("yaml", "PyYAML 未安装，跳过语法检查。安装: pip install pyyaml")
    try:
        yaml.compose(_read_text(p))
        return {"ok": True, "language": "yaml"}
    except yaml.YAMLError as e:
        err = {"msg": str(e)}
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            err["line"] = mark.line + 1
            err["col"] = mark.column + 1
        return {"ok": False, "language": "yaml", "errors": [err]}
    except Exception as e:
        return {"ok": False, "language": "yaml", "errors": [{"msg": str(e)}]}


def _check_php(p: Path) -> dict:
    """PHP：php -l lint 模式。"""
    try:
        result = subprocess.run(
            ["php", "-l", str(p)], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"ok": True, "language": "php"}
        return {
            "ok": False,
            "language": "php",
            "errors": [{"msg": (result.stdout + "\n" + result.stderr).strip()}],
        }
    except FileNotFoundError:
        return _skipped("php", "php 未安装，跳过语法检查。安装: winget install PHP.PHP 或 scoop install php")
    except subprocess.TimeoutExpired:
        return {"ok": False, "language": "php", "error": "php -l 超时 (10s)"}
    except Exception as e:
        return {"ok": False, "language": "php", "errors": [{"msg": str(e)}]}


def _check_pwsh(p: Path) -> dict:
    """PowerShell：Parser.ParseFile 纯解析不执行；优先 pwsh 7，回退 Windows PowerShell。"""
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        return _skipped("powershell", "pwsh/powershell 均不可用，跳过语法检查")
    escaped = str(p).replace("'", "''")
    script = (
        "$t=$null;$e=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$t,[ref]$e);"
        "if($e.Count -gt 0){$e|ForEach-Object{"
        "Write-Output ($_.Extent.StartLineNumber.ToString()+':'+$_.Extent.StartColumnNumber.ToString()+': '+$_.Message)};"
        "exit 1}"
    )
    try:
        result = subprocess.run(
            [exe, "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return {"ok": True, "language": "powershell"}
        output = (result.stdout + "\n" + result.stderr).strip()
        return {"ok": False, "language": "powershell", "errors": [{"msg": output}]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "language": "powershell", "error": "pwsh 解析超时 (15s)"}
    except Exception as e:
        return {"ok": False, "language": "powershell", "errors": [{"msg": str(e)}]}


# WSL 的 bash 启动器可能存在于 PATH 但后端损坏——存在不代表可用，自检结果按可执行路径缓存
_shell_usable: dict = {}


def _shell_selftest(exe: str) -> bool:
    try:
        result = subprocess.run(
            [exe, "-n"], input="true", capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_shell(p: Path) -> dict:
    """Shell：bash/sh -n 从 stdin 读脚本只解析不执行（stdin 方案规避 WSL 不认 Windows 路径的问题）。"""
    exe = shutil.which("bash") or shutil.which("sh")
    if not exe:
        return _skipped("shell", "bash/sh 均不可用，跳过语法检查（Git for Windows 自带 bash）")
    if exe not in _shell_usable:
        _shell_usable[exe] = _shell_selftest(exe)
    if not _shell_usable[exe]:
        return _skipped("shell", f"{exe} 存在但不可用（WSL 启动器异常），跳过语法检查")
    try:
        result = subprocess.run(
            [exe, "-n"],
            input=_read_text(p),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {"ok": True, "language": "shell"}
        output = (result.stderr + "\n" + result.stdout).strip()
        return {"ok": False, "language": "shell", "errors": [{"msg": output}]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "language": "shell", "error": "bash -n 超时 (10s)"}
    except Exception as e:
        return {"ok": False, "language": "shell", "errors": [{"msg": str(e)}]}


def _parse_py_compile_error(stderr: str, language: str) -> dict:
    """解析 py_compile 的标准错误输出。"""
    errors = []
    for line in stderr.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        errors.append({"msg": line})
    return {
        "ok": False,
        "language": language,
        "errors": errors if errors else [{"msg": stderr}],
    }


# 扩展名 → 检查器。惯例：.h 归 C，.hpp/.hh/.hxx 归 C++。
_HANDLERS = {
    ".py": _check_python,
    ".nim": _check_nim,
    ".go": _check_go,
    ".js": _check_node,
    ".ts": _check_node,
    ".jsx": _check_node,
    ".tsx": _check_node,
    ".rs": _check_rust,
    ".java": _check_java,
    ".c": lambda p: _check_c_cpp(p, "c"),
    ".h": lambda p: _check_c_cpp(p, "c"),
    ".cpp": lambda p: _check_c_cpp(p, "c++"),
    ".cc": lambda p: _check_c_cpp(p, "c++"),
    ".cxx": lambda p: _check_c_cpp(p, "c++"),
    ".hpp": lambda p: _check_c_cpp(p, "c++"),
    ".hh": lambda p: _check_c_cpp(p, "c++"),
    ".hxx": lambda p: _check_c_cpp(p, "c++"),
    ".json": _check_json,
    ".toml": _check_toml,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
    ".php": _check_php,
    ".ps1": _check_pwsh,
    ".psm1": _check_pwsh,
    ".psd1": _check_pwsh,
    ".sh": _check_shell,
    ".bash": _check_shell,
}
