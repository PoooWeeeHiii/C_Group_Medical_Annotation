from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "deepedit" / "model.ts"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "models" / "deepedit" / "config.json"


class DeepEditInferRequest(BaseModel):
    case_id: str
    image_id: str
    image_path: str
    current_mask_id: str | None = None
    current_mask_path: str | None = None
    label: str = "label"
    model_id: str | None = "DeepEdit"
    positive_points: list[list[float]] = []
    negative_points: list[list[float]] = []
    scribbles: list[dict[str, Any]] = []
    interaction: dict[str, Any] = {}
    confirmed_slices: list[int] = []
    output_version: str = "v3_preview"


app = FastAPI(title="DeepEdit Inference Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_MODEL = None
_DEVICE = None
_MODEL_ERROR: str | None = None
_MODEL_INFO: dict[str, Any] = {}
_MODEL_MTIME: float | None = None


def _resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _model_path() -> Path:
    config = _model_config()
    path = _resolve_project_path(os.getenv("DEEPEDIT_MODEL_PATH")) or DEFAULT_MODEL_PATH
    if config.get("path"):
        path = _resolve_project_path(str(config["path"])) or path
    return path


def _model_config() -> dict[str, Any]:
    config_path = _resolve_project_path(os.getenv("DEEPEDIT_CONFIG_PATH")) or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"DeepEdit config must be a JSON object: {config_path}")
    return data


def _model_format(path: Path, config: dict[str, Any]) -> str:
    value = str(config.get("format") or os.getenv("DEEPEDIT_MODEL_FORMAT") or "").strip().lower()
    if value:
        return value
    if path.suffix in {".ts", ".torchscript"}:
        return "torchscript"
    if path.suffix in {".pt", ".pth"}:
        return "monai_unet_checkpoint"
    return "torchscript"


def _target_device():
    import torch

    value = os.getenv("DEEPEDIT_DEVICE", "auto").strip().lower()
    if value == "auto":
        value = "cuda" if torch.cuda.is_available() else "cpu"
    if value == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("DEEPEDIT_DEVICE=cuda but CUDA is not available")
    return torch.device(value)


def _checkpoint_state_dict(checkpoint: Any) -> dict[str, Any]:
    if isinstance(checkpoint, dict):
        for key in ("state_dict", "model_state_dict", "network", "net"):
            value = checkpoint.get(key)
            if isinstance(value, dict):
                checkpoint = value
                break
    if not isinstance(checkpoint, dict):
        raise RuntimeError("DeepEdit checkpoint must contain a PyTorch state_dict")
    # Only strip DataParallel wrapping. Do NOT strip "model." — MONAI UNet keys
    # legitimately look like "model.0.conv...."
    cleaned: dict[str, Any] = {}
    for key, value in checkpoint.items():
        name = str(key)
        if name.startswith("module."):
            name = name[len("module."):]
        cleaned[name] = value
    return cleaned


def _align_state_dict_keys(state_dict: dict[str, Any], model_keys: set[str]) -> dict[str, Any]:
    """Optionally strip wrapper prefixes when checkpoint keys do not match the model."""
    if set(state_dict).issubset(model_keys) or set(state_dict) == model_keys:
        return state_dict
    for prefix in ("model.", "network.", "net."):
        remapped = {}
        for key, value in state_dict.items():
            name = str(key)
            if name.startswith(prefix):
                name = name[len(prefix):]
            remapped[name] = value
        if set(remapped).issubset(model_keys) or len(set(remapped) & model_keys) > len(set(state_dict) & model_keys):
            return remapped
    return state_dict


def _load_monai_unet_checkpoint(path: Path, config: dict[str, Any], device):
    import torch
    from monai.networks.nets import UNet

    in_channels = int(config.get("in_channels", os.getenv("DEEPEDIT_IN_CHANNELS", "4")))
    out_channels = int(config.get("out_channels", os.getenv("DEEPEDIT_OUT_CHANNELS", "2")))
    channels = tuple(int(value) for value in config.get("channels", [16, 32, 64, 128, 256]))
    strides = tuple(int(value) for value in config.get("strides", [2, 2, 2, 2]))
    num_res_units = int(config.get("num_res_units", os.getenv("DEEPEDIT_NUM_RES_UNITS", "2")))
    strict = str(config.get("strict", os.getenv("DEEPEDIT_STRICT_LOAD", "true"))).lower() != "false"
    model = UNet(
        spatial_dims=3,
        in_channels=in_channels,
        out_channels=out_channels,
        channels=channels,
        strides=strides,
        num_res_units=num_res_units,
    ).to(device)
    checkpoint = torch.load(str(path), map_location=device, weights_only=False)
    state_dict = _align_state_dict_keys(_checkpoint_state_dict(checkpoint), set(model.state_dict().keys()))
    missing, unexpected = model.load_state_dict(state_dict, strict=strict)
    if strict is False and (missing or unexpected):
        _MODEL_INFO["load_warnings"] = {
            "missing": [str(item) for item in missing],
            "unexpected": [str(item) for item in unexpected],
        }
    return model


