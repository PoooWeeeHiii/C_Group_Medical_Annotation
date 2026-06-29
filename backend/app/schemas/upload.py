from pydantic import BaseModel


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

