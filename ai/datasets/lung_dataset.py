"""Dataset loader — reads manifest + split JSON (Person A export or Day2 manifest)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from ai.augment import augment_pair
from ai.config import BATCH_SIZE, DATASET_ID, PROJECT_ROOT, SPLITS_DIR

try:
    import SimpleITK as sitk
except ImportError:  # pragma: no cover
    sitk = None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_dataset_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def load_split(dataset_id: str = DATASET_ID) -> dict[str, Any]:
    return _read_json(SPLITS_DIR / f"{dataset_id}_split.json")


def load_manifest(dataset_id: str = DATASET_ID) -> dict[str, Any]:
    return _read_json(SPLITS_DIR / f"{dataset_id}_manifest.json")


def records_for_split(split: str, dataset_id: str = DATASET_ID) -> list[dict[str, Any]]:
    """Return normalized records for one split from Person A export or Day2 manifest."""
    split_data = load_split(dataset_id)
    case_ids = set(split_data.get(split, []))
    manifest = load_manifest(dataset_id)

    if "records" in manifest:
        records = [r for r in manifest["records"] if r.get("split") == split]
        if not records and case_ids:
            records = [r for r in manifest["records"] if r.get("case_id") in case_ids]
        return [_normalize_record(r) for r in records]

    entries = manifest.get("entries", [])
    selected = [e for e in entries if e.get("case_id") in case_ids]
    return [_normalize_record(e, split=split) for e in selected]


def _normalize_record(record: dict[str, Any], split: str | None = None) -> dict[str, Any]:
    mask_path = record.get("mask_path") or record.get("label_path")
    return {
        "split": record.get("split", split or "train"),
        "case_id": record["case_id"],
        "image_id": record.get("image_id", ""),
        "mask_id": record.get("mask_id", ""),
        "image_path": record["image_path"],
        "mask_path": mask_path,
        "version": record.get("version", ""),
        "label": record.get("label", "lung_nodule"),
    }


def load_image_array(path: str | Path) -> np.ndarray:
    path = resolve_dataset_path(path)
    suffix = path.name.lower()
    if suffix.endswith((".png", ".jpg", ".jpeg")):
        with Image.open(path) as img:
            return np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    if suffix.endswith((".nii", ".nii.gz")):
        if sitk is None:
            raise ImportError("SimpleITK is required for NIfTI images")
        arr = sitk.GetArrayFromImage(sitk.ReadImage(str(path))).astype(np.float32)
        if arr.ndim == 3:
            arr = arr[arr.shape[0] // 2]
        vmin, vmax = float(arr.min()), float(arr.max())
        if vmax > vmin:
            arr = (arr - vmin) / (vmax - vmin)
        return arr
    raise ValueError(f"Unsupported image format: {path}")


def load_mask_array(path: str | Path) -> np.ndarray:
    path = resolve_dataset_path(path)
    suffix = path.name.lower()
    if suffix.endswith((".png", ".jpg", ".jpeg")):
        with Image.open(path) as img:
            return (np.asarray(img.convert("L")) > 127).astype(np.float32)
    if suffix.endswith((".nii", ".nii.gz")):
        if sitk is None:
            raise ImportError("SimpleITK is required for NIfTI masks")
        arr = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
        if arr.ndim == 3:
            arr = arr[arr.shape[0] // 2]
        return (arr > 0).astype(np.float32)
    raise ValueError(f"Unsupported mask format: {path}")


class LungSegmentationDataset(Dataset):
    def __init__(self, split: str = "train", dataset_id: str = DATASET_ID, augment: bool | None = None):
        self.split = split
        self.dataset_id = dataset_id
        self.augment = split == "train" if augment is None else augment
        self.records = records_for_split(split, dataset_id)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        record = self.records[idx]
        image = load_image_array(record["image_path"])
        mask = load_mask_array(record["mask_path"])
        if self.augment:
            image, mask_u8 = augment_pair(image, mask.astype(np.uint8))
            mask = mask_u8.astype(np.float32)

        return {
            "image": torch.from_numpy(image).unsqueeze(0),
            "mask": torch.from_numpy(mask).unsqueeze(0),
            "case_id": record["case_id"],
            "image_id": record["image_id"],
            "mask_id": record["mask_id"],
            "label": record["label"],
            "version": record["version"],
        }


def build_dataloader(
    split: str = "train",
    dataset_id: str = DATASET_ID,
    batch_size: int = BATCH_SIZE,
    augment: bool | None = None,
    shuffle: bool | None = None,
) -> DataLoader:
    dataset = LungSegmentationDataset(split=split, dataset_id=dataset_id, augment=augment)
    if shuffle is None:
        shuffle = split == "train"
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=0)
