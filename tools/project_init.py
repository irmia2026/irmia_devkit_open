"""
project_init — 项目结构扫描与上下文生成。
扫描项目根目录，detect 语言/框架/依赖，生成结构化 JSON 给 LLM。
"""

import json
import os
import re
from pathlib import Path

from ._helpers import _run_cmd
from ._file_utils import read_file


def scan(project_dir: str = ".") -> dict:
    """扫描项目目录，返回结构化上下文。

    Args:
        project_dir: 项目根目录路径，默认当前目录
    """
    root = Path(project_dir).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"不是有效目录: {project_dir}"}

    context = {
        "project_name": root.name,
        "language": "unknown",
        "entry": None,
        "directories": {},
        "dependencies": {"runtime": [], "dev": [], "optional": []},
        "test_framework": None,
        "git": {},
    }

    _detect_language(root, context)
    _scan_directories(root, context)
    _read_package_files(root, context)
    _git_info(root, context)

    return {"ok": True, "context": context}


# 语言探测遍历时剪枝的目录
_PRUNE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}


def _detect_language(root: Path, ctx: dict):
    detectors = [
        (".py", "python"),
        (".js", "javascript"),
        (".ts", "typescript"),
        (".go", "go"),
        (".nim", "nim"),
        (".rs", "rust"),
        (".java", "java"),
        (".rb", "ruby"),
        (".php", "php"),
    ]
    scored = {}
    count = 0
    stop = False
    for _dirpath, dirnames, filenames in os.walk(root):
        # 原地修改 dirnames 实现目录剪枝
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        for name in filenames:
            count += 1
            if count > 2000:
                stop = True
                break
            suffix = Path(name).suffix.lower()
            for ext, lang in detectors:
                if suffix == ext:
                    scored[lang] = scored.get(lang, 0) + 1
                    break
        if stop:
            break
    if scored:
        ctx["language"] = max(scored, key=scored.get)  # type: ignore


def _scan_directories(root: Path, ctx: dict):
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.name.startswith((".", "__")):
            if entry.name in (
                "src",
                "lib",
                "app",
                "tools",
                "utils",
                "modules",
                "handlers",
            ):
                ctx["directories"][entry.name] = "source"
            elif entry.name in ("tests", "test", "spec", "__tests__"):
                ctx["directories"][entry.name] = "test"
            elif entry.name in ("docs", "doc"):
                ctx["directories"][entry.name] = "doc"
            elif entry.name in ("scripts", "bin", "ci"):
                ctx["directories"][entry.name] = "script"
            else:
                ctx["directories"][entry.name] = "other"

    # detect entry point
    for candidate in (
        "main.py",
        "index.js",
        "index.ts",
        "app.py",
        "main.go",
        "src/main.rs",
    ):
        if (root / candidate).exists():
            ctx["entry"] = candidate
            break


def _read_package_files(root: Path, ctx: dict):
    # Python
    req = root / "requirements.txt"
    if req.exists():
        ctx["dependencies"]["runtime"] = [l.strip() for l in read_file(req).splitlines() if l.strip() and not l.startswith("#")]

    # Node
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(read_file(pkg))
            ctx["dependencies"]["runtime"] = list(data.get("dependencies", {}).keys())
            ctx["dependencies"]["dev"] = list(data.get("devDependencies", {}).keys())
        except (json.JSONDecodeError, OSError):
            pass

    # Python pyproject.toml
    ppt = root / "pyproject.toml"
    if ppt.exists():
        text = read_file(ppt)
        # extract dependencies from [project] section
        dep_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if dep_match:
            deps = [
                d.strip().strip('"').strip("'")
                for d in dep_match.group(1).split(",")
                if d.strip()
            ]
            if deps:
                ctx["dependencies"]["runtime"] = deps

    # Test framework detection
    for tf in ("pytest", "unittest", "jest", "mocha", "go test"):
        if any(tf in str(d).lower() for d in ctx["dependencies"].get("dev", [])):
            ctx["test_framework"] = tf
            break
        if tf == "pytest" and (root / "conftest.py").exists():
            ctx["test_framework"] = "pytest"
            break


def _git_info(root: Path, ctx: dict):
    try:
        r = _run_cmd(["git", "branch", "--show-current"], cwd=str(root), timeout=5)
        if r["ok"]:
            ctx["git"]["branch"] = r["stdout"]
        r2 = _run_cmd(["git", "log", "-1", "--format=%h %s"], cwd=str(root), timeout=5)
        if r2["ok"]:
            ctx["git"]["last_commit"] = r2["stdout"]
        r3 = _run_cmd(["git", "tag", "--sort=-creatordate"], cwd=str(root), timeout=5)
        if r3["ok"] and r3["stdout"]:
            ctx["git"]["recent_tags"] = r3["stdout"].split("\n")[:5]
    except Exception:
        pass
