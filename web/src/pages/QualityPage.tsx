import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { useToast } from "../components/Toast";
import type {
  CaseDetail,
  CaseItem,
  ImageItem,
  MaskItem,
  MaskMetricsReport,
  QualityReportGenerateResult,
  ReportPolishResult,
  ReportPolishStatus,
} from "../types";
import { STATUS_TEXT } from "../types";

function isNiftiMask(mask: MaskItem) {
  return mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz");
}

function formatSliceRange(
  range?:
    | number[]
    | string
    | { start?: number | null; end?: number | null; count?: number | null }
    | null,
) {
  if (range == null) return "-";
  if (Array.isArray(range)) return range.join(" - ");
  if (typeof range === "object") {
    if (range.start == null && range.end == null) return "-";
    const base = `${range.start ?? "-"} – ${range.end ?? "-"}`;
    return range.count != null ? `${base}（${range.count} 层）` : base;
  }
  return String(range);
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function QualityPage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [caseId, setCaseId] = useState("");
  const [masks, setMasks] = useState<MaskItem[]>([]);
  const [maskId, setMaskId] = useState("");
  const [refMaskId, setRefMaskId] = useState("");
  const [report, setReport] = useState<MaskMetricsReport | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [reportTitle, setReportTitle] = useState("");
  const [tone, setTone] = useState<"clinical" | "concise" | "detailed">("clinical");
  const [polishStatus, setPolishStatus] = useState<ReportPolishStatus | null>(null);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [polishing, setPolishing] = useState(false);

  const loadCases = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      const items = data.items || [];
      setCases(items);
      setCaseId((prev) => prev || items[0]?.case_id || "");
    } catch {
      setCases([]);
    }
  }, []);

  const loadMasks = useCallback(async (id: string) => {
    if (!id) {
      setMasks([]);
      setMaskId("");
      setRefMaskId("");
      return;
    }
    try {
      const detail = await apiGet<CaseDetail & { images?: ImageItem[] }>(`/api/case/${id}`);
      const images = detail.images || [];
      const collected: MaskItem[] = [];
      for (const image of images) {
        try {
          const maskData = await apiGet<{ items?: MaskItem[]; masks?: MaskItem[] }>(
            `/api/image/${image.image_id}/masks`,
          );
          collected.push(...(maskData.items || maskData.masks || []));
        } catch {
          // ignore
        }
      }
      const nifti = collected
        .filter(isNiftiMask)
        .sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")));
      setMasks(nifti);
      setMaskId((prev) => (nifti.some((m) => m.mask_id === prev) ? prev : nifti[0]?.mask_id || ""));
      setRefMaskId((prev) => (nifti.some((m) => m.mask_id === prev) ? prev : ""));
    } catch {
      setMasks([]);
      setMaskId("");
      setRefMaskId("");
    }
  }, []);

  const loadPolishStatus = useCallback(async () => {
    try {
      const data = await apiGet<ReportPolishStatus>("/api/quality/report/polish/status");
      setPolishStatus(data);
    } catch {
      setPolishStatus({
        success: false,
        configured: false,
        message: "无法读取润色服务状态",
      });
    }
  }, []);

  useEffect(() => {
    void loadCases();
    void loadPolishStatus();
  }, [loadCases, loadPolishStatus, refreshKey]);

  useEffect(() => {
    void loadMasks(caseId);
    setReport(null);
    setMarkdown("");
    setReportTitle("");
  }, [caseId, loadMasks, refreshKey]);

  async function loadMetrics() {
    if (!maskId) {
      showToast("请先选择要评价的 Mask 版本");
      return;
    }
    setLoadingMetrics(true);
    try {
      const query = refMaskId ? `?ref=${encodeURIComponent(refMaskId)}` : "";
      const data = await apiGet<MaskMetricsReport>(`/api/mask/${maskId}/metrics${query}`);
      setReport(data);
      showToast("质量指标已加载");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "质量指标加载失败");
    } finally {
      setLoadingMetrics(false);
    }
  }

  async function generateReport() {
    if (!maskId) {
      showToast("请先选择要评价的 Mask 版本");
      return;
    }
    setGenerating(true);
    try {
      const data = await apiPost<QualityReportGenerateResult>("/api/quality/report/generate", {
        mask_id: maskId,
        ref_mask_id: refMaskId || null,
        case_id: caseId || null,
        include_error_slices: true,
      });
      setReport(data.metrics || null);
      setMarkdown(data.markdown || "");
      setReportTitle(data.title || "");
      showToast("质量报告已生成");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "质量报告生成失败");
    } finally {
      setGenerating(false);
    }
  }

  async function polishReport() {
    if (!markdown.trim()) {
      showToast("请先生成或填写报告草稿");
      return;
    }
    setPolishing(true);
    try {
      const data = await apiPost<ReportPolishResult>("/api/quality/report/polish", {
        draft_markdown: markdown,
        tone,
        case_id: caseId || null,
        mask_id: maskId || null,
        metrics: report || null,
      });
      if (data.markdown) setMarkdown(data.markdown);
      if (data.polished) {
        showToast(data.message || "AI 润色完成");
      } else {
        showToast(data.message || "未启用 AI 润色，已保留原文");
      }
      void loadPolishStatus();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "AI 润色失败");
    } finally {
      setPolishing(false);
    }
  }

  async function copyMarkdown() {
    if (!markdown.trim()) {
      showToast("报告内容为空");
      return;
    }
    try {
      await navigator.clipboard.writeText(markdown);
      showToast("报告已复制到剪贴板");
    } catch {
      showToast("复制失败，请手动选择文本");
    }
  }

  function downloadMarkdown() {
    if (!markdown.trim()) {
      showToast("报告内容为空");
      return;
    }
    const safeId = (maskId || caseId || "report").replace(/[^\w.-]+/g, "_");
    downloadText(`quality_report_${safeId}.md`, markdown);
    showToast("已下载 Markdown 报告");
  }

  const geometric = report?.geometric;
  const overlap = report?.overlap;
  const errorSlices = report?.error_slices || [];
  const busy = loadingMetrics || generating || polishing;

  return (
    <>
      <section className="panel">
        <h2>质量报告</h2>
        <p className="panel-lead">
          先拉取指标或直接生成 Markdown 报告；可选接入 OpenAI 兼容接口做 AI 润色（需配置{" "}
          <code>REPORT_POLISH_API_KEY</code>）。
        </p>
        <div className="toolbar-row" style={{ marginTop: 12 }}>
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
            <span>评价 Mask</span>
            <select value={maskId} onChange={(e) => setMaskId(e.target.value)}>
              <option value="">选择 Mask</option>
              {masks.map((mask) => (
                <option key={mask.mask_id} value={mask.mask_id}>
                  {mask.version} · {mask.mask_id} · {mask.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>参考 GT</span>
            <select value={refMaskId} onChange={(e) => setRefMaskId(e.target.value)}>
              <option value="">无 GT（仅几何质量）</option>
              {masks
                .filter((mask) => mask.mask_id !== maskId)
                .map((mask) => (
                  <option key={mask.mask_id} value={mask.mask_id}>
                    {mask.version} · {mask.mask_id}
                  </option>
                ))}
            </select>
          </label>
          <button
            className="ghost-button"
            type="button"
            disabled={!masks.length || busy}
            onClick={() => void loadMetrics()}
          >
            {loadingMetrics ? "加载中…" : "拉取指标"}
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={!masks.length || busy}
            onClick={() => void generateReport()}
          >
            {generating ? "生成中…" : "生成质量报告"}
          </button>
        </div>
      </section>

      <div className="grid cols-4" style={{ marginTop: 18 }}>
        <article className="metric-card">
          <div className="metric-label">Dice</div>
          <div className="metric-value">{overlap ? Number(overlap.dice).toFixed(4) : "-"}</div>
          <div className="metric-note">{overlap ? "相对 GT" : "需选择 ref"}</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">IoU</div>
          <div className="metric-value">{overlap ? Number(overlap.iou).toFixed(4) : "-"}</div>
          <div className="metric-note">重叠</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">HD95 mm</div>
          <div className="metric-value">
            {overlap?.hd95_mm != null ? Number(overlap.hd95_mm).toFixed(3) : "-"}
          </div>
          <div className="metric-note">有 GT</div>
        </article>
        <article className="metric-card">
          <div className="metric-label">体积 ml</div>
          <div className="metric-value">
            {geometric?.volume_ml != null ? Number(geometric.volume_ml).toFixed(3) : "-"}
          </div>
          <div className="metric-note">几何质量</div>
        </article>
      </div>

      <div className="grid cols-2" style={{ marginTop: 18 }}>
        <section className="panel">
          <h2>几何质量（无 GT 也可用）</h2>
          {geometric ? (
            <div className="case-meta">
              <div className="meta-line">
                <span>体素数</span>
                <strong>{geometric.voxel_count ?? "-"}</strong>
              </div>
              <div className="meta-line">
                <span>体积 ml</span>
                <strong>
                  {geometric.volume_ml != null ? Number(geometric.volume_ml).toFixed(3) : "-"}
                </strong>
              </div>
              <div className="meta-line">
                <span>连通域</span>
                <strong>{geometric.connected_component_count ?? "-"}</strong>
              </div>
              <div className="meta-line">
                <span>最大连通域占比</span>
                <strong>
                  {geometric.largest_component_ratio != null
                    ? `${(Number(geometric.largest_component_ratio) * 100).toFixed(1)}%`
                    : "-"}
                </strong>
              </div>
              <div className="meta-line">
                <span>切片范围</span>
                <strong>{formatSliceRange(geometric.slice_range)}</strong>
              </div>
            </div>
          ) : (
            <div className="placeholder compact">选择 Mask 后点击「拉取指标」或「生成质量报告」。</div>
          )}
        </section>
        <section className="panel">
          <h2>重叠指标（有 GT）</h2>
          {overlap ? (
            <div className="case-meta">
              <div className="meta-line">
                <span>Precision</span>
                <strong>{Number(overlap.precision).toFixed(4)}</strong>
              </div>
              <div className="meta-line">
                <span>Recall</span>
                <strong>{Number(overlap.recall).toFixed(4)}</strong>
              </div>
              <div className="meta-line">
                <span>体积差 ml</span>
                <strong>
                  {overlap.volume_diff_ml != null ? Number(overlap.volume_diff_ml).toFixed(3) : "-"}
                </strong>
              </div>
              <div className="meta-line">
                <span>Pred / Ref</span>
                <strong>
                  {report?.mask_id} / {report?.ref_mask_id || "-"}
                </strong>
              </div>
            </div>
          ) : (
            <div className="placeholder compact">未选择参考 GT 时仅显示几何质量。</div>
          )}
        </section>
      </div>

      <section className="panel" style={{ marginTop: 18 }}>
        <div className="toolbar-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ margin: 0 }}>{reportTitle || "报告正文（Markdown）"}</h2>
            <p className="panel-lead" style={{ marginTop: 6 }}>
              {polishStatus?.configured
                ? `AI 润色已配置 · 模型 ${polishStatus.model || "-"}`
                : polishStatus?.message || "未配置 AI 润色密钥时仍可生成本地报告"}
            </p>
          </div>
          <div className="toolbar-row" style={{ margin: 0 }}>
            <label className="field" style={{ minWidth: 120 }}>
              <span>润色风格</span>
              <select
                value={tone}
                onChange={(e) => setTone(e.target.value as "clinical" | "concise" | "detailed")}
              >
                <option value="clinical">临床专业</option>
                <option value="concise">简洁</option>
                <option value="detailed">详细解读</option>
              </select>
            </label>
            <button className="ghost-button" type="button" disabled={!markdown || busy} onClick={() => void copyMarkdown()}>
              复制
            </button>
            <button className="ghost-button" type="button" disabled={!markdown || busy} onClick={downloadMarkdown}>
              下载 .md
            </button>
            <button
              className="primary-button"
              type="button"
              disabled={!markdown || busy}
              onClick={() => void polishReport()}
              title={polishStatus?.configured ? "调用润色 AI" : "未配置密钥时将返回原文并提示"}
            >
              {polishing ? "润色中…" : "AI 润色"}
            </button>
          </div>
        </div>
        <textarea
          className="quality-report-editor"
          value={markdown}
          onChange={(e) => setMarkdown(e.target.value)}
          placeholder="点击「生成质量报告」后将在此显示 Markdown；也可手工编辑后再润色。"
          rows={18}
          spellCheck={false}
        />
      </section>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>错误切片列表</h2>
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th>平面</th>
                <th>切片</th>
                <th>错误体素</th>
                <th>Pred</th>
                <th>Ref</th>
              </tr>
            </thead>
            <tbody>
              {errorSlices.length ? (
                errorSlices.map((slice, index) => (
                  <tr key={`${slice.axis}-${slice.slice_index}-${index}`}>
                    <td>{slice.axis || "-"}</td>
                    <td>{Number(slice.slice_index ?? 0) + 1}</td>
                    <td>{slice.error_voxels ?? "-"}</td>
                    <td>{slice.pred_voxels ?? "-"}</td>
                    <td>{slice.ref_voxels ?? "-"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5}>
                    <div className="placeholder">暂无错误切片（需选择 ref 后才可能返回）。</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
