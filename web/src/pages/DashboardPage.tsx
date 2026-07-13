import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../api/client";
import type { CaseItem, TrainJob } from "../types";

function MetricCard({ title, value, note }: { title: string; value: string | number; note: string }) {
  return (
    <article className="metric-card">
      <div className="metric-label">{title}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </article>
  );
}

export function DashboardPage({ refreshKey }: { refreshKey: number }) {
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [trainJob, setTrainJob] = useState<TrainJob | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      setCases(data.items || []);
    } catch {
      setCases([]);
    }
    try {
      const jobs = await apiGet<{ items?: TrainJob[]; job?: TrainJob }>("/api/train/jobs");
      setTrainJob(jobs.job || jobs.items?.[0] || null);
    } catch {
      setTrainJob(null);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const total = cases.length;
  const annotated = cases.filter((item) => item.status !== "unannotated").length;
  const pending = Math.max(total - annotated, 0);
  const progress = total ? Math.round((annotated / total) * 100) : 0;
  const metrics = trainJob?.metrics;
  const bestDice = metrics?.best_val_dice != null ? Number(metrics.best_val_dice).toFixed(3) : "暂无";
  const history = Array.isArray(metrics?.history) ? metrics.history : [];

  return (
    <>
      <div className="dashboard-hero">
        <section className="hero-panel">
          <div className="hero-title">
            <div className="holo-emblem neu-holo" aria-hidden="true">
              <span className="holo-ring ring-a" />
              <span className="holo-ring ring-b" />
              <span className="holo-orbit orbit-a" />
              <span className="holo-orbit orbit-b" />
              <svg className="holo-symbol" viewBox="0 0 120 120">
                <circle className="neu-holo-core" cx="60" cy="60" r="42" />
                <path className="neu-holo-mountain" d="M28 76 L42 46 L52 62 L64 34 L76 58 L88 44 L94 76 Z" />
                <path className="neu-holo-mountain-edge" d="M28 76 L42 46 L52 62 L64 34 L76 58 L88 44 L94 76" />
                <path className="neu-holo-water" d="M26 82 Q42 74 58 82 T90 82" />
                <path className="neu-holo-water neu-holo-water-b" d="M30 90 Q48 84 62 90 T94 90" />
                <text className="neu-holo-letters" x="60" y="66">
                  NEU
                </text>
                <text className="neu-holo-motto" x="60" y="102">
                  自强不息 · 知行合一
                </text>
              </svg>
              <span className="holo-scan" />
              <span className="holo-particle p1" />
              <span className="holo-particle p2" />
              <span className="holo-particle p3" />
            </div>
            <div>
              <h2>Medical Annotation</h2>
              <div className="eyebrow">东北大学 NEU · 人机协同闭环标注</div>
            </div>
          </div>
          <p className="hero-copy">
            CT 导入、病例管理、人工标注、AI 推理、版本审核、质量评价和 Dataset 导出统一在一个闭环系统中完成。
          </p>
          <div className="pipeline">
            {["导入", "病例", "图像", "标注", "Mask", "Dataset", "训练", "模型", "预测", "修正"].map(
              (item) => (
                <span className="chip" key={item}>
                  {item}
                </span>
              ),
            )}
          </div>
        </section>
        <section className="panel chart-box">
          <h2>标注进度</h2>
          <div
            className="ring"
            style={{
              background: `conic-gradient(var(--green) 0 ${progress}%, rgba(255,255,255,.08) ${progress}% 100%)`,
            }}
          >
            <div className="ring-inner">
              <div>
                <strong>{progress}%</strong>
                <br />
                <span className="metric-label">已处理</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div className="grid cols-4">
        <MetricCard title="病例总数" value={total} note="来自后端 /api/cases" />
        <MetricCard title="已标注" value={annotated} note="人工 + AI + 修正" />
        <MetricCard title="待处理" value={pending} note="仍为 unannotated" />
        <MetricCard
          title="最佳 Dice"
          value={bestDice}
          note={metrics ? `模型 ${metrics.model_id || ""}` : "来自最近一次真实训练"}
        />
      </div>

      <div className="grid cols-2" style={{ marginTop: 18 }}>
        <section className="panel">
          <h2>AI训练 Val Dice</h2>
          <div className="line-chart">
            {history.length ? (
              history.slice(-10).map((row) => {
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
              <div className="placeholder compact">尚无真实训练指标。请在「AI训练中心」启动训练。</div>
            )}
          </div>
        </section>
        <section className="panel">
          <h2>最近任务</h2>
          <div className="log-box">
            {`上传 CT (+金标准) -> Case / Image / Mask
人工多标签标注 -> 保存 Mask
AI 预测 -> v2_ai
DeepEdit / 图割 -> v3_preview
导出多类 Dataset -> 训练中心 U-Net
注册模型 -> 标注台选用预测`}
          </div>
        </section>
      </div>
    </>
  );
}
