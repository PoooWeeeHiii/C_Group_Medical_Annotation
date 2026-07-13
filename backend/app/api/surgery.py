from typing import Annotated, Any

from fastapi import APIRouter, Depends

from backend.app.deps import get_optional_user
from backend.app.schemas.surgery import (
    SaveSurgeryResultRequest,
    SaveSurgeryResultResponse,
    SurgeryResultListResponse,
    SurgeryResultRecord,
)
from backend.app.services.surgery_service import (
    get_surgery_result,
    list_surgery_results,
    save_surgery_result,
)


router = APIRouter(prefix="/api", tags=["surgery"])


@router.post("/surgery_results", response_model=SaveSurgeryResultResponse)
def create_surgery_result(
    request: SaveSurgeryResultRequest,
    user: Annotated[dict[str, Any] | None, Depends(get_optional_user)] = None,
) -> SaveSurgeryResultResponse:
    return save_surgery_result(request, user=user)


@router.get("/case/{case_id}/surgery_results", response_model=SurgeryResultListResponse)
def read_case_surgery_results(case_id: str) -> SurgeryResultListResponse:
    items = list_surgery_results(case_id=case_id)
    return SurgeryResultListResponse(
        success=True,
        case_id=case_id,
        count=len(items),
        items=items,
    )


@router.get("/image/{image_id}/surgery_results", response_model=SurgeryResultListResponse)
def read_image_surgery_results(image_id: str) -> SurgeryResultListResponse:
    items = list_surgery_results(image_id=image_id)
    return SurgeryResultListResponse(
        success=True,
        image_id=image_id,
        count=len(items),
        items=items,
    )


@router.get("/surgery_results/{result_id}", response_model=SurgeryResultRecord)
def read_surgery_result(result_id: str) -> SurgeryResultRecord:
    return get_surgery_result(result_id)
