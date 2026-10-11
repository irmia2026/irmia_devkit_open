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


def _install_hint() -> str:
    import sys

    if sys.platform == "win32":
        return "安装 GitHub CLI: winget install GitHub.cli"
    if sys.platform == "darwin":
        return "安装 GitHub CLI: brew install gh"
    return "安装 GitHub CLI: apt install gh 或 dnf install gh"


def _diagnose(gh_bin: str, result: dict, owner_repo: str = "") -> str:
    """按真实错误分类给提示——不要把「命令执行失败」一律说成「可执行文件找不到」。"""
    stderr = (result.get("stderr") or result.get("error") or "").strip()
    low = stderr.lower()
    if "未安装" in stderr or "不在 PATH" in stderr or "no such file" in low:
        return (
            f"gh CLI 未在 {gh_bin} 找到，请检查 config.json 的 gh_path；"
            f"或用 es_search('gh.exe') 找到路径后填入。{_install_hint()}"
        )
    if "not a git repository" in low or "no git remotes" in low:
        if owner_repo:
            return f"gh 无法识别目标仓库（{owner_repo}）：{stderr}"
        return (
            "当前目录不是 git 仓库（或没有远程仓库），gh 判断不出要操作哪个仓库。"
            "传 cwd 指向仓库目录；或传 owner_repo='owner/repo'，会走 --repo 直接指定，不需要本地仓库。"
        )
    if "auth" in low or "logged in" in low or "credential" in low:
        return f"gh 未认证或凭证失效：{stderr}。用 gh auth status 检查，必要时 gh auth login。"
    return f"gh 命令执行失败（退出码 {result.get('code')}）：{stderr or '无 stderr 输出'}"


def _run_gh(
    args: list[str], cwd: str = None, timeout: int = 20, owner_repo: str = ""
) -> dict:
    """执行 gh 子命令。传 owner_repo 时追加 --repo，此时不依赖本地 git 仓库。"""
    if owner_repo:
        args = list(args) + ["--repo", owner_repo]
        cwd = cwd or "."
    if not cwd:
        cwd = os.getcwd()
    gh_bin = _find_gh()
    result = _run_cmd([gh_bin] + args, cwd=cwd, timeout=timeout)
    if not result["ok"]:
        result["proposal"] = _diagnose(gh_bin, result, owner_repo)
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
    cwd: str,
    title: str,
    body: str = "",
    base: str = "master",
    head: str = "",
    owner_repo: str = "",
) -> dict:
    """创建 Pull Request。"""
    args = ["pr", "create", "--title", title, "--base", base]
    tmp = _with_body_file(body, args)
    if head:
        args.extend(["--head", head])
    try:
        return _run_gh(args, cwd=cwd, timeout=30, owner_repo=owner_repo)
    finally:
        _cleanup(tmp)


def pr_list(
    cwd: str, state: str = "open", limit: int = 10, owner_repo: str = ""
) -> dict:
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
        owner_repo=owner_repo,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "prs": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def pr_view(cwd: str, number: int = None, owner_repo: str = "") -> dict:
    """查看 PR 详情。"""
    args = ["pr", "view"]
    if number:
        args.append(str(number))
    args.extend(
        ["--json", "number,title,state,url,body,author,createdAt,mergedAt,mergeable"]
    )
    return _run_gh(args, cwd=cwd, owner_repo=owner_repo)


def pr_merge(
    cwd: str, number: int = None, strategy: str = "squash", owner_repo: str = ""
) -> dict:
    """合并 PR。strategy: squash / rebase / merge。"""
    args = ["pr", "merge"]
    if number:
        args.append(str(number))
    args.append(f"--{strategy}")
    return _run_gh(args, cwd=cwd, timeout=30, owner_repo=owner_repo)


def pr_review(
    cwd: str,
    number: int,
    body: str = "",
    review_event: str = "comment",
    owner_repo: str = "",
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
        return _run_gh(args, cwd=cwd, timeout=30, owner_repo=owner_repo)
    finally:
        _cleanup(tmp)


def issue_create(
    cwd: str,
    title: str,
    body: str = "",
    labels: list[str] = None,
    owner_repo: str = "",
) -> dict:
    """创建 Issue。"""
    args = ["issue", "create", "--title", title]
    tmp = _with_body_file(body, args)
    if labels:
        for label in labels:
            args.extend(["--label", label])
    try:
        return _run_gh(args, cwd=cwd, timeout=30, owner_repo=owner_repo)
    finally:
        _cleanup(tmp)


def issue_list(
    cwd: str,
    state: str = "open",
    limit: int = 10,
    labels: str = "",
    owner_repo: str = "",
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
    r = _run_gh(args, cwd=cwd, owner_repo=owner_repo)
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "issues": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def issue_close(cwd: str, number: int, owner_repo: str = "") -> dict:
    """关闭 Issue。"""
    return _run_gh(["issue", "close", str(number)], cwd=cwd, owner_repo=owner_repo)


def release_create(
    cwd: str,
    tag: str,
    notes: str = "",
    generate_notes: bool = True,
    owner_repo: str = "",
) -> dict:
    """创建 Release。"""
    args = ["release", "create", tag]
    if generate_notes:
        args.append("--generate-notes")
    tmp = _with_body_file(notes, args, "--notes-file")
    try:
        return _run_gh(args, cwd=cwd, timeout=30, owner_repo=owner_repo)
    finally:
        _cleanup(tmp)


def release_list(cwd: str, limit: int = 5, owner_repo: str = "") -> dict:
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
        owner_repo=owner_repo,
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


def run_list(cwd: str, limit: int = 5, owner_repo: str = "") -> dict:
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
        owner_repo=owner_repo,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        return {"ok": True, "runs": data, "count": len(data)}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def run_view(run_id: int, cwd: str = ".", owner_repo: str = "") -> dict:
    """查看 CI 运行详情（含 jobs）。"""
    r = _run_gh(
        [
            "run",
            "view",
            str(run_id),
            "--json",
            "name,status,conclusion,headBranch,createdAt,jobs",
        ],
        cwd=cwd,
        owner_repo=owner_repo,
    )
    if not r["ok"]:
        return r
    try:
        data = json.loads(r["stdout"])
        if isinstance(data, dict):
            return {"ok": True, **data}
        return {"ok": True, "raw": r["stdout"]}
    except json.JSONDecodeError:
        return {"ok": True, "raw": r["stdout"]}


def run_logs(
    run_id: int, cwd: str = ".", max_chars: int = 8000, owner_repo: str = ""
) -> dict:
    """查看 CI 运行日志。输出截断到 max_chars，保留末尾（日志尾部更重要）。"""
    r = _run_gh(
        ["run", "view", str(run_id), "--log"],
        cwd=cwd,
        timeout=60,
        owner_repo=owner_repo,
    )
    if not r["ok"]:
        return r
    logs = r["stdout"]
    result = {"ok": True, "logs": logs, "total_chars": len(logs)}
    if len(logs) > max_chars:
        result["logs"] = logs[-max_chars:]
        result["truncated"] = True
    return result


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
