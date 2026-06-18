# irmia_devkit 增强版 file_read 工具设计文档

## 一、AstrBot 原生 file_read 能力分析

### 1.1 当前实现（基于 _file_utils.py）

```python
def read_file(path: str | Path) -> str:
    """读取文件内容。先试 UTF-8，失败回退 GBK。"""
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="gbk")
```

### 1.2 能力边界

| 维度 | 当前能力 | 限制 |
|------|----------|------|
| 编码检测 | UTF-8 → GBK fallback | 仅支持两种编码，无自动检测 |
| 大文件处理 | 完整读取 | 无分页，大文件直接撑爆上下文 |
| 二进制文件 | 直接抛 UnicodeDecodeError | 无 hex dump / 元信息提取 |
| 目录读取 | 不支持 | 需手动调用 dir_tree + 逐个 file_read |
| 行号控制 | 不支持 | 无法指定起始/结束行 |
| 搜索过滤 | 不支持 | 需配合 rg_search |
| 结构化输出 | 纯文本 | 无文件元信息（大小、编码、行数） |
| 安全限制 | 无 | 无大小限制、无路径校验 |

### 1.3 关键缺口

1. **编码盲区**：UTF-8/GBK 之外的编码（Latin-1、Shift-JIS、EUC-KR 等）完全无法处理
2. **大文件灾难**：100MB 日志文件直接读取会撑爆 LLM 上下文窗口
3. **二进制裸奔**：图片/可执行文件/压缩包直接抛异常，无友好提示
4. **零导航能力**：无法快速预览文件结构、跳转到特定区域
5. **无元信息**：返回内容但不告知文件大小、编码、总行数，LLM 无法判断是否需要继续读取

---

## 二、业界最佳实践调研

### 2.1 Cursor Agent (cursor.com)

```
@file 命令能力：
- 读取单个文件，支持行号范围（@file:10-20）
- 自动检测编码（基于文件内容 heuristics）
- 大文件截断提示（"File too large, showing first 100 lines"）
- 二进制文件拒绝并提示（"Binary file, cannot display"）
```

**亮点**：行号范围、编码自动检测、大文件截断提示

### 2.2 Claude Code (Anthropic)

```
View 工具能力：
- view <file> [start_line] [end_line]
- 支持相对路径和绝对路径
- 返回带行号的代码片段
- 自动检测文件类型（基于扩展名和 shebang）
- 大文件分页（默认 200 行/页，提供 has_more 标志）
- 目录 view 返回文件列表（类似 ls）
```

**亮点**：行号范围、分页机制、目录即文件列表、has_more 标志

### 2.3 GitHub Copilot Chat

```
#file 引用能力：
- 支持文件路径 + 行号范围（#file:path:10-20）
- 自动检测编码（使用 VS Code 的编码检测）
- 大文件截断（> 10KB 时提示截断）
- 二进制文件过滤（基于 isBinaryFile 检测）
```

**亮点**：与 IDE 编码检测集成、二进制文件预过滤

### 2.4 Aider (Paul Gauthier)

```python
# Aider 的 file reading 策略
- 使用 tree-sitter 提取代码结构（类、函数签名）
- 大文件时只读取 "skeleton"（结构框架）
- 支持 /read 命令带行号范围
- 编码检测：chardet + UTF-8 fallback
```

**亮点**：tree-sitter 结构提取、skeleton 模式（只读框架）

### 2.5 Continue.dev

```
Context Provider 能力：
- 文件读取支持 start_line / end_line
- 自动检测编码（chardet）
- 大文件时提供 "summarize" 选项（调用 LLM 总结）
- 二进制文件返回 hex dump（前 1KB）
```

**亮点**：hex dump 模式、LLM 总结选项

---

## 三、能力对比矩阵

