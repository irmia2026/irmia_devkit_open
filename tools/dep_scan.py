"""
dep_scan — 依赖分析。
扫描 Python import，构建依赖图，检测循环引用。含超时保护。
"""

import ast
import time
from pathlib import Path

from ._file_utils import read_file_with_encoding

# 扫描时排除的目录（按路径 parts 判断）
_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".tox", "dist", "build", ".mypy_cache", ".pytest_cache",
}


def _module_name(root: Path, f: Path) -> str | None:
    """把项目内 .py 文件映射为模块名（相对路径去 .py、os.sep 转 "."）。"""
    try:
        rel = f.relative_to(root)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if not parts:
        return None
    if parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return None
    return ".".join(parts)


def scan(project_dir: str = ".", timeout: int = 10) -> dict:
    """扫描 Python 项目 import 依赖图，检测循环引用。

    Args:
        project_dir: 项目根目录
        timeout: 超时秒数，默认 10
    """
    root = Path(project_dir).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"不是有效目录: {project_dir}"}

    dep_graph: dict[str, set[str]] = {}
    deadline = time.time() + timeout

    # 第一遍：收集项目内模块名集合
    module_of: dict[Path, str] = {}
    for f in root.rglob("*.py"):
        if _EXCLUDE_DIRS & set(f.parts):
            continue
        mod = _module_name(root, f)
        if mod:
            module_of[f] = mod
    module_names = set(module_of.values())
    top_level_names = {m.split(".")[0] for m in module_names}

    # 第二遍：提取 import，只保留落在项目内模块集合中的依赖
    scanned = 0
    timed_out = False
    for f, mod in module_of.items():
        scanned += 1
        if time.time() > deadline:
            timed_out = True
            scanned -= 1  # 超时文件未扫描，不计入
            break
        try:
            deps = _extract_imports(f)
            deps = {d for d in deps if d in top_level_names or d in module_names}
            if deps:
                dep_graph[mod] = deps
        except Exception:
            scanned -= 1  # 不计入成功扫描

    if timed_out:
        cycles = _find_cycles(dep_graph)
        return {
            "ok": True,
            "root": str(root),
            "files_scanned": len(dep_graph),
            "dependencies": {k: sorted(v) for k, v in dep_graph.items()},
            "cycles": cycles,
            "has_cycles": len(cycles) > 0,
            "partial": True,
            "note": f"超时 ({timeout}s)，已扫描 {len(dep_graph)}/{scanned} 文件",
            "proposal": f"依赖扫描部分完成——超时({timeout}s)仅扫描{len(dep_graph)}/{scanned}文件",
            "options": [
                "接受部分结果",
                "增加 timeout 参数",
                "缩小 project_dir 范围",
            ],
        }

    cycles = _find_cycles(dep_graph)

    result = {
        "ok": True,
        "root": str(root),
        "files_scanned": len(dep_graph),
        "dependencies": {k: sorted(v) for k, v in dep_graph.items()},
        "cycles": cycles,
        "has_cycles": len(cycles) > 0,
    }
    if cycles:
        first = cycles[0]
        result["proposal"] = (
            f"发现{len(cycles)}个循环引用：{'→'.join(first)}。建议提取共同逻辑到新文件或合并模块。"
        )
        result["options"] = [
            "提取共同依赖到新文件",
            "合并相关模块",
            "忽略(有时循环引用可接受)",
        ]
    elif not dep_graph:
        result["proposal"] = "未扫描到 Python 文件——确认项目目录正确。"
        result["options"] = ["确认 project_dir", "用 dir_list 验证目录内容"]
    return result


def _extract_imports(filepath: Path) -> set[str]:
    imports = set()
    try:
        source, _ = read_file_with_encoding(filepath)
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles = []
    visited = set()
    stack = []

    def dfs(node: str):
        if node in stack:
            idx = stack.index(node)
            cycles.append(stack[idx:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.append(node)
        for neighbor in graph.get(node, set()):
            dfs(neighbor)
        stack.pop()

    for node in graph:
        stack.clear()
        dfs(node)

    seen = set()
    unique = []
    for c in cycles:
        key = tuple(sorted(c))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique
