"""Run spleen segmentation with a local nnUNet v2 checkpoint."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from ai.config import (
    SPLEEN_CHECKPOINT_NAME,
    SPLEEN_CONFIGURATION,
    SPLEEN_DATASET_ID,
    SPLEEN_FOLD,
    SPLEEN_MODEL_DIR,
    SPLEEN_NNUNET_PREPROCESSED,
    SPLEEN_NNUNET_PYTHON,
    SPLEEN_NNUNET_RAW,
    SPLEEN_NNUNET_RESULTS,
    SPLEEN_TRAINER,
)


def _write_nifti(array: np.ndarray, spacing: tuple[float, float, float], out_path: Path) -> None:
    import SimpleITK as sitk

    image = sitk.GetImageFromArray(np.asarray(array, dtype=np.float32))
    # SimpleITK spacing is (x, y, z); VolumeData.spacing follows the same convention.
    image.SetSpacing(tuple(float(v) for v in spacing[:3]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))


def _read_nifti(path: Path) -> np.ndarray:
    import SimpleITK as sitk

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    return np.asarray(array)


def _resolve_python() -> str:
    candidates = [
        Path(SPLEEN_NNUNET_PYTHON),
        SPLEEN_NNUNET_RESULTS.parent / "venv_nnunet_cpu" / "Scripts" / "python.exe",
        SPLEEN_NNUNET_RESULTS.parent / "venv_nnunet" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python"


def _prefer_cli() -> bool:
    """Prefer subprocess CLI when the current interpreter is not the nnUNet env."""
    current = Path(sys.executable).resolve()
    preferred = Path(_resolve_python()).resolve()
    return current != preferred


def _nnunet_env() -> dict[str, str]:
    env = os.environ.copy()
    env["nnUNet_raw"] = str(SPLEEN_NNUNET_RAW)
    env["nnUNet_preprocessed"] = str(SPLEEN_NNUNET_PREPROCESSED)
    env["nnUNet_results"] = str(SPLEEN_NNUNET_RESULTS)
    return env


def _predict_with_python_api(input_dir: Path, output_dir: Path) -> None:
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
        str(SPLEEN_MODEL_DIR),
        use_folds=(int(SPLEEN_FOLD),),
        checkpoint_name=SPLEEN_CHECKPOINT_NAME,
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


def _predict_with_cli(input_dir: Path, output_dir: Path) -> None:
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
            str(SPLEEN_DATASET_ID),
            "-c",
            str(SPLEEN_CONFIGURATION),
            "-f",
            str(SPLEEN_FOLD),
            "-tr",
            str(SPLEEN_TRAINER),
            "-chk",
            str(SPLEEN_CHECKPOINT_NAME),
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
        raise RuntimeError(
            "nnUNet spleen prediction failed. "
            f"command={' '.join(cmd)}\n{detail}"
        )


def ensure_spleen_model_ready() -> Path:
    checkpoint = SPLEEN_MODEL_DIR / f"fold_{SPLEEN_FOLD}" / SPLEEN_CHECKPOINT_NAME
    if not checkpoint.exists():
        raise FileNotFoundError(
            f"Spleen nnUNet checkpoint not found: {checkpoint}. "
            "Set SPLEEN_MODEL_DIR / SPLEEN_CHECKPOINT_NAME if the weights live elsewhere."
        )
    return checkpoint


def predict_spleen_volume(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    output_mask_path: Path,
) -> Path:
    """Segment spleen from a 3D CT volume and write a binary nii.gz mask."""
    ensure_spleen_model_ready()
    if volume.ndim != 3:
        raise ValueError(f"Expected 3D CT volume, got shape={volume.shape}")

    output_mask_path = Path(output_mask_path)
    output_mask_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="spleen_nnunet_") as tmp:
        tmp_dir = Path(tmp)
        input_dir = tmp_dir / "input"
        output_dir = tmp_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        case_stem = "case_0000"
        input_nii = input_dir / f"{case_stem}_0000.nii.gz"
        _write_nifti(volume, spacing, input_nii)

        if _prefer_cli():
            _predict_with_cli(input_dir, output_dir)
        else:
            try:
                _predict_with_python_api(input_dir, output_dir)
            except ModuleNotFoundError:
                _predict_with_cli(input_dir, output_dir)

        predicted = output_dir / f"{case_stem}.nii.gz"
        if not predicted.exists():
            candidates = sorted(output_dir.glob("*.nii.gz"))
            if not candidates:
                raise FileNotFoundError(f"nnUNet produced no mask under {output_dir}")
            predicted = candidates[0]

        mask = (_read_nifti(predicted) > 0).astype(np.uint8)
        _write_nifti(mask, spacing, output_mask_path)

    return output_mask_path
