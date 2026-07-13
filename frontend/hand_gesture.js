/**
 * Browser hand-gesture controller for the 3D volume viewer.
 * Uses MediaPipe Hand Landmarker (Tasks Vision) via CDN.
 *
 * Interaction design (aligned with common 3D / medical gesture systems):
 * - One hand pinch + move  → rotate (pinch-to-rotate)
 * - Open palm drag         → gentle rotate (CatGo-style)
 * - Two hands distance     → zoom (bimanual, log-scaled)
 * - Index point            → cursor / organ hover
 * - Pinch tap / fist       → select
 * - Peace                  → isolate
 * - Thumbs up              → reset view
 */

const VISION_WASM =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const GESTURE_TEXT = {
  none: "未检测到手",
  point: "食指指向",
  open: "张开手掌",
  pinch: "捏合抓取",
  select: "OK 选中特写",
  peace: "比耶隔离特写",
  thumbs_up: "竖拇指重置",
  fist: "握拳选中特写",
  two_hand_zoom: "双手缩放",
};

function dist3(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = (a.z || 0) - (b.z || 0);
  return Math.hypot(dx, dy, dz);
}

function dist2(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function fingerExtended(landmarks, tip, pip, mcp) {
  const wrist = landmarks[0];
  const tipWrist = dist3(landmarks[tip], wrist);
  const pipWrist = dist3(landmarks[pip], wrist);
  const tipMcp = dist3(landmarks[tip], landmarks[mcp]);
  const pipMcp = dist3(landmarks[pip], landmarks[mcp]);
  return tipWrist > pipWrist * 0.95 || tipMcp > pipMcp * 1.02;
}

function classifyHand(landmarks) {
  const thumbTip = landmarks[4];
  const indexTip = landmarks[8];
  const middleTip = landmarks[12];
  const pinkyTip = landmarks[20];

  const pinch = dist3(thumbTip, indexTip);
  const okPinch = dist3(thumbTip, middleTip);
  const openSpan = dist3(thumbTip, pinkyTip);

  const indexUp = fingerExtended(landmarks, 8, 6, 5);
  const middleUp = fingerExtended(landmarks, 12, 10, 9);
  const ringUp = fingerExtended(landmarks, 16, 14, 13);
  const pinkyUp = fingerExtended(landmarks, 20, 18, 17);
  const thumbUp = fingerExtended(landmarks, 4, 3, 2);
  const extendedCount = [indexUp, middleUp, ringUp, pinkyUp].filter(Boolean).length;
  const isOpenPalm = extendedCount >= 3 || openSpan > 0.22;
  const isPoint = indexUp && !middleUp && !ringUp && !pinkyUp && pinch > 0.06;
  const isPinch = pinch < 0.055 && extendedCount <= 2;

  let gesture = "open";
  if (okPinch < 0.05 && indexUp && !isOpenPalm) gesture = "select";
  else if (isPinch) gesture = "pinch";
  else if (indexUp && middleUp && !ringUp && !pinkyUp) gesture = "peace";
  else if (thumbUp && extendedCount <= 1) gesture = "thumbs_up";
  else if (isPoint) gesture = "point";
  else if (extendedCount === 0 && pinch > 0.07) gesture = "fist";
  else if (isOpenPalm) gesture = "open";

  const palm = {
    x: (landmarks[0].x + landmarks[9].x) / 2,
    y: (landmarks[0].y + landmarks[9].y) / 2,
    z: ((landmarks[0].z || 0) + (landmarks[9].z || 0)) / 2,
  };

  return {
    gesture,
    pinch,
    openSpan,
    extendedCount,
    isPinch,
    isOpenPalm,
    isPoint,
    cursor: { x: indexTip.x, y: indexTip.y, z: indexTip.z || 0 },
    palm,
    landmarks,
  };
}

function buildCoach(mode, present, handCount, calibrateMode, progress, motionSpread) {
  if (!present) {
    return {
      step: 1,
      title: "第 1 步：把手放进画面",
      tip: "单手或双手均可。正对摄像头，距离约 40–80cm。双手缩放时请两只手都入镜。",
      ok: false,
    };
  }
  if (!calibrateMode) {
    const modeText = {
      rotate: "捏合拖动 → 旋转",
      palm_rotate: "张开拖动 → 轻旋转",
      zoom: "双手开合 → 缩放",
      point: "食指指向 → 悬停器官",
      idle: "等待手势",
    };
    return {
      step: 0,
      title: `模式：${modeText[mode] || mode}`,
      tip: "捏合拖=旋转 · 开合=缩放 · 食指=悬停 · OK/拳=选中特写 · 比耶=隔离 · 👍=重置",
      ok: true,
    };
  }
  if (handCount < 1) {
    return { step: 2, title: "第 2 步：伸出一只手", tip: "掌心朝摄像头，五指自然张开。", ok: false };
  }
  if (motionSpread > 0.07) {
    return {
      step: 3,
      title: "第 3 步：尽量保持静止",
      tip: "检测到晃动。稳住约 0.5 秒完成校准。",
      ok: false,
    };
  }
  if (progress < 1) {
    return {
      step: 3,
      title: `第 3 步：保持静止 ${Math.round(progress * 100)}%`,
      tip: "继续保持，进度满后自动设为中心。",
      ok: true,
    };
  }
  return { step: 4, title: "校准完成", tip: "当前手掌位置已设为画面中心。", ok: true };
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

export async function createHandGestureController(options = {}) {
  const onFrame = typeof options.onFrame === "function" ? options.onFrame : () => {};
  const onStatus = typeof options.onStatus === "function" ? options.onStatus : () => {};
  const mirrored = options.mirrored !== false;

  const video = document.createElement("video");
  video.setAttribute("playsinline", "true");
  video.muted = true;
  video.autoplay = true;

  let stream = null;
  let landmarker = null;
  let raf = 0;
  let running = false;
  let lastVideoTime = -1;
  let centerOffset = { x: 0.5, y: 0.5 };
  let calibrated = false;
  let calibratingUntil = 0;
  let calmSamples = [];
  let lastSelectAt = 0;
  let lastPeaceAt = 0;
  let lastResetAt = 0;
  let lastCalibrateAt = 0;
  let calibrateMode = false;
  let lastPalm = null;
  let prevPrimary = null;
  let prevHandGap = null;
  let smoothCursor = { x: 0.5, y: 0.5 };
  let smoothDelta = { x: 0, y: 0 };
  let smoothZoomDelta = 0;
  let gestureHold = { name: "open", count: 0 };

  onStatus("正在加载双手手势模型…");
  const vision = await import(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/+esm"
  );
  const { FilesetResolver, HandLandmarker } = vision;
  const fileset = await FilesetResolver.forVisionTasks(VISION_WASM);

  async function createLandmarker(delegate) {
    return HandLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: MODEL_URL,
        delegate,
      },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: 0.5,
      minHandPresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
  }

  try {
    landmarker = await createLandmarker("GPU");
  } catch (error) {
    console.warn("HandLandmarker GPU failed, falling back to CPU", error);
    landmarker = await createLandmarker("CPU");
  }

  function mapX(x) {
    return mirrored ? 1 - x : x;
  }

  function applyCalibration(avgX, avgY, now, source = "auto") {
    centerOffset = { x: mapX(avgX), y: avgY };
    calibrated = true;
    calibrateMode = false;
    calibratingUntil = now + 1200;
    calmSamples = [];
    lastCalibrateAt = now;
    onStatus(source === "instant" ? "已用当前位置设为中心" : "引导校准完成：手掌位置 = 画面中心");
  }

  function beginCalibration() {
    calibrateMode = true;
    calmSamples = [];
    onStatus("进入引导校准：按下方步骤操作，或点「一键设为中心」");
  }

  function cancelCalibration() {
    calibrateMode = false;
    calmSamples = [];
    onStatus("已取消校准，可继续用手势控制");
  }

  function calibrateNow() {
    if (!lastPalm) {
      onStatus("未检测到手：请先把手放进摄像头画面");
      return false;
    }
    applyCalibration(lastPalm.x, lastPalm.y, performance.now(), "instant");
    return true;
  }

  function stabilizeGesture(name) {
    if (gestureHold.name === name) gestureHold.count += 1;
    else gestureHold = { name, count: 1 };
    // Require 2 consecutive frames to accept discrete gestures (anti-flicker).
    if (["select", "fist", "peace", "thumbs_up"].includes(name) && gestureHold.count < 2) {
      return gestureHold.prev || "open";
    }
    gestureHold.prev = name;
    return name;
  }

  async function start() {
    if (running) return;
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    running = true;
    onStatus("双手手势已就绪。单手捏合拖=旋转，双手开合=缩放");
    const loop = () => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (video.readyState < 2) return;
      const now = performance.now();
      if (video.currentTime === lastVideoTime) return;
      lastVideoTime = video.currentTime;
      const result = landmarker.detectForVideo(video, now);
      const allLandmarks = result?.landmarks || [];

      if (!allLandmarks.length) {
        lastPalm = null;
        prevPrimary = null;
        prevHandGap = null;
        const coach = buildCoach("idle", false, 0, calibrateMode, 0, 0);
        onFrame({
          present: false,
          handCount: 0,
          video,
          mirrored,
          calibrated,
          calibrateMode,
          calibrateProgress: 0,
          coach,
          gesture: "none",
          gestureText: GESTURE_TEXT.none,
          mode: "idle",
          rotateDelta: { x: 0, y: 0 },
          zoomDelta: 0,
          landmarks: null,
          hands: [],
        });
        return;
      }

      const hands = allLandmarks.map((lm) => classifyHand(lm));
      // Prefer right-looking hand (larger x before mirror) as primary for pointing/rotate.
      hands.sort((a, b) => b.palm.x - a.palm.x);
      const primary = hands[0];
      const secondary = hands[1] || null;
      lastPalm = primary.palm;

      let mode = "idle";
      let rotateDelta = { x: 0, y: 0 };
      let zoomDelta = 0;
      let activeGesture = primary.gesture;

      if (hands.length >= 2 && secondary) {
        const gap = dist2(primary.palm, secondary.palm);
        if (prevHandGap != null) {
          // Log-ish scaling: positive = hands farther = zoom in (cam closer).
          const raw = (gap - prevHandGap) * 2.8;
          zoomDelta = Math.max(-0.12, Math.min(0.12, raw));
        }
        prevHandGap = gap;
        mode = "zoom";
        activeGesture = "two_hand_zoom";
        prevPrimary = { palm: primary.palm, cursor: primary.cursor };
      } else {
        prevHandGap = null;
        const usePinchRotate = primary.isPinch || primary.gesture === "pinch";
        const usePalmRotate = primary.isOpenPalm && !primary.isPoint;
        if ((usePinchRotate || usePalmRotate) && prevPrimary) {
          const dx = mapX(primary.palm.x) - mapX(prevPrimary.palm.x);
          const dy = primary.palm.y - prevPrimary.palm.y;
          const gain = usePinchRotate ? 2.6 : 1.35;
          rotateDelta = {
            x: Math.max(-0.08, Math.min(0.08, dx * gain)),
            y: Math.max(-0.08, Math.min(0.08, dy * gain)),
          };
          mode = usePinchRotate ? "rotate" : "palm_rotate";
          // CatGo-style: while pinching with little lateral move, finger gap → zoom.
          if (
            usePinchRotate &&
            prevPrimary.pinch != null &&
            Math.hypot(dx, dy) < 0.01
          ) {
            const raw = (prevPrimary.pinch - primary.pinch) * 2.4;
            zoomDelta = Math.max(-0.1, Math.min(0.1, raw));
            if (Math.abs(zoomDelta) > 0.008) mode = "zoom";
          }
        } else if (primary.isPoint || primary.gesture === "point") {
          mode = "point";
        }
        prevPrimary = { palm: primary.palm, cursor: primary.cursor, pinch: primary.pinch };
      }

      activeGesture = stabilizeGesture(activeGesture);

      let cx = mapX(primary.cursor.x);
      let cy = primary.cursor.y;
      cx = Math.max(0, Math.min(1, cx - centerOffset.x + 0.5));
      cy = Math.max(0, Math.min(1, cy - centerOffset.y + 0.5));
      smoothCursor = {
        x: lerp(smoothCursor.x, cx, 0.35),
        y: lerp(smoothCursor.y, cy, 0.35),
      };
      smoothDelta = {
        x: lerp(smoothDelta.x, rotateDelta.x, 0.45),
        y: lerp(smoothDelta.y, rotateDelta.y, 0.45),
      };
      smoothZoomDelta = lerp(smoothZoomDelta, zoomDelta, 0.4);

      let motionSpread = 0;
      if (calibrateMode) {
        calmSamples.push({ x: primary.palm.x, y: primary.palm.y, t: now });
        calmSamples = calmSamples.filter((s) => now - s.t < 900);
        if (calmSamples.length >= 2) {
          const xs = calmSamples.map((s) => s.x);
          const ys = calmSamples.map((s) => s.y);
          motionSpread = Math.max(...xs) - Math.min(...xs) + (Math.max(...ys) - Math.min(...ys));
          if (motionSpread > 0.1) calmSamples = calmSamples.slice(-4);
        }
        if (calmSamples.length >= 8 && motionSpread <= 0.08 && now - lastCalibrateAt > 800) {
          const avgX = calmSamples.reduce((s, p) => s + p.x, 0) / calmSamples.length;
          const avgY = calmSamples.reduce((s, p) => s + p.y, 0) / calmSamples.length;
          applyCalibration(avgX, avgY, now, "guided");
        }
      } else {
        calmSamples = [];
      }

      let selectPulse = false;
      if (!calibrateMode && (activeGesture === "select" || activeGesture === "fist") && now - lastSelectAt > 900) {
        lastSelectAt = now;
        selectPulse = true;
      }
      let peacePulse = false;
      if (!calibrateMode && activeGesture === "peace" && now - lastPeaceAt > 1000) {
        lastPeaceAt = now;
        peacePulse = true;
      }
      let resetPulse = false;
      if (!calibrateMode && activeGesture === "thumbs_up" && now - lastResetAt > 1200) {
        lastResetAt = now;
        resetPulse = true;
      }

      const progress = calibrateMode ? Math.min(1, calmSamples.length / 8) : calibrated ? 1 : 0;
      const coach = buildCoach(mode, true, hands.length, calibrateMode, progress, motionSpread);

      onFrame({
        present: true,
        handCount: hands.length,
        video,
        mirrored,
        gesture: activeGesture,
        gestureText: GESTURE_TEXT[activeGesture] || activeGesture,
        mode,
        rotateDelta: { ...smoothDelta },
        zoomDelta: smoothZoomDelta,
        openAmount: Math.max(0, Math.min(1, (primary.pinch - 0.03) / 0.18)),
        pinch: primary.pinch,
        extendedCount: primary.extendedCount,
        openSpan: primary.openSpan,
        cursor: { ...smoothCursor },
        rawCursor: primary.cursor,
        palm: primary.palm,
        calibrating: calibrateMode || now < calibratingUntil,
        calibrateMode,
        calibrateProgress: progress,
        calibrated,
        coach,
        selectPulse,
        peacePulse,
        resetPulse,
        landmarks: primary.landmarks,
        handsLandmarks: allLandmarks,
      });
    };
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    cancelAnimationFrame(raf);
    raf = 0;
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      stream = null;
    }
    video.srcObject = null;
    prevPrimary = null;
    prevHandGap = null;
    onStatus("手势已关闭");
  }

  function dispose() {
    stop();
    try {
      landmarker?.close?.();
    } catch {
      // ignore
    }
    landmarker = null;
  }

  return {
    start,
    stop,
    dispose,
    beginCalibration,
    cancelCalibration,
    calibrateNow,
    isRunning: () => running,
    isCalibrateMode: () => calibrateMode,
    getVideo: () => video,
  };
}
