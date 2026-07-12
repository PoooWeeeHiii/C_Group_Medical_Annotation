"""Import local CT cases similar to patient1.zip into the platform case center.

Sources:
  - D:\\label_platform\\patient1.zip  (NRRD CT + label; may already exist)
  - D:\\hm_2_spleen\\raw_data\\Task09_Spleen  (MSD spleen CT + labels)
  - D:\\hm_2_totalseg\\extracted\\sXXXX  (TotalSeg CT + organ segmentations)

Usage:
  python scripts/import_local_cases.py
  python scripts/import_local_cases.py --task09 8 --totalseg 3 --attach-labels
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

TASK09_ROOT = Path(r"D:\hm_2_spleen\raw_data\Task09_Spleen")
TOTALSEG_EXTRACTED = Path(r"D:\hm_2_totalseg\extracted")
PATIENT1_ZIP = Path(r"D:\label_platform\patient1.zip")

DEFAULT_ORGANS = [
    "spleen",
    "liver",
    "kidney_left",
    "kidney_right",
    "pancreas",
    "stomach",
    "gallbladder",
]


def _upload_file(api: str, path: Path, *, source_group: str, patient_id: str, modality: str = "CT") -> dict:
    boundary = "----LocalImportBoundary"
    data = path.read_bytes()
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode()
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += data + b"\r\n"
    for name, value in (
        ("source_group", source_group),
        ("patient_id", patient_id),
        ("modality", modality),
    ):
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        api.rstrip("/") + "/api/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_cases(api: str) -> list[dict]:
    with urllib.request.urlopen(api.rstrip("/") + "/api/cases", timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return list(payload.get("items") or [])


def _read_mask_array(path: Path) -> tuple[np.ndarray, object | None]:
    try:
        import SimpleITK as sitk

        image = sitk.ReadImage(str(path))
        array = sitk.GetArrayFromImage(image)
        if array.ndim == 2:
            array = array.reshape((1, array.shape[0], array.shape[1]))
        return (np.asarray(array) > 0).astype(np.uint8), image
    except Exception:
        import nibabel as nib

        array = np.asanyarray(nib.load(str(path)).dataobj)
        if array.ndim == 3:
            array = np.transpose(array, (2, 1, 0))
        elif array.ndim == 2:
            array = array.reshape((1, array.shape[1], array.shape[0]))
        return (np.asarray(array) > 0).astype(np.uint8), None


def _attach_mask(
    *,
    case_id: str,
    image_id: str,
    label: str,
    mask_array: np.ndarray,
    version: str = "v1_manual",
) -> str:
    from backend.app.services.mask_service import _append_3d_mask_record
    from backend.app.services.medical_image_service import load_volume

    _image, volume = load_volume(image_id)
    if mask_array.shape != volume.array.shape[:3]:
        import SimpleITK as sitk

        # Resample mask to image geometry when needed.
        ref = sitk.GetImageFromArray(volume.array.astype(np.float32))
        ref.SetSpacing(tuple(float(v) for v in volume.spacing[:3]))
        ref.SetOrigin(tuple(float(v) for v in volume.origin[:3]))
        moving = sitk.GetImageFromArray(mask_array.astype(np.uint8))
        moving.SetSpacing(tuple(float(v) for v in volume.spacing[:3]))
        moving.SetOrigin(tuple(float(v) for v in volume.origin[:3]))
        resampled = sitk.Resample(moving, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
        mask_array = (sitk.GetArrayFromImage(resampled) > 0).astype(np.uint8)

    if not np.any(mask_array):
        return ""
    mask, _path = _append_3d_mask_record(
        masks=[],
        request_case_id=case_id,
        image_id=image_id,
        version=version,
        label=label,
        encoding=f"imported_label:{label}",
        source_mask_ids=[],
        mask_stack=mask_array,
        volume=volume,
        annotation_id=f"AnnotationImport_{image_id}_{label}",
        label_type="dense",
    )
    return mask.mask_id


def _existing_patient_ids(api: str) -> set[str]:
    return {str(item.get("patient_id") or item.get("case_id") or "") for item in _list_cases(api)}


def import_patient1(api: str, attach_labels: bool) -> dict | None:
    if not PATIENT1_ZIP.exists():
        print(f"[skip] patient1.zip missing: {PATIENT1_ZIP}")
        return None
    existing = _existing_patient_ids(api)
    # Case9003 already holds patient1.zip; avoid duplicate upload unless requested.
    for case in _list_cases(api):
        images = []
        try:
            with urllib.request.urlopen(api.rstrip("/") + f"/api/case/{case['case_id']}", timeout=60) as resp:
                detail = json.loads(resp.read().decode("utf-8"))
            images = detail.get("images") or []
        except Exception:
            continue
        for image in images:
            if "patient1" in str(image.get("filename") or image.get("path") or "").lower():
                print(f"[exists] patient1 already imported as {case['case_id']} / {image.get('image_id')}")
                if attach_labels:
                    _attach_patient1_label(case["case_id"], image["image_id"])
                return {"case_id": case["case_id"], "image_id": image.get("image_id"), "skipped": True}

    result = _upload_file(api, PATIENT1_ZIP, source_group="patient1_nrrd", patient_id="patient1")
    print(f"[upload] patient1 -> {result.get('case_id')} {result.get('image_id')}")
    if attach_labels:
        _attach_patient1_label(result["case_id"], result["image_id"])
    return result


def _attach_patient1_label(case_id: str, image_id: str) -> None:
    import tempfile
    import zipfile

    with zipfile.ZipFile(PATIENT1_ZIP) as zf:
        label_name = next((n for n in zf.namelist() if n.lower().endswith("label.nrrd") or "-label.nrrd" in n.lower()), None)
        if not label_name:
            print("[warn] no label.nrrd inside patient1.zip")
            return
        with tempfile.TemporaryDirectory() as tmp:
            extracted = Path(tmp) / Path(label_name).name
            extracted.write_bytes(zf.read(label_name))
            mask, _ = _read_mask_array(extracted)
            mask_id = _attach_mask(case_id=case_id, image_id=image_id, label="label", mask_array=mask)
            print(f"[label] patient1 label -> {mask_id or 'empty'}")


def import_task09(api: str, limit: int, attach_labels: bool) -> list[dict]:
    images_dir = TASK09_ROOT / "imagesTr"
    labels_dir = TASK09_ROOT / "labelsTr"
    if not images_dir.is_dir():
        print(f"[skip] Task09 missing: {images_dir}")
        return []
    existing = _existing_patient_ids(api)
    results = []
    files = sorted(images_dir.glob("spleen_*.nii.gz"))
    for image_path in files:
        if len(results) >= limit:
            break
        patient_id = image_path.name.replace(".nii.gz", "")
        if patient_id in existing or f"task09_{patient_id}" in existing:
            print(f"[exists] Task09 {patient_id}")
            continue
        result = _upload_file(
            api,
            image_path,
            source_group="task09_spleen",
            patient_id=f"task09_{patient_id}",
        )
        print(f"[upload] Task09 {patient_id} -> {result.get('case_id')} {result.get('image_id')}")
        if attach_labels:
            label_path = labels_dir / image_path.name
            if label_path.exists():
                mask, _ = _read_mask_array(label_path)
                mask_id = _attach_mask(
                    case_id=result["case_id"],
                    image_id=result["image_id"],
                    label="spleen",
                    mask_array=mask,
                )
                print(f"[label] Task09 {patient_id} spleen -> {mask_id or 'empty'}")
        results.append(result)
        existing.add(f"task09_{patient_id}")
    return results


def import_totalseg(api: str, limit: int, attach_labels: bool, organs: list[str]) -> list[dict]:
    if not TOTALSEG_EXTRACTED.is_dir():
        print(f"[skip] TotalSeg extracted missing: {TOTALSEG_EXTRACTED}")
        return []
    existing = _existing_patient_ids(api)
    results = []
    cases = sorted([p for p in TOTALSEG_EXTRACTED.iterdir() if p.is_dir() and (p / "ct.nii.gz").exists()])
    for case_dir in cases:
        if len(results) >= limit:
            break
        patient_id = f"totalseg_{case_dir.name}"
        ct_path = case_dir / "ct.nii.gz"
        existing_case = next(
            (
                item
                for item in _list_cases(api)
                if str(item.get("patient_id") or "") in {patient_id, case_dir.name}
            ),
            None,
        )
        if existing_case is not None:
            print(f"[exists] TotalSeg {case_dir.name} as {existing_case.get('case_id')}")
            case_id = existing_case["case_id"]
            with urllib.request.urlopen(api.rstrip("/") + f"/api/case/{case_id}", timeout=60) as resp:
                detail = json.loads(resp.read().decode("utf-8"))
            images = detail.get("images") or []
            if not images:
                continue
            image_id = images[0]["image_id"]
            result = {"case_id": case_id, "image_id": image_id, "skipped": True}
        else:
            result = _upload_file(
                api,
                ct_path,
                source_group="totalseg_extracted",
                patient_id=patient_id,
            )
            print(f"[upload] TotalSeg {case_dir.name} -> {result.get('case_id')} {result.get('image_id')}")

        if attach_labels:
            seg_dir = case_dir / "segmentations"
            attached = 0
            for organ in organs:
                organ_path = seg_dir / f"{organ}.nii.gz"
                if not organ_path.exists():
                    continue
                mask, _ = _read_mask_array(organ_path)
                mask_id = _attach_mask(
                    case_id=result["case_id"],
                    image_id=result["image_id"],
                    label=organ,
                    mask_array=mask,
                )
                if mask_id:
                    attached += 1
            print(f"[label] TotalSeg {case_dir.name} organs attached={attached}")
        results.append(result)
        existing.add(patient_id)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local CT cases into case center")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--task09", type=int, default=8, help="How many Task09 spleen cases")
    parser.add_argument("--totalseg", type=int, default=3, help="How many TotalSeg extracted cases")
    parser.add_argument("--attach-labels", action="store_true", default=True)
    parser.add_argument("--no-labels", action="store_true")
    parser.add_argument("--skip-patient1", action="store_true")
    args = parser.parse_args()
    attach = args.attach_labels and not args.no_labels

    print(f"API={args.api} attach_labels={attach}")
    if not args.skip_patient1:
        import_patient1(args.api, attach)
    import_task09(args.api, args.task09, attach)
    import_totalseg(args.api, args.totalseg, attach, DEFAULT_ORGANS)

    cases = _list_cases(args.api)
    print(f"Done. case center now has {len(cases)} cases.")
    for item in cases[-15:]:
        print(f"  {item.get('case_id')}  patient={item.get('patient_id')}  source={item.get('source_group')}  masks={item.get('mask_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
