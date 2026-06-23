"""
file_remove — 文件/目录删除、移动工具。
自带路径沙箱和批量确认，防误操作。
"""
import os
import shutil
import subprocess
from pathlib import Path

from ._helpers import proposal_reply
from ._file_utils import human_size

_FORBIDDEN_PREFIXES = [
    "C:/Windows/System32", "C:/Windows/SysWOW64",
    "C:/Program Files", "C:/Program Files (x86)",
    "C:/Users/All Users",
    "/bin", "/boot", "/dev", "/etc", "/lib", "/proc", "/root", "/sbin", "/sys", "/usr", "/var",
]



def remove(path: str, confirm: bool = False, max_items: int = 50) -> dict:
    """删除文件或目录，自带沙箱和批量确认。

    Args:
        path: 文件或目录路径
        confirm: 目录删除需显式确认
        max_items: 目录超过此文件数时返回提案不执行
    """
    p = Path(path).resolve()

    raw = str(Path(path))
    if any(part == ".." for part in raw.replace("\\", "/").split("/")):
        return {"ok": False, "error": "路径包含 .. 穿越，已被拒绝"}

    if not p.exists():
        return {"ok": False, "error": f"路径不存在: {path}"}

    path_str = str(p).replace("\\", "/")
    for forbidden in _FORBIDDEN_PREFIXES:
        if path_str.lower().startswith(forbidden.lower() + "/") or path_str.lower() == forbidden.lower():
            return {"ok": False, "error": f"禁止操作系统目录: {path}",
                    "proposal": "路径位于受保护的系统目录中，删除操作已被拦截。",
                    "evidence": {"path": path, "blocked_by": forbidden}}

    if p.is_file():
        try:
            size = p.stat().st_size
            os.remove(p)
            return {"ok": True, "deleted": 1, "freed": human_size(size), "errors": []}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    if p.is_dir():
        if not confirm:
            return proposal_reply(False,
                f"确认删除目录？目录路径: {path}。请设置 confirm=true。",
                error="目录删除需二次确认",
                options=["confirm_delete", "cancel"])

        # 单次遍历：计数 + 累加大小
        file_count = 0
        total_size = 0
        for f in p.rglob("*"):
            if f.is_file():
                file_count += 1
                try:
                    total_size += f.stat().st_size
                except OSError:
                    pass
        if file_count > max_items:
            return proposal_reply(False,
                f"目录含 {file_count} 个文件，超过上限 {max_items}。确认删除？",
                error=f"目录含 {file_count} 个文件，超过批量限制 ({max_items})",
                evidence={"file_count": file_count, "directory": str(p)},
                options=["confirm_batch_delete", "cancel"])

        errors = []

        try:
            for root, dirs, files in os.walk(p, topdown=False):
                for name in files:
                    fp = os.path.join(root, name)
                    try:
                        os.remove(fp)
                    except OSError as e:
                        errors.append({"path": fp, "reason": str(e)})
                for name in dirs:
                    dp = os.path.join(root, name)
                    try:
                        os.rmdir(dp)
                    except OSError as e:
                        errors.append({"path": dp, "reason": str(e)})
            try:
                os.rmdir(p)
            except OSError as e:
                errors.append({"path": str(p), "reason": str(e)})

            return {
                "ok": True,
                "deleted": file_count - len(errors),
                "freed": human_size(total_size),
                "errors": errors[:10],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": f"不是文件也不是目录: {path}"}


def _check_path(path: str) -> dict | None:
    """统一路径安全校验，供 remove / move 共用。"""
    raw = str(Path(path))
    if any(part == ".." for part in raw.replace("\\", "/").split("/")):
        return {"ok": False, "error": "路径包含 .. 穿越，已被拒绝"}
    p = Path(path).resolve()
    path_str = str(p).replace("\\", "/")
    for forbidden in _FORBIDDEN_PREFIXES:
        if path_str.lower().startswith(forbidden.lower() + "/") or path_str.lower() == forbidden.lower():
            return {"ok": False, "error": f"禁止操作系统目录: {p}",
                    "proposal": "路径位于受保护的系统目录中，操作已被拦截。",
                    "evidence": {"path": str(p), "blocked_by": forbidden}}
    return None


def _find_fast_copy() -> str | None:
    """查找 robocopy (Windows) 或 rsync (Linux)，返回可执行路径。"""
    for name in ("robocopy", "rsync"):
        path = shutil.which(name)
        if path:
            return name
    return None


def _cross_partition_move(sources_resolved: list, dest_str: str) -> tuple[int, list]:
    """跨分区批量移动：优先 robocopy/rsync 多线程拷贝，回退 shutil.move。"""
    tool = _find_fast_copy()
    if not tool:
        # 无专用工具，循环 shutil.move（跨分区逐文件 copy+delete）
        moved = 0
        errors = []
        for src_str, name in sources_resolved:
            target = f"{dest_str}/{name}"
            try:
                shutil.move(src_str, target)
                moved += 1
            except OSError as e:
                errors.append({"source": src_str, "error": str(e)})
        return moved, errors

    # 分离文件与目录，按父目录分组
    file_groups: dict[str, list[tuple[str, str]]] = {}
    dir_sources: list[tuple[str, str]] = []
    for src_str, name in sources_resolved:
        if os.path.isdir(src_str):
            dir_sources.append((src_str, name))
        else:
            parent = os.path.dirname(src_str)
            if parent not in file_groups:
                file_groups[parent] = []
            file_groups[parent].append((src_str, name))

    moved = 0
    errors = []
    timeout = 120  # 跨分区拷贝可能很慢，给 2 分钟

    # 目录：robocopy /E /MOV 或 rsync -a --remove-source-files
    for src_str, name in dir_sources:
        target = f"{dest_str}/{name}"
        try:
            if tool == "robocopy":
                cp = subprocess.run(
                    ["robocopy", src_str, target, "/E", "/MOV", "/MT:8", "/R:2", "/W:1", "/NP", "/NFL", "/NDL"],
                    capture_output=True, text=True, timeout=timeout,
                )
                if cp.returncode >= 8:
                    errors.append({"source": src_str, "error": f"robocopy exit {cp.returncode}"})
                else:
                    moved += 1
            else:
                cp = subprocess.run(
                    ["rsync", "-a", "--remove-source-files", f"{src_str}/", f"{target}/"],
                    capture_output=True, text=True, timeout=timeout,
                )
                if cp.returncode != 0:
                    errors.append({"source": src_str, "error": cp.stderr.strip()[:200]})
                else:
                    moved += 1
        except subprocess.TimeoutExpired:
            errors.append({"source": src_str, "error": "超时"})
        except Exception as e:
            errors.append({"source": src_str, "error": str(e)})

    # 文件：按父目录批量调用 robocopy/rsync
    for parent, items in file_groups.items():
        try:
            dest_sub = dest_str
            names = [name for _, name in items]
            if tool == "robocopy":
                # robocopy 不支持 --files-from，对大量文件分批 500 一组
                for batch_start in range(0, len(names), 500):
                    batch_names = names[batch_start:batch_start + 500]
                    cp = subprocess.run(
                        ["robocopy", parent, dest_sub] + batch_names + ["/MOV", "/MT:8", "/R:2", "/W:1", "/NP", "/NFL", "/NDL"],
                        capture_output=True, text=True, timeout=timeout,
                    )
                    if cp.returncode >= 8:
                        errors.append({"source": parent, "error": f"robocopy exit {cp.returncode}"})
                    else:
                        moved += len(batch_names)
            else:
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".lst", delete=False, encoding="utf-8") as tmp:
                    tmp.write("\n".join(names))
                    tmp_path = tmp.name
                try:
                    cp = subprocess.run(
                        ["rsync", "-a", "--remove-source-files", f"--files-from={tmp_path}", f"{parent}/", f"{dest_sub}/"],
                        capture_output=True, text=True, timeout=timeout,
                    )
                    if cp.returncode != 0:
                        errors.append({"source": parent, "error": cp.stderr.strip()[:200]})
                    else:
                        moved += len(names)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except subprocess.TimeoutExpired:
            errors.append({"source": parent, "error": "超时"})
        except Exception as e:
            errors.append({"source": parent, "error": str(e)})

    return moved, errors


