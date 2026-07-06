from __future__ import annotations

import base64
import gzip
import io
import math
import threading
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image

from backend.app.core.config import IMAGES_DB_PATH, PROJECT_ROOT
from backend.app.services.file_service import load_json_list


@dataclass(frozen=True)
class VolumeData:
    array: np.ndarray
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    direction: tuple[float, ...]
    source: str


NRRD_TYPES: dict[str, str] = {
    "signed char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "unsigned char": "u1",
    "uint8": "u1",
    "short": "i2",
    "short int": "i2",
    "int16": "i2",
    "ushort": "u2",
    "unsigned short": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "unsigned int": "u4",
    "uint32": "u4",
    "float": "f4",
    "double": "f8",
}


WINDOWS = {
    "lung": (-600, 1500),
    "soft": (40, 400),
    "bone": (500, 2000),
}
VOLUME_HU_RANGES = {
    "volume": (-1000.0, 1800.0),
    "lung": (-1000.0, 600.0),
    "soft": (-180.0, 320.0),
    "bone": (-300.0, 1800.0),
}

AXES = {"axial", "coronal", "sagittal"}
_VOLUME_CACHE: dict[tuple[str, int, int], VolumeData] = {}
_VOLUME_CACHE_LOCK = threading.RLock()
_MAX_CACHED_VOLUMES = 4


def _image_record(image_id: str) -> dict:
    images = load_json_list(IMAGES_DB_PATH)
    image = next((item for item in images if item.get("image_id") == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail=f"Image not found: {image_id}")
    return image


def _resolve_path(path_value: str) -> Path:
    path = (PROJECT_ROOT / path_value).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid image path") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Image file not found: {path_value}")
    return path


def _read_nrrd_header(raw: bytes) -> tuple[dict[str, str], int]:
    for marker in (b"\n\n", b"\r\n\r\n"):
        index = raw.find(marker)
        if index != -1:
            header_raw = raw[:index].decode("utf-8", errors="replace")
            data_offset = index + len(marker)
            break
    else:
        raise ValueError("NRRD header terminator not found")

    fields: dict[str, str] = {}
    for line in header_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("NRRD"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
    return fields, data_offset


def _spacing_from_nrrd(fields: dict[str, str]) -> tuple[float, float, float]:
    if "spacings" in fields:
        values = [float(item) for item in fields["spacings"].split()[:3]]
        while len(values) < 3:
            values.append(1.0)
        return values[0], values[1], values[2]
    return 1.0, 1.0, 1.0


def _direction_3d(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) == 9:
        return values
    if len(values) == 4:
        return (values[0], values[1], 0.0, values[2], values[3], 0.0, 0.0, 0.0, 1.0)
    return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _load_nrrd_bytes(raw: bytes, source: str) -> VolumeData:
    fields, data_offset = _read_nrrd_header(raw)
    sizes = [int(item) for item in fields.get("sizes", "").split()]
    if len(sizes) < 2:
        raise ValueError("NRRD sizes field is missing")

    dtype_key = fields.get("type", "short").lower()
    dtype_code = NRRD_TYPES.get(dtype_key)
    if dtype_code is None:
        raise ValueError(f"Unsupported NRRD type: {dtype_key}")

    dtype = np.dtype(dtype_code)
    endian = fields.get("endian", "little").lower()
    if dtype.itemsize > 1:
        dtype = dtype.newbyteorder(">" if endian == "big" else "<")

    encoding = fields.get("encoding", "raw").lower()
    payload = raw[data_offset:]
    if encoding in {"gzip", "gz"}:
        payload = gzip.decompress(payload)

    if encoding in {"ascii", "text", "txt"}:
        data = np.fromstring(payload.decode("utf-8", errors="replace"), sep=" ", dtype=dtype)
    elif encoding in {"raw", "gzip", "gz"}:
        data = np.frombuffer(payload, dtype=dtype)
    else:
        raise ValueError(f"Unsupported NRRD encoding: {encoding}")

    if len(sizes) == 2:
        shape = (1, sizes[1], sizes[0])
    else:
        shape = (sizes[2], sizes[1], sizes[0])
    expected = int(np.prod(shape))
    if data.size < expected:
        raise ValueError("NRRD data payload is shorter than expected")

    array = data[:expected].reshape(shape)
    return VolumeData(
        array=array,
        spacing=_spacing_from_nrrd(fields),
        origin=(0.0, 0.0, 0.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        source=source,
    )


def _load_nrrd_path(path: Path) -> VolumeData:
    return _load_nrrd_bytes(path.read_bytes(), path.name)


def _load_zip_nrrd(path: Path) -> VolumeData:
    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".nrrd")]
        image_names = [name for name in names if "label" not in name.lower() and "mask" not in name.lower()]
        selected = (image_names or names)[0] if names else None
        if selected is None:
            raise ValueError("No NRRD file found in ZIP")
        return _load_nrrd_bytes(archive.read(selected), selected)


