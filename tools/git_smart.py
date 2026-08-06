"""
git_smart — Git 操作封装。
常用 git 命令的结构化输出。不要用 shell 直接执行 git 命令——用此工具。
"""

import os
import re

from ._helpers import proposal_reply, _run_cmd

# 解析 git diff --stat 最后一行: "1 file changed, 5 insertions(+), 2 deletions(-)"
_RE_STAT = re.compile(r"(\d+)\s+files?\s+changed(?:,\s+(\d+)\s+insertions?\(\+\))?(?:,\s+(\d+)\s+deletions?\(\-\))?")


def _run_git(cwd: str, args: list[str], timeout: int = 15) -> dict:
    git_env = os.environ | {"LC_ALL": "C"}
    return _run_cmd(["git"] + args, cwd=cwd, timeout=timeout, env=git_env)


def status(cwd: str) -> dict:
    """查看仓库状态。改代码前必调，确认工作区干净。"""
    r = _run_git(cwd, ["status", "--porcelain"])
    if not r["ok"]:
        return r
    lines = r["stdout"].split("\n") if r["stdout"] else []
    clean = len(lines) == 0 or all(l == "" for l in lines)
    changes = [line for line in lines if line.strip()]
    result = {
        "ok": True,
        "clean": clean,
        "changes": changes[:200],
        "changed_count": len(changes),
    }
    if len(changes) > 200:
        result["changes_truncated"] = True
        result["changes_total"] = len(changes)
    return result


def diff(cwd: str, staged: bool = False, filepath: str = None, max_lines: int = 500) -> dict:
    """查看差异。提交前必调用 --staged。返回结构化统计 + raw diff。
    diff 超过 max_lines 行时截断并附 diff_truncated/diff_total_lines。"""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if filepath:
        args.append("--")
        args.append(filepath)
    r = _run_git(cwd, args)
    if not r["ok"]:
        return r
    # 额外跑 git diff --stat 获取结构化统计
    stat_args = ["diff", "--stat"]
    if staged:
        stat_args.append("--staged")
    if filepath:
        stat_args.extend(["--", filepath])
    stat = _run_git(cwd, stat_args)
    result = {"ok": True, "diff": r["stdout"], "stderr": r["stderr"]}
    diff_lines = r["stdout"].split("\n") if r["stdout"] else []
    if max_lines > 0 and len(diff_lines) > max_lines:
        result["diff"] = "\n".join(diff_lines[:max_lines])
        result["diff_truncated"] = True
        result["diff_total_lines"] = len(diff_lines)
    # 解析 --stat 最后一行: "1 file changed, 5 insertions(+), 2 deletions(-)"
    if stat["ok"] and stat["stdout"]:
        lines = stat["stdout"].strip().split("\n")
        if lines:
            last = lines[-1]
            files_match = _RE_STAT.search(last)
            if files_match:
                result["files_changed"] = int(files_match.group(1))
                try:
                    insertions = int(files_match.group(2)) if files_match.group(2) else 0
                except (ValueError, IndexError):
                    insertions = 0
                try:
                    deletions = int(files_match.group(3)) if files_match.group(3) else 0
                except (ValueError, IndexError):
                    deletions = 0
                result["added"] = insertions
                result["removed"] = deletions
                result["total_changes"] = insertions + deletions
    return result


def log(cwd: str, count: int = 5) -> dict:
    """查看最近提交记录。上限 30 条。"""
    if not isinstance(count, int) or count < 1:
        return {"ok": False, "error": "count 必须为正整数"}
    count = min(count, 30)
    r = _run_git(cwd, ["log", f"-{count}", "--oneline", "--decorate"])
    if not r["ok"]:
        return r
    return {"ok": True, "commits": r["stdout"].split("\n") if r["stdout"] else []}


