"""
syntax_check — 语法检查工具。
改完代码后验证语法正确性。支持 Python / Nim / Go / 通用文本。
"""

import subprocess
import ast
import sys
from pathlib import Path

from ._helpers import proposal_reply


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

    if suffix == ".py":
        return _check_python(p)
    elif suffix == ".nim":
        return _check_nim(p)
    elif suffix == ".go":
        return _check_go(p)
    elif suffix in (".js", ".ts", ".jsx", ".tsx"):
        return _check_node(p)
    else:
        return {
            "ok": True,
            "language": f"text/{suffix}",
            "note": "无法语法检查此类型文件，仅确认文件存在",
        }


def _check_python(p: Path) -> dict:
    """Python 语法检查：先用 ast.parse（无副作用），失败则用 py_compile。"""
    try:
        source = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            source = p.read_text(encoding="gbk")
        except Exception:
            source = p.read_text(encoding="utf-8", errors="replace")

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
            context.append(f"{marker}{i + 1:>4}: {lines[i].rstrip()[:120]}")
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
