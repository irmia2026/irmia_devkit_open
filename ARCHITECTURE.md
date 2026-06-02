# Architecture

## Project Structure

```
irmia_devkit_open/
├── main.py                      # Plugin entry: config init, tool registration
├── config.json                  # User-facing config (auto-generated on first run)
├── _conf_schema.json            # AstrBot WebUI config schema
├── metadata.yaml                # AstrBot plugin metadata
├── pyproject.toml               # Project metadata, ruff config
├── requirements.txt             # Python dependencies
├── README.md / README_EN.md     # User docs
├── ARCHITECTURE.md              # This file
├── CHANGELOG.md                 # Version history
├── .gitattributes               # LF line-ending enforcement
├── skills/
│   └── dev-workflow/
│       └── SKILL.md             # LLM agent workflow instructions
├── tests/
│   ├── conftest.py              # Shared pytest fixtures
│   ├── test_registry.py         # TOOL_GROUPS ↔ _ALL_TOOLS consistency
│   ├── test_helpers.py          # unwrap / err_json / proposal_reply
│   ├── test_safe_edit.py        # Backup → patch → syntax → rollback chain
│   ├── test_file_remove.py      # Path sandbox, forbidden prefixes
│   ├── test_rg_search.py        # Ripgrep + Python fallback
│   ├── test_lint_runner.py      # Linter fallback chain
│   ├── test_syntax_check.py     # Multi-language syntax + context
│   ├── test_regex.py            # ReDoS protection
│   ├── test_http_utils.py       # SSRF validation
│   ├── test_db_query.py         # SQL injection, read-only enforcement
│   └── test_file_zip.py         # Zip-slip protection
└── tools/
    ├── __init__.py              # Package marker
    ├── _registry.py             # Tool class definitions + TOOL_GROUPS + _ALL_TOOLS
    ├── _helpers.py              # err_json, unwrap, run_sync, proposal_reply
    ├── _file_utils.py           # read_file, find_closest_line, size limits
    ├── _http_utils.py           # SSRF validate_url, SafeRedirectHandler
    ├── config.py                # Module-level config singleton
    ├── tool_stats.py            # In-memory call counter
    │
    ├── safe_edit.py             # Backup → replace → syntax check → auto-rollback
    ├── file_patch.py            # Exact text replacement + preview
    ├── syntax_check.py          # Multi-language syntax (Python/Nim/Go/JS/TS)
    ├── lint_runner.py           # ruff/pylint/eslint with auto-fallback
    ├── file_remove.py           # Path-sandboxed file/dir deletion
    │
    ├── git_smart.py             # Structured git status/diff/log/commit/push
    ├── git_changelog.py         # Semantic git log grouping (feat/fix/docs)
    ├── gh_cli.py                # GitHub CLI wrapper (PR/Issue/Release/Repo/CI)
    │
    ├── es_search.py             # Windows Everything filename search
    ├── rg_search.py             # File content search (rg + Python fallback)
    ├── dir_tree.py              # Visual directory tree
    ├── dir_list.py              # Structured directory listing
    ├── file_diff.py             # File-to-file unified diff
    ├── file_hash.py             # MD5/SHA1/SHA256 computation
    ├── file_zip.py              # ZIP compress/extract with Zip-slip protection
    ├── file_watch.py            # Polling-based file change monitor
    ├── config_diff.py           # Key-level JSON/YAML config comparison
    │
    ├── http_get.py              # HTTP GET/POST with SSRF protection
    ├── http_download.py         # Binary download (500MB cap + path sandbox)
    ├── html_extract.py          # HTML → text/links/tables/CSS selector
    ├── json_query.py            # jq-style JSON path traversal
    ├── text_filter.py           # grep/invert/head/tail/count
    ├── diff_strings.py          # In-memory string unified diff
    ├── regex_tester.py          # Regex test + replace with ReDoS protection
    ├── csv_utils.py             # CSV/TSV parse and generate
    ├── md_strip.py              # Markdown → plain text
    ├── log_parse.py             # Nginx/Apache/syslog/JSONL parser
    │
    ├── encode_utils.py          # base64/URL/hex encode/decode
    ├── time_utils.py            # Timestamp↔ISO, time diff
    ├── semver.py                # Semantic version comparison
    ├── uuid_gen.py              # UUID4/hex/token generation
    │
    ├── proc_list.py             # Cross-platform process listing
    ├── sys_snapshot.py          # System health snapshot (CPU/mem/uptime)
    ├── disk_info.py             # Disk usage per partition
    ├── port_check.py            # TCP port connectivity check
    │
    ├── project_init.py          # Project language/framework/dep detection
    ├── dep_scan.py              # Python import graph + cycle detection
    ├── db_query.py              # Read-only SQLite (parameterized)
    ├── svg_render.py            # SVG → PNG (optional cairosvg)
    └── json_schema_val.py       # JSON Schema validation (optional jsonschema)
```

