import { createApi } from "./api.js";

let bridge = window.AstrBotPluginPage;

const PALETTE_KEY = "irmia_devkit_palette_mode";
const APPEARANCE_KEY = "irmia_devkit_appearance_mode";
const CARD_TRANSPARENCY_KEY = "irmia_devkit_card_transparency";
const PALETTE_MODES = ["luxury", "bluewhite", "vivid", "void"];
const APPEARANCE_MODES = ["auto", "dark", "light"];
const PALETTE_LABELS = { luxury: "石墨", bluewhite: "晴空", vivid: "珊瑚", void: "夜色" };
const APPEARANCE_LABELS = { auto: "自动", dark: "深色", light: "浅色" };
const DEFAULT_CARD_TRANSPARENCY = 18;
const CARD_TRANSPARENCY_MAX = 95;

let paletteMode = "luxury";
let appearanceMode = "auto";
let uiSoundEnabled = true;
let cardTransparency = DEFAULT_CARD_TRANSPARENCY;
let audioUnlocked = false;
let audioContext = null;
let cardTransparencySaveTimer = 0;
let api = null;
let toolGroupsDef = {};
let groupsData = [];
let contactsData = [];
let selectedGroupId = "";
let currentConfig = null;
let groupRequestId = 0;
let globalAdminIds = [];
let pathOptions = { es_path: "", gh_path: "", backup_dir: "" };
let searchTerm = "";
let activeGroupFilter = "all";
let chartMode = "live";
let breakdownExpanded = false;

const collapsedMenus = { groups: false, contacts: false };
const DEFAULT_GROUP = {
  id: "__default__",
  name: "全局配置",
  avatar: "",
  updated_at: Number.MAX_SAFE_INTEGER,
  isDefault: true,
  kind: "global",
};

const TOOL_BRIEFS = [
  [/html_extract/, "提取网页正文与结构化内容"],
  [/json_query/, "查询 JSON 字段和嵌套路径"],
  [/csv_parse/, "解析 CSV 表格数据"],
  [/csv_gen/, "生成 CSV 文本"],
  [/log_parse/, "解析日志并提炼关键信息"],
  [/md_strip/, "清理 Markdown 标记"],
  [/http_get/, "发送 GET 请求"],
  [/http_post/, "发送 POST 请求"],
  [/http_download/, "下载远程文件"],
  [/web_search|tavily/, "联网检索内容"],
  [/port_check/, "检测端口占用状态"],
  [/file_zip/, "打包 ZIP 文件"],
  [/file_unzip/, "解压 ZIP 文件"],
  [/file_hash/, "计算文件哈希"],
  [/file_remove/, "删除文件或目录"],
  [/dir_tree/, "查看目录树"],
  [/dir_list/, "列出目录内容"],
  [/es_search/, "搜索本地文件"],
  [/safe_edit/, "安全修改文件"],
  [/multi_edit/, "批量安全修改文件"],
  [/safe_write/, "新建或覆盖文件"],
  [/syntax_check/, "检查代码语法"],
  [/lint_runner/, "运行代码质量检查"],
  [/test_runner/, "运行项目测试"],
  [/rg_search/, "搜索代码内容"],
  [/git_status/, "查看仓库状态"],
  [/git_diff/, "查看代码差异"],
  [/git_commit/, "提交 Git 改动"],
  [/git_push/, "推送 Git 分支"],
  [/git_log/, "查看提交历史"],
  [/git_branch/, "查看当前分支"],
  [/gh_pr/, "管理 GitHub PR"],
  [/gh_issue/, "管理 GitHub Issue"],
  [/gh_release/, "管理 GitHub Release"],
  [/gh_repo/, "管理 GitHub 仓库"],
  [/db_query/, "查询 SQLite 数据"],
  [/shell_exec/, "执行受控命令"],
  [/proc_list/, "查看进程列表"],
  [/disk_info/, "查看磁盘空间"],
  [/time/, "时间换算与格式化"],
  [/uuid_gen/, "生成随机标识"],
  [/encode_decode/, "文本编码与解码"],
  [/generate_image/, "生成图片资源"],
  [/config_diff/, "比较配置差异"],
  [/diff_strings/, "比较文本差异"],
  [/project_init/, "扫描项目结构"],
  [/code_index/, "建立代码索引"],
  [/code_explore/, "探索代码结构"],
  [/code_pack/, "打包代码上下文"],
  [/safe_rollback/, "回滚到备份版本"],
  [/safe_backups/, "查看文件备份"],
  [/safe_read/, "安全读取文件"],
  [/file_patch/, "精确替换文件内容"],
  [/file_preview/, "预览替换效果"],
  [/file_move/, "移动文件或目录"],
  [/git_remote/, "查看远程仓库地址"],
  [/git_changelog/, "生成分类更新日志"],
  [/sys_snapshot/, "查看系统状态快照"],
  [/tool_stats/, "查看工具调用统计"],
  [/op_log/, "查询工具审计日志"],
  [/text_filter/, "过滤和截取文本"],
  [/semver_compare/, "比较语义版本"],
  [/dep_scan/, "扫描依赖和循环引用"],
  [/code_diff_impact/, "追踪改动影响范围"],
  [/code_status/, "检查代码索引状态"],
  [/symbol_rename/, "重命名代码符号"],
];

const GROUP_ICONS = [
  [/(文件|file|zip|目录|dir|path|download|hash)/i, "FI"],
  [/(文本|text|markdown|html|json|csv|日志|log)/i, "TX"],
  [/(网络|http|web|url|api|port)/i, "NW"],
  [/(代码|code|syntax|lint|test|symbol|rename|diff|grep|rg|tree|project)/i, "CD"],
  [/(git|github|gh|仓库|pr|issue|release|branch|commit)/i, "GH"],
  [/(数据库|db|sql|sqlite|query)/i, "DB"],
  [/(系统|shell|process|proc|disk|time|uuid|encode|decode)/i, "OS"],
  [/(图片|image|avatar|生成)/i, "IM"],
];

function escapeHtml(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, m => map[m]);
}

