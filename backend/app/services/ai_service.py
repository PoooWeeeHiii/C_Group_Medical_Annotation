from __future__ import annotations

import re

import numpy as np
from fastapi import HTTPException

from ai.predict import predict_mask_array
from backend.app.schemas.ai import AIPredictRequest, AIPredictResponse
from backend.app.schemas.version import SaveVersionRequest
from backend.app.services.mask_service import _append_3d_mask_record
from backend.app.services.medical_image_service import load_volume
from backend.app.services.sqlite_service import upsert_record
from backend.app.services.version_service import save_version


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return normalized or "model"


def run_ai_prediction(request: AIPredictRequest) -> AIPredictResponse:
    model_id = request.model_id or "builtin_ct_threshold"
    image_record, volume = load_volume(request.image_id)
    if image_record.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    try:
        mask_stack = predict_mask_array(volume.array, label=request.label, model_id=model_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI inference failed: {exc}") from exc

    mask_stack = (np.asarray(mask_stack) > 0).astype(np.uint8)
    if mask_stack.shape != volume.array.shape[:3]:
        raise HTTPException(
            status_code=500,
            detail=f"AI mask shape mismatch: mask={mask_stack.shape}, image={volume.array.shape[:3]}",
        )
    if not np.any(mask_stack):
        raise HTTPException(status_code=422, detail="AI inference produced an empty mask")

    annotation_id = f"AnnotationAI_{request.image_id}_{_safe_id(model_id)}"
    upsert_record(
        "models",
        {
            "model_id": model_id,
            "version": model_id,
            "dice": None,
            "path": None,
            "metrics_json": None,
        },
    )

    mask, mask_path = _append_3d_mask_record(
        masks=[],
        request_case_id=request.case_id,
        image_id=request.image_id,
        version="v2_ai",
        label=request.label,
        encoding=f"ai_inference:{model_id}",
        source_mask_ids=[],
        mask_stack=mask_stack,
        volume=volume,
        annotation_id=annotation_id,
    )
    save_version(
        SaveVersionRequest(
            case_id=request.case_id,
            version="v2_ai",
            annotation=annotation_id,
            model=model_id,
            dataset=None,
        )
    )

    return AIPredictResponse(
        success=True,
        annotation_id=annotation_id,
        mask_id=mask.mask_id,
        version="v2_ai",
        model_id=model_id,
        dice=None,
        mask_path=mask_path,
        mask=mask,
    )
