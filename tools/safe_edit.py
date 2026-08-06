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
from ._file_utils import (
    read_file_with_encoding,
    find_closest_line,
    SAFE_EDIT_MAX_SIZE,
    align_whitespace as _align_whitespace,
    check_path_allowed,
    atomic_write_text,
    _first_existing_parent,
    backup_name_stem,
    prune_backups,
    strip_line_number_prefixes,
)


def _backup_dir() -> Path:
    """读取配置的备份目录，未配置则使用默认值。"""
    config = get_config()
    custom = config.get("backup_dir", "")
    if custom:
        return Path(custom).resolve()
    default = Path.home() / ".irmia" / "backups"
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except (OSError, RuntimeError):
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


def _normalize_line_endings(s: str) -> str:
    """统一把 \\r\\n 转成 \\n，方便跨换行风格匹配。"""
    return s.replace("\r\n", "\n")


def _restore_line_endings(s: str, has_crlf: bool) -> str:
    """如果原文件是 CRLF，把结果再转回 CRLF。"""
    return s.replace("\n", "\r\n") if has_crlf else s


_VALID_MODES = ("replace", "insert_at_line", "delete_lines")


def edit(
    filepath: str,
    old: str = "",
    new: str = "",
    occurrence: int = 0,
    replace_all: bool = False,
    align_whitespace: bool = True,
    mode: str = "replace",
    line: int = 0,
    start_line: int = 0,
    end_line: int = 0,
) -> dict:
    """
    安全编辑文件：自动备份→替换→语法检查→通过保留/失败回滚。

    修改任何代码文件必须使用此工具，不要绕过它直接用 file_write 或 file_patch。

    Args:
        filepath: 文件路径
        old: 旧文本（精确匹配，mode="replace" 时必填）
        new: 新文本
        occurrence: 替换第 N 次出现（0=默认行为，首次出现。多匹配时可用此参数消歧）
        replace_all: 是否替换所有匹配
        align_whitespace: 缩进对齐时保留嵌套函数的内部缩进（默认 True，自动开启）。
            当 new 中包含嵌套 def/class 等多层缩进结构时自动保留。设为 False 可手动关闭。
        mode: 编辑模式。
            "replace"（默认）：old→new 精确替换，old 必填；
            "insert_at_line"：忽略 old，在 line 指定行号之后插入 new（line=0 表示文件开头）；
            "delete_lines"：忽略 old/new，删除 [start_line, end_line] 闭区间行。
        line: insert_at_line 模式的目标行号（1-based，0=文件开头）
        start_line: delete_lines 模式的起始行号（1-based，闭区间）
        end_line: delete_lines 模式的结束行号（1-based，闭区间）

    Returns:
        {"ok": true, "backup": "...", "syntax_ok": true}
        或 {"ok": false, "rolled_back": true, "error": "..."}
        或 {"ok": false, "matches": [行号...], "hint": "请使用 occurrence=N 指定目标"}
    """
    if mode not in _VALID_MODES:
        return {
            "ok": False,
            "error": f"非法 mode: {mode!r}，可选值: {' / '.join(_VALID_MODES)}",
            "options": list(_VALID_MODES),
        }

    # C2: 拦截空 old 字符串，防止 content.replace("", "X") 损毁文件
    if mode == "replace" and not old:
        return {"ok": False, "error": "old 参数不能为空字符串，空替换会损毁文件"}
    if mode == "insert_at_line" and not new:
        return {"ok": False, "error": "insert_at_line 模式 new 参数不能为空"}

    # 路径安全校验：check_path_allowed 内部先检测原始字符串 .. 穿越，
    # 再 resolve 后检测系统目录（含符号链接跟随）。
    safety = check_path_allowed(filepath)
    if safety:
        return safety

    p = Path(filepath).resolve()
    filepath = str(p)

    if not p.exists():
        return {"ok": False, "error": f"文件不存在: {filepath}"}

    if not p.is_file():
        return {"ok": False, "error": f"路径不是文件: {filepath}"}

    if p.stat().st_size > SAFE_EDIT_MAX_SIZE:
        return {"ok": False, "error": "文件超过 20MB 上限，safe_edit 不支持大文件编辑。建议用外部编辑器。"}

    # 检查目标文件所在分区剩余空间（防止备份成功但写入失败）
    try:
        write_dir = p.parent if p.parent.exists() else _first_existing_parent(p.parent)
        usage = shutil.disk_usage(write_dir)
        if usage.free < 100 * 1024 * 1024:
            return {"ok": False, "error": f"目标文件所在分区磁盘空间不足（剩余 {usage.free // 1024 // 1024}MB < 100MB）"}
    except OSError:
        pass

    # 0. 读取文件内容
    try:
        content, encoding = read_file_with_encoding(p)
    except Exception as e:
        return {"ok": False, "error": f"无法解码文件: {e}"}

    # 0.1 CRLF → LF 归一化（与 file_patch / multi_edit 一致），
    #     确保 CRLF 文件 + LF 多行 old 也能匹配
    has_crlf = "\r\n" in content
    if has_crlf:
        content = _normalize_line_endings(content)
        old = _normalize_line_endings(old)
        new = _normalize_line_endings(new)

    if mode != "replace":
        # 行号寻址模式：跳过文本消歧，直接走 备份→行操作 链路
        result_extra = {"mode": mode}
        old_count = 0
    else:
        # 0.2 消歧
        old_count = content.count(old)
        result_extra = {}

        if old_count == 0:
            # 防呆：LLM 把 safe_read 的行号前缀（'  123│ ...'）连内容一起复制
            # 给 old 时，剥除前缀后重试。精确匹配已在上方失败，此处安全。
            stripped_old, had_prefix = strip_line_number_prefixes(old)
            if had_prefix:
                stripped_new, _ = strip_line_number_prefixes(new)
                if content.count(stripped_old) > 0:
                    old, new = stripped_old, stripped_new
                    old_count = content.count(old)
                    result_extra = {"line_numbers_stripped": True}

        if occurrence < 0:
            return {"ok": False, "error": "occurrence 不能为负数"}
        if occurrence > 0 and replace_all:
            return {
                "ok": False,
                "error": "occurrence 与 replace_all 不能同时使用，请只选其一",
                "proposal": "多匹配时要么用 occurrence=N 指定单次替换，要么用 replace_all=True 替换全部",
                "options": ["occurrence=N", "replace_all=True"],
            }

        if old_count == 0:
            # P0-1: whitespace-tolerant fallback before giving up
            aligned = _align_whitespace(content, old, new, align_whitespace)
            if aligned:
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
                **result_extra,
            }

        # 2. 执行替换前先校验 occurrence
        if occurrence > 0 and not replace_all:
            if occurrence > old_count:
                return {"ok": False, "error": f"occurrence={occurrence} 超过匹配总数 {old_count}"}

    # 行号寻址模式：越界校验放在备份之前，避免为失败操作创建无意义备份
    if mode == "insert_at_line":
        total_lines = len(content.splitlines())
        if line < 0 or line > total_lines:
            return {
                "ok": False,
                "error": f"line={line} 越界，文件共 {total_lines} 行（insert_at_line 要求 0 ≤ line ≤ 总行数，0 表示文件开头）",
                "total_lines": total_lines,
                "next_call": {"tool": "safe_read", "params": {"path": filepath}},
            }
    elif mode == "delete_lines":
        total_lines = len(content.splitlines())
        if start_line < 1 or end_line < start_line or end_line > total_lines:
            return {
                "ok": False,
                "error": (
                    f"行号越界：start_line={start_line}, end_line={end_line}，文件共 {total_lines} 行"
                    "（delete_lines 要求 1 ≤ start_line ≤ end_line ≤ 总行数）"
                ),
                "total_lines": total_lines,
                "next_call": {"tool": "safe_read", "params": {"path": filepath}},
            }

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
    backup_path = backup_root / f"{backup_name_stem(p)}.{ts}.bak"
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

    # 2. 执行编辑
    if mode == "insert_at_line":
        insert_text = new if new.endswith("\n") else new + "\n"
        if line == 0:
            new_content = insert_text + content
        else:
            parts = content.split("\n")
            new_content = "\n".join(parts[:line]) + "\n" + insert_text + "\n".join(parts[line:])
        if has_crlf:
            new_content = _restore_line_endings(new_content, has_crlf)
        try:
            # 行号寻址模式保留原文件编码与换行风格
            atomic_write_text(filepath, new_content, encoding)
        except (OSError, UnicodeError) as e:
            return {"ok": False, "error": f"无法写入文件：{e}"}
        result["inserted_after_line"] = line
    elif mode == "delete_lines":
        parts = content.split("\n")
        del parts[start_line - 1 : end_line]
        new_content = "\n".join(parts)
        if has_crlf:
            new_content = _restore_line_endings(new_content, has_crlf)
        try:
            atomic_write_text(filepath, new_content, encoding)
        except (OSError, UnicodeError) as e:
            return {"ok": False, "error": f"无法写入文件：{e}"}
        result["deleted_lines"] = [start_line, end_line]
    elif occurrence > 0 and not replace_all:
        positions = _collect_positions(content, old)
        idx = positions[occurrence - 1]
        new_content = content[:idx] + new + content[idx + len(old) :]
        if has_crlf:
            new_content = _restore_line_endings(new_content, has_crlf)
        try:
            # 统一用 UTF-8 写入，与 file_patch.patch 路径一致：
            # 避免 GBK 等旧编码文件写入含 emoji 等 new 文本时 UnicodeEncodeError。
            atomic_write_text(filepath, new_content, "utf-8")
        except (OSError, UnicodeError) as e:
            return {"ok": False, "error": f"无法写入文件：{e}"}
        result["replaced"] = 1
        result["occurrence"] = occurrence
    else:
        patch_result = patch(filepath, old, new, replace_all, align_whitespace)
        if not patch_result.get("ok"):
            # P7: patch 失败且文件未被修改——刚创建的备份没有保留价值，直接清理，避免备份堆积
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                **result,
                "ok": False,
                "error": patch_result.get("error", "patch 失败"),
                "rolled_back": False,
                "backup_deleted": True,
                "proposal": "文件未被修改，临时备份已清理。修正 old/new 参数后重试 safe_edit。",
                "options": [
                    {
                        "tool": "safe_edit",
                        "params": {
                            "filepath": filepath,
                            "old": old,
                            "new": new,
                            "replace_all": replace_all,
                            "occurrence": occurrence,
                        },
                    }
                ],
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
                except (OSError, UnicodeError) as e:
                    return {
                        **result,
                        "ok": False,
                        "rolled_back": False,
                        "error": f"语法检查失败且回滚失败: {e}",
                        "proposal": f"文件已被修改，备份在 {backup_path}，请手动恢复",
                        "options": [
                            {"tool": "safe_rollback", "params": {"filepath": filepath, "backup_name": backup_path.name}},
                            {"tool": "file_diff", "params": {"file_a": str(backup_path), "file_b": filepath}},
                        ],
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
                    "options": [
                        {
                            "tool": "safe_edit",
                            "params": {
                                "filepath": filepath,
                                "old": old,
                                "new": new,
                                "replace_all": replace_all,
                                "occurrence": occurrence,
                            },
                        },
                        {"tool": "file_diff", "params": {"file_a": str(backup_path), "file_b": filepath}},
                        {"tool": "safe_rollback", "params": {"filepath": filepath, "backup_name": backup_path.name}},
                    ],
                }
        else:
            result["syntax_ok"] = True
    else:
        result["syntax_ok"] = None
        result["syntax_check"] = {"note": "非代码文件，跳过语法检查"}

    # P1: 惰性清理备份目录（防御性，异常静默吞掉，绝不影响编辑主流程）
    prune_backups(str(backup_root))
    result["ok"] = True
    return result


