"""Shared helpers for platform 2.5D U-Net train / infer / postprocess."""
from __future__ import annotations

from typing import Iterable

import numpy as np


def hu_normalize(arr: np.ndarray, hu_min: float = -1000.0, hu_max: float = 400.0) -> np.ndarray:
    clipped = np.clip(arr.astype(np.float32), hu_min, hu_max)
    return (clipped - hu_min) / max(hu_max - hu_min, 1e-6)


def resize2d(arr: np.ndarray, size: tuple[int, int], *, nearest: bool = False) -> np.ndarray:
    from PIL import Image

    h, w = int(size[0]), int(size[1])
    img = Image.fromarray(arr.astype(np.float32), mode="F")
    resample = Image.NEAREST if nearest else Image.BILINEAR
    out = img.resize((w, h), resample=resample)
    result = np.asarray(out, dtype=np.float32)
    if nearest:
        return np.rint(result).astype(np.int64)
    return result


def stack_context_slices(volume: np.ndarray, z: int, context_radius: int) -> np.ndarray:
    """Build (C,H,W) stack: neighboring axial slices around z. C = 2*radius+1."""
    depth = int(volume.shape[0])
    radius = max(0, int(context_radius))
    channels: list[np.ndarray] = []
    for offset in range(-radius, radius + 1):
        zz = min(max(z + offset, 0), depth - 1)
        channels.append(hu_normalize(volume[zz]))
    return np.stack(channels, axis=0).astype(np.float32)


def select_training_slices(
    mask: np.ndarray,
    *,
    num_classes: int,
    max_slices_per_volume: int = 64,
    max_per_class: int = 16,
    background_quota: int = 8,
) -> list[int]:
    """Prefer foreground slices, ensure each class appears when possible."""
    depth = int(mask.shape[0])
    selected: list[int] = []
    seen: set[int] = set()

    def _add(indices: Iterable[int], limit: int | None = None) -> None:
        count = 0
        for z in indices:
            if z in seen:
                continue
            seen.add(int(z))
            selected.append(int(z))
            count += 1
            if limit is not None and count >= limit:
                break
            if len(selected) >= max_slices_per_volume:
                break

    # 1) Cover each class with dedicated slices.
    for class_id in range(1, max(2, num_classes)):
        if len(selected) >= max_slices_per_volume:
            break
        hits = [z for z in range(depth) if np.any(mask[z] == class_id)]
        if not hits:
            continue
        step = max(1, len(hits) // max(1, max_per_class))
        _add(hits[::step], limit=max_per_class)

    # 2) Add remaining any-foreground slices.
    if len(selected) < max_slices_per_volume:
        fg = [z for z in range(depth) if np.any(mask[z] > 0) and z not in seen]
        if fg:
            step = max(1, len(fg) // max(1, max_slices_per_volume - len(selected)))
            _add(fg[::step])

    # 3) A few background slices for class balance.
    if background_quota > 0 and len(selected) < max_slices_per_volume:
        bg = [z for z in range(depth) if not np.any(mask[z] > 0) and z not in seen]
        if bg:
            step = max(1, len(bg) // background_quota)
            _add(bg[::step], limit=background_quota)

    if not selected:
        selected = list(range(min(depth, max_slices_per_volume)))
    return sorted(selected)[:max_slices_per_volume]


def postprocess_multiclass_volume(
    mask: np.ndarray,
    *,
    min_voxels_per_class: int = 64,
    fill_holes: bool = True,
    keep_largest_per_class: bool = True,
) -> np.ndarray:
    """3D cleanup: fill holes, drop tiny components, optionally keep largest blob/class."""
    try:
        from scipy import ndimage as ndi
    except ImportError:
        return mask.astype(np.uint8, copy=False)

    out = np.zeros_like(mask, dtype=np.uint8)
    structure = np.ones((3, 3, 3), dtype=bool)
    for class_id in sorted(int(v) for v in np.unique(mask) if int(v) > 0):
        binary = mask == class_id
        if fill_holes:
            # Fill holes slice-wise (cheaper / stabler than full 3D for CT organs).
            filled = np.empty_like(binary)
            for z in range(binary.shape[0]):
                filled[z] = ndi.binary_fill_holes(binary[z])
            binary = filled
        labeled, n_comp = ndi.label(binary, structure=structure)
        if n_comp == 0:
            continue
        sizes = ndi.sum(binary, labeled, index=list(range(1, n_comp + 1)))
        if np.isscalar(sizes):
            sizes = [float(sizes)]
        keep_ids: list[int] = []
        if keep_largest_per_class:
            best = int(np.argmax(sizes)) + 1
            if float(sizes[best - 1]) >= float(min_voxels_per_class):
                keep_ids = [best]
        else:
            keep_ids = [i + 1 for i, s in enumerate(sizes) if float(s) >= float(min_voxels_per_class)]
        if not keep_ids:
            continue
        out[np.isin(labeled, keep_ids)] = np.uint8(class_id)
    return out
