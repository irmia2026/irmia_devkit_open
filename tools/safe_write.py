"""
safe_write — 新建文件 / 整体覆盖写入工具（safe_edit 的姊妹工具）。

定位：
- 新建文件：safe_write 是首选。自动创建缺失的父目录；写入后做语法检查，
  但检查失败【不阻塞、不删除】——新文件没有"旧版本"可回滚，文件按原样保留，
  返回 proposal 引导用 safe_edit 修正。
- 修改已有文件的局部内容：使用 safe_edit / multi_edit。不要用 safe_write
  覆盖已有文件来"改一部分"——那会丢失所有未改动的内容。
- 确需整体覆盖已有文件（如重写一个生成的配置文件）：
  safe_write(path, content, overwrite=True)。会先备份，语法检查失败
  自动回滚到覆盖前内容（与 safe_edit 行为一致）。

不要用原生 file_write 创建/覆盖代码文件——它没有备份、没有语法检查、
没有路径沙箱，无法撤销。

范围：纯文本（UTF-8）、整文件写入。不支持追加（用 safe_edit 在文件末尾
做一次精确替换）；不支持二进制（用 http_download 写入下载内容）。
"""

import shutil
from datetime import datetime
from pathlib import Path

from .syntax_check import check as syntax_check
from ._file_utils import read_file_with_encoding, human_size, SAFE_EDIT_MAX_SIZE
from .safe_edit import _backup_dir
from .file_remove import _FORBIDDEN_PREFIXES


_PREVIEW_LINES = 8
_CODE_SUFFIXES = (".py", ".nim", ".go", ".js", ".ts", ".jsx", ".tsx")


def _preview(content: str, n: int = _PREVIEW_LINES) -> dict:
    """返回内容的行数统计 + 首尾预览，供 proposal 的 evidence 使用。"""
    lines = content.splitlines()
    return {
        "total_lines": len(lines),
        "head": lines[:n],
        "tail": lines[-n:] if len(lines) > n else [],
    }


def _check_forbidden(p: Path, raw: str) -> dict | None:
    """复用 file_remove 的路径沙箱：拒绝 .. 穿越和系统目录写入。"""
    # 在 Path 解析之前检查原始字符串，防止 Path.normalize() 消除 ..
    if ".." in raw.replace("\\", "/"):
        return {"ok": False, "error": "路径包含 .. 穿越，已被拒绝"}

    path_str = str(p).replace("\\", "/")
    for forbidden in _FORBIDDEN_PREFIXES:
        if path_str.lower().startswith(forbidden.lower() + "/") or path_str.lower() == forbidden.lower():
            return {
                "ok": False,
                "error": f"禁止写入系统目录: {p}",
                "proposal": "路径位于受保护的系统目录中，写入操作已被拦截。",
                "evidence": {"path": str(p), "blocked_by": forbidden},
            }
    return None


def _run_syntax_check(p: Path) -> dict | None:
    """对代码后缀文件运行语法检查；非代码文件返回 None。"""
    if p.suffix.lower() not in _CODE_SUFFIXES:
        return None
    return syntax_check(str(p))


