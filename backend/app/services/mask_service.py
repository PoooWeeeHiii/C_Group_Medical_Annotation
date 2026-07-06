from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import numpy as np
from fastapi import HTTPException

from backend.app.core.config import (
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


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _normalize_label(label: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower()).strip("_")
    return value or "label"


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


def _load_sparse_slice_masks(
    records: list[dict],
    depth: int,
    height: int,
    width: int,
) -> tuple[dict[int, np.ndarray], list[str]]:
    slices: dict[int, np.ndarray] = {}
    source_mask_ids: list[str] = []
    for record in records:
        content = _read_mask_json(str(record.get("path")))
        if not content:
            continue
        slice_index = int(content.get("slice_index", -1))
        content_width = int(content.get("width", 0))
        content_height = int(content.get("height", 0))
        if not 0 <= slice_index < depth:
            raise HTTPException(status_code=400, detail=f"Saved mask slice_index is outside volume: {slice_index}")
        if content_width != width or content_height != height:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Saved mask dimensions do not match source image: "
                    f"mask={content_width}x{content_height}, image={width}x{height}"
                ),
            )
        if content.get("encoding") != "rle":
            raise HTTPException(status_code=400, detail="Only RLE JSON masks can be used for 3D mask generation")
        decoded = _decode_rle(content.get("mask") or [], width, height)
        if not np.any(decoded):
            continue
        slices[slice_index] = decoded
        source_mask_ids.append(str(record.get("mask_id")))
    return slices, source_mask_ids


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


def get_mask_slice_data(mask_id: str, slice_index: int) -> dict[str, Any]:
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
    depth, height, width = array.shape[:3]
    if not 0 <= slice_index < depth:
        raise HTTPException(status_code=400, detail=f"slice_index is outside mask volume: {slice_index}")

    slice_mask = (array[slice_index] > 0).astype(np.uint8)
    return {
        "success": True,
        "mask_id": mask_id,
        "case_id": record.get("case_id"),
        "image_id": record.get("image_id"),
        "version": record.get("version"),
        "label": record.get("label"),
        "slice_index": slice_index,
        "width": width,
        "height": height,
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

    sparse_slices, source_mask_ids = _load_sparse_slice_masks(json_records, depth, height, width)
    if not sparse_slices:
        raise HTTPException(status_code=404, detail="No readable JSON slice masks found")
    for slice_index, slice_mask in sparse_slices.items():
        mask_stack[slice_index] = slice_mask

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
    supported_methods = {"signed_distance", "image_guided_distance"}
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

    sparse_slices, source_mask_ids = _load_sparse_slice_masks(json_records, depth, height, width)
    if not sparse_slices:
        raise HTTPException(status_code=404, detail="No readable sparse masks found for label propagation")

    propagated = _propagate_sparse_slices(
        sparse_slices=sparse_slices,
        volume_array=volume.array,
        spacing=tuple(float(value) for value in volume.spacing),
        fill_holes=request.fill_holes,
        keep_largest_component=request.keep_largest_component,
        image_guidance=request.image_guidance or request.method == "image_guided_distance",
        hu_margin=request.hu_margin,
        closing_radius=max(0, int(request.closing_radius)),
    )
    encoding = (
        "label_propagation_image_guided_distance"
        if request.image_guidance or request.method == "image_guided_distance"
        else "label_propagation_signed_distance"
    )
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
        annotated_slices=sorted(sparse_slices),
        propagated_slices=depth,
        shape=[depth, height, width],
        spacing=[float(value) for value in volume.spacing],
        origin=[float(value) for value in volume.origin],
        direction=[float(value) for value in volume.direction],
        mask=mask,
    )


def deepedit_refine(request: DeepEditRefineRequest) -> DeepEditRefineResponse:
    propagation = label_propagate(
        LabelPropagationRequest(
            case_id=request.case_id,
            image_id=request.image_id,
            source_version=request.source_version,
            output_version=request.output_version,
            label=request.label,
            method="image_guided_distance",
            fill_holes=True,
            keep_largest_component=False,
            image_guidance=True,
            closing_radius=1,
        )
    )
    return DeepEditRefineResponse(
        **propagation.model_dump(),
        refinement_mode="label_propagation_placeholder",
    )