function toolBrief(name) {
  const text = String(name || "").toLowerCase();
  const matched = TOOL_BRIEFS.find(([regex]) => regex.test(text));
  return matched ? matched[1] : "独立工具开关";
}

function iconForName(name) {
  const text = String(name || "");
  const matched = GROUP_ICONS.find(([regex]) => regex.test(text));
  if (matched) return matched[1];
  return text.replace(/[^A-Za-z0-9\u4e00-\u9fa5]/g, "").slice(0, 2).toUpperCase() || "TL";
}

function asToolItems(tools) {
  if (!Array.isArray(tools)) return [];
  return tools.map(item => {
    if (typeof item === "string") return { id: item, name: item, desc: toolBrief(item) };
    if (item && typeof item === "object") {
      const id = String(item.name || item.id || item.tool || item.key || "").trim();
      return {
        id,
        name: String(item.label || item.title || id),
        desc: String(item.desc || item.description || toolBrief(id)),
      };
    }
    return { id: String(item), name: String(item), desc: toolBrief(item) };
  }).filter(item => item.id);
}

function allToolItems() {
  return Object.entries(toolGroupsDef).flatMap(([groupName, tools]) => (
    asToolItems(tools).map(tool => ({ ...tool, groupName }))
  ));
}

function sortedGroupEntries() {
  return Object.entries(toolGroupsDef)
    .map(([groupName, rawTools]) => [groupName, asToolItems(rawTools)])
    .sort((a, b) => b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0]), "zh-Hans-CN"));
}

function savePaletteLocally(mode) {
  try { localStorage.setItem(PALETTE_KEY, mode); } catch { /* ignore */ }
}

function saveAppearanceLocally(mode) {
  try { localStorage.setItem(APPEARANCE_KEY, mode); } catch { /* ignore */ }
}

function saveCardTransparencyLocally(value = cardTransparency) {
  try { localStorage.setItem(CARD_TRANSPARENCY_KEY, String(clampCardTransparency(value))); } catch { /* ignore */ }
}

function getStoredPaletteMode() {
  let saved = paletteMode || "luxury";
  try { saved = localStorage.getItem(PALETTE_KEY) || saved; } catch { /* ignore */ }
  paletteMode = PALETTE_MODES.includes(saved) ? saved : "luxury";
  return paletteMode;
}

function getStoredAppearanceMode() {
  let saved = appearanceMode || "auto";
  try { saved = localStorage.getItem(APPEARANCE_KEY) || saved; } catch { /* ignore */ }
  appearanceMode = APPEARANCE_MODES.includes(saved) ? saved : "auto";
  return appearanceMode;
}

function getStoredCardTransparency() {
  let saved = cardTransparency || DEFAULT_CARD_TRANSPARENCY;
  try { saved = localStorage.getItem(CARD_TRANSPARENCY_KEY) || saved; } catch { /* ignore */ }
  return clampCardTransparency(saved);
}

function resolveAppearance(mode) {
  if (mode === "light" || mode === "dark") return mode;
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

function clampCardTransparency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return DEFAULT_CARD_TRANSPARENCY;
  return Math.min(CARD_TRANSPARENCY_MAX, Math.max(0, Math.round(number)));
}

function refreshCardTransparencyControls() {
  const input = document.getElementById("cardTransparencyInput");
  const label = document.getElementById("cardTransparencyLabel");
  if (input && input.value !== String(cardTransparency)) input.value = String(cardTransparency);
  if (label) label.textContent = `${cardTransparency}%`;
}

function applyCardTransparency(value = cardTransparency) {
  cardTransparency = clampCardTransparency(value);
  const alpha = Math.max(0.04, 1 - (cardTransparency / 100));
  const shellAlpha = Math.max(0.05, Math.min(0.95, alpha * 0.88));
  const softAlpha = Math.max(0.03, Math.min(0.9, alpha * 0.72));
  const mutedAlpha = Math.max(0.02, Math.min(0.82, alpha * 0.58));
  const blur = cardTransparency >= 88 ? 0 : Math.max(0, Math.round(18 * (1 - cardTransparency / 100)));
  const root = document.documentElement;
  root.style.setProperty("--card-alpha", alpha.toFixed(2));
  root.style.setProperty("--card-shell-alpha", shellAlpha.toFixed(2));
  root.style.setProperty("--card-soft-alpha", softAlpha.toFixed(2));
  root.style.setProperty("--card-muted-alpha", mutedAlpha.toFixed(2));
  root.style.setProperty("--card-blur", `${blur}px`);
  root.dataset.cardTransparency = cardTransparency >= 88 ? "high" : (cardTransparency >= 55 ? "medium" : "low");
  refreshCardTransparencyControls();
}

function setStartupLoading(title = "读取配置", detail = "正在加载工具与权限配置") {
  const loader = document.getElementById("startupLoader");
  const titleEl = document.getElementById("startupLoaderTitle");
  const detailEl = document.getElementById("startupLoaderDetail");
  if (titleEl) titleEl.textContent = title;
  if (detailEl) detailEl.textContent = detail;
  loader?.classList.remove("is-hidden");
}

function hideStartupLoading() {
  document.getElementById("startupLoader")?.classList.add("is-hidden");
}

function refreshAudioControls() {
  const soundButton = document.getElementById("soundFeedbackBtn");
  const soundLabel = document.getElementById("soundFeedbackLabel");
  soundButton?.classList.toggle("media-active", uiSoundEnabled);
  soundButton?.classList.toggle("sound-muted", !uiSoundEnabled);
  if (soundLabel) soundLabel.textContent = uiSoundEnabled ? "开启" : "关闭";
  if (soundButton) {
    soundButton.title = uiSoundEnabled ? "按钮音效已开启" : "按钮音效已关闭";
    soundButton.setAttribute("aria-pressed", uiSoundEnabled ? "true" : "false");
  }
}

function ensureAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  if (!audioContext) audioContext = new AudioContextClass();
  if (audioContext.state === "suspended") audioContext.resume().catch(() => {});
  return audioContext;
}

