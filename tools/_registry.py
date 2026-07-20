"""
_registry — @dataclass FunctionTool 类定义注册表。
从 main.py 提取，供 plugin entry 使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from astrbot.api import FunctionTool as _AstrBotFunctionTool
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


@dataclass
class FunctionTool(_AstrBotFunctionTool):
    """AstrBot v4.16+ 兼容基类。"""

from ._helpers import err_json as _err, unwrap as _unwrap, run_sync as _run_sync
from . import tool_stats as _tool_stats

# ── 导入工具函数 ──

from .file_patch import patch as _file_patch, preview as _file_preview
from .git_smart import (
    status as _git_status,
    diff as _git_diff,
    log as _git_log,
    commit as _git_commit,
    current_branch as _git_branch,
    remote_url as _git_remote,
    push as _git_push,
)
from .syntax_check import check as _syntax_check
from .safe_edit import (
    edit as _safe_edit,
    list_backups as _list_backups,
    rollback as _rollback,
)
from .safe_write import write as _safe_write
from .es_search import search as _es_search
from .rg_search import search as _rg_search
from .http_get import get as _http_get, post as _http_post
from .http_download import download as _http_download
from .html_extract import extract as _html_extract
from .dir_tree import tree as _dir_tree
from .disk_info import info as _disk_info
from .port_check import check as _port_check, scan as _port_scan
from .file_diff import compare as _file_diff
from .proc_list import list_processes as _proc_list
from .file_hash import compute as _file_hash
from .file_zip import compress as _file_zip, extract as _file_unzip
from .sys_snapshot import snapshot as _sys_snapshot
from .encode_utils import (
    b64_encode,
    b64_decode,
    url_encode,
    url_decode,
    hex_encode,
    hex_decode,
)
from .time_utils import now as _time_now, ts_to_iso, iso_to_ts, time_diff
from .dir_list import list_dir as _list_dir
from .json_query import query as _json_query
from .text_filter import filter_lines as _text_filter
from .diff_strings import diff as _diff_strings
from .csv_utils import parse as _csv_parse, generate as _csv_gen
from .uuid_gen import gen as _uuid_gen
from .semver import compare as _semver_compare
from .md_strip import strip as _md_strip
from .gh_cli import (
    pr_create as _gh_pr_create,
    pr_list as _gh_pr_list,
    pr_merge as _gh_pr_merge,
    pr_review as _gh_pr_review,
    pr_view as _gh_pr_view,
    issue_create as _gh_issue_create,
    issue_list as _gh_issue_list,
    issue_close as _gh_issue_close,
    release_create as _gh_release_create,
    release_list as _gh_release_list,
    repo_view as _gh_repo_view,
    repo_create as _gh_repo_create,
    run_list as _gh_run_list,
    auth_status as _gh_auth_status,
)
from .log_parse import parse as _log_parse
from .config_diff import diff as _config_diff
from .project_init import scan as _project_init_scan
from .git_changelog import changelog as _git_changelog
from .lint_runner import run as _lint_run
from .test_runner import run as _test_run
from .multi_edit import run as _multi_edit_run
from .shell_exec import run as _shell_exec_run
from .op_log import query as _op_log_query
from .symbol_rename import run as _symbol_rename_run
from .tool_stats import snapshot as _tool_stats_snap
from .db_query import query as _db_query
from .dep_scan import scan as _dep_scan
from .file_remove import remove as _file_remove, move as _file_move
from .safe_read import read as _safe_read

# ── codegraph ──
from .codegraph import CodeGraph as _CodeGraph


def _code_index(project_dir: str, incremental: bool = False) -> dict:
    from pathlib import Path
    root = Path(project_dir).resolve()
    db_path = str(root / ".codegraph" / "codegraph.db")
    cg = _CodeGraph(db_path)
    try:
        return cg.index(str(root), incremental)
    finally:
        cg.close()


def _code_explore(query: str, project_dir: str = ".") -> dict:
    from pathlib import Path
    root = Path(project_dir).resolve()
    db_path = str(root / ".codegraph" / "codegraph.db")
    cg = _CodeGraph(db_path)
    try:
        return cg.explore(query, str(root))
    finally:
        cg.close()


def _code_diff_impact(filepaths: list, max_depth: int = 3, project_dir: str = ".") -> dict:
    from pathlib import Path
    root = Path(project_dir).resolve()
    db_path = str(root / ".codegraph" / "codegraph.db")
    cg = _CodeGraph(db_path)
    try:
        return cg.code_diff_impact(filepaths, max_depth)
    finally:
        cg.close()


def _code_pack(target: str, depth: int = 2, mode: str = "both", project_dir: str = ".") -> dict:
    from pathlib import Path
    root = Path(project_dir).resolve()
    db_path = str(root / ".codegraph" / "codegraph.db")
    cg = _CodeGraph(db_path)
    try:
        return cg.code_pack(target, depth, mode)
    finally:
        cg.close()


def _code_status(project_dir: str = ".") -> dict:
    from pathlib import Path
    root = Path(project_dir).resolve()
    db_path = str(root / ".codegraph" / "codegraph.db")
    cg = _CodeGraph(db_path)
    try:
        return cg.code_status()
    finally:
        cg.close()


# ═══════════════════════════════════════════════════════════
# Tool factory
# ═══════════════════════════════════════════════════════════

from typing import Callable


def make_tool(
    name: str,
    description: str,
    parameters: dict,
    fn: Callable[..., dict],
    *,
    io_bound: bool = True,
) -> type[FunctionTool]:
    """工厂函数：消灭样板 @dataclass + async def call。
    
    clean 步骤自动将空字符串转为 None，统一处理所有 ``or None`` 模式。
    """

    # Build the tool class with type() + dataclass() to access closure variables
    _T_dict = {
        '__annotations__': {'name': str, 'description': str, 'parameters': dict},
        'name': name,
        'description': description,
        'parameters': field(default_factory=lambda: parameters),
    }
    _T = type(name.title().replace('_', '') + 'Tool', (FunctionTool,), _T_dict)
    _T = dataclass(_T)

    if io_bound:
        async def call(self, context, **kwargs):
            _tool_stats.record(self.name)
            clean = {k: (v if v != "" else None) for k, v in kwargs.items()}
            try:
                return _unwrap(await _run_sync(fn, **clean))
            except Exception as e:
                return _err(f"{name} 失败: {e}")
    else:
        async def call(self, context, **kwargs):
            _tool_stats.record(self.name)
            clean = {k: (v if v != "" else None) for k, v in kwargs.items()}
            try:
                return _unwrap(fn(**clean))
            except Exception as e:
                return _err(f"{name} 失败: {e}")

    _T.call = call
    return _T


def _port_check_w(host: str = "127.0.0.1", ports: list | None = None) -> dict:
    if not ports:
        return {"ok": False, "error": "请提供 ports 参数"}
    if len(ports) == 1:
        return _port_check(host, ports[0])
    return _port_scan(ports, host)


# ═══════════════════════════════════════════════════════════
# Tool registrations
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


# ══ 安全编辑链 ══

SafeEditTool = make_tool(
    "safe_edit",
    "【改代码文件唯一选择】安全编辑：自动备份→精确替换→语法检查→通过保留/失败自动回滚。支持 .py/.nim/.go/.js/.ts（语法检查）+ 其他扩展名（跳过语法检查）。不要用 file_write 改已有代码（无备份无回滚）。不要用 astrbot_file_edit_tool 改代码（无备份无语法检查）。非代码文件（.md/.txt/.json）可以用 file_patch 或 safe_edit，两者均可。单文件单改优选；跨文件批量/同一文件多改 → 用 multi_edit（原子提交，继承本工具的空白容错能力）。当 old 文本在文件中多处匹配时，工具会报错并列出所有位置——用 occurrence=N 指定第几次出现继续。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "文件路径"},
                "old": {
                    "type": "string",
                    "description": "要被替换的旧文本（精确匹配，包括缩进）",
                },
                "new": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项，默认 false",
                    "default": False,
                },
                "occurrence": {
                    "type": "integer",
                    "description": "替换第 N 次出现（1-based）。当多处匹配时用于消歧",
                    "default": 0,
                },
            },
            "required": ["filepath", "old", "new"],
        },
    _safe_edit,
)


SafeRollbackTool = make_tool(
    "safe_rollback",
    "回滚文件到之前的备份。不指定 backup_name 则回滚到最近一次备份。safe_edit 失败时已自动回滚，此工具用于手动回滚（如改完后不满意想恢复）。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "要回滚的文件路径"},
                "backup_name": {
                    "type": "string",
                    "description": "指定备份文件名，可选",
                },
            },
            "required": ["filepath"],
        },
    _rollback,
)


SafeBackupsTool = make_tool(
    "safe_backups",
    "列出所有备份文件或指定文件的备份。改代码前可先查看有哪些备份；回滚前可确认备份存在。",
    {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "要查询备份的文件路径，不传则列出全部",
                }
            },
            "required": [],
        },
    _list_backups,
)


FilePatchTool = make_tool(
    "file_patch",
    "【替代 astrbot_file_edit_tool——非代码文件首选】精确替换非代码文件中的文本。不要用 astrbot_file_edit_tool（它找不到旧文本时只报错，无匹配行提示）。代码文件请用 safe_edit（自动备份+语法检查+失败回滚）。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "文件路径"},
                "old": {
                    "type": "string",
                    "description": "要被替换的旧文本（精确匹配）",
                },
                "new": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有匹配项",
                    "default": False,
                },
            },
            "required": ["filepath", "old", "new"],
        },
    _file_patch,
)


FilePreviewTool = make_tool(
    "file_preview",
    "【file_patch 伴侣】预览替换效果，不实际修改文件，返回 unified diff。用于不确定替换效果时，确认无误后再用 file_patch 实际修改。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "文件路径"},
                "old": {"type": "string", "description": "要被替换的旧文本"},
                "new": {"type": "string", "description": "替换后的新文本"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否预览全部替换",
                    "default": False,
                },
            },
            "required": ["filepath", "old", "new"],
        },
    _file_preview,
)


SyntaxCheckTool = make_tool(
    "syntax_check",
    "检查代码文件语法。支持 Python/Nim/Go/JS/TS。safe_edit 内部会自动调用它，所以通常不需要手动调。仅在用 file_patch 手动改完代码后，才需要手动调此工具验证。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "要检查的文件路径"}
            },
            "required": ["filepath"],
        },
    _syntax_check,
)


# ══ Git & GitHub ══

GitStatusTool = make_tool(
    "git_status",
    "【替代 git status——首选】结构化仓库状态，直接返回 changed_count + changes 列表。比原生 git status 少一层 --porcelain 手动解析。改前必调。",
    {
            "type": "object",
            "properties": {"cwd": {"type": "string", "description": "Git 仓库路径"}},
            "required": ["cwd"],
        },
    _git_status,
)


GitDiffTool = make_tool(
    "git_diff",
    "【替代 git diff——首选】结构化差异，直接返回 added/removed/total_changes。比原生 git diff 多一层自动统计。改后 staged=false 看工作区，提交前 staged=true 自查。",
    {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Git 仓库路径"},
                "staged": {
                    "type": "boolean",
                    "description": "是否只看已暂存的更改",
                    "default": False,
                },
                "filepath": {"type": "string", "description": "只看指定文件，可选"},
            },
            "required": ["cwd"],
        },
    _git_diff,
)


GitLogTool = make_tool(
    "git_log",
    "【替代 git log——首选】结构化提交记录，直接返回 commits 列表。比原生 git log 少 --format 拼接。提交前确认历史干净时使用。",
    {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Git 仓库路径"},
                "count": {
                    "type": "integer",
                    "description": "最近几条，默认 5",
                    "default": 5,
                },
            },
            "required": ["cwd"],
        },
    _git_log,
)


GitCommitTool = make_tool(
    "git_commit",
    "【替代 git commit——首选】提交并自动生成结构化反馈（files_staged 列表 + 提案）。比原生 git commit 多一层失败诊断。message 用 fix:/feat:/refactor: 格式。",
    {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Git 仓库路径"},
                "message": {"type": "string", "description": "提交信息（简洁描述）"},
            },
            "required": ["cwd", "message"],
        },
    _git_commit,
)


GitBranchTool = make_tool(
    "git_branch",
    "【替代 git branch——首选】直接返回当前分支名。比原生 git branch 少一次 --show-current 手动提取。",
    {
            "type": "object",
            "properties": {"cwd": {"type": "string", "description": "Git 仓库路径"}},
            "required": ["cwd"],
        },
    _git_branch,
)


GitRemoteTool = make_tool(
    "git_remote",
    "【替代 git remote -v——首选】直接返回远程仓库 URL。比原生 git remote -v 少一行文本解析。",
    {
            "type": "object",
            "properties": {"cwd": {"type": "string", "description": "Git 仓库路径"}},
            "required": ["cwd"],
        },
    _git_remote,
)


GitPushTool = make_tool(
    "git_push",
    "【替代 git push——首选】推送并自动保护当前分支。比原生 git push 多一层 --force 防误触。自动获取当前分支名。",
    {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Git 仓库路径"},
                "remote": {"type": "string", "description": "远程名称，默认 origin"},
                "branch": {
                    "type": "string",
                    "description": "分支名，留空自动获取当前分支",
                },
            },
            "required": ["cwd"],
        },
    _git_push,
)


# ══ 文件系统 ══

EsSearchTool = make_tool(
    "es_search",
    "【优于 dir /s——首选】毫秒级文件名搜索，直接返回结构化列表（name/path/size/date）。比 shell dir /s 快 500 倍，比 Python os.walk 简洁 10 倍。支持通配符（*.py）和 Everything 语法（ext:/folder:/size:）。",
    {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。支持通配符如 *.py，以及 ext: folder: size:>1mb 等语法",
                },
                "path": {
                    "type": "string",
                    "description": "限定搜索目录路径。不传则全盘搜索",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大结果数，默认 100。设 0 仅统计数量不返回列表",
                    "default": 100,
                },
                "regex": {
                    "type": "boolean",
                    "description": "使用正则表达式搜索",
                    "default": False,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "区分大小写",
                    "default": False,
                },
                "whole_word": {
                    "type": "boolean",
                    "description": "全词匹配",
                    "default": False,
                },
                "file_type": {
                    "type": "string",
                    "description": "文件类型过滤: file（仅文件）/ folder（仅文件夹）/ all（默认）",
                    "default": "all",
                },
                "sort_by": {
                    "type": "string",
                    "description": "排序字段: name/path/size/date_modified/date_created/ext",
                    "default": "",
                },
                "ext": {
                    "type": "string",
                    "description": "文件扩展名过滤，如 py / xlsx / exe",
                    "default": "",
                },
            },
            "required": ["query"],
        },
    _es_search,
)


RgSearchTool = make_tool(
    "rg_search",
    "【替代 astrbot_grep_tool——首选】文件内容级代码搜索引擎，查找函数引用、import 出现位置、变量使用点。不要用 astrbot_grep_tool——它返回原始 `file:line:content` 文本，无 count/truncated/files_searched，LLM 每次要手动 `split(\":\")` 解析行号且不知道结果是否被截断。优先 ripgrep（毫秒级），备 Python 纯标库扫描。file_exts 逗号分隔如 'py,js,ts'，list_files=True 只列文件名不展示匹配行。",
    {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式，正则或字面量"},
                "path": {"type": "string", "description": "搜索起始目录，默认当前目录"},
                "file_exts": {"type": "string", "description": "逗号分隔扩展名，如 'py,js,ts'（无点号）"},
                "max_results": {"type": "integer", "description": "最大结果数，默认 40"},
                "case_sensitive": {"type": "boolean", "description": "区分大小写"},
                "whole_word": {"type": "boolean", "description": "全词匹配"},
                "list_files": {"type": "boolean", "description": "是否只返回文件名列表"},
                "context_lines": {"type": "integer", "description": "匹配行周围展示的上下文行数，默认 0。设 2 则返回前后各 2 行", "default": 0},
            },
            "required": ["pattern"],
        },
    _rg_search,
)


# ══ 网络 ══

HttpGetTool = make_tool(
    "http_get",
    "【HTTP GET 唯一选择】HTTP GET 请求 + 智能内容转换。不要用 astrbot_execute_shell 跑 curl——它无 SSRF（内网 IP）防护。默认返回原始 HTML（5000 字符截断）。支持 format='markdown' 转为 LLM 友好 Markdown，format='text' 提取纯文本正文；extract=true 先提取正文再转换（trafilatura 去广告/导航/页脚），默认 false 全页转换。15s 超时。",
    {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "请求 URL"},
                "headers": {"type": "object", "description": "自定义请求头，可选"},
                "format": {
                    "type": "string",
                    "description": "输出格式：html(默认，返回原始HTML) | markdown(LLM友好的Markdown) | text(纯文本正文)",
                    "enum": ["html", "markdown", "text"],
                    "default": "html",
                },
                "extract": {
                    "type": "boolean",
                    "description": "是否先提取正文再转换（trafilatura 去广告/导航/页脚），默认 false 全页转换",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 15",
                    "default": 15,
                },
            },
            "required": ["url"],
        },
    _http_get,
)


@dataclass
class HttpPostTool(FunctionTool):
    """HTTP POST 请求。"""

    name: str = "http_post"
    description: str = (
        "【HTTP POST 唯一选择】HTTP POST 请求。"
        "不要用 astrbot_execute_shell 跑 curl（它无 SSRF 防护）。"
        "data 为 dict 时自动 JSON 编码，str 原样发送。10s 超时。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "请求 URL"},
                "data": {
                    "type": "string",
                    "description": "POST body，dict 自动 JSON 编码，str 原样发送",
                },
                "headers": {"type": "object", "description": "自定义请求头，可选"},
            },
            "required": ["url"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        url: str,
        data: str = "",
        headers: dict = None,
        **kwargs,
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            body = data
            json_failed = False
            if isinstance(data, dict):
                # LLM passed a dict directly — use as-is (matches schema description)
                body = data
            elif data:
                try:
                    parsed = json.loads(data)
                    body = parsed if isinstance(parsed, dict) else data
                except (json.JSONDecodeError, TypeError):
                    json_failed = True
            if json_failed and isinstance(data, str) and data.strip():
                if data.strip()[0] in ("{", "["):
                    return _err("data 看起来是 JSON 但解析失败——请检查 JSON 语法后重试")
            result = await _run_sync(_http_post, url, body if body else None, headers)
            return _unwrap(result)
        except Exception as e:
            return _err(f"http_post 失败: {e}")


HttpDownloadTool = make_tool(
    "http_download",
    "【下载文件唯一选择】下载文件。不要用 astrbot_execute_shell 跑 wget/curl -O（它无 SSRF 防护、无 500MB 上限、无路径沙箱）。支持大文件，自动处理重定向，失败自动清理。",
    {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "下载地址"},
                "path": {"type": "string", "description": "保存路径（含文件名）"},
                "overwrite": {
                    "type": "boolean",
                    "description": "是否覆盖已有文件，默认 false",
                },
                "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
            },
            "required": ["url", "path"],
        },
    _http_download,
)


# ══ 文本处理 ══

HtmlExtractTool = make_tool(
    "html_extract",
    "从 HTML 中提取结构化内容。用 BeautifulSoup + lxml。what: text(纯文本) / links(链接) / tables(表格) / query(CSS选择器)。query 模式需 selector 参数如 'div.content p'。",
    {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "HTML 字符串"},
                "what": {
                    "type": "string",
                    "description": "提取类型: text / links / tables / query",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS 选择器，what='query' 时必填",
                },
            },
            "required": ["html", "what"],
        },
    _html_extract,
)


DirTreeTool = make_tool(
    "dir_tree",
    "【优于 dir /s——首选】目录树可视化，直接返回缩进树形文本。比 shell tree 快 10 倍，比 Python 递归简洁 5 倍，无需手动解析层级。支持 max_depth/show_hidden/pattern 过滤。",
    {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "max_depth": {"type": "integer", "description": "最大递归深度，默认 3"},
                "show_hidden": {
                    "type": "boolean",
                    "description": "是否显示隐藏文件，默认 false",
                },
                "pattern": {"type": "string", "description": "文件名过滤，如 '*.py'"},
            },
            "required": ["path"],
        },
    _dir_tree,
)


DiskInfoTool = make_tool(
    "disk_info",
    "查询所有磁盘分区的使用情况。返回每个盘符的 total/used/free/percent。纯 shutil 标准库。当你需要知道磁盘剩余空间时使用。",
    {"type": "object", "properties": {}, "required": []},
    _disk_info,
)


# ══ 系统信息 ══

PortCheckTool = make_tool(
    "port_check",
    "【替代 netstat——首选】端口检测，3s 超时，直接返回布尔值+端口号。比原生 netstat 少 10 行 awk 过滤。支持单端口检测和批量扫描。",
    {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "主机地址，默认 127.0.0.1",
                    "default": "127.0.0.1",
                },
                "ports": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "端口列表，如 [7860, 19530, 6199]。单端口传 [7860]",
                },
            },
            "required": ["ports"],
        },
    _port_check_w,
)


FileDiffTool = make_tool(
    "file_diff",
    "【替代 fc/diff——首选】结构化文件对比，直接返回 added/removed/total_changes。比原生 fc 多一层统计摘要，输出远比 raw diff 更适合程序处理。返回结构化差异 + unified diff（限 100 行）。",
    {
            "type": "object",
            "properties": {
                "file_a": {"type": "string", "description": "第一个文件路径"},
                "file_b": {"type": "string", "description": "第二个文件路径"},
            },
            "required": ["file_a", "file_b"],
        },
    _file_diff,
)


ProcListTool = make_tool(
    "proc_list",
    "【替代 tasklist/ps——首选】进程列表（name/pid/memory_kb），按内存降序。比原生 tasklist 多一层结构化过滤，支持 filter_name 模糊匹配。",
    {
            "type": "object",
            "properties": {
                "filter_name": {
                    "type": "string",
                    "description": "按进程名模糊过滤，如 'python' 'docker' 'node'",
                }
            },
            "required": [],
        },
    _proc_list,
)


FileHashTool = make_tool(
    "file_hash",
    "计算文件哈希值（MD5/SHA1/SHA256）。默认 SHA256。纯 hashlib 标准库，返回 hex 字符串 + 文件大小。用于验证下载完整性、比对文件是否一致。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "文件路径"},
                "algo": {
                    "type": "string",
                    "description": "哈希算法: md5/sha1/sha256，默认 sha256",
                    "default": "sha256",
                },
            },
            "required": ["filepath"],
        },
    _file_hash,
)


FileZipTool = make_tool(
    "file_zip",
    "【替代 zip——首选】打包到 ZIP，自动验证文件列表。比原生 zip 多一层失败回退。",
    {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}, "description": "要打包的文件/目录路径列表"},
                "output": {"type": "string", "description": "输出 ZIP 文件路径"},
            },
            "required": ["files", "output"],
        },
    _file_zip,
)


FileUnzipTool = make_tool(
    "file_unzip",
    "【替代 unzip——首选】解压 ZIP，自动防御路径穿越。比原生 unzip 多一层 Zip-slip 防护，拦截恶意压缩包。",
    {
            "type": "object",
            "properties": {
                "zip_file": {"type": "string", "description": "ZIP 文件路径"},
                "output_dir": {"type": "string", "description": "解压目标目录"},
            },
            "required": ["zip_file", "output_dir"],
        },
    _file_unzip,
)


SysSnapshotTool = make_tool(
    "sys_snapshot",
    "获取系统整体状态快照：主机名/平台/Python版本/CPU核数/内存总量和可用/进程数/开机时间。纯标准库 + systeminfo/tasklist。当你需要了解系统整体状况时调用。",
    {"type": "object", "properties": {}, "required": []},
    _sys_snapshot,
)


# ══ 编码/时间（合并）══
@dataclass
class EncodeDecodeTool(FunctionTool):
    """编解码：base64 / url / hex 三合一。"""

    name: str = "encode_decode"
    description: str = (
        "【替代 base64_/hex_/url_——首选】编解码三合一。"
        "用 format=base64/url/hex + action=encode/decode 统一入口。"
        "比三个独立工具少占 token，调用路径更短。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "encode / decode", "enum": ["encode", "decode"]},
                "format": {"type": "string", "description": "base64 / url / hex", "default": "base64"},
                "data": {"type": "string", "description": "要处理的文本"},
                "as_uri": {"type": "boolean", "description": "base64 encode 时生成 data: URI", "default": False},
                "strip_uri": {"type": "boolean", "description": "base64 decode 时剥离 data: URI 前缀", "default": False},
            },
            "required": ["action", "data"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], action: str, data: str,
        format: str = "base64", as_uri: bool = False, strip_uri: bool = False, **kwargs
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            fmt = format.lower()
            if fmt == "base64":
                if action == "encode":
                    return _unwrap(await _run_sync(b64_encode, data, as_uri))
                return _unwrap(await _run_sync(b64_decode, data, strip_uri))
            elif fmt == "url":
                if action == "encode":
                    return _unwrap(await _run_sync(url_encode, data))
                return _unwrap(await _run_sync(url_decode, data))
            elif fmt == "hex":
                if action == "encode":
                    return _unwrap(await _run_sync(hex_encode, data))
                return _unwrap(await _run_sync(hex_decode, data))
            else:
                return _err(f"不支持的格式: {format}，使用 base64/url/hex")
        except Exception as e:
            return _err(f"encode_decode 失败: {e}")


@dataclass
class TimeTool(FunctionTool):
    """时间工具：获取时间 / 时间戳互转 / 时间差三合一。"""

    name: str = "time"
    description: str = (
        "【替代 time_now/time_convert/time_diff——首选】时间工具三合一。"
        "action: now(当前时间) / convert(时间戳↔ISO互转) / diff(两ISO时间差)。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "now / convert / diff", "enum": ["now", "convert", "diff"]},
                "value": {"type": "string", "description": "ISO 时间字符串 (convert→时间戳)"},
                "ts": {"type": "integer", "description": "Unix 时间戳 (convert→ISO)"},
                "ms": {"type": "boolean", "description": "是否为毫秒时间戳", "default": False},
                "iso1": {"type": "string", "description": "第一个 ISO 时间 (diff)"},
                "iso2": {"type": "string", "description": "第二个 ISO 时间 (diff)"},
            },
            "required": ["action"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], action: str,
        value: str = "", ts: int = 0, ms: bool = False,
        iso1: str = "", iso2: str = "", **kwargs
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            if action == "now":
                return _unwrap(await _run_sync(_time_now))
            elif action == "convert":
                if value:
                    return _unwrap(await _run_sync(iso_to_ts, value))
                return _unwrap(await _run_sync(ts_to_iso, ts, ms))
            elif action == "diff":
                return _unwrap(await _run_sync(time_diff, iso1, iso2))
            else:
                return _err(f"不支持的 action: {action}，使用 now/convert/diff")
        except Exception as e:
            return _err(f"time 失败: {e}")


DirListTool = make_tool(
    "dir_list",
    "【优于 dir——首选】目录列表，返回结构化条目（name/size/type/date）。比 shell dir 快 10 倍，比 Python os.listdir 少 100 行样板代码。支持 pattern 通配/max_depth/show_hidden，目录优先排序，上限 200。",
    {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"},
                "pattern": {
                    "type": "string",
                    "description": "文件名匹配，如 '*.py' 'test_*'，默认 '*'",
                },
                "max_depth": {"type": "integer", "description": "最大递归深度，默认 1"},
                "show_hidden": {
                    "type": "boolean",
                    "description": "是否显示隐藏文件，默认 false",
                },
            },
            "required": ["path"],
        },
    _list_dir,
)


JsonQueryTool = make_tool(
    "json_query",
    "jq 式 JSON 查询——点路径遍历 JSON 字符串。语法: key.subkey / key[0] / key[-1] / [*].field。用于解析 API 返回、提取嵌套字段、聚合数组元素。纯 json 标准库。",
    {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "JSON 字符串"},
                "path": {
                    "type": "string",
                    "description": "查询路径，如 'data.items[0].name' 或 'users[*].email'",
                },
            },
            "required": ["data", "path"],
        },
    _json_query,
)


TextFilterTool = make_tool(
    "text_filter",
    "【替代 grep——首选】行过滤器，自动切换 regex/fnmatch 双模式。比原生 grep 多 200 行截断保护，支持 grep/invert/head/tail/count。",
    {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作: grep / invert / head / tail / count",
                },
                "text": {"type": "string", "description": "输入文本"},
                "pattern": {
                    "type": "string",
                    "description": "grep/invert 时的匹配模式（通配或正则）",
                },
                "n": {
                    "type": "integer",
                    "description": "head/tail 时取的行数",
                    "default": 10,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "是否区分大小写，默认 false",
                },
                "regex": {
                    "type": "boolean",
                    "description": "是否将 pattern 视为正则表达式，默认 false",
                },
            },
            "required": ["action", "text"],
        },
    _text_filter,
)


DiffStringsTool = make_tool(
    "diff_strings",
    "比较两个字符串（非文件），返回 unified diff。纯 difflib 标准库。返回 added/removed/total_changes/identical。context_lines 控制上下文行数（默认 3）。用于比较命令输出、配置前后差异。",
    {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "第一个字符串"},
                "b": {"type": "string", "description": "第二个字符串"},
                "context_lines": {
                    "type": "integer",
                    "description": "上下文行数，默认 3",
                },
            },
            "required": ["a", "b"],
        },
    _diff_strings,
)


CsvParseTool = make_tool(
    "csv_parse",
    "解析 CSV/TSV 文本为结构化数据（dict 列表）。delimiter='auto' 自动检测分隔符（逗号或制表符）。has_header=True 时首行为表头。返回 headers + rows + count，上限 200 行。纯 csv 标准库。",
    {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "CSV/TSV 文本"},
                "delimiter": {
                    "type": "string",
                    "description": "分隔符，'auto' 自动检测，或指定 ',' '\\t'",
                },
                "has_header": {
                    "type": "boolean",
                    "description": "首行是否为表头，默认 true",
                },
            },
            "required": ["text"],
        },
    _csv_parse,
)


CsvGenTool = make_tool(
    "csv_gen",
    "将 dict 列表生成为 CSV 文本。delimiter 默认逗号。输入格式: [{\"name\":\"a\",\"age\":1}, ...]。纯 csv 标准库。",
    {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "string",
                    "description": 'JSON 数组字符串，如 \'[{"a":1},{"a":2}]\'',
                },
                "delimiter": {"type": "string", "description": "分隔符，默认 ','"},
            },
            "required": ["rows"],
        },
    _csv_gen,
)


# ══ 扩展 ══

UuidGenTool = make_tool(
    "uuid_gen",
    "生成唯一标识符或随机字符串。kind: uuid4(UUID4) / hex(十六进制) / token(字母数字)。hex/token 可设 length 控制长度（默认 16）。纯 uuid+secrets 标准库。",
    {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "类型: uuid4 / hex / token",
                    "default": "uuid4",
                },
                "length": {
                    "type": "integer",
                    "description": "hex/token 时的长度，默认 16",
                },
            },
            "required": [],
        },
    _uuid_gen,
)


SemverTool = make_tool(
    "semver_compare",
    "比较两个语义版本号。返回 > / < / =。支持 '1.2.3' '2.0.0-beta.1' 格式。纯 Python，无依赖。",
    {
            "type": "object",
            "properties": {
                "v1": {"type": "string", "description": "第一个版本号"},
                "v2": {"type": "string", "description": "第二个版本号"},
            },
            "required": ["v1", "v2"],
        },
    _semver_compare,
)


MdStripTool = make_tool(
    "md_strip",
    "剥离 Markdown 标记，返回纯文本。处理标题/粗体/斜体/代码块/链接/图片/列表/引用/删除线。纯 re 标准库。",
    {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Markdown 文本"}},
            "required": ["text"],
        },
    _md_strip,
)


FileReadTool = make_tool(
    "safe_read",
    "【安全文件读取——替代 AstrBot 原生 file_read】安全读取文件内容，支持编码自动检测、行号范围、分页、二进制预览、hex 转储、骨架提取。比原生更强大：自动检测编码（非仅 UTF-8/GBK）、大文件分页不撑爆上下文、二进制文件返回 hex 而非抛异常。目录浏览请用 dir_list / dir_tree；搜索请用 rg_search，不要在此工具内使用。",
    {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（目录请使用 dir_list 或 dir_tree）",
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（1-based，0 表示从头）",
                    "default": 0,
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（0 表示到末尾）",
                    "default": 0,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "最大返回行数（分页）",
                    "default": 200,
                },
                "head": {
                    "type": "integer",
                    "description": "读取前 N 行（优先级高于 start_line/end_line）",
                    "default": 0,
                },
                "tail": {
                    "type": "integer",
                    "description": "读取后 N 行（优先级高于 start_line/end_line）",
                    "default": 0,
                },
                "encoding": {
                    "type": "string",
                    "description": "编码：auto / utf-8 / gbk / latin-1",
                    "default": "auto",
                },
                "mode": {
                    "type": "string",
                    "description": "模式：auto / text / binary / hex / skeleton（目录请使用 dir_list / dir_tree）",
                    "default": "auto",
                },
                "offset": {
                    "type": "integer",
                    "description": "hex 模式下的字节偏移",
                    "default": 0,
                },
                "limit_bytes": {
                    "type": "integer",
                    "description": "hex 模式下最多读取的字节数",
                    "default": 0,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "已弃用：目录读取已移除，请使用 dir_list / dir_tree",
                    "default": 3,
                },
                "max_entries": {
                    "type": "integer",
                    "description": "已弃用：目录读取已移除，请使用 dir_list / dir_tree",
                    "default": 50,
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "已弃用：目录读取已移除，请使用 dir_list / dir_tree",
                    "default": False,
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "是否返回文件/目录元信息",
                    "default": True,
                },
            },
            "required": ["path"],
        },
    _safe_read,
)


@dataclass
class GhPrTool(FunctionTool):
    """GitHub Pull Request 操作。"""

    name: str = "gh_pr"
    description: str = (
        "【替代 gh CLI——首选】GitHub PR 管理。"
        "比原生 gh 多一层 --body-file 转义防护，直接返回结构化 JSON。"
        "action: create/list/merge/view/review。create 需 title+body；merge 需 number+strategy；view 需 number；review 需 number，可传 body/review_event。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作: create / list / merge / view / review",
                    "enum": ["create", "list", "merge", "view", "review"],
                },
                "cwd": {"type": "string", "description": "仓库路径，默认当前工作目录"},
                "title": {"type": "string", "description": "PR 标题（create 时必填）"},
                "body": {"type": "string", "description": "PR 正文（create 时可选）"},
                "number": {
                    "type": "integer",
                    "description": "PR 编号（merge/view 时使用）",
                },
                "state": {
                    "type": "string",
                    "description": "list 时筛选: open/closed/merged",
                },
                "limit": {"type": "integer", "description": "list 时返回数量上限"},
                "base": {
                    "type": "string",
                    "description": "create 时目标分支，默认 master",
                },
                "head": {
                    "type": "string",
                    "description": "create 时源分支，默认当前分支",
                },
                "strategy": {
                    "type": "string",
                    "description": "merge 时合并策略: squash/rebase/merge",
                },
                "review_event": {
                    "type": "string",
                    "description": "review 时操作: comment/approve/request-changes",
                },
            },
            "required": ["action"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        cwd: str = "",
        title: str = "",
        body: str = "",
        number: int = 0,
        state: str = "open",
        limit: int = 10,
        base: str = "master",
        head: str = "",
        strategy: str = "squash",
        review_event: str = "comment",
        **kwargs,
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            match action:
                case "create":
                    if not title:
                        return _err("gh_pr create 需要 title 参数")
                    result = await _run_sync(
                        _gh_pr_create, cwd or "", title, body, base, head
                    )
                case "list":
                    result = await _run_sync(_gh_pr_list, cwd or "", state, limit)
                case "merge":
                    result = await _run_sync(
                        _gh_pr_merge, cwd or "", number or None, strategy
                    )
                case "view":
                    result = await _run_sync(
                        _gh_pr_view, cwd or "", number or None
                    )
                case "review":
                    if not number:
                        return _err("gh_pr review 需要 number 参数")
                    result = await _run_sync(
                        _gh_pr_review, cwd or "", number, body, review_event
                    )
                case _:
                    return _err(f"未知操作: {action}")
            return _unwrap(result)
        except Exception as e:
            return _err(f"gh_pr.{action} 失败: {e}")


@dataclass
class GhIssueTool(FunctionTool):
    """GitHub Issue 操作。"""

    name: str = "gh_issue"
    description: str = (
        "【替代 gh CLI——首选】GitHub Issue 管理。"
        "比原生 gh 多一层结构化 JSON 输出。"
        "action: create/list/close。create 需 title+body；close 需 number。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作: create / list / close",
                    "enum": ["create", "list", "close"],
                },
                "cwd": {"type": "string", "description": "仓库路径，默认当前工作目录"},
                "title": {
                    "type": "string",
                    "description": "Issue 标题（create 时必填）",
                },
                "body": {
                    "type": "string",
                    "description": "Issue 正文（create 时可选）",
                },
                "number": {
                    "type": "integer",
                    "description": "Issue 编号（close 时使用）",
                },
                "state": {"type": "string", "description": "list 时筛选: open/closed"},
                "limit": {"type": "integer", "description": "list 时返回数量上限"},
                "labels": {
                    "type": "string",
                    "description": "标签，逗号分隔（create/list 时可选）",
                },
            },
            "required": ["action"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        cwd: str = "",
        title: str = "",
        body: str = "",
        number: int = 0,
        state: str = "open",
        limit: int = 10,
        labels: str = "",
        **kwargs,
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            match action:
                case "create":
                    if not title:
                        return _err("gh_issue create 需要 title 参数")
                    lbls = [l.strip() for l in labels.split(",")] if labels else None
                    result = await _run_sync(
                        _gh_issue_create, cwd or "", title, body, lbls
                    )
                case "list":
                    result = await _run_sync(
                        _gh_issue_list, cwd or "", state, limit, labels
                    )
                case "close":
                    if not number:
                        return _err("gh_issue close 需要 number 参数")
                    result = await _run_sync(_gh_issue_close, cwd or "", number)
                case _:
                    return _err(f"未知操作: {action}")
            return _unwrap(result)
        except Exception as e:
            return _err(f"gh_issue.{action} 失败: {e}")


@dataclass
class GhReleaseTool(FunctionTool):
    """GitHub Release 操作。"""

    name: str = "gh_release"
    description: str = (
        "【替代 gh CLI——首选】GitHub Release 管理。"
        "比原生 gh 多一层结构化 JSON 输出。"
        "action: create/list。create 需 tag+generate_notes。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作: create / list",
                    "enum": ["create", "list"],
                },
                "cwd": {"type": "string", "description": "仓库路径，默认当前工作目录"},
                "tag": {
                    "type": "string",
                    "description": "Release 标签，如 v1.2.3（create 时必填）",
                },
                "notes": {
                    "type": "string",
                    "description": "Release 说明（create 时可选）",
                },
                "generate_notes": {
                    "type": "boolean",
                    "description": "自动生成 release notes（create 时默认 true）",
                },
                "limit": {"type": "integer", "description": "list 时返回数量上限"},
            },
            "required": ["action"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        cwd: str = "",
        tag: str = "",
        notes: str = "",
        generate_notes: bool = True,
        limit: int = 5,
        **kwargs,
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            match action:
                case "create":
                    if not tag:
                        return _err("gh_release create 需要 tag 参数")
                    result = await _run_sync(
                        _gh_release_create, cwd or "", tag, notes, generate_notes
                    )
                case "list":
                    result = await _run_sync(_gh_release_list, cwd or "", limit)
                case _:
                    return _err(f"未知操作: {action}")
            return _unwrap(result)
        except Exception as e:
            return _err(f"gh_release.{action} 失败: {e}")


@dataclass
class GhRepoTool(FunctionTool):
    """GitHub 仓库与 CI 操作。"""

    name: str = "gh_repo"
    description: str = (
        "【替代 gh CLI——首选】GitHub 仓库与 CI 管理。"
        "比原生 gh 多一层结构化 JSON 输出。"
        "action: create/view/runs/auth。create 需 title(仓库名)。"
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作: create / view / runs / auth",
                    "enum": ["create", "view", "runs", "auth"],
                },
                "cwd": {"type": "string", "description": "仓库路径，默认当前工作目录"},
                "title": {"type": "string", "description": "仓库名（create 时必填）"},
                "owner_repo": {
                    "type": "string",
                    "description": "仓库，格式 owner/repo（view 时可选）",
                },
                "public": {"type": "boolean", "description": "create 时是否公开仓库"},
                "limit": {"type": "integer", "description": "runs 时返回数量上限"},
            },
            "required": ["action"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        cwd: str = "",
        title: str = "",
        owner_repo: str = "",
        public: bool = False,
        limit: int = 5,
        **kwargs,
    ) -> ToolExecResult:
        _tool_stats.record(self.name)
        try:
            match action:
                case "create":
                    if not title:
                        return _err("gh_repo create 需要 title 参数（仓库名）")
                    result = await _run_sync(
                        _gh_repo_create, title, not public, cwd or "", True
                    )
                case "view":
                    result = await _run_sync(_gh_repo_view, cwd or "", owner_repo)
                case "runs":
                    result = await _run_sync(_gh_run_list, cwd or "", limit)
                case "auth":
                    result = await _run_sync(_gh_auth_status)
                case _:
                    return _err(f"未知操作: {action}")
            return _unwrap(result)
        except Exception as e:
            return _err(f"gh_repo.{action} 失败: {e}")


LogParseTool = make_tool(
    "log_parse",
    "解析日志文本为结构化数据。支持 Nginx/Apache 访问日志、syslog、JSON Lines。format=auto 自动检测。",
    {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "日志文本"},
                "format": {
                    "type": "string",
                    "description": "auto / nginx / apache / syslog / jsonl",
                    "default": "auto",
                },
            },
            "required": ["text"],
        },
    _log_parse,
)


ConfigDiffTool = make_tool(
    "config_diff",
    "比较两个 JSON/YAML 配置文件的结构化差异（按 key 比较，非逐行 diff）。",
    {
            "type": "object",
            "properties": {
                "file_a": {"type": "string", "description": "第一个配置文件路径"},
                "file_b": {"type": "string", "description": "第二个配置文件路径"},
            },
            "required": ["file_a", "file_b"],
        },
    _config_diff,
)


ProjectInitTool = make_tool(
    "project_init",
    "扫描项目目录，detect 语言/框架/依赖/目录结构，返回结构化上下文 JSON 给 LLM 理解项目。",
    {
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "项目根目录路径，默认当前目录",
                },
            },
            "required": [],
        },
    _project_init_scan,
)


GitChangelogTool = make_tool(
    "git_changelog",
    "从 git log 生成分类 changelog：按 fix:/feat:/refactor:/docs: 前缀分组，返回结构化 counts。",
    {
            "type": "object",
            "properties": {
                "cwd": {"type": "string", "description": "Git 仓库路径"},
                "count": {
                    "type": "integer",
                    "description": "最近的 commit 数，默认 30",
                },
            },
            "required": ["cwd"],
        },
    _git_changelog,
)


LintRunnerTool = make_tool(
    "lint_runner",
    "代码质量检查（ruff/pylint/eslint）。与 syntax_check 配合使用：syntax_check 查能不能跑，lint_runner 查写得好不好。linter=auto 自动检测已安装的 linter（ruff→pylint→eslint）。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "要检查的文件路径"},
                "linter": {
                    "type": "string",
                    "description": "linter: auto/ruff/pylint/eslint",
                    "default": "auto",
                },
            },
            "required": ["filepath"],
        },
    _lint_run,
)


TestRunnerTool = make_tool(
    "test_runner",
    "统一运行项目测试（pytest/go test/cargo test/jest）。自动发现项目测试框架，也可传 test_cmd 覆盖；返回 passed/failed/skipped/errors 等结构化结果。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "相关文件路径，可选"},
                "project_dir": {
                    "type": "string",
                    "description": "项目根目录，默认当前目录",
                    "default": ".",
                },
                "test_cmd": {
                    "type": "string",
                    "description": "覆盖自动发现的测试命令，可选；会经过安全白名单校验",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间秒数，默认 120",
                    "default": 120,
                },
            },
            "required": [],
        },
    _test_run,
)


MultiEditTool = make_tool(
    "multi_edit",
    "【批量编辑唯一选择】原子多文件编辑，继承 safe_edit 的空白自动对齐+最近行提示能力。接收 edits=[{file, old, new}]，全部语法检查通过后一次性提交，任一失败全体回滚。配合 code_diff_impact 使用：先查出受影响文件 → 再构建 edits 列表 → 一次性原子提交。单文件单处改动请用 safe_edit（API 更简洁）。",
    {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "description": "编辑列表，每项包含 file/old/new，可选 replace_all/occurrence",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "old": {"type": "string"},
                            "new": {"type": "string"},
                            "replace_all": {"type": "boolean", "default": False},
                            "occurrence": {"type": "integer", "default": 0},
                        },
                        "required": ["file", "old", "new"],
                    },
                },
                "syntax_check": {
                    "type": "boolean",
                    "description": "是否在写入前做语法检查，默认 true",
                    "default": True,
                },
            },
            "required": ["edits"],
        },
    _multi_edit_run,
)


SafeWriteTool = make_tool(
    "safe_write",
    "【新建文件首选】新建或整体覆盖文件。自动创建父目录，写入后做语法检查。新建：语法检查失败【不阻塞、不删除】——新文件无旧版可回滚，文件保留+修正指引。改已有文件局部内容请用 safe_edit / multi_edit。确需整体覆盖（如重写生成的配置文件）：设置 overwrite=True（先备份，语法检查失败自动回滚）。",
    {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "目标文件路径（父目录不存在时自动创建）"},
                "content": {"type": "string", "description": "完整文件内容（文本，UTF-8）"},
                "overwrite": {
                    "type": "boolean",
                    "description": "文件已存在时是否覆盖。默认 False——返回 proposal 而不写入",
                    "default": False,
                },
            },
            "required": ["filepath", "content"],
        },
    _safe_write,
)


ToolStatsTool = make_tool(
    "tool_stats",
    "查看工具调用统计：每个工具的调用次数和总调用数。纯内存计数器。",
    {"type": "object", "properties": {}, "required": []},
    _tool_stats_snap,
    io_bound=False,
)


ShellExecTool = make_tool(
    "shell_exec",
    "严格白名单命令执行器。仅用于测试/构建类命令，shell=False 执行，带 cwd 限制、超时和输出截断。pip install、make 等高风险命令默认只提示，需 allow_high_risk=true 才执行。",
    {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "要执行的命令字符串"},
                "project_dir": {
                    "type": "string",
                    "description": "执行目录，必须位于当前工作目录内",
                    "default": ".",
                },
                "timeout": {"type": "integer", "description": "超时秒数，默认 120", "default": 120},
                "max_lines": {"type": "integer", "description": "输出最大行数，默认 500", "default": 500},
                "dry_run": {"type": "boolean", "description": "只校验不执行", "default": False},
                "allow_high_risk": {
                    "type": "boolean",
                    "description": "允许 pip install/make 等高风险白名单命令",
                    "default": False,
                },
            },
            "required": ["cmd"],
        },
    _shell_exec_run,
)


OpLogTool = make_tool(
    "op_log",
    "查询本地工具调用审计日志。action=recent/errors/file/stats。日志只记录参数摘要、文件路径、结果和耗时，不保存完整敏感参数。",
    {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "recent/errors/file/stats",
                    "default": "recent",
                },
                "limit": {"type": "integer", "description": "最多返回条数，默认 10", "default": 10},
                "file": {"type": "string", "description": "action=file 时的文件名/路径片段", "default": ""},
                "tool_name": {"type": "string", "description": "按工具名过滤 recent", "default": ""},
                "session_id": {"type": "string", "description": "按会话过滤 recent", "default": ""},
            },
            "required": [],
        },
    _op_log_query,
)


DbQueryTool = make_tool(
    "db_query",
    "只读查询 SQLite 数据库，不修改数据。参数化防注入，仅允许 SELECT/PRAGMA。",
    {
            "type": "object",
            "properties": {
                "db_path": {"type": "string", "description": "SQLite 数据库文件路径"},
                "sql": {"type": "string", "description": "SELECT 或 PRAGMA 查询语句"},
                "params": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": '查询参数列表，如 [42, "active"]',
                },
            },
            "required": ["db_path", "sql"],
        },
    _db_query,
)


DepScanTool = make_tool(
    "dep_scan",
    "扫描 Python 项目 import 依赖图，检测循环引用。含超时保护。",
    {
            "type": "object",
            "properties": {
                "project_dir": {
                    "type": "string",
                    "description": "项目根目录，默认当前目录",
                },
            },
            "required": [],
        },
    _dep_scan,
)


FileRemoveTool = make_tool(
    "file_remove",
    "【替代 del/rmdir——首选】删除文件或目录，自带沙箱和批量确认。比 shell del 多一层路径保护，比 Python os.remove 多一层批量拦截。目录超过 50 个文件时返回提案，需 confirm=true 确认。",
    {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件或目录路径"},
                "confirm": {
                    "type": "boolean",
                    "description": "目录删除需显式确认",
                    "default": False,
                },
            },
            "required": ["path"],
        },
    _file_remove,
)


FileMoveTool = make_tool(
    "file_move",
    "【批量移动文件/目录首选】将多个文件或目录移动到目标目录。同分区内原子 rename（瞬间完成），跨分区自动 copy+delete。适合重构代码结构、整理目录。避免 agent 用 shell_exec mv 逐文件移动导致超时。",
    {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要移动的源文件/目录路径列表",
                },
                "dest": {"type": "string", "description": "目标目录路径（会自动创建）"},
                "overwrite": {
                    "type": "boolean",
                    "description": "是否覆盖目标已存在的文件",
                    "default": False,
                },
            },
            "required": ["sources", "dest"],
        },
    _file_move,
)


# ══ codegraph ══

CodeIndexTool = make_tool(
    "code_index",
    "建索引—后续所有符号/调用链查询秒回。一次性投入 3–15s，免去反复 safe_read+rg_search 拼答案的分钟级耗时。索引在 .codegraph/codegraph.db，支持增量（跳过未改文件）。",
    {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string", "description": "项目根目录路径"},
            "incremental": {"type": "boolean", "description": "增量索引（跳过未改文件），默认 false", "default": False},
        },
        "required": ["project_dir"],
    },
    _code_index,
)


CodeExploreTool = make_tool(
    "code_explore",
    "🔍 符号/调用链秒查。问「X 在哪」「谁调了 X」「从 A 到 B 的链路」一句话即得结构化答案。前提：先跑 code_index。查不到时看 hint 改进查询词；若符号是日志文本/配置值/注释关键词则 fallback rg_search。",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "自然语言或符号名，如 'safe_edit 在哪' 或 '从 load 到 add_llm_tools 的调用链'"},
            "project_dir": {"type": "string", "description": "项目根目录，默认当前目录", "default": "."},
        },
        "required": ["query"],
    },
    _code_explore,
)


CodeDiffImpactTool = make_tool(
    "code_diff_impact",
    "📊 改代码前必查——谁调了你改的符号？BFS 追踪调用者链（max_depth 默认 3）。结果可直接构造成 edits 列表喂给 multi_edit 批量原子修。不适合查单个符号定义（用 code_explore）。",
    {
        "type": "object",
        "properties": {
            "filepaths": {"type": "array", "items": {"type": "string"}, "description": "变更的文件路径列表"},
            "max_depth": {"type": "integer", "description": "BFS 最大深度，默认 3", "default": 3},
            "project_dir": {"type": "string", "description": "项目根目录，须与 code_index 时传入的目录一致，默认当前目录", "default": "."},
        },
        "required": ["filepaths"],
    },
    _code_diff_impact,
)


CodePackTool = make_tool(
    "code_pack",
    "📦 修 bug 前拿 N 层调用链源码打包。以符号为起点按 callers/callees/both 展开（depth 默认 2），上限 2000 行。不适合查符号定义（用 code_explore，更快）。",
    {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "目标符号名（如 'Main._heal_inactivated_tools'）"},
            "depth": {"type": "integer", "description": "展开层数，默认 2", "default": 2},
            "mode": {"type": "string", "description": "callers / callees / both，默认 both", "default": "both"},
            "project_dir": {"type": "string", "description": "项目根目录，须与 code_index 时传入的目录一致，默认当前目录", "default": "."},
        },
        "required": ["target"],
    },
    _code_pack,
)


CodeStatusTool = make_tool(
    "code_status",
    "🩺 索引健康检查——code_explore 查不到时调我排障。返回文件数/符号数/边数/上次索引时间/DB 大小/缺失的 grammar。索引正常时直接调 code_explore。",
    {
        "type": "object",
        "properties": {
            "project_dir": {"type": "string", "description": "项目根目录，须与 code_index 时传入的目录一致，默认当前目录", "default": "."},
        },
        "required": [],
    },
    _code_status,
)


SymbolRenameTool = make_tool(
    "symbol_rename",
    "Python 符号重命名。只替换 Python NAME token（不碰字符串/注释），默认 dry_run 预览。需先跑 code_index。dry_run=false 时通过 multi_edit 原子应用；多文件重命名需 confirm_multi_file=true 确认。",
    {
        "type": "object",
        "properties": {
            "old": {"type": "string", "description": "旧符号名，如 _auth_guard 或 Class.method"},
            "new": {"type": "string", "description": "新符号名"},
            "project_dir": {"type": "string", "description": "项目根目录，默认当前目录", "default": "."},
            "dry_run": {"type": "boolean", "description": "是否仅预览，默认 true", "default": True},
            "confirm_multi_file": {
                "type": "boolean",
                "description": "多文件重命名时需设为 true 确认，dry_run 预览后使用",
                "default": False,
            },
        },
        "required": ["old", "new"],
    },
    _symbol_rename_run,
)


# ═══════════════════════════════════════════════════════════
# Tool groups and registry
# ═══════════════════════════════════════════════════════════

TOOL_GROUPS: dict[str, list[str]] = {
    "安全编辑链": [
        "safe_edit",
        "safe_rollback",
        "safe_backups",
        "file_patch",
        "file_preview",
        "safe_write",
        "syntax_check",
        "lint_runner",
        "test_runner",
        "multi_edit",
    ],
    "Git & GitHub": [
        "git_status",
        "git_diff",
        "git_log",
        "git_commit",
        "git_branch",
        "git_remote",
        "git_push",
        "gh_pr",
        "gh_issue",
        "gh_release",
        "gh_repo",
    ],
    "文件系统": [
        "es_search",
        "rg_search",
        "dir_tree",
        "dir_list",
        "file_diff",
        "file_hash",
        "file_zip",
        "file_unzip",
        "disk_info",
        "file_remove",
        "file_move",
        "config_diff",
        "safe_read",
    ],
    "系统信息": ["port_check", "proc_list", "sys_snapshot", "tool_stats"],
    "执行与审计": ["shell_exec", "op_log"],
    "网络": ["http_get", "http_post", "http_download"],
    "文本处理": [
        "html_extract",
        "json_query",
        "text_filter",
        "diff_strings",
        "csv_parse",
        "csv_gen",
        "md_strip",
        "log_parse",
    ],
    "编码/时间（合并）": [
        "encode_decode",
        "time",
    ],
    "扩展": [
        "semver_compare",
        "uuid_gen",
        "project_init",
        "git_changelog",
        "db_query",
        "dep_scan",
    ],
    "代码理解": [
        "code_index",
        "code_explore",
        "code_diff_impact",
        "code_pack",
        "code_status",
        "symbol_rename",
    ],
}

_ALL_TOOLS = {
    "safe_edit": SafeEditTool,
    "safe_rollback": SafeRollbackTool,
    "safe_backups": SafeBackupsTool,
    "file_patch": FilePatchTool,
    "file_preview": FilePreviewTool,
    "safe_write": SafeWriteTool,
    "syntax_check": SyntaxCheckTool,
    "lint_runner": LintRunnerTool,
    "test_runner": TestRunnerTool,
    "multi_edit": MultiEditTool,
    "encode_decode": EncodeDecodeTool,
    "time": TimeTool,
    "git_status": GitStatusTool,
    "git_diff": GitDiffTool,
    "git_log": GitLogTool,
    "git_commit": GitCommitTool,
    "git_branch": GitBranchTool,
    "git_remote": GitRemoteTool,
    "git_push": GitPushTool,
    "gh_pr": GhPrTool,
    "gh_issue": GhIssueTool,
    "gh_release": GhReleaseTool,
    "gh_repo": GhRepoTool,
    "es_search": EsSearchTool,
    "rg_search": RgSearchTool,
    "dir_tree": DirTreeTool,
    "dir_list": DirListTool,
    "file_diff": FileDiffTool,
    "file_hash": FileHashTool,
    "file_zip": FileZipTool,
    "file_unzip": FileUnzipTool,
    "disk_info": DiskInfoTool,
    "file_remove": FileRemoveTool,
    "file_move": FileMoveTool,
    "config_diff": ConfigDiffTool,
    "safe_read": FileReadTool,
    "port_check": PortCheckTool,
    "proc_list": ProcListTool,
    "sys_snapshot": SysSnapshotTool,
    "tool_stats": ToolStatsTool,
    "shell_exec": ShellExecTool,
    "op_log": OpLogTool,
    "http_get": HttpGetTool,
    "http_post": HttpPostTool,
    "http_download": HttpDownloadTool,
    "html_extract": HtmlExtractTool,
    "json_query": JsonQueryTool,
    "text_filter": TextFilterTool,
    "diff_strings": DiffStringsTool,
    "csv_parse": CsvParseTool,
    "csv_gen": CsvGenTool,
    "md_strip": MdStripTool,
    "log_parse": LogParseTool,
    "semver_compare": SemverTool,
    "uuid_gen": UuidGenTool,
    "project_init": ProjectInitTool,
    "git_changelog": GitChangelogTool,
    "db_query": DbQueryTool,
    "dep_scan": DepScanTool,
    "code_index": CodeIndexTool,
    "code_explore": CodeExploreTool,
    "code_diff_impact": CodeDiffImpactTool,
    "code_pack": CodePackTool,
    "code_status": CodeStatusTool,
    "symbol_rename": SymbolRenameTool,
}
