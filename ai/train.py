"""Training entry — Day3: Dataset + DataLoader; Day4: full training loop."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import BATCH_SIZE, CHECKPOINT_DIR, DATASET_ID, EPOCHS, LEARNING_RATE, MODEL_ID, RUNS_DIR
from ai.datasets.lung_dataset import build_dataloader, records_for_split


def main() -> None:
    print(f"[Person B Day3] model={MODEL_ID}, dataset={DATASET_ID}")
    print(f"Planned training: epochs={EPOCHS}, batch={BATCH_SIZE}, lr={LEARNING_RATE}")
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    for split in ("train", "val", "test"):
        records = records_for_split(split, DATASET_ID)
        loader = build_dataloader(split=split, dataset_id=DATASET_ID)
        print(f"{split}: {len(records)} samples, {len(loader)} batches")
        if records:
            batch = next(iter(loader))
            print(
                f"  sample batch image={tuple(batch['image'].shape)} "
                f"mask={tuple(batch['mask'].shape)} case={batch['case_id']}"
            )

    print("Day4: wire UNet + Dice+BCE training loop on these DataLoaders.")


if __name__ == "__main__":
    main()
