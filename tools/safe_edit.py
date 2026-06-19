"""
safe_edit — 安全编辑工具（强制使用）。
修改任何代码文件必须用此工具。内部自动：备份→patch→语法检查→通过保留/失败回滚。
"""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .config import get_config, get_plugin_dir
from .file_patch import patch
from .syntax_check import check as syntax_check
from ._file_utils import read_file_with_encoding, find_closest_line, SAFE_EDIT_MAX_SIZE, align_whitespace


def _backup_dir() -> Path:
    """读取配置的备份目录，未配置则使用默认值。"""
    config = get_config()
    custom = config.get("backup_dir", "")
    if custom:
        return Path(custom)
    default = Path.home() / ".irmia" / "backups"
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:
        root = get_plugin_dir() or Path(tempfile.gettempdir())
        return Path(root) / ".irmia" / "backups"


def _collect_positions(content: str, old: str) -> list[int]:
    """收集 old 在 content 中所有非重叠匹配的起始索引。"""
    positions = []
    pos = 0
    while True:
        idx = content.find(old, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + len(old)
    return positions


def edit(
    filepath: str, old: str, new: str, replace_all: bool = False, occurrence: int = 0
) -> dict:
    """
    安全编辑文件：自动备份→替换→语法检查→通过保留/失败回滚。

    修改任何代码文件必须使用此工具，不要绕过它直接用 file_write 或 file_patch。

    Args:
        filepath: 文件路径
        old: 旧文本（精确匹配）
        new: 新文本
        replace_all: 是否替换所有匹配
        occurrence: 替换第 N 次出现（0=默认行为，首次出现。多匹配时可用此参数消歧）

    Returns:
        {"ok": true, "backup": "...", "syntax_ok": true}
        或 {"ok": false, "rolled_back": true, "error": "..."}
        或 {"ok": false, "matches": [行号...], "hint": "请使用 occurrence=N 指定目标"}
    """
    # C2: 拦截空 old 字符串，防止 content.replace("", "X") 损毁文件
    if not old:
        return {"ok": False, "error": "old 参数不能为空字符串，空替换会损毁文件"}

    p = Path(filepath).resolve()
    filepath = str(p)

    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    if p.stat().st_size > SAFE_EDIT_MAX_SIZE:
        return {"ok": False, "error": "文件超过 20MB 上限，safe_edit 不支持大文件编辑。建议用外部编辑器。"}

    # 0. 读取文件内容
    try:
        content, encoding = read_file_with_encoding(p)
    except Exception as e:
        return {"ok": False, "error": f"无法解码文件: {e}"}

    # 0.1 消歧
    old_count = content.count(old)
    if old_count == 0:
        # P0-1: whitespace-tolerant fallback before giving up
        aligned = align_whitespace(content, old, new)
        if aligned and not replace_all:
            old, new = aligned
            old_count = content.count(old)
            result_extra = {"whitespace_aligned": True}
        else:
            closest = find_closest_line(content, old)
            hint = (
                f"最接近的行 #{closest['line']}: {closest['text']}——建议复制此行作为 old 参数重试。"
                if closest
                else "old 文本在文件中未找到，检查是否包含完整且精确的文本片段（包括缩进和换行）。"
            )
            return {
                "ok": False,
                "error": "未找到匹配文本，文件内容未修改",
                "proposal": hint,
                "evidence": closest or {},
                "options": ["复制最接近的行作为 old", "确认缩进级别"],
            }
    else:
        result_extra = {}

    # ── 消歧与替换 ──

    if old_count > 1 and not replace_all and occurrence == 0:
        positions = []
        for idx in _collect_positions(content, old):
            line_num = content[:idx].count("\n") + 1
            line_start = content.rfind("\n", 0, idx) + 1
            line_end = content.find("\n", idx)
            if line_end == -1:
                line_end = len(content)
            preview = content[line_start:line_end].strip()[:80]
            col = idx - line_start + 1
            positions.append({"line": line_num, "col": col, "preview": preview})
        return {
            "ok": False,
            "error": f"old 文本在文件中出现了 {old_count} 次，请指定要替换第几次出现",
            "proposal": f"请使用 occurrence=N 指定目标（1~{old_count}），或设 replace_all=True 替换全部",
            "options": [f"occurrence={i+1}" for i in range(min(old_count, 5))],
            "evidence": {"occurrence_count": old_count, "matches": positions[:20]},
            "matches": positions[:20],
            "occurrence_count": old_count,
        }

    # 2. 执行替换前先校验 occurrence
    if occurrence > 0 and not replace_all:
        if occurrence > old_count:
            return {"ok": False, "error": f"occurrence={occurrence} 超过匹配总数 {old_count}"}

    # 1. 备份（在任何修改之前）
    backup_root = _backup_dir()
    backup_root.mkdir(parents=True, exist_ok=True)  # 先创建，确保 disk_usage 路径存在
    try:
        usage = shutil.disk_usage(backup_root)
        if usage.free < 100 * 1024 * 1024:
            return {"ok": False, "error": f"备份目录磁盘空间不足（剩余 {usage.free // 1024 // 1024}MB < 100MB），无法创建备份"}
    except OSError:
        pass  # 无法检测磁盘空间，继续尝试
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_root / f"{p.name}.{ts}.bak"
    try:
        shutil.copy2(filepath, str(backup_path))
    except OSError as e:
        return {"ok": False, "error": f"无法创建备份：{e}"}

    result = {
        "file": filepath,
        "backup": str(backup_path),
        "timestamp": ts,
        **result_extra,
    }

    # 2. 执行替换
    if occurrence > 0 and not replace_all:
        positions = _collect_positions(content, old)
        idx = positions[occurrence - 1]
        content = content[:idx] + new + content[idx + len(old) :]
        try:
            with open(filepath, "w", encoding=encoding, newline="") as f:
                f.write(content)
        except OSError as e:
            return {"ok": False, "error": f"无法写入文件：{e}"}
        result["replaced"] = 1
        result["occurrence"] = occurrence
    else:
        patch_result = patch(filepath, old, new, replace_all)
        if not patch_result.get("ok"):
            return {
                **result,
                "ok": False,
                "error": patch_result.get("error", "patch 失败"),
                "rolled_back": False,
            }
        result["replaced"] = patch_result.get("replaced", 0)

    # 3. 语法检查（只对代码文件）
    suffix = p.suffix.lower()
    if suffix in (".py", ".nim", ".go", ".js", ".ts", ".jsx", ".tsx"):
        check_result = syntax_check(filepath)
        result["syntax_check"] = check_result

        if not check_result.get("ok"):
            if check_result.get("skipped"):
                result["syntax_ok"] = None
                result["syntax_check"] = check_result
            else:
                try:
                    shutil.copy2(str(backup_path), filepath)
                except OSError as e:
                    return {
                        **result,
                        "ok": False,
                        "rolled_back": False,
                        "error": f"语法检查失败且回滚失败: {e}",
                        "proposal": f"文件已被修改，备份在 {backup_path}，请手动恢复",
                        "options": ["restore_backup", "retry_edit"],
                    }
                syntax_errors = check_result.get("errors", [])
                hint = "已自动回滚。"
                if syntax_errors:
                    se = syntax_errors[0]
                    msg = str(se.get("msg", ""))
                    if "indent" in msg.lower():
                        hint += " 缩进问题——将 old 参数中的缩进减少后重试 safe_edit。"
                    elif "syntax" in msg.lower() or "invalid" in msg.lower():
                        hint += f" 语法问题({msg})——检查 old 参数中括号/引号是否完整。"
                    else:
                        hint += f" 语法错误({msg})——分析错误原因后修正 old 参数重试。"
                return {
                    **result,
                    "ok": False,
                    "rolled_back": True,
                    "error": f"语法检查失败，已自动回滚到备份: {backup_path}",
                    "syntax_errors": syntax_errors,
                    "proposal": hint,
                    "options": ["retry_edit", "show_backup_diff", "restore_backup"],
                }
        else:
            result["syntax_ok"] = True
    else:
        result["syntax_ok"] = None
        result["syntax_check"] = {"note": "非代码文件，跳过语法检查"}

    result["ok"] = True
    return result


def list_backups(filepath: str = None) -> dict:
    """列出备份文件。"""
    _backup_dir().mkdir(parents=True, exist_ok=True)
    backups = []
    for b in sorted(_backup_dir().glob("*.bak"), reverse=True):
        stat = b.stat()
        backups.append(
            {
                "file": b.name,
                "size": stat.st_size,
                "time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    if filepath:
        name = Path(filepath).name
        prefix = f"{name}."
        backups = [b for b in backups if b["file"].startswith(prefix)]

    return {"ok": True, "backups": backups[:20], "total": len(backups)}


def rollback(filepath: str, backup_name: str = None) -> dict:
    """
    回滚文件到指定备份。不指定则回滚到最近的备份。
    """
    p = Path(filepath)

    if backup_name:
        backup_path = _backup_dir() / Path(backup_name).name  # 只取文件名防路径穿越
        if not backup_path.exists():
            return {"ok": False, "error": f"备份不存在: {backup_name}"}
    else:
        # 找最近的备份
        pattern = f"{p.name}.*.bak"
        candidates = sorted(_backup_dir().glob(pattern), reverse=True)
        if not candidates:
            return {"ok": False, "error": f"没有找到 {p.name} 的备份"}
        backup_path = candidates[0]

    shutil.copy2(str(backup_path), filepath)
    return {"ok": True, "file": filepath, "restored_from": str(backup_path)}
