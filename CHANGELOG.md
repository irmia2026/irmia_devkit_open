# Changelog

## v2.6.4 — 全量 code review 修复：响应协议 / 备份生命周期 / 行号寻址编辑 / CI 日志

- **safe_edit 行号寻址**: 新增 `mode=insert_at_line`（`line` 后插入，`0`=文件开头）/ `delete_lines`（`start_line~end_line` 闭区间删除），走完整备份→语法检查→回滚链路；参数 `preserve_inner_indent` 更名 `align_whitespace`（语义不变）。
- **git_commit 修复**: >10 文件拦截的 options 从死胡同文案改为可执行 next_call（`force=true` / `files=[...]`）；新增 `files`（选择性暂存，拒绝绝对路径与 `..` 逃逸）与 `force` 参数；描述明示默认 `git add -A`。
- **gh_repo CI 日志**: 新增 `run_view` / `run_logs` action（`run_id` 参数），CI 失败可取日志尾部自诊断。
- **safe_read 行号**: 文本读取默认带行号前缀（`  123│ 内容`，新增 `line_numbers` 参数可关）；删除 4 个已弃用 schema 参数；`include_metadata` 默认改 false。
- **file_patch**: 新增 `occurrence` 参数消歧多处匹配；proposal 文案引导。
- **multi_edit**: 多处匹配错误透传结构化 `matches`（行号/列/预览，对齐 safe_edit），不再随异常丢弃。
- **备份生命周期**: 新增 `prune_backups`（每文件保留 10 份 + 总量 500MB LRU，`os.scandir` 实现零感开销）；patch 失败不再残留无意义备份。
- **dep_scan 修复**: 循环引用检测从事实上失效（图键与依赖命名空间不匹配）修复为可检出；排除目录扩展至 .venv/node_modules 等 10 个。
- **codegraph 性能**: `_resolve_references` 增加 `resolved=0` 过滤 + `executemany` 批量提交；`_ensure_db` DDL 幂等跳过（每路径一次）；`code_explore` 返回 `caller_locations`/`callee_locations` 引用位置。
- **http_get**: 默认 `format=markdown`（原 html 为 token 黑洞且无分页）；返回新增 `converter` 字段；html 截断附切换格式 hint；页面缓存加 300s TTL。
- **http_post**: schema 暴露 `timeout` 参数；data 描述与实际行为对齐。
- **http_download**: 描述明示仅存文件名、实际落沙箱 `~/.irmia/downloads/`。
- **unwrap 协议修复**: `ok:false` 且含额外字段时不再压扁丢弃（http_get 错误的 status/body 现在可见）。
- **git_smart**: `git_diff` 新增 `max_lines`（默认 500）截断 + `diff_truncated` 标记；`git_status` changes cap 200；`git_push` 预检改用传入的 remote（原硬编码 origin）。
- **db_query**: `fetchall` → `fetchmany(201)`，大表不再全量物化，附 `truncated` 标记；params schema 类型修正（原声明 string 数组与示例矛盾）。
- **port_check**: 实测返回 `latency_ms`（docstring 承诺已久）；移除误导性 next_call；scan 上限 256 端口。
- **shell_exec/test_runner**: timeout 统一钳制上限 600s；Windows 下 `npx`/`npm` 经 `shutil.which` 解析为 `.cmd` 全路径（原直接 FileNotFoundError）。
- **rg_search**: rg 路径匹配行截断 200 字符（与 Python fallback 对齐）；`context_lines` clamp ≤10；rg 加 `-m` 提前限量。
- **es_search**: Windows 无 es.exe 时默认搜索根改为用户目录（原遍历当前盘符根）；POSIX fallback 忽略 regex/whole_word/sort_by 时附 note 说明；文案笔误修复。
- **symbol_rename**: 索引后修改的文件触发 `stale_warning` 提示先增量重建索引。
- **lint_runner**: ruff/linter 探测结果 300s 模块级缓存，消除每次调用的探测子进程。
- **config_diff**: 单文件 10MB 上限；大 value 截断 500 字符。
- **dir_list**: 条目补 `mtime` 字段（描述承诺已久）。
- **op_log**: 审计写入移出事件循环线程（run_sync 线程池化）。
- **git_changelog**: 分类前缀扩展为 feat/fix/perf/refactor/docs/test/chore/build/ci 九类。
- **工程清理**: 删除死文件 `tools/_registry_split.py` 与无调用方的 `_detect_encoding` 别名；文档工具计数 64→65；`time` convert 空参返回明确错误（原静默返回 1970-01-01）。
- **编辑工具行号防呆**: safe_edit / file_patch / multi_edit 在精确匹配失败时，检测 old/new 是否所有行都带 safe_read 行号前缀（`  123│ ...`），是则自动剥除重试；精确匹配优先，文件字面含 `│` 的内容不受影响（有测试锁定）。
- **safe_read tail 行号修复（正确性）**: >1MB 文件的 tail 行号原先由采样估算的总行数推导，实测可漂移数万行，行号寻址编辑会删错行；改为精确统计（文件本有 10MB 上限，成本 ~50ms）。
- **估算值显式标记**: head/range 大文件路径的 `total_lines` 仍为采样估算，响应新增 `total_lines_estimated: true/false` 字段供 LLM 区分。
- **codegraph 索引过期提示**: code_explore / code_pack 的符号行号与打包源码来自索引时刻，索引后编辑过的文件会漂移；现做 mtime 探测，过期时返回 `index_stale` + `stale_warning`（引导 code_index incremental）。
- **next_call 协议统一**: 参数键 `args`/`params` 混用（8 处）统一为 `params`。
- **safe_backups 链路透名**: 备份条目新增 `backup_name` 别名（原 `file` 键保留），与 safe_rollback 参数名对齐。
- **code_explore/code_pack 路径提示**: 结果中的 file 为项目相对路径，新增 `project_dir` + `path_note` 字段引导拼接后再调 safe_read/safe_edit。
- **错误上下文格式统一**: syntax_check / lint_runner 的错误上下文从 `  87: code` 改为与 safe_read 一致的 `  87│ code` 格式，行号剥除防呆同步兼容 `→` 标记，全工具箱复制链路闭合。
- **测试**: 全量 678 passed、8 skipped（新增约 80 条回归用例）；ruff 零新增告警。

