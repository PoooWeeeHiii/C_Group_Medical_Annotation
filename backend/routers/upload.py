"""POST /api/upload — import a CT/medical image and register Case + Image."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import imaging, metadata
from ..config import RAW_DIR, DEFAULT_CASE_STATUS, stored_rel
from ..database import get_db
from ..ids import next_id
from ..models import Case, Image
from ..schemas import UploadResponse

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    source_group: Optional[str] = Form(None),
    patient_id: Optional[str] = Form(None),
    modality: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="empty upload")

    case_id = next_id(db, Case.case_id, "Case")
    image_id = next_id(db, Image.image_id, "Image")

    image_dir = RAW_DIR / case_id / "image"
    try:
        stored = imaging.store_upload(raw_bytes, file.filename or "upload", image_dir)
        width, height, slice_count = imaging.get_dimensions(stored)
    except Exception as exc:  # noqa: BLE001 — surface a clean 400 to the client
        raise HTTPException(status_code=400, detail=f"failed to read image: {exc}")

    rel_path = stored_rel(stored)
    modality = modality or "CT"

    case = Case(
        case_id=case_id,
        patient_id=patient_id,
        modality=modality,
        create_time=datetime.now(timezone.utc),
    )
    image = Image(
        image_id=image_id,
        case_id=case_id,
        path=rel_path,
        width=width,
        height=height,
    )
    db.add(case)
    db.add(image)
    db.commit()

    metadata.write_metadata(
        case_id,
        {
            "case_id": case_id,
            "patient_id": patient_id,
            "modality": modality,
            "source_group": source_group,
            "annotation_status": DEFAULT_CASE_STATUS,
            "created_time": case.create_time.isoformat(),
            "images": [
                {
                    "image_id": image_id,
                    "path": rel_path,
                    "width": width,
                    "height": height,
                    "slice_count": slice_count,
                }
            ],
        },
    )

    return UploadResponse(
        case_id=case_id,
        image_id=image_id,
        patient_id=patient_id,
        modality=modality,
        path=stored_rel(image_dir) + "/",
        width=width,
        height=height,
    )
