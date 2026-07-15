from fastapi import APIRouter

from backend.app.schemas.train import (
    TrainJobListResponse,
    TrainJobRecord,
    TrainJobResponse,
    TrainStartRequest,
    TrainStartResponse,
)
from backend.app.services.train_service import get_train_job, list_train_jobs, start_train_job

router = APIRouter(prefix="/api", tags=["train"])


def _to_record(job: dict) -> TrainJobRecord:
    return TrainJobRecord(
        job_id=str(job.get("job_id")),
        status=str(job.get("status") or "unknown"),
        dataset_id=str(job.get("dataset_id") or ""),
        model_id=str(job.get("model_id") or ""),
        epochs=job.get("epochs"),
        batch_size=job.get("batch_size"),
        lr=job.get("lr"),
        num_classes=job.get("num_classes"),
        context_radius=job.get("context_radius"),
        current_epoch=job.get("current_epoch"),
        train_loss=job.get("train_loss"),
        val_loss=job.get("val_loss"),
        val_dice=job.get("val_dice"),
        logs=list(job.get("logs") or []),
        metrics=job.get("metrics"),
        registered_model_id=job.get("registered_model_id"),
        checkpoint=job.get("checkpoint"),
        error=job.get("error"),
    )


@router.post("/train", response_model=TrainStartResponse)
def start_training(request: TrainStartRequest) -> TrainStartResponse:
    job = start_train_job(
        dataset_id=request.dataset_id,
        model_id=request.model_id,
        epochs=request.epochs,
        batch_size=request.batch_size,
        lr=request.lr,
        num_classes=request.num_classes,
        image_size=request.image_size,
        context_radius=request.context_radius,
        max_slices_per_volume=request.max_slices_per_volume,
        export_dir=request.export_dir,
        resume=request.resume,
        resume_from=request.resume_from,
    )
    return TrainStartResponse(job=_to_record(job))


@router.get("/train", response_model=TrainJobListResponse)
def read_train_jobs() -> TrainJobListResponse:
    items = [_to_record(job) for job in list_train_jobs()]
    return TrainJobListResponse(items=items, count=len(items))


@router.get("/train/{job_id}", response_model=TrainJobResponse)
def read_train_job(job_id: str) -> TrainJobResponse:
    return TrainJobResponse(job=_to_record(get_train_job(job_id)))