## v2.6.3 — http_get 分页翻页 / 嵌套函数缩进修复 / schema 一致性对齐

- **http_get 分页翻页**: 页大小 8000 字符，模块级 LRU 缓存（10 条），`offset` 参数切页；返回 `has_more` + `next_call` + `options` 三件套，agent 盲传即可翻页，不重复下载。
- **http_get review 修复**: 缓存加 `threading.Lock`；`offset` 负值校验；`_read_limited` 截断判断 `>=` 修复边界漏报；`_extract_metadata` BS4 import 提升到 `except ImportError`。
- **safe_edit/file_patch 修复**: 新增 `preserve_inner_indent` 参数（默认 True），缩进对齐改为 delta 平移法，保留嵌套 `def`/`class` 的内部缩进结构，修复替换时嵌套函数被压扁为同级的问题。
- **schema 一致性**: 21 处工具 schema 与函数签名不一致全部修复 — `file_zip` 参数名 `files`→`files_or_dir`（修复运行时 TypeError）、`csv_gen` 类型修正、6 个漏注册参数补全、13 个工具的 `default` 标注补全、`required` 列表对齐。
- **依赖整理**: `chardet` 提升为必装；`requirements.txt` 补全 `webfetch`/`codegraph`/`other` 可选依赖分组（trafilatura/markdownify/psutil/python-magic）。
- **测试**: 19 passed (http_get)。

## v2.6.2 — http_get HTML→Markdown 正文提取

