import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api/client";
import { useRole } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import type { CaseDetail, CaseItem, ImageItem, LabelItem, VolumeMeta } from "../types";
import { STATUS_TEXT } from "../types";

type Axis = "axial" | "coronal" | "sagittal";
type Tool = "brush" | "erase";

interface SliceData {
  width: number;
  height: number;
  values: Float32Array;
  valueMin: number;
  valueMax: number;
}

function encodeMaskRle(data: Uint8Array): Array<[number, number]> {
  if (!data.length) return [];
  const runs: Array<[number, number]> = [];
  let value = data[0];
  let count = 1;
  for (let index = 1; index < data.length; index += 1) {
    const next = data[index];
    if (next === value) count += 1;
    else {
      runs.push([value, count]);
      value = next;
      count = 1;
    }
  }
  runs.push([value, count]);
  return runs;
}

function decodeFloat32Base64(base64: string): Float32Array {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Float32Array(bytes.buffer);
}

function axisSliceCount(meta: VolumeMeta | ImageItem | null | undefined, axis: Axis) {
  if (!meta) return 1;
  if (axis === "coronal") return Math.max(Number(meta.height || 1), 1);
  if (axis === "sagittal") return Math.max(Number((meta as VolumeMeta).width || (meta as ImageItem).width || 1), 1);
  return Math.max(Number(meta.slice_count || 1), 1);
}