def _load_model():
    global _MODEL, _DEVICE, _MODEL_ERROR, _MODEL_INFO, _MODEL_MTIME
    try:
        import torch

        config = _model_config()
        path = _model_path()
        if not path.exists():
            raise FileNotFoundError(f"DeepEdit model weights not found: {path}")
        mtime = path.stat().st_mtime
        if _MODEL is not None and _MODEL_MTIME == mtime:
            return _MODEL, _DEVICE
        _DEVICE = _target_device()
        model_format = _model_format(path, config)
        if model_format == "torchscript":
            model = torch.jit.load(str(path), map_location=_DEVICE)
        elif model_format in {"monai_unet_checkpoint", "monai_unet", "pth"}:
            model = _load_monai_unet_checkpoint(path, config, _DEVICE)
        else:
            raise RuntimeError(f"Unsupported DEEPEDIT_MODEL_FORMAT: {model_format}")
        model.eval()
        _MODEL = model
        _MODEL_MTIME = mtime
        _MODEL_INFO = {
            **_MODEL_INFO,
            "model_format": model_format,
            "model_path": str(path),
            "config_path": str(_resolve_project_path(os.getenv("DEEPEDIT_CONFIG_PATH")) or DEFAULT_CONFIG_PATH),
            "model_mtime": mtime,
        }
        _MODEL_ERROR = None
        return _MODEL, _DEVICE
    except Exception as exc:  # Keep service alive; main backend can fallback.
        _MODEL = None
        _DEVICE = None
        _MODEL_MTIME = None
        _MODEL_ERROR = str(exc)
        return None, None


def _resolve_volume_path(path: Path) -> Path:
    """If path is a zip, extract and return the CT volume file inside (not label)."""
    if path.suffix.lower() != ".zip":
        return path
    import tempfile
    from zipfile import ZipFile

    # Persist extract next to zip so repeated infer calls reuse it.
    extract_dir = path.parent / f"{path.stem}_deepedit_extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    marker = extract_dir / ".extracted"
    if not marker.exists():
        with ZipFile(path) as archive:
            archive.extractall(extract_dir)
        marker.write_text("ok", encoding="utf-8")

    nrrd_files = [p for p in extract_dir.rglob("*.nrrd") if "label" not in p.name.lower() and "mask" not in p.name.lower()]
    nii_files = [
        p
        for p in list(extract_dir.rglob("*.nii")) + list(extract_dir.rglob("*.nii.gz"))
        if "label" not in p.name.lower() and "mask" not in p.name.lower()
    ]
    candidates = nrrd_files or nii_files
    if not candidates:
        # Last resort: any nrrd/nii
        candidates = list(extract_dir.rglob("*.nrrd")) + list(extract_dir.rglob("*.nii")) + list(extract_dir.rglob("*.nii.gz"))
    if not candidates:
        raise FileNotFoundError(f"No CT volume found inside zip: {path}")
    return candidates[0]


def _read_image(path: Path):
    import SimpleITK as sitk

    path = _resolve_volume_path(path)
    try:
        image = sitk.ReadImage(str(path))
        array = sitk.GetArrayFromImage(image).astype(np.float32, copy=False)
        if array.ndim == 2:
            array = array.reshape((1, array.shape[0], array.shape[1]))
        return sitk, image, array
    except RuntimeError:
        # Some TotalSeg NIfTI files have non-orthonormal direction cosines.
        import nibabel as nib

        nii = nib.load(str(path))
        array = np.asanyarray(nii.dataobj)
        if array.ndim == 3:
            array = np.transpose(array, (2, 1, 0))
        elif array.ndim == 2:
            array = array.reshape((1, array.shape[1], array.shape[0]))
        array = array.astype(np.float32, copy=False)
        image = sitk.GetImageFromArray(array)
        zooms = [float(v) for v in nii.header.get_zooms()[:3]]
        # nibabel zooms are XYZ; SimpleITK spacing is XYZ after GetImageFromArray (Z Y X array).
        if len(zooms) == 3:
            image.SetSpacing((zooms[0], zooms[1], zooms[2]))
        return sitk, image, array


