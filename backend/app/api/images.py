from fastapi import APIRouter

from backend.app.schemas.image import ImageDetailResponse
from backend.app.services.case_service import get_image
from backend.app.services.medical_image_service import (
    export_volume_file,
    get_volume_metadata,
    render_slice_png,
)


router = APIRouter(prefix="/api", tags=["images"])


@router.get("/image/{image_id}", response_model=ImageDetailResponse)
def read_image(image_id: str) -> ImageDetailResponse:
    return ImageDetailResponse(success=True, image=get_image(image_id))


@router.get("/image/{image_id}/volume")
def read_image_volume(image_id: str) -> dict:
    return get_volume_metadata(image_id)


@router.get("/image/{image_id}/slice/{slice_index}.png")
def read_image_slice(image_id: str, slice_index: int, window: str = "auto"):
    return render_slice_png(image_id=image_id, slice_index=slice_index, window=window)


@router.get("/image/{image_id}/export-3d")
def export_image_volume(image_id: str):
    return export_volume_file(image_id)
