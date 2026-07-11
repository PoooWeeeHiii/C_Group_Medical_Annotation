"""Inference — aligned with POST /api/ai/predict in docs/04_api_design.md."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import (
    LABELS_DIR,
    SPLEEN_LABEL,
    SPLEEN_MODEL_ID,
    VERSION_AI,
    mask_filename,
)
from ai.spleen_nnunet import ensure_spleen_model_ready, predict_spleen_volume


def build_predict_response(
    case_id: str,
    image_id: str,
    mask_id: str,
    image_path: str,
    mask_path: str,
    label: str = SPLEEN_LABEL,
    model_id: str = SPLEEN_MODEL_ID,
    version: str = VERSION_AI,
    source: str = "ai",
    dice: float | None = None,
) -> dict[str, Any]:
    """Response schema for POST /api/ai/predict."""
    payload = {
        "case_id": case_id,
        "image_id": image_id,
        "mask_id": mask_id,
        "image_path": image_path,
        "mask_path": mask_path,
        "mask_format": "nii.gz",
        "label": label,
        "version": version,
        "source": source,
        "model_id": model_id,
        "filename": mask_filename(case_id, image_id, mask_id, version, label, ext="nii.gz"),
    }
    if dice is not None:
        payload["dice"] = dice
    return payload


def predict_spleen(
    case_id: str,
    image_id: str,
    mask_id: str,
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    image_path: str,
) -> dict[str, Any]:
    """Run spleen nnUNet inference and write a v2_ai mask under dataset/labels/."""
    ensure_spleen_model_ready()
    relative_mask = (
        Path("dataset")
        / "labels"
        / case_id
        / VERSION_AI
        / mask_filename(case_id, image_id, mask_id, VERSION_AI, SPLEEN_LABEL, ext="nii.gz")
    )
    absolute_mask = ROOT / relative_mask
    predict_spleen_volume(volume=volume, spacing=spacing, output_mask_path=absolute_mask)
    return build_predict_response(
        case_id=case_id,
        image_id=image_id,
        mask_id=mask_id,
        image_path=image_path,
        mask_path=str(relative_mask).replace("\\", "/"),
        label=SPLEEN_LABEL,
        model_id=SPLEEN_MODEL_ID,
        version=VERSION_AI,
    )


def predict(
    case_id: str,
    image_id: str,
    image_path: str,
    *,
    mask_id: str = "Mask0001",
    label: str = SPLEEN_LABEL,
    volume: np.ndarray | None = None,
    spacing: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> dict[str, Any]:
    """Run AI segmentation. Currently supports spleen via local nnUNet weights."""
    normalized = label.strip().lower()
    if normalized != SPLEEN_LABEL:
        raise NotImplementedError(
            f"Label '{label}' is not implemented yet. Current AI predictor supports '{SPLEEN_LABEL}'."
        )
    if volume is None:
        raise ValueError("predict() requires a CT volume array for spleen inference")
    return predict_spleen(
        case_id=case_id,
        image_id=image_id,
        mask_id=mask_id,
        volume=volume,
        spacing=spacing,
        image_path=image_path,
    )


if __name__ == "__main__":
    demo = build_predict_response(
        "Case0001",
        "Image0001",
        "Mask0001",
        "dataset/raw/Case0001/image.nii.gz",
        "dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_spleen.nii.gz",
    )
    print("[Person B] predict response schema:", demo)
    try:
        ckpt = ensure_spleen_model_ready()
        print(f"[Person B] spleen checkpoint ready: {ckpt}")
    except FileNotFoundError as exc:
        print(f"[Person B] spleen checkpoint missing: {exc}")