def commit(cwd: str, message: str, files: list = None, force: bool = False) -> dict:
    """提交更改。默认提交全部；files 指定时仅提交这些文件（仓库内相对路径）。
    force=True 时跳过 >10 文件拦截。提交前必调 diff --staged 自查。"""
    s = status(cwd)
    if not s.get("ok"):
        return {"ok": False, "error": f"无法获取状态: {s.get('error', '未知')}"}
    if s.get("clean"):
        return {"ok": False, "error": "没有可提交的更改"}

    message = message.strip()
    if not message:
        return {"ok": False, "error": "提交消息不能为空"}

    # 校验指定文件：仅允许仓库内相对路径，拒绝绝对路径和 .. 逃逸
    staged_files = []
    if files:
        for f in files:
            f = str(f).strip().replace("\\", "/")
            if not f:
                continue
            if f.startswith("/") or re.match(r"^[A-Za-z]:", f):
                return {"ok": False, "error": f"非法文件路径（绝对路径）: {f}"}
            parts = [p for p in f.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                return {"ok": False, "error": f"非法文件路径（越出仓库）: {f}"}
            staged_files.append("/".join(parts))

    changed = len(staged_files) if staged_files else s.get("changed_count", 0)
    if changed > 10 and not force:
        groups = {"Code": [], "Config": [], "Other": []}
        if staged_files:
            names = list(staged_files)
        else:
            names = []
            for f_line in s.get("changes", []):
                # 解析 git status --porcelain 行：前两位是状态码，第3位起是文件名
                f_name = f_line[3:] if len(f_line) > 3 and f_line[2] == ' ' else f_line.strip()
                names.append(f_name.strip())
        for f_name in names:
            if f_name.endswith((".py", ".nim", ".go")):
                groups["Code"].append(f_name)
            elif f_name.endswith((".json", ".yaml", ".yml", ".toml", ".cfg", ".ini")):
                groups["Config"].append(f_name)
            else:
                groups["Other"].append(f_name)
        options = [
            {"tool": "git_commit", "params": {"cwd": cwd, "message": message, "force": True}},
        ]
        if groups["Code"]:
            options.append({
                "tool": "git_commit",
                "params": {"cwd": cwd, "message": message, "files": groups["Code"]},
            })
        return proposal_reply(
            False,
            f"{changed}个文件待提交——Code:{len(groups['Code'])} Config:{len(groups['Config'])} Other:{len(groups['Other'])}。建议分批。",
            error=f"文件过多 ({changed})——建议分批提交",
            evidence={"file_groups": {k: v for k, v in groups.items() if v}},
            options=options,
            reason="too_many_files",
        )

    files_to_stage = staged_files if staged_files else s.get("changes", [])

    if staged_files:
        r1 = _run_git(cwd, ["add", "--"] + staged_files)
    else:
        r1 = _run_git(cwd, ["add", "-A"])
    if not r1["ok"]:
        return {"ok": False, "error": f"git add 失败: {r1.get('stderr', r1.get('error', ''))}"}

    r2 = _run_git(cwd, ["commit", "-m", message], timeout=30)
    if not r2["ok"]:
        return {"ok": False, "error": f"git commit 失败: {r2.get('stderr', r2.get('error', ''))}"}

    # 获取 commit hash
    rh = _run_git(cwd, ["log", "-1", "--format=%H"])
    commit_hash = rh["stdout"] if rh["ok"] else ""

    return {
        "ok": True,
        "hash": commit_hash,
        "message": message,
        "output": r2["stdout"],
        "files_committed": changed,
        "files_staged": files_to_stage,
    }


def current_branch(cwd: str) -> dict:
    """获取当前分支名。"""
    r = _run_git(cwd, ["branch", "--show-current"])
    if not r["ok"]:
        return r
    return {"ok": True, "branch": r["stdout"]}


def remote_url(cwd: str) -> dict:
    """获取远程仓库 URL。"""
    r = _run_git(cwd, ["remote", "get-url", "origin"])
    if not r["ok"]:
        return r
    return {"ok": True, "url": r["stdout"]}


def push(cwd: str, remote: str = "origin", branch: str = "") -> dict:
    """推送到远程仓库。推送前请先用 git_status + git_diff 自查。"""
    if not branch:
        b = current_branch(cwd)
        if not b.get("ok"):
            return {"ok": False, "error": f"无法获取当前分支: {b.get('error')}"}
        branch = b["branch"]

    # 检查是否有未推送的 commit（预检失败如远程跟踪分支不存在时跳过，由后续 push 自己报错）
    r_check = _run_git(cwd, ["log", f"{remote}/{branch}..HEAD", "--oneline"])
    if r_check["ok"]:
        if not r_check["stdout"].strip():
            return {"ok": False, "error": "没有未推送的提交——所有 commit 已在远程"}

    args = ["push", remote, branch]
    return _run_git(cwd, args, timeout=30)
