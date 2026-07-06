from __future__ import annotations

import json
import re
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
)
from backend.app.services.file_service import (
    path_for_api,
)
from backend.app.services.medical_image_service import load_volume
from backend.app.services.sqlite_service import get_record, list_records, next_sqlite_entity_id, upsert_record


VALID_MASK_VERSIONS = {"v1_manual", "v2_ai", "v3_fusion", "final"}
VALID_MASK_FORMATS = {"nii.gz", "json"}
VALID_SLICE_AXES = {"axial", "coronal", "sagittal"}


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


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
) -> list[dict]:
    records = [
        mask
        for mask in masks
        if mask.get("case_id") == case_id
        and mask.get("image_id") == image_id
        and mask.get("version") == version
        and mask.get("label") == label
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
    binary = (axis_mask > 0).astype(np.uint8, copy=False)
    if axis == "axial":
        mask_stack[slice_index] = np.maximum(mask_stack[slice_index], binary)
        return
    if axis == "coronal":
        mask_stack[:, slice_index, :] = np.maximum(mask_stack[:, slice_index, :], binary)
        return
    if axis == "sagittal":
        mask_stack[:, :, slice_index] = np.maximum(mask_stack[:, :, slice_index], binary)
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


def _downsample_mask_volume(array: np.ndarray, max_dim: int) -> tuple[np.ndarray, tuple[int, int, int]]:
    max_dim = max(64, min(max_dim, 192))
    depth, height, width = array.shape[:3]
    stride_z = max(1, int(np.ceil(depth / max_dim)))
    stride_y = max(1, int(np.ceil(height / max_dim)))
    stride_x = max(1, int(np.ceil(width / max_dim)))
    binary = (array > 0).astype(np.uint8, copy=False)
    if stride_z == stride_y == stride_x == 1:
        return binary, (stride_z, stride_y, stride_x)

    out_depth = int(np.ceil(depth / stride_z))
    out_height = int(np.ceil(height / stride_y))
    out_width = int(np.ceil(width / stride_x))
    padded_shape = (out_depth * stride_z, out_height * stride_y, out_width * stride_x)
    padded = np.zeros(padded_shape, dtype=np.uint8)
    padded[:depth, :height, :width] = binary
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
    values = (array > 0).astype(np.uint8)
    downsampled, strides = _downsample_mask_volume(values, max_dim=max_dim)
    texture_values = (downsampled > 0).astype(np.uint8) * 255
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
        "dimensions": [width, height, depth],
        "spacing": [spacing[0] * stride_x, spacing[1] * stride_y, spacing[2] * stride_z],
        "origin": [float(value) for value in image.GetOrigin()[:3]],
        "direction": [float(value) for value in image.GetDirection()],
        "scalar_type": "uint8",
        "downsample_stride": [stride_z, stride_y, stride_x],
        "mask_voxel_count": int(np.count_nonzero(downsampled)),
        "values_base64": base64.b64encode(np.ascontiguousarray(texture_values).tobytes(order="C")).decode("ascii"),
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


def save_mask(request: SaveMaskRequest) -> SaveMaskResponse:
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

    mask_id = next_sqlite_entity_id("Mask", "masks", "mask_id")
    label = _normalize_label(request.label)
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
        "annotation_id": request.annotation_id,
        "case_id": request.case_id,
        "image_id": request.image_id,
        "path": mask_path,
        "version": version,
        "label": label,
        "mask_format": mask_format,
        "axis": _normalize_axis(request.axis) if mask_format == "json" else None,
        "slice_index": request.slice_index,
        "width": request.width,
        "height": request.height,
        "encoding": request.encoding,
        "create_time": _now_iso(),
    }
    upsert_record("masks", record)

    mask = MaskRecord(**record)
    return SaveMaskResponse(success=True, mask_id=mask_id, path=mask_path, mask=mask)


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
    return [
        MaskRecord(**mask)
        for mask in masks
        if mask.get("image_id") == image_id or mask.get("image") == image_id
    ]


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
    depth, height, width = volume.array.shape[:3]
    mask_stack = np.zeros((depth, height, width), dtype=np.uint8)

    masks = _load_masks()
    json_records = _json_mask_records(masks, request.case_id, request.image_id, version, label)
    if not json_records:
        raise HTTPException(status_code=404, detail="No saved JSON slice masks found for this image/version/label")

    sparse_slices_by_axis, source_mask_ids = _load_sparse_axis_masks(json_records, depth, height, width)
    if not any(sparse_slices_by_axis.values()):
        raise HTTPException(status_code=404, detail="No readable JSON slice masks found")
    for axis, sparse_slices in sparse_slices_by_axis.items():
        for slice_index, slice_mask in sparse_slices.items():
            _merge_axis_slice_into_volume(mask_stack, axis, slice_index, slice_mask)

    mask, mask_path = _append_3d_mask_record(
        masks=masks,
        request_case_id=request.case_id,
        image_id=request.image_id,
        version=version,
        label=label,
        encoding="3d_nifti",
        source_mask_ids=source_mask_ids,
        mask_stack=mask_stack,
        volume=volume,
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
    beta: float,
    roi_margin: int,
    max_nodes: int,
) -> np.ndarray:
    candidate = candidate_mask > 0
    sparse_foreground = sparse_mask > 0 if sparse_mask is not None else np.zeros_like(candidate, dtype=bool)
    seed_source = candidate | sparse_foreground
    bbox = _bounding_box(seed_source, max(4, int(roi_margin)))
    if bbox is None:
        return np.zeros_like(candidate_mask, dtype=np.uint8)

    y0, y1, x0, x1 = bbox
    node_count = (y1 - y0) * (x1 - x0)
    if node_count > max(256, int(max_nodes)):
        return candidate.astype(np.uint8)

    candidate_roi = candidate[y0:y1, x0:x1]
    sparse_roi = sparse_foreground[y0:y1, x0:x1]
    foreground = sparse_roi.copy()
    if not np.any(foreground):
        foreground = _morphology_mask(candidate_roi, "erode", 1)
    if not np.any(foreground):
        foreground = candidate_roi.copy()

    dilated = _morphology_mask(candidate_roi | foreground, "dilate", 3)
    background = ~dilated
    background[0, :] = True
    background[-1, :] = True
    background[:, 0] = True
    background[:, -1] = True
    background &= ~foreground
    if not np.any(background):
        return candidate.astype(np.uint8)

    refined_roi = _solve_binary_random_walker(
        image_roi=ct_slice[y0:y1, x0:x1],
        foreground_seeds=foreground,
        background_seeds=background,
        beta=max(1.0, float(beta)),
    )
    refined_roi = np.maximum(refined_roi, sparse_roi.astype(np.uint8))
    refined = np.zeros_like(candidate_mask, dtype=np.uint8)
    refined[y0:y1, x0:x1] = refined_roi
    return refined


