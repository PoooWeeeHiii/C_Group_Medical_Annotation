from __future__ import annotations

import base64
import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.app.core.config import (
    DEEPEDIT_SERVICE_TIMEOUT_SECONDS,
    DEEPEDIT_SERVICE_URL,
    LABELS_DATA_DIR,
    PROJECT_ROOT,
    ensure_project_dirs,
)
from backend.app.schemas.mask import (
    DeepEditRefineRequest,
    DeepEditRefineResponse,
    ExportMaskNiftiRequest,
    ExportMaskNiftiResponse,
    LabelPropagationRequest,
    LabelPropagationResponse,
    MaskRecord,
    SaveMaskRequest,
    SaveMaskResponse,
    UpdateMaskRequest,
)
from backend.app.services.file_service import (
    path_for_api,
)
from backend.app.services.medical_image_service import load_volume
from backend.app.services.sqlite_service import get_record, list_records, next_sqlite_entity_id, upsert_record, delete_record


VALID_MASK_VERSIONS = {"v1_manual", "v2_ai", "v3_preview", "v3_fusion", "final"}
PROMOTABLE_TARGET_VERSIONS = {"v3_fusion", "final"}
VALID_MASK_FORMATS = {"nii.gz", "json"}
VALID_SLICE_AXES = {"axial", "coronal", "sagittal"}
VALID_LABEL_TYPES = {"coarse", "scribble", "dense", "pseudo"}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_label_type(value: str | None, default: str = "dense") -> str:
    if value is None or str(value).strip() == "":
        return default
    cleaned = str(value).strip().lower()
    if cleaned not in VALID_LABEL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported label_type: {value}. Use one of {sorted(VALID_LABEL_TYPES)}",
        )
    return cleaned


def _normalize_label(label: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return value or "label"


def _normalize_axis(axis: str | None) -> str:
    value = (axis or "axial").strip().lower()
    if value not in VALID_SLICE_AXES:
        raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")
    return value


def _load_masks() -> list[dict]:
    return list_records("masks")


def _image_record(image_id: str) -> dict:
    image = get_record("images", "image_id", image_id)
    if image is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_id}")
    return image


def _mask_path(case_id: str, image_id: str, mask_id: str, version: str, label: str, mask_format: str) -> str:
    mask_dir = LABELS_DATA_DIR / case_id / version
    mask_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{case_id}_{image_id}_{mask_id}_{version}_{label}.{mask_format}"
    return path_for_api(mask_dir / filename, PROJECT_ROOT)


def _write_mask_json(path: str, request: SaveMaskRequest, mask_id: str, label: str) -> None:
    if request.slice_index is None or request.width is None or request.height is None:
        raise HTTPException(status_code=400, detail="JSON mask requires slice_index, width and height")
    if request.encoding != "rle":
        raise HTTPException(status_code=400, detail="Current JSON mask writer requires encoding='rle'")
    if request.mask is None:
        raise HTTPException(status_code=400, detail="JSON mask requires mask data")

    content: dict[str, Any] = {
        "case_id": request.case_id,
        "image_id": request.image_id,
        "mask_id": mask_id,
        "axis": _normalize_axis(request.axis),
        "slice_index": request.slice_index,
        "width": request.width,
        "height": request.height,
        "label": label,
        "label_id": request.label_id,
        "encoding": request.encoding,
        "mask": request.mask,
        "points": request.points or [],
        "create_time": _now_iso(),
    }
    target = PROJECT_ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(target)


def _read_mask_json(path: str) -> dict[str, Any] | None:
    target = (PROJECT_ROOT / path).resolve()
    root = PROJECT_ROOT.resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="Invalid mask path")
    if not target.exists() or target.suffix != ".json":
        return None
    with target.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail=f"Mask JSON must be an object: {path}")
    return data


def _decode_rle(runs: list[Any], width: int, height: int) -> np.ndarray:
    values = np.zeros(width * height, dtype=np.uint8)
    offset = 0
    for run in runs:
        if not isinstance(run, (list, tuple)) or len(run) < 2:
            continue
        value = int(run[0])
        count = int(run[1])
        if count <= 0:
            continue
        end = min(offset + count, values.size)
        values[offset:end] = value
        offset = end
        if offset >= values.size:
            break
    return values.reshape((height, width))


def _encode_rle(values: np.ndarray) -> list[list[int]]:
    flat = np.ascontiguousarray(values.astype(np.uint8, copy=False).reshape(-1))
    if flat.size == 0:
        return []
    runs: list[list[int]] = []
    current = int(flat[0])
    count = 1
    for value in flat[1:]:
        next_value = int(value)
        if next_value == current:
            count += 1
        else:
            runs.append([current, count])
            current = next_value
            count = 1
    runs.append([current, count])
    return runs


def _json_mask_records(
    masks: list[dict],
    case_id: str,
    image_id: str,
    version: str,
    label: str,
    *,
    match_any_label: bool = False,
) -> list[dict]:
    records = [
        mask
        for mask in masks
        if mask.get("case_id") == case_id
        and mask.get("image_id") == image_id
        and mask.get("version") == version
        and (match_any_label or mask.get("label") == label)
        and (mask.get("mask_format") == "json" or str(mask.get("path", "")).endswith(".json"))
    ]
    records.sort(key=lambda item: str(item.get("create_time") or ""))
    return records


def _axis_plane_shape(axis: str, depth: int, height: int, width: int) -> tuple[int, int, int]:
    if axis == "axial":
        return depth, height, width
    if axis == "coronal":
        return height, depth, width
    if axis == "sagittal":
        return width, depth, height
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def _display_mask_to_axis_mask(axis: str, decoded: np.ndarray) -> np.ndarray:
    if axis == "axial":
        return decoded
    return np.flipud(decoded)


def _merge_axis_slice_into_volume(
    mask_stack: np.ndarray,
    axis: str,
    slice_index: int,
    axis_mask: np.ndarray,
) -> None:
    values = axis_mask.astype(np.uint8, copy=False)
    painted = values > 0
    if axis == "axial":
        target = mask_stack[slice_index]
        target[painted] = values[painted]
        return
    if axis == "coronal":
        target = mask_stack[:, slice_index, :]
        target[painted] = values[painted]
        return
    if axis == "sagittal":
        target = mask_stack[:, :, slice_index]
        target[painted] = values[painted]
        return
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def _load_sparse_axis_masks(
    records: list[dict],
    depth: int,
    height: int,
    width: int,
) -> tuple[dict[str, dict[int, np.ndarray]], list[str]]:
    slices_by_axis: dict[str, dict[int, np.ndarray]] = {axis: {} for axis in VALID_SLICE_AXES}
    source_mask_ids: list[str] = []
    for record in records:
        content = _read_mask_json(str(record.get("path")))
        if not content:
            continue
        axis = _normalize_axis(str(content.get("axis") or record.get("axis") or "axial"))
        slice_index = int(content.get("slice_index", -1))
        max_slices, expected_height, expected_width = _axis_plane_shape(axis, depth, height, width)
        content_width = int(content.get("width", 0))
        content_height = int(content.get("height", 0))
        if not 0 <= slice_index < max_slices:
            raise HTTPException(
                status_code=400,
                detail=f"Saved {axis} mask slice_index is outside volume: {slice_index}",
            )
        if content_width != expected_width or content_height != expected_height:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Saved mask dimensions do not match source image: "
                    f"axis={axis}, mask={content_width}x{content_height}, "
                    f"expected={expected_width}x{expected_height}"
                ),
            )
        if content.get("encoding") != "rle":
            raise HTTPException(status_code=400, detail="Only RLE JSON masks can be used for 3D mask generation")
        decoded = _decode_rle(content.get("mask") or [], expected_width, expected_height)
        if not np.any(decoded):
            continue
        axis_mask = _display_mask_to_axis_mask(axis, decoded)
        if slice_index in slices_by_axis[axis]:
            slices_by_axis[axis][slice_index] = np.maximum(slices_by_axis[axis][slice_index], axis_mask)
        else:
            slices_by_axis[axis][slice_index] = axis_mask
        source_mask_ids.append(str(record.get("mask_id")))
    return slices_by_axis, source_mask_ids


def _axis_volume_array(volume_array: np.ndarray, axis: str) -> np.ndarray:
    if axis == "axial":
        return volume_array
    if axis == "coronal":
        return np.transpose(volume_array, (1, 0, 2))
    if axis == "sagittal":
        return np.transpose(volume_array, (2, 0, 1))
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def _axis_result_to_volume(axis_array: np.ndarray, axis: str) -> np.ndarray:
    if axis == "axial":
        return axis_array
    if axis == "coronal":
        return np.transpose(axis_array, (1, 0, 2))
    if axis == "sagittal":
        return np.transpose(axis_array, (1, 2, 0))
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def _axis_spacing(spacing: tuple[float, float, float], axis: str) -> tuple[float, float, float]:
    spacing_x = float(spacing[0]) if len(spacing) > 0 else 1.0
    spacing_y = float(spacing[1]) if len(spacing) > 1 else 1.0
    spacing_z = float(spacing[2]) if len(spacing) > 2 else 1.0
    if axis == "axial":
        return spacing_x, spacing_y, spacing_z
    if axis == "coronal":
        return spacing_x, spacing_z, spacing_y
    if axis == "sagittal":
        return spacing_y, spacing_z, spacing_x
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def _annotated_slice_summary(slices_by_axis: dict[str, dict[int, np.ndarray]]) -> list[int]:
    values: set[int] = set()
    for axis_slices in slices_by_axis.values():
        values.update(axis_slices.keys())
    return sorted(values)


def _write_nifti_mask(mask_stack: np.ndarray, volume, path: str) -> None:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to export NIfTI masks") from exc

    target_path = PROJECT_ROOT / path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    image = sitk.GetImageFromArray(mask_stack.astype(np.uint8, copy=False))
    image.SetSpacing(tuple(float(value) for value in volume.spacing))
    image.SetOrigin(tuple(float(value) for value in volume.origin))
    image.SetDirection(tuple(float(value) for value in volume.direction))
    sitk.WriteImage(image, str(target_path))


def _append_3d_mask_record(
    masks: list[dict],
    request_case_id: str,
    image_id: str,
    version: str,
    label: str,
    encoding: str,
    source_mask_ids: list[str],
    mask_stack: np.ndarray,
    volume,
    annotation_id: str | None = None,
    label_type: str = "pseudo",
    label_id: int | None = None,
) -> tuple[MaskRecord, str]:
    depth, height, width = mask_stack.shape[:3]
    mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
    mask_path = _mask_path(
        case_id=request_case_id,
        image_id=image_id,
        mask_id=mask_id,
        version=version,
        label=label,
        mask_format="nii.gz",
    )
    _write_nifti_mask(mask_stack, volume, mask_path)

    record = {
        "mask_id": mask_id,
        "annotation_id": annotation_id,
        "case_id": request_case_id,
        "image_id": image_id,
        "path": mask_path,
        "version": version,
        "label": label,
        "label_id": label_id,
        "label_type": _normalize_label_type(label_type, default="pseudo"),
        "mask_format": "nii.gz",
        "slice_index": None,
        "width": width,
        "height": height,
        "encoding": encoding,
        "create_time": _now_iso(),
        "source_mask_ids": source_mask_ids,
        "shape": [depth, height, width],
        "spacing": [float(value) for value in volume.spacing],
        "origin": [float(value) for value in volume.origin],
        "direction": [float(value) for value in volume.direction],
    }
    upsert_record("masks", record)
    return MaskRecord(**record), mask_path


def _downsample_mask_volume(
    array: np.ndarray,
    max_dim: int,
    *,
    preserve_labels: bool = False,
) -> tuple[np.ndarray, tuple[int, int, int]]:
    max_dim = max(64, min(max_dim, 192))
    depth, height, width = array.shape[:3]
    stride_z = max(1, int(np.ceil(depth / max_dim)))
    stride_y = max(1, int(np.ceil(height / max_dim)))
    stride_x = max(1, int(np.ceil(width / max_dim)))
    source = np.asarray(array)
    if preserve_labels:
        values = np.clip(source, 0, 255).astype(np.uint8, copy=False)
    else:
        values = (source > 0).astype(np.uint8, copy=False)
    if stride_z == stride_y == stride_x == 1:
        return values, (stride_z, stride_y, stride_x)

    out_depth = int(np.ceil(depth / stride_z))
    out_height = int(np.ceil(height / stride_y))
    out_width = int(np.ceil(width / stride_x))
    padded_shape = (out_depth * stride_z, out_height * stride_y, out_width * stride_x)
    padded = np.zeros(padded_shape, dtype=np.uint8)
    padded[:depth, :height, :width] = values
    pooled = padded.reshape(out_depth, stride_z, out_height, stride_y, out_width, stride_x).max(axis=(1, 3, 5))
    return pooled.astype(np.uint8, copy=False), (stride_z, stride_y, stride_x)


