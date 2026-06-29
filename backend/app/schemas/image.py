from pydantic import BaseModel


class ImageRecord(BaseModel):
    image_id: str
    case_id: str
    path: str
    width: int = 0
    height: int = 0
    filename: str
    file_format: str
    slice_count: int | None = None


class ImageDetailResponse(BaseModel):
    success: bool
    image: ImageRecord