- **http_get 增强**: 新增 `format` 参数（html|markdown|text），`extract` 参数（trafilatura 正文提取去广告）；三级降级（trafilatura→markdownify→BS4 纯文本），零依赖也能工作。
- **http_get 修复**: `format=html` 模式下 truncated 标记逻辑修正，修复 body 5KB-5MB 区间截断漏报。
- **可选依赖**: `webfetch` 扩展推荐 trafilatura/markdownify/beautifulsoup4/lxml，`pip install irmia-devkit[webfetch]` 一键安装。
- **测试**: 15 passed (http_get)，覆盖率 format=html/markdown/text + extract=true/false + 格式校验。

## v2.6.1 — FTS 数据完整性 / TOCTOU / 编码 / 回滚安全修复

- **codegraph 修复**: 增量索引时 FTS 插入失败不再静默吞异常，改为标记后于收尾处全量重建 FTS，防止全文搜索永久漏结果。
- **codegraph 测试**: 新增 `TestFtsIncrementalConsistency` 回归测试，覆盖 FTS 脱节→重建恢复的完整路径。
- **multi_edit 修复**: 备份操作提前至语法检查之前，消除 TOCTOU 竞态窗口。
- **safe_edit 修复**: 写入统一使用 UTF-8 编码，避免 GBK 文件写入 emoji 等字符时 `UnicodeEncodeError`；`safe_rollback` 回滚前自动创建 `prerollback.bak` 快照，回滚可撤销。
- **测试**: 全量 593 passed、10 skipped。

## v2.6.0 — 增强文件读取 + 全量安全审查修复

- **新工具**: `safe_read` — 增强版安全文件读取，替代 AstrBot 原生 `file_read`。支持编码自动检测、二进制文件 hex 预览、head/tail、行号范围、目录递归读取、代码骨架提取；失败路径接入项目 proposal 协议，引导 LLM 下一步操作。
- **安全修复**: SSRF 校验增强，拦截 IPv4 八进制/十六进制/短写法绕过（如 `0177.0.0.1`、`0x7f.0.0.1`、`127.1`）。
- **安全修复**: `shell_exec` / `test_runner` 增加命令参数路径校验，禁止参数指向 cwd 外绝对路径或通过 `..` 逃逸。
- **安全修复**: `file_remove` 目录删除改用 `os.walk(followlinks=False)`，不再跟随 symlink 进入外部目录。
- **安全修复**: `file_zip` 打包改用 `os.walk(followlinks=False)` 并跳过 symlink，防止打包沙箱外文件。
- **性能修复**: `safe_write` 覆盖已存在文件前预览读取限制为 100KB，编码检测改用 32KB 采样，避免大文件全量读入内存。
- **性能修复**: `safe_read` tail 模式改为从文件尾部倒读字节块，skeleton 模式限制 512KB/5000 行，行范围模式对大文件停止 EOF 全扫描。
- **Bug 修复**: `safe_read` 目录 `recursive=True` 时 `max_depth` 实际只生效一层的问题。
- **Bug 修复**: `sys_snapshot` 缓存变量 `UnboundLocalError`（补充 `global` 声明）。
- **工程清理**: 移除误提交的 `docs/file_read_design.md`，`docs/` 加入 `.gitignore`。
- **文档同步**: README / README_EN / metadata 工具数更新为 64，版本号统一为 2.6.0。
- **测试**: 全量测试 209 passed、8 skipped；新增 `safe_read`、`safe_write` 大文件预览、`shell_exec` 参数逃逸等回归用例。

## v2.5.7 — 配置页重构 + Release 安装包补齐

- **配置页重构**: 群配置页改为卡片化布局，支持真实 QQ 群列表、群级工具组开关、单工具禁用和批量操作。
- **视觉优化**: 新增柔和高饱和配色、明暗主题切换，并使用裁切后的本地插件 Logo 作为配置页头像。
- **GitHub PR 修复**: 新增 `gh_pr review`，review 正文统一通过 `--body-file` 传递，避免多行内容被 shell 截断。
- **配置说明**: 明确群配置 `extra_admin_ids` 覆盖默认值而非叠加；配置结构重组后建议在 WebUI 中重新保存一次。
- **Release 补齐**: 发行版附加可直接下载安装的插件 ZIP 包。
- **测试**: 相关子集验证 28 passed、1 warning。

