"""Run Plan A multi-organ segmentation with local nnUNet v2 checkpoints.

Organs live under ORGANS_NNUNET_ROOT (default E:\\lxy\\hm_2_organs_nnunet):
  Dataset510_DeepEdit_Heart / 511_Liver / 512_Lung / 513_Kidney
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ai.config import (
    ORGAN_MODEL_ALIASES,
    ORGANS_CHECKPOINT_NAME,
    ORGANS_CONFIGURATION,
    ORGANS_FOLD,
    ORGANS_NNUNET_PREPROCESSED,
    ORGANS_NNUNET_PYTHON,
    ORGANS_NNUNET_RAW,
    ORGANS_NNUNET_RESULTS,
    ORGANS_NNUNET_ROOT,
    ORGANS_TRAINER,
)


@dataclass(frozen=True)
class OrganModelSpec:
    model_id: str
    label: str
    dataset_id: int
    dataset_folder: str
    display_name: str
    dice: float | None = None


ORGAN_MODELS: dict[str, OrganModelSpec] = {
    "heart_nnunet_ds510": OrganModelSpec(
        model_id="heart_nnunet_ds510",
        label="heart",
        dataset_id=510,
        dataset_folder="Dataset510_DeepEdit_Heart",
        display_name="心脏 nnU-Net (Dataset510 / Plan A)",
        dice=0.613,
    ),
    "liver_nnunet_ds511": OrganModelSpec(
        model_id="liver_nnunet_ds511",
        label="liver",
        dataset_id=511,
        dataset_folder="Dataset511_DeepEdit_Liver",
        display_name="肝脏 nnU-Net (Dataset511 / Plan A)",
        dice=0.921,
    ),
    "lung_nnunet_ds512": OrganModelSpec(
        model_id="lung_nnunet_ds512",
        label="lung",
        dataset_id=512,
        dataset_folder="Dataset512_DeepEdit_Lung",
        display_name="肺部 nnU-Net (Dataset512 / Plan A)",
        dice=0.950,
    ),
    "kidney_nnunet_ds513": OrganModelSpec(
        model_id="kidney_nnunet_ds513",
        label="kidney",
        dataset_id=513,
        dataset_folder="Dataset513_DeepEdit_Kidney",
        display_name="肾脏 nnU-Net (Dataset513 / Plan A)",
        dice=0.813,
    ),
}

# Aliases: bare organ name → preferred Plan A model when explicitly requested via backend.
LABEL_TO_MODEL_ID = {spec.label: spec.model_id for spec in ORGAN_MODELS.values()}
# Person B short IDs (Model0010–0013) → canonical *_nnunet_ds51x
PERSON_B_ORGAN_ALIASES = dict(ORGAN_MODEL_ALIASES)


def resolve_organ_model(model_id: str | None = None, label: str | None = None) -> OrganModelSpec | None:
    mid = (model_id or "").strip()
    if mid in PERSON_B_ORGAN_ALIASES:
        mid = PERSON_B_ORGAN_ALIASES[mid]
    elif mid.lower() in PERSON_B_ORGAN_ALIASES:
        mid = PERSON_B_ORGAN_ALIASES[mid.lower()]
    if mid in ORGAN_MODELS:
        return ORGAN_MODELS[mid]
    key = (label or "").strip().lower()
    if key in LABEL_TO_MODEL_ID and mid.lower() in {"", "label", key}:
        return ORGAN_MODELS[LABEL_TO_MODEL_ID[key]]
    return None


def is_organ_nnunet_request(model_id: str, label: str = "", backend: str | None = None) -> bool:
    if (backend or "").strip().lower() in {"organ_nnunet_local", "organ_nnunet"}:
        return True
    mid = (model_id or "").strip()
    if mid in PERSON_B_ORGAN_ALIASES or mid.lower() in PERSON_B_ORGAN_ALIASES:
        return True
    mid_l = mid.lower()
    if mid in ORGAN_MODELS or mid_l in ORGAN_MODELS:
        return True
    if mid_l.endswith("_nnunet_ds510") or mid_l.endswith("_nnunet_ds511"):
        return True
    if mid_l.endswith("_nnunet_ds512") or mid_l.endswith("_nnunet_ds513"):
        return True
    if "nnunet_ds51" in mid_l:
        return True
    key = (label or "").strip().lower()
    return key in LABEL_TO_MODEL_ID and mid_l in {"", "label", key}


def model_dir_for(spec: OrganModelSpec) -> Path:
    override = os.environ.get(f"ORGANS_MODEL_DIR_{spec.dataset_id}")
    if override:
        return Path(override)
    return (
        ORGANS_NNUNET_RESULTS
        / spec.dataset_folder
        / f"{ORGANS_TRAINER}__nnUNetPlans__{ORGANS_CONFIGURATION}"
    )


def checkpoint_path_for(spec: OrganModelSpec) -> Path:
    return model_dir_for(spec) / f"fold_{ORGANS_FOLD}" / ORGANS_CHECKPOINT_NAME


def ensure_organ_model_ready(model_id: str | None = None, label: str | None = None) -> Path:
    spec = resolve_organ_model(model_id=model_id, label=label)
    if spec is None:
        raise FileNotFoundError(f"Unknown organ nnUNet model: model_id={model_id!r} label={label!r}")
    checkpoint = checkpoint_path_for(spec)
    if not checkpoint.exists():
        raise FileNotFoundError(
            f"Organ nnUNet checkpoint not found: {checkpoint}. "
            f"Train Plan A or set ORGANS_NNUNET_ROOT (current={ORGANS_NNUNET_ROOT})."
        )
    return checkpoint


def list_ready_organ_models() -> list[dict]:
    rows = []
    for spec in ORGAN_MODELS.values():
        ckpt = checkpoint_path_for(spec)
        rows.append(
            {
                "model_id": spec.model_id,
                "label": spec.label,
                "dataset_id": spec.dataset_id,
                "ready": ckpt.exists(),
                "checkpoint": str(ckpt),
                "dice": spec.dice,
            }
        )
    return rows


def _write_nifti(array: np.ndarray, spacing: tuple[float, float, float], out_path: Path) -> None:
    import SimpleITK as sitk

    image = sitk.GetImageFromArray(np.asarray(array, dtype=np.float32))
    image.SetSpacing(tuple(float(v) for v in spacing[:3]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))


def _read_nifti(path: Path) -> np.ndarray:
    import SimpleITK as sitk

    return np.asarray(sitk.GetArrayFromImage(sitk.ReadImage(str(path))))


def _resolve_python() -> str:
    candidates = [
        Path(ORGANS_NNUNET_PYTHON),
        Path(r"D:\anaconda\python.exe"),
        ORGANS_NNUNET_ROOT / "venv_nnunet" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python"


def _prefer_cli() -> bool:
    current = Path(sys.executable).resolve()
    preferred = Path(_resolve_python()).resolve()
    return current != preferred


def _nnunet_env() -> dict[str, str]:
    env = os.environ.copy()
    env["nnUNet_raw"] = str(ORGANS_NNUNET_RAW)
    env["nnUNet_preprocessed"] = str(ORGANS_NNUNET_PREPROCESSED)
    env["nnUNet_results"] = str(ORGANS_NNUNET_RESULTS)
    return env


def _predict_with_python_api(spec: OrganModelSpec, input_dir: Path, output_dir: Path) -> None:
    import torch
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    predictor = nnUNetPredictor(
        tile_step_size=0.5,
        use_gaussian=True,
        use_mirroring=True,
        perform_everything_on_device=True,
        device=device,
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=False,
    )
    predictor.initialize_from_trained_model_folder(
        str(model_dir_for(spec)),
        use_folds=(int(ORGANS_FOLD),),
        checkpoint_name=ORGANS_CHECKPOINT_NAME,
    )
    predictor.predict_from_files(
        str(input_dir),
        str(output_dir),
        save_probabilities=False,
        overwrite=True,
        num_processes_preprocessing=1,
        num_processes_segmentation_export=1,
        folder_with_segs_from_prev_stage=None,
        num_parts=1,
        part_id=0,
    )


def _predict_with_cli(spec: OrganModelSpec, input_dir: Path, output_dir: Path) -> None:
    python_exe = Path(_resolve_python())
    predict_exe = python_exe.parent / "nnUNetv2_predict.exe"
    if not predict_exe.exists():
        predict_exe = python_exe.parent / "nnUNetv2_predict"
    if predict_exe.exists():
        cmd = [str(predict_exe)]
    else:
        cmd = [str(python_exe), "-m", "nnunetv2.bin.predict_entry_point"]

    cmd.extend(
        [
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-d",
            str(spec.dataset_id),
            "-c",
            str(ORGANS_CONFIGURATION),
            "-f",
            str(ORGANS_FOLD),
            "-tr",
            str(ORGANS_TRAINER),
            "-chk",
            str(ORGANS_CHECKPOINT_NAME),
            "-npp",
            "1",
            "-nps",
            "1",
        ]
    )
    completed = subprocess.run(
        cmd,
        env=_nnunet_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"nnUNet organ prediction failed ({spec.model_id}).\n{detail}")


def predict_organ_volume(
    *,
    model_id: str | None,
    label: str | None,
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    output_mask_path: Path | None = None,
) -> tuple[np.ndarray, OrganModelSpec]:
    """Return binary mask [D,H,W] and the resolved OrganModelSpec."""
    spec = resolve_organ_model(model_id=model_id, label=label)
    if spec is None:
        raise ValueError(f"Cannot resolve organ nnUNet model from model_id={model_id!r} label={label!r}")
    ensure_organ_model_ready(model_id=spec.model_id, label=spec.label)
    if volume.ndim != 3:
        raise ValueError(f"Expected 3D CT volume, got shape={volume.shape}")

    with tempfile.TemporaryDirectory(prefix=f"organ_nnunet_{spec.label}_") as tmp:
        tmp_dir = Path(tmp)
        input_dir = tmp_dir / "input"
        output_dir = tmp_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        case_stem = "case_0000"
        _write_nifti(volume, spacing, input_dir / f"{case_stem}_0000.nii.gz")

        if _prefer_cli():
            _predict_with_cli(spec, input_dir, output_dir)
        else:
            try:
                _predict_with_python_api(spec, input_dir, output_dir)
            except ModuleNotFoundError:
                _predict_with_cli(spec, input_dir, output_dir)

        predicted = output_dir / f"{case_stem}.nii.gz"
        if not predicted.exists():
            candidates = sorted(output_dir.glob("*.nii.gz"))
            if not candidates:
                raise FileNotFoundError(f"nnUNet produced no mask under {output_dir}")
            predicted = candidates[0]

        mask = (_read_nifti(predicted) > 0).astype(np.uint8)
        if output_mask_path is not None:
            _write_nifti(mask.astype(np.float32), spacing, Path(output_mask_path))
        return mask, spec


def predict_organ_mask_array(
    volume: np.ndarray,
    spacing: tuple[float, float, float] | list[float],
    *,
    model_id: str | None = None,
    label: str | None = None,
) -> np.ndarray:
    mask, _spec = predict_organ_volume(
        model_id=model_id,
        label=label,
        volume=volume,
        spacing=tuple(float(v) for v in spacing[:3]),
    )
    return mask
