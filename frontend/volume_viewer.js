const activeViewers = new WeakMap();

const RENDERING_PRESETS = [
  {
    id: "soft",
    label: "软组织综合",
    mode: 0,
    wl: 40,
    ww: 400,
    opacity: 1.1,
    brightness: 1.02,
    threshold: 0.12,
    steps: 240,
    alphaStop: 0.96,
    opacityClamp: 0.16,
    ambient: 0.28,
    diffuse: 0.54,
    specular: 0.14,
    rim: 0.16,
    edgeStrength: 1.55,
    summary: "压低骨骼遮挡，突出脂肪、肌肉、血管和实质器官边界。",
  },
  {
    id: "bone",
    label: "骨窗高密度",
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
    summary: "连续保留松质骨到骨皮质，降低采样步长并延迟终止，改善肋骨、锁骨和肩胛骨断裂。",
  },
  {
    id: "lung",
    label: "肺窗边界",
    mode: 2,
    wl: -600,
    ww: 1600,
    opacity: 0.92,
    brightness: 0.98,
    threshold: 0.02,
    steps: 360,
    alphaStop: 0.992,
    opacityClamp: 0.105,
    ambient: 0.38,
    diffuse: 0.36,
    specular: 0.05,
    rim: 0.08,
    edgeStrength: 5.20,
    summary: "低密度肺实质保持透明，肺血管、支气管和胸膜边界由 HU + Gradient 双维映射增强。",
  },
];

const PRESET_BY_ID = new Map(RENDERING_PRESETS.map((preset) => [preset.id, preset]));

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

function clearContainer(container) {
  const previous = activeViewers.get(container);
  if (previous) {
    previous.delete();
    activeViewers.delete(container);
  }
  container.replaceChildren();
}

export async function renderVolume3D({ container, imageId, windowName = "volume", maxDim = 176 }) {
  if (!container || !imageId) return;
  clearContainer(container);

  const status = document.createElement("div");
  status.className = "volume-status";
  status.textContent = "正在读取真实 3D CT 体数据...";
  container.appendChild(status);

  const response = await fetchVolumeData({ imageId, maxDim, windowName });

  const volumeData = await response.json();
  const values = decodeBase64ToUint8Array(volumeData.values_base64);

  status.textContent = "正在初始化 WebGL2 体渲染引擎...";
  renderWithWebGL({ container, volumeData, values });
}

