"""Plan A runner: preprocess (3d_fullres, batch_size=1) + short train for heart/liver/lung/kidney.

Usage:
  D:\\anaconda\\python.exe scripts\\run_organs_nnunet_planA.py
  D:\\anaconda\\python.exe scripts\\run_organs_nnunet_planA.py --epochs 10 --organs liver heart
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NNUNET_ROOT = Path(r"E:\lxy\hm_2_organs_nnunet")
PYTHON = Path(r"D:\anaconda\python.exe")

DATASETS = {
    "heart": 510,
    "liver": 511,
    "lung": 512,
    "kidney": 513,
}

TRAINER_BY_EPOCHS = {
    5: "nnUNetTrainer_5epochs",
    10: "nnUNetTrainer_10epochs",
    20: "nnUNetTrainer_20epochs",
    50: "nnUNetTrainer_50epochs",
    100: "nnUNetTrainer_100epochs",
}


def _env(nnunet_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["nnUNet_raw"] = str(nnunet_root / "nnUNet_raw")
    env["nnUNet_preprocessed"] = str(nnunet_root / "nnUNet_preprocessed")
    env["nnUNet_results"] = str(nnunet_root / "nnUNet_results")
    env["nnUNet_n_proc_DA"] = env.get("nnUNet_n_proc_DA", "2")
    return env


def _run(cmd: list[str], env: dict[str, str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(">>", " ".join(cmd))
    print("   log:", log_path)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    return int(proc.returncode)


def _patch_batch_size(plans_path: Path, configuration: str = "3d_fullres", batch_size: int = 1) -> None:
    data = json.loads(plans_path.read_text(encoding="utf-8"))
    cfg = data.get("configurations", {}).get(configuration)
    if not isinstance(cfg, dict):
        raise SystemExit(f"No configuration {configuration} in {plans_path}")
    old = cfg.get("batch_size")
    cfg["batch_size"] = batch_size
    plans_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Patched {plans_path.name} {configuration} batch_size {old} -> {batch_size}")


def _find_plans(preprocessed: Path, dataset_id: int) -> Path:
    matches = sorted(preprocessed.glob(f"Dataset{dataset_id:03d}_*/nnUNetPlans.json"))
    if not matches:
        raise SystemExit(f"Plans not found for dataset {dataset_id} under {preprocessed}")
    return matches[0]


def _parse_best_dice(fold_dir: Path) -> float | None:
    # Prefer progress.npy / training log "Pseudo dice"
    log_files = sorted(fold_dir.glob("training_log_*.txt"))
    best = None
    for log in log_files:
        text = log.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"Mean Validation Dice[:\s]+([0-9.]+)", text):
            best = float(m.group(1))
        # also catch "New best EMA pseudo dice: 0.xx"
        for m in re.finditer(r"Pseudo dice[^\n]*?\[([0-9.]+)", text):
            val = float(m.group(1))
            best = val if best is None else max(best, val)
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_NNUNET_ROOT)
    parser.add_argument("--python", type=Path, default=PYTHON)
    parser.add_argument("--epochs", type=int, default=100, choices=sorted(TRAINER_BY_EPOCHS))
    parser.add_argument("--organs", nargs="+", default=["liver", "kidney", "lung", "heart"])
    parser.add_argument("--skip-convert", action="store_true")
    parser.add_argument("--skip-preprocess", action="store_true")
    parser.add_argument(
        "--auto-skip-preprocess",
        action="store_true",
        help="Skip preprocess for an organ if nnUNetPlans_3d_fullres already has cases",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--fold", type=int, default=0)
    args = parser.parse_args()

    py = str(args.python)
    env = _env(args.root)
    logs = args.root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    trainer = TRAINER_BY_EPOCHS[args.epochs]

    if not args.skip_convert:
        convert_script = ROOT / "scripts" / "prepare_organs_nnunet_from_deepedit.py"
        code = _run(
            [py, str(convert_script), "--root", str(args.root), "--limit", str(args.limit), "--organs", *args.organs],
            env,
            logs / "00_convert.log",
        )
        if code != 0:
            raise SystemExit(f"convert failed: {code}")

    summary: dict[str, dict] = {"epochs": args.epochs, "trainer": trainer, "organs": {}}

    for organ in args.organs:
        dataset_id = DATASETS[organ]
        t0 = time.time()
        organ_log = logs / f"{organ}.log"

        plans_candidates = sorted((args.root / "nnUNet_preprocessed").glob(f"Dataset{dataset_id:03d}_*"))
        preprocessed_dir = None
        if plans_candidates:
            cand = plans_candidates[0] / "nnUNetPlans_3d_fullres"
            if cand.is_dir() and any(cand.iterdir()):
                preprocessed_dir = cand

        do_preprocess = not args.skip_preprocess
        if args.auto_skip_preprocess and preprocessed_dir is not None:
            print(f"[{organ}] auto-skip preprocess ({preprocessed_dir})")
            do_preprocess = False

        if do_preprocess:
            code = _run(
                [
                    "nnUNetv2_plan_and_preprocess",
                    "-d",
                    str(dataset_id),
                    "-c",
                    "3d_fullres",
                    "--verify_dataset_integrity",
                    "-npfp",
                    "1",
                    "-np",
                    "1",
                ],
                env,
                organ_log,
            )
            if code != 0:
                print(f"[{organ}] preprocess FAILED")
                summary["organs"][organ] = {"status": "preprocess_failed", "returncode": code}
                continue

        plans = _find_plans(args.root / "nnUNet_preprocessed", dataset_id)
        _patch_batch_size(plans, "3d_fullres", 1)

        # train
        code = _run(
            [
                "nnUNetv2_train",
                str(dataset_id),
                "3d_fullres",
                str(args.fold),
                "-tr",
                trainer,
            ],
            env,
            organ_log,
        )
        elapsed = time.time() - t0
        results_glob = sorted(
            (args.root / "nnUNet_results").glob(
                f"Dataset{dataset_id:03d}_*/{trainer}__nnUNetPlans__3d_fullres/fold_{args.fold}"
            )
        )
        fold_dir = results_glob[0] if results_glob else None
        dice = _parse_best_dice(fold_dir) if fold_dir else None
        summary["organs"][organ] = {
            "dataset_id": dataset_id,
            "status": "ok" if code == 0 else "train_failed",
            "returncode": code,
            "elapsed_sec": round(elapsed, 1),
            "best_val_dice_parsed": dice,
            "fold_dir": str(fold_dir) if fold_dir else None,
        }
        print(f"[{organ}] done code={code} elapsed={elapsed/60:.1f}min dice={dice}")

    out = args.root / "planA_train_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
