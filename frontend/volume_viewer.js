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

export async function renderVolume3D({
  container,
  imageId,
  maskId = null,
  windowName = "volume",
  maxDim = 176,
  isotropic = true,
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
  let maskData = null;
  let maskValues = null;
  if (maskId) {
    status.textContent = "正在读取 3D Mask 实体数据...";
    const maskResponse = await fetch(apiUrl(`/api/mask/${maskId}/volume-data?max_dim=${maxDim}`));
    if (!maskResponse.ok) {
      const message = await maskResponse.text();
      throw new Error(`3D Mask 接口失败：${message}`);
    }
    maskData = await maskResponse.json();
    maskValues = decodeBase64ToUint8Array(maskData.values_base64);
  }

  status.textContent = "正在初始化 WebGL2 体渲染引擎...";
  renderWithWebGL({ container, volumeData, values, maskData, maskValues });
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

function renderWithWebGL({ container, volumeData, values, maskData = null, maskValues = null }) {
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
          if (maskValue > 0.001) {
            vec3 maskCore = vec3(0.00, 1.00, 0.74);
            vec3 maskRim = vec3(1.00, 0.94, 0.20);
            float maskEdge = smoothstep(0.12, 0.70, length(gradient) * 3.2);
            vec3 maskSampleColor = mix(maskCore, maskRim, maskEdge);
            float maskAlpha = mix(0.16, 0.30, clamp(maskValue, 0.0, 1.0));
            maskColorAccum += (1.0 - maskAlphaAccum) * maskAlpha * maskSampleColor;
            maskAlphaAccum += (1.0 - maskAlphaAccum) * maskAlpha;
            sampleColor = mix(sampleColor, maskSampleColor, 0.72);
            opacity = max(opacity, 0.065);
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
    <div class="tf-editor-mini">
      <strong>Transfer Function Editor</strong>
      <span>HU 分段透明度 + Gradient Opacity + Ray Marching 采样</span>
    </div>
  `;
  container.appendChild(controls);

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
    gl.useProgram(program);
    gl.clearColor(0.01, 0.025, 0.045, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT);
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
    const resampling = volumeData.resampling || {};
    const spacing = Array.isArray(volumeData.spacing) ? volumeData.spacing.map((value) => Number(value).toFixed(2)).join(" / ") : "-";
    const maskText = maskTexture
      ? `Mask 实体叠加：${maskData.mask_id} · ${maskData.version} · ${maskData.dimensions.join("×")}`
      : (maskData ? "Mask 尺寸与 CT 体数据不一致，已跳过叠加" : "未加载 3D Mask");
    const resampleText = resampling.requested
      ? (resampling.applied ? "各向同性重采样已启用" : `各向同性重采样未启用：${resampling.reason || "无需处理"}`)
      : "使用原始 spacing";
    protocolPanel.classList.toggle("collapsed", protocolCollapsed);
    protocolPanel.innerHTML = `
      <button class="protocol-toggle" type="button" data-protocol-toggle>
        <span>Rendering Protocol</span>
        <strong>${viewerState.preset.label}</strong>
        <b>${protocolCollapsed ? "展开" : "收起"}</b>
      </button>
      <div class="protocol-details">
        <span>WL ${viewerState.preset.wl} / WW ${viewerState.preset.ww} · ${viewerState.preset.steps} samples · stop ${viewerState.preset.alphaStop}</span>
        <span>${resampleText} · spacing ${spacing} mm</span>
        <span>${maskText}</span>
        <p>${viewerState.preset.summary}</p>
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
      if (maskTexture) gl.deleteTexture(maskTexture);
      gl.deleteBuffer(vertexBuffer);
      gl.deleteProgram(program);
    },
  });
}
