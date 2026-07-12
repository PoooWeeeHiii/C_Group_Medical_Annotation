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
  "/inference": "AI推理中心",
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
                <rect x="12" y="14" width="56" height="52" rx="12" className="mark-frame" />
                <path d="M24 43h10l5-13 8 25 6-12h9" className="mark-wave" />
                <path d="M40 23v14M33 30h14" className="mark-cross" />
                <line x1="18" y1="18" x2="18" y2="62" className="mark-scan" />
              </svg>
            </div>
            <div>
              <div className="brand-title">Medical Annotation</div>
              <div className="brand-subtitle">C组医学标注平台</div>
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
