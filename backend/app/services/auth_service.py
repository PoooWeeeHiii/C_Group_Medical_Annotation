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
    if role == "ai_service":
        raise HTTPException(status_code=400, detail="不可通过管理界面创建 ai_service 账号")
    username = username.strip()
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    if get_user_by_username(username):
        raise HTTPException(status_code=400, detail=f"Username already exists: {username}")
    ensure_sqlite_ready()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, role, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (username, hash_password(password), role, _now_iso()),
        )
        user_id = int(cursor.lastrowid)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return _user_public(user)


def update_user(user_id: int, *, username: str | None = None, role: str | None = None) -> dict[str, Any]:
    ensure_sqlite_ready()
    current = get_user_by_id(int(user_id))
    if current is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {user_id}")
    if str(current.get("role")) == "ai_service":
        raise HTTPException(status_code=400, detail="不可修改 ai_service 账号")

    fields: list[str] = []
    values: list[Any] = []
    if username is not None:
        username = username.strip()
        if len(username) < 2:
            raise HTTPException(status_code=400, detail="用户名至少 2 个字符")
        conflict = get_user_by_username(username)
        if conflict and int(conflict["id"]) != int(user_id):
            raise HTTPException(status_code=400, detail=f"Username already exists: {username}")
        fields.append("username = ?")
        values.append(username)
    if role is not None:
        role = role.strip().lower()
        if role not in VALID_ROLES or role == "ai_service":
            raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
        fields.append("role = ?")
        values.append(role)
    if not fields:
        return _user_public(current)
    values.append(int(user_id))
    with connect() as connection:
        connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    user = get_user_by_id(int(user_id))
    if user is None:
        raise HTTPException(status_code=500, detail="更新用户失败")
    return _user_public(user)


def reset_user_password(user_id: int, password: str) -> dict[str, Any]:
    ensure_sqlite_ready()
    current = get_user_by_id(int(user_id))
    if current is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {user_id}")
    if str(current.get("role")) == "ai_service":
        raise HTTPException(status_code=400, detail="不可修改 ai_service 账号")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 个字符")
    with connect() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), int(user_id)),
        )
    return _user_public(current)


def delete_user(user_id: int, *, actor_id: int | None = None) -> dict[str, Any]:
    ensure_sqlite_ready()
    current = get_user_by_id(int(user_id))
    if current is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: {user_id}")
    if actor_id is not None and int(actor_id) == int(user_id):
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if str(current.get("role")) == "ai_service":
        raise HTTPException(status_code=400, detail="不可删除 ai_service 账号")
    if str(current.get("username")) == "admin" and str(current.get("role")) == "admin":
        # Keep at least one seeded admin unless there are other admins.
        with connect() as connection:
            admin_count = int(
                connection.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'").fetchone()["c"]
            )
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除唯一的管理员账号")
    public = _user_public(current)
    with connect() as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
    return public
