"""Weak-supervision iteration scaffold (Person B).

Platform exports:
  - weak  label_set → typically v3_preview (pseudo from few-shot / coarse propagation)
  - dense label_set → typically final / v3_fusion

This script consumes those nnU-Net-style export folders and sketches a
scribble / pseudo-label self-training loop. Wire real training in Day4+.

Usage:
  python -m ai.weak_supervise \\
    --weak-dir dataset/exports/Dataset0001 \\
    --dense-dir dataset/exports/Dataset0002 \\
    --rounds 2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dataset_json(export_dir: Path) -> dict:
    path = export_dir / "dataset.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset.json under {export_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _count_cases(export_dir: Path) -> dict[str, int]:
    return {
        "imagesTr": len(list((export_dir / "imagesTr").glob("*.nii*"))) if (export_dir / "imagesTr").exists() else 0,
        "labelsTr": len(list((export_dir / "labelsTr").glob("*.nii*"))) if (export_dir / "labelsTr").exists() else 0,
        "imagesTs": len(list((export_dir / "imagesTs").glob("*.nii*"))) if (export_dir / "imagesTs").exists() else 0,
        "labelsTs": len(list((export_dir / "labelsTs").glob("*.nii*"))) if (export_dir / "labelsTs").exists() else 0,
    }


def summarize_export(name: str, export_dir: Path | None) -> None:
    if export_dir is None:
        print(f"[{name}] (not provided)")
        return
    if not export_dir.exists():
        print(f"[{name}] missing: {export_dir}")
        return
    meta = _load_dataset_json(export_dir)
    counts = _count_cases(export_dir)
    print(f"[{name}] {export_dir}")
    print(f"  name={meta.get('name')} labels={meta.get('labels')}")
    print(f"  files={counts}")


def run_pseudo_label_round(round_idx: int, weak_dir: Path, out_dir: Path) -> None:
    """Placeholder: copy weak labels as 'refined' pseudo labels for next round.

    Real implementation should:
      1. Train on current weak/pseudo labels
      2. Predict on unlabeled / sparse cases
      3. Keep high-confidence voxels (or CRF / random-walker refine)
      4. Write next-round labelsTr under out_dir
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "round": round_idx,
        "source_weak_dir": str(weak_dir),
        "status": "skeleton_only",
        "todo": [
            "load nnU-Net / UNet checkpoint",
            "predict probability maps",
            "threshold + connected-component cleanup",
            "write labelsTr/*.nii.gz",
        ],
    }
    (out_dir / f"pseudo_round_{round_idx}.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[round {round_idx}] wrote {out_dir / f'pseudo_round_{round_idx}.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Weak-supervision / pseudo-label iteration (Person B)")
    parser.add_argument("--weak-dir", type=Path, help="Export dir for weak/pseudo labels (label_set=weak)")
    parser.add_argument("--dense-dir", type=Path, help="Export dir for dense/refined labels (label_set=dense)")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dataset" / "weak_supervise_runs")
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()

    print("[Person B] weak supervision scaffold")
    summarize_export("weak", args.weak_dir)
    summarize_export("dense", args.dense_dir)

    if args.weak_dir and args.weak_dir.exists():
        for round_idx in range(1, max(1, args.rounds) + 1):
            run_pseudo_label_round(round_idx, args.weak_dir, args.out_dir / f"round_{round_idx}")
    else:
        print("Provide --weak-dir pointing to a platform weak export to start pseudo-label rounds.")

    print("Done. Platform remains responsible for exporting weak vs dense splits;")
    print("this script iterates scribbles/pseudo labels offline.")


if __name__ == "__main__":
    main()
