const activeViewers = new WeakMap();

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

  const response = await fetch(`/api/image/${imageId}/volume-data?max_dim=${maxDim}&window=${windowName}`);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`体数据接口失败：${message}`);
  }

  const volumeData = await response.json();
  const values = decodeBase64ToUint8Array(volumeData.values_base64);

  status.textContent = "正在初始化 WebGL2 体渲染引擎...";
  renderWithWebGL({ container, volumeData, values });
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
  badge.textContent = "WebGL2 真实体渲染";
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
        vec3 cancellous = vec3(0.72, 0.63, 0.50);
        vec3 cortical = vec3(1.0, 0.94, 0.78);
        vec3 bone = mix(cancellous, cortical, smoothstep(220.0, 1200.0, hu));
        return mix(bone, vec3(1.0), edge * 0.18);
      }
      if (uRenderMode == 2) {
        vec3 lung = vec3(0.26, 0.45, 0.58);
        vec3 vessel = vec3(0.83, 0.90, 0.90);
        vec3 dense = vec3(1.0, 0.91, 0.74);
        vec3 c = mix(lung, vessel, smoothstep(-420.0, 180.0, hu));
        c = mix(c, dense, smoothstep(260.0, 900.0, hu));
        return mix(c, vec3(1.0), edge * 0.14);
      }
      vec3 fat = vec3(0.72, 0.58, 0.38);
      vec3 muscle = vec3(0.73, 0.55, 0.52);
      vec3 vessel = vec3(0.93, 0.86, 0.76);
      vec3 bone = vec3(1.0, 0.94, 0.78);
      vec3 c = mix(fat, muscle, smoothstep(-70.0, 85.0, hu));
      c = mix(c, vessel, smoothstep(90.0, 260.0, hu));
      c = mix(c, bone, smoothstep(320.0, 950.0, hu));
      return mix(c, vec3(1.0), edge * 0.16);
    }

    float transferOpacity(float hu, float edge) {
      if (uRenderMode == 1) {
        float floorHu = mix(140.0, 620.0, uThreshold);
        if (hu < floorHu) {
          return 0.0;
        }
        float cortical = smoothstep(220.0, 1050.0, hu) * 0.070;
        float denseEdge = edge * smoothstep(160.0, 700.0, hu) * 0.030;
        return (cortical + denseEdge) * uOpacityScale;
      }
      if (uRenderMode == 2) {
        if (hu < -980.0) {
          return 0.0;
        }
        float lung = band(hu, -900.0, -450.0, 100.0) * 0.004;
        float airwayEdge = edge * band(hu, -950.0, -280.0, 140.0) * 0.018;
        float vessel = smoothstep(-120.0, 220.0, hu) * (1.0 - smoothstep(420.0, 900.0, hu)) * 0.026;
        float bone = smoothstep(260.0, 1050.0, hu) * 0.030;
        return (lung + airwayEdge + vessel + bone) * uOpacityScale;
      }

      float floorHu = mix(-260.0, 90.0, uThreshold);
      if (hu < floorHu) {
        return 0.0;
      }
      float fat = band(hu, -180.0, -25.0, 45.0) * 0.010;
      float muscle = band(hu, -20.0, 115.0, 42.0) * 0.030;
      float vessel = band(hu, 90.0, 330.0, 70.0) * 0.050;
      float bone = smoothstep(300.0, 1100.0, hu) * 0.032;
      float gradientBoost = mix(0.45, 1.85, edge);
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
      vec3 lit = color * (0.30 + 0.64 * diffuse + 0.18 * rim);
      return lit + vec3(1.0, 0.94, 0.82) * specular * 0.22;
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

      for (int i = 0; i < 256; i++) {
        if (float(i) >= uSteps || alpha > 0.96) {
          break;
        }
        vec3 p = rayOrigin + rayDir * (nearHit + (float(i) + 0.5) * dt);
        float value = texture(uVolume, p).r;
        float hu = huFromValue(value);
        vec3 gradient = gradientAt(p);
        float edge = smoothstep(0.018, 0.145, length(gradient) * 2.8);
        float opacity = clamp(transferOpacity(hu, edge), 0.0, 0.18);
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

  const viewerState = {
    yaw: 0.65,
    pitch: -0.28,
    opacityScale: 1.08,
    brightness: 1.06,
    threshold: 0.15,
    steps: 224,
    renderMode: 0,
    dragging: false,
    lastX: 0,
    lastY: 0,
  };

  const controls = document.createElement("div");
  controls.className = "volume-control-panel";
  controls.innerHTML = `
    <label>渲染模式
      <select data-volume-mode>
        <option value="0">软组织综合</option>
        <option value="1">骨窗高密度</option>
        <option value="2">肺窗边界</option>
      </select>
    </label>
    <label>透明度
      <input data-volume-opacity type="range" min="20" max="180" value="108" />
    </label>
    <label>亮度
      <input data-volume-brightness type="range" min="70" max="170" value="106" />
    </label>
    <label>组织阈值
      <input data-volume-threshold type="range" min="0" max="100" value="15" />
    </label>
    <label>质量
      <input data-volume-steps type="range" min="128" max="256" value="224" />
    </label>
  `;
  container.appendChild(controls);

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
    gl.uniform3f(
      uniforms.voxelStep,
      1 / Math.max(volumeData.dimensions[0], 1),
      1 / Math.max(volumeData.dimensions[1], 1),
      1 / Math.max(volumeData.dimensions[2], 1)
    );
    gl.uniform1i(uniforms.renderMode, viewerState.renderMode);
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
  controls.querySelector("[data-volume-mode]").addEventListener("change", (event) => {
    viewerState.renderMode = Number(event.target.value);
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
