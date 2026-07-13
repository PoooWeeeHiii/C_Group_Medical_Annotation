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


def _is_totalseg_request(model_id: str, label: str = "") -> bool:
    mid = (model_id or "").strip().lower()
    if mid.startswith("totalseg") or "totalsegmentator" in mid:
        return True
    try:
        from backend.app.services.model_service import get_model

        model = get_model(model_id)
        backend = str((model.get("backend") or model.get("metrics", {}).get("backend") or "")).lower()
        return backend == "totalsegmentator"
    except Exception:
        return False


def _run_totalseg_predict(volume, spacing, label: str, model_id: str) -> np.ndarray:
    organs = _run_totalseg_organs(volume, spacing, label=label, model_id=model_id)
    if not organs:
        raise HTTPException(status_code=422, detail="TotalSegmentator produced empty masks")
    if label in organs:
        return organs[label]
    # Prefer spleen as primary preview when multi-organ
    if "spleen" in organs:
        return organs["spleen"]
    return next(iter(organs.values()))


def _run_totalseg_organs(volume, spacing, label: str, model_id: str) -> dict[str, np.ndarray]:
    try:
        from ai.totalseg_predict import ensure_totalseg_ready, predict_totalseg_organs

        ensure_totalseg_ready()
        return predict_totalseg_organs(
            volume.array if hasattr(volume, "array") else volume,
            spacing,
            label=label,
            model_id=model_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"TotalSegmentator not ready: {exc}",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TotalSegmentator inference failed: {exc}") from exc


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


def get_ai_health():
    from backend.app.schemas.ai import AiHealthResponse

    spleen_ready = False
    spleen_message = ""
    spleen_checkpoint = None
    nnunet_python = None
    try:
        from ai.config import SPLEEN_MODEL_ID, SPLEEN_NNUNET_PYTHON
        from ai.spleen_nnunet import ensure_spleen_model_ready

        nnunet_python = str(SPLEEN_NNUNET_PYTHON)
        checkpoint = ensure_spleen_model_ready()
        spleen_ready = True
        spleen_checkpoint = str(checkpoint)
        spleen_message = "spleen nnUNet checkpoint ready"
        spleen_model_id = str(SPLEEN_MODEL_ID)
    except Exception as exc:
        spleen_message = str(exc)
        spleen_model_id = "Model0002"

    organ_ready_n = 0
    organ_total = 0
    organ_message = ""
    try:
        from ai.config import ORGANS_NNUNET_PYTHON
        from ai.organ_nnunet import list_ready_organ_models

        if not nnunet_python:
            nnunet_python = str(ORGANS_NNUNET_PYTHON)
        rows = list_ready_organ_models()
        organ_total = len(rows)
        organ_ready_n = sum(1 for r in rows if r.get("ready"))
        names = ",".join(r["label"] for r in rows if r.get("ready")) or "none"
        organ_message = f"organ nnUNet ready {organ_ready_n}/{organ_total} ({names})"
    except Exception as exc:
        organ_message = f"organ nnUNet: {exc}"

    totalseg_ready = False
    totalseg_message = ""
    try:
        from ai.totalseg_predict import ensure_totalseg_ready

        python = ensure_totalseg_ready()
        totalseg_ready = True
        totalseg_message = f"TotalSegmentator ready ({python})"
    except Exception as exc:
        totalseg_message = str(exc)

    ready = spleen_ready or totalseg_ready or organ_ready_n > 0
    parts = [spleen_message, organ_message, totalseg_message]
    return AiHealthResponse(
        success=True,
        ready=ready,
        model_id=spleen_model_id if spleen_ready else ("totalseg_spleen" if totalseg_ready else spleen_model_id),
        label="spleen",
        checkpoint=spleen_checkpoint,
        nnunet_python=nnunet_python,
        message=" | ".join(p for p in parts if p),
    )


def _run_local_spleen_nnunet(volume, spacing) -> np.ndarray | None:
    """Try Person B's local Dataset506 spleen weights via ai.spleen_nnunet."""
    try:
        from ai.predict import predict_spleen_mask_array
        from ai.spleen_nnunet import ensure_spleen_model_ready

        ensure_spleen_model_ready()
        return predict_spleen_mask_array(volume, spacing)
    except FileNotFoundError:
        return None
    except Exception as exc:
        # Fall through to command template / baseline; keep detail for logs.
        print(f"[ai_service] local spleen nnUNet unavailable: {exc}")
        return None


def _run_local_organ_nnunet(volume, spacing, model_id: str, label: str) -> tuple[np.ndarray, str] | None:
    """Try Plan A heart/liver/lung/kidney nnUNet weights."""
    try:
        from ai.organ_nnunet import predict_organ_volume

        mask, spec = predict_organ_volume(
            model_id=model_id,
            label=label,
            volume=volume,
            spacing=tuple(float(v) for v in spacing[:3]),
        )
        return mask, spec.label
    except FileNotFoundError as exc:
        print(f"[ai_service] organ nnUNet missing weights: {exc}")
        return None
    except Exception as exc:
        print(f"[ai_service] organ nnUNet unavailable: {exc}")
        return None


def run_ai_prediction(request: AIPredictRequest) -> AIPredictResponse:
    from ai.organ_nnunet import is_organ_nnunet_request
    from ai.totalseg_predict import is_multi_organ_model
    from backend.app.services.model_service import get_model, resolve_predict_label

    model_id, label = resolve_predict_label(request.model_id, request.label)
    # Person B historically used Model0002 for spleen.
    if model_id in {"Model0002", "model0002"}:
        model_id = "spleen_nnunetv2_task506"
        label = label if label and label != "label" else "spleen"
    # Person B Plan A aliases Model0010–0013 → *_nnunet_ds51x
    from ai.config import ORGAN_MODEL_ALIASES

    if model_id in ORGAN_MODEL_ALIASES:
        mapped = ORGAN_MODEL_ALIASES[model_id]
        if not label or label == "label":
            from ai.organ_nnunet import ORGAN_MODELS

            label = ORGAN_MODELS[mapped].label
        model_id = mapped
    elif model_id.lower() in ORGAN_MODEL_ALIASES:
        mapped = ORGAN_MODEL_ALIASES[model_id.lower()]
        if not label or label == "label":
            from ai.organ_nnunet import ORGAN_MODELS

            label = ORGAN_MODELS[mapped].label
        model_id = mapped

    image_record, volume = load_volume(request.image_id)
    if image_record.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    organ_masks: dict[str, np.ndarray] | None = None
    mask_stack = None
    model_status = "unknown"
    backend_name: str | None = None
    fallback_reason: str | None = None
    try:
        image_path = (PROJECT_ROOT / str(image_record.get("path", ""))).resolve()
        registered = None
        try:
            registered = get_model(model_id)
            backend_name = str(registered.get("backend") or registered.get("metrics", {}).get("backend") or "") or None
        except HTTPException:
            registered = None

        if backend_name and backend_name.lower() in {"platform_unet", "platform-unet", "unet2d"}:
            from ai.platform_unet_predict import predict_platform_unet_mask

            mask_stack = predict_platform_unet_mask(
                volume.array,
                model_id=model_id,
                checkpoint_path=(registered or {}).get("path"),
                label=label,
            )
            organ_masks = {label: mask_stack}
            model_status = "platform_unet"
            backend_name = "platform_unet"
        elif (
            (backend_name and backend_name.lower() in {"organ_nnunet_local", "organ_nnunet"})
            or is_organ_nnunet_request(model_id, label, backend_name)
        ):
            organ_result = _run_local_organ_nnunet(volume.array, volume.spacing, model_id, label)
            if organ_result is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Organ nnUNet weights unavailable for model_id={model_id!r}. "
                        "Check ORGANS_NNUNET_ROOT and Plan A checkpoints under "
                        r"E:\lxy\hm_2_organs_nnunet\nnUNet_results."
                    ),
                )
            mask_stack, organ_label = organ_result
            label = organ_label
            organ_masks = {organ_label: mask_stack}
            model_status = "organ_nnunet"
            backend_name = "organ_nnunet_local"
        elif _is_totalseg_request(model_id, label):
            organ_masks = _run_totalseg_organs(volume, volume.spacing, label=label, model_id=model_id)
            model_status = "totalsegmentator"
            backend_name = "totalsegmentator"
            if is_multi_organ_model(model_id):
                # Keep all non-empty organs; primary preview prefers spleen then first.
                if not organ_masks:
                    raise HTTPException(status_code=422, detail="TotalSegmentator produced empty masks")
                if "spleen" in organ_masks:
                    primary_label = "spleen"
                elif label in organ_masks:
                    primary_label = label
                else:
                    primary_label = next(iter(organ_masks))
                label = primary_label
                mask_stack = organ_masks[primary_label]
            else:
                # Single-organ / merged request
                if label in organ_masks:
                    mask_stack = organ_masks[label]
                    organ_masks = {label: mask_stack}
                elif str(label).lower() == "lung" or model_id.endswith("_lung"):
                    lobe_masks = [mask for name, mask in organ_masks.items() if str(name).startswith("lung_")]
                    if not lobe_masks:
                        raise HTTPException(status_code=422, detail="TotalSegmentator produced empty lung masks")
                    merged = lobe_masks[0].copy()
                    for part in lobe_masks[1:]:
                        merged = np.maximum(merged, part)
                    label = "lung"
                    mask_stack = merged
                    organ_masks = {"lung": merged}
                elif len(organ_masks) == 1:
                    label, mask_stack = next(iter(organ_masks.items()))
                else:
                    # Merge all returned ROIs into one mask under requested label
                    merged = None
                    for part in organ_masks.values():
                        merged = part if merged is None else np.maximum(merged, part)
                    assert merged is not None
                    mask_stack = merged
                    organ_masks = {label: merged}
        elif _is_spleen_request(label, model_id):
            mask_stack = _run_local_spleen_nnunet(volume.array, volume.spacing)
            if mask_stack is not None:
                model_status = "spleen_nnunet"
                backend_name = "spleen_nnunet"
            elif image_path.exists():
                mask_stack = _run_external_spleen_command(image_path, request.case_id)
                if mask_stack is not None:
                    model_status = "spleen_nnunet_external"
                    backend_name = "spleen_nnunet"

        if mask_stack is None and organ_masks is None:
            if not request.allow_baseline:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Real AI backend unavailable for model_id={model_id!r}, label={label!r}. "
                        "Configure TotalSegmentator / organ nnUNet / spleen nnUNet / platform_unet weights, "
                        "or pass allow_baseline=true to use the HU-threshold demo baseline."
                    ),
                )
            mask_stack = predict_mask_array(volume.array, label=label, model_id=model_id)
            organ_masks = {label: mask_stack}
            model_status = "baseline_hu"
            backend_name = "baseline_hu"
            fallback_reason = "allow_baseline=true; used HU threshold + connected components"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI inference failed: {exc}") from exc

    if organ_masks is None:
        organ_masks = {label: np.asarray(mask_stack)}

    # Validate + normalize
    cleaned: dict[str, np.ndarray] = {}
    for organ_label, stack in organ_masks.items():
        arr = (np.asarray(stack) > 0).astype(np.uint8)
        if arr.shape != volume.array.shape[:3]:
            raise HTTPException(
                status_code=500,
                detail=f"AI mask shape mismatch for {organ_label}: mask={arr.shape}, image={volume.array.shape[:3]}",
            )
        if np.any(arr):
            cleaned[organ_label] = arr
    if not cleaned:
        raise HTTPException(status_code=422, detail="AI inference produced an empty mask")
    organ_masks = cleaned
    if label not in organ_masks:
        label = "spleen" if "spleen" in organ_masks else next(iter(organ_masks))
    mask_stack = organ_masks[label]

    annotation_id = f"AnnotationAI_{request.image_id}_{_safe_id(model_id)}"
    try:
        existing_model = get_model(model_id)
        upsert_record(
            "models",
            {
                "model_id": model_id,
                "version": existing_model.get("version") or model_id,
                "dice": existing_model.get("dice"),
                "path": existing_model.get("path"),
                "metrics_json": existing_model.get("metrics")
                or {
                    "label": label,
                    "display_name": existing_model.get("display_name") or model_id,
                    "backend": existing_model.get("backend") or "registered",
                    "description": existing_model.get("description") or "",
                },
            },
        )
    except HTTPException:
        upsert_record(
            "models",
            {
                "model_id": model_id,
                "version": model_id,
                "dice": None,
                "path": None,
                "metrics_json": {"label": label, "display_name": model_id},
            },
        )

    organ_mask_ids: list[str] = []
    organ_labels: list[str] = []
    primary_mask = None
    primary_path = ""

    from backend.app.services.gold_label_service import resolve_label_name_to_id

    name_to_id = resolve_label_name_to_id()
    # Extra aliases for TotalSeg / lobe names.
    alias_to_id = {
        "liver": name_to_id.get("liver", 1),
        "kidney": name_to_id.get("kidney", 2),
        "kidney_left": name_to_id.get("kidney", 2),
        "kidney_right": name_to_id.get("kidney", 2),
        "lung": name_to_id.get("lung", 3),
        "lung_upper_lobe_left": name_to_id.get("lung", 3),
        "lung_upper_lobe_right": name_to_id.get("lung", 3),
        "lung_middle_lobe_right": name_to_id.get("lung", 3),
        "lung_lower_lobe_left": name_to_id.get("lung", 3),
        "lung_lower_lobe_right": name_to_id.get("lung", 3),
        "tumor": name_to_id.get("tumor", 4),
        "spleen": name_to_id.get("spleen", 5),
        "heart": name_to_id.get("heart", 9),
        "pancreas": name_to_id.get("pancreas", 6),
        "stomach": name_to_id.get("stomach", 7),
        "gallbladder": name_to_id.get("gallbladder", 8),
    }
    for key, value in name_to_id.items():
        alias_to_id.setdefault(str(key).lower(), int(value))

    def _organ_label_id(organ_name: str) -> int:
        key = str(organ_name or "").strip().lower().replace(" ", "_")
        if key in alias_to_id and int(alias_to_id[key]) > 0:
            return int(alias_to_id[key])
        if key.startswith("lung"):
            return int(alias_to_id.get("lung", 3))
        # Allocate stable fallback ids in 9..63 for unknown organs.
        digest = sum(ord(ch) for ch in key) % 55
        return 9 + digest

    # Build multiclass "全部标注" when more than one organ is present.
    multiclass_stack = None
    if len(organ_masks) > 1:
        multiclass_stack = np.zeros(volume.array.shape[:3], dtype=np.uint8)
        # Paint larger organs first so smaller / critical ROIs can overwrite if needed:
        # actually paint in ascending label_id then higher priority organs last.
        ordered_paint = sorted(
            organ_masks.items(),
            key=lambda item: (_organ_label_id(item[0]), item[0]),
        )
        for organ_label, stack in ordered_paint:
            lid = _organ_label_id(organ_label)
            if lid <= 0 or lid > 255:
                continue
            mask_bool = np.asarray(stack) > 0
            multiclass_stack[mask_bool] = np.uint8(lid)

    # Save primary first: prefer 全部标注 for multi-organ, else the selected organ.
    if multiclass_stack is not None and np.any(multiclass_stack):
        mask, mask_path = _append_3d_mask_record(
            masks=[],
            request_case_id=request.case_id,
            image_id=request.image_id,
            version="v2_ai",
            label="全部标注",
            encoding=f"ai_inference:{model_id}:{model_status}:multiclass",
            source_mask_ids=[],
            mask_stack=multiclass_stack,
            volume=volume,
            annotation_id=annotation_id,
            label_type="pseudo",
            label_id=None,
        )
        organ_mask_ids.append(mask.mask_id)
        organ_labels.append("全部标注")
        primary_mask = mask
        primary_path = mask_path
        label = "全部标注"

    ordered_labels = [name for name in sorted(organ_masks)]
    if primary_mask is None:
        # Single-organ path: keep previous primary preference.
        preferred = [label] + [name for name in ordered_labels if name != label]
        ordered_labels = [name for name in preferred if name in organ_masks]

    for organ_label in ordered_labels:
        lid = _organ_label_id(organ_label)
        # Store class id in voxels for consistent coloring even on single-organ masks.
        classed = (np.asarray(organ_masks[organ_label]) > 0).astype(np.uint8) * np.uint8(lid)
        mask, mask_path = _append_3d_mask_record(
            masks=[],
            request_case_id=request.case_id,
            image_id=request.image_id,
            version="v2_ai",
            label=organ_label,
            encoding=f"ai_inference:{model_id}:{model_status}",
            source_mask_ids=[],
            mask_stack=classed,
            volume=volume,
            annotation_id=annotation_id if organ_label == label else f"{annotation_id}_{_safe_id(organ_label)}",
            label_id=lid,
        )
        organ_mask_ids.append(mask.mask_id)
        organ_labels.append(organ_label)
        if primary_mask is None:
            primary_mask = mask
            primary_path = mask_path

    assert primary_mask is not None
    save_version(
        SaveVersionRequest(
            case_id=request.case_id,
            version="v2_ai",
            annotation=annotation_id,
            model=model_id,
            dataset=None,
        )
    )

    count = len([name for name in organ_labels if name != "全部标注"]) or len(organ_labels)
    message = (
        f"ai predict success ({model_status}): {count} organs"
        + (" + 全部标注" if "全部标注" in organ_labels else "")
        + f" ({', '.join([n for n in organ_labels if n != '全部标注'][:8])}{'...' if count > 8 else ''})"
        if count > 1 or "全部标注" in organ_labels
        else f"ai predict success ({model_status})"
    )
    return AIPredictResponse(
        success=True,
        annotation_id=annotation_id,
        mask_id=primary_mask.mask_id,
        version="v2_ai",
        model_id=model_id,
        label=label,
        dice=None,
        mask_path=primary_path,
        mask=primary_mask,
        message=message,
        organ_count=count,
        organ_labels=organ_labels,
        organ_mask_ids=organ_mask_ids,
        model_status=model_status,
        backend=backend_name,
        fallback_reason=fallback_reason,
    )
