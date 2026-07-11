"""GET /api/cases and GET /api/case/{case_id}."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import metadata
from ..database import get_db
from ..models import Annotation, Case, Image, Mask
from ..schemas import (
    CaseDetail,
    CaseDetailResponse,
    CaseListItem,
    CaseListResponse,
    ImageBrief,
)

router = APIRouter(prefix="/api", tags=["cases"])


def _mask_count(db: Session, case_id: str) -> int:
    return (
        db.query(Mask)
        .join(Annotation, Mask.annotation_id == Annotation.annotation_id)
        .join(Image, Annotation.image_id == Image.image_id)
        .filter(Image.case_id == case_id)
        .count()
    )


@router.get("/cases", response_model=CaseListResponse)
def list_cases(
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Case)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(Case.case_id.like(like), Case.patient_id.like(like)))

    items = []
    for case in query.order_by(Case.case_id).all():
        case_status = metadata.get_status(case.case_id)
        if status and case_status != status:
            continue
        image_count = db.query(Image).filter(Image.case_id == case.case_id).count()
        items.append(
            CaseListItem(
                case_id=case.case_id,
                patient_id=case.patient_id,
                modality=case.modality,
                create_time=case.create_time,
                image_count=image_count,
                mask_count=_mask_count(db, case.case_id),
                status=case_status,
            )
        )
    return CaseListResponse(items=items)


@router.get("/case/{case_id}", response_model=CaseDetailResponse)
def get_case(case_id: str, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.case_id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")

    images = db.query(Image).filter(Image.case_id == case_id).all()
    return CaseDetailResponse(
        case=CaseDetail(
            case_id=case.case_id,
            patient_id=case.patient_id,
            modality=case.modality,
            create_time=case.create_time,
        ),
        images=[
            ImageBrief(
                image_id=img.image_id,
                path=img.path,
                width=img.width,
                height=img.height,
            )
            for img in images
        ],
    )
