"""Helpers for extended system tests: tiny NIfTI upload + RLE masks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .conftest import auth_headers


def make_tiny_nifti(path: Path, shape: tuple[int, int, int] = (16, 32, 32)) -> Path:
    """Create a tiny synthetic CT-like NIfTI (D,H,W)."""
    import nibabel as nib

    depth, height, width = shape
    # Simple gradient + blob so HU-like values exist.
    zz, yy, xx = np.mgrid[0:depth, 0:height, 0:width]
    data = ((xx + yy + zz) % 200).astype(np.int16) - 100
    data[depth // 4 : 3 * depth // 4, height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = 80
    img = nib.Nifti1Image(data, affine=np.eye(4))
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(img, str(path))
    return path


def rle_box(width: int, height: int, x0: int, y0: int, x1: int, y1: int, value: int = 1) -> list[list[int]]:
    """Build RLE runs for a filled rectangle on a blank canvas."""
    flat = np.zeros(width * height, dtype=np.uint8)
    for y in range(y0, y1):
        flat[y * width + x0 : y * width + x1] = value
    runs: list[list[int]] = []
    current = int(flat[0])
    count = 1
    for v in flat[1:]:
        iv = int(v)
        if iv == current:
            count += 1
        else:
            runs.append([current, count])
            current = iv
            count = 1
    runs.append([current, count])
    return runs


def upload_nifti(
    client: httpx.Client,
    nifti_path: Path,
    *,
    token: str | None = None,
    patient_id: str = "SYSTEM_TEST_PATIENT",
) -> dict[str, Any]:
    headers = auth_headers(token) if token else {}
    with nifti_path.open("rb") as f:
        files = {"file": (nifti_path.name, f, "application/gzip")}
        data = {"source_group": "system_test", "patient_id": patient_id, "modality": "CT"}
        r = client.post("/api/upload", headers=headers, files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    return body


def volume_hw(client: httpx.Client, image_id: str) -> tuple[int, int, int]:
    """Return (width, height, slice_count) from volume metadata."""
    r = client.get(f"/api/image/{image_id}/volume")
    assert r.status_code == 200, r.text
    body = r.json()
    width = int(body.get("width") or 0)
    height = int(body.get("height") or 0)
    slices = int(body.get("slice_count") or body.get("depth") or 1)
    assert width > 0 and height > 0
    return width, height, slices


def save_slice_mask(
    client: httpx.Client,
    *,
    token: str,
    case_id: str,
    image_id: str,
    width: int | None = None,
    height: int | None = None,
    slice_index: int = 0,
    label: str = "spleen",
    label_id: int = 1,
    version: str = "v1_manual",
) -> dict[str, Any]:
    if width is None or height is None:
        width, height, _slices = volume_hw(client, image_id)
    assert width and height
    # Paint a centered box that fits the actual slice plane.
    x0, y0 = max(1, width // 4), max(1, height // 4)
    x1, y1 = min(width - 1, 3 * width // 4), min(height - 1, 3 * height // 4)
    if x1 <= x0:
        x0, x1 = 0, width
    if y1 <= y0:
        y0, y1 = 0, height
    payload = {
        "case_id": case_id,
        "image_id": image_id,
        "version": version,
        "label": label,
        "label_id": label_id,
        "mask_format": "json",
        "axis": "axial",
        "slice_index": slice_index,
        "width": width,
        "height": height,
        "encoding": "rle",
        "mask": rle_box(width, height, x0, y0, x1, y1, value=1),
        "overwrite": True,
    }
    r = client.post("/api/save_mask", headers=auth_headers(token), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    return body
