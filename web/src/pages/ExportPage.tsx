import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { useToast } from "../components/Toast";
import type { CaseItem, DatasetExportResult } from "../types";
import { STATUS_TEXT } from "../types";

type SplitValue = "none" | "train" | "val" | "test";

export function ExportPage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [assignments, setAssignments] = useState<Record<string, SplitValue>>({});
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<DatasetExportResult | null>(null);
  const [labelSet, setLabelSet] = useState<"dense" | "weak">("dense");
  const [version, setVersion] = useState("final");
  const [format, setFormat] = useState("nnunet");
  const [materialize, setMaterialize] = useState(true);
  const [strict, setStrict] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      const items = data.items || [];
      setCases(items);
      setAssignments((prev) => {
        const next = { ...prev };
        for (const item of items) {
          if (!next[item.case_id]) next[item.case_id] = "none";
        }
        return next;
      });
    } catch {
      setCases([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (labelSet === "weak" && version === "final") setVersion("v3_preview");
    if (labelSet === "dense" && version === "v3_preview") setVersion("final");
  }, [labelSet, version]);

  const counts = useMemo(() => {
    return Object.values(assignments).reduce(
      (acc, split) => {
        if (split === "train" || split === "val" || split === "test") acc[split] += 1;
        return acc;
      },
      { train: 0, val: 0, test: 0 },
    );
  }, [assignments]);

  async function onExport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const datasetId = String(fd.get("dataset_id") || "").trim() || undefined;
    const name =
      String(fd.get("name") || "").trim() || `medical_seg_${labelSet}_${version}`;

    let exportVersion = version;
    if (labelSet === "weak" && exportVersion === "final") exportVersion = "v3_preview";

    const train: string[] = [];
    const val: string[] = [];
    const test: string[] = [];
    for (const [caseId, split] of Object.entries(assignments)) {
      if (split === "train") train.push(caseId);
      else if (split === "val") val.push(caseId);
      else if (split === "test") test.push(caseId);
    }
    if (!train.length && !val.length && !test.length) {
      showToast("请至少选择一个病例并指定 train/val/test");
      return;
    }

    setExporting(true);
    try {
      const data = await apiPost<DatasetExportResult>(
        "/api/export",
        {
          dataset_id: datasetId,
          name,
          version: exportVersion,
          label_set: labelSet,
          train,
          val,
          test,
          format,
          materialize,
          strict,
        },
        { timeoutMs: 10 * 60 * 1000 },
      );
      setResult(data);
      showToast(data.message || `Dataset 导出成功：${data.dataset_id}`);
    } catch (error) {
      let message = error instanceof Error ? error.message : "Dataset 导出失败";
      try {
        const parsed = JSON.parse(message) as {
          message?: string;
          missing_masks?: Array<{ case_id: string; image_id?: string | null; version?: string; reason?: string }>;
        };
        if (parsed?.message) {
          message = parsed.message;
          if (Array.isArray(parsed.missing_masks)) {
            setResult({
              success: false,
              message: parsed.message,
              label_set: labelSet,
              version: exportVersion,
              report: {
                missing_masks: parsed.missing_masks,
                success_count: 0,
                skipped_count: parsed.missing_masks.length,
                spacing_checks: [],
              },
            });
          }
        }
      } catch {
        // keep raw message
      }
      showToast(message);
    } finally {
      setExporting(false);
    }
  }

  const report = result?.report;

  return (
    <>
      <section className="panel">
        <h2>训练数据集导出</h2>
        <p className="panel-lead">
          勾选 materialize 后会写入 <code>dataset/exports/DatasetXXXX/{"{imagesTr,labelsTr,dataset.json,splits_final.json}"}</code>
          。可分别导出<strong>弱标签</strong>（v3_preview 伪标）与<strong>精标</strong>（final）两套
          split。
        </p>
        <form onSubmit={onExport}>
          <div className="toolbar-row" style={{ marginTop: 12 }}>
            <label className="field">
              <span>Dataset ID</span>
              <input name="dataset_id" placeholder="自动生成 Dataset0001" />
            </label>
            <label className="field">
              <span>名称</span>
              <input name="name" placeholder="medical_segmentation_dataset" />
            </label>
            <label className="field">
              <span>标签集</span>
              <select
                value={labelSet}
                onChange={(e) => setLabelSet(e.target.value as "dense" | "weak")}
              >
                <option value="dense">精标 dense (final)</option>
                <option value="weak">弱标签 weak (v3_preview)</option>
              </select>
            </label>
            <label className="field">
              <span>版本</span>
              <select value={version} onChange={(e) => setVersion(e.target.value)}>
                <option value="final">final</option>
                <option value="v3_fusion">v3_fusion</option>
                <option value="v3_preview">v3_preview</option>
                <option value="v2_ai">v2_ai</option>
              </select>
            </label>
            <label className="field">
              <span>格式</span>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="nnunet">nnUNet</option>
                <option value="json">JSON Manifest</option>
              </select>
            </label>
          </div>
          <div className="toolbar-row" style={{ marginTop: 10 }}>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={materialize}
                onChange={(e) => setMaterialize(e.target.checked)}
              />{" "}
              materialize 真导出（拷贝/转换 NIfTI）
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />{" "}
              严格校验（缺 mask 则失败）
            </label>
            <button
              className="ghost-button"
              type="button"
              onClick={() => {
                const next: Record<string, SplitValue> = {};
                for (const item of cases) next[item.case_id] = "train";
                setAssignments(next);
              }}
            >
              全部设为 train
            </button>
            <button
              className="ghost-button"
              type="button"
              onClick={() => {
                const next: Record<string, SplitValue> = {};
                for (const item of cases) next[item.case_id] = "none";
                setAssignments(next);
              }}
            >
              清空划分
            </button>
            <button className="primary-button" type="submit" disabled={!cases.length || exporting}>
              {exporting ? (materialize ? "物化导出中…" : "导出中…") : "导出 Dataset"}
            </button>
          </div>
        </form>
        <div className="grid cols-3" style={{ marginTop: 14 }}>
          <article className="metric-card">
            <div className="metric-label">Train</div>
            <div className="metric-value">{counts.train}</div>
            <div className="metric-note">训练病例</div>
          </article>
          <article className="metric-card">
            <div className="metric-label">Val</div>
            <div className="metric-value">{counts.val}</div>
            <div className="metric-note">验证病例</div>
          </article>
          <article className="metric-card">
            <div className="metric-label">Test</div>
            <div className="metric-value">{counts.test}</div>
            <div className="metric-note">测试病例</div>
          </article>
        </div>
      </section>

      <section className="table-wrap" style={{ marginTop: 18 }}>
        <table>
          <thead>
            <tr>
              <th>病例</th>
              <th>患者</th>
              <th>状态</th>
              <th>Mask 数</th>
              <th>划分</th>
            </tr>
          </thead>
          <tbody>
            {cases.length ? (
              cases.map((item) => (
                <tr key={item.case_id}>
                  <td>{item.case_id}</td>
                  <td>{item.patient_id || "-"}</td>
                  <td>{STATUS_TEXT[item.status || ""] || item.status || "-"}</td>
                  <td>{item.mask_count ?? "-"}</td>
                  <td>
                    <select
                      value={assignments[item.case_id] || "none"}
                      onChange={(e) =>
                        setAssignments((prev) => ({
                          ...prev,
                          [item.case_id]: e.target.value as SplitValue,
                        }))
                      }
                    >
                      <option value="none">不导出</option>
                      <option value="train">train</option>
                      <option value="val">val</option>
                      <option value="test">test</option>
                    </select>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={5}>
                  <div className="placeholder">暂无病例</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>导出报告</h2>
        {result ? (
          <>
            <div className="case-meta">
              <div className="meta-line">
                <span>Dataset</span>
                <strong>{result.dataset_id || "-"}</strong>
              </div>
              <div className="meta-line">
                <span>标签集</span>
                <strong>{result.label_set || labelSet}</strong>
              </div>
              <div className="meta-line">
                <span>版本</span>
                <strong>{result.version || version}</strong>
              </div>
              <div className="meta-line">
                <span>Manifest</span>
                <strong>{result.output_path || "-"}</strong>
              </div>
              <div className="meta-line">
                <span>Export Dir</span>
                <strong>{result.export_dir || "-"}</strong>
              </div>
              <div className="meta-line">
                <span>dataset.json</span>
                <strong>{result.dataset_json_path || "-"}</strong>
              </div>
              <div className="meta-line">
                <span>splits_final.json</span>
                <strong>{result.splits_final_path || "-"}</strong>
              </div>
              <div className="meta-line">
                <span>说明</span>
                <strong>{result.message || ""}</strong>
              </div>
            </div>
            <div className="grid cols-4" style={{ marginTop: 14 }}>
              <article className="metric-card">
                <div className="metric-label">成功</div>
                <div className="metric-value">{report?.success_count ?? "-"}</div>
                <div className="metric-note">物化成功对数</div>
              </article>
              <article className="metric-card">
                <div className="metric-label">跳过</div>
                <div className="metric-value">{report?.skipped_count ?? "-"}</div>
                <div className="metric-note">缺文件/失败</div>
              </article>
              <article className="metric-card">
                <div className="metric-label">缺 Mask</div>
                <div className="metric-value">{report?.missing_masks?.length ?? "-"}</div>
                <div className="metric-note">校验结果</div>
              </article>
              <article className="metric-card">
                <div className="metric-label">Spacing 异常</div>
                <div className="metric-value">
                  {report?.spacing_checks?.filter((item) => item.status !== "ok").length ?? "-"}
                </div>
                <div className="metric-note">形状/间距</div>
              </article>
            </div>
            <div className="table-wrap" style={{ marginTop: 14 }}>
              <h3 style={{ margin: "0 0 8px" }}>缺 Mask 列表</h3>
              <table>
                <thead>
                  <tr>
                    <th>病例</th>
                    <th>图像</th>
                    <th>版本</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {report?.missing_masks?.length ? (
                    report.missing_masks.map((item, index) => (
                      <tr key={`${item.case_id}-${item.image_id}-${index}`}>
                        <td>{item.case_id}</td>
                        <td>{item.image_id || "-"}</td>
                        <td>{item.version || result.version || version}</td>
                        <td>{item.reason}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4}>无</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="placeholder compact">导出后显示报告。</div>
        )}
      </section>
    </>
  );
}
