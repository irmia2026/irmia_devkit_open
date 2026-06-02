# 弥亚开发工具箱 (Irmia DevKit)

AstrBot 插件，为 LLM Agent 提供代码开发工具集。

Python ≥ 3.10

## 安装

将插件文件夹放入 AstrBot 的 `data/plugins/` 目录，重启 AstrBot。

## 配置

首次启动时自动生成 `config.json`。也可通过 AstrBot WebUI 面板配置。修改工具组开关后需重启生效。

| 字段 | 说明 |
|------|------|
| `admin_ids` | 逗号分隔的额外允许 QQ；插件会自动读取 AstrBot 管理员列表 |
| `tool_groups` | 9 组 bool 开关，`false` = 关闭整组 |
| `disabled_tools` | 逗号分隔单独禁用的工具名 |
| `es_path` | Everything CLI 路径，空自动检测 |
| `gh_path` | GitHub CLI 路径，空自动检测 |
| `backup_dir` | safe_edit 备份目录，空 → `~/.irmia/backups` |
| `state_dir` | （已弃用）异步任务目录 |
| `lock_dirs` | （已弃用）文件锁检测目录 |

### 安全提示

本插件包含文件系统、Git/GitHub、系统信息、网络请求和文件编辑/删除等开发工具。所有工具调用前会检查触发者身份：

- AstrBot 管理员可调用。
- `admin_ids` 中配置的额外 QQ 可调用。
- 其他用户会被拒绝，避免群聊普通成员触发本机敏感工具。

建议只在可信会话中启用，并谨慎开放文件系统、系统信息、网络和 Git/GitHub 工具组。

## 前置依赖

| 工具 | 依赖 | 未安装时 |
|------|------|----------|
| `es_search` | Everything + es.exe (Windows) | 返回错误提示 |
| `gh_pr` / `gh_issue` / `gh_release` / `gh_repo` | GitHub CLI | 返回错误提示 |
| `html_extract` | `beautifulsoup4`，lxml 可选 | 缺 bs4 报错，缺 lxml 回退 html.parser |
| `syntax_check` (Nim/Go/JS/TS) | 对应编译器 | 跳过 (skipped=true) |
| `lint_runner` | ruff / pylint / eslint 任一（自动 fallback） | 返回安装提示 |
| `rg_search` | ripgrep（可选），未安装时 Python fallback | 降级到纯标库扫描 |
| `svg_render` | cairosvg（可选） | 返回安装提示 |
| `json_schema_val` | jsonschema（可选） | 返回安装提示 |
| `config_diff` (YAML) | pyyaml（可选） | 返回安装提示 |

> 其余 50+ 工具为 Python 标准库实现，无外部依赖。

## 设计说明

`safe_edit` 提供了备份→精确替换→whitespace-tolerant 模糊匹配→语法检查→失败自动回滚的五步编辑流程。当 LLM 传的 old 文本差一两格缩进时，自动对齐行首空白后重试匹配（对标 Aider），避免多一轮交互。多处匹配时返回所有位置的 `{行号, 列号, 预览}` 并提示用 `occurrence=N` 消歧。

部分工具（`git_commit`、`syntax_check`、`port_check`、`es_search`、`lint_runner`、`dep_scan` 等 17 个）在失败或歧义时返回 `{proposal, evidence, options, next_call}` 结构化信息，替代纯文本错误。

`syntax_check`/`lint_runner`/`rg_search` 在返回结果中附带代码上下文片段，帮助 LLM 直接定位问题，无需额外读文件。

61 个工具按 9 组管理，可在 `config.json` 中按组或按单个工具关闭。

## 架构

详见 [ARCHITECTURE.md](ARCHITECTURE.md)，包含：
- 模块依赖关系图和初始化流程
- 如何新增工具的完整步骤
- 响应协议规范（三种 JSON shape）
- 安全设计架构（SSRF 四层、safe_edit 防御链、ReDoS 三重盾）
- 异步执行模型和测试策略

## 工具列表 (61)

### 🔒 安全编辑链 (7)

| 工具 | 用途 |
|------|------|
| `safe_edit` | 备份→替换→语法检查→通过保留/失败回滚 |
| `safe_rollback` | 回滚到指定或最近备份 |
| `safe_backups` | 列出备份文件 |
| `file_patch` | 精确文本替换，非代码文件用 |
| `file_preview` | 预览替换效果 (dry-run diff) |
| `syntax_check` | Python / Nim / Go / JS / TS 语法 |
| `lint_runner` | ruff / pylint / eslint 代码质量 |

### 🔀 Git & GitHub (11)

