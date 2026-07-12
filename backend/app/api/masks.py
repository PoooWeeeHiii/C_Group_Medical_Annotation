from fastapi import APIRouter, Depends

from backend.app.deps import get_optional_user
from backend.app.schemas.mask import (
    CompareMasksRequest,
    CompareMasksResponse,
    DeepEditRefineRequest,
    DeepEditRefineResponse,
    DeleteMaskResponse,
    ExportMaskNiftiRequest,
    ExportMaskNiftiResponse,
    LabelingAssistResponse,
    LabelPropagationRequest,
    LabelPropagationResponse,
    MaskDetailResponse,
    MaskListResponse,
    MaskMetricsResponse,
    PromoteMaskRequest,
    RollbackMaskResponse,
    SaveMaskRequest,
    SaveMaskResponse,
    UpdateMaskRequest,
)
from backend.app.services.mask_service import (
    compare_masks,
    deepedit_refine,
    delete_mask,
    export_mask_nifti,
    get_labeling_assist,
    get_mask,
    get_mask_content,
    get_mask_metrics,
    get_mask_quality_summary,
    get_mask_slice_data,
    get_mask_surface_mesh,
    get_mask_volume_data,
    label_propagate,
    list_masks_for_image,
    promote_mask,
    rollback_mask,
    save_mask,
    update_mask,
)


router = APIRouter(prefix="/api", tags=["masks"])


@router.post("/save_mask", response_model=SaveMaskResponse)
def save_image_mask(
    request: SaveMaskRequest,
    user: dict | None = Depends(get_optional_user),
) -> SaveMaskResponse:
    return save_mask(request, user=user)


@router.put("/mask/{mask_id}", response_model=SaveMaskResponse)
def update_image_mask(
    mask_id: str,
    request: UpdateMaskRequest,
    user: dict | None = Depends(get_optional_user),
) -> SaveMaskResponse:
    return update_mask(mask_id, request, user=user)


@router.delete("/mask/{mask_id}", response_model=DeleteMaskResponse)
def remove_image_mask(
    mask_id: str,
    user: dict | None = Depends(get_optional_user),
) -> DeleteMaskResponse:
    result = delete_mask(mask_id, user=user)
    return DeleteMaskResponse(**result)


@router.post("/export_mask_nifti", response_model=ExportMaskNiftiResponse)
def export_image_mask_nifti(request: ExportMaskNiftiRequest) -> ExportMaskNiftiResponse:
    return export_mask_nifti(request)


@router.post("/label_propagate", response_model=LabelPropagationResponse)
def propagate_image_label(request: LabelPropagationRequest) -> LabelPropagationResponse:
    return label_propagate(request)


@router.get("/image/{image_id}/labeling_assist", response_model=LabelingAssistResponse)
@router.get("/images/{image_id}/labeling_assist", response_model=LabelingAssistResponse)
def read_labeling_assist(
    image_id: str,
    label: str = "label",
    axis: str = "axial",
    top_k: int = 5,
    min_slices: int = 3,
    source_version: str = "v1_manual",
    preview_mask_id: str | None = None,
) -> LabelingAssistResponse:
    return LabelingAssistResponse(
        **get_labeling_assist(
            image_id,
            label=label,
            axis=axis,
            top_k=top_k,
            min_slices=min_slices,
            source_version=source_version,
            preview_mask_id=preview_mask_id,
        )
    )


@router.post("/deepedit/refine", response_model=DeepEditRefineResponse)
def refine_image_mask_deepedit(request: DeepEditRefineRequest) -> DeepEditRefineResponse:
    return deepedit_refine(request)


@router.post("/mask/{mask_id}/promote", response_model=SaveMaskResponse)
def promote_image_mask(
    mask_id: str,
    request: PromoteMaskRequest,
    user: dict | None = Depends(get_optional_user),
) -> SaveMaskResponse:
    return promote_mask(mask_id=mask_id, target_version=request.target_version, user=user)


@router.post("/masks/compare", response_model=CompareMasksResponse)
def compare_image_masks(request: CompareMasksRequest) -> CompareMasksResponse:
    return CompareMasksResponse(**compare_masks(request.pred_mask_id, request.ref_mask_id))


@router.get("/mask/{mask_a}/compare/{mask_b}", response_model=CompareMasksResponse)
def compare_masks_by_path(mask_a: str, mask_b: str) -> CompareMasksResponse:
    return CompareMasksResponse(**compare_masks(mask_a, mask_b))


@router.get("/mask/{mask_id}/metrics", response_model=MaskMetricsResponse)
def read_mask_metrics(mask_id: str, ref: str | None = None) -> MaskMetricsResponse:
    return MaskMetricsResponse(**get_mask_metrics(mask_id, ref_mask_id=ref))


@router.post("/mask/{mask_id}/rollback", response_model=RollbackMaskResponse)
def rollback_image_mask(
    mask_id: str,
    user: dict | None = Depends(get_optional_user),
) -> RollbackMaskResponse:
    result = rollback_mask(mask_id, user=user)
    return RollbackMaskResponse(
        success=True,
        mask_id=result["mask_id"],
        path=result["path"],
        source_mask_id=result["source_mask_id"],
        version=result["version"],
        mask=result["mask"],
        message=result["message"],
    )


@router.get("/mask/{mask_id}", response_model=MaskDetailResponse)
def read_mask(mask_id: str) -> MaskDetailResponse:
    return MaskDetailResponse(success=True, mask=get_mask(mask_id), content=get_mask_content(mask_id))


@router.get("/mask/{mask_id}/volume-data")
def read_mask_volume_data(mask_id: str, max_dim: int = 176) -> dict:
    return get_mask_volume_data(mask_id=mask_id, max_dim=max_dim)


@router.get("/mask/{mask_id}/surface-mesh")
def read_mask_surface_mesh(
    mask_id: str,
    min_component_voxels: int = 64,
    max_components: int = 8,
    max_triangles: int = 90000,
    target_reduction: float = 0.55,
    smooth_iterations: int = 8,
    remove_thin: bool = True,
    constrain_to_body: bool = True,
    constrain_to_source_roi: bool = True,
    source_roi_margin_mm: float = 45.0,
) -> dict:
    return get_mask_surface_mesh(
        mask_id=mask_id,
        min_component_voxels=min_component_voxels,
        max_components=max_components,
        max_triangles=max_triangles,
        target_reduction=target_reduction,
        smooth_iterations=smooth_iterations,
        remove_thin=remove_thin,
        constrain_to_body=constrain_to_body,
        constrain_to_source_roi=constrain_to_source_roi,
        source_roi_margin_mm=source_roi_margin_mm,
    )


@router.get("/mask/{mask_id}/quality")
def read_mask_quality(mask_id: str) -> dict:
    return get_mask_quality_summary(mask_id=mask_id)


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
