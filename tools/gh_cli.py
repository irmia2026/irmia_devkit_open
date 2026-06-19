"""
gh_cli — GitHub CLI 封装。
通过 gh 命令直接操作 GitHub，无需浏览器。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from .config import get_config
from ._helpers import _run_cmd


def _find_gh() -> str:
    """查找 gh CLI 路径。先读配置，再自动搜索 PATH 和常见安装位置。"""
    config = get_config()
    custom = config.get("gh_path", "")
    if custom and os.path.exists(custom):
        return custom
    path = shutil.which("gh")
    if path:
        return path
    # Windows 常见安装位置
    for guess in [
        r"C:\Program Files\GitHub CLI\gh.exe",
        r"C:\Program Files (x86)\GitHub CLI\gh.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe"),
    ]:
        if os.path.exists(guess):
            return guess
    return "gh"


def _run_gh(args: list[str], cwd: str = None, timeout: int = 20) -> dict:
    if not cwd:
        cwd = os.getcwd()
    gh_bin = _find_gh()
    result = _run_cmd([gh_bin] + args, cwd=cwd, timeout=timeout)
    if not result["ok"] and gh_bin not in result.get("error", ""):
        if gh_bin != "gh":
            result["error"] = f"gh 未找到: {gh_bin}"
    if not result["ok"] and gh_bin == "gh":
        import sys
        if sys.platform == "win32":
            install_hint = "安装 GitHub CLI: winget install GitHub.cli"
        elif sys.platform == "darwin":
            install_hint = "安装 GitHub CLI: brew install gh"
        else:
            install_hint = "安装 GitHub CLI: apt install gh 或 dnf install gh"
        result["error"] = (
            f"{result.get('error', 'gh 未找到')}。"
            f"如已安装 gh CLI，用 rg_search('gh') 找到路径后填入 config.json 的 gh_path；"
            f"或 {install_hint}"
        )
    return result


def _with_body_file(
    body: str, args: list[str], flag: str = "--body-file"
) -> str | None:
    """如果 body 非空，写入临时文件并追加 flag + 路径到 args，返回文件路径用于后续清理。"""
    if not body:
        return None
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    try:
        f.write(body)
        f.close()
    except Exception:
        f.close()
        try:
            os.unlink(f.name)
        except OSError:
            pass
        raise
    args.extend([flag, f.name])
    return f.name


def _cleanup(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def pr_create(
    cwd: str, title: str, body: str = "", base: str = "master", head: str = ""
) -> dict:
    """创建 Pull Request。"""
    args = ["pr", "create", "--title", title, "--base", base]
    tmp = _with_body_file(body, args)
    if head:
        args.extend(["--head", head])
    try:
        return _run_gh(args, cwd=cwd, timeout=30)
    finally:
        _cleanup(tmp)


def pr_list(cwd: str, state: str = "open", limit: int = 10) -> dict:
    """列出 PR。"""
    r = _run_gh(
        [
            "pr",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,state,url,author,createdAt",
        ],
        cwd=cwd,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "prs": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def pr_view(cwd: str, number: int = None) -> dict:
    """查看 PR 详情。"""
    args = ["pr", "view"]
    if number:
        args.append(str(number))
    args.extend(
        ["--json", "number,title,state,url,body,author,createdAt,mergedAt,mergeable"]
    )
    return _run_gh(args, cwd=cwd)


def pr_merge(cwd: str, number: int = None, strategy: str = "squash") -> dict:
    """合并 PR。strategy: squash / rebase / merge。"""
    args = ["pr", "merge"]
    if number:
        args.append(str(number))
    args.append(f"--{strategy}")
    return _run_gh(args, cwd=cwd, timeout=30)


def pr_review(
    cwd: str,
    number: int,
    body: str = "",
    review_event: str = "comment",
) -> dict:
    """提交 PR review。body 始终通过 --body-file 传递，避免 shell/CLI 截断多行正文。"""
    event_flags = {
        "approve": "--approve",
        "request-changes": "--request-changes",
        "comment": "--comment",
    }
    flag = event_flags.get(str(review_event or "comment").strip().lower())
    if not flag:
        return {"ok": False, "error": "review_event 必须是 approve/request-changes/comment"}
    args = ["pr", "review", str(number), flag]
    tmp = _with_body_file(body, args)
    try:
        return _run_gh(args, cwd=cwd, timeout=30)
    finally:
        _cleanup(tmp)


def issue_create(
    cwd: str, title: str, body: str = "", labels: list[str] = None
) -> dict:
    """创建 Issue。"""
    args = ["issue", "create", "--title", title]
    tmp = _with_body_file(body, args)
    if labels:
        for label in labels:
            args.extend(["--label", label])
    try:
        return _run_gh(args, cwd=cwd, timeout=30)
    finally:
        _cleanup(tmp)


def issue_list(
    cwd: str, state: str = "open", limit: int = 10, labels: str = ""
) -> dict:
    """列出 Issue。"""
    args = [
        "issue",
        "list",
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        "number,title,state,url,labels,createdAt",
    ]
    if labels:
        args.extend(["--label", labels])
    r = _run_gh(args, cwd=cwd)
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "issues": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def issue_close(cwd: str, number: int) -> dict:
    """关闭 Issue。"""
    return _run_gh(["issue", "close", str(number)], cwd=cwd)


def release_create(
    cwd: str, tag: str, notes: str = "", generate_notes: bool = True
) -> dict:
    """创建 Release。"""
    args = ["release", "create", tag]
    if generate_notes:
        args.append("--generate-notes")
    tmp = _with_body_file(notes, args, "--notes-file")
    try:
        return _run_gh(args, cwd=cwd, timeout=30)
    finally:
        _cleanup(tmp)


def release_list(cwd: str, limit: int = 5) -> dict:
    """列出 Release。"""
    r = _run_gh(
        [
            "release",
            "list",
            "--limit",
            str(limit),
            "--json",
            "name,tagName,publishedAt,isLatest,isPrerelease",
        ],
        cwd=cwd,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "releases": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def repo_view(cwd: str, owner_repo: str = "") -> dict:
    """查看仓库信息。"""
    args = ["repo", "view"]
    if owner_repo:
        args.append(owner_repo)
    args.extend(
        ["--json", "name,description,url,defaultBranchRef,stargazerCount,forkCount"]
    )
    return _run_gh(args, cwd=cwd)


def run_list(cwd: str, limit: int = 5) -> dict:
    """查看 CI 运行记录。"""
    r = _run_gh(
        [
            "run",
            "list",
            "--limit",
            str(limit),
            "--json",
            "name,status,conclusion,createdAt,headBranch,url",
        ],
        cwd=cwd,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "runs": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def repo_create(
    name: str, private: bool = True, cwd: str = "", push: bool = True
) -> dict:
    """创建 GitHub 仓库并推送。"""
    args = ["repo", "create", name]
    if private:
        args.append("--private")
    else:
        args.append("--public")
    if cwd:
        args.extend(["--source", cwd, "--remote", "origin"])
        if push:
            args.append("--push")
    return _run_gh(args, cwd=cwd if cwd else None, timeout=30)


def auth_status() -> dict:
    """检查 gh 认证状态。"""
    return _run_gh(["auth", "status"])
