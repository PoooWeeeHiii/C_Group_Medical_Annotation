const state = {
  view: "dashboard",
  authToken: localStorage.getItem("label_platform_token") || "",
  currentUser: null,
  users: [],
  tasks: [],
  cases: [],
  caseDetails: {},
  masksByImage: {},
  versionsByCase: {},
  loadedMaskContents: {},
  restoredMaskSlices: {},
  sliceValueCache: {},
  propagatedSliceLoads: {},
  /** 重做清空后，禁止自动把已保存/AI 叠加结果写回 2D 画布 */
  suppressCanvasMaskRestore: {},
  /** 打开图像时不自动把 AI/传播结果叠到 2D 标注画布（避免“自带标注”） */
  autoOverlayOnCanvas: false,
  /** 打开图像时不自动恢复已保存的 JSON Mask 到画布（需手动点「加载」） */
  autoRestoreSavedMasks: false,
  maskQualityById: {},
  volumeMeta: {},
  volumeErrors: {},
  datasetExportResult: null,
  exportAssignments: {},
  exportMaterialize: true,
  exportStrict: true,
  activeCaseId: null,
  activeImageId: null,
  activeSlice: 0,
  activeAxis: "axial",
  activeSlices: { axial: 0, coronal: 0, sagittal: 0 },
  activeWindow: "auto",
  annotationTool: "brush",
  annotationLabel: "liver",
  annotationLabelId: 1,
  eraseCurrentClassOnly: true,
  brushRadius: Number(localStorage.getItem("label_brush_radius")) || 4,
  eraseRadius: Number(localStorage.getItem("label_erase_radius")) || 10,
  brushCursorPoint: null,
  annotationDrawing: false,
  annotationLastPoint: null,
  annotationShapeStart: null,
  annotationPolygonPoints: [],
  annotationPolygonPreviewPoint: null,
  annotationIgnoreNextClickUntil: 0,
  annotationPreviewRect: null,
  refineParams: {
    randomWalkerBeta: 90,
    roiMargin: 24,
    minVoxels: 64,
  },
  magicWandPreset: "liver",
  magicWandThreshold: 35,
  magicWandMaxPixels: 180000,
  sliceMasks: {},
  pointAnnotations: {},
  negativeScribbles: {},
  undoStack: [],
  redoStack: [],
  volumeViewMode: "2d",
  active3DMaskId: null,
  showMip: false,
  volumeLoadingKey: null,
  recoveringAnnotation: false,
  models: [],
  selectedModelId: "",
  aiPredictTarget: localStorage.getItem("label_ai_predict_target") || "all",
  inferencePreview: null,
  lastCompareResult: null,
  reviewQueue: [],
  versionDiff: null,
  versionCompareA: "",
  versionCompareB: "",
  qualityCaseId: "",
  qualityMaskId: "",
  qualityRefMaskId: "",
  qualityReport: null,
  qualityMasks: [],
  // P5: few-shot / coarse / weak
  annotationMode: "dense", // dense | coarse | scribble
  fewShotMinSlices: 3,
  labelingAssist: null,
  exportLabelSet: "dense", // dense | weak
  // 2D viewer zoom / pan (display only; annotation stays in image pixels)
  viewerZoom: 1,
  viewerPanX: 0,
  viewerPanY: 0,
  viewerPanning: false,
  viewerPanLast: null,
  trainJob: null,
  trainJobs: [],
  trainPollTimer: null,
  labelCatalog: [],
};

const titles = {
  dashboard: "数据总览",
  cases: "病例中心",
  annotation: "标注工作台",
  train: "AI训练中心",
  inference: "AI推理中心",
  versions: "版本审核",
  quality: "质量报告",
  export: "Dataset导出",
  settings: "系统设置",
};

const roleText = {
  annotator: "标注员",
  reviewer: "审核员",
  admin: "管理员",
  ai_service: "AI服务",
};

const DEFAULT_LABEL_CATALOG = [
  { label_id: 0, name: "background", display_name: "背景", color: "#1c2938", sort_order: 0, enabled: true },
  { label_id: 6, name: "heart", display_name: "心", color: "#ff6b8a", sort_order: 1, enabled: true },
  { label_id: 1, name: "liver", display_name: "肝", color: "#00e5b0", sort_order: 2, enabled: true },
  { label_id: 5, name: "spleen", display_name: "脾", color: "#b66dff", sort_order: 3, enabled: true },
  { label_id: 3, name: "lung", display_name: "肺", color: "#ffb020", sort_order: 4, enabled: true },
  { label_id: 2, name: "kidney", display_name: "肾", color: "#38a3ff", sort_order: 5, enabled: true },
  { label_id: 7, name: "bone", display_name: "骨", color: "#e2e8f0", sort_order: 6, enabled: true },
  { label_id: 4, name: "tumor", display_name: "肿瘤", color: "#ff4d4f", sort_order: 7, enabled: true },
  { label_id: 8, name: "other", display_name: "其他", color: "#94a3b8", sort_order: 8, enabled: true },
];

function effectiveLabelCatalog({ includeBackground = true, enabledOnly = true } = {}) {
  const source = (state.labelCatalog && state.labelCatalog.length)
    ? state.labelCatalog
    : DEFAULT_LABEL_CATALOG;
  return source
    .filter((item) => (includeBackground || Number(item.label_id) > 0) && (!enabledOnly || item.enabled !== false))
    .slice()
    .sort((a, b) => (Number(a.sort_order) - Number(b.sort_order)) || (Number(a.label_id) - Number(b.label_id)));
}

function labelById(labelId) {
  const id = Number(labelId);
  return effectiveLabelCatalog({ includeBackground: true, enabledOnly: false })
    .find((item) => Number(item.label_id) === id)
    || DEFAULT_LABEL_CATALOG.find((item) => Number(item.label_id) === id)
    || null;
}

function labelColor(labelId) {
  return labelById(labelId)?.color || "#00e5b0";
}

function labelDisplayText(labelId) {
  const item = labelById(labelId);
  if (!item) return `${labelId}`;
  return item.display_name || item.name;
}

function setActiveAnnotationLabel(labelId) {
  const id = Number(labelId) || 1;
  const item = labelById(id);
  state.annotationLabelId = id;
  state.annotationLabel = item?.name || `label_${id}`;
  const presetKey = LABEL_TO_MAGIC_PRESET[state.annotationLabel];
  const preset = presetKey ? magicWandPresets[presetKey] : null;
  if (preset) {
    state.magicWandPreset = presetKey;
    state.magicWandThreshold = preset.threshold;
  }
}

function canManageUsers() {
  return currentRole() === "admin";
}

function canManageLabels() {
  return currentRole() === "admin";
}

const statusText = {
  unannotated: "未标注",
  annotated: "已标注",
  pending: "待审核",
  reviewed: "已审核",
  final: "已确认",
};

const annotationTools = [
  ["brush", "画笔"],
  ["erase", "橡皮擦"],
  ["smartErase", "智能橡皮擦"],
  ["polygon", "多边形"],
  ["rectangle", "矩形ROI"],
  ["point", "点标注"],
  ["magic", "智能选择"],
  ["undo", "←"],
  ["redo", "→"],
  ["clearAll", "重做"],
  ["clear", "清空"],
];

const annotationToolTitles = {
  undo: "撤销上一步",
  redo: "恢复（撤销后回溯）",
  clearAll: "清空全部切片的手动标注",
  clear: "清空当前切片标注",
};

/**
 * 智能选择容差（种子点 HU ± threshold）。
 * range 文案来自常见 CT 参考 HU（非增强为主，个体/机型/期相会有偏差）：
 * - 心：心肌/血池约 30~60 HU
 * - 肝：实质约 45~65 HU
 * - 脾：实质约 40~60 HU
 * - 肺：实质约 -900~-500 HU（与软组织对比大，容差更大）
 * - 肾：皮质/实质约 30~50 HU
 * - 骨：皮质/松质约 200~1000+ HU
 * - 肿瘤：密度差异大，默认中等容差，建议再微调
 */
const magicWandPresets = {
  heart: { label: "心", threshold: 40, range: "参考30~60" },
  liver: { label: "肝", threshold: 35, range: "参考45~65" },
  spleen: { label: "脾", threshold: 35, range: "参考40~60" },
  lung: { label: "肺", threshold: 100, range: "参考-900~-500" },
  kidney: { label: "肾", threshold: 35, range: "参考30~50" },
  bone: { label: "骨骼", threshold: 180, range: "参考200~1000+" },
  tumor: { label: "肿瘤", threshold: 50, range: "异质，建议微调" },
  soft: { label: "软组织通用", threshold: 45, range: "参考25~50" },
  custom: { label: "自定义", threshold: 45, range: "10~250" },
};

const AI_PREDICT_TARGETS = [
  { value: "all", label: "全部器官" },
  { value: "heart", label: "心" },
  { value: "liver", label: "肝" },
  { value: "spleen", label: "脾" },
  { value: "lung", label: "肺" },
  { value: "kidney", label: "肾" },
  { value: "bone", label: "骨骼" },
  { value: "tumor", label: "疑似肿瘤" },
  { value: "other", label: "其他" },
];

const LABEL_TO_MAGIC_PRESET = {
  heart: "heart",
  liver: "liver",
  spleen: "spleen",
  lung: "lung",
  kidney: "kidney",
  bone: "bone",
  tumor: "tumor",
  other: "soft",
};

const sliceAxes = {
  axial: { label: "轴位 Axial", coordinate: "z" },
  coronal: { label: "冠状位 Coronal", coordinate: "y" },
  sagittal: { label: "矢状位 Sagittal", coordinate: "x" },
};

const $ = (selector) => document.querySelector(selector);
const API_BASE = window.location.port && window.location.port !== "8000" ? "http://127.0.0.1:8000" : "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function activeAxis() {
  return sliceAxes[state.activeAxis] ? state.activeAxis : "axial";
}

function axisLabel(axis = activeAxis()) {
  return sliceAxes[axis]?.label || axis;
}

function axisCoordinateName(axis = activeAxis()) {
  return sliceAxes[axis]?.coordinate || "z";
}

function axisSliceCount(meta, axis = activeAxis()) {
  if (!meta) return 1;
  if (axis === "coronal") return Math.max(Number(meta.height || 1), 1);
  if (axis === "sagittal") return Math.max(Number(meta.width || 1), 1);
  return Math.max(Number(meta.slice_count || 1), 1);
}

function currentSliceIndex(axis = activeAxis()) {
  return Number(state.activeSlices?.[axis] ?? state.activeSlice ?? 0);
}

function setCurrentSliceIndex(value, axis = activeAxis()) {
  const next = Math.max(0, Number(value) || 0);
  if (!state.activeSlices) state.activeSlices = { axial: 0, coronal: 0, sagittal: 0 };
  state.activeSlices[axis] = next;
  if (axis === "axial") state.activeSlice = next;
}

function sliceStorageKey(axis = activeAxis(), sliceIndex = currentSliceIndex(axis)) {
  return `${axis}:${Number(sliceIndex) || 0}`;
}

function parseSliceStorageKey(key) {
  const raw = String(key);
  if (raw.includes(":")) {
    const [axis, sliceIndex] = raw.split(":");
    return {
      axis: sliceAxes[axis] ? axis : "axial",
      sliceIndex: Number(sliceIndex) || 0,
    };
  }
  return { axis: "axial", sliceIndex: Number(raw) || 0 };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  $("#pageTitle").textContent = titles[view] || "医学影像标注";
  render();
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.authToken) headers.Authorization = `Bearer ${state.authToken}`;
  return headers;
}

function currentRole() {
  return state.currentUser?.role || null;
}

function canReview() {
  return currentRole() === "reviewer" || currentRole() === "admin";
}

function canAnnotate() {
  return currentRole() === "annotator" || currentRole() === "admin" || currentRole() === "reviewer";
}

function canConfirmFinal() {
  return canReview();
}

function canManageTasks() {
  return canReview();
}

function setAuthSession(token, user) {
  state.authToken = token || "";
  state.currentUser = user || null;
  if (token) localStorage.setItem("label_platform_token", token);
  else localStorage.removeItem("label_platform_token");
  updateAuthChrome();
}

function clearAuthSession() {
  setAuthSession("", null);
  state.users = [];
  state.tasks = [];
}

function updateAuthChrome() {
  const userPill = $("#userPill");
  const loginButton = $("#loginButton");
  const logoutButton = $("#logoutButton");
  if (userPill) {
    userPill.textContent = state.currentUser
      ? `${state.currentUser.username} · ${roleText[state.currentUser.role] || state.currentUser.role}`
      : "未登录";
  }
  if (loginButton) loginButton.classList.toggle("hidden", Boolean(state.currentUser));
  if (logoutButton) logoutButton.classList.toggle("hidden", !state.currentUser);
  const overlay = $("#loginOverlay");
  if (overlay) overlay.classList.toggle("hidden", Boolean(state.currentUser));
}

async function apiGet(path) {
  const response = await fetch(apiUrl(path), { headers: authHeaders() });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) clearAuthSession();
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || {});
    throw new Error(detail || `${path} 请求失败：${response.status}`);
  }
  return data;
}

async function apiPost(path, payload, options = {}) {
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 0);
  let timer = null;
  if (timeoutMs > 0) {
    timer = window.setTimeout(() => controller.abort(), timeoutMs);
  }
  try {
    const response = await fetch(apiUrl(path), {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload ?? {}),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) clearAuthSession();
      const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || {});
      throw new Error(detail || `${path} 请求失败：${response.status}`);
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`${path} 超时（>${Math.round(timeoutMs / 1000)}s），CPU 推理可能较慢，请稍后在 Mask 列表中刷新查看`);
    }
    throw error;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

async function apiDelete(path) {
  const response = await fetch(apiUrl(path), {
    method: "DELETE",
    headers: authHeaders(),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) clearAuthSession();
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || {});
    throw new Error(detail || `${path} 请求失败：${response.status}`);
  }
  return data;
}

async function apiPut(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "PUT",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload ?? {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) clearAuthSession();
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || {});
    throw new Error(detail || `${path} 请求失败：${response.status}`);
  }
  return data;
}

async function loadCaseDetail(caseId) {
  if (!caseId) return null;
  if (!state.caseDetails[caseId]) {
    state.caseDetails[caseId] = await apiGet(`/api/case/${caseId}`);
  }
  const detail = state.caseDetails[caseId];
  if (!state.activeImageId && detail.images?.length) {
    state.activeImageId = detail.images[0].image_id;
  }
  return detail;
}

function readableVolumeErrorMessage(message) {
  if (message.includes("NRRD data payload is shorter than expected")) {
    return "当前病例的 NRRD 文件不完整，无法读取真实体数据。";
  }
  if (message.includes("Image file not found") || message.includes("Image not found")) {
    return "当前病例的图像文件未找到。";
  }
  if (message.includes("Cannot read medical volume")) {
    return `当前病例体数据读取失败：${message}`;
  }
  return message;
}

async function loadVolumeMeta(imageId) {
  if (!imageId) return null;
  if (!state.volumeMeta[imageId]) {
    state.volumeMeta[imageId] = await apiGet(`/api/image/${imageId}/volume`);
    if (!sliceAxes[state.activeAxis]) state.activeAxis = "axial";
    const restoredSlice = state.restoredMaskSlices[imageId];
    const axis = sliceAxes[restoredSlice?.axis] ? restoredSlice.axis : state.activeAxis || "axial";
    state.activeAxis = axis;
    const maxSlice = Math.max(axisSliceCount(state.volumeMeta[imageId], axis) - 1, 0);
    if (restoredSlice && (!restoredSlice.axis || restoredSlice.axis === axis)) {
      setCurrentSliceIndex(Math.min(restoredSlice.sliceIndex ?? Math.floor(maxSlice / 2), maxSlice), axis);
    } else {
      setCurrentSliceIndex(Math.min(Math.floor(maxSlice / 2), maxSlice), axis);
    }
  }
  return state.volumeMeta[imageId];
}

async function loadImageMasks(imageId, { force = false } = {}) {
  if (!imageId) return [];
  if (force || !state.masksByImage[imageId]) {
    try {
      const data = await apiGet(`/api/image/${imageId}/masks`);
      state.masksByImage[imageId] = data.items || data.masks || [];
      if (state.autoRestoreSavedMasks && !state.suppressCanvasMaskRestore[imageId]) {
        await restoreSavedMaskContents(imageId, state.masksByImage[imageId]);
      }
    } catch (error) {
      console.warn("Mask 列表加载失败，已按空列表处理：", error);
      state.masksByImage[imageId] = [];
    }
  }
  return state.masksByImage[imageId];
}

async function loadCaseVersions(caseId, { force = false } = {}) {
  if (!caseId) return [];
  if (force || !state.versionsByCase[caseId]) {
    try {
      const data = await apiGet(`/api/case/${caseId}/versions`);
      state.versionsByCase[caseId] = data.items || [];
    } catch (error) {
      console.warn("版本列表加载失败，已按空列表处理：", error);
      state.versionsByCase[caseId] = [];
    }
  }
  return state.versionsByCase[caseId];
}

async function loadModels({ force = false } = {}) {
  if (!force && state.models.length) return state.models;
  try {
    const data = await apiGet("/api/models");
    state.models = data.items || [];
    if (!state.selectedModelId && state.models.length) {
      state.selectedModelId = state.models[0].model_id;
    } else if (state.selectedModelId && !state.models.some((item) => item.model_id === state.selectedModelId)) {
      state.selectedModelId = state.models[0]?.model_id || "";
    }
  } catch (error) {
    console.warn("模型列表加载失败：", error);
    state.models = [];
  }
  return state.models;
}

async function loadReviewQueue({ force = false } = {}) {
  if (!canReview()) {
    state.reviewQueue = [];
    return [];
  }
  if (!force && state.reviewQueue.length) return state.reviewQueue;
  try {
    const data = await apiGet("/api/review/queue");
    state.reviewQueue = data.items || [];
  } catch (error) {
    console.warn("审核队列加载失败：", error);
    state.reviewQueue = [];
  }
  return state.reviewQueue;
}

function niftiMasksForCase(caseId) {
  const detail = state.caseDetails[caseId];
  const imageIds = (detail?.images || []).map((image) => image.image_id);
  const masks = [];
  for (const imageId of imageIds) {
    for (const mask of state.masksByImage[imageId] || []) {
      if (mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz")) {
        masks.push(mask);
      }
    }
  }
  return masks.sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")));
}

async function ensureCaseMasksLoaded(caseId) {
  if (!caseId) return [];
  const detail = await loadCaseDetail(caseId);
  const images = detail?.images || [];
  for (const image of images) {
    await loadImageMasks(image.image_id);
  }
  return niftiMasksForCase(caseId);
}

async function runVersionDiff(event) {
  const button = event?.currentTarget;
  const maskA = state.versionCompareA || $("#versionCompareA")?.value;
  const maskB = state.versionCompareB || $("#versionCompareB")?.value;
  if (!maskA || !maskB) {
    showToast("请选择两个 Mask 进行版本 diff");
    return;
  }
  if (button) button.disabled = true;
  try {
    const data = await apiGet(`/api/mask/${maskA}/compare/${maskB}`);
    state.versionDiff = data;
    state.lastCompareResult = data;
    showToast(`Diff Dice=${Number(data.dice).toFixed(4)} · ΔV=${Number(data.volume_diff_ml).toFixed(2)} ml`);
    render();
  } catch (error) {
    showToast(error.message || "版本 diff 失败");
  } finally {
    if (button) button.disabled = false;
  }
}

