const state = {
  view: "dashboard",
  cases: [],
  caseDetails: {},
  volumeMeta: {},
  activeCaseId: null,
  activeImageId: null,
  activeSlice: 0,
  activeWindow: "auto",
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
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} 请求失败：${response.status}`);
  return response.json();
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

async function loadVolumeMeta(imageId) {
  if (!imageId) return null;
  if (!state.volumeMeta[imageId]) {
    state.volumeMeta[imageId] = await apiGet(`/api/image/${imageId}/volume`);
    const maxSlice = Math.max((state.volumeMeta[imageId].slice_count || 1) - 1, 0);
    state.activeSlice = Math.min(Math.floor(maxSlice / 2), maxSlice);
  }
  return state.volumeMeta[imageId];
}

async function refreshCases() {
  try {
    const data = await apiGet("/api/cases");
    state.cases = data.items || [];
    if (!state.activeCaseId && state.cases.length) state.activeCaseId = state.cases[0].case_id;
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
    const response = await fetch("/api/upload", { method: "POST", body });
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

function renderAnnotation() {
  const item = activeCase();
  const image = activeImage();
  const volume = image ? state.volumeMeta[image.image_id] : null;
  const sliceCount = volume?.slice_count || image?.slice_count || 1;
  const maxSlice = Math.max(sliceCount - 1, 0);
  const activeSlice = Math.min(state.activeSlice, maxSlice);
  const meta = item
    ? [["病例", item.case_id], ["患者", item.patient_id], ["影像类型", item.modality], ["状态", statusText[item.status] || item.status || "未标注"], ["图像数", item.image_count]]
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
        <div class="timeline"><span class="chip">v1_人工</span><span class="chip">v2_AI</span><span class="chip">v3_融合</span><span class="chip">final</span></div>
        <h3 style="margin-top:24px">标签</h3>
        <div class="label-list">${labelList()}</div>
      </aside>
      <section class="viewer">
        <div class="viewer-toolbar"><span id="viewerTitle">${item ? item.case_id : "暂无病例"} | 轴位 Axial</span><span id="viewerInfo">${image ? image.image_id : "等待图像"} | 缩放 100%</span></div>
        <div class="ct-frame real-image-frame">
          ${image ? `<img id="sliceImage" class="ct-slice-image" alt="医学影像切片" />` : `<div class="slice-empty">暂无可显示图像</div>`}
          <div class="mask-overlay"></div>
          <div class="roi-box"></div>
          <div class="coordinate" id="sliceCoordinate">z: ${activeSlice + 1} / ${sliceCount}</div>
        </div>
        <div class="slider-row"><span>切片</span><input id="sliceSlider" type="range" min="0" max="${maxSlice}" value="${activeSlice}" /><strong id="sliceValue">${activeSlice + 1}</strong></div>
        <div class="slider-row"><span>透明度</span><input type="range" min="0" max="100" value="54" /><strong>54%</strong></div>
        <div class="slider-row"><span>窗位</span><select id="windowSelect"><option value="auto">自动</option><option value="lung">肺窗</option><option value="soft">软组织</option><option value="bone">骨窗</option></select><strong id="windowValue">自动</strong></div>
      </section>
      <aside class="tool-panel">
        <h2>标注工具</h2>
        <div class="tool-grid">${["画笔", "橡皮擦", "多边形", "矩形ROI", "点标注", "智能选择", "撤销", "重做", "清空", "AI预测"].map((tool) => `<button class="tool-button">${tool}</button>`).join("")}</div>
        <div class="grid action-stack" style="margin-top:18px"><button class="primary-button">保存 Mask</button><button class="ghost-button">设为 final</button><a class="ghost-button export-link ${image ? "" : "disabled-link"}" href="${image ? `/api/image/${image.image_id}/export-3d` : "#"}">导出 3D 图像</a><button class="danger-button">驳回</button></div>
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
    const meta = await loadVolumeMeta(image.image_id);
    updateSliceViewer(image, meta);
  } catch (error) {
    showToast(error.message || "图像读取失败");
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
  imageElement.src = `/api/image/${image.image_id}/slice/${state.activeSlice}.png?window=${state.activeWindow}&t=${Date.now()}`;
  $("#sliceValue").textContent = String(sliceNumber);
  $("#sliceCoordinate").textContent = `z: ${sliceNumber} / ${meta.slice_count}`;
  $("#viewerInfo").textContent = `${image.image_id} | ${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSize").textContent = `${meta.width} × ${meta.height} × ${meta.slice_count}`;
  $("#volumeSource").textContent = meta.source;
  const select = $("#windowSelect");
  if (select) {
    select.value = state.activeWindow;
    $("#windowValue").textContent = select.options[select.selectedIndex].textContent;
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
  return `
    <section class="panel"><h2>${state.activeCaseId || "Case0001"} 版本时间线</h2><div class="timeline"><span class="chip">人工 V1</span><span class="chip">AI V1</span><span class="chip">修正 V2</span><span class="chip">final</span></div></section>
    <div class="grid cols-2" style="margin-top:18px"><section class="viewer"><h2>版本 A</h2><div class="ct-frame" style="min-height:330px"><div class="mask-overlay"></div></div></section><section class="viewer"><h2>版本 B</h2><div class="ct-frame" style="min-height:330px"><div class="roi-box"></div></div></section></div>
    <div class="grid cols-4" style="margin-top:18px">${metricCard("Dice", "0.86", "重叠度")}${metricCard("IoU", "0.75", "交并比")}${metricCard("HD95", "4.2", "边界距离")}${metricCard("体积差异", "12%", "差异比例")}</div>
  `;
}

function renderQuality() {
  return `<div class="grid cols-4">${metricCard("Dice", "0.86", "整体")}${metricCard("IoU", "0.75", "整体")}${metricCard("Precision", "0.88", "阳性预测")}${metricCard("Recall", "0.84", "敏感性")}</div><div class="grid cols-2" style="margin-top:18px"><section class="panel"><h2>质量雷达图</h2><div class="placeholder">Dice / IoU / Precision / Recall / HD95 / ASSD</div></section><section class="viewer"><h2>错误区域</h2><div class="ct-frame" style="min-height:300px"><div class="mask-overlay"></div><div class="roi-box"></div></div></section></div>`;
}

function renderExport() {
  return `<section class="panel"><div class="toolbar-row"><div class="field"><label>版本</label><select><option>final</option><option>v3_融合</option><option>v2_AI</option></select></div><div class="field"><label>格式</label><select><option>nnUNet</option><option>PNG</option><option>JSON</option><option>COCO</option><option>YOLO</option></select></div><button class="primary-button">导出 Dataset</button><button class="ghost-button">下载 ZIP</button></div></section><section class="table-wrap" style="margin-top:18px"><table><thead><tr><th>病例ID</th><th>图像路径</th><th>Mask路径</th><th>版本</th><th>数据划分</th></tr></thead><tbody><tr><td>Case0001</td><td>dataset/images/Case0001</td><td>dataset/labels/Case0001/final</td><td>final</td><td>train</td></tr></tbody></table></section>`;
}

function renderSettings() {
  return `<div class="grid cols-2"><section class="panel"><h2>标签管理</h2><div class="label-list">${labelList()}</div></section><section class="panel"><h2>系统路径</h2><div class="case-meta"><div class="meta-line"><span>原始数据</span><strong>dataset/raw</strong></div><div class="meta-line"><span>训练图像</span><strong>dataset/images</strong></div><div class="meta-line"><span>标签数据</span><strong>dataset/labels</strong></div><div class="meta-line"><span>数据划分</span><strong>dataset/splits</strong></div></div></section></div>`;
}

function render() {
  const views = { dashboard: renderDashboard, cases: renderCases, annotation: renderAnnotation, train: renderTrain, inference: renderInference, versions: renderVersions, quality: renderQuality, export: renderExport, settings: renderSettings };
  $("#viewRoot").innerHTML = (views[state.view] || renderDashboard)();
  const uploadForm = $("#uploadForm");
  if (uploadForm) uploadForm.addEventListener("submit", uploadCase);
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
    sliceSlider.addEventListener("input", () => {
      state.activeSlice = Number(sliceSlider.value);
      const image = activeImage();
      const meta = image ? state.volumeMeta[image.image_id] : null;
      if (image && meta) updateSliceViewer(image, meta);
    });
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