| 能力 | AstrBot 原生 | Cursor | Claude Code | Copilot | Aider | Continue | irmia 目标 |
|------|-------------|--------|-------------|---------|-------|----------|-----------|
| 编码自动检测 | ❌ 仅 UTF-8/GBK | ✅ heuristics | ✅ 扩展名+内容 | ✅ VS Code 检测 | ✅ chardet | ✅ chardet | ✅ **chardet + 多编码 fallback** |
| 行号范围 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ **start_line + end_line** |
| 大文件分页 | ❌ | ⚠️ 截断提示 | ✅ has_more | ⚠️ 截断提示 | ✅ skeleton | ✅ summarize | ✅ **分页 + skeleton + 截断** |
| 二进制处理 | ❌ 抛异常 | ❌ 拒绝 | ❌ 拒绝 | ❌ 拒绝 | ❌ | ✅ hex dump | ✅ **hex dump + 元信息** |
| 目录读取 | ❌ | ❌ | ✅ 返回列表 | ❌ | ❌ | ❌ | ✅ **递归/非递归目录读取** |
| 搜索过滤 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ **内置 regex 过滤** |
| 文件元信息 | ❌ | ⚠️ | ✅ | ⚠️ | ✅ | ✅ | ✅ **大小/编码/行数/修改时间** |
| 结构化输出 | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ **统一 JSON 结构** |
| 安全限制 | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ **大小限制 + 路径校验** |

---

## 四、irmia_devkit 增强方案设计

### 4.1 核心设计原则

1. **向后兼容**：现有 `read_file` 函数保留，内部调用新实现
2. **渐进增强**：默认行为不变，通过参数启用高级功能
3. **LLM 友好**：返回结构化 JSON，包含元信息帮助 LLM 决策
4. **安全优先**：大小限制、路径校验、二进制文件友好处理

### 4.2 接口设计

```python
def read(
    path: str,
    *,
    start_line: int = 0,           # 起始行号（1-based，0 表示从头）
    end_line: int = 0,             # 结束行号（0 表示到末尾）
    max_lines: int = 200,          # 最大返回行数（分页）
    offset: int = 0,              # 字节偏移（二进制模式）
    limit_bytes: int = 0,         # 字节限制（二进制模式）
    encoding: str = "auto",        # 编码：auto / utf-8 / gbk / latin-1 / ...
    mode: str = "auto",           # 模式：auto / text / binary / hex / skeleton
    include_metadata: bool = True, # 是否包含文件元信息
    grep_pattern: str = "",        # 可选：只返回匹配行（regex）
    context_lines: int = 0,       # grep 时包含的上下文行数
) -> dict:
    """
    增强版文件读取工具。
    
    Returns:
        {
            "ok": True,
            "path": "绝对路径",
            "mode": "text" | "binary" | "hex" | "skeleton",
            "encoding": "utf-8",           # 检测到的编码
            "size": 12345,                 # 文件大小（字节）
            "total_lines": 1000,          # 总行数（文本模式）
            "returned_lines": 200,        # 实际返回行数
            "start_line": 1,              # 返回的起始行号
            "end_line": 200,              # 返回的结束行号
            "has_more": True,             # 是否有更多内容
            "content": "文件内容...",       # 文本内容
            "hex_preview": "",            # hex 模式时的前 N 字节 hex
            "skeleton": {},               # skeleton 模式时的结构信息
            "metadata": {
                "mtime": "2024-01-01T00:00:00",
                "is_binary": False,
                "mime_type": "text/x-python",
            },
            "truncated": False,           # 是否被截断
            "truncation_reason": "",      # 截断原因
        }
    """
```

### 4.3 模式详解

#### mode="auto"（默认）
- 自动检测文件类型（基于内容 + 扩展名）
- 文本文件 → 按编码读取文本
- 二进制文件（图片/可执行文件/压缩包）→ 返回 hex dump + 元信息
- 大文件（> 100KB）→ 自动截断并提示

