import { createApi } from "./api.js";

let bridge = window.AstrBotPluginPage;

const PALETTE_KEY = "irmia_devkit_palette_mode";
const APPEARANCE_KEY = "irmia_devkit_appearance_mode";
const CARD_TRANSPARENCY_KEY = "irmia_devkit_card_transparency";
const PALETTE_MODES = ["luxury", "bluewhite", "vivid", "void"];
const APPEARANCE_MODES = ["auto", "dark", "light"];
const MEDIA_AUDIO_MODES = ["video", "audio", "both", "off"];
const PALETTE_LABELS = { luxury: "石墨", bluewhite: "晴空", vivid: "珊瑚", void: "夜色" };
const APPEARANCE_LABELS = { auto: "自动", dark: "深色", light: "浅色" };
const BACKGROUND_MODES = ["preset", "custom"];
const BACKGROUND_KIND_LABELS = { image: "图片", gif: "动图", video: "视频" };
const MEDIA_AUDIO_LABELS = { video: "视频声", audio: "背景音", both: "同时", off: "全关" };
const DEFAULT_CARD_TRANSPARENCY = 18;
const CARD_TRANSPARENCY_MAX = 95;
const MEDIA_UPLOAD_CHUNK_BYTES = 384 * 1024;
const MEDIA_READ_CHUNK_BYTES = 128 * 1024;
const VIDEO_PROGRESS_KEY_PREFIX = "irmia_devkit_video_progress:";
const VIDEO_PROGRESS_RESET_GUARD_SECONDS = 2;
const VIDEO_MIME_BY_EXT = {
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".ogg": "video/ogg",
  ".ogv": "video/ogg",
  ".mov": "video/quicktime",
};
const AUDIO_MIME_BY_EXT = {
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".ogg": "audio/ogg",
  ".oga": "audio/ogg",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
  ".flac": "audio/flac",
  ".webm": "audio/webm",
};
const IMAGE_MIME_BY_EXT = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".bmp": "image/bmp",
  ".ico": "image/x-icon",
};

let paletteMode = "luxury";
let appearanceMode = "auto";
let backgroundMode = "preset";
let backgroundMediaEnabled = true;
let customBackgroundUrl = "";
let backgroundMedia = null;
let backgroundAudioMedia = null;
let savedLocalVideoMedia = null;
let uiSoundEnabled = true;
let mediaAudioMode = "video";
let videoSoundEnabled = false;
let videoSoundUserSet = false;
let cardTransparency = DEFAULT_CARD_TRANSPARENCY;
let audioUnlocked = false;
let audioContext = null;
let pendingBackgroundAudioPlay = false;
let activeBackgroundObjectUrl = "";
let pendingVideoSeek = null;
let videoProgressSaveTimer = 0;
let videoProgressHeartbeatTimer = 0;
let videoProgressHeartbeatLastSyncAt = 0;
let videoProgressRestoreTarget = 0;
let videoProgressRestoring = false;
let cardTransparencySaveTimer = 0;
let api = null;
let toolGroupsDef = {};
let groupsData = [];
let contactsData = [];
let selectedGroupId = "";
let currentConfig = null;
let globalAdminIds = [];
let pathOptions = { es_path: "", gh_path: "", backup_dir: "" };
let searchTerm = "";
let activeGroupFilter = "all";
let chartMode = "live";
let breakdownExpanded = false;

const collapsedMenus = { groups: true, contacts: true };
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

function mediaSource(media) {
  return String(media?.url || media?.data_url || "");
}

function backgroundTypeForSource(source) {
  const value = String(source || "").trim().toLowerCase();
  if (value.startsWith("data:image/gif")) return "gif";
  if (value.startsWith("data:image/")) return "image";
  if (value.startsWith("data:video/") || value.startsWith("blob:")) return "video";
  return "";
}

function backgroundTypeForMedia(media) {
  if (!media) return "";
  const mime = String(media.mime || "").toLowerCase();
  if (media.kind === "video" || mime.startsWith("video/")) return "video";
  if (mime === "image/gif") return "gif";
  if (media.kind === "image" || mime.startsWith("image/")) return "image";
  return backgroundTypeForSource(mediaSource(media));
}

function fileExtension(filename) {
  const match = String(filename || "").toLowerCase().match(/\.[a-z0-9]+$/);
  return match ? match[0] : "";
}

function mimeFromExtension(filename) {
  const ext = fileExtension(filename);
  return VIDEO_MIME_BY_EXT[ext] || AUDIO_MIME_BY_EXT[ext] || IMAGE_MIME_BY_EXT[ext] || "";
}

function safeStorageToken(value) {
  return String(value || "")
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 72) || "local";
}

function localVideoIdForFile(file) {
  const name = safeStorageToken(file?.name || "video");
  const size = Math.max(0, Number(file?.size || 0));
  const modified = Math.max(0, Number(file?.lastModified || 0));
  return `${name}_${size}_${modified}`.slice(0, 120);
}

function matchesSavedLocalVideo(file, localId) {
  if (!savedLocalVideoMedia) return false;
  if (savedLocalVideoMedia.local_id === localId) return true;
  const savedName = String(savedLocalVideoMedia.filename || "");
  const savedSize = Number(savedLocalVideoMedia.size || 0);
  return savedName === String(file?.name || "") && (!savedSize || savedSize === Number(file?.size || 0));
}

function videoProgressStorageKey(media) {
  const id = media?.local_id || media?.progress_key || media?.storage || media?.filename || "";
  return id ? `${VIDEO_PROGRESS_KEY_PREFIX}${safeStorageToken(id)}` : "";
}

