from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.services.sqlite_service import connect, ensure_sqlite_ready


VALID_ROLES = {"annotator", "reviewer", "admin", "ai_service"}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _user_public(row: dict[str, Any] | Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": int(data["id"]),
        "username": str(data["username"]),
        "role": str(data["role"]),
        "create_time": str(data.get("create_time") or ""),
    }


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    ensure_sqlite_ready()
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username: str) -> dict[str, Any] | None:
    ensure_sqlite_ready()
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def list_users(include_ai_service: bool = False) -> list[dict[str, Any]]:
    ensure_sqlite_ready()
    with connect() as connection:
        if include_ai_service:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM users WHERE role != 'ai_service' ORDER BY id"
            ).fetchall()
    return [_user_public(row) for row in rows]


def authenticate_user(username: str, password: str) -> dict[str, Any]:
    user = get_user_by_username(username.strip())
    if user is None or not verify_password(password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    public = _user_public(user)
    token = create_access_token(
        {
            "sub": public["id"],
            "username": public["username"],
            "role": public["role"],
        }
    )
    return {"access_token": token, "token_type": "bearer", "user": public}


def create_user(username: str, password: str, role: str) -> dict[str, Any]:
    role = role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
    if get_user_by_username(username.strip()):
        raise HTTPException(status_code=400, detail=f"Username already exists: {username}")
    ensure_sqlite_ready()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, role, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (username.strip(), hash_password(password), role, _now_iso()),
        )
        user_id = int(cursor.lastrowid)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return _user_public(user)
