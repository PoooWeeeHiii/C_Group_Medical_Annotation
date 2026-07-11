"""Prepare TotalSegmentator v2 zip as nnUNet training datasets.

Official TotalSegmentator trains 5 part-models. This script also supports a
platform-friendly single-label spleen dataset.

Examples:
  # Extract the downloaded zip
  python scripts/prepare_totalseg_nnunet.py extract

  # Smoke-convert 3 cases from zip (no full extract needed)
  python scripts/prepare_totalseg_nnunet.py convert --from-zip --parts spleen --limit 3

  # Full organs conversion after extract
  python scripts/prepare_totalseg_nnunet.py convert --parts organs

  # Convert all 5 official parts + spleen
  python scripts/prepare_totalseg_nnunet.py convert --parts all,spleen
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    import nibabel as nib
except ImportError as exc:  # pragma: no cover
    raise SystemExit("nibabel is required. Install it in the nnUNet Python env.") from exc


DEFAULT_ROOT = Path(r"D:\hm_2_totalseg")
DEFAULT_ZIP = DEFAULT_ROOT / "raw_archives" / "Totalsegmentator_dataset_v201.zip"

# Keep IDs away from the local spleen Dataset506.
PART_DATASETS = {
    "organs": ("Dataset601_TotalSeg_Organs", "class_map_part_organs"),
    "vertebrae": ("Dataset602_TotalSeg_Vertebrae", "class_map_part_vertebrae"),
    "cardiac": ("Dataset603_TotalSeg_Cardiac", "class_map_part_cardiac"),
    "muscles": ("Dataset604_TotalSeg_Muscles", "class_map_part_muscles"),
    "ribs": ("Dataset605_TotalSeg_Ribs", "class_map_part_ribs"),
    "spleen": ("Dataset606_TotalSeg_Spleen", "spleen_only"),
}

CLASS_MAP_5_PARTS = {
    "class_map_part_organs": {
        1: "spleen",
        2: "kidney_right",
        3: "kidney_left",
        4: "gallbladder",
        5: "liver",
        6: "stomach",
        7: "pancreas",
        8: "adrenal_gland_right",
        9: "adrenal_gland_left",
        10: "lung_upper_lobe_left",
        11: "lung_lower_lobe_left",
        12: "lung_upper_lobe_right",
        13: "lung_middle_lobe_right",
        14: "lung_lower_lobe_right",
        15: "esophagus",
        16: "trachea",
        17: "thyroid_gland",
        18: "small_bowel",
        19: "duodenum",
        20: "colon",
        21: "urinary_bladder",
        22: "prostate",
        23: "kidney_cyst_left",
        24: "kidney_cyst_right",
    },
    "class_map_part_vertebrae": {
        1: "sacrum",
        2: "vertebrae_S1",
        3: "vertebrae_L5",
        4: "vertebrae_L4",
        5: "vertebrae_L3",
        6: "vertebrae_L2",
        7: "vertebrae_L1",
        8: "vertebrae_T12",
        9: "vertebrae_T11",
        10: "vertebrae_T10",
        11: "vertebrae_T9",
        12: "vertebrae_T8",
        13: "vertebrae_T7",
        14: "vertebrae_T6",
        15: "vertebrae_T5",
        16: "vertebrae_T4",
        17: "vertebrae_T3",
        18: "vertebrae_T2",
        19: "vertebrae_T1",
        20: "vertebrae_C7",
        21: "vertebrae_C6",
        22: "vertebrae_C5",
        23: "vertebrae_C4",
        24: "vertebrae_C3",
        25: "vertebrae_C2",
        26: "vertebrae_C1",
    },
    "class_map_part_cardiac": {
        1: "heart",
        2: "aorta",
        3: "pulmonary_vein",
        4: "brachiocephalic_trunk",
        5: "subclavian_artery_right",
        6: "subclavian_artery_left",
        7: "common_carotid_artery_right",
        8: "common_carotid_artery_left",
        9: "brachiocephalic_vein_left",
        10: "brachiocephalic_vein_right",
        11: "atrial_appendage_left",
        12: "superior_vena_cava",
        13: "inferior_vena_cava",
        14: "portal_vein_and_splenic_vein",
        15: "iliac_artery_left",
        16: "iliac_artery_right",
        17: "iliac_vena_left",
        18: "iliac_vena_right",
    },
    "class_map_part_muscles": {
        1: "humerus_left",
        2: "humerus_right",
        3: "scapula_left",
        4: "scapula_right",
        5: "clavicula_left",
        6: "clavicula_right",
        7: "femur_left",
        8: "femur_right",
        9: "hip_left",
        10: "hip_right",
        11: "spinal_cord",
        12: "gluteus_maximus_left",
        13: "gluteus_maximus_right",
        14: "gluteus_medius_left",
        15: "gluteus_medius_right",
        16: "gluteus_minimus_left",
        17: "gluteus_minimus_right",
        18: "autochthon_left",
        19: "autochthon_right",
        20: "iliopsoas_left",
        21: "iliopsoas_right",
        22: "brain",
        23: "skull",
    },
    "class_map_part_ribs": {
        1: "rib_left_1",
        2: "rib_left_2",
        3: "rib_left_3",
        4: "rib_left_4",
        5: "rib_left_5",
        6: "rib_left_6",
        7: "rib_left_7",
        8: "rib_left_8",
        9: "rib_left_9",
        10: "rib_left_10",
        11: "rib_left_11",
        12: "rib_left_12",
        13: "rib_right_1",
        14: "rib_right_2",
        15: "rib_right_3",
        16: "rib_right_4",
        17: "rib_right_5",
        18: "rib_right_6",
        19: "rib_right_7",
        20: "rib_right_8",
        21: "rib_right_9",
        22: "rib_right_10",
        23: "rib_right_11",
        24: "rib_right_12",
        25: "sternum",
        26: "costal_cartilages",
    },
}


def _labels_for_part(part: str) -> list[str]:
    if part == "spleen":
        return ["spleen"]
    key = PART_DATASETS[part][1]
    cmap = CLASS_MAP_5_PARTS[key]
    return [cmap[i] for i in sorted(cmap)]


def _ensure_dirs(nnunet_path: Path) -> None:
    for name in ("imagesTr", "labelsTr", "imagesTs", "labelsTs"):
        (nnunet_path / name).mkdir(parents=True, exist_ok=True)


def _write_dataset_json(nnunet_path: Path, labels: list[str], num_training: int) -> None:
    payload = {
        "name": nnunet_path.name,
        "description": "TotalSegmentator v2 converted for nnUNet training",
        "reference": "https://zenodo.org/record/6802614",
        "licence": "Apache 2.0",
        "release": "2.0.1",
        "channel_names": {"0": "CT"},
        "labels": {name: idx for idx, name in enumerate(["background", *labels])},
        "numTraining": num_training,
        "file_ending": ".nii.gz",
        "overwrite_image_reader_writer": "NibabelIOWithReorient",
    }
    (nnunet_path / "dataset.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def _write_splits(preprocessed_root: Path, foldername: str, train_ids: list[str], val_ids: list[str]) -> Path:
    out_dir = preprocessed_root / foldername
    out_dir.mkdir(parents=True, exist_ok=True)
    splits = [{"train": train_ids, "val": val_ids}]
    out = out_dir / "splits_final.json"
    out.write_text(json.dumps(splits, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    return out


def _combine_labels_from_arrays(ref_shape, affine, mask_arrays: list[np.ndarray | None], out_path: Path) -> None:
    combined = np.zeros(ref_shape, dtype=np.uint8)
    for idx, arr in enumerate(mask_arrays, start=1):
        if arr is None:
            continue
        combined[arr > 0] = idx
    nib.save(nib.Nifti1Image(combined, affine), str(out_path))


def _load_meta(meta_source: Path | zipfile.ZipFile) -> pd.DataFrame:
    if isinstance(meta_source, zipfile.ZipFile):
        with meta_source.open("meta.csv") as handle:
            return pd.read_csv(handle, sep=";")
    return pd.read_csv(meta_source / "meta.csv", sep=";")


def _subject_lists(meta: pd.DataFrame, limit: int | None) -> tuple[list[str], list[str], list[str]]:
    train_ids = list(meta[meta["split"] == "train"]["image_id"].astype(str))
    val_ids = list(meta[meta["split"] == "val"]["image_id"].astype(str))
    test_ids = list(meta[meta["split"] == "test"]["image_id"].astype(str))
    if limit is not None:
        # Keep a tiny but valid train/val/test mix for smoke tests.
        train_ids = train_ids[: max(limit, 1)]
        val_ids = val_ids[:1] if val_ids else []
        test_ids = test_ids[:1] if test_ids else []
    return train_ids, val_ids, test_ids


def extract_zip(zip_path: Path, extract_dir: Path) -> Path:
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip not found: {zip_path}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    marker = extract_dir / "meta.csv"
    if marker.exists():
        print(f"Already extracted: {extract_dir}")
        return extract_dir

    print(f"Extracting {zip_path} -> {extract_dir}")
    print("This can take a long time (~22GB zip, 100k+ files).")
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        for name in tqdm(members, desc="extract"):
            archive.extract(name, path=extract_dir)
    if not marker.exists():
        raise RuntimeError(f"Extraction finished but meta.csv missing under {extract_dir}")
    print("EXTRACT_OK")
    return extract_dir


class _ZipCaseStore:
    def __init__(self, zip_path: Path):
        self.zip_path = zip_path
        self.zf = zipfile.ZipFile(zip_path)
        print("Indexing zip members...")
        self.names = set(self.zf.namelist())
        print(f"zip_members={len(self.names)}")

    def close(self) -> None:
        self.zf.close()

    def has_ct(self, subject: str) -> bool:
        return f"{subject}/ct.nii.gz" in self.names

    def read_bytes(self, member: str) -> bytes | None:
        if member not in self.names:
            return None
        return self.zf.read(member)


def _copy_or_write_bytes(data: bytes, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)


def convert_part(
    *,
    part: str,
    dataset_root: Path | None,
    zip_path: Path | None,
    nnunet_raw: Path,
    nnunet_preprocessed: Path,
    limit: int | None = None,
    overwrite: bool = False,
) -> Path:
    if part not in PART_DATASETS:
        raise ValueError(f"Unknown part '{part}'. Choose from {sorted(PART_DATASETS)}")

    foldername, _ = PART_DATASETS[part]
    labels = _labels_for_part(part)
    nnunet_path = nnunet_raw / foldername
    if nnunet_path.exists() and any(nnunet_path.iterdir()) and not overwrite:
        print(f"Skip existing {nnunet_path} (pass --overwrite to rebuild)")
        return nnunet_path

    if nnunet_path.exists() and overwrite:
        shutil.rmtree(nnunet_path)
    _ensure_dirs(nnunet_path)

    store = None
    meta: pd.DataFrame
    if zip_path is not None:
        store = _ZipCaseStore(zip_path)
        meta = _load_meta(store.zf)
    else:
        assert dataset_root is not None
        meta = _load_meta(dataset_root)

    train_ids, val_ids, test_ids = _subject_lists(meta, limit)
    print(
        f"[{part}] folder={foldername} labels={len(labels)} "
        f"train={len(train_ids)} val={len(val_ids)} test={len(test_ids)}"
    )

    def process_subject(subject: str, split: str) -> None:
        img_dir = "imagesTr" if split != "test" else "imagesTs"
        lbl_dir = "labelsTr" if split != "test" else "labelsTs"
        out_img = nnunet_path / img_dir / f"{subject}_0000.nii.gz"
        out_lbl = nnunet_path / lbl_dir / f"{subject}.nii.gz"

        if store is not None:
            ct_bytes = store.read_bytes(f"{subject}/ct.nii.gz")
            if ct_bytes is None:
                print(f"Missing CT in zip: {subject}")
                return
            _copy_or_write_bytes(ct_bytes, out_img)
            ref = nib.load(str(out_img))
            mask_arrays: list[np.ndarray | None] = []
            for roi in labels:
                raw = store.read_bytes(f"{subject}/segmentations/{roi}.nii.gz")
                if raw is None:
                    mask_arrays.append(None)
                    continue
                tmp = nnunet_path / f".tmp_{subject}_{roi}.nii.gz"
                tmp.write_bytes(raw)
                mask_arrays.append(nib.load(str(tmp)).get_fdata())
                tmp.unlink(missing_ok=True)
            _combine_labels_from_arrays(ref.shape, ref.affine, mask_arrays, out_lbl)
            return

        assert dataset_root is not None
        subject_path = dataset_root / subject
        ct_path = subject_path / "ct.nii.gz"
        if not ct_path.exists():
            print(f"Missing CT: {ct_path}")
            return
        shutil.copy2(ct_path, out_img)
        ref = nib.load(str(ct_path))
        mask_arrays = []
        for roi in labels:
            roi_path = subject_path / "segmentations" / f"{roi}.nii.gz"
            if not roi_path.exists():
                mask_arrays.append(None)
                continue
            mask_arrays.append(nib.load(str(roi_path)).get_fdata())
        _combine_labels_from_arrays(ref.shape, ref.affine, mask_arrays, out_lbl)

    for subject in tqdm(train_ids + val_ids, desc=f"{part}-train/val"):
        process_subject(subject, "train")
    for subject in tqdm(test_ids, desc=f"{part}-test"):
        process_subject(subject, "test")

    _write_dataset_json(nnunet_path, labels, num_training=len(train_ids) + len(val_ids))
    splits_path = _write_splits(nnunet_preprocessed, foldername, train_ids, val_ids)
    manifest = {
        "part": part,
        "dataset_folder": foldername,
        "dataset_id": int(foldername[7:10]),
        "labels": labels,
        "train": len(train_ids),
        "val": len(val_ids),
        "test": len(test_ids),
        "nnunet_raw": str(nnunet_path),
        "splits_final": str(splits_path),
        "next_preprocess": (
            f'nnUNetv2_plan_and_preprocess -d {int(foldername[7:10])} '
            f"-pl ExperimentPlanner -c 3d_fullres -np 2"
        ),
        "next_train": (
            f"nnUNetv2_train {int(foldername[7:10])} 3d_fullres 0 -tr nnUNetTrainerNoMirroring"
        ),
    }
    (nnunet_path / "conversion_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if store is not None:
        store.close()
    print(f"CONVERT_OK {foldername}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return nnunet_path


def parse_parts(raw: str) -> list[str]:
    parts: list[str] = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "all":
            parts.extend(["organs", "vertebrae", "cardiac", "muscles", "ribs"])
        else:
            parts.append(token)
    # preserve order, drop duplicates
    seen = set()
    ordered = []
    for part in parts:
        if part not in seen:
            ordered.append(part)
            seen.add(part)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare TotalSegmentator zip for nnUNet training")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="D:\\hm_2_totalseg")
    parser.add_argument("--zip", type=Path, default=None, help="Path to Totalsegmentator_dataset_v201.zip")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract the downloaded zip")
    p_extract.add_argument("--force", action="store_true")

    p_convert = sub.add_parser("convert", help="Convert extracted/zip data to nnUNet raw format")
    p_convert.add_argument(
        "--parts",
        default="spleen,organs",
        help="Comma list: organs,vertebrae,cardiac,muscles,ribs,spleen,all",
    )
    p_convert.add_argument("--from-zip", action="store_true", help="Read cases directly from zip")
    p_convert.add_argument("--limit", type=int, default=None, help="Limit cases for smoke testing")
    p_convert.add_argument("--overwrite", action="store_true")

    p_status = sub.add_parser("status", help="Show extract/convert status")
    return parser


def cmd_status(root: Path, zip_path: Path) -> int:
    extracted = root / "extracted"
    raw = root / "nnUNet_raw"
    print("zip_exists", zip_path.exists(), zip_path)
    print("extracted_meta", (extracted / "meta.csv").exists())
    if (extracted / "meta.csv").exists():
        meta = pd.read_csv(extracted / "meta.csv", sep=";")
        print("extracted_split", meta["split"].value_counts().to_dict())
    if raw.exists():
        for child in sorted(raw.glob("Dataset*")):
            n_tr = len(list((child / "imagesTr").glob("*.nii.gz"))) if (child / "imagesTr").exists() else 0
            print(f"raw {child.name}: imagesTr={n_tr}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root: Path = args.root
    zip_path: Path = args.zip or (root / "raw_archives" / "Totalsegmentator_dataset_v201.zip")
    extract_dir = root / "extracted"
    nnunet_raw = root / "nnUNet_raw"
    nnunet_preprocessed = root / "nnUNet_preprocessed"
    nnunet_raw.mkdir(parents=True, exist_ok=True)
    nnunet_preprocessed.mkdir(parents=True, exist_ok=True)

    if args.command == "status":
        return cmd_status(root, zip_path)

    if args.command == "extract":
        if args.force and extract_dir.exists():
            print(f"Removing {extract_dir}")
            shutil.rmtree(extract_dir)
        extract_zip(zip_path, extract_dir)
        return 0

    if args.command == "convert":
        parts = parse_parts(args.parts)
        dataset_root = None
        use_zip = args.from_zip
        if not use_zip:
            if not (extract_dir / "meta.csv").exists():
                print("Extracted dataset not found. Use --from-zip or run: prepare_totalseg_nnunet.py extract")
                return 1
            dataset_root = extract_dir
            zip_for_convert = None
        else:
            zip_for_convert = zip_path
        for part in parts:
            convert_part(
                part=part,
                dataset_root=dataset_root,
                zip_path=zip_for_convert,
                nnunet_raw=nnunet_raw,
                nnunet_preprocessed=nnunet_preprocessed,
                limit=args.limit,
                overwrite=args.overwrite,
            )
        return 0

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    # Faster zip member checks: build name set lazily inside store when needed.
    raise SystemExit(main())
