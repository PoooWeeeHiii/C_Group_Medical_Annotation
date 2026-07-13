from pydantic import BaseModel, Field


class TrainStartRequest(BaseModel):
    dataset_id: str
    model_id: str | None = None
    epochs: int = Field(default=20, ge=1, le=500)
    batch_size: int = Field(default=4, ge=1, le=64)
    lr: float = Field(default=1e-4, gt=0)
    num_classes: int = Field(default=6, ge=2, le=64)
    image_size: int = Field(default=320, ge=64, le=512)
    context_radius: int = Field(default=1, ge=0, le=3, description="2.5D neighbor radius; 1 => 3 input channels")
    max_slices_per_volume: int = Field(default=64, ge=8, le=256)
    export_dir: str | None = None


class TrainJobRecord(BaseModel):
    job_id: str
    status: str
    dataset_id: str
    model_id: str
    epochs: int | None = None
    batch_size: int | None = None
    lr: float | None = None
    num_classes: int | None = None
    context_radius: int | None = None
    current_epoch: int | None = None
    train_loss: float | None = None
    val_loss: float | None = None
    val_dice: float | None = None
    logs: list[str] = Field(default_factory=list)
    metrics: dict | None = None
    registered_model_id: str | None = None
    checkpoint: str | None = None
    error: str | None = None


class TrainStartResponse(BaseModel):
    success: bool = True
    job: TrainJobRecord


class TrainJobResponse(BaseModel):
    success: bool = True
    job: TrainJobRecord


class TrainJobListResponse(BaseModel):
    success: bool = True
    items: list[TrainJobRecord]
    count: int
