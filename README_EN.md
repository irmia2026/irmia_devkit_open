# Irmia DevKit (弥亚开发工具箱)

An AstrBot plugin providing 61 secure, structured code development tools for LLM Agents.

**Requires**: Python ≥ 3.10, AstrBot any version.

> ⚠️ This plugin is designed for single-user local development. Do not deploy in multi-user shared bot scenarios. All file operations are intended for use within the working directory only.

## Installation

Place the plugin folder into AstrBot's `data/plugins/` directory and restart AstrBot.

## Configuration

`config.json` is auto-generated on first launch. All fields can be configured via AstrBot WebUI.

| Field | Description |
|------|------|
| `tool_groups` | 9 group bool switches (`false` = disable entire group) |
| `es_path` | Everything CLI path (auto-detect if empty) |
| `gh_path` | GitHub CLI path (auto-detect if empty) |
| `backup_dir` | safe_edit backup directory (default: `~/.irmia/backups`) |

## Dependencies

| Tool | Dependency | Behavior if missing |
|------|-----------|-------------------|
| `es_search` | Everything + es.exe (Windows) | Returns error |
| `gh_pr` / `gh_issue` / `gh_release` / `gh_repo` | GitHub CLI | Returns error |
| `html_extract` | `beautifulsoup4`, lxml optional | bs4 required, lxml falls back to html.parser |
| `syntax_check` (Nim/Go/JS/TS) | Respective compilers | Skipped (skipped=true) |
| `lint_runner` | ruff / pylint / eslint (auto-fallback) | Returns install hint |
| `rg_search` | ripgrep (optional, Python fallback) | Falls back to stdlib scan |
| `svg_render` | cairosvg (optional) | Returns install hint |
| `json_schema_val` | jsonschema (optional) | Returns install hint |
| `config_diff` (YAML) | pyyaml (optional) | Returns install hint |

> The remaining 50+ tools use Python standard library only.

## Design

`safe_edit` enforces a defensive editing workflow: backup → exact replacement → whitespace-tolerant fallback → syntax check → auto-rollback on failure. When the LLM's `old` string is off by a level of indentation, whitespace alignment automatically retries before failing. Multi-match ambiguity is resolved through `occurrence=N` with line-by-line previews.

17 tools return structured `{proposal, evidence, options, next_call}` on failure or ambiguity instead of plain error text.

`syntax_check`/`lint_runner`/`rg_search` include surrounding code context in their results, enabling the LLM to locate issues without an extra file read.

61 tools organized into 9 groups. Disable entire groups or individual tools via `config.json`.

## Tool List (61)

### 🔒 Safe Edit Chain (7)

| Tool | Description |
|------|-------------|
| `safe_edit` | Backup → replace → syntax check → keep/rollback. **Only way to edit code** |
| `safe_rollback` | Rollback file to a backup |
| `safe_backups` | List all backup files |
| `file_patch` | Exact text replacement for non-code files |
| `file_preview` | Preview replacement effect (dry-run diff) |
| `syntax_check` | Syntax check for Python / Nim / Go / JS / TS |
| `lint_runner` | Code quality check (ruff / pylint / eslint with auto-fallback) |

### 🔀 Git & GitHub (11)

| Tool | Description |
|------|-------------|
| `git_status` | Repository status (--porcelain) |
| `git_diff` | Workspace/staged diff |
| `git_log` | Recent N commits |
| `git_commit` | Stage all + commit (>10 files blocked) |
| `git_branch` | Current branch |
| `git_remote` | Remote URL |
| `git_push` | Push to origin (no --force) |
| `gh_pr` | Pull Request: create/list/merge/view |
| `gh_issue` | Issue: create/list/close |
| `gh_release` | Release: create/list |
| `gh_repo` | Repo: create/view/CI/auth check |

### 📁 File System (12)

| Tool | Description |
|------|-------------|
| `es_search` | Everything filename search (Windows) |
| `rg_search` | File content search (ripgrep + Python fallback) |
| `dir_tree` | Directory tree visualization |
| `dir_list` | Structured directory listing |
| `file_diff` | File-to-file diff |
| `file_hash` | MD5 / SHA1 / SHA256 |
| `file_zip` | ZIP archive |
| `file_unzip` | ZIP extract (Zip-slip protection) |
| `file_remove` | Delete files/directories (sandbox + confirmation) |
| `disk_info` | Disk partition usage (Windows/Linux) |
| `file_watch` | File change monitoring |
| `config_diff` | Key-level JSON/YAML config comparison |

### 📊 System Info (4)

| Tool | Description |
|------|-------------|
| `port_check` | Port detection / batch scan |
| `proc_list` | Process list |
| `sys_snapshot` | System snapshot (CPU/mem/processes/uptime) |
| `tool_stats` | Tool call statistics |

### 🌐 Network (3)

| Tool | Description |
|------|-------------|
| `http_get` | HTTP GET (SSRF protection) |
| `http_post` | HTTP POST |
| `http_download` | Binary download (500MB cap + path sandbox) |

### 📝 Text Processing (10)

| Tool | Description |
|------|-------------|
| `html_extract` | HTML → text/links/tables/CSS selector |
| `json_query` | jq-style JSON path query |
| `text_filter` | Line filter (grep/head/tail/count) |
| `diff_strings` | String unified diff |
| `regex_test` | Regex match testing |
| `regex_replace` | Regex replacement |
| `csv_parse` | CSV/TSV → structured data |
| `csv_gen` | Structured data → CSV/TSV |
| `md_strip` | Markdown → plain text |
| `log_parse` | Nginx/Apache/syslog/JSONL parser |

### 🔤 Encoding (3)

| Tool | Description |
|------|-------------|
| `base64_` | Base64 encode/decode (action: encode/decode) |
| `hex_` | Hex encode/decode (action: encode/decode) |
| `url_` | URL encode/decode (action: encode/decode) |

### ⏱ Time (3)

| Tool | Description |
|------|-------------|
| `time_now` | Current time (ISO + timestamp) |
| `time_convert` | Timestamp ↔ ISO conversion (direction: to_iso/to_ts) |
| `time_diff` | Time delta between two ISO timestamps |

### 🧩 Extensions (8)

| Tool | Description |
|------|-------------|
| `semver_compare` | Semantic version comparison |
| `uuid_gen` | UUID / hex / token generation |
| `svg_render` | SVG → PNG rendering |
| `json_schema_val` | JSON Schema validation |
| `project_init` | Project structure scan |
| `git_changelog` | Git log semantic grouping |
| `db_query` | SQLite read-only query |
| `dep_scan` | Python import graph + cycle detection |

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

100 test cases covering SSRF, safe_edit, Zip-slip, SQL injection, ReDoS, registry consistency, linter fallback, and tool correctness.

## Version

2.3.0 · [Changelog](CHANGELOG.md)

## Author

伊尔弥亚 (irmia2026) · https://github.com/irmia2026/irmia_devkit_open
