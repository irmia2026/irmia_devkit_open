"""
safe_read — 增强版安全文件读取工具。

比 AstrBot 原生 file_read 更强大，但边界清晰：
- 只做"安全读取"，不做搜索（搜索交给 rg_search）
- 编码自动检测（chardet + UTF-8/GBK/Latin-1 fallback）
- 二进制文件检测 + hex preview
- 行号范围（start_line / end_line）
- Head / Tail 模式
- 大文件截断（truncate）+ has_more 提示
- 目录读取（递归/非递归）
- 文件元信息（大小、编码、行数、修改时间）
- Skeleton 模式（代码结构提取）

依赖：
- 必需：标准库
- 可选：chardet（编码检测更准确）
- 可选：python-magic（MIME 类型检测）
"""

from __future__ import annotations

import binascii
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._file_utils import (
    detect_encoding,
    human_size,
    is_binary_file,
    SymlinkGuard,
    check_path_allowed,
)


# ── 配置阈值 ──

MAX_FILE_SIZE = 10 * 1024 * 1024       # 10MB：硬拒绝读取内容
LARGE_FILE_THRESHOLD = 100 * 1024         # 100KB：自动截断提示
MAX_LINES_PER_CALL = 200                 # 每次最多返回 200 行
MAX_HEX_BYTES = 1024                     # hex preview 最多 1KB
MAX_HEX_LINES = 64                       # hex preview 最多 64 行
MAX_DIR_ENTRIES = 50                     # 目录读取最大条目数


# ── Hex Preview ──

def _hex_preview(path: str | Path, max_bytes: int = MAX_HEX_BYTES, offset: int = 0) -> str:
    """生成 hex dump（类似 xxd），支持字节偏移。"""
    p = Path(path)
    file_size = p.stat().st_size
    start = min(offset, file_size)
    read_size = min(max_bytes, file_size - start)

    with p.open('rb') as f:
        f.seek(start)
        data = f.read(read_size)

    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        addr = start + i
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        hex_part = hex_part.ljust(48)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f'{addr:08x}: {hex_part}  {ascii_part}')
        if len(lines) >= MAX_HEX_LINES:
            break

    result = '\n'.join(lines)
    remaining = file_size - start - len(data)
    if remaining > 0:
        result += f'\n... ({remaining} more bytes)'
    return result


# ── 文件元信息 ──

def _get_metadata(path: str | Path) -> dict[str, Any]:
    """获取文件元信息。"""
    p = Path(path)
    stat = p.stat()
    return {
        'size': stat.st_size,
        'human_size': human_size(stat.st_size),
        'mtime': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        'ctime': datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        'is_file': p.is_file(),
        'is_dir': p.is_dir(),
        'is_symlink': p.is_symlink(),
        'permissions': oct(stat.st_mode)[-3:],
    }


def _get_mime_type(path: str | Path) -> str:
    """获取文件 MIME 类型。"""
    p = Path(path)
    mime, _ = mimetypes.guess_type(str(p))
    if mime:
        return mime
    
    try:
        import magic
        return magic.from_file(str(p), mime=True)
    except Exception:
        pass
    
    ext = p.suffix.lower()
    mime_map = {
        '.py': 'text/x-python',
        '.js': 'text/javascript',
        '.ts': 'text/typescript',
        '.go': 'text/x-go',
        '.rs': 'text/x-rust',
        '.java': 'text/x-java',
        '.c': 'text/x-c',
        '.cpp': 'text/x-c++',
        '.h': 'text/x-c',
        '.hpp': 'text/x-c++',
        '.nim': 'text/x-nim',
        '.md': 'text/markdown',
        '.json': 'application/json',
        '.yaml': 'text/yaml',
        '.yml': 'text/yaml',
        '.xml': 'text/xml',
        '.sql': 'text/x-sql',
        '.sh': 'text/x-shellscript',
        '.bash': 'text/x-shellscript',
        '.zsh': 'text/x-shellscript',
        '.vim': 'text/x-vim',
        '.el': 'text/x-emacs-lisp',
        '.lisp': 'text/x-common-lisp',
        '.scm': 'text/x-scheme',
        '.rkt': 'text/x-racket',
    }
    return mime_map.get(ext, 'application/octet-stream')


# ── 行号范围读取 ──

