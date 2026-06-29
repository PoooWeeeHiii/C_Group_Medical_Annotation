from fastapi import APIRouter, File, Form, UploadFile

from backend.app.schemas.upload import UploadResponse
from backend.app.services.case_service import create_case_from_upload


router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_case(
    file: UploadFile = File(...),
    source_group: str = Form("local"),
    patient_id: str | None = Form(None),
    modality: str | None = Form(None),
) -> UploadResponse:
    return await create_case_from_upload(
        file=file,
        source_group=source_group,
        patient_id=patient_id,
        modality=modality,
    )

