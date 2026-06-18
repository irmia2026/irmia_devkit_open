import { createApi } from "./api.js";

const bridge = window.AstrBotPluginPage;
const PALETTE_KEY = "irmia_devkit_palette_mode";
const APPEARANCE_KEY = "irmia_devkit_appearance_mode";
const PALETTE_MODES = ["luxury", "bluewhite", "vivid", "void"];
const APPEARANCE_MODES = ["auto", "dark", "light"];
const PALETTE_LABELS = { luxury: "鎏金", bluewhite: "冰蓝", vivid: "霓虹", void: "暗涌" };
const APPEARANCE_LABELS = { auto: "自动", dark: "深色", light: "浅色" };
let paletteMode = "luxury";
let appearanceMode = "auto";
let api = null;
let toolGroupsDef = {};
let groupsData = [];
let selectedGroupId = null;
let currentConfig = null;
let globalAdminIds = [];

const GROUP_EMOJIS = [
  [/(文件系统|文件|file|zip|目录|dir|path|download|hash)/i, "📁"],
  [/(文本处理|文本|text|markdown|html|json|csv|日志|log)/i, "📝"],
  [/(网络|http|web|url|api|port)/i, "🌐"],
  [/(代码|code|syntax|lint|test|symbol|rename|diff|grep|rg|tree|project)/i, "🧩"],
  [/(git|github|gh|仓库|pr|issue|release|branch|commit)/i, "🌿"],
  [/(数据库|db|sql|sqlite|query)/i, "🗄️"],
  [/(系统|shell|process|proc|disk|time|uuid|encode|decode)/i, "⚙️"],
  [/(图片|image|avatar|生成)/i, "🎨"],
];

function emojiForName(name) {
  const text = String(name || "");
  const matched = GROUP_EMOJIS.find(([regex]) => regex.test(text));
  return matched ? matched[1] : "🔧";
}

function toolBrief(name) {
  const text = String(name || "").toLowerCase();
  const rules = [
    [/html_extract/, "提取网页内容"], [/json_query/, "查询 JSON 字段"], [/csv_parse/, "解析 CSV 表格"], [/csv_gen/, "生成 CSV 文本"], [/log_parse/, "解析日志文本"], [/md_strip/, "清理 Markdown"],
    [/http_get/, "发送 GET 请求"], [/http_post/, "发送 POST 请求"], [/http_download/, "下载远程文件"], [/web_search|tavily/, "联网检索内容"], [/port_check/, "检测端口状态"],
    [/file_zip/, "打包 ZIP"], [/file_unzip/, "解压 ZIP"], [/file_hash/, "计算文件哈希"], [/file_remove/, "删除文件目录"], [/dir_tree/, "查看目录树"], [/dir_list/, "列出目录内容"], [/es_search/, "搜索本地文件"],
    [/safe_edit/, "安全修改文件"], [/multi_edit/, "批量安全修改"], [/safe_write/, "新建或覆盖文件"], [/syntax_check/, "检查代码语法"], [/lint_runner/, "检查代码质量"], [/test_runner/, "运行项目测试"], [/rg_search/, "搜索代码内容"],
    [/git_status/, "查看仓库状态"], [/git_diff/, "查看代码差异"], [/git_commit/, "提交 Git 改动"], [/git_push/, "推送 Git 分支"], [/git_log/, "查看提交历史"], [/git_branch/, "查看当前分支"],
    [/gh_pr/, "管理 GitHub PR"], [/gh_issue/, "管理 GitHub Issue"], [/gh_release/, "管理 GitHub Release"], [/gh_repo/, "管理 GitHub 仓库"],
    [/db_query/, "查询 SQLite"], [/shell_exec/, "执行安全命令"], [/proc_list/, "查看进程"], [/disk_info/, "查看磁盘空间"], [/time/, "时间转换计算"], [/uuid_gen/, "生成随机标识"], [/encode_decode/, "文本编解码"],
    [/generate_image/, "生成图片"], [/config_diff/, "比较配置差异"], [/diff_strings/, "比较文本差异"], [/project_init/, "扫描项目结构"], [/code_index/, "建立代码索引"], [/code_explore/, "探索代码结构"], [/code_pack/, "打包代码上下文"],
  ];
  const matched = rules.find(([regex]) => regex.test(text));
  return matched ? matched[1] : "独立工具开关";
}

function escapeHtml(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, m => map[m]);
}

