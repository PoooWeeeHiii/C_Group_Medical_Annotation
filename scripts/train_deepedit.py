"""Train a contract-aligned DeepEdit MONAI UNet from TotalSeg spleen CT+mask.

Reads Dataset606_TotalSeg_Spleen (preferred) under TOTALSEG_ROOT / nnUNet_raw,
simulates positive/negative clicks and a degraded current_mask, then writes
models/deepedit/deepedit_unet.pth matching ai/deepedit_service.py input contract:

  channels = [CT_norm, positive, negative, current_mask]  # [B, 4, D, H, W]

Usage (CPU env example):
  $env:TOTALSEG_ROOT = "D:\\hm_2_totalseg"
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\train_deepedit.py --limit 8 --epochs 3 --crop 64 96 96
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "models" / "deepedit" / "config.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "models" / "deepedit" / "deepedit_unet.pth"
DEFAULT_TOTALSEG = Path(os.environ.get("TOTALSEG_ROOT", r"D:\hm_2_totalseg"))
SPLEEN_DATASET = "Dataset606_TotalSeg_Spleen"


def _load_config(path: Path) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    return {
        "format": "monai_unet_checkpoint",
        "path": "models/deepedit/deepedit_unet.pth",
        "in_channels": 4,
        "out_channels": 2,
        "channels": [16, 32, 64, 128, 256],
        "strides": [2, 2, 2, 2],
        "num_res_units": 2,
        "strict": True,
    }


def _normalize_ct(array: np.ndarray) -> np.ndarray:
    return np.clip((array + 1000.0) / 2000.0, 0.0, 1.0).astype(np.float32, copy=False)


def _read_nifti(path: Path) -> np.ndarray:
    try:
        import nibabel as nib

        array = np.asanyarray(nib.load(str(path)).dataobj)
        # nibabel is typically (X, Y, Z); convert to (Z, Y, X) to match SimpleITK / DeepEdit service.
        if array.ndim == 3:
            array = np.transpose(array, (2, 1, 0))
        elif array.ndim == 2:
            array = array.reshape((1, array.shape[1], array.shape[0]))
        return array.astype(np.float32, copy=False)
    except Exception:
        import SimpleITK as sitk

        array = sitk.GetArrayFromImage(sitk.ReadImage(str(path))).astype(np.float32, copy=False)
        if array.ndim == 2:
            array = array.reshape((1, array.shape[0], array.shape[1]))
        return array


def _discover_pairs(root: Path, limit: int | None) -> list[tuple[Path, Path]]:
    dataset_dir = root / "nnUNet_raw" / SPLEEN_DATASET
    images_tr = dataset_dir / "imagesTr"
    labels_tr = dataset_dir / "labelsTr"
    if not images_tr.is_dir() or not labels_tr.is_dir():
        raise SystemExit(
            f"Spleen dataset not found under {dataset_dir}. "
            "Run scripts/prepare_totalseg_nnunet.py convert --parts spleen first."
        )
    pairs: list[tuple[Path, Path]] = []
    for image_path in sorted(images_tr.glob("*_0000.nii.gz")):
        case_id = image_path.name.replace("_0000.nii.gz", "")
        label_path = labels_tr / f"{case_id}.nii.gz"
        if not label_path.exists():
            continue
        pairs.append((image_path, label_path))
    if not pairs:
        raise SystemExit(f"No CT/mask pairs found in {dataset_dir}")
    # Caller may skip empty labels; oversample candidates when limit is set.
    if limit is not None:
        pairs = pairs[: max(limit * 3, limit)]
    return pairs


def _sample_points(mask: np.ndarray, count: int, *, foreground: bool, rng: random.Random) -> list[tuple[int, int, int]]:
    if foreground:
        coords = np.argwhere(mask > 0)
    else:
        # Prefer near-boundary background for harder negatives.
        from scipy import ndimage

        dilated = ndimage.binary_dilation(mask > 0, iterations=2)
        band = np.logical_and(dilated, mask <= 0)
        coords = np.argwhere(band)
        if coords.size == 0:
            coords = np.argwhere(mask <= 0)
    if coords.size == 0:
        return []
    indices = [rng.randrange(len(coords)) for _ in range(count)]
    # coords are (z, y, x); convert to (x, y, z) for channel drawing consistency with service
    return [(int(coords[i][2]), int(coords[i][1]), int(coords[i][0])) for i in indices]


def _draw_sphere(channel: np.ndarray, point_xyz: tuple[int, int, int], radius: int = 3) -> None:
    x, y, z = point_xyz
    depth, height, width = channel.shape
    z0, z1 = max(0, z - radius), min(depth, z + radius + 1)
    y0, y1 = max(0, y - radius), min(height, y + radius + 1)
    x0, x1 = max(0, x - radius), min(width, x + radius + 1)
    zz, yy, xx = np.ogrid[z0:z1, y0:y1, x0:x1]
    channel[z0:z1, y0:y1, x0:x1][(zz - z) ** 2 + (yy - y) ** 2 + (xx - x) ** 2 <= radius * radius] = 1.0


def _degrade_mask(gt: np.ndarray, rng: random.Random) -> np.ndarray:
    from scipy import ndimage

    mask = (gt > 0).astype(np.uint8)
    mode = rng.choice(["erode", "dilate", "hole", "drop"])
    if mode == "erode":
        return ndimage.binary_erosion(mask, iterations=rng.randint(1, 2)).astype(np.float32)
    if mode == "dilate":
        return ndimage.binary_dilation(mask, iterations=rng.randint(1, 2)).astype(np.float32)
    if mode == "hole":
        degraded = mask.astype(np.float32)
        coords = np.argwhere(mask > 0)
        if len(coords):
            cz, cy, cx = coords[rng.randrange(len(coords))]
            r = rng.randint(4, 10)
            z0, z1 = max(0, cz - r), min(mask.shape[0], cz + r + 1)
            y0, y1 = max(0, cy - r), min(mask.shape[1], cy + r + 1)
            x0, x1 = max(0, cx - r), min(mask.shape[2], cx + r + 1)
            degraded[z0:z1, y0:y1, x0:x1] = 0
        return degraded
    # drop: empty current mask → rely on clicks
    return np.zeros_like(mask, dtype=np.float32)


def _crop_roi(
    ct: np.ndarray,
    gt: np.ndarray,
    current: np.ndarray,
    pos: np.ndarray,
    neg: np.ndarray,
    crop_dhw: tuple[int, int, int],
    rng: random.Random,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    depth, height, width = ct.shape
    cd, ch, cw = crop_dhw
    cd, ch, cw = min(cd, depth), min(ch, height), min(cw, width)

    coords = np.argwhere(gt > 0)
    if len(coords):
        center = coords[rng.randrange(len(coords))]
        cz, cy, cx = int(center[0]), int(center[1]), int(center[2])
    else:
        cz, cy, cx = depth // 2, height // 2, width // 2

    z0 = max(0, min(depth - cd, cz - cd // 2))
    y0 = max(0, min(height - ch, cy - ch // 2))
    x0 = max(0, min(width - cw, cx - cw // 2))
    z1, y1, x1 = z0 + cd, y0 + ch, x0 + cw
    sl = (slice(z0, z1), slice(y0, y1), slice(x0, x1))
    return ct[sl], gt[sl], current[sl], pos[sl], neg[sl]


def _build_sample(
    ct: np.ndarray,
    gt: np.ndarray,
    crop_dhw: tuple[int, int, int],
    rng: random.Random,
    n_pos: int,
    n_neg: int,
) -> tuple[np.ndarray, np.ndarray]:
    gt_bin = (gt > 0).astype(np.float32)
    current = _degrade_mask(gt_bin, rng)
    pos = np.zeros_like(gt_bin, dtype=np.float32)
    neg = np.zeros_like(gt_bin, dtype=np.float32)
    for point in _sample_points(gt_bin, n_pos, foreground=True, rng=rng):
        _draw_sphere(pos, point)
    for point in _sample_points(gt_bin, n_neg, foreground=False, rng=rng):
        _draw_sphere(neg, point)

    ct_c, gt_c, cur_c, pos_c, neg_c = _crop_roi(ct, gt_bin, current, pos, neg, crop_dhw, rng)
    channels = np.stack([_normalize_ct(ct_c), pos_c, neg_c, cur_c], axis=0).astype(np.float32)
    target = gt_c.astype(np.float32)
    return channels, target


def _dice_bce_loss(logits, target):
    import torch
    import torch.nn.functional as F

    # logits: [B, 2, D, H, W], use foreground channel 1
    fg_logits = logits[:, 1:2]
    probs = torch.sigmoid(fg_logits)
    target = target.unsqueeze(1) if target.ndim == 4 else target
    bce = F.binary_cross_entropy_with_logits(fg_logits, target)
    dims = (2, 3, 4)
    intersection = (probs * target).sum(dim=dims)
    union = probs.sum(dim=dims) + target.sum(dim=dims)
    dice = 1.0 - ((2 * intersection + 1e-5) / (union + 1e-5)).mean()
    return bce + dice


def main() -> int:
    parser = argparse.ArgumentParser(description="Train DeepEdit from TotalSeg spleen")
    parser.add_argument("--totalseg-root", type=Path, default=DEFAULT_TOTALSEG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=12, help="Max training cases")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--crop", type=int, nargs=3, default=[48, 96, 96], metavar=("D", "H", "W"))
    parser.add_argument("--pos-clicks", type=int, default=4)
    parser.add_argument("--neg-clicks", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", type=str, default="auto")
    args = parser.parse_args()

    try:
        import torch
        from monai.networks.nets import UNet
        from scipy import ndimage  # noqa: F401 — required by degrade/sample helpers
    except ImportError as exc:
        raise SystemExit("Need torch, monai, scipy, SimpleITK. Install from requirements.txt.") from exc

    rng = random.Random(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    config = _load_config(args.config)
    device_name = args.device
    if device_name == "auto":
        device_name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device_name)

    pairs = _discover_pairs(args.totalseg_root, args.limit)
    print(f"Training on {len(pairs)} cases from {args.totalseg_root / 'nnUNet_raw' / SPLEEN_DATASET}")
    print(f"Device={device} crop={tuple(args.crop)} epochs={args.epochs}")

    model = UNet(
        spatial_dims=3,
        in_channels=int(config.get("in_channels", 4)),
        out_channels=int(config.get("out_channels", 2)),
        channels=tuple(int(v) for v in config.get("channels", [16, 32, 64, 128, 256])),
        strides=tuple(int(v) for v in config.get("strides", [2, 2, 2, 2])),
        num_res_units=int(config.get("num_res_units", 2)),
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    # Preload volumes (small limit by default).
    loaded: list[tuple[np.ndarray, np.ndarray]] = []
    for image_path, label_path in pairs:
        if args.limit is not None and len(loaded) >= args.limit:
            break
        ct = _read_nifti(image_path)
        gt = _read_nifti(label_path)
        if ct.shape != gt.shape:
            print(f"Skip shape mismatch: {image_path.name} {ct.shape} vs {gt.shape}")
            continue
        if not np.any(gt > 0):
            print(f"Skip empty label: {label_path.name}")
            continue
        loaded.append((ct, gt))
        print(f"  loaded {image_path.name} shape={ct.shape}")
    if not loaded:
        raise SystemExit("No usable volumes after filtering")

    crop_dhw = (int(args.crop[0]), int(args.crop[1]), int(args.crop[2]))
    model.train()
    for epoch in range(1, args.epochs + 1):
        epoch_loss = 0.0
        steps = 0
        order = list(range(len(loaded)))
        rng.shuffle(order)
        for idx in order:
            ct, gt = loaded[idx]
            channels, target = _build_sample(ct, gt, crop_dhw, rng, args.pos_clicks, args.neg_clicks)
            x = torch.from_numpy(channels[None]).to(device=device, dtype=torch.float32)
            y = torch.from_numpy(target[None]).to(device=device, dtype=torch.float32)
            optimizer.zero_grad(set_to_none=True)
            logits = model(x)
            loss = _dice_bce_loss(logits, y)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item())
            steps += 1
        avg = epoch_loss / max(steps, 1)
        print(f"epoch {epoch}/{args.epochs} loss={avg:.4f}")

    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": model.state_dict(),
        "config": {
            "format": "monai_unet_checkpoint",
            "in_channels": int(config.get("in_channels", 4)),
            "out_channels": int(config.get("out_channels", 2)),
            "channels": list(config.get("channels", [16, 32, 64, 128, 256])),
            "strides": list(config.get("strides", [2, 2, 2, 2])),
            "num_res_units": int(config.get("num_res_units", 2)),
        },
        "train_meta": {
            "dataset": SPLEEN_DATASET,
            "cases": len(loaded),
            "epochs": args.epochs,
            "crop": list(crop_dhw),
            "totalseg_root": str(args.totalseg_root),
        },
    }
    torch.save(payload, str(output))

    config_out = dict(config)
    config_out.update(payload["config"])
    config_out["path"] = "models/deepedit/deepedit_unet.pth"
    config_path = args.config if args.config.is_absolute() else PROJECT_ROOT / args.config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config_out, f, indent=2)
        f.write("\n")

    print(f"Wrote checkpoint {output}")
    print(f"Updated config {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
