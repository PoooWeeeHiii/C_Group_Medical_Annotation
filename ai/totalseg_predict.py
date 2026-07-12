"""Run organ segmentation with TotalSegmentator for platform AI predict.

Uses a dedicated Python (TOTALSEG_PYTHON) via subprocess so the FastAPI
process does not need to import totalsegmentator / nnUNet itself.

Env:
  TOTALSEG_PYTHON   python with `pip install TotalSegmentator`
  TOTALSEG_DEVICE   auto|cpu|gpu|cuda  (default auto)
  TOTALSEG_FAST     true/false — use --fast (3mm) for CPU speed (default true on cpu)
  TOTALSEG_TIMEOUT_SECONDS  default 1800
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from ai.config import TOTALSEG_DEVICE, TOTALSEG_FAST, TOTALSEG_PYTHON, TOTALSEG_TIMEOUT_SECONDS

# Map platform labels → TotalSegmentator class names (v2).
LABEL_TO_ROI: dict[str, list[str]] = {
    "spleen": ["spleen"],
    "脾": ["spleen"],
    "脾脏": ["spleen"],
    "liver": ["liver"],
    "肝": ["liver"],
    "肝脏": ["liver"],
    "heart": ["heart"],
    "心": ["heart"],
    "心脏": ["heart"],
    "kidney": ["kidney_left", "kidney_right"],
    "kidney_left": ["kidney_left"],
    "kidney_right": ["kidney_right"],
    "left_kidney": ["kidney_left"],
    "right_kidney": ["kidney_right"],
    "肾": ["kidney_left", "kidney_right"],
    "左肾": ["kidney_left"],
    "右肾": ["kidney_right"],
    "pancreas": ["pancreas"],
    "stomach": ["stomach"],
    "gallbladder": ["gallbladder"],
    "left_lung": ["lung_upper_lobe_left", "lung_lower_lobe_left"],
    "right_lung": [
        "lung_upper_lobe_right",
        "lung_middle_lobe_right",
        "lung_lower_lobe_right",
    ],
    "lung": [
        "lung_upper_lobe_left",
        "lung_lower_lobe_left",
        "lung_upper_lobe_right",
        "lung_middle_lobe_right",
        "lung_lower_lobe_right",
    ],
    "肺": [
        "lung_upper_lobe_left",
        "lung_lower_lobe_left",
        "lung_upper_lobe_right",
        "lung_middle_lobe_right",
        "lung_lower_lobe_right",
    ],
    "左肺": ["lung_upper_lobe_left", "lung_lower_lobe_left"],
    "右肺": [
        "lung_upper_lobe_right",
        "lung_middle_lobe_right",
        "lung_lower_lobe_right",
    ],
}

# Official TotalSeg "organs" part (~24 classes) — good default for multi-organ.
ORGANS_ROI: list[str] = [
    "spleen",
    "kidney_right",
    "kidney_left",
    "gallbladder",
    "liver",
    "stomach",
    "pancreas",
    "adrenal_gland_right",
    "adrenal_gland_left",
    "lung_upper_lobe_left",
    "lung_lower_lobe_left",
    "lung_upper_lobe_right",
    "lung_middle_lobe_right",
    "lung_lower_lobe_right",
    "esophagus",
    "trachea",
    "thyroid_gland",
    "small_bowel",
    "duodenum",
    "colon",
    "urinary_bladder",
    "prostate",
    "kidney_cyst_left",
    "kidney_cyst_right",
]

MULTI_ORGAN_MODELS = {"totalseg_total", "totalseg_all", "totalseg_organs", "totalseg_multi"}


def is_multi_organ_model(model_id: str) -> bool:
    mid = (model_id or "").strip().lower()
    return mid in MULTI_ORGAN_MODELS or mid.endswith("_total") or mid.endswith("_organs")


def resolve_roi_subset(label: str, model_id: str = "") -> list[str] | None:
    """Return roi_subset list, or None to run full TotalSeg (all classes)."""
    mid = (model_id or "").strip().lower()
    if mid in {"totalseg_total", "totalseg_all"}:
        return None
    if mid in {"totalseg_organs", "totalseg_multi"}:
        return list(ORGANS_ROI)

    key = (label or "").strip().lower()
    if key in {"all", "total", "multi", "organs"}:
        return list(ORGANS_ROI) if key == "organs" else None
    if key in LABEL_TO_ROI:
        return list(LABEL_TO_ROI[key])
    for organ, rois in LABEL_TO_ROI.items():
        if organ in mid or organ in key:
            return list(rois)
    return ["spleen"]


def ensure_totalseg_ready() -> Path:
    python = Path(TOTALSEG_PYTHON)
    if not python.exists():
        raise FileNotFoundError(
            f"TOTALSEG_PYTHON not found: {python}. "
            "Install TotalSegmentator in that env: pip install TotalSegmentator"
        )
    probe = subprocess.run(
        [str(python), "-c", "import totalsegmentator; print('ok')"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        raise FileNotFoundError(
            f"totalsegmentator not importable with {python}: {detail}. "
            "Run: pip install TotalSegmentator"
        )
    return python


def _resolve_device() -> str:
    value = (TOTALSEG_DEVICE or "auto").strip().lower()
    if value in {"auto", ""}:
        try:
            import torch

            return "gpu" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    if value in {"cuda", "gpu"}:
        return "gpu"
    return "cpu"


def _use_fast(device: str) -> bool:
    raw = (TOTALSEG_FAST or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return device == "cpu"


def _write_nifti(array: np.ndarray, spacing: tuple[float, float, float], out_path: Path) -> None:
    import SimpleITK as sitk

    image = sitk.GetImageFromArray(np.asarray(array, dtype=np.float32))
    image.SetSpacing(tuple(float(v) for v in spacing[:3]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(image, str(out_path))


def _read_binary_mask(path: Path) -> np.ndarray:
    import SimpleITK as sitk

    array = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    return (np.asarray(array) > 0).astype(np.uint8)


def _resample_to_reference(
    mask: np.ndarray,
    reference_path: Path,
    mask_spacing_guess: tuple[float, float, float],
) -> np.ndarray:
    import SimpleITK as sitk

    reference = sitk.ReadImage(str(reference_path))
    ref_array = sitk.GetArrayFromImage(reference)
    if tuple(mask.shape[:3]) == tuple(ref_array.shape[:3]):
        return mask.astype(np.uint8, copy=False)

    mask_image = sitk.GetImageFromArray(mask.astype(np.uint8))
    mask_image.SetSpacing(tuple(float(v) for v in mask_spacing_guess[:3]))
    mask_image.SetOrigin(reference.GetOrigin())
    mask_image.SetDirection(reference.GetDirection())
    resampled = sitk.Resample(
        mask_image,
        reference,
        sitk.Transform(),
        sitk.sitkNearestNeighbor,
        0,
        sitk.sitkUInt8,
    )
    return (sitk.GetArrayFromImage(resampled) > 0).astype(np.uint8)


def _merge_roi_masks(output_dir: Path, rois: list[str]) -> np.ndarray | None:
    merged = None
    for roi in rois:
        candidates = [
            output_dir / f"{roi}.nii.gz",
            output_dir / f"{roi}.nii",
            output_dir / "segmentations" / f"{roi}.nii.gz",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            continue
        part = _read_binary_mask(path)
        merged = part if merged is None else np.maximum(merged, part)
    return merged


def _collect_organ_masks(
    output_dir: Path,
    reference_path: Path,
    spacing: tuple[float, float, float],
    target_shape: tuple[int, int, int],
    allowed: set[str] | None = None,
) -> dict[str, np.ndarray]:
    """Load each non-empty organ nifti from TotalSeg output folder."""
    results: dict[str, np.ndarray] = {}
    search_roots = [output_dir, output_dir / "segmentations"]
    files: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        files.extend(sorted(root.glob("*.nii.gz")))
        files.extend(sorted(root.glob("*.nii")))

    for path in files:
        name = path.name
        if name.endswith(".nii.gz"):
            label = name[: -len(".nii.gz")]
        else:
            label = path.stem
        if label.lower() in {"ct", "image", "input"}:
            continue
        if allowed is not None and label not in allowed:
            continue
        mask = _read_binary_mask(path)
        if tuple(mask.shape[:3]) != target_shape:
            mask = _resample_to_reference(mask, reference_path, spacing)
        if tuple(mask.shape[:3]) != target_shape:
            continue
        if not np.any(mask):
            continue
        results[label] = mask.astype(np.uint8)
    return results


def _run_totalseg_subprocess(
    python: Path,
    input_nifti: Path,
    output_dir: Path,
    rois: list[str] | None,
    device: str,
    fast: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    roi_arg = "None" if rois is None else repr(rois)
    script = f"""