## Initialization Flow

```
AstrBot loads plugin
  └─ imports main.py
       ├─ main.py imports tools/_registry.py
       │    └─ _registry imports ALL 45 tool modules (even disabled ones)
       │    └─ populates TOOL_GROUPS and _ALL_TOOLS
       └─ Main.__init__()
            ├─ Reads config.json (→ data_dir or plugin_dir)
            ├─ Merges WebUI config (if present)
            ├─ Calls config.set_config() to inject global config
            ├─ Filters tools by enabled TOOL_GROUPS
            ├─ Instantiates enabled tool classes from _ALL_TOOLS
            └─ Calls context.add_llm_tools(*tools) to register with AstrBot
```

## Tool Execution Flow

```
LLM decides to call "safe_edit"
  └─ AstrBot routes to SafeEditTool.call()
       ├─ _tool_stats.record("safe_edit")         # Increment counter
       ├─ await _run_sync(_safe_edit, filepath, old, new, replace_all, occurrence)
       │    └─ run_sync() uses loop.run_in_executor(None, ...)
       │         └─ Thread pool executes safe_edit.edit() synchronously
       ├─ _unwrap(result)                          # Standardize response format
       │    ├─ Is it a dict?                  → No → err_json("非预期类型")
       │    ├─ Has proposal/options/evidence? → Yes → pass through as-is
       │    ├─ result["ok"] is False?         → Yes → err_json(result["error"])
       │    └─ Otherwise                      → wrap in {"ok": True, "data": result}
       └─ Returns ToolExecResult (JSON string) to AstrBot → sent to LLM
```

## Response Protocol

All tools return a `dict` with at minimum `{"ok": bool}`. The `_unwrap()` function normalizes them into one of three JSON shapes:

### Shape 1: Plain Success
```json
{"ok": true, "data": {"replaced": 1, "file": "/path/to/file.py"}}
```
For simple successful operations. The original dict is nested under `data`.

### Shape 2: Structured Proposal (success or failure with guidance)
```json
{
  "ok": false,
  "proposal": "port 7860 is not listening",
  "error": "connection refused",
  "evidence": {"host": "127.0.0.1", "port": 7860},
  "options": ["check if service is running", "verify port number"]
}
```
For failures or ambiguous results where the LLM needs to make a choice.
`proposal_reply()` is the factory function. `_unwrap()` passes these through without modification.

### Shape 3: Plain Error
```json
{"ok": false, "error": "file not found"}
```
For simple, unambiguous errors with no recovery path.

## Config Flow

```
config.json (on disk) → main.py reads → _config dict
WebUI config (AstrBot) → main.py merges → _config dict
  ↓
config.set_config(_config, plugin_dir)    # Module-level singleton
  ↓
Tools that need config:
  safe_edit.py  → get_config()["backup_dir"]  # restore backup path
  es_search.py  → get_config()["es_path"]     # custom es.exe location
  gh_cli.py     → get_config()["gh_path"]     # custom gh CLI location
```

## Async Model

Two patterns exist for tool execution:

### Pattern A: Thread pool (I/O-bound tools) — PREFERRED
```python
async def call(self, context, **kwargs):
    result = await _run_sync(tool_function, arg1, arg2)
    return _unwrap(result)
```
Used by: safe_edit, git_*, http_*, file_*, rg_search, syntax_check, lint_runner, etc.
The synchronous function runs in `ThreadPoolExecutor`, keeping the event loop unblocked.

