"""Smoke-test spleen nnUNet prediction against a known Medical Decathlon case.

Usage:
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\smoke_spleen_predict.py
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\smoke_spleen_predict.py --case spleen_59
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import SimpleITK as sitk

from ai.config import SPLEEN_NNUNET_ROOT, VERSION_AI
from ai.metrics import dice_score, iou_score
from ai.predict import predict_spleen
from ai.spleen_nnunet import ensure_spleen_model_ready


def _load_nifti(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    spacing = tuple(float(v) for v in image.GetSpacing()[:3])
    return np.asarray(array), spacing


def _register_dev_case(case_id: str, image_id: str, source_nii: Path) -> Path:
    """Copy a sample CT into dataset/raw and register it in the local JSON DB."""
    from backend.app.core.config import (
        CASES_DB_PATH,
        IMAGES_DB_PATH,
        PROJECT_ROOT,
        RAW_DATA_DIR,
        ensure_project_dirs,
    )

    ensure_project_dirs()
    raw_dir = RAW_DATA_DIR / case_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / source_nii.name
    if not target.exists() or target.stat().st_size != source_nii.stat().st_size:
        shutil.copy2(source_nii, target)

    def _load(path: Path) -> list:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(path: Path, items: list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = _load(CASES_DB_PATH)
    images = _load(IMAGES_DB_PATH)
    if not any(item.get("case_id") == case_id for item in cases):
        cases.append(
            {
                "case_id": case_id,
                "patient_id": case_id,
                "modality": "CT",
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_group": "spleen_smoke",
                "status": "unannotated",
            }
        )
        _save(CASES_DB_PATH, cases)

    image_path = str(target.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    record = {
        "image_id": image_id,
        "case_id": case_id,
        "path": image_path,
        "width": 0,
        "height": 0,
        "filename": target.name,
        "file_format": "nii.gz",
        "slice_count": None,
    }
    existing_index = next((i for i, item in enumerate(images) if item.get("image_id") == image_id), None)
    if existing_index is None:
        images.append(record)
    else:
        images[existing_index] = record
    _save(IMAGES_DB_PATH, images)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test spleen AI prediction")
    parser.add_argument("--case", default="spleen_59", help="Case stem, e.g. spleen_59")
    parser.add_argument(
        "--skip-predict",
        action="store_true",
        help="Only check checkpoint / paths, do not run nnUNet",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Also register the sample into database/dev_*.json for API testing",
    )
    args = parser.parse_args()

    case_stem = args.case
    image_nii = (
        SPLEEN_NNUNET_ROOT
        / "nnUNet_raw"
        / "Dataset506_Spleen"
        / "imagesTs"
        / f"{case_stem}_0000.nii.gz"
    )
    if not image_nii.exists():
        image_nii = SPLEEN_NNUNET_ROOT / "casewise_predict_input" / case_stem / f"{case_stem}_0000.nii.gz"
    gt_nii = (
        SPLEEN_NNUNET_ROOT
        / "nnUNet_raw"
        / "Dataset506_Spleen"
        / "labelsTs"
        / f"{case_stem}.nii.gz"
    )

    print("=== spleen predict smoke test ===")
    ckpt = ensure_spleen_model_ready()
    print(f"checkpoint: {ckpt}")
    print(f"image:      {image_nii} exists={image_nii.exists()}")
    print(f"gt:         {gt_nii} exists={gt_nii.exists()}")
    if not image_nii.exists():
        print("ERROR: input CT not found")
        return 1

    case_id = "Case9001"
    image_id = "Image9001"
    mask_id = "Mask9001"
    if args.register:
        registered = _register_dev_case(case_id, image_id, image_nii)
        print(f"registered: {registered}")

    if args.skip_predict:
        print("skip-predict set; environment check only")
        return 0

    volume, spacing = _load_nifti(image_nii)
    print(f"volume shape={volume.shape} spacing={spacing}")
    t0 = time.time()
    result = predict_spleen(
        case_id=case_id,
        image_id=image_id,
        mask_id=mask_id,
        volume=volume,
        spacing=spacing,
        image_path=str(image_nii),
    )
    elapsed = time.time() - t0
    mask_path = ROOT / result["mask_path"]
    print(f"elapsed_sec={elapsed:.1f}")
    print(f"result={json.dumps(result, ensure_ascii=False, indent=2)}")
    print(f"mask_exists={mask_path.exists()} size={mask_path.stat().st_size if mask_path.exists() else 0}")

    if not mask_path.exists():
        print("ERROR: predicted mask missing")
        return 1

    pred, _ = _load_nifti(mask_path)
    pred_bin = (pred > 0).astype(np.uint8)
    print(f"pred voxels={int(pred_bin.sum())} unique={np.unique(pred_bin).tolist()}")

    metrics = {"elapsed_sec": round(elapsed, 2), "pred_voxels": int(pred_bin.sum())}
    if gt_nii.exists():
        gt, _ = _load_nifti(gt_nii)
        if gt.shape != pred_bin.shape:
            print(f"WARNING: shape mismatch pred={pred_bin.shape} gt={gt.shape}")
        else:
            metrics["dice"] = round(dice_score(pred_bin, gt), 4)
            metrics["iou"] = round(iou_score(pred_bin, gt), 4)
            print(f"dice={metrics['dice']} iou={metrics['iou']}")
            if metrics["dice"] < 0.5:
                print("WARNING: Dice looks low for a known test case")
                return 2

    out_json = ROOT / "outputs" / "spleen_smoke_metrics.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({"case": case_stem, "version": VERSION_AI, **metrics, **result}, indent=2) + "\n", encoding="utf-8")
    print(f"metrics_written={out_json}")

    if args.register:
        from backend.app.core.config import MASKS_DB_PATH, VERSIONS_DB_PATH

        def _load(path: Path) -> list:
            if not path.exists():
                return []
            return json.loads(path.read_text(encoding="utf-8"))

        def _save(path: Path, items: list) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        masks = _load(MASKS_DB_PATH)
        if not any(item.get("mask_id") == mask_id for item in masks):
            masks.append(
                {
                    "mask_id": mask_id,
                    "annotation_id": None,
                    "case_id": case_id,
                    "image_id": image_id,
                    "path": result["mask_path"],
                    "version": VERSION_AI,
                    "label": "spleen",
                    "mask_format": "nii.gz",
                    "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model_id": "Model0002",
                }
            )
            _save(MASKS_DB_PATH, masks)
            print(f"mask_db_registered={MASKS_DB_PATH}")

        versions = _load(VERSIONS_DB_PATH)
        if not any(item.get("case_id") == case_id and item.get("version") == VERSION_AI for item in versions):
            versions.append(
                {
                    "case_id": case_id,
                    "version": VERSION_AI,
                    "annotation": None,
                    "model": "Model0002",
                    "dataset": None,
                    "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
            _save(VERSIONS_DB_PATH, versions)
            print(f"version_db_registered={VERSIONS_DB_PATH}")

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
