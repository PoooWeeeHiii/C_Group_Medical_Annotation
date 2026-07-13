from fastapi import APIRouter

from backend.app.schemas.version import (
    SaveVersionRequest,
    SaveVersionResponse,
    VersionListResponse,
)
from backend.app.services.version_service import list_versions_for_case, save_version


router = APIRouter(prefix="/api", tags=["versions"])


@router.post("/version", response_model=SaveVersionResponse)
def save_case_version(request: SaveVersionRequest) -> SaveVersionResponse:
    return save_version(request)


@router.get("/case/{case_id}/versions", response_model=VersionListResponse)
def read_case_versions(case_id: str) -> VersionListResponse:
    items = list_versions_for_case(case_id)
    return VersionListResponse(
        success=True,
        case_id=case_id,
        count=len(items),
        items=items,
    )
