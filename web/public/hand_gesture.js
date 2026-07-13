/**
 * Browser hand-gesture controller for the 3D volume viewer.
 * Uses MediaPipe Hand Landmarker (Tasks Vision) via CDN.
 */

const VISION_WASM =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const GESTURE_TEXT = {
  none: "未检测到手",
  move: "移动中",
  open: "张开手掌",
  pinch: "捏合/收缩",
  select: "OK 选中",
  peace: "比耶",
  thumbs_up: "竖大拇指",
  fist: "握拳",
};

function dist3(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = (a.z || 0) - (b.z || 0);
  return Math.hypot(dx, dy, dz);
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
  const openScore = extendedCount / 4 + Math.max(0, Math.min(1, (openSpan - 0.1) / 0.28));
  const isOpenPalm = extendedCount >= 2 || openSpan > 0.18 || openScore >= 0.9;

  let gesture = "move";
  if (okPinch < 0.055 && indexUp && !isOpenPalm) gesture = "select";
  else if (pinch < 0.05 && extendedCount <= 1) gesture = "pinch";
  else if (indexUp && middleUp && !ringUp && !pinkyUp) gesture = "peace";
  else if (thumbUp && extendedCount <= 1) gesture = "thumbs_up";
  else if (isOpenPalm) gesture = "open";
  else if (extendedCount === 0 && pinch > 0.06) gesture = "fist";

  const openAmount = Math.max(0, Math.min(1, (pinch - 0.03) / 0.18));

  return {
    gesture,
    pinch,
    openAmount,
    openSpan,
    openScore,
    extendedCount,
    cursor: { x: indexTip.x, y: indexTip.y, z: indexTip.z || 0 },
    palm: {
      x: (landmarks[0].x + landmarks[9].x) / 2,
      y: (landmarks[0].y + landmarks[9].y) / 2,
    },
  };
}

