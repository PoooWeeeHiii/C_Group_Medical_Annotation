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
    mask_format: str = "nii.gz"
    axis: str = "axial"
    slice_index: int | None = None
    width: int | None = None
    height: int | None = None
    label_id: int | None = None
    encoding: str | None = None
    mask: list[Any] | None = None
    points: list[dict[str, Any]] | None = None


class SaveMaskResponse(BaseModel):
    success: bool
    mask_id: str
    path: str
    mask: MaskRecord


class PromoteMaskRequest(BaseModel):
    target_version: str = "v3_fusion"


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


class DeepEditRefineResponse(LabelPropagationResponse):
    refinement_mode: str = "deepedit_fallback_random_walker"
    model_status: str = "fallback"
    model_message: str | None = None