function readSavedVideoPlaybackTime(media) {
  const key = videoProgressStorageKey(media);
  if (!key) return Number(media?.playback_time || 0) || 0;
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "{}");
    const time = Number(parsed.time);
    if (Number.isFinite(time) && time > 0) return time;
  } catch { /* ignore */ }
  return Number(media?.playback_time || 0) || 0;
}

function writeSavedVideoPlaybackTime(media, time) {
  const key = videoProgressStorageKey(media);
  const value = Number(time);
  if (!key || !Number.isFinite(value) || value < 0) return;
  const rounded = Math.max(0, Number(value.toFixed(2)));
  try {
    localStorage.setItem(key, JSON.stringify({ time: rounded, updated_at: Date.now() }));
  } catch { /* ignore */ }
  if (media) media.playback_time = rounded;
}

function hasReachedVideoRestoreTarget(video) {
  if (!videoProgressRestoreTarget) return true;
  if (!video) return false;
  const time = Number(video.currentTime || 0);
  if (!Number.isFinite(time)) return false;
  return time >= Math.max(0.25, videoProgressRestoreTarget - 0.5);
}

function markVideoProgressRestored(video) {
  if (!videoProgressRestoring && !videoProgressRestoreTarget) return true;
  if (!hasReachedVideoRestoreTarget(video)) return false;
  videoProgressRestoreTarget = 0;
  videoProgressRestoring = false;
  return true;
}

function restoreVideoPlaybackProgress(video, media) {
  const savedTime = readSavedVideoPlaybackTime(media);
  videoProgressRestoreTarget = 0;
  videoProgressRestoring = false;
  if (!video || !savedTime) return;
  const seek = () => {
    const duration = Number(video.duration || 0);
    const nextTime = duration > 1 ? Math.min(savedTime, Math.max(0, duration - 0.6)) : savedTime;
    videoProgressRestoreTarget = Number.isFinite(nextTime) && nextTime > 0 ? nextTime : 0;
    videoProgressRestoring = videoProgressRestoreTarget > 0;
    try {
      if (Number.isFinite(nextTime) && nextTime > 0) video.currentTime = nextTime;
    } catch {
      pendingVideoSeek = nextTime;
    }
  };
  if (video.readyState >= 1) seek();
  else {
    pendingVideoSeek = savedTime;
    videoProgressRestoring = true;
    video.addEventListener("loadedmetadata", seek, { once: true });
  }
}

function shouldSaveVideoPlaybackProgress(media, time, { allowReset = false } = {}) {
  if (!media || media.kind !== "video") return false;
  if (!Number.isFinite(time) || time < 0) return false;
  if (!allowReset && videoProgressRestoreTarget > 0 && time < Math.max(0.25, videoProgressRestoreTarget - 0.5)) return false;
  if (videoProgressRestoreTarget > 0 && time >= Math.max(0.25, videoProgressRestoreTarget - 0.5)) {
    videoProgressRestoreTarget = 0;
    videoProgressRestoring = false;
  }
  if (videoProgressRestoring && !allowReset) return false;
  const previousTime = readSavedVideoPlaybackTime(media);
  if (!allowReset && previousTime > VIDEO_PROGRESS_RESET_GUARD_SECONDS && time < VIDEO_PROGRESS_RESET_GUARD_SECONDS) return false;
  return true;
}

function saveVideoPlaybackProgress({ syncPreferences = false, allowReset = false } = {}) {
  const video = document.getElementById("customBackgroundVideo");
  if (!video || !backgroundMedia || backgroundMedia.kind !== "video") return;
  const time = Number(video.currentTime || 0);
  if (!shouldSaveVideoPlaybackProgress(backgroundMedia, time, { allowReset })) return;
  writeSavedVideoPlaybackTime(backgroundMedia, time);
  if (syncPreferences) saveUiPreferences();
}

function startVideoProgressHeartbeat() {
  if (videoProgressHeartbeatTimer) return;
  videoProgressHeartbeatLastSyncAt = Date.now();
  videoProgressHeartbeatTimer = window.setInterval(() => {
    const now = Date.now();
    const shouldSyncPreferences = now - videoProgressHeartbeatLastSyncAt >= 3500;
    saveVideoPlaybackProgress({ syncPreferences: shouldSyncPreferences });
    if (shouldSyncPreferences) videoProgressHeartbeatLastSyncAt = now;
  }, 1000);
}

function stopVideoProgressHeartbeat({ flush = false } = {}) {
  if (videoProgressHeartbeatTimer) {
    window.clearInterval(videoProgressHeartbeatTimer);
    videoProgressHeartbeatTimer = 0;
  }
  if (flush) flushVideoPlaybackProgressSave();
}

function flushVideoPlaybackProgressSave() {
  window.clearTimeout(videoProgressSaveTimer);
  saveVideoPlaybackProgress({ syncPreferences: true });
  videoProgressHeartbeatLastSyncAt = Date.now();
}

function scheduleVideoPlaybackProgressSave() {
  saveVideoPlaybackProgress();
  window.clearTimeout(videoProgressSaveTimer);
  videoProgressSaveTimer = window.setTimeout(() => saveVideoPlaybackProgress({ syncPreferences: true }), 1200);
}

function mediaKindForFile(file) {
  const mime = String(file?.type || mimeFromExtension(file?.name) || "").toLowerCase();
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("image/")) return "image";
  return "";
}

function isVideoFile(file) {
  return mediaKindForFile(file) === "video";
}

function clampCardTransparency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return DEFAULT_CARD_TRANSPARENCY;
  return Math.min(CARD_TRANSPARENCY_MAX, Math.max(0, Math.round(number)));
}

