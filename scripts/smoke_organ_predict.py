"""Smoke-test Plan A organ nnUNet (heart/liver/lung/kidney) vs DeepEdit pseudo-labels.

Usage:
  D:\\anaconda\\python.exe scripts\\smoke_organ_predict.py --organ heart
  D:\\anaconda\\python.exe scripts\\smoke_organ_predict.py --organ all
  D:\\anaconda\\python.exe scripts\\smoke_organ_predict.py --organ lung --case spleen_10 --register
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

from ai.config import ORGANS_NNUNET_ROOT, VERSION_AI
from ai.metrics import dice_score, iou_score
from ai.organ_nnunet import ensure_organ_model_ready, list_ready_organ_models
from ai.predict import predict_organ

DEEPEDIT_ROOT = Path(r"E:\lxy\hm_2_deepedit\dataset")

# Person B short IDs + platform case IDs for API e2e
ORGAN_META = {
    "heart": {"model_id": "Model0010", "case_id": "Case9010", "image_id": "Image9010", "mask_id": "Mask9010"},
    "liver": {"model_id": "Model0011", "case_id": "Case9011", "image_id": "Image9011", "mask_id": "Mask9011"},
    "lung": {"model_id": "Model0012", "case_id": "Case9012", "image_id": "Image9012", "mask_id": "Mask9012"},
    "kidney": {"model_id": "Model0013", "case_id": "Case9013", "image_id": "Image9013", "mask_id": "Mask9013"},
}


def _load_nifti(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    spacing = tuple(float(v) for v in image.GetSpacing()[:3])
    return np.asarray(array), spacing


def _merge_binary(paths: list[Path]) -> np.ndarray | None:
    merged = None
    for path in paths:
        if not path.exists():
            continue
        arr, _ = _load_nifti(path)
        bin_arr = (arr > 0).astype(np.uint8)
        merged = bin_arr if merged is None else np.maximum(merged, bin_arr)
    return merged


def _load_gt(organ: str, case_stem: str) -> np.ndarray | None:
    labels = DEEPEDIT_ROOT / "labels"
    if organ == "heart":
        path = labels / "heart" / f"{case_stem}.nii.gz"
        if not path.exists():
            return None
        arr, _ = _load_nifti(path)
        return (arr > 0).astype(np.uint8)
    if organ == "liver":
        path = labels / "liver" / f"{case_stem}.nii.gz"
        if not path.exists():
            return None
        arr, _ = _load_nifti(path)
        return (arr > 0).astype(np.uint8)
    if organ == "lung":
        return _merge_binary(
            [
                labels / "left_lung" / f"{case_stem}.nii.gz",
                labels / "right_lung" / f"{case_stem}.nii.gz",
            ]
        )
    if organ == "kidney":
        return _merge_binary(
            [
                labels / "left_kidney" / f"{case_stem}.nii.gz",
                labels / "right_kidney" / f"{case_stem}.nii.gz",
            ]
        )
    return None


def _resolve_image(case_stem: str) -> Path:
    candidates = [
        DEEPEDIT_ROOT / "images" / f"{case_stem}_0000.nii.gz",
        ORGANS_NNUNET_ROOT / "nnUNet_raw" / "Dataset511_DeepEdit_Liver" / "imagesTr" / f"{case_stem}_0000.nii.gz",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _register_dev_case(case_id: str, image_id: str, source_nii: Path) -> Path:
    from backend.app.core.config import (
        PROJECT_ROOT,
        RAW_DATA_DIR,
        ensure_project_dirs,
    )
    from backend.app.services.sqlite_service import get_record, upsert_record

    ensure_project_dirs()
    raw_dir = RAW_DATA_DIR / case_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / source_nii.name
    if not target.exists() or target.stat().st_size != source_nii.stat().st_size:
        shutil.copy2(source_nii, target)

    image_path = str(target.resolve().relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
    if get_record("cases", "case_id", case_id) is None:
        upsert_record(
            "cases",
            {
                "case_id": case_id,
                "patient_id": case_id,
                "modality": "CT",
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source_group": "organ_smoke",
                "status": "unannotated",
            },
        )
    upsert_record(
        "images",
        {
            "image_id": image_id,
            "case_id": case_id,
            "path": image_path,
            "width": 0,
            "height": 0,
            "filename": target.name,
            "file_format": "nii.gz",
            "slice_count": None,
        },
    )
    return target


def _run_one(organ: str, case_stem: str, skip_predict: bool, register: bool) -> int:
    meta = ORGAN_META[organ]
    from ai.organ_nnunet import LABEL_TO_MODEL_ID

    canon_id = LABEL_TO_MODEL_ID[organ]
    image_nii = _resolve_image(case_stem)

    print(f"\n=== organ predict smoke: {organ} ===")
    ckpt = ensure_organ_model_ready(model_id=canon_id, label=organ)
    print(f"checkpoint: {ckpt}")
    print(f"image:      {image_nii} exists={image_nii.exists()}")
    if not image_nii.exists():
        print("ERROR: input CT not found")
        return 1

    case_id = meta["case_id"]
    image_id = meta["image_id"]
    mask_id = meta["mask_id"]
    model_id = meta["model_id"]

    if register:
        registered = _register_dev_case(case_id, image_id, image_nii)
        print(f"registered: {registered}")

    if skip_predict:
        print("skip-predict set; environment check only")
        return 0

    volume, spacing = _load_nifti(image_nii)
    print(f"volume shape={volume.shape} spacing={spacing}")
    t0 = time.time()
    result = predict_organ(
        case_id=case_id,
        image_id=image_id,
        mask_id=mask_id,
        volume=volume,
        spacing=spacing,
        image_path=str(image_nii),
        model_id=model_id,
        label=organ,
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

    metrics: dict = {
        "organ": organ,
        "case": case_stem,
        "model_id": model_id,
        "canonical_model_id": canon_id,
        "elapsed_sec": round(elapsed, 2),
        "pred_voxels": int(pred_bin.sum()),
        "version": VERSION_AI,
        **result,
    }
    warn_low_dice = False
    gt = _load_gt(organ, case_stem)
    if gt is not None:
        if gt.shape != pred_bin.shape:
            print(f"WARNING: shape mismatch pred={pred_bin.shape} gt={gt.shape}")
        else:
            metrics["dice"] = round(dice_score(pred_bin, gt), 4)
            metrics["iou"] = round(iou_score(pred_bin, gt), 4)
            print(f"dice={metrics['dice']} iou={metrics['iou']} (vs DeepEdit/TotalSeg pseudo GT)")
            # Soft floor: heart is weaker; others should clear 0.5 easily on train-like cases
            floor = 0.15 if organ == "heart" else 0.5
            if metrics["dice"] < floor:
                print(f"WARNING: Dice looks low for {organ} (floor={floor})")
                warn_low_dice = True
    else:
        print("WARNING: no pseudo GT found; skipped Dice")

    smoke_dir = ORGANS_NNUNET_ROOT / "smoke_infer"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    smoke_out = smoke_dir / f"{case_stem}_{organ}_pred.nii.gz"
    shutil.copy2(mask_path, smoke_out)
    metrics["smoke_copy"] = str(smoke_out)

    out_json = ROOT / "outputs" / f"organ_smoke_metrics_{organ}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"metrics_written={out_json}")

    if register:
        from backend.app.services.sqlite_service import get_record, upsert_record

        if get_record("masks", "mask_id", mask_id) is None:
            upsert_record(
                "masks",
                {
                    "mask_id": mask_id,
                    "annotation_id": None,
                    "case_id": case_id,
                    "image_id": image_id,
                    "path": result["mask_path"],
                    "version": VERSION_AI,
                    "label": organ,
                    "mask_format": "nii.gz",
                    "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "model_id": model_id,
                },
            )
            print("mask_db_registered=sqlite:masks")

        versions = []
        try:
            from backend.app.services.sqlite_service import list_records

            versions = list_records("versions")
        except Exception:
            versions = []
        if not any(item.get("case_id") == case_id and item.get("version") == VERSION_AI for item in versions):
            upsert_record(
                "versions",
                {
                    "case_id": case_id,
                    "version": VERSION_AI,
                    "annotation": None,
                    "model": model_id,
                    "dataset": None,
                    "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            print("version_db_registered=sqlite:versions")

    print(f"SMOKE_OK_{organ.upper()}")
    return 2 if warn_low_dice else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Plan A organ AI prediction")
    parser.add_argument(
        "--organ",
        default="all",
        choices=["heart", "liver", "lung", "kidney", "all"],
        help="Which organ to smoke-test",
    )
    parser.add_argument("--case", default="spleen_10", help="Case stem, e.g. spleen_10")
    parser.add_argument("--skip-predict", action="store_true", help="Only check checkpoints")
    parser.add_argument("--register", action="store_true", help="Register into database/dev_*.json")
    args = parser.parse_args()

    print("=== organ nnUNet readiness ===")
    for row in list_ready_organ_models():
        print(f"  {row['model_id']}: ready={row['ready']} dice={row['dice']}")

    organs = list(ORGAN_META.keys()) if args.organ == "all" else [args.organ]
    worst = 0
    for organ in organs:
        code = _run_one(organ, args.case, args.skip_predict, args.register)
        worst = max(worst, code)
    if worst == 0:
        print("\nSMOKE_OK_ALL")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
