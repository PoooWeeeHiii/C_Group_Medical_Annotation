#!/usr/bin/env python3
"""Smoke-test LungSegmentationDataset against local dataset/splits JSON."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.config import DATASET_ID
from ai.datasets.lung_dataset import LungSegmentationDataset, records_for_split


def main() -> None:
    for split in ("train", "val", "test"):
        records = records_for_split(split, DATASET_ID)
        ds = LungSegmentationDataset(split=split, dataset_id=DATASET_ID)
        print(f"{split}: manifest records={len(records)}, dataset len={len(ds)}")
        if len(ds) == 0:
            continue
        item = ds[0]
        print(
            f"  {item['case_id']} image={tuple(item['image'].shape)} "
            f"mask={tuple(item['mask'].shape)} label={item['label']}"
        )


if __name__ == "__main__":
    main()
