import { FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet, apiPost, apiUploadForm } from "../api/client";
import { useRole } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import type { CaseItem, TaskItem, User } from "../types";
import { ROLE_TEXT, STATUS_TEXT } from "../types";

export function CasesPage({ refreshKey }: { refreshKey: number }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { canManageTasks } = useRole();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ items: CaseItem[] }>("/api/cases");
      setCases(data.items || []);
    } catch {
      setCases([]);
    }
    try {
      const data = await apiGet<{ items: TaskItem[] }>("/api/tasks");
      setTasks(data.items || []);
    } catch {
      setTasks([]);
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

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fileInput = form.elements.namedItem("files") as HTMLInputElement;
    const files = fileInput.files;
    if (!files?.length) {
      showToast("请选择文件");
      return;
    }
    setUploading(true);
    try {
      const body = new FormData();
      Array.from(files).forEach((file) => body.append("files", file));
      const result = await apiUploadForm<{ case_id?: string; message?: string }>("/api/upload", body);
      showToast(result.message || `已上传病例 ${result.case_id || ""}`);
      form.reset();
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function onAssign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fd = new FormData(event.currentTarget);
    try {
      await apiPost("/api/tasks", {
        case_id: String(fd.get("case_id") || ""),
        assignee_id: Number(fd.get("assignee_id")),
        deadline: String(fd.get("deadline") || "") || undefined,
        note: String(fd.get("note") || "") || undefined,
      });
      showToast("任务已分配");
      event.currentTarget.reset();
      await load();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "分配失败");
    }
  }

  return (
    <section className="panel">
      <h2>导入 CT 病例</h2>
      <p className="panel-lead">
        支持 DICOM（.dcm）、NIfTI、NRRD、ZIP；可附带金标准 label / SEG / RTSTRUCT。
      </p>
      <form className="upload-form" onSubmit={onUpload}>
        <label className="field">
          <span>选择文件</span>
          <input name="files" type="file" multiple accept=".dcm,.nii,.nii.gz,.nrrd,.zip,.png,.jpg,.jpeg" />
        </label>
        <button className="primary-button" type="submit" disabled={uploading}>
          {uploading ? "上传中…" : "上传导入"}
        </button>
      </form>

      <h2 style={{ marginTop: 24 }}>病例列表</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Case ID</th>
              <th>Patient</th>
              <th>模态</th>
              <th>图像数</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {cases.length ? (
              cases.map((item) => (
                <tr key={item.case_id}>
                  <td>
                    <strong>{item.case_id}</strong>
                  </td>
                  <td>{item.patient_id || "-"}</td>
                  <td>{item.modality || "-"}</td>
                  <td>{item.image_count ?? "-"}</td>
                  <td>
                    <span className="status-badge">
                      {STATUS_TEXT[item.status || ""] || item.status || "未标注"}
                    </span>
                  </td>
                  <td>
                    <button
                      className="ghost-button"
                      type="button"
                      onClick={() => navigate(`/annotation/${item.case_id}`)}
                    >
                      进入标注
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6}>
                  <div className="placeholder">暂无病例。请先上传文件。</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2 style={{ marginTop: 24 }}>任务分配</h2>
      {canManageTasks ? (
        <form id="taskForm" className="toolbar-row" onSubmit={onAssign} style={{ marginBottom: 14 }}>
          <label className="field">
            <span>病例</span>
            <select name="case_id" required>
              <option value="">选择病例</option>
              {cases.map((item) => (
                <option key={item.case_id} value={item.case_id}>
                  {item.case_id} · {STATUS_TEXT[item.status || ""] || item.status}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>标注员</span>
            <select name="assignee_id" required>
              <option value="">选择用户</option>
              {users
                .filter((u) => u.role === "annotator" || u.role === "admin")
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}（{ROLE_TEXT[u.role] || u.role}）
                  </option>
                ))}
            </select>
          </label>
          <label className="field">
            <span>截止日期</span>
            <input name="deadline" type="date" />
          </label>
          <label className="field">
            <span>备注</span>
            <input name="note" placeholder="可选" />
          </label>
          <button className="primary-button" type="submit">
            分配任务
          </button>
        </form>
      ) : (
        <p className="panel-lead">审核员/管理员可分配任务。</p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>病例</th>
              <th>负责人</th>
              <th>状态</th>
              <th>截止</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {tasks.length ? (
              tasks.map((task) => (
                <tr key={task.task_id}>
                  <td>
                    <strong>{task.task_id}</strong>
                  </td>
                  <td>{task.case_id}</td>
                  <td>{task.assignee_username || task.assignee_id}</td>
                  <td>{task.status}</td>
                  <td>{task.deadline || "-"}</td>
                  <td>{task.note || "-"}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6}>
                  <div className="placeholder">暂无任务。</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
