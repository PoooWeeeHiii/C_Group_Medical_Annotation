"""Build a materialize'd platform U-Net dataset from DeepEdit multi-organ labels.

Merges heart/liver/spleen/lung/kidney into a 6-class mask and writes:
  dataset/exports/<dataset_id>/{imagesTr,labelsTr,imagesTs,labelsTs}
  dataset/splits/<dataset_id>_{manifest,split,label_map}.json

Usage:
  D:\\anaconda\\python.exe scripts\\prepare_platform_unet_from_deepedit.py
  D:\\anaconda\\python.exe scripts\\prepare_platform_unet_from_deepedit.py --limit 16 --val-ratio 0.25
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path(r"E:\lxy\hm_2_deepedit\dataset")

# Platform-style multiclass IDs (num_classes=6 → ids 0..5)
LABEL_MAP = {
    "background": 0,
    "liver": 1,
    "kidney": 2,
    "lung": 3,
    "spleen": 4,
    "heart": 5,
}

# source folder(s) under labels/ → class id
ORGAN_SOURCES: list[tuple[int, list[str]]] = [
    (1, ["liver"]),
    (2, ["left_kidney", "right_kidney", "kidney"]),
    (3, ["left_lung", "right_lung", "lung"]),
    (4, ["spleen"]),
    (5, ["heart"]),
]


def _read(path: Path):
    import SimpleITK as sitk

    img = sitk.ReadImage(str(path))
    return sitk.GetArrayFromImage(img), img


def _write(path: Path, array: np.ndarray, ref) -> None:
    import SimpleITK as sitk

    out = sitk.GetImageFromArray(np.asarray(array))
    out.CopyInformation(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(out, str(path))


def _merge_multiclass(case_stem: str, labels_root: Path, shape: tuple[int, ...]) -> np.ndarray | None:
    combined = np.zeros(shape, dtype=np.uint8)
    any_fg = False
    for class_id, folders in ORGAN_SOURCES:
        for folder in folders:
            path = labels_root / folder / f"{case_stem}.nii.gz"
            if not path.is_file():
                continue
            arr, _ = _read(path)
            if arr.shape != shape:
                if arr.T.shape == shape:
                    arr = arr.T
                else:
                    print(f"  skip shape {folder}/{case_stem}: {arr.shape} vs {shape}")
                    continue
            fg = arr > 0
            if np.any(fg):
                any_fg = True
                # later organs overwrite earlier only on fg; keep non-overlap preferred
                combined[fg] = class_id
    return combined if any_fg else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare platform U-Net dataset from DeepEdit organs")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--dataset-id", default="DatasetPersonBUNet")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--val-ratio", type=float, default=0.25)
    parser.add_argument("--link", action="store_true", help="Hardlink CT instead of copy when possible")
    args = parser.parse_args()

    src: Path = args.src
    images_dir = src / "images"
    labels_root = src / "labels"
    if not images_dir.is_dir():
        print(f"Missing images: {images_dir}")
        return 1

    stems = sorted(p.name.replace("_0000.nii.gz", "") for p in images_dir.glob("*_0000.nii.gz"))
    if args.limit:
        stems = stems[: max(1, args.limit)]
    if len(stems) < 2:
        print("Need at least 2 cases for train/val")
        return 1

    n_val = max(1, int(round(len(stems) * args.val_ratio)))
    val_stems = set(stems[-n_val:])
    train_stems = [s for s in stems if s not in val_stems]
    if not train_stems:
        train_stems = stems[:-1]
        val_stems = {stems[-1]}

    export_root = ROOT / "dataset" / "exports" / args.dataset_id
    if export_root.exists():
        shutil.rmtree(export_root)
    for sub in ("imagesTr", "labelsTr", "imagesTs", "labelsTs"):
        (export_root / sub).mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    kept_train = 0
    kept_val = 0
    for stem in stems:
        img_src = images_dir / f"{stem}_0000.nii.gz"
        arr, ref = _read(img_src)
        mask = _merge_multiclass(stem, labels_root, arr.shape)
        if mask is None:
            print(f"SKIP empty multiclass {stem}")
            continue
        is_val = stem in val_stems
        split = "val" if is_val else "train"
        img_dir = export_root / ("imagesTs" if is_val else "imagesTr")
        lab_dir = export_root / ("labelsTs" if is_val else "labelsTr")
        img_dst = img_dir / f"{stem}_0000.nii.gz"
        lab_dst = lab_dir / f"{stem}.nii.gz"
        if args.link:
            try:
                if not img_dst.exists():
                    img_dst.hardlink_to(img_src)
            except OSError:
                shutil.copy2(img_src, img_dst)
        else:
            shutil.copy2(img_src, img_dst)
        _write(lab_dst, mask, ref)
        records.append(
            {
                "split": split,
                "case_id": stem,
                "image_id": stem,
                "image_path": str(img_dst.relative_to(ROOT)).replace("\\", "/"),
                "mask_path": str(lab_dst.relative_to(ROOT)).replace("\\", "/"),
                "nnunet_id": stem,
                "label": "multiclass",
                "version": "pseudo_deepedit",
            }
        )
        if is_val:
            kept_val += 1
        else:
            kept_train += 1
        print(f"OK {split} {stem} voxels={int((mask > 0).sum())}")

    if kept_train == 0:
        print("No training cases written")
        return 1

    # nnUNet-ish dataset.json
    dataset_json = {
        "name": args.dataset_id,
        "description": "Platform U-Net from DeepEdit multi-organ pseudo labels (Person B)",
        "channel_names": {"0": "CT"},
        "labels": {k: v for k, v in LABEL_MAP.items()},
        "numTraining": kept_train,
        "file_ending": ".nii.gz",
    }
    (export_root / "dataset.json").write_text(
        json.dumps(dataset_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (export_root / "splits_final.json").write_text(
        json.dumps(
            {
                "train": [r["nnunet_id"] for r in records if r["split"] == "train"],
                "val": [r["nnunet_id"] for r in records if r["split"] == "val"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    splits_dir = ROOT / "dataset" / "splits"
    splits_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset_id": args.dataset_id,
        "name": "person_b_platform_unet_from_deepedit",
        "version": "pseudo_deepedit",
        "label_set": "dense",
        "format": "nnunet",
        "materialize": True,
        "counts": {"train": kept_train, "val": kept_val, "test": 0, "total": kept_train + kept_val},
        "label_map": LABEL_MAP,
        "records": records,
        "export_dir": f"dataset/exports/{args.dataset_id}",
        "notes": "Built for observable platform 2.5D U-Net demo; labels are DeepEdit/TotalSeg pseudo.",
    }
    (splits_dir / f"{args.dataset_id}_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (splits_dir / f"{args.dataset_id}_split.json").write_text(
        json.dumps(
            {
                "dataset_id": args.dataset_id,
                "train": [r["case_id"] for r in records if r["split"] == "train"],
                "val": [r["case_id"] for r in records if r["split"] == "val"],
                "test": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (splits_dir / f"{args.dataset_id}_label_map.json").write_text(
        json.dumps(LABEL_MAP, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(
        f"Wrote {args.dataset_id}: train={kept_train} val={kept_val} -> {export_root}\n"
        f"Next:\n"
        f"  POST /api/train dataset_id={args.dataset_id} epochs=20 num_classes=6 image_size=256\n"
        f"  or: D:\\anaconda\\python.exe -m ai.train --dataset-id {args.dataset_id} "
        f"--model-id ModelUNet_{args.dataset_id} --epochs 20 --num-classes 6 --image-size 256"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
