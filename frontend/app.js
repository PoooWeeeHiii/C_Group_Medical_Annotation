const state = {
  view: "dashboard",
  cases: [],
  caseDetails: {},
  masksByImage: {},
  versionsByCase: {},
  volumeMeta: {},
  volumeErrors: {},
  datasetExportResult: null,
  activeCaseId: null,
  activeImageId: null,
  activeSlice: 0,
  activeWindow: "auto",
  volumeViewMode: "2d",
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

const labels = [
  ["#1c2938", "0 背景"],
  ["#00e5b0", "1 肝脏"],
  ["#38a3ff", "2 肾脏"],
  ["#ffb020", "3 肺部"],
  ["#ff4d4f", "4 肿瘤"],
];

const statusText = {
  unannotated: "未标注",
  annotated: "已标注",
  pending: "待审核",
  reviewed: "已审核",
  final: "已确认",
};

const $ = (selector) => document.querySelector(selector);
const API_BASE = window.location.port && window.location.port !== "8000" ? "http://127.0.0.1:8000" : "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
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

async function apiGet(path) {
  const response = await fetch(apiUrl(path));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || {});
    throw new Error(detail || `${path} 请求失败：${response.status}`);
  }
  return data;
}

async function apiPost(path, payload, options = {}) {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? 0;
  let timer = null;
  if (timeoutMs > 0) {
    timer = window.setTimeout(() => controller.abort(), timeoutMs);
  }
  try {
    const response = await fetch(apiUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
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
    const maxSlice = Math.max((state.volumeMeta[imageId].slice_count || 1) - 1, 0);
    state.activeSlice = Math.min(Math.floor(maxSlice / 2), maxSlice);
  }
  return state.volumeMeta[imageId];
}

async function loadImageMasks(imageId, { force = false } = {}) {
  if (!imageId) return [];
  if (force || !state.masksByImage[imageId]) {
    const data = await apiGet(`/api/image/${imageId}/masks`);
    state.masksByImage[imageId] = data.items || data.masks || [];
  }
  return state.masksByImage[imageId];
}

async function loadCaseVersions(caseId, { force = false } = {}) {
  if (!caseId) return [];
  if (force || !state.versionsByCase[caseId]) {
    const data = await apiGet(`/api/case/${caseId}/versions`);
    state.versionsByCase[caseId] = data.items || [];
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
    const response = await fetch(apiUrl("/api/upload"), { method: "POST", body });
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
    const data = await apiPost("/api/save_mask", {
      case_id: item.case_id,
      image_id: image.image_id,
      version: "v1_manual",
      label: "label",
      mask_format: "nii.gz",
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: "v1_manual",
      annotation: data.mask.annotation_id || null,
      model: null,
      dataset: null,
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    showToast(`Mask 保存成功：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "Mask 保存失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function runAiPredict(event) {
  const button = event.currentTarget;
  const item = activeCase();
  const image = activeImage();
  if (!item || !image) {
    showToast("请先选择病例和图像");
    return;
  }

  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "AI预测中...";
  showToast("正在运行脾 nnUNet 推理，CPU 可能需要数分钟...");
  try {
    const data = await apiPost("/api/ai/predict", {
      case_id: item.case_id,
      image_id: image.image_id,
      model_id: "Model0002",
      label: "spleen",
    }, { timeoutMs: 30 * 60 * 1000 });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    showToast(`脾 AI 标注完成：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "AI 预测失败");
  } finally {
    button.disabled = false;
    button.textContent = previousText;
  }
}

async function approveFinalMask(event) {
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
    const source = [...masks].reverse().find((mask) => mask.version === "v1_manual");
    if (!source) {
      throw new Error("当前图像还没有 v1_manual Mask，请先保存 Mask");
    }
    const data = await apiPost("/api/save_mask", {
      case_id: item.case_id,
      image_id: image.image_id,
      annotation_id: source.annotation_id || null,
      version: "final",
      label: source.label || "label",
      mask_format: "nii.gz",
    });
    await apiPost("/api/version", {
      case_id: item.case_id,
      version: "final",
      annotation: data.mask.annotation_id || source.annotation_id || null,
      model: null,
      dataset: null,
    });
    await loadImageMasks(image.image_id, { force: true });
    await loadCaseVersions(item.case_id, { force: true });
    await refreshCases();
    showToast(`已设为 final：${data.mask_id}`);
    render();
  } catch (error) {
    showToast(error.message || "final 审核失败");
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
人工修正 -> v3_fusion
审核确认 -> final
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

function renderMaskList(masks) {
  if (!masks.length) {
    return `<div class="placeholder compact">暂无 Mask。点击“保存 Mask”生成 v1_manual 记录。</div>`;
  }
  return `
    <div class="mask-record-list">
      ${masks.map((mask) => `
        <article class="mask-record">
          <div><strong>${escapeHtml(mask.mask_id)}</strong><span>${escapeHtml(mask.version)}</span></div>
          <div><span>标签</span><b>${escapeHtml(mask.label)}</b></div>
          <code>${escapeHtml(mask.path)}</code>
        </article>
      `).join("")}
    </div>
  `;
}

function renderVersionList(versions) {
  if (!versions.length) {
    return `<div class="placeholder compact">暂无版本记录。保存 Mask 后会写入 v1_manual，设为 final 后会写入 final。</div>`;
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

function renderViewerModeButtons() {
  return `
    <div class="viewer-mode-switch">
      <button class="mode-button ${state.volumeViewMode === "2d" ? "active" : ""}" data-view-mode="2d">2D切片</button>
      <button class="mode-button ${state.volumeViewMode === "3d" ? "active" : ""}" data-view-mode="3d">3D体视图</button>
    </div>
  `;
}

function render2DViewer(item, image, volume, activeSlice, sliceCount, maxSlice) {
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span id="viewerTitle">${item ? item.case_id : "暂无病例"} | 轴位 Axial</span><span id="viewerInfo">${image ? image.image_id : "等待图像"} | 缩放 100%</span></div>
      ${renderViewerModeButtons()}
      <div class="ct-frame real-image-frame">
        ${image ? `<img id="sliceImage" class="ct-slice-image" alt="医学影像切片" />` : ""}
        <div id="sliceError" class="slice-empty ${image ? "hidden" : ""}">${image ? "正在读取体数据..." : "暂无可显示图像"}</div>
        <div class="mask-overlay"></div>
        <div class="roi-box"></div>
        <div class="coordinate" id="sliceCoordinate">z: ${activeSlice + 1} / ${sliceCount}</div>
      </div>
      <div class="slider-row"><span>切片</span><input id="sliceSlider" type="range" min="0" max="${maxSlice}" value="${activeSlice}" /><strong id="sliceValue">${activeSlice + 1}</strong></div>
      <div class="slider-row"><span>透明度</span><input type="range" min="0" max="100" value="54" /><strong>54%</strong></div>
      <div class="slider-row"><span>窗位</span><select id="windowSelect"><option value="auto">自动</option><option value="lung">肺窗</option><option value="soft">软组织</option><option value="bone">骨窗</option></select><strong id="windowValue">自动</strong></div>
      <div class="image-source-line" id="sliceSource">切片接口：等待加载</div>
    </section>
  `;
}

function render3DViewer(item, image, volume) {
  const width = volume?.width || 1;
  const height = volume?.height || 1;
  const depth = volume?.slice_count || 1;
  const canRender = Boolean(image && volume);
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
        <span>AI Mask Overlay</span>
        <strong>${image ? apiUrl(`/api/image/${image.image_id}/masks`) : "等待图像"}</strong>
      </div>
      <button class="ghost-button" disabled>等待 Person B 输出 Mask</button>
    </div>
  `;
  return `
    <section class="viewer">
      <div class="viewer-toolbar"><span>${item ? item.case_id : "暂无病例"} | 3D体视图</span><span>${canRender ? `${width} × ${height} × ${depth}` : "等待体数据"}</span></div>
      ${renderViewerModeButtons()}
      <div id="volumeContainer" class="volume-container" data-image-id="${image?.image_id || ""}">
        <div class="volume-status">${canRender ? "正在初始化 WebGL2 真实体渲染..." : "正在读取体数据..."}</div>
      </div>
      ${mprGrid}
      ${mipGrid}
      ${maskOverlayPanel}
      <div class="image-source-line">三维体渲染用于总览、软组织和骨窗观察；细小病灶请结合 2D 切片、MIP 和 MinIP。</div>
      <div class="image-source-line">3D来源：${canRender ? `浏览器 GPU WebGL2 3D Texture Ray Casting + /api/image/${image.image_id}/volume-data?isotropic=true` : "等待加载"}</div>
    </section>
  `;
}

function renderAnnotation() {
  const item = activeCase();
  const image = activeImage();
  const volume = image ? state.volumeMeta[image.image_id] : null;
  const masks = masksForActiveImage();
  const versions = versionsForActiveCase();
  const sliceCount = volume?.slice_count || image?.slice_count || 1;
  const maxSlice = Math.max(sliceCount - 1, 0);
  const activeSlice = Math.min(state.activeSlice, maxSlice);
  const meta = item
    ? [["病例", item.case_id], ["患者", item.patient_id], ["影像类型", item.modality], ["状态", statusText[item.status] || item.status || "未标注"], ["图像数", item.image_count], ["Mask数", masks.length]]
    : [["病例", "暂无病例"], ["患者", "-"], ["影像类型", "-"], ["状态", "-"], ["图像数", "0"]];
  if (image) {
    meta.push(["图像", image.image_id]);
    meta.push(["格式", image.file_format]);
  }
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
        <div class="timeline">${["v1_manual", "v2_ai", "v3_fusion", "final"].map((version) => `<span class="chip ${versions.some((item) => item.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
        <h3 style="margin-top:24px">标签</h3>
        <div class="label-list">${labelList()}</div>
      </aside>
      ${state.volumeViewMode === "3d" ? render3DViewer(item, image, volume) : render2DViewer(item, image, volume, activeSlice, sliceCount, maxSlice)}
      <aside class="tool-panel">
        <h2>标注工具</h2>
        <div class="tool-grid">${["画笔", "橡皮擦", "多边形", "矩形ROI", "点标注", "智能选择", "撤销", "重做", "清空"].map((tool) => `<button class="tool-button">${tool}</button>`).join("")}<button class="tool-button" data-ai-predict ${image ? "" : "disabled"}>AI预测</button></div>
        <div class="grid action-stack" style="margin-top:18px"><button class="primary-button" data-save-mask ${image ? "" : "disabled"}>保存 Mask</button><button class="ghost-button" data-final-mask ${masks.some((mask) => mask.version === "v1_manual") ? "" : "disabled"}>设为 final</button><a class="ghost-button export-link ${image ? "" : "disabled-link"}" href="${image ? apiUrl(`/api/image/${image.image_id}/export-3d`) : "#"}">导出 3D 图像</a><button class="danger-button">驳回</button></div>
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

  const maxSlice = Math.max((meta.slice_count || 1) - 1, 0);
  state.activeSlice = Math.max(0, Math.min(state.activeSlice, maxSlice));
  const slider = $("#sliceSlider");
  if (slider) {
    slider.max = String(maxSlice);
    slider.value = String(state.activeSlice);
  }

  const sliceNumber = state.activeSlice + 1;
  const sliceUrl = apiUrl(`/api/image/${image.image_id}/slice/${state.activeSlice}.png?window=${state.activeWindow}&t=${Date.now()}`);
  imageElement.onload = () => {
    imageElement.classList.remove("hidden");
    $("#sliceError").classList.add("hidden");
  };
  imageElement.onerror = () => {
    displaySliceError("切片图像加载失败，请确认当前病例是真实 DICOM / NRRD / NIfTI 体数据。");
  };
  imageElement.src = sliceUrl;
  $("#sliceValue").textContent = String(sliceNumber);
  $("#sliceCoordinate").textContent = `z: ${sliceNumber} / ${meta.slice_count}`;
  $("#sliceSource").textContent = `切片接口：/api/image/${image.image_id}/slice/${state.activeSlice}.png`;
  $("#viewerInfo").textContent = `${image.image_id} | ${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSize").textContent = `${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSource").textContent = meta.source;
  const select = $("#windowSelect");
  if (select) {
    select.value = state.activeWindow;
    $("#windowValue").textContent = select.options[select.selectedIndex].textContent;
  }
}

function displaySliceError(message) {
  const errorBox = $("#sliceError");
  const imageElement = $("#sliceImage");
  if (imageElement) imageElement.classList.add("hidden");
  if (errorBox) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }
  const source = $("#volumeSource");
  if (source) source.textContent = "读取失败";
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
  const item = activeCase();
  const image = activeImage();
  const masks = masksForActiveImage();
  const aiMask = [...masks].reverse().find((mask) => mask.version === "v2_ai" && mask.label === "spleen");
  return `
    <section class="panel toolbar-row">
      <div class="field"><label>模型版本</label><select><option value="Model0002">Spleen_nnUNet_2d (Model0002)</option></select></div>
      <div class="field"><label>标签</label><input value="spleen" disabled /></div>
      <button class="primary-button" data-ai-predict ${image ? "" : "disabled"}>开始脾推理</button>
      <button class="ghost-button" disabled>当前输出：v2_ai</button>
    </section>
    <div class="grid cols-3" style="margin-top:18px">
      <section class="viewer"><h2>原始图像</h2><div class="ct-frame" style="min-height:320px"><strong>${image ? escapeHtml(image.image_id) : "请先选择病例"}</strong></div></section>
      <section class="viewer"><h2>AI Mask</h2><div class="ct-frame" style="min-height:320px"><div class="mask-overlay"></div><code>${aiMask ? escapeHtml(aiMask.path) : "尚未生成"}</code></div></section>
      <section class="viewer"><h2>叠加显示</h2><div class="ct-frame" style="min-height:320px"><div class="mask-overlay"></div><div class="roi-box"></div><strong>${item ? escapeHtml(item.case_id) : "-"}</strong></div></section>
    </div>
  `;
}

function renderVersions() {
  const item = activeCase();
  const versions = versionsForActiveCase();
  return `
    <section class="panel">
      <h2>${item ? item.case_id : "暂无病例"} 版本时间线</h2>
      <div class="timeline">${["v1_manual", "v2_ai", "v3_fusion", "final"].map((version) => `<span class="chip ${versions.some((entry) => entry.version === version) ? "active-chip" : ""}">${version}</span>`).join("")}</div>
      ${renderVersionList(versions)}
    </section>
    <div class="grid cols-2" style="margin-top:18px"><section class="viewer"><h2>人工 / AI 版本</h2><div class="ct-frame" style="min-height:330px"><div class="mask-overlay"></div></div></section><section class="viewer"><h2>final 审核版本</h2><div class="ct-frame" style="min-height:330px"><div class="roi-box"></div></div></section></div>
    <div class="grid cols-4" style="margin-top:18px">${metricCard("Dice", "0.86", "重叠度")}${metricCard("IoU", "0.75", "交并比")}${metricCard("HD95", "4.2", "边界距离")}${metricCard("体积差异", "12%", "差异比例")}</div>
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
  return `<div class="grid cols-2"><section class="panel"><h2>标签管理</h2><div class="label-list">${labelList()}</div></section><section class="panel"><h2>系统路径</h2><div class="case-meta"><div class="meta-line"><span>原始数据</span><strong>dataset/raw</strong></div><div class="meta-line"><span>训练图像</span><strong>dataset/images</strong></div><div class="meta-line"><span>标签数据</span><strong>dataset/labels</strong></div><div class="meta-line"><span>数据划分</span><strong>dataset/splits</strong></div></div></section></div>`;
}

function render() {
  const views = { dashboard: renderDashboard, cases: renderCases, annotation: renderAnnotation, train: renderTrain, inference: renderInference, versions: renderVersions, quality: renderQuality, export: renderExport, settings: renderSettings };
  $("#viewRoot").innerHTML = (views[state.view] || renderDashboard)();
  const uploadForm = $("#uploadForm");
  if (uploadForm) uploadForm.addEventListener("submit", uploadCase);
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
  const saveMaskButton = $("[data-save-mask]");
  if (saveMaskButton) {
    saveMaskButton.addEventListener("click", saveCurrentMask);
  }
  document.querySelectorAll("[data-ai-predict]").forEach((button) => {
    button.addEventListener("click", runAiPredict);
  });
  const finalMaskButton = $("[data-final-mask]");
  if (finalMaskButton) {
    finalMaskButton.addEventListener("click", approveFinalMask);
  }
  const exportDatasetButton = $("[data-export-dataset]");
  if (exportDatasetButton) {
    exportDatasetButton.addEventListener("click", exportDataset);
  }
  document.querySelectorAll("[data-open-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeCaseId = button.dataset.openCase;
      state.activeImageId = null;
      state.activeSlice = 0;
      setView("annotation");
    });
  });
  const sliceSlider = $("#sliceSlider");
  if (sliceSlider) {
    const refreshSlice = () => {
      state.activeSlice = Number(sliceSlider.value);
      const image = activeImage();
      const meta = image ? state.volumeMeta[image.image_id] : null;
      if (image && meta) updateSliceViewer(image, meta);
    };
    sliceSlider.addEventListener("input", refreshSlice);
    sliceSlider.addEventListener("change", refreshSlice);
  }
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
  const loadingKey = `${image.image_id}:volume-hu-v2`;
  if (state.volumeLoadingKey === loadingKey && container.dataset.ready === "true") return;
  state.volumeLoadingKey = loadingKey;
  container.dataset.ready = "loading";

  try {
    const module = await import(`/frontend/volume_viewer.js?v=cross-origin-api-20260701`);
    await module.renderVolume3D({
      container,
      imageId: image.image_id,
      windowName: "volume",
      maxDim: 176,
      isotropic: true,
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
    render();
    showToast("数据已刷新");
  });
}

async function init() {
  $("#currentDate").textContent = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  bindNavigation();
  await refreshCases();
  render();
}

init();
