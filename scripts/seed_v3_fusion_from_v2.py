"""Seed v3_fusion from existing v2_ai masks (pipeline smoke without UI).

Copies NIfTI under dataset/labels/<Case>/v2_ai/ → .../v3_fusion/ with renamed
version token, and upserts mask/version rows into SQLite.

Usage:
  D:\\anaconda\\python.exe scripts\\seed_v3_fusion_from_v2.py --dry-run
  D:\\anaconda\\python.exe scripts\\seed_v3_fusion_from_v2.py --case Case9011
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LABELS = PROJECT_ROOT / "dataset" / "labels"


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy v2_ai → v3_fusion for HITL smoke")
    parser.add_argument("--labels-root", type=Path, default=LABELS)
    parser.add_argument("--case", default=None, help="Only one case_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--register-db", action="store_true", help="Upsert into SQLite")
    args = parser.parse_args()

    if not args.labels_root.is_dir():
        print(f"No labels dir: {args.labels_root}")
        return 1

    copied = 0
    for case_dir in sorted(args.labels_root.iterdir()):
        if not case_dir.is_dir():
            continue
        if args.case and case_dir.name != args.case:
            continue
        src_dir = case_dir / "v2_ai"
        if not src_dir.is_dir():
            continue
        dst_dir = case_dir / "v3_fusion"
        for src in list(src_dir.glob("*.nii.gz")) + list(src_dir.glob("*.nii")):
            new_name = src.name.replace("_v2_ai_", "_v3_fusion_")
            dst = dst_dir / new_name
            print(f"{'DRY ' if args.dry_run else ''}{src.relative_to(args.labels_root)} -> {dst.relative_to(args.labels_root)}")
            if args.dry_run:
                copied += 1
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            if args.register_db:
                from backend.app.services.sqlite_service import get_record, upsert_record

                # Parse Case_Image_Mask from filename
                stem = new_name
                for ext in (".nii.gz", ".nii"):
                    if stem.endswith(ext):
                        stem = stem[: -len(ext)]
                        break
                parts = stem.split("_")
                if len(parts) < 5:
                    continue
                case_id, image_id, mask_id = parts[0], parts[1], parts[2]
                label = parts[-1]
                if len(parts) >= 6 and parts[-2] in {"left", "right"}:
                    label = f"{parts[-2]}_{parts[-1]}"
                fusion_mask_id = f"{mask_id}_fusion"
                rel = str(dst.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if get_record("masks", "mask_id", fusion_mask_id) is None:
                    upsert_record(
                        "masks",
                        {
                            "mask_id": fusion_mask_id,
                            "annotation_id": None,
                            "case_id": case_id,
                            "image_id": image_id,
                            "path": rel,
                            "version": "v3_fusion",
                            "label": label,
                            "mask_format": "nii.gz",
                            "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "model_id": "seed_from_v2_ai",
                        },
                    )
                upsert_record(
                    "versions",
                    {
                        "case_id": case_id,
                        "version": "v3_fusion",
                        "annotation": fusion_mask_id,
                        "model": "seed_from_v2_ai",
                        "dataset": None,
                        "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                )

    print(f"copied={copied}")
    if copied == 0:
        print("No v2_ai masks found. Run organ/spleen AI predict first.")
    else:
        print("Next: scripts/prepare_deepedit_from_fusion.py")
        print("      scripts/prepare_organs_nnunet_from_fusion.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
