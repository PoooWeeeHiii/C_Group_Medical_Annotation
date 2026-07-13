from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend.app.schemas.surgery import (
    SaveSurgeryResultRequest,
    SaveSurgeryResultResponse,
    SurgeryResultRecord,
)
from backend.app.services.sqlite_service import connect, ensure_sqlite_ready, get_record


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def ensure_surgery_schema(connection=None) -> None:
    owns = connection is None
    if owns:
        ensure_sqlite_ready()
        connection = connect()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS surgery_results (
                result_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                image_id TEXT NOT NULL,
                mask_id TEXT,
                label_id INTEGER NOT NULL,
                organ_name TEXT,
                organ_display_name TEXT,
                organ_color TEXT,
                organ_json TEXT,
                roi_margin_pct REAL NOT NULL DEFAULT 18,
                knife_radius INTEGER NOT NULL DEFAULT 2,
                cuboid_min TEXT NOT NULL,
                cuboid_max TEXT NOT NULL,
                cut_planes TEXT NOT NULL DEFAULT '[]',
                carved_voxels INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER,
                username TEXT,
                note TEXT,
                create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                update_time TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_surgery_results_case ON surgery_results(case_id);
            CREATE INDEX IF NOT EXISTS idx_surgery_results_image ON surgery_results(image_id);
            CREATE INDEX IF NOT EXISTS idx_surgery_results_mask ON surgery_results(mask_id);
            CREATE INDEX IF NOT EXISTS idx_surgery_results_label ON surgery_results(label_id);
            """
        )
        # Migrate older tables created before organ columns existed.
        cols = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(surgery_results)").fetchall()
        }
        alter_statements = []
        if "organ_name" not in cols:
            alter_statements.append("ALTER TABLE surgery_results ADD COLUMN organ_name TEXT")
        if "organ_display_name" not in cols:
            alter_statements.append("ALTER TABLE surgery_results ADD COLUMN organ_display_name TEXT")
        if "organ_color" not in cols:
            alter_statements.append("ALTER TABLE surgery_results ADD COLUMN organ_color TEXT")
        if "organ_json" not in cols:
            alter_statements.append("ALTER TABLE surgery_results ADD COLUMN organ_json TEXT")
        for sql in alter_statements:
            connection.execute(sql)
        if owns:
            connection.commit()
    finally:
        if owns:
            connection.close()


def _next_result_id(connection) -> str:
    rows = connection.execute("SELECT result_id FROM surgery_results").fetchall()
    pattern = re.compile(r"^SurgeryResult(\d+)$")
    max_number = 0
    for row in rows:
        match = pattern.match(str(row["result_id"] or ""))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"SurgeryResult{max_number + 1:04d}"


def _as_vec3(values: list[float] | None, field: str) -> list[float]:
    if not isinstance(values, list) or len(values) != 3:
        raise HTTPException(status_code=422, detail=f"{field} must be a length-3 number array")
    try:
        out = [float(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must contain numbers") from exc
    return out


def _normalize_cut_planes(raw_planes: list[Any]) -> list[dict[str, Any]]:
    planes: list[dict[str, Any]] = []
    for index, item in enumerate(raw_planes or []):
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
        origin = _as_vec3(data.get("origin"), f"cut_planes[{index}].origin")
        normal = _as_vec3(data.get("normal"), f"cut_planes[{index}].normal")
        keep = data.get("keepSign", data.get("keep_sign", 1))
        try:
            keep_sign = int(keep if keep is not None else 1)
        except (TypeError, ValueError):
            keep_sign = 1
        if keep_sign not in (-1, 1):
            keep_sign = 1 if keep_sign >= 0 else -1
        polygon_raw = data.get("polygon") or []
        polygon: list[list[float]] = []
        if isinstance(polygon_raw, list):
            for point in polygon_raw:
                if isinstance(point, list) and len(point) >= 3:
                    polygon.append([float(point[0]), float(point[1]), float(point[2])])
        planes.append(
            {
                "origin": origin,
                "normal": normal,
                "keepSign": keep_sign,
                "polygon": polygon,
            }
        )
    return planes


def _resolve_organ_fields(request: SaveSurgeryResultRequest) -> dict[str, Any]:
    organ_raw = request.organ
    organ_data = organ_raw.model_dump() if hasattr(organ_raw, "model_dump") else dict(organ_raw or {})
    label_id = int(request.label_id)
    organ_name = (
        request.organ_name
        or organ_data.get("name")
        or None
    )
    organ_display_name = (
        request.organ_display_name
        or organ_data.get("display_name")
        or organ_name
        or f"label_{label_id}"
    )
    organ_color = request.organ_color or organ_data.get("color") or None

    # Fill missing name/color from label catalog when possible.
    if not organ_name or not organ_color:
        try:
            from backend.app.services.label_service import get_label

            catalog = get_label(label_id)
            if catalog:
                organ_name = organ_name or str(catalog.get("name") or f"label_{label_id}")
                organ_display_name = (
                    request.organ_display_name
                    or organ_data.get("display_name")
                    or str(catalog.get("display_name") or catalog.get("name") or organ_name)
                )
                organ_color = organ_color or str(catalog.get("color") or "#00e5b0")
        except Exception:
            pass

    organ_name = str(organ_name or f"label_{label_id}")
    organ_display_name = str(organ_display_name or organ_name)
    organ_color = str(organ_color or "#00e5b0")
    organ = {
        "label_id": label_id,
        "name": organ_name,
        "display_name": organ_display_name,
        "color": organ_color,
    }
    return {
        "organ_name": organ_name,
        "organ_display_name": organ_display_name,
        "organ_color": organ_color,
        "organ": organ,
    }


def _public(row: dict[str, Any] | Any) -> SurgeryResultRecord:
    data = dict(row)
    organ_json = data.get("organ_json")
    if isinstance(organ_json, str) and organ_json.strip():
        try:
            organ = json.loads(organ_json)
        except json.JSONDecodeError:
            organ = None
    else:
        organ = None
    if not isinstance(organ, dict):
        organ = {
            "label_id": int(data["label_id"]),
            "name": data.get("organ_name"),
            "display_name": data.get("organ_display_name"),
            "color": data.get("organ_color"),
        }
    return SurgeryResultRecord(
        result_id=str(data["result_id"]),
        case_id=str(data["case_id"]),
        image_id=str(data["image_id"]),
        mask_id=str(data["mask_id"]) if data.get("mask_id") else None,
        label_id=int(data["label_id"]),
        organ_name=str(data["organ_name"]) if data.get("organ_name") else None,
        organ_display_name=str(data["organ_display_name"]) if data.get("organ_display_name") else None,
        organ_color=str(data["organ_color"]) if data.get("organ_color") else None,
        organ=organ,
        roi_margin_pct=float(data.get("roi_margin_pct") or 18),
        knife_radius=int(data.get("knife_radius") or 2),
        cuboid_min=json.loads(data["cuboid_min"]) if isinstance(data.get("cuboid_min"), str) else list(data.get("cuboid_min") or []),
        cuboid_max=json.loads(data["cuboid_max"]) if isinstance(data.get("cuboid_max"), str) else list(data.get("cuboid_max") or []),
        cut_planes=json.loads(data["cut_planes"]) if isinstance(data.get("cut_planes"), str) else list(data.get("cut_planes") or []),
        carved_voxels=int(data.get("carved_voxels") or 0),
        user_id=int(data["user_id"]) if data.get("user_id") is not None else None,
        username=str(data["username"]) if data.get("username") else None,
        note=str(data["note"]) if data.get("note") else None,
        create_time=str(data.get("create_time") or ""),
        update_time=str(data["update_time"]) if data.get("update_time") else None,
    )


def save_surgery_result(
    request: SaveSurgeryResultRequest,
    user: dict[str, Any] | None = None,
) -> SaveSurgeryResultResponse:
    ensure_surgery_schema()
    case = get_record("cases", "case_id", request.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case not found: {request.case_id}")
    image = get_record("images", "image_id", request.image_id)
    if image is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {request.image_id}")
    if str(image.get("case_id") or "") != str(request.case_id):
        raise HTTPException(status_code=422, detail="image_id does not belong to case_id")

    if request.mask_id:
        mask = get_record("masks", "mask_id", request.mask_id)
        if mask is None:
            raise HTTPException(status_code=404, detail=f"Mask not found: {request.mask_id}")

    if int(request.label_id) <= 0:
        raise HTTPException(status_code=422, detail="label_id must be a positive organ label")

    cuboid_min = _as_vec3(request.cuboid_min, "cuboid_min")
    cuboid_max = _as_vec3(request.cuboid_max, "cuboid_max")
    for i in range(3):
        if cuboid_max[i] < cuboid_min[i]:
            raise HTTPException(status_code=422, detail="cuboid_max must be >= cuboid_min on each axis")

    cut_planes = _normalize_cut_planes(list(request.cut_planes or []))
    organ_fields = _resolve_organ_fields(request)
    now = _now_iso()
    user_id = int(user["id"]) if user and user.get("id") is not None else None
    username = str(user.get("username") or "") if user else None

    with connect() as connection:
        ensure_surgery_schema(connection)
        result_id = _next_result_id(connection)
        connection.execute(
            """
            INSERT INTO surgery_results (
                result_id, case_id, image_id, mask_id, label_id,
                organ_name, organ_display_name, organ_color, organ_json,
                roi_margin_pct, knife_radius, cuboid_min, cuboid_max,
                cut_planes, carved_voxels, user_id, username, note, create_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                str(request.case_id),
                str(request.image_id),
                str(request.mask_id) if request.mask_id else None,
                int(request.label_id),
                organ_fields["organ_name"],
                organ_fields["organ_display_name"],
                organ_fields["organ_color"],
                json.dumps(organ_fields["organ"], ensure_ascii=False),
                float(request.roi_margin_pct),
                int(request.knife_radius),
                json.dumps(cuboid_min),
                json.dumps(cuboid_max),
                json.dumps(cut_planes),
                max(0, int(request.carved_voxels or 0)),
                user_id,
                username,
                (request.note or "").strip() or None,
                now,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM surgery_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()

    item = _public(row)
    try:
        from backend.app.services.workflow_service import append_audit_log

        append_audit_log(
            action="save_surgery_result",
            user={"id": user_id, "username": username} if user_id is not None else None,
            entity_type="surgery_result",
            entity_id=result_id,
            case_id=request.case_id,
            detail={
                "result_id": result_id,
                "image_id": request.image_id,
                "mask_id": request.mask_id,
                "label_id": request.label_id,
                "organ": organ_fields["organ"],
                "cut_planes": len(cut_planes),
                "carved_voxels": item.carved_voxels,
            },
        )
    except Exception:
        pass

    return SaveSurgeryResultResponse(
        success=True,
        result_id=result_id,
        item=item,
        message=(
            f"手术 ROI 已保存：{result_id}"
            f"（器官={organ_fields['organ_display_name']}，刀痕面 {len(cut_planes)}）"
        ),
    )


def list_surgery_results(
    *,
    case_id: str | None = None,
    image_id: str | None = None,
) -> list[SurgeryResultRecord]:
    ensure_surgery_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if case_id:
        clauses.append("case_id = ?")
        params.append(case_id)
    if image_id:
        clauses.append("image_id = ?")
        params.append(image_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM surgery_results {where} ORDER BY create_time DESC, result_id DESC",
            params,
        ).fetchall()
    return [_public(row) for row in rows]


def get_surgery_result(result_id: str) -> SurgeryResultRecord:
    ensure_surgery_schema()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM surgery_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Surgery result not found: {result_id}")
    return _public(row)
