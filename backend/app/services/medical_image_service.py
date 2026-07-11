from __future__ import annotations

import base64
import gzip
import io
import math
import threading
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image

from backend.app.core.config import PROJECT_ROOT
from backend.app.services.sqlite_service import get_record


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
    image = get_record("images", "image_id", image_id)
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
    elif suffix in {".dcm", ".dicom"}:
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


def _filter_binary_components(binary: np.ndarray, min_voxels: int, max_components: int) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        from scipy import ndimage as ndi
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="scipy is required for VTK CT surface mesh") from exc

    before = int(np.count_nonzero(binary))
    if before == 0:
        return binary.astype(np.uint8, copy=False), {
            "voxel_count_before": 0,
            "voxel_count_after": 0,
            "component_count_before": 0,
            "component_count_after": 0,
        }
    labeled, component_count = ndi.label(binary > 0, structure=np.ones((3, 3, 3), dtype=np.uint8))
    sizes = np.bincount(labeled.reshape(-1))
    labels = np.arange(1, sizes.size)
    keep = [
        int(label)
        for label in sorted(labels, key=lambda value: int(sizes[value]), reverse=True)
        if int(sizes[label]) >= max(1, int(min_voxels))
    ][: max(1, int(max_components))]
    if not keep and labels.size:
        keep = [int(labels[np.argmax(sizes[1:])])]
    cleaned = np.isin(labeled, keep)
    after = int(np.count_nonzero(cleaned))
    return cleaned.astype(np.uint8, copy=False), {
        "voxel_count_before": before,
        "voxel_count_after": after,
        "component_count_before": int(component_count),
        "component_count_after": len(keep),
        "removed_voxels": before - after,
        "kept_component_voxels": [int(sizes[label]) for label in keep],
    }


