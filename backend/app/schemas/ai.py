from pydantic import BaseModel, Field

from backend.app.schemas.mask import MaskRecord


class AIPredictRequest(BaseModel):
    case_id: str
    image_id: str
    model_id: str | None = None
    label: str = Field(default="label", min_length=1)


class AIPredictResponse(BaseModel):
    success: bool
    annotation_id: str
    mask_id: str
    version: str
    model_id: str | None = None
    label: str | None = None
    dice: float | None = None
    mask_path: str
    mask: MaskRecord
    message: str = "ai predict success"


class AiHealthResponse(BaseModel):
    success: bool
    ready: bool
    model_id: str = "spleen_nnunetv2_task506"
    label: str = "spleen"
    checkpoint: str | None = None
    nnunet_python: str | None = None
    message: str
