"""
rg_search — 文件内容级代码搜索引擎。
优先使用 ripgrep (rg)，未安装时回退到 Python 纯标准库扫描。
"""

import os
import re
import subprocess
import shutil
from pathlib import Path

from ._helpers import proposal_reply

# 扫描时跳过的目录名
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".eggs", "build", "dist", "target",
}

# Python fallback 扫描文件上限（防止超时）
_MAX_FILES_SCANNED = 5000

# ReDoS 防护
_MAX_PATTERN_LEN = 1000
_MAX_TOTAL_SEARCH_STEPS = 500_000


def _has_nested_quantifiers(pattern: str) -> bool:
    """检测常见灾难性回溯模式，如 (a+)+、(a*)*、(a?)+ 等。"""
    # 直接匹配 (X+)+、(X*)*、(X?)+ 及等价变体
    stack = []
    for ch in pattern:
        if ch == '(':
            stack.append([])
        elif ch == ')':
            if not stack:
                continue
            inner = stack.pop()
            if not inner:
                continue
            # 内部是否包含量词
            has_inner_quant = any(q in inner for q in '+*?')
            # 括号后紧跟的量词
            # 这里通过后续字符判断，需要向前看：暂存在解析循环外处理
        elif stack:
            stack[-1].append(ch)

    # 更简单可靠：用正则检测 ( [^()]* [+*?] [^()]* ) [+*?]
    return bool(re.search(r'\([^()]*[+\*?][^()]*\)[+\*?]', pattern))


def _find_rg() -> str | None:
    """查找 rg 可执行文件路径，未找到返回 None。"""
    return shutil.which("rg")


_RG_LINE_RE = re.compile(r"^(.*?):(\d+):(.*)$")


def _parse_rg_output(stdout: str) -> list[dict]:
    """解析 rg --line-number --no-heading 输出 file:line:content"""
    matches = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        m = _RG_LINE_RE.match(line)
        if not m:
            continue
        try:
            lineno = int(m.group(2))
        except ValueError:
            continue
        matches.append({"file": m.group(1), "line": lineno, "content": m.group(3)})
    return matches


_RG_CTX_RE = re.compile(r"^(.*?)([-:])(\d+)([-:])(.*)$")


def _parse_rg_with_context(stdout: str) -> list[dict]:
    """解析 rg -C N 输出，将匹配行和上下文行分组为 match 对象。
    匹配行: file:line:content（冒号分隔）
    上下文行: file-line-content（横线分隔）
    """
    matches = []
    current = None
    for line in stdout.split("\n"):
        if not line or line.strip() == "--":
            if current:
                matches.append(current)
                current = None
            continue
        m = _RG_CTX_RE.match(line)
        if not m:
            continue
        file = m.group(1)
        sep1 = m.group(2)  # : for match, - for context
        lineno = m.group(3)
        sep2 = m.group(4)  # : for match, - for context
        text = m.group(5)
        if sep1 == ":" and sep2 == ":":
            # This is a match line: file:line:content
            if current:
                matches.append(current)
            current = {"file": file, "line": int(lineno), "content": text, "context": []}
        elif current is not None:
            # Context line: append to current match
            current["context"].append({"line": int(lineno), "content": text})
    if current:
        matches.append(current)
    return matches


def _python_fallback(
    pattern: str,
    search_path: str,
    file_exts: list[str],
    max_results: int,
    case_sensitive: bool,
    whole_word: bool,
    list_files: bool,
) -> dict:
    """Python 纯标准库内容搜索 fallback。"""
    # ReDoS 前置拦截
    if len(pattern) > _MAX_PATTERN_LEN:
        return proposal_reply(
            False,
            f"pattern 长度超过 {_MAX_PATTERN_LEN}，请缩短搜索模式",
            error="pattern_too_long",
            evidence={"length": len(pattern), "max": _MAX_PATTERN_LEN},
            options=["缩短 pattern", "使用更精确的关键字"],
        )
    if _has_nested_quantifiers(pattern):
        return proposal_reply(
            False,
            "pattern 包含嵌套量词（如 (a+)+），可能引发灾难性回溯，请简化",
            error="nested_quantifiers",
            evidence={"pattern": pattern},
            options=["移除嵌套量词", "使用字面量搜索"],
        )

    flags = 0 if case_sensitive else re.IGNORECASE
    if whole_word:
        pattern = rf"\b{re.escape(pattern)}\b"
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return {"ok": False, "error": f"正则表达式无效: {e}"}

    matches = []
    files_searched = 0
    truncated = False
    search_steps = 0

    for root, dirs, files in os.walk(search_path):
        # 跳过隐藏/非代码目录
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]

        for fname in files:
            if files_searched >= _MAX_FILES_SCANNED:
                truncated = True
                break

            # 扩展名过滤
            if file_exts:
                ext = os.path.splitext(fname)[1].lstrip(".")
                if ext not in file_exts:
                    continue

            files_searched += 1
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        search_steps += 1
                        if search_steps > _MAX_TOTAL_SEARCH_STEPS:
                            truncated = True
                            break
                        if compiled.search(line):
                            matches.append({
                                "file": fpath,
                                "line": lineno,
                                "content": line.strip()[:200],
                            })
                            if list_files:
                                unique_files = len(set(m["file"] for m in matches))
                                if unique_files >= max_results:
                                    truncated = True
                                    break
                            elif len(matches) >= max_results:
                                truncated = True
                                break
            except (OSError, PermissionError):
                continue

            if truncated:
                break
        if truncated:
            break

    if list_files:
        seen = set()
        unique = []
        for m in matches:
            if m["file"] not in seen:
                seen.add(m["file"])
                unique.append(m)
        matches = [{"file": m["file"]} for m in unique]

    result = {
        "ok": True,
        "engine": "python",
        "count": len(matches),
        "matches": matches,
        "truncated": truncated,
        "files_searched": files_searched,
        "search_steps": search_steps,
        "note": "rg 未安装，使用 Python 扫描（较慢）。建议: winget install BurntSushi.ripgrep.MSVC 或 apt install ripgrep",
    }
    return result


