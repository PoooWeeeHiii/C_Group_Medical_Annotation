from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend.app.services.sqlite_service import connect, ensure_sqlite_ready


DEFAULT_LABELS: list[dict[str, Any]] = [
    {"label_id": 0, "name": "background", "display_name": "背景", "color": "#1c2938", "sort_order": 0},
    {"label_id": 1, "name": "liver", "display_name": "肝", "color": "#00e5b0", "sort_order": 2},
    {"label_id": 2, "name": "kidney", "display_name": "肾", "color": "#38a3ff", "sort_order": 5},
    {"label_id": 3, "name": "lung", "display_name": "肺", "color": "#ffb020", "sort_order": 4},
    {"label_id": 4, "name": "tumor", "display_name": "肿瘤", "color": "#ff4d4f", "sort_order": 7},
    {"label_id": 5, "name": "spleen", "display_name": "脾", "color": "#b66dff", "sort_order": 3},
    {"label_id": 6, "name": "heart", "display_name": "心", "color": "#ff6b8a", "sort_order": 1},
    {"label_id": 7, "name": "bone", "display_name": "骨", "color": "#e2e8f0", "sort_order": 6},
    {"label_id": 8, "name": "other", "display_name": "其他", "color": "#94a3b8", "sort_order": 8},
]


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _public(row: dict[str, Any] | Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "label_id": int(data["label_id"]),
        "name": str(data["name"]),
        "display_name": str(data.get("display_name") or data["name"]),
        "color": str(data.get("color") or "#00e5b0"),
        "sort_order": int(data.get("sort_order") or 0),
        "enabled": bool(int(data.get("enabled") if data.get("enabled") is not None else 1)),
        "create_time": str(data.get("create_time") or ""),
        "update_time": str(data.get("update_time") or ""),
    }


def ensure_label_schema(connection=None) -> None:
    owns = connection is None
    if owns:
        ensure_sqlite_ready()
        connection = connect()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS labels (
                label_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#00e5b0',
                sort_order INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                update_time TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_labels_enabled ON labels(enabled);
            CREATE INDEX IF NOT EXISTS idx_labels_sort ON labels(sort_order, label_id);
            """
        )
        count = int(connection.execute("SELECT COUNT(*) AS c FROM labels").fetchone()["c"])
        if count == 0:
            now = _now_iso()
            for item in DEFAULT_LABELS:
                connection.execute(
                    """
                    INSERT INTO labels (label_id, name, display_name, color, sort_order, enabled, create_time)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        int(item["label_id"]),
                        str(item["name"]),
                        str(item["display_name"]),
                        str(item["color"]),
                        int(item["sort_order"]),
                        now,
                    ),
                )
        else:
            _sync_builtin_labels(connection)
        if owns:
            connection.commit()
    finally:
        if owns:
            connection.close()