def _read_current_mask(path: Path | None, shape: tuple[int, int, int]) -> np.ndarray:
    if path is None or not path.exists():
        return np.zeros(shape, dtype=np.float32)
    try:
        import SimpleITK as sitk

        array = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
    except Exception:
        import nibabel as nib

        array = np.asanyarray(nib.load(str(path)).dataobj)
        if array.ndim == 3:
            array = np.transpose(array, (2, 1, 0))
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    if tuple(array.shape[:3]) != shape:
        return np.zeros(shape, dtype=np.float32)
    return (array > 0).astype(np.float32, copy=False)


def _draw_seed_sphere(channel: np.ndarray, point: list[float], value: float, radius: int = 4) -> None:
    if len(point) < 3:
        return
    depth, height, width = channel.shape[:3]
    x = max(0, min(int(round(float(point[0]))), width - 1))
    y = max(0, min(int(round(float(point[1]))), height - 1))
    z = max(0, min(int(round(float(point[2]))), depth - 1))
    z0, z1 = max(0, z - radius), min(depth, z + radius + 1)
    y0, y1 = max(0, y - radius), min(height, y + radius + 1)
    x0, x1 = max(0, x - radius), min(width, x + radius + 1)
    zz, yy, xx = np.ogrid[z0:z1, y0:y1, x0:x1]
    channel[z0:z1, y0:y1, x0:x1][
        (zz - z) ** 2 + (yy - y) ** 2 + (xx - x) ** 2 <= radius * radius
    ] = value


def _normalize_axis(axis: str) -> str:
    value = (axis or "axial").strip().lower()
    if value in {"axial", "z", "xy"}:
        return "axial"
    if value in {"coronal", "y", "xz"}:
        return "coronal"
    if value in {"sagittal", "x", "yz"}:
        return "sagittal"
    return "axial"


def _scribble_prompt_points(scribbles: list[dict[str, Any]], prompt_type: str) -> list[list[float]]:
    """Convert 2D canvas scribbles into voxel XYZ points (same contract as mask_service)."""
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
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                x = float(point[0])
                y = float(point[1])
                z = float(point[2]) if len(point) >= 3 else float(slice_index)
            elif isinstance(point, dict):
                x = float(point.get("x", 0))
                y = float(point.get("y", 0))
                z = float(point.get("z", slice_index))
            else:
                continue
            if axis == "axial":
                output.append([x, y, z])
            elif axis == "coronal":
                output.append([x, z, y])
            else:
                output.append([z, x, y])
    return output


