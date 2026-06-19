"""
test_runner - unified pytest/go test/cargo test/jest wrapper.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from .shell_exec import split_command, validate_command


_PYTEST_SUMMARY_RE = re.compile(
    r"(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?"
    r"(?:(?P<passed>\d+)\s+passed)?(?:,\s*)?"
    r"(?:(?P<skipped>\d+)\s+skipped)?",
    re.IGNORECASE,
)


def _resolve_project_dir(filepath: str = "", project_dir: str = ".") -> Path:
    if filepath:
        p = Path(filepath).resolve()
        if p.exists():
            return p.parent if p.is_file() else p
    return Path(project_dir or ".").resolve()


def discover(project_dir: Path) -> tuple[str, list[str]]:
    if (project_dir / "go.mod").exists():
        return "go", ["go", "test", "./...", "-json"]
    if (project_dir / "Cargo.toml").exists():
        return "cargo", ["cargo", "test"]
    if (project_dir / "package.json").exists():
        try:
            data = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            deps = {}
            deps.update(data.get("dependencies", {}) if isinstance(data, dict) else {})
            deps.update(data.get("devDependencies", {}) if isinstance(data, dict) else {})
            if "jest" in deps or "jest" in str(scripts.get("test", "")):
                return "jest", ["npx", "jest", "--json"]
            if "test" in scripts:
                return "npm", ["npm", "test"]
        except Exception:
            pass
        return "jest", ["npx", "jest", "--json"]
    return "pytest", [sys.executable, "-m", "pytest", "-q", "--tb=short"]


def _run(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str, float, bool]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout)),
            shell=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or "", time.monotonic() - start, False
    except subprocess.TimeoutExpired as exc:
        return -1, _to_text(exc.stdout), _to_text(exc.stderr), time.monotonic() - start, True
    except FileNotFoundError as exc:
        return 127, "", str(exc), time.monotonic() - start, False


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _parse_pytest(stdout: str, stderr: str, returncode: int, elapsed: float, timeout: bool) -> dict:
    text = "\n".join([stdout, stderr])
    passed = failed = skipped = 0
    raw_summary = ""
    for line in reversed(text.splitlines()):
        if " passed" in line or " failed" in line or " skipped" in line:
            raw_summary = line.strip("= ")
            for num, label in re.findall(r"(\d+)\s+(passed|failed|skipped|error|errors)", raw_summary):
                if label == "passed":
                    passed += int(num)
                elif label == "failed":
                    failed += int(num)
                elif label == "skipped":
                    skipped += int(num)
                else:
                    failed += int(num)
            break
    errors = []
    for line in text.splitlines():
        if line.startswith("FAILED "):
            parts = line.split(" - ", 1)
            errors.append({"test": parts[0].replace("FAILED ", "", 1), "msg": parts[1] if len(parts) > 1 else ""})
    return {
        "ok": not timeout and returncode == 0,
        "framework": "pytest",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors[:20],
        "duration_s": round(elapsed, 3),
        "coverage_pct": None,
        "raw_summary": raw_summary or (stderr.strip() or stdout.strip())[-500:],
        "returncode": returncode,
        "timeout": timeout,
    }


def _parse_go(stdout: str, stderr: str, returncode: int, elapsed: float, timeout: bool) -> dict:
    passed = failed = skipped = 0
    errors = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = event.get("Action")
        test = event.get("Test")
        if not test:
            continue
        if action == "pass":
            passed += 1
        elif action == "fail":
            failed += 1
            errors.append({"test": test, "file": event.get("Package", ""), "msg": event.get("Output", "")})
        elif action == "skip":
            skipped += 1
    return {
        "ok": not timeout and returncode == 0,
        "framework": "go",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors[:20],
        "duration_s": round(elapsed, 3),
        "coverage_pct": None,
        "raw_summary": (stderr.strip() or stdout.strip())[-500:],
        "returncode": returncode,
        "timeout": timeout,
    }


def _parse_cargo(stdout: str, stderr: str, returncode: int, elapsed: float, timeout: bool) -> dict:
    text = "\n".join([stdout, stderr])
    passed = failed = skipped = 0
    raw_summary = ""
    for line in reversed(text.splitlines()):
        if "test result:" in line:
            raw_summary = line.strip()
            for num, label in re.findall(r"(\d+)\s+(passed|failed|ignored|filtered)", raw_summary):
                if label == "passed":
                    passed += int(num)
                elif label == "failed":
                    failed += int(num)
                elif label in ("ignored", "filtered"):
                    skipped += int(num)
            break
    errors = [{"test": m.group(1), "msg": "failed"} for m in re.finditer(r"----\s+(.+?)\s+stdout\s+----", text)]
    return {
        "ok": not timeout and returncode == 0,
        "framework": "cargo",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors[:20],
        "duration_s": round(elapsed, 3),
        "coverage_pct": None,
        "raw_summary": raw_summary or (stderr.strip() or stdout.strip())[-500:],
        "returncode": returncode,
        "timeout": timeout,
    }


def _parse_jest(stdout: str, stderr: str, returncode: int, elapsed: float, timeout: bool) -> dict:
    text = stdout.strip()
    data = None
    if text:
        # locate the outermost JSON object — jest may prefix with npm output
        try:
            start = text.index('"numPassedTests"')
            # rewind to the preceding '{'
            brace = text.rfind("{", 0, start)
            if brace != -1:
                end = text.rfind("}")
                if end > brace:
                    data = json.loads(text[brace:end + 1])
        except (ValueError, json.JSONDecodeError):
            pass
        if data is None:
            try:
                data = json.loads(text[text.rfind("{"):text.rfind("}") + 1])
            except Exception:
                data = None
    if isinstance(data, dict):
        errors = []
        for suite in data.get("testResults", []):
            for item in suite.get("assertionResults", []):
                if item.get("status") == "failed":
                    errors.append({
                        "test": " ".join(item.get("ancestorTitles", []) + [item.get("title", "")]).strip(),
                        "file": suite.get("name", ""),
                        "msg": "\n".join(item.get("failureMessages", []))[:1000],
                    })
        return {
            "ok": not timeout and returncode == 0,
            "framework": "jest",
            "passed": int(data.get("numPassedTests", 0)),
            "failed": int(data.get("numFailedTests", 0)),
            "skipped": int(data.get("numPendingTests", 0)),
            "errors": errors[:20],
            "duration_s": round(elapsed, 3),
            "coverage_pct": None,
            "raw_summary": data.get("success", ""),
            "returncode": returncode,
            "timeout": timeout,
        }
    failed = len(re.findall(r"\bFAIL\b", stdout))
    passed = len(re.findall(r"\bPASS\b", stdout))
    return {
        "ok": not timeout and returncode == 0,
        "framework": "jest",
        "passed": passed,
        "failed": failed,
        "skipped": 0,
        "errors": [],
        "duration_s": round(elapsed, 3),
        "coverage_pct": None,
        "raw_summary": (stderr.strip() or stdout.strip())[-500:],
        "returncode": returncode,
        "timeout": timeout,
    }


def _parser_for(framework: str):
    if framework == "go":
        return _parse_go
    if framework == "cargo":
        return _parse_cargo
    if framework in ("jest", "npm"):
        return _parse_jest
    return _parse_pytest


def run(
    filepath: str = "",
    project_dir: str = ".",
    test_cmd: str = "",
    timeout: int = 120,
) -> dict:
    root = _resolve_project_dir(filepath, project_dir)
    if not root.exists():
        return {"ok": False, "error": f"project_dir does not exist: {root}"}

    framework, args = discover(root)
    if test_cmd:
        try:
            args = split_command(test_cmd)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        valid = validate_command(args, allow_high_risk=False)
        if not valid.get("ok"):
            return valid
        exe = Path(args[0]).name.lower().removesuffix(".exe")
        framework = {"python": "pytest", "py": "pytest", "pytest": "pytest", "go": "go", "cargo": "cargo", "npx": "jest", "npm": "npm"}.get(exe, framework)

    returncode, stdout, stderr, elapsed, timed_out = _run(args, root, timeout)
    result = _parser_for(framework)(stdout, stderr, returncode, elapsed, timed_out)
    result["cmd"] = " ".join(args)
    result["project_dir"] = str(root)
    if timed_out:
        result["error"] = f"test command timed out after {timeout}s"
    elif returncode == 127:
        result["error"] = stderr.strip() or "test command not found"
    return result