def move(sources: list, dest: str, overwrite: bool = False) -> dict:
    """批量移动文件/目录到目标目录。

    同分区内使用原子 rename（O(1)），跨分区自动退化为 copy+delete。
    避免 agent 通过 shell_exec 逐文件 mv 导致超时。

    Args:
        sources: 源文件/目录路径列表
        dest: 目标目录路径（会自动创建）
        overwrite: 是否覆盖目标已存在的文件

    Returns:
        {"ok": true, "moved": N, "total_requested": N, "destination": "...", "errors": [...]}
    """
    if not isinstance(sources, list) or not sources:
        return {"ok": False, "error": "sources 必须是非空列表"}

    # 目录快捷提示：移动整个目录用 shutil.move（同分区 O(1) rename），
    # 比逐个传文件路径快几个数量级。不阻塞，仅在结果中附带 hint。
    move_hint = ""
    if len(sources) > 1000:
        # 采样前 100 个判断是否共父目录，不 resolve 全部（省 5000+ 次 stat）
        sample = sources[:100]
        dirs = {str(Path(s).parent.resolve()) for s in sample if isinstance(s, (str, os.PathLike))}
        if len(dirs) == 1:
            move_hint = (
                f"检测到 {len(sources)} 个源文件都在同一目录下。"
                f"下次可直接移动该目录（同分区内原子 rename，瞬间完成）："
                f"move([\"{next(iter(dirs))}\"], dest)"
            )
    if not dest or not isinstance(dest, (str, os.PathLike)):
        return {"ok": False, "error": "dest 不能为空"}

    # 目标路径安全
    dest_err = _check_path(str(dest))
    if dest_err:
        return dest_err

    dest_path = Path(dest).resolve()
    if dest_path.exists() and not dest_path.is_dir():
        return {"ok": False, "error": f"目标路径不是目录: {dest}"}

    # 源路径逐个校验
    sources_resolved = []
    errors = []
    # 硬上限防止 OOM（6 万 Path 对象 ≈ 60MB，50K 是安全上限）
    if len(sources) > 50_000:
        return proposal_reply(
            False,
            f"sources 列表过长 ({len(sources)} > 50000)，可能触发内存/超时问题。"
            "如果这些文件在同一目录下，请直接移动该目录。",
            error="sources_list_too_long",
            evidence={"count": len(sources), "max": 50000},
            options=["移动父目录", "分批移动"],
        )
    for i, src in enumerate(sources):
        if not isinstance(src, (str, os.PathLike)):
            return {"ok": False, "error": f"sources[{i}] 必须是字符串路径"}
        src_str = str(src)
        err = _check_path(src_str)
        if err:
            return err
        src_path = Path(src_str).resolve()
        if not src_path.exists():
            errors.append({"source": src_str, "error": "源路径不存在"})
            continue
        # 预存 (src_str, name) 对，避免循环内重复 Path→str 转换
        sources_resolved.append((str(src_path), src_path.name))

    if not sources_resolved:
        return {"ok": False, "error": "没有可移动的有效源路径", "errors": errors}

    try:
        dest_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"无法创建目标目录: {e}"}

    # 跨分区检测：取第一个源的设备 ID 与目标比较
    cross_partition = False
    try:
        src_dev = os.stat(sources_resolved[0][0]).st_dev
        dst_dev = os.stat(str(dest_path)).st_dev
        cross_partition = src_dev != dst_dev
    except OSError:
        pass

    dest_str = str(dest_path)
    # 一次 listdir 代替 N 次 os.path.exists（N 可达数万时差异显著）
    dest_contents = set(os.listdir(dest_str)) if os.path.isdir(dest_str) else set()

    # overwrite=False 时过滤掉目标已存在的文件（两路径统一检查）
    if not overwrite and dest_contents:
        filtered = []
        for src_str, name in sources_resolved:
            if name in dest_contents:
                errors.append({"source": src_str, "error": f"目标已存在: {dest_str}/{name}"})
            else:
                filtered.append((src_str, name))
        sources_resolved = filtered

    if not sources_resolved:
        return {"ok": True, "moved": 0, "total_requested": len(sources),
                "destination": str(dest_path), "errors": errors[:20]}

    if cross_partition:
        # 跨分区：robocopy/rsync 多线程拷贝（10-50x 快于 Python 循环）
        moved, move_errors = _cross_partition_move(sources_resolved, dest_str)
        errors.extend(move_errors)
    else:
        moved = 0
        for src_str, name in sources_resolved:
            target = f"{dest_str}/{name}"
            try:
                try:
                    os.rename(src_str, target)
                except OSError:
                    shutil.move(src_str, target)
                moved += 1
                dest_contents.add(name)
            except OSError as e:
                errors.append({"source": src_str, "error": str(e)})

    result = {
        "ok": True,
        "moved": moved,
        "total_requested": len(sources),
        "destination": str(dest_path),
        "errors": errors[:20],
    }
    if cross_partition:
        result["cross_partition"] = True
        tool = _find_fast_copy()
        if tool:
            result["engine"] = tool
            result["hint"] = f"跨分区移动，使用 {tool} 多线程拷贝完成。"
        else:
            result["hint"] = (
                "跨分区移动，未找到 robocopy/rsync，使用 Python shutil.move 逐文件拷贝（较慢）。"
            )
    elif move_hint:
        result["hint"] = move_hint
    return result
