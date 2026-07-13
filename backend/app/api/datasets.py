from fastapi import APIRouter

from backend.app.schemas.dataset import DatasetExportRequest, DatasetExportResponse
from backend.app.services.dataset_service import export_dataset


router = APIRouter(prefix="/api", tags=["datasets"])


@router.post("/export", response_model=DatasetExportResponse)
def export_dataset_release(request: DatasetExportRequest) -> DatasetExportResponse:
    return export_dataset(request)