def _vtk_binary_surface_mesh(
    binary: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float],
    max_triangles: int,
    target_reduction: float,
    smooth_iterations: int,
) -> tuple[np.ndarray, np.ndarray, list[int], dict[str, int]]:
    try:
        import vtk
        from vtk.util import numpy_support
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="vtk is not installed. Run `pip install -r requirements.txt` to enable VTK CT surface mesh.",
        ) from exc

    depth, height, width = binary.shape[:3]
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(int(width), int(height), int(depth))
    image_data.SetSpacing(tuple(float(value) for value in spacing))
    image_data.SetOrigin(tuple(float(value) for value in origin))
    scalars = numpy_support.numpy_to_vtk(
        np.ascontiguousarray(binary.astype(np.uint8, copy=False)).reshape(-1, order="C"),
        deep=True,
        array_type=vtk.VTK_UNSIGNED_CHAR,
    )
    scalars.SetName("surface")
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
        smoother.SetNumberOfIterations(max(0, min(int(smooth_iterations), 18)))
        smoother.BoundarySmoothingOff()
        smoother.FeatureEdgeSmoothingOff()
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()
        smoother.Update()
        if smoother.GetOutput().GetNumberOfPolys() > 0:
            polydata = smoother.GetOutput()

    original_triangles = int(polydata.GetNumberOfPolys())
    if original_triangles > max_triangles:
        reduction = max(float(target_reduction), min(0.94, 1.0 - (float(max_triangles) / float(original_triangles))))
        best = polydata
        best_count = original_triangles
        for attempt in sorted(set([reduction, 0.70, 0.84, 0.92, 0.95])):
            decimator = vtk.vtkQuadricDecimation()
            decimator.SetInputData(polydata)
            decimator.SetTargetReduction(max(0.0, min(float(attempt), 0.95)))
            decimator.VolumePreservationOn()
            decimator.Update()
            output = decimator.GetOutput()
            count = int(output.GetNumberOfPolys())
            if output.GetNumberOfPoints() > 0 and 0 < count < best_count:
                best = output
                best_count = count
            if 0 < count <= max_triangles:
                best = output
                break
        polydata = best

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
        raise HTTPException(status_code=422, detail="VTK could not extract CT surface mesh")

    points = numpy_support.vtk_to_numpy(polydata.GetPoints().GetData()).astype(np.float32, copy=False)
    normal_data = polydata.GetPointData().GetNormals()
    if normal_data is not None:
        normals = numpy_support.vtk_to_numpy(normal_data).astype(np.float32, copy=False)
    else:
        normals = np.zeros_like(points, dtype=np.float32)
    extent = np.array(
        [
            spacing[0] * max(width - 1, 1),
            spacing[1] * max(height - 1, 1),
            spacing[2] * max(depth - 1, 1),
        ],
        dtype=np.float32,
    )
    normalized = (points - np.array(origin, dtype=np.float32)) / np.maximum(extent, 1e-6)
    normalized = np.clip(normalized, 0.0, 1.0).astype(np.float32, copy=False)

    polys = numpy_support.vtk_to_numpy(polydata.GetPolys().GetData()).astype(np.int64, copy=False)
    indices: list[int] = []
    cursor = 0
    while cursor < polys.size:
        count = int(polys[cursor])
        if count == 3 and cursor + 3 < polys.size:
            indices.extend(int(value) for value in polys[cursor + 1 : cursor + 4])
        cursor += count + 1
    return normalized, normals.astype(np.float32, copy=False), indices, {
        "original_triangle_count": original_triangles,
        "triangle_count": int(len(indices) // 3),
        "vertex_count": int(normalized.shape[0]),
    }


def get_image_surface_mesh(
    image_id: str,
    protocol: str = "bone",
    max_dim: int = 176,
    min_component_voxels: int = 512,
    max_components: int = 3,
    max_triangles: int = 120000,
    target_reduction: float = 0.50,
    smooth_iterations: int = 6,
) -> dict[str, Any]:
    image, volume = load_volume(image_id)
    downsampled, strides = _downsample_volume(volume.array, max_dim=max_dim)
    protocol = (protocol or "bone").strip().lower()
    if protocol == "body":
        binary = downsampled > -550
        iso_description = "body HU > -550"
    elif protocol == "lung":
        try:
            from scipy import ndimage as ndi
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=500, detail="scipy is required for lung VTK surface mesh") from exc
        body_seed = downsampled > -850
        envelope = np.zeros_like(body_seed, dtype=bool)
        for z in range(body_seed.shape[0]):
            envelope[z] = ndi.binary_fill_holes(body_seed[z])
        envelope = ndi.binary_closing(envelope, structure=np.ones((3, 5, 5), dtype=bool), iterations=1)
        binary = envelope & (downsampled > -980) & (downsampled < -420)
        iso_description = "lung/low-density cavity inside body envelope"
    elif protocol == "soft":
        binary = (downsampled > -160) & (downsampled < 360)
        iso_description = "soft tissue -160 < HU < 360"
    else:
        protocol = "bone"
        binary = downsampled > 180
        iso_description = "bone HU > 180"

    binary, cleanup = _filter_binary_components(
        binary.astype(np.uint8, copy=False),
        min_voxels=min_component_voxels,
        max_components=max_components,
    )
    if not np.any(binary):
        raise HTTPException(status_code=422, detail=f"No CT surface found for protocol: {protocol}")

    stride_z, stride_y, stride_x = strides
    spacing = (
        float(volume.spacing[0]) * stride_x,
        float(volume.spacing[1]) * stride_y,
        float(volume.spacing[2]) * stride_z,
    )
    positions, normals, indices, mesh_info = _vtk_binary_surface_mesh(
        binary=binary,
        spacing=spacing,
        origin=volume.origin,
        max_triangles=max_triangles,
        target_reduction=target_reduction,
        smooth_iterations=smooth_iterations,
    )
    depth, height, width = binary.shape[:3]
    return {
        "success": True,
        "image_id": image["image_id"],
        "case_id": image["case_id"],
        "source": "vtk_marching_cubes",
        "protocol": protocol,
        "iso": iso_description,
        "dimensions": [width, height, depth],
        "spacing": [float(value) for value in spacing],
        "origin": [float(value) for value in volume.origin],
        "cleanup": cleanup,
        "vertex_count": mesh_info["vertex_count"],
        "triangle_count": mesh_info["triangle_count"],
        "original_triangle_count": mesh_info["original_triangle_count"],
        "positions": positions.reshape(-1).round(6).tolist(),
        "normals": normals.reshape(-1).round(5).tolist(),
        "indices": indices,
    }


def export_volume_file(image_id: str) -> FileResponse:
    image = _image_record(image_id)
    path = _resolve_path(str(image["path"]))
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"{image['image_id']}_{path.name}",
    )
