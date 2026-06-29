"""Dataset loader — reads dataset/splits/Dataset0001_split.json on Day3."""
from __future__ import annotations

from pathlib import Path

from ai.config import DATASET_ROOT, SPLITS_DIR


class LungSegmentationDataset:
    def __init__(self, split: str = "train", dataset_id: str = "Dataset0001"):
        self.split = split
        self.dataset_id = dataset_id
        self.split_file = SPLITS_DIR / f"{dataset_id}_split.json"
        self.root = DATASET_ROOT

    def __len__(self) -> int:
        return 0

    def __getitem__(self, idx: int):
        raise NotImplementedError("Day3: load image + mask from dataset/images and dataset/labels")
