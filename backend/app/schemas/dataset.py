from pydantic import BaseModel, Field


class DatasetExportRequest(BaseModel):
    dataset_id: str | None = None
    name: str = "medical_segmentation_dataset"
    version: str = "final"
    train: list[str] = Field(default_factory=list)
    val: list[str] = Field(default_factory=list)
    test: list[str] = Field(default_factory=list)
    format: str = "nnunet"


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
