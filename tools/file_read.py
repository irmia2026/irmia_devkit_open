"""
file_read — 增强版文件读取工具。

比 AstrBot 原生 file_read 更强大：
- 编码自动检测（chardet + UTF-8/GBK/Latin-1 fallback）
- 二进制文件检测 + hex preview
- 行号范围（start_line / end_line）
- Head / Tail 模式
- 大文件截断（truncate）+ has_more 提示
- 目录读取（递归/非递归）
- 文件元信息（大小、编码、行数、修改时间）
- 搜索过滤（grep_pattern + context_lines）
- Skeleton 模式（代码结构提取）

依赖：
- 必需：标准库（pathlib, os, re, mimetypes, binascii, struct, json, datetime）
- 可选：chardet（编码检测更准确）
- 可选：python-magic（MIME 类型检测）
- 可选：tree-sitter（skeleton 模式代码结构提取）
"""

from __future__ import annotations

import binascii
import json
import mimetypes
import os
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── 配置阈值 ──

MAX_FILE_SIZE = 10 * 1024 * 1024       # 10MB：硬拒绝读取内容
LARGE_FILE_THRESHOLD = 100 * 1024         # 100KB：自动截断提示
MAX_LINES_PER_CALL = 200                 # 每次最多返回 200 行
MAX_BYTES_PER_CALL = 50 * 1024           # 每次最多 50KB
MAX_HEX_BYTES = 1024                     # hex preview 最多 1KB
MAX_HEX_LINES = 64                       # hex preview 最多 64 行
GREP_TIMEOUT = 5.0                       # 正则搜索超时（秒）


# ── 编码检测 ──

# 二进制文件扩展名黑名单
_BINARY_EXTENSIONS = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.svg',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.db', '.sqlite', '.sqlite3',
})

# 文本文件扩展名白名单（即使内容像二进制也强制按文本）
_TEXT_EXTENSIONS = frozenset({
    '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
    '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.clj',
    '.html', '.htm', '.css', '.scss', '.less', '.xml', '.json', '.yaml', '.yml',
    '.md', '.txt', '.rst', '.log', '.ini', '.cfg', '.conf', '.sh', '.bash', '.zsh',
    '.sql', '.vim', '.emacs', '.el', '.lisp', '.scm', '.rkt',
    '.nim', '.nims', '.nimble',
})


def _has_chardet() -> bool:
    """检查是否安装了 chardet。"""
    try:
        import chardet
        return True
    except ImportError:
        return False


def _detect_encoding(path: str | Path) -> str:
    """检测文件编码。
    
    优先级：
    1. chardet（如果安装）
    2. UTF-8 BOM 检测
    3. UTF-8 尝试
    4. GBK 尝试（中文环境）
    5. Latin-1 无损 fallback（保证不抛异常）
    """
    p = Path(path)
    
    # 读取样本（前 32KB）
    sample_size = min(32 * 1024, p.stat().st_size)
    with p.open('rb') as f:
        raw = f.read(sample_size)
    
    # 1. UTF-8 BOM 检测
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    
    # 2. chardet 检测
    if _has_chardet():
        import chardet
        result = chardet.detect(raw)
        if result and result['confidence'] > 0.7:
            detected = result['encoding']
            if detected:
                # 验证检测结果
                try:
                    raw.decode(detected)
                    return detected
                except (UnicodeDecodeError, LookupError):
                    pass
    
    # 3. UTF-8 尝试
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass
    
    # 4. GBK 尝试（中文环境）
    try:
        raw.decode('gbk')
        return 'gbk'
    except UnicodeDecodeError:
        pass
    
    # 5. Latin-1 无损 fallback（ISO-8859-1，每个字节都有定义）
    return 'latin-1'


# ── 二进制检测 ──

