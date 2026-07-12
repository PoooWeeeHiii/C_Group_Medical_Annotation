import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost, apiPut } from "../api/client";
import { useRole } from "../auth/AuthContext";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import type { LabelItem, User } from "../types";
import { ROLE_TEXT } from "../types";

export function SettingsPage({ refreshKey }: { refreshKey: number }) {
  const { user } = useAuth();
  const { canManageLabels, canManageUsers, canManageTasks } = useRole();
  const { showToast } = useToast();
  const [labels, setLabels] = useState<LabelItem[]>([]);
  const [users, setUsers] = useState<User[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: LabelItem[] }>(
        "/api/labels?include_background=true&enabled_only=false",
      );
      setLabels(data.items || []);
    } catch {
      setLabels([]);
    }
    if (canManageTasks) {
      try {
        const data = await apiGet<{ items: User[] }>("/api/users");
        setUsers(data.items || []);
      } catch {
        setUsers([]);
      }
    }
  }, [canManageTasks]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function createLabel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = {
      name: String(fd.get("name") || "").trim(),
      display_name: String(fd.get("display_name") || "").trim() || undefined,
      color: String(fd.get("color") || "#00e5b0"),
    };
    const labelId = String(fd.get("label_id") || "").trim();
    if (labelId) payload.label_id = Number(labelId);
    try {
      await apiPost("/api/labels", payload);
      event.currentTarget.reset();
      showToast("标签已创建");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "创建失败");
    }
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    try {
      await apiPost("/api/users", {
        username: String(fd.get("username") || "").trim(),
        password: String(fd.get("password") || ""),
        role: String(fd.get("role") || "annotator"),
      });
      event.currentTarget.reset();
      showToast("用户已创建");
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "创建失败");
    }
  }

  return (
    <div className="grid cols-2 settings-grid">
      <section className="panel">
        <h2>标签管理</h2>
        <p className="panel-lead">标签目录供标注台、金标准导入与导出共用。</p>
        {canManageLabels ? (
          <form className="toolbar-row settings-form" onSubmit={createLabel}>
            <label className="field">
              <span>ID（可选）</span>
              <input name="label_id" type="number" min={1} placeholder="自动分配" />
            </label>
            <label className="field">
              <span>英文名 name</span>
              <input name="name" required placeholder="pancreas" />
            </label>
            <label className="field">
              <span>显示名</span>
              <input name="display_name" placeholder="胰腺" />
            </label>
            <label className="field">
              <span>颜色</span>
              <input name="color" type="color" defaultValue="#7dd3fc" />
            </label>
            <button type="submit" className="primary-button">
              新增标签
            </button>
          </form>
        ) : (
          <p className="panel-lead">当前角色仅可查看；管理员可增删改。</p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>name</th>
                <th>显示名</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {labels.map((item) => {
                const disabled = item.enabled === false;
                const isBg = item.label_id === 0;
                return (
                  <tr key={item.label_id} className={disabled ? "row-disabled" : ""}>
                    <td>
                      <span className="swatch" style={{ background: item.color }} /> {item.label_id}
                    </td>
                    <td>{item.name}</td>
                    <td>{item.display_name || item.name}</td>
                    <td>{disabled ? "已禁用" : "启用"}</td>
                    <td className="settings-actions">
                      {canManageLabels && !isBg ? (
                        <>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={async () => {
                              const displayName = window.prompt("显示名", item.display_name || item.name);
                              if (displayName === null) return;
                              const name = window.prompt("英文名 name", item.name);
                              if (name === null) return;
                              const color = window.prompt("颜色", item.color);
                              if (color === null) return;
                              try {
                                await apiPut(`/api/labels/${item.label_id}`, {
                                  display_name: displayName.trim(),
                                  name: name.trim(),
                                  color: color.trim(),
                                });
                                showToast("标签已更新");
                                await load();
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "更新失败");
                              }
                            }}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={async () => {
                              try {
                                await apiPut(`/api/labels/${item.label_id}`, { enabled: disabled });
                                showToast(disabled ? "已启用" : "已禁用");
                                await load();
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "更新失败");
                              }
                            }}
                          >
                            {disabled ? "启用" : "禁用"}
                          </button>
                          <button
                            type="button"
                            className="danger-button"
                            onClick={async () => {
                              if (!window.confirm(`删除标签 #${item.label_id}？`)) return;
                              try {
                                await apiDelete(`/api/labels/${item.label_id}`);
                                showToast("标签已删除");
                                await load();
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "删除失败");
                              }
                            }}
                          >
                            删除
                          </button>
                        </>
                      ) : (
                        <span className="muted">{isBg ? "系统保留" : "只读"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>用户管理</h2>
        <div className="case-meta" style={{ marginBottom: 14 }}>
          <div className="meta-line">
            <span>当前用户</span>
            <strong>{user?.username || "未登录"}</strong>
          </div>
          <div className="meta-line">
            <span>角色</span>
            <strong>{user ? ROLE_TEXT[user.role] || user.role : "-"}</strong>
          </div>
        </div>
        {canManageUsers ? (
          <form className="toolbar-row settings-form" onSubmit={createUser}>
            <label className="field">
              <span>用户名</span>
              <input name="username" required minLength={2} />
            </label>
            <label className="field">
              <span>密码</span>
              <input name="password" type="password" required minLength={6} />
            </label>
            <label className="field">
              <span>角色</span>
              <select name="role" defaultValue="annotator">
                <option value="annotator">标注员</option>
                <option value="reviewer">审核员</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <button type="submit" className="primary-button">
              创建用户
            </button>
          </form>
        ) : (
          <p className="panel-lead">
            {canManageTasks ? "仅管理员可创建/改密/删除。" : "登录后由管理员维护账号。"}
          </p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>用户名</th>
                <th>角色</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.length ? (
                users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.id}</td>
                    <td>{u.username}</td>
                    <td>{ROLE_TEXT[u.role] || u.role}</td>
                    <td>{u.create_time || "-"}</td>
                    <td className="settings-actions">
                      {canManageUsers ? (
                        <>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={async () => {
                              const role = window.prompt("角色 annotator/reviewer/admin", u.role);
                              if (role === null) return;
                              try {
                                await apiPut(`/api/users/${u.id}`, { role: role.trim() });
                                showToast("角色已更新");
                                await load();
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "更新失败");
                              }
                            }}
                          >
                            改角色
                          </button>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={async () => {
                              const password = window.prompt("新密码（至少6位）");
                              if (password === null) return;
                              try {
                                await apiPost(`/api/users/${u.id}/password`, { password });
                                showToast("密码已重置");
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "重置失败");
                              }
                            }}
                          >
                            重置密码
                          </button>
                          <button
                            type="button"
                            className="danger-button"
                            onClick={async () => {
                              if (!window.confirm(`删除用户 ${u.username}？`)) return;
                              try {
                                await apiDelete(`/api/users/${u.id}`);
                                showToast("用户已删除");
                                await load();
                              } catch (error) {
                                showToast(error instanceof Error ? error.message : "删除失败");
                              }
                            }}
                          >
                            删除
                          </button>
                        </>
                      ) : (
                        <span className="muted">只读</span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5}>
                    <div className="placeholder">
                      {user
                        ? canManageTasks
                          ? "暂无用户"
                          : "需要审核员/管理员权限"
                        : "请先登录"}
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