function hexToRgb(hex: string): [number, number, number] {
  const raw = hex.replace("#", "");
  const full = raw.length === 3 ? raw.split("").map((c) => c + c).join("") : raw;
  const value = Number.parseInt(full || "00e5b0", 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function AnnotationPage({ refreshKey }: { refreshKey: number }) {
  const { caseId: routeCaseId } = useParams<{ caseId?: string }>();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { canAnnotate } = useRole();

  const [cases, setCases] = useState<CaseItem[]>([]);
  const [caseId, setCaseId] = useState(routeCaseId || "");
  const [images, setImages] = useState<ImageItem[]>([]);
  const [imageId, setImageId] = useState("");
  const [volume, setVolume] = useState<VolumeMeta | null>(null);
  const [labels, setLabels] = useState<LabelItem[]>([]);
  const [labelId, setLabelId] = useState(1);
  const [axis, setAxis] = useState<Axis>("axial");
  const [sliceIndex, setSliceIndex] = useState(0);
  const [tool, setTool] = useState<Tool>("brush");
  const [brushSize, setBrushSize] = useState(4);
  const [saving, setSaving] = useState(false);
  const [sliceLoading, setSliceLoading] = useState(false);

  const imageCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskDataRef = useRef<Uint8Array | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const sliceCacheRef = useRef<Map<string, SliceData>>(new Map());
  const maskStoreRef = useRef<Map<string, Uint8Array>>(new Map());

  const selectedLabel = useMemo(
    () => labels.find((item) => item.label_id === labelId) || labels.find((item) => item.label_id > 0) || null,
    [labels, labelId],
  );

  const sliceCount = axisSliceCount(volume || images.find((img) => img.image_id === imageId), axis);
  const maxSlice = Math.max(sliceCount - 1, 0);

  const maskStoreKey = useCallback(
    (imgId: string, ax: Axis, index: number) => `${imgId}:${ax}:${index}`,
    [],
  );

  const loadCases = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      const items = data.items || [];
      setCases(items);
      setCaseId((prev) => prev || routeCaseId || items[0]?.case_id || "");
    } catch {
      setCases([]);
    }
  }, [routeCaseId]);

  const loadLabels = useCallback(async () => {
    try {
      const data = await apiGet<{ items: LabelItem[] }>(
        "/api/labels?include_background=true&enabled_only=true",
      );
      const items = (data.items || []).filter((item) => item.enabled !== false);
      setLabels(items);
      const first = items.find((item) => item.label_id > 0);
      if (first) setLabelId((prev) => (items.some((item) => item.label_id === prev) ? prev : first.label_id));
    } catch {
      setLabels([]);
    }
  }, []);

  useEffect(() => {
    void loadCases();
    void loadLabels();
  }, [loadCases, loadLabels, refreshKey]);

  useEffect(() => {
    if (routeCaseId) setCaseId(routeCaseId);
  }, [routeCaseId]);

  useEffect(() => {
    if (!caseId) {
      setImages([]);
      setImageId("");
      setVolume(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await apiGet<CaseDetail & { images?: ImageItem[] }>(`/api/case/${caseId}`);
        if (cancelled) return;
        const nextImages = detail.images || [];
        setImages(nextImages);
        setImageId((prev) =>
          nextImages.some((img) => img.image_id === prev) ? prev : nextImages[0]?.image_id || "",
        );
      } catch {
        if (!cancelled) {
          setImages([]);
          setImageId("");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [caseId, refreshKey]);

  useEffect(() => {
    if (!imageId) {
      setVolume(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const meta = await apiGet<VolumeMeta>(`/api/image/${imageId}/volume`);
        if (!cancelled) setVolume(meta);
      } catch {
        if (!cancelled) {
          const image = images.find((img) => img.image_id === imageId);
          setVolume(
            image
              ? {
                  width: image.width,
                  height: image.height,
                  slice_count: image.slice_count || 1,
                }
              : null,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [imageId, images]);

  useEffect(() => {
    setSliceIndex((prev) => Math.min(prev, maxSlice));
  }, [maxSlice, axis]);

  const paintMaskCircle = useCallback(
    (point: { x: number; y: number }, radius: number, value: number) => {
      const mask = maskDataRef.current;
      const canvas = maskCanvasRef.current;
      if (!mask || !canvas) return;
      const { width, height } = canvas;
      const r2 = radius * radius;
      const minX = Math.max(0, Math.floor(point.x - radius));
      const maxX = Math.min(width - 1, Math.ceil(point.x + radius));
      const minY = Math.max(0, Math.floor(point.y - radius));
      const maxY = Math.min(height - 1, Math.ceil(point.y + radius));
      for (let y = minY; y <= maxY; y += 1) {
        for (let x = minX; x <= maxX; x += 1) {
          const dx = x - point.x;
          const dy = y - point.y;
          if (dx * dx + dy * dy <= r2) mask[y * width + x] = value;
        }
      }
    },
    [],
  );

  const renderMaskOverlay = useCallback(() => {
    const canvas = maskCanvasRef.current;
    const mask = maskDataRef.current;
    if (!canvas || !mask) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width, height } = canvas;
    const imageData = ctx.createImageData(width, height);
    const colorById = new Map(
      labels.map((item) => [item.label_id, hexToRgb(item.color || "#00e5b0")] as const),
    );
    const fallback = hexToRgb(selectedLabel?.color || "#00e5b0");
    for (let i = 0; i < mask.length; i += 1) {
      const id = mask[i];
      if (id > 0) {
        const [r, g, b] = colorById.get(id) || fallback;
        const offset = i * 4;
        imageData.data[offset] = r;
        imageData.data[offset + 1] = g;
        imageData.data[offset + 2] = b;
        imageData.data[offset + 3] = 150;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }, [labels, selectedLabel?.color]);

  const renderGrayscale = useCallback((slice: SliceData) => {
    const canvas = imageCanvasRef.current;
    if (!canvas) return;
    canvas.width = slice.width;
    canvas.height = slice.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const imageData = ctx.createImageData(slice.width, slice.height);
    const min = Number(slice.valueMin);
    const max = Number(slice.valueMax);
    const span = Math.max(max - min, 1e-6);
    for (let i = 0; i < slice.values.length; i += 1) {
      const gray = Math.max(0, Math.min(255, Math.round(((slice.values[i] - min) / span) * 255)));
      const offset = i * 4;
      imageData.data[offset] = gray;
      imageData.data[offset + 1] = gray;
      imageData.data[offset + 2] = gray;
      imageData.data[offset + 3] = 255;
    }
    ctx.putImageData(imageData, 0, 0);
  }, []);

  const ensureMaskBuffer = useCallback(
    (width: number, height: number) => {
      if (!imageId) return;
      const key = maskStoreKey(imageId, axis, sliceIndex);
      let data = maskStoreRef.current.get(key);
      if (!data || data.length !== width * height) {
        data = new Uint8Array(width * height);
        maskStoreRef.current.set(key, data);
      }
      maskDataRef.current = data;
      const maskCanvas = maskCanvasRef.current;
      if (maskCanvas) {
        maskCanvas.width = width;
        maskCanvas.height = height;
      }
      renderMaskOverlay();
    },
    [axis, imageId, maskStoreKey, renderMaskOverlay, sliceIndex],
  );

  useEffect(() => {
    if (!imageId) return;
    let cancelled = false;
    const cacheKey = `${imageId}:${axis}:${sliceIndex}`;
    (async () => {
      setSliceLoading(true);
      try {
        let slice = sliceCacheRef.current.get(cacheKey);
        if (!slice) {
          const data = await apiGet<{
            width: number;
            height: number;
            values_base64: string;
            value_min: number;
            value_max: number;
          }>(`/api/image/${imageId}/slice/${axis}/${sliceIndex}/values`);
          slice = {
            width: data.width,
            height: data.height,
            values: decodeFloat32Base64(data.values_base64),
            valueMin: data.value_min,
            valueMax: data.value_max,
          };
          sliceCacheRef.current.set(cacheKey, slice);
        }
        if (cancelled) return;
        renderGrayscale(slice);
        ensureMaskBuffer(slice.width, slice.height);
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : "切片加载失败");
        }
      } finally {
        if (!cancelled) setSliceLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [axis, ensureMaskBuffer, imageId, renderGrayscale, showToast, sliceIndex]);

  function canvasPoint(event: ReactPointerEvent<HTMLCanvasElement>) {
    const canvas = maskCanvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / Math.max(rect.width, 1);
    const scaleY = canvas.height / Math.max(rect.height, 1);
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  function paintLine(from: { x: number; y: number }, to: { x: number; y: number }) {
    const radius = tool === "erase" ? Math.max(brushSize, 8) : brushSize;
    const value = tool === "erase" ? 0 : selectedLabel?.label_id || labelId || 1;
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius * 0.6)));
    for (let step = 0; step <= steps; step += 1) {
      const ratio = step / steps;
      paintMaskCircle(
        {
          x: from.x + (to.x - from.x) * ratio,
          y: from.y + (to.y - from.y) * ratio,
        },
        radius,
        value,
      );
    }
    if (imageId) {
      maskStoreRef.current.set(maskStoreKey(imageId, axis, sliceIndex), maskDataRef.current!);
    }
    renderMaskOverlay();
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!canAnnotate) {
      showToast("当前角色不可标注");
      return;
    }
    const point = canvasPoint(event);
    if (!point) return;
    drawingRef.current = true;
    lastPointRef.current = point;
    paintLine(point, point);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return;
    const point = canvasPoint(event);
    if (!point || !lastPointRef.current) return;
    paintLine(lastPointRef.current, point);
    lastPointRef.current = point;
  }

  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    drawingRef.current = false;
    lastPointRef.current = null;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // ignore
    }
  }

  async function saveCurrentMask() {
    if (!caseId || !imageId) {
      showToast("请先选择病例和图像");
      return;
    }
    const mask = maskDataRef.current;
    const canvas = maskCanvasRef.current;
    if (!mask || !canvas || !canvas.width || !canvas.height) {
      showToast("当前切片画布尚未加载，无法保存 Mask");
      return;
    }
    let hasPixels = false;
    for (let i = 0; i < mask.length; i += 1) {
      if (mask[i] > 0) {
        hasPixels = true;
        break;
      }
    }
    if (!hasPixels) {
      showToast("当前切片没有标注内容，请先画 Mask");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        case_id: caseId,
        image_id: imageId,
        version: "v1_manual",
        label: selectedLabel?.name || "label",
        label_id: selectedLabel?.label_id || labelId,
        label_type: "dense",
        mask_format: "json",
        axis,
        slice_index: sliceIndex,
        width: canvas.width,
        height: canvas.height,
        encoding: "rle",
        mask: encodeMaskRle(mask),
        points: [],
      };
      const data = await apiPost<{
        mask_id: string;
        updated?: boolean;
        mask?: { annotation_id?: string };
      }>("/api/save_mask", payload);
      await apiPost("/api/version", {
        case_id: caseId,
        version: "v1_manual",
        annotation: data.mask?.annotation_id || null,
        model: null,
        dataset: null,
      });
      showToast(
        `已保存 Mask ${data.mask_id}${data.updated ? "（覆盖）" : "（新建）"} · ${axis} 第 ${sliceIndex + 1} 层`,
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Mask 保存失败");
    } finally {
      setSaving(false);
    }
  }

  function clearCurrentMask() {
    const canvas = maskCanvasRef.current;
    if (!canvas || !maskDataRef.current) return;
    maskDataRef.current.fill(0);
    if (imageId) maskStoreRef.current.set(maskStoreKey(imageId, axis, sliceIndex), maskDataRef.current);
    renderMaskOverlay();
  }

  return (
    <div className="grid cols-annotation" style={{ display: "grid", gridTemplateColumns: "260px 1fr 280px", gap: 16 }}>
      <aside className="case-sidebar">
        <h2>病例 / 图像</h2>
        <label className="field" style={{ display: "block", marginTop: 12 }}>
          <span>病例</span>
          <select
            value={caseId}
            onChange={(e) => {
              const next = e.target.value;
              setCaseId(next);
              if (next) navigate(`/annotation/${next}`);
              else navigate("/annotation");
            }}
          >
            <option value="">选择病例</option>
            {cases.map((item) => (
              <option key={item.case_id} value={item.case_id}>
                {item.case_id} · {STATUS_TEXT[item.status || ""] || item.status}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ display: "block", marginTop: 12 }}>
          <span>图像</span>
          <select value={imageId} onChange={(e) => setImageId(e.target.value)}>
            <option value="">选择图像</option>
            {images.map((img) => (
              <option key={img.image_id} value={img.image_id}>
                {img.filename || img.image_id}
              </option>
            ))}
          </select>
        </label>
        <div className="case-meta" style={{ marginTop: 16 }}>
          <div className="meta-line">
            <span>状态</span>
            <strong>
              {STATUS_TEXT[cases.find((item) => item.case_id === caseId)?.status || ""] ||
                cases.find((item) => item.case_id === caseId)?.status ||
                "-"}
            </strong>
          </div>
          <div className="meta-line">
            <span>切片</span>
            <strong>
              {sliceIndex + 1} / {sliceCount}
            </strong>
          </div>
          <div className="meta-line">
            <span>平面</span>
            <strong>{axis}</strong>
          </div>
        </div>
      </aside>

      <section className="viewer">
        <div className="viewer-toolbar">
          <div>
            <strong>2D 标注视图</strong>
            {sliceLoading ? <span className="muted"> · 加载切片中…</span> : null}
          </div>
          <div className="viewer-mode-switch">
            {(["axial", "coronal", "sagittal"] as Axis[]).map((item) => (
              <button
                key={item}
                type="button"
                className={`ghost-button ${axis === item ? "active" : ""}`}
                onClick={() => setAxis(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        <div className="ct-frame real-image-frame" style={{ minHeight: 520 }}>
          {imageId ? (
            <>
              <canvas
                ref={imageCanvasRef}
                className="ct-slice-image"
                style={{ objectFit: "contain", width: "100%", height: "100%", pointerEvents: "none" }}
              />
              <canvas
                ref={maskCanvasRef}
                className="annotation-canvas"
                style={{ inset: 0, width: "100%", height: "100%", objectFit: "contain" }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                onPointerLeave={onPointerUp}
              />
              <div className="coordinate">
                {axis}: {sliceIndex + 1} / {sliceCount}
              </div>
            </>
          ) : (
            <div className="slice-empty">请选择病例与图像</div>
          )}
        </div>
        <div className="slider-row">
          <span>切片</span>
          <input
            type="range"
            min={0}
            max={maxSlice}
            value={Math.min(sliceIndex, maxSlice)}
            onChange={(e) => setSliceIndex(Number(e.target.value))}
            disabled={!imageId}
          />
          <span>
            {sliceIndex + 1}/{sliceCount}
          </span>
        </div>
      </section>

      <aside className="tool-panel">
        <h2>标注工具</h2>
        <div className="toolbar-row" style={{ marginTop: 12 }}>
          <button
            type="button"
            className={`tool-button ${tool === "brush" ? "active" : ""}`}
            onClick={() => setTool("brush")}
          >
            画笔
          </button>
          <button
            type="button"
            className={`tool-button ${tool === "erase" ? "active" : ""}`}
            onClick={() => setTool("erase")}
          >
            橡皮
          </button>
        </div>
        <div className="label-picker" style={{ marginTop: 14 }}>
          <div className="label-picker-header">
            <span>标注类别</span>
            <strong>
              {selectedLabel?.name || "-"} #{selectedLabel?.label_id ?? labelId}
            </strong>
          </div>
          <div className="label-picker-grid">
            {labels
              .filter((item) => item.label_id > 0 && item.enabled !== false)
              .map((item) => (
                <button
                  key={item.label_id}
                  type="button"
                  className={`label-row label-pick ${labelId === item.label_id ? "active" : ""}`}
                  onClick={() => setLabelId(item.label_id)}
                >
                  <span className="swatch" style={{ background: item.color }} />
                  {item.label_id} {item.display_name || item.name}
                </button>
              ))}
          </div>
        </div>
        <label className="field" style={{ display: "block", marginTop: 12 }}>
          <span>笔刷半径 {brushSize}</span>
          <input
            type="range"
            min={1}
            max={24}
            value={brushSize}
            onChange={(e) => setBrushSize(Number(e.target.value))}
          />
        </label>
        <div className="annotation-state-line" style={{ marginTop: 12 }}>
          <span>
            当前工具：<strong>{tool === "brush" ? "画笔" : "橡皮"}</strong>
          </span>
          <span>
            当前 label：
            <strong>
              {selectedLabel?.name || "-"} #{selectedLabel?.label_id ?? labelId}
            </strong>
          </span>
        </div>
        <div className="toolbar-row" style={{ marginTop: 18 }}>
          <button
            className="primary-button"
            type="button"
            disabled={!canAnnotate || !imageId || saving}
            onClick={() => void saveCurrentMask()}
          >
            {saving ? "保存中…" : "保存 Mask"}
          </button>
          <button className="ghost-button" type="button" onClick={clearCurrentMask} disabled={!imageId}>
            清空本层
          </button>
        </div>
        <p className="panel-lead" style={{ marginTop: 16 }}>
          切片来自 <code>/api/image/{"{id}"}/slice/{"{axis}"}/{"{index}"}/values</code>；保存走{" "}
          <code>/api/save_mask</code>（RLE JSON）并写入版本 <code>v1_manual</code>。
        </p>
      </aside>
    </div>
  );
}
