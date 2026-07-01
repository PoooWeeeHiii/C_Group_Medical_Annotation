from pydantic import BaseModel, Field


class MaskRecord(BaseModel):
    mask_id: str
    annotation_id: str | None = None
    case_id: str | None = None
    image_id: str | None = None
    path: str
    version: str = "v1_manual"
    label: str = "label"
    mask_format: str = "nii.gz"
    create_time: str | None = None


class SaveMaskRequest(BaseModel):
    case_id: str
    image_id: str
    annotation_id: str | None = None
    version: str = "v1_manual"
    label: str = Field(default="label", min_length=1)
    mask_format: str = "nii.gz"


class SaveMaskResponse(BaseModel):
    success: bool
    mask_id: str
    path: str
    mask: MaskRecord


class MaskDetailResponse(BaseModel):
    success: bool
    mask: MaskRecord


class MaskListResponse(BaseModel):
    success: bool
    image_id: str
    count: int
    items: list[MaskRecord]
    masks: list[MaskRecord]
