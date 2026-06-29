from pydantic import BaseModel

from backend.app.schemas.image import ImageRecord


class CaseRecord(BaseModel):
    case_id: str
    patient_id: str
    modality: str
    create_time: str
    source_group: str = "local"
    status: str = "unannotated"


class CaseListItem(CaseRecord):
    image_count: int = 0
    mask_count: int = 0


class CaseDetailResponse(BaseModel):
    success: bool
    case: CaseRecord
    images: list[ImageRecord]