## v2.5.6 — codegraph 性能修复 + review 安全加固

- **op_log 修复**: `_redact_value` 子串匹配改为下划线分词语义匹配，修复 `keyboard`/`monkey` 等参数被 `key` 误脱敏；`_result_status` 非 JSON 字符串返回 `error` 而非 `ok`；`_INITIALIZED_DB` 类型修复（Path→str），修复 Python 3.12 下 `Path == str` 永远 False 导致每次 `record()` 重复建表。

- **codegraph 索引性能修复**: `_resolve_references` Phase 2（跨文件 import 解析）从 O(N×M) 次 SQL 查询改为预建哈希索引 O(1) 查表，修复 500+ 文件项目索引超时问题。astrbot-fork（504 文件/4917 符号/75459 边）从 >120s 超时恢复到 3.8s。
- **codegraph P0 Bug 修复（Claude 审查）**: `_code_diff_impact`/`_code_pack`/`_code_status` 增加 `project_dir` 参数，修复与 `code_index` 路径不一致导致的"索引为空"静默误报；`_extract_python` source 截断上限 500→6000 字符，`_row_to_dict` 补全 `source_truncated`/`total_lines` 透传；增量索引增加已删除文件清理逻辑，确保 `mtimes`/`symbols`/`edges`/`fts` 同步。
- **codegraph 性能优化（无效回退）**: 尝试 ThreadPool/ProcessPool 自适应并行，Windows 上线程调度开销 > 解析收益，恢复单线程。流式写入每 50 文件批处理。超大文件（>1MB）跳过索引。
- **安全加固**: `safe_write.py` 路径穿越检查在 `Path()` 解析前执行，防止 `Path.normalize()` 消除 `..`；`_extract_file_worker` 增加 `relative_to` ValueError 保护。
- **Review 修复**: `FakeCodeGraph` mock 签名同步 `project_dir` 参数；进度日志 `result` 变量 NameError 修复。
- **测试**: 180 passed、8 skipped。

## v2.5.5 — MCP 改动同步 + 安全修复 + 文档对齐

- **MCP 改动同步（本插件适配）**: 新增 `safe_write` 新建/整体覆盖写入工具；删除非核心工具 `file_watch`、`svg_render`、`json_schema_val` 和 `regex_test`/`regex_replace`；合并 `base64_`+`hex_`+`url_` 为 `encode_decode`，合并 `time_now`+`time_convert`+`time_diff` 为 `time`。工具数 71→63，工具组 11→10。
- **Bug 修复（从 MCP 版移植）**: `shell_exec` `_DANGEROUS_RAW` 追加 `&` 和 `%`；`symbol_rename` 跨文件重命名改用 `proposal_reply()` 协议；`http_get` HTTPError 返回增加 `status` 字段；`syntax_check` 编译器缺失返回 `ok=False`；`file_remove` 系统目录黑名单从 `C:/Windows` 收窄到 `System32`+`SysWOW64`。
- **真实安全问题修复**: `shell_exec` 禁止带路径的命令（防止 `/malicious/python` 被当作 `python` 放行）；`rg_search` Python fallback 增加 ReDoS 防护（pattern 长度 1000、嵌套量词检测、搜索步数上限 50 万）；`op_log` 扩展敏感词（`passwd`/`pwd`/`private_key`/`credential`/`api_key`）。
- **文档与配置同步**: README、README_EN、ARCHITECTURE、`_conf_schema.json`、metadata 全面更新到 63 工具/10 组，移除已删工具的残留引用。
- **测试**: 新增 `test_safe_write.py` 覆盖新建/覆盖/语法错误保留/回滚/系统目录拦截；`test_auth.py` 工具名同步；`test_registry.py` 计数改为 63；`test_rg_search.py` 新增 ReDoS 防护用例；`test_op_log.py` 新增 api_key/private_key 脱敏用例。当前本地验证 180 passed、8 skipped。

