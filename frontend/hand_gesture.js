/**
 * Browser hand-gesture controller for the 3D volume viewer.
 * Uses MediaPipe Hand Landmarker (Tasks Vision) via CDN.
 */

const VISION_WASM =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

function dist3(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = (a.z || 0) - (b.z || 0);
  return Math.hypot(dx, dy, dz);
}

function fingerExtended(landmarks, tip, pip, mcp) {
  // Tip farther from wrist than PIP → roughly extended.
  const wrist = landmarks[0];
  return dist3(landmarks[tip], wrist) > dist3(landmarks[pip], wrist) * 1.05
    && dist3(landmarks[tip], landmarks[mcp]) > dist3(landmarks[pip], landmarks[mcp]) * 0.95;
}

function classifyHand(landmarks) {
  const thumbTip = landmarks[4];
  const indexTip = landmarks[8];
  const middleTip = landmarks[12];
  const ringTip = landmarks[16];
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

  let gesture = "move";
  if (okPinch < 0.05 && indexUp) gesture = "select"; // OK / thumb-middle
  else if (pinch < 0.045 && extendedCount <= 1) gesture = "pinch";
  else if (indexUp && middleUp && !ringUp && !pinkyUp) gesture = "peace";
  else if (thumbUp && extendedCount === 0) gesture = "thumbs_up";
  else if (extendedCount >= 4) gesture = "open";
  else if (extendedCount === 0 && pinch > 0.06) gesture = "fist";

  // 0 = fully contracted (体外), 1 = fully open (体内)
  const openAmount = Math.max(0, Math.min(1, (pinch - 0.03) / 0.18));

  return {
    gesture,
    pinch,
    openAmount,
    openSpan,
    cursor: { x: indexTip.x, y: indexTip.y, z: indexTip.z || 0 },
    palm: {
      x: (landmarks[0].x + landmarks[9].x) / 2,
      y: (landmarks[0].y + landmarks[9].y) / 2,
    },
    extendedCount,
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
  let centerOffset = { x: 0, y: 0 };
  let calibratingUntil = 0;
  let calmSamples = [];
  let lastSelectAt = 0;
  let lastPeaceAt = 0;
  let lastResetAt = 0;

  onStatus("正在加载手势模型…");
  const vision = await import(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/+esm"
  );
  const { FilesetResolver, HandLandmarker } = vision;
  const fileset = await FilesetResolver.forVisionTasks(VISION_WASM);
  landmarker = await HandLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath: MODEL_URL,
      delegate: "GPU",
    },
    runningMode: "VIDEO",
    numHands: 1,
    minHandDetectionConfidence: 0.55,
    minHandPresenceConfidence: 0.55,
    minTrackingConfidence: 0.55,
  });

  async function start() {
    if (running) return;
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    running = true;
    onStatus("手势控制已开启：张开手掌校准中心，收缩/舒展控制进深");
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
        onFrame({
          present: false,
          video,
          mirrored,
        });
        return;
      }

      const parsed = classifyHand(landmarks);
      // MediaPipe x is left→right in image; mirror for selfie camera UX.
      let cx = mirrored ? 1 - parsed.cursor.x : parsed.cursor.x;
      let cy = parsed.cursor.y;
      cx = Math.max(0, Math.min(1, cx - centerOffset.x + 0.5));
      cy = Math.max(0, Math.min(1, cy - centerOffset.y + 0.5));

      // Calibrate: open palm held still ~0.9s near intended center.
      if (parsed.gesture === "open") {
        calmSamples.push({ x: parsed.palm.x, y: parsed.palm.y, t: now });
        calmSamples = calmSamples.filter((s) => now - s.t < 900);
        if (calmSamples.length > 18) {
          const avgX = calmSamples.reduce((s, p) => s + p.x, 0) / calmSamples.length;
          const avgY = calmSamples.reduce((s, p) => s + p.y, 0) / calmSamples.length;
          const mx = mirrored ? 1 - avgX : avgX;
          centerOffset = { x: mx, y: avgY };
          calibratingUntil = now + 1200;
          calmSamples = [];
          onStatus("中心已校准：当前手掌位置对应画面中心");
        }
      } else {
        calmSamples = [];
      }

      let selectPulse = false;
      if ((parsed.gesture === "select" || parsed.gesture === "fist") && now - lastSelectAt > 900) {
        lastSelectAt = now;
        selectPulse = true;
      }
      let peacePulse = false;
      if (parsed.gesture === "peace" && now - lastPeaceAt > 1000) {
        lastPeaceAt = now;
        peacePulse = true;
      }
      let resetPulse = false;
      if (parsed.gesture === "thumbs_up" && now - lastResetAt > 1200) {
        lastResetAt = now;
        resetPulse = true;
      }

      onFrame({
        present: true,
        video,
        mirrored,
        gesture: parsed.gesture,
        openAmount: parsed.openAmount,
        pinch: parsed.pinch,
        cursor: { x: cx, y: cy },
        rawCursor: parsed.cursor,
        calibrating: now < calibratingUntil,
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
    cancelAnimationFrame(raf);
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    video.srcObject = null;
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
    isRunning: () => running,
  };
}
