import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { useToast } from "../components/Toast";
import type { CaseDetail, CaseItem, ImageItem, MaskItem, MaskMetricsReport } from "../types";
import { STATUS_TEXT } from "../types";

function isNiftiMask(mask: MaskItem) {
  return mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz");
}

function formatSliceRange(range: number[] | string | undefined) {
  if (Array.isArray(range)) return range.join(" - ");
  return range || "-";
}

export function QualityPage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [caseId, setCaseId] = useState("");
  const [masks, setMasks] = useState<MaskItem[]>([]);
  const [maskId, setMaskId] = useState("");
  const [refMaskId, setRefMaskId] = useState("");
  const [report, setReport] = useState<MaskMetricsReport | null>(null);
  const [loading, setLoading] = useState(false);

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

  useEffect(() => {
    void loadCases();
  }, [loadCases, refreshKey]);

  useEffect(() => {
    void loadMasks(caseId);
    setReport(null);
  }, [caseId, loadMasks, refreshKey]);

  async function loadMetrics() {
    if (!maskId) {
      showToast("请先选择要评价的 Mask 版本");
      return;
    }
    setLoading(true);
    try {
      const query = refMaskId ? `?ref=${encodeURIComponent(refMaskId)}` : "";
      const data = await apiGet<MaskMetricsReport>(`/api/mask/${maskId}/metrics${query}`);
      setReport(data);
      showToast("质量指标已加载");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "质量指标加载失败");
    } finally {
      setLoading(false);
    }
  }

  const geometric = report?.geometric;
  const overlap = report?.overlap;
  const errorSlices = report?.error_slices || [];

  return (
    <>
      <section className="panel">
        <h2>质量报告</h2>
        <p className="panel-lead">
          无 GT 时展示体积/连通域；有 GT 时请求 <code>/api/mask/{"{id}"}/metrics?ref=...</code> 返回 Dice /
          IoU / HD95 与错误切片。
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
            className="primary-button"
            type="button"
            disabled={!masks.length || loading}
            onClick={() => void loadMetrics()}
          >
            {loading ? "加载中…" : "拉取指标"}
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
            <div className="placeholder compact">选择 Mask 后点击「拉取指标」。</div>
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
