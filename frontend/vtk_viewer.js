const VTK_VERSION = "36.2.1";
const VTK_BUNDLE_URL = `https://esm.sh/@kitware/vtk.js@${VTK_VERSION}?bundle`;
const activeViewers = new WeakMap();

let vtkModulesPromise = null;

async function loadVtkModules() {
  if (!vtkModulesPromise) {
    vtkModulesPromise = import(VTK_BUNDLE_URL).then((module) => {
      const vtk = module.default || module;
      const modules = {
        vtkGenericRenderWindow: vtk.Rendering?.Misc?.vtkGenericRenderWindow,
        vtkImageData: vtk.Common?.DataModel?.vtkImageData,
        vtkDataArray: vtk.Common?.Core?.vtkDataArray,
        vtkVolume: vtk.Rendering?.Core?.vtkVolume,
        vtkVolumeMapper: vtk.Rendering?.Core?.vtkVolumeMapper,
        vtkColorTransferFunction: vtk.Rendering?.Core?.vtkColorTransferFunction,
        vtkPiecewiseFunction: vtk.Common?.DataModel?.vtkPiecewiseFunction,
      };

      const missing = Object.entries(modules)
        .filter(([, value]) => !value?.newInstance)
        .map(([name]) => name);
      if (missing.length) {
        throw new Error(`vtk.js bundle 缺少模块：${missing.join(", ")}`);
      }
      return modules;
    });
  }
  return vtkModulesPromise;
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

function configureVolumeProperty(actor, vtkColorTransferFunction, vtkPiecewiseFunction) {
  const ctfun = vtkColorTransferFunction.newInstance();
  ctfun.addRGBPoint(0, 0.0, 0.0, 0.0);
  ctfun.addRGBPoint(55, 0.18, 0.22, 0.28);
  ctfun.addRGBPoint(105, 0.78, 0.82, 0.86);
  ctfun.addRGBPoint(180, 0.95, 0.92, 0.82);
  ctfun.addRGBPoint(255, 1.0, 1.0, 1.0);

  const ofun = vtkPiecewiseFunction.newInstance();
  ofun.addPoint(0, 0.0);
  ofun.addPoint(45, 0.0);
  ofun.addPoint(90, 0.04);
  ofun.addPoint(150, 0.12);
  ofun.addPoint(255, 0.42);

  const property = actor.getProperty();
  property.setRGBTransferFunction(0, ctfun);
  property.setScalarOpacity(0, ofun);
  property.setScalarOpacityUnitDistance(0, 3.0);
  property.setInterpolationTypeToLinear();
  property.setShade(true);
  property.setAmbient(0.22);
  property.setDiffuse(0.72);
  property.setSpecular(0.28);
  property.setSpecularPower(18);
}

export async function renderVtkVolume({ container, imageId, windowName = "lung", maxDim = 144 }) {
  if (!container || !imageId) return;
  clearContainer(container);

  const status = document.createElement("div");
  status.className = "vtk-status";
  status.textContent = "正在读取真实 3D CT 体数据...";
  container.appendChild(status);

  const response = await fetch(`/api/image/${imageId}/vtk-volume?max_dim=${maxDim}&window=${windowName}`);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`体数据接口失败：${message}`);
  }

  const volumeData = await response.json();
  const values = decodeBase64ToUint8Array(volumeData.values_base64);

  status.textContent = "正在初始化 vtk.js 体渲染引擎...";
  try {
    const modules = await loadVtkModules();
    renderWithVtk({ container, modules, volumeData, values });
  } catch (error) {
    console.warn("vtk.js failed, falling back to local WebGL2 volume renderer", error);
    renderWithWebGL({ container, volumeData, values });
  }
}

