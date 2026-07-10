from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from backend.app.core.config import ensure_project_dirs
from backend.app.schemas.version import SaveVersionRequest, SaveVersionResponse, VersionRecord
from backend.app.services.sqlite_service import get_record, list_records, upsert_record


VALID_VERSIONS = {"v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _case_exists(case_id: str) -> bool:
    return get_record("cases", "case_id", case_id) is not None


def _load_versions() -> list[dict]:
    return list_records("versions")


def _validate_version(version: str) -> str:
    value = version.strip()
    if value not in VALID_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported version: {value}. Use one of {sorted(VALID_VERSIONS)}",
        )
    return value


def save_version(request: SaveVersionRequest) -> SaveVersionResponse:
    ensure_project_dirs()
    if not _case_exists(request.case_id):
        raise HTTPException(status_code=404, detail=f"Case not found: {request.case_id}")

    version = _validate_version(request.version)
    record = {
        "case_id": request.case_id,
        "version": version,
        "annotation": request.annotation,
        "model": request.model,
        "dataset": request.dataset,
        "create_time": _now_iso(),
    }
    upsert_record("versions", record)

    item = VersionRecord(**record)
    return SaveVersionResponse(success=True, version=version, item=item)


def list_versions_for_case(case_id: str) -> list[VersionRecord]:
    if not _case_exists(case_id):
        raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")
    versions = _load_versions()
    return [
        VersionRecord(**item)
        for item in versions
        if item.get("case_id") == case_id
    ]
