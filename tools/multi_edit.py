"""
multi_edit - atomic orchestration for multiple exact text edits.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from ._file_utils import SAFE_EDIT_MAX_SIZE, read_file_with_encoding, find_closest_line, align_whitespace, backup_name_stem, check_path_allowed, prune_backups
from .safe_edit import _backup_dir
from .syntax_check import check as syntax_check_file


_CODE_SUFFIXES = (".py", ".nim", ".go", ".js", ".ts", ".jsx", ".tsx")


class AmbiguousMatchError(ValueError):
    """old 文本多匹配且未指定 occurrence/replace_all 时抛出，携带匹配位置证据。"""

    def __init__(self, message: str, matches: list | None = None, total: int = 0):
        super().__init__(message)
        self.matches = matches or []
        self.total = total


def _normalize_line_endings(s: str) -> str:
    """统一把 \\r\\n 转成 \\n，方便跨换行风格匹配。"""
    return s.replace("\r\n", "\n")


def _positions(content: str, old: str) -> list[int]:
    positions = []
    pos = 0
    while True:
        idx = content.find(old, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + len(old)
    return positions


def _line_col(content: str, idx: int) -> tuple[int, int]:
    line = content[:idx].count("\n") + 1
    start = content.rfind("\n", 0, idx) + 1
    return line, idx - start + 1


def _apply_one(content: str, edit_item: dict, item_index: int) -> tuple[str, dict]:
    old = _normalize_line_endings(edit_item.get("old", ""))
    new = _normalize_line_endings(edit_item.get("new", ""))
    replace_all = bool(edit_item.get("replace_all", False))
    occurrence = int(edit_item.get("occurrence", 0) or 0)
    if not old:
        raise ValueError(f"edit #{item_index}: old must not be empty")
    if occurrence < 0:
        raise ValueError(f"edit #{item_index}: occurrence must be >= 0")
    if replace_all and occurrence > 0:
        raise ValueError(f"edit #{item_index}: replace_all and occurrence are mutually exclusive")
    positions = _positions(content, old)
    if not positions:
        # P0-1: whitespace-tolerant fallback (inherited from safe_edit)
        aligned = align_whitespace(content, old, new)
        if aligned:
            old, new = aligned
            positions = _positions(content, old)
        if not positions:
            closest = find_closest_line(content, old)
            hint = (
                f"最接近的行 #{closest['line']}: {closest['text']}——建议复制此行作为 old 参数重试。"
                if closest
                else "old 文本在文件中未找到，检查是否包含完整且精确的文本片段（包括缩进和换行）。"
            )
            raise ValueError(
                f"edit #{item_index}: old text not found — {hint}"
            )
    if replace_all:
        return content.replace(old, new), {"replaced": len(positions), "replace_all": True}
    if occurrence > 0:
        if occurrence > len(positions):
            raise ValueError(f"edit #{item_index}: occurrence={occurrence} exceeds match count {len(positions)}")
        idx = positions[occurrence - 1]
        return content[:idx] + new + content[idx + len(old):], {"replaced": 1, "occurrence": occurrence}
    if len(positions) > 1:
        previews = []
        for idx in positions[:20]:
            line, col = _line_col(content, idx)
            line_start = content.rfind("\n", 0, idx) + 1
            line_end = content.find("\n", idx)
            if line_end == -1:
                line_end = len(content)
            previews.append({"line": line, "col": col, "preview": content[line_start:line_end].strip()[:100]})
        raise AmbiguousMatchError(
            f"edit #{item_index}: old text appears {len(positions)} times; specify occurrence or replace_all",
            matches=previews,
            total=len(positions),
        )
    idx = positions[0]
    return content[:idx] + new + content[idx + len(old):], {"replaced": 1}


def _syntax_check_temp(original: Path, content: str, encoding: str) -> dict:
    if original.suffix.lower() not in _CODE_SUFFIXES:
        return {"ok": True, "language": "text", "skipped": True}
    fd = -1
    tmp_name = ""
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{original.name}.", suffix=original.suffix, text=True)
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            fd = -1
            f.write(content)
        return syntax_check_file(tmp_name)
    except Exception as exc:
        return {"ok": False, "error": f"syntax check internal error: {exc}"}
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _backup_file(path: Path) -> Path:
    backup_root = _backup_dir()
    backup_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_root / f"{backup_name_stem(path)}.{ts}.multi.bak"
    shutil.copy2(str(path), str(backup_path))
    return backup_path


def run(edits: list, syntax_check: bool = True) -> dict:
    """Apply a list of exact text edits atomically.

    Args:
        edits: list of {file, old, new[, replace_all, occurrence]}.
        syntax_check: run syntax check on code files before committing.

    Returns:
        {ok, applied, total_requested, total_applied, rolled_back_all, backups, plan}

    Multi-edit semantics for the same file:
        Edits are applied sequentially — the second edit's ``old`` must
        match the file content **after** the first edit has been applied.
        Example:
            [{"file":"a.py", "old":"foo", "new":"bar"},
             {"file":"a.py", "old":"bar", "new":"baz"}]  # works
            [{"file":"a.py", "old":"foo", "new":"bar"},
             {"file":"a.py", "old":"foo", "new":"baz"}]  # fails: second edit can't find "foo"
    """
    if not isinstance(edits, list) or not edits:
        return {"ok": False, "error": "edits must be a non-empty list"}

    files: dict[Path, dict] = {}
    plan = []
    try:
        for i, item in enumerate(edits, 1):
            if not isinstance(item, dict):
                return {"ok": False, "error": f"edit #{i} must be an object"}
            raw_file = item.get("file") or item.get("filepath")
            if not raw_file:
                return {"ok": False, "error": f"edit #{i}: file is required"}
            # 先对原始字符串做路径安全检查（.. 穿越 / 系统目录），
            # 再 resolve 供内部使用（与 safe_edit 一致的顺序）。
            err = check_path_allowed(raw_file)
            if err:
                return err
            path = Path(raw_file).resolve()
            if not path.exists() or not path.is_file():
                return {"ok": False, "error": f"edit #{i}: file does not exist: {raw_file}"}
            if path.stat().st_size > SAFE_EDIT_MAX_SIZE:
                return {"ok": False, "error": f"edit #{i}: file exceeds 20MB limit: {raw_file}"}
            if path not in files:
                content, encoding = read_file_with_encoding(path)
                files[path] = {
                    "original": content,
                    "content": _normalize_line_endings(content),
                    "encoding": encoding,
                    "has_crlf": "\r\n" in content,
                    "edits": [],
                }
            new_content, meta = _apply_one(files[path]["content"], item, i)
            files[path]["content"] = new_content
            files[path]["edits"].append({"index": i, **meta})
            plan.append({"file": str(path), "edit": i, **meta})
    except AmbiguousMatchError as exc:
        # B6: 消歧证据（匹配位置）随错误返回，与 safe_edit 的响应形态对齐
        count = exc.total or len(exc.matches)
        return {
            "ok": False,
            "error": str(exc),
            "proposal": f"请使用 occurrence=N 指定目标（1~{count}），或设 replace_all=True 替换全部",
            "options": [f"occurrence={i+1}" for i in range(min(count, 5))] + ["replace_all=True"],
            "evidence": {"occurrence_count": count, "matches": exc.matches[:20]},
            "matches": exc.matches[:20],
            "occurrence_count": count,
            "applied": [],
            "total_requested": len(edits),
            "total_applied": 0,
            "rolled_back_all": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "applied": [],
            "total_requested": len(edits),
            "total_applied": 0,
            "rolled_back_all": True,
        }

    # 先备份原文件（快照），再做语法检查，最后原子提交。
    # 顺序不能颠倒：若先语法检查后备份，检查期间文件被外界改动会备份到错误内容（TOCTOU）。
    backups: dict[Path, Path] = {}
    try:
        for path in files:
            backups[path] = _backup_file(path)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"backup failed: {exc}",
            "applied": [],
            "total_requested": len(edits),
            "total_applied": 0,
            "rolled_back_all": True,
        }

    if syntax_check:
        for path, data in files.items():
            result = _syntax_check_temp(path, data["content"], data["encoding"])
            if not result.get("ok"):
                return {
                    "ok": False,
                    "error": f"{path}: syntax check failed",
                    "syntax_check": result,
                    "applied": [],
                    "total_requested": len(edits),
                    "total_applied": 0,
                    "rolled_back_all": True,
                }

    tmp_paths: dict[Path, Path] = {}
    try:
        for path, data in files.items():
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent), text=True)
            final_content = data["content"].replace("\n", "\r\n") if data["has_crlf"] else data["content"]
            with os.fdopen(fd, "w", encoding=data["encoding"], newline="") as f:
                f.write(final_content)
            tmp_paths[path] = Path(tmp_name)
        for path, tmp_path in tmp_paths.items():
            os.replace(str(tmp_path), str(path))
    except Exception as exc:
        rollback_errors = []
        for path, backup in backups.items():
            try:
                shutil.copy2(str(backup), str(path))
            except OSError as rb_exc:
                rollback_errors.append({"file": str(path), "error": str(rb_exc)})
        for tmp_path in tmp_paths.values():
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
        return {
            "ok": False,
            "error": f"commit failed: {exc}",
            "applied": [],
            "total_requested": len(edits),
            "total_applied": 0,
            "rolled_back_all": len(rollback_errors) == 0,
            "rollback_errors": rollback_errors,
        }

    # calculate total replacements (replace_all may replace >1 instance per edit)
    replacements_made = sum(e.get("replaced", 1) for e in plan)

    # P1: 惰性清理备份目录（防御性，异常静默吞掉，绝不影响编辑主流程）
    prune_backups(str(_backup_dir()))

    return {
        "ok": True,
        "applied": [str(p) for p in files],
        "total_requested": len(edits),
        "total_applied": len(edits),
        "replacements_made": replacements_made,
        "rolled_back_all": False,
        "backups": {str(path): str(backup) for path, backup in backups.items()},
        "plan": plan,
    }
