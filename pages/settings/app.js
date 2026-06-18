import { createApi } from "./api.js";

// 弥亚开发工具箱配置页 — 前端逻辑

const bridge = window.AstrBotPluginPage;
const PALETTE_KEY = "irmia_devkit_palette_mode";
const PALETTE_MODES = ["luxury", "bluewhite", "vivid"];
const PALETTE_LABELS = { luxury: "金奢", bluewhite: "蓝白", vivid: "炫彩" };
const DEFAULT_GROUP_ID = "__default__";
let paletteMode = "luxury";
let api = null;
let toolGroupsDef = {};
let groupsData = [];
let selectedGroupId = null;
let currentConfig = null;
let globalAdminIds = [];

function escapeHtml(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, m => map[m]);
}

function savePaletteLocally(mode) {
  try { localStorage.setItem(PALETTE_KEY, mode); } catch { /* ignore storage errors */ }
}

function getStoredPaletteMode() {
  let saved = paletteMode || "luxury";
  try { saved = localStorage.getItem(PALETTE_KEY) || saved; } catch { /* ignore storage errors */ }
  paletteMode = PALETTE_MODES.includes(saved) ? saved : "luxury";
  return paletteMode;
}

function applyPalette(mode = getStoredPaletteMode()) {
  paletteMode = PALETTE_MODES.includes(mode) ? mode : "luxury";
  document.documentElement.dataset.palette = paletteMode;
  const label = document.getElementById("paletteModeLabel");
  if (label) label.textContent = PALETTE_LABELS[paletteMode] || "金奢";
}

function cyclePaletteMode() {
  const current = document.documentElement.dataset.palette || paletteMode || getStoredPaletteMode();
  const currentIndex = PALETTE_MODES.includes(current) ? PALETTE_MODES.indexOf(current) : 0;
  const next = PALETTE_MODES[(currentIndex + 1) % PALETTE_MODES.length];
  paletteMode = next;
  savePaletteLocally(next);
  applyPalette(next);
  saveUiPreferences();
}

async function loadUiPreferences() {
  try {
    const data = await api.safeGet("ui_preferences");
    const palette = data.preferences?.palette_mode;
    if (PALETTE_MODES.includes(palette)) {
      paletteMode = palette;
      savePaletteLocally(palette);
      applyPalette(palette);
      return;
    }
  } catch (e) { console.warn("loadUiPreferences", e); }
  saveUiPreferences();
}

async function saveUiPreferences() {
  if (!api) return;
  try { await api.safePost("ui_preferences/save", { palette_mode: paletteMode }); }
  catch (e) { console.warn("saveUiPreferences", e); }
}

// ── 初始化 ──

async function init() {
  applyPalette();
  document.getElementById("paletteToggleBtn")?.addEventListener("click", cyclePaletteMode);
  await loadUiPreferences();
  await loadToolGroups();
  await loadGlobalAdmins();
  await loadGroups();
}

async function loadToolGroups() {
  try {
    const data = await api.safeGet("tool_groups");
    if (data.ok) toolGroupsDef = data.groups || {};
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
      groupsData = normalizeGroups(data.groups || []);
      if (!selectedGroupId) selectedGroupId = DEFAULT_GROUP_ID;
      renderGroupList();
      if (!currentConfig) await selectGroup(selectedGroupId);
    }
  } catch (e) { console.error("loadGroups", e); }
}

function normalizeGroups(groups) {
  const list = groups.filter(g => g.id !== DEFAULT_GROUP_ID);
  list.sort((a, b) => {
    const at = Number(a.updated_at || 0);
    const bt = Number(b.updated_at || 0);
    if (bt !== at) return bt - at;
    return String(a.name || a.id || "").localeCompare(String(b.name || b.id || ""), "zh-Hans-CN");
  });
  return [{ id: DEFAULT_GROUP_ID, name: "默认群配置", avatar: "", is_default: true, updated_at: 0 }, ...list];
}

function groupMeta(groupId) {
  return groupsData.find(g => g.id === groupId) || { id: groupId, name: `群${groupId}`, is_default: false };
}

function allToolNames() {
  return Object.values(toolGroupsDef).flat();
}

function countEnabledGroups(toolGroups) {
  return Object.keys(toolGroupsDef).filter(name => toolGroups[name] !== false).length;
}

