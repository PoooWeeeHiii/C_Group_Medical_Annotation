import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost } from "../api/client";
import { useToast } from "../components/Toast";
import type { CaseDetail, CaseItem, ImageItem, ModelItem } from "../types";
import { STATUS_TEXT } from "../types";

interface PredictResult {
  mask_id?: string;
  model_id?: string;
  version?: string;
  case_id?: string;
  image_id?: string;
  model_status?: string;
  backend?: string | null;
  organ_count?: number;
  organ_labels?: string[];
  fallback_reason?: string | null;
  message?: string;
}

export function InferencePage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [caseId, setCaseId] = useState("");
  const [imageId, setImageId] = useState("");
  const [images, setImages] = useState<ImageItem[]>([]);
  const [modelId, setModelId] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PredictResult | null>(null);
  const [sliceIndex, setSliceIndex] = useState(0);
  const [sliceCount, setSliceCount] = useState(1);

  const selectedModel = models.find((item) => item.model_id === modelId) || models[0] || null;

  const loadCasesAndModels = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      const items = data.items || [];
      setCases(items);
      setCaseId((prev) => prev || items[0]?.case_id || "");
    } catch {
      setCases([]);
    }
    try {
      const data = await apiGet<{ items: ModelItem[] }>("/api/models");
      const items = data.items || [];
      setModels(items);
      setModelId((prev) => prev || items[0]?.model_id || "");
    } catch {
      setModels([]);
    }
  }, []);

  useEffect(() => {
    void loadCasesAndModels();
  }, [loadCasesAndModels, refreshKey]);

  useEffect(() => {
    if (!caseId) {
      setImages([]);
      setImageId("");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await apiGet<CaseDetail & { case?: CaseItem; images?: ImageItem[] }>(
          `/api/case/${caseId}`,
        );
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
  }, [caseId]);

  useEffect(() => {
    if (!imageId) {
      setSliceCount(1);
      setSliceIndex(0);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const volume = await apiGet<{ slice_count?: number; width?: number; height?: number }>(
          `/api/image/${imageId}/volume`,
        );
        if (cancelled) return;
        const count = Math.max(Number(volume.slice_count || 1), 1);
        setSliceCount(count);
        setSliceIndex((prev) => Math.min(prev, count - 1));
      } catch {
        if (!cancelled) {
          const fallback = images.find((img) => img.image_id === imageId);
          const count = Math.max(Number(fallback?.slice_count || 1), 1);
          setSliceCount(count);
          setSliceIndex(0);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [imageId, images]);

  async function runPredict() {
    if (!caseId || !imageId || !selectedModel) {
      showToast("请先选择病例、图像和模型");
      return;
    }
    const isHeavy =
      String(selectedModel.label || "").toLowerCase().includes("spleen") ||
      String(selectedModel.model_id || "").toLowerCase().includes("spleen") ||
      String(selectedModel.model_id || "").toLowerCase().includes("totalseg") ||
      String(selectedModel.backend || "").toLowerCase().includes("totalsegmentator");
    if (isHeavy) {
      showToast("正在运行 AI 推理（TotalSeg / nnU-Net），CPU 可能需要数分钟，请耐心等待...");
    }
    setRunning(true);
    try {
      const data = await apiPost<PredictResult>(
        "/api/ai/predict",
        {
          case_id: caseId,
          image_id: imageId,
          model_id: selectedModel.model_id,
          label: selectedModel.label || "label",
          allow_baseline: false,
        },
        { timeoutMs: isHeavy ? 30 * 60 * 1000 : 120 * 1000 },
      );
      setResult({
        ...data,
        case_id: caseId,
        image_id: imageId,
      });
      const statusText = data.model_status || data.backend || "unknown";
      const hasAll = Array.isArray(data.organ_labels) && data.organ_labels.includes("全部标注");
      showToast(
        hasAll
          ? `AI 预测完成 [${statusText}]：已生成「全部标注」分色 · ${data.organ_count || 1} 个器官`
          : `AI 预测完成 [${statusText}]：${data.organ_count || 1} 个器官 · ${data.mask_id} · ${data.model_id}`,
      );
      if (data.fallback_reason) showToast(`注意：${data.fallback_reason}`);
      if (Array.isArray(data.organ_labels) && data.organ_labels.length > 1) {
        showToast(
          `已写入：${data.organ_labels.slice(0, 12).join(", ")}${data.organ_labels.length > 12 ? " ..." : ""}`,
        );
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : "AI 预测失败");
    } finally {
      setRunning(false);
    }
  }

  const previewImageId = result?.image_id || imageId;
  const previewMaskId = result?.mask_id || "";

  return (
    <>
      <section className="panel">
        <h2>AI 推理中心</h2>
        <p className="panel-lead">
          选择病例与模型后运行 predict，结果写入 <code>v2_ai</code>，可在此预览并跳转标注台修正。
        </p>
        <div className="toolbar-row inference-toolbar">
          <label className="field">
            <span>病例</span>
            <select value={caseId} onChange={(e) => setCaseId(e.target.value)}>
              <option value="">选择病例</option>
              {cases.map((item) => (
                <option key={item.case_id} value={item.case_id}>
                  {item.case_id} · {STATUS_TEXT[item.status || ""] || item.status}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>图像</span>
            <select value={imageId} onChange={(e) => setImageId(e.target.value)}>
              <option value="">选择图像</option>
              {images.map((img) => (
                <option key={img.image_id} value={img.image_id}>
                  {img.image_id}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>模型</span>
            <select value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">选择模型</option>
              {models.map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.display_name || model.name || model.model_id}
                  {model.external_ready ? " · 外部权重就绪" : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button"
            type="button"
            disabled={!caseId || !imageId || !selectedModel || running}
            onClick={() => void runPredict()}
          >
            {running ? "预测中…" : "开始推理"}
          </button>
          <button
            className="ghost-button"
            type="button"
            disabled={!caseId}
            onClick={() => navigate(caseId ? `/annotation/${caseId}` : "/annotation")}
          >
            打开标注台
          </button>
        </div>
        <div className="case-meta" style={{ marginTop: 14 }}>
          <div className="meta-line">
            <span>model_id</span>
            <strong>{selectedModel?.model_id || "-"}</strong>
          </div>
          <div className="meta-line">
            <span>label</span>
            <strong>{selectedModel?.label || "-"}</strong>
          </div>
          <div className="meta-line">
            <span>backend</span>
            <strong>{selectedModel?.backend || "-"}</strong>
          </div>
          <div className="meta-line">
            <span>说明</span>
            <strong>{selectedModel?.description || "-"}</strong>
          </div>
        </div>
      </section>

      <div className="grid cols-3" style={{ marginTop: 18 }}>
        <section className="viewer">
          <h2>原始图像</h2>
          <div className="ct-frame inference-frame">
            {previewImageId ? (
              <img
                className="ct-slice-image"
                src={`/api/image/${previewImageId}/slice/axial/${sliceIndex}.png?window=auto`}
                alt="原始切片"
              />
            ) : (
              <div className="slice-empty">选择病例后显示</div>
            )}
          </div>
        </section>
        <section className="viewer">
          <h2>AI Mask (v2_ai)</h2>
          <div className="ct-frame inference-frame">
            {previewMaskId ? (
              <img
                className="ct-slice-image"
                src={`/api/mask/${previewMaskId}/slice/axial/${sliceIndex}`}
                alt="AI mask"
              />
            ) : (
              <div className="slice-empty">推理后显示 v2_ai</div>
            )}
          </div>
        </section>
        <section className="viewer">
          <h2>状态</h2>
          <div className="case-meta" style={{ marginTop: 12 }}>
            <div className="meta-line">
              <span>切片</span>
              <strong>
                {sliceIndex + 1} / {sliceCount}
              </strong>
            </div>
            <div className="meta-line">
              <span>结果</span>
              <strong>{result ? "已完成" : running ? "运行中" : "待推理"}</strong>
            </div>
            <div className="meta-line">
              <span>Mask</span>
              <strong>{result?.mask_id || "-"}</strong>
            </div>
            <div className="meta-line">
              <span>版本</span>
              <strong>{result?.version || "-"}</strong>
            </div>
          </div>
        </section>
      </div>

      <div className="slider-row" style={{ marginTop: 14 }}>
        <span>轴向切片</span>
        <input
          type="range"
          min={0}
          max={Math.max(sliceCount - 1, 0)}
          value={sliceIndex}
          onChange={(e) => setSliceIndex(Number(e.target.value))}
          disabled={!previewImageId}
        />
        <span>
          {sliceIndex + 1}/{sliceCount}
        </span>
      </div>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>最近推理结果</h2>
        {result ? (
          <div className="case-meta">
            <div className="meta-line">
              <span>病例</span>
              <strong>{result.case_id}</strong>
            </div>
            <div className="meta-line">
              <span>图像</span>
              <strong>{result.image_id}</strong>
            </div>
            <div className="meta-line">
              <span>Mask</span>
              <strong>{result.mask_id}</strong>
            </div>
            <div className="meta-line">
              <span>模型</span>
              <strong>{result.model_id}</strong>
            </div>
            <div className="meta-line">
              <span>版本</span>
              <strong>{result.version}</strong>
            </div>
            <div className="meta-line">
              <span>状态</span>
              <strong>{result.model_status || result.backend || "-"}</strong>
            </div>
          </div>
        ) : (
          <div className="placeholder compact">
            尚未推理。未配置真实模型权重时预测会失败（不再静默使用 HU baseline）；可配置 TotalSeg / nnUNet /
            平台 U-Net。
          </div>
        )}
      </section>
    </>
  );
}