function playUiSound(kind = "tap") {
  if (!uiSoundEnabled || !audioUnlocked) return;
  const ctx = ensureAudioContext();
  if (!ctx) return;
  const now = ctx.currentTime;
  const profiles = {
    tap: { notes: [420], duration: 0.075, volume: 0.034, end: 1.12 },
    switch: { notes: [520, 610], duration: 0.11, volume: 0.04, end: 1.02 },
    "switch-on": { notes: [480, 660], duration: 0.13, volume: 0.045, end: 1.08 },
    "switch-off": { notes: [460, 330], duration: 0.12, volume: 0.038, end: 0.96 },
    confirm: { notes: [560, 720], duration: 0.12, volume: 0.042, end: 1.05 },
    save: { notes: [620, 820, 980], duration: 0.17, volume: 0.046, end: 1.04 },
    success: { notes: [660, 880], duration: 0.14, volume: 0.046, end: 1.05 },
    reset: { notes: [360, 500], duration: 0.12, volume: 0.04, end: 1.18 },
    cancel: { notes: [360, 300], duration: 0.1, volume: 0.032, end: 0.94 },
    error: { notes: [220, 180], duration: 0.16, volume: 0.042, type: "triangle", end: 0.9 },
  };
  const profile = profiles[kind] || profiles.tap;
  const step = profile.duration / Math.max(1, profile.notes.length);
  profile.notes.forEach((freq, index) => {
    const start = now + (index * step);
    const stop = start + step + 0.018;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = profile.type || "sine";
    osc.frequency.setValueAtTime(freq, start);
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, freq * (profile.end || 1.08)), stop);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(profile.volume || 0.04, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, stop);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(stop + 0.01);
  });
}

function buttonSoundKind(button) {
  const id = button?.id || "";
  if (id === "confirmOkBtn") return "confirm";
  if (id === "confirmCancelBtn") return "cancel";
  if (id === "saveConfigBtn" || id === "savePathOptionsBtn") return "confirm";
  if (id === "resetConfigBtn") return "reset";
  if (id === "enableAllToolsBtn") return "switch-on";
  if (id === "disableAllToolsBtn") return "switch-off";
  if (id === "paletteToggleBtn" || id === "appearanceToggleBtn") return "switch";
  if (id === "soundFeedbackBtn") return "switch";
  if (button?.classList?.contains("tool-action")) return "";
  return button?.classList?.contains("btn-primary") ? "confirm" : "tap";
}

function unlockAudioFeedback() {
  audioUnlocked = true;
  ensureAudioContext();
}

function refreshThemeControls() {
  const paletteLabel = document.getElementById("paletteModeLabel");
  const appearanceLabel = document.getElementById("appearanceModeLabel");
  if (paletteLabel) paletteLabel.textContent = PALETTE_LABELS[paletteMode] || "石墨";
  if (appearanceLabel) appearanceLabel.textContent = APPEARANCE_LABELS[appearanceMode] || "自动";
  refreshAudioControls();
  refreshCardTransparencyControls();
}

function applyPalette(mode = getStoredPaletteMode()) {
  paletteMode = PALETTE_MODES.includes(mode) ? mode : "luxury";
  document.documentElement.dataset.palette = paletteMode;
  refreshThemeControls();
}

function applyAppearance(mode = getStoredAppearanceMode()) {
  appearanceMode = APPEARANCE_MODES.includes(mode) ? mode : "auto";
  document.documentElement.dataset.appearance = appearanceMode;
  document.documentElement.dataset.theme = resolveAppearance(appearanceMode);
  refreshThemeControls();
}

async function cyclePaletteMode() {
  const current = document.documentElement.dataset.palette || paletteMode || getStoredPaletteMode();
  const currentIndex = PALETTE_MODES.includes(current) ? PALETTE_MODES.indexOf(current) : 0;
  const next = PALETTE_MODES[(currentIndex + 1) % PALETTE_MODES.length];
  paletteMode = next;
  savePaletteLocally(next);
  applyPalette(next);
  await saveUiPreferences();
  showToast(`配色已切换为 ${PALETTE_LABELS[next] || next}`);
}

async function cycleAppearanceMode() {
  const current = appearanceMode || getStoredAppearanceMode();
  const currentIndex = APPEARANCE_MODES.includes(current) ? APPEARANCE_MODES.indexOf(current) : 0;
  const next = APPEARANCE_MODES[(currentIndex + 1) % APPEARANCE_MODES.length];
  appearanceMode = next;
  saveAppearanceLocally(next);
  applyAppearance(next);
  await saveUiPreferences();
  showToast(`明暗模式已切换为 ${APPEARANCE_LABELS[next] || next}`);
}

async function loadUiPreferences() {
  try {
    const data = await api.safeGet("ui_preferences");
    const prefs = data.preferences || {};
    const palette = prefs.palette_mode;
    const appearance = prefs.appearance_mode;
    if (PALETTE_MODES.includes(palette)) {
      paletteMode = palette;
      savePaletteLocally(palette);
    }
    if (APPEARANCE_MODES.includes(appearance)) {
      appearanceMode = appearance;
      saveAppearanceLocally(appearance);
    }
    uiSoundEnabled = prefs.ui_sound_enabled !== false;
    cardTransparency = clampCardTransparency(
      prefs.card_transparency === undefined ? getStoredCardTransparency() : prefs.card_transparency
    );
    saveCardTransparencyLocally(cardTransparency);
    applyCardTransparency(cardTransparency);
  } catch (e) {
    console.warn("loadUiPreferences", e);
  }
  applyPalette(paletteMode);
  applyAppearance(appearanceMode);
  refreshAudioControls();
}

async function saveUiPreferences() {
  if (!api) return;
  try {
    await api.safePost("ui_preferences/save", {
      palette_mode: paletteMode,
      appearance_mode: appearanceMode,
      ui_sound_enabled: uiSoundEnabled,
      card_transparency: cardTransparency,
    });
  } catch (e) {
    console.warn("saveUiPreferences", e);
  }
}