function countDisabledTools(disabledTools) {
  return Array.isArray(disabledTools) ? disabledTools.length : 0;
}

// ── 渲染群列表 ──

function renderGroupList() {
  const container = document.getElementById("groupList");
  container.innerHTML = "";

  groupsData.forEach(g => {
    const item = document.createElement("div");
    item.className = "group-item" + (g.id === selectedGroupId ? " active" : "") + (g.is_default ? " default" : "");
    item.onclick = () => selectGroup(g.id);

    const avatarHtml = g.is_default
      ? `<div class="group-avatar-placeholder default-icon">⚙️</div>`
      : g.avatar
        ? `<img class="group-avatar" src="${escapeHtml(g.avatar)}" onerror="this.outerHTML='<div class=group-avatar-placeholder>群</div>'">`
        : `<div class="group-avatar-placeholder">群</div>`;

    item.innerHTML = `
      ${avatarHtml}
      <div class="group-info">
        <div class="group-name">${escapeHtml(g.name)}</div>
        <div class="group-id-tag">${g.is_default ? "始终置顶 · 所有群兜底" : `群号 ${escapeHtml(g.id)}`}</div>
      </div>
    `;
    container.appendChild(item);
  });
}

// ── 选择群 ──

async function selectGroup(groupId) {
  selectedGroupId = groupId;
  renderGroupList();

  try {
    const data = await api.safeGet("group_config", { group_id: groupId });
    if (data.ok) {
      currentConfig = data.config;
      renderConfigPanel();
    }
  } catch (e) { console.error("selectGroup", e); }
}

// ── 渲染配置面板 ──

function renderConfigPanel() {
  document.getElementById("emptyState").style.display = "none";
  const panel = document.getElementById("configPanel");
  panel.style.display = "block";

  const meta = groupMeta(selectedGroupId);
  const isDefault = selectedGroupId === DEFAULT_GROUP_ID;
  const adminIdsStr = globalAdminIds.join("、");
  const extraAdminIds = currentConfig.extra_admin_ids || "";
  const cfgToolGroups = currentConfig.tool_groups || {};
  const disabledTools = Array.isArray(currentConfig.disabled_tools) ? currentConfig.disabled_tools : [];

  const allGroups = {};
  for (const g in toolGroupsDef) allGroups[g] = cfgToolGroups[g] !== undefined ? cfgToolGroups[g] : true;

  panel.innerHTML = `
    <div class="hero-card">
      <div>
        <div class="kicker">${isDefault ? "默认策略" : "群聊策略"}</div>
        <h3>${escapeHtml(meta.name)}</h3>
        <div class="subtitle">${isDefault ? "默认群配置始终置顶，作为所有群的兜底权限。" : `群号 ${escapeHtml(selectedGroupId)} · 可覆盖默认群配置`}</div>
      </div>
      <div class="summary-grid">
        <div><b>${escapeHtml(countEnabledGroups(allGroups))}</b><span>启用工具组</span></div>
        <div><b>${escapeHtml(countDisabledTools(disabledTools))}</b><span>单工具禁用</span></div>
      </div>
    </div>

    <details class="section-card" open>
      <summary><span>1</span><b>权限入口</b><em>管理员范围，权限最大</em></summary>
      <div class="admin-badge">全局管理员：${escapeHtml(adminIdsStr || "未配置")}</div>
      <label class="field-label" for="extraAdminIds">额外管理员</label>
      <input class="input-field" id="extraAdminIds" type="text" value="${escapeHtml(extraAdminIds)}" placeholder="用户 ID，多个用逗号分隔">
      <div class="input-hint">${isDefault ? "默认额外管理员会对所有群生效。" : "当前群额外管理员会覆盖默认配置中的额外管理员。"}</div>
    </details>

    <details class="section-card" open>
      <summary><span>2</span><b>工具组开关</b><em>按能力组批量控制，配置最多</em></summary>
      <div class="tool-group-grid">${renderToolGroupRows(allGroups)}</div>
    </details>

    <details class="section-card">
      <summary><span>3</span><b>单工具禁用</b><em>精细兜底，优先级最高</em></summary>
      <div class="input-hint top-hint">勾选后，即使所在工具组开启，该工具也会被禁用。</div>
      <div class="tool-chip-grid">${renderToolChips(disabledTools)}</div>
    </details>

    <div class="btn-row sticky-actions">
      <button class="btn btn-primary" id="saveConfigBtn">保存配置</button>
      <button class="btn btn-secondary" id="resetConfigBtn">重置为默认</button>
    </div>
  `;

  document.getElementById("saveConfigBtn")?.addEventListener("click", saveConfig);
  document.getElementById("resetConfigBtn")?.addEventListener("click", resetConfig);
}