def list_backups(filepath: str | None = None) -> dict:
    """列出备份文件。"""
    backup_root = _backup_dir()
    backup_root.mkdir(parents=True, exist_ok=True)
    backups = []
    for b in sorted(backup_root.glob("*.bak"), reverse=True):
        stat = b.stat()
        backups.append(
            {
                "file": b.name,
                "size": stat.st_size,
                "time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    if filepath:
        prefix = f"{backup_name_stem(Path(filepath))}."
        backups = [b for b in backups if b["file"].startswith(prefix)]

    return {"ok": True, "backups": backups[:20], "total": len(backups)}


def rollback(filepath: str, backup_name: str | None = None) -> dict:
    """
    回滚文件到指定备份。不指定则回滚到最近的备份。
    """
    safety = check_path_allowed(filepath)
    if safety:
        return safety

    p = Path(filepath).resolve()
    filepath = str(p)

    if not p.exists():
        return {"ok": False, "error": f"目标文件不存在: {filepath}"}

    backup_root = _backup_dir()

    if backup_name:
        backup_path = backup_root / Path(backup_name).name  # 只取文件名防路径穿越
        if not backup_path.exists():
            return {"ok": False, "error": f"备份不存在: {backup_name}"}
    else:
        # 找最近的备份
        pattern = f"{backup_name_stem(p)}.*.bak"
        candidates = sorted(backup_root.glob(pattern), reverse=True)
        if not candidates:
            return {"ok": False, "error": f"没有找到 {p.name} 的备份"}
        backup_path = candidates[0]

    try:
        # 回滚前先把当前状态备份一次，使回滚可撤销（防止回滚错无法恢复）。
        cur_ts = datetime.now().strftime("%Y%m%d%H%M%S")
        pre_rollback_backup = backup_root / f"{backup_name_stem(p)}.{cur_ts}.prerollback.bak"
        shutil.copy2(filepath, str(pre_rollback_backup))
    except (OSError, UnicodeError) as e:
        return {"ok": False, "error": f"回滚前备份当前状态失败: {e}", "proposal": "请先确认目标文件可写"}

    try:
        shutil.copy2(str(backup_path), filepath)
    except (OSError, UnicodeError) as e:
        return {"ok": False, "error": f"回滚失败: {e}", "proposal": f"备份在 {backup_path}，请手动复制恢复"}
    return {
        "ok": True,
        "file": filepath,
        "restored_from": str(backup_path),
        "current_state_backup": str(pre_rollback_backup),
        "note": "回滚前的当前状态已备份，可再次 rollback 撤销本次回滚",
    }