def get_mask_volume_data(mask_id: str, max_dim: int = 176) -> dict[str, Any]:
    import base64

    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to render 3D masks") from exc

    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if record.get("mask_format") != "nii.gz":
        raise HTTPException(status_code=400, detail="Only 3D NIfTI masks can be rendered in 3D view")

    path = (PROJECT_ROOT / str(record.get("path"))).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mask path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Mask file not found: {record.get('path')}")

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    raw = np.clip(np.asarray(array), 0, 255).astype(np.uint8, copy=False)
    unique_labels = sorted({int(v) for v in np.unique(raw) if int(v) > 0})
    label_name = str(record.get("label") or "").strip().lower()
    is_named_multi = label_name in {"全部标注", "all_labels", "multiclass", "all", "alllabels"}
    # Single-organ AI masks store voxels as label_id (e.g. lung=3), not 0/1.
    # That must NOT be treated as multiclass — otherwise 3D forces WebGL volume
    # and skips VTK mesh highlight.
    multiclass = is_named_multi or (len(unique_labels) > 1 and set(unique_labels) != {255})
    if multiclass:
        downsampled, strides = _downsample_mask_volume(raw, max_dim=max_dim, preserve_labels=True)
        texture_values = downsampled.astype(np.uint8, copy=False)
        full_voxel_count = int(np.count_nonzero(raw))
        unique_labels = sorted({int(v) for v in np.unique(downsampled) if int(v) > 0})
    else:
        binary = (raw > 0).astype(np.uint8)
        downsampled, strides = _downsample_mask_volume(binary, max_dim=max_dim, preserve_labels=False)
        texture_values = (downsampled > 0).astype(np.uint8) * np.uint8(255)
        full_voxel_count = int(np.count_nonzero(binary))
        unique_labels = [1] if full_voxel_count else []
    depth, height, width = downsampled.shape[:3]
    spacing = tuple(float(value) for value in image.GetSpacing()[:3])
    stride_z, stride_y, stride_x = strides
    return {
        "success": True,
        "mask_id": mask_id,
        "case_id": record.get("case_id"),
        "image_id": record.get("image_id"),
        "version": record.get("version"),
        "label": record.get("label"),
        "label_id": record.get("label_id"),
        "multiclass": bool(multiclass),
        "unique_labels": unique_labels,
        "dimensions": [width, height, depth],
        "spacing": [spacing[0] * stride_x, spacing[1] * stride_y, spacing[2] * stride_z],
        "origin": [float(value) for value in image.GetOrigin()[:3]],
        "direction": [float(value) for value in image.GetDirection()],
        "scalar_type": "uint8",
        "downsample_stride": [stride_z, stride_y, stride_x],
        "full_mask_voxel_count": full_voxel_count,
        "mask_voxel_count": int(np.count_nonzero(downsampled)),
        "values_base64": base64.b64encode(np.ascontiguousarray(texture_values).tobytes(order="C")).decode("ascii"),
    }


def _read_nifti_mask_array(mask_id: str) -> tuple[dict[str, Any], Any, np.ndarray]:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to read 3D masks") from exc

    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if record.get("mask_format") != "nii.gz":
        raise HTTPException(status_code=400, detail="Only 3D NIfTI masks can be rendered as surface mesh")

    path = (PROJECT_ROOT / str(record.get("path"))).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mask path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Mask file not found: {record.get('path')}")

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    return record, image, (array > 0).astype(np.uint8, copy=False)


