"""
shell_exec - constrained command execution for test/build workflows.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path


_DANGEROUS_RAW = ("|", ";", "&", "||", ">", "<", "$(", "`", "\n", "\r", "%")
_SAFE_COMMANDS: dict[str, tuple[str, ...]] = {
    "npm": ("test", "run", "build", "lint", "install"),
    "npx": ("jest", "vitest", "tsc", "eslint"),
    "cargo": ("test", "build", "check", "clippy", "fmt"),
    "go": ("test", "build", "vet", "fmt"),
    "pip": ("install", "uninstall", "list", "freeze"),
    "make": ("*",),
    "pytest": ("*",),
    "python": ("-m",),
    "py": ("-m",),
}
_HIGH_RISK = {
    ("pip", "install"),
    ("pip", "uninstall"),
    ("npm", "install"),
    ("make", "*"),
}


def split_command(cmd: str) -> list[str]:
    """Split a command string without invoking a shell."""
    if not cmd or not cmd.strip():
        raise ValueError("cmd must not be empty")
    if any(part in cmd for part in _DANGEROUS_RAW):
        raise ValueError("command contains shell control characters")
    try:
        parts = shlex.split(cmd, posix=False)
    except ValueError as exc:
        raise ValueError(f"invalid command syntax: {exc}") from exc
    cleaned = [p for p in parts if p.strip()]
    if not cleaned:
        raise ValueError("cmd must not be empty")
    # 禁止带路径的命令，防止 /malicious/python 被当作 python 放行
    if any(sep in cleaned[0] for sep in ("/", "\\")):
        raise ValueError("command must be a bare executable name (no path separators)")
    for arg in cleaned:
        if any(part in arg for part in _DANGEROUS_RAW):
            raise ValueError("argument contains shell control characters")
        lowered = arg.replace("\\", "/").lower()
        if lowered.startswith("/dev/") or "/dev/" in lowered:
            raise ValueError("argument references /dev, which is not allowed")
    return cleaned


def truncate_output(text: str, max_lines: int = 500) -> tuple[str, bool]:
    if max_lines <= 0:
        max_lines = 500
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    head = max(1, int(max_lines * 0.2))
    tail = max(1, max_lines - head - 1)
    omitted = len(lines) - head - tail
    joined = "\n".join(
        lines[:head] + [f"[...{omitted} lines omitted...]"] + lines[-tail:]
    )
    return joined, True


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _subcommand(args: list[str]) -> str:
    if len(args) < 2:
        return ""
    return args[1].lower()


def validate_command(args: list[str], allow_high_risk: bool = False) -> dict:
    exe = Path(args[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    allowed = _SAFE_COMMANDS.get(exe)
    if allowed is None:
        return {"ok": False, "error": f"command not allowed: {args[0]}"}

    sub = _subcommand(args)
    if exe in ("python", "py"):
        if len(args) < 3 or args[1] != "-m" or args[2] != "pytest":
            return {"ok": False, "error": "only python -m pytest is allowed"}
        sub = "-m"
    elif "*" not in allowed and sub not in allowed:
        return {"ok": False, "error": f"subcommand not allowed: {exe} {sub or '<none>'}"}

    risk_key = (exe, sub)
    if exe == "make":
        risk_key = ("make", "*")
    high_risk = risk_key in _HIGH_RISK
    if high_risk and not allow_high_risk:
        return {
            "ok": False,
            "error": f"high-risk command requires allow_high_risk=true: {' '.join(args)}",
            "proposal": "Review the command first, then retry with allow_high_risk=true if it is intentional.",
            "evidence": {"command": args, "risk": "high"},
            "options": ["dry_run=true", "allow_high_risk=true", "cancel"],
        }
    return {"ok": True, "command": args, "high_risk": high_risk}


def _resolve_cwd(project_dir: str) -> Path:
    cwd = Path.cwd().resolve()
    target = (cwd / project_dir).resolve() if not Path(project_dir).is_absolute() else Path(project_dir).resolve()
    if not target.exists() or not target.is_dir():
        raise ValueError(f"project_dir does not exist or is not a directory: {project_dir}")
    try:
        target.relative_to(cwd)
    except ValueError as exc:
        raise ValueError("project_dir must be inside the current working directory") from exc
    return target


def run(
    cmd: str,
    project_dir: str = ".",
    timeout: int = 120,
    max_lines: int = 500,
    dry_run: bool = False,
    allow_high_risk: bool = False,
) -> dict:
    try:
        args = split_command(cmd)
        cwd = _resolve_cwd(project_dir)
        valid = validate_command(args, allow_high_risk=allow_high_risk)
        if not valid.get("ok"):
            return valid
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "cmd": " ".join(args),
            "args": args,
            "cwd": str(cwd),
            "high_risk": bool(valid.get("high_risk")),
        }

    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "HOME": os.environ.get("HOME", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "CARGO_HOME": os.environ.get("CARGO_HOME", ""),
        "GOPATH": os.environ.get("GOPATH", ""),
        "NODE_PATH": os.environ.get("NODE_PATH", ""),
        "COLUMNS": "999",
    }
    start = time.monotonic()
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout)),
            shell=False,
            env=env,
        )
    except FileNotFoundError:
        return {"ok": False, "error": f"command not found: {args[0]}", "cmd": " ".join(args)}
    except subprocess.TimeoutExpired as exc:
        stdout, out_truncated = truncate_output(_to_text(exc.stdout), max_lines)
        stderr, err_truncated = truncate_output(_to_text(exc.stderr), max_lines)
        return {
            "ok": False,
            "error": f"command timed out after {timeout}s",
            "cmd": " ".join(args),
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_s": round(time.monotonic() - start, 3),
            "truncated": out_truncated or err_truncated,
        }

    stdout, out_truncated = truncate_output(completed.stdout or "", max_lines)
    stderr, err_truncated = truncate_output(completed.stderr or "", max_lines)
    ok = completed.returncode == 0
    return {
        "ok": ok,
        "cmd": " ".join(args),
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_s": round(time.monotonic() - start, 3),
        "truncated": out_truncated or err_truncated,
        "high_risk": bool(valid.get("high_risk")),
        **({} if ok else {"error": f"command exited with code {completed.returncode}"}),
    }