async function fetchVolumeData({ imageId, maxDim, windowName }) {
  const query = `max_dim=${maxDim}&window=${windowName}`;
  const primary = await fetch(`/api/image/${imageId}/volume-data?${query}`);
  if (primary.ok) return primary;
  if (primary.status !== 404) {
    const message = await primary.text();
    throw new Error(`体数据接口失败：${message}`);
  }

  const legacy = await fetch(`/api/image/${imageId}/vtk-volume?${query}`);
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

function renderWithWebGL({ container, volumeData, values }) {
  clearContainer(container);

  const canvas = document.createElement("canvas");
  canvas.className = "webgl-volume-canvas";
  container.appendChild(canvas);

  const badge = document.createElement("div");
  badge.className = "volume-engine-badge";
  badge.textContent = "WebGL2 医学渲染协议";
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
    uniform vec3 uVoxelStep;
    uniform int uRenderMode;

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

    float band(float hu, float low, float high, float feather) {
      return smoothstep(low, low + feather, hu) * (1.0 - smoothstep(high - feather, high, hu));
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
        vec3 parenchyma = vec3(0.13, 0.32, 0.44);
        vec3 bronchial = vec3(0.48, 0.70, 0.76);
        vec3 vessel = vec3(0.82, 0.92, 0.93);
        vec3 c = mix(air, parenchyma, smoothstep(-960.0, -650.0, hu));
        c = mix(c, bronchial, smoothstep(-620.0, -260.0, hu));
        c = mix(c, vessel, smoothstep(-180.0, 220.0, hu));
        return mix(c, vec3(0.86, 0.98, 1.0), edge * 0.28);
      }
      vec3 fat = vec3(0.70, 0.52, 0.34);
      vec3 muscle = vec3(0.72, 0.48, 0.46);
      vec3 vessel = vec3(0.98, 0.80, 0.62);
      vec3 bone = vec3(0.84, 0.78, 0.68);
      vec3 c = mix(fat, muscle, smoothstep(-70.0, 85.0, hu));
      c = mix(c, vessel, smoothstep(90.0, 260.0, hu));
      c = mix(c, bone, smoothstep(320.0, 950.0, hu));
      return mix(c, vec3(1.0), edge * 0.16);
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
        float alveoli = band(hu, -930.0, -620.0, 95.0) * 0.0026;
        float parenchymaEdge = edge * band(hu, -940.0, -380.0, 150.0) * 0.056;
        float bronchusEdge = edge * band(hu, -760.0, -120.0, 170.0) * 0.034;
        float vessel = band(hu, -250.0, 260.0, 95.0) * 0.040;
        float pleura = edge * smoothstep(-850.0, -260.0, hu) * (1.0 - smoothstep(320.0, 760.0, hu)) * 0.030;
        float bone = smoothstep(320.0, 1300.0, hu) * 0.003;
        return (alveoli + parenchymaEdge + bronchusEdge + vessel + pleura + bone) * uOpacityScale;
      }

      float floorHu = mix(-260.0, 90.0, uThreshold);
      if (hu < floorHu) {
        return 0.0;
      }
      float fat = band(hu, -180.0, -25.0, 45.0) * 0.010;
      float muscle = band(hu, -20.0, 115.0, 42.0) * 0.030;
      float vessel = band(hu, 90.0, 330.0, 70.0) * 0.056;
      float bone = smoothstep(300.0, 1100.0, hu) * 0.012;
      float gradientBoost = mix(0.52, 1.95, edge);
      return (fat + muscle + vessel + bone + edge * 0.010) * gradientBoost * uOpacityScale;
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
      vec3 rayOrigin = invRotation * vec3(screen * 0.84, -1.65) + vec3(0.5);
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

      for (int i = 0; i < 448; i++) {
        if (float(i) >= uSteps || alpha > uAlphaStop) {
          break;
        }
        vec3 p = rayOrigin + rayDir * (nearHit + (float(i) + 0.5) * dt);
        float value = texture(uVolume, p).r;
        float hu = huFromValue(value);
        vec3 gradient = gradientAt(p);
        float edge = smoothstep(0.018, 0.145, length(gradient) * uEdgeStrength);
        float opacity = clamp(transferOpacity(hu, edge), 0.0, uOpacityClamp);
        vec3 sampleColor = applyLighting(transferColor(hu, edge), gradient, rayDir, edge);
        color += (1.0 - alpha) * opacity * sampleColor;
        alpha += (1.0 - alpha) * opacity;
      }

      vec3 background = vec3(0.01, 0.025, 0.045);
      color *= uBrightness;
      outColor = vec4(mix(background, color, min(alpha * 1.45, 1.0)), 1.0);
    }
  `;

  const program = createProgram(gl, vertexSource, fragmentSource);
  const positionLocation = gl.getAttribLocation(program, "aPosition");
  const uniforms = {
    volume: gl.getUniformLocation(program, "uVolume"),
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
    voxelStep: gl.getUniformLocation(program, "uVoxelStep"),
    renderMode: gl.getUniformLocation(program, "uRenderMode"),
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

  const initialPreset = defaultPreset();
  const viewerState = {
    yaw: 0.65,
    pitch: -0.28,
    preset: initialPreset,
    opacityScale: initialPreset.opacity,
    brightness: initialPreset.brightness,
    threshold: initialPreset.threshold,
    steps: initialPreset.steps,
    dragging: false,
    lastX: 0,
    lastY: 0,
  };

  const controls = document.createElement("div");
  controls.className = "volume-control-panel";
  controls.innerHTML = `
    <label class="preset-select">医学渲染协议
      <select data-volume-mode>
        ${RENDERING_PRESETS.map((preset) => `<option value="${preset.id}">${preset.label}</option>`).join("")}
      </select>
    </label>
    <label>透明度
      <input data-volume-opacity type="range" min="20" max="180" value="${Math.round(initialPreset.opacity * 100)}" />
    </label>
    <label>亮度
      <input data-volume-brightness type="range" min="70" max="170" value="${Math.round(initialPreset.brightness * 100)}" />
    </label>
    <label>组织阈值
      <input data-volume-threshold type="range" min="0" max="100" value="${Math.round(initialPreset.threshold * 100)}" />
    </label>
    <label>质量
      <input data-volume-steps type="range" min="160" max="448" value="${initialPreset.steps}" />
    </label>
  `;
  container.appendChild(controls);

  const protocolPanel = document.createElement("div");
  protocolPanel.className = "volume-protocol-panel";
  container.appendChild(protocolPanel);

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
    gl.useProgram(program);
    gl.clearColor(0.01, 0.025, 0.045, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_3D, texture);
    gl.uniform1i(uniforms.volume, 0);
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
  function updateProtocolPanel() {
    protocolPanel.innerHTML = `
      <div class="protocol-kicker">Rendering Protocol</div>
      <strong>${viewerState.preset.label}</strong>
      <span>WL ${viewerState.preset.wl} / WW ${viewerState.preset.ww} · ${viewerState.preset.steps} samples · stop ${viewerState.preset.alphaStop}</span>
      <p>${viewerState.preset.summary}</p>
    `;
    container.dataset.preset = viewerState.preset.id;
  }

  function syncControlValues() {
    controls.querySelector("[data-volume-opacity]").value = String(Math.round(viewerState.opacityScale * 100));
    controls.querySelector("[data-volume-brightness]").value = String(Math.round(viewerState.brightness * 100));
    controls.querySelector("[data-volume-threshold]").value = String(Math.round(viewerState.threshold * 100));
    controls.querySelector("[data-volume-steps]").value = String(viewerState.steps);
  }

  updateProtocolPanel();

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

  const resizeObserver = new ResizeObserver(draw);
  resizeObserver.observe(container);
  draw();

  activeViewers.set(container, {
    delete() {
      resizeObserver.disconnect();
      gl.deleteTexture(texture);
      gl.deleteBuffer(vertexBuffer);
      gl.deleteProgram(program);
    },
  });
}
