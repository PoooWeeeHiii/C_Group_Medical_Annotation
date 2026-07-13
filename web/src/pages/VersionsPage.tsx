import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { useRole } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import type { CaseDetail, CaseItem, ImageItem, MaskItem, ReviewQueueItem, VersionItem } from "../types";
import { STATUS_TEXT } from "../types";

const VERSION_TIMELINE = ["v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"];

function isNiftiMask(mask: MaskItem) {
  return mask.mask_format === "nii.gz" || String(mask.path || "").endsWith(".nii.gz");
}

export function VersionsPage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const { canReview, canAnnotate } = useRole();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [caseId, setCaseId] = useState("");
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [masks, setMasks] = useState<MaskItem[]>([]);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [diff, setDiff] = useState<{
    dice?: number;
    iou?: number;
    volume_diff_ml?: number;
    hd95_mm?: number | null;
    pred_version?: string | null;
    ref_version?: string | null;
    intersection?: number;
    pred_voxels?: number;
    ref_voxels?: number;
    pred_volume_ml?: number;
    ref_volume_ml?: number;
    shape?: number[];
  } | null>(null);
  const [rejectNote, setRejectNote] = useState("");

  const loadQueue = useCallback(async () => {
    if (!canReview) {
      setQueue([]);
      return;
    }
    try {
      const data = await apiGet<{ items?: ReviewQueueItem[] }>("/api/review/queue");
      setQueue(data.items || []);
    } catch {
      setQueue([]);
    }
  }, [canReview]);

  const loadCaseData = useCallback(async (id: string) => {
    if (!id) {
      setVersions([]);
      setMasks([]);
      setRejectNote("");
      return;
    }
    try {
      const detail = await apiGet<CaseDetail & { case?: CaseItem; images?: ImageItem[] }>(
        `/api/case/${id}`,
      );
      setRejectNote(detail.case?.reject_note || detail.reject_note || "");
      const images = detail.images || [];
      const collected: MaskItem[] = [];
      for (const image of images) {
        try {
          const maskData = await apiGet<{ items?: MaskItem[]; masks?: MaskItem[] }>(
            `/api/image/${image.image_id}/masks`,
          );
          collected.push(...(maskData.items || maskData.masks || []));
        } catch {
          // ignore per-image failures
        }
      }
      const nifti = collected
        .filter(isNiftiMask)
        .sort((a, b) => String(b.create_time || "").localeCompare(String(a.create_time || "")));
      setMasks(nifti);
      setCompareA((prev) => (nifti.some((m) => m.mask_id === prev) ? prev : nifti[0]?.mask_id || ""));
      setCompareB((prev) =>
        nifti.some((m) => m.mask_id === prev) ? prev : nifti[1]?.mask_id || nifti[0]?.mask_id || "",
      );
    } catch {
      setMasks([]);
      setRejectNote("");
    }
    try {
      const data = await apiGet<{ items?: VersionItem[] }>(`/api/case/${id}/versions`);
      setVersions(data.items || []);
    } catch {
      setVersions([]);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      const items = data.items || [];
      setCases(items);
      setCaseId((prev) => prev || items[0]?.case_id || "");
    } catch {
      setCases([]);
    }
    await loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    void loadCaseData(caseId);
  }, [caseId, loadCaseData, refreshKey]);

  async function submitCase() {
    if (!caseId) return;
    try {
      const data = await apiPost<{ message?: string }>(`/api/case/${caseId}/submit`, {
        note: "submitted from versions page",
      });
      showToast(data.message || "已提交审核");
      await load();
      await loadCaseData(caseId);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "提交失败");
    }
  }

  async function approveCase(targetId = caseId) {
    if (!targetId) return;
    try {
      const data = await apiPost<{ message?: string }>(`/api/case/${targetId}/approve`, {
        note: "approved",
      });
      showToast(data.message || "审核通过");
      await load();
      if (targetId === caseId) await loadCaseData(caseId);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "审核失败");
    }
  }

  async function rejectCase(targetId = caseId) {
    if (!targetId) return;
    const note = window.prompt("请输入驳回原因", "需要继续修正标注") || "rejected";
    try {
      const data = await apiPost<{ message?: string }>(`/api/case/${targetId}/reject`, { note });
      showToast(data.message || "已驳回");
      await load();
      if (targetId === caseId) await loadCaseData(caseId);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "驳回失败");
    }
  }

  async function runDiff() {
    if (!compareA || !compareB || compareA === compareB) {
      showToast("请选择两个不同的 Mask");
      return;
    }
    try {
      const data = await apiGet<{
        dice?: number;
        iou?: number;
        volume_diff_ml?: number;
        hd95_mm?: number | null;
        pred_version?: string | null;
        ref_version?: string | null;
      }>(`/api/mask/${compareA}/compare/${compareB}`);
      setDiff(data);
      showToast(`Dice ${Number(data.dice || 0).toFixed(4)}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Diff 失败");
    }
  }

  async function rollbackMask(maskId: string) {
    if (!window.confirm(`确认将 ${maskId} 回滚复制为新的 v3_preview？`)) return;
    try {
      const data = await apiPost<{ message?: string; mask_id?: string }>(
        `/api/mask/${maskId}/rollback`,
        {},
      );
      showToast(data.message || `已回滚为 ${data.mask_id}`);
      await loadCaseData(caseId);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "回滚失败");
    }
  }

  const activeCase = cases.find((item) => item.case_id === caseId);

  return (
    <>
      <section className="panel">
        <h2>审核队列（pending）</h2>
        <p className="panel-lead">
          审核员无需打开标注台即可通过/驳回。通过将自动 promote 最新 v3_preview/v3_fusion → final。
        </p>
        {canReview ? (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>病例</th>
                  <th>患者</th>
                  <th>可 promote</th>
                  <th>Mask 数</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {queue.length ? (
                  queue.map((entry) => (
                    <tr key={entry.case_id}>
                      <td>{entry.case_id}</td>
                      <td>{entry.patient_id || "-"}</td>
                      <td>
                        {entry.promotable_mask_id ? (
                          `${entry.promotable_version} / ${entry.promotable_mask_id}`
                        ) : (
                          <span className="muted">无</span>
                        )}
                      </td>
                      <td>{entry.mask_count ?? "-"}</td>
                      <td className="review-actions">
                        <button className="ghost-button" type="button" onClick={() => setCaseId(entry.case_id)}>
                          查看版本
                        </button>
                        <button
                          className="primary-button"
                          type="button"
                          disabled={!entry.promotable_mask_id}
                          onClick={() => void approveCase(entry.case_id)}
                        >
                          通过→final
                        </button>
                        <button
                          className="danger-button"
                          type="button"
                          onClick={() => void rejectCase(entry.case_id)}
                        >
                          驳回
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5}>
                      <div className="placeholder">当前没有 pending 病例</div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="placeholder compact">请使用 reviewer / admin 账号查看审核队列。</div>
        )}
      </section>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>版本管理</h2>
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
          <button
            className="ghost-button"
            type="button"
            disabled={!caseId || !canAnnotate}
            onClick={() => void submitCase()}
          >
            提交审核
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={!caseId || !canReview}
            onClick={() => void approveCase()}
          >
            审核通过→final
          </button>
          <button
            className="danger-button"
            type="button"
            disabled={!caseId || !canReview}
            onClick={() => void rejectCase()}
          >
            驳回
          </button>
        </div>
        <div className="timeline" style={{ marginTop: 14 }}>
          {VERSION_TIMELINE.map((version) => (
            <span
              className={`chip ${versions.some((entry) => entry.version === version) ? "active-chip" : ""}`}
              key={version}
            >
              {version}
            </span>
          ))}
        </div>
        {(rejectNote || activeCase?.reject_note) && (
          <div className="reject-note-box" style={{ marginTop: 12 }}>
            <span>最近驳回意见</span>
            <strong>{rejectNote || activeCase?.reject_note}</strong>
          </div>
        )}
        <div className="table-wrap" style={{ marginTop: 14 }}>
          <table>
            <thead>
              <tr>
                <th>版本</th>
                <th>Annotation</th>
                <th>Model</th>
                <th>Dataset</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {versions.length ? (
                versions.map((item, index) => (
                  <tr key={`${item.version}-${item.create_time}-${index}`}>
                    <td>
                      <strong>{item.version}</strong>
                    </td>
                    <td>{item.annotation || "-"}</td>
                    <td>{item.model || "-"}</td>
                    <td>{item.dataset || "-"}</td>
                    <td>{item.create_time || "-"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5}>
                    <div className="placeholder compact">
                      暂无版本记录。保存 Mask 后会写入 v1_manual，智能修正后写入 v3_preview，确认后写入
                      v3_fusion 或 final。
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel diff-panel" style={{ marginTop: 18 }}>
        <div className="subsection-title">
          <span>版本 Diff / 回滚</span>
          <strong>三维 Mask 体素级对比</strong>
        </div>
        <p className="panel-lead">
          将两个 NIfTI Mask 二值化（体素 &gt; 0）后计算重叠与表面距离。Dice / IoU 越接近 1 越相似；体积差为
          A−B；HD95 为双向表面距离的 95 分位（mm）。
        </p>
        <div className="diff-controls">
          <label className="field">
            <span>Mask A（预测侧）</span>
            <select value={compareA} onChange={(e) => setCompareA(e.target.value)}>
              <option value="">选择 Mask</option>
              {masks.map((mask) => (
                <option key={mask.mask_id} value={mask.mask_id}>
                  {mask.mask_id} · {mask.version} · {mask.label}
                </option>
              ))}
            </select>
          </label>
          <div className="diff-vs" aria-hidden="true">
            VS
          </div>
          <label className="field">
            <span>Mask B（参考侧）</span>
            <select value={compareB} onChange={(e) => setCompareB(e.target.value)}>
              <option value="">选择 Mask</option>
              {masks.map((mask) => (
                <option key={mask.mask_id} value={mask.mask_id}>
                  {mask.mask_id} · {mask.version} · {mask.label}
                </option>
              ))}
            </select>
          </label>
          <button className="primary-button" type="button" disabled={!masks.length} onClick={() => void runDiff()}>
            计算 Diff
          </button>
        </div>
        <div className="diff-metrics">
          <article className="diff-metric-card">
            <div className="metric-label">Dice</div>
            <div className="metric-value">{diff ? Number(diff.dice).toFixed(4) : "-"}</div>
            <div className="metric-note">
              {diff ? `${diff.pred_version} vs ${diff.ref_version}` : "2|A∩B| / (|A|+|B|)"}
            </div>
          </article>
          <article className="diff-metric-card">
            <div className="metric-label">IoU</div>
            <div className="metric-value">{diff ? Number(diff.iou).toFixed(4) : "-"}</div>
            <div className="metric-note">{diff ? "重叠比" : "|A∩B| / |A∪B|"}</div>
          </article>
          <article className="diff-metric-card">
            <div className="metric-label">体积差</div>
            <div className="metric-value">
              {diff ? Number(diff.volume_diff_ml).toFixed(3) : "-"}
              {diff ? <small> ml</small> : null}
            </div>
            <div className="metric-note">
              {diff
                ? `A ${Number(diff.pred_volume_ml || 0).toFixed(2)} − B ${Number(diff.ref_volume_ml || 0).toFixed(2)} ml`
                : "体素数 × spacing"}
            </div>
          </article>
          <article className="diff-metric-card">
            <div className="metric-label">HD95</div>
            <div className="metric-value">
              {diff?.hd95_mm != null ? Number(diff.hd95_mm).toFixed(3) : "-"}
              {diff?.hd95_mm != null ? <small> mm</small> : null}
            </div>
            <div className="metric-note">表面距离 95 分位</div>
          </article>
        </div>
        {diff ? (
          <div className="diff-detail">
            <span>
              相交体素 <b>{Number(diff.intersection || 0).toLocaleString("zh-CN")}</b>
            </span>
            <span>
              A 体素 <b>{Number(diff.pred_voxels || 0).toLocaleString("zh-CN")}</b>
            </span>
            <span>
              B 体素 <b>{Number(diff.ref_voxels || 0).toLocaleString("zh-CN")}</b>
            </span>
            <span>
              尺寸 <b>{Array.isArray(diff.shape) ? diff.shape.join("×") : "-"}</b>
            </span>
          </div>
        ) : null}
        <h3 className="diff-list-title">本病例 3D Mask</h3>
        <div className="mask-version-cards">
          {masks.length ? (
            masks.map((mask) => {
              const pathText = String(mask.path || "");
              const shortPath = pathText.split("/").slice(-2).join("/") || pathText;
              return (
                <article className="mask-version-card" key={mask.mask_id}>
                  <div className="mask-version-card-head">
                    <strong>{mask.mask_id}</strong>
                    <span className="chip active-chip">{mask.version}</span>
                  </div>
                  <div className="mask-version-card-meta">
                    <span>
                      标签 <b>{mask.label || "-"}</b>
                    </span>
                    <code title={pathText}>{shortPath}</code>
                  </div>
                  <button
                    className="ghost-button"
                    type="button"
                    onClick={() => void rollbackMask(mask.mask_id)}
                  >
                    回滚为 v3_preview
                  </button>
                </article>
              );
            })
          ) : (
            <div className="placeholder compact">当前病例暂无 3D NIfTI Mask</div>
          )}
        </div>
      </section>
    </>
  );
}
