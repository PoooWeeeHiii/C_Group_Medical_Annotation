import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "./Toast";

export function LoginOverlay() {
  const { user, login } = useAuth();
  const { showToast } = useToast();
  const [dismissed, setDismissed] = useState(false);
  const [username, setUsername] = useState("annotator");
  const [password, setPassword] = useState("annotator123");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const open = () => setDismissed(false);
    window.addEventListener("label-platform-open-login", open);
    return () => window.removeEventListener("label-platform-open-login", open);
  }, []);

  if (user || dismissed) return null;

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
    <div className="login-overlay">
      <form className="login-card" onSubmit={onSubmit}>
        <h2>登录标注平台</h2>
        <p>演示账号：annotator / reviewer / admin，密码均为对应名 + 123</p>
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
        <div className="login-actions">
          <button className="primary-button" type="submit" disabled={busy}>
            登录
          </button>
          <button className="ghost-button" type="button" onClick={() => setDismissed(true)}>
            稍后
          </button>
        </div>
      </form>
    </div>
  );
}