def _filter_mask_components(binary: np.ndarray, min_voxels: int, max_components: int) -> tuple[np.ndarray, dict[str, Any]]:
    min_voxels = max(1, int(min_voxels))
    max_components = max(1, int(max_components))
    voxel_count_before = int(np.count_nonzero(binary))
    if voxel_count_before == 0:
        return binary.astype(np.uint8, copy=False), {
            "voxel_count_before": 0,
            "voxel_count_after": 0,
            "component_count_before": 0,
            "component_count_after": 0,
            "removed_voxels": 0,
        }

    try:
        from scipy import ndimage as ndi
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="scipy is required to clean mask surface artifacts") from exc

    labeled, component_count = ndi.label(binary > 0, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if component_count == 0:
        return np.zeros_like(binary, dtype=np.uint8), {
            "voxel_count_before": voxel_count_before,
            "voxel_count_after": 0,
            "component_count_before": 0,
            "component_count_after": 0,
            "removed_voxels": voxel_count_before,
        }

    sizes = np.bincount(labeled.reshape(-1))
    component_labels = np.arange(1, sizes.size)
    keep_labels = [
        int(label)
        for label in sorted(component_labels, key=lambda value: int(sizes[value]), reverse=True)
        if int(sizes[label]) >= min_voxels
    ][:max_components]
    if not keep_labels:
        keep_labels = [int(component_labels[np.argmax(sizes[1:])])]

    cleaned = np.isin(labeled, keep_labels)
    voxel_count_after = int(np.count_nonzero(cleaned))
    return cleaned.astype(np.uint8, copy=False), {
        "voxel_count_before": voxel_count_before,
        "voxel_count_after": voxel_count_after,
        "component_count_before": int(component_count),
        "component_count_after": len(keep_labels),
        "removed_voxels": voxel_count_before - voxel_count_after,
        "kept_component_voxels": [int(sizes[label]) for label in keep_labels],
    }


def _remove_thin_axial_artifacts(binary: np.ndarray, min_support_slices: int = 2) -> tuple[np.ndarray, int]:
    """Remove sparse single-slice sheets before surface extraction.

    The current label propagation fallback can occasionally create flat sheets
    outside the anatomy. Real 3D targets usually have support on neighboring
    slices, so this pass removes voxels that have no z-neighborhood support.
    """
    depth = binary.shape[0]
    if depth < 5:
        return binary.astype(np.uint8, copy=False), 0

    source = binary > 0
    support = np.zeros_like(source, dtype=np.uint8)
    for offset in (-3, -2, -1, 1, 2, 3):
        shifted = np.zeros_like(source, dtype=bool)
        if offset < 0:
            shifted[:offset] = source[-offset:]
        else:
            shifted[offset:] = source[:-offset]
        support += shifted.astype(np.uint8, copy=False)

    cleaned = source & (support >= max(1, int(min_support_slices)))
    removed = int(np.count_nonzero(source) - np.count_nonzero(cleaned))
    return cleaned.astype(np.uint8, copy=False), removed


def _constrain_mask_to_ct_body(record: dict[str, Any], binary: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    image_id = str(record.get("image_id") or "")
    if not image_id:
        return binary.astype(np.uint8, copy=False), {"applied": False, "reason": "mask has no image_id"}

    try:
        _, volume = load_volume(image_id)
        from scipy import ndimage as ndi
    except Exception as exc:
        return binary.astype(np.uint8, copy=False), {"applied": False, "reason": str(exc)}

    ct = volume.array
    if ct.shape[:3] != binary.shape[:3]:
        return binary.astype(np.uint8, copy=False), {
            "applied": False,
            "reason": f"ct/mask shape mismatch: ct={list(ct.shape[:3])}, mask={list(binary.shape[:3])}",
        }

    body_seed = ct > -850
    labeled, component_count = ndi.label(body_seed, structure=np.ones((3, 3, 3), dtype=np.uint8))
    if component_count > 0:
      sizes = np.bincount(labeled.reshape(-1))
      largest = int(np.argmax(sizes[1:]) + 1)
      body_seed = labeled == largest

    # Fill axial holes so lung/airway masks inside the chest remain inside the
    # envelope, then dilate a little to tolerate imperfect CT thresholding.
    envelope = np.zeros_like(body_seed, dtype=bool)
    for z in range(body_seed.shape[0]):
        envelope[z] = ndi.binary_fill_holes(body_seed[z])
    envelope = ndi.binary_closing(envelope, structure=np.ones((3, 5, 5), dtype=bool), iterations=1)
    envelope = ndi.binary_dilation(envelope, structure=np.ones((3, 5, 5), dtype=bool), iterations=2)

    before = int(np.count_nonzero(binary))
    constrained = (binary > 0) & envelope
    after = int(np.count_nonzero(constrained))
    if before > 0 and after < max(16, int(before * 0.02)):
        return binary.astype(np.uint8, copy=False), {
            "applied": False,
            "reason": "ct envelope would remove nearly all mask voxels",
            "voxel_count_before": before,
            "voxel_count_after": after,
        }
    return constrained.astype(np.uint8, copy=False), {
        "applied": True,
        "voxel_count_before": before,
        "voxel_count_after": after,
        "removed_voxels": before - after,
    }


def _source_mask_ids(record: dict[str, Any]) -> list[str]:
    source = record.get("source_mask_ids")
    if isinstance(source, list):
        return [str(value) for value in source]
    if isinstance(source, str) and source.strip():
        try:
            parsed = json.loads(source)
            if isinstance(parsed, list):
                return [str(value) for value in parsed]
        except json.JSONDecodeError:
            return [item.strip() for item in source.split(",") if item.strip()]
    return []


def _constrain_mask_to_source_roi(
    record: dict[str, Any],
    binary: np.ndarray,
    spacing: tuple[float, float, float],
    margin_mm: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    masks = _load_masks()
    source_ids = set(_source_mask_ids(record))
    source_records = [
        item
        for item in masks
        if item.get("mask_id") in source_ids
        and (item.get("mask_format") == "json" or str(item.get("path") or "").endswith(".json"))
    ]
    if not source_records:
        return binary.astype(np.uint8, copy=False), {"applied": False, "reason": "no source 2D JSON masks"}

    depth, height, width = binary.shape[:3]
    z_values: list[np.ndarray] = []
    y_values: list[np.ndarray] = []
    x_values: list[np.ndarray] = []
    for source in source_records:
        content = _read_mask_json(str(source.get("path") or ""))
        if not content or content.get("encoding") != "rle":
            continue
        axis = _normalize_axis(str(content.get("axis") or source.get("axis") or "axial"))
        slice_index = int(content.get("slice_index", -1))
        content_width = int(content.get("width", 0))
        content_height = int(content.get("height", 0))
        if content_width <= 0 or content_height <= 0:
            continue
        decoded = _decode_rle(content.get("mask") or [], content_width, content_height)
        axis_mask = _display_mask_to_axis_mask(axis, decoded)
        rows, cols = np.nonzero(axis_mask > 0)
        if rows.size == 0 or cols.size == 0:
            continue

        if axis == "axial" and 0 <= slice_index < depth:
            z_values.append(np.full(rows.shape, slice_index, dtype=np.int32))
            y_values.append(rows.astype(np.int32, copy=False))
            x_values.append(cols.astype(np.int32, copy=False))
        elif axis == "coronal" and 0 <= slice_index < height:
            z_values.append(rows.astype(np.int32, copy=False))
            y_values.append(np.full(rows.shape, slice_index, dtype=np.int32))
            x_values.append(cols.astype(np.int32, copy=False))
        elif axis == "sagittal" and 0 <= slice_index < width:
            z_values.append(rows.astype(np.int32, copy=False))
            y_values.append(cols.astype(np.int32, copy=False))
            x_values.append(np.full(rows.shape, slice_index, dtype=np.int32))

    if not z_values:
        return binary.astype(np.uint8, copy=False), {"applied": False, "reason": "source 2D masks are empty"}

    z_all = np.concatenate(z_values)
    y_all = np.concatenate(y_values)
    x_all = np.concatenate(x_values)
    margin_x = max(4, int(round(float(margin_mm) / max(float(spacing[0]), 1e-6))))
    margin_y = max(4, int(round(float(margin_mm) / max(float(spacing[1]), 1e-6))))
    margin_z = max(2, int(round(float(margin_mm) / max(float(spacing[2]), 1e-6))))
    z0 = max(0, int(z_all.min()) - margin_z)
    z1 = min(depth, int(z_all.max()) + margin_z + 1)
    y0 = max(0, int(y_all.min()) - margin_y)
    y1 = min(height, int(y_all.max()) + margin_y + 1)
    x0 = max(0, int(x_all.min()) - margin_x)
    x1 = min(width, int(x_all.max()) + margin_x + 1)

    roi = np.zeros_like(binary, dtype=bool)
    roi[z0:z1, y0:y1, x0:x1] = True
    before = int(np.count_nonzero(binary))
    constrained = (binary > 0) & roi
    after = int(np.count_nonzero(constrained))
    if before > 0 and after < max(16, int(before * 0.005)):
        return binary.astype(np.uint8, copy=False), {
            "applied": False,
            "reason": "source ROI would remove nearly all propagated voxels",
            "source_mask_ids": sorted(source_ids),
            "voxel_count_before": before,
            "voxel_count_after": after,
        }
    return constrained.astype(np.uint8, copy=False), {
        "applied": True,
        "source_mask_ids": sorted(source_ids),
        "margin_mm": float(margin_mm),
        "roi_zyx": [z0, z1, y0, y1, x0, x1],
        "voxel_count_before": before,
        "voxel_count_after": after,
        "removed_voxels": before - after,
    }


def _decimate_polydata(polydata, target_reduction: float, max_triangles: int):
    try:
        import vtk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=503, detail="vtk is required for mask surface mesh generation") from exc

    triangle_count = int(polydata.GetNumberOfPolys())
    reduction = max(0.0, min(float(target_reduction), 0.92))
    if max_triangles > 0 and triangle_count > max_triangles:
        reduction = max(reduction, min(0.92, 1.0 - (float(max_triangles) / float(triangle_count))))
    if reduction <= 0.001:
        return polydata

    best_output = polydata
    best_triangle_count = triangle_count
    attempts = [reduction]
    if max_triangles > 0 and triangle_count > max_triangles:
        attempts.extend([0.70, 0.82, 0.90, 0.94])

    for attempt in sorted(set(max(0.0, min(value, 0.94)) for value in attempts)):
        decimator = vtk.vtkQuadricDecimation()
        decimator.SetInputData(polydata)
        decimator.SetTargetReduction(attempt)
        decimator.VolumePreservationOn()
        decimator.Update()
        output = decimator.GetOutput()
        output_triangles = int(output.GetNumberOfPolys())
        if output.GetNumberOfPoints() == 0 or output_triangles == 0:
            continue
        if output_triangles < best_triangle_count:
            best_output = output
            best_triangle_count = output_triangles
        if max_triangles <= 0 or output_triangles <= max_triangles:
            return output

    return best_output


def get_mask_surface_mesh(
    mask_id: str,
    min_component_voxels: int = 64,
    max_components: int = 8,
    max_triangles: int = 90000,
    target_reduction: float = 0.55,
    smooth_iterations: int = 8,
    remove_thin: bool = True,
    constrain_to_body: bool = True,
    constrain_to_source_roi: bool = True,
    source_roi_margin_mm: float = 45.0,
) -> dict[str, Any]:
    try:
        import vtk
        from vtk.util import numpy_support
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="vtk is not installed. Run `pip install -r requirements.txt` to enable VTK mask surface mesh.",
        ) from exc

    record, image, binary = _read_nifti_mask_array(mask_id)
    spacing = tuple(float(value) for value in image.GetSpacing()[:3])
    cleanup: dict[str, Any] = {}
    if constrain_to_source_roi:
        binary, roi_cleanup = _constrain_mask_to_source_roi(
            record=record,
            binary=binary,
            spacing=spacing,
            margin_mm=source_roi_margin_mm,
        )
        cleanup["source_roi_constraint"] = roi_cleanup
    if constrain_to_body:
        binary, body_cleanup = _constrain_mask_to_ct_body(record, binary)
        cleanup["ct_body_constraint"] = body_cleanup
    if remove_thin:
        binary, removed_thin_voxels = _remove_thin_axial_artifacts(binary)
        cleanup["removed_thin_voxels"] = removed_thin_voxels

    binary, component_cleanup = _filter_mask_components(
        binary=binary,
        min_voxels=min_component_voxels,
        max_components=max_components,
    )
    cleanup.update(component_cleanup)
    if not np.any(binary):
        raise HTTPException(status_code=422, detail="Mask is empty after artifact cleanup")

    depth, height, width = binary.shape[:3]
    origin = tuple(float(value) for value in image.GetOrigin()[:3])

    image_data = vtk.vtkImageData()
    image_data.SetDimensions(int(width), int(height), int(depth))
    image_data.SetSpacing(spacing)
    image_data.SetOrigin(origin)
    scalars = numpy_support.numpy_to_vtk(
        np.ascontiguousarray(binary).reshape(-1, order="C"),
        deep=True,
        array_type=vtk.VTK_UNSIGNED_CHAR,
    )
    scalars.SetName("mask")
    image_data.GetPointData().SetScalars(scalars)

    marching = vtk.vtkMarchingCubes()
    marching.SetInputData(image_data)
    marching.SetValue(0, 0.5)
    marching.ComputeNormalsOff()
    marching.ComputeGradientsOff()
    marching.Update()

    triangle_filter = vtk.vtkTriangleFilter()
    triangle_filter.SetInputConnection(marching.GetOutputPort())
    triangle_filter.Update()
    polydata = triangle_filter.GetOutput()

    if smooth_iterations > 0 and polydata.GetNumberOfPoints() > 0:
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputData(polydata)
        smoother.SetNumberOfIterations(max(0, min(int(smooth_iterations), 24)))
        smoother.BoundarySmoothingOff()
        smoother.FeatureEdgeSmoothingOff()
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()
        smoother.Update()
        smoothed = smoother.GetOutput()
        if smoothed.GetNumberOfPoints() > 0 and smoothed.GetNumberOfPolys() > 0:
            polydata = smoothed

    polydata = _decimate_polydata(polydata, target_reduction=target_reduction, max_triangles=max_triangles)
    normals_filter = vtk.vtkPolyDataNormals()
    normals_filter.SetInputData(polydata)
    normals_filter.ComputePointNormalsOn()
    normals_filter.ComputeCellNormalsOff()
    normals_filter.SplittingOff()
    normals_filter.ConsistencyOn()
    normals_filter.AutoOrientNormalsOn()
    normals_filter.Update()
    normals_polydata = normals_filter.GetOutput()
    if normals_polydata.GetNumberOfPoints() > 0 and normals_polydata.GetPointData().GetNormals() is not None:
        polydata = normals_polydata

    if polydata.GetNumberOfPoints() == 0 or polydata.GetNumberOfPolys() == 0:
        raise HTTPException(status_code=422, detail="VTK could not extract a surface from this mask")

    points = polydata.GetPoints()
    vtk_points = numpy_support.vtk_to_numpy(points.GetData()).astype(np.float32, copy=False)
    normal_data = polydata.GetPointData().GetNormals()
    if normal_data is not None:
        normals = numpy_support.vtk_to_numpy(normal_data).astype(np.float32, copy=False)
    else:
        normals = np.zeros_like(vtk_points, dtype=np.float32)
    extent = np.array(
        [
            spacing[0] * max(width - 1, 1),
            spacing[1] * max(height - 1, 1),
            spacing[2] * max(depth - 1, 1),
        ],
        dtype=np.float32,
    )
    normalized = (vtk_points - np.array(origin, dtype=np.float32)) / np.maximum(extent, 1e-6)
    normalized = np.clip(normalized, 0.0, 1.0).astype(np.float32, copy=False)

    polys = numpy_support.vtk_to_numpy(polydata.GetPolys().GetData()).astype(np.int64, copy=False)
    indices: list[int] = []
    cursor = 0
    while cursor < polys.size:
        count = int(polys[cursor])
        if count == 3 and cursor + 3 < polys.size:
            indices.extend(int(value) for value in polys[cursor + 1 : cursor + 4])
        cursor += count + 1

    if not indices:
        raise HTTPException(status_code=422, detail="VTK surface contains no triangles")

    return {
        "success": True,
        "mask_id": mask_id,
        "case_id": record.get("case_id"),
        "image_id": record.get("image_id"),
        "version": record.get("version"),
        "label": record.get("label"),
        "source": "vtk_marching_cubes",
        "dimensions": [width, height, depth],
        "spacing": [float(value) for value in spacing],
        "origin": [float(value) for value in origin],
        "cleanup": cleanup,
        "vertex_count": int(normalized.shape[0]),
        "triangle_count": int(len(indices) // 3),
        "positions": normalized.reshape(-1).round(6).tolist(),
        "normals": normals.reshape(-1).round(5).tolist(),
        "indices": indices,
    }


def get_mask_quality_summary(mask_id: str) -> dict[str, Any]:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to read 3D mask quality") from exc

    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if record.get("mask_format") != "nii.gz":
        raise HTTPException(status_code=400, detail="Only 3D NIfTI masks have 3D quality summary")

    path = (PROJECT_ROOT / str(record.get("path"))).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mask path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Mask file not found: {record.get('path')}")

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    values = array > 0
    depth, height, width = values.shape[:3]
    spacing = [float(value) for value in image.GetSpacing()[:3]]
    voxel_count = int(np.count_nonzero(values))
    voxel_volume_mm3 = float(spacing[0] * spacing[1] * spacing[2])
    physical_volume_mm3 = voxel_count * voxel_volume_mm3

    if voxel_count > 0:
        z_indices = np.where(np.any(values, axis=(1, 2)))[0]
        slice_range = {
            "start": int(z_indices[0]),
            "end": int(z_indices[-1]),
            "count": int(z_indices[-1] - z_indices[0] + 1),
        }
        component_image = sitk.ConnectedComponent(sitk.GetImageFromArray(values.astype(np.uint8)))
        stats = sitk.LabelShapeStatisticsImageFilter()
        stats.Execute(component_image)
        component_sizes = [int(stats.GetNumberOfPixels(label)) for label in stats.GetLabels()]
        connected_component_count = len(component_sizes)
        largest_component_voxels = max(component_sizes) if component_sizes else 0
    else:
        slice_range = {"start": None, "end": None, "count": 0}
        connected_component_count = 0
        largest_component_voxels = 0
    largest_component_ratio = (largest_component_voxels / voxel_count) if voxel_count else 0.0

    return {
        "success": True,
        "mask_id": mask_id,
        "case_id": record.get("case_id"),
        "image_id": record.get("image_id"),
        "version": record.get("version"),
        "label": record.get("label"),
        "voxel_count": voxel_count,
        "volume_ml": physical_volume_mm3 / 1000.0,
        "connected_component_count": connected_component_count,
        "largest_component_voxels": largest_component_voxels,
        "largest_component_ratio": largest_component_ratio,
        "slice_range": slice_range,
        "dimensions": [width, height, depth],
        "spacing": spacing,
        "physical_volume_mm3": physical_volume_mm3,
    }


def _mask_slice_by_axis(array: np.ndarray, axis: str, slice_index: int) -> np.ndarray:
    depth, height, width = array.shape[:3]
    if axis == "axial":
        index = max(0, min(slice_index, depth - 1))
        return array[index, :, :]
    if axis == "coronal":
        index = max(0, min(slice_index, height - 1))
        return np.flipud(array[:, index, :])
    if axis == "sagittal":
        index = max(0, min(slice_index, width - 1))
        return np.flipud(array[:, :, index])
    raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")


def get_mask_slice_data(mask_id: str, slice_index: int, axis: str = "axial") -> dict[str, Any]:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required to read propagated mask slices") from exc

    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if record.get("mask_format") != "nii.gz":
        raise HTTPException(status_code=400, detail="Only 3D NIfTI masks can provide propagated slices")

    path = (PROJECT_ROOT / str(record.get("path"))).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mask path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Mask file not found: {record.get('path')}")

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    axis = _normalize_axis(axis)
    depth, height, width = array.shape[:3]
    max_slices, expected_height, expected_width = _axis_plane_shape(axis, depth, height, width)
    if not 0 <= slice_index < max_slices:
        raise HTTPException(status_code=400, detail=f"slice_index is outside mask volume: {slice_index}")

    slice_mask = (_mask_slice_by_axis(array, axis, slice_index) > 0).astype(np.uint8)
    return {
        "success": True,
        "mask_id": mask_id,
        "case_id": record.get("case_id"),
        "image_id": record.get("image_id"),
        "version": record.get("version"),
        "label": record.get("label"),
        "axis": axis,
        "slice_index": slice_index,
        "width": expected_width,
        "height": expected_height,
        "encoding": "rle",
        "mask": _encode_rle(slice_mask),
    }


def _find_slice_json_mask(
    *,
    case_id: str,
    image_id: str,
    version: str,
    label: str,
    axis: str,
    slice_index: int | None,
) -> dict | None:
    if slice_index is None:
        return None
    candidates = [
        mask
        for mask in _load_masks()
        if mask.get("case_id") == case_id
        and mask.get("image_id") == image_id
        and mask.get("version") == version
        and mask.get("label") == label
        and (mask.get("mask_format") == "json" or str(mask.get("path") or "").endswith(".json"))
        and int(mask.get("slice_index") if mask.get("slice_index") is not None else -1) == int(slice_index)
    ]
    matched: list[dict] = []
    for mask in candidates:
        mask_axis = mask.get("axis")
        if not mask_axis:
            content = _read_mask_json(str(mask.get("path") or ""))
            mask_axis = (content or {}).get("axis") or "axial"
        if str(mask_axis).strip().lower() == axis:
            matched.append(mask)
    if not matched:
        return None
    matched.sort(key=lambda item: str(item.get("create_time") or ""))
    return matched[-1]


def save_mask(request: SaveMaskRequest, user: dict | None = None) -> SaveMaskResponse:
    ensure_project_dirs()

    version = request.version.strip()
    if version not in VALID_MASK_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mask version: {version}. Use one of {sorted(VALID_MASK_VERSIONS)}",
        )

    mask_format = request.mask_format.strip().lower()
    if mask_format not in VALID_MASK_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported mask format: {mask_format}")

    image = _image_record(request.image_id)
    if image.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    label = _normalize_label(request.label)
    axis = _normalize_axis(request.axis) if mask_format == "json" else None
    existing = None
    if mask_format == "json" and request.overwrite:
        existing = _find_slice_json_mask(
            case_id=request.case_id,
            image_id=request.image_id,
            version=version,
            label=label,
            axis=axis or "axial",
            slice_index=request.slice_index,
        )
    if request.label_type is not None:
        label_type = _normalize_label_type(request.label_type)
    elif existing and existing.get("label_type"):
        label_type = _normalize_label_type(str(existing.get("label_type")))
    else:
        label_type = "dense"

    updated = False
    if existing:
        mask_id = str(existing["mask_id"])
        mask_path = str(existing.get("path") or "")
        updated = True
    else:
        mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
        mask_path = _mask_path(
            case_id=request.case_id,
            image_id=request.image_id,
            mask_id=mask_id,
            version=version,
            label=label,
            mask_format=mask_format,
        )

    if mask_format == "json":
        _write_mask_json(mask_path, request, mask_id, label)

    record = {
        "mask_id": mask_id,
        "annotation_id": (
            request.annotation_id
            if request.annotation_id is not None
            else (existing.get("annotation_id") if existing else None)
        ),
        "case_id": request.case_id,
        "image_id": request.image_id,
        "path": mask_path,
        "version": version,
        "label": label,
        "label_id": request.label_id,
        "label_type": label_type,
        "mask_format": mask_format,
        "axis": axis,
        "slice_index": request.slice_index,
        "width": request.width,
        "height": request.height,
        "encoding": request.encoding,
        "create_time": _now_iso() if not existing else existing.get("create_time") or _now_iso(),
    }
    upsert_record("masks", record)

    if version == "v1_manual":
        from backend.app.services.workflow_service import append_audit_log, mark_case_annotated

        mark_case_annotated(
            request.case_id,
            user=user,
            detail={"mask_id": mask_id, "version": version, "label": label, "updated": updated, "axis": axis},
        )
        append_audit_log(
            action="update_mask" if updated else "create_mask",
            user=user,
            entity_type="mask",
            entity_id=mask_id,
            case_id=request.case_id,
            detail={"axis": axis, "slice_index": request.slice_index, "label": label},
        )

    mask = MaskRecord(**record)
    return SaveMaskResponse(success=True, mask_id=mask_id, path=mask_path, mask=mask, updated=updated)


def update_mask(mask_id: str, request: UpdateMaskRequest, user: dict | None = None) -> SaveMaskResponse:
    ensure_project_dirs()
    masks = _load_masks()
    source = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if not (source.get("mask_format") == "json" or str(source.get("path") or "").endswith(".json")):
        raise HTTPException(status_code=400, detail="Only JSON slice masks can be updated in place")

    label = _normalize_label(request.label) if request.label else _normalize_label(str(source.get("label") or "label"))
    axis = _normalize_axis(request.axis) if request.axis else _normalize_axis(str(source.get("axis") or "axial"))
    slice_index = request.slice_index if request.slice_index is not None else source.get("slice_index")
    width = request.width if request.width is not None else source.get("width")
    height = request.height if request.height is not None else source.get("height")
    encoding = request.encoding if request.encoding is not None else source.get("encoding") or "rle"
    if request.label_type is not None:
        label_type = _normalize_label_type(request.label_type)
    elif source.get("label_type"):
        label_type = _normalize_label_type(str(source.get("label_type")))
    else:
        label_type = "dense"
    if slice_index is None or width is None or height is None:
        raise HTTPException(status_code=400, detail="JSON mask update requires slice_index, width and height")
    if request.mask is None:
        content = _read_mask_json(str(source.get("path") or ""))
        if not content or content.get("mask") is None:
            raise HTTPException(status_code=400, detail="Mask update requires mask data")
        mask_runs = content.get("mask")
        points = request.points if request.points is not None else content.get("points") or []
    else:
        mask_runs = request.mask
        points = request.points or []

    save_request = SaveMaskRequest(
        case_id=str(source.get("case_id")),
        image_id=str(source.get("image_id")),
        annotation_id=source.get("annotation_id"),
        version=str(source.get("version") or "v1_manual"),
        label=label,
        label_type=label_type,
        mask_format="json",
        axis=axis,
        slice_index=int(slice_index),
        width=int(width),
        height=int(height),
        label_id=request.label_id if request.label_id is not None else source.get("label_id"),
        encoding=str(encoding),
        mask=mask_runs,
        points=points,
        overwrite=False,
    )
    mask_path = str(source.get("path") or "")
    _write_mask_json(mask_path, save_request, mask_id, label)
    record = {
        **source,
        "label": label,
        "label_id": save_request.label_id,
        "label_type": label_type,
        "axis": axis,
        "slice_index": int(slice_index),
        "width": int(width),
        "height": int(height),
        "encoding": str(encoding),
        "create_time": _now_iso(),
    }
    upsert_record("masks", record)

    from backend.app.services.workflow_service import append_audit_log, mark_case_annotated

    mark_case_annotated(
        str(source.get("case_id")),
        user=user,
        detail={"mask_id": mask_id, "updated": True, "axis": axis},
    )
    append_audit_log(
        action="update_mask",
        user=user,
        entity_type="mask",
        entity_id=mask_id,
        case_id=str(source.get("case_id")),
        detail={"axis": axis, "slice_index": slice_index, "label": label},
    )
    return SaveMaskResponse(
        success=True,
        mask_id=mask_id,
        path=mask_path,
        mask=MaskRecord(**record),
        updated=True,
    )


def delete_mask(mask_id: str, user: dict | None = None) -> dict:
    ensure_project_dirs()
    masks = _load_masks()
    source = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")

    path = PROJECT_ROOT / str(source.get("path") or "")
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid mask path") from exc
    if path.exists() and path.is_file():
        path.unlink()

    deleted = delete_record("masks", "mask_id", mask_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")

    from backend.app.services.workflow_service import append_audit_log

    append_audit_log(
        action="delete_mask",
        user=user,
        entity_type="mask",
        entity_id=mask_id,
        case_id=str(source.get("case_id") or ""),
        detail={"path": source.get("path"), "version": source.get("version"), "label": source.get("label")},
    )
    return {"success": True, "mask_id": mask_id, "message": "deleted"}


def promote_mask(mask_id: str, target_version: str, user: dict | None = None) -> SaveMaskResponse:
    ensure_project_dirs()
    target_version = target_version.strip()
    if target_version not in PROMOTABLE_TARGET_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target_version: {target_version}. Use one of {sorted(PROMOTABLE_TARGET_VERSIONS)}",
        )

    if target_version == "final" and user and str(user.get("role")) == "annotator":
        raise HTTPException(status_code=403, detail="Annotators cannot confirm final")

    masks = _load_masks()
    source = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if source.get("version") not in {"v3_preview", "v3_fusion"}:
        raise HTTPException(
            status_code=400,
            detail="Only v3_preview or v3_fusion 3D masks can be promoted",
        )
    if source.get("version") == "v3_fusion" and target_version != "final":
        raise HTTPException(status_code=400, detail="v3_fusion can only be promoted to final")
    if source.get("version") == target_version:
        raise HTTPException(status_code=400, detail=f"Mask is already {target_version}")

    source_path = PROJECT_ROOT / str(source.get("path") or "")
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source mask file not found: {source.get('path')}")
    if not (source.get("mask_format") == "nii.gz" or str(source.get("path") or "").endswith(".nii.gz")):
        raise HTTPException(status_code=400, detail="Only NIfTI 3D masks can be promoted")

    new_mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
    label = _normalize_label(str(source.get("label") or "label"))
    new_path = _mask_path(
        case_id=str(source.get("case_id")),
        image_id=str(source.get("image_id")),
        mask_id=new_mask_id,
        version=target_version,
        label=label,
        mask_format="nii.gz",
    )
    target_path = PROJECT_ROOT / new_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)

    source_mask_ids = [mask_id]
    existing_source_ids = source.get("source_mask_ids")
    if isinstance(existing_source_ids, str):
        try:
            parsed = json.loads(existing_source_ids)
            if isinstance(parsed, list):
                source_mask_ids.extend(str(value) for value in parsed)
        except json.JSONDecodeError:
            pass
    elif isinstance(existing_source_ids, list):
        source_mask_ids.extend(str(value) for value in existing_source_ids)

    record = {
        "mask_id": new_mask_id,
        "annotation_id": source.get("annotation_id"),
        "case_id": source.get("case_id"),
        "image_id": source.get("image_id"),
        "path": new_path,
        "version": target_version,
        "label": label,
        "label_type": "dense" if target_version == "final" else (source.get("label_type") or "pseudo"),
        "mask_format": "nii.gz",
        "slice_index": None,
        "width": source.get("width"),
        "height": source.get("height"),
        "encoding": f"promoted_from_{mask_id}",
        "create_time": _now_iso(),
        "source_mask_ids": sorted(set(source_mask_ids)),
        "shape": source.get("shape"),
        "spacing": source.get("spacing"),
        "origin": source.get("origin"),
        "direction": source.get("direction"),
    }
    upsert_record("masks", record)

    from backend.app.services.workflow_service import append_audit_log, finalize_case

    append_audit_log(
        action="promote_mask",
        user=user,
        entity_type="mask",
        entity_id=new_mask_id,
        case_id=str(source.get("case_id")),
        detail={"from_mask": mask_id, "target_version": target_version},
    )
    if target_version == "final" and user:
        finalize_case(
            str(source.get("case_id")),
            user,
            detail={"mask_id": new_mask_id, "promoted_from": mask_id},
        )

    mask = MaskRecord(**record)
    return SaveMaskResponse(success=True, mask_id=new_mask_id, path=new_path, mask=mask)


