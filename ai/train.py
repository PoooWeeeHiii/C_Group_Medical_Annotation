"""Training entry — Day5: full U-Net training with best-checkpoint evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import (
    BATCH_SIZE,
    CHECKPOINT_DIR,
    DATASET_ID,
    EARLY_STOP_PATIENCE,
    EPOCHS,
    IN_CHANNELS,
    LEARNING_RATE,
    LOSS_BCE_WEIGHT,
    LOSS_DICE_WEIGHT,
    MODEL_ARCH,
    MODEL_ID,
    OUT_CHANNELS,
    RUNS_DIR,
    UNET_BASE_CHANNELS,
    WEIGHT_DECAY,
    checkpoint_path,
)
from ai.datasets.lung_dataset import build_dataloader, records_for_split
from ai.loss import bce_loss, combined_loss, dice_loss
from ai.metrics import dice_score, iou_score
from ai.models.unet import UNet2D


def select_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def evaluate(model: nn.Module, loader, device: torch.device) -> dict[str, float]:
    model.eval()
    total_loss = 0.0
    dice_values: list[float] = []
    iou_values: list[float] = []
    batches = 0

    with torch.no_grad():
        for batch in loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)
            logits = model(images)
            loss = combined_loss(logits, masks)
            total_loss += float(loss.item())
            batches += 1

            probs = torch.sigmoid(logits).cpu().numpy()
            targets = masks.cpu().numpy()
            for pred_map, target_map in zip(probs, targets):
                dice_values.append(dice_score(pred_map[0], target_map[0]))
                iou_values.append(iou_score(pred_map[0], target_map[0]))

    if batches == 0:
        return {"loss": 0.0, "dice": 0.0, "iou": 0.0}

    return {
        "loss": total_loss / batches,
        "dice": sum(dice_values) / len(dice_values),
        "iou": sum(iou_values) / len(iou_values),
    }


def train_one_epoch(model: nn.Module, loader, optimizer, device: torch.device) -> dict[str, float]:
    model.train()
    total_loss = 0.0
    dice_values: list[float] = []
    batches = 0

    for batch in loader:
        images = batch["image"].to(device)
        masks = batch["mask"].to(device)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = combined_loss(logits, masks)
        loss.backward()
        optimizer.step()

        total_loss += float(loss.item())
        batches += 1
        probs = torch.sigmoid(logits).detach().cpu().numpy()
        targets = masks.detach().cpu().numpy()
        for pred_map, target_map in zip(probs, targets):
            dice_values.append(dice_score(pred_map[0], target_map[0]))

    if batches == 0:
        return {"loss": 0.0, "dice": 0.0}

    return {"loss": total_loss / batches, "dice": sum(dice_values) / len(dice_values)}


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    best_val_dice: float,
    history: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_id": MODEL_ID,
            "model_arch": MODEL_ARCH,
            "epoch": epoch,
            "best_val_dice": best_val_dice,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "history": history,
            "config": {
                "in_channels": IN_CHANNELS,
                "out_channels": OUT_CHANNELS,
                "base_channels": UNET_BASE_CHANNELS,
                "learning_rate": LEARNING_RATE,
                "batch_size": BATCH_SIZE,
                "loss_dice_weight": LOSS_DICE_WEIGHT,
                "loss_bce_weight": LOSS_BCE_WEIGHT,
            },
        },
        path,
    )


def load_checkpoint(model: nn.Module, path: Path, device: torch.device) -> dict:
    checkpoint = torch.load(path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    return checkpoint


def run_training(epochs: int, dataset_id: str = DATASET_ID) -> Path:
    device = select_device()
    train_records = records_for_split("train", dataset_id)
    val_records = records_for_split("val", dataset_id)
    if not train_records:
        raise RuntimeError("No training samples found. Run scripts/convert_lung_examples.py first.")

    train_loader = build_dataloader("train", dataset_id=dataset_id)
    val_loader = build_dataloader("val", dataset_id=dataset_id, shuffle=False)
    test_loader = build_dataloader("test", dataset_id=dataset_id, shuffle=False)

    model = UNet2D(
        in_channels=IN_CHANNELS,
        out_channels=OUT_CHANNELS,
        base_channels=UNET_BASE_CHANNELS,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=5)

    best_val_dice = -1.0
    best_epoch = 0
    patience_left = EARLY_STOP_PATIENCE
    history: list[dict] = []
    ckpt_path = checkpoint_path(MODEL_ID)

    print(f"[Person B Day5] device={device}, train={len(train_records)}, val={len(val_records)}")
    print(f"Model params: {sum(p.numel() for p in model.parameters()):,}")

    for epoch in range(1, epochs + 1):
        train_metrics = train_one_epoch(model, train_loader, optimizer, device)
        val_metrics = evaluate(model, val_loader, device)
        record = {
            "epoch": epoch,
            "train_loss": train_metrics["loss"],
            "train_dice": train_metrics["dice"],
            "val_loss": val_metrics["loss"],
            "val_dice": val_metrics["dice"],
            "val_iou": val_metrics["iou"],
        }
        history.append(record)
        print(
            f"Epoch {epoch:03d} | "
            f"train loss={train_metrics['loss']:.4f} dice={train_metrics['dice']:.4f} | "
            f"val loss={val_metrics['loss']:.4f} dice={val_metrics['dice']:.4f} iou={val_metrics['iou']:.4f}"
        )

        scheduler.step(val_metrics["dice"])

        if val_metrics["dice"] > best_val_dice:
            best_val_dice = val_metrics["dice"]
            best_epoch = epoch
            patience_left = EARLY_STOP_PATIENCE
            save_checkpoint(ckpt_path, model, optimizer, epoch, best_val_dice, history)
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(f"Early stop at epoch {epoch} (best epoch={best_epoch}, val dice={best_val_dice:.4f})")
                break

    if ckpt_path.exists():
        checkpoint = load_checkpoint(model, ckpt_path, device)
        print(f"Loaded best checkpoint from epoch {checkpoint.get('epoch')} (val dice={checkpoint.get('best_val_dice', 0):.4f})")

    test_metrics = evaluate(model, test_loader, device)
    print(
        f"Test | loss={test_metrics['loss']:.4f} "
        f"dice={test_metrics['dice']:.4f} iou={test_metrics['iou']:.4f}"
    )

    run_dir = RUNS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "model_id": MODEL_ID,
        "dataset_id": dataset_id,
        "best_epoch": best_epoch,
        "best_val_dice": best_val_dice,
        "test_metrics": test_metrics,
        "history": history,
        "checkpoint": str(ckpt_path.relative_to(ROOT)),
    }
    (run_dir / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Checkpoint: {ckpt_path}")
    print(f"Run log: {run_dir / 'metrics.json'}")
    return ckpt_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train U-Net 2D for lung segmentation")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--dataset-id", default=DATASET_ID)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_training(epochs=args.epochs, dataset_id=args.dataset_id)


if __name__ == "__main__":
    main()