function asToolItems(tools) {
  if (!Array.isArray(tools)) return [];
  return tools.map(item => {
    if (typeof item === "string") return { id: item, name: item, desc: toolBrief(item) };
    if (item && typeof item === "object") {
      const id = String(item.name || item.id || item.tool || item.key || "").trim();
      return { id, name: String(item.label || item.title || id), desc: String(item.desc || item.description || toolBrief(id)) };
    }
    return { id: String(item), name: String(item), desc: toolBrief(item) };
  }).filter(item => item.id);
}

function allToolItems() {
  return Object.values(toolGroupsDef).flatMap(asToolItems);
}

function savePaletteLocally(mode) {
  try { localStorage.setItem(PALETTE_KEY, mode); } catch { /* ignore */ }
}

function saveAppearanceLocally(mode) {
  try { localStorage.setItem(APPEARANCE_KEY, mode); } catch { /* ignore */ }
}

function getStoredPaletteMode() {
  let saved = paletteMode || "luxury";
  try { saved = localStorage.getItem(PALETTE_KEY) || saved; } catch { /* ignore */ }
  paletteMode = PALETTE_MODES.includes(saved) ? saved : "luxury";
  return paletteMode;
}

function applyPalette(mode = getStoredPaletteMode()) {
  paletteMode = PALETTE_MODES.includes(mode) ? mode : "luxury";
  document.documentElement.dataset.palette = paletteMode;
  const label = document.getElementById("paletteModeLabel");
  if (label) label.textContent = PALETTE_LABELS[paletteMode] || "鎏金";
}

function getStoredAppearanceMode() {
  let saved = appearanceMode || "auto";
  try { saved = localStorage.getItem(APPEARANCE_KEY) || saved; } catch { /* ignore */ }
  appearanceMode = APPEARANCE_MODES.includes(saved) ? saved : "auto";
  return appearanceMode;
}

function resolveAppearance(mode) {
  if (mode === "light" || mode === "dark") return mode;
  return window.matchMedia?.("(prefers-color-scheme: light)")?.matches ? "light" : "dark";
}

function applyAppearance(mode = getStoredAppearanceMode()) {
  appearanceMode = APPEARANCE_MODES.includes(mode) ? mode : "auto";
  document.documentElement.dataset.appearance = appearanceMode;
  document.documentElement.dataset.theme = resolveAppearance(appearanceMode);
  const label = document.getElementById("appearanceModeLabel");
  if (label) label.textContent = APPEARANCE_LABELS[appearanceMode] || "自动";
}

async function cycleAppearanceMode() {
  const current = appearanceMode || getStoredAppearanceMode();
  const currentIndex = APPEARANCE_MODES.includes(current) ? APPEARANCE_MODES.indexOf(current) : 0;
  const next = APPEARANCE_MODES[(currentIndex + 1) % APPEARANCE_MODES.length];
  appearanceMode = next;
  saveAppearanceLocally(next);
  applyAppearance(next);
  await saveUiPreferences();
}

async function cyclePaletteMode() {
  const current = document.documentElement.dataset.palette || paletteMode || getStoredPaletteMode();
  const currentIndex = PALETTE_MODES.includes(current) ? PALETTE_MODES.indexOf(current) : 0;
  const next = PALETTE_MODES[(currentIndex + 1) % PALETTE_MODES.length];
  paletteMode = next;
  savePaletteLocally(next);
  applyPalette(next);
  await saveUiPreferences();
}

async function loadUiPreferences() {
  try {
    const data = await api.safeGet("ui_preferences");
    const palette = data.preferences?.palette_mode;
    const appearance = data.preferences?.appearance_mode;
    if (APPEARANCE_MODES.includes(appearance)) {
      appearanceMode = appearance;
      saveAppearanceLocally(appearance);
      applyAppearance(appearance);
    }
    if (PALETTE_MODES.includes(palette)) {
      paletteMode = palette;
      savePaletteLocally(palette);
      applyPalette(palette);
      return;
    }
  } catch (e) { console.warn("loadUiPreferences", e); }
  applyPalette();
  applyAppearance();
}

async function saveUiPreferences() {
  if (!api) return;
  try { await api.safePost("ui_preferences/save", { palette_mode: paletteMode, appearance_mode: appearanceMode }); }
  catch (e) { console.warn("saveUiPreferences", e); }
}

