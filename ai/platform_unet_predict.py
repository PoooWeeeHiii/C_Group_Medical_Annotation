"""Inference for platform-trained 2.5D U-Net checkpoints (+ 3D postprocess)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from fastapi import HTTPException

from ai.config import CHECKPOINT_DIR, PROJECT_ROOT
from ai.models.unet import UNet2D
from ai.platform_unet_common import postprocess_multiclass_volume, resize2d, stack_context_slices


def _resolve_checkpoint(model_id: str, checkpoint_path: str | None) -> Path:
    if checkpoint_path:
        path = Path(checkpoint_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return path
    candidates = [
        CHECKPOINT_DIR / f"{model_id}.pt",
        PROJECT_ROOT / "ai" / "checkpoints" / f"{model_id}.pt",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise HTTPException(status_code=404, detail=f"platform_unet checkpoint not found for {model_id}")


def predict_platform_unet_mask(
    volume: np.ndarray,
    *,
    model_id: str,
    checkpoint_path: str | None = None,
    label: str = "label",
    min_voxels_per_class: int = 64,
    apply_postprocess: bool = True,
) -> np.ndarray:
    ckpt_file = _resolve_checkpoint(model_id, checkpoint_path)
    payload = torch.load(ckpt_file, map_location="cpu")
    num_classes = int(payload.get("num_classes") or 6)
    image_size = int(payload.get("image_size") or 320)
    context_radius = int(payload.get("context_radius") if payload.get("context_radius") is not None else 0)
    in_channels = int(payload.get("in_channels") or (2 * context_radius + 1))
    # Backward compat: old checkpoints were single-channel 2D.
    if "in_channels" not in payload and "context_radius" not in payload:
        in_channels = 1
        context_radius = 0

    model = UNet2D(in_channels=in_channels, out_channels=num_classes)
    try:
        model.load_state_dict(payload["state_dict"])
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"platform_unet checkpoint incompatible with current architecture "
                f"(in_channels={in_channels}): {exc}. Re-train after upgrading to 2.5D."
            ),
        ) from exc
    model.eval()

    vol = np.asarray(volume)
    if vol.ndim == 2:
        vol = vol[None, ...]
    depth, height, width = vol.shape[:3]
    out = np.zeros((depth, height, width), dtype=np.uint8)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    with torch.no_grad():
        for z in range(depth):
            if context_radius > 0 or in_channels > 1:
                stack = stack_context_slices(vol, z, context_radius)
                # If checkpoint expects different channel count, pad/crop.
                if stack.shape[0] < in_channels:
                    pad = np.repeat(stack[-1:], in_channels - stack.shape[0], axis=0)
                    stack = np.concatenate([stack, pad], axis=0)
                elif stack.shape[0] > in_channels:
                    mid = stack.shape[0] // 2
                    half = in_channels // 2
                    stack = stack[mid - half : mid - half + in_channels]
                channels = [resize2d(stack[c], (image_size, image_size), nearest=False) for c in range(stack.shape[0])]
                tensor = torch.from_numpy(np.stack(channels, axis=0)[None, ...]).float().to(device)
            else:
                from ai.platform_unet_common import hu_normalize

                slice_img = hu_normalize(vol[z])
                resized = resize2d(slice_img, (image_size, image_size), nearest=False)
                tensor = torch.from_numpy(resized[None, None, ...]).float().to(device)

            logits = model(tensor)
            pred = torch.argmax(logits, dim=1)[0].cpu().numpy().astype(np.int64)
            pred_full = resize2d(pred.astype(np.float32), (height, width), nearest=True).astype(np.uint8)
            out[z] = pred_full

    if apply_postprocess:
        out = postprocess_multiclass_volume(
            out,
            min_voxels_per_class=min_voxels_per_class,
            fill_holes=True,
            keep_largest_per_class=True,
        )

    if not np.any(out):
        raise HTTPException(status_code=422, detail="platform_unet produced an empty mask")
    return out
