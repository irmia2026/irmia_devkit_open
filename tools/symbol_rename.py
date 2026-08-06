"""
symbol_rename - conservative Python token rename backed by codegraph.
"""

from __future__ import annotations

import difflib
import io
import keyword
import re
import sqlite3
import tokenize
from pathlib import Path

from ._file_utils import read_file_with_encoding
from .multi_edit import run as multi_edit_run
from ._helpers import proposal_reply


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _db_path(project_dir: str) -> Path:
    return Path(project_dir).resolve() / ".codegraph" / "codegraph.db"


def _validate_names(old: str, new: str) -> tuple[str, str]:
    old_short = old.rsplit(".", 1)[-1]
    new_short = new.rsplit(".", 1)[-1]
    if not _IDENT_RE.match(old_short):
        raise ValueError(f"old is not a valid Python identifier: {old}")
    if not _IDENT_RE.match(new_short) or keyword.iskeyword(new_short):
        raise ValueError(f"new is not a valid Python identifier: {new}")
    return old_short, new_short


def _connect_index(project_dir: str) -> sqlite3.Connection:
    db = _db_path(project_dir)
    if not db.exists():
        raise ValueError("codegraph index not found; run code_index first")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
    if not row:
        conn.close()
        raise ValueError("codegraph index is empty; run code_index first")
    return conn


def _symbol_rows(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    short = name.rsplit(".", 1)[-1]
    return conn.execute(
        "SELECT name, kind, file, line FROM symbols WHERE name=? OR name LIKE ? ORDER BY file, line",
        (name, f"%.{short}"),
    ).fetchall()


def _indexed_python_files(conn: sqlite3.Connection, project_dir: str, old: str) -> list[Path]:
    rows = conn.execute(
        "SELECT DISTINCT file FROM symbols WHERE file LIKE '%.py' "
        "UNION SELECT DISTINCT file FROM edges WHERE file LIKE '%.py'"
    ).fetchall()
    root = Path(project_dir).resolve()
    files = []
    for row in rows:
        p = (root / row[0]).resolve()
        if p.exists() and p.is_file():
            files.append(p)
    return sorted(set(files))


def _line_offsets(content: str) -> list[int]:
    offsets = [0]
    total = 0
    for line in content.splitlines(keepends=True):
        total += len(line)
        offsets.append(total)
    return offsets


def _absolute(offsets: list[int], pos: tuple[int, int]) -> int:
    line, col = pos
    if line - 1 >= len(offsets):
        return offsets[-1]
    return offsets[line - 1] + col


def _rename_content(content: str, old: str, new: str) -> tuple[str, list[dict]]:
    offsets = _line_offsets(content)
    replacements: list[tuple[int, int, tokenize.TokenInfo]] = []
    reader = io.StringIO(content).readline
    for tok in tokenize.generate_tokens(reader):
        if tok.type == tokenize.NAME and tok.string == old:
            start = _absolute(offsets, tok.start)
            end = _absolute(offsets, tok.end)
            replacements.append((start, end, tok))
    if not replacements:
        return content, []
    pieces = []
    last = 0
    refs = []
    for start, end, tok in replacements:
        pieces.append(content[last:start])
        pieces.append(new)
        last = end
        refs.append({
            "line": tok.start[0],
            "col": tok.start[1] + 1,
            "context": tok.line.strip()[:160],
        })
    pieces.append(content[last:])
    return "".join(pieces), refs


def _preview_diff(path: Path, old_content: str, new_content: str) -> str:
    return "\n".join(difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        fromfile=str(path),
        tofile=str(path) + " (renamed)",
        lineterm="",
    ))


def run(old: str, new: str, project_dir: str = ".", dry_run: bool = True, confirm_multi_file: bool = False) -> dict:
    try:
        old_short, new_short = _validate_names(old, new)
        conn = _connect_index(project_dir)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        old_rows = _symbol_rows(conn, old)
        if not old_rows:
            return {"ok": False, "error": f"target symbol not found in codegraph: {old}"}
        conflicts = _symbol_rows(conn, new)
        if conflicts:
            return {
                "ok": False,
                "error": f"naming conflict: {new} already exists",
                "conflicts": [dict(row) for row in conflicts[:20]],
            }
        files = _indexed_python_files(conn, project_dir, old_short)
        row = conn.execute("SELECT value FROM meta WHERE key='last_index'").fetchone()
        last_index = float(row[0]) if row else 0.0
    finally:
        conn.close()

    # 索引新鲜度检查：索引后被修改的文件可能让冲突检测不完整
    stale = 0
    for path in files:
        try:
            if path.stat().st_mtime > last_index:
                stale += 1
        except OSError:
            pass
    stale_warning = ""
    if stale:
        stale_warning = (
            f"{stale} 个文件在索引后被修改，冲突检测可能不完整，"
            "建议先 code_index(incremental=true)"
        )

    refs = []
    edits = []
    diffs = []
    for path in files:
        try:
            content, _encoding = read_file_with_encoding(path)
        except Exception:
            continue
        new_content, file_refs = _rename_content(content, old_short, new_short)
        if not file_refs:
            continue
        for ref in file_refs:
            refs.append({"file": str(path), **ref})
        edits.append({"file": str(path), "old": content, "new": new_content})
        if len(diffs) < 10:
            diffs.append({"file": str(path), "diff": _preview_diff(path, content, new_content)})

    if not refs:
        return {
            "ok": False,
            "error": f"symbol {old_short} exists in codegraph but no Python NAME tokens were found",
            "indexed_symbols": [dict(row) for row in old_rows[:20]],
        }

    result = {
        "ok": True,
        "dry_run": bool(dry_run),
        "old": old_short,
        "new": new_short,
        "total_refs": len(refs),
        "files_changed": sorted({r["file"] for r in refs}),
        "references": refs[:100],
        "diffs": diffs,
        "indexed_symbols": [dict(row) for row in old_rows[:20]],
    }
    if stale_warning:
        result["stale_warning"] = stale_warning
    if dry_run:
        return result

    # Safety valve: renaming renames ALL same-named tokens project-wide
    # with no scope disambiguation — require explicit confirmation for multi-file.
    if len(result.get("files_changed", [])) > 1 and not confirm_multi_file:
        return proposal_reply(
            False,
            f"symbol_rename would rename {old_short}→{new_short} in "
            f"{len(result['files_changed'])} files with no scope disambiguation. "
            f"Review the dry_run diffs first, then retry with confirm_multi_file=true.",
            error="cross_file_rename",
            evidence={"files_changed": result.get("files_changed", []),
                      "files_count": len(result.get("files_changed", [])),
                      "diffs": result.get("diffs", []),
                      "total_refs": result.get("total_refs", 0)},
            options=["dry_run=true to review diffs", "confirm_multi_file=true to proceed", "cancel"],
            **({"stale_warning": stale_warning} if stale_warning else {}),
        )

    applied = multi_edit_run(edits, syntax_check=True)
    if not applied.get("ok"):
        return {
            "ok": False,
            "error": applied.get("error", "multi_edit failed"),
            "preview": result,
            "multi_edit": applied,
        }
    return {
        **result,
        "dry_run": False,
        "renamed": len(refs),
        "multi_edit": applied,
    }
