from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend.app.services.auth_service import get_user_by_id
from backend.app.services.sqlite_service import connect, ensure_sqlite_ready, get_record
from backend.app.services.workflow_service import append_audit_log


VALID_TASK_STATUSES = {"open", "in_progress", "submitted", "approved", "rejected", "cancelled"}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _task_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    assignee = get_user_by_id(int(data["assignee_id"])) if data.get("assignee_id") is not None else None
    assigner = get_user_by_id(int(data["assigner_id"])) if data.get("assigner_id") is not None else None
    return {
        "task_id": data["task_id"],
        "case_id": data["case_id"],
        "assignee_id": int(data["assignee_id"]),
        "assignee_username": assignee["username"] if assignee else None,
        "assignee_role": assignee["role"] if assignee else None,
        "assigner_id": int(data["assigner_id"]) if data.get("assigner_id") is not None else None,
        "assigner_username": assigner["username"] if assigner else None,
        "deadline": data.get("deadline"),
        "status": data.get("status") or "open",
        "note": data.get("note"),
        "create_time": data.get("create_time"),
        "update_time": data.get("update_time"),
    }


def create_task(
    *,
    case_id: str,
    assignee_id: int,
    assigner: dict[str, Any],
    deadline: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    role = str(assigner.get("role") or "")
    if role not in {"admin", "reviewer"}:
        raise HTTPException(status_code=403, detail="Only admin or reviewer can create tasks")
    if get_record("cases", "case_id", case_id) is None:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
    assignee = get_user_by_id(assignee_id)
    if assignee is None:
        raise HTTPException(status_code=404, detail=f"Assignee not found: {assignee_id}")
    if str(assignee.get("role")) not in {"annotator", "reviewer", "admin"}:
        raise HTTPException(status_code=400, detail="Assignee role is invalid")

    task_id = _next_task_id()
    ensure_sqlite_ready()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, case_id, assignee_id, assigner_id, deadline, status, note, create_time, update_time
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                task_id,
                case_id,
                int(assignee_id),
                int(assigner["id"]),
                deadline,
                note,
                _now_iso(),
                _now_iso(),
            ),
        )
    task = get_task(task_id)
    append_audit_log(
        action="create_task",
        user=assigner,
        entity_type="task",
        entity_id=task_id,
        case_id=case_id,
        detail={"assignee_id": assignee_id, "deadline": deadline, "note": note},
    )
    return task


def _next_task_id() -> str:
    ensure_sqlite_ready()
    with connect() as connection:
        rows = connection.execute("SELECT task_id FROM tasks").fetchall()
    import re

    pattern = re.compile(r"^Task(\d+)$")
    max_number = 0
    for row in rows:
        match = pattern.match(str(row["task_id"] or ""))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"Task{max_number + 1:04d}"


def get_task(task_id: str) -> dict[str, Any]:
    ensure_sqlite_ready()
    with connect() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return _task_row_to_dict(row)


def list_tasks(
    *,
    case_id: str | None = None,
    assignee_id: int | None = None,
    status: str | None = None,
    current_user: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ensure_sqlite_ready()
    clauses: list[str] = []
    params: list[Any] = []
    if case_id:
        clauses.append("case_id = ?")
        params.append(case_id)
    if assignee_id is not None:
        clauses.append("assignee_id = ?")
        params.append(int(assignee_id))
    if status:
        clauses.append("status = ?")
        params.append(status)
    # Annotators only see their own tasks unless admin/reviewer.
    if current_user and str(current_user.get("role")) == "annotator":
        clauses.append("assignee_id = ?")
        params.append(int(current_user["id"]))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM tasks {where} ORDER BY create_time DESC, task_id DESC",
            params,
        ).fetchall()
    return [_task_row_to_dict(row) for row in rows]


def update_task(
    task_id: str,
    *,
    current_user: dict[str, Any],
    status: str | None = None,
    assignee_id: int | None = None,
    deadline: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    task = get_task(task_id)
    role = str(current_user.get("role") or "")
    if role == "annotator" and int(task["assignee_id"]) != int(current_user["id"]):
        raise HTTPException(status_code=403, detail="Annotators can only update their own tasks")
    if role not in {"annotator", "reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient role to update task")

    next_status = status.strip().lower() if status else None
    if next_status and next_status not in VALID_TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported task status: {status}")
    if next_status in {"approved", "rejected", "cancelled"} and role == "annotator":
        raise HTTPException(status_code=403, detail="Annotators cannot approve/reject/cancel tasks")
    if assignee_id is not None:
        if role not in {"admin", "reviewer"}:
            raise HTTPException(status_code=403, detail="Only admin or reviewer can reassign tasks")
        if get_user_by_id(assignee_id) is None:
            raise HTTPException(status_code=404, detail=f"Assignee not found: {assignee_id}")

    ensure_sqlite_ready()
    with connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status = COALESCE(?, status),
                assignee_id = COALESCE(?, assignee_id),
                deadline = COALESCE(?, deadline),
                note = COALESCE(?, note),
                update_time = ?
            WHERE task_id = ?
            """,
            (
                next_status,
                int(assignee_id) if assignee_id is not None else None,
                deadline,
                note,
                _now_iso(),
                task_id,
            ),
        )
    updated = get_task(task_id)
    append_audit_log(
        action="update_task",
        user=current_user,
        entity_type="task",
        entity_id=task_id,
        case_id=updated["case_id"],
        detail={"status": next_status, "assignee_id": assignee_id, "deadline": deadline, "note": note},
    )
    return updated