function renderWithVtk({ container, modules, volumeData, values }) {
  clearContainer(container);
  const genericRenderWindow = modules.vtkGenericRenderWindow.newInstance({
    background: [0.02, 0.04, 0.07],
  });
  genericRenderWindow.setContainer(container);
  genericRenderWindow.resize();

  const renderer = genericRenderWindow.getRenderer();
  const renderWindow = genericRenderWindow.getRenderWindow();

  const imageData = modules.vtkImageData.newInstance();
  imageData.setDimensions(...volumeData.dimensions);
  imageData.setSpacing(...volumeData.spacing);
  imageData.setOrigin(...volumeData.origin);
  imageData.getPointData().setScalars(
    modules.vtkDataArray.newInstance({
      name: "CTVolume",
      values,
      numberOfComponents: 1,
    })
  );

  const mapper = modules.vtkVolumeMapper.newInstance();
  mapper.setInputData(imageData);
  mapper.setSampleDistance(Math.max(...volumeData.spacing) * 0.75);

  const actor = modules.vtkVolume.newInstance();
  actor.setMapper(mapper);
  configureVolumeProperty(actor, modules.vtkColorTransferFunction, modules.vtkPiecewiseFunction);

  renderer.addVolume(actor);
  renderer.resetCamera();
  const camera = renderer.getActiveCamera();
  camera.azimuth(35);
  camera.elevation(22);
  renderer.resetCameraClippingRange();
  renderWindow.render();

  activeViewers.set(container, genericRenderWindow);

  const resizeObserver = new ResizeObserver(() => {
    genericRenderWindow.resize();
    renderWindow.render();
  });
  resizeObserver.observe(container);
  const originalDelete = genericRenderWindow.delete.bind(genericRenderWindow);
  genericRenderWindow.delete = () => {
    resizeObserver.disconnect();
    originalDelete();
  };
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
      vec3 delta = vec3(1.0 / 96.0);
      float gx = texture(uVolume, p + vec3(delta.x, 0.0, 0.0)).r - texture(uVolume, p - vec3(delta.x, 0.0, 0.0)).r;
      float gy = texture(uVolume, p + vec3(0.0, delta.y, 0.0)).r - texture(uVolume, p - vec3(0.0, delta.y, 0.0)).r;
      float gz = texture(uVolume, p + vec3(0.0, 0.0, delta.z)).r - texture(uVolume, p - vec3(0.0, 0.0, delta.z)).r;
      return vec3(gx, gy, gz);
    }

    vec3 transferColor(float value, float edge) {
      if (uRenderMode == 1) {
        vec3 marrow = vec3(0.72, 0.66, 0.58);
        vec3 cortical = vec3(1.0, 0.92, 0.76);
        return mix(marrow, cortical, smoothstep(0.58, 0.98, value));
      }
      if (uRenderMode == 2) {
        vec3 tissue = vec3(0.52, 0.66, 0.78);
        vec3 dense = vec3(0.96, 0.88, 0.74);
        return mix(tissue, dense, smoothstep(0.35, 0.90, value));
      }
      vec3 air = vec3(0.015, 0.035, 0.055);
      vec3 lung = vec3(0.30, 0.48, 0.58);
      vec3 vessel = vec3(0.78, 0.86, 0.88);
      vec3 dense = vec3(1.0, 0.92, 0.78);
      vec3 c = mix(air, lung, smoothstep(0.12, 0.34, value));
      c = mix(c, vessel, smoothstep(0.34, 0.68, value));
      c = mix(c, dense, smoothstep(0.68, 1.0, value));
      return mix(c, vec3(1.0), edge * 0.16);
    }

    float transferOpacity(float value, float edge) {
      if (uRenderMode == 1) {
        return (smoothstep(0.52, 0.90, value) * 0.080 + edge * 0.018) * uOpacityScale;
      }
      if (uRenderMode == 2) {
        return (smoothstep(0.28, 0.84, value) * 0.050 + edge * 0.012) * uOpacityScale;
      }
      float vessel = smoothstep(0.38, 0.82, value) * 0.045;
      float parenchyma = smoothstep(0.16, 0.36, value) * (1.0 - smoothstep(0.48, 0.68, value)) * 0.012;
      return (vessel + parenchyma + edge * 0.010) * uOpacityScale;
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

      for (int i = 0; i < 192; i++) {
        if (float(i) >= uSteps || alpha > 0.96) {
          break;
        }
        vec3 p = rayOrigin + rayDir * (nearHit + (float(i) + 0.5) * dt);
        float value = texture(uVolume, p).r;
        float edge = length(gradientAt(p)) * 2.6;
        float opacity = clamp(transferOpacity(value, edge), 0.0, 0.16);
        vec3 sampleColor = transferColor(value, edge);
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
    opacityScale: 1.25,
    brightness: 1.18,
    steps: 176,
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
        <option value="0">肺部增强</option>
        <option value="1">骨窗高密度</option>
        <option value="2">软组织</option>
      </select>
    </label>
    <label>透明度
      <input data-volume-opacity type="range" min="40" max="220" value="125" />
    </label>
    <label>亮度
      <input data-volume-brightness type="range" min="70" max="180" value="118" />
    </label>
    <label>质量
      <input data-volume-steps type="range" min="80" max="192" value="176" />
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