## v2.5.0 — 测试/执行/审计/重命名能力补完

- **新工具 — 安全编辑链**: 新增 `test_runner`（pytest/go test/cargo test/jest 统一封装）和 `multi_edit`（原子多文件编辑，失败全量回滚，同文件顺序应用语义已文档化），补齐 syntax_check → lint_runner → test_runner 的验证链路。
- **新工具 — 执行与审计组**: 新增 `shell_exec` 严格白名单命令执行器（七层防御：白名单→子命令→危险字符→shell=False→cwd限制→COLUMNS修复→高风险确认；移除 `go run`，已添加 APPDATA/LOCALAPPDATA/CARGO_HOME/GOPATH/NODE_PATH 环境变量）和 `op_log` SQLite 工具调用审计日志（recent/errors/file/stats 查询，session 自动轮转，敏感参数脱敏）。
- **新工具 — 代码理解组**: 新增 `symbol_rename`，基于 codegraph 索引和 Python `tokenize` 做符号重命名，默认 dry-run，多文件重命名需 `confirm_multi_file=true` 确认，只替换 NAME token，不改字符串和注释。
- **codegraph 泄漏修复落地**: `_registry.py` 的 5 个 `_code_*` 包装函数统一在 `finally` 中关闭 `CodeGraph` 连接，修正 v2.4.5 changelog 曾声称已修但包装层仍泄漏的问题。
- **审计接入**: `protect_tool` 在授权工具调用完成后 best-effort 写入 `op_log`，鉴权失败不污染审计库，审计失败不影响原工具返回。
- **受限环境兼容**: `safe_edit` 默认备份目录在用户目录不可写时降级到临时目录 `.irmia/backups`；HTTP SSRF 测试改为 mock 公网 DNS，避免本机 DNS 污染导致误判。
- **Review 修复 (R1+R2)**:
  - C1: 移除 `go run` 白名单；H1: 补全 Windows 环境变量（APPDATA/LOCALAPPDATA/CARGO_HOME/GOPATH/NODE_PATH）；H3: 临时文件写入系统 temp 目录；M1: 修复 shlex 冗余引号剥离；M4: jest JSON 健壮解析；M5/L4: multi_edit 同文件编辑语义文档化 + `replacements_made` 字段；L2: op_log 拆分 `_ensure_db` 单次建表
  - C2: SymbolRenameTool 补 `confirm_multi_file` 参数（schema + call 方法 + description），修复多文件重命名安全阀；H4: `_unwrap` 扩展透传 stdout/stderr/cmd 诊断字段，shell_exec 超时不丢失输出；H5: op_log stats 移除 `db_path`/`session_id` 信息泄露
- **文档与配置同步**: 工具数 66→71，工具组 10→11，新增「执行与审计」组；同步 README、README_En、ARCHITECTURE、配置 schema、metadata 和版本号。
- **测试扩展**: 新增 shell_exec/test_runner/multi_edit/op_log/symbol_rename 用例；当前本地验证 174 passed、8 skipped。

## v2.4.5 — 语义索引 5 工具 + gh_cli 自动定位 + 文档补完

- **新工具 — 代码理解组**: 新增 `code_index` 建语义索引、`code_explore` 符号搜索与调用链追踪、`code_diff_impact` 变更波及分析、`code_pack` 精准上下文打包、`code_status` 索引健康检查。Python AST 零依赖解析 + 可选 tree-sitter 多语言（JS/TS/Go/Rust/Java/C/C++），SQLite FTS5 存储，一次调用即答案。64→67 工具，9 组→10 组
- **语义索引引擎稳定**: 修复 SQLite 连接泄漏和增量索引时序问题，扩展多语言支持（Python 全框架 + JS/TS/Java/Rust）
- **safe_edit 多匹配消歧**: 多处匹配时不再报错退出，列出所有候选位置供选择
- **错误返回防截断**: 语义索引工具在未建索引或查无结果时返回完整提示，不再被截断为模糊报错
- **gh_cli 自动定位**: 移除本地路径硬编码，改为全盘自动搜索 gh.exe + 未找到时给出安装指引
- **缺依赖友好**: `html_extract`、`syntax_check`、语义索引、`config_diff` 缺少可选依赖时返回 pip install 指引而非报错
- **测试扩展**: 新增 27 个语义索引用例，总用例 120→147
- **文档查漏**: README 工具组数/工具数修正、tree-sitter 可选依赖说明、README_EN 同步；`.gitignore` 补 SQLite WAL 和索引目录规则；全项目陈旧引用 13 处修复

