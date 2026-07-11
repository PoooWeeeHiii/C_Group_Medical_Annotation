from __future__ import annotations

import sys
from datetime import datetime

from fastapi import HTTPException

from backend.app.core.config import (
    MASKS_DB_PATH,
    PROJECT_ROOT,
    ensure_project_dirs,
)
from backend.app.schemas.ai import AiPredictRequest, AiPredictResponse, AiHealthResponse
from backend.app.schemas.version import SaveVersionRequest
from backend.app.services.file_service import load_json_list, next_entity_id, path_for_api, save_json_list
from backend.app.services.medical_image_service import load_volume
from backend.app.services.version_service import save_version


ROOT = PROJECT_ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_label(label: str) -> str:
    value = "".join(ch if ch.isalnum() else "_" for ch in label.strip().lower()).strip("_")
    return value or "label"


def get_ai_health() -> AiHealthResponse:
    try:
        from ai.config import SPLEEN_MODEL_ID, SPLEEN_NNUNET_PYTHON
        from ai.spleen_nnunet import ensure_spleen_model_ready
    except Exception as exc:  # pragma: no cover
        return AiHealthResponse(
            success=False,
            ready=False,
            message=f"AI module import failed: {exc}",
        )

    try:
        checkpoint = ensure_spleen_model_ready()
        return AiHealthResponse(
            success=True,
            ready=True,
            model_id=SPLEEN_MODEL_ID,
            label="spleen",
            checkpoint=str(checkpoint),
            nnunet_python=str(SPLEEN_NNUNET_PYTHON),
            message="spleen nnUNet checkpoint ready",
        )
    except FileNotFoundError as exc:
        return AiHealthResponse(
            success=True,
            ready=False,
            model_id=SPLEEN_MODEL_ID,
            label="spleen",
            nnunet_python=str(SPLEEN_NNUNET_PYTHON),
            message=str(exc),
        )


def run_ai_predict(request: AiPredictRequest) -> AiPredictResponse:
    ensure_project_dirs()
    label = _normalize_label(request.label)
    if label != "spleen":
        raise HTTPException(
            status_code=400,
            detail=f"Current AI predictor only supports label=spleen, got '{request.label}'",
        )

    image, volume = load_volume(request.image_id)
    if image.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    masks = load_json_list(MASKS_DB_PATH)
    mask_id = next_entity_id("Mask", masks, "mask_id")
    image_path = str(image.get("path") or "")

    try:
        from ai.predict import predict_spleen
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to import AI predictor: {exc}") from exc

    try:
        result = predict_spleen(
            case_id=request.case_id,
            image_id=request.image_id,
            mask_id=mask_id,
            volume=volume.array,
            spacing=volume.spacing,
            image_path=image_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI spleen prediction failed: {exc}") from exc

    mask_path = result["mask_path"]
    absolute_mask = (PROJECT_ROOT / mask_path).resolve()
    if not absolute_mask.exists():
        raise HTTPException(status_code=500, detail=f"Predicted mask was not written: {mask_path}")

    api_path = path_for_api(absolute_mask, PROJECT_ROOT).replace("\\", "/")

    record = {
        "mask_id": mask_id,
        "annotation_id": None,
        "case_id": request.case_id,
        "image_id": request.image_id,
        "path": api_path,
        "version": "v2_ai",
        "label": label,
        "mask_format": "nii.gz",
        "create_time": _now_iso(),
        "model_id": result.get("model_id") or request.model_id or "Model0002",
    }
    masks.append(record)
    save_json_list(MASKS_DB_PATH, masks)

    save_version(
        SaveVersionRequest(
            case_id=request.case_id,
            version="v2_ai",
            annotation=None,
            model=record["model_id"],
            dataset=None,
        )
    )

    return AiPredictResponse(
        success=True,
        annotation_id=None,
        mask_id=mask_id,
        version="v2_ai",
        model_id=record["model_id"],
        label=label,
        dice=result.get("dice"),
        mask_path=api_path.replace("\\", "/"),
        message="spleen ai predict success",
    )
