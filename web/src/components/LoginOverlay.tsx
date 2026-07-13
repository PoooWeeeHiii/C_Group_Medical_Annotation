import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "./Toast";

const ROLE_PRESETS = {
  annotator: {
    username: "annotator",
    password: "annotator123",
    hint: "演示口令：annotator123 · 可标注、预测、提交审核",
    title: "标注员",
    en: "Annotator",
    desc: "2D/3D 标注 · AI 预测 · 提交审核",
  },
  reviewer: {
    username: "reviewer",
    password: "reviewer123",
    hint: "演示口令：reviewer123 · 可审核通过 / 驳回、查看队列",
    title: "审核员",
    en: "Reviewer",
    desc: "审核队列 · 通过 / 驳回 · 质量对比",
  },
  admin: {
    username: "admin",
    password: "admin123",
    hint: "演示口令：admin123 · 用户与系统设置全权限",
    title: "管理员",
    en: "Admin",
    desc: "用户与任务 · 标签设置 · 全权限",
  },
} as const;

type RoleKey = keyof typeof ROLE_PRESETS;

export function LoginOverlay() {
  const { user, login } = useAuth();
  const { showToast } = useToast();
  const [dismissed, setDismissed] = useState(false);
  const [role, setRole] = useState<RoleKey>("annotator");
  const [username, setUsername] = useState(ROLE_PRESETS.annotator.username);
  const [password, setPassword] = useState(ROLE_PRESETS.annotator.password);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const open = () => setDismissed(false);
    window.addEventListener("label-platform-open-login", open);
    return () => window.removeEventListener("label-platform-open-login", open);
  }, []);

  if (user || dismissed) return null;

  function selectRole(next: RoleKey) {
    const preset = ROLE_PRESETS[next];
    setRole(next);
    setUsername(preset.username);
    setPassword(preset.password);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await login(username.trim(), password);
      showToast(`已登录：${username.trim()}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-overlay login-gate">
      <div className="login-gate-bg" aria-hidden="true">
        <span className="login-grid" />
        <span className="login-orb login-orb-a" />
        <span className="login-orb login-orb-b" />
        <span className="login-scanline" />
      </div>
      <div className="login-gate-shell">
        <section className="login-hero">
          <div className="login-hero-mark brand-mark" aria-hidden="true">
            <svg viewBox="0 0 80 80" role="img">
              <circle className="neu-core" cx="40" cy="40" r="30" />
              <circle className="neu-ring-inner" cx="40" cy="40" r="33" />
              <circle className="neu-ring-tech" cx="40" cy="40" r="36" />
              <path className="neu-mountain" d="M18 50 L28 32 L35 42 L43 24 L51 40 L58 30 L62 50 Z" />
              <path className="neu-mountain-edge" d="M18 50 L28 32 L35 42 L43 24 L51 40 L58 30 L62 50" />
              <path className="neu-water" d="M17 54 Q28 49 39 54 T61 54" />
              <path className="neu-water neu-water-b" d="M19 59 Q31 55 41 59 T63 59" />
              <text className="neu-letters" x="40" y="44">
                NEU
              </text>
              <circle className="neu-node" cx="40" cy="16" r="1.8" />
            </svg>
          </div>
          <p className="login-kicker">Northeastern University · Medical AI</p>
          <h1>医学影像标注平台</h1>
          <p className="login-hero-copy">
            人机协同闭环：导入 · 标注 · AI 预测 · 审核 · 训练 · 导出。请选择身份接入系统。
          </p>
          <ul className="login-feature-list">
            <li>
              <span>01</span>多平面标注与 3D 体视
            </li>
            <li>
              <span>02</span>多器官 AI 推理与修正
            </li>
            <li>
              <span>03</span>版本审核与 Dataset 导出
            </li>
          </ul>
          <div className="login-hero-foot">自强不息 · 知行合一</div>
        </section>

        <section className="login-panel">
          <div className="login-panel-head">
            <h2>身份接入</h2>
            <p>选择角色后自动填充演示账号，也可手动修改。</p>
          </div>
          <div className="role-cards" role="radiogroup" aria-label="选择登录身份">
            {(Object.keys(ROLE_PRESETS) as RoleKey[]).map((key) => {
              const item = ROLE_PRESETS[key];
              const active = role === key;
              return (
                <button
                  key={key}
                  type="button"
                  className={`role-card ${active ? "active" : ""}`}
                  aria-pressed={active}
                  onClick={() => selectRole(key)}
                >
                  <strong>{item.title}</strong>
                  <span>{item.en}</span>
                  <small>{item.desc}</small>
                </button>
              );
            })}
          </div>
          <form className="login-form" onSubmit={onSubmit}>
            <label>
              用户名
              <input value={username} onChange={(e) => setUsername(e.target.value)} required />
            </label>
            <label>
              密码
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            <p className="login-hint">{ROLE_PRESETS[role].hint}</p>
            <div className="login-actions">
              <button className="primary-button login-submit" type="submit" disabled={busy}>
                进入系统
              </button>
              <button className="ghost-button" type="button" onClick={() => setDismissed(true)}>
                稍后浏览
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
