"""Rasterize DICOM RTSTRUCT contours onto a reference CT volume.

Improvements vs naive rasterization:
- Match CT series by FrameOfReferenceUID when multiple series exist
- Contour in-bounds QC (detect gross misalignment)
- Configurable ROI name -> label_id map
- Return QC metadata with attached masks for upload UI
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.app.core.config import PROJECT_ROOT
from backend.app.services.gold_label_service import attach_mask_array, resolve_label_name_to_id

DEFAULT_ROI_MAP_PATH = PROJECT_ROOT / "config" / "rtstruct_roi_map.json"


def _load_roi_map() -> dict[str, int]:
    mapping = {str(k).lower(): int(v) for k, v in resolve_label_name_to_id().items()}
    path = DEFAULT_ROI_MAP_PATH
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, value in (data.get("roi_to_label_id") or data or {}).items():
                mapping[str(key).lower()] = int(value)
        except Exception:
            pass
    return mapping


def _roi_label_id(roi_name: str, fallback: int, roi_map: dict[str, int] | None = None) -> int:
    name = (roi_name or "").strip().lower().replace(" ", "_")
    mapping = roi_map or _load_roi_map()
    if name in mapping:
        return int(mapping[name])
    for key, value in mapping.items():
        if key and key in name:
            return int(value)
    return int(fallback) if 1 <= fallback < 64 else 1


def _rtstruct_frame_of_reference_uids(ds) -> set[str]:
    uids: set[str] = set()
    try:
        for item in getattr(ds, "ReferencedFrameOfReferenceSequence", []) or []:
            uid = str(getattr(item, "FrameOfReferenceUID", "") or "")
            if uid:
                uids.add(uid)
            for study in getattr(item, "RTReferencedStudySequence", []) or []:
                for series in getattr(study, "RTReferencedSeriesSequence", []) or []:
                    # ContourImageSequence may also imply series, but FoR is primary.
                    pass
    except Exception:
        pass
    # Some exports put FoR on the top-level dataset.
    top = str(getattr(ds, "FrameOfReferenceUID", "") or "")
    if top:
        uids.add(top)
    return uids


def _series_frame_of_reference(dicom_file: str) -> str | None:
    try:
        import pydicom

        ds = pydicom.dcmread(dicom_file, stop_before_pixels=True, force=True)
        uid = str(getattr(ds, "FrameOfReferenceUID", "") or "")
        return uid or None
    except Exception:
        return None


def _load_series_geometry(
    dicom_series_dir: Path,
    *,
    preferred_frame_of_reference: set[str] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Load DICOM series; prefer series whose FoR matches the RTSTRUCT."""
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required for RTSTRUCT rasterization") from exc

    reader = sitk.ImageSeriesReader()
    series_ids = list(reader.GetGDCMSeriesIDs(str(dicom_series_dir)) or [])
    chosen_names: list[str] | None = None
    matched_for = False
    chosen_for: str | None = None

    if series_ids:
        # Score each series: FoR match first, then file count.
        scored: list[tuple[int, int, str, list[str], str | None]] = []
        for sid in series_ids:
            names = list(reader.GetGDCMSeriesFileNames(str(dicom_series_dir), sid) or [])
            if not names:
                continue
            for_uid = _series_frame_of_reference(names[0])
            score = 0
            if preferred_frame_of_reference and for_uid and for_uid in preferred_frame_of_reference:
                score += 1000
                matched_for = True
            score += min(len(names), 500)
            scored.append((score, len(names), sid, names, for_uid))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if scored:
            chosen_names = scored[0][3]
            chosen_for = scored[0][4]
            matched_for = bool(
                preferred_frame_of_reference
                and chosen_for
                and chosen_for in preferred_frame_of_reference
            )

    if not chosen_names:
        files = sorted(
            [
                str(p)
                for p in dicom_series_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in {".dcm", ".dicom", ""}
            ]
        )
        if not files:
            raise HTTPException(status_code=400, detail="No DICOM series found for RTSTRUCT reference")
        chosen_names = files
        chosen_for = _series_frame_of_reference(files[0])

    reader.SetFileNames(chosen_names)
    image = reader.Execute()
    array = sitk.GetArrayFromImage(image)
    geometry = {
        "spacing": tuple(float(v) for v in image.GetSpacing()),
        "origin": tuple(float(v) for v in image.GetOrigin()),
        "direction": tuple(float(v) for v in image.GetDirection()),
        "size": tuple(int(v) for v in image.GetSize()),
        "sitk_image": image,
        "frame_of_reference_uid": chosen_for,
        "frame_of_reference_matched": matched_for,
        "series_file_count": len(chosen_names),
    }
    return array, geometry