def _is_binary_file(path: str | Path, sample_size: int = 8192) -> tuple[bool, str]:
    """检测文件是否为二进制文件。
    
    返回：(is_binary, reason)
    reason: 'extension' | 'content' | 'text_extension' | 'unknown'
    """
    p = Path(path)
    ext = p.suffix.lower()
    
    # 1. 扩展名黑名单
    if ext in _BINARY_EXTENSIONS:
        return True, 'extension'
    
    # 2. 扩展名白名单（强制文本）
    if ext in _TEXT_EXTENSIONS:
        return False, 'text_extension'
    
    # 3. 内容检测
    file_size = p.stat().st_size
    if file_size == 0:
        return False, 'unknown'  # 空文件视为文本
    
    read_size = min(sample_size, file_size)
    with p.open('rb') as f:
        chunk = f.read(read_size)
    
    # null 字节比例检测
    null_count = chunk.count(b'\x00')
    if null_count > 0 and len(chunk) > 0:
        null_ratio = null_count / len(chunk)
        if null_ratio > 0.3:  # 30% 以上 null 字节视为二进制
            return True, 'content'
    
    # 控制字符比例检测（除常见空白和换行外）
    control_chars = sum(1 for b in chunk if b < 32 and b not in (9, 10, 13))
    if len(chunk) > 0:
        control_ratio = control_chars / len(chunk)
        if control_ratio > 0.1:  # 10% 以上控制字符视为二进制
            return True, 'content'
    
    return False, 'unknown'


def _get_mime_type(path: str | Path) -> str:
    """获取文件 MIME 类型。"""
    p = Path(path)
    mime, _ = mimetypes.guess_type(str(p))
    if mime:
        return mime
    
    # 尝试 python-magic（如果安装）
    try:
        import magic
        return magic.from_file(str(p), mime=True)
    except Exception:
        pass
    
    # 基于扩展名的 fallback
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


# ── Hex Preview ──

def _hex_preview(path: str | Path, max_bytes: int = MAX_HEX_BYTES) -> str:
    """生成 hex dump（类似 xxd）。
    
    格式：
    00000000: 8950 4e47 0d0a 1a0a 0000 000d 4948 4452  .PNG........IHDR
    """
    p = Path(path)
    file_size = p.stat().st_size
    read_size = min(max_bytes, file_size)
    
    with p.open('rb') as f:
        data = f.read(read_size)
    
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        hex_part = hex_part.ljust(48)  # 对齐
        
        # ASCII 可打印字符
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        
        lines.append(f'{i:08x}: {hex_part}  {ascii_part}')
        
        if len(lines) >= MAX_HEX_LINES:
            break
    
    result = '\n'.join(lines)
    if file_size > read_size:
        result += f'\n... ({file_size - read_size} more bytes)'
    
    return result


# ── 文件元信息 ──

def _get_metadata(path: str | Path) -> dict[str, Any]:
    """获取文件元信息。"""
    p = Path(path)
    stat = p.stat()
    
    return {
        'size': stat.st_size,
        'human_size': _human_size(stat.st_size),
        'mtime': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        'ctime': datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        'is_file': p.is_file(),
        'is_dir': p.is_dir(),
        'is_symlink': p.is_symlink(),
        'permissions': oct(stat.st_mode)[-3:],
    }


