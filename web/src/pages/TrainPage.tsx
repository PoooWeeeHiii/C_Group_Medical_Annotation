import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { useToast } from "../components/Toast";
import type { TrainJob } from "../types";

const ACTIVE_STATUSES = new Set(["running", "queued", "pending"]);

export function TrainPage({ refreshKey }: { refreshKey: number }) {
  const { showToast } = useToast();
  const [jobs, setJobs] = useState<TrainJob[]>([]);
  const [activeJob, setActiveJob] = useState<TrainJob | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshJob = useCallback(async (jobId?: string) => {
    if (!jobId) {
      const list = await apiGet<{ items?: TrainJob[] }>("/api/train");
      const items = list.items || [];
      setJobs(items);
      // Prefer Person B completed jobs with Val Dice for the summary panel.
      const preferred =
        items.find((item) => item.status === "completed" && item.metrics?.best_val_dice != null) ||
        items[0] ||
        null;
      setActiveJob(preferred);
      return preferred;
    }
    const data = await apiGet<{ job: TrainJob }>(`/api/train/${jobId}`);
    setActiveJob(data.job);
    setJobs((prev) => {
      const next = prev.filter((item) => item.job_id !== data.job.job_id);
      return [data.job, ...next];
    });
    return data.job;
  }, []);

  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      pollRef.current = window.setInterval(async () => {
        try {
          const job = await refreshJob(jobId);
          if (job && !ACTIVE_STATUSES.has(job.status)) {
            stopPolling();
            if (job.status === "completed") {
              showToast(`训练完成并已注册：${job.registered_model_id || job.model_id || job.job_id}`);
            } else if (job.status === "failed") {
              showToast(job.error || "训练失败");
            }
          }
        } catch {
          // keep polling
        }
      }, 2500);
    },
    [refreshJob, showToast, stopPolling],
  );

  const load = useCallback(async () => {
    try {
      const job = await refreshJob();
      if (job && ACTIVE_STATUSES.has(job.status)) {
        startPolling(job.job_id);
      }
    } catch {
      setJobs([]);
      setActiveJob(null);
    }
  }, [refreshJob, startPolling]);

  useEffect(() => {
    void load();
    return () => stopPolling();
  }, [load, refreshKey, stopPolling]);

  async function onStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const datasetId = String(fd.get("dataset_id") || "").trim();
    if (!datasetId) {
      showToast("请填写已导出的 Dataset ID");
      return;
    }
    setStarting(true);
    try {
      const modelId = String(fd.get("model_id") || "").trim();
      const data = await apiPost<{ job: TrainJob }>(
        "/api/train",
        {
          dataset_id: datasetId,
          model_id: modelId || null,
          epochs: Number(fd.get("epochs") || 20),
          batch_size: Number(fd.get("batch_size") || 4),
          lr: Number(fd.get("lr") || 0.0001),
          num_classes: Number(fd.get("num_classes") || 6),
          image_size: Number(fd.get("image_size") || 320),
          context_radius: Number(fd.get("context_radius") || 1),
        },
        { timeoutMs: 60_000 },
      );
      setActiveJob(data.job);
      setJobs((prev) => [data.job, ...prev.filter((item) => item.job_id !== data.job.job_id)]);
      showToast(`训练任务已启动：${data.job.job_id}`);
      startPolling(data.job.job_id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "启动训练失败");
    } finally {
      setStarting(false);
    }
  }

  const job = activeJob;
  const status = job?.status || "idle";
  const history = Array.isArray(job?.metrics?.history) ? job.metrics.history : [];
  const logs =
    (job?.logs || job?.log_tail || []).slice(-40).join("\n") ||
    "等待开始训练…\n先在 Dataset 导出页 materialize，再填写 dataset_id。";
  const busy = ACTIVE_STATUSES.has(status);

  return (
    <>
      <div className="grid cols-2">
        <section className="panel">
          <h2>训练配置</h2>
          <p className="panel-lead">
            下方列表已包含 Person B 完成的 <strong>脾 nnUNet / Plan A 四器官 / DeepEdit</strong> 任务。
            也可基于导出 Dataset 启动平台 <strong>2.5D U-Net</strong> 新训练。
          </p>
          <form className="toolbar-row inference-toolbar" style={{ marginTop: 14, flexWrap: "wrap", gap: 10 }} onSubmit={onStart}>
            <label className="field">
              <span>Dataset ID</span>
              <input name="dataset_id" placeholder="Dataset0001" required />
            </label>
            <label className="field">
              <span>Model ID</span>
              <input name="model_id" defaultValue={job?.model_id || ""} placeholder="自动生成" />
            </label>
            <label className="field">
              <span>Epochs</span>
              <input name="epochs" type="number" min={1} max={500} defaultValue={20} />
            </label>
            <label className="field">
              <span>Batch</span>
              <input name="batch_size" type="number" min={1} max={64} defaultValue={4} />
            </label>
            <label className="field">
              <span>LR</span>
              <input name="lr" type="number" step={0.0001} defaultValue={0.0001} />
            </label>
            <label className="field">
              <span>Classes</span>
              <input name="num_classes" type="number" min={2} max={64} defaultValue={6} />
            </label>
            <label className="field">
              <span>Image size</span>
              <input name="image_size" type="number" min={64} max={512} defaultValue={320} />
            </label>
            <label className="field">
              <span>2.5D radius</span>
              <input name="context_radius" type="number" min={0} max={3} defaultValue={1} title="1=三通道(z-1,z,z+1)" />
            </label>
            <button className="primary-button" type="submit" disabled={starting || busy}>
              {starting ? "启动中…" : "开始训练"}
            </button>
            <button
              className="ghost-button"
              type="button"
              onClick={async () => {
                try {
                  await refreshJob(job?.job_id);
                  showToast("状态已刷新");
                } catch (error) {
                  showToast(error instanceof Error ? error.message : "刷新失败");
                }
              }}
            >
              刷新状态
            </button>
            <strong style={{ marginLeft: 12 }}>状态：{status}</strong>
          </form>
          {job?.registered_model_id ? (
            <p style={{ marginTop: 12, color: "var(--green)" }}>
              已注册模型：{job.registered_model_id}，可去标注台选用预测。
            </p>
          ) : null}
          {job?.error ? <p className="panel-lead" style={{ color: "var(--danger, #ff6b6b)" }}>{job.error}</p> : null}
        </section>

        <section className="panel">
          <h2>Val Dice</h2>
          <div className="line-chart">
            {history.length ? (
              history.map((row) => {
                const dice = Math.max(0, Math.min(1, Number(row.val_dice) || 0));
                return (
                  <div
                    className="bar"
                    key={row.epoch}
                    style={{ height: `${Math.round(dice * 100)}%` }}
                    title={`epoch ${row.epoch}: dice ${dice.toFixed(3)}`}
                  />
                );
              })
            ) : (
              <div className="placeholder compact">训练开始后显示 Val Dice</div>
            )}
          </div>
          <div className="case-meta" style={{ marginTop: 12 }}>
            <div className="meta-line">
              <span>epoch</span>
              <strong>{job?.current_epoch ?? "-"}</strong>
            </div>
            <div className="meta-line">
              <span>train_loss</span>
              <strong>{job?.train_loss != null ? Number(job.train_loss).toFixed(4) : "-"}</strong>
            </div>
            <div className="meta-line">
              <span>val_dice</span>
              <strong>{job?.val_dice != null ? Number(job.val_dice).toFixed(4) : "-"}</strong>
            </div>
            <div className="meta-line">
              <span>best_val_dice</span>
              <strong>
                {job?.metrics?.best_val_dice != null ? Number(job.metrics.best_val_dice).toFixed(4) : "-"}
              </strong>
            </div>
          </div>
        </section>
      </div>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>训练任务列表</h2>
        <p className="panel-lead">含平台 U-Net 任务与 Person B 本地已训完模型（只读摘要）。</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>来源</th>
                <th>Dataset</th>
                <th>Model</th>
                <th>Val Dice</th>
                <th>状态</th>
                <th>Epoch</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length ? (
                jobs.map((item) => {
                  const source = String(item.metrics?.source || (item.job_id.startsWith("TrainJob_PersonB") ? "person_b" : "platform"));
                  const dice =
                    item.val_dice ??
                    item.metrics?.best_val_dice ??
                    null;
                  return (
                  <tr key={item.job_id}>
                    <td>
                      <strong>{item.job_id}</strong>
                    </td>
                    <td>
                      <span className="status-badge">{source}</span>
                    </td>
                    <td>{item.dataset_id || "-"}</td>
                    <td>{item.registered_model_id || item.model_id || "-"}</td>
                    <td>{dice != null ? Number(dice).toFixed(4) : "-"}</td>
                    <td>
                      <span className="status-badge">{item.status}</span>
                    </td>
                    <td>
                      {item.current_epoch ?? "-"} / {item.epochs ?? "-"}
                    </td>
                    <td>
                      <button
                        className="ghost-button"
                        type="button"
                        onClick={async () => {
                          try {
                            const next = await refreshJob(item.job_id);
                            if (next && ACTIVE_STATUSES.has(next.status)) startPolling(next.job_id);
                          } catch (error) {
                            showToast(error instanceof Error ? error.message : "加载失败");
                          }
                        }}
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={8}>
                    <div className="placeholder">暂无训练任务。</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" style={{ marginTop: 18 }}>
        <h2>训练日志</h2>
        <div className="log-box">{logs}</div>
      </section>
    </>
  );
}
