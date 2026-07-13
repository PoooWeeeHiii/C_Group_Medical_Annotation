"""Convert DeepEdit multi-organ dataset → binary nnUNet datasets (Plan A).

Organs:
  Dataset510_DeepEdit_Heart
  Dataset511_DeepEdit_Liver
  Dataset512_DeepEdit_Lung     (left_lung | right_lung)
  Dataset513_DeepEdit_Kidney   (left_kidney | right_kidney)

Default source: E:\\lxy\\hm_2_deepedit\\dataset
Default root:   E:\\lxy\\hm_2_organs_nnunet

Example:
  D:\\anaconda\\python.exe scripts\\prepare_organs_nnunet_from_deepedit.py --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

DEFAULT_SRC = Path(r"E:\lxy\hm_2_deepedit\dataset")
DEFAULT_ROOT = Path(r"E:\lxy\hm_2_organs_nnunet")

ORGAN_DATASETS: dict[str, tuple[str, list[str]]] = {
    # key: (folder_name, source label folder names to OR-merge)
    "heart": ("Dataset510_DeepEdit_Heart", ["heart"]),
    "liver": ("Dataset511_DeepEdit_Liver", ["liver"]),
    "lung": ("Dataset512_DeepEdit_Lung", ["left_lung", "right_lung"]),
    "kidney": ("Dataset513_DeepEdit_Kidney", ["left_kidney", "right_kidney"]),
}


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _read_mask(path: Path) -> tuple[np.ndarray, np.ndarray]:
    import nibabel as nib

    img = nib.load(str(path))
    arr = np.asanyarray(img.dataobj)
    return arr, img.affine


def _write_binary_mask(out_path: Path, shape: tuple[int, ...], affine, sources: list[Path]) -> bool:
    import nibabel as nib

    combined = np.zeros(shape, dtype=np.uint8)
    any_fg = False
    for src in sources:
        if not src.is_file():
            continue
        arr, _ = _read_mask(src)
        if arr.shape != shape:
            # try transpose common mismatches
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


def _write_dataset_json(nnunet_path: Path, organ: str, num_training: int) -> None:
    payload = {
        "name": nnunet_path.name,
        "description": f"Plan A short 3d_fullres from DeepEdit pseudo-labels ({organ})",
        "reference": "Person B DeepEdit dataset / TotalSeg pseudo",
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


def convert_organ(
    src_root: Path,
    nnunet_raw: Path,
    organ: str,
    folder_name: str,
    label_dirs: list[str],
    limit: int | None,
    case_ids: list[str],
) -> list[str]:
    out = nnunet_raw / folder_name
    images_tr = out / "imagesTr"
    labels_tr = out / "labelsTr"
    images_tr.mkdir(parents=True, exist_ok=True)
    labels_tr.mkdir(parents=True, exist_ok=True)

    kept: list[str] = []
    for case_id in case_ids:
        if limit is not None and len(kept) >= limit:
            break
        img_src = src_root / "images" / f"{case_id}_0000.nii.gz"
        if not img_src.is_file():
            print(f"[{organ}] missing CT {img_src.name}")
            continue
        import nibabel as nib

        ref = nib.load(str(img_src))
        shape = ref.shape
        affine = ref.affine
        mask_sources = [src_root / "labels" / d / f"{case_id}.nii.gz" for d in label_dirs]
        lab_dst = labels_tr / f"{case_id}.nii.gz"
        ok = _write_binary_mask(lab_dst, shape, affine, mask_sources)
        if not ok:
            print(f"[{organ}] empty/missing label for {case_id}")
            if lab_dst.exists():
                lab_dst.unlink()
            continue
        _link_or_copy(img_src, images_tr / f"{case_id}_0000.nii.gz")
        kept.append(case_id)
        print(f"[{organ}] + {case_id}")

    _write_dataset_json(out, organ, len(kept))
    print(f"[{organ}] wrote {len(kept)} cases -> {out}")
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan A: DeepEdit organs → nnUNet raw")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--organs",
        nargs="+",
        default=["heart", "liver", "lung", "kidney"],
        choices=list(ORGAN_DATASETS.keys()),
    )
    args = parser.parse_args()

    src: Path = args.src
    if not (src / "images").is_dir():
        raise SystemExit(f"Missing images under {src}")

    case_ids = sorted(
        p.name.replace("_0000.nii.gz", "") for p in (src / "images").glob("*_0000.nii.gz")
    )
    if not case_ids:
        raise SystemExit(f"No CT volumes in {src / 'images'}")

    nnunet_raw = args.root / "nnUNet_raw"
    nnunet_raw.mkdir(parents=True, exist_ok=True)
    (args.root / "nnUNet_preprocessed").mkdir(parents=True, exist_ok=True)
    (args.root / "nnUNet_results").mkdir(parents=True, exist_ok=True)

    summary: dict[str, list[str]] = {}
    for organ in args.organs:
        folder, labels = ORGAN_DATASETS[organ]
        kept = convert_organ(src, nnunet_raw, organ, folder, labels, args.limit, case_ids)
        summary[organ] = kept

    meta = {
        "source": str(src),
        "root": str(args.root),
        "organs": {k: {"dataset": ORGAN_DATASETS[k][0], "n": len(v), "cases": v} for k, v in summary.items()},
    }
    out_meta = args.root / "planA_convert_meta.json"
    out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