from totalsegmentator.python_api import totalsegmentator
totalsegmentator(
    input=r'''{input_nifti}''',
    output=r'''{output_dir}''',
    task='total',
    roi_subset={roi_arg},
    device='{device}',
    fast={fast!r},
    quiet=True,
    nr_thr_resamp=1,
    nr_thr_saving=1,
)
print('totalseg_done')
"""
    result = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
        timeout=int(TOTALSEG_TIMEOUT_SECONDS),
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"TotalSegmentator failed: {detail[-2000:]}")


def predict_totalseg_volume(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    *,
    label: str = "spleen",
    model_id: str = "totalseg_spleen",
) -> np.ndarray:
    """Return binary mask [D,H,W] for a single-organ request (merged if multi-ROI)."""
    organs = predict_totalseg_organs(volume, spacing, label=label, model_id=model_id)
    if not organs:
        raise RuntimeError("TotalSegmentator produced empty organ masks")
    rois = resolve_roi_subset(label, model_id)
    if rois and len(rois) == 1 and rois[0] in organs:
        return organs[rois[0]]
    if label in organs:
        return organs[label]
    merged = None
    for mask in organs.values():
        merged = mask if merged is None else np.maximum(merged, mask)
    assert merged is not None
    return merged


def predict_totalseg_organs(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
    *,
    label: str = "spleen",
    model_id: str = "totalseg_spleen",
) -> dict[str, np.ndarray]:
    """Return {organ_name: binary_mask} for all non-empty organs in this run."""
    python = ensure_totalseg_ready()
    rois = resolve_roi_subset(label, model_id)
    device = _resolve_device()
    fast = _use_fast(device)
    target_shape = tuple(int(v) for v in volume.shape[:3])

    with tempfile.TemporaryDirectory(prefix="totalseg_predict_") as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / "ct.nii.gz"
        output_dir = tmp_path / "seg"
        _write_nifti(volume, spacing, input_path)
        _run_totalseg_subprocess(python, input_path, output_dir, rois, device, fast)

        allowed = set(rois) if rois is not None else None
        organs = _collect_organ_masks(
            output_dir,
            input_path,
            spacing,
            target_shape,
            allowed=allowed,
        )
        if organs:
            return organs

        # Fallback: single merged mask for single-organ requests
        if rois:
            merged = _merge_roi_masks(output_dir, rois)
            if merged is not None:
                if tuple(merged.shape[:3]) != target_shape:
                    merged = _resample_to_reference(merged, input_path, spacing)
                if np.any(merged):
                    name = rois[0] if len(rois) == 1 else (label or "organ")
                    return {name: merged.astype(np.uint8)}
        raise RuntimeError(f"TotalSegmentator produced no mask files (rois={rois})")
