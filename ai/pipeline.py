"""Convert Person A raw uploads or local Lung examples into dataset/images + labels."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ai.config import (
    DATASET_ROOT,
    DEFAULT_LABEL,
    IMAGES_DIR,
    LABELS_DIR,
    RAW_DIR,
    SPLITS_DIR,
    VERSION_AI,
    VERSION_MANUAL,
)
from ai.preprocess import (
    best_tumor_slice,
    export_slice_pair,
    image_path,
    label_path,
    load,
    load_dicom_series,
    load_seg_dicom,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LUNG_DICOM_CASES = {
    "Case0001": {
        "patient_id": "LUNG1-001",
        "ct_dir": "LUNG1-001/09-18-2008-StudyID-NA-69331/0.000000-NA-82046",
        "seg_file": "LUNG1-001/09-18-2008-StudyID-NA-69331/300.000000-Segmentation-9.554/1-1.dcm",
        "image_id": "Image0001",
        "mask_id": "Mask0001",
        "version": VERSION_AI,
    },
    "Case0002": {
        "patient_id": "LUNG1-002",
        "ct_dir": "LUNG1-002/01-01-2014-StudyID-NA-85095/1.000000-NA-61228",
        "seg_file": "LUNG1-002/01-01-2014-StudyID-NA-85095/300.000000-Segmentation-5.421/1-1.dcm",
        "image_id": "Image0002",
        "mask_id": "Mask0001",
        "version": VERSION_AI,
    },
    "Case0003": {
        "patient_id": "LUNG1-003",
        "ct_dir": "LUNG1-003/01-01-2014-StudyID-NA-34270/1.000000-NA-28595",
        "seg_file": "LUNG1-003/01-01-2014-StudyID-NA-34270/300.000000-Segmentation-2.316/1-1.dcm",
        "image_id": "Image0003",
        "mask_id": "Mask0001",
        "version": VERSION_AI,
    },
}

NRRD_CASE = {
    "Case0004": {
        "patient_id": "patient1",
        "ct_file": "patient1/p1.nrrd",
        "label_file": "patient1/p1-label.nrrd",
        "image_id": "Image0001",
        "mask_id": "Mask0001",
        "version": VERSION_MANUAL,
    }
}


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))


def register_raw_copy(case_id: str, source_path: Path) -> Path:
    target_dir = RAW_DIR / case_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source_path.name
    if source_path.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_path, target)
    else:
        shutil.copy2(source_path, target)
    return target


def convert_dicom_case(case_id: str, cfg: dict, lung_root: Path, label: str = DEFAULT_LABEL) -> dict:
    ct_dir = lung_root / cfg["ct_dir"]
    seg_file = lung_root / cfg["seg_file"]
    ct_vol = load_dicom_series(ct_dir)
    mask_vol = load_seg_dicom(seg_file)
    z = best_tumor_slice(mask_vol)
    out_img = image_path(case_id, cfg["image_id"], label)
    out_msk = label_path(case_id, cfg["image_id"], cfg["mask_id"], cfg["version"], label)
    export_slice_pair(ct_vol, mask_vol, z, out_img, out_msk)
    register_raw_copy(case_id, ct_dir)
    return {
        "case_id": case_id,
        "image_id": cfg["image_id"],
        "mask_id": cfg["mask_id"],
        "patient_id": cfg["patient_id"],
        "image_path": _rel(out_img),
        "label_path": _rel(out_msk),
        "version": cfg["version"],
        "label": label,
        "slice_index": z,
    }


def convert_nrrd_case(case_id: str, cfg: dict, lung_root: Path, label: str = DEFAULT_LABEL) -> dict:
    ct_vol = load(lung_root / cfg["ct_file"])
    mask_vol = load(lung_root / cfg["label_file"])
    if mask_vol.ndim == 4:
        mask_vol = mask_vol[..., 0]
    mask_vol = (mask_vol > 0).astype("uint8")
    z = best_tumor_slice(mask_vol)
    out_img = image_path(case_id, cfg["image_id"], label)
    out_msk = label_path(case_id, cfg["image_id"], cfg["mask_id"], cfg["version"], label)
    export_slice_pair(ct_vol, mask_vol, z, out_img, out_msk)
    register_raw_copy(case_id, lung_root / cfg["ct_file"])
    return {
        "case_id": case_id,
        "image_id": cfg["image_id"],
        "mask_id": cfg["mask_id"],
        "patient_id": cfg["patient_id"],
        "image_path": _rel(out_img),
        "label_path": _rel(out_msk),
        "version": cfg["version"],
        "label": label,
        "slice_index": z,
    }


def convert_lung_examples(lung_root: Path, label: str = DEFAULT_LABEL) -> list[dict]:
    entries: list[dict] = []
    for case_id, cfg in LUNG_DICOM_CASES.items():
        entries.append(convert_dicom_case(case_id, cfg, lung_root, label))
    for case_id, cfg in NRRD_CASE.items():
        entries.append(convert_nrrd_case(case_id, cfg, lung_root, label))
    return entries


def write_manifest(entries: list[dict], dataset_id: str = "Dataset0001") -> Path:
    manifest = {"dataset_id": dataset_id, "entries": entries}
    out = SPLITS_DIR / f"{dataset_id}_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def process_raw_upload(case_id: str, image_id: str = "Image0001", mask_id: str = "Mask0001") -> dict | None:
    """Process files uploaded by Person A under dataset/raw/CaseXXXX/."""
    raw_case_dir = RAW_DIR / case_id
    if not raw_case_dir.exists():
        return None
    children = list(raw_case_dir.iterdir())
    if not children:
        return None
    source = children[0]
    if source.is_dir():
        ct_vol = load_dicom_series(source)
        mask_vol = None
    else:
        ct_vol = load(source)
        mask_vol = None
    z = ct_vol.shape[0] // 2
    out_img = image_path(case_id, image_id)
    export_slice_pair(ct_vol, mask_vol, z, out_img, None)
    return {"case_id": case_id, "image_id": image_id, "image_path": _rel(out_img), "slice_index": z}