def get_mask(mask_id: str) -> MaskRecord:
    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    return MaskRecord(**record)


def get_mask_content(mask_id: str) -> dict[str, Any] | None:
    masks = _load_masks()
    record = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if record.get("mask_format") != "json":
        return None
    return _read_mask_json(str(record.get("path")))


def list_masks_for_image(image_id: str) -> list[MaskRecord]:
    _image_record(image_id)
    masks = _load_masks()
    result: list[MaskRecord] = []
    for mask in masks:
        if mask.get("image_id") != image_id and mask.get("image") != image_id:
            continue
        record = dict(mask)
        if (record.get("mask_format") == "json" or str(record.get("path") or "").endswith(".json")) and not record.get("axis"):
            content = _read_mask_json(str(record.get("path") or ""))
            if content:
                record["axis"] = content.get("axis") or "axial"
                if record.get("slice_index") is None and content.get("slice_index") is not None:
                    record["slice_index"] = content.get("slice_index")
        result.append(MaskRecord(**{key: record.get(key) for key in MaskRecord.model_fields}))
    return result


def export_mask_nifti(request: ExportMaskNiftiRequest) -> ExportMaskNiftiResponse:
    image_record, volume = load_volume(request.image_id)
    if image_record.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )

    version = request.version.strip()
    if version not in VALID_MASK_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mask version: {version}. Use one of {sorted(VALID_MASK_VERSIONS)}",
        )
    label = _normalize_label(request.label)
    match_any = bool(request.match_any_label or label in {"*", "all", "全部标注"})
    output_label = str(request.output_label or "").strip() or ("全部标注" if match_any else label)
    depth, height, width = volume.array.shape[:3]
    mask_stack = np.zeros((depth, height, width), dtype=np.uint8)

    masks = _load_masks()
    json_records = _json_mask_records(
        masks,
        request.case_id,
        request.image_id,
        version,
        label,
        match_any_label=match_any,
    )
    if not json_records:
        raise HTTPException(status_code=404, detail="No saved JSON slice masks found for this image/version/label")

    sparse_slices_by_axis, source_mask_ids = _load_sparse_axis_masks(json_records, depth, height, width)
    if not any(sparse_slices_by_axis.values()):
        raise HTTPException(status_code=404, detail="No readable JSON slice masks found")
    for axis, sparse_slices in sparse_slices_by_axis.items():
        for slice_index, slice_mask in sparse_slices.items():
            _merge_axis_slice_into_volume(mask_stack, axis, slice_index, slice_mask)

    if not np.any(mask_stack):
        raise HTTPException(status_code=422, detail="Stacked 2D annotations produced an empty 3D mask")

    mask, mask_path = _append_3d_mask_record(
        masks=masks,
        request_case_id=request.case_id,
        image_id=request.image_id,
        version=version,
        label=output_label,
        encoding="3d_nifti_from_json_slices",
        source_mask_ids=source_mask_ids,
        mask_stack=mask_stack,
        volume=volume,
        label_type="dense",
    )
    return ExportMaskNiftiResponse(
        success=True,
        mask_id=mask.mask_id,
        path=mask_path,
        source_mask_ids=source_mask_ids,
        shape=[depth, height, width],
        spacing=[float(value) for value in volume.spacing],
        origin=[float(value) for value in volume.origin],
        direction=[float(value) for value in volume.direction],
        mask=mask,
    )


