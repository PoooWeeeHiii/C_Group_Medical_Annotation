"""Training entry — Day1 skeleton."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import BATCH_SIZE, CHECKPOINT_DIR, EPOCHS, LEARNING_RATE, MODEL_ID, RUNS_DIR


def main():
    print(f"[Person B Day1] model={MODEL_ID}, epochs={EPOCHS}, batch={BATCH_SIZE}, lr={LEARNING_RATE}")
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    print("Flow: Dataset -> DataLoader -> UNet -> Dice+BCE -> Train -> Val -> Best checkpoint")
    print("Day4: implement training loop.")


if __name__ == "__main__":
    main()