function isBackgroundAudioEnabled() {
  return Boolean(backgroundAudioMedia && mediaSource(backgroundAudioMedia) && (mediaAudioMode === "audio" || mediaAudioMode === "both"));
}

function hasStoredVideoBackground(media = backgroundMedia) {
  return Boolean(media?.kind === "video" && media.storage);
}

function hasRestorableLocalVideo(media = backgroundMedia) {
  return Boolean(media?.kind === "video" && media.local_id && !mediaSource(media));
}

function hasVideoBackground() {
  return backgroundMode === "custom" && backgroundMedia?.kind === "video" && Boolean(mediaSource(backgroundMedia));
}

function getEffectiveVideoSoundEnabled() {
  if (!hasVideoBackground()) return false;
  return mediaAudioMode === "video" || mediaAudioMode === "both";
}

function hasBackgroundAudio() {
  return Boolean(mediaSource(backgroundAudioMedia));
}

function availableMediaAudioModes() {
  const hasVideo = hasVideoBackground();
  const hasAudio = hasBackgroundAudio();
  const modes = [];
  if (hasVideo) modes.push("video");
  if (hasAudio) modes.push("audio");
  if (hasVideo && hasAudio) modes.push("both");
  modes.push("off");
  return modes;
}

function normalizeMediaAudioMode(mode = mediaAudioMode) {
  const desired = MEDIA_AUDIO_MODES.includes(mode) ? mode : "video";
  if (desired === "off") return "off";
  const modes = availableMediaAudioModes();
  return modes.includes(desired) ? desired : (modes.find(item => item !== "off") || "off");
}

function syncLegacyAudioFlags() {
  mediaAudioMode = normalizeMediaAudioMode(mediaAudioMode);
  videoSoundEnabled = mediaAudioMode === "video" || mediaAudioMode === "both";
  videoSoundUserSet = true;
  if (backgroundAudioMedia) backgroundAudioMedia.enabled = mediaAudioMode === "audio" || mediaAudioMode === "both";
}

function refreshVideoSoundControls() {
  const button = document.getElementById("backgroundAudioBtn");
  const label = document.getElementById("mediaAudioModeLabel") || document.getElementById("backgroundAudioLabel");
  const hasVideo = hasVideoBackground();
  const hasAudio = hasBackgroundAudio();
  const enabled = getEffectiveVideoSoundEnabled();
  if (!button) return;
  mediaAudioMode = normalizeMediaAudioMode(mediaAudioMode);
  button.disabled = false;
  button.classList.toggle("media-active", hasVideo || hasAudio);
  button.classList.toggle("sound-muted", mediaAudioMode === "off" || (!enabled && mediaAudioMode !== "audio" && mediaAudioMode !== "both"));
  if (label) label.textContent = hasVideo || hasAudio ? (MEDIA_AUDIO_LABELS[mediaAudioMode] || "视频声") : "上传";
  button.title = hasVideo && hasAudio
    ? "点击切换视频声 / 背景音 / 同时播放 / 全关"
    : (hasVideo ? "点击切换视频声 / 全关，上传背景音后可切换更多模式" : "点击切换背景音 / 全关");
  button.setAttribute("aria-pressed", hasVideo || hasAudio ? (mediaAudioMode === "off" ? "false" : "true") : "false");
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

function revokeBackgroundObjectUrl() {
  if (!activeBackgroundObjectUrl) return;
  if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
    URL.revokeObjectURL(activeBackgroundObjectUrl);
  }
  activeBackgroundObjectUrl = "";
}

function attachUploadedVideoSource(media, file) {
  if (media?.kind !== "video" || !file || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return media;
  }
  revokeBackgroundObjectUrl();
  activeBackgroundObjectUrl = URL.createObjectURL(file);
  return { ...media, url: activeBackgroundObjectUrl };
}

function blobToBase64Payload(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.onerror = () => reject(new Error("媒体分片读取失败"));
    reader.readAsDataURL(blob);
  });
}

