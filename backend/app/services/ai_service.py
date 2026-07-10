from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from fastapi import HTTPException

from ai.predict import predict_mask_array
from backend.app.core.config import PROJECT_ROOT
from backend.app.schemas.ai import AIPredictRequest, AIPredictResponse
from backend.app.schemas.version import SaveVersionRequest
from backend.app.services.mask_service import _append_3d_mask_record
from backend.app.services.medical_image_service import load_volume
from backend.app.services.sqlite_service import upsert_record
from backend.app.services.version_service import save_version


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return normalized or "model"


def _is_spleen_request(label: str, model_id: str) -> bool:
    target = f"{label} {model_id}".lower()
    return "spleen" in target or "脾" in target


def _read_mask_nifti(path: Path) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to read external AI mask") from exc
    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    return (array > 0).astype(np.uint8)


def _run_external_spleen_command(image_path: Path, case_id: str) -> np.ndarray | None:
    """Run an optional nnU-Net spleen predictor command.

    The referenced spleen experiment repository stores reproducible nnU-Net
    commands but not the model checkpoint. When the local checkpoint/runtime is
    available, set SPLEEN_NNUNET_PREDICT_COMMAND with placeholders:

    {input_dir} {output_dir} {image_path} {output_path} {case_id}

    Example:
    nnUNetv2_predict -i {input_dir} -o {output_dir} -d 506 -c 2d -f 0
    """
    command_template = os.getenv("SPLEEN_NNUNET_PREDICT_COMMAND")
    if not command_template:
        return None

    timeout = int(os.getenv("SPLEEN_NNUNET_TIMEOUT_SECONDS", "900"))
    with tempfile.TemporaryDirectory(prefix="spleen_nnunet_") as tmp:
        tmp_path = Path(tmp)
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        nnunet_case = _safe_id(case_id)
        input_image = input_dir / f"{nnunet_case}_0000.nii.gz"
        if image_path.name.endswith(".nii.gz") or image_path.suffix.lower() == ".nii":
            shutil.copy2(image_path, input_image)
        else:
            try:
                import SimpleITK as sitk
            except ModuleNotFoundError as exc:
                raise HTTPException(status_code=500, detail="SimpleITK is required to convert image for nnU-Net") from exc
            image = sitk.ReadImage(str(image_path))
            sitk.WriteImage(image, str(input_image))

        output_path = output_dir / f"{nnunet_case}.nii.gz"
        formatted = command_template.format(
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            image_path=str(input_image),
            output_path=str(output_path),
            case_id=nnunet_case,
        )
        try:
            subprocess.run(
                shlex.split(formatted),
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise HTTPException(status_code=500, detail=f"Spleen nnU-Net inference failed: {detail}") from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="Spleen nnU-Net inference timed out") from exc

        candidates = [output_path] + sorted(output_dir.glob("*.nii.gz"))
        for candidate in candidates:
            if candidate.exists():
                return _read_mask_nifti(candidate)
    return None


def run_ai_prediction(request: AIPredictRequest) -> AIPredictResponse:
    model_id = request.model_id or "builtin_ct_threshold"
    image_record, volume = load_volume(request.image_id)
    if image_record.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    try:
        image_path = (PROJECT_ROOT / str(image_record.get("path", ""))).resolve()
        mask_stack = None
        if _is_spleen_request(request.label, model_id) and image_path.exists():
            mask_stack = _run_external_spleen_command(image_path, request.case_id)
        if mask_stack is None:
            mask_stack = predict_mask_array(volume.array, label=request.label, model_id=model_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI inference failed: {exc}") from exc

    mask_stack = (np.asarray(mask_stack) > 0).astype(np.uint8)
    if mask_stack.shape != volume.array.shape[:3]:
        raise HTTPException(
            status_code=500,
            detail=f"AI mask shape mismatch: mask={mask_stack.shape}, image={volume.array.shape[:3]}",
        )
    if not np.any(mask_stack):
        raise HTTPException(status_code=422, detail="AI inference produced an empty mask")

    annotation_id = f"AnnotationAI_{request.image_id}_{_safe_id(model_id)}"
    upsert_record(
        "models",
        {
            "model_id": model_id,
            "version": model_id,
            "dice": None,
            "path": None,
            "metrics_json": None,
        },
    )

    mask, mask_path = _append_3d_mask_record(
        masks=[],
        request_case_id=request.case_id,
        image_id=request.image_id,
        version="v2_ai",
        label=request.label,
        encoding=f"ai_inference:{model_id}",
        source_mask_ids=[],
        mask_stack=mask_stack,
        volume=volume,
        annotation_id=annotation_id,
    )
    save_version(
        SaveVersionRequest(
            case_id=request.case_id,
            version="v2_ai",
            annotation=annotation_id,
            model=model_id,
            dataset=None,
        )
    )

    return AIPredictResponse(
        success=True,
        annotation_id=annotation_id,
        mask_id=mask.mask_id,
        version="v2_ai",
        model_id=model_id,
        dice=None,
        mask_path=mask_path,
        mask=mask,
    )