def _sync_builtin_labels(connection) -> None:
    """补齐内置类别并刷新显示名/颜色/排序，不改已有 name→id 映射。"""
    now = _now_iso()
    existing_rows = connection.execute("SELECT * FROM labels").fetchall()
    by_name = {str(row["name"]): dict(row) for row in existing_rows}
    used_ids = {int(row["label_id"]) for row in existing_rows}
    next_id = (max(used_ids) + 1) if used_ids else 1

    for item in DEFAULT_LABELS:
        name = str(item["name"])
        row = by_name.get(name)
        if row:
            connection.execute(
                """
                UPDATE labels
                SET display_name = ?, color = ?, sort_order = ?, update_time = ?
                WHERE name = ?
                """,
                (
                    str(item["display_name"]),
                    str(item["color"]),
                    int(item["sort_order"]),
                    now,
                    name,
                ),
            )
            continue
        preferred = int(item["label_id"])
        label_id = preferred if preferred not in used_ids else next_id
        if label_id == next_id:
            next_id += 1
        used_ids.add(label_id)
        connection.execute(
            """
            INSERT INTO labels (label_id, name, display_name, color, sort_order, enabled, create_time)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (
                label_id,
                name,
                str(item["display_name"]),
                str(item["color"]),
                int(item["sort_order"]),
                now,
            ),
        )


def list_labels(*, enabled_only: bool = False, include_background: bool = True) -> list[dict[str, Any]]:
    ensure_sqlite_ready()
    ensure_label_schema()
    with connect() as connection:
        sql = "SELECT * FROM labels"
        clauses: list[str] = []
        if enabled_only:
            clauses.append("enabled = 1")
        if not include_background:
            clauses.append("label_id > 0")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY sort_order ASC, label_id ASC"
        rows = connection.execute(sql).fetchall()
    return [_public(row) for row in rows]


def get_label(label_id: int) -> dict[str, Any] | None:
    ensure_sqlite_ready()
    ensure_label_schema()
    with connect() as connection:
        row = connection.execute("SELECT * FROM labels WHERE label_id = ?", (int(label_id),)).fetchone()
    return _public(row) if row else None


def _validate_name(name: str) -> str:
    cleaned = str(name or "").strip().lower().replace(" ", "_")
    if not cleaned or not cleaned.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="标签 name 须为字母/数字/下划线")
    return cleaned


def _validate_color(color: str) -> str:
    value = str(color or "").strip()
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) not in (4, 7):
        raise HTTPException(status_code=400, detail="颜色须为 #RGB 或 #RRGGBB")
    try:
        int(value[1:], 16)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="颜色格式无效") from exc
    return value.lower() if len(value) == 7 else value


def create_label(
    *,
    label_id: int | None = None,
    name: str,
    display_name: str | None = None,
    color: str = "#00e5b0",
    sort_order: int | None = None,
) -> dict[str, Any]:
    ensure_sqlite_ready()
    ensure_label_schema()
    name = _validate_name(name)
    display = str(display_name or name).strip() or name
    color = _validate_color(color)
    with connect() as connection:
        if label_id is None:
            row = connection.execute("SELECT COALESCE(MAX(label_id), 0) + 1 AS next_id FROM labels").fetchone()
            label_id = int(row["next_id"])
            if label_id < 1:
                label_id = 1
        else:
            label_id = int(label_id)
            if label_id < 1:
                raise HTTPException(status_code=400, detail="label_id 须 >= 1（0 为背景保留）")
            existing = connection.execute("SELECT label_id FROM labels WHERE label_id = ?", (label_id,)).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail=f"label_id 已存在: {label_id}")
        conflict = connection.execute("SELECT label_id FROM labels WHERE name = ?", (name,)).fetchone()
        if conflict:
            raise HTTPException(status_code=400, detail=f"标签名已存在: {name}")
        if sort_order is None:
            sort_order = label_id
        now = _now_iso()
        connection.execute(
            """
            INSERT INTO labels (label_id, name, display_name, color, sort_order, enabled, create_time)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (label_id, name, display, color, int(sort_order), now),
        )
        connection.commit()
    item = get_label(label_id)
    if item is None:
        raise HTTPException(status_code=500, detail="创建标签失败")
    return item


def update_label(
    label_id: int,
    *,
    name: str | None = None,
    display_name: str | None = None,
    color: str | None = None,
    sort_order: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    ensure_sqlite_ready()
    ensure_label_schema()
    label_id = int(label_id)
    current = get_label(label_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"标签不存在: {label_id}")
    if label_id == 0 and enabled is False:
        raise HTTPException(status_code=400, detail="背景标签不可禁用")

    fields: list[str] = []
    values: list[Any] = []
    if name is not None:
        name = _validate_name(name)
        with connect() as connection:
            conflict = connection.execute(
                "SELECT label_id FROM labels WHERE name = ? AND label_id != ?",
                (name, label_id),
            ).fetchone()
        if conflict:
            raise HTTPException(status_code=400, detail=f"标签名已存在: {name}")
        fields.append("name = ?")
        values.append(name)
    if display_name is not None:
        fields.append("display_name = ?")
        values.append(str(display_name).strip() or current["display_name"])
    if color is not None:
        fields.append("color = ?")
        values.append(_validate_color(color))
    if sort_order is not None:
        fields.append("sort_order = ?")
        values.append(int(sort_order))
    if enabled is not None:
        fields.append("enabled = ?")
        values.append(1 if enabled else 0)
    if not fields:
        return current
    fields.append("update_time = ?")
    values.append(_now_iso())
    values.append(label_id)
    with connect() as connection:
        connection.execute(f"UPDATE labels SET {', '.join(fields)} WHERE label_id = ?", values)
        connection.commit()
    item = get_label(label_id)
    if item is None:
        raise HTTPException(status_code=500, detail="更新标签失败")
    return item


def delete_label(label_id: int, *, hard: bool = False) -> dict[str, Any]:
    label_id = int(label_id)
    if label_id == 0:
        raise HTTPException(status_code=400, detail="背景标签不可删除")
    current = get_label(label_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"标签不存在: {label_id}")
    if hard:
        with connect() as connection:
            connection.execute("DELETE FROM labels WHERE label_id = ?", (label_id,))
            connection.commit()
        return {**current, "deleted": True, "hard": True}
    return update_label(label_id, enabled=False)


def label_name_to_id_map() -> dict[str, int]:
    """Merge DB catalog with historical aliases for gold/RTSTRUCT import."""
    mapping = {
        "background": 0,
        "kidney_left": 2,
        "kidney_right": 2,
        "pancreas": 6,
        "stomach": 7,
        "gallbladder": 8,
    }
    for item in list_labels(enabled_only=False, include_background=True):
        mapping[str(item["name"]).lower()] = int(item["label_id"])
        display = str(item.get("display_name") or "").strip().lower()
        if display:
            mapping[display] = int(item["label_id"])
    return mapping