def _cleanup_binary_slice(
    slice_mask: np.ndarray,
    fill_holes: bool,
    keep_largest_component: bool,
    closing_radius: int,
) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required for label propagation") from exc

    image = sitk.GetImageFromArray((slice_mask > 0).astype(np.uint8))
    if closing_radius > 0:
        image = sitk.BinaryMorphologicalClosing(image, [int(closing_radius), int(closing_radius)])
    if fill_holes:
        image = sitk.BinaryFillhole(image, fullyConnected=False)
    if keep_largest_component:
        components = sitk.ConnectedComponent(image)
        relabeled = sitk.RelabelComponent(components, sortByObjectSize=True)
        image = sitk.Equal(relabeled, 1)
    return sitk.GetArrayFromImage(image).astype(np.uint8)


def _signed_distance_slice(slice_mask: np.ndarray, spacing_xy: tuple[float, float]) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required for label propagation") from exc

    binary = (slice_mask > 0).astype(np.uint8)
    image = sitk.GetImageFromArray(binary)
    image.SetSpacing((float(spacing_xy[0]), float(spacing_xy[1])))
    distance = sitk.SignedMaurerDistanceMap(
        image,
        insideIsPositive=True,
        squaredDistance=False,
        useImageSpacing=True,
    )
    return sitk.GetArrayFromImage(distance).astype(np.float32)


def _foreground_hu_range(
    volume_array: np.ndarray,
    sparse_slices: dict[int, np.ndarray],
    hu_margin: float | None,
) -> tuple[float, float] | None:
    values: list[np.ndarray] = []
    for z, slice_mask in sparse_slices.items():
        foreground = volume_array[z][slice_mask > 0]
        if foreground.size:
            values.append(foreground.astype(np.float32, copy=False))
    if not values:
        return None

    samples = np.concatenate(values)
    if samples.size > 250_000:
        step = max(1, samples.size // 250_000)
        samples = samples[::step]
    lower = float(np.percentile(samples, 2))
    upper = float(np.percentile(samples, 98))
    margin = float(hu_margin) if hu_margin is not None else max(30.0, (upper - lower) * 0.2)
    return lower - margin, upper + margin


def _apply_image_guidance(candidate: np.ndarray, ct_slice: np.ndarray, hu_range: tuple[float, float] | None) -> np.ndarray:
    if hu_range is None or not np.any(candidate):
        return candidate.astype(np.uint8, copy=False)

    low, high = hu_range
    guided = (candidate > 0) & (ct_slice >= low) & (ct_slice <= high)
    candidate_area = int(np.count_nonzero(candidate))
    guided_area = int(np.count_nonzero(guided))

    # If the HU prior is too strict for a slice, keep the distance result instead
    # of deleting the propagated label entirely.
    if guided_area < max(8, int(candidate_area * 0.05)):
        return candidate.astype(np.uint8, copy=False)
    return guided.astype(np.uint8)


def _morphology_mask(mask: np.ndarray, operation: str, iterations: int) -> np.ndarray:
    iterations = max(0, int(iterations))
    if iterations <= 0:
        return (mask > 0)
    try:
        from scipy import ndimage as ndi
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="scipy is required for graph-based label propagation") from exc

    structure = np.ones((3, 3), dtype=bool)
    binary = mask > 0
    if operation == "erode":
        return ndi.binary_erosion(binary, structure=structure, iterations=iterations)
    if operation == "dilate":
        return ndi.binary_dilation(binary, structure=structure, iterations=iterations)
    raise HTTPException(status_code=500, detail=f"Unsupported morphology operation: {operation}")


def _bounding_box(mask: np.ndarray, margin: int) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask > 0)
    if ys.size == 0 or xs.size == 0:
        return None
    height, width = mask.shape[:2]
    y0 = max(0, int(ys.min()) - margin)
    y1 = min(height, int(ys.max()) + margin + 1)
    x0 = max(0, int(xs.min()) - margin)
    x1 = min(width, int(xs.max()) + margin + 1)
    return y0, y1, x0, x1


def _normalize_graph_image(image: np.ndarray) -> np.ndarray:
    values = image.astype(np.float32, copy=False)
    low = float(np.percentile(values, 1))
    high = float(np.percentile(values, 99))
    if high <= low:
        return np.zeros_like(values, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0.0, 1.0).astype(np.float32, copy=False)


def _solve_binary_random_walker(
    image_roi: np.ndarray,
    foreground_seeds: np.ndarray,
    background_seeds: np.ndarray,
    beta: float,
) -> np.ndarray:
    try:
        from scipy import sparse
        from scipy.sparse import linalg as splinalg
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="scipy is required for graph-based label propagation") from exc

    height, width = image_roi.shape[:2]
    node_count = height * width
    if node_count == 0:
        return np.zeros((height, width), dtype=np.uint8)

    image = _normalize_graph_image(image_roi)
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    diagonal = np.zeros(node_count, dtype=np.float64)

    def add_edge(first: np.ndarray, second: np.ndarray, weights: np.ndarray) -> None:
        first_flat = first.reshape(-1)
        second_flat = second.reshape(-1)
        weight_flat = weights.reshape(-1).astype(np.float64, copy=False)
        diagonal[first_flat] += weight_flat
        diagonal[second_flat] += weight_flat
        rows.extend(first_flat.tolist())
        cols.extend(second_flat.tolist())
        data.extend((-weight_flat).tolist())
        rows.extend(second_flat.tolist())
        cols.extend(first_flat.tolist())
        data.extend((-weight_flat).tolist())

    ids = np.arange(node_count, dtype=np.int32).reshape(height, width)
    if width > 1:
        diff = image[:, 1:] - image[:, :-1]
        weights = np.exp(-float(beta) * diff * diff) + 1e-6
        add_edge(ids[:, :-1], ids[:, 1:], weights)
    if height > 1:
        diff = image[1:, :] - image[:-1, :]
        weights = np.exp(-float(beta) * diff * diff) + 1e-6
        add_edge(ids[:-1, :], ids[1:, :], weights)

    rows.extend(range(node_count))
    cols.extend(range(node_count))
    data.extend(diagonal.tolist())
    laplacian = sparse.csr_matrix((data, (rows, cols)), shape=(node_count, node_count))

    fg = foreground_seeds.reshape(-1).astype(bool, copy=False)
    bg = background_seeds.reshape(-1).astype(bool, copy=False) & ~fg
    known = fg | bg
    unknown = ~known
    if not np.any(fg) or not np.any(bg):
        return fg.reshape(height, width).astype(np.uint8)
    if not np.any(unknown):
        return fg.reshape(height, width).astype(np.uint8)

    known_values = fg[known].astype(np.float64)
    l_uu = laplacian[unknown][:, unknown]
    l_ul = laplacian[unknown][:, known]
    rhs = -(l_ul @ known_values)
    try:
        solution, info = splinalg.cg(l_uu, rhs, rtol=1e-5, atol=1e-7, maxiter=300)
    except TypeError:
        solution, info = splinalg.cg(l_uu, rhs, tol=1e-5, maxiter=300)
    if info != 0:
        solution = splinalg.spsolve(l_uu, rhs)

    probabilities = np.zeros(node_count, dtype=np.float64)
    probabilities[fg] = 1.0
    probabilities[unknown] = np.clip(solution, 0.0, 1.0)
    return (probabilities.reshape(height, width) >= 0.5).astype(np.uint8)


def _random_walker_refine_slice(
    ct_slice: np.ndarray,
    candidate_mask: np.ndarray,
    sparse_mask: np.ndarray | None,
    positive_seed_mask: np.ndarray | None,
    negative_seed_mask: np.ndarray | None,
    beta: float,
    roi_margin: int,
    max_nodes: int,
) -> np.ndarray:
    candidate = candidate_mask > 0
    sparse_foreground = sparse_mask > 0 if sparse_mask is not None else np.zeros_like(candidate, dtype=bool)
    positive_seed = positive_seed_mask > 0 if positive_seed_mask is not None else np.zeros_like(candidate, dtype=bool)
    negative_seed = negative_seed_mask > 0 if negative_seed_mask is not None else np.zeros_like(candidate, dtype=bool)
    seed_source = candidate | sparse_foreground | positive_seed | negative_seed
    bbox = _bounding_box(seed_source, max(4, int(roi_margin)))
    if bbox is None:
        return np.zeros_like(candidate_mask, dtype=np.uint8)

    y0, y1, x0, x1 = bbox
    node_count = (y1 - y0) * (x1 - x0)
    if node_count > max(256, int(max_nodes)):
        return (candidate & ~negative_seed).astype(np.uint8)

    candidate_roi = candidate[y0:y1, x0:x1]
    sparse_roi = sparse_foreground[y0:y1, x0:x1]
    positive_roi = positive_seed[y0:y1, x0:x1]
    negative_roi = negative_seed[y0:y1, x0:x1]
    foreground = (sparse_roi | positive_roi) & ~negative_roi
    if not np.any(foreground):
        foreground = _morphology_mask(candidate_roi & ~negative_roi, "erode", 1)
    if not np.any(foreground):
        foreground = candidate_roi & ~negative_roi

    dilated = _morphology_mask(candidate_roi | foreground, "dilate", 3)
    background = negative_roi | ~dilated
    background[0, :] = True
    background[-1, :] = True
    background[:, 0] = True
    background[:, -1] = True
    background &= ~foreground
    if not np.any(background):
        return (candidate & ~negative_seed).astype(np.uint8)

    refined_roi = _solve_binary_random_walker(
        image_roi=ct_slice[y0:y1, x0:x1],
        foreground_seeds=foreground,
        background_seeds=background,
        beta=max(1.0, float(beta)),
    )
    refined_roi = np.maximum(refined_roi, sparse_roi.astype(np.uint8))
    refined_roi = np.maximum(refined_roi, positive_roi.astype(np.uint8))
    refined_roi[negative_roi] = 0
    refined = np.zeros_like(candidate_mask, dtype=np.uint8)
    refined[y0:y1, x0:x1] = refined_roi
    refined[negative_seed] = 0
    return refined


def _refine_with_random_walker(
    candidate_volume: np.ndarray,
    volume_array: np.ndarray,
    sparse_slices: dict[int, np.ndarray],
    positive_slices: dict[int, np.ndarray] | None,
    negative_slices: dict[int, np.ndarray] | None,
    fill_holes: bool,
    keep_largest_component: bool,
    closing_radius: int,
    beta: float,
    roi_margin: int,
    max_nodes: int,
) -> np.ndarray:
    positive_slices = positive_slices or {}
    negative_slices = negative_slices or {}
    refined = np.zeros_like(candidate_volume, dtype=np.uint8)
    for slice_index in range(candidate_volume.shape[0]):
        if (
            not np.any(candidate_volume[slice_index])
            and slice_index not in sparse_slices
            and slice_index not in positive_slices
        ):
            continue
        slice_refined = _random_walker_refine_slice(
            ct_slice=volume_array[slice_index],
            candidate_mask=candidate_volume[slice_index],
            sparse_mask=sparse_slices.get(slice_index),
            positive_seed_mask=positive_slices.get(slice_index),
            negative_seed_mask=negative_slices.get(slice_index),
            beta=beta,
            roi_margin=roi_margin,
            max_nodes=max_nodes,
        )
        cleaned = _cleanup_binary_slice(
            slice_refined,
            fill_holes=fill_holes,
            keep_largest_component=keep_largest_component,
            closing_radius=closing_radius,
        )
        if slice_index in negative_slices:
            cleaned[negative_slices[slice_index] > 0] = 0
        refined[slice_index] = cleaned

    for slice_index, slice_mask in {**sparse_slices, **positive_slices}.items():
        refined[slice_index] = np.maximum(refined[slice_index], (slice_mask > 0).astype(np.uint8))
    for slice_index, slice_mask in negative_slices.items():
        refined[slice_index][slice_mask > 0] = 0
    return refined


def _seed_volume_from_sparse_slices(
    sparse_slices: dict[int, np.ndarray],
    shape: tuple[int, int, int],
) -> np.ndarray:
    seed_volume = np.zeros(shape, dtype=np.uint8)
    depth = shape[0]
    for slice_index, slice_mask in sparse_slices.items():
        if 0 <= slice_index < depth:
            seed_volume[slice_index] = np.maximum(seed_volume[slice_index], (slice_mask > 0).astype(np.uint8))
    return seed_volume