def _read_lines_range(
    path: str | Path,
    encoding: str,
    start_line: int = 1,
    end_line: int = 0,
    max_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, int, bool]:
    """读取指定行号范围的内容。
    
    返回：(lines, actual_start, actual_end, total_lines, has_more)
    """
    p = Path(path)
    lines = []
    current_line = 0
    total_lines = 0
    
    start = max(1, start_line)
    end = end_line if end_line > 0 else float('inf')
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            total_lines += 1
            
            if current_line + 1 < start:
                current_line += 1
                continue
            
            if current_line + 1 > end:
                break
            
            lines.append(line.rstrip('\n').rstrip('\r'))
            current_line += 1
            
            if len(lines) >= max_lines:
                # 继续扫描统计总行数
                for _ in f:
                    total_lines += 1
                break
    
    actual_start = start if start <= total_lines else 0
    actual_end = actual_start + len(lines) - 1 if lines else 0
    has_more = actual_end < total_lines
    
    return lines, actual_start, actual_end, total_lines, has_more


def _read_head(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, bool]:
    """读取文件头部 n 行。
    
    返回：(lines, total_lines, has_more)
    """
    p = Path(path)
    lines = []
    total_lines = 0
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            total_lines += 1
            if len(lines) < n_lines:
                lines.append(line.rstrip('\n').rstrip('\r'))
    
    has_more = total_lines > len(lines)
    return lines, total_lines, has_more


def _read_tail(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, bool]:
    """读取文件尾部 n 行。
    
    返回：(lines, total_lines, start_line, has_more)
    """
    from collections import deque
    
    p = Path(path)
    buffer = deque(maxlen=n_lines)
    total_lines = 0
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            total_lines += 1
            buffer.append(line.rstrip('\n').rstrip('\r'))
    
    lines = list(buffer)
    start_line = max(1, total_lines - len(lines) + 1)
    has_more = start_line > 1
    
    return lines, total_lines, start_line, has_more


# ── Skeleton 模式 ──

