from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    success: bool
    case_id: str
    image_id: str
    patient_id: str
    modality: str
    path: str
    width: int
    height: int
    message: str
    attached_masks: list[dict] = Field(default_factory=list)
    attached_mask_ids: list[str] = Field(default_factory=list)
    attached_mask_count: int = 0