def _human_size(n: int) -> str:
    """字节数 → 人类可读大小。"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024:
            s = f'{n:.1f}{unit}'
            return s.replace('.0', '') if '.0' in s else s
        n /= 1024
    return f'{n:.1f}PB'


# ── 行号索引 ──

def _count_lines(path: str | Path, encoding: str) -> int:
    """计算文件总行数。"""
    p = Path(path)
    count = 0
    with p.open('r', encoding=encoding, errors='replace') as f:
        for _ in f:
            count += 1
    return count


def _read_lines_range(
    path: str | Path,
    encoding: str,
    start_line: int = 1,
    end_line: int = 0,
    max_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, bool]:
    """读取指定行号范围的内容。
    
    返回：(lines, actual_start, actual_end, has_more)
    """
    p = Path(path)
    lines = []
    current_line = 0
    
    # 参数校验
    start = max(1, start_line)
    end = end_line if end_line > 0 else float('inf')
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            current_line += 1
            
            if current_line < start:
                continue
            
            if current_line > end:
                break
            
            lines.append(line.rstrip('\n').rstrip('\r'))
            
            if len(lines) >= max_lines:
                break
    
    actual_start = start if start <= current_line else 0
    actual_end = actual_start + len(lines) - 1 if lines else 0
    # has_more：如果因为 max_lines 限制而停止，且文件还有更多行
    has_more = current_line > end or (len(lines) >= max_lines and current_line > actual_end)
    # 修正：如果文件总行数超过读取的行数，也有更多内容
    if not has_more and len(lines) > 0:
        # 继续读取检查是否还有更多行
        with p.open('r', encoding=encoding, errors='replace') as f:
            total = sum(1 for _ in f)
        has_more = total > actual_end
    
    return lines, actual_start, actual_end, has_more


def _read_head(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, bool]:
    """读取文件头部 n 行。
    
    返回：(lines, total_read, has_more)
    """
    p = Path(path)
    lines = []
    total_read = 0
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            total_read += 1
            if len(lines) < n_lines:
                lines.append(line.rstrip('\n').rstrip('\r'))
    
    has_more = total_read > len(lines)
    return lines, total_read, has_more


def _read_tail(
    path: str | Path,
    encoding: str,
    n_lines: int = MAX_LINES_PER_CALL,
) -> tuple[list[str], int, int, bool]:
    """读取文件尾部 n 行。
    
    返回：(lines, total_lines, start_line, has_more)
    """
    p = Path(path)
    
    # 先统计总行数（对于大文件可能较慢，但 tail 通常用于日志）
    # 优化：使用 deque 保持最后 N 行
    from collections import deque
    
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


# ── Grep 过滤 ──

def _grep_lines(
    path: str | Path,
    encoding: str,
    pattern: str,
    context_lines: int = 0,
    max_matches: int = MAX_LINES_PER_CALL,
) -> tuple[list[dict], int, bool]:
    """在文件中搜索匹配行。
    
    返回：(matches, total_matches, has_more)
    match: {line, content, context_before, context_after}
    """
    p = Path(path)
    
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f'Invalid regex pattern: {e}')
    
    # 读取所有行（带上下文缓存）
    all_lines = []
    matches = []
    
    with p.open('r', encoding=encoding, errors='replace') as f:
        for line in f:
            all_lines.append(line.rstrip('\n').rstrip('\r'))
    
    total_lines = len(all_lines)
    
    for i, line in enumerate(all_lines):
        if regex.search(line):
            match = {
                'line': i + 1,
                'content': line,
            }
            
            if context_lines > 0:
                start = max(0, i - context_lines)
                end = min(total_lines, i + context_lines + 1)
                match['context_before'] = all_lines[start:i]
                match['context_after'] = all_lines[i+1:end]
            
            matches.append(match)
            
            if len(matches) >= max_matches:
                break
    
    has_more = len(matches) >= max_matches and any(
        regex.search(all_lines[j]) for j in range(len(matches), total_lines)
    )
    
    return matches, len(matches), has_more


# ── Skeleton 模式 ──

def _extract_skeleton(path: str | Path, encoding: str) -> dict[str, Any]:
    """提取代码文件的骨架结构（类、函数、导入）。
    
    使用正则提取，不依赖 tree-sitter（零依赖）。
    """
    p = Path(path)
    ext = p.suffix.lower()
    
    # 语言检测
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
        # 导入语句
        import_pattern = re.compile(r'^(import\s+\S+|from\s+\S+\s+import\s+\S+)')
        # 类定义
        class_pattern = re.compile(r'^class\s+(\w+)')
        # 函数/方法定义
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
        # 通用模式：尝试识别函数/类定义
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
        'imports': imports[:50],  # 限制数量
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
    max_entries: int = 50,
    include_hidden: bool = False,
) -> tuple[list[dict], int, bool]:
    """读取目录内容。
    
    返回：(entries, total_entries, has_more)
    entry: {name, type, size, mtime, permissions, [children]}
    """
    p = Path(path)
    entries = []
    total_entries = 0
    
    try:
        items = list(p.iterdir())
    except PermissionError:
        raise PermissionError(f'Permission denied: {path}')
    except OSError as e:
        raise OSError(f'Cannot read directory: {path}: {e}')
    
    # 过滤隐藏文件
    if not include_hidden:
        items = [item for item in items if not item.name.startswith('.')]
    
    total_entries = len(items)
    
    # 排序：目录在前，文件在后，按名称排序
    items.sort(key=lambda x: (0 if x.is_dir() else 1, x.name.lower()))
    
    for item in items[:max_entries]:
        entry = {
            'name': item.name,
            'path': str(item),
            'type': 'directory' if item.is_dir() else 'file',
        }
        
        if item.is_file():
            stat = item.stat()
            entry['size'] = stat.st_size
            entry['human_size'] = _human_size(stat.st_size)
            entry['mtime'] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        
        if item.is_dir() and recursive:
            try:
                children, child_total, _ = _read_directory(
                    item, recursive=False, max_entries=10, include_hidden=include_hidden
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
    include_metadata: bool = True,
    grep_pattern: str = '',
    context_lines: int = 0,
    recursive: bool = False,
    max_entries: int = 50,
) -> dict:
    """增强版文件读取工具。
    
    Args:
        path: 文件或目录路径
        start_line: 起始行号（1-based，0 表示从头）
        end_line: 结束行号（0 表示到末尾）
        max_lines: 最大返回行数
        offset: 字节偏移（二进制/hex 模式）
        limit_bytes: 字节限制（二进制/hex 模式）
        encoding: 编码：auto / utf-8 / gbk / latin-1 / ...
        mode: 模式：auto / text / binary / hex / skeleton / directory
        head: 读取前 N 行（优先级高于 start_line/end_line）
        tail: 读取后 N 行（优先级高于 start_line/end_line）
        include_metadata: 是否包含文件元信息
        grep_pattern: 可选：只返回匹配 regex 的行
        context_lines: grep 时的上下文行数
        recursive: 目录读取时是否递归
        max_entries: 目录读取时最大条目数
    
    Returns:
        结构化 JSON 结果
    """
    p = Path(path).expanduser().resolve()
    
    # 路径校验
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
                    p, recursive=recursive, max_entries=max_entries
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
    
    # 文件读取
    if not p.is_file():
        return {
            'ok': False,
            'error': f'Path is not a file: {path}',
            'path': str(p),
        }
    
    # 获取元信息
    metadata = _get_metadata(p) if include_metadata else {}
    file_size = p.stat().st_size
    
    # 大小限制检查
    if file_size > MAX_FILE_SIZE:
        return {
            'ok': False,
            'error': f'File too large ({metadata.get("human_size", file_size)} > {_human_size(MAX_FILE_SIZE)}). Use grep_pattern to search or use skeleton mode.',
            'path': str(p),
            'metadata': metadata,
            'suggested_mode': 'skeleton',
        }
    
    # 编码检测
    detected_encoding = encoding if encoding != 'auto' else _detect_encoding(p)
    
    # 二进制检测
    is_binary, binary_reason = _is_binary_file(p)
    mime_type = _get_mime_type(p)
    
    # 模式决策
    actual_mode = mode
    if mode == 'auto':
        if is_binary:
            actual_mode = 'binary'
        elif file_size > LARGE_FILE_THRESHOLD:
            actual_mode = 'text'  # 大文本文件仍按文本，但会截断
        else:
            actual_mode = 'text'
    
    # 二进制模式处理
    if actual_mode == 'binary':
        return {
            'ok': True,
            'path': str(p),
            'mode': 'binary',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', _human_size(file_size)),
            'mime_type': mime_type,
            'is_binary': True,
            'binary_reason': binary_reason,
            'hex_preview': _hex_preview(p, MAX_HEX_BYTES),
            'metadata': metadata,
            'content': '',  # 不返回二进制内容
            'truncated': False,
            'truncation_reason': 'Binary file - hex preview only',
        }
    
    # Hex 模式处理
    if actual_mode == 'hex':
        max_bytes = limit_bytes if limit_bytes > 0 else MAX_HEX_BYTES
        hex_content = _hex_preview(p, max_bytes)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'hex',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', _human_size(file_size)),
            'mime_type': mime_type,
            'hex_content': hex_content,
            'metadata': metadata,
            'content': '',
            'truncated': file_size > max_bytes,
            'truncation_reason': f'Hex preview limited to {max_bytes} bytes' if file_size > max_bytes else '',
        }
    
    # Skeleton 模式处理
    if actual_mode == 'skeleton':
        skeleton = _extract_skeleton(p, detected_encoding)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'skeleton',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', _human_size(file_size)),
            'mime_type': mime_type,
            'skeleton': skeleton,
            'metadata': metadata,
            'content': '',
            'truncated': False,
        }
    
    # 文本模式处理
    # 计算总行数
    try:
        total_lines = _count_lines(p, detected_encoding)
    except Exception:
        total_lines = 0
    
    # Grep 模式
    if grep_pattern:
        try:
            matches, match_count, has_more = _grep_lines(
                p, detected_encoding, grep_pattern, context_lines, max_lines
            )
            
            return {
                'ok': True,
                'path': str(p),
                'mode': 'text',
                'encoding': detected_encoding,
                'size': file_size,
                'human_size': metadata.get('human_size', _human_size(file_size)),
                'mime_type': mime_type,
                'total_lines': total_lines,
                'grep_pattern': grep_pattern,
                'matches': matches,
                'total_matches': match_count,
                'returned_matches': len(matches),
                'has_more': has_more,
                'metadata': metadata,
                'content': '',  # grep 模式不返回完整 content
                'truncated': has_more,
                'truncation_reason': f'Matched {match_count} lines, showing {len(matches)}' if has_more else '',
            }
        except ValueError as e:
            return {
                'ok': False,
                'error': str(e),
                'path': str(p),
            }
    
    # Head 模式
    if head > 0:
        lines, total_read, has_more = _read_head(p, detected_encoding, head)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', _human_size(file_size)),
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
    
    # Tail 模式
    if tail > 0:
        lines, total_lines_actual, start_line, has_more = _read_tail(p, detected_encoding, tail)
        
        return {
            'ok': True,
            'path': str(p),
            'mode': 'text',
            'encoding': detected_encoding,
            'size': file_size,
            'human_size': metadata.get('human_size', _human_size(file_size)),
            'mime_type': mime_type,
            'total_lines': total_lines_actual,
            'returned_lines': len(lines),
            'start_line': start_line,
            'end_line': total_lines_actual,
            'has_more': has_more,
            'content': '\n'.join(lines),
            'metadata': metadata,
            'truncated': has_more,
            'truncation_reason': f'Showing last {len(lines)} of {total_lines_actual} lines' if has_more else '',
        }
    
    # 行号范围模式
    lines, actual_start, actual_end, has_more = _read_lines_range(
        p, detected_encoding, start_line, end_line, max_lines
    )
    
    # 检查是否被截断
    truncated = has_more or (file_size > LARGE_FILE_THRESHOLD and len(lines) >= max_lines)
    # 如果文件大但行数少（比如单行大文件），也标记为截断
    if not truncated and file_size > LARGE_FILE_THRESHOLD:
        truncated = True
    truncation_reason = ''
    if truncated:
        if file_size > LARGE_FILE_THRESHOLD:
            hs = metadata.get("human_size", _human_size(file_size))
            truncation_reason = f'File is large ({hs}). Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
        else:
            truncation_reason = f'Showing lines {actual_start}-{actual_end} of {total_lines}. Use start_line={actual_end+1} to continue.'
    
    return {
        'ok': True,
        'path': str(p),
        'mode': 'text',
        'encoding': detected_encoding,
        'size': file_size,
        'human_size': metadata.get('human_size', _human_size(file_size)),
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


# 保留旧接口兼容
read_file = read
