/**
 * Browser hand-gesture controller for the 3D volume viewer.
 * Uses MediaPipe Hand Landmarker (Tasks Vision) via CDN.
 *
 * Interaction design (aligned with common 3D / medical gesture systems):
 * - One hand pinch + move  → rotate (pinch-to-rotate)
 * - Open palm drag         → gentle rotate (CatGo-style)
 * - Two hands distance     → zoom (bimanual, log-scaled)
 * - Index point            → cursor / organ hover
 * - Pinch tap (短捏一下)   → select + focus
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
  pinch: "捏合拖动",
  select: "捏一下选中",
  peace: "比耶隔离特写",
  thumbs_up: "竖拇指重置",
  fist: "握拳",
  two_hand_zoom: "双手缩放",
  knife: "发誓刀面切割",
  knife_idle: "手术刀待命（捏合收刀）",
  sheath: "捏合收刀",
  oath: "发誓立掌",
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
  // Slightly looser pinch so "捏一下" is easier to trigger.
  const isPinch = pinch < 0.07 && extendedCount <= 2;
  // 发誓：五指伸开、掌面朝前（立掌），用作手术刀刀面。
  const isOath = extendedCount >= 3 && openSpan > 0.18 && pinch > 0.06;

  let gesture = "open";
  if (isOath) gesture = "oath";
  else if (isPinch) gesture = "pinch";
  else if (indexUp && middleUp && !ringUp && !pinkyUp) gesture = "peace";
  else if (thumbUp && extendedCount <= 1) gesture = "thumbs_up";
  else if (isPoint) gesture = "point";
  else if (extendedCount === 0 && pinch > 0.08) gesture = "fist";
  else if (isOpenPalm) gesture = "open";
  else if (okPinch < 0.05 && indexUp && !isOpenPalm) gesture = "select";

  const palm = {
    x: (landmarks[0].x + landmarks[9].x) / 2,
    y: (landmarks[0].y + landmarks[9].y) / 2,
    z: ((landmarks[0].z || 0) + (landmarks[9].z || 0)) / 2,
  };
  // Palm blade basis (MediaPipe landmark indices).
  const indexMcp = landmarks[5];
  const pinkyMcp = landmarks[17];
  const wrist = landmarks[0];

  return {
    gesture,
    pinch,
    openSpan,
    extendedCount,
    isPinch,
    isOpenPalm,
    isOath,
    isPoint,
    cursor: { x: indexTip.x, y: indexTip.y, z: indexTip.z || 0 },
    palm,
    blade: {
      a: { x: indexMcp.x, y: indexMcp.y, z: indexMcp.z || 0 },
      b: { x: pinkyMcp.x, y: pinkyMcp.y, z: pinkyMcp.z || 0 },
      c: { x: middleTip.x, y: middleTip.y, z: middleTip.z || 0 },
      wrist: { x: wrist.x, y: wrist.y, z: wrist.z || 0 },
      palm,
    },
    landmarks,
  };
}

function buildCoach(mode, present, handCount, calibrateMode, progress, motionSpread, surgeryMode = false, surgeryPhase = "select") {
  if (!present) {
    return {
      step: 1,
      title: "第 1 步：把手放进画面",
      tip: surgeryMode
        ? "模拟手术：尽量双手入镜。先选器官，再给长方体ROI，最后切割。"
        : "单手或双手均可。正对摄像头，距离约 40–80cm。双手缩放时请两只手都入镜。",
      ok: false,
    };
  }
  if (!calibrateMode) {
    if (surgeryMode) {
      if (surgeryPhase === "select") {
        return {
          step: 1,
          title: "手术第1步：选中器官",
          tip: "左手食指指向目标器官 → 捏一下选中。选中前不能切割。",
          ok: mode === "point" || mode === "select",
        };
      }
      if (surgeryPhase === "roi") {
        return {
          step: 2,
          title: "手术第2步：确定长方体大小",
          tip: "拖动 ROI 边距看绿盒变化，满意后点「确定长方体 ROI 大小」。确认前不能切割。",
          ok: true,
        };
      }
      const modeText = {
        rotate: "视图手：旋转",
        palm_rotate: "视图手：轻旋转",
        zoom: "双手：缩放",
        point: "视图手：悬停器官",
        knife: "手术刀：切割中",
        knife_idle: "手术刀：待命（捏合收刀）",
        sheath: "手术刀：已收刀",
        idle: "等待手势",
      };
      return {
        step: 3,
        title: `手术第3步 · ${modeText[mode] || mode}`,
        tip: "ROI 已锁定。在长方体内立掌切割，捏合收刀留痕。",
        ok: true,
      };
    }
    const modeText = {
      rotate: "捏合拖动 → 旋转",
      palm_rotate: "张开拖动 → 轻旋转",
      zoom: "双手开合 → 缩放",
      point: "食指指向 → 悬停器官",
      select: "捏一下 → 选中器官",
      idle: "等待手势",
    };
    return {
      step: 0,
      title: `模式：${modeText[mode] || mode}`,
      tip: "食指悬停器官 → 捏一下选中特写 · 捏住拖动=旋转 · 开合=缩放 · 比耶=隔离 · 👍=重置",
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
  let lastKnifePulseAt = 0;
  let calibrateMode = false;
  let lastPalm = null;
  let prevPrimary = null;
  let prevHandGap = null;
  let prevKnifeCursor = null;
  let smoothCursor = { x: 0.5, y: 0.5 };
  let smoothKnifeCursor = { x: 0.5, y: 0.5 };
  let smoothDelta = { x: 0, y: 0 };
  let smoothZoomDelta = 0;
  let gestureHold = { name: "open", count: 0 };
  let surgeryMode = false;
  let surgeryPhase = "select";
  /** When true, screen-right hand is the scalpel (default). */
  let knifeOnRight = true;
  /** Pinch-tap select: short pinch without drag. */
  let pinchWasDown = false;
  let pinchTapPending = false;
  let pinchDownAt = 0;
  let pinchDownPalm = null;
  let pinchDragged = false;

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
      video: {
        facingMode: "user",
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
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
        prevKnifeCursor = null;
        const coach = buildCoach("idle", false, 0, calibrateMode, 0, 0, surgeryMode, surgeryPhase);
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
          surgeryMode,
          knifeActive: false,
          knifeCutting: false,
          knifeCursor: null,
          knifeScreenPts: null,
          knifeStrokeEnd: false,
          rotateDelta: { x: 0, y: 0 },
          zoomDelta: 0,
          landmarks: null,
          hands: [],
        });
        return;
      }

      const hands = allLandmarks.map((lm) => classifyHand(lm));
      // Sort by mirrored screen X: larger = more to the right of the user view.
      hands.sort((a, b) => mapX(b.palm.x) - mapX(a.palm.x));
      const rightHand = hands[0];
      const leftHand = hands[1] || null;

      let viewHand = rightHand;
      let knifeHand = null;
      if (surgeryMode) {
        if (hands.length >= 2) {
          knifeHand = knifeOnRight ? rightHand : leftHand;
          viewHand = knifeOnRight ? leftHand : rightHand;
        } else {
          // Single hand in surgery: treat as knife when cutting pose, else view.
          const only = rightHand;
          const knifePose = only.isPoint || (only.isPinch && only.extendedCount <= 2);
          if (knifePose) {
            knifeHand = only;
            viewHand = null;
          } else {
            viewHand = only;
            knifeHand = null;
          }
        }
      }

      const primary = viewHand || rightHand;
      const secondary = surgeryMode
        ? (hands.length >= 2 ? (knifeOnRight ? leftHand : rightHand) : null)
        : (hands[1] || null);
      lastPalm = (viewHand || knifeHand || rightHand).palm;

      let mode = "idle";
      let rotateDelta = { x: 0, y: 0 };
      let zoomDelta = 0;
      let activeGesture = primary?.gesture || "open";
      let knifeActive = false;
      let knifeCutting = false;
      let knifeStrokeEnd = false;
      let knifeCursorRaw = null;
      let knifeScreenPts = null;

      if (surgeryMode && knifeHand) {
        knifeActive = true;
        // 发誓立掌 = 刀面切割；捏合 = 收刀并结束本刀（比握拳更稳、更好识别）。
        const isSheath =
          Boolean(knifeHand.isPinch || knifeHand.gesture === "pinch")
          || (knifeHand.gesture === "select" && knifeHand.pinch < 0.06);
        const isCuttingPose = Boolean(
          (knifeHand.isOath || knifeHand.gesture === "oath") && !isSheath,
        );
        knifeCutting = isCuttingPose;
        if (isSheath && now - lastKnifePulseAt > 450) {
          lastKnifePulseAt = now;
          knifeStrokeEnd = true;
          knifeCutting = false;
          mode = "sheath";
          activeGesture = "sheath";
        }
        const mapBladePt = (p) => {
          let x = mapX(p.x);
          let y = p.y;
          x = Math.max(0, Math.min(1, x - centerOffset.x + 0.5));
          y = Math.max(0, Math.min(1, y - centerOffset.y + 0.5));
          return { x, y };
        };
        const blade = knifeHand.blade;
        knifeScreenPts = blade
          ? [mapBladePt(blade.a), mapBladePt(blade.b), mapBladePt(blade.c)]
          : null;
        knifeCursorRaw = mapBladePt(knifeHand.palm || knifeHand.cursor);
        smoothKnifeCursor = {
          x: lerp(smoothKnifeCursor.x, knifeCursorRaw.x, 0.4),
          y: lerp(smoothKnifeCursor.y, knifeCursorRaw.y, 0.4),
        };
        if (knifeCutting) {
          mode = "knife";
          activeGesture = "knife";
        } else if (!knifeStrokeEnd) {
          mode = "knife_idle";
          activeGesture = "knife_idle";
        }
      }

      // View / navigation hand (and two-hand zoom) — skip rotate from knife hand.
      if (!calibrateMode && viewHand) {
        if (hands.length >= 2 && !surgeryMode && secondary) {
          const gap = dist2(primary.palm, secondary.palm);
          if (prevHandGap != null) {
            const raw = (gap - prevHandGap) * 2.8;
            zoomDelta = Math.max(-0.12, Math.min(0.12, raw));
          }
          prevHandGap = gap;
          mode = "zoom";
          activeGesture = "two_hand_zoom";
          prevPrimary = { palm: viewHand.palm, cursor: viewHand.cursor };
        } else if (hands.length >= 2 && surgeryMode) {
          // In surgery, two-hand gap still zooms using both palms.
          const a = viewHand.palm;
          const b = knifeHand?.palm || a;
          const gap = dist2(a, b);
          if (prevHandGap != null && !knifeCutting) {
            const raw = (gap - prevHandGap) * 2.4;
            zoomDelta = Math.max(-0.12, Math.min(0.12, raw));
            if (Math.abs(zoomDelta) > 0.008) mode = "zoom";
          }
          prevHandGap = gap;
          const usePinchRotate = viewHand.isPinch || viewHand.gesture === "pinch";
          const usePalmRotate = viewHand.isOpenPalm && !viewHand.isPoint;
          if ((usePinchRotate || usePalmRotate) && prevPrimary && !knifeCutting) {
            const dx = mapX(viewHand.palm.x) - mapX(prevPrimary.palm.x);
            const dy = viewHand.palm.y - prevPrimary.palm.y;
            const gain = usePinchRotate ? 2.6 : 1.35;
            rotateDelta = {
              x: Math.max(-0.08, Math.min(0.08, dx * gain)),
              y: Math.max(-0.08, Math.min(0.08, dy * gain)),
            };
            if (Math.hypot(rotateDelta.x, rotateDelta.y) > 0.001) {
              mode = usePinchRotate ? "rotate" : "palm_rotate";
            }
          } else if (viewHand.isPoint || viewHand.gesture === "point") {
            if (!knifeCutting) mode = "point";
          }
          prevPrimary = { palm: viewHand.palm, cursor: viewHand.cursor, pinch: viewHand.pinch };
        } else {
          prevHandGap = null;
          const usePinchRotate = viewHand.isPinch || viewHand.gesture === "pinch";
          const usePalmRotate = viewHand.isOpenPalm && !viewHand.isPoint;
          if ((usePinchRotate || usePalmRotate) && prevPrimary) {
            const dx = mapX(viewHand.palm.x) - mapX(prevPrimary.palm.x);
            const dy = viewHand.palm.y - prevPrimary.palm.y;
            const gain = usePinchRotate ? 2.6 : 1.35;
            rotateDelta = {
              x: Math.max(-0.08, Math.min(0.08, dx * gain)),
              y: Math.max(-0.08, Math.min(0.08, dy * gain)),
            };
            mode = usePinchRotate ? "rotate" : "palm_rotate";
            if (
              usePinchRotate &&
              prevPrimary.pinch != null &&
              Math.hypot(dx, dy) < 0.01
            ) {
              const raw = (prevPrimary.pinch - viewHand.pinch) * 2.4;
              zoomDelta = Math.max(-0.1, Math.min(0.1, raw));
              if (Math.abs(zoomDelta) > 0.008) mode = "zoom";
            }
          } else if (viewHand.isPoint || viewHand.gesture === "point") {
            mode = "point";
          }
          prevPrimary = { palm: viewHand.palm, cursor: viewHand.cursor, pinch: viewHand.pinch };
        }
        if (mode === "zoom" && activeGesture === "two_hand_zoom") {
          // keep zoom gesture label
        } else {
          activeGesture = stabilizeGesture(viewHand.gesture);
        }
        if (surgeryMode && knifeCutting) {
          activeGesture = "knife";
          mode = "knife";
        } else if (surgeryMode && knifeActive && !knifeCutting && (mode === "idle" || mode === "knife_idle")) {
          activeGesture = "knife_idle";
          mode = "knife_idle";
        }
      } else if (!surgeryMode) {
        // Original non-surgery path
        if (hands.length >= 2 && secondary) {
          const gap = dist2(primary.palm, secondary.palm);
          if (prevHandGap != null) {
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
      }

      const cursorSource = surgeryMode && knifeHand ? knifeHand : (viewHand || primary);
      let cx = mapX(cursorSource.cursor.x);
      let cy = cursorSource.cursor.y;
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
        const palm = (viewHand || primary).palm;
        calmSamples.push({ x: palm.x, y: palm.y, t: now });
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

      const selectSource = viewHand || primary;
      let selectPulse = false;
      // Pinch-tap select: short 捏一下 without dragging → select organ under cursor.
      // Pinch+drag still rotates (existing rotate path).
      if (!calibrateMode && selectSource && !(surgeryMode && knifeCutting)) {
        const pinching = Boolean(selectSource.isPinch || selectSource.gesture === "pinch");
        const palm = selectSource.palm;
        if (pinching && !pinchWasDown) {
          pinchWasDown = true;
          pinchTapPending = true;
          pinchDragged = false;
          pinchDownAt = now;
          pinchDownPalm = { x: palm.x, y: palm.y };
        } else if (pinching && pinchTapPending && pinchDownPalm) {
          const moved = Math.hypot(palm.x - pinchDownPalm.x, palm.y - pinchDownPalm.y);
          if (moved > 0.028) {
            pinchDragged = true;
            pinchTapPending = false;
          }
          // Held still briefly counts as a deliberate tap-select.
          if (
            !pinchDragged &&
            now - pinchDownAt > 180 &&
            now - pinchDownAt < 520 &&
            moved < 0.018 &&
            now - lastSelectAt > 550
          ) {
            lastSelectAt = now;
            selectPulse = true;
            pinchTapPending = false;
          }
        } else if (!pinching && pinchWasDown) {
          if (
            pinchTapPending &&
            !pinchDragged &&
            now - pinchDownAt < 550 &&
            now - lastSelectAt > 550
          ) {
            lastSelectAt = now;
            selectPulse = true;
          }
          pinchWasDown = false;
          pinchTapPending = false;
          pinchDragged = false;
          pinchDownPalm = null;
        }
      } else if (!selectSource?.isPinch) {
        pinchWasDown = false;
        pinchTapPending = false;
        pinchDragged = false;
        pinchDownPalm = null;
      }

      if (selectPulse) {
        activeGesture = "select";
        mode = "select";
      }

      let peacePulse = false;
      if (
        !calibrateMode &&
        selectSource?.gesture === "peace" &&
        now - lastPeaceAt > 1000
      ) {
        lastPeaceAt = now;
        peacePulse = true;
      }
      let resetPulse = false;
      if (
        !calibrateMode &&
        selectSource?.gesture === "thumbs_up" &&
        now - lastResetAt > 1200
      ) {
        lastResetAt = now;
        resetPulse = true;
      }

      const progress = calibrateMode ? Math.min(1, calmSamples.length / 8) : calibrated ? 1 : 0;
      const coach = buildCoach(mode, true, hands.length, calibrateMode, progress, motionSpread, surgeryMode, surgeryPhase);

      onFrame({
        present: true,
        handCount: hands.length,
        video,
        mirrored,
        gesture: activeGesture,
        gestureText: GESTURE_TEXT[activeGesture] || activeGesture,
        mode,
        surgeryMode,
        knifeOnRight,
        knifeActive,
        knifeCutting,
        knifeStrokeEnd,
        knifeCursor: knifeActive ? { ...smoothKnifeCursor } : null,
        knifeScreenPts,
        rotateDelta: { ...smoothDelta },
        zoomDelta: smoothZoomDelta,
        openAmount: Math.max(0, Math.min(1, ((viewHand || primary).pinch - 0.03) / 0.18)),
        pinch: (viewHand || primary).pinch,
        extendedCount: (viewHand || primary).extendedCount,
        openSpan: (viewHand || primary).openSpan,
        cursor: { ...smoothCursor },
        rawCursor: (viewHand || primary).cursor,
        palm: (viewHand || primary).palm,
        calibrating: calibrateMode || now < calibratingUntil,
        calibrateMode,
        calibrateProgress: progress,
        calibrated,
        coach,
        selectPulse,
        peacePulse,
        resetPulse,
        landmarks: (viewHand || primary).landmarks,
        handsLandmarks: allLandmarks,
      });
      prevKnifeCursor = knifeCursorRaw;
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
    setSurgeryMode(enabled) {
      surgeryMode = Boolean(enabled);
      if (!surgeryMode) surgeryPhase = "select";
      prevKnifeCursor = null;
      onStatus(surgeryMode ? "已进入模拟手术：先选器官 → 长方体ROI → 切割" : "已恢复普通手势映射");
    },
    setSurgeryPhase(phase) {
      const next = String(phase || "select");
      surgeryPhase = ["select", "roi", "cut"].includes(next) ? next : "select";
    },
    isSurgeryMode: () => surgeryMode,
    setKnifeOnRight(value) {
      knifeOnRight = Boolean(value);
    },
    toggleKnifeHand() {
      knifeOnRight = !knifeOnRight;
      onStatus(knifeOnRight ? "手术刀：屏幕右侧手" : "手术刀：屏幕左侧手");
      return knifeOnRight;
    },
    isRunning: () => running,
    isCalibrateMode: () => calibrateMode,
    getVideo: () => video,
  };
}
