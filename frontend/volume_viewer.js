const activeViewers = new WeakMap();
const API_BASE = window.location.port && window.location.port !== "8000" ? "http://127.0.0.1:8000" : "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

const RENDERING_PRESETS = [
  {
    id: "overview",
    label: "总览",
    mode: 0,
    wl: 40,
    ww: 400,
    opacity: 1.1,
    brightness: 1.08,
    threshold: 0.12,
    steps: 240,
    alphaStop: 0.96,
    opacityClamp: 0.125,
    ambient: 0.34,
    diffuse: 0.48,
    specular: 0.08,
    rim: 0.16,
    edgeStrength: 1.85,
    summary: "通用 CT 总览协议，使用中性灰阶显示整体空间关系和主要组织结构。",
  },
  {
    id: "soft",
    label: "软组织",
    mode: 4,
    wl: 40,
    ww: 80,
    opacity: 0.96,
    brightness: 1.06,
    threshold: 0.18,
    steps: 320,
    alphaStop: 0.982,
    opacityClamp: 0.070,
    ambient: 0.42,
    diffuse: 0.34,
    specular: 0.04,
    rim: 0.10,
    edgeStrength: 3.20,
    summary: "窄窗软组织协议，弱化高密度骨遮挡，突出实质软组织和高密度异常区域。",
  },
  {
    id: "bone",
    label: "骨窗",
    mode: 1,
    wl: 300,
    ww: 1800,
    opacity: 1.32,
    brightness: 1.20,
    threshold: 0.18,
    steps: 384,
    alphaStop: 0.995,
    opacityClamp: 0.095,
    ambient: 0.14,
    diffuse: 0.68,
    specular: 0.82,
    rim: 0.30,
    edgeStrength: 4.40,
    summary: "连续保留松质骨到骨皮质，降低采样步长并延迟终止，改善薄骨结构断裂。",
  },
];

const PRESET_BY_ID = new Map(RENDERING_PRESETS.map((preset) => [preset.id, preset]));

const CT_MESH_LAYER_STYLES = {
  body: {
    label: "外层",
    color: [0.36, 0.58, 0.72],
    alphaKey: "outerMeshAlpha",
    material: "outer",
  },
  lung: {
    label: "肺/低密度腔",
    color: [0.30, 0.70, 0.95],
    alphaKey: "lungMeshAlpha",
    material: "lung",
  },
  soft: {
    label: "软组织",
    color: [0.86, 0.62, 0.55],
    alphaKey: "innerMeshAlpha",
    material: "soft",
  },
  bone: {
    label: "骨性",
    color: [0.92, 0.88, 0.68],
    alphaKey: "boneMeshAlpha",
    material: "bone",
  },
};

function defaultPreset() {
  return RENDERING_PRESETS[0];
}

function decodeBase64ToUint8Array(value) {
  const binary = window.atob(value);
  const output = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    output[i] = binary.charCodeAt(i);
  }
  return output;
}

function hexToRgb01(hex) {
  const value = String(hex || "#00e5b0").replace("#", "").trim();
  const normalized = value.length === 3
    ? value.split("").map((part) => part + part).join("")
    : value.padEnd(6, "0").slice(0, 6);
  const number = Number.parseInt(normalized, 16);
  return [
    ((number >> 16) & 255) / 255,
    ((number >> 8) & 255) / 255,
    (number & 255) / 255,
  ];
}

const DEFAULT_LABEL_PALETTE = {
  0: [0.11, 0.16, 0.22],
  1: [0.0, 0.9, 0.69],       // liver
  2: [0.22, 0.64, 1.0],      // kidney
  3: [1.0, 0.69, 0.13],      // lung
  4: [1.0, 0.3, 0.31],       // tumor
  5: [0.71, 0.43, 1.0],      // spleen
  6: [0.49, 0.83, 0.99],     // pancreas
  7: [0.96, 0.62, 0.04],     // stomach
  8: [0.34, 0.8, 0.55],      // gallbladder
};

function buildLabelPalette(labelColors) {
  const palette = Array.from({ length: 16 }, (_, index) => DEFAULT_LABEL_PALETTE[index] || [0.0, 0.9, 0.69]);
  if (labelColors && typeof labelColors === "object") {
    for (const [key, value] of Object.entries(labelColors)) {
      const id = Number(key);
      if (!Number.isFinite(id) || id < 0 || id > 15) continue;
      if (Array.isArray(value) && value.length >= 3) {
        palette[id] = [Number(value[0]), Number(value[1]), Number(value[2])];
      } else if (typeof value === "string") {
        palette[id] = hexToRgb01(value);
      }
    }
  }
  return palette;
}

function rotateVecX(v, a) {
  const s = Math.sin(a);
  const c = Math.cos(a);
  return [v[0], c * v[1] - s * v[2], s * v[1] + c * v[2]];
}

function rotateVecY(v, a) {
  const s = Math.sin(a);
  const c = Math.cos(a);
  return [c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]];
}

function sampleMaskLabelId(maskData, maskValues, uvx, uvy, uvz) {
  if (!maskData || !maskValues) return 0;
  const [width, height, depth] = maskData.dimensions;
  const x = Math.max(0, Math.min(width - 1, Math.floor(uvx * width)));
  const y = Math.max(0, Math.min(height - 1, Math.floor(uvy * height)));
  const z = Math.max(0, Math.min(depth - 1, Math.floor(uvz * depth)));
  return maskValues[z * width * height + y * width + x] || 0;
}

function computeLabelFocus(maskData, maskValues, labelId) {
  if (!maskData || !maskValues || !labelId || !Array.isArray(maskData.dimensions)) {
    return null;
  }
  const [width, height, depth] = maskData.dimensions.map((value) => Number(value) || 0);
  if (!width || !height || !depth) return null;
  const multi =
    Boolean(maskData.multiclass) &&
    Array.isArray(maskData.unique_labels) &&
    maskData.unique_labels.length > 1;
  const voxelCount = width * height * depth;
  let stride = 1;
  if (voxelCount > 160 * 160 * 160) stride = 2;
  if (voxelCount > 240 * 240 * 180) stride = 3;

  let count = 0;
  let sumX = 0;
  let sumY = 0;
  let sumZ = 0;
  let minX = 1;
  let minY = 1;
  let minZ = 1;
  let maxX = 0;
  let maxY = 0;
  let maxZ = 0;

  for (let z = 0; z < depth; z += stride) {
    const zBase = z * width * height;
    for (let y = 0; y < height; y += stride) {
      const yBase = zBase + y * width;
      for (let x = 0; x < width; x += stride) {
        const raw = maskValues[yBase + x] | 0;
        if (!raw) continue;
        const id = multi ? raw : 1;
        if (id !== labelId) continue;
        const nx = (x + 0.5) / width;
        const ny = (y + 0.5) / height;
        const nz = (z + 0.5) / depth;
        sumX += nx;
        sumY += ny;
        sumZ += nz;
        count += 1;
        if (nx < minX) minX = nx;
        if (ny < minY) minY = ny;
        if (nz < minZ) minZ = nz;
        if (nx > maxX) maxX = nx;
        if (ny > maxY) maxY = ny;
        if (nz > maxZ) maxZ = nz;
      }
    }
  }
  if (!count) return null;
  const extent = Math.max(maxX - minX, maxY - minY, maxZ - minZ, 0.04);
  return {
    center: [sumX / count, sumY / count, sumZ / count],
    extent,
    count,
  };
}

function pickMaskLabelAtCursor(maskData, maskValues, viewerState, canvas, nx, ny) {
  if (!maskData || !maskValues || !canvas) return 0;
  const aspect = canvas.width / Math.max(canvas.height, 1);
  const screenX = (nx * 2 - 1) * aspect;
  const screenY = -(ny * 2 - 1);
  const camDist = Math.max(viewerState.camDist || 1.65, 0.35);
  const screenScale = 0.84 * (camDist / 1.65);
  const focus = viewerState.focusCenter || [0.5, 0.5, 0.5];
  let origin = [screenX * screenScale, screenY * screenScale, -camDist];
  let dir = [0, 0, 1];
  // Match shader: invRotation = transpose(rotateY * rotateX) applied to camera space.
  // Equivalent: apply rotateX then rotateY to vectors in reverse of forward rotation.
  origin = rotateVecX(origin, viewerState.pitch);
  origin = rotateVecY(origin, viewerState.yaw);
  dir = rotateVecX(dir, viewerState.pitch);
  dir = rotateVecY(dir, viewerState.yaw);
  const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
  dir = [dir[0] / len, dir[1] / len, dir[2] / len];
  origin = [origin[0] + focus[0], origin[1] + focus[1], origin[2] + focus[2]];

  // Ray-box intersection on unit cube.
  let tNear = 0;
  let tFar = 1e9;
  for (let axis = 0; axis < 3; axis += 1) {
    if (Math.abs(dir[axis]) < 1e-6) {
      if (origin[axis] < 0 || origin[axis] > 1) return 0;
      continue;
    }
    let t0 = (0 - origin[axis]) / dir[axis];
    let t1 = (1 - origin[axis]) / dir[axis];
    if (t0 > t1) [t0, t1] = [t1, t0];
    tNear = Math.max(tNear, t0);
    tFar = Math.min(tFar, t1);
    if (tFar < tNear) return 0;
  }
  tNear = Math.max(tNear, 0);
  const steps = 160;
  const dt = (tFar - tNear) / steps;
  let best = 0;
  for (let i = 0; i < steps; i += 1) {
    const t = tNear + (i + 0.5) * dt;
    const p = [origin[0] + dir[0] * t, origin[1] + dir[1] * t, origin[2] + dir[2] * t];
    const raw = sampleMaskLabelId(maskData, maskValues, p[0], p[1], p[2]);
    if (!raw) continue;
    const multi =
      Boolean(maskData.multiclass) &&
      Array.isArray(maskData.unique_labels) &&
      maskData.unique_labels.length > 1;
    const labelId = multi ? raw : 1;
    if (labelId > 0) {
      best = labelId;
      // Prefer first hit from camera (near surface).
      break;
    }
  }
  return best;
}

async function loadLabelNameMap() {
  try {
    const response = await fetch(apiUrl("/api/labels?include_background=true&enabled_only=false"));
    if (!response.ok) return {};
    const data = await response.json();
    const map = {};
    for (const item of data.items || []) {
      map[item.label_id] = item.display_name || item.name || `label_${item.label_id}`;
    }
    map[0] = "背景";
    return map;
  } catch {
    return {
      0: "背景",
      1: "肝脏",
      2: "肾脏",
      3: "肺部",
      4: "肿瘤",
      5: "脾脏",
    };
  }
}

function isMaskSurfaceVoxel(values, width, height, depth, x, y, z) {
  const index = z * width * height + y * width + x;
  if (!values[index]) return false;
  return (
    x === 0 || x === width - 1 ||
    y === 0 || y === height - 1 ||
    z === 0 || z === depth - 1 ||
    !values[index - 1] ||
    !values[index + 1] ||
    !values[index - width] ||
    !values[index + width] ||
    !values[index - width * height] ||
    !values[index + width * height]
  );
}