async function init() {
  applyPalette();
  applyAppearance();
  window.matchMedia?.("(prefers-color-scheme: light)")?.addEventListener?.("change", () => {
    if (appearanceMode === "auto") applyAppearance("auto");
  });
  document.getElementById("paletteToggleBtn")?.addEventListener("click", cyclePaletteMode);
  document.getElementById("appearanceToggleBtn")?.addEventListener("click", cycleAppearanceMode);
  document.getElementById("refreshGroupsBtn")?.addEventListener("click", async () => {
    await loadGroups();
    showToast("群聊列表已刷新");
  });
  await loadUiPreferences();
  await loadToolGroups();
  await loadGlobalAdmins();
  await loadGroups();
}

async function loadToolGroups() {
  try {
    const data = await api.safeGet("tool_groups");
    if (data.ok) toolGroupsDef = data.groups || {};
    const toolCount = allToolItems().length;
    const label = document.getElementById("toolCountLabel");
    if (label) label.textContent = String(toolCount);
  } catch (e) { console.error("loadToolGroups", e); }
}

async function loadGlobalAdmins() {
  try {
    const data = await api.safeGet("global_admin_ids");
    if (data.ok) globalAdminIds = data.admin_ids || [];
  } catch (e) { console.error("loadGlobalAdmins", e); }
}

async function loadGroups() {
  try {
    const data = await api.safeGet("groups");
    if (data.ok) {
      groupsData = data.groups || [];
      renderGroupList();
    }
  } catch (e) { console.error("loadGroups", e); showToast("群聊加载失败"); }
}

function renderGroupList() {
  const container = document.getElementById("groupList");
  if (!container) return;
  container.innerHTML = "";
  const countLabel = document.getElementById("groupCountLabel");
  if (countLabel) countLabel.textContent = String(groupsData.length);

  if (!groupsData.length) {
    container.innerHTML = `<div class="group-item"><div class="group-avatar-placeholder">?</div><div><div class="group-name">暂无群聊</div><div class="group-id-tag">等待平台返回群列表</div></div></div>`;
    return;
  }

  groupsData.forEach(g => {
    const item = document.createElement("div");
    item.className = "group-item" + (g.id === selectedGroupId ? " active" : "");
    item.onclick = () => selectGroup(g.id);
    const avatarHtml = g.avatar
      ? `<img class="group-avatar" src="${escapeHtml(g.avatar)}" onerror="this.outerHTML='<div class=group-avatar-placeholder>群</div>'">`
      : `<div class="group-avatar-placeholder">群</div>`;
    item.innerHTML = `
      ${avatarHtml}
      <div>
        <div class="group-name">${escapeHtml(g.name)}</div>
        <div class="group-id-tag">${escapeHtml(g.id)}</div>
      </div>
      <div class="group-chip">配置</div>
    `;
    container.appendChild(item);
  });
}

async function selectGroup(groupId) {
  selectedGroupId = groupId;
  renderGroupList();
  try {
    const data = await api.safeGet("group_config", { group_id: groupId });
    if (data.ok) {
      currentConfig = normalizeConfig(data.config || {});
      renderConfigPanel();
    }
  } catch (e) { console.error("selectGroup", e); showToast("配置加载失败"); }
}

function normalizeConfig(config) {
  const cfg = config || {};
  const groupToggles = {};
  for (const groupName of Object.keys(toolGroupsDef)) {
    groupToggles[groupName] = cfg.tool_groups?.[groupName] !== undefined ? Boolean(cfg.tool_groups[groupName]) : true;
  }
  const disabledTools = Array.isArray(cfg.disabled_tools) ? cfg.disabled_tools.map(String) : [];
  return {
    group_id: cfg.group_id || selectedGroupId,
    extra_admin_ids: cfg.extra_admin_ids || "",
    tool_groups: groupToggles,
    disabled_tools: disabledTools,
  };
}

function getEnabledToolCount() {
  const disabled = new Set(currentConfig?.disabled_tools || []);
  return allToolItems().filter(tool => !disabled.has(tool.id)).length;
}