def _load_with_simpleitk(path: Path) -> VolumeData:
    import SimpleITK as sitk

    suffix = path.suffix.lower()
    if suffix == ".zip":
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with ZipFile(path) as archive:
                archive.extractall(tmp_path)
            nrrd_files = [p for p in tmp_path.rglob("*.nrrd") if "label" not in p.name.lower()]
            nii_files = list(tmp_path.rglob("*.nii")) + list(tmp_path.rglob("*.nii.gz"))
            candidates = nrrd_files or nii_files
            if candidates:
                image = sitk.ReadImage(str(candidates[0]))
            else:
                dicom_names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(tmp_path))
                if not dicom_names:
                    raise ValueError("No readable medical image found in ZIP")
                reader = sitk.ImageSeriesReader()
                reader.SetFileNames(dicom_names)
                image = reader.Execute()
    elif suffix == ".dcm":
        dicom_names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(path.parent))
        if dicom_names:
            reader = sitk.ImageSeriesReader()
            reader.SetFileNames(dicom_names)
            image = reader.Execute()
        else:
            image = sitk.ReadImage(str(path))
    else:
        image = sitk.ReadImage(str(path))

    array = sitk.GetArrayFromImage(image)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    spacing = tuple(float(v) for v in image.GetSpacing()[:3])
    origin = tuple(float(v) for v in image.GetOrigin()[:3])
    direction = _direction_3d(tuple(float(v) for v in image.GetDirection()))
    return VolumeData(array=array, spacing=spacing, origin=origin, direction=direction, source="SimpleITK")


