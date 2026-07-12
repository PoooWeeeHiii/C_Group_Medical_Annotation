"""Background training jobs for platform U-Net."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.app.core.config import PROJECT_ROOT
from backend.app.services.model_service import register_model

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def list_train_jobs() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(job) for job in sorted(_JOBS.values(), key=lambda item: item.get("created_at") or 0, reverse=True)]


def get_train_job(job_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Train job not found: {job_id}")
        return dict(job)


def _update_job(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        logs = list(job.get("logs") or [])
        logs.append(line.rstrip())
        job["logs"] = logs[-400:]


def _run_job(job_id: str, command: list[str], env: dict[str, str], model_id: str, dataset_id: str) -> None:
    _update_job(job_id, status="running", started_at=time.time())
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _update_job(job_id, pid=process.pid)
        assert process.stdout is not None
        for line in process.stdout:
            _append_log(job_id, line)
            try:
                payload = json.loads(line.strip())
                if payload.get("event") == "epoch":
                    _update_job(
                        job_id,
                        current_epoch=payload.get("epoch"),
                        train_loss=payload.get("train_loss"),
                        val_loss=payload.get("val_loss"),
                        val_dice=payload.get("val_dice"),
                    )
                if payload.get("event") == "done":
                    _update_job(job_id, metrics=payload.get("metrics"))
            except json.JSONDecodeError:
                pass
        code = process.wait()
        if code != 0:
            _update_job(job_id, status="failed", exit_code=code, finished_at=time.time())
            _append_log(job_id, f"[error] training exited with code {code}")
            return

        metrics_path = PROJECT_ROOT / "ai" / "runs" / f"{model_id}_metrics.json"
        metrics = {}
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        checkpoint = metrics.get("checkpoint") or f"ai/checkpoints/{model_id}.pt"
        dice = metrics.get("best_val_dice")
        register_model(
            model_id=model_id,
            version=model_id,
            label="multiclass",
            display_name=f"Platform U-Net 2.5D ({model_id})",
            path=checkpoint,
            dice=float(dice) if dice is not None else None,
            description=(
                f"Trained on {dataset_id}; 2.5D slice U-Net + 3D postprocess. "
                "For production prefer TotalSeg / nnUNet."
            ),
            backend="platform_unet",
        )
        _update_job(
            job_id,
            status="completed",
            exit_code=0,
            finished_at=time.time(),
            metrics=metrics,
            registered_model_id=model_id,
            checkpoint=checkpoint,
        )
        _append_log(job_id, f"[done] registered model {model_id}")
    except Exception as exc:
        _update_job(job_id, status="failed", error=str(exc), finished_at=time.time())
        _append_log(job_id, f"[error] {exc}")


def start_train_job(
    *,
    dataset_id: str,
    model_id: str | None = None,
    epochs: int = 20,
    batch_size: int = 4,
    lr: float = 1e-4,
    num_classes: int = 6,
    image_size: int = 320,
    context_radius: int = 1,
    max_slices_per_volume: int = 64,
    export_dir: str | None = None,
) -> dict[str, Any]:
    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id is required")
    model_id = (model_id or f"ModelUNet_{dataset_id}").strip()
    job_id = f"TrainJob_{uuid.uuid4().hex[:10]}"

    python = sys.executable
    command = [
        python,
        str(PROJECT_ROOT / "ai" / "train.py"),
        "--dataset-id",
        dataset_id,
        "--model-id",
        model_id,
        "--epochs",
        str(max(1, int(epochs))),
        "--batch-size",
        str(max(1, int(batch_size))),
        "--lr",
        str(float(lr)),
        "--num-classes",
        str(max(2, int(num_classes))),
        "--image-size",
        str(max(64, int(image_size))),
        "--context-radius",
        str(max(0, int(context_radius))),
        "--max-slices-per-volume",
        str(max(8, int(max_slices_per_volume))),
    ]
    if export_dir:
        command.extend(["--export-dir", export_dir])

    job = {
        "job_id": job_id,
        "status": "queued",
        "dataset_id": dataset_id,
        "model_id": model_id,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "num_classes": num_classes,
        "image_size": image_size,
        "context_radius": context_radius,
        "max_slices_per_volume": max_slices_per_volume,
        "export_dir": export_dir,
        "command": command,
        "logs": [],
        "created_at": time.time(),
        "metrics": None,
        "registered_model_id": None,
    }
    with _LOCK:
        _JOBS[job_id] = job

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, command, env, model_id, dataset_id),
        daemon=True,
    )
    thread.start()
    return dict(job)
