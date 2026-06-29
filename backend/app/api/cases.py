from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.schemas.case import CaseDetailResponse, CaseListItem
from backend.app.services.case_service import get_case, list_cases


router = APIRouter(prefix="/api", tags=["cases"])


class CaseListResponse(BaseModel):
    success: bool
    items: list[CaseListItem]


@router.get("/cases", response_model=CaseListResponse)
def read_cases() -> CaseListResponse:
    return CaseListResponse(success=True, items=list_cases())


@router.get("/case/{case_id}", response_model=CaseDetailResponse)
def read_case(case_id: str) -> CaseDetailResponse:
    case, images = get_case(case_id)
    return CaseDetailResponse(success=True, case=case, images=images)