function renderConfigPanel() {
  document.getElementById("emptyState").style.display = "none";
  const panel = document.getElementById("configPanel");
  panel.style.display = "block";
  const groupName = groupsData.find(g => g.id === selectedGroupId)?.name || `群${selectedGroupId}`;
  const allTools = allToolItems();
  const adminIdsStr = globalAdminIds.join("、") || "未配置";
  const enabledTools = getEnabledToolCount();

  panel.innerHTML = `
    <div class="hero">
      <div class="hero-card">
        <div class="hero-grid">
          <div>
            <div class="kicker">IRMIA DEVKIT</div>
            <h2>${escapeHtml(groupName)}</h2>
            <p>群号 ${escapeHtml(selectedGroupId)}。这里控制工具箱在该群内的可用范围。</p>
          </div>
          <div class="stat-grid">
            <div><b>${Object.keys(toolGroupsDef).length}</b><span>工具组</span></div>
            <div><b>${enabledTools}</b><span>已开启工具</span></div>
            <div><b>${allTools.length - enabledTools}</b><span>已关闭工具</span></div>
          </div>
        </div>
      </div>
    </div>

    <div class="top-pair">
      <div class="card admin-card">
        <h3>管理权限</h3>
        <div class="admin-row">
          <div class="input-hint">全局管理员：${escapeHtml(adminIdsStr)}</div>
          <label class="field-label" for="extraAdminIds">额外管理员 QQ</label>
          <input class="input-field" id="extraAdminIds" type="text" value="${escapeHtml(currentConfig.extra_admin_ids)}" placeholder="例如：123456,987654">
          <div class="input-hint">多个 QQ 用逗号分隔。仅影响当前群。</div>
        </div>
      </div>
      <div class="card bulk-card">
        <h3>批量工具</h3>
        <div class="bulk-actions">
          <button class="bulk-row" id="enableAllToolsBtn" type="button">
            <div><b>开启全部工具</b><span>打开所有工具组和单工具</span></div>
          </button>
          <button class="bulk-row danger" id="disableAllToolsBtn" type="button">
            <div><b>关闭全部工具</b><span>关闭所有工具组和单工具</span></div>
          </button>
        </div>
      </div>
    </div>

    <div class="board">
      ${renderToolGroupCards()}
    </div>

    <div class="actions">
      <button class="btn btn-secondary" id="resetConfigBtn" type="button">重置当前群</button>
      <button class="btn btn-primary" id="saveConfigBtn" type="button">保存配置</button>
    </div>
  `;

  bindConfigEvents();
}

function renderToolGroupCards() {
  const disabled = new Set(currentConfig.disabled_tools || []);
  return Object.entries(toolGroupsDef)
    .map(([groupName, rawTools]) => [groupName, rawTools, asToolItems(rawTools).length])
    .sort((a, b) => b[2] - a[2] || String(a[0]).localeCompare(String(b[0]), "zh-Hans-CN"))
    .map(([groupName, rawTools], index) => {
    const tools = asToolItems(rawTools);
    const groupChecked = currentConfig.tool_groups[groupName] !== false;
    const rows = tools.map(tool => {
      const checked = !disabled.has(tool.id);
      return `
        <label class="tool-card">
          <div class="tool-emoji">${emojiForName(tool.name || tool.id)}</div>
          <div class="tool-copy">
            <div class="tool-name">${escapeHtml(tool.name)}</div>
            <div class="tool-desc">${escapeHtml(tool.desc)}</div>
          </div>
          <span class="switch">
            <input class="tool-toggle" type="checkbox" data-tool="${escapeHtml(tool.id)}" data-group-name="${escapeHtml(groupName)}" ${checked ? "checked" : ""}>
            <span class="switch-track"></span><span class="switch-thumb"></span>
          </span>
        </label>`;
    }).join("");
    return `
      <section class="group-card">
        <div class="group-head">
          <div class="group-title">
            <span class="group-icon"><span class="group-icon-symbol">${emojiForName(groupName)}</span></span>
            <div><b>${escapeHtml(groupName)}</b><span>${tools.length} 个工具，可单独控制</span></div>
          </div>
          <label class="switch" title="工具组总开关">
            <input class="group-toggle" type="checkbox" data-group="${escapeHtml(groupName)}" ${groupChecked ? "checked" : ""}>
            <span class="switch-track"></span><span class="switch-thumb"></span>
          </label>
        </div>
        <div class="tool-grid">${rows || `<div class="tool-card"><div><div class="tool-name">空工具组</div><div class="tool-desc">注册表暂未提供工具</div></div></div>`}</div>
      </section>`;
  }).join("");
}

