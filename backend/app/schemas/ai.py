from pydantic import BaseModel, Field

from backend.app.schemas.mask import MaskRecord


class AIPredictRequest(BaseModel):
    case_id: str
    image_id: str
    model_id: str | None = None
    label: str = Field(default="label", min_length=1)
    # Default: refuse silent HU-threshold baseline. Opt in only for demos.
    allow_baseline: bool = False


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
    organ_count: int = 1
    organ_labels: list[str] = Field(default_factory=list)
    organ_mask_ids: list[str] = Field(default_factory=list)
    model_status: str = "unknown"
    backend: str | None = None
    fallback_reason: str | None = None


class AiHealthResponse(BaseModel):
    success: bool
    ready: bool
    model_id: str = "spleen_nnunetv2_task506"
    label: str = "spleen"
    checkpoint: str | None = None
    nnunet_python: str | None = None
    message: str
