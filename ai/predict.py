from __future__ import annotations

import argparse
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
