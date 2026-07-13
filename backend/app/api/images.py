from fastapi import APIRouter

from backend.app.schemas.image import ImageDetailResponse
from backend.app.services.case_service import get_image
from backend.app.services.medical_image_service import (
    export_volume_file,
    get_slice_values,
    get_image_surface_mesh,
    get_volume_metadata,
    get_volume_render_data,
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


@router.get("/image/{image_id}/volume-data")
def read_volume_render_data(
    image_id: str,
    max_dim: int = 144,
    window: str = "lung",
    isotropic: bool = False,
    target_spacing: float | None = None,
) -> dict:
    return get_volume_render_data(
        image_id=image_id,
        max_dim=max_dim,
        window=window,
        isotropic=isotropic,
        target_spacing=target_spacing,
    )


@router.get("/image/{image_id}/surface-mesh")
def read_image_surface_mesh(
    image_id: str,
    protocol: str = "bone",
    max_dim: int = 176,
    min_component_voxels: int = 512,
    max_components: int = 3,
    max_triangles: int = 120000,
    target_reduction: float = 0.50,
    smooth_iterations: int = 6,
) -> dict:
    return get_image_surface_mesh(
        image_id=image_id,
        protocol=protocol,
        max_dim=max_dim,
        min_component_voxels=min_component_voxels,
        max_components=max_components,
        max_triangles=max_triangles,
        target_reduction=target_reduction,
        smooth_iterations=smooth_iterations,
    )


@router.get("/image/{image_id}/vtk-volume")
def read_legacy_volume_render_data(
    image_id: str,
    max_dim: int = 144,
    window: str = "lung",
    isotropic: bool = False,
    target_spacing: float | None = None,
) -> dict:
    return get_volume_render_data(
        image_id=image_id,
        max_dim=max_dim,
        window=window,
        isotropic=isotropic,
        target_spacing=target_spacing,
    )


@router.get("/image/{image_id}/slice/{slice_index}.png")
def read_image_slice(image_id: str, slice_index: int, window: str = "auto"):
    return render_slice_png(image_id=image_id, slice_index=slice_index, window=window)


@router.get("/image/{image_id}/slice/{axis}/{slice_index}.png")
def read_image_axis_slice(image_id: str, axis: str, slice_index: int, window: str = "auto"):
    return render_slice_png(image_id=image_id, slice_index=slice_index, window=window, axis=axis)


@router.get("/image/{image_id}/slice/{slice_index}/values")
def read_image_slice_values(image_id: str, slice_index: int):
    return get_slice_values(image_id=image_id, slice_index=slice_index, axis="axial")


@router.get("/image/{image_id}/slice/{axis}/{slice_index}/values")
def read_image_axis_slice_values(image_id: str, axis: str, slice_index: int):
    return get_slice_values(image_id=image_id, slice_index=slice_index, axis=axis)


@router.get("/image/{image_id}/projection/{axis}.png")
def read_image_projection(
    image_id: str,
    axis: str,
    method: str = "mip",
    window: str = "auto",
    center: int | None = None,
    thickness: int | None = None,
):
    return render_projection_png(
        image_id=image_id,
        axis=axis,
        method=method,
        window=window,
        center=center,
        thickness=thickness,
    )


@router.get("/image/{image_id}/export-3d")
def export_image_volume(image_id: str):
    return export_volume_file(image_id)
