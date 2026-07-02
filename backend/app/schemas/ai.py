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
    dice: float | None = None
    mask_path: str
    mask: MaskRecord
