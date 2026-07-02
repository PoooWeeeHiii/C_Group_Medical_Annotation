from __future__ import annotations

from backend.app.schemas.ai import AIPredictRequest, AIPredictResponse
from backend.app.schemas.mask import SaveMaskRequest
from backend.app.schemas.version import SaveVersionRequest
from backend.app.services.mask_service import save_mask
from backend.app.services.version_service import save_version


def predict_placeholder(request: AIPredictRequest) -> AIPredictResponse:
    model_id = request.model_id or "ModelPlaceholder"
    annotation_id = f"AnnotationAI_{request.image_id}_{model_id}"
    saved_mask = save_mask(
        SaveMaskRequest(
            case_id=request.case_id,
            image_id=request.image_id,
            annotation_id=annotation_id,
            version="v2_ai",
            label=request.label,
            mask_format="nii.gz",
        )
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
        mask_id=saved_mask.mask_id,
        version="v2_ai",
        model_id=model_id,
        dice=None,
        mask_path=saved_mask.path,
        mask=saved_mask.mask,
    )
