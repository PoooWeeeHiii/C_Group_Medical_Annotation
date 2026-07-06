from fastapi import APIRouter

from backend.app.schemas.mask import (
    DeepEditRefineRequest,
    DeepEditRefineResponse,
    ExportMaskNiftiRequest,
    ExportMaskNiftiResponse,
    LabelPropagationRequest,
    LabelPropagationResponse,
    MaskDetailResponse,
    MaskListResponse,
    SaveMaskRequest,
    SaveMaskResponse,
)
from backend.app.services.mask_service import (
    deepedit_refine,
    export_mask_nifti,
    get_mask,
    get_mask_content,
    get_mask_slice_data,
    get_mask_volume_data,
    label_propagate,
    list_masks_for_image,
    save_mask,
)


router = APIRouter(prefix="/api", tags=["masks"])


@router.post("/save_mask", response_model=SaveMaskResponse)
def save_image_mask(request: SaveMaskRequest) -> SaveMaskResponse:
    return save_mask(request)


@router.post("/export_mask_nifti", response_model=ExportMaskNiftiResponse)
def export_image_mask_nifti(request: ExportMaskNiftiRequest) -> ExportMaskNiftiResponse:
    return export_mask_nifti(request)


@router.post("/label_propagate", response_model=LabelPropagationResponse)
def propagate_image_label(request: LabelPropagationRequest) -> LabelPropagationResponse:
    return label_propagate(request)


@router.post("/deepedit/refine", response_model=DeepEditRefineResponse)
def refine_image_mask_deepedit(request: DeepEditRefineRequest) -> DeepEditRefineResponse:
    return deepedit_refine(request)


@router.get("/mask/{mask_id}", response_model=MaskDetailResponse)
def read_mask(mask_id: str) -> MaskDetailResponse:
    return MaskDetailResponse(success=True, mask=get_mask(mask_id), content=get_mask_content(mask_id))


@router.get("/mask/{mask_id}/volume-data")
def read_mask_volume_data(mask_id: str, max_dim: int = 176) -> dict:
    return get_mask_volume_data(mask_id=mask_id, max_dim=max_dim)


@router.get("/mask/{mask_id}/slice/{slice_index}")
def read_mask_slice_data(mask_id: str, slice_index: int) -> dict:
    return get_mask_slice_data(mask_id=mask_id, slice_index=slice_index)


@router.get("/mask/{mask_id}/slice/{axis}/{slice_index}")
def read_mask_axis_slice_data(mask_id: str, axis: str, slice_index: int) -> dict:
    return get_mask_slice_data(mask_id=mask_id, axis=axis, slice_index=slice_index)


@router.get("/image/{image_id}/masks", response_model=MaskListResponse)
@router.get("/images/{image_id}/masks", response_model=MaskListResponse)
def list_image_masks(image_id: str) -> MaskListResponse:
    matched = list_masks_for_image(image_id)
    return MaskListResponse(
        success=True,
        image_id=image_id,
        count=len(matched),
        items=matched,
        masks=matched,
    )