def _extract_skeleton(path: str | Path, encoding: str) -> dict[str, Any]:
    """提取代码文件的骨架结构（类、函数、导入）。"""
    p = Path(path)
    ext = p.suffix.lower()
    
    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.nim': 'nim',
    }
    language = language_map.get(ext, 'unknown')
    
    imports = []
    classes = []
    functions = []
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        content = f.read()
    
    lines = content.split('\n')
    
    if language == 'python':
        import_pattern = re.compile(r'^(import\s+\S+|from\s+\S+\s+import\s+\S+)')
        class_pattern = re.compile(r'^class\s+(\w+)')
        func_pattern = re.compile(r'^(?:async\s+)?def\s+(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language in ('javascript', 'typescript'):
        import_pattern = re.compile(r'^(import|export)\s+')
        class_pattern = re.compile(r'^class\s+(\w+)')
        func_pattern = re.compile(r'^(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                name = match.group(1) or match.group(2)
                functions.append({'line': i + 1, 'name': name, 'content': line_stripped})
    
    elif language == 'go':
        import_pattern = re.compile(r'^import\s+')
        func_pattern = re.compile(r'^func\s+(?:\([^)]*\)\s+)?(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'rust':
        import_pattern = re.compile(r'^use\s+')
        func_pattern = re.compile(r'^(?:pub\s+)?fn\s+(\w+)')
        struct_pattern = re.compile(r'^(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := struct_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'java':
        import_pattern = re.compile(r'^import\s+')
        class_pattern = re.compile(r'^(?:public\s+|private\s+|protected\s+)?(?:class|interface|enum)\s+(\w+)')
        func_pattern = re.compile(r'^(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    elif language == 'nim':
        import_pattern = re.compile(r'^import\s+')
        func_pattern = re.compile(r'^(?:proc|func|macro|template|iterator|converter)\s+(\w+)')
        type_pattern = re.compile(r'^type\s+')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif type_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': 'type_block', 'content': line_stripped})
    
    else:
        func_pattern = re.compile(r'^(?:def|function|func|fn|proc|method|sub)\s+(\w+)')
        class_pattern = re.compile(r'^class\s+(\w+)')
        import_pattern = re.compile(r'^(import|include|require|using|use|from|#include)\s+')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if import_pattern.match(line_stripped):
                imports.append({'line': i + 1, 'content': line_stripped})
            elif match := class_pattern.match(line_stripped):
                classes.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
            elif match := func_pattern.match(line_stripped):
                functions.append({'line': i + 1, 'name': match.group(1), 'content': line_stripped})
    
    return {
        'language': language,
        'total_lines': len(lines),
        'imports': imports[:50],
        'classes': classes[:50],
        'functions': functions[:50],
        'import_count': len(imports),
        'class_count': len(classes),
        'function_count': len(functions),
    }


# ── 目录读取 ──

def _read_directory(
    path: str | Path,
    recursive: bool = False,
    max_entries: int = MAX_DIR_ENTRIES,
    include_hidden: bool = False,
    max_depth: int = 3,
    current_depth: int = 0,
    guard: SymlinkGuard | None = None,
) -> tuple[list[dict], int, bool]:
    """读取目录内容。"""
    p = Path(path)
    entries = []
    total_entries = 0
    if guard is None:
        guard = SymlinkGuard()

    try:
        items = list(p.iterdir())
    except PermissionError:
        raise PermissionError(f'Permission denied: {path}')
    except OSError as e:
        raise OSError(f'Cannot read directory: {path}: {e}')

    if not include_hidden:
        items = [item for item in items if not item.name.startswith('.')]

    total_entries = len(items)
    items.sort(key=lambda x: (0 if x.is_dir() else 1, x.name.lower()))

    for item in items[:max_entries]:
        # symlink 循环检测
        if guard.is_seen(str(item)):
            continue

        entry = {
            'name': item.name,
            'path': str(item),
            'type': 'directory' if item.is_dir() else 'file',
        }

        if item.is_file():
            stat = item.stat()
            entry['size'] = stat.st_size
            entry['human_size'] = human_size(stat.st_size)
            entry['mtime'] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        if item.is_dir() and recursive and current_depth < max_depth:
            try:
                children, child_total, _ = _read_directory(
                    item,
                    recursive=False,
                    max_entries=10,
                    include_hidden=include_hidden,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    guard=guard,
                )
                entry['children'] = children
                entry['child_count'] = child_total
            except (PermissionError, OSError):
                entry['children'] = []
                entry['child_count'] = 0

        entries.append(entry)

    has_more = len(items) > max_entries
    return entries, total_entries, has_more


# ── 主函数 ──

def read(
    path: str,
    *,
    start_line: int = 0,
    end_line: int = 0,
    max_lines: int = MAX_LINES_PER_CALL,
    offset: int = 0,
    limit_bytes: int = 0,
    encoding: str = 'auto',
    mode: str = 'auto',
    head: int = 0,
    tail: int = 0,
    max_depth: int = 3,
    include_metadata: bool = True,
    recursive: bool = False,
    max_entries: int = MAX_DIR_ENTRIES,
    include_hidden: bool = False,
) -> dict:
    """增强版安全文件读取工具。
    
    Args:
        path: 文件或目录路径
        start_line: 起始行号（1-based，0 表示从头）
        end_line: 结束行号（0 表示到末尾）
        max_lines: 最大返回行数
        offset: 字节偏移（hex 模式）
        limit_bytes: 字节限制（hex 模式）
        encoding: 编码：auto / utf-8 / gbk / latin-1
        mode: 模式：auto / text / binary / hex / skeleton / directory
        head: 读取前 N 行（优先级高于 start_line/end_line）
        tail: 读取后 N 行（优先级高于 start_line/end_line）
        include_metadata: 是否包含文件元信息
        recursive: 目录读取时是否递归
        max_entries: 目录读取时最大条目数
        include_hidden: 是否包含隐藏文件
    """
    # 0. 路径安全校验（与 safe_write/file_remove 同级）
    forbidden = check_path_allowed(path)
    if forbidden:
        return forbidden

    # 1. symlink 控制：不自动跟随 symlink 跳出工作目录/进入系统目录
    #    必须在 resolve() 之前检查，因为 resolve() 会跟随 symlink。
    raw_path = Path(path).expanduser()
    try:
        if raw_path.is_symlink():
            target = os.readlink(raw_path)
            resolved_target = Path(target)
            if not resolved_target.is_absolute():
                resolved_target = (raw_path.parent / resolved_target).resolve()
            forbidden_target = check_path_allowed(resolved_target)
            if forbidden_target:
                return {
                    'ok': False,
                    'error': f'Symlink 指向受保护路径: {resolved_target}',
                    'path': str(raw_path),
                }
    except OSError:
        pass

    p = raw_path.resolve()

    if not p.exists():
        return {
            'ok': False,
            'error': f'Path not found: {path}',
            'path': str(p),
        }
    
    # 目录读取
    if p.is_dir():
        if mode == 'auto' or mode == 'directory':
            try:
                entries, total_entries, has_more = _read_directory(
                    p,
                    recursive=recursive,
                    max_entries=max_entries,
                    include_hidden=include_hidden,
                    max_depth=max_depth,
                )
                
                result = {
                    'ok': True,
                    'path': str(p),
                    'mode': 'directory',
                    'entries': entries,
                    'total_entries': total_entries,
                    'returned_entries': len(entries),
                    'has_more': has_more,
                }
                
                if include_metadata:
                    result['metadata'] = _get_metadata(p)
                
                return result
            except Exception as e:
                return {
                    'ok': False,
                    'error': f'Failed to read directory: {e}',
                    'path': str(p),
                }
        else:
            return {
                'ok': False,
                'error': f'Path is a directory, cannot read as {mode}',
                'path': str(p),
            }
    
    if not p.is_file():
        return {
            'ok': False,
            'error': f'Path is not a file: {path}',
            'path': str(p),
        }
    
    metadata = _get_metadata(p) if include_metadata else {}
    file_size = p.stat().st_size
    
    if file_size > MAX_FILE_SIZE:
        return {
            'ok': False,
            'error': f'File too large ({metadata.get("human_size", file_size)} > {human_size(MAX_FILE_SIZE)}). Use skeleton mode or rg_search.',
            'path': str(p),
            'metadata': metadata,
            'suggested_mode': 'skeleton',
        }
    
    detected_encoding = encoding if encoding != 'auto' else detect_encoding(p)
    is_binary, binary_reason = is_binary_file(p)
    mime_type = _get_mime_type(p)
    
    actual_mode = mode
    if mode == 'auto':
        actual_mode = 'binary' if is_binary else 'text'
    
    if actual_mode == 'binary':
        return {
            'ok': True,
            'path': str(p),
            'mode': 'binary',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'is_binary': True,
            'binary_reason': binary_reason,
            'hex_preview': _hex_preview(p, MAX_HEX_BYTES, offset=offset),
            'metadata': metadata,
            'content': '',
            'truncated': False,
            'truncation_reason': 'Binary file - hex preview only',
        }
    
    if actual_mode == 'hex':
        max_bytes = limit_bytes if limit_bytes > 0 else MAX_HEX_BYTES
        hex_content = _hex_preview(p, max_bytes, offset=offset)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'hex',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'hex_content': hex_content,
            'metadata': metadata,
            'content': '',
            'truncated': file_size > max_bytes,
            'truncation_reason': f'Hex preview limited to {max_bytes} bytes' if file_size > max_bytes else '',
        }
    
    if actual_mode == 'skeleton':
        skeleton = _extract_skeleton(p, detected_encoding)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'skeleton',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'skeleton': skeleton,
            'metadata': metadata,
            'content': '',
            'truncated': False,
        }
    
    # 文本模式
    if head > 0:
        lines, total_lines, has_more = _read_head(p, detected_encoding, head)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'total_lines': total_lines,
            'returned_lines': len(lines),
            'start_line': 1,
            'end_line': len(lines),
            'has_more': has_more,
            'content': '\n'.join(lines),
            'metadata': metadata,
            'truncated': has_more,
            'truncation_reason': f'Showing first {len(lines)} of {total_lines} lines' if has_more else '',
        }
    
    if tail > 0:
        lines, total_lines, start_line, has_more = _read_tail(p, detected_encoding, tail)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', human_size(file_size)),
            'mime_type': mime_type,
            'total_lines': total_lines,
            'returned_lines': len(lines),
            'start_line': start_line,
            'end_line': total_lines,
            'has_more': has_more,
            'content': '\n'.join(lines),
            'metadata': metadata,
            'truncated': has_more,
            'truncation_reason': f'Showing last {len(lines)} of {total_lines} lines' if has_more else '',
        }
    
    # 行号范围模式
    lines, actual_start, actual_end, total_lines, has_more = _read_lines_range(
        p, detected_encoding, start_line, end_line, max_lines
    )
    
    truncated = has_more or (file_size > LARGE_FILE_THRESHOLD)
    truncation_reason = ''
    if truncated:
        if file_size > LARGE_FILE_THRESHOLD:
            hs = metadata.get('human_size', human_size(file_size))
            truncation_reason = f'File is large ({hs}). Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
        else:
            truncation_reason = f'Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
    
    return {
        'ok': True,
        'path': str(p),
        'mode': 'text',
        'encoding': detected_encoding,
        'size': file_size,
        'human_size': metadata.get('human_size', human_size(file_size)),
        'mime_type': mime_type,
        'total_lines': total_lines,
        'returned_lines': len(lines),
        'start_line': actual_start,
        'end_line': actual_end,
        'has_more': has_more,
        'content': '\n'.join(lines),
        'metadata': metadata,
        'truncated': truncated,
        'truncation_reason': truncation_reason,
    }