def write(filepath: str, content: str, overwrite: bool = False) -> dict:
    """
    新建文件，或在 overwrite=True 时整体覆盖已有文件。

    Args:
        filepath: 目标文件路径。父目录不存在时会自动创建。
        content: 完整文件内容（文本，UTF-8）。
        overwrite: 文件已存在时是否覆盖。默认 False——已存在时返回
                   proposal（含文件大小/行数/预览），引导改用 safe_edit
                   或显式设置 overwrite=True。

    Returns:
        新建成功:
            {"ok": true, "created": true, "file": ..., "bytes": N,
             "lines": N, "created_dirs": [...],
             "syntax_ok": true|false|null, "syntax_check": {...}}
            (syntax_ok=false 时附带 syntax_errors + proposal，文件仍保留)

        已存在且 overwrite=False:
            {"ok": false, "proposal": "...", "error": "文件已存在",
             "evidence": {"existing_size": N, "preview": {...}},
             "options": [...]}

        覆盖成功:
            {"ok": true, "created": false, "overwritten": true,
             "backup": "...", "bytes_before": X, "bytes_after": Y,
             "lines": N, "syntax_ok": true|null}

        覆盖但语法检查失败（已自动回滚）:
            {"ok": false, "rolled_back": true, "error": "...",
             "syntax_errors": [...], "proposal": "...", "options": [...]}
    """
    if content is None:
        return {"ok": False, "error": "content 不能为 None"}

    raw = str(Path(filepath))
    p = Path(filepath).resolve()

    forbidden = _check_forbidden(p, raw)
    if forbidden:
        return forbidden

    content_bytes = len(content.encode("utf-8"))
    if content_bytes > SAFE_EDIT_MAX_SIZE:
        return {
            "ok": False,
            "error": f"content 超过 20MB 上限（{human_size(content_bytes)}），safe_write 不支持超大文件写入",
        }

    # ══════════════════════════════════════════════════════════════
    # 已存在的文件
    # ══════════════════════════════════════════════════════════════
    if p.exists():
        if p.is_dir():
            return {"ok": False, "error": f"路径是一个目录，不是文件: {p}"}

        # ── overwrite=False：返回 proposal + 预览，不写入 ──
        if not overwrite:
            try:
                existing, _ = read_file_with_encoding(p)
            except Exception:
                existing = ""
            return {
                "ok": False,
                "error": "文件已存在",
                "proposal": (
                    f"文件已存在（{human_size(p.stat().st_size)}，"
                    f"{len(existing.splitlines())} 行）。"
                    "如需修改局部内容请用 safe_edit；"
                    "如需整体覆盖，设置 overwrite=true（会先备份，可回滚）。"
                ),
                "evidence": {
                    "existing_size": p.stat().st_size,
                    "preview": _preview(existing),
                },
                "options": ["改用 safe_edit 做局部修改", "设置 overwrite=true 整体覆盖"],
            }

        # ── overwrite=True：备份 → 写入 → 语法检查（阻塞，失败回滚）──
        backup_root = _backup_dir()
        backup_root.mkdir(parents=True, exist_ok=True)  # 先创建，确保 disk_usage 路径存在
        try:
            usage = shutil.disk_usage(backup_root)
            if usage.free < 100 * 1024 * 1024:
                return {
                    "ok": False,
                    "error": f"备份目录磁盘空间不足（剩余 {usage.free // 1024 // 1024}MB < 100MB），无法创建备份",
                }
        except OSError:
            pass

        try:
            _, encoding = read_file_with_encoding(p)
        except Exception:
            encoding = "utf-8"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_root / f"{p.name}.{ts}.write.bak"
        try:
            shutil.copy2(str(p), str(backup_path))
        except OSError as e:
            return {"ok": False, "error": f"无法创建备份：{e}"}

        bytes_before = p.stat().st_size

        try:
            with open(p, "w", encoding=encoding, newline="") as f:
                f.write(content)
        except OSError as e:
            return {"ok": False, "error": f"无法写入文件：{e}"}

        result = {
            "file": str(p),
            "created": False,
            "overwritten": True,
            "backup": str(backup_path),
            "bytes_before": bytes_before,
            "bytes_after": p.stat().st_size,
            "lines": len(content.splitlines()),
        }

        check_result = _run_syntax_check(p)
        if check_result is None:
            result["syntax_ok"] = None
            result["syntax_check"] = {"note": "非代码文件，跳过语法检查"}
        elif check_result.get("ok"):
            result["syntax_ok"] = True
            result["syntax_check"] = check_result
        elif check_result.get("skipped"):
            result["syntax_ok"] = None
            result["syntax_check"] = check_result
        else:
            # 语法检查失败 → 回滚到覆盖前内容（有"旧版本"可恢复）
            try:
                shutil.copy2(str(backup_path), str(p))
            except OSError as e:
                return {
                    **result,
                    "ok": False,
                    "rolled_back": False,
                    "error": f"语法检查失败且回滚失败: {e}",
                    "proposal": f"文件已被覆盖，备份在 {backup_path}，请手动恢复",
                    "options": ["restore_backup"],
                }
            return {
                **result,
                "ok": False,
                "rolled_back": True,
                "error": f"语法检查失败，已自动回滚到覆盖前内容: {backup_path}",
                "syntax_errors": check_result.get("errors", []),
                "proposal": (
                    "覆盖内容存在语法错误，已恢复原文件。"
                    "检查 content 是否完整后重试，或先用 safe_edit 做增量修改。"
                ),
                "options": ["修正后重新 safe_write(overwrite=true)", "改用 safe_edit 做局部修改", "show_backup_diff"],
            }

        result["ok"] = True
        return result

    # ══════════════════════════════════════════════════════════════
    # 不存在的文件：新建（自动创建父目录）
    # ══════════════════════════════════════════════════════════════
    created_dirs: list[str] = []
    parent = p.parent
    if not parent.exists():
        missing = []
        cur = parent
        while not cur.exists():
            missing.append(cur)
            cur = cur.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"无法创建父目录：{e}"}
        created_dirs = [str(d) for d in reversed(missing)]

    try:
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        return {"ok": False, "error": f"无法写入文件：{e}"}

    result = {
        "ok": True,
        "file": str(p),
        "created": True,
        "bytes": p.stat().st_size,
        "lines": len(content.splitlines()),
        "created_dirs": created_dirs,
    }

    check_result = _run_syntax_check(p)
    if check_result is None:
        result["syntax_ok"] = None
        result["syntax_check"] = {"note": "非代码文件，跳过语法检查"}
    elif check_result.get("ok"):
        result["syntax_ok"] = True
        result["syntax_check"] = check_result
    elif check_result.get("skipped"):
        result["syntax_ok"] = None
        result["syntax_check"] = check_result
    else:
        # 新文件语法检查不阻塞——没有"旧版本"可回滚，文件按原样保留，
        # 把决定权交给 LLM（用 safe_edit 修正 / file_remove 重来）。
        result["syntax_ok"] = False
        result["syntax_check"] = check_result
        result["syntax_errors"] = check_result.get("errors", [])
        result["proposal"] = (
            "文件已创建，但存在语法错误（新文件无可回滚的旧版本，已按原样保留）。"
            "建议用 safe_edit 修正，或检查 content 是否完整。"
        )
        result["options"] = ["用 safe_edit 修正语法错误", "file_remove 后重新 safe_write"]

    return result
