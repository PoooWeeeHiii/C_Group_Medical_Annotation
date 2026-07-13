"""Data preprocessing — Day2: load / normalize / resize / crop / save."""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np
import pydicom
from PIL import Image

from ai.config import CT_HU_MAX, CT_HU_MIN, IMAGE_SIZE, LABELS_DIR, mask_filename

try:
    import nrrd
except ImportError:  # pragma: no cover
    nrrd = None

try:
    from highdicom.seg import Segmentation
except ImportError:  # pragma: no cover
    Segmentation = None


def _rescale_hu(ds: pydicom.Dataset, arr: np.ndarray) -> np.ndarray:
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    return arr.astype(np.float32) * slope + intercept


def load(path: str | Path) -> np.ndarray:
    """Load PNG/JPG, NRRD, single DICOM, or DICOM series directory."""
    path = Path(path)
    if path.is_dir():
        return load_dicom_series(path)
    suffix = path.name.lower()
    if suffix.endswith(".nrrd"):
        if nrrd is None:
            raise ImportError("pynrrd is required for NRRD files")
        data, _ = nrrd.read(str(path))
        return np.asarray(data, dtype=np.float32)
    if suffix.endswith(".dcm"):
        ds = pydicom.dcmread(str(path))
        return _rescale_hu(ds, ds.pixel_array)
    if suffix.endswith((".png", ".jpg", ".jpeg")):
        with Image.open(path) as img:
            return np.asarray(img.convert("L"), dtype=np.float32)
    raise ValueError(f"Unsupported input path: {path}")


def load_dicom_series(series_dir: str | Path) -> np.ndarray:
    series_dir = Path(series_dir)
    files = [p for p in series_dir.glob("*.dcm") if p.is_file()]
    if not files:
        raise FileNotFoundError(f"No DICOM files in {series_dir}")
    slices = [pydicom.dcmread(str(f)) for f in files]
    slices.sort(key=lambda ds: float(ds.ImagePositionPatient[2]))
    volume = np.stack([_rescale_hu(ds, ds.pixel_array) for ds in slices], axis=0)
    return volume.astype(np.float32)


def load_seg_dicom(seg_path: str | Path, segment_number: int = 1) -> np.ndarray:
    if Segmentation is None:
        raise ImportError("highdicom is required for DICOM SEG files")
    seg = Segmentation.from_file(str(seg_path))
    mask = seg.get_volume(segment_numbers=[segment_number]).array
    if mask.ndim == 4:
        mask = mask[..., 0]
    return (mask > 0).astype(np.uint8)


def normalize(volume: np.ndarray, modality: str = "CT") -> np.ndarray:
    if modality.upper() != "CT":
        vmin, vmax = float(volume.min()), float(volume.max())
        if vmax <= vmin:
            return np.zeros_like(volume, dtype=np.float32)
        return ((volume - vmin) / (vmax - vmin)).astype(np.float32)
    clipped = np.clip(volume, CT_HU_MIN, CT_HU_MAX)
    return ((clipped - CT_HU_MIN) / (CT_HU_MAX - CT_HU_MIN)).astype(np.float32)


def resize(arr: np.ndarray, size: Tuple[int, int] = IMAGE_SIZE) -> np.ndarray:
    h, w = size
    if arr.ndim != 2:
        raise ValueError("resize() expects a 2D array; pick a slice before resizing")
    mode = Image.Resampling.NEAREST if arr.dtype == np.uint8 else Image.Resampling.BILINEAR
    out = Image.fromarray(arr).resize((w, h), resample=mode)
    return np.asarray(out, dtype=arr.dtype if arr.dtype == np.uint8 else np.float32)


def crop(arr: np.ndarray, bbox: Tuple[int, int, int, int] | None = None) -> np.ndarray:
    if bbox is None:
        return arr
    y0, y1, x0, x1 = bbox
    return arr[y0:y1, x0:x1]


def save(arr: np.ndarray, path: str | Path, *, is_mask: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_mask:
        Image.fromarray(((arr > 0).astype(np.uint8) * 255)).save(path)
    else:
        data = np.clip(arr, 0.0, 1.0)
        Image.fromarray((data * 255).astype(np.uint8)).save(path)
    return path


def label_path(case_id: str, image_id: str, mask_id: str, version: str, label: str = "lung_nodule") -> Path:
    fname = mask_filename(case_id, image_id, mask_id, version, label, ext="png")
    return LABELS_DIR / case_id / version / fname


def image_path(case_id: str, image_id: str, label: str = "lung_nodule") -> Path:
    from ai.config import IMAGES_DIR

    fname = f"{case_id}_{image_id}_{label}.png"
    return IMAGES_DIR / case_id / fname


def best_tumor_slice(mask_volume: np.ndarray) -> int:
    counts = mask_volume.reshape(mask_volume.shape[0], -1).sum(axis=1)
    return int(np.argmax(counts)) if counts.sum() > 0 else mask_volume.shape[0] // 2


def export_slice_pair(
    ct_volume: np.ndarray,
    mask_volume: np.ndarray | None,
    slice_index: int,
    out_image: Path,
    out_mask: Path | None = None,
    size: Tuple[int, int] = IMAGE_SIZE,
) -> tuple[Path, Path | None]:
    ct_slice = normalize(ct_volume[slice_index])
    ct_slice = resize(ct_slice, size)
    save(ct_slice, out_image, is_mask=False)
    if mask_volume is None or out_mask is None:
        return out_image, None
    mask_slice = resize(mask_volume[slice_index].astype(np.uint8), size)
    save(mask_slice, out_mask, is_mask=True)
    return out_image, out_mask
