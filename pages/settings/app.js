import { createApi } from "./api.js";

// 弥亚开发工具箱配置页 — 前端逻辑

const bridge = window.AstrBotPluginPage;
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

// ── 初始化 ──

async function init() {
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
      groupsData = data.groups || [];
      renderGroupList();
    }
  } catch (e) { console.error("loadGroups", e); }
}

// ── 渲染群列表 ──

function renderGroupList() {
  const container = document.getElementById("groupList");
  container.innerHTML = "";

  groupsData.forEach(g => {
    const item = document.createElement("div");
    item.className = "group-item" + (g.id === selectedGroupId ? " active" : "");
    item.onclick = () => selectGroup(g.id);

    const avatarHtml = g.avatar
      ? `<img class="group-avatar" src="${escapeHtml(g.avatar)}" onerror="this.outerHTML='<div class=group-avatar-placeholder>💬</div>'">`
      : `<div class="group-avatar-placeholder">💬</div>`;

    item.innerHTML = `
      ${avatarHtml}
      <div>
        <div class="group-name">${escapeHtml(g.name)}</div>
        <div class="group-id-tag">${escapeHtml(g.id)}</div>
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

  const groupName = groupsData.find(g => g.id === selectedGroupId)?.name || `群${selectedGroupId}`;
  const adminIdsStr = globalAdminIds.join("、");
  const extraAdminIds = currentConfig.extra_admin_ids || "";

  const cfgToolGroups = currentConfig.tool_groups || {};
  const allGroups = {};
  for (const g in toolGroupsDef) {
    allGroups[g] = cfgToolGroups[g] !== undefined ? cfgToolGroups[g] : true;
  }

  let toolGroupRows = "";
  for (const [name, tools] of Object.entries(toolGroupsDef)) {
    const checked = allGroups[name] ? "checked" : "";
    toolGroupRows += `
      <div class="tool-group-row">
        <div>
          <span class="tool-group-name">${escapeHtml(name)}</span>
          <span class="tool-group-count">(${escapeHtml(tools.length)} 工具)</span>
        </div>
        <label class="toggle">
          <input type="checkbox" data-group="${escapeHtml(name)}" ${checked}>
          <div class="toggle-track"></div>
          <div class="toggle-thumb"></div>
        </label>
      </div>
    `;
  }

  panel.innerHTML = `
    <h3>${escapeHtml(groupName)}</h3>
    <div class="subtitle">群号 ${escapeHtml(selectedGroupId)} · 独立配置工具权限</div>

    <div class="admin-badge">🔒 全局管理员：${escapeHtml(adminIdsStr || "未配置")}</div>

    <div class="card">
      <div class="card-title"><span class="emoji">👤</span> 额外管理员</div>
      <input class="input-field" id="extraAdminIds" type="text"
        value="${escapeHtml(extraAdminIds)}"
        placeholder="QQ 号，多个用逗号分隔">
      <div class="input-hint">额外允许使用开发者工具箱的用户 QQ 号（逗号分隔），不受全局管理员限制</div>
    </div>

    <div class="card">
      <div class="card-title"><span class="emoji">🔧</span> 工具组开关</div>
      ${toolGroupRows}
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" id="saveConfigBtn">💾 保存配置</button>
      <button class="btn btn-secondary" id="resetConfigBtn">🔄 重置为默认</button>
    </div>
  `;

  document.getElementById("saveConfigBtn")?.addEventListener("click", saveConfig);
  document.getElementById("resetConfigBtn")?.addEventListener("click", resetConfig);
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
    mask.onclick = event => {
      if (event.target === mask) cleanup(false);
    };
  });
}

function touchCurrentGroup() {
  const now = Math.floor(Date.now() / 1000);
  groupsData = groupsData.map(g => g.id === selectedGroupId ? { ...g, updated_at: now } : g);
  groupsData.sort((a, b) => {
    const at = Number(a.updated_at || 0);
    const bt = Number(b.updated_at || 0);
    if (bt !== at) return bt - at;
    return String(a.name || a.id || "").localeCompare(String(b.name || b.id || ""), "zh-Hans-CN");
  });
  renderGroupList();
}

// ── 保存配置 ──

async function saveConfig() {
  if (!(await showConfirm("确定保存当前群聊的开发工具箱配置吗？", "保存配置"))) return;

  const extraIds = document.getElementById("extraAdminIds").value.trim();
  const toolGroups = {};
  document.querySelectorAll(".toggle input[type=checkbox]").forEach(cb => {
    toolGroups[cb.dataset.group] = cb.checked;
  });

  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: extraIds,
    tool_groups: toolGroups,
  };

  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      currentConfig = payload;
      showToast("✅ 配置已保存");
      touchCurrentGroup();
      await loadGroups();
    } else {
      showToast("❌ 保存失败");
    }
  } catch (e) {
    console.error("[Devkit] saveConfig", e);
    showToast("❌ 网络错误");
  }
}

// ── 重置配置 ──

async function resetConfig() {
  if (!(await showConfirm("确定将当前群聊配置重置为默认值吗？此操作会清空额外管理员并开启所有工具组。", "重置默认配置"))) return;

  const defaultToolGroups = {};
  for (const g in toolGroupsDef) defaultToolGroups[g] = true;

  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: "",
    tool_groups: defaultToolGroups,
  };

  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      currentConfig = payload;
      renderConfigPanel();
      showToast("✅ 已重置为默认");
      touchCurrentGroup();
      await loadGroups();
    }
  } catch (e) {
    console.error("[Devkit] resetConfig", e);
    showToast("❌ 网络错误");
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
    if (bridge?.ready) {
      await bridge.ready();
    }
    api = createApi(bridge);
    await init();
  } catch (e) {
    console.error("[Devkit] boot failed", e);
    showToast("❌ 前端桥接初始化失败");
  }
}

boot();