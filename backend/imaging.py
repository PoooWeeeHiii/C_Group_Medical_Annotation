"""Medical image I/O: import uploaded files and render slices to PNG.

Supported inputs: DICOM (zip of a series or a folder), NIfTI (.nii/.nii.gz),
NRRD (.nrrd), MetaImage (.mha/.mhd) and plain 2D images (.png/.jpg/.jpeg).

The frontend never parses medical formats; it only requests PNG slices from
``GET /api/image/{id}/slice/{n}`` (docs/04, docs/05).
"""
from __future__ import annotations

import io
import os
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from PIL import Image as PILImage

VOLUME_EXTS = (".nii", ".nii.gz", ".nrrd", ".mha", ".mhd", ".dcm")
IMAGE_2D_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


def _has_ext(name: str, exts) -> bool:
    lower = name.lower()
    return any(lower.endswith(e) for e in exts)


def store_upload(raw_bytes: bytes, filename: str, dest_dir: Path) -> Path:
    """Persist an uploaded file under ``dest_dir``.

    Zip archives (assumed DICOM series) are extracted; the returned path is the
    directory that actually contains the readable image data. For single files
    the returned path is the file itself.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            zf.extractall(dest_dir)
        return _resolve_series_dir(dest_dir)

    out = dest_dir / Path(filename).name
    out.write_bytes(raw_bytes)
    return out


def _resolve_series_dir(root: Path) -> Path:
    """Find the directory holding a readable image after extracting a zip.

    Prefers a directory containing a DICOM series; otherwise a directory with a
    single volume/2D file. Falls back to ``root``.
    """
    candidates = [root, *[p for p in root.rglob("*") if p.is_dir()]]
    # First: a directory GDCM recognises as a DICOM series.
    for d in candidates:
        try:
            series_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(d))
        except Exception:
            series_ids = []
        if series_ids:
            return d
    # Second: a directory that directly contains a volume/2D file.
    for d in candidates:
        for f in d.iterdir():
            if f.is_file() and _has_ext(f.name, VOLUME_EXTS + IMAGE_2D_EXTS):
                return d
    return root


def _read_volume(path: Path) -> sitk.Image:
    """Read a path (file or DICOM-series directory) into a SimpleITK image."""
    if path.is_dir():
        reader = sitk.ImageSeriesReader()
        series_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(path))
        if series_ids:
            files = reader.GetGDCMSeriesFileNames(str(path), series_ids[0])
            reader.SetFileNames(files)
            return reader.Execute()
        # directory with a single volume/2D file
        for f in sorted(path.iterdir()):
            if f.is_file() and _has_ext(f.name, VOLUME_EXTS + IMAGE_2D_EXTS):
                return sitk.ReadImage(str(f))
        raise ValueError(f"No readable image found in directory: {path}")
    return sitk.ReadImage(str(path))


@lru_cache(maxsize=32)
def _load_array_cached(path_str: str, mtime: float):
    """Return (array[z,y,x], size=(w,h,slices)). Cached by path+mtime."""
    path = Path(path_str)
    lower = path.name.lower()
    if path.is_file() and _has_ext(lower, IMAGE_2D_EXTS):
        arr = np.asarray(PILImage.open(path).convert("L"))
        arr = arr[np.newaxis, ...]  # (1, y, x)
    else:
        img = _read_volume(path)
        arr = sitk.GetArrayFromImage(img)  # (z, y, x) for 3D, (y, x) for 2D
        if arr.ndim == 2:
            arr = arr[np.newaxis, ...]
    slices, height, width = arr.shape[0], arr.shape[1], arr.shape[2]
    return arr, (width, height, slices)


def _load_array(abs_path: Path):
    try:
        mtime = os.path.getmtime(abs_path)
    except OSError:
        mtime = 0.0
    return _load_array_cached(str(abs_path), mtime)


def get_dimensions(abs_path: Path):
    """Return (width, height, slice_count)."""
    _, (w, h, s) = _load_array(abs_path)
    return w, h, s


def read_slice_png(abs_path: Path, slice_index: int) -> bytes:
    """Render one slice as an 8-bit grayscale PNG (min-max windowed)."""
    arr, (_, _, slices) = _load_array(abs_path)
    if slice_index < 0 or slice_index >= slices:
        raise IndexError(f"slice_index {slice_index} out of range [0, {slices})")
    sl = arr[slice_index].astype(np.float32)
    lo, hi = float(sl.min()), float(sl.max())
    if hi > lo:
        norm = (sl - lo) / (hi - lo) * 255.0
    else:
        norm = np.zeros_like(sl)
    png = PILImage.fromarray(norm.astype(np.uint8), mode="L")
    buf = io.BytesIO()
    png.save(buf, format="PNG")
    return buf.getvalue()