#### mode="text"
- 强制按文本读取
- 编码检测：chardet → UTF-8 → GBK → Latin-1（无损）fallback
- 支持行号范围、分页

#### mode="binary"
- 返回二进制文件的元信息
- 不返回内容，只返回：大小、MIME 类型、前 16 字节 hex

#### mode="hex"
- 返回 hex dump（类似 `xxd`）
- 支持 offset + limit_bytes 分页

#### mode="skeleton"
- 仅提取代码结构（类、函数、导入）
- 使用 tree-sitter 或正则提取
- 适用于大文件快速预览

### 4.4 编码检测策略

```python
# 优先级：
# 1. 用户指定 encoding（如果指定了且有效）
# 2. chardet 检测（如果安装了 chardet）
# 3. UTF-8 BOM 检测
# 4. UTF-8 尝试
# 5. GBK 尝试（中文环境）
# 6. Latin-1 无损 fallback（保证不抛异常）

# 依赖：
# - 可选：pip install chardet（提升检测准确率）
# - 无依赖时：BOM → UTF-8 → GBK → Latin-1
```

### 4.5 大文件处理策略

```python
# 阈值配置（可配置）
MAX_FILE_SIZE = 10 * 1024 * 1024      # 10MB：硬拒绝
LARGE_FILE_THRESHOLD = 100 * 1024      # 100KB：自动截断提示
MAX_LINES_PER_CALL = 200               # 每次最多返回 200 行
MAX_BYTES_PER_CALL = 50 * 1024         # 每次最多 50KB

# 策略：
# 1. > 10MB：返回错误 + 元信息，建议用 rg_search 或 skeleton 模式
# 2. > 100KB：自动截断，返回 has_more=True + 截断提示
# 3. 正常文件：返回完整内容（受 max_lines 限制）
```

### 4.6 二进制文件处理

```python
# 检测逻辑：
# 1. 扩展名黑名单：.jpg, .png, .exe, .dll, .zip, .tar.gz, ...
# 2. 内容检测：读取前 8KB，检查 null 字节比例 > 30%
# 3. MIME 类型检测：python-magic（可选）

# 返回结构：
{
    "ok": True,
    "mode": "binary",
    "path": "...",
    "size": 1048576,
    "mime_type": "image/png",
    "hex_preview": "00000000: 8950 4e47 0d0a 1a0a 0000 000d 4948 4452  .PNG........IHDR",
    "metadata": {
        "is_binary": True,
        "suggested_tool": "file_hash 或外部工具",
    },
    "content": "",  # 空，不返回二进制内容
}
```

### 4.7 目录读取能力

```python
# 当 path 是目录时：
{
    "ok": True,
    "mode": "directory",
    "path": "...",
    "entries": [
        {"name": "file.py", "type": "file", "size": 1234, "mtime": "..."},
        {"name": "subdir", "type": "directory", "entries": [...]},  # 递归时
    ],
    "total_entries": 50,
    "returned_entries": 20,  # 分页
    "has_more": True,
}
```

### 4.8 搜索过滤能力

```python
# grep_pattern 参数：
# - 支持 Python regex
# - 只返回匹配行
# - context_lines：匹配行前后上下文

# 返回结构：
{
    "ok": True,
    "mode": "text",
    "grep_pattern": "def \w+",
    "matches": [
        {
            "line": 10,
            "content": "def hello():",
            "context_before": ["# 注释", ""],
            "context_after": ["    pass", ""],
        }
    ],
    "total_matches": 5,
    "returned_matches": 5,
}
```

---

## 五、实现规划

### 5.1 文件结构

```
tools/
├── _file_utils.py          # 现有，保留兼容接口
├── file_read.py            # 新增：增强版 file_read 工具
└── tests/
    └── test_file_read.py   # 新增：测试
```

### 5.2 依赖

