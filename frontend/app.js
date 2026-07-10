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
  maskQualityById: {},
  volumeMeta: {},
  volumeErrors: {},
  datasetExportResult: null,
  activeCaseId: null,
  activeImageId: null,
  activeSlice: 0,
  activeAxis: "axial",
  activeSlices: { axial: 0, coronal: 0, sagittal: 0 },
  activeWindow: "auto",
  annotationTool: "brush",
  annotationLabel: "label",
  annotationLabelId: 1,
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
  magicWandPreset: "soft",
  magicWandThreshold: 45,
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

const labels = [
  ["#1c2938", "0 背景"],
  ["#00e5b0", "1 肝脏"],
  ["#38a3ff", "2 肾脏"],
  ["#ffb020", "3 肺部"],
  ["#ff4d4f", "4 肿瘤"],
  ["#b66dff", "5 脾脏"],
];

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
  ["undo", "撤销"],
  ["redo", "重做"],
  ["clear", "清空"],
];

const magicWandPresets = {
  lung: { label: "肺部 / 空气边界", threshold: 100, range: "80~120" },
  bone: { label: "骨骼", threshold: 180, range: "120~250" },
  soft: { label: "软组织", threshold: 45, range: "25~50" },
  vessel: { label: "血管 / 实质器官", threshold: 45, range: "30~60" },
  brain: { label: "脑窗", threshold: 25, range: "15~35" },
  custom: { label: "自定义", threshold: 45, range: "10~200" },
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

async function apiPost(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
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
      await restoreSavedMaskContents(imageId, state.masksByImage[imageId]);
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

async function restoreSession() {
  if (!state.authToken) {
    updateAuthChrome();
    return false;
  }
  try {
    const data = await apiGet("/api/me");
    state.currentUser = data.user;
    updateAuthChrome();
    if (canManageTasks()) {
      try {
        const users = await apiGet("/api/users");
        state.users = users.items || [];
      } catch {
        state.users = [];
      }
    }
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
    if (canManageTasks()) {
      const users = await apiGet("/api/users");
      state.users = users.items || [];
    }
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
    showToast(`审核通过：${data.case_id} → ${data.status}`);
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
    await refreshCases();
    await refreshTasks();
    showToast(`已驳回：${data.case_id} → ${data.status}`);
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
  if (!fileInput.files.length) {
    showToast("请选择一个 DICOM / NRRD / NIfTI / PNG 文件");
    return;
  }

  const body = new FormData();
  body.append("file", fileInput.files[0]);
  body.append("patient_id", form.patient_id.value || "");
  body.append("modality", form.modality.value || "CT");
  body.append("source_group", form.source_group.value || "local");

  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  button.textContent = "上传中...";
  try {
    const response = await fetch(apiUrl("/api/upload"), { method: "POST", body, headers: authHeaders() });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "上传失败");
    showToast(`导入成功：${data.case_id} / ${data.image_id}`);
    state.activeCaseId = data.case_id;
    state.activeImageId = data.image_id;
    form.reset();
    await refreshCases();
    setView("cases");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "上传病例";
  }
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
    const updatedCount = saved.filter((item) => item.updated).length;
    const createdCount = saved.length - updatedCount;
    showToast(`已保存 ${saved.length} 个切片 Mask（新建 ${createdCount} / 覆盖 ${updatedCount}）`);
    render();
  } catch (error) {
    showToast(error.message || "Mask 保存失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
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

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "预测中...";
  try {
    const data = await apiPost("/api/ai/predict", {
      case_id: item.case_id,
      image_id: image.image_id,
      model_id: "spleen_nnunetv2_task506",
      label: "spleen",
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    state.active3DMaskId = data.mask_id;
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    showToast(`脾脏 AI 预测完成：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "AI 预测失败");
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
    const current3DMask = latest3DMask(currentMasks);
    const prompts = deepEditPromptPayload(image);
    const scribbles = deepEditScribblePayload(image);
    const data = await apiPost("/api/deepedit/refine", {
      case_id: item.case_id,
      image_id: image.image_id,
      source_version: "v1_manual",
      current_mask_version: "v3_fusion",
      current_mask_id: current3DMask?.mask_id || null,
      output_version: "v3_preview",
      label: state.annotationLabel,
      model_id: "DeepEdit",
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
    showToast(`已生成 v3_preview 预览：${data.mask_id} · ${data.model_status || data.refinement_mode}`);
    render();
  } catch (error) {
    showToast(error.message || "智能3D传播修正失败");
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

  const masks = await loadImageMasks(image.image_id, { force: true });
  const hasManualJson = masks.some((mask) => (
    mask.version === "v1_manual" &&
    (mask.mask_format === "json" || String(mask.path || "").endsWith(".json"))
  ));
  if (!hasManualJson) {
    showToast("请先回到 2D 切片，画好标注并点击“保存 Mask”");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "生成高亮实体...";
  try {
    const data = await create3DMaskPreview(item, image);
    if (!data?.mask_id) {
      throw new Error("3D Mask 未生成");
    }
    state.active3DMaskId = data.mask_id;
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    state.volumeViewMode = "3d";
    state.volumeLoadingKey = null;
    state.propagatedSliceLoads = {};
    showToast(`已高亮显示当前标注：${data.mask_id}`);
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
  const item = activeCase();
  if (!item) {
    showToast("请先选择病例");
    return;
  }
  const version = $("#exportVersion")?.value || "final";
  const format = $("#exportFormat")?.value || "nnunet";
  const datasetId = $("#exportDatasetId")?.value.trim() || undefined;

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "导出中...";
  try {
    const data = await apiPost("/api/export", {
      dataset_id: datasetId,
      name: `${item.case_id}_${version}`,
      version,
      train: [item.case_id],
      val: [],
      test: [],
      format,
    });
    state.datasetExportResult = data;
    showToast(`Dataset 导出成功：${data.dataset_id}`);
    render();
  } catch (error) {
    showToast(error.message || "Dataset 导出失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
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
          当前前端已接入后端上传和病例查询接口，可作为 Vue/React 重构前的交互原型。
        </p>
        <div class="pipeline">
          ${["导入", "病例", "图像", "标注", "Mask", "Dataset", "训练", "模型", "预测", "修正"].map((item) => `<span class="chip">${item}</span>`).join("")}
        </div>
      </section>
      <section class="panel chart-box">
        <h2>标注进度</h2>
        <div class="ring" style="background: conic-gradient(var(--green) 0 ${progress}%, rgba(255,255,255,.08) ${progress}% 100%)">
          <div class="ring-inner"><div><strong>${progress}%</strong><br><span class="metric-label">已审核</span></div></div>
        </div>
      </section>
    </div>
    <div class="grid cols-4">
      ${metricCard("病例总数", total, "来自后端 /api/cases")}
      ${metricCard("已标注", annotated, "人工 + AI + 修正")}
      ${metricCard("待审核", pending, "等待 final 确认")}
      ${metricCard("最佳 Dice", "0.86", "基线目标")}
    </div>
    <div class="grid cols-2" style="margin-top:18px">
      <section class="panel">
        <h2>AI训练 Loss / Dice</h2>
        <div class="line-chart">${[32, 48, 41, 62, 58, 74, 69, 82, 77, 88].map((height) => `<div class="bar" style="height:${height}%"></div>`).join("")}</div>
      </section>
      <section class="panel">
        <h2>最近任务</h2>
        <div class="log-box">上传 CT -> 生成 Case / Image
人工 ROI -> 保存 Mask
AI 预测 -> v2_ai
智能修正 -> v3_preview
确认预览 -> v3_fusion / final
导出数据集 -> Dataset0001</div>
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
      <form id="uploadForm" class="toolbar-row">
        <input class="file-input" type="file" name="file" accept=".dcm,.zip,.nii,.gz,.nrrd,.png,.jpg,.jpeg" />
        <div class="field"><label>患者编号</label><input name="patient_id" placeholder="LUNG1-001" /></div>
        <div class="field"><label>影像类型</label><select name="modality"><option value="CT">CT</option><option value="MRI">MRI</option><option value="PNG">PNG/JPG</option></select></div>
        <div class="field"><label>数据来源</label><select name="source_group"><option value="local">本地</option><option value="A">A组</option><option value="B">B组</option></select></div>
        <button class="primary-button" type="submit">上传病例</button>
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

function labelList() {
  return labels.map(([color, text]) => `<div class="label-row"><span class="swatch" style="background:${color}"></span>${text}</div>`).join("");
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
  const toolButtons = annotationTools
    .map(([tool, label]) => `<button class="tool-button ${state.annotationTool === tool ? "active" : ""}" data-annotation-tool="${tool}">${label}</button>`)
    .join("");
  return `${toolButtons}<button class="tool-button" data-ai-predict>AI预测</button>`;
}

function annotationToolLabel(tool = state.annotationTool) {
  return annotationTools.find(([key]) => key === tool)?.[1] || tool;
}

function renderMagicWandControls() {
  const options = Object.entries(magicWandPresets)
    .map(([key, preset]) => `<option value="${key}" ${state.magicWandPreset === key ? "selected" : ""}>${preset.label} (${preset.range})</option>`)
    .join("");
  return `
    <div class="magic-wand-controls">
      <div class="magic-control-row">
        <label for="magicPreset">智能场景</label>
        <select id="magicPreset">${options}</select>
      </div>
      <div class="magic-control-row">
        <label for="magicThreshold">智能阈值</label>
        <input id="magicThreshold" type="range" min="10" max="200" step="1" value="${state.magicWandThreshold}" />
        <strong id="magicThresholdValue">HU ± ${state.magicWandThreshold}</strong>
      </div>
    </div>
  `;
}

function renderSmartRefineHint() {
  return `
    <div class="deepedit-controls">
      <span>智能修正提示</span>
      <small>画笔/多边形/矩形 = 正向标注；智能橡皮擦点击相似区域自动擦除，并同时记为 DeepEdit 负点。点击“智能3D传播修正”后会一起更新 3D Mask。</small>
    </div>
  `;
}

function renderRefineParamControls() {
  const params = state.refineParams;
  return `
    <div class="refine-param-controls">
      <div class="param-header"><span>修正参数</span><strong>Fallback 图模型</strong></div>
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
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span id="viewerTitle">${item ? item.case_id : "暂无病例"} | ${axisLabel(axis)}</span><span id="viewerInfo">${image ? image.image_id : "等待图像"} | 缩放 100%</span></div>
      ${renderViewerModeButtons()}
      <div class="ct-frame real-image-frame">
        ${image ? `<img id="sliceImage" class="ct-slice-image" alt="医学影像切片" />` : ""}
        <div id="sliceError" class="slice-empty ${image ? "hidden" : ""}">${image ? "正在读取体数据..." : "暂无可显示图像"}</div>
        ${image ? `<canvas id="annotationCanvas" class="annotation-canvas" aria-label="标注画布"></canvas>` : ""}
        <div class="coordinate" id="sliceCoordinate">${axisCoordinateName(axis)}: ${activeSlice + 1} / ${sliceCount}</div>
      </div>
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
  const active3DMask = latest3DMask(masks);
  const axialIndex = Math.max(0, Math.floor(depth / 2));
  const coronalIndex = Math.max(0, Math.floor(height / 2));
  const sagittalIndex = Math.max(0, Math.floor(width / 2));
  const mprGrid = `
    <div class="viewer-subsection">
      <div class="subsection-title"><span>MPR 三平面重建</span><strong>轴位 / 冠状位 / 矢状位</strong></div>
      <div class="orthogonal-grid mpr-grid">
        <div><span>轴位 Slice ${axialIndex + 1}</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/axial/${axialIndex}.png?window=auto`)}" alt="轴位 MPR" />` : ""}</div>
        <div><span>冠状位 Slice ${coronalIndex + 1}</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/coronal/${coronalIndex}.png?window=auto`)}" alt="冠状位 MPR" />` : ""}</div>
        <div><span>矢状位 Slice ${sagittalIndex + 1}</span>${canRender ? `<img loading="lazy" src="${apiUrl(`/api/image/${image.image_id}/slice/sagittal/${sagittalIndex}.png?window=auto`)}" alt="矢状位 MPR" />` : ""}</div>
      </div>
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
  const maskOverlayPanel = `
    <div class="mask-overlay-panel">
      <div>
        <span>3D Mask 实体叠加</span>
        <strong>${active3DMask ? `${active3DMask.mask_id} · ${active3DMask.version}` : "暂无 3D Mask"}</strong>
        <code>${active3DMask ? active3DMask.path : "请先在 2D 中保存 Mask，再执行智能3D传播修正"}</code>
        ${renderMaskQualitySummary(active3DMask)}
      </div>
      <button class="primary-button" data-render-annotation-3d ${canRender ? "" : "disabled"}>高亮显示当前标注</button>
    </div>
  `;
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span>${item ? item.case_id : "暂无病例"} | 3D体视图</span><span>${canRender ? `${width} × ${height} × ${depth}` : "等待体数据"}</span></div>
      ${renderViewerModeButtons()}
      <div id="volumeContainer" class="volume-container" data-image-id="${image?.image_id || ""}" data-mask-id="${active3DMask?.mask_id || ""}">
        <div class="volume-status">${canRender ? "正在初始化 VTK 综合重建..." : "正在读取体数据..."}</div>
      </div>
      ${mprGrid}
      ${mipGrid}
      ${maskOverlayPanel}
      <div class="image-source-line">三维视图默认使用 VTK 综合重建：外层、肺/低密度腔、软组织、骨性结构和 Mask 均使用 VTK mesh。</div>
      <div class="image-source-line">3D来源：${canRender ? `/api/image/${image.image_id}/surface-mesh?protocol=body|lung|soft|bone${active3DMask ? ` + /api/mask/${active3DMask.mask_id}/surface-mesh` : ""}；WebGL2 体渲染保留为备用` : "等待加载"}</div>
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
  const versionTimeline = ["v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"];
  return `
    <div class="workbench-layout">
      <aside class="case-sidebar">
        <h2>病例信息</h2>
        <div class="case-meta">${meta.map(([key, value]) => `<div class="meta-line"><span>${key}</span><strong>${value}</strong></div>`).join("")}</div>
        <h3 style="margin-top:24px">体数据</h3>
        <div class="case-meta">
          <div class="meta-line"><span>尺寸</span><strong id="volumeSize">${volume ? `${volume.width} × ${volume.height} × ${volume.slice_count}` : "加载中"}</strong></div>
          <div class="meta-line"><span>读取器</span><strong id="volumeSource">${volume?.source || "-"}</strong></div>
        </div>
        <h3 style="margin-top:24px">版本</h3>
        <div class="timeline">${versionTimeline.map((version) => `<span class="chip ${versions.some((item) => item.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
        <h3 style="margin-top:24px">标签</h3>
        <div class="label-list">${labelList()}</div>
      </aside>
      ${state.volumeViewMode === "3d" ? render3DViewer(item, image, volume, masks) : render2DViewer(item, image, volume, activeSlice, sliceCount, maxSlice, axis)}
      <aside class="tool-panel">
        <h2>标注工具</h2>
        <div class="tool-grid">${renderToolButtons()}</div>
        <div class="annotation-state-line"><span>当前工具：<strong id="annotationToolLabel">${annotationToolLabel()}</strong></span><span>当前 label：<strong>${escapeHtml(state.annotationLabel)} #${state.annotationLabelId}</strong></span><span>智能阈值：<strong>HU ± ${state.magicWandThreshold}</strong></span><span>当前切片：<strong id="annotationMaskStats">0 像素</strong></span></div>
        ${renderMagicWandControls()}
        ${renderSmartRefineHint()}
        ${renderRefineParamControls()}
        <div class="grid action-stack" style="margin-top:18px">
          <button class="primary-button" data-save-mask ${image && canAnnotate() ? "" : "disabled"}>保存 Mask</button>
          <button class="ghost-button" data-submit-case ${image && (currentRole() === "annotator" || currentRole() === "admin") ? "" : "disabled"}>提交审核</button>
          <button class="ghost-button" data-smart-3d-refine ${image && canAnnotate() ? "" : "disabled"}>智能3D传播修正</button>
          <button class="ghost-button" data-confirm-fusion ${previewMask && canAnnotate() ? "" : "disabled"}>确认 v3_fusion</button>
          <button class="ghost-button" data-final-mask ${(previewMask || fusionMask) && canConfirmFinal() ? "" : "disabled"}>确认 final</button>
          <button class="ghost-button" data-approve-case ${item && canReview() ? "" : "disabled"}>审核通过</button>
          <button class="danger-button" data-reject-case ${item && canReview() ? "" : "disabled"}>驳回</button>
          <button class="ghost-button" data-export-mask-nifti ${image && canAnnotate() ? "" : "disabled"}>导出 3D Mask</button>
          <button class="ghost-button" data-start-3d-render ${image ? "" : "disabled"}>导出 3D 图像</button>
        </div>
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

function getDisplayedImageRect(imageElement) {
  const frame = imageElement?.parentElement;
  if (!imageElement || !frame || !imageElement.naturalWidth || !imageElement.naturalHeight) return null;
  const frameRect = frame.getBoundingClientRect();
  const imageRatio = imageElement.naturalWidth / imageElement.naturalHeight;
  const frameRatio = frameRect.width / frameRect.height;
  let width = frameRect.width;
  let height = frameRect.height;
  let left = 0;
  let top = 0;

  if (frameRatio > imageRatio) {
    height = frameRect.height;
    width = height * imageRatio;
    left = (frameRect.width - width) / 2;
  } else {
    width = frameRect.width;
    height = width / imageRatio;
    top = (frameRect.height - height) / 2;
  }

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
  canvas.style.left = `${rect.frameLeft}px`;
  canvas.style.top = `${rect.frameTop}px`;
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  renderCurrentSliceMask();
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

function annotationStrokeStyle() {
  const color = labels[state.annotationLabelId]?.[0] || labels[1]?.[0] || "#00e5b0";
  return color;
}

function hexToRgb(hex) {
  const normalized = String(hex || "#00e5b0").replace("#", "");
  const value = Number.parseInt(normalized.length === 3 ? normalized.split("").map((char) => char + char).join("") : normalized, 16);
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
    showToast("没有可重做的操作");
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
    updateAnnotationMaskStats();
    return;
  }

  const imageData = context.createImageData(mask.width, mask.height);
  for (let index = 0; index < mask.data.length; index += 1) {
    const labelId = mask.data[index];
    if (!labelId) continue;
    const color = hexToRgb(labels[labelId]?.[0] || annotationStrokeStyle());
    const offset = index * 4;
    imageData.data[offset] = color.r;
    imageData.data[offset + 1] = color.g;
    imageData.data[offset + 2] = color.b;
    imageData.data[offset + 3] = 150;
  }
  context.putImageData(imageData, 0, 0);
  drawPointAnnotations(context);
  drawRectanglePreview(context);
  drawPolygonPreview(context);
  updateAnnotationMaskStats();
}

function drawPointAnnotations(context) {
  const points = currentSlicePoints({ create: false }) || [];
  if (!context || !points.length) return;
  context.save();
  for (const point of points) {
    const promptType = point.promptType || "positive";
    const color = promptType === "negative" ? "#ff4d4f" : labels[point.labelId]?.[0] || annotationStrokeStyle();
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

  for (let y = startY; y <= endY; y += 1) {
    for (let x = startX; x <= endX; x += 1) {
      const dx = x - centerX;
      const dy = y - centerY;
      if (dx * dx + dy * dy <= radiusSquared) {
        mask.data[y * mask.width + x] = labelId;
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
  const radius = isEraser ? 10 : 4;
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
  const point = pointerToImagePoint(event);
  if (point) updateAnnotationCoordinate(point);
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
  if (!canvas) return;
  resizeAnnotationCanvas();
  canvas.addEventListener("pointerdown", handleAnnotationPointerDown);
  canvas.addEventListener("pointermove", handleAnnotationPointerMove);
  canvas.addEventListener("pointerup", finishAnnotationPointer);
  canvas.addEventListener("pointercancel", finishAnnotationPointer);
  canvas.addEventListener("pointerleave", finishAnnotationPointer);
  canvas.addEventListener("dblclick", finishAnnotationPolygon);
}

async function hydrateVersions() {
  const item = activeCase();
  if (!item) return;
  const needsRender = !state.versionsByCase[item.case_id];
  try {
    await loadCaseVersions(item.case_id);
    if (needsRender) render();
  } catch (error) {
    showToast(error.message || "版本记录加载失败");
  }
}

function renderTrain() {
  return `
    <div class="grid cols-2">
      <section class="panel"><h2>训练配置</h2><div class="grid cols-2" style="margin-top:16px">${["Dataset0001", "U-Net", "50 Epoch", "LR 0.001", "Batch 4", "BCE + Dice"].map((item) => `<span class="chip">${item}</span>`).join("")}</div><div class="toolbar-row" style="margin-top:18px"><button class="primary-button">开始训练</button><button class="ghost-button">停止</button><button class="ghost-button">继续</button></div></section>
      <section class="panel"><h2>Loss / Dice 曲线</h2><div class="line-chart">${[78, 70, 61, 54, 47, 42, 36, 32].map((height) => `<div class="bar" style="height:${height}%"></div>`).join("")}</div></section>
    </div>
    <section class="panel" style="margin-top:18px"><h2>训练日志</h2><div class="log-box">Epoch 01 | Loss 0.812 | Dice 0.42
Epoch 02 | Loss 0.703 | Dice 0.51
Epoch 03 | Loss 0.618 | Dice 0.59
等待 Person B 接入 train.py...</div></section>
  `;
}

function renderInference() {
  return `
    <section class="panel toolbar-row"><div class="field"><label>模型版本</label><select><option>UNet_V1</option><option>Attention_UNet_V1</option></select></div><button class="primary-button">开始推理</button><button class="ghost-button">保存为 v2_ai</button></section>
    <div class="grid cols-3" style="margin-top:18px">
      <section class="viewer"><h2>原始图像</h2><div class="ct-frame" style="min-height:320px"></div></section>
      <section class="viewer"><h2>AI Mask</h2><div class="ct-frame" style="min-height:320px"><div class="mask-overlay"></div></div></section>
      <section class="viewer"><h2>叠加显示</h2><div class="ct-frame" style="min-height:320px"><div class="mask-overlay"></div><div class="roi-box"></div></div></section>
    </div>
  `;
}

function renderVersions() {
  const item = activeCase();
  const versions = versionsForActiveCase();
  return `
    <section class="panel">
      <h2>${item ? item.case_id : "暂无病例"} 版本时间线</h2>
      <div class="timeline">${["v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"].map((version) => `<span class="chip ${versions.some((entry) => entry.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
      <div class="toolbar-row" style="margin-top:14px">
        <button class="ghost-button" data-submit-case ${item && (currentRole() === "annotator" || currentRole() === "admin") ? "" : "disabled"}>提交审核</button>
        <button class="primary-button" data-approve-case ${item && canReview() ? "" : "disabled"}>审核通过</button>
        <button class="danger-button" data-reject-case ${item && canReview() ? "" : "disabled"}>驳回</button>
      </div>
      ${renderVersionList(versions)}
    </section>
    <div class="grid cols-2" style="margin-top:18px"><section class="viewer"><h2>人工 / AI 版本</h2><div class="ct-frame" style="min-height:330px"><div class="mask-overlay"></div></div></section><section class="viewer"><h2>final 审核版本</h2><div class="ct-frame" style="min-height:330px"><div class="roi-box"></div></div></section></div>
    <div class="grid cols-4" style="margin-top:18px">${metricCard("当前状态", item ? (statusText[item.status] || item.status) : "-", "病例状态机")}${metricCard("角色", state.currentUser ? (roleText[state.currentUser.role] || state.currentUser.role) : "未登录", "决定审核权限")}${metricCard("任务数", state.tasks.length, "当前可见任务")}${metricCard("版本数", versions.length, "已写入版本")}</div>
  `;
}

function renderQuality() {
  return `<div class="grid cols-4">${metricCard("Dice", "0.86", "整体")}${metricCard("IoU", "0.75", "整体")}${metricCard("Precision", "0.88", "阳性预测")}${metricCard("Recall", "0.84", "敏感性")}</div><div class="grid cols-2" style="margin-top:18px"><section class="panel"><h2>质量雷达图</h2><div class="placeholder">Dice / IoU / Precision / Recall / HD95 / ASSD</div></section><section class="viewer"><h2>错误区域</h2><div class="ct-frame" style="min-height:300px"><div class="mask-overlay"></div><div class="roi-box"></div></div></section></div>`;
}

function renderExport() {
  const item = activeCase();
  const result = state.datasetExportResult;
  return `
    <section class="panel">
      <div class="toolbar-row">
        <div class="field"><label>Dataset ID</label><input id="exportDatasetId" placeholder="自动生成 Dataset0001" /></div>
        <div class="field"><label>版本</label><select id="exportVersion"><option value="final">final</option><option value="v3_fusion">v3_fusion</option><option value="v2_ai">v2_ai</option><option value="v1_manual">v1_manual</option></select></div>
        <div class="field"><label>格式</label><select id="exportFormat"><option value="nnunet">nnUNet</option><option value="json">JSON Manifest</option></select></div>
        <button class="primary-button" data-export-dataset ${item ? "" : "disabled"}>导出 Dataset</button>
      </div>
    </section>
    <section class="table-wrap" style="margin-top:18px">
      <table><thead><tr><th>病例ID</th><th>导出版本</th><th>数据划分</th><th>说明</th></tr></thead><tbody><tr><td>${item ? item.case_id : "-"}</td><td>final</td><td>train</td><td>当前最小版本按当前病例导出；val/test 暂为空。</td></tr></tbody></table>
    </section>
    <section class="panel" style="margin-top:18px">
      <h2>导出结果</h2>
      ${result ? `
        <div class="case-meta">
          <div class="meta-line"><span>Dataset</span><strong>${escapeHtml(result.dataset_id)}</strong></div>
          <div class="meta-line"><span>Manifest</span><strong>${escapeHtml(result.output_path)}</strong></div>
          <div class="meta-line"><span>Split</span><strong>${escapeHtml(result.split_path)}</strong></div>
          <div class="meta-line"><span>Label Map</span><strong>${escapeHtml(result.label_map_path)}</strong></div>
        </div>
      ` : `<div class="placeholder compact">尚未导出。请先确保当前病例已有 final Mask。</div>`}
    </section>
  `;
}

function renderSettings() {
  return `<div class="grid cols-2"><section class="panel"><h2>标签管理</h2><div class="label-list">${labelList()}</div></section><section class="panel"><h2>账号与权限</h2><div class="case-meta"><div class="meta-line"><span>当前用户</span><strong>${state.currentUser ? escapeHtml(state.currentUser.username) : "未登录"}</strong></div><div class="meta-line"><span>角色</span><strong>${state.currentUser ? escapeHtml(roleText[state.currentUser.role] || state.currentUser.role) : "-"}</strong></div><div class="meta-line"><span>演示账号</span><strong>admin/admin123 · reviewer/reviewer123 · annotator/annotator123</strong></div><div class="meta-line"><span>状态机</span><strong>unannotated → annotated → pending → reviewed → final</strong></div></div></section></div>`;
}

function render() {
  const views = { dashboard: renderDashboard, cases: renderCases, annotation: renderAnnotation, train: renderTrain, inference: renderInference, versions: renderVersions, quality: renderQuality, export: renderExport, settings: renderSettings };
  $("#viewRoot").innerHTML = (views[state.view] || renderDashboard)();
  const uploadForm = $("#uploadForm");
  if (uploadForm) uploadForm.addEventListener("submit", uploadCase);
  const taskForm = $("#taskForm");
  if (taskForm) taskForm.addEventListener("submit", createTaskAssignment);
  const loginForm = $("#loginForm");
  if (loginForm) loginForm.addEventListener("submit", handleLogin);
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
  bindMagicWandControls();
  bindRefineParamControls();
  bindAnnotationCanvas();
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
  const finalMaskButton = $("[data-final-mask]");
  if (finalMaskButton) {
    finalMaskButton.addEventListener("click", approveFinalMask);
  }
  const fusionMaskButton = $("[data-confirm-fusion]");
  if (fusionMaskButton) {
    fusionMaskButton.addEventListener("click", approveFusionMask);
  }
  const aiPredictButton = $("[data-ai-predict]");
  if (aiPredictButton) {
    aiPredictButton.addEventListener("click", runAIPredict);
  }
  const exportMaskNiftiButton = $("[data-export-mask-nifti]");
  if (exportMaskNiftiButton) {
    exportMaskNiftiButton.addEventListener("click", exportMaskNifti);
  }
  const smart3DRefineButton = $("[data-smart-3d-refine]");
  if (smart3DRefineButton) {
    smart3DRefineButton.addEventListener("click", runSmart3DRefine);
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
  document.querySelectorAll("[data-open-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeCaseId = button.dataset.openCase;
      state.activeImageId = null;
      state.activeAxis = "axial";
      state.activeSlice = 0;
      state.activeSlices = { axial: 0, coronal: 0, sagittal: 0 };
      state.undoStack = [];
      state.redoStack = [];
      setView("annotation");
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
}

async function startVolumeViewer(image) {
  const container = $("#volumeContainer");
  if (!container || !image) return;
  const maskId = container.dataset.maskId || "";
  const loadingKey = `${image.image_id}:volume-hu-v3:${maskId || "no-mask"}`;
  if (state.volumeLoadingKey === loadingKey && container.dataset.ready === "true") return;
  state.volumeLoadingKey = loadingKey;
  container.dataset.ready = "loading";

  try {
    const module = await import(`/frontend/volume_viewer.js?v=vtk-organ-color-ui-20260710`);
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
    });
    container.dataset.ready = "true";
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
  window.addEventListener("resize", () => resizeAnnotationCanvas());
  await restoreSession();
  await refreshCases();
  render();
  updateAuthChrome();
}

init();