| 工具 | 用途 |
|------|------|
| `git_status` | 仓库状态 (--porcelain) |
| `git_diff` | 工作区/暂存区差异 |
| `git_log` | 最近 N 条提交 |
| `git_commit` | 暂存并提交（>10 文件拦截） |
| `git_branch` | 当前分支 |
| `git_remote` | 远程 URL |
| `git_push` | 推送（无 --force） |
| `gh_pr` | PR：创建/列出/合并/查看 |
| `gh_issue` | Issue：创建/列出/关闭 |
| `gh_release` | Release：创建/列出 |
| `gh_repo` | 仓库：创建/查看/CI/认证 |

### 📁 文件系统 (12)

| 工具 | 用途 |
|------|------|
| `es_search` | Everything 文件名搜索 (Windows) |
| `rg_search` | 文件内容搜索（ripgrep + Python fallback） |
| `dir_tree` | 目录树 |
| `dir_list` | 目录列表 |
| `file_diff` | 文件差异比较 |
| `file_hash` | MD5 / SHA1 / SHA256 |
| `file_zip` | ZIP 打包 |
| `file_unzip` | ZIP 解压（Zip-slip 防护） |
| `file_remove` | 删除文件/目录（沙箱+批量确认） |
| `disk_info` | 磁盘分区使用情况 |
| `file_watch` | 文件变化监控 |
| `config_diff` | 配置文件 key 级差异 |

### 📊 系统信息 (4)

| 工具 | 用途 |
|------|------|
| `port_check` | 端口检测 / 批量扫描 |
| `proc_list` | 进程列表 |
| `sys_snapshot` | 系统快照 (CPU/内存/进程/开机) |
| `tool_stats` | 工具调用统计 |

### 🌐 网络 (3)

| 工具 | 用途 |
|------|------|
| `http_get` | HTTP GET (SSRF 防护) |
| `http_post` | HTTP POST |
| `http_download` | 二进制下载 (500MB 上限 + 路径沙箱) |

### 📝 文本处理 (10)

| 工具 | 用途 |
|------|------|
| `html_extract` | HTML → 文本/链接/表格 |
| `json_query` | jq 式 JSON 路径查询 |
| `text_filter` | 行过滤 (grep/head/tail/count) |
| `diff_strings` | 字符串 unified diff |
| `regex_test` | 正则匹配测试 |
| `regex_replace` | 正则替换 |
| `csv_parse` | CSV/TSV → 结构化数据 |
| `csv_gen` | 结构化 → CSV/TSV |
| `md_strip` | Markdown → 纯文本 |
| `log_parse` | Nginx/Apache/syslog/JSON Lines |

### 🔤 编码 (3)

| 工具 | 用途 |
|------|------|
| `base64_` | Base64 编解码（action: encode/decode） |
| `hex_` | 十六进制编解码（action: encode/decode） |
| `url_` | URL 编解码（action: encode/decode） |

### ⏱ 时间 (3)

| 工具 | 用途 |
|------|------|
| `time_now` | 当前时间 |
| `time_convert` | 时间戳↔ISO 互转（direction: to_iso/to_ts） |
| `time_diff` | 时间差 |

### 🧩 扩展 (8)

| 工具 | 用途 |
|------|------|
| `semver_compare` | 语义版本比较 |
| `uuid_gen` | UUID / hex / token |
| `svg_render` | SVG→PNG |
| `json_schema_val` | JSON Schema 校验 |
| `project_init` | 项目结构扫描 |
| `git_changelog` | git log 分类 |
| `db_query` | SQLite 只读查询 |
| `dep_scan` | Python 依赖图 + 循环检测 |

### 🧠 Skill

| 名称 | 触发 |
|------|------|
| `dev-workflow` | 编码/改代码/修 bug/重构任务 |

## 快速上手

改代码的标准流程：

```
git_status(cwd=".")               # 确认工作区干净
rg_search(pattern="old_func", file_exts="py")  # 找到所有引用
safe_edit(filepath="main.py",     # 执行编辑
          old="x = 1",
          new="x = 42")
syntax_check(filepath="main.py")  # 验证语法
lint_runner(filepath="main.py")   # 检查代码质量
git_diff(cwd=".", staged=true)    # 自查改动
git_commit(cwd=".",               # 提交
           message="refactor: replace old_func with new_func")
```

## 测试

```bash
pip install pytest
python -m pytest tests/ -v
```

100 用例，覆盖 SSRF、safe_edit 防御链、Zip-slip、SQL 注入、ReDoS、注册表一致性、linter fallback 等。

## 英文文档

[English README](README_EN.md)

## 版本

2.3.0 · [Changelog](CHANGELOG.md)

## 作者

伊尔弥亚 (irmia2026) · https://github.com/irmia2026/irmia_devkit_open