async function rollbackMaskVersion(maskId) {
  if (!maskId) return;
  if (!window.confirm(`确认将 ${maskId} 回滚复制为新的 v3_preview？`)) return;
  try {
    const data = await apiPost(`/api/mask/${maskId}/rollback`, {});
    const item = activeCase();
    if (item) {
      await loadCaseDetail(item.case_id);
      await ensureCaseMasksLoaded(item.case_id);
      await loadCaseVersions(item.case_id, { force: true });
    }
    state.active3DMaskId = data.mask_id;
    showToast(data.message || `已回滚为 ${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "回滚失败");
  }
}

async function loadQualityReport() {
  const maskId = state.qualityMaskId || $("#qualityMaskSelect")?.value;
  const refId = state.qualityRefMaskId || $("#qualityRefSelect")?.value || "";
  if (!maskId) {
    showToast("请先选择要评价的 Mask 版本");
    return;
  }
  state.qualityMaskId = maskId;
  state.qualityRefMaskId = refId;
  try {
    const query = refId ? `?ref=${encodeURIComponent(refId)}` : "";
    const data = await apiGet(`/api/mask/${maskId}/metrics${query}`);
    state.qualityReport = data;
    if (data.overlap) {
      state.lastCompareResult = {
        ...data.overlap,
        pred_mask_id: maskId,
        ref_mask_id: refId,
        dice: data.overlap.dice,
        iou: data.overlap.iou,
        precision: data.overlap.precision,
        recall: data.overlap.recall,
      };
    }
    render();
  } catch (error) {
    showToast(error.message || "质量指标加载失败");
  }
}

function selectedModel() {
  return state.models.find((item) => item.model_id === state.selectedModelId) || state.models[0] || null;
}

function promptCounts(image) {
  if (!image) return { positive: 0, negative: 0 };
  const prompts = deepEditPromptPayload(image);
  return { positive: prompts.positive.length, negative: prompts.negative.length };
}

async function refreshCases() {
  try {
    const data = await apiGet("/api/cases");
    state.cases = data.items || [];
    if (
      state.cases.length &&
      (!state.activeCaseId || !state.cases.some((item) => item.case_id === state.activeCaseId))
    ) {
      state.activeCaseId = state.cases[state.cases.length - 1].case_id;
      state.activeImageId = null;
    }
    document.querySelector(".status-dot").classList.add("online");
    $("#apiStatus").textContent = "后端已连接";
  } catch {
    $("#apiStatus").textContent = "后端未连接";
    document.querySelector(".status-dot").classList.remove("online");
  }
}

async function refreshLabels() {
  try {
    const data = await apiGet("/api/labels?include_background=true&enabled_only=false");
    state.labelCatalog = data.items || [];
    if (!labelById(state.annotationLabelId) || labelById(state.annotationLabelId)?.enabled === false) {
      const first = effectiveLabelCatalog({ includeBackground: false, enabledOnly: true })[0];
      if (first) setActiveAnnotationLabel(first.label_id);
    } else {
      setActiveAnnotationLabel(state.annotationLabelId);
    }
  } catch {
    if (!state.labelCatalog.length) state.labelCatalog = DEFAULT_LABEL_CATALOG.slice();
  }
}

async function refreshUsersList() {
  if (!canManageTasks()) {
    state.users = [];
    return;
  }
  try {
    const users = await apiGet("/api/users");
    state.users = users.items || [];
  } catch {
    state.users = [];
  }
}

async function restoreSession() {
  if (!state.authToken) {
    updateAuthChrome();
    return false;
  }
  try {
    const data = await apiGet("/api/me");
    state.currentUser = data.user;
    updateAuthChrome();
    await refreshUsersList();
    await refreshTasks();
    return true;
  } catch {
    clearAuthSession();
    updateAuthChrome();
    return false;
  }
}

async function refreshTasks() {
  if (!state.currentUser) {
    state.tasks = [];
    return [];
  }
  try {
    const data = await apiGet("/api/tasks");
    state.tasks = data.items || [];
  } catch {
    state.tasks = [];
  }
  return state.tasks;
}

async function handleLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const username = form.username.value.trim();
  const password = form.password.value;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const data = await apiPost("/api/auth/login", { username, password });
    setAuthSession(data.access_token, data.user);
    await refreshUsersList();
    await refreshLabels();
    await refreshTasks();
    showToast(`已登录：${data.user.username}（${roleText[data.user.role] || data.user.role}）`);
    render();
  } catch (error) {
    showToast(error.message || "登录失败");
  } finally {
    button.disabled = false;
  }
}

function handleLogout() {
  clearAuthSession();
  showToast("已退出登录");
  render();
}

async function submitCaseForReview(event) {
  const button = event.currentTarget;
  const item = activeCase();
  if (!item) {
    showToast("请先选择病例");
    return;
  }
  if (!state.currentUser) {
    showToast("请先登录");
    return;
  }
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "提交中...";
  try {
    const data = await apiPost(`/api/case/${item.case_id}/submit`, { note: "submitted from annotation workbench" });
    await refreshCases();
    await refreshTasks();
    showToast(`已提交审核：${data.case_id} → ${data.status}`);
    render();
  } catch (error) {
    showToast(error.message || "提交审核失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function approveCaseReview(event) {
  const button = event.currentTarget;
  const item = activeCase();
  if (!item) {
    showToast("请先选择病例");
    return;
  }
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "通过中...";
  try {
    const data = await apiPost(`/api/case/${item.case_id}/approve`, { note: "approved" });
    await refreshCases();
    await refreshTasks();
    await loadReviewQueue({ force: true });
    state._reviewQueueHydrated = true;
    showToast(`审核通过并 promote → final：${data.case_id} → ${data.status}`);
    render();
  } catch (error) {
    showToast(error.message || "审核通过失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function rejectCaseReview(event) {
  const button = event.currentTarget;
  const item = activeCase();
  if (!item) {
    showToast("请先选择病例");
    return;
  }
  const note = window.prompt("请输入驳回原因", "需要继续修正标注") || "rejected";
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "驳回中...";
  try {
    const data = await apiPost(`/api/case/${item.case_id}/reject`, { note });
    delete state.caseDetails[item.case_id];
    await refreshCases();
    await refreshTasks();
    await loadReviewQueue({ force: true });
    state._reviewQueueHydrated = true;
    showToast(`已驳回：${data.case_id} → ${data.status}（版本保留，不进 final）`);
    render();
  } catch (error) {
    showToast(error.message || "驳回失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function createTaskAssignment(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!canManageTasks()) {
    showToast("仅审核员/管理员可分配任务");
    return;
  }
  const caseId = form.case_id.value;
  const assigneeId = Number(form.assignee_id.value);
  const deadline = form.deadline.value || null;
  const note = form.note.value.trim() || null;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await apiPost("/api/tasks", {
      case_id: caseId,
      assignee_id: assigneeId,
      deadline,
      note,
    });
    await refreshTasks();
    showToast("任务已分配");
    form.reset();
    render();
  } catch (error) {
    showToast(error.message || "任务分配失败");
  } finally {
    button.disabled = false;
  }
}

async function uploadCase(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const fileInput = form.querySelector("[name=file]");
  const files = fileInput?.files ? [...fileInput.files] : [];
  await uploadCtFiles(files, form);
}

function isAllowedCtFile(file) {
  const name = String(file?.name || "").toLowerCase();
  if (!name) return false;
  if (name.endsWith(".nii.gz")) return true;
  const ext = name.includes(".") ? `.${name.split(".").pop()}` : "";
  const allowed = new Set([".dcm", ".dicom", ".nii", ".gz", ".nrrd", ".zip", ".png", ".jpg", ".jpeg"]);
  if (allowed.has(ext)) return true;
  // Extensionless DICOM instances are common in clinical exports.
  return ext === "" && file.size > 128;
}

function describeUploadSelection(files) {
  if (!files.length) return "未选择文件";
  if (files.length === 1) return files[0].name;
  return `${files.length} 个文件（${files[0].name} 等）`;
}

async function uploadCtFiles(fileList, form) {
  const files = [...(fileList || [])].filter(Boolean);
  if (!files.length) {
    showToast("请选择或拖入 CT 文件（DICOM / NIfTI / NRRD / ZIP）");
    return;
  }
  const invalid = files.filter((file) => !isAllowedCtFile(file));
  if (invalid.length) {
    showToast(`含不支持的文件：${invalid[0].name}`);
    return;
  }
  if (files.length > 1) {
    const allDicom = files.every((file) => {
      const name = file.name.toLowerCase();
      return name.endsWith(".dcm") || name.endsWith(".dicom") || !name.includes(".");
    });
    const hasVolume = files.some((file) => {
      const name = file.name.toLowerCase();
      return name.endsWith(".nii") || name.endsWith(".nii.gz") || name.endsWith(".nrrd") || name.endsWith(".zip");
    });
    const hasLabel = files.some((file) => {
      const name = file.name.toLowerCase();
      return name.includes("label") || name.includes("mask") || name.includes("seg") || name.includes("rtstruct");
    });
    if (!allDicom && !(hasVolume && (hasLabel || files.length >= 2))) {
      showToast("多文件：请上传同一 DICOM 序列，或 CT + 金标准 label/SEG/RTSTRUCT");
      return;
    }
  }

  const body = new FormData();
  for (const file of files) body.append("files", file);
  body.append("patient_id", form?.patient_id?.value || "");
  body.append("modality", form?.modality?.value || "CT");
  body.append("source_group", form?.source_group?.value || "local");

  const button = form?.querySelector("button[type=submit]");
  const hint = $("#uploadDropHint");
  const previousText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "导入中...";
  }
  if (hint) hint.textContent = `正在导入 ${describeUploadSelection(files)}...`;

  try {
    const response = await fetch(apiUrl("/api/upload"), { method: "POST", body, headers: authHeaders() });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : (detail?.message || "上传失败"));
    }
    showToast(
      data.attached_mask_count
        ? `导入成功：${data.case_id} / ${data.image_id}，已挂载 ${data.attached_mask_count} 个金标准 Mask`
        : `导入成功：${data.case_id} / ${data.image_id}`,
    );
    const warnings = (data.attached_masks || [])
      .map((item) => item.warning || item.rtstruct_qc?.alignment_message)
      .filter(Boolean);
    if (warnings.length) {
      showToast(`RTSTRUCT 对齐提示：${warnings[0]}`);
    }
    state.activeCaseId = data.case_id;
    state.activeImageId = data.image_id;
    if (form) {
      const patientId = form.patient_id?.value || "";
      const modality = form.modality?.value || "CT";
      const sourceGroup = form.source_group?.value || "local";
      form.reset();
      if (form.patient_id) form.patient_id.value = patientId;
      if (form.modality) form.modality.value = modality;
      if (form.source_group) form.source_group.value = sourceGroup;
    }
    const nameEl = $("#uploadSelectedName");
    if (nameEl) nameEl.textContent = "未选择文件";
    await refreshCases();
    setView("cases");
  } catch (error) {
    showToast(error.message || "上传失败");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = previousText || "上传病例";
    }
    if (hint) hint.textContent = "点击选择，或将 CT 文件拖到此处；选完后自动导入";
  }
}

function bindUploadDropzone() {
  const form = $("#uploadForm");
  const dropzone = $("#uploadDropzone");
  const fileInput = form?.querySelector("[name=file]");
  const nameEl = $("#uploadSelectedName");
  if (!form || !dropzone || !fileInput) return;

  const syncName = () => {
    if (nameEl) nameEl.textContent = describeUploadSelection([...fileInput.files]);
  };

  const openPicker = () => fileInput.click();

  dropzone.addEventListener("click", (event) => {
    // Avoid double-firing if the hidden input somehow receives the click.
    if (event.target === fileInput) return;
    openPicker();
  });
  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  });

  fileInput.addEventListener("change", async () => {
    syncName();
    if (!fileInput.files?.length) return;
    await uploadCtFiles(fileInput.files, form);
    fileInput.value = "";
    syncName();
  });

  ["dragenter", "dragover"].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      event.stopPropagation();
      dropzone.classList.add("is-dragover");
    });
  });
  dropzone.addEventListener("dragleave", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (dropzone.contains(event.relatedTarget)) return;
    dropzone.classList.remove("is-dragover");
  });
  dropzone.addEventListener("drop", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    dropzone.classList.remove("is-dragover");
    const files = [...(event.dataTransfer?.files || [])];
    if (!files.length) return;
    if (nameEl) nameEl.textContent = describeUploadSelection(files);
    await uploadCtFiles(files, form);
  });
}

async function saveCurrentMask(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "保存中...";
  try {
    const saved = await saveAllAnnotatedMasks(item, image);
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    await refreshLabelingAssist({ silent: true });
    const updatedCount = saved.filter((item) => item.updated).length;
    const createdCount = saved.length - updatedCount;
    const labeled = localLabeledAxialSlices(image);
    let extra = "";
    if ((state.annotationMode === "coarse" || state.annotationMode === "scribble") && labeled.length >= state.fewShotMinSlices) {
      extra = " · 可一键传播生成 3D preview";
    }
    showToast(`已保存 ${saved.length} 个切片 Mask（${currentLabelType()}，新建 ${createdCount} / 覆盖 ${updatedCount}）${extra}`);
    render();
  } catch (error) {
    showToast(error.message || "Mask 保存失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

function allowCanvasMaskRestore(imageId = activeImage()?.image_id) {
  if (imageId) delete state.suppressCanvasMaskRestore[imageId];
  state.autoOverlayOnCanvas = true;
}

async function loadMaskForEditing(maskId) {
  const image = activeImage();
  if (!image || !maskId) return;
  try {
    const detail = await apiGet(`/api/mask/${maskId}`);
    const content = detail.content;
    const mask = detail.mask;
    if (!content || content.encoding !== "rle") {
      throw new Error("仅支持加载 JSON RLE 切片 Mask");
    }
    const width = Number(content.width || 0);
    const height = Number(content.height || 0);
    const sliceIndex = Number(content.slice_index ?? mask.slice_index ?? 0);
    const axis = sliceAxes[content.axis || mask.axis] ? (content.axis || mask.axis) : "axial";
    if (!width || !height) throw new Error("Mask 尺寸无效");

    allowCanvasMaskRestore(image.image_id);
    state.volumeViewMode = "2d";
    state.activeAxis = axis;
    setCurrentSliceIndex(sliceIndex, axis);
    if (!state.sliceMasks[image.image_id]) state.sliceMasks[image.image_id] = {};
    const sliceKey = sliceStorageKey(axis, sliceIndex);
    state.sliceMasks[image.image_id][sliceKey] = {
      width,
      height,
      data: decodeMaskRle(content.mask, width, height),
      source: "loaded_mask",
      maskId,
    };
    if (Array.isArray(content.points)) {
      if (!state.pointAnnotations[image.image_id]) state.pointAnnotations[image.image_id] = {};
      state.pointAnnotations[image.image_id][sliceKey] = content.points.map((point) => ({ ...point }));
    }
    state.loadedMaskContents[maskId] = true;
    state.restoredMaskSlices[image.image_id] = { axis, sliceIndex };
    showToast(`已加载 ${maskId} 到 ${axisLabel(axis)} 第 ${sliceIndex + 1} 层`);
    render();
  } catch (error) {
    showToast(error.message || "加载 Mask 失败");
  }
}

async function deleteMaskRecord(maskId) {
  const image = activeImage();
  const item = activeCase();
  if (!maskId) return;
  if (!window.confirm(`确认删除 ${maskId}？此操作不可恢复。`)) return;
  try {
    await apiDelete(`/api/mask/${maskId}`);
    delete state.loadedMaskContents[maskId];
    if (image) await loadImageMasks(image.image_id, { force: true });
    if (item) await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    showToast(`已删除 ${maskId}`);
    render();
  } catch (error) {
    showToast(error.message || "删除 Mask 失败");
  }
}

async function create3DMaskPreview(item, image) {
  try {
    const data = await apiPost("/api/label_propagate", {
      case_id: item.case_id,
      image_id: image.image_id,
      source_version: "v1_manual",
      output_version: "v3_preview",
      label: state.annotationLabel,
      label_id: state.annotationLabelId,
      label_type: "pseudo",
      method: "image_guided_distance",
      fill_holes: true,
      keep_largest_component: false,
      image_guidance: true,
      closing_radius: 1,
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: "v3_preview",
      annotation: data.mask_id,
      model: "label_propagation_image_guided_distance",
      dataset: null,
    });
    return data;
  } catch (error) {
    console.warn("3D Mask 预览生成失败：", error);
    showToast(`2D Mask 已保存，但 3D 实体生成失败：${error.message || "未知错误"}`);
    return null;
  }
}

async function refreshLabelingAssist({ silent = false } = {}) {
  const image = activeImage();
  if (!image) return null;
  try {
    const params = new URLSearchParams({
      label: state.annotationLabel,
      axis: "axial",
      top_k: "5",
      min_slices: String(state.fewShotMinSlices),
      source_version: "v1_manual",
    });
    const data = await apiGet(`/api/image/${image.image_id}/labeling_assist?${params.toString()}`);
    state.labelingAssist = data;
    if (!silent) showToast(`已刷新：已标 ${data.workload?.labeled_count || 0} 层，推荐 ${data.recommendations?.length || 0} 层`);
    return data;
  } catch (error) {
    if (!silent) showToast(error.message || "刷新标注推荐失败");
    return null;
  }
}

async function runFewShotPropagate(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "检查标注中...";
  try {
    // 先把本地未保存的切片写入服务器（若本地为空则跳过）
    const localLabeled = localLabeledAxialSlices(image);
    if (localLabeled.length) {
      button.textContent = "保存并传播中...";
      try {
        await saveAllAnnotatedMasks(item, image);
      } catch (error) {
        // 本地可能只有空壳，不阻断：传播本身读的是服务器 v1_manual
        console.warn("传播前保存本地标注跳过：", error);
      }
    }

    // 与向导面板一致：以服务器已保存轴位层数为准
    const assist = await refreshLabelingAssist({ silent: true });
    const serverCount = Number(assist?.workload?.labeled_count);
    const localCount = localLabeledAxialSlices(image).length;
    const labeledCount = Number.isFinite(serverCount) ? serverCount : localCount;
    if (labeledCount < state.fewShotMinSlices) {
      showToast(
        `请至少标注 ${state.fewShotMinSlices} 层轴位切片并保存（服务器已保存 ${labeledCount} 层，本地 ${localCount} 层）`,
      );
      return;
    }

    button.textContent = "一键传播中...";
    const data = await create3DMaskPreview(item, image);
    if (!data) throw new Error("传播失败");
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    await refreshLabelingAssist({ silent: true });
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    showToast(`少量标注传播完成：${data.mask_id}（基于已保存 ${labeledCount} 层轴位标注）`);
    render();
  } catch (error) {
    showToast(error.message || "一键传播失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

function setAnnotationMode(mode) {
  if (!["dense", "coarse", "scribble"].includes(mode)) return;
  state.annotationMode = mode;
  const allowed = new Set(annotationToolsForMode().map(([tool]) => tool));
  if (!allowed.has(state.annotationTool)) {
    state.annotationTool = state.annotationMode === "coarse" ? "rectangle" : state.annotationMode === "scribble" ? "brush" : "brush";
  }
  render();
}

function jumpToRecommendedSlice(sliceIndex) {
  const image = activeImage();
  const meta = image ? state.volumeMeta[image.image_id] : null;
  if (!image || !meta) return;
  state.volumeViewMode = "2d";
  state.activeAxis = "axial";
  const maxSlice = Math.max(axisSliceCount(meta, "axial") - 1, 0);
  setCurrentSliceIndex(Math.min(Math.max(0, Number(sliceIndex) || 0), maxSlice), "axial");
  updateSliceViewer(image, meta);
  showToast(`已跳转到推荐层 ${Number(sliceIndex) + 1}`);
}

async function promotePreviewMask(targetVersion, event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "确认中...";
  try {
    const masks = await loadImageMasks(image.image_id, { force: true });
    const source = latestMaskByVersion(masks, "v3_preview") ||
      (targetVersion === "final" ? latestMaskByVersion(masks, "v3_fusion") : null);
    if (!source) {
      throw new Error(targetVersion === "final" ? "请先生成 v3_preview 或 v3_fusion 3D Mask" : "请先生成 v3_preview 预览结果");
    }
    const data = await apiPost(`/api/mask/${source.mask_id}/promote`, {
      target_version: targetVersion,
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: targetVersion,
      annotation: data.mask_id,
      model: `promoted_from:${source.mask_id}`,
      dataset: null,
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    showToast(`已确认 ${targetVersion}：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || `${targetVersion} 确认失败`);
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function approveFusionMask(event) {
  return promotePreviewMask("v3_fusion", event);
}

async function approveFinalMask(event) {
  return promotePreviewMask("final", event);
}

async function runAIPredict(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  await loadModels();
  const request = resolveAiPredictRequest();
  const model = request.model;
  if (!model) {
    showToast("暂无可用模型，请先在推理中心确认模型注册表");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = `预测${request.targetLabel}中...`;
  const isHeavy = String(model.label || "").toLowerCase().includes("spleen") ||
    String(model.model_id || "").toLowerCase().includes("spleen") ||
    String(model.model_id || "").toLowerCase().includes("totalseg") ||
    String(model.model_id || "").toLowerCase().includes("tumor") ||
    String(model.backend || "").toLowerCase().includes("totalsegmentator") ||
    String(model.backend || "").toLowerCase().includes("tumor_residual") ||
    request.target === "all" ||
    request.target === "tumor";
  if (isHeavy) {
    const tumorHint = request.target === "tumor"
      ? "疑似肿瘤启发式：先跑器官再取残差，非诊断结果；CPU 可能需数分钟…"
      : `正在预测「${request.targetLabel}」（TotalSeg / nnU-Net），CPU 可能需要数分钟…`;
    showToast(tumorHint);
  }
  try {
    const data = await apiPost("/api/ai/predict", {
      case_id: item.case_id,
      image_id: image.image_id,
      model_id: model.model_id,
      label: request.label,
      allow_baseline: false,
    }, { timeoutMs: isHeavy ? 30 * 60 * 1000 : 120 * 1000 });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    // Prefer multiclass「全部标注」as the active 3D / overlay mask.
    const masks = state.masksByImage[image.image_id] || [];
    const allLabelsMask = masks.find((mask) => mask.mask_id === data.mask_id)
      || masks.find((mask) => String(mask.label || "") === "全部标注" && mask.version === "v2_ai")
      || masks.find((mask) => mask.mask_id === data.mask_id);
    state.active3DMaskId = (allLabelsMask && allLabelsMask.mask_id) || data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    state.inferencePreview = {
      case_id: item.case_id,
      image_id: image.image_id,
      mask_id: state.active3DMaskId,
      model_id: data.model_id,
      version: data.version,
      model_status: data.model_status,
      backend: data.backend,
    };
    if (request.target !== "all") {
      const catalogItem = effectiveLabelCatalog({ includeBackground: false, enabledOnly: true })
        .find((entry) => entry.name === request.target);
      if (catalogItem) setActiveAnnotationLabel(catalogItem.label_id);
      else state.annotationLabel = request.target;
    }
    const statusText = data.model_status || data.backend || "unknown";
    const hasAll = Array.isArray(data.organ_labels) && data.organ_labels.includes("全部标注");
    showToast(
      hasAll
        ? `AI 预测完成 [${statusText}]：已生成「全部标注」· ${data.organ_count || 1} 个器官`
        : `AI 预测完成 [${statusText}]：${request.targetLabel} · ${data.mask_id}`,
    );
    if (data.fallback_reason) {
      showToast(`注意：${data.fallback_reason}`);
    }
    if (Array.isArray(data.organ_labels) && data.organ_labels.length > 1) {
      showToast(`已写入：${data.organ_labels.slice(0, 12).join(", ")}${data.organ_labels.length > 12 ? " ..." : ""}`);
    }
    render();
  } catch (error) {
    showToast(error.message || "AI 预测失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function loadV2AiTo2D(event) {
  const button = event?.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }
  if (button) {
    button.disabled = true;
  }
  try {
    const masks = await loadImageMasks(image.image_id, { force: true });
    const aiMask = latestMaskByVersion(masks, "v2_ai");
    if (!aiMask) {
      throw new Error("当前图像尚无 v2_ai Mask，请先运行 AI 预测");
    }
    state.active3DMaskId = aiMask.mask_id;
    state.volumeViewMode = "2d";
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    if (aiMask.label) state.annotationLabel = aiMask.label;
    const quality = await loadMaskQuality(aiMask.mask_id).catch(() => null);
    const range = quality?.slice_range;
    if (range && range.start != null && range.end != null) {
      state.activeAxis = "axial";
      setCurrentSliceIndex(Math.floor((Number(range.start) + Number(range.end)) / 2), "axial");
    }
    showToast(`已从 v2_ai 加载到 2D：${aiMask.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "加载 v2_ai 失败");
  } finally {
    if (button) button.disabled = false;
  }
}

async function compareActiveMasks(event) {
  const button = event.currentTarget;
  const image = activeImage();
  if (!image) {
    showToast("请先选择图像");
    return;
  }
  const masks = await loadImageMasks(image.image_id, { force: true });
  const pred = latestMaskByVersion(masks, "v2_ai") || latest3DMask(masks);
  const ref = latestMaskByVersion(masks, "final") ||
    latestMaskByVersion(masks, "v3_fusion") ||
    latestMaskByVersion(masks, "v3_preview");
  if (!pred || !ref || pred.mask_id === ref.mask_id) {
    showToast("需要两个不同的 3D Mask（如 v2_ai 与 final/v3_preview）才能计算 Dice");
    return;
  }
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "计算中...";
  try {
    const data = await apiPost("/api/masks/compare", {
      pred_mask_id: pred.mask_id,
      ref_mask_id: ref.mask_id,
    });
    state.lastCompareResult = data;
    showToast(`Dice=${data.dice.toFixed(4)} · IoU=${data.iou.toFixed(4)}（${pred.version} vs ${ref.version}）`);
    render();
  } catch (error) {
    showToast(error.message || "Dice 计算失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function exportMaskNifti(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "导出中...";
  try {
    const data = await apiPost("/api/export_mask_nifti", {
      case_id: item.case_id,
      image_id: image.image_id,
      version: "v1_manual",
      label: state.annotationLabel,
    });
    await loadImageMasks(image.image_id, { force: true });
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    showToast(`3D Mask 导出成功：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "3D Mask 导出失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function saveCurrentSliceIfAnnotated(item, image) {
  try {
    return await saveAllAnnotatedMasks(item, image);
  } catch {
    return null;
  }
}

function deepEditPromptPayload(image) {
  const positive = [];
  const negative = [];
  const seenNegative = new Set();
  const pushNegative = (x, y, z) => {
    const key = `${Math.round(x)}:${Math.round(y)}:${Math.round(z)}`;
    if (seenNegative.has(key)) return;
    seenNegative.add(key);
    negative.push([Number(x) || 0, Number(y) || 0, Number(z) || 0]);
  };
  const imagePoints = state.pointAnnotations[image.image_id] || {};
  for (const [sliceKey, points] of Object.entries(imagePoints)) {
    const { axis, sliceIndex } = parseSliceStorageKey(sliceKey);
    if (axis !== "axial") continue;
    for (const point of points || []) {
      if ((point.promptType || "positive") === "negative") {
        pushNegative(point.x, point.y, point.sliceIndex ?? sliceIndex);
      } else {
        positive.push([Number(point.x) || 0, Number(point.y) || 0, Number(point.sliceIndex ?? sliceIndex) || 0]);
      }
    }
  }
  // Smart eraser regions are also treated as DeepEdit negative clicks.
  const imageNegativeScribbles = state.negativeScribbles?.[image.image_id] || {};
  for (const [sliceKey, points] of Object.entries(imageNegativeScribbles)) {
    const { axis, sliceIndex } = parseSliceStorageKey(sliceKey);
    if (axis !== "axial" || !Array.isArray(points)) continue;
    for (const point of points) {
      if (point?.asNegativePoint === false) continue;
      pushNegative(point.x, point.y, point.z ?? point.sliceIndex ?? sliceIndex);
    }
  }
  return { positive, negative: negative.slice(-300) };
}

function deepEditScribblePayload(image) {
  const scribbles = [];
  const imageMasks = state.sliceMasks[image.image_id] || {};
  for (const [sliceKey, mask] of Object.entries(imageMasks)) {
    const { axis, sliceIndex } = parseSliceStorageKey(sliceKey);
    if (axis !== "axial" || !mask?.data) continue;
    const foregroundPixels = mask.data.reduce((sum, value) => sum + (value > 0 ? 1 : 0), 0);
    if (!foregroundPixels) continue;
    scribbles.push({
      axis,
      slice_index: sliceIndex,
      width: mask.width,
      height: mask.height,
      label_id: state.annotationLabelId,
      foreground_pixels: foregroundPixels,
      encoding: "saved_v1_manual_rle",
      prompt_type: "positive",
    });
  }
  const imageNegativeScribbles = state.negativeScribbles?.[image.image_id] || {};
  for (const [sliceKey, points] of Object.entries(imageNegativeScribbles)) {
    const { axis, sliceIndex } = parseSliceStorageKey(sliceKey);
    if (axis !== "axial" || !Array.isArray(points) || !points.length) continue;
    scribbles.push({
      axis,
      slice_index: sliceIndex,
      label_id: 0,
      point_count: points.length,
      points: points.slice(-600),
      prompt_type: "negative",
      encoding: "smart_eraser_points",
    });
  }
  return scribbles;
}

function confirmedSliceIndices(image) {
  const values = new Set([currentSliceIndex()]);
  const imageMasks = state.sliceMasks[image.image_id] || {};
  const imagePoints = state.pointAnnotations[image.image_id] || {};
  const imageNegativeScribbles = state.negativeScribbles?.[image.image_id] || {};
  for (const key of [...Object.keys(imageMasks), ...Object.keys(imagePoints), ...Object.keys(imageNegativeScribbles)]) {
    const { axis, sliceIndex } = parseSliceStorageKey(key);
    if (axis === "axial") values.add(sliceIndex);
  }
  return [...values].sort((a, b) => a - b);
}

async function runSmart3DRefine(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "保存并生成...";
  try {
    await saveCurrentSliceIfAnnotated(item, image);
    button.textContent = "智能修正中...";
    const currentMasks = await loadImageMasks(image.image_id, { force: true });
    const current3DMask = latest3DMask(currentMasks) ||
      latestMaskByVersion(currentMasks, "v2_ai") ||
      latestMaskByVersion(currentMasks, "v3_preview");
    const prompts = deepEditPromptPayload(image);
    const scribbles = deepEditScribblePayload(image);
    const data = await apiPost("/api/deepedit/refine", {
      case_id: item.case_id,
      image_id: image.image_id,
      source_version: "v1_manual",
      current_mask_version: current3DMask?.version || "v3_fusion",
      current_mask_id: current3DMask?.mask_id || null,
      output_version: "v3_preview",
      label: state.annotationLabel,
      model_id: "DeepEdit",
      require_neural: true,
      random_walker_beta: state.refineParams.randomWalkerBeta,
      random_walker_roi_margin: state.refineParams.roiMargin,
      connected_component_min_voxels: state.refineParams.minVoxels,
      positive_points: prompts.positive,
      negative_points: prompts.negative,
      scribbles,
      interaction: {
        type: "deepedit",
        prompt_source: "2d_axial_canvas",
        current_tool: state.annotationTool,
        prompt_mode: "brush_positive_smart_eraser_negative",
        positive_count: prompts.positive.length,
        negative_count: prompts.negative.length,
      },
      confirmed_slices: confirmedSliceIndices(image),
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: "v3_preview",
      annotation: data.mask_id,
      model: data.refinement_mode,
      dataset: null,
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    showToast(`DeepEdit 神经网络修正完成：${data.mask_id} · ${data.model_status || data.refinement_mode}`);
    render();
  } catch (error) {
    showToast(error.message || "DeepEdit 修正失败（需启动 DeepEdit 服务；图割请用「图割修正」）");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function runGraphCutRefine(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "图割修正中...";
  try {
    await saveCurrentSliceIfAnnotated(item, image);
    const prompts = deepEditPromptPayload(image);
    const data = await apiPost("/api/label_propagate", {
      case_id: item.case_id,
      image_id: image.image_id,
      source_version: "v1_manual",
      output_version: "v3_preview",
      label: state.annotationLabel,
      label_id: state.annotationLabelId,
      label_type: "pseudo",
      method: "random_walker",
      fill_holes: true,
      keep_largest_component: false,
      image_guidance: true,
      closing_radius: 1,
      random_walker_beta: state.refineParams.randomWalkerBeta,
      random_walker_roi_margin: state.refineParams.roiMargin,
      connected_component_mode: "seeded",
      connected_component_min_voxels: state.refineParams.minVoxels,
      connected_component_max_components: 8,
      positive_points: prompts.positive,
      negative_points: prompts.negative,
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: "v3_preview",
      annotation: data.mask_id,
      model: "graph_cut_random_walker",
      dataset: null,
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    showToast(`图割修正完成（Random Walker · ${state.annotationLabel}#${state.annotationLabelId}）：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "图割修正失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function renderAnnotationMaskIn3D(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "保存并生成 3D…";
  try {
    try {
      await saveAllAnnotatedMasks(item, image);
    } catch (error) {
      console.warn("自动保存未完成切片标注：", error);
    }
    const masks = await loadImageMasks(image.image_id, { force: true });
    const hasManualJson = masks.some((mask) => (
      mask.version === "v1_manual" &&
      (mask.mask_format === "json" || String(mask.path || "").endsWith(".json"))
    ));
    if (!hasManualJson) {
      showToast("请先在 2D 画好标注并点击「保存 Mask」；2D JSON 不能直接出现在 3D 下拉框里");
      return;
    }

    // Stack all saved 2D JSON slices into one NIfTI for true “自己标注” highlight
    // (not AI propagation). Dropdown only lists nii.gz masks.
    button.textContent = "堆叠 2D→3D…";
    const data = await apiPost("/api/export_mask_nifti", {
      case_id: item.case_id,
      image_id: image.image_id,
      version: "v1_manual",
      label: "*",
      match_any_label: true,
      output_label: "全部标注",
    });
    if (!data?.mask_id) throw new Error("3D Mask 未生成");
    state.active3DMaskId = data.mask_id;
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    showToast(`已把你的 2D 标注堆成 3D 高亮：${data.mask_id}（可在下拉框选择）`);
    render();
  } catch (error) {
    showToast(error.message || "当前标注高亮失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function start3DImageRender(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "准备3D渲染...";
  try {
    try {
      await saveAllAnnotatedMasks(item, image);
    } catch (error) {
      console.warn("没有可自动保存的 2D 标注，将直接打开 3D 体视图：", error);
    }

    await loadImageMasks(image.image_id, { force: true });
    const masks = state.masksByImage[image.image_id] || [];
    const hasManualJson = masks.some((mask) => (
      mask.version === "v1_manual" &&
      (mask.mask_format === "json" || String(mask.path || "").endsWith(".json"))
    ));

    if (hasManualJson) {
      button.textContent = "生成高亮实体...";
      const data = await create3DMaskPreview(item, image);
      if (data?.mask_id) state.active3DMaskId = data.mask_id;
      await loadImageMasks(image.image_id, { force: true });
      await loadCaseVersions(item.case_id, { force: true });
    } else {
      const existingMask = latest3DMask(masks);
      state.active3DMaskId = existingMask?.mask_id || null;
    }

    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    allowCanvasMaskRestore(image.image_id);
    showToast(state.active3DMaskId ? "正在渲染 3D 图像并高亮当前标注" : "正在渲染 3D 图像");
    render();
  } catch (error) {
    showToast(error.message || "3D 图像渲染失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function exportDataset(event) {
  const button = event.currentTarget;
  const labelSet = $("#exportLabelSet")?.value || state.exportLabelSet || "dense";
  let version = $("#exportVersion")?.value || (labelSet === "weak" ? "v3_preview" : "final");
  if (labelSet === "weak" && version === "final") version = "v3_preview";
  const format = $("#exportFormat")?.value || "nnunet";
  const datasetId = $("#exportDatasetId")?.value.trim() || undefined;
  const materialize = $("#exportMaterialize")?.checked ?? state.exportMaterialize;
  const strict = $("#exportStrict")?.checked ?? state.exportStrict;
  const name = $("#exportDatasetName")?.value.trim() || `medical_seg_${labelSet}_${version}`;

  const train = [];
  const val = [];
  const test = [];
  for (const [caseId, split] of Object.entries(state.exportAssignments || {})) {
    if (split === "train") train.push(caseId);
    else if (split === "val") val.push(caseId);
    else if (split === "test") test.push(caseId);
  }
  if (!train.length && !val.length && !test.length) {
    const fallback = activeCase();
    if (fallback) train.push(fallback.case_id);
  }
  if (!train.length && !val.length && !test.length) {
    showToast("请至少选择一个病例并指定 train/val/test");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = materialize ? "物化导出中..." : "导出中...";
  try {
    const data = await apiPost("/api/export", {
      dataset_id: datasetId,
      name,
      version,
      label_set: labelSet,
      train,
      val,
      test,
      format,
      materialize: Boolean(materialize),
      strict: Boolean(strict),
    }, { timeoutMs: 10 * 60 * 1000 });
    state.datasetExportResult = data;
    state.exportLabelSet = labelSet;
    state.exportMaterialize = Boolean(materialize);
    state.exportStrict = Boolean(strict);
    showToast(data.message || `Dataset 导出成功：${data.dataset_id}`);
    render();
  } catch (error) {
    let message = error.message || "Dataset 导出失败";
    try {
      const parsed = JSON.parse(message);
      if (parsed?.message) {
        message = parsed.message;
        if (Array.isArray(parsed.missing_masks)) {
          state.datasetExportResult = {
            success: false,
            message: parsed.message,
            label_set: labelSet,
            version,
            report: {
              missing_masks: parsed.missing_masks,
              success_count: 0,
              skipped_count: parsed.missing_masks.length,
              spacing_checks: [],
            },
          };
        }
      }
    } catch {
      // keep raw message
    }
    showToast(message);
    render();
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

function ensureExportAssignments() {
  if (!state.exportAssignments) state.exportAssignments = {};
  for (const item of state.cases) {
    if (!state.exportAssignments[item.case_id]) {
      state.exportAssignments[item.case_id] = item.case_id === state.activeCaseId ? "train" : "none";
    }
  }
}

function metricCard(label, value, note) {
  return `
    <article class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div>
      <div class="metric-note">${note}</div>
    </article>
  `;
}

function renderDashboard() {
  const total = state.cases.length;
  const annotated = state.cases.filter((item) => item.status !== "unannotated").length;
  const pending = Math.max(total - annotated, 0);
  const progress = total ? Math.round((annotated / total) * 100) : 0;
  const metrics = state.trainJob?.metrics || state.trainJobs?.[0]?.metrics;
  const bestDice = metrics?.best_val_dice != null ? Number(metrics.best_val_dice).toFixed(3) : "暂无";
  const history = Array.isArray(metrics?.history) ? metrics.history : [];
  const bars = history.length
    ? history.slice(-10).map((row) => {
        const dice = Math.max(0, Math.min(1, Number(row.val_dice) || 0));
        return `<div class="bar" style="height:${Math.round(dice * 100)}%" title="epoch ${row.epoch}: dice ${dice.toFixed(3)}"></div>`;
      }).join("")
    : `<div class="placeholder compact">尚无真实训练指标。请在「AI训练中心」启动训练。</div>`;
  return `
    <div class="dashboard-hero">
      <section class="hero-panel">
        <div class="hero-title">
          <div class="holo-emblem" aria-hidden="true">
            <span class="holo-ring ring-a"></span>
            <span class="holo-ring ring-b"></span>
            <span class="holo-orbit orbit-a"></span>
            <span class="holo-orbit orbit-b"></span>
            <svg class="holo-symbol" viewBox="0 0 120 120">
              <path d="M60 18l34 19v46l-34 19-34-19V37z" class="holo-hex" />
              <path d="M34 65h16l7-22 12 42 9-20h10" class="holo-wave" />
              <path d="M60 39v22M49 50h22" class="holo-cross" />
            </svg>
            <span class="holo-scan"></span>
            <span class="holo-particle p1"></span>
            <span class="holo-particle p2"></span>
            <span class="holo-particle p3"></span>
          </div>
          <div>
            <h2>Medical Annotation</h2>
            <div class="eyebrow">人机协同闭环标注系统</div>
          </div>
        </div>
        <p class="hero-copy">
          CT 导入、病例管理、人工标注、AI 推理、版本审核、质量评价和 Dataset 导出统一在一个闭环系统中完成。
          支持金标准上传、多标签编辑、多类导出与平台 U-Net 训练注册。
        </p>
        <div class="pipeline">
          ${["导入", "病例", "图像", "标注", "Mask", "Dataset", "训练", "模型", "预测", "修正"].map((item) => `<span class="chip">${item}</span>`).join("")}
        </div>
      </section>
      <section class="panel chart-box">
        <h2>标注进度</h2>
        <div class="ring" style="background: conic-gradient(var(--green) 0 ${progress}%, rgba(255,255,255,.08) ${progress}% 100%)">
          <div class="ring-inner"><div><strong>${progress}%</strong><br><span class="metric-label">已处理</span></div></div>
        </div>
      </section>
    </div>
    <div class="grid cols-4">
      ${metricCard("病例总数", total, "来自后端 /api/cases")}
      ${metricCard("已标注", annotated, "人工 + AI + 修正")}
      ${metricCard("待处理", pending, "仍为 unannotated")}
      ${metricCard("最佳 Dice", bestDice, metrics ? `模型 ${escapeHtml(metrics.model_id || "")}` : "来自最近一次真实训练")}
    </div>
    <div class="grid cols-2" style="margin-top:18px">
      <section class="panel">
        <h2>AI训练 Val Dice</h2>
        <div class="line-chart">${bars}</div>
      </section>
      <section class="panel">
        <h2>最近任务</h2>
        <div class="log-box">上传 CT (+金标准) -> Case / Image / Mask
人工多标签标注 -> 保存 Mask
AI 预测 -> v2_ai（真实后端或失败提示）
DeepEdit / 图割 -> v3_preview
导出多类 Dataset -> 训练中心 U-Net
注册模型 -> 推理中心选用</div>
      </section>
    </div>
  `;
}

function renderCaseRows() {
  if (!state.cases.length) {
    return `<tr><td colspan="6"><div class="placeholder">暂无病例。请先上传 DICOM / NRRD / NIfTI / PNG/JPG 文件。</div></td></tr>`;
  }
  return state.cases.map((item) => `
    <tr>
      <td><strong>${item.case_id}</strong></td>
      <td>${item.patient_id}</td>
      <td>${item.modality}</td>
      <td>${item.image_count}</td>
      <td><span class="status-badge">${statusText[item.status] || item.status || "未标注"}</span></td>
      <td><button class="ghost-button" data-open-case="${item.case_id}">进入标注</button></td>
    </tr>
  `).join("");
}

function renderCases() {
  const userOptions = (state.users || [])
    .filter((user) => user.role === "annotator" || user.role === "admin")
    .map((user) => `<option value="${user.id}">${escapeHtml(user.username)}（${roleText[user.role] || user.role}）</option>`)
    .join("");
  const caseOptions = state.cases
    .map((item) => `<option value="${escapeHtml(item.case_id)}">${escapeHtml(item.case_id)} · ${escapeHtml(statusText[item.status] || item.status)}</option>`)
    .join("");
  const taskRows = state.tasks.length
    ? state.tasks.map((task) => `
      <tr>
        <td><strong>${escapeHtml(task.task_id)}</strong></td>
        <td>${escapeHtml(task.case_id)}</td>
        <td>${escapeHtml(task.assignee_username || task.assignee_id)}</td>
        <td>${escapeHtml(task.status)}</td>
        <td>${escapeHtml(task.deadline || "-")}</td>
        <td>${escapeHtml(task.note || "-")}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="6"><div class="placeholder">暂无任务。审核员/管理员可在下方分配。</div></td></tr>`;
  return `
    <section class="panel">
      <h2>导入 CT 病例</h2>
      <p class="panel-lead">支持 DICOM（.dcm，可多选序列）、NIfTI（.nii/.nii.gz）、NRRD、ZIP；选择文件打开后自动导入，也可直接拖入下方区域。</p>
      <form id="uploadForm" class="upload-form">
        <div id="uploadDropzone" class="upload-dropzone" tabindex="0" role="button" aria-label="选择或拖入 CT 文件">
          <input
            id="uploadFileInput"
            class="upload-file-input"
            type="file"
            name="file"
            multiple
            accept=".dcm,.dicom,.nii,.nii.gz,.nrrd,.zip,.gz,application/dicom,application/zip,.png,.jpg,.jpeg,image/*"
          />
          <div class="upload-dropzone-body">
            <strong>点击选择文件，或拖入 CT 文件</strong>
            <span id="uploadDropHint">点击选择或拖入：CT，或 CT+金标准 label/SEG/RTSTRUCT；选完后自动导入</span>
            <em id="uploadSelectedName">未选择文件</em>
          </div>
        </div>
        <div class="toolbar-row" style="margin-top:14px;margin-bottom:0">
          <div class="field"><label>患者编号</label><input name="patient_id" placeholder="LUNG1-001" /></div>
          <div class="field"><label>影像类型</label><select name="modality"><option value="CT">CT</option><option value="MRI">MRI</option><option value="PNG">PNG/JPG</option></select></div>
          <div class="field"><label>数据来源</label><select name="source_group"><option value="local">本地</option><option value="A">A组</option><option value="B">B组</option></select></div>
          <button class="primary-button" type="submit">上传病例</button>
        </div>
      </form>
    </section>
    <section class="table-wrap" style="margin-top:18px">
      <table>
        <thead><tr><th>病例ID</th><th>患者编号</th><th>影像类型</th><th>图像数</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>${renderCaseRows()}</tbody>
      </table>
    </section>
    <section class="panel" style="margin-top:18px">
      <h2>标注任务</h2>
      ${canManageTasks() ? `
        <form id="taskForm" class="toolbar-row" style="margin-bottom:14px">
          <div class="field"><label>病例</label><select name="case_id">${caseOptions || "<option value=''>暂无病例</option>"}</select></div>
          <div class="field"><label>指派给</label><select name="assignee_id">${userOptions || "<option value=''>暂无用户</option>"}</select></div>
          <div class="field"><label>截止日期</label><input name="deadline" type="date" /></div>
          <div class="field"><label>备注</label><input name="note" placeholder="请完成脾脏标注" /></div>
          <button class="primary-button" type="submit">分配任务</button>
        </form>
      ` : `<div class="placeholder compact" style="margin-bottom:12px">当前角色仅可查看分配给自己的任务。</div>`}
      <div class="table-wrap">
        <table>
          <thead><tr><th>任务ID</th><th>病例</th><th>执行人</th><th>状态</th><th>截止</th><th>备注</th></tr></thead>
          <tbody>${taskRows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function activeCase() {
  return state.cases.find((item) => item.case_id === state.activeCaseId) || state.cases[0] || null;
}

function activeImages() {
  const item = activeCase();
  if (!item) return [];
  return state.caseDetails[item.case_id]?.images || [];
}

function activeImage() {
  const images = activeImages();
  return images.find((image) => image.image_id === state.activeImageId) || images[0] || null;
}

function labelListOptions() {
  return effectiveLabelCatalog({ includeBackground: false, enabledOnly: true })
    .map((item) => {
      const id = Number(item.label_id);
      const selected = state.annotationLabelId === id ? "selected" : "";
      return `<option value="${id}" ${selected} data-color="${escapeHtml(item.color)}">${escapeHtml(labelDisplayText(id))}</option>`;
    })
    .join("");
}

function renderLabelPicker() {
  const color = labelColor(state.annotationLabelId);
  return `
    <div class="label-picker">
      <label class="label-select-field">
        <span>标注类别</span>
        <div class="label-select-row">
          <span class="swatch" id="activeLabelSwatch" style="background:${escapeHtml(color)}" title="${escapeHtml(color)}"></span>
          <select id="annotationLabelSelect" title="选择当前标注类别">
            ${labelListOptions()}
          </select>
        </div>
      </label>
      <div class="brush-size-controls">
        <div class="brush-size-row">
          <label for="brushRadius">画笔粗细</label>
          <input id="brushRadius" type="range" min="1" max="40" step="1" value="${state.brushRadius}" />
          <strong id="brushRadiusValue">${state.brushRadius}px</strong>
        </div>
        <div class="brush-size-row">
          <label for="eraseRadius">橡皮粗细</label>
          <input id="eraseRadius" type="range" min="1" max="60" step="1" value="${state.eraseRadius}" />
          <strong id="eraseRadiusValue">${state.eraseRadius}px</strong>
        </div>
      </div>
      <p class="label-picker-hint">画笔/智能选择等会按当前类别写入，颜色与色块一致。</p>
      <label class="erase-mode-row">
        <input type="checkbox" id="eraseCurrentClassOnly" ${state.eraseCurrentClassOnly ? "checked" : ""} />
        橡皮擦仅清除当前类别
      </label>
    </div>
  `;
}

function masksForActiveImage() {
  const image = activeImage();
  return image ? state.masksByImage[image.image_id] || [] : [];
}

function versionsForActiveCase() {
  const item = activeCase();
  return item ? state.versionsByCase[item.case_id] || [] : [];
}

function latestMaskByVersion(masks, version) {
  return [...(masks || [])]
    .filter((mask) => mask.version === version)
    .sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")))[0] || null;
}

function latest3DMask(masks) {
  const priority = { final: 5, v3_fusion: 4, v3_preview: 3, v2_ai: 2, v1_manual: 1 };
  // Always honor the explicitly selected mask (e.g. after AI predict -> v2_ai).
  const preferred = [...(masks || [])].find((mask) => (
    mask.mask_id === state.active3DMaskId &&
    (mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz"))
  ));
  if (preferred) return preferred;
  const propagated = latestPropagatedMask(masks);
  if (propagated) return propagated;
  return [...(masks || [])]
    .filter((mask) => mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz"))
    .sort((a, b) => {
      const versionScore = (priority[b.version] || 0) - (priority[a.version] || 0);
      if (versionScore !== 0) return versionScore;
      return String(b.create_time || "").localeCompare(String(a.create_time || ""));
    })[0] || null;
}

function latestPropagatedMask(masks) {
  const priority = { final: 4, v3_fusion: 3, v3_preview: 2 };
  return [...(masks || [])]
    .filter((mask) => (
      (mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz")) &&
      (mask.version === "v3_preview" || mask.version === "v3_fusion" || mask.version === "final")
    ))
    .sort((a, b) => {
      const versionScore = (priority[b.version] || 0) - (priority[a.version] || 0);
      if (versionScore !== 0) return versionScore;
      return String(b.create_time || "").localeCompare(String(a.create_time || ""));
    })[0] || null;
}

function latestOverlay3DMask(masks) {
  const preferred = [...(masks || [])].find((mask) => (
    mask.mask_id === state.active3DMaskId &&
    (mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz"))
  ));
  if (preferred) return preferred;
  return latestPropagatedMask(masks) || latest3DMask(masks);
}

function formatInteger(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : "-";
}

function formatNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "-";
}

function formatPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "-";
}

function formatSliceRange(range) {
  if (!range || range.start === null || range.end === null || range.start === undefined || range.end === undefined) {
    return "无";
  }
  return `${Number(range.start) + 1}-${Number(range.end) + 1}（${formatInteger(range.count)}层）`;
}

async function loadMaskQuality(maskId, { force = false } = {}) {
  if (!maskId) return null;
  if (!force && state.maskQualityById[maskId]) return state.maskQualityById[maskId];
  const data = await apiGet(`/api/mask/${maskId}/quality`);
  state.maskQualityById[maskId] = data;
  return data;
}

function renderMaskQualitySummary(mask) {
  if (!mask) {
    return `<div class="mask-quality-summary muted">暂无 3D Mask 质量摘要。</div>`;
  }
  const quality = state.maskQualityById[mask.mask_id];
  if (!quality) {
    return `
      <div class="mask-quality-summary" id="maskQualitySummary" data-mask-id="${escapeHtml(mask.mask_id)}">
        <span>质量摘要</span>
        <div class="quality-grid"><strong>加载中...</strong></div>
      </div>
    `;
  }
  return `
    <div class="mask-quality-summary" id="maskQualitySummary" data-mask-id="${escapeHtml(mask.mask_id)}">
      ${maskQualitySummaryMarkup(quality)}
    </div>
  `;
}

function maskQualitySummaryMarkup(quality) {
  return `
    <span>质量摘要</span>
    <div class="quality-grid">
      <strong><em>体素数</em>${formatInteger(quality.voxel_count)}</strong>
      <strong><em>体积</em>${formatNumber(quality.volume_ml, 3)} ml</strong>
      <strong><em>连通域</em>${formatInteger(quality.connected_component_count)}</strong>
      <strong><em>最大连通域</em>${formatPercent(quality.largest_component_ratio)}</strong>
      <strong><em>切片范围</em>${formatSliceRange(quality.slice_range)}</strong>
    </div>
  `;
}

function updateMaskQualitySummary(maskId) {
  const target = $("#maskQualitySummary");
  if (!target || target.dataset.maskId !== maskId) return;
  const quality = state.maskQualityById[maskId];
  if (!quality) {
    target.innerHTML = `<span>质量摘要</span><div class="quality-grid"><strong>加载失败</strong></div>`;
    return;
  }
  target.innerHTML = maskQualitySummaryMarkup(quality);
}

function renderMaskList(masks) {
  if (!masks.length) {
    return `<div class="placeholder compact">暂无 Mask。点击“保存 Mask”生成 v1_manual 记录。</div>`;
  }
  const sorted = [...masks].sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")));
  return `
    <div class="mask-record-list">
      ${sorted.map((mask) => {
        const isJson = mask.mask_format === "json" || String(mask.path || "").endsWith(".json");
        const axis = mask.axis || "axial";
        const sliceText = mask.slice_index == null ? "-" : `${Number(mask.slice_index) + 1}`;
        return `
        <article class="mask-record">
          <div><strong>${escapeHtml(mask.mask_id)}</strong><span>${escapeHtml(mask.version)}</span></div>
          <div><span>标签</span><b>${escapeHtml(mask.label)}</b></div>
          <div><span>类型</span><b>${escapeHtml(mask.label_type || "-")}</b></div>
          <div><span>平面</span><b>${escapeHtml(axis)} / ${escapeHtml(sliceText)}</b></div>
          <code>${escapeHtml(mask.path)}</code>
          <div class="mask-record-actions">
            ${isJson ? `<button class="ghost-button" data-load-mask="${escapeHtml(mask.mask_id)}">加载编辑</button>` : ""}
            <button class="danger-button" data-delete-mask="${escapeHtml(mask.mask_id)}">删除</button>
          </div>
        </article>
      `;
      }).join("")}
    </div>
  `;
}

function renderVersionList(versions) {
  if (!versions.length) {
    return `<div class="placeholder compact">暂无版本记录。保存 Mask 后会写入 v1_manual，智能修正后写入 v3_preview，确认后写入 v3_fusion 或 final。</div>`;
  }
  return `
    <div class="version-record-list">
      ${versions.map((item) => `
        <article class="version-record">
          <strong>${escapeHtml(item.version)}</strong>
          <span>annotation: ${escapeHtml(item.annotation || "-")}</span>
          <span>model: ${escapeHtml(item.model || "-")}</span>
          <span>dataset: ${escapeHtml(item.dataset || "-")}</span>
        </article>
      `).join("")}
    </div>
  `;
}

function renderToolButtons() {
  const allowed = annotationToolsForMode();
  const parts = [];
  let emittedUndoRedo = false;
  for (const [tool, label] of allowed) {
    if (tool === "undo" || tool === "redo") {
      if (emittedUndoRedo) continue;
      emittedUndoRedo = true;
      const undo = allowed.find(([key]) => key === "undo");
      const redo = allowed.find(([key]) => key === "redo");
      const pair = [undo, redo].filter(Boolean).map(([key, text]) => {
        const title = annotationToolTitles[key] || text;
        return `<button class="tool-button" data-annotation-tool="${key}" title="${title}" aria-label="${title}">${text}</button>`;
      }).join("");
      parts.push(`<div class="tool-undo-redo">${pair}</div>`);
      continue;
    }
    const title = annotationToolTitles[tool] || label;
    parts.push(
      `<button class="tool-button ${state.annotationTool === tool ? "active" : ""}" data-annotation-tool="${tool}" title="${title}" aria-label="${title}">${label}</button>`,
    );
  }
  return `${parts.join("")}${renderAiPredictControl()}`;
}

function renderAiPredictControl() {
  const current = state.aiPredictTarget || "all";
  const options = AI_PREDICT_TARGETS.map((item) => (
    `<option value="${escapeHtml(item.value)}" ${current === item.value ? "selected" : ""}>${escapeHtml(item.label)}</option>`
  )).join("");
  return `
    <div class="ai-predict-row">
      <label class="ai-predict-field" for="aiPredictTarget">
        <span>AI预测目标</span>
        <select id="aiPredictTarget" title="选择要预测的器官">
          ${options}
        </select>
      </label>
      <button type="button" class="tool-button ai-predict-button" data-ai-predict>开始AI预测</button>
    </div>
  `;
}

function resolveAiPredictRequest() {
  const target = String(state.aiPredictTarget || "all").trim().toLowerCase() || "all";
  const targetMeta = AI_PREDICT_TARGETS.find((item) => item.value === target);
  let model = selectedModel();
  const totalsegModels = state.models.filter((item) => /totalseg|totalsegmentator/i.test(String(item.model_id || item.backend || "")));
  const isBuiltinDemo = (item) => {
    const id = String(item?.model_id || "").toLowerCase();
    const backend = String(item?.backend || "").toLowerCase();
    return id.startsWith("builtin_") || backend.includes("builtin_ct_threshold");
  };
  const matchesTarget = (item) => {
    const id = String(item.model_id || "").toLowerCase();
    const label = String(item.label || "").toLowerCase();
    return id.includes(target) || label === target || label.includes(target);
  };
  if (target === "all") {
    const multi = totalsegModels.find((item) => {
      const id = String(item.model_id || "").toLowerCase();
      return /totalseg_(total|all|organs|multi)/.test(id) || id.endsWith("_total") || id.endsWith("_organs");
    }) || totalsegModels[0];
    if (multi) model = multi;
  } else if (target === "tumor") {
    // 疑似肿瘤：走器官残差启发式（后端会先跑 TotalSeg organs）
    const heuristic = state.models.find((item) => String(item.model_id || "").toLowerCase() === "tumor_residual_heuristic");
    const organsModel = totalsegModels.find((item) => {
      const id = String(item.model_id || "").toLowerCase();
      return id.includes("organs") || id.endsWith("_organs");
    });
    model = heuristic || organsModel || totalsegModels[0] || model;
  } else {
    // 单器官优先 TotalSeg / 真实后端；不要命中 builtin_bone / builtin_lung（无真实权重）
    const namedTotalseg = totalsegModels.find(matchesTarget);
    const namedReal = state.models.find((item) => matchesTarget(item) && !isBuiltinDemo(item));
    model = namedTotalseg || namedReal || totalsegModels[0] || model;
  }
  return {
    target,
    targetLabel: targetMeta?.label || target,
    model,
    label: target === "all" ? "all" : target,
  };
}

function annotationToolsForMode() {
  if (state.annotationMode === "coarse") {
    const allowed = new Set(["rectangle", "magic", "undo", "redo", "clearAll", "clear"]);
    return annotationTools.filter(([tool]) => allowed.has(tool));
  }
  if (state.annotationMode === "scribble") {
    const allowed = new Set(["brush", "erase", "smartErase", "point", "undo", "redo", "clearAll", "clear"]);
    return annotationTools.filter(([tool]) => allowed.has(tool));
  }
  return annotationTools;
}

function currentLabelType() {
  if (state.annotationMode === "coarse") return "coarse";
  if (state.annotationMode === "scribble") return "scribble";
  return "dense";
}

function localLabeledAxialSlices(image) {
  if (!image) return [];
  const values = new Set();
  const imageMasks = state.sliceMasks[image.image_id] || {};
  const imagePoints = state.pointAnnotations[image.image_id] || {};
  for (const key of [...Object.keys(imageMasks), ...Object.keys(imagePoints)]) {
    const { axis, sliceIndex } = parseSliceStorageKey(key);
    if (axis !== "axial") continue;
    const mask = imageMasks[key];
    const points = imagePoints[key] || [];
    const hasPixels = mask?.data && [...mask.data].some((value) => value > 0);
    if (hasPixels || points.length) values.add(sliceIndex);
  }
  return [...values].sort((a, b) => a - b);
}

function renderAnnotationModeControls() {
  const modes = [
    ["dense", "精标"],
    ["coarse", "粗标"],
    ["scribble", "涂鸦"],
  ];
  return `
    <div class="annotation-mode-panel">
      <div class="param-header"><span>标注模式</span><strong>${currentLabelType()}</strong></div>
      <div class="segmented-control cols-3">
        ${modes.map(([mode, label]) => `
          <button type="button" class="${state.annotationMode === mode ? "active" : ""}" data-annotation-mode="${mode}">${label}</button>
        `).join("")}
      </div>
      <small>${state.annotationMode === "coarse"
        ? "粗标：仅矩形 / Magic Wand，保存后可一键传播生成弱监督伪标。"
        : state.annotationMode === "scribble"
          ? "涂鸦：画笔/点/智能橡皮擦，适合 scribble 弱监督。"
          : "精标：全部工具，label_type=dense。"}</small>
    </div>
  `;
}

function renderFewShotWizard(image, volume) {
  const assist = state.labelingAssist;
  const localLabeled = localLabeledAxialSlices(image);
  const labeledCount = assist?.workload?.labeled_count ?? localLabeled.length;
  const totalSlices = assist?.workload?.total_slices ?? (volume ? axisSliceCount(volume, "axial") : 0);
  const minSlices = state.fewShotMinSlices;
  const remaining = Math.max(0, minSlices - labeledCount);
  const ready = labeledCount >= minSlices;
  const recommendations = assist?.recommendations || [];
  const estimated = assist?.workload?.estimated_remaining_dense ?? Math.max(0, Math.ceil(totalSlices * 0.12) - labeledCount);
  return `
    <div class="few-shot-panel">
      <div class="param-header"><span>少量标注向导</span><strong>${labeledCount} / ${minSlices} 层</strong></div>
      <label class="param-row" for="fewShotMinSlices">
        <span>最少标 N 层</span>
        <input id="fewShotMinSlices" type="number" min="1" max="20" step="1" value="${minSlices}" />
      </label>
      <div class="workload-grid">
        <div><span>已标层数</span><strong>${labeledCount}</strong></div>
        <div><span>总层数</span><strong>${totalSlices || "-"}</strong></div>
        <div><span>距最少还差</span><strong>${remaining}</strong></div>
        <div><span>预估精标剩余</span><strong>${estimated}</strong></div>
      </div>
      <div class="few-shot-actions action-stack">
        <button class="primary-button" data-few-shot-propagate ${image && canAnnotate() && ready ? "" : "disabled"}>
          ${ready ? "一键传播 → v3_preview" : `还需标 ${remaining} 层`}
        </button>
        <button class="ghost-button" data-refresh-labeling-assist ${image ? "" : "disabled"}>刷新推荐</button>
      </div>
      <div class="al-recommend-list">
        <span>下一层推荐</span>
        <div class="al-recommend-chips">
          ${recommendations.length ? recommendations.map((item) => `
            <button type="button" class="al-slice-chip" data-jump-slice="${item.slice_index}" title="${escapeHtml(item.reason)} score=${item.score}">
              层 ${item.slice_index + 1}<small>${escapeHtml(item.reason)}</small>
            </button>
          `).join("") : `<small>保存几层标注后点「刷新推荐」，系统会提示优先标哪几层。</small>`}
        </div>
      </div>
    </div>
  `;
}

function annotationToolLabel(tool = state.annotationTool) {
  return annotationTools.find(([key]) => key === tool)?.[1] || tool;
}

function renderMagicWandControls() {
  const options = Object.entries(magicWandPresets)
    .map(([key, preset]) => `<option value="${key}" ${state.magicWandPreset === key ? "selected" : ""}>${preset.label}（${preset.range}）</option>`)
    .join("");
  return `
    <div class="magic-wand-controls">
      <div class="magic-control-row">
        <label for="magicPreset">智能场景</label>
        <select id="magicPreset">${options}</select>
      </div>
      <div class="magic-control-row threshold-row">
        <label for="magicThreshold">智能阈值</label>
        <input id="magicThreshold" type="range" min="10" max="250" step="1" value="${state.magicWandThreshold}" />
        <strong id="magicThresholdValue">HU ± ${state.magicWandThreshold}</strong>
      </div>
      <p class="label-picker-hint">点选后按「种子 HU ± 阈值」生长；换标注类别会自动匹配场景。</p>
    </div>
  `;
}

function renderSmartRefineHint() {
  const image = activeImage();
  const counts = promptCounts(image);
  return `
    <div class="deepedit-controls">
      <span>智能修正提示</span>
      <div class="prompt-count-row">
        <strong class="prompt-positive" id="promptPositiveCount">正点 ${counts.positive}</strong>
        <strong class="prompt-negative" id="promptNegativeCount">负点 ${counts.negative}</strong>
      </div>
      <small>画笔/多边形/矩形 = 正向标注；智能橡皮擦记为负点。「DeepEdit 神经网络」需独立服务；无服务时请用「图割修正」。</small>
    </div>
  `;
}

function updatePromptCountDisplay() {
  const counts = promptCounts(activeImage());
  const positive = $("#promptPositiveCount");
  const negative = $("#promptNegativeCount");
  if (positive) positive.textContent = `正点 ${counts.positive}`;
  if (negative) negative.textContent = `负点 ${counts.negative}`;
}

function renderRefineParamControls() {
  const params = state.refineParams;
  return `
    <div class="refine-param-controls">
      <div class="param-header"><span>修正参数</span><strong>图割 Random Walker</strong></div>
      <label class="param-row" for="randomWalkerBeta">
        <span>边界敏感度 beta</span>
        <input id="randomWalkerBeta" type="range" min="20" max="180" step="5" value="${params.randomWalkerBeta}" />
        <input id="randomWalkerBetaValue" type="number" min="20" max="180" step="5" value="${params.randomWalkerBeta}" />
      </label>
      <label class="param-row" for="roiMargin">
        <span>ROI margin</span>
        <input id="roiMargin" type="range" min="4" max="80" step="2" value="${params.roiMargin}" />
        <input id="roiMarginValue" type="number" min="4" max="80" step="2" value="${params.roiMargin}" />
      </label>
      <label class="param-row" for="minVoxels">
        <span>最小连通域体素</span>
        <input id="minVoxels" type="range" min="0" max="1000" step="16" value="${params.minVoxels}" />
        <input id="minVoxelsValue" type="number" min="0" max="1000" step="16" value="${params.minVoxels}" />
      </label>
      <small>beta 越高越贴灰度边界；ROI margin 越大搜索区域越宽；最小体素越大越容易清理小噪点。</small>
    </div>
  `;
}

function renderViewerModeButtons() {
  return `
    <div class="viewer-mode-switch">
      <button class="mode-button ${state.volumeViewMode === "2d" ? "active" : ""}" data-view-mode="2d">2D切片</button>
      <button class="mode-button ${state.volumeViewMode === "3d" ? "active" : ""}" data-view-mode="3d">3D体视图</button>
    </div>
  `;
}

function render2DViewer(item, image, volume, activeSlice, sliceCount, maxSlice, axis) {
  const zoomPercent = Math.round((Number(state.viewerZoom) || 1) * 100);
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span id="viewerTitle">${item ? item.case_id : "暂无病例"} | ${axisLabel(axis)}</span><span id="viewerInfo">${image ? image.image_id : "等待图像"} | 缩放 ${zoomPercent}%</span></div>
      ${renderViewerModeButtons()}
      <div class="ct-frame real-image-frame" id="sliceFrame">
        ${image ? `<img id="sliceImage" class="ct-slice-image" alt="医学影像切片" />` : ""}
        <div id="sliceError" class="slice-empty ${image ? "hidden" : ""}">${image ? "正在读取体数据..." : "暂无可显示图像"}</div>
        ${image ? `<canvas id="annotationCanvas" class="annotation-canvas" aria-label="标注画布"></canvas>` : ""}
        <div class="coordinate" id="sliceCoordinate">${axisCoordinateName(axis)}: ${activeSlice + 1} / ${sliceCount}</div>
      </div>
      <div class="slider-row zoom-row">
        <span>缩放</span>
        <div class="zoom-controls">
          <button type="button" class="ghost-button zoom-button" data-zoom-action="out" title="缩小">−</button>
          <input id="viewerZoomSlider" type="range" min="25" max="400" step="5" value="${zoomPercent}" aria-label="缩放比例" />
          <button type="button" class="ghost-button zoom-button" data-zoom-action="in" title="放大">+</button>
          <button type="button" class="ghost-button zoom-button" data-zoom-action="fit" title="适应窗口">适应</button>
        </div>
        <strong id="zoomValue">${zoomPercent}%</strong>
      </div>
      <small class="zoom-hint">滚轮缩放；按住 Alt 或鼠标中键拖动平移。不同 CT 尺寸可用缩放对齐标注。</small>
      <div class="slider-row">
        <span>标注平面</span>
        <select id="axisSelect" aria-label="选择标注平面">
          <option value="axial" ${axis === "axial" ? "selected" : ""}>轴位 Axial</option>
          <option value="coronal" ${axis === "coronal" ? "selected" : ""}>冠状位 Coronal</option>
          <option value="sagittal" ${axis === "sagittal" ? "selected" : ""}>矢状位 Sagittal</option>
        </select>
        <strong id="axisValue">${axisCoordinateName(axis).toUpperCase()}</strong>
      </div>
      <div class="slider-row"><span>切片</span><input id="sliceSlider" type="range" min="0" max="${maxSlice}" value="${activeSlice}" /><strong id="sliceValue">${activeSlice + 1}</strong></div>
      <div class="slider-row"><span>透明度</span><input type="range" min="0" max="100" value="54" /><strong>54%</strong></div>
      <div class="slider-row"><span>窗宽窗位</span><select id="windowSelect" aria-label="选择CT窗宽窗位"><option value="auto">自动</option><option value="lung">肺窗</option><option value="soft">软组织</option><option value="bone">骨窗</option></select><strong id="windowValue">自动</strong></div>
      <div class="image-source-line" id="sliceSource">切片接口：等待加载</div>
    </section>
  `;
}

function render3DViewer(item, image, volume, masks = []) {
  const width = volume?.width || 1;
  const height = volume?.height || 1;
  const depth = volume?.slice_count || 1;
  const canRender = Boolean(image && volume);
  const niftiMasks = [...(masks || [])]
    .filter((mask) => mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz"))
    .sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")));
  const active3DMask = latest3DMask(masks);
  const axialIndex = Math.min(currentSliceIndex("axial"), Math.max(depth - 1, 0));
  const coronalIndex = Math.min(currentSliceIndex("coronal"), Math.max(height - 1, 0));
  const sagittalIndex = Math.min(currentSliceIndex("sagittal"), Math.max(width - 1, 0));
  const mprGrid = `
    <div class="viewer-subsection">
      <div class="subsection-title"><span>MPR 三平面重建（与选中 Mask / 切片联动）</span><strong>点击可回 2D 修正</strong></div>
      <div class="orthogonal-grid mpr-grid">
        <button type="button" class="mpr-jump" data-jump-2d-axis="axial" data-jump-2d-slice="${axialIndex}">
          <span>轴位 Slice ${axialIndex + 1}</span>
          ${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/axial/${axialIndex}.png?window=auto`)}" alt="轴位 MPR" />` : ""}
        </button>
        <button type="button" class="mpr-jump" data-jump-2d-axis="coronal" data-jump-2d-slice="${coronalIndex}">
          <span>冠状位 Slice ${coronalIndex + 1}</span>
          ${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/coronal/${coronalIndex}.png?window=auto`)}" alt="冠状位 MPR" />` : ""}
        </button>
        <button type="button" class="mpr-jump" data-jump-2d-axis="sagittal" data-jump-2d-slice="${sagittalIndex}">
          <span>矢状位 Slice ${sagittalIndex + 1}</span>
          ${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/sagittal/${sagittalIndex}.png?window=auto`)}" alt="矢状位 MPR" />` : ""}
        </button>
      </div>
      <div class="slider-row"><span>轴位联动</span><input id="mprAxialSlider" type="range" min="0" max="${Math.max(depth - 1, 0)}" value="${axialIndex}" /><strong>${axialIndex + 1}</strong></div>
      <div class="slider-row"><span>冠状联动</span><input id="mprCoronalSlider" type="range" min="0" max="${Math.max(height - 1, 0)}" value="${coronalIndex}" /><strong>${coronalIndex + 1}</strong></div>
      <div class="slider-row"><span>矢状联动</span><input id="mprSagittalSlider" type="range" min="0" max="${Math.max(width - 1, 0)}" value="${sagittalIndex}" /><strong>${sagittalIndex + 1}</strong></div>
    </div>
  `;
  const mipGrid = state.showMip
    ? `
      <div class="viewer-subsection">
      <div class="subsection-title"><span>MIP / MinIP 投影</span><strong>高密度 / 低密度结构辅助观察</strong></div>
      <div class="orthogonal-grid">
        <div><span>轴位 MIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/axial.png?method=mip&window=auto`)}" alt="轴位 MIP" />` : ""}</div>
        <div><span>冠状位 MIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/coronal.png?method=mip&window=auto`)}" alt="冠状位 MIP" />` : ""}</div>
        <div><span>矢状位 MIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/sagittal.png?method=mip&window=auto`)}" alt="矢状位 MIP" />` : ""}</div>
        <div><span>轴位 MinIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/axial.png?method=min&window=auto`)}" alt="轴位 MinIP" />` : ""}</div>
        <div><span>冠状位 MinIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/coronal.png?method=min&window=auto`)}" alt="冠状位 MinIP" />` : ""}</div>
        <div><span>矢状位 MinIP</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/projection/sagittal.png?method=min&window=auto`)}" alt="矢状位 MinIP" />` : ""}</div>
      </div>
      </div>
    `
    : `
      <div class="mip-placeholder">
        <span>体渲染用于整体空间观察；细节诊断请结合 2D 切片。MIP/MinIP 可辅助观察高密度结构和低密度腔隙。</span>
        <button class="ghost-button" data-load-mip>加载 MIP / MinIP</button>
      </div>
    `;
  const maskOptions = niftiMasks.length
    ? niftiMasks.map((mask) => `
        <option value="${escapeHtml(mask.mask_id)}" ${active3DMask?.mask_id === mask.mask_id ? "selected" : ""}>
          ${escapeHtml(mask.mask_id)} · ${escapeHtml(mask.version)} · ${escapeHtml(mask.label)}
        </option>
      `).join("")
    : `<option value="">暂无 3D Mask</option>`;
  const maskOverlayPanel = `
    <div class="mask-overlay-panel">
      <div>
        <span>3D Mask 选中高亮</span>
        <strong>${active3DMask ? `${active3DMask.mask_id} · ${active3DMask.version}` : "暂无 3D Mask"}</strong>
        <label class="mask-select-row" for="active3DMaskSelect">选择 Mask（仅 nii.gz）</label>
        <select id="active3DMaskSelect" ${niftiMasks.length ? "" : "disabled"}>${maskOptions}</select>
        <code>${active3DMask
          ? active3DMask.path
          : "手动画的是 2D JSON，不能直接出现在此列表。请点右侧按钮：把已保存的 2D 标注堆成 3D 后再选。"}</code>
        ${renderMaskQualitySummary(active3DMask)}
      </div>
      <button class="primary-button" data-render-annotation-3d ${canRender ? "" : "disabled"}>用我的2D标注生成3D高亮</button>
    </div>
  `;
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span>${item ? item.case_id : "暂无病例"} | 3D体视图</span><span>${canRender ? `${width} × ${height} × ${depth}` : "等待体数据"}</span></div>
      ${renderViewerModeButtons()}
      <div id="volumeContainer" class="volume-container" data-image-id="${image?.image_id || ""}" data-mask-id="${active3DMask?.mask_id || ""}" data-highlight-mask="true">
        <div class="volume-status">${canRender ? "正在初始化 VTK 综合重建..." : "正在读取体数据..."}</div>
      </div>
      ${mprGrid}
      ${mipGrid}
      ${maskOverlayPanel}
      <div class="image-source-line">三维体数据标注 = 体渲染可视化 + 3D mask 生成/编辑闭环（2D 修正为主），不是必须 3D 画笔。</div>
      <div class="image-source-line">3D来源：${canRender ? `/api/image/${image.image_id}/surface-mesh?protocol=body|lung|soft|bone${active3DMask ? ` + /api/mask/${active3DMask.mask_id}/surface-mesh` : ""}；选中 Mask 高亮叠加` : "等待加载"}</div>
    </section>
  `;
}

function renderAnnotation() {
  const item = activeCase();
  const image = activeImage();
  const volume = image ? state.volumeMeta[image.image_id] : null;
  const masks = masksForActiveImage();
  const versions = versionsForActiveCase();
  const axis = activeAxis();
  const sliceCount = axisSliceCount(volume || image, axis);
  const maxSlice = Math.max(sliceCount - 1, 0);
  const activeSlice = Math.min(currentSliceIndex(axis), maxSlice);
  const meta = item
    ? [["病例", item.case_id], ["患者", item.patient_id], ["影像类型", item.modality], ["状态", statusText[item.status] || item.status || "未标注"], ["图像数", item.image_count], ["Mask数", masks.length]]
    : [["病例", "暂无病例"], ["患者", "-"], ["影像类型", "-"], ["状态", "-"], ["图像数", "0"]];
  if (image) {
    meta.push(["图像", image.image_id]);
    meta.push(["格式", image.file_format]);
  }
  const previewMask = latestMaskByVersion(masks, "v3_preview");
  const fusionMask = latestMaskByVersion(masks, "v3_fusion");
  const aiMask = latestMaskByVersion(masks, "v2_ai");
  const versionTimeline = ["v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"];
  const model = selectedModel();
  const rejectNote = item?.reject_note || state.caseDetails[item?.case_id]?.case?.reject_note || "";
  return `
    <div class="workbench-layout">
      <aside class="case-sidebar">
        <h2>病例信息</h2>
        <div class="case-meta">${meta.map(([key, value]) => `<div class="meta-line"><span>${key}</span><strong>${value}</strong></div>`).join("")}</div>
        ${rejectNote ? `<div class="reject-note-box"><span>驳回意见</span><strong>${escapeHtml(rejectNote)}</strong><small>版本保留在 v3_preview / v2_ai，未进入 final</small></div>` : ""}
        <h3 style="margin-top:24px">体数据</h3>
        <div class="case-meta">
          <div class="meta-line"><span>尺寸</span><strong id="volumeSize">${volume ? `${volume.width} × ${volume.height} × ${volume.slice_count}` : "加载中"}</strong></div>
          <div class="meta-line"><span>读取器</span><strong id="volumeSource">${volume?.source || "-"}</strong></div>
        </div>
        <h3 style="margin-top:24px">AI 模型</h3>
        <div class="case-meta">
          <div class="meta-line"><span>当前模型</span><strong>${model ? escapeHtml(model.display_name || model.model_id) : "未加载"}</strong></div>
          <div class="meta-line"><span>model_id</span><strong>${model ? escapeHtml(model.model_id) : "-"}</strong></div>
        </div>
        <h3 style="margin-top:24px">版本</h3>
        <div class="timeline">${versionTimeline.map((version) => `<span class="chip ${versions.some((item) => item.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
        <h3 style="margin-top:24px">标签</h3>
        ${renderLabelPicker()}
      </aside>
      ${state.volumeViewMode === "3d" ? render3DViewer(item, image, volume, masks) : render2DViewer(item, image, volume, activeSlice, sliceCount, maxSlice, axis)}
      <aside class="tool-panel">
        <h2>标注工具</h2>
        ${renderAnnotationModeControls()}
        ${renderLabelPicker()}
        <div class="tool-grid">${renderToolButtons()}</div>
        <div class="annotation-state-line"><span>当前工具：<strong id="annotationToolLabel">${annotationToolLabel()}</strong></span><span>当前 label：<strong>${escapeHtml(state.annotationLabel)} #${state.annotationLabelId}</strong></span><span>智能阈值：<strong>HU ± ${state.magicWandThreshold}</strong></span><span>当前切片：<strong id="annotationMaskStats">0 像素</strong></span></div>
        ${renderMagicWandControls()}
        ${renderFewShotWizard(image, volume)}
        ${renderSmartRefineHint()}
        ${renderRefineParamControls()}
        <div class="grid action-stack" style="margin-top:18px">
          <button class="primary-button" data-save-mask ${image && canAnnotate() ? "" : "disabled"}>保存 Mask</button>
          <button class="ghost-button" data-load-v2-ai ${image && aiMask ? "" : "disabled"}>从 v2_ai 加载到 2D</button>
          <button class="ghost-button" data-submit-case ${image && (currentRole() === "annotator" || currentRole() === "admin") ? "" : "disabled"}>提交审核</button>
          <button class="ghost-button" data-smart-3d-refine ${image && canAnnotate() ? "" : "disabled"}>DeepEdit 神经网络</button>
          <button class="ghost-button" data-graph-cut-refine ${image && canAnnotate() ? "" : "disabled"}>图割修正</button>
          <button class="ghost-button" data-confirm-fusion ${previewMask && canAnnotate() ? "" : "disabled"}>确认 v3_fusion</button>
          <button class="ghost-button" data-final-mask ${(previewMask || fusionMask) && canConfirmFinal() ? "" : "disabled"}>确认 final</button>
          <button class="ghost-button" data-compare-masks ${image ? "" : "disabled"}>计算 Dice</button>
          <button class="ghost-button" data-approve-case ${item && canReview() ? "" : "disabled"}>审核通过</button>
          <button class="danger-button" data-reject-case ${item && canReview() ? "" : "disabled"}>驳回</button>
          <button class="ghost-button" data-export-mask-nifti ${image && canAnnotate() ? "" : "disabled"}>导出 3D Mask</button>
          <button class="ghost-button" data-start-3d-render ${image ? "" : "disabled"}>导出 3D 图像</button>
        </div>
        ${state.lastCompareResult ? `<div class="compare-result-box"><span>最近 Dice</span><strong>${Number(state.lastCompareResult.dice).toFixed(4)}</strong><small>${escapeHtml(state.lastCompareResult.pred_mask_id)} vs ${escapeHtml(state.lastCompareResult.ref_mask_id)}</small></div>` : ""}
        <h3 style="margin-top:22px">当前 Mask</h3>
        ${renderMaskList(masks)}
      </aside>
    </div>
  `;
}

async function hydrateAnnotation() {
  const item = activeCase();
  if (!item) return;
  try {
    await loadCaseDetail(item.case_id);
    const image = activeImage();
    if (!image) return;
    const needsMaskRender = !state.masksByImage[image.image_id] || !state.versionsByCase[item.case_id];
    await loadImageMasks(image.image_id);
    await loadCaseVersions(item.case_id);
    refreshLabelingAssist({ silent: true }).catch(() => {});
    if (needsMaskRender) {
      render();
      return;
    }
    const meta = await loadVolumeMeta(image.image_id);
    if (state.volumeViewMode === "2d") {
      updateSliceViewer(image, meta);
      return;
    }
    if (!$("#volumeContainer")) {
      render();
      return;
    }
    startVolumeViewer(image);
  } catch (error) {
    const image = activeImage();
    const message = readableVolumeErrorMessage(error.message || "图像读取失败");
    if (image) state.volumeErrors[image.image_id] = message;
    const recovered = await recoverReadableAnnotation(image?.image_id, message);
    if (recovered) return;
    displaySliceError(message);
    showToast(message);
  }
}

async function recoverReadableAnnotation(failedImageId, reason) {
  if (state.recoveringAnnotation) return false;
  state.recoveringAnnotation = true;
  try {
    const candidates = [...state.cases].reverse();
    for (const caseItem of candidates) {
      const detail = await loadCaseDetail(caseItem.case_id);
      for (const image of detail.images || []) {
        if (image.image_id === failedImageId) continue;
        try {
          await loadVolumeMeta(image.image_id);
          state.activeCaseId = caseItem.case_id;
          state.activeImageId = image.image_id;
          await loadImageMasks(image.image_id, { force: true });
          await loadCaseVersions(caseItem.case_id, { force: true });
          showToast(`${reason} 已切换到可读病例 ${caseItem.case_id}`);
          render();
          return true;
        } catch (candidateError) {
          state.volumeErrors[image.image_id] = readableVolumeErrorMessage(candidateError.message || "图像读取失败");
        }
      }
    }
    return false;
  } finally {
    state.recoveringAnnotation = false;
  }
}

function updateSliceViewer(image, meta) {
  const imageElement = $("#sliceImage");
  if (!imageElement || !meta) {
    render();
    return;
  }

  const axis = activeAxis();
  const sliceCount = axisSliceCount(meta, axis);
  const maxSlice = Math.max(sliceCount - 1, 0);
  setCurrentSliceIndex(Math.max(0, Math.min(currentSliceIndex(axis), maxSlice)), axis);
  const sliceIndex = currentSliceIndex(axis);
  const slider = $("#sliceSlider");
  if (slider) {
    slider.max = String(maxSlice);
    slider.value = String(sliceIndex);
  }

  const sliceNumber = sliceIndex + 1;
  const sliceUrl = apiUrl(`/api/image/${image.image_id}/slice/${axis}/${sliceIndex}.png?window=${state.activeWindow}&t=${Date.now()}`);
  imageElement.onload = () => {
    imageElement.classList.remove("hidden");
    $("#sliceError").classList.add("hidden");
    $("#annotationCanvas")?.classList.remove("hidden");
    resizeAnnotationCanvas({ reset: true });
    restorePropagatedSliceMask(image.image_id);
  };
  imageElement.onerror = () => {
    displaySliceError("切片图像加载失败，请确认当前病例是真实 DICOM / NRRD / NIfTI 体数据。");
  };
  imageElement.src = sliceUrl;
  $("#sliceValue").textContent = String(sliceNumber);
  $("#sliceCoordinate").textContent = `${axisCoordinateName(axis)}: ${sliceNumber} / ${sliceCount}`;
  $("#sliceSource").textContent = `切片接口：/api/image/${image.image_id}/slice/${axis}/${sliceIndex}.png`;
  const overlayMask = latestOverlay3DMask(state.masksByImage[image.image_id] || []);
  if (overlayMask) {
    $("#sliceSource").textContent += ` · 叠加Mask：${overlayMask.mask_id} / ${overlayMask.version}`;
  }
  $("#viewerInfo").textContent = `${image.image_id} | ${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSize").textContent = `${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSource").textContent = meta.source;
  const select = $("#windowSelect");
  if (select) {
    select.value = state.activeWindow;
    $("#windowValue").textContent = select.options[select.selectedIndex].textContent;
  }
  const axisSelect = $("#axisSelect");
  if (axisSelect) {
    axisSelect.value = axis;
    $("#axisValue").textContent = axisCoordinateName(axis).toUpperCase();
  }
}

function displaySliceError(message) {
  const errorBox = $("#sliceError");
  const imageElement = $("#sliceImage");
  const annotationCanvas = $("#annotationCanvas");
  if (imageElement) imageElement.classList.add("hidden");
  if (annotationCanvas) annotationCanvas.classList.add("hidden");
  if (errorBox) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }
  const source = $("#volumeSource");
  if (source) source.textContent = "读取失败";
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function setAnnotationTool(tool) {
  if (tool === "clear") {
    clearAnnotationCanvas();
    return;
  }
  if (tool === "clearAll") {
    clearAllManualAnnotations();
    return;
  }
  if (tool === "undo") {
    undoAnnotation();
    return;
  }
  if (tool === "redo") {
    redoAnnotation();
    return;
  }
  state.annotationTool = tool;
  state.annotationDrawing = false;
  state.annotationLastPoint = null;
  state.annotationShapeStart = null;
  state.annotationPreviewRect = null;
  if (tool !== "polygon") {
    state.annotationPolygonPoints = [];
    state.annotationPolygonPreviewPoint = null;
  }
  updateAnnotationToolButtons();
}

function updateAnnotationToolButtons() {
  document.querySelectorAll("[data-annotation-tool]").forEach((button) => {
    button.classList.toggle("active", button.dataset.annotationTool === state.annotationTool);
  });
  const toolLabel = $("#annotationToolLabel");
  if (toolLabel) toolLabel.textContent = annotationToolLabel();
}

function updateMagicWandControls() {
  const thresholdValue = $("#magicThresholdValue");
  if (thresholdValue) thresholdValue.textContent = `HU ± ${state.magicWandThreshold}`;
  const thresholdInput = $("#magicThreshold");
  if (thresholdInput) thresholdInput.value = String(state.magicWandThreshold);
  const presetSelect = $("#magicPreset");
  if (presetSelect) presetSelect.value = state.magicWandPreset;
}

function bindMagicWandControls() {
  const presetSelect = $("#magicPreset");
  if (presetSelect) {
    presetSelect.addEventListener("change", () => {
      state.magicWandPreset = presetSelect.value;
      const preset = magicWandPresets[state.magicWandPreset];
      if (preset) state.magicWandThreshold = preset.threshold;
      updateMagicWandControls();
    });
  }

  const thresholdInput = $("#magicThreshold");
  if (thresholdInput) {
    thresholdInput.addEventListener("input", () => {
      state.magicWandThreshold = Number(thresholdInput.value);
      state.magicWandPreset = "custom";
      updateMagicWandControls();
    });
  }
}

function bindRefineParamControls() {
  const bindings = [
    ["randomWalkerBeta", "randomWalkerBetaValue", "randomWalkerBeta", 20, 180],
    ["roiMargin", "roiMarginValue", "roiMargin", 4, 80],
    ["minVoxels", "minVoxelsValue", "minVoxels", 0, 1000],
  ];
  for (const [rangeId, numberId, key, min, max] of bindings) {
    const range = $(`#${rangeId}`);
    const number = $(`#${numberId}`);
    if (!range || !number) continue;
    const update = (rawValue) => {
      const value = clamp(Number(rawValue) || min, min, max);
      state.refineParams[key] = value;
      range.value = String(value);
      number.value = String(value);
    };
    range.addEventListener("input", () => update(range.value));
    number.addEventListener("change", () => update(number.value));
  }
}

function updateAnnotationMaskStats() {
  const stats = $("#annotationMaskStats");
  if (!stats) return;
  const mask = currentSliceMask({ create: false });
  const points = currentSlicePoints({ create: false }) || [];
  if (!mask) {
    stats.textContent = `0 像素 / ${points.length} 点`;
    return;
  }
  let count = 0;
  for (const value of mask.data) {
    if (value) count += 1;
  }
  const sourceText = mask.source === "label_propagation" || mask.source === "ai_predict"
    ? ` / ${mask.maskId}`
    : "";
  stats.textContent = `${count} 像素 / ${points.length} 点${sourceText}`;
}

function clearAnnotationCanvas() {
  pushUndoSnapshot();
  const image = activeImage();
  const sliceKey = sliceStorageKey(activeAxis(), currentSliceIndex());
  const mask = currentSliceMask({ create: false });
  if (mask) mask.data.fill(0);
  const points = currentSlicePoints({ create: false });
  if (points) points.length = 0;
  if (image && state.negativeScribbles[image.image_id]) {
    state.negativeScribbles[image.image_id][sliceKey] = [];
  }
  renderCurrentSliceMask();
  state.annotationDrawing = false;
  state.annotationLastPoint = null;
  state.annotationShapeStart = null;
  state.annotationPolygonPoints = [];
  state.annotationPolygonPreviewPoint = null;
  state.annotationPreviewRect = null;
  showToast("当前切片标注已清空");
}

/** 「重做」：清空当前图像全部切片的手动标注（需确认），并阻止自动叠加回灌。 */
async function clearAllManualAnnotations() {
  const image = activeImage();
  if (!image) {
    showToast("请先打开图像");
    return;
  }
  const imageId = image.image_id;
  const maskCount = Object.keys(state.sliceMasks[imageId] || {}).length;
  const pointSlices = Object.values(state.pointAnnotations[imageId] || {});
  const pointCount = pointSlices.reduce((sum, pts) => sum + (pts?.length || 0), 0);
  const negCount = Object.values(state.negativeScribbles[imageId] || {}).reduce(
    (sum, pts) => sum + (pts?.length || 0),
    0,
  );
  const savedJsonMasks = (state.masksByImage[imageId] || []).filter((mask) => (
    mask.version === "v1_manual"
    && (mask.mask_format === "json" || String(mask.path || "").endsWith(".json"))
  ));
  const hasOverlay = Boolean(latestOverlay3DMask(state.masksByImage[imageId] || []));
  if (!maskCount && !pointCount && !negCount && !savedJsonMasks.length && !hasOverlay) {
    showToast("当前没有可清空的手动标注");
    return;
  }
  const ok = window.confirm(
    "确认清空当前图像全部切片的标注？\n"
    + "将清除所有切片画布内容，并停止自动叠加已保存/AI 结果到 2D 画布。\n"
    + (savedJsonMasks.length ? `同时删除服务器上 ${savedJsonMasks.length} 条已保存的 v1_manual 切片 Mask。\n` : "")
    + "此操作后无法通过「←」撤销恢复。",
  );
  if (!ok) return;

  // 本地：每个切片清零并移除
  const imageMasks = state.sliceMasks[imageId] || {};
  for (const sliceKey of Object.keys(imageMasks)) {
    const mask = imageMasks[sliceKey];
    if (mask?.data) mask.data.fill(0);
  }
  state.sliceMasks[imageId] = {};
  state.pointAnnotations[imageId] = {};
  state.negativeScribbles[imageId] = {};
  state.undoStack = [];
  state.redoStack = [];
  state.annotationDrawing = false;
  state.annotationLastPoint = null;
  state.annotationShapeStart = null;
  state.annotationPolygonPoints = [];
  state.annotationPolygonPreviewPoint = null;
  state.annotationPreviewRect = null;
  state.suppressCanvasMaskRestore[imageId] = true;
  state.autoOverlayOnCanvas = false;
  delete state.restoredMaskSlices[imageId];

  // 清除该图像相关的自动回灌缓存，避免换层时再次写入
  for (const key of Object.keys(state.propagatedSliceLoads)) {
    if (key.startsWith(`${imageId}:`)) delete state.propagatedSliceLoads[key];
  }
  for (const mask of state.masksByImage[imageId] || []) {
    delete state.loadedMaskContents[mask.mask_id];
  }

  // 删除服务器上已保存的手动 JSON 切片，避免刷新后又恢复
  let deleted = 0;
  for (const mask of savedJsonMasks) {
    try {
      await apiDelete(`/api/mask/${mask.mask_id}`);
      deleted += 1;
      delete state.loadedMaskContents[mask.mask_id];
    } catch (error) {
      console.warn(`删除 Mask 失败：${mask.mask_id}`, error);
    }
  }
  if (deleted) {
    try {
      await loadImageMasks(imageId, { force: true });
    } catch (error) {
      console.warn("刷新 Mask 列表失败：", error);
    }
  }

  renderCurrentSliceMask();
  updateAnnotationMaskStats();
  showToast(
    deleted
      ? `已清空全部切片标注，并删除 ${deleted} 条已保存 Mask`
      : "已清空全部切片标注（已禁用自动叠加回灌）",
  );
  render();
}

function clampViewerZoom(value) {
  return clamp(Number(value) || 1, 0.25, 4);
}

function updateViewerZoomDisplay() {
  const zoomPercent = Math.round(clampViewerZoom(state.viewerZoom) * 100);
  const info = $("#viewerInfo");
  const zoomValue = $("#zoomValue");
  const slider = $("#viewerZoomSlider");
  const image = activeImage();
  if (info) info.textContent = `${image ? image.image_id : "等待图像"} | 缩放 ${zoomPercent}%`;
  if (zoomValue) zoomValue.textContent = `${zoomPercent}%`;
  if (slider && Number(slider.value) !== zoomPercent) slider.value = String(zoomPercent);
}

function resetViewerZoom({ render = true } = {}) {
  state.viewerZoom = 1;
  state.viewerPanX = 0;
  state.viewerPanY = 0;
  state.viewerPanning = false;
  state.viewerPanLast = null;
  if (render) {
    resizeAnnotationCanvas();
    updateViewerZoomDisplay();
  }
}

function setViewerZoom(nextZoom, { anchorClientX = null, anchorClientY = null } = {}) {
  const imageElement = $("#sliceImage");
  const frame = $("#sliceFrame") || imageElement?.parentElement;
  const oldZoom = clampViewerZoom(state.viewerZoom);
  const newZoom = clampViewerZoom(nextZoom);
  if (!frame || Math.abs(newZoom - oldZoom) < 1e-6) {
    state.viewerZoom = newZoom;
    updateViewerZoomDisplay();
    return;
  }

  const frameRect = frame.getBoundingClientRect();
  const anchorX = anchorClientX == null ? frameRect.left + frameRect.width / 2 : anchorClientX;
  const anchorY = anchorClientY == null ? frameRect.top + frameRect.height / 2 : anchorClientY;
  const before = getDisplayedImageRect(imageElement);
  state.viewerZoom = newZoom;
  if (before) {
    const relX = (anchorX - before.viewportLeft) / Math.max(before.width, 1);
    const relY = (anchorY - before.viewportTop) / Math.max(before.height, 1);
    const afterWidth = before.width * (newZoom / oldZoom);
    const afterHeight = before.height * (newZoom / oldZoom);
    const desiredLeft = anchorX - relX * afterWidth;
    const desiredTop = anchorY - relY * afterHeight;
    const centeredLeft = frameRect.left + (frameRect.width - afterWidth) / 2;
    const centeredTop = frameRect.top + (frameRect.height - afterHeight) / 2;
    state.viewerPanX = desiredLeft - centeredLeft;
    state.viewerPanY = desiredTop - centeredTop;
  }
  resizeAnnotationCanvas();
  updateViewerZoomDisplay();
}

function getDisplayedImageRect(imageElement) {
  const frame = imageElement?.parentElement;
  if (!imageElement || !frame || !imageElement.naturalWidth || !imageElement.naturalHeight) return null;
  const frameRect = frame.getBoundingClientRect();
  const imageRatio = imageElement.naturalWidth / imageElement.naturalHeight;
  const frameRatio = frameRect.width / Math.max(frameRect.height, 1);
  let width = frameRect.width;
  let height = frameRect.height;

  if (frameRatio > imageRatio) {
    height = frameRect.height;
    width = height * imageRatio;
  } else {
    width = frameRect.width;
    height = width / imageRatio;
  }

  const zoom = clampViewerZoom(state.viewerZoom);
  width *= zoom;
  height *= zoom;
  const left = (frameRect.width - width) / 2 + (Number(state.viewerPanX) || 0);
  const top = (frameRect.height - height) / 2 + (Number(state.viewerPanY) || 0);

  return {
    viewportLeft: frameRect.left + left,
    viewportTop: frameRect.top + top,
    frameLeft: left,
    frameTop: top,
    width,
    height,
  };
}

function resizeAnnotationCanvas({ reset = false } = {}) {
  const imageElement = $("#sliceImage");
  const canvas = $("#annotationCanvas");
  const rect = getDisplayedImageRect(imageElement);
  if (!canvas || !imageElement || !rect) return;

  if (canvas.width !== imageElement.naturalWidth || canvas.height !== imageElement.naturalHeight || reset) {
    canvas.width = imageElement.naturalWidth;
    canvas.height = imageElement.naturalHeight;
    state.annotationPolygonPoints = [];
  }

  imageElement.style.inset = "auto";
  imageElement.style.objectFit = "fill";
  imageElement.style.left = `${rect.frameLeft}px`;
  imageElement.style.top = `${rect.frameTop}px`;
  imageElement.style.width = `${rect.width}px`;
  imageElement.style.height = `${rect.height}px`;

  canvas.style.left = `${rect.frameLeft}px`;
  canvas.style.top = `${rect.frameTop}px`;
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  canvas.style.cursor = state.viewerPanning ? "grabbing" : "crosshair";
  renderCurrentSliceMask();
  updateViewerZoomDisplay();
}

function pointerToImagePoint(event) {
  const imageElement = $("#sliceImage");
  const canvas = $("#annotationCanvas");
  const rect = getDisplayedImageRect(imageElement);
  if (!imageElement || !canvas || !rect) return null;

  const insideX = event.clientX - rect.viewportLeft;
  const insideY = event.clientY - rect.viewportTop;
  if (insideX < 0 || insideY < 0 || insideX > rect.width || insideY > rect.height) return null;

  return {
    x: clamp((insideX / rect.width) * imageElement.naturalWidth, 0, imageElement.naturalWidth - 1),
    y: clamp((insideY / rect.height) * imageElement.naturalHeight, 0, imageElement.naturalHeight - 1),
  };
}

function activePaintRadius(tool = state.annotationTool) {
  const isEraser = tool === "erase";
  const input = $(isEraser ? "#eraseRadius" : "#brushRadius");
  const fromDom = input ? Number(input.value) : NaN;
  const fromState = Number(isEraser ? state.eraseRadius : state.brushRadius);
  const fallback = isEraser ? 10 : 4;
  const max = isEraser ? 60 : 40;
  const value = Number.isFinite(fromDom) ? fromDom : (Number.isFinite(fromState) ? fromState : fallback);
  return clamp(value, 1, max);
}

function setPaintRadius(kind, rawValue) {
  const isEraser = kind === "erase";
  const max = isEraser ? 60 : 40;
  const fallback = isEraser ? 10 : 4;
  const value = clamp(Number(rawValue) || fallback, 1, max);
  if (isEraser) state.eraseRadius = value;
  else state.brushRadius = value;
  try {
    localStorage.setItem(isEraser ? "label_erase_radius" : "label_brush_radius", String(value));
  } catch {
    /* ignore quota */
  }
  const input = $(isEraser ? "#eraseRadius" : "#brushRadius");
  const label = $(isEraser ? "#eraseRadiusValue" : "#brushRadiusValue");
  if (input && input.value !== String(value)) input.value = String(value);
  if (label) label.textContent = `${value}px`;
  if (state.brushCursorPoint) renderCurrentSliceMask();
}

function bindBrushSizeControlsOnce() {
  if (document.body.dataset.brushSizeBound === "1") return;
  document.body.dataset.brushSizeBound = "1";
  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.id === "brushRadius") setPaintRadius("brush", target.value);
    if (target.id === "eraseRadius") setPaintRadius("erase", target.value);
  });
  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.id === "brushRadius") setPaintRadius("brush", target.value);
    if (target.id === "eraseRadius") setPaintRadius("erase", target.value);
  });
}

function syncBrushSizeControlsFromState() {
  setPaintRadius("brush", state.brushRadius);
  setPaintRadius("erase", state.eraseRadius);
}

function annotationStrokeStyle() {
  const color = labelColor(state.annotationLabelId);
  return color;
}

function hexToRgb(hex) {
  const raw = String(hex || "#00e5b0").trim();
  const normalized = raw.startsWith("#") ? raw.slice(1) : raw;
  const expanded = normalized.length === 3
    ? normalized.split("").map((char) => char + char).join("")
    : normalized;
  if (!/^[0-9a-fA-F]{6}$/.test(expanded)) {
    return { r: 0, g: 229, b: 176 };
  }
  const value = Number.parseInt(expanded, 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

function currentSliceMask({ create = true } = {}) {
  const image = activeImage();
  const canvas = $("#annotationCanvas");
  if (!image || !canvas || !canvas.width || !canvas.height) return null;
  const imageId = image.image_id;
  const sliceKey = sliceStorageKey();
  if (!state.sliceMasks[imageId]) state.sliceMasks[imageId] = {};
  let mask = state.sliceMasks[imageId][sliceKey];
  const needsNewMask = !mask || mask.width !== canvas.width || mask.height !== canvas.height;
  if (needsNewMask && create) {
    mask = {
      width: canvas.width,
      height: canvas.height,
      data: new Uint8Array(canvas.width * canvas.height),
    };
    state.sliceMasks[imageId][sliceKey] = mask;
  }
  return mask || null;
}

function currentSlicePoints({ create = true } = {}) {
  const image = activeImage();
  if (!image) return null;
  const imageId = image.image_id;
  const sliceKey = sliceStorageKey();
  if (!state.pointAnnotations[imageId]) state.pointAnnotations[imageId] = {};
  if (!state.pointAnnotations[imageId][sliceKey] && create) {
    state.pointAnnotations[imageId][sliceKey] = [];
  }
  return state.pointAnnotations[imageId][sliceKey] || null;
}

function encodeMaskRle(data) {
  if (!data || !data.length) return [];
  const runs = [];
  let value = data[0];
  let count = 1;
  for (let index = 1; index < data.length; index += 1) {
    const next = data[index];
    if (next === value) {
      count += 1;
    } else {
      runs.push([value, count]);
      value = next;
      count = 1;
    }
  }
  runs.push([value, count]);
  return runs;
}

function decodeMaskRle(runs, width, height) {
  const data = new Uint8Array(width * height);
  let offset = 0;
  for (const run of runs || []) {
    const value = Number(run[0] || 0);
    const count = Number(run[1] || 0);
    if (count <= 0) continue;
    data.fill(value, offset, Math.min(offset + count, data.length));
    offset += count;
    if (offset >= data.length) break;
  }
  return data;
}

function decodeFloat32Base64(base64) {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Float32Array(bytes.buffer);
}

async function loadSliceValues(imageId, sliceIndex, axis = activeAxis()) {
  const key = `${imageId}:${axis}:${sliceIndex}`;
  if (!state.sliceValueCache[key]) {
    const data = await apiGet(`/api/image/${imageId}/slice/${axis}/${sliceIndex}/values`);
    state.sliceValueCache[key] = {
      width: data.width,
      height: data.height,
      values: decodeFloat32Base64(data.values_base64),
      valueMin: data.value_min,
      valueMax: data.value_max,
    };
  }
  return state.sliceValueCache[key];
}

function currentSliceMaskPayload(item, image) {
  const canvas = $("#annotationCanvas");
  if (!canvas || !canvas.width || !canvas.height) {
    throw new Error("当前切片画布尚未加载，无法保存 Mask");
  }
  const mask = currentSliceMask({ create: false });
  const points = currentSlicePoints({ create: false }) || [];
  const data = mask?.data || new Uint8Array(canvas.width * canvas.height);
  const hasMaskPixels = data.some((value) => value > 0);
  if (!hasMaskPixels && !points.length) {
    throw new Error("当前切片没有标注内容，请先画 Mask 或添加点标注");
  }
  return {
    case_id: item.case_id,
    image_id: image.image_id,
    version: "v1_manual",
    label: state.annotationLabel,
    label_id: state.annotationLabelId,
    label_type: currentLabelType(),
    mask_format: "json",
    axis: activeAxis(),
    slice_index: currentSliceIndex(),
    width: canvas.width,
    height: canvas.height,
    encoding: "rle",
    mask: encodeMaskRle(data),
    points: points.map((point) => ({ ...point })),
  };
}

function buildSliceMaskPayload(item, image, axis, sliceIndex, mask, points = []) {
  const data = mask?.data || new Uint8Array((mask?.width || 0) * (mask?.height || 0));
  const hasMaskPixels = data.some((value) => value > 0);
  if (!hasMaskPixels && !points.length) return null;
  if (!mask?.width || !mask?.height) return null;
  return {
    case_id: item.case_id,
    image_id: image.image_id,
    version: "v1_manual",
    label: state.annotationLabel,
    label_id: state.annotationLabelId,
    label_type: currentLabelType(),
    mask_format: "json",
    axis,
    slice_index: Number(sliceIndex),
    width: mask.width,
    height: mask.height,
    encoding: "rle",
    mask: encodeMaskRle(data),
    points: points.map((point) => ({ ...point })),
  };
}

async function saveAllAnnotatedMasks(item, image) {
  const imageMasks = state.sliceMasks[image.image_id] || {};
  const imagePoints = state.pointAnnotations[image.image_id] || {};
  const sliceKeys = new Set([...Object.keys(imageMasks), ...Object.keys(imagePoints)]);
  const saved = [];

  for (const sliceKey of [...sliceKeys].sort((a, b) => {
    const axisOrder = { axial: 0, coronal: 1, sagittal: 2 };
    const left = parseSliceStorageKey(a);
    const right = parseSliceStorageKey(b);
    return (axisOrder[left.axis] - axisOrder[right.axis]) || (left.sliceIndex - right.sliceIndex);
  })) {
    const parsed = parseSliceStorageKey(sliceKey);
    const payload = buildSliceMaskPayload(item, image, parsed.axis, parsed.sliceIndex, imageMasks[sliceKey], imagePoints[sliceKey] || []);
    if (!payload) continue;
    const data = await apiPost("/api/save_mask", payload);
    saved.push(data);
  }

  if (!saved.length) {
    const data = await apiPost("/api/save_mask", currentSliceMaskPayload(item, image));
    saved.push(data);
  }

  await apiPost("/api/version", {
    case_id: item.case_id,
    version: "v1_manual",
    annotation: saved[saved.length - 1].mask.annotation_id || null,
    model: null,
    dataset: null,
  });
  return saved;
}

async function restoreSavedMaskContents(imageId, masks) {
  if (state.suppressCanvasMaskRestore[imageId]) return;
  const jsonMasks = [...(masks || [])]
    .filter((mask) => mask.mask_format === "json" || String(mask.path || "").endsWith(".json"))
    .sort((a, b) => String(a.create_time || "").localeCompare(String(b.create_time || "")));

  for (const mask of jsonMasks) {
    if (state.loadedMaskContents[mask.mask_id]) continue;
    try {
      const detail = await apiGet(`/api/mask/${mask.mask_id}`);
      const content = detail.content;
      if (!content || content.encoding !== "rle") continue;
      const width = Number(content.width || 0);
      const height = Number(content.height || 0);
      const sliceIndex = Number(content.slice_index ?? 0);
      const axis = sliceAxes[content.axis] ? content.axis : "axial";
      const sliceKey = sliceStorageKey(axis, sliceIndex);
      if (!width || !height) continue;
      if (!state.sliceMasks[imageId]) state.sliceMasks[imageId] = {};
      state.sliceMasks[imageId][sliceKey] = {
        width,
        height,
        data: decodeMaskRle(content.mask, width, height),
      };
      if (Array.isArray(content.points) && content.points.length) {
        if (!state.pointAnnotations[imageId]) state.pointAnnotations[imageId] = {};
        state.pointAnnotations[imageId][sliceKey] = content.points.map((point) => ({ ...point }));
      }
      state.restoredMaskSlices[imageId] = { axis, sliceIndex };
      state.loadedMaskContents[mask.mask_id] = true;
    } catch (error) {
      console.warn(`Mask 内容加载失败：${mask.mask_id}`, error);
    }
  }
  renderCurrentSliceMask();
}

async function restorePropagatedSliceMask(imageId) {
  if (!state.autoOverlayOnCanvas || state.suppressCanvasMaskRestore[imageId]) {
    renderCurrentSliceMask();
    return;
  }
  const image = activeImage();
  const canvas = $("#annotationCanvas");
  if (!image || image.image_id !== imageId || !canvas || !canvas.width || !canvas.height) return;
  const overlayMask = latestOverlay3DMask(state.masksByImage[imageId] || []);
  if (!overlayMask) return;

  const axis = activeAxis();
  const sliceIndex = currentSliceIndex(axis);
  const sliceKey = sliceStorageKey(axis, sliceIndex);
  const loadKey = `${imageId}:${overlayMask.mask_id}:${axis}:${sliceIndex}`;
  if (state.propagatedSliceLoads[loadKey]) {
    renderCurrentSliceMask();
    return;
  }

  try {
    const data = await apiGet(`/api/mask/${overlayMask.mask_id}/slice/${axis}/${sliceIndex}`);
    if (data.width !== canvas.width || data.height !== canvas.height) {
      throw new Error(`叠加结果尺寸不匹配：${data.width}×${data.height} / ${canvas.width}×${canvas.height}`);
    }
    if (!state.sliceMasks[imageId]) state.sliceMasks[imageId] = {};
    state.sliceMasks[imageId][sliceKey] = {
      width: data.width,
      height: data.height,
      data: decodeMaskRle(data.mask, data.width, data.height),
      source: overlayMask.version === "v2_ai" ? "ai_predict" : "label_propagation",
      maskId: overlayMask.mask_id,
    };
    state.propagatedSliceLoads[loadKey] = true;
    renderCurrentSliceMask();
  } catch (error) {
    console.warn(`叠加结果切片加载失败：${overlayMask.mask_id} / ${sliceIndex}`, error);
  }
}

function currentSliceSnapshot() {
  const image = activeImage();
  const canvas = $("#annotationCanvas");
  if (!image || !canvas || !canvas.width || !canvas.height) return null;
  const mask = currentSliceMask({ create: false });
  const points = currentSlicePoints({ create: false }) || [];
  const negativePoints = state.negativeScribbles[image.image_id]?.[sliceStorageKey(activeAxis(), currentSliceIndex())] || [];
  return {
    imageId: image.image_id,
    axis: activeAxis(),
    sliceIndex: currentSliceIndex(),
    width: canvas.width,
    height: canvas.height,
    data: mask ? new Uint8Array(mask.data) : new Uint8Array(canvas.width * canvas.height),
    points: points.map((point) => ({ ...point })),
    negativePoints: negativePoints.map((point) => ({ ...point })),
  };
}

function applySliceSnapshot(snapshot) {
  if (!snapshot) return;
  const axis = sliceAxes[snapshot.axis] ? snapshot.axis : "axial";
  const sliceKey = sliceStorageKey(axis, snapshot.sliceIndex);
  if (!state.sliceMasks[snapshot.imageId]) state.sliceMasks[snapshot.imageId] = {};
  state.sliceMasks[snapshot.imageId][sliceKey] = {
    width: snapshot.width,
    height: snapshot.height,
    data: new Uint8Array(snapshot.data),
  };
  if (!state.pointAnnotations[snapshot.imageId]) state.pointAnnotations[snapshot.imageId] = {};
  state.pointAnnotations[snapshot.imageId][sliceKey] = (snapshot.points || []).map((point) => ({ ...point }));
  if (!state.negativeScribbles[snapshot.imageId]) state.negativeScribbles[snapshot.imageId] = {};
  state.negativeScribbles[snapshot.imageId][sliceKey] = (snapshot.negativePoints || []).map((point) => ({ ...point }));
  state.annotationDrawing = false;
  state.annotationLastPoint = null;
  state.annotationShapeStart = null;
  state.annotationPolygonPoints = [];
  state.annotationPolygonPreviewPoint = null;
  state.annotationPreviewRect = null;
  renderCurrentSliceMask();
}

function pushUndoSnapshot() {
  const snapshot = currentSliceSnapshot();
  if (!snapshot) return;
  state.undoStack.push(snapshot);
  if (state.undoStack.length > 50) state.undoStack.shift();
  state.redoStack = [];
}

function undoAnnotation() {
  const previous = state.undoStack.pop();
  if (!previous) {
    showToast("没有可撤销的操作");
    return;
  }
  const current = currentSliceSnapshot();
  if (current) state.redoStack.push(current);
  applySliceSnapshot(previous);
}

function redoAnnotation() {
  const next = state.redoStack.pop();
  if (!next) {
    showToast("没有可恢复的操作（请先用 ← 撤销）");
    return;
  }
  const current = currentSliceSnapshot();
  if (current) state.undoStack.push(current);
  applySliceSnapshot(next);
}

function renderCurrentSliceMask() {
  const canvas = $("#annotationCanvas");
  const context = canvas?.getContext("2d");
  if (!canvas || !context || !canvas.width || !canvas.height) return;
  const mask = currentSliceMask({ create: false });
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (!mask) {
    drawPointAnnotations(context);
    drawRectanglePreview(context);
    drawPolygonPreview(context);
    drawBrushSizeCursor(context);
    updateAnnotationMaskStats();
    return;
  }

  const imageData = context.createImageData(mask.width, mask.height);
  for (let index = 0; index < mask.data.length; index += 1) {
    const labelId = mask.data[index];
    if (!labelId) continue;
    const color = hexToRgb(labelColor(labelId));
    const offset = index * 4;
    imageData.data[offset] = color.r;
    imageData.data[offset + 1] = color.g;
    imageData.data[offset + 2] = color.b;
    // 提高不透明度，避免半透明叠在 CT 上后色相看起来和色块不一致
    imageData.data[offset + 3] = 210;
  }
  context.putImageData(imageData, 0, 0);
  drawPointAnnotations(context);
  drawRectanglePreview(context);
  drawPolygonPreview(context);
  drawBrushSizeCursor(context);
  updateAnnotationMaskStats();
}

function drawBrushSizeCursor(context) {
  if (!context || !state.brushCursorPoint) return;
  if (state.annotationTool !== "brush" && state.annotationTool !== "erase") return;
  const radius = activePaintRadius(state.annotationTool);
  context.save();
  context.strokeStyle = state.annotationTool === "erase" ? "rgba(255, 77, 79, 0.95)" : "rgba(255, 255, 255, 0.95)";
  context.fillStyle = state.annotationTool === "erase" ? "rgba(255, 77, 79, 0.12)" : "rgba(0, 229, 176, 0.12)";
  context.lineWidth = 1.5;
  context.beginPath();
  context.arc(state.brushCursorPoint.x, state.brushCursorPoint.y, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.restore();
}

function drawPointAnnotations(context) {
  const points = currentSlicePoints({ create: false }) || [];
  if (!context || !points.length) return;
  context.save();
  for (const point of points) {
    const promptType = point.promptType || "positive";
    const color = promptType === "negative" ? "#ff4d4f" : labelColor(point.labelId) || annotationStrokeStyle();
    context.strokeStyle = "rgba(255, 255, 255, 0.95)";
    context.fillStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    context.arc(point.x, point.y, 5, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.beginPath();
    context.moveTo(point.x - 9, point.y);
    context.lineTo(point.x + 9, point.y);
    if (promptType !== "negative") {
      context.moveTo(point.x, point.y - 9);
      context.lineTo(point.x, point.y + 9);
    }
    context.stroke();
  }
  context.restore();
}

function drawRectanglePreview(context) {
  const rect = state.annotationPreviewRect;
  if (!context || !rect?.from || !rect?.to) return;
  const x = Math.min(rect.from.x, rect.to.x);
  const y = Math.min(rect.from.y, rect.to.y);
  const width = Math.abs(rect.to.x - rect.from.x);
  const height = Math.abs(rect.to.y - rect.from.y);
  if (width < 1 || height < 1) return;
  context.save();
  context.strokeStyle = annotationStrokeStyle();
  context.fillStyle = "rgba(0, 229, 176, 0.12)";
  context.lineWidth = 2;
  context.setLineDash([8, 5]);
  context.fillRect(x, y, width, height);
  context.strokeRect(x, y, width, height);
  context.restore();
}

function drawPolygonPreview(context) {
  const points = state.annotationPolygonPoints;
  if (!context || !points.length) return;
  context.save();
  context.strokeStyle = annotationStrokeStyle();
  context.fillStyle = "rgba(0, 229, 176, 0.12)";
  context.lineWidth = 2;
  context.setLineDash([6, 4]);
  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) {
    context.lineTo(point.x, point.y);
  }
  if (state.annotationPolygonPreviewPoint) {
    context.lineTo(state.annotationPolygonPreviewPoint.x, state.annotationPolygonPreviewPoint.y);
  }
  if (points.length >= 3) {
    context.lineTo(points[0].x, points[0].y);
    context.fill();
  }
  context.stroke();
  context.setLineDash([]);
  for (const point of points) {
    context.beginPath();
    context.arc(point.x, point.y, 4, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
  context.restore();
}

function paintMaskCircle(point, radius, labelId) {
  const mask = currentSliceMask({ create: true });
  if (!mask || !point) return;
  const centerX = Math.round(point.x);
  const centerY = Math.round(point.y);
  const radiusSquared = radius * radius;
  const startX = clamp(centerX - radius, 0, mask.width - 1);
  const endX = clamp(centerX + radius, 0, mask.width - 1);
  const startY = clamp(centerY - radius, 0, mask.height - 1);
  const endY = clamp(centerY + radius, 0, mask.height - 1);
  const eraseOnlyCurrent = state.eraseCurrentClassOnly !== false;
  const currentClass = state.annotationLabelId;

  for (let y = startY; y <= endY; y += 1) {
    for (let x = startX; x <= endX; x += 1) {
      const dx = x - centerX;
      const dy = y - centerY;
      if (dx * dx + dy * dy <= radiusSquared) {
        const index = y * mask.width + x;
        if (labelId === 0) {
          if (!eraseOnlyCurrent || mask.data[index] === currentClass) {
            mask.data[index] = 0;
          }
        } else {
          mask.data[index] = labelId;
        }
      }
    }
  }
}

function recordSmartErasePoint(point, { asNegativePoint = true } = {}) {
  const image = activeImage();
  if (!image || !point) return;
  if (!state.negativeScribbles[image.image_id]) state.negativeScribbles[image.image_id] = {};
  const sliceKey = sliceStorageKey(activeAxis(), currentSliceIndex());
  if (!state.negativeScribbles[image.image_id][sliceKey]) {
    state.negativeScribbles[image.image_id][sliceKey] = [];
  }
  const points = state.negativeScribbles[image.image_id][sliceKey];
  const rounded = {
    x: Math.round(point.x),
    y: Math.round(point.y),
    z: currentSliceIndex(),
    axis: activeAxis(),
    asNegativePoint,
  };
  const last = points[points.length - 1];
  if (!last || Math.hypot(last.x - rounded.x, last.y - rounded.y) >= 3) {
    points.push(rounded);
    if (points.length > 1200) points.splice(0, points.length - 1200);
  }
}

function recordSmartEraseRegion(selectedIndices, width, seedPoint) {
  if (!selectedIndices?.length) return;
  const stride = Math.max(1, Math.floor(Math.sqrt(selectedIndices.length / 80)));
  recordSmartErasePoint(seedPoint, { asNegativePoint: true });
  for (let offset = 0; offset < selectedIndices.length; offset += stride) {
    const index = selectedIndices[offset];
    recordSmartErasePoint(
      { x: index % width, y: Math.floor(index / width) },
      { asNegativePoint: offset % (stride * 4) === 0 },
    );
  }

  const points = currentSlicePoints({ create: true });
  if (!points || !seedPoint) return;
  points.push({
    id: `Neg${String(points.length + 1).padStart(4, "0")}`,
    x: Math.round(seedPoint.x),
    y: Math.round(seedPoint.y),
    axis: activeAxis(),
    sliceIndex: currentSliceIndex(),
    promptType: "negative",
    labelId: 0,
    label: "negative",
  });
}

function paintMaskLine(from, to, tool = state.annotationTool) {
  if (!from || !to) return;
  const isEraser = tool === "erase";
  const radius = activePaintRadius(tool);
  const labelId = isEraser ? 0 : state.annotationLabelId;
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius * 0.6)));
  for (let step = 0; step <= steps; step += 1) {
    const ratio = step / steps;
    const point = {
      x: from.x + (to.x - from.x) * ratio,
      y: from.y + (to.y - from.y) * ratio,
    };
    paintMaskCircle(point, radius, labelId);
  }
  renderCurrentSliceMask();
}

function drawAnnotationLine(from, to, tool = state.annotationTool) {
  paintMaskLine(from, to, tool);
}

function drawAnnotationPoint(point) {
  const points = currentSlicePoints({ create: true });
  if (!points || !point) return;
  points.push({
    id: `Point${String(points.length + 1).padStart(4, "0")}`,
    x: Math.round(point.x),
    y: Math.round(point.y),
    axis: activeAxis(),
    sliceIndex: currentSliceIndex(),
    promptType: "positive",
    labelId: state.annotationLabelId,
    label: state.annotationLabel,
  });
  renderCurrentSliceMask();
}

function drawAnnotationRectangle(from, to) {
  const mask = currentSliceMask({ create: true });
  if (!mask || !from || !to) return;
  const x = Math.min(from.x, to.x);
  const y = Math.min(from.y, to.y);
  const width = Math.abs(to.x - from.x);
  const height = Math.abs(to.y - from.y);
  if (width < 2 || height < 2) return;
  const startX = clamp(Math.round(x), 0, mask.width - 1);
  const endX = clamp(Math.round(x + width), 0, mask.width - 1);
  const startY = clamp(Math.round(y), 0, mask.height - 1);
  const endY = clamp(Math.round(y + height), 0, mask.height - 1);
  for (let row = startY; row <= endY; row += 1) {
    for (let col = startX; col <= endX; col += 1) {
      mask.data[row * mask.width + col] = state.annotationLabelId;
    }
  }
  renderCurrentSliceMask();
}

function floodFillRegion({
  width,
  height,
  startX,
  startY,
  maxPixels,
  acceptIndex,
}) {
  const seedIndex = startY * width + startX;
  if (!acceptIndex(seedIndex)) return [];
  const visited = new Uint8Array(width * height);
  const queue = new Int32Array(width * height);
  const selected = [];
  let head = 0;
  let tail = 0;
  queue[tail] = seedIndex;
  tail += 1;
  visited[seedIndex] = 1;

  while (head < tail) {
    const index = queue[head];
    head += 1;
    if (!acceptIndex(index)) continue;
    selected.push(index);
    if (selected.length >= maxPixels) break;

    const x = index % width;
    const y = Math.floor(index / width);
    const neighbors = [
      x > 0 ? index - 1 : -1,
      x < width - 1 ? index + 1 : -1,
      y > 0 ? index - width : -1,
      y < height - 1 ? index + width : -1,
    ];
    for (const next of neighbors) {
      if (next >= 0 && !visited[next]) {
        visited[next] = 1;
        queue[tail] = next;
        tail += 1;
      }
    }
  }
  return selected;
}

async function runMagicWandSelection(point) {
  const image = activeImage();
  if (!image || !point) return;
  const mask = currentSliceMask({ create: true });
  if (!mask) return;

  try {
    const slice = await loadSliceValues(image.image_id, currentSliceIndex(), activeAxis());
    if (slice.width !== mask.width || slice.height !== mask.height) {
      throw new Error(`智能选择尺寸不匹配：切片 ${slice.width}×${slice.height}，画布 ${mask.width}×${mask.height}`);
    }

    const width = slice.width;
    const height = slice.height;
    const startX = clamp(Math.round(point.x), 0, width - 1);
    const startY = clamp(Math.round(point.y), 0, height - 1);
    const seedIndex = startY * width + startX;
    const seedValue = slice.values[seedIndex];
    const threshold = state.magicWandThreshold;
    const selected = floodFillRegion({
      width,
      height,
      startX,
      startY,
      maxPixels: state.magicWandMaxPixels,
      acceptIndex: (index) => Math.abs(slice.values[index] - seedValue) <= threshold,
    });

    if (!selected.length) {
      showToast("智能选择没有找到相近区域");
      return;
    }

    pushUndoSnapshot();
    for (const index of selected) {
      mask.data[index] = state.annotationLabelId;
    }
    renderCurrentSliceMask();
    showToast(`智能选择完成：${selected.length} 像素，HU ${Math.round(seedValue)} ± ${threshold}`);
  } catch (error) {
    showToast(error.message || "智能选择失败");
  }
}

async function runSmartEraseSelection(point) {
  const image = activeImage();
  if (!image || !point) return;
  const mask = currentSliceMask({ create: true });
  if (!mask) return;

  try {
    const width = mask.width;
    const height = mask.height;
    const startX = clamp(Math.round(point.x), 0, width - 1);
    const startY = clamp(Math.round(point.y), 0, height - 1);
    const seedIndex = startY * width + startX;
    const seedLabel = mask.data[seedIndex];
    const threshold = state.magicWandThreshold;
    let selected = [];
    let mode = "hu";

    // Prefer erasing the connected annotated blob under the cursor.
    if (seedLabel > 0) {
      selected = floodFillRegion({
        width,
        height,
        startX,
        startY,
        maxPixels: state.magicWandMaxPixels,
        acceptIndex: (index) => mask.data[index] === seedLabel,
      });
      mode = "mask";
    }

    // Otherwise grow a HU-similar region and clear any mask inside it.
    if (!selected.length) {
      const slice = await loadSliceValues(image.image_id, currentSliceIndex(), activeAxis());
      if (slice.width !== width || slice.height !== height) {
        throw new Error(`智能橡皮擦尺寸不匹配：切片 ${slice.width}×${slice.height}，画布 ${width}×${height}`);
      }
      const seedValue = slice.values[seedIndex];
      selected = floodFillRegion({
        width,
        height,
        startX,
        startY,
        maxPixels: state.magicWandMaxPixels,
        acceptIndex: (index) => Math.abs(slice.values[index] - seedValue) <= threshold,
      });
      mode = "hu";
    }

    if (!selected.length) {
      showToast("智能橡皮擦没有识别到可擦除区域");
      return;
    }

    pushUndoSnapshot();
    let erased = 0;
    for (const index of selected) {
      if (mask.data[index]) {
        mask.data[index] = 0;
        erased += 1;
      }
    }
    recordSmartEraseRegion(selected, width, { x: startX, y: startY });
    renderCurrentSliceMask();
    updatePromptCountDisplay();
    const modeText = mode === "mask" ? "连通标注区域" : `HU ± ${threshold}`;
    showToast(`智能擦除完成：识别 ${selected.length} 像素，清除 ${erased} 标注，已记为 DeepEdit 负点（${modeText}）`);
  } catch (error) {
    showToast(error.message || "智能橡皮擦失败");
  }
}

function fillPolygonToMask(points) {
  const mask = currentSliceMask({ create: true });
  if (!mask || !points || points.length < 3) return false;
  const rasterCanvas = document.createElement("canvas");
  rasterCanvas.width = mask.width;
  rasterCanvas.height = mask.height;
  const rasterContext = rasterCanvas.getContext("2d");
  if (!rasterContext) return false;

  rasterContext.fillStyle = "#ffffff";
  rasterContext.beginPath();
  rasterContext.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) {
    rasterContext.lineTo(point.x, point.y);
  }
  rasterContext.closePath();
  rasterContext.fill();

  const { data } = rasterContext.getImageData(0, 0, mask.width, mask.height);
  let filled = 0;
  for (let index = 0; index < mask.data.length; index += 1) {
    if (data[index * 4 + 3] > 0) {
      mask.data[index] = state.annotationLabelId;
      filled += 1;
    }
  }
  renderCurrentSliceMask();
  return filled > 0;
}

function isNearPoint(point, target, threshold = 10) {
  if (!point || !target) return false;
  return Math.hypot(point.x - target.x, point.y - target.y) <= threshold;
}

function closePolygonAnnotation() {
  if (state.annotationTool !== "polygon" || state.annotationPolygonPoints.length < 3) return false;
  const didFill = fillPolygonToMask(state.annotationPolygonPoints);
  state.annotationPolygonPoints = [];
  state.annotationPolygonPreviewPoint = null;
  state.annotationIgnoreNextClickUntil = Date.now() + 250;
  if (!didFill) renderCurrentSliceMask();
  return didFill;
}

function updateAnnotationCoordinate(point) {
  const coordinate = $("#sliceCoordinate");
  const image = activeImage();
  const axis = activeAxis();
  const sliceNumber = currentSliceIndex(axis) + 1;
  if (!coordinate || !point) return;
  coordinate.textContent = `x: ${Math.round(point.x)}  y: ${Math.round(point.y)}  ${axisCoordinateName(axis)}: ${sliceNumber} | ${axisLabel(axis)} | ${image?.image_id || "-"}`;
}

function handleAnnotationPointerDown(event) {
  resizeAnnotationCanvas();
  const isPan =
    event.button === 1 ||
    event.altKey ||
    (event.button === 0 && event.shiftKey && !state.annotationDrawing);
  if (isPan) {
    event.preventDefault();
    state.viewerPanning = true;
    state.viewerPanLast = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    resizeAnnotationCanvas();
    return;
  }
  if (state.annotationTool === "polygon" && Date.now() < state.annotationIgnoreNextClickUntil) {
    event.preventDefault();
    return;
  }
  const point = pointerToImagePoint(event);
  if (!point) return;
  event.preventDefault();
  event.currentTarget.setPointerCapture?.(event.pointerId);
  updateAnnotationCoordinate(point);

  if (state.annotationTool === "point") {
    pushUndoSnapshot();
    drawAnnotationPoint(point);
    return;
  }
  if (state.annotationTool === "magic") {
    runMagicWandSelection(point);
    return;
  }
  if (state.annotationTool === "smartErase") {
    runSmartEraseSelection(point);
    return;
  }
  if (state.annotationTool === "polygon") {
    if (!state.annotationPolygonPoints.length) pushUndoSnapshot();
    if (state.annotationPolygonPoints.length >= 3 && isNearPoint(point, state.annotationPolygonPoints[0])) {
      closePolygonAnnotation();
      return;
    }
    state.annotationPolygonPoints.push(point);
    state.annotationPolygonPreviewPoint = null;
    renderCurrentSliceMask();
    return;
  }
  if (state.annotationTool === "rectangle") {
    pushUndoSnapshot();
    state.annotationDrawing = true;
    state.annotationShapeStart = point;
    state.annotationPreviewRect = { from: point, to: point };
    renderCurrentSliceMask();
    return;
  }
  if (state.annotationTool === "brush" || state.annotationTool === "erase") {
    pushUndoSnapshot();
    state.annotationDrawing = true;
    state.annotationLastPoint = point;
    drawAnnotationLine(point, point);
  }
}

function handleAnnotationPointerMove(event) {
  if (state.viewerPanning && state.viewerPanLast) {
    event.preventDefault();
    const dx = event.clientX - state.viewerPanLast.x;
    const dy = event.clientY - state.viewerPanLast.y;
    state.viewerPanLast = { x: event.clientX, y: event.clientY };
    state.viewerPanX += dx;
    state.viewerPanY += dy;
    resizeAnnotationCanvas();
    return;
  }
  const point = pointerToImagePoint(event);
  if (point) updateAnnotationCoordinate(point);
  if ((state.annotationTool === "brush" || state.annotationTool === "erase") && point) {
    state.brushCursorPoint = point;
    if (!state.annotationDrawing) {
      renderCurrentSliceMask();
    }
  }
  if (state.annotationTool === "polygon" && state.annotationPolygonPoints.length && point) {
    state.annotationPolygonPreviewPoint = point;
    renderCurrentSliceMask();
    return;
  }
  if (!state.annotationDrawing || !point) return;
  event.preventDefault();
  if (state.annotationTool === "brush" || state.annotationTool === "erase") {
    drawAnnotationLine(state.annotationLastPoint, point);
    state.annotationLastPoint = point;
    return;
  }
  if (state.annotationTool === "rectangle") {
    state.annotationPreviewRect = { from: state.annotationShapeStart, to: point };
    renderCurrentSliceMask();
    return;
  }
}

function finishAnnotationPointer(event) {
  if (state.viewerPanning) {
    state.viewerPanning = false;
    state.viewerPanLast = null;
    resizeAnnotationCanvas();
    return;
  }
  const point = pointerToImagePoint(event);
  if (state.annotationDrawing && state.annotationTool === "rectangle" && point) {
    state.annotationPreviewRect = null;
    drawAnnotationRectangle(state.annotationShapeStart, point);
  } else if (state.annotationTool === "rectangle" && state.annotationPreviewRect) {
    state.annotationPreviewRect = null;
    renderCurrentSliceMask();
  }
  state.annotationDrawing = false;
  state.annotationLastPoint = null;
  state.annotationShapeStart = null;
}

function finishAnnotationPolygon(event) {
  event.preventDefault();
  closePolygonAnnotation();
}

function bindAnnotationCanvas() {
  const canvas = $("#annotationCanvas");
  const frame = $("#sliceFrame");
  if (!canvas) return;
  resizeAnnotationCanvas();
  canvas.addEventListener("pointerdown", handleAnnotationPointerDown);
  canvas.addEventListener("pointermove", handleAnnotationPointerMove);
  canvas.addEventListener("pointerup", finishAnnotationPointer);
  canvas.addEventListener("pointercancel", finishAnnotationPointer);
  canvas.addEventListener("pointerleave", finishAnnotationPointer);
  canvas.addEventListener("dblclick", finishAnnotationPolygon);

  if (frame && !frame.dataset.zoomBound) {
    frame.dataset.zoomBound = "1";
    frame.addEventListener(
      "wheel",
      (event) => {
        if (state.volumeViewMode !== "2d") return;
        event.preventDefault();
        const factor = event.deltaY > 0 ? 0.9 : 1.1;
        setViewerZoom(clampViewerZoom(state.viewerZoom) * factor, {
          anchorClientX: event.clientX,
          anchorClientY: event.clientY,
        });
      },
      { passive: false },
    );
    frame.addEventListener("auxclick", (event) => {
      if (event.button === 1) event.preventDefault();
    });

    const startPan = (event) => {
      const isPan =
        event.button === 1 ||
        event.altKey ||
        (event.button === 0 && event.shiftKey && !state.annotationDrawing);
      if (!isPan) return false;
      event.preventDefault();
      state.viewerPanning = true;
      state.viewerPanLast = { x: event.clientX, y: event.clientY };
      frame.setPointerCapture?.(event.pointerId);
      resizeAnnotationCanvas();
      return true;
    };

    frame.addEventListener("pointerdown", (event) => {
      startPan(event);
    });
    frame.addEventListener("pointermove", (event) => {
      if (!state.viewerPanning || !state.viewerPanLast) return;
      const dx = event.clientX - state.viewerPanLast.x;
      const dy = event.clientY - state.viewerPanLast.y;
      state.viewerPanLast = { x: event.clientX, y: event.clientY };
      state.viewerPanX += dx;
      state.viewerPanY += dy;
      resizeAnnotationCanvas();
    });
    const endPan = (event) => {
      if (!state.viewerPanning) return;
      state.viewerPanning = false;
      state.viewerPanLast = null;
      try {
        frame.releasePointerCapture?.(event.pointerId);
      } catch (_error) {
        // ignore
      }
      resizeAnnotationCanvas();
    };
    frame.addEventListener("pointerup", endPan);
    frame.addEventListener("pointercancel", endPan);
  }
}

async function hydrateVersions() {
  if (state._hydratingVersions) return;
  state._hydratingVersions = true;
  try {
    const firstQueueLoad = !state._reviewQueueHydrated;
    await loadReviewQueue({ force: firstQueueLoad });
    state._reviewQueueHydrated = true;
    const item = activeCase();
    if (!item) {
      if (firstQueueLoad) render();
      return;
    }
    const needsMasks = !niftiMasksForCase(item.case_id).length;
    const needsVersions = !state.versionsByCase[item.case_id];
    await loadCaseDetail(item.case_id);
    if (needsVersions) await loadCaseVersions(item.case_id, { force: true });
    if (needsMasks) await ensureCaseMasksLoaded(item.case_id);
    const masks = niftiMasksForCase(item.case_id);
    let changed = false;
    if (!state.versionCompareA && masks[0]) {
      state.versionCompareA = masks[0].mask_id;
      changed = true;
    }
    if (!state.versionCompareB && (masks[1] || masks[0])) {
      state.versionCompareB = (masks[1] || masks[0]).mask_id;
      changed = true;
    }
    if (firstQueueLoad || needsMasks || needsVersions || changed) render();
  } catch (error) {
    showToast(error.message || "版本记录加载失败");
  } finally {
    state._hydratingVersions = false;
  }
}

function renderTrain() {
  const job = state.trainJob;
  const exportId = state.datasetExportResult?.dataset_id || "";
  const history = Array.isArray(job?.metrics?.history) ? job.metrics.history : [];
  const chart = history.length
    ? history.map((row) => {
        const dice = Math.max(0, Math.min(1, Number(row.val_dice) || 0));
        return `<div class="bar" style="height:${Math.round(dice * 100)}%" title="E${row.epoch}"></div>`;
      }).join("")
    : `<div class="placeholder compact">训练开始后显示 Val Dice</div>`;
  const logs = (job?.logs || []).slice(-40).join("\n") || "等待开始训练…\n先在 Dataset 导出页 materialize，再填写 dataset_id。";
  const status = job?.status || "idle";
  return `
    <div class="grid cols-2">
      <section class="panel">
        <h2>训练配置</h2>
        <p class="panel-lead">基于导出的 nnUNet 目录训练平台 <strong>2.5D U-Net</strong>（邻层上下文 + 按类采样 + 推理 3D 后处理）。正式高精度分割请优先用 TotalSeg / nnUNet。</p>
        <div class="toolbar-row inference-toolbar" style="margin-top:14px; flex-wrap:wrap; gap:10px">
          <div class="field"><label>Dataset ID</label><input id="trainDatasetId" value="${escapeHtml(exportId)}" placeholder="Dataset0001" /></div>
          <div class="field"><label>Model ID</label><input id="trainModelId" value="${escapeHtml(job?.model_id || "")}" placeholder="自动生成" /></div>
          <div class="field"><label>Epochs</label><input id="trainEpochs" type="number" min="1" max="200" value="20" /></div>
          <div class="field"><label>Batch</label><input id="trainBatch" type="number" min="1" max="32" value="4" /></div>
          <div class="field"><label>LR</label><input id="trainLr" type="number" step="0.0001" value="0.0001" /></div>
          <div class="field"><label>Classes</label><input id="trainClasses" type="number" min="2" max="32" value="6" /></div>
          <div class="field"><label>Image size</label><input id="trainImageSize" type="number" min="64" max="512" value="320" /></div>
          <div class="field"><label>2.5D radius</label><input id="trainContextRadius" type="number" min="0" max="3" value="1" title="1=三通道(z-1,z,z+1)" /></div>
        </div>
        <div class="toolbar-row" style="margin-top:18px">
          <button class="primary-button" data-start-train ${status === "running" || status === "queued" ? "disabled" : ""}>开始训练</button>
          <button class="ghost-button" data-refresh-train>刷新状态</button>
          <strong style="margin-left:12px">状态：${escapeHtml(status)}</strong>
        </div>
        ${job?.registered_model_id ? `<p style="margin-top:12px;color:var(--green)">已注册模型：${escapeHtml(job.registered_model_id)}，可去推理中心选用。</p>` : ""}
      </section>
      <section class="panel">
        <h2>Val Dice</h2>
        <div class="line-chart">${chart}</div>
        <div class="case-meta" style="margin-top:12px">
          <div class="meta-line"><span>epoch</span><strong>${job?.current_epoch ?? "-"}</strong></div>
          <div class="meta-line"><span>train_loss</span><strong>${job?.train_loss != null ? Number(job.train_loss).toFixed(4) : "-"}</strong></div>
          <div class="meta-line"><span>val_dice</span><strong>${job?.val_dice != null ? Number(job.val_dice).toFixed(4) : "-"}</strong></div>
        </div>
      </section>
    </div>
    <section class="panel" style="margin-top:18px">
      <h2>训练日志</h2>
      <div class="log-box" id="trainLogBox">${escapeHtml(logs)}</div>
    </section>
  `;
}

async function startPlatformTrain(event) {
  const button = event.currentTarget;
  const datasetId = $("#trainDatasetId")?.value?.trim();
  if (!datasetId) {
    showToast("请填写已导出的 Dataset ID");
    return;
  }
  button.disabled = true;
  try {
    const data = await apiPost("/api/train", {
      dataset_id: datasetId,
      model_id: $("#trainModelId")?.value?.trim() || null,
      epochs: Number($("#trainEpochs")?.value || 20),
      batch_size: Number($("#trainBatch")?.value || 4),
      lr: Number($("#trainLr")?.value || 0.0001),
      num_classes: Number($("#trainClasses")?.value || 6),
      image_size: Number($("#trainImageSize")?.value || 320),
      context_radius: Number($("#trainContextRadius")?.value || 1),
    }, { timeoutMs: 60 * 1000 });
    state.trainJob = data.job;
    showToast(`训练任务已启动：${data.job.job_id}`);
    startTrainPolling(data.job.job_id);
    render();
  } catch (error) {
    showToast(error.message || "启动训练失败");
  } finally {
    button.disabled = false;
  }
}

async function refreshTrainJob(jobId) {
  const id = jobId || state.trainJob?.job_id;
  if (!id) {
    const list = await apiGet("/api/train");
    state.trainJobs = list.items || [];
    if (state.trainJobs[0]) state.trainJob = state.trainJobs[0];
    return state.trainJob;
  }
  const data = await apiGet(`/api/train/${id}`);
  state.trainJob = data.job;
  return data.job;
}

function startTrainPolling(jobId) {
  if (state.trainPollTimer) {
    clearInterval(state.trainPollTimer);
    state.trainPollTimer = null;
  }
  state.trainPollTimer = setInterval(async () => {
    try {
      const job = await refreshTrainJob(jobId);
      if (state.view === "train" || state.view === "dashboard") render();
      if (job && (job.status === "completed" || job.status === "failed")) {
        clearInterval(state.trainPollTimer);
        state.trainPollTimer = null;
        if (job.status === "completed") {
          await loadModels();
          showToast(`训练完成并已注册：${job.registered_model_id || job.model_id}`);
        }
      }
    } catch (_error) {
      // keep polling until user leaves
    }
  }, 2500);
}

async function hydrateTrain() {
  try {
    await refreshTrainJob();
    if (state.trainJob && (state.trainJob.status === "running" || state.trainJob.status === "queued")) {
      startTrainPolling(state.trainJob.job_id);
    }
  } catch (_error) {
    // ignore
  }
}

function renderInference() {
  const item = activeCase();
  const image = activeImage();
  const models = state.models || [];
  const modelOptions = models.length
    ? models.map((model) => `
        <option value="${escapeHtml(model.model_id)}" ${state.selectedModelId === model.model_id ? "selected" : ""}>
          ${escapeHtml(model.display_name || model.model_id)}${model.external_ready ? " · 外部权重就绪" : ""}
        </option>
      `).join("")
    : `<option value="">加载中 / 暂无模型</option>`;
  const caseOptions = state.cases.map((caseItem) => `
    <option value="${escapeHtml(caseItem.case_id)}" ${item?.case_id === caseItem.case_id ? "selected" : ""}>
      ${escapeHtml(caseItem.case_id)} · ${escapeHtml(statusText[caseItem.status] || caseItem.status)}
    </option>
  `).join("");
  const preview = state.inferencePreview;
  const previewMaskId = preview?.mask_id || latestMaskByVersion(masksForActiveImage(), "v2_ai")?.mask_id || "";
  const previewImageId = preview?.image_id || image?.image_id || "";
  const sliceIndex = currentSliceIndex("axial");
  const selected = selectedModel();
  return `
    <section class="panel">
      <h2>AI 推理中心</h2>
      <p class="panel-lead">选择病例与模型后运行 predict，结果写入 <code>v2_ai</code>，可在此预览并跳转标注台修正。</p>
      <div class="toolbar-row inference-toolbar">
        <div class="field"><label>病例</label><select id="inferenceCaseSelect">${caseOptions || "<option value=''>暂无病例</option>"}</select></div>
        <div class="field"><label>模型</label><select id="inferenceModelSelect">${modelOptions}</select></div>
        <button class="primary-button" data-ai-predict ${item && image ? "" : "disabled"}>开始推理</button>
        <button class="ghost-button" data-load-v2-ai ${previewMaskId || latestMaskByVersion(masksForActiveImage(), "v2_ai") ? "" : "disabled"}>预览并加载到 2D</button>
        <button class="ghost-button" data-open-annotation-from-inference ${item ? "" : "disabled"}>打开标注台</button>
      </div>
      <div class="case-meta" style="margin-top:14px">
        <div class="meta-line"><span>model_id</span><strong>${selected ? escapeHtml(selected.model_id) : "-"}</strong></div>
        <div class="meta-line"><span>label</span><strong>${selected ? escapeHtml(selected.label) : "-"}</strong></div>
        <div class="meta-line"><span>backend</span><strong>${selected ? escapeHtml(selected.backend) : "-"}</strong></div>
        <div class="meta-line"><span>说明</span><strong>${selected ? escapeHtml(selected.description || "-") : "-"}</strong></div>
      </div>
    </section>
    <div class="grid cols-3" style="margin-top:18px">
      <section class="viewer">
        <h2>原始图像</h2>
        <div class="ct-frame inference-frame">
          ${previewImageId ? `<img src="${apiUrl(`/api/image/${previewImageId}/slice/axial/${sliceIndex}.png?window=auto`)}" alt="原始切片" />` : `<div class="slice-empty">选择病例后显示</div>`}
        </div>
      </section>
      <section class="viewer">
        <h2>AI Mask (v2_ai)</h2>
        <div class="ct-frame inference-frame">
          ${previewMaskId ? `<img src="${apiUrl(`/api/mask/${previewMaskId}/slice/axial/${sliceIndex}`).replace('/slice/', '/slice/')}" alt="AI mask 占位" class="hidden" /><div class="mask-overlay inference-mask" data-inference-mask="${escapeHtml(previewMaskId)}" data-inference-slice="${sliceIndex}"></div><canvas id="inferenceMaskCanvas" class="inference-mask-canvas"></canvas>` : `<div class="slice-empty">推理后显示 v2_ai</div>`}
        </div>
      </section>
      <section class="viewer">
        <h2>叠加预览</h2>
        <div class="ct-frame inference-frame">
          ${previewImageId ? `<img src="${apiUrl(`/api/image/${previewImageId}/slice/axial/${sliceIndex}.png?window=auto`)}" alt="叠加底图" /><canvas id="inferenceOverlayCanvas" class="inference-mask-canvas"></canvas>` : `<div class="slice-empty">等待推理</div>`}
        </div>
      </section>
    </div>
    <section class="panel" style="margin-top:18px">
      <h2>最近推理结果</h2>
      ${preview ? `
        <div class="case-meta">
          <div class="meta-line"><span>病例</span><strong>${escapeHtml(preview.case_id)}</strong></div>
          <div class="meta-line"><span>图像</span><strong>${escapeHtml(preview.image_id)}</strong></div>
          <div class="meta-line"><span>Mask</span><strong>${escapeHtml(preview.mask_id)}</strong></div>
          <div class="meta-line"><span>模型</span><strong>${escapeHtml(preview.model_id)}</strong></div>
          <div class="meta-line"><span>版本</span><strong>${escapeHtml(preview.version)}</strong></div>
        </div>
      ` : `<div class="placeholder compact">尚未推理。未配置真实模型权重时预测会失败（不再静默使用 HU baseline）；可配置 TotalSeg / nnUNet / 平台 U-Net。</div>`}
    </section>
  `;
}

async function hydrateInference() {
  const hadModels = state.models.length > 0;
  await loadModels();
  const item = activeCase();
  if (item) {
    await loadCaseDetail(item.case_id);
    const image = activeImage();
    if (image) {
      await loadImageMasks(image.image_id);
      await loadVolumeMeta(image.image_id).catch(() => null);
      const aiMask = latestMaskByVersion(state.masksByImage[image.image_id] || [], "v2_ai");
      if (aiMask && !state.inferencePreview) {
        state.inferencePreview = {
          case_id: item.case_id,
          image_id: image.image_id,
          mask_id: aiMask.mask_id,
          model_id: selectedModel()?.model_id || "",
          version: "v2_ai",
        };
      }
    }
  }
  if (!hadModels && state.models.length) {
    render();
    return;
  }
  await paintInferencePreview();
}

async function paintInferencePreview() {
  const preview = state.inferencePreview;
  const image = activeImage();
  const maskId = preview?.mask_id || latestMaskByVersion(masksForActiveImage(), "v2_ai")?.mask_id;
  const imageId = preview?.image_id || image?.image_id;
  if (!maskId || !imageId) return;
  const sliceIndex = currentSliceIndex("axial");
  try {
    const data = await apiGet(`/api/mask/${maskId}/slice/axial/${sliceIndex}`);
    const maskCanvas = $("#inferenceMaskCanvas");
    const overlayCanvas = $("#inferenceOverlayCanvas");
    const paint = (canvas, withImage) => {
      if (!canvas) return;
      canvas.width = data.width;
      canvas.height = data.height;
      const ctx = canvas.getContext("2d");
      const imageData = ctx.createImageData(data.width, data.height);
      const decoded = decodeMaskRle(data.mask, data.width, data.height);
      for (let i = 0; i < decoded.length; i += 1) {
        const offset = i * 4;
        if (decoded[i] > 0) {
          imageData.data[offset] = 0;
          imageData.data[offset + 1] = 229;
          imageData.data[offset + 2] = 176;
          imageData.data[offset + 3] = withImage ? 140 : 220;
        }
      }
      ctx.putImageData(imageData, 0, 0);
    };
    paint(maskCanvas, false);
    paint(overlayCanvas, true);
  } catch (error) {
    console.warn("推理预览绘制失败：", error);
  }
}

function renderVersions() {
  const item = activeCase();
  const versions = versionsForActiveCase();
  const queue = state.reviewQueue || [];
  const masks = item ? niftiMasksForCase(item.case_id) : [];
  const maskOptionHtml = (selectedId) => masks.length
    ? masks.map((mask) => `<option value="${escapeHtml(mask.mask_id)}" ${selectedId === mask.mask_id ? "selected" : ""}>${escapeHtml(mask.mask_id)} · ${escapeHtml(mask.version)} · ${escapeHtml(mask.label)}</option>`).join("")
    : `<option value="">暂无 3D Mask</option>`;
  const diff = state.versionDiff;
  const caseOptions = state.cases.map((caseItem) => `
    <option value="${escapeHtml(caseItem.case_id)}" ${item?.case_id === caseItem.case_id ? "selected" : ""}>
      ${escapeHtml(caseItem.case_id)} · ${escapeHtml(statusText[caseItem.status] || caseItem.status)}
    </option>
  `).join("");

  return `
    <section class="panel">
      <h2>审核队列（pending）</h2>
      <p class="panel-lead">审核员无需打开标注台即可通过/驳回。通过将自动 promote 最新 v3_preview/v3_fusion → final。</p>
      ${canReview() ? `
        <section class="table-wrap" style="margin-top:12px">
          <table>
            <thead><tr><th>病例</th><th>患者</th><th>可 promote</th><th>Mask 数</th><th>操作</th></tr></thead>
            <tbody>
              ${queue.length ? queue.map((entry) => `
                <tr>
                  <td>${escapeHtml(entry.case_id)}</td>
                  <td>${escapeHtml(entry.patient_id)}</td>
                  <td>${entry.promotable_mask_id ? `${escapeHtml(entry.promotable_version)} / ${escapeHtml(entry.promotable_mask_id)}` : "<span class='muted'>无</span>"}</td>
                  <td>${escapeHtml(entry.mask_count)}</td>
                  <td class="review-actions">
                    <button class="ghost-button" data-focus-case="${escapeHtml(entry.case_id)}">查看版本</button>
                    <button class="primary-button" data-queue-approve="${escapeHtml(entry.case_id)}" ${entry.promotable_mask_id ? "" : "disabled"}>通过→final</button>
                    <button class="danger-button" data-queue-reject="${escapeHtml(entry.case_id)}">驳回</button>
                  </td>
                </tr>
              `).join("") : `<tr><td colspan="5">当前没有 pending 病例</td></tr>`}
            </tbody>
          </table>
        </section>
      ` : `<div class="placeholder compact">请使用 reviewer / admin 账号查看审核队列。</div>`}
    </section>

    <section class="panel" style="margin-top:18px">
      <h2>版本管理</h2>
      <div class="toolbar-row" style="margin-top:12px">
        <div class="field"><label>病例</label><select id="versionCaseSelect">${caseOptions || "<option value=''>暂无病例</option>"}</select></div>
        <button class="ghost-button" data-submit-case ${item && (currentRole() === "annotator" || currentRole() === "admin") ? "" : "disabled"}>提交审核</button>
        <button class="primary-button" data-approve-case ${item && canReview() ? "" : "disabled"}>审核通过→final</button>
        <button class="danger-button" data-reject-case ${item && canReview() ? "" : "disabled"}>驳回</button>
      </div>
      <div class="timeline" style="margin-top:14px">${["v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"].map((version) => `<span class="chip ${versions.some((entry) => entry.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
      ${item?.reject_note ? `<div class="reject-note-box" style="margin-top:12px"><span>最近驳回意见</span><strong>${escapeHtml(item.reject_note)}</strong></div>` : ""}
      ${renderVersionList(versions)}
    </section>

    <section class="panel" style="margin-top:18px">
      <h2>版本 Diff / 回滚</h2>
      <div class="toolbar-row" style="margin-top:12px">
        <div class="field"><label>Mask A</label><select id="versionCompareA">${maskOptionHtml(state.versionCompareA)}</select></div>
        <div class="field"><label>Mask B</label><select id="versionCompareB">${maskOptionHtml(state.versionCompareB)}</select></div>
        <button class="primary-button" data-run-version-diff ${masks.length ? "" : "disabled"}>计算 Diff</button>
      </div>
      <div class="grid cols-4" style="margin-top:14px">
        ${metricCard("Dice", diff ? Number(diff.dice).toFixed(4) : "-", diff ? `${diff.pred_version} vs ${diff.ref_version}` : "GET /api/mask/{a}/compare/{b}")}
        ${metricCard("IoU", diff ? Number(diff.iou).toFixed(4) : "-", "重叠")}
        ${metricCard("体积差 ml", diff ? Number(diff.volume_diff_ml).toFixed(3) : "-", "A − B")}
        ${metricCard("HD95 mm", diff?.hd95_mm != null ? Number(diff.hd95_mm).toFixed(3) : "-", "表面距离")}
      </div>
      <section class="table-wrap" style="margin-top:14px">
        <table>
          <thead><tr><th>Mask</th><th>版本</th><th>标签</th><th>路径</th><th>操作</th></tr></thead>
          <tbody>
            ${masks.length ? masks.map((mask) => `
              <tr>
                <td>${escapeHtml(mask.mask_id)}</td>
                <td>${escapeHtml(mask.version)}</td>
                <td>${escapeHtml(mask.label)}</td>
                <td><code>${escapeHtml(mask.path)}</code></td>
                <td><button class="ghost-button" data-rollback-mask="${escapeHtml(mask.mask_id)}">回滚为 v3_preview</button></td>
              </tr>
            `).join("") : `<tr><td colspan="5">当前病例暂无 3D NIfTI Mask</td></tr>`}
          </tbody>
        </table>
      </section>
    </section>

    <div class="grid cols-4" style="margin-top:18px">
      ${metricCard("当前状态", item ? (statusText[item.status] || item.status) : "-", "病例状态机")}
      ${metricCard("角色", state.currentUser ? (roleText[state.currentUser.role] || state.currentUser.role) : "未登录", "决定审核权限")}
      ${metricCard("待审数", queue.length, "pending 队列")}
      ${metricCard("版本数", versions.length, "已写入版本")}
    </div>
  `;
}

function renderQuality() {
  const caseId = state.qualityCaseId || activeCase()?.case_id || "";
  const masks = state.qualityMasks.length ? state.qualityMasks : (caseId ? niftiMasksForCase(caseId) : []);
  const report = state.qualityReport;
  const geometric = report?.geometric;
  const overlap = report?.overlap;
  const errorSlices = report?.error_slices || [];
  const caseOptions = state.cases.map((caseItem) => `
    <option value="${escapeHtml(caseItem.case_id)}" ${caseId === caseItem.case_id ? "selected" : ""}>
      ${escapeHtml(caseItem.case_id)} · ${escapeHtml(statusText[caseItem.status] || caseItem.status)}
    </option>
  `).join("");
  const maskOptions = masks.length
    ? masks.map((mask) => `
        <option value="${escapeHtml(mask.mask_id)}" ${state.qualityMaskId === mask.mask_id ? "selected" : ""}>
          ${escapeHtml(mask.version)} · ${escapeHtml(mask.mask_id)} · ${escapeHtml(mask.label)}
        </option>
      `).join("")
    : `<option value="">暂无 3D Mask</option>`;
  const refOptions = [`<option value="">无 GT（仅几何质量）</option>`].concat(
    masks.filter((mask) => mask.mask_id !== state.qualityMaskId).map((mask) => `
      <option value="${escapeHtml(mask.mask_id)}" ${state.qualityRefMaskId === mask.mask_id ? "selected" : ""}>
        ${escapeHtml(mask.version)} · ${escapeHtml(mask.mask_id)}
      </option>
    `)
  ).join("");

  return `
    <section class="panel">
      <h2>质量报告</h2>
      <p class="panel-lead">无 GT 时展示体积/连通域；有 GT 时请求 <code>/api/mask/{id}/metrics?ref=...</code> 返回 Dice / IoU / HD95 与错误切片。</p>
      <div class="toolbar-row" style="margin-top:12px">
        <div class="field"><label>病例</label><select id="qualityCaseSelect">${caseOptions || "<option value=''>暂无病例</option>"}</select></div>
        <div class="field"><label>评价 Mask</label><select id="qualityMaskSelect">${maskOptions}</select></div>
        <div class="field"><label>参考 GT</label><select id="qualityRefSelect">${refOptions}</select></div>
        <button class="primary-button" data-load-quality ${masks.length ? "" : "disabled"}>拉取指标</button>
      </div>
    </section>

    <div class="grid cols-4" style="margin-top:18px">
      ${metricCard("Dice", overlap ? Number(overlap.dice).toFixed(4) : "-", overlap ? "相对 GT" : "需选择 ref")}
      ${metricCard("IoU", overlap ? Number(overlap.iou).toFixed(4) : "-", "重叠")}
      ${metricCard("HD95 mm", overlap?.hd95_mm != null ? Number(overlap.hd95_mm).toFixed(3) : "-", "有 GT")}
      ${metricCard("体积 ml", geometric ? Number(geometric.volume_ml).toFixed(3) : "-", "几何质量")}
    </div>

    <div class="grid cols-2" style="margin-top:18px">
      <section class="panel">
        <h2>几何质量（无 GT 也可用）</h2>
        ${geometric ? `
          <div class="case-meta">
            <div class="meta-line"><span>体素数</span><strong>${formatInteger(geometric.voxel_count)}</strong></div>
            <div class="meta-line"><span>体积 ml</span><strong>${formatNumber(geometric.volume_ml, 3)}</strong></div>
            <div class="meta-line"><span>连通域</span><strong>${formatInteger(geometric.connected_component_count)}</strong></div>
            <div class="meta-line"><span>最大连通域占比</span><strong>${formatPercent(geometric.largest_component_ratio)}</strong></div>
            <div class="meta-line"><span>切片范围</span><strong>${formatSliceRange(geometric.slice_range)}</strong></div>
          </div>
        ` : `<div class="placeholder compact">选择 Mask 后点击「拉取指标」。</div>`}
      </section>
      <section class="panel">
        <h2>重叠指标（有 GT）</h2>
        ${overlap ? `
          <div class="case-meta">
            <div class="meta-line"><span>Precision</span><strong>${Number(overlap.precision).toFixed(4)}</strong></div>
            <div class="meta-line"><span>Recall</span><strong>${Number(overlap.recall).toFixed(4)}</strong></div>
            <div class="meta-line"><span>体积差 ml</span><strong>${Number(overlap.volume_diff_ml).toFixed(3)}</strong></div>
            <div class="meta-line"><span>Pred / Ref</span><strong>${escapeHtml(report.mask_id)} / ${escapeHtml(report.ref_mask_id || "-")}</strong></div>
          </div>
        ` : `<div class="placeholder compact">未选择参考 GT 时仅显示几何质量。</div>`}
      </section>
    </div>

    <section class="panel" style="margin-top:18px">
      <h2>错误切片列表（可选）</h2>
      <section class="table-wrap" style="margin-top:12px">
        <table>
          <thead><tr><th>平面</th><th>切片</th><th>错误体素</th><th>Pred</th><th>Ref</th></tr></thead>
          <tbody>
            ${errorSlices.length ? errorSlices.map((slice) => `
              <tr>
                <td>${escapeHtml(slice.axis)}</td>
                <td>${Number(slice.slice_index) + 1}</td>
                <td>${formatInteger(slice.error_voxels)}</td>
                <td>${formatInteger(slice.pred_voxels)}</td>
                <td>${formatInteger(slice.ref_voxels)}</td>
              </tr>
            `).join("") : `<tr><td colspan="5">${overlap ? "无显著差异切片" : "选择 GT 后可列出错误切片"}</td></tr>`}
          </tbody>
        </table>
      </section>
    </section>
  `;
}

async function hydrateQuality() {
  if (state._hydratingQuality) return;
  state._hydratingQuality = true;
  try {
    const caseId = state.qualityCaseId || activeCase()?.case_id || state.cases[0]?.case_id || "";
    if (!caseId) return;
    const needsCaseSwitch = state.qualityCaseId !== caseId || !state.qualityMasks.length;
    state.qualityCaseId = caseId;
    state.activeCaseId = caseId;
    await loadCaseDetail(caseId);
    if (needsCaseSwitch) {
      state.qualityMasks = await ensureCaseMasksLoaded(caseId);
      if (!state.qualityMaskId || !state.qualityMasks.some((mask) => mask.mask_id === state.qualityMaskId)) {
        state.qualityMaskId = state.qualityMasks[0]?.mask_id || "";
      }
      state.qualityReport = null;
      render();
      return;
    }
    if (!state.qualityReport && state.qualityMaskId) {
      await loadQualityReport();
    }
  } catch (error) {
    showToast(error.message || "质量页加载失败");
  } finally {
    state._hydratingQuality = false;
  }
}

function renderExport() {
  ensureExportAssignments();
  const result = state.datasetExportResult;
  const report = result?.report;
  const version = result?.version || (state.exportLabelSet === "weak" ? "v3_preview" : "final");
  const assignmentRows = state.cases.map((item) => {
    const split = state.exportAssignments[item.case_id] || "none";
    return `
      <tr>
        <td>${escapeHtml(item.case_id)}</td>
        <td>${escapeHtml(item.patient_id)}</td>
        <td>${escapeHtml(statusText[item.status] || item.status)}</td>
        <td>${escapeHtml(item.mask_count)}</td>
        <td>
          <select data-export-split="${escapeHtml(item.case_id)}">
            <option value="none" ${split === "none" ? "selected" : ""}>不导出</option>
            <option value="train" ${split === "train" ? "selected" : ""}>train</option>
            <option value="val" ${split === "val" ? "selected" : ""}>val</option>
            <option value="test" ${split === "test" ? "selected" : ""}>test</option>
          </select>
        </td>
      </tr>
    `;
  }).join("");
  const selectedCounts = Object.values(state.exportAssignments || {}).reduce((acc, split) => {
    if (split === "train" || split === "val" || split === "test") acc[split] += 1;
    return acc;
  }, { train: 0, val: 0, test: 0 });

  return `
    <section class="panel">
      <h2>训练数据集导出</h2>
      <p class="panel-lead">勾选 materialize 后会写入 <code>dataset/exports/DatasetXXXX/{imagesTr,labelsTr,dataset.json,splits_final.json}</code>。可分别导出<strong>弱标签</strong>（v3_preview 伪标）与<strong>精标</strong>（final）两套 split。</p>
      <div class="toolbar-row" style="margin-top:12px">
        <div class="field"><label>Dataset ID</label><input id="exportDatasetId" placeholder="自动生成 Dataset0001" /></div>
        <div class="field"><label>名称</label><input id="exportDatasetName" placeholder="medical_segmentation_dataset" /></div>
        <div class="field"><label>标签集</label>
          <select id="exportLabelSet">
            <option value="dense" ${state.exportLabelSet === "dense" ? "selected" : ""}>精标 dense (final)</option>
            <option value="weak" ${state.exportLabelSet === "weak" ? "selected" : ""}>弱标签 weak (v3_preview)</option>
          </select>
        </div>
        <div class="field"><label>版本</label>
          <select id="exportVersion">
            <option value="final">final</option>
            <option value="v3_fusion">v3_fusion</option>
            <option value="v3_preview">v3_preview</option>
            <option value="v2_ai">v2_ai</option>
          </select>
        </div>
        <div class="field"><label>格式</label><select id="exportFormat"><option value="nnunet">nnUNet</option><option value="json">JSON Manifest</option></select></div>
      </div>
      <div class="toolbar-row" style="margin-top:10px">
        <label class="checkbox-row"><input id="exportMaterialize" type="checkbox" ${state.exportMaterialize ? "checked" : ""} /> materialize 真导出（拷贝/转换 NIfTI）</label>
        <label class="checkbox-row"><input id="exportStrict" type="checkbox" ${state.exportStrict ? "checked" : ""} /> 严格校验（缺 mask 则失败）</label>
        <button class="ghost-button" data-export-assign-all-train>全部设为 train</button>
        <button class="ghost-button" data-export-clear-splits>清空划分</button>
        <button class="primary-button" data-export-dataset ${state.cases.length ? "" : "disabled"}>导出 Dataset</button>
      </div>
      <div class="grid cols-3" style="margin-top:14px">
        ${metricCard("Train", selectedCounts.train, "训练病例")}
        ${metricCard("Val", selectedCounts.val, "验证病例")}
        ${metricCard("Test", selectedCounts.test, "测试病例")}
      </div>
    </section>

    <section class="table-wrap" style="margin-top:18px">
      <table>
        <thead><tr><th>病例</th><th>患者</th><th>状态</th><th>Mask 数</th><th>划分</th></tr></thead>
        <tbody>
          ${assignmentRows || `<tr><td colspan="5">暂无病例</td></tr>`}
        </tbody>
      </table>
    </section>

    <section class="panel" style="margin-top:18px">
      <h2>导出报告</h2>
      ${result ? `
        <div class="case-meta">
          <div class="meta-line"><span>Dataset</span><strong>${escapeHtml(result.dataset_id || "-")}</strong></div>
          <div class="meta-line"><span>标签集</span><strong>${escapeHtml(result.label_set || state.exportLabelSet || "dense")}</strong></div>
          <div class="meta-line"><span>版本</span><strong>${escapeHtml(result.version || version)}</strong></div>
          <div class="meta-line"><span>Manifest</span><strong>${escapeHtml(result.output_path || "-")}</strong></div>
          <div class="meta-line"><span>Export Dir</span><strong>${escapeHtml(result.export_dir || "-")}</strong></div>
          <div class="meta-line"><span>dataset.json</span><strong>${escapeHtml(result.dataset_json_path || "-")}</strong></div>
          <div class="meta-line"><span>splits_final.json</span><strong>${escapeHtml(result.splits_final_path || "-")}</strong></div>
          <div class="meta-line"><span>说明</span><strong>${escapeHtml(result.message || "")}</strong></div>
        </div>
        <div class="grid cols-4" style="margin-top:14px">
          ${metricCard("成功", report ? report.success_count : "-", "物化成功对数")}
          ${metricCard("跳过", report ? report.skipped_count : "-", "缺文件/失败")}
          ${metricCard("缺 Mask", report?.missing_masks?.length ?? "-", "校验结果")}
          ${metricCard("Spacing 异常", report?.spacing_checks?.filter((item) => item.status !== "ok").length ?? "-", "形状/间距")}
        </div>
        <section class="table-wrap" style="margin-top:14px">
          <h3 style="margin:0 0 8px">缺 Mask 列表</h3>
          <table>
            <thead><tr><th>病例</th><th>图像</th><th>版本</th><th>原因</th></tr></thead>
            <tbody>
              ${(report?.missing_masks || []).length ? report.missing_masks.map((item) => `
                <tr>
                  <td>${escapeHtml(item.case_id)}</td>
                  <td>${escapeHtml(item.image_id || "-")}</td>
                  <td>${escapeHtml(item.version || version)}</td>
                  <td>${escapeHtml(item.reason)}</td>
                </tr>
              `).join("") : `<tr><td colspan="4">无</td></tr>`}
            </tbody>
          </table>
        </section>
        <section class="table-wrap" style="margin-top:14px">
          <h3 style="margin:0 0 8px">Spacing 检查</h3>
          <table>
            <thead><tr><th>病例</th><th>图像</th><th>Mask</th><th>状态</th><th>详情</th></tr></thead>
            <tbody>
              ${(report?.spacing_checks || []).length ? report.spacing_checks.map((item) => `
                <tr>
                  <td>${escapeHtml(item.case_id)}</td>
                  <td>${escapeHtml(item.image_id)}</td>
                  <td>${escapeHtml(item.mask_id)}</td>
                  <td>${escapeHtml(item.status)}</td>
                  <td>${escapeHtml(item.detail || "-")}</td>
                </tr>
              `).join("") : `<tr><td colspan="5">尚未物化或无检查项</td></tr>`}
            </tbody>
          </table>
        </section>
      ` : `<div class="placeholder compact">尚未导出。请为病例指定 train/val/test，并确保目标版本有 3D NIfTI Mask。</div>`}
    </section>
  `;
}

function renderSettings() {
  const catalog = effectiveLabelCatalog({ includeBackground: true, enabledOnly: false });
  const labelRows = catalog.length
    ? catalog.map((item) => {
      const disabled = item.enabled === false;
      const isBg = Number(item.label_id) === 0;
      return `
        <tr class="${disabled ? "row-disabled" : ""}">
          <td><span class="swatch" style="background:${escapeHtml(item.color)}"></span> ${item.label_id}</td>
          <td>${escapeHtml(item.name)}</td>
          <td>${escapeHtml(item.display_name || item.name)}</td>
          <td>${disabled ? "已禁用" : "启用"}</td>
          <td class="settings-actions">
            ${canManageLabels() && !isBg ? `
              <button type="button" class="ghost-button" data-edit-label="${item.label_id}">编辑</button>
              <button type="button" class="ghost-button" data-toggle-label="${item.label_id}" data-enabled="${disabled ? "1" : "0"}">${disabled ? "启用" : "禁用"}</button>
              <button type="button" class="danger-button" data-delete-label="${item.label_id}">删除</button>
            ` : (isBg ? `<span class="muted">系统保留</span>` : `<span class="muted">只读</span>`)}
          </td>
        </tr>
      `;
    }).join("")
    : `<tr><td colspan="5"><div class="placeholder">暂无标签</div></td></tr>`;

  const userRows = (state.users || []).length
    ? state.users.map((user) => `
      <tr>
        <td>${user.id}</td>
        <td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(roleText[user.role] || user.role)}</td>
        <td>${escapeHtml(user.create_time || "-")}</td>
        <td class="settings-actions">
          ${canManageUsers() ? `
            <button type="button" class="ghost-button" data-edit-user="${user.id}">改角色</button>
            <button type="button" class="ghost-button" data-reset-password="${user.id}">重置密码</button>
            <button type="button" class="danger-button" data-delete-user="${user.id}">删除</button>
          ` : `<span class="muted">只读</span>`}
        </td>
      </tr>
    `).join("")
    : `<tr><td colspan="5"><div class="placeholder">${state.currentUser ? (canManageTasks() ? "暂无用户" : "需要审核员/管理员权限查看用户列表") : "请先登录"}</div></td></tr>`;

  return `
    <div class="grid cols-2 settings-grid">
      <section class="panel">
        <h2>标签管理</h2>
        <p class="panel-lead">标签目录供标注台、金标准导入与导出共用。禁用后不再出现在标注选择器中。</p>
        ${canManageLabels() ? `
          <form id="labelCreateForm" class="toolbar-row settings-form">
            <label class="field"><span>ID（可选）</span><input name="label_id" type="number" min="1" placeholder="自动分配" /></label>
            <label class="field"><span>英文名 name</span><input name="name" required placeholder="pancreas" /></label>
            <label class="field"><span>显示名</span><input name="display_name" placeholder="胰腺" /></label>
            <label class="field"><span>颜色</span><input name="color" type="color" value="#7dd3fc" /></label>
            <button type="submit" class="primary-button">新增标签</button>
          </form>
        ` : `<p class="panel-lead">当前角色仅可查看；管理员可增删改。</p>`}
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>name</th><th>显示名</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>${labelRows}</tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <h2>用户管理</h2>
        <div class="case-meta" style="margin-bottom:14px">
          <div class="meta-line"><span>当前用户</span><strong>${state.currentUser ? escapeHtml(state.currentUser.username) : "未登录"}</strong></div>
          <div class="meta-line"><span>角色</span><strong>${state.currentUser ? escapeHtml(roleText[state.currentUser.role] || state.currentUser.role) : "-"}</strong></div>
          <div class="meta-line"><span>状态机</span><strong>unannotated → annotated → pending → reviewed → final</strong></div>
        </div>
        ${canManageUsers() ? `
          <form id="userCreateForm" class="toolbar-row settings-form">
            <label class="field"><span>用户名</span><input name="username" required minlength="2" placeholder="new_user" /></label>
            <label class="field"><span>密码</span><input name="password" type="password" required minlength="6" placeholder="至少6位" /></label>
            <label class="field"><span>角色</span>
              <select name="role">
                <option value="annotator">标注员</option>
                <option value="reviewer">审核员</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <button type="submit" class="primary-button">创建用户</button>
          </form>
        ` : `<p class="panel-lead">${canManageTasks() ? "审核员可查看用户列表；仅管理员可创建/改密/删除。" : "登录后由管理员维护账号。"}</p>`}
        <div class="table-wrap">
          <table>
            <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>${userRows}</tbody>
          </table>
        </div>
      </section>
    </div>
  `;
}

async function handleLabelCreate(event) {
  event.preventDefault();
  if (!canManageLabels()) return;
  const form = event.currentTarget;
  const fd = new FormData(form);
  const payload = {
    name: String(fd.get("name") || "").trim(),
    display_name: String(fd.get("display_name") || "").trim() || undefined,
    color: String(fd.get("color") || "#00e5b0"),
  };
  const labelIdRaw = String(fd.get("label_id") || "").trim();
  if (labelIdRaw) payload.label_id = Number(labelIdRaw);
  try {
    await apiPost("/api/labels", payload);
    form.reset();
    await refreshLabels();
    render();
    showToast("标签已创建");
  } catch (error) {
    showToast(error.message || "创建标签失败");
  }
}

async function handleLabelEdit(labelId) {
  if (!canManageLabels()) return;
  const item = labelById(labelId);
  if (!item) return;
  const displayName = window.prompt("显示名", item.display_name || item.name);
  if (displayName === null) return;
  const name = window.prompt("英文名 name", item.name);
  if (name === null) return;
  const color = window.prompt("颜色 (#RRGGBB)", item.color || "#00e5b0");
  if (color === null) return;
  try {
    await apiPut(`/api/labels/${labelId}`, {
      display_name: displayName.trim(),
      name: name.trim(),
      color: color.trim(),
    });
    await refreshLabels();
    render();
    showToast("标签已更新");
  } catch (error) {
    showToast(error.message || "更新标签失败");
  }
}

async function handleLabelToggle(labelId, enabled) {
  if (!canManageLabels()) return;
  try {
    await apiPut(`/api/labels/${labelId}`, { enabled: Boolean(enabled) });
    await refreshLabels();
    render();
    showToast(enabled ? "标签已启用" : "标签已禁用");
  } catch (error) {
    showToast(error.message || "更新失败");
  }
}

async function handleLabelDelete(labelId) {
  if (!canManageLabels()) return;
  if (!window.confirm(`禁用并移除标签 #${labelId}？现有 mask 中的像素值不会自动改写。`)) return;
  try {
    await apiDelete(`/api/labels/${labelId}`);
    await refreshLabels();
    render();
    showToast("标签已删除（软删除）");
  } catch (error) {
    showToast(error.message || "删除失败");
  }
}

async function handleUserCreate(event) {
  event.preventDefault();
  if (!canManageUsers()) return;
  const form = event.currentTarget;
  const fd = new FormData(form);
  try {
    await apiPost("/api/users", {
      username: String(fd.get("username") || "").trim(),
      password: String(fd.get("password") || ""),
      role: String(fd.get("role") || "annotator"),
    });
    form.reset();
    await refreshUsersList();
    render();
    showToast("用户已创建");
  } catch (error) {
    showToast(error.message || "创建用户失败");
  }
}

async function handleUserEditRole(userId) {
  if (!canManageUsers()) return;
  const user = (state.users || []).find((item) => Number(item.id) === Number(userId));
  if (!user) return;
  const role = window.prompt("角色：annotator / reviewer / admin", user.role);
  if (role === null) return;
  try {
    await apiPut(`/api/users/${userId}`, { role: role.trim() });
    await refreshUsersList();
    render();
    showToast("角色已更新");
  } catch (error) {
    showToast(error.message || "更新失败");
  }
}

async function handleUserResetPassword(userId) {
  if (!canManageUsers()) return;
  const password = window.prompt("输入新密码（至少 6 位）");
  if (password === null) return;
  try {
    await apiPost(`/api/users/${userId}/password`, { password });
    showToast("密码已重置");
  } catch (error) {
    showToast(error.message || "重置失败");
  }
}

async function handleUserDelete(userId) {
  if (!canManageUsers()) return;
  const user = (state.users || []).find((item) => Number(item.id) === Number(userId));
  if (!window.confirm(`确认删除用户 ${user?.username || userId}？`)) return;
  try {
    await apiDelete(`/api/users/${userId}`);
    await refreshUsersList();
    render();
    showToast("用户已删除");
  } catch (error) {
    showToast(error.message || "删除失败");
  }
}

function bindSettingsActions() {
  const labelForm = $("#labelCreateForm");
  if (labelForm) labelForm.addEventListener("submit", handleLabelCreate);
  const userForm = $("#userCreateForm");
  if (userForm) userForm.addEventListener("submit", handleUserCreate);
  document.querySelectorAll("[data-edit-label]").forEach((button) => {
    button.addEventListener("click", () => handleLabelEdit(button.dataset.editLabel));
  });
  document.querySelectorAll("[data-toggle-label]").forEach((button) => {
    button.addEventListener("click", () => {
      handleLabelToggle(button.dataset.toggleLabel, button.dataset.enabled === "1");
    });
  });
  document.querySelectorAll("[data-delete-label]").forEach((button) => {
    button.addEventListener("click", () => handleLabelDelete(button.dataset.deleteLabel));
  });
  document.querySelectorAll("[data-edit-user]").forEach((button) => {
    button.addEventListener("click", () => handleUserEditRole(button.dataset.editUser));
  });
  document.querySelectorAll("[data-reset-password]").forEach((button) => {
    button.addEventListener("click", () => handleUserResetPassword(button.dataset.resetPassword));
  });
  document.querySelectorAll("[data-delete-user]").forEach((button) => {
    button.addEventListener("click", () => handleUserDelete(button.dataset.deleteUser));
  });
}

function render() {
  const views = { dashboard: renderDashboard, cases: renderCases, annotation: renderAnnotation, train: renderTrain, inference: renderInference, versions: renderVersions, quality: renderQuality, export: renderExport, settings: renderSettings };
  $("#viewRoot").innerHTML = (views[state.view] || renderDashboard)();
  const uploadForm = $("#uploadForm");
  if (uploadForm) uploadForm.addEventListener("submit", uploadCase);
  bindUploadDropzone();
  const taskForm = $("#taskForm");
  if (taskForm) taskForm.addEventListener("submit", createTaskAssignment);
  const loginForm = $("#loginForm");
  if (loginForm) loginForm.addEventListener("submit", handleLogin);
  bindSettingsActions();
  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.volumeViewMode = button.dataset.viewMode;
      if (state.volumeViewMode === "3d") state.showMip = false;
      render();
    });
  });
  const loadMipButton = $("[data-load-mip]");
  if (loadMipButton) {
    loadMipButton.addEventListener("click", () => {
      state.showMip = true;
      render();
    });
  }
  document.querySelectorAll("[data-annotation-tool]").forEach((button) => {
    button.addEventListener("click", () => setAnnotationTool(button.dataset.annotationTool));
  });
  document.querySelectorAll("[data-annotation-mode]").forEach((button) => {
    button.addEventListener("click", () => setAnnotationMode(button.dataset.annotationMode));
  });
  const fewShotMinInput = $("#fewShotMinSlices");
  if (fewShotMinInput) {
    fewShotMinInput.addEventListener("change", () => {
      state.fewShotMinSlices = Math.max(1, Math.min(20, Number(fewShotMinInput.value) || 3));
      refreshLabelingAssist({ silent: true }).then(() => render());
    });
  }
  const fewShotPropagate = $("[data-few-shot-propagate]");
  if (fewShotPropagate) fewShotPropagate.addEventListener("click", runFewShotPropagate);
  const refreshAssist = $("[data-refresh-labeling-assist]");
  if (refreshAssist) {
    refreshAssist.addEventListener("click", async () => {
      await refreshLabelingAssist();
      render();
    });
  }
  document.querySelectorAll("[data-jump-slice]").forEach((button) => {
    button.addEventListener("click", () => jumpToRecommendedSlice(Number(button.dataset.jumpSlice)));
  });
  bindMagicWandControls();
  bindRefineParamControls();
  bindAnnotationCanvas();
  document.querySelectorAll("[data-pick-label]").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveAnnotationLabel(button.dataset.pickLabel);
      render();
    });
  });
  const annotationLabelSelect = $("#annotationLabelSelect");
  if (annotationLabelSelect) {
    annotationLabelSelect.addEventListener("change", () => {
      setActiveAnnotationLabel(annotationLabelSelect.value);
      render();
    });
  }
  syncBrushSizeControlsFromState();
  const eraseCurrentClassOnly = $("#eraseCurrentClassOnly");
  if (eraseCurrentClassOnly) {
    eraseCurrentClassOnly.addEventListener("change", () => {
      state.eraseCurrentClassOnly = eraseCurrentClassOnly.checked;
    });
  }
  const saveMaskButton = $("[data-save-mask]");
  if (saveMaskButton) {
    saveMaskButton.addEventListener("click", saveCurrentMask);
  }
  const submitCaseButton = $("[data-submit-case]");
  if (submitCaseButton) {
    submitCaseButton.addEventListener("click", submitCaseForReview);
  }
  const approveCaseButton = $("[data-approve-case]");
  if (approveCaseButton) {
    approveCaseButton.addEventListener("click", approveCaseReview);
  }
  const rejectCaseButton = $("[data-reject-case]");
  if (rejectCaseButton) {
    rejectCaseButton.addEventListener("click", rejectCaseReview);
  }
  document.querySelectorAll("[data-queue-approve]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeCaseId = button.dataset.queueApprove;
      await approveCaseReview({ currentTarget: button });
    });
  });
  document.querySelectorAll("[data-queue-reject]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeCaseId = button.dataset.queueReject;
      await rejectCaseReview({ currentTarget: button });
    });
  });
  document.querySelectorAll("[data-focus-case]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.activeCaseId = button.dataset.focusCase;
      state.activeImageId = null;
      state.versionDiff = null;
      delete state.caseDetails[state.activeCaseId];
      await loadCaseDetail(state.activeCaseId);
      render();
    });
  });
  const versionCaseSelect = $("#versionCaseSelect");
  if (versionCaseSelect) {
    versionCaseSelect.addEventListener("change", async () => {
      state.activeCaseId = versionCaseSelect.value || null;
      state.activeImageId = null;
      state.versionDiff = null;
      state.versionCompareA = "";
      state.versionCompareB = "";
      if (state.activeCaseId) delete state.caseDetails[state.activeCaseId];
      render();
    });
  }
  const versionCompareA = $("#versionCompareA");
  if (versionCompareA) {
    versionCompareA.addEventListener("change", () => {
      state.versionCompareA = versionCompareA.value;
    });
  }
  const versionCompareB = $("#versionCompareB");
  if (versionCompareB) {
    versionCompareB.addEventListener("change", () => {
      state.versionCompareB = versionCompareB.value;
    });
  }
  const runVersionDiffButton = $("[data-run-version-diff]");
  if (runVersionDiffButton) {
    runVersionDiffButton.addEventListener("click", runVersionDiff);
  }
  document.querySelectorAll("[data-rollback-mask]").forEach((button) => {
    button.addEventListener("click", () => rollbackMaskVersion(button.dataset.rollbackMask));
  });
  const qualityCaseSelect = $("#qualityCaseSelect");
  if (qualityCaseSelect) {
    qualityCaseSelect.addEventListener("change", async () => {
      state.qualityCaseId = qualityCaseSelect.value || "";
      state.activeCaseId = state.qualityCaseId;
      state.qualityMaskId = "";
      state.qualityRefMaskId = "";
      state.qualityReport = null;
      state.qualityMasks = [];
      render();
    });
  }
  const qualityMaskSelect = $("#qualityMaskSelect");
  if (qualityMaskSelect) {
    qualityMaskSelect.addEventListener("change", () => {
      state.qualityMaskId = qualityMaskSelect.value;
      state.qualityReport = null;
    });
  }
  const qualityRefSelect = $("#qualityRefSelect");
  if (qualityRefSelect) {
    qualityRefSelect.addEventListener("change", () => {
      state.qualityRefMaskId = qualityRefSelect.value;
      state.qualityReport = null;
    });
  }
  const loadQualityButton = $("[data-load-quality]");
  if (loadQualityButton) {
    loadQualityButton.addEventListener("click", loadQualityReport);
  }
  const finalMaskButton = $("[data-final-mask]");
  if (finalMaskButton) {
    finalMaskButton.addEventListener("click", approveFinalMask);
  }
  const fusionMaskButton = $("[data-confirm-fusion]");
  if (fusionMaskButton) {
    fusionMaskButton.addEventListener("click", approveFusionMask);
  }
  const aiPredictTarget = $("#aiPredictTarget");
  if (aiPredictTarget) {
    aiPredictTarget.addEventListener("change", () => {
      state.aiPredictTarget = aiPredictTarget.value || "all";
      try {
        localStorage.setItem("label_ai_predict_target", state.aiPredictTarget);
      } catch {
        /* ignore */
      }
    });
  }
  document.querySelectorAll("[data-ai-predict]").forEach((button) => {
    button.addEventListener("click", runAIPredict);
  });
  const loadV2AiButton = $("[data-load-v2-ai]");
  if (loadV2AiButton) {
    loadV2AiButton.addEventListener("click", loadV2AiTo2D);
  }
  const compareMasksButton = $("[data-compare-masks]");
  if (compareMasksButton) {
    compareMasksButton.addEventListener("click", compareActiveMasks);
  }
  const openAnnotationFromInference = $("[data-open-annotation-from-inference]");
  if (openAnnotationFromInference) {
    openAnnotationFromInference.addEventListener("click", () => setView("annotation"));
  }
  const inferenceCaseSelect = $("#inferenceCaseSelect");
  if (inferenceCaseSelect) {
    inferenceCaseSelect.addEventListener("change", async () => {
      state.activeCaseId = inferenceCaseSelect.value || null;
      state.activeImageId = null;
      state.inferencePreview = null;
      delete state.caseDetails[state.activeCaseId];
      await loadCaseDetail(state.activeCaseId);
      render();
    });
  }
  const inferenceModelSelect = $("#inferenceModelSelect");
  if (inferenceModelSelect) {
    inferenceModelSelect.addEventListener("change", () => {
      state.selectedModelId = inferenceModelSelect.value;
      const model = selectedModel();
      if (model?.label) state.annotationLabel = model.label;
      render();
    });
  }
  const active3DMaskSelect = $("#active3DMaskSelect");
  if (active3DMaskSelect) {
    active3DMaskSelect.addEventListener("change", () => {
      state.active3DMaskId = active3DMaskSelect.value || null;
      state.volumeLoadingKey = null;
      state.propagatedSliceLoads = {};
      allowCanvasMaskRestore();
      render();
    });
  }
  document.querySelectorAll("[data-jump-2d-axis]").forEach((button) => {
    button.addEventListener("click", () => {
      const axis = sliceAxes[button.dataset.jump2dAxis] ? button.dataset.jump2dAxis : "axial";
      const sliceIndex = Number(button.dataset.jump2dSlice || 0);
      state.activeAxis = axis;
      setCurrentSliceIndex(sliceIndex, axis);
      state.volumeViewMode = "2d";
      state.propagatedSliceLoads = {};
      render();
    });
  });
  const bindMprSlider = (id, axis) => {
    const slider = $(id);
    if (!slider) return;
    const refresh = () => {
      setCurrentSliceIndex(Number(slider.value), axis);
      render();
    };
    slider.addEventListener("change", refresh);
  };
  bindMprSlider("#mprAxialSlider", "axial");
  bindMprSlider("#mprCoronalSlider", "coronal");
  bindMprSlider("#mprSagittalSlider", "sagittal");
  const exportMaskNiftiButton = $("[data-export-mask-nifti]");
  if (exportMaskNiftiButton) {
    exportMaskNiftiButton.addEventListener("click", exportMaskNifti);
  }
  const smart3DRefineButton = $("[data-smart-3d-refine]");
  if (smart3DRefineButton) {
    smart3DRefineButton.addEventListener("click", runSmart3DRefine);
  }
  const graphCutRefineButton = $("[data-graph-cut-refine]");
  if (graphCutRefineButton) {
    graphCutRefineButton.addEventListener("click", runGraphCutRefine);
  }
  const startTrainButton = $("[data-start-train]");
  if (startTrainButton) {
    startTrainButton.addEventListener("click", startPlatformTrain);
  }
  const refreshTrainButton = $("[data-refresh-train]");
  if (refreshTrainButton) {
    refreshTrainButton.addEventListener("click", async () => {
      try {
        await refreshTrainJob();
        render();
      } catch (error) {
        showToast(error.message || "刷新训练状态失败");
      }
    });
  }
  const renderAnnotation3DButton = $("[data-render-annotation-3d]");
  if (renderAnnotation3DButton) {
    renderAnnotation3DButton.addEventListener("click", renderAnnotationMaskIn3D);
  }
  const start3DRenderButton = $("[data-start-3d-render]");
  if (start3DRenderButton) {
    start3DRenderButton.addEventListener("click", start3DImageRender);
  }
  const exportDatasetButton = $("[data-export-dataset]");
  if (exportDatasetButton) {
    exportDatasetButton.addEventListener("click", exportDataset);
  }
  document.querySelectorAll("[data-export-split]").forEach((select) => {
    select.addEventListener("change", () => {
      if (!state.exportAssignments) state.exportAssignments = {};
      state.exportAssignments[select.dataset.exportSplit] = select.value;
    });
  });
  const assignAllTrain = $("[data-export-assign-all-train]");
  if (assignAllTrain) {
    assignAllTrain.addEventListener("click", () => {
      ensureExportAssignments();
      for (const item of state.cases) state.exportAssignments[item.case_id] = "train";
      render();
    });
  }
  const clearSplits = $("[data-export-clear-splits]");
  if (clearSplits) {
    clearSplits.addEventListener("click", () => {
      ensureExportAssignments();
      for (const item of state.cases) state.exportAssignments[item.case_id] = "none";
      render();
    });
  }
  const materializeBox = $("#exportMaterialize");
  if (materializeBox) {
    materializeBox.addEventListener("change", () => {
      state.exportMaterialize = materializeBox.checked;
    });
  }
  const strictBox = $("#exportStrict");
  if (strictBox) {
    strictBox.addEventListener("change", () => {
      state.exportStrict = strictBox.checked;
    });
  }
  const exportLabelSet = $("#exportLabelSet");
  if (exportLabelSet) {
    exportLabelSet.addEventListener("change", () => {
      state.exportLabelSet = exportLabelSet.value;
      const versionSelect = $("#exportVersion");
      if (versionSelect && state.exportLabelSet === "weak") versionSelect.value = "v3_preview";
      if (versionSelect && state.exportLabelSet === "dense") versionSelect.value = "final";
    });
  }
  document.querySelectorAll("[data-open-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeCaseId = button.dataset.openCase;
      state.activeImageId = null;
      state.activeAxis = "axial";
      state.activeSlice = 0;
      state.activeSlices = { axial: 0, coronal: 0, sagittal: 0 };
      state.undoStack = [];
      state.redoStack = [];
      resetViewerZoom({ render: false });
      setView("annotation");
    });
  });
  const viewerZoomSlider = $("#viewerZoomSlider");
  if (viewerZoomSlider) {
    viewerZoomSlider.addEventListener("input", () => {
      setViewerZoom(Number(viewerZoomSlider.value) / 100);
    });
  }
  document.querySelectorAll("[data-zoom-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.zoomAction;
      if (action === "in") setViewerZoom(clampViewerZoom(state.viewerZoom) * 1.15);
      else if (action === "out") setViewerZoom(clampViewerZoom(state.viewerZoom) / 1.15);
      else if (action === "fit") resetViewerZoom();
    });
  });
  const sliceSlider = $("#sliceSlider");
  if (sliceSlider) {
    const refreshSlice = () => {
      setCurrentSliceIndex(Number(sliceSlider.value));
      const image = activeImage();
      const meta = image ? state.volumeMeta[image.image_id] : null;
      if (image && meta) updateSliceViewer(image, meta);
    };
    sliceSlider.addEventListener("input", refreshSlice);
    sliceSlider.addEventListener("change", refreshSlice);
  }
  const axisSelect = $("#axisSelect");
  if (axisSelect) {
    axisSelect.value = activeAxis();
    axisSelect.addEventListener("change", () => {
      const nextAxis = sliceAxes[axisSelect.value] ? axisSelect.value : "axial";
      state.activeAxis = nextAxis;
      state.undoStack = [];
      state.redoStack = [];
      state.annotationPolygonPoints = [];
      state.annotationPolygonPreviewPoint = null;
      state.annotationPreviewRect = null;
      const image = activeImage();
      const meta = image ? state.volumeMeta[image.image_id] : null;
      if (image && meta) {
        const maxSlice = Math.max(axisSliceCount(meta, nextAxis) - 1, 0);
        setCurrentSliceIndex(Math.min(currentSliceIndex(nextAxis), maxSlice), nextAxis);
        updateSliceViewer(image, meta);
      } else {
        render();
      }
    });
  }
  document.querySelectorAll("[data-load-mask]").forEach((button) => {
    button.addEventListener("click", () => loadMaskForEditing(button.dataset.loadMask));
  });
  document.querySelectorAll("[data-delete-mask]").forEach((button) => {
    button.addEventListener("click", () => deleteMaskRecord(button.dataset.deleteMask));
  });
  const windowSelect = $("#windowSelect");
  if (windowSelect) {
    windowSelect.value = state.activeWindow;
    windowSelect.addEventListener("change", () => {
      state.activeWindow = windowSelect.value;
      $("#windowValue").textContent = windowSelect.options[windowSelect.selectedIndex].textContent;
      const image = activeImage();
      const meta = image ? state.volumeMeta[image.image_id] : null;
      if (image && meta) updateSliceViewer(image, meta);
    });
  }
  if (state.view === "annotation") hydrateAnnotation();
  if (state.view === "versions") hydrateVersions();
  if (state.view === "inference") hydrateInference();
  if (state.view === "quality") hydrateQuality();
  if (state.view === "train" || state.view === "dashboard") hydrateTrain();
}

