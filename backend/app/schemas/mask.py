from typing import Any

from pydantic import BaseModel, Field


class MaskRecord(BaseModel):
    mask_id: str
    annotation_id: str | None = None
    case_id: str | None = None
    image_id: str | None = None
    path: str
    version: str = "v1_manual"
    label: str = "label"
    label_id: int | None = None
    label_type: str | None = None
    mask_format: str = "nii.gz"
    axis: str | None = None
    slice_index: int | None = None
    width: int | None = None
    height: int | None = None
    encoding: str | None = None
    create_time: str | None = None


class SaveMaskRequest(BaseModel):
    case_id: str
    image_id: str
    annotation_id: str | None = None
    version: str = "v1_manual"
    label: str = Field(default="label", min_length=1)
    label_type: str | None = None
    mask_format: str = "nii.gz"
    axis: str = "axial"
    slice_index: int | None = None
    width: int | None = None
    height: int | None = None
    label_id: int | None = None
    encoding: str | None = None
    mask: list[Any] | None = None
    points: list[dict[str, Any]] | None = None
    overwrite: bool = True


class UpdateMaskRequest(BaseModel):
    label: str | None = None
    label_id: int | None = None
    label_type: str | None = None
    axis: str | None = None
    slice_index: int | None = None
    width: int | None = None
    height: int | None = None
    encoding: str | None = None
    mask: list[Any] | None = None
    points: list[dict[str, Any]] | None = None


class SaveMaskResponse(BaseModel):
    success: bool
    mask_id: str
    path: str
    mask: MaskRecord
    updated: bool = False


class DeleteMaskResponse(BaseModel):
    success: bool
    mask_id: str
    message: str = "deleted"


class PromoteMaskRequest(BaseModel):
    target_version: str = "v3_fusion"


class CompareMasksRequest(BaseModel):
    pred_mask_id: str = Field(min_length=1)
    ref_mask_id: str = Field(min_length=1)


class CompareMasksResponse(BaseModel):
    success: bool = True
    pred_mask_id: str
    ref_mask_id: str
    pred_version: str | None = None
    ref_version: str | None = None
    shape: list[int]
    pred_voxels: int
    ref_voxels: int
    intersection: int
    dice: float
    iou: float
    precision: float
    recall: float
    volume_diff_voxels: int = 0
    volume_diff_ml: float = 0.0
    pred_volume_ml: float | None = None
    ref_volume_ml: float | None = None
    hd95_mm: float | None = None
    spacing: list[float] | None = None


class MaskMetricsResponse(BaseModel):
    success: bool = True
    mask_id: str
    ref_mask_id: str | None = None
    version: str | None = None
    label: str | None = None
    geometric: dict[str, Any] | None = None
    overlap: dict[str, Any] | None = None
    error_slices: list[dict[str, Any]] = Field(default_factory=list)


class RollbackMaskResponse(BaseModel):
    success: bool = True
    mask_id: str
    path: str
    source_mask_id: str
    version: str = "v3_preview"
    mask: MaskRecord
    message: str = "rolled back to v3_preview"


class MaskDetailResponse(BaseModel):
    success: bool
    mask: MaskRecord
    content: dict[str, Any] | None = None


class MaskListResponse(BaseModel):
    success: bool
    image_id: str
    count: int
    items: list[MaskRecord]
    masks: list[MaskRecord]


class ExportMaskNiftiRequest(BaseModel):
    case_id: str
    image_id: str
    version: str = "v1_manual"
    label: str = "label"
    # True: stack all labels of this version into one multiclass 3D volume.
    match_any_label: bool = False
    output_label: str | None = None


class ExportMaskNiftiResponse(BaseModel):
    success: bool
    mask_id: str
    path: str
    source_mask_ids: list[str]
    shape: list[int]
    spacing: list[float]
    origin: list[float]
    direction: list[float]
    mask: MaskRecord


class LabelPropagationRequest(BaseModel):
    case_id: str
    image_id: str
    source_version: str = "v1_manual"
    output_version: str = "v3_preview"
    label: str = "label"
    label_type: str = "pseudo"
    method: str = "image_guided_distance"
    fill_holes: bool = True
    keep_largest_component: bool = False
    image_guidance: bool = True
    hu_margin: float | None = None
    closing_radius: int = 1
    random_walker_beta: float = 90.0
    random_walker_roi_margin: int = 24
    random_walker_max_nodes: int = 45000
    connected_component_mode: str = "seeded"
    connected_component_min_voxels: int = 64
    connected_component_max_components: int = 8
    positive_points: list[list[float]] = []
    negative_points: list[list[float]] = []
    label_id: int | None = None
    match_any_label: bool = False


class LabelPropagationResponse(BaseModel):
    success: bool
    mask_id: str
    path: str
    method: str
    source_mask_ids: list[str]
    annotated_slices: list[int]
    propagated_slices: int
    shape: list[int]
    spacing: list[float]
    origin: list[float]
    direction: list[float]
    mask: MaskRecord
    label_type: str | None = "pseudo"


class ActiveLearningSliceItem(BaseModel):
    slice_index: int
    score: float
    reason: str
    components: int = 0
    area: int = 0
    iou_prev: float | None = None
    iou_next: float | None = None
    entropy: float | None = None


class LabelingWorkload(BaseModel):
    labeled_slices: list[int] = Field(default_factory=list)
    labeled_count: int = 0
    total_slices: int = 0
    min_recommended: int = 3
    remaining_to_min: int = 0
    estimated_remaining_dense: int = 0
    coverage_ratio: float = 0.0


class LabelingAssistResponse(BaseModel):
    success: bool = True
    image_id: str
    case_id: str | None = None
    axis: str = "axial"
    label: str = "label"
    workload: LabelingWorkload
    recommendations: list[ActiveLearningSliceItem] = Field(default_factory=list)
    ready_for_propagate: bool = False
    has_preview: bool = False
    preview_mask_id: str | None = None


class DeepEditRefineRequest(BaseModel):
    case_id: str
    image_id: str
    source_version: str = "v1_manual"
    current_mask_version: str = "v3_fusion"
    current_mask_id: str | None = None
    output_version: str = "v3_preview"
    label: str = "label"
    model_id: str | None = "DeepEdit"
    random_walker_beta: float = 90.0
    random_walker_roi_margin: int = 24
    connected_component_min_voxels: int = 64
    positive_points: list[list[float]] = []
    negative_points: list[list[float]] = []
    scribbles: list[dict[str, Any]] = []
    interaction: dict[str, Any] = {}
    confirmed_slices: list[int] = []
    # Default: neural DeepEdit only. Use /api/label_propagate for graph-cut.
    require_neural: bool = True


class DeepEditRefineResponse(LabelPropagationResponse):
    refinement_mode: str = "deepedit_fallback_random_walker"
    model_status: str = "fallback"
    model_message: str | None = None