function handleCardTransparencyInput(event) {
  applyCardTransparency(event.currentTarget.value);
  saveCardTransparencyLocally(cardTransparency);
  scheduleCardTransparencySave();
}

function scheduleCardTransparencySave() {
  saveCardTransparencyLocally(cardTransparency);
  window.clearTimeout(cardTransparencySaveTimer);
  cardTransparencySaveTimer = window.setTimeout(() => {
    saveCardTransparencyLocally(cardTransparency);
    saveUiPreferences();
  }, 450);
}

function flushCardTransparencySave() {
  window.clearTimeout(cardTransparencySaveTimer);
  saveCardTransparencyLocally(cardTransparency);
  saveUiPreferences();
}

async function handleCardTransparencyChange(event) {
  applyCardTransparency(event.currentTarget.value);
  saveCardTransparencyLocally(cardTransparency);
  window.clearTimeout(cardTransparencySaveTimer);
  await saveUiPreferences();
  playUiSound("switch");
  showToast(`卡片透明度 ${cardTransparency}%`);
}

async function toggleUiSoundFeedback() {
  const nextEnabled = !uiSoundEnabled;
  unlockAudioFeedback();
  if (nextEnabled) {
    uiSoundEnabled = true;
    playUiSound("switch-on");
  } else {
    playUiSound("switch-off");
    uiSoundEnabled = false;
  }
  refreshAudioControls();
  await saveUiPreferences();
  showToast(uiSoundEnabled ? "按钮音效已开启" : "按钮音效已关闭");
}