def _draw_seed_disk(mask: np.ndarray, row: int, col: int, radius: int) -> None:
    height, width = mask.shape[:2]
    radius = max(1, int(radius))
    row = max(0, min(int(row), height - 1))
    col = max(0, min(int(col), width - 1))
    y0 = max(0, row - radius)
    y1 = min(height, row + radius + 1)
    x0 = max(0, col - radius)
    x1 = min(width, col + radius + 1)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask[y0:y1, x0:x1][(yy - row) ** 2 + (xx - col) ** 2 <= radius * radius] = 1


def _point_to_axis_indices(point: list[float], axis: str, shape: tuple[int, int, int]) -> tuple[int, int, int] | None:
    if len(point) < 3:
        return None
    depth, height, width = shape
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    z = int(round(float(point[2])))
    if axis == "axial":
        slice_index, row, col = z, y, x
    elif axis == "coronal":
        slice_index, row, col = y, z, x
    elif axis == "sagittal":
        slice_index, row, col = x, z, y
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported slice axis: {axis}")
    if not (0 <= slice_index < depth and 0 <= row < height and 0 <= col < width):
        return None
    return slice_index, row, col


def _point_prompt_slices(
    points: list[list[float]],
    axis: str,
    shape: tuple[int, int, int],
    radius: int = 5,
) -> dict[int, np.ndarray]:
    _, height, width = shape
    slices: dict[int, np.ndarray] = {}
    for point in points or []:
        indices = _point_to_axis_indices(point, axis, shape)
        if indices is None:
            continue
        slice_index, row, col = indices
        if slice_index not in slices:
            slices[slice_index] = np.zeros((height, width), dtype=np.uint8)
        _draw_seed_disk(slices[slice_index], row, col, radius)
    return slices


def _scribble_prompt_points(scribbles: list[dict[str, Any]], prompt_type: str) -> list[list[float]]:
    output: list[list[float]] = []
    target_type = prompt_type.strip().lower()
    for scribble in scribbles or []:
        if not isinstance(scribble, dict):
            continue
        if str(scribble.get("prompt_type") or "positive").strip().lower() != target_type:
            continue
        axis = _normalize_axis(str(scribble.get("axis") or "axial"))
        slice_index = int(scribble.get("slice_index", 0))
        for point in scribble.get("points") or []:
            if not isinstance(point, dict):
                continue
            x = float(point.get("x", 0))
            y = float(point.get("y", 0))
            z = float(point.get("z", slice_index))
            if axis == "axial":
                output.append([x, y, z])
            elif axis == "coronal":
                output.append([x, z, y])
            elif axis == "sagittal":
                output.append([z, x, y])
    return output


def _connected_component_filter_volume(
    mask_volume: np.ndarray,
    seed_volume: np.ndarray | None,
    mode: str,
    min_voxels: int,
    max_components: int,
    keep_largest_component: bool,
) -> np.ndarray:
    mode = (mode or "seeded").strip().lower()
    if keep_largest_component:
        mode = "largest"
    if mode in {"none", "off", "disabled"}:
        return (mask_volume > 0).astype(np.uint8)
    if mode not in {"seeded", "largest", "largest_n", "size"}:
        raise HTTPException(
            status_code=400,
            detail="connected_component_mode must be one of: seeded, largest, largest_n, size, none",
        )

    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="SimpleITK is required for connected component cleanup") from exc

    binary = (mask_volume > 0).astype(np.uint8, copy=False)
    if not np.any(binary):
        return binary

    image = sitk.GetImageFromArray(binary)
    components_image = sitk.ConnectedComponent(image, False)
    components = sitk.GetArrayFromImage(components_image).astype(np.int32, copy=False)
    component_ids, counts = np.unique(components[components > 0], return_counts=True)
    if component_ids.size == 0:
        return binary

    min_voxels = max(0, int(min_voxels))
    max_components = max(1, int(max_components))
    sizes = {int(component_id): int(count) for component_id, count in zip(component_ids, counts)}
    keep_ids: set[int] = set()

    if mode == "seeded":
        seeds = (seed_volume > 0) if seed_volume is not None else np.zeros_like(binary, dtype=bool)
        seed_component_ids = np.unique(components[seeds & (components > 0)])
        keep_ids.update(int(component_id) for component_id in seed_component_ids if sizes.get(int(component_id), 0) >= min_voxels)
        # Hard constraint: never delete the component touched by a user seed just
        # because it is small; small seeded lesions must survive cleanup.
        keep_ids.update(int(component_id) for component_id in seed_component_ids)
        if not keep_ids:
            sorted_ids = sorted(sizes, key=lambda component_id: sizes[component_id], reverse=True)
            keep_ids.update(component_id for component_id in sorted_ids[:max_components] if sizes[component_id] >= min_voxels)
    elif mode == "largest":
        largest_id = max(sizes, key=sizes.get)
        keep_ids.add(largest_id)
    elif mode == "largest_n":
        sorted_ids = sorted(sizes, key=lambda component_id: sizes[component_id], reverse=True)
        keep_ids.update(component_id for component_id in sorted_ids[:max_components] if sizes[component_id] >= min_voxels)
    else:
        keep_ids.update(component_id for component_id, size in sizes.items() if size >= min_voxels)

    if not keep_ids:
        return binary
    filtered = np.isin(components, list(keep_ids)).astype(np.uint8)
    if seed_volume is not None and np.any(seed_volume):
        filtered = np.maximum(filtered, (seed_volume > 0).astype(np.uint8))
    return filtered


def _propagate_sparse_slices(
    sparse_slices: dict[int, np.ndarray],
    volume_array: np.ndarray,
    spacing: tuple[float, float, float],
    fill_holes: bool,
    keep_largest_component: bool,
    image_guidance: bool,
    hu_margin: float | None,
    closing_radius: int,
) -> np.ndarray:
    annotated_slices = sorted(sparse_slices)
    if not annotated_slices:
        raise HTTPException(status_code=404, detail="No annotated slices found for propagation")

    depth, height, width = volume_array.shape[:3]
    spacing_x = float(spacing[0]) if len(spacing) > 0 else 1.0
    spacing_y = float(spacing[1]) if len(spacing) > 1 else 1.0
    spacing_z = float(spacing[2]) if len(spacing) > 2 else 1.0
    hu_range = _foreground_hu_range(volume_array, sparse_slices, hu_margin) if image_guidance else None
    distances = {
        slice_index: _signed_distance_slice((sparse_slices[slice_index] > 0).astype(np.uint8), (spacing_x, spacing_y))
        for slice_index in annotated_slices
    }
    propagated = np.zeros((depth, height, width), dtype=np.uint8)

    for z in range(depth):
        if z in sparse_slices:
            propagated[z] = (sparse_slices[z] > 0).astype(np.uint8)
            continue
        if z < annotated_slices[0]:
            reference_z = annotated_slices[0]
            distance = distances[reference_z] - abs(z - reference_z) * spacing_z
        elif z > annotated_slices[-1]:
            reference_z = annotated_slices[-1]
            distance = distances[reference_z] - abs(z - reference_z) * spacing_z
        else:
            upper_position = next(index for index, value in enumerate(annotated_slices) if value > z)
            z0 = annotated_slices[upper_position - 1]
            z1 = annotated_slices[upper_position]
            physical_z0 = z0 * spacing_z
            physical_z1 = z1 * spacing_z
            weight = (z * spacing_z - physical_z0) / max(1e-6, physical_z1 - physical_z0)
            distance = (1.0 - weight) * distances[z0] + weight * distances[z1]
        candidate = (distance > 0).astype(np.uint8)
        propagated[z] = _apply_image_guidance(candidate, volume_array[z], hu_range)

    for z in range(depth):
        if z not in sparse_slices:
            propagated[z] = _cleanup_binary_slice(
                propagated[z],
                fill_holes=fill_holes,
                keep_largest_component=keep_largest_component,
                closing_radius=closing_radius,
            )

    # Hard constraint: user-confirmed sparse slices must not be changed by propagation.
    for z, slice_mask in sparse_slices.items():
        propagated[z] = (slice_mask > 0).astype(np.uint8)

    return propagated


def label_propagate(request: LabelPropagationRequest) -> LabelPropagationResponse:
    image_record, volume = load_volume(request.image_id)
    if image_record.get("case_id") != request.case_id:
        raise HTTPException(
            status_code=400,
            detail=f"Image {request.image_id} does not belong to case {request.case_id}",
        )
    supported_methods = {"signed_distance", "image_guided_distance", "random_walker"}
    if request.method not in supported_methods:
        raise HTTPException(
            status_code=400,
            detail=f"Current V1 label propagation supports {sorted(supported_methods)}",
        )

    source_version = request.source_version.strip()
    output_version = request.output_version.strip()
    if source_version not in VALID_MASK_VERSIONS or output_version not in VALID_MASK_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported version. Use one of {sorted(VALID_MASK_VERSIONS)}",
        )

    label = _normalize_label(request.label)
    output_label_type = _normalize_label_type(request.label_type, default="pseudo")
    label_id = int(request.label_id) if request.label_id is not None else None
    depth, height, width = volume.array.shape[:3]
    masks = _load_masks()
    match_any = bool(request.match_any_label or label_id is not None or label in {"*", "all", "multiclass"})
    json_records = _json_mask_records(
        masks,
        request.case_id,
        request.image_id,
        source_version,
        label,
        match_any_label=match_any,
    )
    if not json_records and match_any:
        # Fall back to exact label match if any-label found nothing unexpected
        json_records = _json_mask_records(masks, request.case_id, request.image_id, source_version, label)
    if not json_records:
        raise HTTPException(status_code=404, detail="No saved sparse JSON masks found for label propagation")

    sparse_slices_by_axis, source_mask_ids = _load_sparse_axis_masks(json_records, depth, height, width)
    if label_id is not None and label_id > 0:
        for axis_name, axis_slices in sparse_slices_by_axis.items():
            for slice_index, axis_mask in list(axis_slices.items()):
                filtered = (axis_mask == label_id).astype(np.uint8)
                if np.any(filtered):
                    axis_slices[slice_index] = filtered
                else:
                    del axis_slices[slice_index]
    if not any(sparse_slices_by_axis.values()):
        raise HTTPException(status_code=404, detail="No readable sparse masks found for label propagation")

    propagated = np.zeros((depth, height, width), dtype=np.uint8)
    for axis in ("axial", "coronal", "sagittal"):
        sparse_slices = sparse_slices_by_axis.get(axis) or {}
        if not sparse_slices:
            continue
        axis_volume = _axis_volume_array(volume.array, axis)
        axis_result = _propagate_sparse_slices(
            sparse_slices=sparse_slices,
            volume_array=axis_volume,
            spacing=_axis_spacing(tuple(float(value) for value in volume.spacing), axis),
            fill_holes=request.fill_holes,
            keep_largest_component=request.keep_largest_component,
            image_guidance=request.image_guidance or request.method == "image_guided_distance",
            hu_margin=request.hu_margin,
            closing_radius=max(0, int(request.closing_radius)),
        )
        if request.method == "random_walker":
            positive_slices = _point_prompt_slices(request.positive_points, axis, axis_result.shape[:3])
            negative_slices = _point_prompt_slices(request.negative_points, axis, axis_result.shape[:3])
            axis_result = _refine_with_random_walker(
                candidate_volume=axis_result,
                volume_array=axis_volume,
                sparse_slices=sparse_slices,
                positive_slices=positive_slices,
                negative_slices=negative_slices,
                fill_holes=request.fill_holes,
                keep_largest_component=request.keep_largest_component,
                closing_radius=max(0, int(request.closing_radius)),
                beta=request.random_walker_beta,
                roi_margin=request.random_walker_roi_margin,
                max_nodes=request.random_walker_max_nodes,
            )
        else:
            positive_slices = {}
            negative_slices = {}
        axis_seed_volume = _seed_volume_from_sparse_slices(sparse_slices, axis_result.shape[:3])
        axis_result = _connected_component_filter_volume(
            mask_volume=axis_result,
            seed_volume=axis_seed_volume,
            mode=request.connected_component_mode,
            min_voxels=request.connected_component_min_voxels,
            max_components=request.connected_component_max_components,
            keep_largest_component=request.keep_largest_component,
        )
        for slice_index, slice_mask in negative_slices.items():
            axis_result[slice_index][slice_mask > 0] = 0
        for slice_index, slice_mask in positive_slices.items():
            axis_result[slice_index] = np.maximum(axis_result[slice_index], (slice_mask > 0).astype(np.uint8))
        for slice_index, slice_mask in negative_slices.items():
            axis_result[slice_index][slice_mask > 0] = 0
        propagated = np.maximum(propagated, _axis_result_to_volume(axis_result, axis))
    if label_id is not None and label_id > 0:
        propagated = (propagated > 0).astype(np.uint8) * np.uint8(label_id)
    if request.method == "random_walker":
        encoding = "label_propagation_random_walker_graph"
    elif request.image_guidance or request.method == "image_guided_distance":
        encoding = "label_propagation_image_guided_distance"
    else:
        encoding = "label_propagation_signed_distance"
    mask, mask_path = _append_3d_mask_record(
        masks=masks,
        request_case_id=request.case_id,
        image_id=request.image_id,
        version=output_version,
        label=label,
        encoding=encoding,
        source_mask_ids=source_mask_ids,
        mask_stack=propagated,
        volume=volume,
        label_type=output_label_type,
        label_id=label_id,
    )
    return LabelPropagationResponse(
        success=True,
        mask_id=mask.mask_id,
        path=mask_path,
        method=request.method,
        source_mask_ids=source_mask_ids,
        annotated_slices=_annotated_slice_summary(sparse_slices_by_axis),
        propagated_slices=depth,
        shape=[depth, height, width],
        spacing=[float(value) for value in volume.spacing],
        origin=[float(value) for value in volume.origin],
        direction=[float(value) for value in volume.direction],
        mask=mask,
        label_type=output_label_type,
    )


