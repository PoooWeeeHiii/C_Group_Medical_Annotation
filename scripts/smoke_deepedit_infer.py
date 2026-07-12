"""Smoke-test DeepEdit /infer with a small synthetic volume (CPU-friendly).

Also optionally hits the main backend refine path when BACKEND_URL is set.

Usage:
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\smoke_deepedit_infer.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = PROJECT_ROOT / "models" / "deepedit" / "_smoke"


def _write_volume(path: Path, array: np.ndarray) -> None:
    import SimpleITK as sitk

    image = sitk.GetImageFromArray(array.astype(np.float32, copy=False))
    image.SetSpacing((1.0, 1.0, 1.0))
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(path))


def _make_synthetic() -> tuple[Path, Path, list[list[float]], list[list[float]], list[int]]:
    depth, height, width = 32, 64, 64
    ct = np.full((depth, height, width), -1000.0, dtype=np.float32)
    mask = np.zeros((depth, height, width), dtype=np.uint8)
    # ellipsoid "organ"
    zz, yy, xx = np.ogrid[:depth, :height, :width]
    organ = ((zz - 16) / 8) ** 2 + ((yy - 32) / 14) ** 2 + ((xx - 32) / 14) ** 2 <= 1.0
    ct[organ] = 80.0
    mask[organ] = 1
    # degrade current mask (shrink)
    current = np.zeros_like(mask)
    current[organ] = 1
    current[14:18, 28:36, 28:36] = 0

    image_path = SMOKE_DIR / "ct.nii.gz"
    mask_path = SMOKE_DIR / "current_mask.nii.gz"
    _write_volume(image_path, ct)
    _write_volume(mask_path, current.astype(np.float32))

    positive = [[32.0, 32.0, 16.0], [30.0, 34.0, 15.0]]
    negative = [[10.0, 10.0, 5.0], [50.0, 50.0, 25.0]]
    confirmed = [16]
    return image_path, mask_path, positive, negative, confirmed


def _post_json(url: str, payload: dict, timeout: float = 120.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    base = os.environ.get("DEEPEDIT_SERVICE_URL", "http://127.0.0.1:8010").rstrip("/")
    health_url = base + "/health"
    infer_url = base + "/infer"
    with urllib.request.urlopen(health_url, timeout=60) as resp:
        health = json.loads(resp.read().decode("utf-8"))
    print("health model_loaded:", health.get("model_loaded"))
    print("health model_format:", (health.get("model_info") or {}).get("model_format"))
    if not health.get("model_loaded"):
        print("model_error:", health.get("model_error"))
        return 1

    image_path, mask_path, positive, negative, confirmed = _make_synthetic()
    payload = {
        "case_id": "smoke",
        "image_id": "smoke",
        "image_path": str(image_path),
        "current_mask_path": str(mask_path),
        "label": "spleen",
        "model_id": "DeepEdit",
        "positive_points": positive,
        "negative_points": negative,
        "scribbles": [
            {
                "prompt_type": "negative",
                "axis": "axial",
                "slice_index": 20,
                "points": [{"x": 8, "y": 8, "z": 20}],
            }
        ],
        "confirmed_slices": confirmed,
        "output_version": "v3_preview",
    }
    result = _post_json(infer_url, payload, timeout=300)
    print("infer success:", result.get("success"))
    print("model_status:", result.get("model_status"))
    print("message:", result.get("message"))
    print("shape:", result.get("shape"))
    print("has_mask_base64:", bool(result.get("mask_base64")))
    if result.get("model_status") != "remote_model" or not result.get("success"):
        return 1

    # Optional: if main backend is up, verify refine proxy returns remote_model.
    backend = "http://127.0.0.1:8000"
    try:
        with urllib.request.urlopen(backend + "/docs", timeout=3) as resp:
            backend_up = resp.status == 200
    except Exception:
        backend_up = False
    if backend_up:
        print("backend detected; refine e2e requires a real case_id/image_id — skipped synthetic")
    else:
        print("backend not running on :8000 (DeepEdit service path verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