function renderToolGroupRows(allGroups) {
  return Object.entries(toolGroupsDef).map(([name, tools]) => {
    const checked = allGroups[name] ? "checked" : "";
    return `
      <div class="tool-group-row">
        <div>
          <span class="tool-group-name">${escapeHtml(name)}</span>
          <span class="tool-group-count">${escapeHtml(tools.length)} 个工具</span>
        </div>
        <label class="toggle">
          <input type="checkbox" data-group="${escapeHtml(name)}" ${checked}>
          <div class="toggle-track"></div>
          <div class="toggle-thumb"></div>
        </label>
      </div>
    `;
  }).join("");
}

function renderToolChips(disabledTools) {
  const disabledSet = new Set(disabledTools);
  return Object.entries(toolGroupsDef).map(([groupName, tools]) => `
    <div class="tool-chip-section">
      <div class="tool-chip-title">${escapeHtml(groupName)}</div>
      <div class="tool-chip-list">
        ${tools.map(tool => `
          <label class="tool-chip ${disabledSet.has(tool) ? "off" : ""}">
            <input type="checkbox" data-tool="${escapeHtml(tool)}" ${disabledSet.has(tool) ? "checked" : ""}>
            <span>${escapeHtml(tool)}</span>
          </label>
        `).join("")}
      </div>
    </div>
  `).join("");
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
  groupsData = normalizeGroups(groupsData);
  renderGroupList();
}

// ── 保存配置 ──

async function saveConfig() {
  const name = groupMeta(selectedGroupId).name;
  if (!(await showConfirm(`确定保存「${name}」的开发工具箱配置吗？`, "保存配置"))) return;

  const extraIds = document.getElementById("extraAdminIds").value.trim();
  const toolGroups = {};
  document.querySelectorAll(".toggle input[type=checkbox]").forEach(cb => {
    toolGroups[cb.dataset.group] = cb.checked;
  });
  const disabledTools = [];
  document.querySelectorAll(".tool-chip input[type=checkbox]").forEach(cb => {
    if (cb.checked) disabledTools.push(cb.dataset.tool);
  });

  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: extraIds,
    tool_groups: toolGroups,
    disabled_tools: disabledTools,
  };

  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      currentConfig = data.config || payload;
      showToast("配置已保存");
      touchCurrentGroup();
      await loadGroups();
    } else {
      showToast("保存失败");
    }
  } catch (e) {
    console.error("[Devkit] saveConfig", e);
    showToast("网络错误");
  }
}

// ── 重置配置 ──

async function resetConfig() {
  const isDefault = selectedGroupId === DEFAULT_GROUP_ID;
  const msg = isDefault
    ? "确定重置默认群配置吗？这会清空默认额外管理员，开启所有工具组，并取消单工具禁用。"
    : "确定重置当前群配置吗？这会清空额外管理员，开启所有工具组，并取消单工具禁用。";
  if (!(await showConfirm(msg, "重置默认配置"))) return;

  const defaultToolGroups = {};
  for (const g in toolGroupsDef) defaultToolGroups[g] = true;

  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: "",
    tool_groups: defaultToolGroups,
    disabled_tools: [],
  };

  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      currentConfig = data.config || payload;
      renderConfigPanel();
      showToast("已重置为默认");
      touchCurrentGroup();
      await loadGroups();
    }
  } catch (e) {
    console.error("[Devkit] resetConfig", e);
    showToast("网络错误");
  }
}

// ── Toast ──

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

// ── 启动 ──

async function boot() {
  try {
    if (bridge?.ready) await bridge.ready();
    api = createApi(bridge);
    await init();
  } catch (e) {
    console.error("[Devkit] boot failed", e);
    showToast("前端桥接初始化失败");
  }
}

boot();