function buildCoach(parsed, present, calibrateMode, progress, motionSpread) {
  if (!present) {
    return {
      step: 1,
      title: "第 1 步：把手放进画面",
      tip: "请将一只手正对摄像头，放到绿色框内，距离约 40–80cm，光线尽量均匀。",
      ok: false,
    };
  }
  if (!calibrateMode) {
    return {
      step: 0,
      title: `当前手势：${GESTURE_TEXT[parsed.gesture] || parsed.gesture}`,
      tip: "可直接收缩/舒展控制进深。需要校准中心时，点「开始引导校准」。",
      ok: true,
    };
  }
  if (parsed.extendedCount < 2 && parsed.openSpan < 0.15) {
    return {
      step: 2,
      title: "第 2 步：五指尽量张开",
      tip: `当前张开不够（已伸展 ${parsed.extendedCount}/4 指）。请掌心朝摄像头，五指张开。`,
      ok: false,
    };
  }
  if (motionSpread > 0.06) {
    return {
      step: 3,
      title: "第 3 步：尽量保持静止",
      tip: "检测到手在晃动。请像拍照一样稳住 0.5 秒，进度条会上涨。",
      ok: false,
    };
  }
  if (progress < 1) {
    return {
      step: 3,
      title: `第 3 步：保持静止 ${Math.round(progress * 100)}%`,
      tip: "很好！继续保持张开手掌静止，进度满后自动完成校准。",
      ok: true,
    };
  }
  return {
    step: 4,
    title: "校准完成",
    tip: "当前手掌位置已设为画面中心。",
    ok: true,
  };
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

  onStatus("正在加载手势模型…");
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
      numHands: 1,
      minHandDetectionConfidence: 0.45,
      minHandPresenceConfidence: 0.45,
      minTrackingConfidence: 0.45,
    });
  }

  try {
    landmarker = await createLandmarker("GPU");
  } catch (error) {
    console.warn("HandLandmarker GPU failed, falling back to CPU", error);
    landmarker = await createLandmarker("CPU");
  }

  function applyCalibration(avgX, avgY, now, source = "auto") {
    const mx = mirrored ? 1 - avgX : avgX;
    centerOffset = { x: mx, y: avgY };
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

  async function start() {
    if (running) return;
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    running = true;
    onStatus("手势已就绪。建议先点「开始引导校准」，或「一键设为中心」");
    const loop = () => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (video.readyState < 2) return;
      const now = performance.now();
      if (video.currentTime === lastVideoTime) return;
      lastVideoTime = video.currentTime;
      const result = landmarker.detectForVideo(video, now);
      const landmarks = result?.landmarks?.[0];

      if (!landmarks) {
        lastPalm = null;
        const coach = buildCoach(null, false, calibrateMode, 0, 0);
        onFrame({
          present: false,
          video,
          mirrored,
          calibrated,
          calibrateMode,
          calibrateProgress: 0,
          coach,
          gesture: "none",
          gestureText: GESTURE_TEXT.none,
          landmarks: null,
        });
        return;
      }

      const parsed = classifyHand(landmarks);
      lastPalm = parsed.palm;
      let cx = mirrored ? 1 - parsed.cursor.x : parsed.cursor.x;
      let cy = parsed.cursor.y;
      cx = Math.max(0, Math.min(1, cx - centerOffset.x + 0.5));
      cy = Math.max(0, Math.min(1, cy - centerOffset.y + 0.5));

      let motionSpread = 0;
      // In calibrate mode: accumulate when hand is visible enough; much more forgiving.
      if (calibrateMode) {
        const openish =
          parsed.gesture === "open" ||
          parsed.extendedCount >= 2 ||
          parsed.openSpan > 0.15 ||
          parsed.openScore >= 0.85;
        if (openish) {
          calmSamples.push({ x: parsed.palm.x, y: parsed.palm.y, t: now });
          calmSamples = calmSamples.filter((s) => now - s.t < 900);
          if (calmSamples.length >= 2) {
            const xs = calmSamples.map((s) => s.x);
            const ys = calmSamples.map((s) => s.y);
            motionSpread = Math.max(...xs) - Math.min(...xs) + (Math.max(...ys) - Math.min(...ys));
            if (motionSpread > 0.1) calmSamples = calmSamples.slice(-4);
          }
          // Only need ~8 stable frames (~0.4–0.6s)
          if (calmSamples.length >= 8 && motionSpread <= 0.08 && now - lastCalibrateAt > 800) {
            const avgX = calmSamples.reduce((s, p) => s + p.x, 0) / calmSamples.length;
            const avgY = calmSamples.reduce((s, p) => s + p.y, 0) / calmSamples.length;
            applyCalibration(avgX, avgY, now, "guided");
          }
        } else {
          const newest = calmSamples[calmSamples.length - 1];
          if (!newest || now - newest.t > 400) calmSamples = [];
        }
      } else {
        calmSamples = [];
      }

      let selectPulse = false;
      if (!calibrateMode && (parsed.gesture === "select" || parsed.gesture === "fist") && now - lastSelectAt > 900) {
        lastSelectAt = now;
        selectPulse = true;
      }
      let peacePulse = false;
      if (!calibrateMode && parsed.gesture === "peace" && now - lastPeaceAt > 1000) {
        lastPeaceAt = now;
        peacePulse = true;
      }
      let resetPulse = false;
      if (!calibrateMode && parsed.gesture === "thumbs_up" && now - lastResetAt > 1200) {
        lastResetAt = now;
        resetPulse = true;
      }

      const progress = calibrateMode ? Math.min(1, calmSamples.length / 8) : calibrated ? 1 : 0;
      const coach = buildCoach(parsed, true, calibrateMode, progress, motionSpread);

      onFrame({
        present: true,
        video,
        mirrored,
        gesture: parsed.gesture,
        gestureText: GESTURE_TEXT[parsed.gesture] || parsed.gesture,
        openAmount: parsed.openAmount,
        pinch: parsed.pinch,
        extendedCount: parsed.extendedCount,
        openSpan: parsed.openSpan,
        cursor: { x: cx, y: cy },
        rawCursor: parsed.cursor,
        palm: parsed.palm,
        calibrating: calibrateMode || now < calibratingUntil,
        calibrateMode,
        calibrateProgress: progress,
        calibrated,
        coach,
        selectPulse,
        peacePulse,
        resetPulse,
        landmarks,
      });
    };
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    running = false;
    calibrateMode = false;
    cancelAnimationFrame(raf);
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    video.srcObject = null;
    lastPalm = null;
    onStatus("手势控制已关闭");
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
    video,
    start,
    stop,
    dispose,
    beginCalibration,
    cancelCalibration,
    calibrateNow,
    isRunning: () => running,
    isCalibrateMode: () => calibrateMode,
  };
}