function hasMaskThicknessSupport(values, width, height, depth, x, y, z) {
  const index = z * width * height + y * width + x;
  if (!values[index]) return false;
  const area = width * height;
  const zMinus2 = z >= 2 && values[index - area * 2];
  const zPlus2 = z < depth - 2 && values[index + area * 2];
  const zMinus3 = z >= 3 && values[index - area * 3];
  const zPlus3 = z < depth - 3 && values[index + area * 3];
  if (!(zMinus2 || zPlus2 || zMinus3 || zPlus3)) {
    return false;
  }

  let support = 0;
  for (let dz = -2; dz <= 2; dz += 1) {
    const zz = z + dz;
    if (zz < 0 || zz >= depth) continue;
    for (let dy = -1; dy <= 1; dy += 1) {
      const yy = y + dy;
      if (yy < 0 || yy >= height) continue;
      for (let dx = -1; dx <= 1; dx += 1) {
        const xx = x + dx;
        if (xx < 0 || xx >= width) continue;
        if (values[zz * area + yy * width + xx]) support += 1;
      }
    }
  }
  return support >= 12;
}

function huFromTextureValue(value, huRange) {
  const low = Number(huRange?.[0] ?? -1000);
  const high = Number(huRange?.[1] ?? 1800);
  return low + (high - low) * (Number(value) / 255);
}

function hasNearbyBodySignal(volumeData, volumeValues, width, height, depth, x, y, z) {
  if (!volumeData || !volumeValues || !Array.isArray(volumeData.dimensions)) {
    return true;
  }
  if (
    volumeData.dimensions[0] !== width ||
    volumeData.dimensions[1] !== height ||
    volumeData.dimensions[2] !== depth
  ) {
    return true;
  }
  const huRange = Array.isArray(volumeData.hu_range) ? volumeData.hu_range : [-1000, 1800];
  const offsets = [
    [0, 0, 0],
    [4, 0, 0], [-4, 0, 0],
    [0, 4, 0], [0, -4, 0],
    [0, 0, 3], [0, 0, -3],
    [7, 0, 0], [-7, 0, 0],
    [0, 7, 0], [0, -7, 0],
    [0, 0, 5], [0, 0, -5],
  ];
  for (const [dx, dy, dz] of offsets) {
    const sx = Math.max(0, Math.min(width - 1, x + dx));
    const sy = Math.max(0, Math.min(height - 1, y + dy));
    const sz = Math.max(0, Math.min(depth - 1, z + dz));
    const hu = huFromTextureValue(volumeValues[sz * width * height + sy * width + sx], huRange);
    if (hu > -700) {
      return true;
    }
  }
  return false;
}

function createMaskSurfacePoints(maskData, maskValues, options = {}) {
  const maxPoints = options.maxPoints || 140000;
  if (!maskData || !maskValues || !Array.isArray(maskData.dimensions)) {
    return new Float32Array();
  }
  const [width, height, depth] = maskData.dimensions.map((value) => Number(value) || 0);
  if (!width || !height || !depth) return new Float32Array();

  const candidates = [];
  let stride = 1;
  const voxelCount = width * height * depth;
  if (voxelCount > 180 * 180 * 180) stride = 2;
  if (voxelCount > 260 * 260 * 180) stride = 3;

  for (let z = 0; z < depth; z += stride) {
    for (let y = 0; y < height; y += stride) {
      for (let x = 0; x < width; x += stride) {
        if (
          isMaskSurfaceVoxel(maskValues, width, height, depth, x, y, z) &&
          hasMaskThicknessSupport(maskValues, width, height, depth, x, y, z) &&
          hasNearbyBodySignal(options.volumeData, options.volumeValues, width, height, depth, x, y, z)
        ) {
          candidates.push((x + 0.5) / width, (y + 0.5) / height, (z + 0.5) / depth);
        }
      }
    }
  }

  if (candidates.length / 3 <= maxPoints) {
    return new Float32Array(candidates);
  }
  const output = new Float32Array(maxPoints * 3);
  const step = Math.ceil(candidates.length / 3 / maxPoints);
  let cursor = 0;
  for (let point = 0; point < candidates.length / 3 && cursor < output.length; point += step) {
    output[cursor++] = candidates[point * 3];
    output[cursor++] = candidates[point * 3 + 1];
    output[cursor++] = candidates[point * 3 + 2];
  }
  return output.subarray(0, cursor);
}

function normalizeMeshPayload(meshData) {
  if (!meshData || !Array.isArray(meshData.positions) || !Array.isArray(meshData.indices)) {
    return null;
  }
  if (meshData.positions.length < 9 || meshData.indices.length < 3) {
    return null;
  }
  return {
    ...meshData,
    positionsArray: new Float32Array(meshData.positions),
    normalsArray: Array.isArray(meshData.normals) && meshData.normals.length === meshData.positions.length
      ? new Float32Array(meshData.normals)
      : new Float32Array(meshData.positions.length),
    indicesArray: new Uint32Array(meshData.indices),
  };
}

function clearContainer(container) {
  const previous = activeViewers.get(container);
  if (previous) {
    previous.delete();
    activeViewers.delete(container);
  }
  container.replaceChildren();
}

export async function renderVolume3D({
  container,
  imageId,
  maskId = null,
  windowName = "volume",
  maxDim = 176,
  isotropic = true,
  highlightMask = false,
  labelColors = null,
}) {
  if (!container || !imageId) return;
  clearContainer(container);

  const status = document.createElement("div");
  status.className = "volume-status";
  status.textContent = "正在读取真实 3D CT 体数据...";
  container.appendChild(status);

  const response = await fetchVolumeData({ imageId, maxDim, windowName, isotropic });

  const volumeData = await response.json();
  const values = decodeBase64ToUint8Array(volumeData.values_base64);
  status.textContent = "正在提取 VTK CT 内外表面网格...";
  const ctMeshRequests = [
    { protocol: "body", query: `protocol=body&max_dim=${maxDim}&min_component_voxels=2000&max_components=1&max_triangles=70000&target_reduction=0.45&smooth_iterations=12` },
    { protocol: "lung", query: `protocol=lung&max_dim=${maxDim}&min_component_voxels=900&max_components=4&max_triangles=70000&target_reduction=0.46&smooth_iterations=12` },
    { protocol: "soft", query: `protocol=soft&max_dim=${maxDim}&min_component_voxels=1200&max_components=8&max_triangles=110000&target_reduction=0.42&smooth_iterations=14` },
    { protocol: "bone", query: `protocol=bone&max_dim=${maxDim}&min_component_voxels=512&max_components=3&max_triangles=110000&target_reduction=0.38&smooth_iterations=14` },
  ];
  const ctMeshes = (await Promise.all(ctMeshRequests.map(async (request) => {
    const ctMeshResponse = await fetch(apiUrl(`/api/image/${imageId}/surface-mesh?${request.query}`));
    if (!ctMeshResponse.ok) {
      const message = await ctMeshResponse.text();
      console.warn(`VTK CT ${request.protocol} mesh unavailable:`, message);
      return null;
    }
    const mesh = normalizeMeshPayload(await ctMeshResponse.json());
    return mesh ? { ...mesh, layer: request.protocol } : null;
  }))).filter(Boolean);
  let maskData = null;
  let maskValues = null;
  let maskMesh = null;
  if (maskId) {
    status.textContent = "正在读取 3D Mask 实体数据...";
    const maskResponse = await fetch(apiUrl(`/api/mask/${maskId}/volume-data?max_dim=${maxDim}`));
    if (!maskResponse.ok) {
      const message = await maskResponse.text();
      throw new Error(`3D Mask 接口失败：${message}`);
    }
    maskData = await maskResponse.json();
    maskValues = decodeBase64ToUint8Array(maskData.values_base64);

    status.textContent = "正在提取 VTK Mask 表面网格...";
    const meshQuery = "min_component_voxels=96&max_components=8&max_triangles=90000&target_reduction=0.45&smooth_iterations=10&remove_thin=true&constrain_to_body=true&constrain_to_source_roi=true&source_roi_margin_mm=45";
    const meshResponse = await fetch(apiUrl(`/api/mask/${maskId}/surface-mesh?${meshQuery}`));
    if (meshResponse.ok) {
      maskMesh = normalizeMeshPayload(await meshResponse.json());
    } else {
      const message = await meshResponse.text();
      console.warn("VTK mask surface mesh unavailable, fallback to WebGL point surface:", message);
    }
  }

  status.textContent = "正在初始化 VTK 综合 3D 渲染...";
  renderWithWebGL({
    container,
    volumeData,
    values,
    ctMeshes,
    maskData,
    maskValues,
    maskMesh,
    highlightMask,
    labelColors,
  });
}

async function fetchVolumeData({ imageId, maxDim, windowName, isotropic }) {
  const query = `max_dim=${maxDim}&window=${windowName}&isotropic=${isotropic ? "true" : "false"}`;
  const primary = await fetch(apiUrl(`/api/image/${imageId}/volume-data?${query}`));
  if (primary.ok) return primary;
  if (primary.status !== 404) {
    const message = await primary.text();
    throw new Error(`体数据接口失败：${message}`);
  }

  const legacy = await fetch(apiUrl(`/api/image/${imageId}/vtk-volume?${query}`));
  if (legacy.ok) return legacy;
  const message = await legacy.text();
  throw new Error(`体数据接口失败：${message}`);
}

function createShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`WebGL shader 编译失败：${message}`);
  }
  return shader;
}

function createProgram(gl, vertexSource, fragmentSource) {
  const vertexShader = createShader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  gl.deleteShader(vertexShader);
  gl.deleteShader(fragmentShader);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`WebGL program 链接失败：${message}`);
  }
  return program;
}