def _load_volume_from_path(path: Path) -> VolumeData:
    try:
        return _load_with_simpleitk(path)
    except ModuleNotFoundError:
        pass
    except Exception:
        # Fall through to the lightweight NRRD reader when SimpleITK cannot read
        # a local sample. Real DICOM/NIfTI support still comes from SimpleITK.
        pass

    try:
        if path.suffix.lower() == ".nrrd":
            return _load_nrrd_path(path)
        if path.suffix.lower() == ".zip":
            return _load_zip_nrrd(path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot read medical volume: {exc}") from exc

    raise HTTPException(
        status_code=422,
        detail="Cannot read this image without SimpleITK. Please install requirements.txt.",
    )


def _cached_volume(path: Path) -> VolumeData:
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _VOLUME_CACHE_LOCK:
        cached = _VOLUME_CACHE.get(key)
        if cached is not None:
            return cached

        volume = _load_volume_from_path(path)
        _VOLUME_CACHE[key] = volume
        while len(_VOLUME_CACHE) > _MAX_CACHED_VOLUMES:
            _VOLUME_CACHE.pop(next(iter(_VOLUME_CACHE)))
        return volume


def load_volume(image_id: str) -> tuple[dict, VolumeData]:
    image = _image_record(image_id)
    path = _resolve_path(str(image["path"]))
    return image, _cached_volume(path)


def get_volume_metadata(image_id: str) -> dict:
    image, volume = load_volume(image_id)
    depth, height, width = volume.array.shape[:3]
    return {
        "success": True,
        "image_id": image["image_id"],
        "case_id": image["case_id"],
        "width": width,
        "height": height,
        "slice_count": depth,
        "spacing": volume.spacing,
        "origin": volume.origin,
        "direction": volume.direction,
        "source": volume.source,
        "file_format": image.get("file_format", "unknown"),
        "path": image.get("path", ""),
    }


def _window_slice(slice_data: np.ndarray, window: str) -> np.ndarray:
    data = slice_data.astype(np.float32)
    if window in WINDOWS:
        level, width = WINDOWS[window]
        low = level - width / 2
        high = level + width / 2
    else:
        low, high = np.percentile(data, [1, 99])
        if high <= low:
            low, high = float(data.min()), float(data.max())
        if high <= low:
            high = low + 1

    data = np.clip(data, low, high)
    data = (data - low) / (high - low) * 255.0
    return data.astype(np.uint8)


def _volume_hu_range(volume_data: np.ndarray, window: str) -> tuple[float, float]:
    if window in VOLUME_HU_RANGES:
        return VOLUME_HU_RANGES[window]

    data = volume_data.astype(np.float32)
    low, high = np.percentile(data, [0.5, 99.7])
    if high <= low:
        low, high = float(data.min()), float(data.max())
    if high <= low:
        high = low + 1.0
    return float(low), float(high)


def _window_volume(volume_data: np.ndarray, window: str) -> tuple[np.ndarray, tuple[float, float]]:
    data = volume_data.astype(np.float32)
    low, high = _volume_hu_range(data, window)

    data = np.clip(data, low, high)
    data = (data - low) / (high - low) * 255.0
    return np.ascontiguousarray(data.astype(np.uint8)), (float(low), float(high))


def _downsample_volume(array: np.ndarray, max_dim: int) -> tuple[np.ndarray, tuple[int, int, int]]:
    max_dim = max(64, min(max_dim, 192))
    depth, height, width = array.shape[:3]
    stride_z = max(1, int(np.ceil(depth / max_dim)))
    stride_y = max(1, int(np.ceil(height / max_dim)))
    stride_x = max(1, int(np.ceil(width / max_dim)))
    return array[::stride_z, ::stride_y, ::stride_x], (stride_z, stride_y, stride_x)


def _resample_volume_isotropic(
    volume: VolumeData,
    max_dim: int,
    target_spacing: float | None = None,
) -> tuple[VolumeData, dict]:
    spacing = tuple(max(float(value), 1e-6) for value in volume.spacing)
    depth, height, width = volume.array.shape[:3]
    original_size = (width, height, depth)
    requested_spacing = float(target_spacing) if target_spacing and target_spacing > 0 else min(spacing)
    requested_spacing = max(requested_spacing, 1e-6)
    max_dim = max(64, min(max_dim, 192))
    max_voxels = max_dim**3

    new_size = [
        max(1, int(round(original_size[index] * spacing[index] / requested_spacing)))
        for index in range(3)
    ]
    voxel_count = math.prod(new_size)
    final_spacing = requested_spacing
    if voxel_count > max_voxels:
        scale = (voxel_count / max_voxels) ** (1.0 / 3.0)
        final_spacing = requested_spacing * scale
        new_size = [
            max(1, int(round(original_size[index] * spacing[index] / final_spacing)))
            for index in range(3)
        ]

    if max(spacing) / min(spacing) < 1.08 and all(size <= max_dim for size in original_size):
        return volume, {
            "requested": True,
            "applied": False,
            "reason": "source spacing is already close to isotropic",
            "original_spacing": spacing,
            "target_spacing": spacing,
            "size": original_size,
        }

    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return volume, {
            "requested": True,
            "applied": False,
            "reason": "SimpleITK is not installed",
            "original_spacing": spacing,
            "target_spacing": spacing,
            "size": original_size,
        }

    image = sitk.GetImageFromArray(volume.array.astype(np.float32, copy=False))
    image.SetSpacing(spacing)
    image.SetOrigin(volume.origin)
    image.SetDirection(volume.direction)

    resampler = sitk.ResampleImageFilter()
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetSize([int(value) for value in new_size])
    resampler.SetOutputSpacing([float(final_spacing)] * 3)
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetDefaultPixelValue(-1000.0)
    resampler.SetOutputPixelType(sitk.sitkFloat32)

    resampled = resampler.Execute(image)
    resampled_array = sitk.GetArrayFromImage(resampled)
    resampled_volume = VolumeData(
        array=resampled_array,
        spacing=tuple(float(value) for value in resampled.GetSpacing()[:3]),
        origin=tuple(float(value) for value in resampled.GetOrigin()[:3]),
        direction=tuple(float(value) for value in resampled.GetDirection()),
        source=f"{volume.source} + isotropic resample",
    )
    return resampled_volume, {
        "requested": True,
        "applied": True,
        "original_spacing": spacing,
        "target_spacing": resampled_volume.spacing,
        "size": tuple(int(value) for value in new_size),
    }


def _slice_by_axis(array: np.ndarray, axis: str, slice_index: int) -> np.ndarray:
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
    raise HTTPException(status_code=400, detail=f"Unsupported axis: {axis}")


def _projection_by_axis(array: np.ndarray, axis: str, method: str) -> np.ndarray:
    if method == "mean":
        reducer = np.mean
    elif method == "min":
        reducer = np.min
    else:
        reducer = np.max

    if axis == "axial":
        return reducer(array, axis=0)
    if axis == "coronal":
        return np.flipud(reducer(array, axis=1))
    if axis == "sagittal":
        return np.flipud(reducer(array, axis=2))
    raise HTTPException(status_code=400, detail=f"Unsupported axis: {axis}")


def _png_response(pixels: np.ndarray) -> Response:
    image = Image.fromarray(pixels, mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


def render_slice_png(image_id: str, slice_index: int, window: str = "auto", axis: str = "axial") -> Response:
    _, volume = load_volume(image_id)
    if volume.array.size <= 0:
        raise HTTPException(status_code=422, detail="Volume has no slices")
    if axis not in AXES:
        raise HTTPException(status_code=400, detail=f"Unsupported axis: {axis}")
    pixels = _window_slice(_slice_by_axis(volume.array, axis, slice_index), window)
    return _png_response(pixels)


def get_slice_values(image_id: str, slice_index: int, axis: str = "axial") -> dict:
    image, volume = load_volume(image_id)
    if volume.array.size <= 0:
        raise HTTPException(status_code=422, detail="Volume has no slices")
    if axis not in AXES:
        raise HTTPException(status_code=400, detail=f"Unsupported axis: {axis}")

    values = np.ascontiguousarray(_slice_by_axis(volume.array, axis, slice_index).astype(np.float32, copy=False))
    height, width = values.shape[:2]
    return {
        "success": True,
        "image_id": image["image_id"],
        "case_id": image["case_id"],
        "axis": axis,
        "slice_index": max(0, min(slice_index, volume.array.shape[0] - 1)) if axis == "axial" else slice_index,
        "width": width,
        "height": height,
        "scalar_type": "float32",
        "value_min": float(values.min()),
        "value_max": float(values.max()),
        "values_base64": base64.b64encode(values.tobytes(order="C")).decode("ascii"),
    }


def render_projection_png(image_id: str, axis: str = "axial", method: str = "mip", window: str = "auto") -> Response:
    _, volume = load_volume(image_id)
    if volume.array.size <= 0:
        raise HTTPException(status_code=422, detail="Volume has no voxels")
    if axis not in AXES:
        raise HTTPException(status_code=400, detail=f"Unsupported axis: {axis}")
    pixels = _window_slice(_projection_by_axis(volume.array, axis, method), window)
    return _png_response(pixels)


def get_volume_render_data(
    image_id: str,
    max_dim: int = 144,
    window: str = "lung",
    isotropic: bool = False,
    target_spacing: float | None = None,
) -> dict:
    image, volume = load_volume(image_id)
    resampling = {
        "requested": False,
        "applied": False,
        "original_spacing": volume.spacing,
        "target_spacing": volume.spacing,
    }
    if isotropic:
        volume, resampling = _resample_volume_isotropic(
            volume=volume,
            max_dim=max_dim,
            target_spacing=target_spacing,
        )
    downsampled, strides = _downsample_volume(volume.array, max_dim)
    values, hu_range = _window_volume(downsampled, window)
    depth, height, width = values.shape[:3]
    sx, sy, sz = volume.spacing
    stride_z, stride_y, stride_x = strides
    payload = base64.b64encode(values.tobytes(order="C")).decode("ascii")

    return {
        "success": True,
        "image_id": image["image_id"],
        "case_id": image["case_id"],
        "dimensions": [width, height, depth],
        "spacing": [sx * stride_x, sy * stride_y, sz * stride_z],
        "origin": volume.origin,
        "direction": volume.direction,
        "scalar_type": "uint8",
        "window": window,
        "resampling": resampling,
        "hu_range": [hu_range[0], hu_range[1]],
        "max_dim": max_dim,
        "downsample_stride": [stride_z, stride_y, stride_x],
        "value_range": [int(values.min()), int(values.max())],
        "values_base64": payload,
    }


def export_volume_file(image_id: str) -> FileResponse:
    image = _image_record(image_id)
    path = _resolve_path(str(image["path"]))
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{image['image_id']}_{path.name}",
    )
