"""Harvest platform v3_fusion / final masks into DeepEdit few-shot dataset.

Scans dataset/labels/<Case*>/<version>/*_<organ>.nii.gz and copies CT+mask
pairs into a DeepEdit manifest root (default E:\\lxy\\hm_2_deepedit\\dataset).

Usage:
  D:\\anaconda\\python.exe scripts\\prepare_deepedit_from_fusion.py
  D:\\anaconda\\python.exe scripts\\prepare_deepedit_from_fusion.py --versions v3_fusion final
  D:\\anaconda\\python.exe scripts\\train_deepedit.py --manifest E:\\lxy\\hm_2_deepedit\\dataset\\manifest.json --resume --epochs 10
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(r"E:\lxy\hm_2_deepedit\dataset")
ORGANS = {
    "heart",
    "liver",
    "spleen",
    "left_lung",
    "right_lung",
    "left_kidney",
    "right_kidney",
    "kidney",
    "lung",
}
# Map platform filenames / aliases → DeepEdit organ keys
ALIAS = {
    "kidney_left": "left_kidney",
    "kidney_right": "right_kidney",
    "lung_left": "left_lung",
    "lung_right": "right_lung",
}


def _normalize_organ(token: str) -> str | None:
    key = token.strip().lower().replace("-", "_")
    key = ALIAS.get(key, key)
    if key in ORGANS:
        return key
    return None


def _parse_mask_name(name: str) -> tuple[str, str] | None:
    """Parse Case0001_Image0001_Mask0001_v3_fusion_spleen.nii.gz → (case, organ)."""
    stem = name
    for ext in (".nii.gz", ".nii", ".nrrd"):
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
    # fuzzy: any nifti under case folder
    for root in (images_dir / case_id, raw_dir / case_id):
        if not root.is_dir():
            continue
        hits = sorted(root.glob("*.nii.gz")) + sorted(root.glob("*.nii"))
        if hits:
            return hits[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy v3_fusion masks into DeepEdit dataset")
    parser.add_argument("--labels-root", type=Path, default=PROJECT_ROOT / "dataset" / "labels")
    parser.add_argument("--images-root", type=Path, default=PROJECT_ROOT / "dataset" / "images")
    parser.add_argument("--raw-root", type=Path, default=PROJECT_ROOT / "dataset" / "raw")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["v3_fusion", "final", "v3_preview"],
        help="Prefer earlier entries when multiple versions exist for same case+organ",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    labels_root: Path = args.labels_root
    if not labels_root.is_dir():
        print(f"No labels directory: {labels_root}")
        return 1

    # Collect best mask per (case, organ) by version priority
    chosen: dict[tuple[str, str], Path] = {}
    priority = {v: i for i, v in enumerate(args.versions)}
    for case_dir in sorted(labels_root.iterdir()):
        if not case_dir.is_dir():
            continue
        for version_dir in case_dir.iterdir():
            if not version_dir.is_dir():
                continue
            ver = version_dir.name
            if ver not in priority:
                continue
            for mask_path in list(version_dir.glob("*.nii.gz")) + list(version_dir.glob("*.nii")):
                parsed = _parse_mask_name(mask_path.name)
                if not parsed:
                    continue
                case_id, organ = parsed
                key = (case_id, organ)
                prev = chosen.get(key)
                if prev is None:
                    chosen[key] = mask_path
                    continue
                prev_ver = prev.parent.name
                if priority.get(ver, 99) < priority.get(prev_ver, 99):
                    chosen[key] = mask_path

    if not chosen:
        print(
            "No v3_fusion/final masks found yet. "
            "After DeepEdit refine on the platform, re-run this script."
        )
        return 0

    out_root: Path = args.out_root
    images_out = out_root / "images"
    labels_out = out_root / "labels"
    records: list[dict] = []
    copied = 0
    skipped = 0

    for (case_id, organ), mask_path in sorted(chosen.items()):
        ct_src = _find_ct(case_id, args.images_root, args.raw_root)
        if ct_src is None:
            print(f"SKIP no CT for {case_id} ({organ})")
            skipped += 1
            continue
        img_name = f"{case_id}_0000.nii.gz"
        lab_rel = Path("labels") / organ / f"{case_id}.nii.gz"
        img_dst = images_out / img_name
        lab_dst = out_root / lab_rel
        if not args.dry_run:
            images_out.mkdir(parents=True, exist_ok=True)
            lab_dst.parent.mkdir(parents=True, exist_ok=True)
            if not img_dst.exists():
                shutil.copy2(ct_src, img_dst)
            shutil.copy2(mask_path, lab_dst)
        records.append(
            {
                "case_id": case_id,
                "organ": organ,
                "image": f"images/{img_name}",
                "label": lab_rel.as_posix(),
                "source_version": mask_path.parent.name,
                "source_mask": str(mask_path.relative_to(PROJECT_ROOT))
                if mask_path.is_relative_to(PROJECT_ROOT)
                else str(mask_path),
            }
        )
        copied += 1
        print(f"OK {case_id}/{organ} <- {mask_path.parent.name}")

    # Merge with existing manifest records (keep previous pseudo-labels)
    manifest_path = out_root / "manifest.json"
    existing: list[dict] = []
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing = list(data.get("records") or [])
        except Exception:
            existing = []

    by_key = {(r.get("case_id"), r.get("organ")): r for r in existing if r.get("case_id") and r.get("organ")}
    for rec in records:
        by_key[(rec["case_id"], rec["organ"])] = rec
    merged = list(by_key.values())
    counts: dict[str, int] = {}
    for rec in merged:
        organ = str(rec.get("organ") or "unknown")
        counts[organ] = counts.get(organ, 0) + 1

    payload = {
        "organs": sorted({str(r.get("organ")) for r in merged if r.get("organ")}),
        "n_records": len(merged),
        "counts_by_organ": counts,
        "records": merged,
        "updated_by": "prepare_deepedit_from_fusion.py",
    }
    if not args.dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"copied={copied} skipped={skipped} manifest_records={len(merged)} -> {manifest_path}")
    print("Next: train with --manifest and --resume, e.g.")
    print(
        f"  D:\\anaconda\\python.exe scripts\\train_deepedit.py "
        f"--manifest {manifest_path} --resume --epochs 10 --crop 64 128 128"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