```python
# 必需（标准库）：
# - pathlib, os, json, re, mimetypes, binascii, struct

# 可选（提升体验）：
# - chardet: 编码自动检测
# - python-magic: MIME 类型检测
# - tree-sitter: skeleton 模式代码结构提取
```

### 5.3 与现有工具集成

| 现有工具 | 集成方式 |
|----------|----------|
| `safe_edit` | 内部调用 `file_read` 读取文件，利用行号定位 |
| `file_patch` | 利用 `grep_pattern` 快速定位修改区域 |
| `rg_search` | 搜索结果 → `file_read` 读取匹配区域（带 context_lines）|
| `codegraph` | skeleton 模式替代 codegraph 的部分功能 |
| `dir_tree` | 目录读取模式替代 dir_tree 的简单场景 |

### 5.4 注册为工具

```python
# 在 _registry.py 中注册：
FileReadTool = make_tool(
    "file_read",
    "【增强版文件读取】读取文件内容，支持编码自动检测、行号范围、分页、二进制预览、目录列表、搜索过滤。比 AstrBot 原生 file_read 更强大：自动检测编码（非仅 UTF-8/GBK）、大文件分页不撑爆上下文、二进制文件返回 hex 而非抛异常、支持目录读取和 regex 过滤。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件或目录路径"},
            "start_line": {"type": "integer", "default": 0, "description": "起始行号（1-based，0 表示从头）"},
            "end_line": {"type": "integer", "default": 0, "description": "结束行号（0 表示到末尾）"},
            "max_lines": {"type": "integer", "default": 200, "description": "最大返回行数"},
            "encoding": {"type": "string", "default": "auto", "description": "编码：auto / utf-8 / gbk / latin-1"},
            "mode": {"type": "string", "default": "auto", "description": "模式：auto / text / binary / hex / skeleton"},
            "grep_pattern": {"type": "string", "default": "", "description": "可选：只返回匹配 regex 的行"},
            "context_lines": {"type": "integer", "default": 0, "description": "grep 时的上下文行数"},
        },
        "required": ["path"],
    },
    _file_read,
)
```

---

## 六、风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| chardet 未安装时降级 | 低 | 内置 UTF-8 → GBK → Latin-1 fallback |
| 大文件读取内存峰值 | 中 | 流式读取 + 行号索引预构建 |
| 二进制文件误判为文本 | 低 | 扩展名黑名单 + null 字节比例检测 |
| 路径遍历攻击 | 低 | 复用现有 `_auth_guard` 路径校验 |
| 正则搜索 ReDoS | 低 | 超时控制（5 秒）+ 复杂度限制 |

---

## 七、与 MCP 版对比

| 能力 | MCP 版 | irmia 插件版（本设计） |
|------|--------|----------------------|
| 编码检测 | chardet | chardet（可选）+ 内置 fallback |
| 行号范围 | ✅ | ✅ |
| 分页 | ✅ | ✅ |
| 二进制 hex | ✅ | ✅ |
| 目录读取 | ❌ | ✅ |
| 搜索过滤 | ❌ | ✅ |
| skeleton 模式 | ❌ | ✅ |
| 与 codegraph 集成 | ❌ | ✅ |

---

## 八、总结

**核心增强点**：

1. **编码**：从 2 种 → 自动检测 + 多编码 fallback（含 Latin-1 无损）
2. **大文件**：从裸读 → 分页 + 截断提示 + skeleton 模式
3. **二进制**：从抛异常 → hex dump + 元信息 + 友好提示
4. **导航**：从纯文本 → 行号范围 + 目录读取 + 搜索过滤
5. **LLM 友好**：从纯字符串 → 结构化 JSON + 元信息 + has_more 标志

**实现优先级**：
1. P0：编码自动检测 + 行号范围 + 大文件截断
2. P1：二进制 hex + 目录读取 + 分页 has_more
3. P2：skeleton 模式 + grep 过滤 + MIME 检测

**依赖**：仅需标准库，可选 chardet（推荐安装）。
