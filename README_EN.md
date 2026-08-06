# Irmia DevKit (弥亚开发工具箱)

An AstrBot plugin providing 65 secure, structured code development tools for LLM Agents.

**Requires**: Python ≥ 3.10, AstrBot any version.

> ⚠️ This plugin is designed for single-user local development. Do not deploy in multi-user shared bot scenarios. All file operations are intended for use within the working directory only.

## Installation

Place the plugin folder into AstrBot's `data/plugins/` directory and restart AstrBot.

## Configuration

`config.json` is auto-generated on first launch. All fields can be configured via AstrBot WebUI.

| Field | Description |
|------|------|
| `owner_sid` | Admin session ID (optional; plugin auto-reads AstrBot admin list) |
| `allowed_ids` | Additional allowed user IDs (comma-separated) |
| `group_config_enabled` | Enable per-group permission config (default: false, restart required) |
| `tool_groups` | 10 group bool switches (`false` = disable entire group) |
| `disabled_tools` | Comma-separated names of individually disabled tools |
| `es_path` | Everything CLI path (auto-detect if empty) |
| `gh_path` | GitHub CLI path (auto-detect if empty) |
| `backup_dir` | safe_edit backup directory (default: `~/.irmia/backups`) |

## Dependencies

| Tool | Dependency | Behavior if missing |
|------|-----------|-------------------|
| `es_search` | Everything + es.exe (Windows) / locate / fd | Returns error or Python os.walk scan |
| `gh_pr` / `gh_issue` / `gh_release` / `gh_repo` | GitHub CLI | Returns error |
| `html_extract` | `beautifulsoup4`, lxml optional | bs4 required, lxml falls back to html.parser |
| `syntax_check` (Nim/Go/JS/TS) | Respective compilers | Skipped (skipped=true) |
| `lint_runner` | ruff / pylint / eslint (auto-fallback) | Returns install hint |
| `rg_search` | ripgrep (optional, Python fallback) | Falls back to stdlib scan |
| `config_diff` (YAML) | pyyaml (optional) | Returns install hint |
| `code_index` (multi-lang) | tree-sitter + grammar (optional) | Zero-deps for Python; other languages skipped |

> The remaining 50+ tools use Python standard library only.

## Design

`safe_edit` enforces a defensive editing workflow: backup → exact replacement → whitespace-tolerant fallback → syntax check → auto-rollback on failure. When the LLM's `old` string is off by a level of indentation, whitespace alignment automatically retries before failing. Multi-match ambiguity is resolved through `occurrence=N` with line-by-line previews.

**Permission control**: Two-layer defense — `on_llm_request` hook removes plugin tools from `req.func_tool` (LLM cannot see them) + `protect_tool` wraps each tool's `call()` with admin check. Automatically reads AstrBot's global admin list; no duplicate configuration needed.

17 tools return structured `{proposal, evidence, options, next_call}` on failure or ambiguity instead of plain error text.

`syntax_check`/`lint_runner`/`rg_search` include surrounding code context in their results, enabling the LLM to locate issues without an extra file read.

65 tools organized into 10 groups. Disable entire groups or individual tools via `config.json`.

## Tool List (65)

### 🔒 Safe Edit Chain (10)

| Tool | Description |
|------|-------------|
| `safe_edit` | Backup → replace → syntax check → keep/rollback; line-insert/delete modes; auto-strips copied line-number prefixes. **Only way to edit code** |
| `safe_write` | Create new files / overwrite whole files with syntax check |
| `safe_rollback` | Rollback file to a backup |
| `safe_backups` | List backup files (auto retention: 10 per file + 500MB LRU) |
| `file_patch` | Exact text replacement for non-code files, occurrence disambiguation |
| `file_preview` | Preview replacement effect (dry-run diff) |
| `syntax_check` | Syntax check for Python / Nim / Go / JS / TS |
| `lint_runner` | Code quality check (ruff / pylint / eslint with auto-fallback) |
| `test_runner` | Unified pytest / go test / cargo test / jest runner |
| `multi_edit` | Atomic multi-file editing with full rollback |

### 🔀 Git & GitHub (11)