function bindConfigEvents() {
  document.querySelectorAll(".group-toggle").forEach(input => {
    input.addEventListener("change", event => {
      const groupName = event.currentTarget.dataset.group;
      currentConfig.tool_groups[groupName] = event.currentTarget.checked;
      document.querySelectorAll(`.tool-toggle[data-group-name="${CSS.escape(groupName)}"]`).forEach(toolToggle => {
        toolToggle.checked = event.currentTarget.checked;
        setToolDisabled(toolToggle.dataset.tool, !event.currentTarget.checked);
      });
      renderConfigPanel();
    });
  });

  document.querySelectorAll(".tool-toggle").forEach(input => {
    input.addEventListener("change", event => {
      setToolDisabled(event.currentTarget.dataset.tool, !event.currentTarget.checked);
      renderConfigPanel();
    });
  });

  document.getElementById("enableAllToolsBtn")?.addEventListener("click", async () => {
    setAllToolsState(true);
    renderConfigPanel();
    await persistConfig("已开启全部工具");
  });
  document.getElementById("disableAllToolsBtn")?.addEventListener("click", async () => {
    setAllToolsState(false);
    renderConfigPanel();
    await persistConfig("已关闭全部工具");
  });
  document.getElementById("saveConfigBtn")?.addEventListener("click", saveConfig);
  document.getElementById("resetConfigBtn")?.addEventListener("click", resetConfig);
}

function setAllToolsState(enabled) {
  for (const groupName of Object.keys(toolGroupsDef)) {
    currentConfig.tool_groups[groupName] = enabled;
  }
  currentConfig.disabled_tools = enabled ? [] : allToolItems().map(tool => tool.id).sort();
}

function setToolDisabled(toolId, disabled) {
  const set = new Set(currentConfig.disabled_tools || []);
  if (disabled) set.add(toolId); else set.delete(toolId);
  currentConfig.disabled_tools = Array.from(set).sort();
}

function showConfirm(message, title = "确认操作") {
  return new Promise(resolve => {
    const mask = document.getElementById("confirmMask");
    const titleEl = document.getElementById("confirmTitle");
    const msgEl = document.getElementById("confirmMessage");
    const okBtn = document.getElementById("confirmOkBtn");
    const cancelBtn = document.getElementById("confirmCancelBtn");
    titleEl.textContent = title;
    msgEl.textContent = message;
    mask.classList.add("show");
    const cleanup = result => {
      mask.classList.remove("show");
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      resolve(result);
    };
    okBtn.onclick = () => cleanup(true);
    cancelBtn.onclick = () => cleanup(false);
    mask.onclick = event => { if (event.target === mask) cleanup(false); };
  });
}

function touchCurrentGroup() {
  const now = Math.floor(Date.now() / 1000);
  groupsData = groupsData.map(g => g.id === selectedGroupId ? { ...g, updated_at: now } : g);
  groupsData.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
  renderGroupList();
}

async function persistConfig(message = "配置已保存") {
  currentConfig.extra_admin_ids = document.getElementById("extraAdminIds")?.value.trim() || currentConfig.extra_admin_ids || "";
  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: currentConfig.extra_admin_ids,
    tool_groups: currentConfig.tool_groups,
    disabled_tools: currentConfig.disabled_tools,
  };
  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      currentConfig = normalizeConfig(payload);
      showToast(message);
      touchCurrentGroup();
      await loadGroups();
      return true;
    }
    showToast("保存失败");
  } catch (e) { console.error("persistConfig", e); showToast("保存请求失败"); }
  return false;
}

async function saveConfig() {
  if (!(await showConfirm("保存当前群的工具箱权限配置？", "保存配置"))) return;
  await persistConfig("配置已保存");
}

async function resetConfig() {
  if (!(await showConfirm("重置当前群配置？额外管理员会清空，所有工具会重新开启。", "重置配置"))) return;
  const toolGroups = {};
  for (const groupName of Object.keys(toolGroupsDef)) toolGroups[groupName] = true;
  currentConfig = { group_id: selectedGroupId, extra_admin_ids: "", tool_groups: toolGroups, disabled_tools: [] };
  renderConfigPanel();
  await persistConfig("已重置并保存");
}

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function waitForBridge(timeoutMs = 4000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  return window.AstrBotPluginPage;
}

async function boot() {
  try {
    const pageBridge = bridge || await waitForBridge();
    if (pageBridge?.ready) await pageBridge.ready();
    api = createApi(pageBridge);
    await init();
  } catch (e) {
    console.error("[Devkit] boot failed", e);
    showToast("配置页初始化失败");
  }
}

boot();
