from fastapi import APIRouter

from backend.app.schemas.image import ImageDetailResponse
from backend.app.services.case_service import get_image
from backend.app.services.medical_image_service import (
    export_volume_file,
    get_volume_metadata,
    get_vtk_volume_data,
    render_projection_png,
    render_slice_png,
)


router = APIRouter(prefix="/api", tags=["images"])


@router.get("/image/{image_id}", response_model=ImageDetailResponse)
def read_image(image_id: str) -> ImageDetailResponse:
    return ImageDetailResponse(success=True, image=get_image(image_id))


@router.get("/image/{image_id}/volume")
def read_image_volume(image_id: str) -> dict:
    return get_volume_metadata(image_id)


@router.get("/image/{image_id}/vtk-volume")
def read_vtk_volume(image_id: str, max_dim: int = 144, window: str = "lung") -> dict:
    return get_vtk_volume_data(image_id=image_id, max_dim=max_dim, window=window)


@router.get("/image/{image_id}/slice/{slice_index}.png")
def read_image_slice(image_id: str, slice_index: int, window: str = "auto"):
    return render_slice_png(image_id=image_id, slice_index=slice_index, window=window)


@router.get("/image/{image_id}/slice/{axis}/{slice_index}.png")
def read_image_axis_slice(image_id: str, axis: str, slice_index: int, window: str = "auto"):
    return render_slice_png(image_id=image_id, slice_index=slice_index, window=window, axis=axis)


@router.get("/image/{image_id}/projection/{axis}.png")
def read_image_projection(image_id: str, axis: str, method: str = "mip", window: str = "auto"):
    return render_projection_png(image_id=image_id, axis=axis, method=method, window=window)


@router.get("/image/{image_id}/export-3d")
def export_image_volume(image_id: str):
    return export_volume_file(image_id)
