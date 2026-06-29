"""Data pipeline skeleton — Day1: function stubs, Day2: implement."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np

from ai.config import IMAGE_SIZE, LABELS_DIR, mask_filename


def load(path: str | Path) -> np.ndarray:
    """Load DICOM series folder, NIfTI, NRRD or PNG."""
    raise NotImplementedError("Day2: DICOM/NIfTI/NRRD/PNG loader")


def normalize(volume: np.ndarray, modality: str = "CT") -> np.ndarray:
    """CT window [-1000, 400] HU then scale to [0, 1]."""
    raise NotImplementedError("Day2: intensity normalization")


def resize(arr: np.ndarray, size: Tuple[int, int] = IMAGE_SIZE) -> np.ndarray:
    """Resize 2D slice to (H, W)."""
    raise NotImplementedError("Day2: resize with cv2 or torch")


def crop(arr: np.ndarray, bbox: Tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Optional ROI crop."""
    raise NotImplementedError("Day2: optional lung ROI crop")


def save(arr: np.ndarray, path: str | Path, *, is_mask: bool = False) -> Path:
    """Save to dataset/images or dataset/labels."""
    raise NotImplementedError("Day2: save PNG or nii.gz")


def label_path(case_id: str, image_id: str, mask_id: str, version: str, label: str = "lung_nodule") -> Path:
    """Build standard mask path under dataset/labels/."""
    fname = mask_filename(case_id, image_id, mask_id, version, label)
    return LABELS_DIR / case_id / version / fname
