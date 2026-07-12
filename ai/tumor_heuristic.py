"""Suspected-tumor heuristic from TotalSeg organ residual soft tissue.

Not a diagnostic tumor model. Pipeline:
  body ∩ soft-tissue HU − organs − bone − lung air → connected components → top candidates
"""
from __future__ import annotations

from typing import Any

import numpy as np


def estimate_body_mask(ct: np.ndarray) -> np.ndarray:
    """Largest non-air body envelope (axial fill + light close/dilate)."""
    from scipy import ndimage as ndi

    data = np.asarray(ct)
    body_seed = data > -850
    labeled, component_count = ndi.label(body_seed, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if component_count > 0:
        sizes = np.bincount(labeled.reshape(-1))
        largest = int(np.argmax(sizes[1:]) + 1)
        body_seed = labeled == largest

    envelope = np.zeros_like(body_seed, dtype=bool)
    for z in range(body_seed.shape[0]):
        envelope[z] = ndi.binary_fill_holes(body_seed[z])
    envelope = ndi.binary_closing(envelope, structure=np.ones((3, 5, 5), dtype=bool), iterations=1)
    envelope = ndi.binary_dilation(envelope, structure=np.ones((3, 5, 5), dtype=bool), iterations=1)
    return envelope


def merge_organ_union(organ_masks: dict[str, np.ndarray]) -> np.ndarray:
    merged: np.ndarray | None = None
    for mask in organ_masks.values():
        part = np.asarray(mask) > 0
        merged = part if merged is None else np.logical_or(merged, part)
    if merged is None:
        raise ValueError("organ_masks is empty")
    return merged


def _voxel_volume_ml(spacing: tuple[float, float, float] | list[float]) -> float:
    # SimpleITK spacing is (x, y, z) mm; array is (z, y, x). Product is still voxel volume.
    sx, sy, sz = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
    return abs(sx * sy * sz) / 1000.0


def predict_suspected_tumor(
    ct: np.ndarray,
    organ_masks: dict[str, np.ndarray],
    spacing: tuple[float, float, float] | list[float],
    *,
    hu_low: float = -80.0,
    hu_high: float = 180.0,
    bone_hu: float = 250.0,
    lung_hu_low: float = -980.0,
    lung_hu_high: float = -320.0,
    rind_mm: float = 12.0,
    min_volume_ml: float = 0.8,
    max_volume_ml: float = 400.0,
    max_components: int = 8,
    min_voxels: int = 80,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Return binary suspected-tumor mask [D,H,W] and metadata."""
    from scipy import ndimage as ndi

    data = np.asarray(ct, dtype=np.float32)
    if not organ_masks:
        raise ValueError("organ_masks required for residual tumor heuristic")

    body = estimate_body_mask(data)
    organs = merge_organ_union(organ_masks)

    # Prefer TotalSeg lung lobes when present; else HU air pocket inside body.
    lung_keys = [name for name in organ_masks if str(name).lower().startswith("lung")]
    if lung_keys:
        lung = merge_organ_union({k: organ_masks[k] for k in lung_keys})
    else:
        lung = body & (data > lung_hu_low) & (data < lung_hu_high)

    bone = body & (data > bone_hu)
    soft = body & (data >= hu_low) & (data <= hu_high)

    # Drop subcutaneous rind (distance from body surface).
    sx, sy, sz = float(spacing[0]), float(spacing[1]), float(spacing[2])
    dist = ndi.distance_transform_edt(body, sampling=(sz, sy, sx))
    inner_body = dist >= max(0.0, float(rind_mm))

    residual = soft & inner_body & ~organs & ~bone & ~lung

    # Drop thin sheet noise.
    residual = ndi.binary_opening(residual, structure=np.ones((3, 3, 3), dtype=bool), iterations=1)
    residual = ndi.binary_closing(residual, structure=np.ones((3, 3, 3), dtype=bool), iterations=1)

    labeled, component_count = ndi.label(residual, structure=np.ones((3, 3, 3), dtype=np.uint8))
    voxel_ml = _voxel_volume_ml(spacing)
    kept: list[tuple[int, int, float]] = []
    if component_count > 0:
        counts = np.bincount(labeled.reshape(-1))
        for comp_id in range(1, component_count + 1):
            voxels = int(counts[comp_id])
            if voxels < min_voxels:
                continue
            vol_ml = voxels * voxel_ml
            if vol_ml < min_volume_ml or vol_ml > max_volume_ml:
                continue
            kept.append((comp_id, voxels, vol_ml))

    kept.sort(key=lambda item: item[1], reverse=True)
    kept = kept[: max(1, int(max_components))]

    out = np.zeros(data.shape[:3], dtype=np.uint8)
    for comp_id, _voxels, _vol in kept:
        out[labeled == comp_id] = 1

    meta: dict[str, Any] = {
        "method": "tumor_residual_heuristic",
        "diagnostic": False,
        "note": "suspected residual soft-tissue candidates (not a tumor diagnosis)",
        "component_count": len(kept),
        "component_count_before_filter": int(component_count),
        "volume_ml": float(sum(item[2] for item in kept)),
        "voxel_count": int(np.count_nonzero(out)),
        "voxel_ml": float(voxel_ml),
        "hu_window": [float(hu_low), float(hu_high)],
        "rind_mm": float(rind_mm),
        "min_volume_ml": float(min_volume_ml),
        "max_volume_ml": float(max_volume_ml),
        "max_components": int(max_components),
        "organ_labels_used": sorted(str(k) for k in organ_masks.keys()),
        "components": [
            {"id": int(comp_id), "voxels": int(voxels), "volume_ml": round(float(vol_ml), 3)}
            for comp_id, voxels, vol_ml in kept
        ],
    }
    return out, meta
