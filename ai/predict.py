from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np


def _largest_components(mask: np.ndarray, keep: int = 1) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return mask.astype(np.uint8, copy=False)

    image = sitk.GetImageFromArray((mask > 0).astype(np.uint8))
    components = sitk.ConnectedComponent(image)
    relabeled = sitk.RelabelComponent(components, sortByObjectSize=True)
    output = np.zeros(mask.shape, dtype=np.uint8)
    for label_id in range(1, max(1, keep) + 1):
        output |= sitk.GetArrayFromImage(sitk.Equal(relabeled, label_id)).astype(np.uint8)
    return output.astype(np.uint8, copy=False)


def _close_mask(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    if radius <= 0:
        return mask.astype(np.uint8, copy=False)
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return mask.astype(np.uint8, copy=False)

    image = sitk.GetImageFromArray((mask > 0).astype(np.uint8))
    closed = sitk.BinaryMorphologicalClosing(image, [radius, radius, radius])
    return sitk.GetArrayFromImage(closed).astype(np.uint8)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return mask.astype(np.uint8, copy=False)

    image = sitk.GetImageFromArray((mask > 0).astype(np.uint8))
    filled = sitk.BinaryFillhole(image, fullyConnected=False)
    return sitk.GetArrayFromImage(filled).astype(np.uint8)


def _bounding_box(mask: np.ndarray) -> tuple[int, int, int, int, int, int] | None:
    points = np.argwhere(mask > 0)
    if points.size == 0:
        return None
    z_min, y_min, x_min = points.min(axis=0)
    z_max, y_max, x_max = points.max(axis=0) + 1
    return int(z_min), int(z_max), int(y_min), int(y_max), int(x_min), int(x_max)


def _remove_border_components(mask: np.ndarray) -> np.ndarray:
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return mask.astype(np.uint8, copy=False)

    binary = (mask > 0).astype(np.uint8)
    depth, height, width = binary.shape[:3]
    components = sitk.ConnectedComponent(sitk.GetImageFromArray(binary))
    stats = sitk.LabelShapeStatisticsImageFilter()
    stats.Execute(components)
    output = np.zeros(binary.shape, dtype=np.uint8)
    for label_id in stats.GetLabels():
        x, y, _z, size_x, size_y, _size_z = stats.GetBoundingBox(label_id)
        touches_border = (
            x <= 0
            or y <= 0
            or x + size_x >= width
            or y + size_y >= height
        )
        if touches_border:
            continue
        output |= sitk.GetArrayFromImage(sitk.Equal(components, label_id)).astype(np.uint8)
    return output


def _select_spleen_component(mask: np.ndarray, body_mask: np.ndarray) -> np.ndarray:
    """Pick a compact lateral upper-abdominal soft-tissue component.

    The trained spleen repo supplied for this project does not include the
    checkpoint, so this fallback keeps the same nnU-Net-style postprocessing
    idea: connected component analysis + hole filling. It is only a baseline
    until a real nnU-Net/DeepEdit service is configured.
    """
    body_box = _bounding_box(body_mask)
    if body_box is None:
        return _largest_components(mask, keep=1)

    z_min, z_max, y_min, y_max, x_min, x_max = body_box
    z_span = max(1, z_max - z_min)
    y_span = max(1, y_max - y_min)
    x_span = max(1, x_max - x_min)

    roi = np.zeros(mask.shape, dtype=bool)
    roi[
        z_min + int(z_span * 0.28) : z_min + int(z_span * 0.82),
        y_min + int(y_span * 0.18) : y_min + int(y_span * 0.88),
        x_min:x_max,
    ] = True
    lateral_margin = max(2, int(x_span * 0.12))
    center_left = x_min + int(x_span * 0.36)
    center_right = x_min + int(x_span * 0.64)
    lateral = np.zeros(mask.shape, dtype=bool)
    lateral[:, :, x_min + lateral_margin : center_left] = True
    lateral[:, :, center_right : x_max - lateral_margin] = True

    candidate = (mask > 0) & roi & lateral
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError:
        return _largest_components(candidate, keep=1)

    components = sitk.ConnectedComponent(sitk.GetImageFromArray(candidate.astype(np.uint8)))
    stats = sitk.LabelShapeStatisticsImageFilter()
    stats.Execute(components)
    labels = list(stats.GetLabels())
    if not labels:
        return _largest_components(candidate, keep=1)

    body_center_x = (x_min + x_max) / 2.0
    body_center_z = (z_min + z_max) / 2.0
    best_label = None
    best_score = -math.inf
    for label_id in labels:
        bbox_x, bbox_y, bbox_z, size_x, size_y, size_z = stats.GetBoundingBox(label_id)
        voxels = float(stats.GetNumberOfPixels(label_id))
        if voxels < 80:
            continue
        cx = bbox_x + size_x / 2.0
        cz = bbox_z + size_z / 2.0
        lateral_score = abs(cx - body_center_x) / max(1.0, x_span / 2.0)
        upper_abdomen_score = 1.0 - abs(cz - body_center_z) / max(1.0, z_span / 2.0)
        compactness_penalty = max(size_x, size_y, size_z) / max(1.0, min(size_x, size_y, size_z))
        score = math.log1p(voxels) + 2.0 * lateral_score + upper_abdomen_score - 0.25 * compactness_penalty
        if score > best_score:
            best_score = score
            best_label = label_id

    if best_label is None:
        return _largest_components(candidate, keep=1)
    return sitk.GetArrayFromImage(sitk.Equal(components, best_label)).astype(np.uint8)


def _predict_spleen_baseline(data: np.ndarray) -> np.ndarray:
    body = _largest_components(data > -350, keep=1) > 0
    soft_tissue = (data >= 15) & (data <= 145) & body
    soft_tissue &= data < 180
    selected = _select_spleen_component(soft_tissue, body)
    selected = _close_mask(selected, radius=2)
    selected = _fill_holes(selected)
    return _largest_components(selected, keep=1)


def predict_mask_array(volume_array: np.ndarray, label: str = "label", model_id: str | None = None) -> np.ndarray:
    """Return a 3D uint8 mask for a CT volume.

    This is the built-in baseline inference implementation. It is deliberately
    deterministic and geometry-safe: the backend writes the returned array back
    with the original CT spacing/origin/direction. Person B can replace this
    function with a trained nnU-Net/MONAI/MedSAM predictor while preserving the
    same input/output contract.
    """
    data = volume_array.astype(np.float32, copy=False)
    label_key = (label or "label").strip().lower()
    model_key = (model_id or "builtin_ct_threshold").strip().lower()

    if "lung" in label_key or "lung" in model_key:
        # Air-filled lung parenchyma. Remove border-connected outside air, then
        # keep the two largest internal low-density components.
        mask = (data > -980) & (data < -320)
        mask = _remove_border_components(mask)
        mask = _largest_components(mask, keep=2)
        return _close_mask(mask, radius=1)

    if "bone" in label_key or "bone" in model_key:
        return _close_mask(data > 250, radius=1)

    if "tumor" in label_key or "lesion" in label_key or "nodule" in label_key:
        body_values = data[data > -500]
        if body_values.size:
            threshold = float(np.percentile(body_values, 98.5))
        else:
            threshold = float(np.percentile(data, 98.5))
        return _close_mask(data > threshold, radius=1)

    if "brain" in label_key or "brain" in model_key:
        mask = (data > 15) & (data < 95)
        return _largest_components(_close_mask(mask, radius=1), keep=1)

    if "spleen" in label_key or "spleen" in model_key or "脾" in label:
        return _predict_spleen_baseline(data)

    # Generic CT foreground baseline. This is not diagnosis-grade, but it is a
    # real voxel inference result and produces a valid v2_ai NIfTI mask.
    return _largest_components(data > -500, keep=1)


def _read_image(path: Path):
    try:
        import SimpleITK as sitk
    except ModuleNotFoundError as exc:
        raise RuntimeError("SimpleITK is required for CLI inference") from exc
    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image)
    return sitk, image, array


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Run CT segmentation inference and write a NIfTI mask.")
    parser.add_argument("--input", required=True, help="Input CT image path readable by SimpleITK.")
    parser.add_argument("--output", required=True, help="Output mask .nii.gz path.")
    parser.add_argument("--label", default="label", help="Target label name.")
    parser.add_argument("--model-id", default="builtin_ct_threshold", help="Model id or built-in protocol.")
    args = parser.parse_args()

    sitk, image, array = _read_image(Path(args.input))
    mask = predict_mask_array(array, label=args.label, model_id=args.model_id)
    output = sitk.GetImageFromArray(mask.astype(np.uint8, copy=False))
    output.CopyInformation(image)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(output, str(target))


if __name__ == "__main__":
    run_cli()