def _latest_mask_record(image_id: str, version: str) -> dict | None:
    candidates = [
        mask
        for mask in _load_masks()
        if mask.get("image_id") == image_id and mask.get("version") == version
    ]
    candidates.sort(key=lambda item: str(item.get("create_time") or ""))
    return candidates[-1] if candidates else None


def _deepedit_payload(request: DeepEditRefineRequest, current_mask: dict | None) -> dict[str, Any]:
    image = _image_record(request.image_id)
    return {
        "case_id": request.case_id,
        "image_id": request.image_id,
        "image_path": image.get("path"),
        "current_mask_id": (request.current_mask_id or current_mask.get("mask_id")) if current_mask else request.current_mask_id,
        "current_mask_path": current_mask.get("path") if current_mask else None,
        "label": request.label,
        "model_id": request.model_id,
        "positive_points": request.positive_points,
        "negative_points": request.negative_points,
        "scribbles": request.scribbles,
        "interaction": request.interaction,
        "confirmed_slices": request.confirmed_slices,
        "output_version": request.output_version,
    }


def _post_json_service(url: str, payload: dict[str, Any], timeout_seconds: float, service_name: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(
        url.rstrip("/") + "/infer",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"{service_name} service request failed: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail=f"{service_name} service response must be a JSON object")
    return data


def _call_deepedit_service(request: DeepEditRefineRequest, current_mask: dict | None) -> dict[str, Any] | None:
    if not DEEPEDIT_SERVICE_URL:
        return None
    try:
        return _post_json_service(
            DEEPEDIT_SERVICE_URL,
            _deepedit_payload(request, current_mask),
            DEEPEDIT_SERVICE_TIMEOUT_SECONDS,
            "DeepEdit",
        )
    except HTTPException as exc:
        # Service down / timeout / bad payload → fall back to random_walker instead of hard-failing refine.
        if exc.status_code in {502, 503, 504}:
            return {
                "success": False,
                "model_status": "service_unavailable",
                "message": str(exc.detail),
            }
        raise


def _remote_refinement_response(
    request: DeepEditRefineRequest,
    remote_result: dict[str, Any],
    method: str,
    status: str,
    default_message: str,
) -> DeepEditRefineResponse | None:
    if not remote_result or remote_result.get("success") is False:
        return None
    if remote_result.get("mask_id"):
        mask_id = str(remote_result["mask_id"])
        mask = get_mask(mask_id)
        source_mask_ids = [request.current_mask_id] if request.current_mask_id else []
    elif remote_result.get("mask_base64"):
        image_record, volume = load_volume(request.image_id)
        if image_record.get("case_id") != request.case_id:
            raise HTTPException(
                status_code=400,
                detail=f"Image {request.image_id} does not belong to case {request.case_id}",
            )
        label = _normalize_label(request.label)
        mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
        mask_path = _mask_path(
            case_id=request.case_id,
            image_id=request.image_id,
            mask_id=mask_id,
            version=request.output_version,
            label=label,
            mask_format="nii.gz",
        )
        target = PROJECT_ROOT / mask_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(base64.b64decode(str(remote_result["mask_base64"])))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="DeepEdit service returned invalid mask_base64") from exc

        shape = remote_result.get("shape")
        if not isinstance(shape, list) or len(shape) != 3:
            shape = list(volume.array.shape[:3])
        source_mask_ids = [request.current_mask_id] if request.current_mask_id else []
        record = {
            "mask_id": mask_id,
            "annotation_id": None,
            "case_id": request.case_id,
            "image_id": request.image_id,
            "path": mask_path,
            "version": request.output_version,
            "label": label,
            "mask_format": "nii.gz",
            "slice_index": None,
            "width": int(shape[2]),
            "height": int(shape[1]),
            "encoding": "deepedit_neural_network",
            "create_time": _now_iso(),
            "source_mask_ids": source_mask_ids,
            "shape": [int(value) for value in shape],
            "spacing": remote_result.get("spacing") or [float(value) for value in volume.spacing],
            "origin": remote_result.get("origin") or [float(value) for value in volume.origin],
            "direction": remote_result.get("direction") or [float(value) for value in volume.direction],
        }
        upsert_record("masks", record)
        mask = MaskRecord(**record)
    else:
        return None
    response_shape = list(remote_result.get("shape") or [])
    propagated_slices = int(response_shape[0]) if response_shape else int(mask.height or 0)
    return DeepEditRefineResponse(
        success=True,
        mask_id=mask.mask_id,
        path=mask.path,
        method=method,
        source_mask_ids=source_mask_ids,
        annotated_slices=sorted(set(int(value) for value in request.confirmed_slices)),
        propagated_slices=propagated_slices,
        shape=response_shape,
        spacing=list(remote_result.get("spacing") or []),
        origin=list(remote_result.get("origin") or []),
        direction=list(remote_result.get("direction") or []),
        mask=mask,
        refinement_mode=method,
        model_status=status,
        model_message=str(remote_result.get("message") or default_message),
    )


def deepedit_refine(request: DeepEditRefineRequest) -> DeepEditRefineResponse:
    current_mask = None
    if request.current_mask_id:
        current_mask = next((item for item in _load_masks() if item.get("mask_id") == request.current_mask_id), None)
        if current_mask is None:
            raise HTTPException(status_code=404, detail=f"Current mask not found: {request.current_mask_id}")
    else:
        current_mask = _latest_mask_record(request.image_id, request.current_mask_version)

    remote_result = _call_deepedit_service(request, current_mask)
    response = _remote_refinement_response(
        request,
        remote_result or {},
        method="deepedit_neural_network",
        status="remote_model",
        default_message="DeepEdit service returned mask_id",
    )
    if response is not None:
        return response

    remote_status = ""
    remote_message = ""
    if isinstance(remote_result, dict):
        remote_status = str(remote_result.get("model_status") or "")
        remote_message = str(remote_result.get("message") or "")

    if request.require_neural:
        if not DEEPEDIT_SERVICE_URL:
            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepEdit neural service is not configured (DEEPEDIT_SERVICE_URL). "
                    "Start the DeepEdit service, or use「图割修正」(/api/label_propagate) instead."
                ),
            )
        detail = remote_message or remote_status or "DeepEdit service did not return a usable mask"
        raise HTTPException(
            status_code=503,
            detail=(
                f"DeepEdit neural refine unavailable: {detail}. "
                "Check the DeepEdit service /health and weights, or use「图割修正」."
            ),
        )

    positive_points = list(request.positive_points or [])
    negative_points = list(request.negative_points or [])
    positive_points.extend(_scribble_prompt_points(request.scribbles, "positive"))
    negative_points.extend(_scribble_prompt_points(request.scribbles, "negative"))

    propagation = label_propagate(
        LabelPropagationRequest(
            case_id=request.case_id,
            image_id=request.image_id,
            source_version=request.source_version,
            output_version=request.output_version,
            label=request.label,
            label_type="pseudo",
            method="random_walker",
            fill_holes=True,
            keep_largest_component=False,
            image_guidance=True,
            closing_radius=1,
            random_walker_beta=request.random_walker_beta,
            random_walker_roi_margin=request.random_walker_roi_margin,
            connected_component_mode="seeded",
            connected_component_min_voxels=request.connected_component_min_voxels,
            connected_component_max_components=8,
            positive_points=positive_points,
            negative_points=negative_points,
        )
    )
    return DeepEditRefineResponse(
        **propagation.model_dump(),
        refinement_mode="deepedit_fallback_random_walker",
        model_status="fallback_no_deepedit_model",
        model_message=(
            remote_message
            or "DeepEdit neural path unavailable; used graph-based random_walker "
            "(require_neural=false). Prefer「图割修正」for this mode."
        ),
    )


def compare_masks(pred_mask_id: str, ref_mask_id: str, *, include_hd95: bool = True) -> dict[str, Any]:
    """Compute Dice / IoU / volume diff (and optional HD95) between two 3D NIfTI masks."""
    pred_record, pred_image, pred = _read_nifti_mask_array(pred_mask_id)
    ref_record, ref_image, ref = _read_nifti_mask_array(ref_mask_id)
    if pred.shape != ref.shape:
        raise HTTPException(
            status_code=400,
            detail=f"Mask shape mismatch: pred={pred.shape}, ref={ref.shape}",
        )
    spacing = [float(value) for value in pred_image.GetSpacing()[:3]]
    voxel_ml = float(spacing[0] * spacing[1] * spacing[2]) / 1000.0
    pred_bin = pred > 0
    ref_bin = ref > 0
    intersection = int(np.count_nonzero(pred_bin & ref_bin))
    pred_count = int(np.count_nonzero(pred_bin))
    ref_count = int(np.count_nonzero(ref_bin))
    union = pred_count + ref_count - intersection
    dice = (2.0 * intersection / (pred_count + ref_count)) if (pred_count + ref_count) else 1.0
    iou = (intersection / union) if union else 1.0
    precision = (intersection / pred_count) if pred_count else 0.0
    recall = (intersection / ref_count) if ref_count else 0.0
    volume_diff_voxels = pred_count - ref_count
    hd95 = _hausdorff_distance_95(pred_bin, ref_bin, spacing) if include_hd95 else None
    return {
        "success": True,
        "pred_mask_id": pred_mask_id,
        "ref_mask_id": ref_mask_id,
        "pred_version": pred_record.get("version"),
        "ref_version": ref_record.get("version"),
        "shape": [int(value) for value in pred.shape],
        "pred_voxels": pred_count,
        "ref_voxels": ref_count,
        "intersection": intersection,
        "dice": round(float(dice), 6),
        "iou": round(float(iou), 6),
        "precision": round(float(precision), 6),
        "recall": round(float(recall), 6),
        "volume_diff_voxels": int(volume_diff_voxels),
        "volume_diff_ml": round(float(volume_diff_voxels) * voxel_ml, 6),
        "pred_volume_ml": round(float(pred_count) * voxel_ml, 6),
        "ref_volume_ml": round(float(ref_count) * voxel_ml, 6),
        "hd95_mm": None if hd95 is None else round(float(hd95), 6),
        "spacing": spacing,
    }


def _hausdorff_distance_95(pred: np.ndarray, ref: np.ndarray, spacing: list[float]) -> float | None:
    """Approximate bidirectional HD95 (mm) using surface distance transforms."""
    if not np.any(pred) and not np.any(ref):
        return 0.0
    if not np.any(pred) or not np.any(ref):
        return None
    try:
        from scipy import ndimage as ndi
    except ModuleNotFoundError:
        return None

    spacing_zyx = np.asarray([spacing[2], spacing[1], spacing[0]], dtype=np.float64)

    def surface(mask: np.ndarray) -> np.ndarray:
        eroded = ndi.binary_erosion(mask, structure=np.ones((3, 3, 3), dtype=bool), border_value=0)
        return mask & ~eroded

    pred_surface = surface(pred)
    ref_surface = surface(ref)
    if not np.any(pred_surface):
        pred_surface = pred
    if not np.any(ref_surface):
        ref_surface = ref

    dt_ref = ndi.distance_transform_edt(~ref_surface, sampling=spacing_zyx)
    dt_pred = ndi.distance_transform_edt(~pred_surface, sampling=spacing_zyx)
    d_pred_to_ref = dt_ref[pred_surface]
    d_ref_to_pred = dt_pred[ref_surface]
    if d_pred_to_ref.size == 0 and d_ref_to_pred.size == 0:
        return 0.0
    distances = np.concatenate([d_pred_to_ref.ravel(), d_ref_to_pred.ravel()])
    return float(np.percentile(distances, 95))


