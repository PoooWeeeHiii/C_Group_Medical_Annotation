"""Convert platform v3_fusion / final masks → nnUNet HITL datasets (Person B).

Creates Dataset520–523 under ORGANS_NNUNET_ROOT so Plan A Dataset510–513
are not overwritten. Source: platform dataset/labels/<Case>/<version>/*.nii.gz

Usage:
  D:\\anaconda\\python.exe scripts\\prepare_organs_nnunet_from_fusion.py --dry-run
  D:\\anaconda\\python.exe scripts\\prepare_organs_nnunet_from_fusion.py --limit 40
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = PROJECT_ROOT / "dataset" / "labels"
DEFAULT_RAW = PROJECT_ROOT / "dataset" / "raw"
DEFAULT_IMAGES = PROJECT_ROOT / "dataset" / "images"
DEFAULT_ROOT = Path(r"E:\lxy\hm_2_organs_nnunet")

# HITL incremental datasets (do not clash with Plan A 510–513)
ORGAN_DATASETS: dict[str, tuple[str, set[str]]] = {
    "heart": ("Dataset520_HITL_Heart", {"heart"}),
    "liver": ("Dataset521_HITL_Liver", {"liver"}),
    "lung": ("Dataset522_HITL_Lung", {"lung", "left_lung", "right_lung"}),
    "kidney": ("Dataset523_HITL_Kidney", {"kidney", "left_kidney", "right_kidney"}),
}

ALIAS = {
    "kidney_left": "left_kidney",
    "kidney_right": "right_kidney",
    "lung_left": "left_lung",
    "lung_right": "right_lung",
}


def _normalize_organ(token: str) -> str | None:
    key = token.strip().lower().replace("-", "_")
    key = ALIAS.get(key, key)
    for organ, (_folder, labels) in ORGAN_DATASETS.items():
        if key == organ or key in labels:
            return organ
    return None


def _parse_mask_name(name: str) -> tuple[str, str] | None:
    stem = name
    for ext in (".nii.gz", ".nii"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    parts = stem.split("_")
    if len(parts) < 5:
        return None
    case_id = parts[0]
    organ = _normalize_organ(parts[-1])
    if organ is None and len(parts) >= 6:
        organ = _normalize_organ("_".join(parts[-2:]))
    if organ is None:
        return None
    return case_id, organ


def _find_ct(case_id: str, images_dir: Path, raw_dir: Path) -> Path | None:
    candidates = [
        images_dir / case_id / f"{case_id}_Image0001.nii.gz",
        images_dir / case_id / f"{case_id}.nii.gz",
        images_dir / f"{case_id}_0000.nii.gz",
        raw_dir / case_id / f"{case_id}.nii.gz",
    ]
    for path in candidates:
        if path.is_file():
            return path
    for root in (images_dir / case_id, raw_dir / case_id):
        if not root.is_dir():
            continue
        hits = sorted(root.glob("*.nii.gz")) + sorted(root.glob("*.nii"))
        if hits:
            return hits[0]
    return None


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _read_mask(path: Path):
    import nibabel as nib

    img = nib.load(str(path))
    return np.asanyarray(img.dataobj), img.affine


def _write_binary(out_path: Path, shape, affine, sources: list[Path]) -> bool:
    import nibabel as nib

    combined = np.zeros(shape, dtype=np.uint8)
    any_fg = False
    for src in sources:
        if not src.is_file():
            continue
        arr, _ = _read_mask(src)
        if arr.shape != shape:
            if arr.T.shape == shape:
                arr = arr.T
            else:
                print(f"  skip shape mismatch {src.name}: {arr.shape} vs {shape}")
                continue
        fg = arr > 0
        if np.any(fg):
            any_fg = True
            combined[fg] = 1
    if not any_fg:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(combined, affine), str(out_path))
    return True


def _collect_masks(
    labels_root: Path,
    versions: list[str],
) -> dict[str, dict[str, list[Path]]]:
    """organ → case_id → list of mask paths (to OR-merge)."""
    priority = {v: i for i, v in enumerate(versions)}
    # (organ, case_id, label_token) → best path
    best: dict[tuple[str, str, str], Path] = {}
    for case_dir in sorted(labels_root.iterdir()):
        if not case_dir.is_dir():
            continue
        for version_dir in case_dir.iterdir():
            if not version_dir.is_dir() or version_dir.name not in priority:
                continue
            ver = version_dir.name
            for mask_path in list(version_dir.glob("*.nii.gz")) + list(version_dir.glob("*.nii")):
                parsed = _parse_mask_name(mask_path.name)
                if not parsed:
                    continue
                case_id, organ = parsed
                token = mask_path.name
                for ext in (".nii.gz", ".nii"):
                    if token.endswith(ext):
                        token = token[: -len(ext)]
                        break
                label_token = token.split("_")[-1]
                if len(token.split("_")) >= 6 and label_token in {"lung", "kidney"}:
                    maybe = "_".join(token.split("_")[-2:])
                    if maybe in {"left_lung", "right_lung", "left_kidney", "right_kidney"}:
                        label_token = maybe
                key = (organ, case_id, label_token)
                prev = best.get(key)
                if prev is None or priority[ver] < priority.get(prev.parent.name, 99):
                    best[key] = mask_path

    grouped: dict[str, dict[str, list[Path]]] = {}
    for (organ, case_id, _token), path in best.items():
        grouped.setdefault(organ, {}).setdefault(case_id, []).append(path)
    return grouped


def _write_dataset_json(nnunet_path: Path, organ: str, num_training: int) -> None:
    payload = {
        "name": nnunet_path.name,
        "description": f"HITL fusion/final masks for {organ} (Person B)",
        "reference": "platform v3_fusion / final",
        "licence": "internal-course",
        "release": "0.1",
        "channel_names": {"0": "CT"},
        "labels": {"background": 0, organ: 1},
        "numTraining": num_training,
        "file_ending": ".nii.gz",
        "overwrite_image_reader_writer": "NibabelIOWithReorient",
    }
    (nnunet_path / "dataset.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Platform fusion → nnUNet HITL datasets")
    parser.add_argument("--labels-root", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--images-root", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["v3_fusion", "final"],
        help="Prefer earlier entries",
    )
    parser.add_argument(
        "--organs",
        nargs="+",
        default=["heart", "liver", "lung", "kidney"],
        choices=list(ORGAN_DATASETS.keys()),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.labels_root.is_dir():
        print(f"No labels directory: {args.labels_root}")
        return 1

    grouped = _collect_masks(args.labels_root, args.versions)
    if not any(grouped.get(o) for o in args.organs):
        print(
            "No v3_fusion/final organ masks found. "
            "Run DeepEdit refine + promote on the platform first, "
            "or: scripts/seed_v3_fusion_from_v2.py"
        )
        return 0

    nnunet_raw = args.root / "nnUNet_raw"
    if not args.dry_run:
        nnunet_raw.mkdir(parents=True, exist_ok=True)
        (args.root / "nnUNet_preprocessed").mkdir(parents=True, exist_ok=True)
        (args.root / "nnUNet_results").mkdir(parents=True, exist_ok=True)

    summary: dict[str, list[str]] = {}
    for organ in args.organs:
        folder, _labels = ORGAN_DATASETS[organ]
        cases = grouped.get(organ) or {}
        kept: list[str] = []
        out = nnunet_raw / folder
        images_tr = out / "imagesTr"
        labels_tr = out / "labelsTr"
        for case_id, mask_paths in sorted(cases.items()):
            if args.limit is not None and len(kept) >= args.limit:
                break
            ct = _find_ct(case_id, args.images_root, args.raw_root)
            if ct is None:
                print(f"[{organ}] SKIP no CT for {case_id}")
                continue
            if args.dry_run:
                print(f"[{organ}] would add {case_id} <- {len(mask_paths)} masks")
                kept.append(case_id)
                continue
            import nibabel as nib

            ref = nib.load(str(ct))
            lab_dst = labels_tr / f"{case_id}.nii.gz"
            ok = _write_binary(lab_dst, ref.shape, ref.affine, mask_paths)
            if not ok:
                print(f"[{organ}] empty mask for {case_id}")
                continue
            _link_or_copy(ct, images_tr / f"{case_id}_0000.nii.gz")
            kept.append(case_id)
            print(f"[{organ}] + {case_id}")
        if not args.dry_run:
            images_tr.mkdir(parents=True, exist_ok=True)
            labels_tr.mkdir(parents=True, exist_ok=True)
            _write_dataset_json(out, organ, len(kept))
        summary[organ] = kept
        print(f"[{organ}] n={len(kept)} -> {out}")

    meta = {
        "source": "platform_fusion",
        "labels_root": str(args.labels_root),
        "root": str(args.root),
        "versions": args.versions,
        "organs": {
            k: {"dataset": ORGAN_DATASETS[k][0], "n": len(v), "cases": v} for k, v in summary.items()
        },
    }
    out_meta = args.root / "hitl_fusion_convert_meta.json"
    if not args.dry_run:
        out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {out_meta}")
    else:
        print(json.dumps(meta, indent=2, ensure_ascii=False))
    print("Next: nnUNetv2_plan_and_preprocess -d 520 521 522 523 then train Dataset520–523")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
