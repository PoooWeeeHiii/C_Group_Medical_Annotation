from fastapi import APIRouter, File, Form, UploadFile

from backend.app.schemas.upload import UploadResponse
from backend.app.services.case_service import create_case_from_upload


router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload_case(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    source_group: str = Form("local"),
    patient_id: str | None = Form(None),
    modality: str | None = Form(None),
) -> UploadResponse:
    uploads: list[UploadFile] = []
    if files:
        uploads.extend([item for item in files if item is not None and getattr(item, "filename", None)])
    if file is not None and getattr(file, "filename", None):
        uploads.append(file)
    # Deduplicate by object identity while preserving order
    seen: set[int] = set()
    unique: list[UploadFile] = []
    for item in uploads:
        key = id(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return await create_case_from_upload(
        files=unique,
        source_group=source_group,
        patient_id=patient_id,
        modality=modality,
    )