async function init() {
  setStartupLoading("读取配置", "正在加载工具与权限配置");
  applyPalette();
  applyAppearance();
  cardTransparency = getStoredCardTransparency();
  applyCardTransparency(cardTransparency);
  window.matchMedia?.("(prefers-color-scheme: dark)")?.addEventListener?.("change", () => {
    if (appearanceMode === "auto") applyAppearance("auto");
  });

  document.getElementById("paletteToggleBtn")?.addEventListener("click", cyclePaletteMode);
  document.getElementById("appearanceToggleBtn")?.addEventListener("click", cycleAppearanceMode);
  document.getElementById("cardTransparencyInput")?.addEventListener("input", handleCardTransparencyInput);
  document.getElementById("cardTransparencyInput")?.addEventListener("change", handleCardTransparencyChange);
  document.getElementById("soundFeedbackBtn")?.addEventListener("click", toggleUiSoundFeedback);
  document.addEventListener("pointerdown", unlockAudioFeedback, { once: true, capture: true });
  document.addEventListener("keydown", unlockAudioFeedback, { once: true, capture: true });
  document.addEventListener("click", event => {
    const button = event.target?.closest?.("button");
    if (!button || button.disabled) return;
    const soundKind = buttonSoundKind(button);
    if (soundKind) playUiSound(soundKind);
  }, true);
  window.addEventListener("beforeunload", flushCardTransparencySave);
  document.getElementById("refreshGroupsBtn")?.addEventListener("click", async () => {
    await loadContacts();
    showToast("群聊和私聊列表已刷新");
  });
  document.getElementById("dashboardSearch")?.addEventListener("input", event => {
    searchTerm = event.currentTarget.value.trim().toLowerCase();
    renderGroupList();
    if (currentConfig) renderConfigPanel();
  });
  document.querySelector(".breadcrumb")?.addEventListener("click", () => {
    const search = document.getElementById("dashboardSearch");
    if (search) search.value = "";
    searchTerm = "";
    activeGroupFilter = "all";
    renderGroupList();
    if (currentConfig) renderConfigPanel();
    document.getElementById("section-overview-top")?.scrollIntoView({ behavior: "smooth", block: "start" });
    showToast("已回到总览");
  });
  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      document.getElementById("dashboardSearch")?.focus();
    }
  });
  document.querySelectorAll(".nav-jump").forEach(button => {
    button.addEventListener("click", () => {
      if (!currentConfig) {
        showToast("请先选择配置对象");
        return;
      }
      document.querySelectorAll(".nav-jump").forEach(item => item.classList.toggle("active", item === button));
      const target = document.getElementById(`section-${button.dataset.jump}`);
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  await loadUiPreferences();
  await loadToolGroups();
  await loadGlobalAdmins();
  await loadPathOptions();
  await loadContacts();
  hideStartupLoading();
}

async function loadToolGroups() {
  try {
    const data = await api.safeGet("tool_groups");
    if (data.ok) toolGroupsDef = data.groups || {};
    const label = document.getElementById("toolCountLabel");
    if (label) label.textContent = String(allToolItems().length);
  } catch (e) {
    console.error("loadToolGroups", e);
  }
}

async function loadGlobalAdmins() {
  try {
    const data = await api.safeGet("global_admin_ids");
    if (data.ok) globalAdminIds = data.admin_ids || [];
  } catch (e) {
    console.error("loadGlobalAdmins", e);
  }
}

async function loadPathOptions() {
  try {
    const data = await api.safeGet("path_options");
    if (data.ok && data.paths) pathOptions = { ...pathOptions, ...data.paths };
  } catch (e) {
    console.error("loadPathOptions", e);
  }
}

function pathValue(key) {
  return escapeHtml(pathOptions?.[key] || "");
}

function renderPathOptionsPanel() {
  return `
    <section class="dashboard-card path-card" id="section-paths">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Path Options</p>
          <h3>外部路径</h3>
        </div>
        <button class="btn btn-secondary compact" id="savePathOptionsBtn" type="button">保存路径</button>
      </div>
      <div class="path-grid">
        <label class="field">
          <span>Everything CLI</span>
          <input class="input-field path-input" data-path-key="es_path" value="${pathValue("es_path")}" placeholder="留空自动检测 es.exe">
        </label>
        <label class="field">
          <span>GitHub CLI</span>
          <input class="input-field path-input" data-path-key="gh_path" value="${pathValue("gh_path")}" placeholder="留空自动检测 gh.exe">
        </label>
        <label class="field wide">
          <span>备份目录</span>
          <input class="input-field path-input" data-path-key="backup_dir" value="${pathValue("backup_dir")}" placeholder="留空使用默认备份目录">
        </label>
      </div>
    </section>`;
}

async function savePathOptions() {
  document.querySelectorAll(".path-input[data-path-key]").forEach(input => {
    pathOptions[input.dataset.pathKey] = input.value.trim();
  });
  try {
    const data = await api.safePost("path_options/save", pathOptions);
    if (data.ok) {
      pathOptions = { ...pathOptions, ...data.paths };
      playUiSound("save");
      showToast("外部路径已保存");
      return;
    }
    playUiSound("error");
    showToast("外部路径保存失败");
  } catch (e) {
    console.error("savePathOptions", e);
    playUiSound("error");
    showToast("外部路径保存请求失败");
  }
}

async function loadContacts() {
  try {
    const [groups, contacts] = await Promise.all([api.safeGet("groups"), api.safeGet("contacts")]);
    if (!groups.ok) throw new Error("groups failed");
    const realGroups = Array.isArray(groups.groups) ? groups.groups.filter(g => g && g.id !== "__default__") : [];
    groupsData = sortContacts(realGroups.map(g => ({ ...g, kind: "group" })));
    contactsData = contacts.ok && Array.isArray(contacts.contacts)
      ? sortContacts(contacts.contacts.map(c => ({ ...c, kind: "private" })))
      : [];
    renderGroupList();
  } catch (e) {
    console.error("loadContacts", e);
    showToast("群聊和私聊列表加载失败");
  }
}

function groupAvatarHtml(item) {
  const avatar = String(item.avatar || "").trim();
  if (/^https?:\/\//i.test(avatar) || /^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(avatar)) {
    return `<img class="group-avatar" src="${escapeHtml(avatar)}" alt="" referrerpolicy="no-referrer">`;
  }
  const text = item.isDefault ? "全" : item.kind === "private" ? "私" : "群";
  return `<div class="group-avatar-placeholder">${text}</div>`;
}

function contactById(id) {
  return id === "__default__" ? DEFAULT_GROUP : [...groupsData, ...contactsData].find(item => item.id === id);
}

function matchesSearch(item) {
  if (!searchTerm) return true;
  const haystack = [item.name, item.id, item.user_id, item.kind].join(" ").toLowerCase();
  return haystack.includes(searchTerm);
}

function renderContactSection(key, title, items) {
  const visibleItems = items.filter(matchesSearch);
  const collapsed = collapsedMenus[key];
  const body = collapsed
    ? ""
    : (visibleItems.length ? visibleItems.map(renderContactItem).join("") : `<div class="group-empty">暂无匹配的${escapeHtml(title)}</div>`);
  return `
    <section class="contact-section ${collapsed ? "collapsed" : ""}">
      <button class="contact-section-head" type="button" data-menu="${key}">
        <span>${escapeHtml(title)}</span><b>${visibleItems.length}</b>
      </button>
      <div class="contact-section-body">${body}</div>
    </section>`;
}

function renderContactItem(item) {
  const isActive = item.id === selectedGroupId;
  const chip = item.isDefault ? "默认" : item.kind === "private" ? "私聊" : "群聊";
  const detail = item.isDefault ? "未单独配置时使用" : escapeHtml(item.user_id || item.id);
  return `
    <button class="group-item ${isActive ? "active" : ""}" type="button" data-id="${escapeHtml(item.id)}">
      ${groupAvatarHtml(item)}
      <span class="group-copy">
        <strong>${escapeHtml(item.name)}</strong>
        <small>${detail}</small>
      </span>
      <em>${chip}</em>
    </button>`;
}

function renderGroupList() {
  const container = document.getElementById("groupList");
  if (!container) return;
  const groupCount = document.getElementById("groupCountLabel");
  const privateCount = document.getElementById("privateCountLabel");
  if (groupCount) groupCount.textContent = String(groupsData.length);
  if (privateCount) privateCount.textContent = String(contactsData.length);

  const defaultVisible = matchesSearch(DEFAULT_GROUP) || !searchTerm;
  const globalHtml = defaultVisible ? `<section class="global-contact-card">${renderContactItem(DEFAULT_GROUP)}</section>` : "";
  container.innerHTML =
    globalHtml +
    renderContactSection("groups", "群聊列表", groupsData) +
    renderContactSection("contacts", "私聊列表", contactsData);

  container.querySelectorAll(".contact-section-head").forEach(button => {
    button.onclick = () => {
      collapsedMenus[button.dataset.menu] = !collapsedMenus[button.dataset.menu];
      renderGroupList();
    };
  });
  container.querySelectorAll(".group-item[data-id]").forEach(item => {
    item.onclick = () => selectGroup(item.dataset.id);
  });
}

async function selectGroup(groupId) {
  const requestId = ++groupRequestId;
  selectedGroupId = groupId;
  currentConfig = null;
  activeGroupFilter = "all";
  renderGroupList();
  renderConfigPanel();
  try {
    const data = await api.safeGet("group_config", { group_id: groupId });
    if (requestId !== groupRequestId) return;
    if (!data.ok) throw new Error("group_config failed");
    currentConfig = normalizeConfig({ ...data.config, group_id: groupId });
    renderConfigPanel();
  } catch (e) {
    if (requestId !== groupRequestId) return;
    console.error("selectGroup", e);
    showToast("配置加载失败");
  }
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

function getGroupStats(groupName, tools) {
  const disabled = new Set(currentConfig?.disabled_tools || []);
  const enabled = tools.filter(tool => !disabled.has(tool.id)).length;
  const total = tools.length;
  return {
    enabled,
    disabled: total - enabled,
    total,
    ratio: total ? Math.round((enabled / total) * 100) : 0,
    groupEnabled: currentConfig?.tool_groups?.[groupName] !== false,
  };
}

function formatDate() {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "2-digit", year: "numeric" }).format(new Date());
}

function currentTargetMeta() {
  const contact = contactById(selectedGroupId);
  const fallbackName = selectedGroupId.startsWith("private:")
    ? `私聊 ${selectedGroupId.slice(8)}`
    : `群聊 ${selectedGroupId}`;
  const name = contact?.name || fallbackName;
  const kind = contact?.isDefault ? "全局" : contact?.kind === "private" ? "私聊" : "群聊";
  const hint = selectedGroupId === "__default__"
    ? "默认配置会影响所有未单独配置的群聊和私聊。"
    : contact?.kind === "private"
      ? "这里只控制该私聊场景下 DevKit 工具的可用范围。"
      : "这里只控制该群聊场景下 DevKit 工具的可用范围。";
  return { name, kind, hint };
}

function renderMetricCards(allTools, enabledTools) {
  const groupCount = Object.keys(toolGroupsDef).length;
  const disabledTools = Math.max(allTools.length - enabledTools, 0);
  const enabledGroups = Object.keys(currentConfig.tool_groups || {}).filter(key => currentConfig.tool_groups[key] !== false).length;
  const metrics = [
    ["工具总数", allTools.length, "已注册工具", "total"],
    ["可用工具", enabledTools, "当前对象已开启", "on"],
    ["关闭工具", disabledTools, "当前对象已关闭", "off"],
    ["启用分组", `${enabledGroups}/${groupCount}`, "工具组总开关", "group"],
  ];
  return metrics.map(([label, value, caption, tone], index) => `
    <article class="metric-card ${tone}">
      <div class="metric-head">
        <span>${label}</span>
        <div class="mini-bars" aria-hidden="true">${[0, 1, 2, 3, 4].map(i => `<i style="height:${12 + ((index + i) % 5) * 3}px"></i>`).join("")}</div>
      </div>
      <strong>${escapeHtml(value)}</strong>
      <small>${caption}</small>
    </article>`).join("");
}

function renderTrendCard() {
  const entries = sortedGroupEntries();
  const maxTools = Math.max(...entries.map(([, tools]) => tools.length), 1);
  const scaleLabels = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0]
    .map(value => `<span>${value}</span>`)
    .join("");
  const monthLabels = entries.slice(0, 12).map(([groupName, tools]) => {
    const stats = getGroupStats(groupName, tools);
    const height = 18 + Math.round((stats.total / maxTools) * 110);
    const enabledHeight = chartMode === "group"
      ? height
      : Math.max(6, Math.round(height * (stats.ratio / 100)));
    return `
      <div class="chart-column" title="${escapeHtml(groupName)}：${stats.enabled}/${stats.total}">
        <div class="bar-rail">
          <i class="bar-total" style="height:${height}px"></i>
          <i class="bar-enabled" style="height:${enabledHeight}px"></i>
        </div>
        <span>${escapeHtml(iconForName(groupName))}</span>
      </div>`;
  }).join("");
  const metaValue = chartMode === "group" ? entries.length : getEnabledToolCount();
  const metaCaption = chartMode === "group" ? "个工具组参与统计" : "个工具可用";
  const metaLabel = chartMode === "group" ? "分组容量" : "当前对象";
  return `
    <section class="dashboard-card trend-card" id="section-overview">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Tool Availability</p>
          <h3>工具启用分布</h3>
        </div>
        <div class="segmented" role="group" aria-label="图表统计模式">
          <button class="segment-button ${chartMode === "group" ? "active" : ""}" type="button" data-chart-mode="group">Group</button>
          <button class="segment-button ${chartMode === "live" ? "active" : ""}" type="button" data-chart-mode="live">Live</button>
        </div>
      </div>
      <div class="chart-meta">
        <span>${metaLabel}</span>
        <strong>${metaValue}</strong>
        <span>${metaCaption}</span>
      </div>
      <div class="bar-chart">
        <div class="chart-scale" aria-hidden="true">${scaleLabels}</div>
        <div class="chart-bars">${monthLabels || `<div class="chart-empty">暂无工具组数据</div>`}</div>
      </div>
    </section>`;
}

function renderBreakdownCard() {
  const entries = sortedGroupEntries();
  const visibleEntries = breakdownExpanded ? entries : entries.slice(0, 6);
  const hiddenCount = Math.max(entries.length - visibleEntries.length, 0);
  const rows = visibleEntries.map(([groupName, tools]) => {
    const stats = getGroupStats(groupName, tools);
    return `
      <div class="breakdown-row ${stats.groupEnabled ? "" : "muted"}">
        <div class="breakdown-icon">${escapeHtml(iconForName(groupName))}</div>
        <div class="breakdown-copy">
          <strong>${escapeHtml(groupName)}</strong>
          <span>${stats.enabled}/${stats.total} 个工具可用</span>
          <div class="progress"><i style="width:${stats.ratio}%"></i></div>
        </div>
        <label class="switch" title="工具组总开关">
          <input class="group-toggle" type="checkbox" data-group="${escapeHtml(groupName)}" ${stats.groupEnabled ? "checked" : ""}>
          <span class="switch-track"></span><span class="switch-thumb"></span>
        </label>
      </div>`;
  }).join("");
  const moreRow = hiddenCount > 0
    ? `<button class="breakdown-more-row" type="button" data-breakdown-toggle>展开其余 ${hiddenCount} 个分组</button>`
    : "";
  return `
    <section class="dashboard-card breakdown-card" id="section-groups">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Group Controls</p>
          <h3>工具分组</h3>
        </div>
        <button class="more-button" type="button" data-breakdown-toggle aria-label="${breakdownExpanded ? "折叠工具分组" : "展开全部工具分组"}">${breakdownExpanded ? "收起" : "全部"}</button>
      </div>
      <div class="breakdown-list">${rows || `<div class="table-empty">暂无工具分组</div>`}${moreRow}</div>
    </section>`;
}

function renderAdminCard(adminIdsStr) {
  return `
    <section class="dashboard-card admin-card" id="section-admins">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Permission</p>
          <h3>管理员权限</h3>
        </div>
      </div>
      <div class="admin-grid">
        <div class="admin-note">
          <span>全局管理员</span>
          <strong>${escapeHtml(adminIdsStr)}</strong>
        </div>
        <label class="field">
          <span>额外管理员 QQ</span>
          <input class="input-field" id="extraAdminIds" type="text" value="${escapeHtml(currentConfig.extra_admin_ids)}" placeholder="例如：123456,987654">
        </label>
      </div>
    </section>`;
}

function renderBulkCard() {
  return `
    <section class="dashboard-card bulk-card">
      <div class="card-title-row">
        <div>
          <p class="eyebrow">Quick Actions</p>
          <h3>批量操作</h3>
        </div>
      </div>
      <div class="bulk-actions">
        <button class="bulk-row" id="enableAllToolsBtn" type="button">
          <span>开启全部工具</span>
          <b>打开所有工具组与单工具</b>
        </button>
        <button class="bulk-row danger" id="disableAllToolsBtn" type="button">
          <span>关闭全部工具</span>
          <b>关闭所有工具组与单工具</b>
        </button>
      </div>
    </section>`;
}

function renderGroupFilters() {
  const filters = [`<button class="group-filter ${activeGroupFilter === "all" ? "active" : ""}" type="button" data-group="all">全部</button>`];
  for (const [groupName, tools] of sortedGroupEntries()) {
    filters.push(`<button class="group-filter ${activeGroupFilter === groupName ? "active" : ""}" type="button" data-group="${escapeHtml(groupName)}">${escapeHtml(groupName)}<span>${tools.length}</span></button>`);
  }
  return filters.join("");
}

function filteredToolRows() {
  const disabled = new Set(currentConfig.disabled_tools || []);
  return allToolItems().filter(tool => {
    const groupOk = activeGroupFilter === "all" || tool.groupName === activeGroupFilter;
    if (!groupOk) return false;
    if (!searchTerm) return true;
    return [tool.id, tool.name, tool.desc, tool.groupName].join(" ").toLowerCase().includes(searchTerm);
  }).map(tool => ({ ...tool, enabled: !disabled.has(tool.id) }));
}

function renderToolGroupCards() {
  const rows = filteredToolRows();
  if (!rows.length) {
    return `<tr><td colspan="5"><div class="table-empty">没有匹配的工具配置项</div></td></tr>`;
  }
  return rows.map(tool => `
    <tr class="${tool.enabled ? "" : "disabled-row"}">
      <td>
        <div class="tool-cell">
          <span>${escapeHtml(iconForName(tool.groupName))}</span>
          <div><strong>${escapeHtml(tool.name)}</strong><small>${escapeHtml(tool.id)}</small></div>
        </div>
      </td>
      <td>${escapeHtml(tool.groupName)}</td>
      <td class="desc-cell">${escapeHtml(tool.desc)}</td>
      <td><span class="status-pill ${tool.enabled ? "on" : "off"}">${tool.enabled ? "已开启" : "已关闭"}</span></td>
      <td>
        <button class="tool-action tool-switch ${tool.enabled ? "enabled" : "disabled"}" type="button" data-tool="${escapeHtml(tool.id)}" data-group-name="${escapeHtml(tool.groupName)}" aria-pressed="${tool.enabled ? "true" : "false"}">
          <span class="switch-mini" aria-hidden="true"></span>
          <b>${tool.enabled ? "关闭" : "开启"}</b>
        </button>
      </td>
    </tr>`).join("");
}

function renderConfigPanel() {
  const empty = document.getElementById("emptyState");
  const panel = document.getElementById("configPanel");
  if (!selectedGroupId || !currentConfig) {
    if (empty) empty.style.display = "grid";
    if (panel) panel.style.display = "none";
    return;
  }

  if (empty) empty.style.display = "none";
  if (!panel) return;
  panel.style.display = "block";

  const target = currentTargetMeta();
  const allTools = allToolItems();
  const enabledTools = getEnabledToolCount();
  const adminIdsStr = globalAdminIds.join("、") || "未配置";
  const disabledCount = Math.max(allTools.length - enabledTools, 0);

  panel.innerHTML = `
    <div class="dashboard-content">
      <section class="welcome-row" id="section-overview-top">
        <div>
          <p class="eyebrow">弥亚开发工具箱</p>
          <h2>Welcome back, ${escapeHtml(target.name)}</h2>
          <span>${escapeHtml(target.kind)}配置 · ${escapeHtml(target.hint)}</span>
        </div>
        <div class="welcome-actions">
          <button class="btn btn-secondary compact" id="resetConfigBtn" type="button">重置当前配置</button>
          <button class="btn btn-primary compact" id="saveConfigBtn" type="button">保存配置</button>
          <time>${formatDate()}</time>
        </div>
      </section>

      <section class="metrics-grid">${renderMetricCards(allTools, enabledTools)}</section>

      <section class="analysis-grid">
        ${renderTrendCard()}
        ${renderBreakdownCard()}
      </section>

      <section class="settings-grid">
        ${renderAdminCard(adminIdsStr)}
        ${renderBulkCard()}
        ${renderPathOptionsPanel()}
      </section>

      <section class="dashboard-card tool-table-card" id="section-tools">
        <div class="card-title-row table-head">
          <div>
            <p class="eyebrow">Recent Tools</p>
            <h3>工具配置项</h3>
          </div>
          <div class="table-summary"><strong>${enabledTools}</strong><span>开启</span><strong>${disabledCount}</strong><span>关闭</span></div>
        </div>
        <div class="filter-row">${renderGroupFilters()}</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>工具</th>
                <th>分组</th>
                <th>说明</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>${renderToolGroupCards()}</tbody>
          </table>
        </div>
      </section>
    </div>`;

  bindConfigEvents();
}

function bindConfigEvents() {
  const panel = document.getElementById("configPanel");
  panel.querySelector("#extraAdminIds")?.addEventListener("input", event => {
    currentConfig.extra_admin_ids = event.currentTarget.value;
  });
  panel.querySelectorAll(".path-input[data-path-key]").forEach(input => {
    input.addEventListener("input", event => {
      pathOptions[event.currentTarget.dataset.pathKey] = event.currentTarget.value;
    });
  });
  panel.querySelectorAll(".group-toggle").forEach(input => {
    input.addEventListener("change", event => {
      const groupName = event.currentTarget.dataset.group;
      const enabled = event.currentTarget.checked;
      playUiSound(enabled ? "switch-on" : "switch-off");
      currentConfig.tool_groups[groupName] = enabled;
      asToolItems(toolGroupsDef[groupName] || []).forEach(tool => setToolDisabled(tool.id, !enabled));
      renderConfigPanel();
      showToast(`${groupName} 已${enabled ? "开启" : "关闭"}，记得保存`);
    });
  });

  panel.querySelectorAll(".tool-action").forEach(button => {
    button.addEventListener("click", event => {
      const toolId = event.currentTarget.dataset.tool;
      const disabledSet = new Set(currentConfig.disabled_tools || []);
      const shouldDisable = !disabledSet.has(toolId);
      playUiSound(shouldDisable ? "switch-off" : "switch-on");
      setToolDisabled(toolId, shouldDisable);
      renderConfigPanel();
      showToast(`${toolId} 已${shouldDisable ? "关闭" : "开启"}，记得保存`);
    });
  });

  panel.querySelectorAll(".group-filter").forEach(button => {
    button.addEventListener("click", event => {
      activeGroupFilter = event.currentTarget.dataset.group || "all";
      renderConfigPanel();
    });
  });

  panel.querySelectorAll(".segment-button[data-chart-mode]").forEach(button => {
    button.addEventListener("click", event => {
      chartMode = event.currentTarget.dataset.chartMode === "group" ? "group" : "live";
      renderConfigPanel();
      showToast(chartMode === "group" ? "图表已切换为分组容量" : "图表已切换为实时启用");
    });
  });

  panel.querySelectorAll("[data-breakdown-toggle]").forEach(button => {
    button.addEventListener("click", () => {
      breakdownExpanded = !breakdownExpanded;
      renderConfigPanel();
      showToast(breakdownExpanded ? "已展开全部工具分组" : "已折叠工具分组");
    });
  });

  document.getElementById("enableAllToolsBtn")?.addEventListener("click", async () => {
    setAllToolsState(true);
    renderConfigPanel();
    showToast("已开启全部工具，记得保存");
  });
  document.getElementById("disableAllToolsBtn")?.addEventListener("click", async () => {
    setAllToolsState(false);
    renderConfigPanel();
    showToast("已关闭全部工具，记得保存");
  });
  document.getElementById("saveConfigBtn")?.addEventListener("click", saveConfig);
  document.getElementById("resetConfigBtn")?.addEventListener("click", resetConfig);
  document.getElementById("savePathOptionsBtn")?.addEventListener("click", savePathOptions);
}

function setAllToolsState(enabled) {
  for (const groupName of Object.keys(toolGroupsDef)) {
    currentConfig.tool_groups[groupName] = enabled;
  }
  currentConfig.disabled_tools = enabled ? [] : allToolItems().map(tool => tool.id).sort();
}

function setToolDisabled(toolId, disabled) {
  const set = new Set(currentConfig.disabled_tools || []);
  if (disabled) set.add(toolId);
  else set.delete(toolId);
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
    mask.onclick = event => {
      if (event.target === mask) cleanup(false);
    };
  });
}