## v2.4.0 — 代码语义索引 + L2 原生工具摘除恢复

- **新工具 (P0)**: 新增 `code_index` / `code_explore` — Python AST 解析 + SQLite FTS5 存储，三级搜索（LIKE → FTS5 → hint），5 种边类型（calls/imports/extends/references/overrides），后处理引用消解。一次调用即答案，不退到 rg_search 手动拼凑。61→63 工具，9→10 组（新增「代码理解」组）
- **L2 原生工具摘除恢复**: `_auth_guard` 在授权用户路径摘除有 devkit 替代品的 AstrBot 原生工具（`astrbot_file_edit_tool`→`safe_edit`、`astrbot_grep_tool`→`rg_search`），仅当替代品确实可用时才摘除
- **Agent 友好**: tool description 改为命令式使用指南（何时调用、不要先 rg_search、返回是 Read-equivalent），移除"用 file_read 查看"反模式 hint
- **缺陷修复**: `_unparse_attr` 返回类型修复（Bug1）、FTS5 索引去源码噪声（Bug2）、SQLite 连接泄漏修复、`core/__init__.py` 补全

## v2.3.7 — 工具管理权收回 + 防御上线

- **工具管理权收回**: 不再覆写 `handler_module_path` 强制对齐 Astrbot，改为利用 `startswith` 方向差异——`_PLUGIN_MODULE_PREFIX` 不带 `.main` 后缀，使 `turn_off_plugin` 能正确停用、`_unbind_plugin` 不被误删
- **防御**: `handler_module_path` 前缀避坑 → `__init__` 自愈（`_heal_inactivated_tools` + DB 清理）→ `_auth_guard` 请求级兜底 → `star_map` alias 修复 WebUI 来源显示
- **上游问题**: 定位并报告 4 个 AstrBot 上游 bug（`config.py` 停用时无差别 reload、`startswith` 方向反 ×2、`turn_on_plugin` 重启路径缺失、`handler_module_path` 前缀不一致）

## v2.3.6 — 群级 WebUI + handler_module_path 修正