function renderWithWebGL({
  container,
  volumeData,
  values,
  ctMeshes = [],
  maskData = null,
  maskValues = null,
  maskMesh = null,
  highlightMask = false,
  labelColors = null,
}) {
  clearContainer(container);

  const canvas = document.createElement("canvas");
  canvas.className = "webgl-volume-canvas";
  container.appendChild(canvas);

  const badge = document.createElement("div");
  badge.className = "volume-engine-badge";
  badge.textContent = "3D 医学渲染";
  container.appendChild(badge);

  const gl = canvas.getContext("webgl2", {
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: false,
  });
  if (!gl) {
    throw new Error("当前浏览器不支持 WebGL2，无法进行本地 3D 体渲染。");
  }

  const vertexSource = `#version 300 es
    in vec2 aPosition;
    out vec2 vUv;
    void main() {
      vUv = aPosition * 0.5 + 0.5;
      gl_Position = vec4(aPosition, 0.0, 1.0);
    }
  `;

  const fragmentSource = `#version 300 es
    precision highp float;
    precision highp sampler3D;

    in vec2 vUv;
    out vec4 outColor;

    uniform sampler3D uVolume;
    uniform sampler3D uMask;
    uniform bool uHasMask;
    uniform float uYaw;
    uniform float uPitch;
    uniform float uAspect;
    uniform float uSteps;
    uniform float uOpacityScale;
    uniform float uBrightness;
    uniform float uThreshold;
    uniform float uHuLow;
    uniform float uHuHigh;
    uniform float uAmbient;
    uniform float uDiffuse;
    uniform float uSpecular;
    uniform float uRim;
    uniform float uEdgeStrength;
    uniform float uAlphaStop;
    uniform float uOpacityClamp;
    uniform vec3 uMaskColor;
    uniform float uMaskAlpha;
    uniform vec3 uVoxelStep;
    uniform int uRenderMode;
    uniform float uCamDist;
    uniform bool uMulticlass;
    uniform vec3 uPalette[16];
    uniform int uIsolateLabel;
    uniform vec3 uFocus;

    mat3 rotateX(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c);
    }

    mat3 rotateY(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
    }

    vec3 colorForLabel(float maskNorm) {
      if (!uMulticlass) {
        return uMaskColor;
      }
      int id = int(maskNorm * 255.0 + 0.5);
      if (id <= 0) {
        return uMaskColor;
      }
      if (id > 15) {
        id = 1 + (id % 15);
      }
      return uPalette[id];
    }

    bool intersectBox(vec3 origin, vec3 dir, out float nearHit, out float farHit) {
      vec3 invDir = 1.0 / dir;
      vec3 t0 = (vec3(0.0) - origin) * invDir;
      vec3 t1 = (vec3(1.0) - origin) * invDir;
      vec3 tmin = min(t0, t1);
      vec3 tmax = max(t0, t1);
      nearHit = max(max(tmin.x, tmin.y), tmin.z);
      farHit = min(min(tmax.x, tmax.y), tmax.z);
      return farHit > max(nearHit, 0.0);
    }

    vec3 gradientAt(vec3 p) {
      vec3 delta = uVoxelStep;
      float gx = texture(uVolume, p + vec3(delta.x, 0.0, 0.0)).r - texture(uVolume, p - vec3(delta.x, 0.0, 0.0)).r;
      float gy = texture(uVolume, p + vec3(0.0, delta.y, 0.0)).r - texture(uVolume, p - vec3(0.0, delta.y, 0.0)).r;
      float gz = texture(uVolume, p + vec3(0.0, 0.0, delta.z)).r - texture(uVolume, p - vec3(0.0, 0.0, delta.z)).r;
      return vec3(gx, gy, gz);
    }

    float huFromValue(float value) {
      return mix(uHuLow, uHuHigh, value);
    }

    float sampleHu(vec3 p) {
      return huFromValue(texture(uVolume, clamp(p, vec3(0.0), vec3(1.0))).r);
    }

    float band(float hu, float low, float high, float feather) {
      return smoothstep(low, low + feather, hu) * (1.0 - smoothstep(high - feather, high, hu));
    }

    float localContrastAt(vec3 p) {
      vec3 d1 = uVoxelStep * 1.5;
      vec3 d2 = uVoxelStep * 3.0;
      float center = sampleHu(p);
      float n1 =
        abs(center - sampleHu(p + vec3(d1.x, 0.0, 0.0))) +
        abs(center - sampleHu(p - vec3(d1.x, 0.0, 0.0))) +
        abs(center - sampleHu(p + vec3(0.0, d1.y, 0.0))) +
        abs(center - sampleHu(p - vec3(0.0, d1.y, 0.0))) +
        abs(center - sampleHu(p + vec3(0.0, 0.0, d1.z))) +
        abs(center - sampleHu(p - vec3(0.0, 0.0, d1.z)));
      float n2 =
        abs(center - sampleHu(p + vec3(d2.x, 0.0, 0.0))) +
        abs(center - sampleHu(p - vec3(d2.x, 0.0, 0.0))) +
        abs(center - sampleHu(p + vec3(0.0, d2.y, 0.0))) +
        abs(center - sampleHu(p - vec3(0.0, d2.y, 0.0))) +
        abs(center - sampleHu(p + vec3(0.0, 0.0, d2.z))) +
        abs(center - sampleHu(p - vec3(0.0, 0.0, d2.z)));
      return smoothstep(30.0, 180.0, (n1 * 0.70 + n2 * 0.30) / 6.0);
    }

    float maskAt(vec3 p) {
      float m = texture(uMask, clamp(p, vec3(0.0), vec3(1.0))).r;
      vec3 d = uVoxelStep * 1.35;
      m = max(m, texture(uMask, clamp(p + vec3(d.x, 0.0, 0.0), vec3(0.0), vec3(1.0))).r);
      m = max(m, texture(uMask, clamp(p - vec3(d.x, 0.0, 0.0), vec3(0.0), vec3(1.0))).r);
      m = max(m, texture(uMask, clamp(p + vec3(0.0, d.y, 0.0), vec3(0.0), vec3(1.0))).r);
      m = max(m, texture(uMask, clamp(p - vec3(0.0, d.y, 0.0), vec3(0.0), vec3(1.0))).r);
      m = max(m, texture(uMask, clamp(p + vec3(0.0, 0.0, d.z), vec3(0.0), vec3(1.0))).r);
      m = max(m, texture(uMask, clamp(p - vec3(0.0, 0.0, d.z), vec3(0.0), vec3(1.0))).r);
      return m;
    }

    float maskThicknessAt(vec3 p) {
      float center = texture(uMask, clamp(p, vec3(0.0), vec3(1.0))).r;
      if (center < 0.001) {
        return 0.0;
      }
      vec3 dz2 = vec3(0.0, 0.0, uVoxelStep.z * 2.2);
      vec3 dz3 = vec3(0.0, 0.0, uVoxelStep.z * 3.2);
      float zSupport = max(
        max(texture(uMask, clamp(p + dz2, vec3(0.0), vec3(1.0))).r, texture(uMask, clamp(p - dz2, vec3(0.0), vec3(1.0))).r),
        max(texture(uMask, clamp(p + dz3, vec3(0.0), vec3(1.0))).r, texture(uMask, clamp(p - dz3, vec3(0.0), vec3(1.0))).r)
      );
      vec3 dxy = uVoxelStep * vec3(1.7, 1.7, 0.0);
      float xySupport =
        texture(uMask, clamp(p + vec3(dxy.x, 0.0, 0.0), vec3(0.0), vec3(1.0))).r +
        texture(uMask, clamp(p - vec3(dxy.x, 0.0, 0.0), vec3(0.0), vec3(1.0))).r +
        texture(uMask, clamp(p + vec3(0.0, dxy.y, 0.0), vec3(0.0), vec3(1.0))).r +
        texture(uMask, clamp(p - vec3(0.0, dxy.y, 0.0), vec3(0.0), vec3(1.0))).r;
      return smoothstep(0.10, 0.90, zSupport) * smoothstep(0.25, 1.50, xySupport);
    }

    vec3 transferColor(float hu, float edge) {
      if (uRenderMode == 1) {
        vec3 cancellous = vec3(0.68, 0.58, 0.42);
        vec3 trabecular = vec3(0.90, 0.82, 0.64);
        vec3 cortical = vec3(1.0, 0.97, 0.86);
        vec3 c = mix(cancellous, trabecular, smoothstep(140.0, 520.0, hu));
        c = mix(c, cortical, smoothstep(620.0, 1600.0, hu));
        return mix(c, vec3(1.0), edge * 0.32);
      }
      if (uRenderMode == 2) {
        vec3 air = vec3(0.05, 0.09, 0.13);
        vec3 interfaceColor = vec3(0.34, 0.70, 0.84);
        vec3 airwayColor = vec3(0.58, 0.88, 0.92);
        vec3 vesselColor = vec3(0.90, 0.97, 0.96);
        vec3 pleuraColor = vec3(0.80, 0.96, 1.0);
        vec3 c = mix(air, interfaceColor, edge);
        c = mix(c, airwayColor, band(hu, -880.0, -180.0, 180.0) * edge);
        c = mix(c, vesselColor, band(hu, -220.0, 300.0, 120.0));
        c = mix(c, pleuraColor, edge * smoothstep(-760.0, -260.0, hu));
        return c;
      }
      if (uRenderMode == 3) {
        vec3 background = vec3(0.02, 0.04, 0.06);
        vec3 vesselCore = vec3(0.88, 0.97, 0.98);
        vec3 vesselWall = vec3(0.42, 0.78, 0.86);
        vec3 dense = vec3(1.0, 0.90, 0.74);
        vec3 c = mix(background, vesselWall, smoothstep(-260.0, -80.0, hu));
        c = mix(c, vesselCore, smoothstep(-60.0, 180.0, hu));
        c = mix(c, dense, smoothstep(260.0, 700.0, hu));
        return mix(c, vec3(1.0), edge * 0.18);
      }
      if (uRenderMode == 4) {
        vec3 csf = vec3(0.20, 0.25, 0.30);
        vec3 grayMatter = vec3(0.62, 0.66, 0.68);
        vec3 blood = vec3(0.95, 0.90, 0.82);
        vec3 c = mix(csf, grayMatter, smoothstep(18.0, 48.0, hu));
        c = mix(c, blood, smoothstep(58.0, 92.0, hu));
        return mix(c, vec3(1.0), edge * 0.10);
      }
      vec3 fat = vec3(0.48, 0.49, 0.46);
      vec3 muscle = vec3(0.62, 0.64, 0.64);
      vec3 vessel = vec3(0.82, 0.86, 0.86);
      vec3 bone = vec3(0.76, 0.76, 0.72);
      vec3 c = mix(fat, muscle, smoothstep(-70.0, 85.0, hu));
      c = mix(c, vessel, smoothstep(90.0, 260.0, hu));
      c = mix(c, bone, smoothstep(320.0, 950.0, hu));
      return mix(c, vec3(0.92, 0.96, 0.96), edge * 0.11);
    }

    float transferOpacity(float hu, float edge) {
      if (uRenderMode == 1) {
        float floorHu = mix(80.0, 420.0, uThreshold);
        if (hu < floorHu) {
          return 0.0;
        }
        float cancellous = band(hu, 120.0, 470.0, 90.0) * 0.026;
        float trabecular = smoothstep(180.0, 760.0, hu) * (1.0 - smoothstep(1450.0, 2600.0, hu)) * 0.044;
        float cortical = smoothstep(520.0, 1550.0, hu) * 0.068;
        float denseEdge = edge * smoothstep(110.0, 520.0, hu) * 0.058;
        return (cancellous + trabecular + cortical + denseEdge) * uOpacityScale;
      }
      if (uRenderMode == 2) {
        if (hu < -980.0) {
          return 0.0;
        }
        float alveoli = band(hu, -930.0, -650.0, 90.0) * 0.00015;
        float airTissueInterface = edge * band(hu, -960.0, -360.0, 150.0) * 0.052;
        float airwayWall = edge * band(hu, -900.0, -180.0, 170.0) * 0.048;
        float vessel = band(hu, -230.0, 310.0, 105.0) * (0.020 + edge * 0.044);
        float pleura = edge * smoothstep(-860.0, -300.0, hu) * (1.0 - smoothstep(260.0, 700.0, hu)) * 0.058;
        float boneReject = 1.0 - smoothstep(300.0, 850.0, hu) * 0.96;
        return (alveoli + airTissueInterface + airwayWall + vessel + pleura) * boneReject * uOpacityScale;
      }
      if (uRenderMode == 3) {
        float vesselCore = band(hu, -180.0, 320.0, 95.0) * 0.070;
        float vesselEdge = edge * band(hu, -300.0, 360.0, 125.0) * 0.050;
        float hilum = smoothstep(40.0, 300.0, hu) * (1.0 - smoothstep(600.0, 1100.0, hu)) * 0.030;
        float boneReject = 1.0 - smoothstep(520.0, 980.0, hu) * 0.88;
        return (vesselCore + vesselEdge + hilum) * boneReject * uOpacityScale;
      }
      if (uRenderMode == 4) {
        float brainTissue = band(hu, 18.0, 62.0, 12.0) * 0.038;
        float grayWhiteEdge = edge * band(hu, 16.0, 72.0, 18.0) * 0.030;
        float hyperdense = smoothstep(62.0, 96.0, hu) * (1.0 - smoothstep(150.0, 260.0, hu)) * 0.048;
        float skullReject = 1.0 - smoothstep(180.0, 420.0, hu) * 0.96;
        return (brainTissue + grayWhiteEdge + hyperdense) * skullReject * uOpacityScale;
      }

      float floorHu = mix(-260.0, 90.0, uThreshold);
      if (hu < floorHu) {
        return 0.0;
      }
      float fat = band(hu, -180.0, -25.0, 45.0) * 0.007;
      float muscle = band(hu, -20.0, 115.0, 42.0) * 0.026;
      float vessel = band(hu, 90.0, 330.0, 70.0) * 0.044;
      float bone = smoothstep(300.0, 1100.0, hu) * 0.006;
      float gradientBoost = mix(0.60, 1.70, edge);
      return (fat + muscle + vessel + bone + edge * 0.008) * gradientBoost * uOpacityScale;
    }

    vec3 applyLighting(vec3 color, vec3 gradient, vec3 rayDir, float edge) {
      float gradientLength = length(gradient);
      if (gradientLength < 0.0001) {
        return color * 0.82;
      }

      vec3 normal = normalize(gradient);
      if (dot(normal, -rayDir) < 0.0) {
        normal = -normal;
      }
      vec3 lightDir = normalize(vec3(-0.45, 0.60, -0.66));
      vec3 viewDir = normalize(-rayDir);
      float diffuse = max(dot(normal, lightDir), 0.0);
      float rim = pow(1.0 - max(dot(normal, viewDir), 0.0), 2.2);
      float specular = pow(max(dot(reflect(-lightDir, normal), viewDir), 0.0), 28.0) * edge;
      vec3 lit = color * (uAmbient + uDiffuse * diffuse + uRim * rim);
      return lit + vec3(1.0, 0.94, 0.82) * specular * uSpecular;
    }

    void main() {
      vec2 screen = vUv * 2.0 - 1.0;
      screen.x *= uAspect;

      mat3 invRotation = transpose(rotateY(uYaw) * rotateX(uPitch));
      float camDist = max(uCamDist, 0.35);
      float screenScale = 0.84 * (camDist / 1.65);
      vec3 rayOrigin = invRotation * vec3(screen * screenScale, -camDist) + uFocus;
      vec3 rayDir = normalize(invRotation * vec3(0.0, 0.0, 1.0));

      float nearHit;
      float farHit;
      if (!intersectBox(rayOrigin, rayDir, nearHit, farHit)) {
        outColor = vec4(0.01, 0.025, 0.045, 1.0);
        return;
      }

      nearHit = max(nearHit, 0.0);
      float distance = farHit - nearHit;
      float dt = distance / uSteps;
      vec3 color = vec3(0.0);
      float alpha = 0.0;
      vec3 maskColorAccum = vec3(0.0);
      float maskAlphaAccum = 0.0;

      for (int i = 0; i < 448; i++) {
        if (float(i) >= uSteps || (!uHasMask && alpha > uAlphaStop)) {
          break;
        }
        vec3 p = rayOrigin + rayDir * (nearHit + (float(i) + 0.5) * dt);
        float value = texture(uVolume, p).r;
        float hu = huFromValue(value);
        vec3 gradient = gradientAt(p);
        float edge = smoothstep(0.018, 0.145, length(gradient) * uEdgeStrength);
        if (uRenderMode == 2) {
          edge = max(edge, localContrastAt(p) * 0.62);
        }
        float opacity = clamp(transferOpacity(hu, edge), 0.0, uOpacityClamp);
        vec3 sampleColor = applyLighting(transferColor(hu, edge), gradient, rayDir, edge);
        if (uHasMask) {
          float maskValue = maskAt(p);
          float maskThickness = maskThicknessAt(p);
          if (uIsolateLabel > 0 && uMulticlass) {
            int id = int(maskValue * 255.0 + 0.5);
            if (id != uIsolateLabel) {
              maskValue = 0.0;
              maskThickness = 0.0;
            }
          }
          if (maskValue > 0.001 && maskThickness > 0.02) {
            vec3 maskCore = colorForLabel(maskValue);
            vec3 maskRim = mix(maskCore, vec3(1.0, 0.95, 0.20), 0.35);
            float maskEdge = smoothstep(0.12, 0.70, length(gradient) * 3.2);
            vec3 maskSampleColor = mix(maskCore, maskRim, maskEdge);
            float maskAlpha = mix(uMaskAlpha * 0.25, uMaskAlpha, clamp(maskValue * maskThickness, 0.0, 1.0));
            if (uMulticlass) {
              // Class ids are small (1/255..), boost presence so thin organs stay visible.
              maskAlpha = mix(uMaskAlpha * 0.35, uMaskAlpha, clamp(maskThickness, 0.0, 1.0));
            }
            maskColorAccum += (1.0 - maskAlphaAccum) * maskAlpha * maskSampleColor;
            maskAlphaAccum += (1.0 - maskAlphaAccum) * maskAlpha;
            sampleColor = mix(sampleColor, maskSampleColor, 0.72 * maskThickness);
            opacity = max(opacity, 0.065 * maskThickness);
          }
        }
        color += (1.0 - alpha) * opacity * sampleColor;
        alpha += (1.0 - alpha) * opacity;
      }

      vec3 background = vec3(0.01, 0.025, 0.045);
      color *= uBrightness;
      vec3 finalColor = mix(background, color, min(alpha * 1.45, 1.0));
      if (uHasMask && maskAlphaAccum > 0.01) {
        finalColor = mix(finalColor, maskColorAccum, min(maskAlphaAccum * 1.55, 0.92));
      }
      outColor = vec4(finalColor, 1.0);
    }
  `;

  const program = createProgram(gl, vertexSource, fragmentSource);
  const positionLocation = gl.getAttribLocation(program, "aPosition");
  const uniforms = {
    volume: gl.getUniformLocation(program, "uVolume"),
    mask: gl.getUniformLocation(program, "uMask"),
    hasMask: gl.getUniformLocation(program, "uHasMask"),
    yaw: gl.getUniformLocation(program, "uYaw"),
    pitch: gl.getUniformLocation(program, "uPitch"),
    aspect: gl.getUniformLocation(program, "uAspect"),
    steps: gl.getUniformLocation(program, "uSteps"),
    opacityScale: gl.getUniformLocation(program, "uOpacityScale"),
    brightness: gl.getUniformLocation(program, "uBrightness"),
    threshold: gl.getUniformLocation(program, "uThreshold"),
    huLow: gl.getUniformLocation(program, "uHuLow"),
    huHigh: gl.getUniformLocation(program, "uHuHigh"),
    ambient: gl.getUniformLocation(program, "uAmbient"),
    diffuse: gl.getUniformLocation(program, "uDiffuse"),
    specular: gl.getUniformLocation(program, "uSpecular"),
    rim: gl.getUniformLocation(program, "uRim"),
    edgeStrength: gl.getUniformLocation(program, "uEdgeStrength"),
    alphaStop: gl.getUniformLocation(program, "uAlphaStop"),
    opacityClamp: gl.getUniformLocation(program, "uOpacityClamp"),
    maskColor: gl.getUniformLocation(program, "uMaskColor"),
    maskAlpha: gl.getUniformLocation(program, "uMaskAlpha"),
    voxelStep: gl.getUniformLocation(program, "uVoxelStep"),
    renderMode: gl.getUniformLocation(program, "uRenderMode"),
    camDist: gl.getUniformLocation(program, "uCamDist"),
    multiclass: gl.getUniformLocation(program, "uMulticlass"),
    palette: gl.getUniformLocation(program, "uPalette"),
    isolateLabel: gl.getUniformLocation(program, "uIsolateLabel"),
    focus: gl.getUniformLocation(program, "uFocus"),
  };

  const vertexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
    gl.STATIC_DRAW
  );

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_3D, texture);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage3D(
    gl.TEXTURE_3D,
    0,
    gl.R8,
    volumeData.dimensions[0],
    volumeData.dimensions[1],
    volumeData.dimensions[2],
    0,
    gl.RED,
    gl.UNSIGNED_BYTE,
    values
  );

  let maskTexture = null;
  const maskDimensionsMatch = Boolean(
    maskData &&
    maskValues &&
    Array.isArray(maskData.dimensions) &&
    maskData.dimensions[0] === volumeData.dimensions[0] &&
    maskData.dimensions[1] === volumeData.dimensions[1] &&
    maskData.dimensions[2] === volumeData.dimensions[2]
  );
  if (maskDimensionsMatch) {
    maskTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_3D, maskTexture);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage3D(
      gl.TEXTURE_3D,
      0,
      gl.R8,
      maskData.dimensions[0],
      maskData.dimensions[1],
      maskData.dimensions[2],
      0,
      gl.RED,
      gl.UNSIGNED_BYTE,
      maskValues
    );
  }

  const surfaceVertexSource = `#version 300 es
    in vec3 aMaskPosition;
    uniform float uYaw;
    uniform float uPitch;
    uniform float uAspect;
    uniform float uPointSize;
    uniform vec3 uFocus;
    out float vDepthShade;

    mat3 rotateX(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c);
    }

    mat3 rotateY(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
    }

    void main() {
      vec3 centered = aMaskPosition - uFocus;
      vec3 rotated = rotateY(uYaw) * rotateX(uPitch) * centered;
      vec2 screen = rotated.xy / 0.42;
      screen.x /= max(uAspect, 0.001);
      gl_Position = vec4(screen, 0.15 + rotated.z * 0.55, 1.0);
      gl_PointSize = uPointSize * (1.12 - rotated.z * 0.35);
      vDepthShade = clamp(0.68 + rotated.z * 0.65, 0.35, 1.20);
    }
  `;

  const surfaceFragmentSource = `#version 300 es
    precision highp float;
    uniform vec3 uColor;
    uniform float uAlpha;
    in float vDepthShade;
    out vec4 outColor;

    void main() {
      vec2 p = gl_PointCoord * 2.0 - 1.0;
      float r = dot(p, p);
      if (r > 1.0) {
        discard;
      }
      float edge = smoothstep(1.0, 0.18, r);
      vec3 color = mix(uColor, vec3(1.0, 0.96, 0.35), 0.20) * vDepthShade;
      outColor = vec4(color, uAlpha * edge);
    }
  `;
  const meshVertexSource = `#version 300 es
    in vec3 aMaskPosition;
    in vec3 aMaskNormal;
    uniform float uYaw;
    uniform float uPitch;
    uniform float uAspect;
    uniform float uScale;
    uniform vec3 uFocus;
    out vec3 vNormal;
    out float vDepthShade;

    mat3 rotateX(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c);
    }

    mat3 rotateY(float a) {
      float s = sin(a);
      float c = cos(a);
      return mat3(c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c);
    }

    void main() {
      mat3 rotation = rotateY(uYaw) * rotateX(uPitch);
      vec3 centered = aMaskPosition - uFocus;
      vec3 rotated = rotation * centered;
      vec2 screen = rotated.xy / max(uScale, 0.1);
      screen.x /= max(uAspect, 0.001);
      gl_Position = vec4(screen, 0.15 + rotated.z * 0.55, 1.0);
      vNormal = normalize(rotation * aMaskNormal);
      vDepthShade = clamp(0.62 + rotated.z * 0.70, 0.34, 1.22);
    }
  `;
  const meshFragmentSource = `#version 300 es
    precision highp float;
    uniform vec3 uColor;
    uniform float uAlpha;
    uniform float uSpecular;
    uniform float uRim;
    uniform float uMaterial;
    in vec3 vNormal;
    in float vDepthShade;
    out vec4 outColor;

    void main() {
      vec3 n = normalize(vNormal);
      vec3 lightDir = normalize(vec3(-0.45, 0.62, 0.64));
      vec3 viewDir = normalize(vec3(0.0, 0.0, 1.0));
      float diffuse = max(dot(n, lightDir), 0.0);
      float back = max(dot(-n, lightDir), 0.0) * 0.18;
      float rim = pow(1.0 - max(dot(n, viewDir), 0.0), 2.0) * uRim;
      float specular = pow(max(dot(reflect(-lightDir, n), viewDir), 0.0), 34.0) * uSpecular;
      vec3 warm = mix(uColor, vec3(1.0, 0.95, 0.74), 0.16 * uMaterial);
      vec3 color = warm * (0.38 + 0.58 * diffuse + back + rim) * vDepthShade;
      color += vec3(1.0, 0.96, 0.80) * specular;
      outColor = vec4(color, uAlpha);
    }
  `;
  const surfaceProgram = createProgram(gl, surfaceVertexSource, surfaceFragmentSource);
  const surfacePositionLocation = gl.getAttribLocation(surfaceProgram, "aMaskPosition");
  const surfaceUniforms = {
    yaw: gl.getUniformLocation(surfaceProgram, "uYaw"),
    pitch: gl.getUniformLocation(surfaceProgram, "uPitch"),
    aspect: gl.getUniformLocation(surfaceProgram, "uAspect"),
    pointSize: gl.getUniformLocation(surfaceProgram, "uPointSize"),
    color: gl.getUniformLocation(surfaceProgram, "uColor"),
    alpha: gl.getUniformLocation(surfaceProgram, "uAlpha"),
    focus: gl.getUniformLocation(surfaceProgram, "uFocus"),
  };
  const meshProgram = createProgram(gl, meshVertexSource, meshFragmentSource);
  const meshPositionLocation = gl.getAttribLocation(meshProgram, "aMaskPosition");
  const meshNormalLocation = gl.getAttribLocation(meshProgram, "aMaskNormal");
  const meshUniforms = {
    yaw: gl.getUniformLocation(meshProgram, "uYaw"),
    pitch: gl.getUniformLocation(meshProgram, "uPitch"),
    aspect: gl.getUniformLocation(meshProgram, "uAspect"),
    scale: gl.getUniformLocation(meshProgram, "uScale"),
    color: gl.getUniformLocation(meshProgram, "uColor"),
    alpha: gl.getUniformLocation(meshProgram, "uAlpha"),
    specular: gl.getUniformLocation(meshProgram, "uSpecular"),
    rim: gl.getUniformLocation(meshProgram, "uRim"),
    material: gl.getUniformLocation(meshProgram, "uMaterial"),
    focus: gl.getUniformLocation(meshProgram, "uFocus"),
  };
  const meshPositions = maskMesh?.positionsArray || new Float32Array();
  const meshNormals = maskMesh?.normalsArray || new Float32Array(meshPositions.length);
  const meshIndices = maskMesh?.indicesArray || new Uint32Array();
  const hasMeshSurface = meshPositions.length > 0 && meshIndices.length > 0;
  const ctMeshLayers = (Array.isArray(ctMeshes) ? ctMeshes : []).filter((mesh) => (
    mesh?.positionsArray?.length > 0 && mesh?.indicesArray?.length > 0
  ));
  const ctMeshBuffers = ctMeshLayers.map((mesh) => {
    const vertexBufferRef = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBufferRef);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.positionsArray, gl.STATIC_DRAW);
    const normalBufferRef = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, normalBufferRef);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.normalsArray || new Float32Array(mesh.positionsArray.length), gl.STATIC_DRAW);
    const indexBufferRef = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBufferRef);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indicesArray, gl.STATIC_DRAW);
    const style = CT_MESH_LAYER_STYLES[mesh.layer] || CT_MESH_LAYER_STYLES.bone;
    return {
      mesh,
      style,
      vertexBuffer: vertexBufferRef,
      normalBuffer: normalBufferRef,
      indexBuffer: indexBufferRef,
      indexCount: mesh.indicesArray.length,
    };
  });
  const hasCtMeshSurface = ctMeshBuffers.length > 0;
  const ctTriangleCount = ctMeshLayers.reduce((total, mesh) => total + Number(mesh.triangle_count || mesh.indicesArray.length / 3 || 0), 0);
  const meshVertexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, meshVertexBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, meshPositions, gl.STATIC_DRAW);
  const meshNormalBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, meshNormalBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, meshNormals, gl.STATIC_DRAW);
  const meshIndexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, meshIndexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, meshIndices, gl.STATIC_DRAW);
  const surfacePoints = maskDimensionsMatch
    ? createMaskSurfacePoints(maskData, maskValues, { volumeData, volumeValues: values })
    : new Float32Array();
  const surfaceBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, surfaceBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, surfacePoints, gl.STATIC_DRAW);

  const initialPreset = defaultPreset();
  const labelPalette = buildLabelPalette(labelColors);
  // Backend may historically mark single-organ masks (voxel=label_id) as multiclass.
  // Only treat as multiclass when more than one positive class is present.
  const uniqueLabelCount = Array.isArray(maskData?.unique_labels) ? maskData.unique_labels.length : 0;
  const isMulticlassMask = Boolean(maskData?.multiclass) && uniqueLabelCount > 1;
  const viewerState = {
    yaw: 0.65,
    pitch: -0.28,
    camDist: 1.65,
    focusCenter: [0.5, 0.5, 0.5],
    focusTarget: null,
    camDistTarget: null,
    meshScaleTarget: null,
    focusAnim: 0,
    renderEngine: isMulticlassMask ? "volume" : hasCtMeshSurface ? "vtk" : "volume",
    preset: initialPreset,
    opacityScale: initialPreset.opacity,
    brightness: initialPreset.brightness,
    threshold: initialPreset.threshold,
    steps: initialPreset.steps,
    maskColor: highlightMask ? "#ffb020" : "#00e5b0",
    maskAlpha: highlightMask ? 0.82 : 0.58,
    outerMeshAlpha: 0.12,
    lungMeshAlpha: 0.42,
    innerMeshAlpha: 0.32,
    boneMeshAlpha: 0.22,
    meshScale: 0.72,
    maskSurfaceEnabled: true,
    multiclass: isMulticlassMask,
    labelPalette,
    isolatedLabelId: 0,
    hoveredLabelId: 0,
    selectedLabelId: 0,
    dragging: false,
    lastX: 0,
    lastY: 0,
  };

  const controls = document.createElement("div");
  controls.className = "volume-control-panel collapsed";
  controls.innerHTML = `
    <button class="volume-control-toggle" type="button" data-volume-controls-toggle>
      <span>渲染参数</span>
      <strong>展开</strong>
    </button>
    <div class="volume-control-body">
      <div class="control-section compact-section">
        <label class="control-field preset-select">
          <span>渲染方式</span>
          <select data-render-engine>
            <option value="vtk" ${hasCtMeshSurface ? "selected" : "disabled"}>VTK 综合重建（内外）</option>
            <option value="volume" ${hasCtMeshSurface ? "" : "selected"}>WebGL 体渲染（备用）</option>
          </select>
        </label>
      </div>
      <div class="mesh-metrics">
        <div class="mesh-metric"><span>CT Mesh</span><b>${hasCtMeshSurface ? ctTriangleCount.toLocaleString("zh-CN") : "-"}</b></div>
        <div class="mesh-metric"><span>Mask Mesh</span><b>${hasMeshSurface ? Number(maskMesh.triangle_count || meshIndices.length / 3).toLocaleString("zh-CN") : "-"}</b></div>
        <div class="mesh-metric"><span>Spacing</span><b>${Array.isArray(volumeData.spacing) ? volumeData.spacing.map((value) => Number(value).toFixed(1)).join("/") : "-"}</b></div>
      </div>
      <div class="volume-mode-controls ${hasCtMeshSurface ? "is-hidden" : ""}" data-volume-mode-controls>
        <label class="control-field preset-select">
          <span>医学渲染协议</span>
          <select data-volume-mode>
            ${RENDERING_PRESETS.map((preset) => `<option value="${preset.id}">${preset.label}</option>`).join("")}
          </select>
        </label>
        <label class="control-field"><span>体透明度</span>
          <input data-volume-opacity type="range" min="20" max="180" value="${Math.round(initialPreset.opacity * 100)}" />
        </label>
        <label class="control-field"><span>体亮度</span>
          <input data-volume-brightness type="range" min="70" max="170" value="${Math.round(initialPreset.brightness * 100)}" />
        </label>
        <label class="control-field"><span>组织阈值</span>
          <input data-volume-threshold type="range" min="0" max="100" value="${Math.round(initialPreset.threshold * 100)}" />
        </label>
        <label class="control-field"><span>采样质量</span>
          <input data-volume-steps type="range" min="160" max="448" value="${initialPreset.steps}" />
        </label>
      </div>
      <div class="vtk-layer-controls" data-vtk-controls>
        <label class="control-field"><span><i style="background:#5c94b8"></i>外层</span>
          <input data-outer-mesh-alpha type="range" min="0" max="45" value="${Math.round(viewerState.outerMeshAlpha * 100)}" />
        </label>
        <label class="control-field"><span><i style="background:#4db3f2"></i>肺/低密度腔</span>
          <input data-lung-mesh-alpha type="range" min="0" max="75" value="${Math.round(viewerState.lungMeshAlpha * 100)}" />
        </label>
        <label class="control-field"><span><i style="background:#db9e8c"></i>软组织</span>
          <input data-inner-mesh-alpha type="range" min="0" max="70" value="${Math.round(viewerState.innerMeshAlpha * 100)}" />
        </label>
        <label class="control-field"><span><i style="background:#ebe0ad"></i>骨性</span>
          <input data-bone-mesh-alpha type="range" min="0" max="70" value="${Math.round(viewerState.boneMeshAlpha * 100)}" />
        </label>
      </div>
      ${maskDimensionsMatch ? `
        <label class="control-field"><span>高亮颜色</span>
          <input data-mask-color type="color" value="#00e5b0" />
        </label>
        <label class="control-field"><span>高亮透明度</span>
          <input data-mask-alpha type="range" min="10" max="95" value="58" />
        </label>
        <label class="control-field mask-surface-toggle"><span>表面高亮</span>
          <input data-mask-surface type="checkbox" checked />
        </label>
      ` : ""}
      <div class="tf-editor-mini">
        <strong>VTK Surface Mesh</strong>
        <span>外层 body + 内部 soft tissue + 骨性 bone 均来自后端 VTK Marching Cubes。</span>
      </div>
    </div>
  `;
  container.appendChild(controls);
  let controlsCollapsed = true;

  const protocolPanel = document.createElement("div");
  protocolPanel.className = "volume-protocol-panel collapsed";
  container.appendChild(protocolPanel);
  let protocolCollapsed = true;

  function resize() {
    const rect = container.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function draw() {
    resize();
    const huRange = Array.isArray(volumeData.hu_range) ? volumeData.hu_range : [-1000, 1800];
    gl.clearColor(0.01, 0.025, 0.045, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    const maskColor = hexToRgb01(viewerState.maskColor);

    if (viewerState.renderEngine === "volume") {
      gl.disable(gl.DEPTH_TEST);
      gl.useProgram(program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_3D, texture);
      gl.uniform1i(uniforms.volume, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_3D, maskTexture || texture);
      gl.uniform1i(uniforms.mask, 1);
      gl.uniform1i(uniforms.hasMask, maskTexture ? 1 : 0);
      gl.uniform1f(uniforms.yaw, viewerState.yaw);
      gl.uniform1f(uniforms.pitch, viewerState.pitch);
      gl.uniform1f(uniforms.aspect, canvas.width / Math.max(canvas.height, 1));
      gl.uniform1f(uniforms.steps, viewerState.steps);
      gl.uniform1f(uniforms.opacityScale, viewerState.opacityScale);
      gl.uniform1f(uniforms.brightness, viewerState.brightness);
      gl.uniform1f(uniforms.threshold, viewerState.threshold);
      gl.uniform1f(uniforms.huLow, Number(huRange[0]));
      gl.uniform1f(uniforms.huHigh, Number(huRange[1]));
      gl.uniform1f(uniforms.ambient, viewerState.preset.ambient);
      gl.uniform1f(uniforms.diffuse, viewerState.preset.diffuse);
      gl.uniform1f(uniforms.specular, viewerState.preset.specular);
      gl.uniform1f(uniforms.rim, viewerState.preset.rim);
      gl.uniform1f(uniforms.edgeStrength, viewerState.preset.edgeStrength);
      gl.uniform1f(uniforms.alphaStop, viewerState.preset.alphaStop);
      gl.uniform1f(uniforms.opacityClamp, viewerState.preset.opacityClamp);
      gl.uniform3f(uniforms.maskColor, maskColor[0], maskColor[1], maskColor[2]);
      gl.uniform1f(uniforms.maskAlpha, viewerState.maskAlpha);
      gl.uniform1f(uniforms.camDist, viewerState.camDist);
      gl.uniform1i(uniforms.multiclass, viewerState.multiclass ? 1 : 0);
      if (uniforms.focus) {
        const focus = viewerState.focusCenter || [0.5, 0.5, 0.5];
        gl.uniform3f(uniforms.focus, focus[0], focus[1], focus[2]);
      }
      if (uniforms.isolateLabel) {
        gl.uniform1i(uniforms.isolateLabel, viewerState.isolatedLabelId || 0);
      }
      if (uniforms.palette) {
        const flat = new Float32Array(48);
        for (let i = 0; i < 16; i += 1) {
          const color = viewerState.labelPalette[i] || [0, 0.9, 0.69];
          flat[i * 3] = color[0];
          flat[i * 3 + 1] = color[1];
          flat[i * 3 + 2] = color[2];
        }
        gl.uniform3fv(uniforms.palette, flat);
      }
      gl.uniform3f(
        uniforms.voxelStep,
        1 / Math.max(volumeData.dimensions[0], 1),
        1 / Math.max(volumeData.dimensions[1], 1),
        1 / Math.max(volumeData.dimensions[2], 1)
      );
      gl.uniform1i(uniforms.renderMode, viewerState.preset.mode);
      gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
      gl.enableVertexAttribArray(positionLocation);
      gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }

    function drawMesh(vertexBufferRef, normalBufferRef, indexBufferRef, indexCount, color, alpha, material) {
      if (!indexCount) return;
      gl.useProgram(meshProgram);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.depthMask(alpha >= 0.92);
      gl.bindBuffer(gl.ARRAY_BUFFER, vertexBufferRef);
      gl.enableVertexAttribArray(meshPositionLocation);
      gl.vertexAttribPointer(meshPositionLocation, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, normalBufferRef);
      gl.enableVertexAttribArray(meshNormalLocation);
      gl.vertexAttribPointer(meshNormalLocation, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBufferRef);
      gl.uniform1f(meshUniforms.yaw, viewerState.yaw);
      gl.uniform1f(meshUniforms.pitch, viewerState.pitch);
      gl.uniform1f(meshUniforms.aspect, canvas.width / Math.max(canvas.height, 1));
      gl.uniform1f(meshUniforms.scale, viewerState.meshScale);
      gl.uniform3f(meshUniforms.color, color[0], color[1], color[2]);
      gl.uniform1f(meshUniforms.alpha, alpha);
      if (meshUniforms.focus) {
        const focus = viewerState.focusCenter || [0.5, 0.5, 0.5];
        gl.uniform3f(meshUniforms.focus, focus[0], focus[1], focus[2]);
      }
      gl.uniform1f(meshUniforms.specular, material === "mask" ? 0.42 : 0.20);
      gl.uniform1f(meshUniforms.rim, material === "mask" ? 0.34 : 0.22);
      gl.uniform1f(meshUniforms.material, material === "mask" ? 1.0 : 0.35);
      gl.drawElements(gl.TRIANGLES, indexCount, gl.UNSIGNED_INT, 0);
      gl.depthMask(true);
      gl.disable(gl.BLEND);
    }

    if (viewerState.renderEngine === "vtk" && hasCtMeshSurface) {
      for (const layer of ctMeshBuffers) {
        const alpha = Number(viewerState[layer.style.alphaKey] ?? 0.2);
        if (alpha <= 0.001) continue;
        drawMesh(
          layer.vertexBuffer,
          layer.normalBuffer,
          layer.indexBuffer,
          layer.indexCount,
          layer.style.color,
          alpha,
          layer.style.material
        );
      }
    }
    if (viewerState.renderEngine === "vtk" && viewerState.maskSurfaceEnabled && hasMeshSurface && maskData) {
      drawMesh(
        meshVertexBuffer,
        meshNormalBuffer,
        meshIndexBuffer,
        meshIndices.length,
        maskColor,
        Math.min(0.94, viewerState.maskAlpha + 0.18),
        "mask"
      );
    } else if (viewerState.renderEngine === "volume" && !hasMeshSurface && viewerState.maskSurfaceEnabled && surfacePoints.length > 0 && maskData) {
      gl.useProgram(surfaceProgram);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.bindBuffer(gl.ARRAY_BUFFER, surfaceBuffer);
      gl.enableVertexAttribArray(surfacePositionLocation);
      gl.vertexAttribPointer(surfacePositionLocation, 3, gl.FLOAT, false, 0, 0);
      gl.uniform1f(surfaceUniforms.yaw, viewerState.yaw);
      gl.uniform1f(surfaceUniforms.pitch, viewerState.pitch);
      gl.uniform1f(surfaceUniforms.aspect, canvas.width / Math.max(canvas.height, 1));
      gl.uniform1f(surfaceUniforms.pointSize, Math.max(2.2, Math.min(6.0, 620 / Math.max(...maskData.dimensions))));
      gl.uniform3f(surfaceUniforms.color, maskColor[0], maskColor[1], maskColor[2]);
      gl.uniform1f(surfaceUniforms.alpha, viewerState.maskAlpha);
      if (surfaceUniforms.focus) {
        const focus = viewerState.focusCenter || [0.5, 0.5, 0.5];
        gl.uniform3f(surfaceUniforms.focus, focus[0], focus[1], focus[2]);
      }
      gl.drawArrays(gl.POINTS, 0, surfacePoints.length / 3);
      gl.disable(gl.BLEND);
    }
  }

  canvas.addEventListener("pointerdown", (event) => {
    viewerState.dragging = true;
    viewerState.lastX = event.clientX;
    viewerState.lastY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!viewerState.dragging) return;
    const dx = event.clientX - viewerState.lastX;
    const dy = event.clientY - viewerState.lastY;
    viewerState.lastX = event.clientX;
    viewerState.lastY = event.clientY;
    viewerState.yaw += dx * 0.01;
    viewerState.pitch = Math.max(-1.2, Math.min(1.2, viewerState.pitch + dy * 0.01));
    draw();
  });
  canvas.addEventListener("pointerup", (event) => {
    viewerState.dragging = false;
    canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      // Scroll up = zoom into body (smaller camDist / larger mesh), scroll down = pull out.
      const direction = event.deltaY > 0 ? 1 : -1;
      const factor = Math.exp(direction * 0.12);
      viewerState.camDist = Math.min(3.8, Math.max(0.45, viewerState.camDist * factor));
      viewerState.meshScale = Math.min(1.85, Math.max(0.28, viewerState.meshScale / factor));
      viewerState.camDistTarget = null;
      viewerState.meshScaleTarget = null;
      draw();
    },
    { passive: false },
  );

  function resetViewFocus() {
    viewerState.focusTarget = [0.5, 0.5, 0.5];
    viewerState.camDistTarget = 1.65;
    viewerState.meshScaleTarget = 0.72;
    viewerState.yaw = 0.65;
    viewerState.pitch = -0.28;
    viewerState.isolatedLabelId = 0;
    startFocusAnimation();
  }

  function focusOnSelectedLabel(labelId, options = {}) {
    const isolate = options.isolate !== false;
    const focus = computeLabelFocus(maskData, maskValues, labelId);
    if (!focus) return false;
    viewerState.selectedLabelId = labelId;
    if (isolate) viewerState.isolatedLabelId = labelId;
    viewerState.focusTarget = focus.center;
    // Smaller organ → closer camera / smaller meshScale (meshScale divides screen coords).
    const extent = focus.extent;
    viewerState.camDistTarget = Math.max(0.48, Math.min(2.1, extent * 2.6 + 0.38));
    viewerState.meshScaleTarget = Math.max(0.22, Math.min(0.95, extent * 1.35 + 0.12));
    startFocusAnimation();
    return true;
  }

  let focusRaf = 0;
  function startFocusAnimation() {
    if (!viewerState.focusCenter) viewerState.focusCenter = [0.5, 0.5, 0.5];
    if (!viewerState.focusTarget) viewerState.focusTarget = [...viewerState.focusCenter];
    cancelAnimationFrame(focusRaf);
    let frames = 0;
    const step = () => {
      const t = 0.22;
      const c = viewerState.focusCenter;
      const ft = viewerState.focusTarget;
      c[0] += (ft[0] - c[0]) * t;
      c[1] += (ft[1] - c[1]) * t;
      c[2] += (ft[2] - c[2]) * t;
      if (viewerState.camDistTarget != null) {
        viewerState.camDist += (viewerState.camDistTarget - viewerState.camDist) * t;
      }
      if (viewerState.meshScaleTarget != null) {
        viewerState.meshScale += (viewerState.meshScaleTarget - viewerState.meshScale) * t;
      }
      draw();
      frames += 1;
      const close =
        Math.hypot(ft[0] - c[0], ft[1] - c[1], ft[2] - c[2]) < 0.004 &&
        (viewerState.camDistTarget == null ||
          Math.abs(viewerState.camDist - viewerState.camDistTarget) < 0.01);
      if (!close && frames < 40) {
        focusRaf = requestAnimationFrame(step);
      } else {
        viewerState.focusCenter = [...ft];
        if (viewerState.camDistTarget != null) viewerState.camDist = viewerState.camDistTarget;
        if (viewerState.meshScaleTarget != null) viewerState.meshScale = viewerState.meshScaleTarget;
        draw();
      }
    };
    focusRaf = requestAnimationFrame(step);
  }

  canvas.addEventListener("dblclick", (event) => {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const nx = (event.clientX - rect.left) / rect.width;
    const ny = (event.clientY - rect.top) / rect.height;
    const labelId = pickMaskLabelAtCursor(maskData, maskValues, viewerState, canvas, nx, ny);
    if (labelId > 0) {
      focusOnSelectedLabel(labelId);
      updateOrganHud?.();
    }
  });

  function updateProtocolPanel() {
    const resampling = volumeData.resampling || {};
    const spacing = Array.isArray(volumeData.spacing) ? volumeData.spacing.map((value) => Number(value).toFixed(2)).join(" / ") : "-";
    const maskText = maskTexture
      ? `Mask：${maskData.mask_id} · ${maskData.label || maskData.version}${viewerState.multiclass ? " · 多类分色" : ""} · ${hasMeshSurface ? `VTK ${Number(maskMesh.triangle_count || meshIndices.length / 3).toLocaleString("zh-CN")} triangles` : "体渲染叠加"}`
      : (maskData ? "Mask 尺寸与 CT 体数据不一致，已跳过叠加" : "未加载 3D Mask");
    const ctMeshText = hasCtMeshSurface
      ? `CT VTK：${ctMeshLayers.map((mesh) => CT_MESH_LAYER_STYLES[mesh.layer]?.label || mesh.layer).join(" / ")} · ${ctTriangleCount.toLocaleString("zh-CN")} triangles`
      : "CT VTK mesh 未加载，使用 WebGL2 volume ray casting";
    const resampleText = resampling.requested
      ? (resampling.applied ? "各向同性重采样已启用" : `各向同性重采样未启用：${resampling.reason || "无需处理"}`)
      : "使用原始 spacing";
    protocolPanel.classList.toggle("collapsed", protocolCollapsed);
    protocolPanel.innerHTML = `
      <button class="protocol-toggle" type="button" data-protocol-toggle>
        <span>Rendering Protocol</span>
        <strong>${viewerState.renderEngine === "vtk" ? "VTK 综合" : viewerState.preset.label}</strong>
        <b>${protocolCollapsed ? "展开" : "收起"}</b>
      </button>
      <div class="protocol-details">
        <span>当前引擎：${viewerState.renderEngine === "vtk" ? "VTK 综合重建" : "WebGL2 体渲染"}</span>
        <span>${resampleText} · spacing ${spacing} mm</span>
        <span>${ctMeshText}</span>
        <span>${maskText}</span>
        <span>滚轮：向内/向外调整观察距离（进身体 / 拉远）</span>
        <p>${viewerState.renderEngine === "vtk" ? "仅显示 VTK 三角网格：外层、内部软组织、骨性结构和 Mask 均由 VTK mesh 渲染。多类分色请切换到 WebGL 体渲染。" : viewerState.preset.summary}</p>
      </div>
    `;
    protocolPanel.querySelector("[data-protocol-toggle]").addEventListener("click", () => {
      protocolCollapsed = !protocolCollapsed;
      updateProtocolPanel();
    });
    container.dataset.preset = viewerState.preset.id;
  }

  function syncControlValues() {
    controls.querySelector("[data-volume-opacity]").value = String(Math.round(viewerState.opacityScale * 100));
    controls.querySelector("[data-volume-brightness]").value = String(Math.round(viewerState.brightness * 100));
    controls.querySelector("[data-volume-threshold]").value = String(Math.round(viewerState.threshold * 100));
    controls.querySelector("[data-volume-steps]").value = String(viewerState.steps);
  }

  function updateControlPanel() {
    controls.classList.toggle("collapsed", controlsCollapsed);
    const toggle = controls.querySelector("[data-volume-controls-toggle] strong");
    if (toggle) toggle.textContent = controlsCollapsed ? "展开" : "收起";
    badge.textContent = viewerState.renderEngine === "vtk" ? "VTK 综合重建" : "WebGL2 体渲染";
    const volumeControls = controls.querySelector("[data-volume-mode-controls]");
    if (volumeControls) {
      volumeControls.classList.toggle("is-hidden", viewerState.renderEngine !== "volume");
    }
    controls.querySelectorAll("[data-vtk-controls]").forEach((element) => {
      element.classList.toggle("is-hidden", viewerState.renderEngine !== "vtk");
    });
  }

  updateProtocolPanel();
  updateControlPanel();

  controls.querySelector("[data-volume-controls-toggle]").addEventListener("click", () => {
    controlsCollapsed = !controlsCollapsed;
    updateControlPanel();
  });

  controls.querySelector("[data-render-engine]").addEventListener("change", (event) => {
    const requested = event.target.value;
    viewerState.renderEngine = requested === "vtk" && !hasCtMeshSurface ? "volume" : requested;
    if (event.target.value !== viewerState.renderEngine) {
      event.target.value = viewerState.renderEngine;
    }
    updateControlPanel();
    updateProtocolPanel();
    draw();
  });

  controls.querySelector("[data-volume-mode]").addEventListener("change", (event) => {
    const preset = PRESET_BY_ID.get(event.target.value) || defaultPreset();
    viewerState.preset = preset;
    viewerState.opacityScale = preset.opacity;
    viewerState.brightness = preset.brightness;
    viewerState.threshold = preset.threshold;
    viewerState.steps = preset.steps;
    syncControlValues();
    updateProtocolPanel();
    draw();
  });
  controls.querySelector("[data-volume-opacity]").addEventListener("input", (event) => {
    viewerState.opacityScale = Number(event.target.value) / 100;
    draw();
  });
  controls.querySelector("[data-volume-brightness]").addEventListener("input", (event) => {
    viewerState.brightness = Number(event.target.value) / 100;
    draw();
  });
  controls.querySelector("[data-volume-threshold]").addEventListener("input", (event) => {
    viewerState.threshold = Number(event.target.value) / 100;
    draw();
  });
  controls.querySelector("[data-volume-steps]").addEventListener("input", (event) => {
    viewerState.steps = Number(event.target.value);
    draw();
  });
  const maskColorInput = controls.querySelector("[data-mask-color]");
  if (maskColorInput) {
    maskColorInput.addEventListener("input", (event) => {
      viewerState.maskColor = event.target.value;
      draw();
    });
  }
  const maskAlphaInput = controls.querySelector("[data-mask-alpha]");
  if (maskAlphaInput) {
    maskAlphaInput.addEventListener("input", (event) => {
      viewerState.maskAlpha = Number(event.target.value) / 100;
      draw();
    });
  }
  const meshAlphaBindings = [
    ["[data-outer-mesh-alpha]", "outerMeshAlpha"],
    ["[data-lung-mesh-alpha]", "lungMeshAlpha"],
    ["[data-inner-mesh-alpha]", "innerMeshAlpha"],
    ["[data-bone-mesh-alpha]", "boneMeshAlpha"],
  ];
  for (const [selector, stateKey] of meshAlphaBindings) {
    const input = controls.querySelector(selector);
    if (input) {
      input.addEventListener("input", (event) => {
        viewerState[stateKey] = Number(event.target.value) / 100;
        draw();
      });
    }
  }
  const maskSurfaceInput = controls.querySelector("[data-mask-surface]");
  if (maskSurfaceInput) {
    maskSurfaceInput.addEventListener("change", (event) => {
      viewerState.maskSurfaceEnabled = Boolean(event.target.checked);
      draw();
    });
  }

  // --- Hand gesture control (bimanual; panel docked top-right to free 3D center) ---
  const gesturePanel = document.createElement("div");
  gesturePanel.className = "gesture-panel gesture-panel--compact";
  gesturePanel.innerHTML = `
    <div class="gesture-toolbar">
      <button type="button" class="ghost-button" data-gesture-toggle>开启手势</button>
      <button type="button" class="ghost-button hidden" data-gesture-minimize title="收起预览">▾</button>
    </div>
    <div class="gesture-body hidden" data-gesture-body>
      <div class="gesture-video-wrap">
        <video class="gesture-video" data-gesture-video playsinline muted></video>
        <canvas class="gesture-overlay" data-gesture-overlay></canvas>
        <div class="gesture-frame-guide" aria-hidden="true"></div>
      </div>
      <div class="gesture-status" data-gesture-status>摄像头未开启</div>
      <div class="gesture-coach" data-gesture-coach>
        <strong data-coach-title>准备中</strong>
        <p data-coach-tip>开启后：捏合拖=旋转 · 双手开合=缩放。</p>
      </div>
      <div class="gesture-progress-wrap">
        <div class="gesture-progress-label"><span>校准</span><span data-calibrate-pct>0%</span></div>
        <div class="gesture-progress-track"><div class="gesture-progress-bar" data-calibrate-bar></div></div>
      </div>
      <div class="gesture-actions">
        <button type="button" class="primary-button" data-gesture-guide>引导校准</button>
        <button type="button" class="ghost-button" data-gesture-instant>设为中心</button>
        <button type="button" class="ghost-button hidden" data-gesture-cancel-cal>取消</button>
      </div>
      <div class="gesture-live" data-gesture-live>当前：-</div>
      <details class="gesture-help">
        <summary>手势说明</summary>
        <div class="gesture-hint">
          <div><b>单手捏合 + 拖动</b>：旋转（pinch-to-rotate）</div>
          <div><b>张开手掌 + 拖动</b>：轻量旋转</div>
          <div><b>双手同时入镜，开合距离</b>：缩放（bimanual zoom）</div>
          <div><b>食指指向</b>：悬停器官</div>
          <div><b>OK / 握拳</b>：选中并特写居中放大 · <b>比耶</b>：隔离特写 · <b>竖拇指</b>：重置</div>
        </div>
      </details>
      <div class="gesture-organ" data-gesture-organ>悬停：-</div>
      <div class="gesture-selected" data-gesture-selected>已选：无</div>
    </div>
  `;
  container.appendChild(gesturePanel);

  const cursorEl = document.createElement("div");
  cursorEl.className = "gesture-cursor hidden";
  cursorEl.innerHTML = `<span class="gesture-cursor-ring"></span><span class="gesture-cursor-label" data-gesture-cursor-label></span>`;
  container.appendChild(cursorEl);

  const labelNameMapPromise = loadLabelNameMap();
  let labelNameMap = {};
  labelNameMapPromise.then((map) => {
    labelNameMap = map;
  });

  let gestureController = null;
  let lastHoverId = 0;
  let hoverSince = 0;
  let controlsCollapsedBeforeGesture = null;

  function labelTitle(id) {
    if (!id) return "背景 / 无标注";
    return labelNameMap[id] || `类别 #${id}`;
  }

  function updateOrganHud() {
    const organEl = gesturePanel.querySelector("[data-gesture-organ]");
    const selectedEl = gesturePanel.querySelector("[data-gesture-selected]");
    const cursorLabel = cursorEl.querySelector("[data-gesture-cursor-label]");
    const hoverId = viewerState.hoveredLabelId || 0;
    const selectedId = viewerState.selectedLabelId || 0;
    if (organEl) organEl.textContent = `悬停：${labelTitle(hoverId)}${hoverId ? ` (#${hoverId})` : ""}`;
    if (selectedEl) {
      selectedEl.textContent = selectedId
        ? `已选：${labelTitle(selectedId)} (#${selectedId})${viewerState.isolatedLabelId ? " · 隔离" : ""}`
        : "已选：无";
    }
    if (cursorLabel) {
      cursorLabel.textContent = hoverId ? labelTitle(hoverId) : "";
      cursorLabel.classList.toggle("visible", Boolean(hoverId));
    }
  }

  function updateCoachUi(frame) {
    const coach = frame.coach || {};
    const titleEl = gesturePanel.querySelector("[data-coach-title]");
    const tipEl = gesturePanel.querySelector("[data-coach-tip]");
    const liveEl = gesturePanel.querySelector("[data-gesture-live]");
    const pctEl = gesturePanel.querySelector("[data-calibrate-pct]");
    const barEl = gesturePanel.querySelector("[data-calibrate-bar]");
    const cancelBtn = gesturePanel.querySelector("[data-gesture-cancel-cal]");
    const guideBtn = gesturePanel.querySelector("[data-gesture-guide]");
    const coachBox = gesturePanel.querySelector("[data-gesture-coach]");
    if (titleEl) titleEl.textContent = coach.title || "准备中";
    if (tipEl) tipEl.textContent = coach.tip || "";
    if (liveEl) {
      const handTag = frame.handCount > 1 ? `双手×${frame.handCount}` : "单手";
      liveEl.textContent = frame.present
        ? `${handTag} · ${frame.gestureText || frame.gesture || "-"} · ${frame.mode || "-"}`
        : "当前：未检测到手";
    }
    const progress = Number(frame.calibrateProgress || 0);
    if (pctEl) pctEl.textContent = `${Math.round(progress * 100)}%`;
    if (barEl) barEl.style.width = `${Math.round(progress * 100)}%`;
    if (coachBox) coachBox.classList.toggle("ok", Boolean(coach.ok));
    if (coachBox) coachBox.classList.toggle("warn", !coach.ok);
    if (cancelBtn) cancelBtn.classList.toggle("hidden", !frame.calibrateMode);
    if (guideBtn) guideBtn.textContent = frame.calibrateMode ? "校准中…" : "引导校准";
  }

  function drawHandOverlay(handsOrLandmarks) {
    const videoEl = gesturePanel.querySelector("[data-gesture-video]");
    const overlay = gesturePanel.querySelector("[data-gesture-overlay]");
    if (!videoEl || !overlay) return;
    const width = videoEl.clientWidth || 200;
    const height = videoEl.clientHeight || 150;
    if (overlay.width !== width || overlay.height !== height) {
      overlay.width = width;
      overlay.height = height;
    }
    const ctx = overlay.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    if (!handsOrLandmarks) return;
    const handsList = Array.isArray(handsOrLandmarks[0])
      ? handsOrLandmarks
      : [handsOrLandmarks];
    const edges = [
      [0, 1], [1, 2], [2, 3], [3, 4],
      [0, 5], [5, 6], [6, 7], [7, 8],
      [0, 9], [9, 10], [10, 11], [11, 12],
      [0, 13], [13, 14], [14, 15], [15, 16],
      [0, 17], [17, 18], [18, 19], [19, 20],
      [5, 9], [9, 13], [13, 17],
    ];
    const palettes = [
      { stroke: "rgba(0, 229, 176, 0.95)", fill: "rgba(0, 194, 255, 0.95)" },
      { stroke: "rgba(255, 176, 32, 0.95)", fill: "rgba(255, 120, 80, 0.95)" },
    ];
    handsList.forEach((landmarks, handIdx) => {
      if (!landmarks?.length) return;
      const palette = palettes[handIdx % palettes.length];
      ctx.strokeStyle = palette.stroke;
      ctx.fillStyle = palette.fill;
      ctx.lineWidth = 2;
      for (const [a, b] of edges) {
        const pa = landmarks[a];
        const pb = landmarks[b];
        if (!pa || !pb) continue;
        ctx.beginPath();
        ctx.moveTo((1 - pa.x) * width, pa.y * height);
        ctx.lineTo((1 - pb.x) * width, pb.y * height);
        ctx.stroke();
      }
      for (const point of landmarks) {
        ctx.beginPath();
        ctx.arc((1 - point.x) * width, point.y * height, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    });
  }

  function syncCalibrateButtons() {
    const inCal = Boolean(gestureController?.isCalibrateMode?.());
    gesturePanel.querySelector("[data-gesture-cancel-cal]")?.classList.toggle("hidden", !inCal);
  }

  gesturePanel.querySelector("[data-gesture-guide]").addEventListener("click", () => {
    if (!gestureController?.isRunning()) {
      gesturePanel.querySelector("[data-gesture-status]").textContent = "请先开启手势控制";
      return;
    }
    gestureController.beginCalibration();
    syncCalibrateButtons();
  });
  gesturePanel.querySelector("[data-gesture-instant]").addEventListener("click", () => {
    if (!gestureController?.isRunning()) {
      gesturePanel.querySelector("[data-gesture-status]").textContent = "请先开启手势控制";
      return;
    }
    const ok = gestureController.calibrateNow();
    if (ok) syncCalibrateButtons();
  });
  gesturePanel.querySelector("[data-gesture-cancel-cal]").addEventListener("click", () => {
    gestureController?.cancelCalibration?.();
    syncCalibrateButtons();
  });

  gesturePanel.querySelector("[data-gesture-minimize]")?.addEventListener("click", () => {
    const body = gesturePanel.querySelector("[data-gesture-body]");
    const minBtn = gesturePanel.querySelector("[data-gesture-minimize]");
    if (!body) return;
    const collapsed = body.classList.toggle("is-collapsed");
    gesturePanel.classList.toggle("is-minimized", collapsed);
    if (minBtn) minBtn.textContent = collapsed ? "▴" : "▾";
  });

  gesturePanel.querySelector("[data-gesture-toggle]").addEventListener("click", async () => {
    const button = gesturePanel.querySelector("[data-gesture-toggle]");
    const body = gesturePanel.querySelector("[data-gesture-body]");
    const statusEl = gesturePanel.querySelector("[data-gesture-status]");
    const minBtn = gesturePanel.querySelector("[data-gesture-minimize]");
    if (gestureController?.isRunning()) {
      gestureController.stop();
      cursorEl.classList.add("hidden");
      body.classList.add("hidden");
      body.classList.remove("is-collapsed");
      gesturePanel.classList.remove("is-minimized");
      minBtn?.classList.add("hidden");
      button.textContent = "开启手势";
      drawHandOverlay(null);
      if (controlsCollapsedBeforeGesture != null) {
        controlsCollapsed = controlsCollapsedBeforeGesture;
        controlsCollapsedBeforeGesture = null;
        updateControlPanel();
      }
      return;
    }
    button.disabled = true;
    button.textContent = "加载模型…";
    try {
      if (!gestureController) {
        const module = await import(`/frontend/hand_gesture.js?v=focus-select-20260713`);
        gestureController = await module.createHandGestureController({
          onStatus: (text) => {
            if (statusEl) statusEl.textContent = text;
          },
          onFrame: (frame) => {
            const videoEl = gesturePanel.querySelector("[data-gesture-video]");
            if (videoEl && frame.video && videoEl.srcObject !== frame.video.srcObject) {
              videoEl.srcObject = frame.video.srcObject;
            }
            updateCoachUi(frame);
            drawHandOverlay(frame.handsLandmarks?.length ? frame.handsLandmarks : (frame.landmarks || null));
            syncCalibrateButtons();

            if (!frame.present) {
              cursorEl.classList.add("hidden");
              return;
            }
            cursorEl.classList.remove("hidden");
            cursorEl.style.left = `${frame.cursor.x * 100}%`;
            cursorEl.style.top = `${frame.cursor.y * 100}%`;
            cursorEl.dataset.gesture = frame.gesture || "move";
            cursorEl.dataset.mode = frame.mode || "idle";

            // Continuous camera control from scientific mappings:
            // pinch/palm drag → rotate; two-hand gap → zoom. Pause while calibrating.
            if (!frame.calibrateMode) {
              const rd = frame.rotateDelta || { x: 0, y: 0 };
              if (Math.abs(rd.x) > 0.0005 || Math.abs(rd.y) > 0.0005) {
                viewerState.yaw += rd.x * 2.2;
                viewerState.pitch = Math.max(
                  -1.2,
                  Math.min(1.2, viewerState.pitch - rd.y * 1.8),
                );
              }
              const zd = Number(frame.zoomDelta || 0);
              if (Math.abs(zd) > 0.0008) {
                // Hands farther → zoom in (smaller camDist), same as Minority Report / Pan_Zoom MH.
                viewerState.camDist = Math.max(
                  0.55,
                  Math.min(4.2, viewerState.camDist * (1 - zd * 0.85)),
                );
                viewerState.meshScale = Math.min(1.85, Math.max(0.28, 1.2 / viewerState.camDist));
              }
            }

            const hoverId = pickMaskLabelAtCursor(
              maskData,
              maskValues,
              viewerState,
              canvas,
              frame.cursor.x,
              frame.cursor.y,
            );
            const now = performance.now();
            if (hoverId !== lastHoverId) {
              lastHoverId = hoverId;
              hoverSince = now;
            }
            viewerState.hoveredLabelId = hoverId;
            if (hoverId && now - hoverSince > 350) cursorEl.classList.add("dwell");
            else cursorEl.classList.remove("dwell");

            if (frame.selectPulse && hoverId > 0) {
              viewerState.selectedLabelId = hoverId;
              const focused = focusOnSelectedLabel(hoverId, { isolate: true });
              if (statusEl) {
                statusEl.textContent = focused
                  ? `特写：${labelTitle(hoverId)}`
                  : `已选中器官：${labelTitle(hoverId)}`;
              }
              container.dispatchEvent(
                new CustomEvent("gesture-organ-select", {
                  detail: { labelId: hoverId, name: labelTitle(hoverId), focused },
                }),
              );
            }
            if (frame.peacePulse) {
              if (viewerState.isolatedLabelId) {
                viewerState.isolatedLabelId = 0;
                if (statusEl) statusEl.textContent = "已取消器官隔离";
              } else if (viewerState.selectedLabelId || hoverId) {
                const id = viewerState.selectedLabelId || hoverId;
                viewerState.isolatedLabelId = id;
                focusOnSelectedLabel(id, { isolate: true });
                if (statusEl) statusEl.textContent = `特写隔离：${labelTitle(id)}`;
              }
            }
            if (frame.resetPulse) {
              viewerState.selectedLabelId = 0;
              resetViewFocus();
              if (statusEl) statusEl.textContent = "视角已重置";
            }
            if (frame.calibrating) cursorEl.classList.add("calibrating");
            else cursorEl.classList.remove("calibrating");

            updateOrganHud();
            draw();
          },
        });
      }
      // Free the 3D center: collapse the left metrics/control panel while gesturing.
      if (controlsCollapsedBeforeGesture == null) {
        controlsCollapsedBeforeGesture = controlsCollapsed;
      }
      if (!controlsCollapsed) {
        controlsCollapsed = true;
        updateControlPanel();
      }
      body.classList.remove("hidden", "is-collapsed");
      gesturePanel.classList.remove("is-minimized");
      minBtn?.classList.remove("hidden");
      if (minBtn) minBtn.textContent = "▾";
      await gestureController.start();
      button.textContent = "关闭手势";
      if (statusEl) statusEl.textContent = "已开启。捏合拖=旋转 · 双手开合=缩放";
    } catch (error) {
      if (statusEl) statusEl.textContent = `手势启动失败：${error.message || error}`;
      button.textContent = "开启手势";
      body.classList.remove("hidden");
    } finally {
      button.disabled = false;
    }
  });

  const resizeObserver = new ResizeObserver(draw);
  resizeObserver.observe(container);
  draw();

  activeViewers.set(container, {
    delete() {
      resizeObserver.disconnect();
      try {
        cancelAnimationFrame(focusRaf);
        gestureController?.dispose?.();
      } catch {
        // ignore
      }
      gestureController = null;
      gl.deleteTexture(texture);
      if (maskTexture) gl.deleteTexture(maskTexture);
      for (const layer of ctMeshBuffers) {
        gl.deleteBuffer(layer.vertexBuffer);
        gl.deleteBuffer(layer.normalBuffer);
        gl.deleteBuffer(layer.indexBuffer);
      }
      gl.deleteBuffer(meshVertexBuffer);
      gl.deleteBuffer(meshNormalBuffer);
      gl.deleteBuffer(meshIndexBuffer);
      gl.deleteBuffer(surfaceBuffer);
      gl.deleteBuffer(vertexBuffer);
      gl.deleteProgram(meshProgram);
      gl.deleteProgram(surfaceProgram);
      gl.deleteProgram(program);
    },
  });
}