def _prompt_channels(
    shape: tuple[int, int, int],
    positive: list[list[float]],
    negative: list[list[float]],
    scribbles: list[dict[str, Any]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    positive_channel = np.zeros(shape, dtype=np.float32)
    negative_channel = np.zeros(shape, dtype=np.float32)
    positive_points = list(positive or [])
    negative_points = list(negative or [])
    positive_points.extend(_scribble_prompt_points(scribbles or [], "positive"))
    negative_points.extend(_scribble_prompt_points(scribbles or [], "negative"))
    for point in positive_points:
        _draw_seed_sphere(positive_channel, point, 1.0)
    for point in negative_points:
        _draw_seed_sphere(negative_channel, point, 1.0)
    return positive_channel, negative_channel


def _normalize_ct(array: np.ndarray) -> np.ndarray:
    return np.clip((array + 1000.0) / 2000.0, 0.0, 1.0).astype(np.float32, copy=False)


def _apply_confirmed_slices(
    prediction: np.ndarray,
    current_mask: np.ndarray,
    confirmed_slices: list[int] | None,
) -> np.ndarray:
    """Hard-write confirmed axial slices from current_mask so they are never overwritten."""
    if not confirmed_slices:
        return prediction
    output = prediction.copy()
    depth = output.shape[0]
    for raw in confirmed_slices:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= index < depth:
            output[index] = (current_mask[index] > 0).astype(np.uint8, copy=False)
    return output


def _pad_to_factor(volume: np.ndarray, factor: int = 16) -> tuple[np.ndarray, tuple[int, int, int]]:
    depth, height, width = volume.shape[:3]
    pad_d = (factor - depth % factor) % factor
    pad_h = (factor - height % factor) % factor
    pad_w = (factor - width % factor) % factor
    if pad_d == 0 and pad_h == 0 and pad_w == 0:
        return volume, (depth, height, width)
    padded = np.pad(volume, ((0, pad_d), (0, pad_h), (0, pad_w)), mode="constant", constant_values=0)
    return padded, (depth, height, width)


def _run_model(volume: np.ndarray, positive: np.ndarray, negative: np.ndarray, current_mask: np.ndarray) -> np.ndarray | None:
    model, device = _load_model()
    if model is None or device is None:
        return None

    import torch

    original_shape = tuple(int(v) for v in volume.shape[:3])
    volume_p, _ = _pad_to_factor(volume)
    positive_p, _ = _pad_to_factor(positive)
    negative_p, _ = _pad_to_factor(negative)
    current_p, _ = _pad_to_factor(current_mask)

    channels = np.stack([_normalize_ct(volume_p), positive_p, negative_p, current_p], axis=0)
    tensor = torch.from_numpy(channels[None]).to(device=device, dtype=torch.float32)
    with torch.inference_mode():
        try:
            output = model(tensor)
        except TypeError:
            output = model({"image": tensor})
        if isinstance(output, dict):
            for key in ("pred", "logits", "output"):
                if key in output:
                    output = output[key]
                    break
            else:
                raise RuntimeError("DeepEdit model returned a dict without pred/logits/output")
        if isinstance(output, (list, tuple)):
            output = output[0]
        if output is None:
            raise RuntimeError("DeepEdit model returned None")
        output = output.detach()
        if output.ndim == 5:
            channel_index = 1 if output.shape[1] > 1 else 0
            output = output[0, channel_index]
        elif output.ndim == 4:
            channel_index = 1 if output.shape[0] > 1 else 0
            output = output[channel_index]
        if torch.min(output) < 0 or torch.max(output) > 1:
            output = torch.sigmoid(output)
        probabilities = output.detach().cpu().numpy()
    threshold = float(os.getenv("DEEPEDIT_THRESHOLD", "0.5"))
    mask = (probabilities >= threshold).astype(np.uint8)
    d, h, w = original_shape
    return mask[:d, :h, :w]


def _write_mask_base64(sitk_module, reference_image, mask: np.ndarray) -> str:
    output = sitk_module.GetImageFromArray(mask.astype(np.uint8, copy=False))
    output.CopyInformation(reference_image)
    # Windows cannot rewrite a still-open NamedTemporaryFile; close first.
    tmp = tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        sitk_module.WriteImage(output, str(tmp_path))
        return base64.b64encode(tmp_path.read_bytes()).decode("ascii")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False
    model, device = _load_model()
    return {
        "success": model is not None,
        "model_path": str(_model_path()),
        "model_loaded": model is not None,
        "model_error": _MODEL_ERROR,
        "model_info": _MODEL_INFO,
        "device": str(device) if device is not None else None,
        "cuda_available": cuda_available,
    }


@app.post("/infer")
def infer(request: DeepEditInferRequest) -> dict[str, Any]:
    model, device = _load_model()
    if model is None:
        return {
            "success": False,
            "model_status": "missing_or_invalid_model",
            "message": _MODEL_ERROR or "DeepEdit model is not loaded",
        }

    image_path = _resolve_project_path(request.image_path)
    if image_path is None or not image_path.exists():
        return {"success": False, "model_status": "missing_image", "message": f"Image not found: {request.image_path}"}

    sitk, image, volume = _read_image(image_path)
    current_mask = _read_current_mask(_resolve_project_path(request.current_mask_path), tuple(volume.shape[:3]))
    positive, negative = _prompt_channels(
        tuple(volume.shape[:3]),
        request.positive_points,
        request.negative_points,
        request.scribbles,
    )
    mask = _run_model(volume, positive, negative, current_mask)
    if mask is None:
        return {
            "success": False,
            "model_status": "missing_or_invalid_model",
            "message": _MODEL_ERROR or "DeepEdit model is not loaded",
        }
    mask = _apply_confirmed_slices(mask, current_mask, request.confirmed_slices)

    return {
        "success": True,
        "model_status": "remote_model",
        "model_id": request.model_id,
        "message": f"DeepEdit neural inference completed on {device}",
        "mask_base64": _write_mask_base64(sitk, image, mask),
        "shape": [int(value) for value in mask.shape[:3]],
        "spacing": [float(value) for value in image.GetSpacing()[:3]],
        "origin": [float(value) for value in image.GetOrigin()[:3]],
        "direction": [float(value) for value in image.GetDirection()],
    }