- **群级权限配置 (PR #4)**: 新增 `devkit_web.py` Web 管理面板 — 按群聊独立配置工具箱权限（额外管理员、工具组开关），支持全局管理员和群级额外管理员双层鉴权
- **配置**: 新增 `group_config_enabled` 开关（默认关闭），`config.json` / `_conf_schema.json` 同步
- **前端**: `pages/settings/` — 蓝白主题 WebUI，群列表侧边栏 + 配置面板，XSS 防护，确认弹窗，Toast 提示
- **AstrBot 兼容修复**: `handler_module_path` 从子模块路径（`astrbot_plugin_irmia_devkit.tools.xxx`）改为插件根路径（`data.plugins.astrbot_plugin_irmia_devkit`），对齐 `star_manager` 的 deactivate/activate 路径匹配逻辑，修复插件禁用/启用后工具被意外关闭的问题
- **上游问题**: 发现并报告 AstrBot `star_manager.py` 中 `plugin.module_path.startswith(mp)` 的比较方向反了（应 `mp.startswith(plugin.module_path)`），导致插件禁用/启用时工具状态持久化损坏；含完整 6 步复现路径和插件侧 workaround
- **日志优化**: L2 摘除实验（已回退）；`_auth_guard` 回到纯 L1 模式，管理员路径零开销

## v2.3.5 — 双层权限防线 + 代码审查修复

- **权限防线 (P0)**: 新增 `tools/_auth.py` 模块 — `protect_tool()` 包裹每个工具的 `call()` 执行前鉴权；`build_allowed_ids()` 自动读取 AstrBot 全局管理员列表 + 插件额外配置
- **钩子清理 (P0)**: `main.py` 新增 `_auth_guard` — `on_llm_request` 钩子按 `handler_module_path` 清空本插件工具，非管理员 LLM 不可见
- **配置**: `config.json` / `_conf_schema.json` 新增 `owner_sid`、`allowed_ids` 字段
- **测试**: 新增 `test_auth.py` — 20 用例覆盖 `protect_tool` 放行/拦截/异常、`build_allowed_ids` 合并/降级、Layer 1 过滤逻辑（共 120 用例）
- **代码审查修复**: 三轮审查修复 18 项问题 — `_allowed_ids` 缓存同步、`_rebuild_func_tool` 静默失败→告警、`http_download` 反模式消除、`syntax_check` 异常限窄+TimeoutExpired、`rg_search` whole_word `re.escape`、死 import 清理、`flag_map` 提取常量等
- **交叉验证修复**: 第五轮全量审查 + AstrBot 源码交叉比对，修复 25 项 — `safe_edit` 回滚+备份异常捕获、`regex_tester` `replace()` 超时保护、`gh_cli` 临时文件泄漏、`es_search` regex+ext 冲突、`file_zip` 符号链接 SymlinkGuard、`rg_search` 错误区分、`_auth` 多配置管理员同步、`port_check` socket 初始化、`csv_utils` 行上限、`semver` v 前缀、`log_parse` 精确匹配等
- **API 规范化**: `_registry.py` 移除无效 `func_type` 字段；`_auth.py`/`main.py` 改用 `event.is_admin()` 替代 `getattr`
- **缺陷**: 零存量已知缺陷

## v2.3.0 — 基础层补完 (60→61)

- **新工具**: `rg_search` — 文件内容级代码搜索引擎（ripgrep + Python fallback），支持正则、全词匹配、文件类型过滤、上下文展示
- **编辑增强 (P0)**: `safe_edit`/`file_patch` 加 whitespace-tolerant 匹配（对标 Aider），精确匹配失败时自动对齐行首空白重试
- **上下文赋能 (P0)**: `rg_search` 支持 `context_lines` 参数（rg -C），`lint_runner` 返回错误行前后代码片段，`syntax_check` 语法错误附带上下文标记
- **Git 增强 (P0)**: `git_diff` 返回结构化统计（files_changed/added/removed/total_changes）
- **linter fallback**: `lint_runner` 的 ruff↔pylint 互 fallback——首选未安装时自动切换备用 linter
- **架构重构 (P1)**: 提取 `_run_cmd()` 统一 subprocess 封装，7 个文件收口；`http_get`/`http_download` 共享 `make_opener`/`check_url`；`config_diff`/`project_init`/`dep_scan` 统一 encoding fallback
- **psutil 条件引入 (P1)**: `proc_list` 优先使用 psutil（跨平台 + 性能优化），不可用时 fallback 原有实现
- **防御加固 (P2)**: `json_query` 加递归深度限制 (50)、`dir_tree`/`dir_list` 共享 `SymlinkGuard`、`safe_edit` 备份前预检磁盘空间、`db_query` SQLite URI 跨平台路径修复
- **测试**: 从 51 用例扩展到 100 用例（+rg_search、+lint_runner fallback、+file_remove 沙箱、+syntax_check context、+registry 一致性检查、+helpers unwrap 透传）
- **文档**: 新增 `ARCHITECTURE.md`（模块图/数据流/新增工具指南/安全架构）、`README_EN.md`
- **修复**: `file_patch` 缺 `difflib` import → NameError、`_registry` `TimeDiffTool` 重复定义、`_parse_rg_output` 冒号解析跨平台 bug、`main.py` config 路径改用 `StarTools.get_data_dir()`
- **依赖**: 新增 `rg_search` 可选依赖 ripgrep（未安装时 Python fallback）

## v2.2.0 — 统一交互协议

- **proposal 协议**: 新增 `proposal_reply()` 工厂函数，17 个工具的失败/歧义返回统一为 `{proposal, evidence, options, next_call}` 四字段结构化提案。覆盖 `safe_edit`、`git_commit`、`syntax_check`、`port_check`、`es_search`、`lint_runner`、`dep_scan`、`config_diff`、`log_parse`、`text_filter` 等
- **测试**: 新建 `tests/` 目录，51 个 pytest 用例覆盖 SSRF、safe_edit 安全链、Zip-slip、SQL 注入、正则回溯、helpers 协议、git commit 守卫
- **AstrBot 合规**: `requirements.txt`、`astrbot_version`、`short_desc`、`support_platforms`、`logo.png`
- **ruff**: 全项目格式化 + `pyproject.toml` 配置
- **修复**: `_http_utils` 域名路径 NameError、`sys_snapshot` `_extract_mb` 缺失、`_conf_schema.json` trailing comma、`safe_edit` 接入 `backup_dir` 配置、HTTP redirect SSRF 重新校验、gh_cli try/finally 临时文件清理、`human_size` TB/PB 兜底、备份文件名微秒防撞

## v2.0.0 — 生态扩展 (60→63)

- **新工具**: `tool_stats` 调用统计、`db_query` SQLite 只读查询（参数化防注入）、`dep_scan` Python import 依赖图 + 循环引用检测
- **优雅打磨**: tool_stats 注入率 100%、`_registry.py` 9 组分区注释、README 快速索引

## v1.8 — 质量层 (59→60)

- **新工具**: `lint_runner` — ruff/pylint/eslint 代码质量检查，与 `syntax_check` 互补

## v1.7 — 决策层 (57→59)

- **新工具**: `project_init` 项目结构扫描（detect 语言/框架/依赖）、`git_changelog` git log 语义分组

## v1.6 — 架构收口 + 安全加固 (54→57)

- **架构**: GhCliTool 拆为 `gh_pr`/`gh_issue`/`gh_release`/`gh_repo` 4 独立工具；注册表外移至 `tools/_registry.py`，main.py 1580→113 行
- **安全**: IPv4-mapped-IPv6 SSRF 检查、正则嵌套量词拒绝（防 ReDoS）
- **质量**: file_watch 每轮 rglob 重扫、UA 统一、bare except 加错误信息

## v1.5 — 新工具 (49→54)

- **新工具**: `log_parse` 日志解析、`file_watch` 文件监控、`config_diff` 配置文件 key 级对比、`svg_render` SVG→PNG、`json_schema_val` JSON Schema 校验
- **增强**: `text_filter` 新增 `regex=True` 正则模式

## v1.4 — 质量打磨 (41→49)

- **工具拆分**: `encode_utils` 拆为 6 独立工具（base64/url/hex encode/decode）；`time_utils` 拆为 4 独立工具（now/ts_to_iso/iso_to_ts/time_diff）
- **提取**: `_helpers.py` 共享辅助模块
- **修复**: `syntax_check` Python GBK fallback

## v1.3 — 跨平台 (41)

- **Linux 回退**: `proc_list` ps aux、`disk_info` POSIX、`sys_snapshot` /proc
- **降级**: `html_extract` lxml→html.parser fallback

## v1.2.1 — Bugfix (41)

- **修复**: `file_patch` 编码保留（GBK 读→UTF-8 写回）、清理 `_ok` 死代码
- **文档**: README Python ≥3.10、.gitignore 补全

## v1.2.0 — 初始发布 (42→41)

- **配置系统**: `config.json` + `_conf_schema.json` + `tools/config.py`
- **路径脱敏**: 移除 5 处硬编码路径
- **安全修复**: SSRF DNS 重绑定、es_search 参数索引、json_query [-1] 正则、opencode 环境变量白名单
- **Git**: 7 工具 description 加"替代原生命令"前缀
- **移除**: opencode 工具及所有残留引用
