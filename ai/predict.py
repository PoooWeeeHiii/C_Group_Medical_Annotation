"""Inference — aligned with POST /api/ai/predict in docs/04_api_design.md."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import MODEL_ID, VERSION_AI, mask_filename


def predict(case_id: str, image_id: str, image_path: str) -> dict[str, Any]:
    """Run AI segmentation. Day6: load checkpoint and infer."""
    raise NotImplementedError("Day6: model inference")


def build_predict_response(
    case_id: str,
    image_id: str,
    mask_id: str,
    image_path: str,
    mask_path: str,
    label: str = "lung_nodule",
    model_id: str = MODEL_ID,
    version: str = VERSION_AI,
    source: str = "ai",
) -> dict[str, Any]:
    """Response schema for POST /api/ai/predict."""
    return {
        "case_id": case_id,
        "image_id": image_id,
        "mask_id": mask_id,
        "image_path": image_path,
        "mask_path": mask_path,
        "mask_format": "png",
        "label": label,
        "version": version,
        "source": source,
        "model_id": model_id,
        "filename": mask_filename(case_id, image_id, mask_id, version, label),
    }


if __name__ == "__main__":
    demo = build_predict_response(
        "Case0001", "Image0001", "Mask0001",
        "dataset/images/Case0001/Case0001_Image0001.nii.gz",
        "dataset/labels/Case0001/v2_ai/Case0001_Image0001_Mask0001_v2_ai_lung_nodule.png",
    )
    print("[Person B Day1] predict response schema:", demo)
