"""Attach gold-standard labels (NIfTI/NRRD/DICOM SEG) to uploaded CT cases."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.app.core.config import PROJECT_ROOT
from backend.app.services.mask_service import _append_3d_mask_record
from backend.app.services.medical_image_service import load_volume

# Platform class ids used by the annotation UI (fallback; DB catalog overrides via resolve_label_name_to_id).
LABEL_NAME_TO_ID = {
    "background": 0,
    "liver": 1,
    "kidney": 2,
    "kidney_left": 2,
    "kidney_right": 2,
    "lung": 3,
    "tumor": 4,
    "spleen": 5,
    "pancreas": 6,
    "stomach": 7,
    "gallbladder": 8,
}


def resolve_label_name_to_id() -> dict[str, int]:
    mapping = dict(LABEL_NAME_TO_ID)
    try:
        from backend.app.services.label_service import label_name_to_id_map

        mapping.update(label_name_to_id_map())
    except Exception:
        pass
    return mapping


def is_label_filename(name: str) -> bool:
    lower = (name or "").lower().replace("\\", "/")
    base = Path(lower).name
    if "rtstruct" in base or base.endswith(".dcm") and "rs" in base:
        return False
    if "label" in base or "mask" in base or "seg" in base:
        return True
    if base.endswith(".seg.nrrd") or base.endswith("-label.nrrd") or base.endswith("_label.nii.gz"):
        return True
    return False


def classify_upload_path(path: Path) -> str:
    """Return one of: ct, label, dicom_seg, rtstruct, dicom, unknown."""
    name = path.name.lower()
    if name.endswith(".zip"):
        return "archive"
    if _is_rtstruct_file(path):
        return "rtstruct"
    if _is_dicom_seg_file(path):
        return "dicom_seg"
    if is_label_filename(name) and _is_volume_file(name):
        return "label"
    if _is_volume_file(name):
        return "ct"
    if name.endswith(".dcm") or name.endswith(".dicom") or path.suffix == "":
        return "dicom"
    return "unknown"


def _is_volume_file(name: str) -> bool:
    lower = name.lower()
    return lower.endswith((".nii", ".nii.gz", ".nrrd", ".mha", ".mhd"))


def _is_rtstruct_file(path: Path) -> bool:
    name = path.name.lower()
    if "rtstruct" in name or name.startswith("rs.") or ".rs." in name:
        return True
    try:
        import pydicom

        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        modality = str(getattr(ds, "Modality", "") or "").upper()
        sop = str(getattr(ds, "SOPClassUID", "") or "")
        return modality == "RTSTRUCT" or "1.2.840.10008.5.1.4.1.1.481.3" in sop
    except Exception:
        return False


def _is_dicom_seg_file(path: Path) -> bool:
    name = path.name.lower()
    if "seg" in name and (name.endswith(".dcm") or name.endswith(".dicom")):
        # Heuristic; confirm with Modality when possible.
        pass
    try:
        import pydicom

        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        modality = str(getattr(ds, "Modality", "") or "").upper()
        sop = str(getattr(ds, "SOPClassUID", "") or "")
        return modality == "SEG" or "1.2.840.10008.5.1.4.1.1.66.4" in sop
    except Exception:
        return "seg" in name and name.endswith((".dcm", ".dicom"))


def read_label_array(path: Path, *, preserve_multiclass: bool = True) -> np.ndarray:
    try:
        import SimpleITK as sitk

        image = sitk.ReadImage(str(path))
        array = sitk.GetArrayFromImage(image)
    except Exception:
        try:
            import nibabel as nib

            array = np.asanyarray(nib.load(str(path)).dataobj)
            if array.ndim == 3:
                array = np.transpose(array, (2, 1, 0))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read label volume {path.name}: {exc}") from exc

    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    array = np.asarray(array)
    if preserve_multiclass:
        return array.astype(np.uint8, copy=False)
    return (array > 0).astype(np.uint8)


def resample_mask_to_volume(mask_array: np.ndarray, volume) -> np.ndarray:
    if mask_array.shape == volume.array.shape[:3]:
        return mask_array.astype(np.uint8, copy=False)
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK required to resample gold labels") from exc

    ref = sitk.GetImageFromArray(volume.array.astype(np.float32))
    ref.SetSpacing(tuple(float(v) for v in volume.spacing[:3]))
    ref.SetOrigin(tuple(float(v) for v in volume.origin[:3]))
    if getattr(volume, "direction", None) is not None:
        try:
            ref.SetDirection(tuple(float(v) for v in volume.direction[:9]))
        except Exception:
            pass
    moving = sitk.GetImageFromArray(mask_array.astype(np.uint8))
    moving.SetSpacing(tuple(float(v) for v in volume.spacing[:3]))
    moving.SetOrigin(tuple(float(v) for v in volume.origin[:3]))
    resampled = sitk.Resample(moving, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    return sitk.GetArrayFromImage(resampled).astype(np.uint8)


def infer_label_name(path: Path) -> str:
    stem = path.name.lower()
    for key in ("spleen", "liver", "kidney", "lung", "tumor", "pancreas", "stomach", "gallbladder"):
        if key in stem:
            return key
    if "label" in stem:
        return "label"
    return re.sub(r"[^a-z0-9]+", "_", Path(stem).stem).strip("_") or "label"


def attach_mask_array(
    *,
    case_id: str,
    image_id: str,
    label: str,
    mask_array: np.ndarray,
    version: str = "v1_manual",
    encoding: str | None = None,
    label_id: int | None = None,
) -> dict[str, Any] | None:
    _image, volume = load_volume(image_id)
    mask_array = resample_mask_to_volume(np.asarray(mask_array), volume)
    if not np.any(mask_array):
        return None
    if label_id is None:
        label_id = resolve_label_name_to_id().get(str(label).lower())
    mask, path = _append_3d_mask_record(
        masks=[],
        request_case_id=case_id,
        image_id=image_id,
        version=version,
        label=label,
        encoding=encoding or f"gold_standard:{label}",
        source_mask_ids=[],
        mask_stack=mask_array.astype(np.uint8),
        volume=volume,
        annotation_id=f"AnnotationGold_{image_id}_{label}",
        label_type="dense",
        label_id=label_id,
    )
    return {"mask_id": mask.mask_id, "label": label, "label_id": label_id, "path": path}


def attach_nifti_or_nrrd_label(
    *,
    case_id: str,
    image_id: str,
    label_path: Path,
    preserve_multiclass: bool = True,
) -> list[dict[str, Any]]:
    array = read_label_array(label_path, preserve_multiclass=preserve_multiclass)
    unique = [int(v) for v in np.unique(array) if int(v) > 0]
    attached: list[dict[str, Any]] = []

    # Single-class binary / one foreground id → one mask named from filename.
    if len(unique) <= 1 or not preserve_multiclass:
        label = infer_label_name(label_path)
        label_id = unique[0] if len(unique) == 1 and unique[0] <= 20 else resolve_label_name_to_id().get(label)
        binary = (array > 0).astype(np.uint8)
        if label_id and label_id > 0:
            binary = binary * np.uint8(label_id)
        result = attach_mask_array(
            case_id=case_id,
            image_id=image_id,
            label=label if len(unique) <= 1 else "multiclass",
            mask_array=binary if len(unique) <= 1 else array.astype(np.uint8),
            encoding=f"gold_standard_file:{label_path.name}",
            label_id=label_id if len(unique) <= 1 else None,
        )
        if result:
            attached.append(result)
        return attached

    # Multi-class volume: store one multiclass NIfTI (preferred for export).
    result = attach_mask_array(
        case_id=case_id,
        image_id=image_id,
        label="multiclass",
        mask_array=array.astype(np.uint8),
        encoding=f"gold_standard_multiclass:{label_path.name}",
        label_id=None,
    )
    if result:
        attached.append(result)
    return attached


def read_dicom_seg_array(seg_path: Path, reference_shape: tuple[int, int, int]) -> np.ndarray:
    """Rasterize DICOM SEG into a multiclass volume matching reference_shape (Z,Y,X)."""
    try:
        import pydicom
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="pydicom is required for DICOM SEG") from exc

    ds = pydicom.dcmread(str(seg_path), force=True)
    depth, height, width = reference_shape
    volume = np.zeros((depth, height, width), dtype=np.uint8)

    # Prefer highdicom if available.
    try:
        import highdicom as hd

        seg = hd.seg.Segmentation.from_dataset(ds)
        for segment_number in seg.get_segment_numbers():
            # Map segment number into platform id when possible.
            try:
                desc = seg.get_segment_description(segment_number)
                name = str(getattr(desc, "SegmentLabel", "") or segment_number).lower()
            except Exception:
                name = str(segment_number)
            label_id = resolve_label_name_to_id().get(name, int(segment_number) if int(segment_number) < 64 else 1)
            frames = seg.get_pixels_by_source_instance(
                source_sop_instance_uids=None,
                segment_numbers=[segment_number],
            )
            # Fallback: stack all frames for this segment if API differs.
            arr = np.asarray(frames)
            if arr.ndim == 3 and arr.shape == volume.shape:
                volume[arr > 0] = np.uint8(label_id)
        if np.any(volume):
            return volume
    except Exception:
        pass

    # Minimal fallback: decode pixel array if already volumetric.
    try:
        pixels = np.asarray(ds.pixel_array)
        if pixels.ndim == 3:
            if pixels.shape == volume.shape:
                return (pixels > 0).astype(np.uint8)
            # Resize-ish: take min shape crop/pad
            out = np.zeros_like(volume)
            zz = min(depth, pixels.shape[0])
            yy = min(height, pixels.shape[1])
            xx = min(width, pixels.shape[2])
            out[:zz, :yy, :xx] = (pixels[:zz, :yy, :xx] > 0).astype(np.uint8)
            return out
        if pixels.ndim == 2 and depth == 1:
            return (pixels > 0).astype(np.uint8).reshape(1, height, width)[:, :height, :width]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to decode DICOM SEG: {exc}") from exc

    raise HTTPException(status_code=400, detail="DICOM SEG could not be rasterized to the CT geometry")


def attach_dicom_seg(*, case_id: str, image_id: str, seg_path: Path) -> list[dict[str, Any]]:
    _image, volume = load_volume(image_id)
    shape = volume.array.shape[:3]
    array = read_dicom_seg_array(seg_path, shape)
    result = attach_mask_array(
        case_id=case_id,
        image_id=image_id,
        label="multiclass",
        mask_array=array,
        encoding=f"gold_standard_dicom_seg:{seg_path.name}",
    )
    return [result] if result else []


def find_label_files_in_dir(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        kind = classify_upload_path(path)
        if kind in {"label", "dicom_seg"}:
            found.append(path)
    return found


def find_ct_and_labels_in_zip_extract(extract_dir: Path) -> tuple[Path | None, list[Path]]:
    ct_candidates: list[Path] = []
    labels: list[Path] = []
    for path in extract_dir.rglob("*"):
        if not path.is_file():
            continue
        kind = classify_upload_path(path)
        if kind == "label" or kind == "dicom_seg":
            labels.append(path)
        elif kind == "ct":
            ct_candidates.append(path)
        elif kind == "dicom":
            ct_candidates.append(path)
    # Prefer non-label nrrd/nii as CT
    ct_volumes = [p for p in ct_candidates if _is_volume_file(p.name) and not is_label_filename(p.name)]
    ct = ct_volumes[0] if ct_volumes else (ct_candidates[0] if ct_candidates else None)
    return ct, labels


def attach_gold_labels_for_case(
    *,
    case_id: str,
    image_id: str,
    label_paths: list[Path],
    rtstruct_paths: list[Path] | None = None,
    dicom_series_dir: Path | None = None,
) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for path in label_paths:
        kind = classify_upload_path(path)
        try:
            if kind == "dicom_seg":
                attached.extend(attach_dicom_seg(case_id=case_id, image_id=image_id, seg_path=path))
            elif kind == "label":
                attached.extend(
                    attach_nifti_or_nrrd_label(case_id=case_id, image_id=image_id, label_path=path)
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to attach gold label {path.name}: {exc}") from exc

    if rtstruct_paths:
        from backend.app.services.rtstruct_service import attach_rtstruct_masks

        for rs_path in rtstruct_paths:
            attached.extend(
                attach_rtstruct_masks(
                    case_id=case_id,
                    image_id=image_id,
                    rtstruct_path=rs_path,
                    dicom_series_dir=dicom_series_dir,
                )
            )
    return attached