async function startVolumeViewer(image) {
  const container = $("#volumeContainer");
  if (!container || !image) return;
  const maskId = container.dataset.maskId || "";
  const highlightMask = container.dataset.highlightMask === "true";
  const loadingKey = `${image.image_id}:volume-hu-v3:${maskId || "no-mask"}:hl-${highlightMask ? "1" : "0"}`;
  if (state.volumeLoadingKey === loadingKey && container.dataset.ready === "true") return;
  state.volumeLoadingKey = loadingKey;
  container.dataset.ready = "loading";

  try {
    const module = await import(`/frontend/volume_viewer.js?v=lung-vtk-fix-20260712`);
    if (maskId) {
      loadMaskQuality(maskId)
        .then(() => updateMaskQualitySummary(maskId))
        .catch((error) => {
          console.warn(`3D Mask 质量摘要加载失败：${maskId}`, error);
          updateMaskQualitySummary(maskId);
        });
    }
    await module.renderVolume3D({
      container,
      imageId: image.image_id,
      maskId: maskId || null,
      windowName: "volume",
      maxDim: 176,
      isotropic: false,
      highlightMask,
      labelColors: Object.fromEntries(
        effectiveLabelCatalog({ includeBackground: true, enabledOnly: false }).map((item) => [
          item.label_id,
          item.color,
        ]),
      ),
    });
    container.dataset.ready = "true";
    container.addEventListener("gesture-organ-select", (event) => {
      const name = event.detail?.name || `label_${event.detail?.labelId}`;
      showToast(`手势选中器官：${name}`);
    });
  } catch (error) {
    container.dataset.ready = "false";
    container.innerHTML = `<div class="volume-status error">3D 体渲染加载失败：${error.message}</div>`;
  }
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#refreshButton").addEventListener("click", async () => {
    await refreshCases();
    await refreshTasks();
    await refreshLabels();
    await refreshUsersList();
    render();
    showToast("数据已刷新");
  });
  $("#loginButton")?.addEventListener("click", () => {
    $("#loginOverlay")?.classList.remove("hidden");
    $("#loginUsername")?.focus();
  });
  $("#logoutButton")?.addEventListener("click", handleLogout);
  $("#loginDismiss")?.addEventListener("click", () => {
    if (state.currentUser) $("#loginOverlay")?.classList.add("hidden");
  });
}

async function init() {
  $("#currentDate").textContent = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  bindNavigation();
  bindBrushSizeControlsOnce();
  state.brushRadius = clamp(Number(localStorage.getItem("label_brush_radius")) || 4, 1, 40);
  state.eraseRadius = clamp(Number(localStorage.getItem("label_erase_radius")) || 10, 1, 60);
  window.addEventListener("resize", () => resizeAnnotationCanvas());
  await restoreSession();
  await refreshLabels();
  await refreshCases();
  await loadModels();
  render();
  updateAuthChrome();
}

init();