### Pattern B: Direct call (CPU-bound, <1ms) — ACCEPTABLE
```python
async def call(self, context, **kwargs):
    return _unwrap(tool_function(arg1))
```
Used by: base64_*, hex_*, url_*, time_*, semver_compare, uuid_gen, md_strip.
These operations are sub-millisecond pure computation. Direct execution is fine.

> Note: `regex_test` / `regex_replace` originally used Pattern B and blocked the event loop for up to 3 seconds.
> Fixed in v2.3 to use Pattern A with thread-safe SIGALRM fallback.

## How to Add a New Tool

### Step 1: Create the tool module
```python
# tools/my_tool.py
def my_action(param: str) -> dict:
    return {"ok": True, "result": f"processed: {param}"}
```

### Step 2: Register in _registry.py
```python
# Add import at top:
from .my_tool import my_action as _my_action

# Add class definition in the appropriate group section:
@dataclass
class MyActionTool(FunctionTool):
    name: str = "my_action"
    description: str = "What this tool does, when to use it."
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "the parameter"},
        },
        "required": ["param"],
    })
    async def call(self, context, param: str, **kwargs):
        _tool_stats.record(self.name)
        try:
            result = await _run_sync(_my_action, param)
            return _unwrap(result)
        except Exception as e:
            return _err(f"my_action failed: {e}")

# Add to TOOL_GROUPS (pick the right group):
# e.g. under "文件系统" or create a new group

# Add to _ALL_TOOLS:
# "my_action": MyActionTool,
```

### Step 3: Write tests
```python
# tests/test_my_tool.py
from tools.my_tool import my_action

class TestMyTool:
    def test_basic(self):
        result = my_action("test")
        assert result["ok"] is True
        assert "test" in result["result"]
```

### Step 4: Run tests and update docs
```bash
pytest tests/ -v
# Update README.md and README_EN.md with new tool entry
```

## Security Architecture

### SSRF Protection (_http_utils.py)
```
Layer 1: Direct IP check against private net ranges
Layer 2: IPv4-mapped-IPv6 extraction (::ffff:192.168.1.1)
Layer 3: DNS resolution + IP check after hostname → IP lookup
Layer 4: SafeRedirectHandler re-validates on every HTTP redirect
```

### File Editing Safety (safe_edit.py)
```
1. Validate file exists and is under size limit
2. Read content (UTF-8 → GBK fallback)
3. Count occurrences of old text
4. Create backup in ~/.irmia/backups/
5. Execute replacement
6. Run syntax check on code files
7. If syntax fails → auto-rollback to backup
8. Return structured result with proposal/options
```

### SQL Injection Prevention (db_query.py)
```
1. Whitelist: only SELECT and PRAGMA statements
2. Mode: SQLite URI with ?mode=ro (read-only at database level)
3. Parameterized: params parameter for user input
4. Row factory: sqlite3.Row for dict-like access
```

### ReDoS Protection (regex_tester.py)
```
1. Pattern length limit (2000 chars)
2. Input text length limit (100,000 chars)
3. Nested quantifier detection (e.g., (a+)+) → reject
4. SIGALRM timeout (3s, Unix main thread)
5. Match count hard limit (500, Windows/thread fallback)
```

### Zip-Slip Protection (file_zip.py)
```
1. Resolve target directory to absolute path
2. For each ZIP entry, compute (target_dir / entry_name).resolve()
3. Verify resolved path starts with target directory path + os.sep
4. Reject entries that escape the target directory
```

## Testing Strategy

Tests use **real filesystems** in temporary directories (Aider-style). No mocking of `open()`, `Path`, or `os`.

Key patterns:
- `sandbox_dir` fixture: project-relative temp dir (avoids system-protected paths)
- `project_dir` fixture: mini Python project with imports and __pycache__
- `tmp_py_file` / `tmp_txt_file` / `tmp_json_file`: single-file fixtures
- `_reset_config` autouse fixture: resets global config between tests
- Registry tests use `pytest.mark.skipif` for astrbot dependency

```
pytest tests/ -v              # Run all tests
pytest tests/test_safe_edit.py -v    # Run specific module
pytest tests/ -v --tb=long    # Full tracebacks on failure
```
