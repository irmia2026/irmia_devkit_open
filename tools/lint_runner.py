"""
lint_runner — 代码质量检查（ruff/pylint/eslint）。
与 syntax_check 互补：syntax_check 查"能不能跑"，lint_runner 查"写得好不好"。
"""

import subprocess
import sys
import json
import re as _re
import shutil
from pathlib import Path


def run(filepath: str, linter: str = "auto") -> dict:
    """对文件运行 linter，返回结构化 issues。
    当首选 linter 未安装时自动回退到备用 linter。
    参照 rg_search 的三层 fallback 模式。

    Args:
        filepath: 文件路径
        linter: auto(检测)/ruff/pylint/eslint
    """
    p = Path(filepath)
    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    if linter == "auto":
        linter = _detect(p)

    runners = {
        "ruff": _run_ruff,
        "pylint": _run_pylint,
        "eslint": _run_eslint,
    }
    runner = runners.get(linter)
    if not runner:
        return {
            "ok": False,
            "error": f"不支持的 linter: {linter}，可选: {list(runners.keys())}",
        }

    result = runner(p)
    if isinstance(result, dict) and "fallback" in result:
        fallback = runners.get(result["fallback"])
        if fallback:
            result = fallback(p)
    if result.get("ok") and result.get("issues"):
        _add_context(p, result["issues"])
    return result


def _detect(p: Path) -> str:
    suffix = p.suffix.lower()
    if suffix in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
        return "eslint"
    if shutil.which("ruff"):
        return "ruff"
    if shutil.which("pylint"):
        return "pylint"
    return "ruff"


def _get_line_context(p: Path, line_num: int, context_size: int = 2) -> list[str] | None:
    """读取文件，返回指定行附近 context_size 行的上下文。"""
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
    except Exception:
        return None
    start = max(0, line_num - context_size - 1)
    end = min(len(lines), line_num + context_size)
    ctx = []
    for i in range(start, end):
        actual = i + 1
        marker = "→" if actual == line_num else " "
        ctx.append(f"{marker}{actual:>4}: {lines[i].rstrip()[:120]}")
    return ctx


def _add_context(p: Path, issues: list, max_issues: int = 5) -> None:
    """为前 max_issues 个问题附加代码上下文。"""
    for issue in issues[:max_issues]:
        line_num = issue.get("line")
        if not line_num:
            loc = issue.get("location")
            if isinstance(loc, dict):
                line_num = loc.get("row")
        if not line_num:
            # 尝试从 message 中提取 (line N) 模式（eslint 风格）
            m = _re.search(r"\(line (\d+)\)", issue.get("message", ""))
            if m:
                line_num = int(m.group(1))
        if line_num:
            ctx = _get_line_context(p, line_num)
            if ctx:
                issue["context"] = ctx


def _find_ruff() -> list:
    """查找 ruff 可执行路径：优先命令行，备 python -m ruff"""
    if shutil.which("ruff"):
        return ["ruff"]
    try:
        subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, timeout=5, check=True)
        return [sys.executable, "-m", "ruff"]
    except Exception:
        return []


def _run_ruff(p: Path) -> dict:
    ruff_cmd = _find_ruff()
    if not ruff_cmd:
        if shutil.which("pylint"):
            return {
                "ok": False,
                "error": "ruff 未安装，自动回退到 pylint",
                "fallback": "pylint",
            }
        return {"ok": False, "error": "ruff 和 pylint 均未安装，请运行: pip install ruff 或 pip install pylint"}
    try:
        r = subprocess.run(
            ruff_cmd + ["check", "--output-format", "json", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return {"ok": True, "linter": "ruff", "issues": [], "count": 0}
        issues = json.loads(r.stdout) if r.stdout.strip() else []
        result = {"ok": True, "linter": "ruff", "issues": issues, "count": len(issues)}
        if issues:
            result["proposal"] = f"ruff发现{len(issues)}个问题"
            result["options"] = ["逐个修复", "确认是否有意为之"]
        return result
    except json.JSONDecodeError:
        return {
            "ok": True,
            "linter": "ruff",
            "raw": r.stdout.strip()[:2000],
            "count": 0,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ruff 超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_pylint(p: Path) -> dict:
    if not shutil.which("pylint"):
        if shutil.which("ruff"):
            return {
                "ok": False,
                "error": "pylint 未安装，自动回退到 ruff",
                "fallback": "ruff",
            }
        return {"ok": False, "error": "pylint 和 ruff 均未安装，请运行: pip install ruff 或 pip install pylint"}
    try:
        r = subprocess.run(
            ["pylint", "--output-format", "json", str(p)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        issues = json.loads(r.stdout) if r.stdout.strip() else []
        r = {"ok": True, "linter": "pylint", "issues": issues, "count": len(issues)}
        if issues:
            r["proposal"] = f"pylint发现{len(issues)}个问题"
            r["options"] = ["逐个修复", "确认是否有意为之"]
        return r
    except json.JSONDecodeError:
        return {
            "ok": True,
            "linter": "pylint",
            "raw": r.stdout.strip()[:2000],
            "count": 0,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pylint 超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run_eslint(p: Path) -> dict:
    if not shutil.which("eslint"):
        return {"ok": False, "error": "eslint 未安装，请运行: npm install -g eslint"}
    try:
        r = subprocess.run(
            ["eslint", "--format", "json", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = json.loads(r.stdout) if r.stdout.strip() else []
        if isinstance(result, list) and len(result) > 0:
            messages = result[0].get("messages", [])
            r = {
                "ok": True,
                "linter": "eslint",
                "issues": messages,
                "count": len(messages),
            }
            if messages:
                r["proposal"] = f"eslint发现{len(messages)}个问题"
                r["options"] = ["逐个修复", "确认是否有意为之"]
            return r
        return {"ok": True, "linter": "eslint", "issues": [], "count": 0}
    except json.JSONDecodeError:
        return {
            "ok": True,
            "linter": "eslint",
            "raw": r.stdout.strip()[:2000],
            "count": 0,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "eslint 超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