def _fill_polygon(mask2d: np.ndarray, rr_cc: list[tuple[float, float]]) -> None:
    if len(rr_cc) < 3:
        return
    try:
        from skimage.draw import polygon

        rr = np.array([p[1] for p in rr_cc], dtype=np.float64)
        cc = np.array([p[0] for p in rr_cc], dtype=np.float64)
        rows, cols = polygon(rr, cc, shape=mask2d.shape)
        mask2d[rows, cols] = 1
        return
    except Exception:
        pass
    height, width = mask2d.shape
    for x, y in rr_cc:
        xi = int(round(x))
        yi = int(round(y))
        if 0 <= yi < height and 0 <= xi < width:
            mask2d[yi, xi] = 1


def rasterize_rtstruct(
    rtstruct_path: Path,
    *,
    reference_image,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Rasterize RTSTRUCT into multiclass mask + QC report."""
    try:
        import pydicom
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="pydicom and SimpleITK are required for RTSTRUCT") from exc

    ds = pydicom.dcmread(str(rtstruct_path), force=True)
    if str(getattr(ds, "Modality", "")).upper() != "RTSTRUCT":
        if not hasattr(ds, "ROIContourSequence"):
            raise HTTPException(status_code=400, detail=f"Not an RTSTRUCT file: {rtstruct_path.name}")

    ref_array = sitk.GetArrayFromImage(reference_image)
    depth, height, width = ref_array.shape[:3]
    out = np.zeros((depth, height, width), dtype=np.uint8)
    roi_map = _load_roi_map()

    roi_number_to_name: dict[int, str] = {}
    if hasattr(ds, "StructureSetROISequence"):
        for item in ds.StructureSetROISequence:
            try:
                roi_number_to_name[int(item.ROINumber)] = str(item.ROIName)
            except Exception:
                continue

    if not hasattr(ds, "ROIContourSequence"):
        raise HTTPException(status_code=400, detail="RTSTRUCT has no ROIContourSequence")

    points_total = 0
    points_inside = 0
    points_out = 0
    rois_written: list[dict[str, Any]] = []
    next_fallback = 1

    for roi_contour in ds.ROIContourSequence:
        try:
            roi_number = int(getattr(roi_contour, "ReferencedROINumber", next_fallback))
        except Exception:
            roi_number = next_fallback
        roi_name = roi_number_to_name.get(roi_number, f"roi_{roi_number}")
        label_id = _roi_label_id(roi_name, next_fallback, roi_map)
        next_fallback += 1
        roi_voxels_before = int(np.count_nonzero(out == label_id))

        if not hasattr(roi_contour, "ContourSequence"):
            continue
        for contour in roi_contour.ContourSequence:
            try:
                data = [float(v) for v in contour.ContourData]
            except Exception:
                continue
            if len(data) < 9:
                continue
            points: list[tuple[float, float, int]] = []
            for i in range(0, len(data), 3):
                x, y, z = data[i], data[i + 1], data[i + 2]
                points_total += 1
                try:
                    idx = reference_image.TransformPhysicalPointToIndex((x, y, z))
                except Exception:
                    points_out += 1
                    continue
                ix, iy, iz = int(round(idx[0])), int(round(idx[1])), int(round(idx[2]))
                inside = 0 <= iz < depth and 0 <= iy < height and 0 <= ix < width
                if inside:
                    points_inside += 1
                    points.append((float(ix), float(iy), iz))
                else:
                    points_out += 1
            if len(points) < 3:
                continue
            by_z: dict[int, list[tuple[float, float]]] = {}
            for ix, iy, iz in points:
                by_z.setdefault(iz, []).append((ix, iy))
            for iz, poly in by_z.items():
                slice_mask = np.zeros((height, width), dtype=np.uint8)
                _fill_polygon(slice_mask, poly)
                out[iz][slice_mask > 0] = np.uint8(label_id)

        roi_voxels = int(np.count_nonzero(out == label_id)) - roi_voxels_before
        rois_written.append(
            {
                "roi_name": roi_name,
                "roi_number": roi_number,
                "label_id": label_id,
                "voxels": max(0, roi_voxels),
            }
        )

    out_ratio = float(points_out) / float(points_total) if points_total else 1.0
    qc = {
        "points_total": points_total,
        "points_inside": points_inside,
        "points_out_of_bounds": points_out,
        "out_of_bounds_ratio": round(out_ratio, 4),
        "rois": rois_written,
        "nonempty_voxels": int(np.count_nonzero(out)),
        "alignment_status": "ok",
        "alignment_message": None,
    }
    if points_total == 0 or not np.any(out):
        raise HTTPException(
            status_code=422,
            detail=(
                "RTSTRUCT produced an empty mask. Usually the CT series does not match "
                "the structure set geometry (different exam / missing slices / FoR mismatch)."
            ),
        )
    if out_ratio > 0.5:
        raise HTTPException(
            status_code=422,
            detail=(
                f"RTSTRUCT appears misaligned with CT: {out_ratio:.0%} contour points "
                "fell outside the volume. Upload the matching DICOM series from the same exam "
                "(same FrameOfReferenceUID), not a different study."
            ),
        )
    if out_ratio > 0.1:
        qc["alignment_status"] = "warning"
        qc["alignment_message"] = (
            f"{out_ratio:.0%} contour points were outside the CT bounds; "
            "check whether the correct series was used."
        )
    return out, qc


def attach_rtstruct_masks(
    *,
    case_id: str,
    image_id: str,
    rtstruct_path: Path,
    dicom_series_dir: Path | None = None,
) -> list[dict[str, Any]]:
    from backend.app.services.medical_image_service import load_volume
    import SimpleITK as sitk
    import pydicom

    image_record, volume = load_volume(image_id)
    image_path = (PROJECT_ROOT / str(image_record.get("path") or "")).resolve()

    rs = pydicom.dcmread(str(rtstruct_path), stop_before_pixels=True, force=True)
    preferred_for = _rtstruct_frame_of_reference_uids(rs)

    reference = None
    geometry_meta: dict[str, Any] = {}
    if dicom_series_dir and dicom_series_dir.is_dir():
        try:
            _arr, geometry = _load_series_geometry(
                dicom_series_dir,
                preferred_frame_of_reference=preferred_for or None,
            )
            reference = geometry["sitk_image"]
            geometry_meta = {
                "frame_of_reference_uid": geometry.get("frame_of_reference_uid"),
                "frame_of_reference_matched": geometry.get("frame_of_reference_matched"),
                "series_file_count": geometry.get("series_file_count"),
            }
        except Exception:
            reference = None

    if reference is None and image_path.is_file() and image_path.suffix.lower() in {".dcm", ".dicom", ""}:
        try:
            _arr, geometry = _load_series_geometry(
                image_path.parent,
                preferred_frame_of_reference=preferred_for or None,
            )
            reference = geometry["sitk_image"]
            geometry_meta = {
                "frame_of_reference_uid": geometry.get("frame_of_reference_uid"),
                "frame_of_reference_matched": geometry.get("frame_of_reference_matched"),
                "series_file_count": geometry.get("series_file_count"),
            }
        except Exception:
            reference = None

    if reference is None:
        # Last resort: reconstruct geometry from platform volume metadata.
        reference = sitk.GetImageFromArray(volume.array.astype(np.float32))
        reference.SetSpacing(tuple(float(v) for v in volume.spacing[:3]))
        reference.SetOrigin(tuple(float(v) for v in volume.origin[:3]))
        try:
            reference.SetDirection(tuple(float(v) for v in volume.direction[:9]))
        except Exception:
            pass
        geometry_meta = {
            "frame_of_reference_uid": None,
            "frame_of_reference_matched": False,
            "series_file_count": None,
            "note": "fallback_volume_geometry",
        }

    # Hard requirement when RTSTRUCT declares FoR and we loaded a DICOM series.
    if preferred_for and geometry_meta.get("frame_of_reference_uid"):
        if not geometry_meta.get("frame_of_reference_matched"):
            raise HTTPException(
                status_code=422,
                detail=(
                    "RTSTRUCT FrameOfReferenceUID does not match the uploaded CT series. "
                    f"RTSTRUCT FoR={sorted(preferred_for)}; "
                    f"CT FoR={geometry_meta.get('frame_of_reference_uid')}. "
                    "Please upload the CT series from the same examination."
                ),
            )

    mask, qc = rasterize_rtstruct(rtstruct_path, reference_image=reference)
    if mask.shape != volume.array.shape[:3]:
        from backend.app.services.gold_label_service import resample_mask_to_volume

        mask = resample_mask_to_volume(mask, volume)

    result = attach_mask_array(
        case_id=case_id,
        image_id=image_id,
        label="multiclass",
        mask_array=mask,
        encoding=f"gold_standard_rtstruct:{rtstruct_path.name}",
    )
    if not result:
        return []
    result["rtstruct_qc"] = {**qc, **geometry_meta, "rtstruct_frame_of_reference_uids": sorted(preferred_for)}
    if qc.get("alignment_status") == "warning":
        result["warning"] = qc.get("alignment_message")
    return [result]
