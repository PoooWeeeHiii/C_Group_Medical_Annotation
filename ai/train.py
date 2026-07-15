"""Train platform 2.5D U-Net on exported dataset / manifest."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.config import CHECKPOINT_DIR, LEARNING_RATE, PROJECT_ROOT, RUNS_DIR
from ai.loss import combined_loss
from ai.models.unet import UNet2D
from ai.platform_unet_common import resize2d, select_training_slices, stack_context_slices

try:
    import SimpleITK as sitk
except ImportError:  # pragma: no cover
    sitk = None


class ExportSliceDataset(Dataset):
    """Axial 2.5D slices from nnUNet-style export folder or manifest records."""

    def __init__(
        self,
        *,
        export_dir: Path | None,
        records: list[dict] | None,
        split: str,
        image_size: tuple[int, int] = (320, 320),
        max_slices_per_volume: int = 64,
        num_classes: int = 6,
        context_radius: int = 1,
    ):
        self.samples: list[tuple[np.ndarray, np.ndarray]] = []
        self.image_size = image_size
        self.num_classes = num_classes
        self.context_radius = max(0, int(context_radius))
        self.in_channels = 2 * self.context_radius + 1
        pairs: list[tuple[Path, Path]] = []

        if export_dir and export_dir.is_dir():
            if split in {"val", "test"}:
                image_dirs = [export_dir / "imagesTs"]
            elif split == "all":
                image_dirs = [export_dir / "imagesTr", export_dir / "imagesTs"]
            else:
                image_dirs = [export_dir / "imagesTr"]
            for image_dir in image_dirs:
                label_dir = export_dir / ("labelsTs" if image_dir.name == "imagesTs" else "labelsTr")
                for image_path in sorted(image_dir.glob("*_0000.nii.gz")):
                    stem = image_path.name.replace("_0000.nii.gz", "")
                    label_path = label_dir / f"{stem}.nii.gz"
                    if label_path.exists():
                        pairs.append((image_path, label_path))
            # Use Ts as extra train data when train split is thin.
            if split in {"train", "all"} and len(pairs) < 4:
                for image_path in sorted((export_dir / "imagesTs").glob("*_0000.nii.gz")):
                    stem = image_path.name.replace("_0000.nii.gz", "")
                    label_path = export_dir / "labelsTs" / f"{stem}.nii.gz"
                    if label_path.exists():
                        pairs.append((image_path, label_path))
        elif records:
            for record in records:
                if split != "all" and record.get("split") and record.get("split") != split:
                    continue
                image_path = PROJECT_ROOT / str(record.get("image_path") or "")
                mask_path = PROJECT_ROOT / str(record.get("mask_path") or "")
                if image_path.exists() and mask_path.exists():
                    pairs.append((image_path, mask_path))

        if sitk is None:
            raise RuntimeError("SimpleITK is required for training")

        for image_path, mask_path in pairs:
            image_sitk = sitk.ReadImage(str(image_path))
            mask_sitk = sitk.ReadImage(str(mask_path))
            # Light spacing-aware resample to ~1mm in-plane when very coarse.
            try:
                sp = image_sitk.GetSpacing()
                if float(sp[0]) > 1.5 or float(sp[1]) > 1.5:
                    new_spacing = (min(float(sp[0]), 1.0), min(float(sp[1]), 1.0), float(sp[2]))
                    size = image_sitk.GetSize()
                    new_size = [
                        max(32, int(round(size[i] * sp[i] / new_spacing[i])))
                        for i in range(3)
                    ]
                    image_sitk = sitk.Resample(
                        image_sitk,
                        new_size,
                        sitk.Transform(),
                        sitk.sitkLinear,
                        image_sitk.GetOrigin(),
                        new_spacing,
                        image_sitk.GetDirection(),
                        0.0,
                        image_sitk.GetPixelID(),
                    )
                    mask_sitk = sitk.Resample(
                        mask_sitk,
                        image_sitk,
                        sitk.Transform(),
                        sitk.sitkNearestNeighbor,
                        0,
                        mask_sitk.GetPixelID(),
                    )
            except Exception:
                pass

            image = sitk.GetArrayFromImage(image_sitk).astype(np.float32)
            mask = sitk.GetArrayFromImage(mask_sitk).astype(np.int64)
            if image.ndim == 2:
                image = image[None, ...]
                mask = mask[None, ...]
            if image.shape[:3] != mask.shape[:3]:
                continue

            zs = select_training_slices(
                mask,
                num_classes=num_classes,
                max_slices_per_volume=max_slices_per_volume,
            )
            for z in zs:
                stack = stack_context_slices(image, z, self.context_radius)
                resized_channels = [
                    resize2d(stack[c], image_size, nearest=False) for c in range(stack.shape[0])
                ]
                img = np.stack(resized_channels, axis=0)
                msk = resize2d(mask[z].astype(np.float32), image_size, nearest=True)
                msk = np.clip(msk, 0, num_classes - 1).astype(np.int64)
                self.samples.append((img.astype(np.float32), msk))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        image, mask = self.samples[index]
        return {
            "image": torch.from_numpy(image).float(),
            "mask": torch.from_numpy(mask).long(),
        }


def _dice_metric(logits: torch.Tensor, target: torch.Tensor) -> float:
    pred = torch.argmax(logits, dim=1)
    target = target.long()
    scores = []
    num_classes = logits.shape[1]
    for class_id in range(1, num_classes):
        p = pred == class_id
        t = target == class_id
        inter = (p & t).sum().item()
        denom = p.sum().item() + t.sum().item()
        if denom > 0:
            scores.append(2.0 * inter / denom)
    return float(sum(scores) / len(scores)) if scores else 0.0


def train(
    *,
    dataset_id: str,
    model_id: str,
    epochs: int,
    batch_size: int,
    lr: float,
    num_classes: int,
    image_size: int,
    export_dir: str | None,
    context_radius: int = 1,
    max_slices_per_volume: int = 64,
) -> dict:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    context_radius = max(0, int(context_radius))
    in_channels = 2 * context_radius + 1

    resolved_export = None
    if export_dir:
        resolved_export = Path(export_dir)
        if not resolved_export.is_absolute():
            resolved_export = PROJECT_ROOT / resolved_export
    else:
        candidate = PROJECT_ROOT / "dataset" / "exports" / dataset_id
        if candidate.is_dir():
            resolved_export = candidate

    records = None
    manifest_path = PROJECT_ROOT / "dataset" / "splits" / f"{dataset_id}_manifest.json"
    if manifest_path.exists():
        records = json.loads(manifest_path.read_text(encoding="utf-8")).get("records") or []

    common = dict(
        export_dir=resolved_export,
        records=records,
        image_size=(image_size, image_size),
        num_classes=num_classes,
        context_radius=context_radius,
        max_slices_per_volume=max_slices_per_volume,
    )
    train_ds = ExportSliceDataset(split="train", **common)
    val_ds = ExportSliceDataset(split="val", **common)
    if len(train_ds) == 0:
        train_ds = ExportSliceDataset(split="all", **common)
    if len(train_ds) == 0:
        raise RuntimeError(
            f"No training slices found for dataset_id={dataset_id}. "
            "Export with materialize=true first (more cases → better Dice)."
        )
    if len(val_ds) == 0:
        val_ds = train_ds

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = UNet2D(in_channels=in_channels, out_channels=num_classes).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    history = []
    best_dice = -1.0
    ckpt_path = CHECKPOINT_DIR / f"{model_id}.pt"
    metrics_path = RUNS_DIR / f"{model_id}_metrics.json"

    print(
        json.dumps(
            {
                "event": "start",
                "in_channels": in_channels,
                "context_radius": context_radius,
                "train_slices": len(train_ds),
                "val_slices": len(val_ds),
                "image_size": image_size,
                "mode": "2.5D" if context_radius > 0 else "2D",
            }
        ),
        flush=True,
    )

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for batch in train_loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)
            optimizer.zero_grad()
            logits = model(images)
            loss = combined_loss(logits, masks)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * images.size(0)
        train_loss /= max(len(train_ds), 1)

        model.eval()
        val_loss = 0.0
        val_dice = 0.0
        count = 0
        with torch.no_grad():
            for batch in val_loader:
                images = batch["image"].to(device)
                masks = batch["mask"].to(device)
                logits = model(images)
                loss = combined_loss(logits, masks)
                val_loss += float(loss.item()) * images.size(0)
                val_dice += _dice_metric(logits, masks) * images.size(0)
                count += images.size(0)
        val_loss /= max(count, 1)
        val_dice /= max(count, 1)
        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_dice": val_dice,
            "time": time.time(),
        }
        history.append(row)
        print(json.dumps({"event": "epoch", **row}), flush=True)

        if val_dice >= best_dice:
            best_dice = val_dice
            torch.save(
                {
                    "model_id": model_id,
                    "dataset_id": dataset_id,
                    "num_classes": num_classes,
                    "image_size": image_size,
                    "in_channels": in_channels,
                    "context_radius": context_radius,
                    "architecture": "unet_2_5d" if context_radius > 0 else "unet_2d",
                    "state_dict": model.state_dict(),
                    "val_dice": best_dice,
                    "epoch": epoch,
                },
                ckpt_path,
            )

    metrics = {
        "model_id": model_id,
        "dataset_id": dataset_id,
        "best_val_dice": best_dice,
        "epochs": epochs,
        "num_classes": num_classes,
        "image_size": image_size,
        "in_channels": in_channels,
        "context_radius": context_radius,
        "architecture": "unet_2_5d" if context_radius > 0 else "unet_2d",
        "train_slices": len(train_ds),
        "checkpoint": str(ckpt_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "history": history,
        "note": "Prefer TotalSeg/nnUNet for production; this is a platform 2.5D demo model.",
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps({"event": "done", "metrics": metrics}), flush=True)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train platform 2.5D U-Net")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--model-id", default="ModelUNet0001")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=LEARNING_RATE)
    parser.add_argument("--num-classes", type=int, default=6)
    parser.add_argument("--image-size", type=int, default=320)
    parser.add_argument("--context-radius", type=int, default=1, help="2.5D neighbor radius (1 => 3 channels)")
    parser.add_argument("--max-slices-per-volume", type=int, default=64)
    parser.add_argument("--export-dir", default=None)
    args = parser.parse_args()
    train(
        dataset_id=args.dataset_id,
        model_id=args.model_id,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        num_classes=args.num_classes,
        image_size=args.image_size,
        export_dir=args.export_dir,
        context_radius=args.context_radius,
        max_slices_per_volume=args.max_slices_per_volume,
    )


if __name__ == "__main__":
    main()