| Tool | Description |
|------|-------------|
| `git_status` | Repository status (--porcelain) |
| `git_diff` | Workspace/staged diff |
| `git_log` | Recent N commits |
| `git_commit` | Stage + commit (>10 files blocked; files for selective staging / force) |
| `git_branch` | Current branch |
| `git_remote` | Remote URL |
| `git_push` | Push to origin (no --force) |
| `gh_pr` | Pull Request: create/list/merge/view |
| `gh_issue` | Issue: create/list/close |
| `gh_release` | Release: create/list |
| `gh_repo` | Repo: create/view/CI status/CI logs/auth check |

### 📁 File System (12)

| Tool | Description |
|------|-------------|
| `safe_read` | Enhanced safe file read: auto-encoding, line-number prefixes, binary/hex, head/tail, line ranges, skeleton |
| `es_search` | Everything/locate/fd filename search |
| `rg_search` | File content search (ripgrep + Python fallback) |
| `dir_tree` | Directory tree visualization |
| `dir_list` | Structured directory listing |
| `file_diff` | File-to-file diff |
| `file_hash` | MD5 / SHA1 / SHA256 |
| `file_zip` | ZIP archive |
| `file_unzip` | ZIP extract (Zip-slip protection) |
| `file_remove` | Delete files/directories (sandbox + confirmation) |
| `disk_info` | Disk partition usage (Windows/Linux) |
| `config_diff` | Key-level JSON/YAML config comparison |

### 📊 System Info (4)

| Tool | Description |
|------|-------------|
| `port_check` | Port detection / batch scan |
| `proc_list` | Process list |
| `sys_snapshot` | System snapshot (CPU/mem/processes/uptime) |
| `tool_stats` | Tool call statistics |

### 🧾 Execution & Audit (2)

| Tool | Description |
|------|-------------|
| `shell_exec` | Strict allowlisted command execution with timeout/truncation |
| `op_log` | SQLite audit trail query for tool calls |

### 🌐 Network (3)

| Tool | Description |
|------|-------------|
| `http_get` | HTTP GET + HTML→Markdown extraction (SSRF protection, markdown pagination by default) |
| `http_post` | HTTP POST |
| `http_download` | Binary download (500MB cap + path sandbox) |

### 📝 Text Processing (8)

| Tool | Description |
|------|-------------|
| `html_extract` | HTML → text/links/tables/CSS selector |
| `json_query` | jq-style JSON path query |
| `text_filter` | Line filter (grep/head/tail/count) |
| `diff_strings` | String unified diff |
| `csv_parse` | CSV/TSV → structured data |
| `csv_gen` | Structured data → CSV/TSV |
| `md_strip` | Markdown → plain text |
| `log_parse` | Nginx/Apache/syslog/JSONL parser |

### 🔤 Encoding & ⏱ Time (2)

| Tool | Description |
|------|-------------|
| `encode_decode` | Base64 / URL / Hex encode/decode (action + format) |
| `time` | Current time / timestamp ↔ ISO / time diff (action) |

### 🧩 Extensions (6)

| Tool | Description |
|------|-------------|
| `semver_compare` | Semantic version comparison |
| `uuid_gen` | UUID / hex / token generation |
| `project_init` | Project structure scan |
| `git_changelog` | Git log semantic grouping |
| `db_query` | SQLite read-only query |
| `dep_scan` | Python import graph + cycle detection |

### 🤖 Code Understanding (6)

| Tool | Description |
|------|-------------|
| `code_index` | Build semantic index (symbols + call edges) |
| `code_explore` | Natural language codebase exploration |
| `code_diff_impact` | Blast radius analysis for file changes |
| `code_pack` | Precision context packing — collect call chain sources |
| `code_status` | Index health check — coverage and status |
| `symbol_rename` | Python symbol rename using codegraph + token replacement |

### 🧠 Skill

| Name | Trigger |
|------|---------|
| `dev-workflow` | Code tasks: edit / fix / refactor / implement |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for:
- Module dependency graph and data flow
- How to add a new tool (step-by-step guide)
- Response protocol specification
- Security architecture details
- Async execution model
- Testing strategy

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

Current local verification: 661 passed and 8 skipped. Coverage includes SSRF, safe_edit, Zip-slip, SQL injection, ReDoS, registry consistency, linter/test fallback, auth permission checks, semantic indexing, atomic edits, safe command execution, and audit logging.

## Version

2.6.4 · [Changelog](CHANGELOG.md)

## Author

伊尔弥亚 (irmia2026) · https://github.com/irmia2026/irmia_devkit_open