function base64ToBytes(base64) {
  const binary = atob(String(base64 || ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

async function uploadChunkedMedia(slot, file) {
  if (!api) throw new Error("插件 API 尚未就绪");
  const kind = mediaKindForFile(file);
  const mime = String(file.type || mimeFromExtension(file.name) || "application/octet-stream").toLowerCase();
  const init = await api.safePost(`media/${slot}/chunk/init`, {
    filename: file.name || "media",
    mime,
    size: file.size || 0,
  });
  const uploadId = init.upload_id;
  const chunkBytes = Math.min(Number(init.chunk_bytes) || MEDIA_UPLOAD_CHUNK_BYTES, MEDIA_UPLOAD_CHUNK_BYTES);
  if (!uploadId) throw new Error("媒体上传会话创建失败");
  let index = 0;
  for (let offset = 0; offset < file.size; offset += chunkBytes) {
    const chunk = file.slice(offset, Math.min(offset + chunkBytes, file.size));
    const data = await blobToBase64Payload(chunk);
    await api.safePost(`media/${slot}/chunk/append`, {
      upload_id: uploadId,
      index,
      data,
    });
    index += 1;
    const percent = Math.min(99, Math.round(((offset + chunk.size) / file.size) * 100));
    showToast(`正在上传视频 ${percent}%...`);
  }
  const completed = await api.safePost(`media/${slot}/chunk/complete`, { upload_id: uploadId });
  const media = completed.media || completed;
  if (!media?.kind) throw new Error("媒体上传响应缺少类型");
  return kind === "video" ? attachUploadedVideoSource(media, file) : media;
}

async function downloadStoredMedia(media, slot = "background") {
  if (!api || !media?.storage) return null;
  const chunks = [];
  let offset = 0;
  let done = false;
  let guard = 0;
  const expectedSize = Math.max(0, Number(media.size || 0));
  const maxChunks = Math.max(2, Math.ceil((expectedSize || (50 * 1024 * 1024)) / MEDIA_READ_CHUNK_BYTES) + 2);
  while (!done) {
    guard += 1;
    if (guard > maxChunks) throw new Error("stored media chunk read exceeded expected size");
    const result = await api.safePost(`media/${slot}/chunk/read`, {
      storage: media.storage,
      mime: media.mime,
      offset,
      length: MEDIA_READ_CHUNK_BYTES,
    });
    const encoded = typeof result === "string" ? result : (result?.chunk_data || result?.data || "");
    if (!encoded) throw new Error("stored media chunk read returned empty data");
    const bytes = base64ToBytes(encoded);
    chunks.push(bytes);
    const nextOffset = typeof result === "object" ? Number(result.next_offset || 0) : 0;
    offset = Number.isFinite(nextOffset) && nextOffset > offset ? nextOffset : offset + bytes.byteLength;
    done = typeof result === "object"
      ? Boolean(result.done)
      : (expectedSize ? offset >= expectedSize : bytes.byteLength < MEDIA_READ_CHUNK_BYTES);
  }
  if (!chunks.length) return null;
  if (expectedSize && offset < expectedSize) throw new Error("stored media chunk read was incomplete");
  return new Blob(chunks, { type: media.mime || "application/octet-stream" });
}

async function hydrateStoredMedia(media) {
  if (!media || mediaSource(media)) return media;
  if (media.kind === "video" && media.storage) {
    try {
      const blob = await downloadStoredMedia(media, "background");
      return blob ? attachUploadedVideoSource(media, blob) : media;
    } catch (error) {
      console.warn("hydrateStoredMedia", error);
    }
  }
  return media;
}

function persistableMedia(media) {
  if (!media) return null;
  const clean = {};
  ["kind", "mime", "storage", "local_id", "filename", "size", "last_modified", "enabled", "playback_time"].forEach(key => {
    if (media[key] !== undefined && media[key] !== null && media[key] !== "") clean[key] = media[key];
  });
  if (media.local) clean.local = true;
  if (!clean.storage && !clean.local_id && mediaSource(media)) clean.data_url = mediaSource(media);
  return Object.keys(clean).length ? clean : null;
}

function resetBackgroundVideo({ revoke = true } = {}) {
  const video = document.getElementById("customBackgroundVideo");
  saveVideoPlaybackProgress();
  stopVideoProgressHeartbeat();
  videoProgressRestoreTarget = 0;
  videoProgressRestoring = false;
  if (revoke) revokeBackgroundObjectUrl();
  if (!video) return;
  video.pause();
  video.removeAttribute("src");
  video.load();
  refreshVideoSoundControls();
}

function primeBackgroundVideo(video) {
  if (!video) return;
  video.loop = true;
  video.playsInline = true;
  video.defaultPlaybackRate = 1;
  video.playbackRate = 1;
  video.preload = "auto";
  video.setAttribute("playsinline", "");
  video.setAttribute("preload", "auto");
  video.setAttribute("autoplay", "");
}

function applyBackgroundVideoAudioState(video, shouldPlaySound) {
  if (!video) return;
  video.muted = !shouldPlaySound;
  video.volume = shouldPlaySound ? 1 : 0;
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

function startBackgroundVideoPlayback(video, shouldPlaySound) {
  primeBackgroundVideo(video);
  video.muted = true;
  video.volume = 0;
  const playResult = video.play();
  playResult?.then?.(() => applyBackgroundVideoAudioState(video, shouldPlaySound));
  playResult?.then?.(() => startVideoProgressHeartbeat());
  if (!playResult?.then) startVideoProgressHeartbeat();
  return playResult;
}

function refreshBackgroundVideo(media) {
  const video = document.getElementById("customBackgroundVideo");
  if (!video) return;
  const source = media?.kind === "video" ? mediaSource(media) : "";
  if (!source) {
    resetBackgroundVideo();
    return;
  }
  const sourceChanged = video.src !== source;
  if (sourceChanged) {
    setStartupLoading("缓存视频", "正在准备本地视频背景");
    video.src = source;
    restoreVideoPlaybackProgress(video, media);
    video.addEventListener("loadeddata", hideStartupLoading, { once: true });
  } else if (pendingVideoSeek && video.readyState >= 1) {
    try {
      video.currentTime = pendingVideoSeek;
      pendingVideoSeek = null;
    } catch { /* ignore */ }
  }
  const shouldPlaySound = getEffectiveVideoSoundEnabled();
  const playResult = startBackgroundVideoPlayback(video, shouldPlaySound);
  playResult?.catch?.(error => {
    console.warn("[DevKit] background video failed to play", error);
    hideStartupLoading();
    if (shouldPlaySound && error?.name === "NotAllowedError") {
      showToast("浏览器阻止自动播放视频原声，点击页面后会再次尝试播放");
      return;
    }
    showToast("视频背景无法播放，请换 MP4/WebM/OGV/MOV 或重新上传");
  });
  refreshVideoSoundControls();
}

function refreshAudioControls() {
  const audio = document.getElementById("backgroundAudio");
  const audioButton = document.getElementById("backgroundAudioBtn");
  const replaceButton = document.getElementById("replaceBackgroundAudioBtn");
  const label = document.getElementById("mediaAudioModeLabel") || document.getElementById("backgroundAudioLabel");
  const soundButton = document.getElementById("soundFeedbackBtn");
  const soundLabel = document.getElementById("soundFeedbackLabel");
  const hasAudio = hasBackgroundAudio();
  const playing = hasAudio && audio && !audio.paused;

  mediaAudioMode = normalizeMediaAudioMode(mediaAudioMode);
  if (label) label.textContent = hasAudio || hasVideoBackground() ? (MEDIA_AUDIO_LABELS[mediaAudioMode] || "视频声") : "上传";
  audioButton?.classList.toggle("media-active", hasAudio || hasVideoBackground());
  audioButton?.classList.toggle("audio-playing", Boolean(playing));
  replaceButton?.classList.toggle("media-active", hasAudio);
  soundButton?.classList.toggle("media-active", uiSoundEnabled);
  soundButton?.classList.toggle("sound-muted", !uiSoundEnabled);
  if (soundLabel) soundLabel.textContent = uiSoundEnabled ? "开启" : "关闭";
  if (soundButton) {
    soundButton.title = uiSoundEnabled ? "按钮音效已开启" : "按钮音效已关闭";
    soundButton.setAttribute("aria-pressed", uiSoundEnabled ? "true" : "false");
  }
  refreshVideoSoundControls();
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
  if (id === "resetConfigBtn" || id === "presetBackgroundBtn") return "reset";
  if (id === "enableAllToolsBtn") return "switch-on";
  if (id === "disableAllToolsBtn") return "switch-off";
  if (id === "paletteToggleBtn" || id === "appearanceToggleBtn") return "switch";
  if (id === "backgroundAudioBtn" || id === "soundFeedbackBtn") return "switch";
  if (id === "customBackgroundBtn" || id === "replaceBackgroundAudioBtn") return "confirm";
  if (button?.classList?.contains("tool-action")) return "";
  return button?.classList?.contains("btn-primary") ? "confirm" : "tap";
}

function unlockAudioFeedback() {
  audioUnlocked = true;
  ensureAudioContext();
  if (pendingBackgroundAudioPlay) {
    pendingBackgroundAudioPlay = false;
    playBackgroundAudio().catch(() => {});
  }
  if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
}

async function applyMediaAudioMode(mode, { persist = true, autoplayAudio = true } = {}) {
  mediaAudioMode = normalizeMediaAudioMode(mode);
  syncLegacyAudioFlags();
  const audio = document.getElementById("backgroundAudio");
  const allMediaAudioOff = mediaAudioMode === "off";
  const wantsAudio = isBackgroundAudioEnabled();
  if (!allMediaAudioOff && wantsAudio && hasBackgroundAudio()) {
    if (autoplayAudio) {
      unlockAudioFeedback();
      await playBackgroundAudio().catch(() => {
        pendingBackgroundAudioPlay = true;
        showToast("浏览器阻止自动播放背景音，请再点击一次");
      });
    }
  } else {
    audio?.pause();
    pendingBackgroundAudioPlay = false;
    if (backgroundAudioMedia) backgroundAudioMedia.enabled = false;
  }
  if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
  refreshAudioControls();
  if (persist) await saveUiPreferences();
}

async function cycleMediaAudioMode() {
  const hasVideo = hasVideoBackground();
  const hasAudio = hasBackgroundAudio();
  if (!hasVideo && !hasAudio) {
    document.getElementById("backgroundAudioInput")?.click();
    return;
  }
  const modes = availableMediaAudioModes();
  const current = normalizeMediaAudioMode(mediaAudioMode);
  const currentIndex = modes.includes(current) ? modes.indexOf(current) : 0;
  const next = modes[(currentIndex + 1) % modes.length];
  await applyMediaAudioMode(next);
  showToast(`媒体音效：${MEDIA_AUDIO_LABELS[next] || next}`);
}

async function playBackgroundAudio() {
  const audio = document.getElementById("backgroundAudio");
  const source = mediaSource(backgroundAudioMedia);
  if (!audio || !source) return false;
  if (audio.src !== source) audio.src = source;
  audio.volume = 0.42;
  await audio.play();
  if (backgroundAudioMedia) backgroundAudioMedia.enabled = true;
  if (mediaAudioMode === "video" && !hasVideoBackground()) mediaAudioMode = "audio";
  if (mediaAudioMode === "off") mediaAudioMode = hasVideoBackground() ? "both" : "audio";
  refreshAudioControls();
  if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
  return true;
}

function applyBackgroundAudio(media, { autoplay = false } = {}) {
  backgroundAudioMedia = media && mediaSource(media) ? { ...media } : null;
  if (backgroundAudioMedia?.enabled && mediaAudioMode === "video" && !hasVideoBackground()) mediaAudioMode = "audio";
  const audio = document.getElementById("backgroundAudio");
  if (audio) {
    audio.pause();
    const source = mediaSource(backgroundAudioMedia);
    if (source) audio.src = source;
    else audio.removeAttribute("src");
  }
  pendingBackgroundAudioPlay = Boolean(autoplay && backgroundAudioMedia?.enabled && mediaAudioMode !== "off");
  if (pendingBackgroundAudioPlay && audioUnlocked) {
    pendingBackgroundAudioPlay = false;
    playBackgroundAudio().catch(() => {});
  }
  refreshAudioControls();
  if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
}

function refreshThemeControls() {
  const custom = backgroundMode === "custom";
  const backgroundKind = custom
    ? (backgroundTypeForMedia(backgroundMedia) || backgroundTypeForSource(customBackgroundUrl) || "image")
    : "preset";
  const hasCustomBackground = Boolean(backgroundMedia || customBackgroundUrl);
  const paletteLabel = document.getElementById("paletteModeLabel");
  const appearanceLabel = document.getElementById("appearanceModeLabel");
  const backgroundLabel = document.getElementById("backgroundModeLabel");
  const backgroundButton = document.getElementById("customBackgroundBtn");
  if (paletteLabel) paletteLabel.textContent = PALETTE_LABELS[paletteMode] || "石墨";
  if (appearanceLabel) appearanceLabel.textContent = APPEARANCE_LABELS[appearanceMode] || "自动";
  if (backgroundLabel) backgroundLabel.textContent = custom ? (BACKGROUND_KIND_LABELS[backgroundKind] || "自定义") : (hasCustomBackground ? "可启用" : "上传");
  backgroundButton?.classList.toggle("media-active", custom);
  if (backgroundButton) {
    backgroundButton.title = hasRestorableLocalVideo(backgroundMedia)
      ? "重新选择上次本地视频以续播"
      : "上传自定义背景并识别背景类型";
  }
  document.getElementById("presetBackgroundBtn")?.toggleAttribute("disabled", !custom);
  document.documentElement.dataset.backgroundMode = custom ? "custom" : "preset";
  document.documentElement.dataset.backgroundKind = backgroundKind;
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

function applyCustomBackground(url) {
  const source = String(url || "");
  applyBackgroundMedia(source ? { kind: "image", mime: "image/jpeg", data_url: source, filename: "legacy-background" } : null);
}

function applyBackgroundMedia(media) {
  const source = mediaSource(media);
  const storedVideo = hasStoredVideoBackground(media) || hasRestorableLocalVideo(media);
  backgroundMedia = (source || storedVideo) ? { ...media } : null;
  customBackgroundUrl = source;
  if (source || storedVideo) {
    backgroundMode = "custom";
    backgroundMediaEnabled = true;
    if (backgroundMedia.kind === "video" && backgroundAudioMedia && backgroundAudioMedia.enabled !== true && mediaAudioMode === "audio") {
      mediaAudioMode = "video";
    }
    syncLegacyAudioFlags();
    if (backgroundMedia.kind === "video") {
      document.documentElement.style.removeProperty("--custom-bg-image");
      if (source) refreshBackgroundVideo(backgroundMedia);
      else resetBackgroundVideo({ revoke: false });
    } else {
      resetBackgroundVideo();
      document.documentElement.style.setProperty("--custom-bg-image", `url("${source}")`);
    }
  } else {
    backgroundMode = "preset";
    backgroundMediaEnabled = false;
    customBackgroundUrl = "";
    backgroundMedia = null;
    resetBackgroundVideo();
    document.documentElement.style.removeProperty("--custom-bg-image");
  }
  applyPalette(paletteMode);
  applyAppearance(appearanceMode);
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
    const bgMode = prefs.background_mode;
    const bgUrl = prefs.custom_background_url;
    if (PALETTE_MODES.includes(palette)) {
      paletteMode = palette;
      savePaletteLocally(palette);
    }
    if (APPEARANCE_MODES.includes(appearance)) {
      appearanceMode = appearance;
      saveAppearanceLocally(appearance);
    }
    uiSoundEnabled = prefs.ui_sound_enabled !== false;
    mediaAudioMode = MEDIA_AUDIO_MODES.includes(prefs.media_audio_mode) ? prefs.media_audio_mode : "video";
    videoSoundEnabled = prefs.video_sound_enabled === true;
    videoSoundUserSet = prefs.video_sound_user_set === true;
    cardTransparency = clampCardTransparency(
      prefs.card_transparency === undefined ? getStoredCardTransparency() : prefs.card_transparency
    );
    saveCardTransparencyLocally(cardTransparency);
    applyCardTransparency(cardTransparency);
    const savedBackgroundMedia = prefs.background_media || null;
    savedLocalVideoMedia = savedBackgroundMedia?.local_id ? { ...savedBackgroundMedia } : null;
    backgroundMedia = await hydrateStoredMedia(savedBackgroundMedia);
    backgroundAudioMedia = prefs.background_audio || null;
    if (!MEDIA_AUDIO_MODES.includes(prefs.media_audio_mode)) {
      if (videoSoundEnabled && backgroundAudioMedia?.enabled) mediaAudioMode = "both";
      else if (backgroundAudioMedia?.enabled) mediaAudioMode = "audio";
      else mediaAudioMode = "video";
    }
    customBackgroundUrl = mediaSource(backgroundMedia) || String(bgUrl || "");
    backgroundMediaEnabled = prefs.background_media_enabled !== false;
    const hasPlayableLocalVideo = Boolean(backgroundMedia?.local_id && mediaSource(backgroundMedia));
    const hasRestorableLocal = hasRestorableLocalVideo(backgroundMedia);
    const hasSavedBackground = Boolean((backgroundMedia && (!backgroundMedia.local_id || hasPlayableLocalVideo || hasRestorableLocal || backgroundMedia.storage || mediaSource(backgroundMedia))) || customBackgroundUrl);
    backgroundMode = hasSavedBackground
      ? (backgroundMediaEnabled ? "custom" : "preset")
      : (BACKGROUND_MODES.includes(bgMode) ? bgMode : "preset");
    applyBackgroundAudio(backgroundAudioMedia, { autoplay: true });
    if (backgroundMode === "custom" && ((backgroundMedia && (mediaSource(backgroundMedia) || hasStoredVideoBackground(backgroundMedia) || hasRestorableLocalVideo(backgroundMedia))) || customBackgroundUrl)) {
      if (backgroundMedia) applyBackgroundMedia(backgroundMedia);
      else applyCustomBackground(customBackgroundUrl);
      return;
    }
    if (hasSavedBackground) {
      resetBackgroundVideo({ revoke: false });
      document.documentElement.style.removeProperty("--custom-bg-image");
      applyPalette(paletteMode);
      applyAppearance(appearanceMode);
      refreshAudioControls();
      return;
    }
  } catch (e) {
    console.warn("loadUiPreferences", e);
  }
  backgroundMode = "preset";
  backgroundMediaEnabled = false;
  backgroundMedia = null;
  customBackgroundUrl = "";
  applyPalette(paletteMode);
  applyAppearance(appearanceMode);
  refreshAudioControls();
}

async function saveUiPreferences() {
  if (!api) return;
  syncLegacyAudioFlags();
  try {
    await api.safePost("ui_preferences/save", {
      palette_mode: paletteMode,
      appearance_mode: appearanceMode,
      background_mode: backgroundMode,
      background_media_enabled: backgroundMediaEnabled,
      background_media: persistableMedia(backgroundMedia),
      background_audio: persistableMedia(backgroundAudioMedia),
      media_audio_mode: mediaAudioMode,
      ui_sound_enabled: uiSoundEnabled,
      video_sound_enabled: videoSoundEnabled,
      video_sound_user_set: videoSoundUserSet,
      card_transparency: cardTransparency,
      custom_background_url: backgroundMedia?.storage || backgroundMedia?.local_id ? "" : (customBackgroundUrl || ""),
    });
  } catch (e) {
    console.warn("saveUiPreferences", e);
  }
}

function activateStoredCustomBackground() {
  if (!backgroundMedia && !customBackgroundUrl) return false;
  backgroundMediaEnabled = true;
  if (backgroundMedia) applyBackgroundMedia(backgroundMedia);
  else applyCustomBackground(customBackgroundUrl);
  saveUiPreferences();
  showToast("已启用上次上传的背景");
  return true;
}

function handleBackgroundButtonClick() {
  if (backgroundMode === "custom") {
    if (hasRestorableLocalVideo(backgroundMedia)) showToast("请选择上次本地视频以恢复播放进度");
    document.getElementById("customBackgroundInput")?.click();
    return;
  }
  if (activateStoredCustomBackground()) return;
  document.getElementById("customBackgroundInput")?.click();
}

async function switchToPresetBackground() {
  backgroundMode = "preset";
  backgroundMediaEnabled = false;
  resetBackgroundVideo({ revoke: false });
  document.documentElement.style.removeProperty("--custom-bg-image");
  applyPalette(paletteMode);
  applyAppearance(appearanceMode);
  refreshThemeControls();
  await saveUiPreferences();
  showToast("已恢复预设背景");
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

async function handleCustomBackgroundUpload(event) {
  const file = event.currentTarget.files?.[0];
  event.currentTarget.value = "";
  if (!file) return;
  try {
    showToast(isVideoFile(file) ? "正在载入本地视频..." : "正在保存背景媒体...");
    if (isVideoFile(file)) setStartupLoading("缓存视频", "正在准备本地视频背景");
    const media = isVideoFile(file)
      ? await uploadChunkedMedia("background", file)
      : attachUploadedVideoSource(await uploadMedia("media/background/upload", file), file);
    applyBackgroundMedia(media);
    await saveUiPreferences();
    showToast(media.kind === "video" ? "本地视频背景已启用" : "自定义背景已启用");
  } catch (e) {
    console.error("handleCustomBackgroundUpload", e);
    hideStartupLoading();
    showToast(e.message || "背景处理失败");
  }
}

async function uploadMedia(endpoint, file) {
  if (bridge?.upload) {
    const result = await bridge.upload(endpoint, file);
    if (result?.ok === false) throw new Error(result.error || "媒体上传失败");
    const media = result?.media || result;
    if (!media?.kind) throw new Error("媒体响应缺少类型");
    if (!mediaSource(media) && media.kind !== "video") throw new Error("媒体响应缺少可播放数据");
    return media;
  }
  const dataUrl = await fileToDataUrl(file);
  const kind = mediaKindForFile(file) || "image";
  return { kind, mime: file.type || mimeFromExtension(file.name) || "application/octet-stream", filename: file.name, data_url: dataUrl };
}

function handleBackgroundAudioButtonClick() {
  if (!backgroundAudioMedia) {
    document.getElementById("backgroundAudioInput")?.click();
    return;
  }
  const audio = document.getElementById("backgroundAudio");
  if (audio?.paused) {
    unlockAudioFeedback();
    playBackgroundAudio()
      .then(() => saveUiPreferences())
      .catch(() => showToast("背景音播放被浏览器拦截，请再点击一次"));
  } else {
    audio?.pause();
    if (backgroundAudioMedia) backgroundAudioMedia.enabled = false;
    refreshAudioControls();
    if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
    saveUiPreferences();
    showToast("背景音已暂停");
  }
}

async function handleBackgroundAudioUpload(event) {
  const file = event.currentTarget.files?.[0];
  event.currentTarget.value = "";
  if (!file) return;
  try {
    showToast("正在保存背景音...");
    const media = await uploadMedia("media/audio/upload", file);
    media.enabled = true;
    mediaAudioMode = "audio";
    applyBackgroundAudio(media, { autoplay: true });
    unlockAudioFeedback();
    await playBackgroundAudio().catch(() => {});
    await saveUiPreferences();
    showToast("背景音已启用");
  } catch (e) {
    console.error("handleBackgroundAudioUpload", e);
    showToast(e.message || "背景音处理失败");
  }
}

async function toggleVideoSound() {
  if (!hasVideoBackground()) {
    showToast("请先上传视频背景");
    return;
  }
  videoSoundUserSet = true;
  videoSoundEnabled = !getEffectiveVideoSoundEnabled();
  refreshBackgroundVideo(backgroundMedia);
  await saveUiPreferences();
  showToast(videoSoundEnabled ? "视频原声已开启" : "视频原声已静音");
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
  document.getElementById("customBackgroundBtn")?.addEventListener("click", handleBackgroundButtonClick);
  document.getElementById("customBackgroundInput")?.addEventListener("change", handleCustomBackgroundUpload);
  document.getElementById("backgroundAudioBtn")?.addEventListener("click", cycleMediaAudioMode);
  document.getElementById("cardTransparencyInput")?.addEventListener("input", handleCardTransparencyInput);
  document.getElementById("cardTransparencyInput")?.addEventListener("change", handleCardTransparencyChange);
  document.getElementById("replaceBackgroundAudioBtn")?.addEventListener("click", () => {
    document.getElementById("backgroundAudioInput")?.click();
  });
  document.getElementById("backgroundAudioInput")?.addEventListener("change", handleBackgroundAudioUpload);
  document.getElementById("soundFeedbackBtn")?.addEventListener("click", toggleUiSoundFeedback);
  document.getElementById("presetBackgroundBtn")?.addEventListener("click", switchToPresetBackground);
  document.addEventListener("pointerdown", unlockAudioFeedback, { once: true, capture: true });
  document.addEventListener("keydown", unlockAudioFeedback, { once: true, capture: true });
  document.addEventListener("click", event => {
    const button = event.target?.closest?.("button");
    if (!button || button.disabled) return;
    const soundKind = buttonSoundKind(button);
    if (soundKind) playUiSound(soundKind);
  }, true);
  const backgroundAudio = document.getElementById("backgroundAudio");
  backgroundAudio?.addEventListener("play", () => {
    refreshAudioControls();
    if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
  });
  backgroundAudio?.addEventListener("pause", () => {
    refreshAudioControls();
    if (hasVideoBackground()) refreshBackgroundVideo(backgroundMedia);
  });
  const backgroundVideo = document.getElementById("customBackgroundVideo");
  backgroundVideo?.addEventListener("play", startVideoProgressHeartbeat);
  backgroundVideo?.addEventListener("playing", startVideoProgressHeartbeat);
  backgroundVideo?.addEventListener("timeupdate", scheduleVideoPlaybackProgressSave);
  backgroundVideo?.addEventListener("seeked", () => {
    if (!markVideoProgressRestored(backgroundVideo)) return;
    saveVideoPlaybackProgress({ syncPreferences: true });
  });
  backgroundVideo?.addEventListener("pause", () => {
    stopVideoProgressHeartbeat();
    saveVideoPlaybackProgress({ syncPreferences: true });
  });
  backgroundVideo?.addEventListener("ended", () => {
    stopVideoProgressHeartbeat();
    saveVideoPlaybackProgress({ syncPreferences: true });
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushVideoPlaybackProgressSave();
  });
  window.addEventListener("pagehide", flushVideoPlaybackProgressSave);
  window.addEventListener("beforeunload", flushVideoPlaybackProgressSave);
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
  if (item.avatar) {
    return `<img class="group-avatar" src="${escapeHtml(item.avatar)}" alt="">`;
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
    : (visibleItems.length ? visibleItems.map(renderContactItem).join("") : `<div class="group-empty">暂无匹配的${title}</div>`);
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
  selectedGroupId = groupId;
  activeGroupFilter = "all";
  renderGroupList();
  try {
    const data = await api.safeGet("group_config", { group_id: groupId });
    if (data.ok) {
      currentConfig = normalizeConfig(data.config || {});
      renderConfigPanel();
    }
  } catch (e) {
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
          <p class="eyebrow">Irmia DevKit</p>
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
  document.querySelectorAll(".group-toggle").forEach(input => {
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

  document.querySelectorAll(".tool-action").forEach(button => {
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

  document.querySelectorAll(".group-filter").forEach(button => {
    button.addEventListener("click", event => {
      activeGroupFilter = event.currentTarget.dataset.group || "all";
      renderConfigPanel();
    });
  });

  document.querySelectorAll(".segment-button[data-chart-mode]").forEach(button => {
    button.addEventListener("click", event => {
      chartMode = event.currentTarget.dataset.chartMode === "group" ? "group" : "live";
      renderConfigPanel();
      showToast(chartMode === "group" ? "图表已切换为分组容量" : "图表已切换为实时启用");
    });
  });

  document.querySelectorAll("[data-breakdown-toggle]").forEach(button => {
    button.addEventListener("click", () => {
      breakdownExpanded = !breakdownExpanded;
      renderConfigPanel();
      showToast(breakdownExpanded ? "已展开全部工具分组" : "已折叠工具分组");
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
  const adminInput = document.getElementById("extraAdminIds");
  if (adminInput) currentConfig.extra_admin_ids = adminInput.value.trim();
  const payload = {
    group_id: selectedGroupId,
    extra_admin_ids: currentConfig.extra_admin_ids,
    tool_groups: currentConfig.tool_groups,
    disabled_tools: currentConfig.disabled_tools,
  };
  try {
    const data = await api.safePost("group_config/save", payload);
    if (data.ok) {
      if (currentConfig && selectedGroupId) {
        currentConfig = normalizeConfig(payload);
        renderConfigPanel();
      }
      playUiSound("save");
      showToast(message);
      touchCurrentGroup();
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
  await persistConfig("已重置并保存");
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