def _refine_with_random_walker(
    candidate_volume: np.ndarray,
    volume_array: np.ndarray,
    sparse_slices: dict[int, np.ndarray],
    fill_holes: bool,
    keep_largest_component: bool,
    closing_radius: int,
    beta: float,
    roi_margin: int,
    max_nodes: int,
) -> np.ndarray:
    refined = np.zeros_like(candidate_volume, dtype=np.uint8)
    for slice_index in range(candidate_volume.shape[0]):
        if not np.any(candidate_volume[slice_index]) and slice_index not in sparse_slices:
            continue
        slice_refined = _random_walker_refine_slice(
            ct_slice=volume_array[slice_index],
            candidate_mask=candidate_volume[slice_index],
            sparse_mask=sparse_slices.get(slice_index),
            beta=beta,
            roi_margin=roi_margin,
            max_nodes=max_nodes,
        )
        refined[slice_index] = _cleanup_binary_slice(
            slice_refined,
            fill_holes=fill_holes,
            keep_largest_component=keep_largest_component,
            closing_radius=closing_radius,
        )

    for slice_index, slice_mask in sparse_slices.items():
        refined[slice_index] = np.maximum(refined[slice_index], (slice_mask > 0).astype(np.uint8))
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
    depth, height, width = volume.array.shape[:3]
    masks = _load_masks()
    json_records = _json_mask_records(masks, request.case_id, request.image_id, source_version, label)
    if not json_records:
        raise HTTPException(status_code=404, detail="No saved sparse JSON masks found for label propagation")

    sparse_slices_by_axis, source_mask_ids = _load_sparse_axis_masks(json_records, depth, height, width)
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
            axis_result = _refine_with_random_walker(
                candidate_volume=axis_result,
                volume_array=axis_volume,
                sparse_slices=sparse_slices,
                fill_holes=request.fill_holes,
                keep_largest_component=request.keep_largest_component,
                closing_radius=max(0, int(request.closing_radius)),
                beta=request.random_walker_beta,
                roi_margin=request.random_walker_roi_margin,
                max_nodes=request.random_walker_max_nodes,
            )
        axis_seed_volume = _seed_volume_from_sparse_slices(sparse_slices, axis_result.shape[:3])
        axis_result = _connected_component_filter_volume(
            mask_volume=axis_result,
            seed_volume=axis_seed_volume,
            mode=request.connected_component_mode,
            min_voxels=request.connected_component_min_voxels,
            max_components=request.connected_component_max_components,
            keep_largest_component=request.keep_largest_component,
        )
        propagated = np.maximum(propagated, _axis_result_to_volume(axis_result, axis))
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
    return _post_json_service(
        DEEPEDIT_SERVICE_URL,
        _deepedit_payload(request, current_mask),
        DEEPEDIT_SERVICE_TIMEOUT_SECONDS,
        "DeepEdit",
    )


def _remote_refinement_response(
    request: DeepEditRefineRequest,
    remote_result: dict[str, Any],
    method: str,
    status: str,
    default_message: str,
) -> DeepEditRefineResponse | None:
    if not remote_result or not remote_result.get("mask_id"):
        return None
    mask_id = str(remote_result["mask_id"])
    mask = get_mask(mask_id)
    return DeepEditRefineResponse(
        success=True,
        mask_id=mask.mask_id,
        path=mask.path,
        method=method,
        source_mask_ids=[request.current_mask_id] if request.current_mask_id else [],
        annotated_slices=sorted(set(int(value) for value in request.confirmed_slices)),
        propagated_slices=mask.height or 0,
        shape=[],
        spacing=[],
        origin=[],
        direction=[],
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

    propagation = label_propagate(
        LabelPropagationRequest(
            case_id=request.case_id,
            image_id=request.image_id,
            source_version=request.source_version,
            output_version=request.output_version,
            label=request.label,
            method="random_walker",
            fill_holes=True,
            keep_largest_component=False,
            image_guidance=True,
            closing_radius=1,
            connected_component_mode="seeded",
            connected_component_min_voxels=64,
            connected_component_max_components=8,
        )
    )
    return DeepEditRefineResponse(
        **propagation.model_dump(),
        refinement_mode="deepedit_fallback_random_walker",
        model_status="fallback_no_deepedit_model",
        model_message=(
            "DEEPEDIT_SERVICE_URL is not configured; used graph-based random_walker refinement "
            "with positive/negative prompts saved in the request contract."
        ),
    )
