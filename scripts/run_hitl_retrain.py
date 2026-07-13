"""Person B HITL retrain orchestrator: fusion harvest → DeepEdit / nnUNet prepare.

Does NOT run long nnUNet training by default (use --train-deepedit for few-shot).

Usage:
  D:\\anaconda\\python.exe scripts\\run_hitl_retrain.py --dry-run --seed-from-v2 --prepare-deepedit --prepare-nnunet
  D:\\anaconda\\python.exe scripts\\run_hitl_retrain.py --seed-from-v2 --prepare-deepedit --prepare-nnunet
  D:\\anaconda\\python.exe scripts\\run_hitl_retrain.py --prepare-deepedit --train-deepedit --epochs 5
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def _run(cmd: list[str]) -> int:
    print(">", " ".join(cmd))
    return int(subprocess.run(cmd, cwd=str(ROOT)).returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="HITL fusion → retrain prepare loop")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to harvest scripts")
    parser.add_argument(
        "--seed-from-v2",
        action="store_true",
        help="Copy v2_ai → v3_fusion for smoke when no real fusion yet",
    )
    parser.add_argument("--prepare-deepedit", action="store_true", help="Harvest → hm_2_deepedit manifest")
    parser.add_argument("--prepare-nnunet", action="store_true", help="Harvest → Dataset520–523")
    parser.add_argument("--train-deepedit", action="store_true", help="Few-shot resume train DeepEdit")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--manifest", default=r"E:\lxy\hm_2_deepedit\dataset\manifest.json")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    if not any([args.seed_from_v2, args.prepare_deepedit, args.prepare_nnunet, args.train_deepedit]):
        parser.print_help()
        print(
            "\nTip: pass at least one of "
            "--seed-from-v2 / --prepare-deepedit / --prepare-nnunet / --train-deepedit"
        )
        return 2

    if args.seed_from_v2:
        cmd = [PY, str(ROOT / "scripts" / "seed_v3_fusion_from_v2.py")]
        if args.dry_run:
            cmd.append("--dry-run")
        else:
            cmd.append("--register-db")
        if _run(cmd) != 0:
            return 1

    if args.prepare_deepedit:
        cmd = [PY, str(ROOT / "scripts" / "prepare_deepedit_from_fusion.py")]
        if args.dry_run:
            cmd.append("--dry-run")
        if _run(cmd) != 0:
            return 1

    if args.prepare_nnunet:
        cmd = [PY, str(ROOT / "scripts" / "prepare_organs_nnunet_from_fusion.py")]
        if args.dry_run:
            cmd.append("--dry-run")
        if _run(cmd) != 0:
            return 1

    if args.train_deepedit:
        if args.dry_run:
            print("> (skip train_deepedit in --dry-run)")
        else:
            cmd = [
                PY,
                str(ROOT / "scripts" / "train_deepedit.py"),
                "--manifest",
                args.manifest,
                "--resume",
                "--epochs",
                str(args.epochs),
                "--crop",
                "64",
                "128",
                "128",
                "--limit",
                str(args.limit),
            ]
            if _run(cmd) != 0:
                return 1
            print("Restart DeepEdit: powershell -File scripts\\start_deepedit.ps1")

    print("HITL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