def _error_slices(pred: np.ndarray, ref: np.ndarray, *, top_k: int = 8) -> list[dict[str, Any]]:
    pred_bin = pred > 0
    ref_bin = ref > 0
    xor = np.logical_xor(pred_bin, ref_bin)
    if not np.any(xor):
        return []
    per_slice = np.count_nonzero(xor, axis=(1, 2))
    ranked = np.argsort(per_slice)[::-1]
    results: list[dict[str, Any]] = []
    for index in ranked:
        error_voxels = int(per_slice[index])
        if error_voxels <= 0:
            break
        results.append(
            {
                "axis": "axial",
                "slice_index": int(index),
                "error_voxels": error_voxels,
                "pred_voxels": int(np.count_nonzero(pred_bin[index])),
                "ref_voxels": int(np.count_nonzero(ref_bin[index])),
            }
        )
        if len(results) >= top_k:
            break
    return results


def get_mask_metrics(mask_id: str, ref_mask_id: str | None = None, *, error_slice_top_k: int = 8) -> dict[str, Any]:
    geometric = get_mask_quality_summary(mask_id)
    payload: dict[str, Any] = {
        "success": True,
        "mask_id": mask_id,
        "ref_mask_id": ref_mask_id,
        "version": geometric.get("version"),
        "label": geometric.get("label"),
        "geometric": {
            "voxel_count": geometric.get("voxel_count"),
            "volume_ml": geometric.get("volume_ml"),
            "connected_component_count": geometric.get("connected_component_count"),
            "largest_component_voxels": geometric.get("largest_component_voxels"),
            "largest_component_ratio": geometric.get("largest_component_ratio"),
            "slice_range": geometric.get("slice_range"),
            "dimensions": geometric.get("dimensions"),
            "spacing": geometric.get("spacing"),
        },
        "overlap": None,
        "error_slices": [],
    }
    if not ref_mask_id:
        return payload

    overlap = compare_masks(mask_id, ref_mask_id, include_hd95=True)
    pred_record, _, pred = _read_nifti_mask_array(mask_id)
    _, _, ref = _read_nifti_mask_array(ref_mask_id)
    payload["overlap"] = {
        "dice": overlap["dice"],
        "iou": overlap["iou"],
        "precision": overlap["precision"],
        "recall": overlap["recall"],
        "hd95_mm": overlap.get("hd95_mm"),
        "volume_diff_voxels": overlap.get("volume_diff_voxels"),
        "volume_diff_ml": overlap.get("volume_diff_ml"),
        "pred_voxels": overlap.get("pred_voxels"),
        "ref_voxels": overlap.get("ref_voxels"),
        "pred_version": pred_record.get("version"),
        "ref_version": overlap.get("ref_version"),
    }
    payload["error_slices"] = _error_slices(pred, ref, top_k=error_slice_top_k)
    return payload


def rollback_mask(mask_id: str, user: dict | None = None) -> dict[str, Any]:
    """Copy an existing 3D NIfTI mask as a new v3_preview version (rollback / restore)."""
    ensure_project_dirs()
    masks = _load_masks()
    source = next((item for item in masks if item.get("mask_id") == mask_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Mask not found: {mask_id}")
    if not (source.get("mask_format") == "nii.gz" or str(source.get("path") or "").endswith(".nii.gz")):
        raise HTTPException(status_code=400, detail="Only 3D NIfTI masks can be rolled back to v3_preview")

    source_path = PROJECT_ROOT / str(source.get("path") or "")
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source mask file not found: {source.get('path')}")

    target_version = "v3_preview"
    new_mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
    label = _normalize_label(str(source.get("label") or "label"))
    new_path = _mask_path(
        case_id=str(source.get("case_id")),
        image_id=str(source.get("image_id")),
        mask_id=new_mask_id,
        version=target_version,
        label=label,
        mask_format="nii.gz",
    )
    target_path = PROJECT_ROOT / new_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)

    record = {
        "mask_id": new_mask_id,
        "annotation_id": source.get("annotation_id"),
        "case_id": source.get("case_id"),
        "image_id": source.get("image_id"),
        "path": new_path,
        "version": target_version,
        "label": label,
        "label_type": source.get("label_type") or "pseudo",
        "mask_format": "nii.gz",
        "slice_index": None,
        "width": source.get("width"),
        "height": source.get("height"),
        "encoding": f"rollback_from_{mask_id}",
        "create_time": _now_iso(),
        "source_mask_ids": [mask_id],
        "shape": source.get("shape"),
        "spacing": source.get("spacing"),
        "origin": source.get("origin"),
        "direction": source.get("direction"),
    }
    upsert_record("masks", record)

    from backend.app.services.version_service import save_version
    from backend.app.schemas.version import SaveVersionRequest
    from backend.app.services.workflow_service import append_audit_log

    save_version(
        SaveVersionRequest(
            case_id=str(source.get("case_id")),
            version=target_version,
            annotation=new_mask_id,
            model=f"rollback_from:{mask_id}",
            dataset=None,
        )
    )
    append_audit_log(
        action="rollback_mask",
        user=user,
        entity_type="mask",
        entity_id=new_mask_id,
        case_id=str(source.get("case_id")),
        detail={"from_mask": mask_id, "from_version": source.get("version"), "to_version": target_version},
    )
    mask = MaskRecord(**record)
    return {
        "success": True,
        "mask_id": new_mask_id,
        "path": new_path,
        "source_mask_id": mask_id,
        "version": target_version,
        "mask": mask,
        "message": f"rolled back {mask_id} ({source.get('version')}) → {new_mask_id} (v3_preview)",
    }


def find_promotable_mask_for_case(case_id: str) -> dict[str, Any] | None:
    priority = {"v3_fusion": 3, "v3_preview": 2}
    candidates = [
        item
        for item in _load_masks()
        if item.get("case_id") == case_id
        and item.get("version") in priority
        and (item.get("mask_format") == "nii.gz" or str(item.get("path") or "").endswith(".nii.gz"))
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            priority.get(str(item.get("version")), 0),
            str(item.get("create_time") or ""),
        ),
        reverse=True,
    )
    return candidates[0]


def _slice_binary_iou(a: np.ndarray, b: np.ndarray) -> float:
    a_bin = a > 0
    b_bin = b > 0
    inter = int(np.count_nonzero(a_bin & b_bin))
    union = int(np.count_nonzero(a_bin | b_bin))
    if union == 0:
        return 1.0
    return float(inter / union)


def _slice_component_count(slice_mask: np.ndarray) -> int:
    try:
        from scipy import ndimage as ndi
    except ModuleNotFoundError:
        return int(np.count_nonzero(slice_mask) > 0)
    labeled, count = ndi.label(slice_mask > 0)
    return int(count)


def _binary_entropy_proxy(p: float) -> float:
    p = float(min(max(p, 1e-6), 1.0 - 1e-6))
    return float(-(p * np.log2(p) + (1.0 - p) * np.log2(1.0 - p)))


def get_labeling_assist(
    image_id: str,
    *,
    label: str = "label",
    axis: str = "axial",
    top_k: int = 5,
    min_slices: int = 3,
    source_version: str = "v1_manual",
    preview_mask_id: str | None = None,
) -> dict[str, Any]:
    """Few-shot workload + lightweight active-learning slice recommendations."""
    from backend.app.schemas.mask import ActiveLearningSliceItem, LabelingAssistResponse, LabelingWorkload

    axis = _normalize_axis(axis)
    label = _normalize_label(label)
    top_k = max(1, min(int(top_k), 20))
    min_slices = max(1, min(int(min_slices), 20))

    image_record, volume = load_volume(image_id)
    axis_volume = _axis_volume_array(volume.array, axis)
    total_slices = int(axis_volume.shape[0])
    case_id = str(image_record.get("case_id") or "")

    masks = _load_masks()
    json_records = _json_mask_records(masks, case_id, image_id, source_version, label)
    sparse_by_axis, _ = _load_sparse_axis_masks(json_records, *volume.array.shape[:3])
    labeled = sorted(int(index) for index in (sparse_by_axis.get(axis) or {}).keys())
    labeled_set = set(labeled)

    preview_record = None
    if preview_mask_id:
        preview_record = next((item for item in masks if item.get("mask_id") == preview_mask_id), None)
    if preview_record is None:
        for version in ("v3_preview", "v3_fusion", "v2_ai", "final"):
            preview_record = _latest_mask_record(image_id, version)
            if preview_record is not None:
                break

    preview_axis = None
    has_preview = False
    preview_id = None
    if preview_record is not None and (
        preview_record.get("mask_format") == "nii.gz" or str(preview_record.get("path") or "").endswith(".nii.gz")
    ):
        try:
            _, _, preview_stack = _read_nifti_mask_array(str(preview_record["mask_id"]))
            preview_axis = _axis_volume_array(preview_stack, axis)
            has_preview = True
            preview_id = str(preview_record["mask_id"])
        except Exception:
            preview_axis = None

    recommendations: list[ActiveLearningSliceItem] = []
    if has_preview and preview_axis is not None:
        scores: list[tuple[float, ActiveLearningSliceItem]] = []
        for slice_index in range(total_slices):
            if slice_index in labeled_set:
                continue
            slice_mask = preview_axis[slice_index]
            area = int(np.count_nonzero(slice_mask))
            components = _slice_component_count(slice_mask)
            iou_prev = _slice_binary_iou(preview_axis[slice_index - 1], slice_mask) if slice_index > 0 else None
            iou_next = (
                _slice_binary_iou(slice_mask, preview_axis[slice_index + 1]) if slice_index + 1 < total_slices else None
            )
            instability = 0.0
            if iou_prev is not None:
                instability += 1.0 - iou_prev
            if iou_next is not None:
                instability += 1.0 - iou_next
            if iou_prev is not None and iou_next is not None:
                instability *= 0.5
            # Neighbor disagreement as soft probability proxy → binary entropy.
            disagreement = instability
            entropy = _binary_entropy_proxy(0.5 * disagreement) if disagreement > 0 else 0.0
            component_score = min(1.0, components / 4.0)
            area_norm = min(1.0, area / max(1.0, float(slice_mask.size) * 0.05))
            score = 0.55 * instability + 0.25 * entropy + 0.15 * component_score + 0.05 * area_norm
            if area == 0 and (iou_prev or 0) < 0.05 and (iou_next or 0) < 0.05:
                score *= 0.15
            reason = "boundary_instability" if instability >= 0.25 else ("multi_component" if components > 1 else "coverage_gap")
            scores.append(
                (
                    score,
                    ActiveLearningSliceItem(
                        slice_index=slice_index,
                        score=round(float(score), 4),
                        reason=reason,
                        components=components,
                        area=area,
                        iou_prev=None if iou_prev is None else round(float(iou_prev), 4),
                        iou_next=None if iou_next is None else round(float(iou_next), 4),
                        entropy=round(float(entropy), 4),
                    ),
                )
            )
        scores.sort(key=lambda item: item[0], reverse=True)
        recommendations = [item for _, item in scores[:top_k]]
    else:
        # No preview yet: recommend midpoints of largest unlabeled gaps (or evenly spaced).
        gap_candidates: list[tuple[int, int]] = []
        if not labeled:
            step = max(1, total_slices // max(min_slices + 1, 2))
            for index in range(step, total_slices - 1, step):
                gap_candidates.append((index, step))
        else:
            anchors = [-1, *labeled, total_slices]
            for left, right in zip(anchors, anchors[1:]):
                gap = right - left
                if gap <= 1:
                    continue
                mid = (left + right) // 2
                if mid not in labeled_set and 0 <= mid < total_slices:
                    gap_candidates.append((mid, gap))
        gap_candidates.sort(key=lambda item: item[1], reverse=True)
        for slice_index, gap in gap_candidates[:top_k]:
            recommendations.append(
                ActiveLearningSliceItem(
                    slice_index=slice_index,
                    score=round(min(1.0, gap / max(total_slices, 1)), 4),
                    reason="largest_gap",
                    components=0,
                    area=0,
                )
            )

    labeled_count = len(labeled)
    remaining_to_min = max(0, min_slices - labeled_count)
    # Heuristic: dense labeling often needs ~12–15% of slices; few-shot stops near min_slices.
    dense_target = max(min_slices, int(round(total_slices * 0.12)))
    estimated_remaining_dense = max(0, dense_target - labeled_count)
    workload = LabelingWorkload(
        labeled_slices=labeled,
        labeled_count=labeled_count,
        total_slices=total_slices,
        min_recommended=min_slices,
        remaining_to_min=remaining_to_min,
        estimated_remaining_dense=estimated_remaining_dense,
        coverage_ratio=round(labeled_count / total_slices, 4) if total_slices else 0.0,
    )
    response = LabelingAssistResponse(
        success=True,
        image_id=image_id,
        case_id=case_id or None,
        axis=axis,
        label=label,
        workload=workload,
        recommendations=recommendations,
        ready_for_propagate=labeled_count >= min_slices,
        has_preview=has_preview,
        preview_mask_id=preview_id,
    )
    return response.model_dump()
