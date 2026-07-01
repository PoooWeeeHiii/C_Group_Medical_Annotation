from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException

from backend.app.core.config import (
    IMAGES_DB_PATH,
    LABELS_DATA_DIR,
    MASKS_DB_PATH,
    PROJECT_ROOT,
    ensure_project_dirs,
)
from backend.app.schemas.mask import MaskRecord, SaveMaskRequest, SaveMaskResponse
from backend.app.services.file_service import (
    load_json_list,
    next_entity_id,
    path_for_api,
    save_json_list,
)


VALID_MASK_VERSIONS = {"v1_manual", "v2_ai", "v3_fusion", "final"}
MASK_FORMAT = "nii.gz"


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_label(label: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return value or "label"


def _load_masks() -> list[dict]:
    return load_json_list(MASKS_DB_PATH)


def _image_record(image_id: str) -> dict:
    images = load_json_list(IMAGES_DB_PATH)
    image = next((item for item in images if item.get("image_id") == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_id}")
    return image


def _mask_path(case_id: str, image_id: str, mask_id: str, version: str, label: str) -> str:
    mask_dir = LABELS_DATA_DIR / case_id / version
    mask_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{case_id}_{image_id}_{mask_id}_{version}_{label}.{MASK_FORMAT}"
    return path_for_api(mask_dir / filename, PROJECT_ROOT)


def save_mask(request: SaveMaskRequest) -> SaveMaskResponse:
    ensure_project_dirs()

    version = request.version.strip()
    if version not in VALID_MASK_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mask version: {version}. Use one of {sorted(VALID_MASK_VERSIONS)}",
        )

    mask_format = request.mask_format.strip().lower()
    if mask_format != MASK_FORMAT:
        raise HTTPException(status_code=400, detail="Current platform standard only supports nii.gz masks")

    image = _image_record(request.image_id)
    if image.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    masks = _load_masks()
    mask_id = next_entity_id("Mask", masks, "mask_id")
    label = _normalize_label(request.label)
    mask_path = _mask_path(
        case_id=request.case_id,
        image_id=request.image_id,
        mask_id=mask_id,
        version=version,
        label=label,
    )

    record = {
        "mask_id": mask_id,
        "annotation_id": request.annotation_id,
        "case_id": request.case_id,
        "image_id": request.image_id,
        "path": mask_path,
        "version": version,
        "label": label,
        "mask_format": MASK_FORMAT,
        "create_time": _now_iso(),
    }
    masks.append(record)
    save_json_list(MASKS_DB_PATH, masks)

    mask = MaskRecord(**record)
    return SaveMaskResponse(success=True, mask_id=mask_id, path=mask_path, mask=mask)


def get_mask(mask_id: str) -> MaskRecord:
    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    return MaskRecord(**record)


def list_masks_for_image(image_id: str) -> list[MaskRecord]:
    _image_record(image_id)
    masks = _load_masks()
    return [
        MaskRecord(**mask)
        for mask in masks
        if mask.get("image_id") == image_id or mask.get("image") == image_id
    ]
