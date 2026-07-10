from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend.app.services.sqlite_service import connect, ensure_sqlite_ready, get_record, next_sqlite_entity_id


CASE_STATUSES = {"unannotated", "annotated", "pending", "reviewed", "final"}

CASE_TRANSITIONS = {
    "unannotated": {"annotated"},
    "annotated": {"pending", "annotated"},
    "pending": {"reviewed", "annotated", "final"},
    "reviewed": {"final", "annotated", "pending"},
    "final": {"annotated"},
}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def append_audit_log(
    *,
    action: str,
    user: dict[str, Any] | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    case_id: str | None = None,
    detail: dict[str, Any] | str | None = None,
) -> None:
    ensure_sqlite_ready()
    detail_text = detail if isinstance(detail, str) or detail is None else json.dumps(detail, ensure_ascii=False)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO audit_logs (user_id, username, action, entity_type, entity_id, case_id, detail, create_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user["id"]) if user and user.get("id") is not None else None,
                str(user["username"]) if user and user.get("username") else None,
                action,
                entity_type,
                entity_id,
                case_id,
                detail_text,
                _now_iso(),
            ),
        )


def list_audit_logs(case_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    ensure_sqlite_ready()
    limit = max(1, min(int(limit), 500))
    with connect() as connection:
        if case_id:
            rows = connection.execute(
                """
                SELECT * FROM audit_logs
                WHERE case_id = ?
                ORDER BY log_id DESC
                LIMIT ?
                """,
                (case_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM audit_logs
                ORDER BY log_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_case_record(case_id: str) -> dict[str, Any]:
    case = get_record("cases", "case_id", case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
    return case


def set_case_status(
    case_id: str,
    new_status: str,
    *,
    user: dict[str, Any] | None = None,
    action: str,
    detail: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if new_status not in CASE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported case status: {new_status}")
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if not force and new_status != current and new_status not in CASE_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: {current} -> {new_status}",
        )
    updated = {**case, "status": new_status}
    ensure_sqlite_ready()
    with connect() as connection:
        connection.execute(
            "UPDATE cases SET status = ? WHERE case_id = ?",
            (new_status, case_id),
        )
    append_audit_log(
        action=action,
        user=user,
        entity_type="case",
        entity_id=case_id,
        case_id=case_id,
        detail={"from": current, "to": new_status, **(detail or {})},
    )
    return updated


def mark_case_annotated(case_id: str, user: dict[str, Any] | None = None, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if current in {"pending", "reviewed", "final"}:
        # Keep review pipeline status; still audit the save.
        append_audit_log(
            action="save_mask",
            user=user,
            entity_type="case",
            entity_id=case_id,
            case_id=case_id,
            detail={"status_kept": current, **(detail or {})},
        )
        return case
    return set_case_status(
        case_id,
        "annotated",
        user=user,
        action="save_mask",
        detail=detail,
        force=current == "annotated",
    )


def submit_case(case_id: str, user: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    role = str(user.get("role") or "")
    if role not in {"annotator", "admin"}:
        raise HTTPException(status_code=403, detail="Only annotator or admin can submit a case")
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if current not in {"annotated", "reviewed"}:
        raise HTTPException(status_code=400, detail=f"Case status must be annotated before submit, got {current}")
    updated = set_case_status(case_id, "pending", user=user, action="submit", detail={"note": note})
    _sync_tasks_for_case(case_id, "submitted", user=user, note=note)
    return updated


def approve_case(case_id: str, user: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    role = str(user.get("role") or "")
    if role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Only reviewer or admin can approve a case")
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if current != "pending":
        raise HTTPException(status_code=400, detail=f"Case status must be pending before approve, got {current}")
    updated = set_case_status(case_id, "reviewed", user=user, action="approve", detail={"note": note})
    _sync_tasks_for_case(case_id, "approved", user=user, note=note)
    return updated


def reject_case(case_id: str, user: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    role = str(user.get("role") or "")
    if role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Only reviewer or admin can reject a case")
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if current not in {"pending", "reviewed", "final"}:
        raise HTTPException(status_code=400, detail=f"Case status cannot be rejected from {current}")
    updated = set_case_status(
        case_id,
        "annotated",
        user=user,
        action="reject",
        detail={"note": note or "rejected"},
        force=True,
    )
    _sync_tasks_for_case(case_id, "rejected", user=user, note=note)
    return updated


def finalize_case(case_id: str, user: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    role = str(user.get("role") or "")
    if role not in {"reviewer", "admin"}:
        raise HTTPException(status_code=403, detail="Only reviewer or admin can confirm final")
    case = get_case_record(case_id)
    current = str(case.get("status") or "unannotated")
    if current not in {"reviewed", "pending"}:
        raise HTTPException(status_code=400, detail=f"Case status must be reviewed (or pending) before final, got {current}")
    return set_case_status(case_id, "final", user=user, action="finalize", detail=detail)


def _sync_tasks_for_case(case_id: str, status: str, user: dict[str, Any] | None = None, note: str | None = None) -> None:
    ensure_sqlite_ready()
    with connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status = ?, note = COALESCE(?, note), update_time = ?
            WHERE case_id = ? AND status IN ('open', 'in_progress', 'submitted')
            """,
            (status, note, _now_iso(), case_id),
        )
    append_audit_log(
        action="task_sync",
        user=user,
        entity_type="case",
        entity_id=case_id,
        case_id=case_id,
        detail={"task_status": status, "note": note},
    )
