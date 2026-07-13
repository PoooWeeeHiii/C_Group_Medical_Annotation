import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "./Toast";
import { LoginOverlay } from "./LoginOverlay";
import { NAV_ITEMS, ROLE_TEXT } from "../types";
import { apiGet } from "../api/client";

const TITLES: Record<string, string> = {
  "/": "数据总览",
  "/cases": "病例中心",
  "/annotation": "标注工作台",
  "/train": "AI训练中心",
  "/versions": "版本审核",
  "/quality": "质量报告",
  "/export": "Dataset导出",
  "/settings": "系统设置",
};

export function AppLayout({ onRefresh }: { onRefresh: () => void }) {
  const { user, logout } = useAuth();
  const { showToast } = useToast();
  const location = useLocation();
  const [apiOnline, setApiOnline] = useState(false);
  const [dateText, setDateText] = useState("");

  useEffect(() => {
    setDateText(
      new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }),
    );
    apiGet("/api/health")
      .then(() => setApiOnline(true))
      .catch(() => setApiOnline(false));
  }, [location.pathname]);

  const titleKey = Object.keys(TITLES).find((key) =>
    key === "/" ? location.pathname === "/" : location.pathname.startsWith(key),
  );
  const pageTitle = TITLES[titleKey || "/"] || "医学影像标注";

  return (
    <>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
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
            <div>
              <div className="brand-title">Medical Annotation</div>
              <div className="brand-subtitle">NEU · C组医学标注平台</div>
            </div>
          </div>

          <nav className="nav-list" aria-label="主导航">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="sidebar-footer">
            <span className={`status-dot ${apiOnline ? "online" : ""}`} />
            <span>{apiOnline ? "后端已连接" : "后端未连接"}</span>
          </div>
        </aside>

        <main className="workspace">
          <header className="topbar">
            <div>
              <div className="eyebrow">医学 AI 工作站 · React</div>
              <h1>{pageTitle}</h1>
            </div>
            <div className="topbar-actions">
              <div className="date-pill">
                {user ? `${user.username} · ${ROLE_TEXT[user.role] || user.role}` : "未登录"}
              </div>
              <div className="date-pill">{dateText}</div>
              {!user ? (
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => window.dispatchEvent(new Event("label-platform-open-login"))}
                >
                  登录
                </button>
              ) : (
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => {
                    logout();
                    showToast("已退出登录");
                  }}
                >
                  退出
                </button>
              )}
              <button
                className="ghost-button"
                type="button"
                onClick={() => {
                  onRefresh();
                  showToast("数据已刷新");
                }}
              >
                刷新
              </button>
            </div>
          </header>
          <section className="view-root" aria-live="polite">
            <Outlet />
          </section>
        </main>
      </div>
      <LoginOverlay />
    </>
  );
}
