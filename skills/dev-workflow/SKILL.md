---
name: dev-workflow
description: >
  收到编码任务时强制走安全工作流。触发：写代码、改代码、修bug、重构、实现功能、修改文件。
  核心原则：先确认后执行、自动备份回滚、语法门禁。
  可用工具：safe_edit、safe_read、multi_edit、safe_rollback、safe_backups、file_patch、
  git_*、syntax_check、lint_runner、test_runner、file_diff、es_search、rg_search、
  dir_tree、dir_list、gh_pr、gh_issue、dep_scan、code_*、symbol_rename。
---

# 开发工作流

## 核心原则

```
一边确认一边推进。
该停的时候停（方案阶段、计划阶段、审查后），
该走的时候走（小修改、已验证的步骤）。
不等用户催，也不用写死的路由表。
```

## 改代码之前

1. `git_status` — 确认工作区干净，无意外修改
2. `git_branch` — 确认在正确的分支上
3. `safe_backups` — 看一眼有没有旧备份可用
4. `safe_read` — 改前先读文件确认当前内容（支持自动编码检测、head/tail/行范围/hex）
5. 文件搜索：`es_search`（按文件名/扩展名/大小）→ `rg_search`（按代码内容）→ `dir_tree`（按目录层级浏览）
6. 代码理解 → 走「代码智能工具组」决策树（见下方完整章节）

## 节奏感

- **需求模糊** → 先 brainstorming 探索方案，确认后再动
- **需求清晰但复杂** → 先 writing-plans 拆任务，确认后再执行
- **简单修改** → 直接 safe_edit
- **审完** → 问是否修 Critical/High，修完自动 commit push

不需要路由表，不需要流水线引擎。用判断力。

## safe_edit 铁律

- 改代码**必须**用 `safe_edit`，禁止 `file_write` 或裸 `file_patch`
- **同文件多处修改 / 跨文件批量改** → 用 `multi_edit`（原子提交，继承语法检查和回滚能力）
- 改前 `git status`，改后 `git diff --staged`
- `safe_edit` 自动跑 `syntax_check`，语法错就分析根因重新改
- 语法失败自动回滚，不要手动恢复
- 回滚后工具返回 `proposal` 和 `options`——直接看提案，选一个选项，重试
- 代码改完后用 `lint_runner` 检查质量（ruff→pylint 自动 fallback）
- 想回到之前版本 → `safe_rollback`

## git 提交

- commit message 按 `fix:` / `feat:` / `refactor:` 规范
- `git diff --cached` 自查无敏感内容
- 大改动前备份到安全目录（如插件的 backups/ 目录）
- 推送后如需创建 PR → 用 `gh_pr`

## 代码智能工具组

> 图优先，grep 兜底。能用图就不要 rg_search。

### 心智模型

```
code_index（一次性建索引）
  │
  ├─ 查符号定义/调用者 ──→ code_explore
  ├─ 修 bug 要完整上下文 ──→ code_pack
  ├─ 改完了查影响范围 ──→ code_diff_impact
  └─ explore 返回空 ──→ code_status（再 fallback rg_search）
```

### 决策树

| 意图 | 用这个 |
|------|--------|
| 第一次进项目 | `code_index` 全量建索引；后续文件有改动时 `code_index(incremental=true)` 秒级更新 |
| 「X 在哪定义」「谁调了 X」 | `code_explore("X")` |
| 修 X 的 bug，要 X + 依赖链全部源码 | `code_pack("X", depth=2)` |
| 刚改了文件 Y，会影响什么 | `code_diff_impact(["Y"])` |
| explore 查不到，怀疑索引坏了 | `code_status` |
| 索引正常但 explore 查不到 | fallback → `rg_search` |

### 铁律

1. **图优先** — 能 code_explore 就不要 rg_search
2. **建索引一次性** — 进项目全量 `code_index`，后续只改了几个文件用 `incremental=true` 增量更新
3. **失败先查 status** — explore 返回空 → 先 `code_status`，再怀疑查询词
4. **打包替代多次 explore** — 需要 3+ 符号源码才能理解流程 → 直接 `code_pack`
5. **改完必查影响** — commit 前 `code_diff_impact`，确认不炸隐藏调用者
6. **用符号名而非自然语言** — `_auth_guard` 而非「权限守卫怎么工作」

### 反模式

- ❌ 不建索引就调 explore
- ❌ 每查一个符号重新 code_index
- ❌ explore 失败直接 rg_search，不查 code_status
- ❌ 用 code_pack 查单个符号定义（用 explore 更快）
- ❌ 用 explore 查改动影响（用 diff_impact，它从文件反推符号树）
- ❌ 改 5 个文件但 diff_impact 只查 1 个（传列表一次查全）