function touchCurrentGroup() {
  if (!selectedGroupId) return;
  const now = Math.floor(Date.now() / 1000);
  const update = item => item.id === selectedGroupId ? { ...item, updated_at: now } : item;
  if (selectedGroupId.startsWith("private:")) contactsData = sortContacts(contactsData.map(update));
  else groupsData = sortContacts(groupsData.map(update));
  renderGroupList();
}

function sortContacts(items, keepDefault = false) {
  return [...items].sort((a, b) => {
    if (keepDefault && a.id === "__default__") return -1;
    if (keepDefault && b.id === "__default__") return 1;
    return Number(b.updated_at || 0) - Number(a.updated_at || 0);
  });
}

async function persistConfig(message = "配置已保存，立即生效") {
  if (!currentConfig || !selectedGroupId) return false;
  const savingConfig = currentConfig;
  const adminInput = document.getElementById("extraAdminIds");
  if (adminInput) currentConfig.extra_admin_ids = adminInput.value.trim();
  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: currentConfig.extra_admin_ids,
    tool_groups: { ...currentConfig.tool_groups },
    disabled_tools: [...currentConfig.disabled_tools],
  };
  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      // Keep edits made while the save request was in flight.
      if (currentConfig === savingConfig && selectedGroupId === payload.group_id) {
        renderConfigPanel();
      }
      playUiSound("save");
      showToast(message);
      if (selectedGroupId === payload.group_id) touchCurrentGroup();
      await loadContacts();
      return true;
    }
    playUiSound("error");
    showToast("保存失败");
  } catch (e) {
    console.error("persistConfig", e);
    playUiSound("error");
    showToast("保存请求失败");
  }
  return false;
}

async function saveConfig() {
  const ok = await showConfirm("保存当前工具箱权限配置？保存后会在运行中立即生效。", "保存配置");
  if (!ok) return;
  await persistConfig("配置已保存，立即生效");
}

async function resetConfig() {
  const ok = await showConfirm("重置当前对象配置？额外管理员会清空，所有工具会重新开启。", "重置配置");
  if (!ok) return;
  const toolGroups = {};
  for (const groupName of Object.keys(toolGroupsDef)) toolGroups[groupName] = true;
  currentConfig = { group_id: selectedGroupId, extra_admin_ids: "", tool_groups: toolGroups, disabled_tools: [] };
  renderConfigPanel();
  showToast("已重置当前配置，记得保存");
}

function showToast(message) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => el.classList.remove("show"), 2200);
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
    setStartupLoading("读取配置", "正在连接插件配置");
    bridge = bridge || await waitForBridge();
    if (bridge?.ready) await bridge.ready();
    api = createApi(bridge);
    await init();
  } catch (e) {
    console.error("[DevKit] boot failed", e);
    hideStartupLoading();
    showToast("配置页初始化失败");
  }
}

boot();