def search(
    pattern: str,
    path: str = ".",
    file_exts: str = "",
    max_results: int = 40,
    case_sensitive: bool = False,
    whole_word: bool = False,
    list_files: bool = False,
    context_lines: int = 0,
) -> dict:
    """
    文件内容搜索。优先 ripgrep，未安装时 Python fallback。

    Args:
        pattern: 正则表达式或字面量搜索文本
        path: 搜索起始目录，默认当前目录
        file_exts: 逗号分隔的扩展名，如 "py,js,ts"（无点号）
        max_results: 最大结果数，默认 40
        case_sensitive: 区分大小写
        whole_word: 全词匹配
        list_files: True 时只返回匹配的文件名列表，不展示匹配行
        context_lines: 匹配行周围展示的上下文行数，默认 0（rg -C N）

    Returns:
        {"ok": true, "engine": "rg"|"python", "count": N, "matches": [...], ...}
    """
    search_path = os.path.abspath(path)
    if not os.path.isdir(search_path):
        return {"ok": False, "error": f"目录不存在: {search_path}"}

    exts = [e.strip().lstrip(".") for e in file_exts.split(",") if e.strip()]

    # ── Layer 1: ripgrep ──
    rg_path = _find_rg()
    if rg_path:
        try:
            args = [rg_path, "--line-number", "--no-heading", "--color", "never"]

            if not case_sensitive:
                args.append("--ignore-case")
            if whole_word:
                args.append("--word-regexp")
            if list_files:
                args.append("--files-with-matches")

            for ext in exts:
                args.extend(["-g", f"*.{ext}"])

            if context_lines > 0 and not list_files:
                args.extend(["-C", str(context_lines)])

            args.extend(["--", pattern, search_path])

            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )

            if proc.returncode not in (0, 1):
                return {
                    "ok": False,
                    "error": proc.stderr.strip() or f"rg 返回码 {proc.returncode}",
                }

            stdout = proc.stdout.strip()
            if list_files:
                files = [f.strip() for f in stdout.split("\n") if f.strip()]
                return {
                    "ok": True,
                    "engine": "rg",
                    "count": len(files),
                    "matches": [{"file": f} for f in files[:max_results]],
                    "truncated": len(files) > max_results,
                    "files_searched": len(files),
                }

            if context_lines > 0:
                all_matches = _parse_rg_with_context(stdout)
            else:
                all_matches = _parse_rg_output(stdout)
            truncated = len(all_matches) > max_results
            return {
                "ok": True,
                "engine": "rg",
                "count": min(len(all_matches), max_results),
                "matches": all_matches[:max_results],
                "truncated": truncated,
                "files_searched": len(set(m["file"] for m in all_matches)),
            }

        except subprocess.TimeoutExpired:
            return proposal_reply(
                False,
                "rg 搜索超时 (30s)——尝试缩小搜索范围或指定 file_exts",
                error="rg 搜索超时（30s）",
                evidence={"pattern": pattern, "path": search_path},
                options=["缩小 path 范围", "指定 file_exts 过滤", "回退到 Python 扫描"],
            )
        except FileNotFoundError:
            # rg not installed — fallback to Python
            pass
        except Exception as e:
            return {"ok": False, "error": f"rg 执行失败: {e}"}

    # ── Layer 2 & 3: Python fallback ──
    return _python_fallback(
        pattern, search_path, exts, max_results,
        case_sensitive, whole_word, list_files,
    )
