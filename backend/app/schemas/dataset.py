from typing import Any

from pydantic import BaseModel, Field


class DatasetExportRequest(BaseModel):
    dataset_id: str | None = None
    name: str = "medical_segmentation_dataset"
    version: str = "final"
    # dense = 精标 (final/v3_fusion)；weak = 弱标签伪标 (v3_preview) + 稀疏粗标溯源
    label_set: str = "dense"
    train: list[str] = Field(default_factory=list)
    val: list[str] = Field(default_factory=list)
    test: list[str] = Field(default_factory=list)
    format: str = "nnunet"
    materialize: bool = False
    strict: bool = True


class SpacingCheckItem(BaseModel):
    case_id: str
    image_id: str
    mask_id: str
    status: str
    image_spacing: list[float] | None = None
    mask_spacing: list[float] | None = None
    image_shape: list[int] | None = None
    mask_shape: list[int] | None = None
    detail: str | None = None


class MissingMaskItem(BaseModel):
    case_id: str
    image_id: str | None = None
    version: str
    reason: str


class DatasetExportReport(BaseModel):
    success_count: int = 0
    skipped_count: int = 0
    missing_masks: list[MissingMaskItem] = Field(default_factory=list)
    spacing_checks: list[SpacingCheckItem] = Field(default_factory=list)
    materialized_files: list[str] = Field(default_factory=list)
    export_dir: str | None = None


class DatasetExportResponse(BaseModel):
    success: bool
    dataset_id: str
    output_path: str
    split_path: str
    label_map_path: str
    train_count: int
    val_count: int
    test_count: int
    message: str
    materialize: bool = False
    label_set: str = "dense"
    version: str = "final"
    export_dir: str | None = None
    dataset_json_path: str | None = None
    splits_final_path: str | None = None
    report: DatasetExportReport | None = None
