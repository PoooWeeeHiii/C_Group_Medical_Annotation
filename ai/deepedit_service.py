from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI
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

_MODEL = None
_DEVICE = None
_MODEL_ERROR: str | None = None
_MODEL_INFO: dict[str, Any] = {}


def _resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _model_path() -> Path:
    return _resolve_project_path(os.getenv("DEEPEDIT_MODEL_PATH")) or DEFAULT_MODEL_PATH


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
    cleaned: dict[str, Any] = {}
    for key, value in checkpoint.items():
        name = str(key)
        for prefix in ("module.", "model.", "network.", "net."):
            if name.startswith(prefix):
                name = name[len(prefix):]
        cleaned[name] = value
    return cleaned


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
    checkpoint = torch.load(str(path), map_location=device)
    state_dict = _checkpoint_state_dict(checkpoint)
    missing, unexpected = model.load_state_dict(state_dict, strict=strict)
    if strict is False and (missing or unexpected):
        _MODEL_INFO["load_warnings"] = {
            "missing": [str(item) for item in missing],
            "unexpected": [str(item) for item in unexpected],
        }
    return model


def _load_model():
    global _MODEL, _DEVICE, _MODEL_ERROR, _MODEL_INFO
    if _MODEL is not None:
        return _MODEL, _DEVICE
    try:
        import torch

        config = _model_config()
        path = _model_path()
        if config.get("path"):
            path = _resolve_project_path(str(config["path"])) or path
        if not path.exists():
            raise FileNotFoundError(f"DeepEdit model weights not found: {path}")
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
        _MODEL_INFO = {
            **_MODEL_INFO,
            "model_format": model_format,
            "model_path": str(path),
            "config_path": str(_resolve_project_path(os.getenv("DEEPEDIT_CONFIG_PATH")) or DEFAULT_CONFIG_PATH),
        }
        _MODEL_ERROR = None
        return _MODEL, _DEVICE
    except Exception as exc:  # Keep service alive; main backend can fallback.
        _MODEL_ERROR = str(exc)
        return None, None


def _read_image(path: Path):
    import SimpleITK as sitk

    image = sitk.ReadImage(str(path))
    array = sitk.GetArrayFromImage(image).astype(np.float32, copy=False)
    if array.ndim == 2:
        array = array.reshape((1, array.shape[0], array.shape[1]))
    return sitk, image, array


def _read_current_mask(path: Path | None, shape: tuple[int, int, int]) -> np.ndarray:
    if path is None or not path.exists():
        return np.zeros(shape, dtype=np.float32)
    import SimpleITK as sitk

    array = sitk.GetArrayFromImage(sitk.ReadImage(str(path)))
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


def _prompt_channels(shape: tuple[int, int, int], positive: list[list[float]], negative: list[list[float]]) -> tuple[np.ndarray, np.ndarray]:
    positive_channel = np.zeros(shape, dtype=np.float32)
    negative_channel = np.zeros(shape, dtype=np.float32)
    for point in positive or []:
        _draw_seed_sphere(positive_channel, point, 1.0)
    for point in negative or []:
        _draw_seed_sphere(negative_channel, point, 1.0)
    return positive_channel, negative_channel


def _normalize_ct(array: np.ndarray) -> np.ndarray:
    return np.clip((array + 1000.0) / 2000.0, 0.0, 1.0).astype(np.float32, copy=False)


def _run_model(volume: np.ndarray, positive: np.ndarray, negative: np.ndarray, current_mask: np.ndarray) -> np.ndarray | None:
    model, device = _load_model()
    if model is None or device is None:
        return None

    import torch

    channels = np.stack([_normalize_ct(volume), positive, negative, current_mask], axis=0)
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
    return (probabilities >= threshold).astype(np.uint8)


def _write_mask_base64(sitk_module, reference_image, mask: np.ndarray) -> str:
    output = sitk_module.GetImageFromArray(mask.astype(np.uint8, copy=False))
    output.CopyInformation(reference_image)
    with tempfile.NamedTemporaryFile(suffix=".nii.gz") as tmp:
        sitk_module.WriteImage(output, tmp.name)
        return base64.b64encode(Path(tmp.name).read_bytes()).decode("ascii")


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
    positive, negative = _prompt_channels(tuple(volume.shape[:3]), request.positive_points, request.negative_points)
    mask = _run_model(volume, positive, negative, current_mask)
    if mask is None:
        return {
            "success": False,
            "model_status": "missing_or_invalid_model",
            "message": _MODEL_ERROR or "DeepEdit model is not loaded",
        }

    return {
        "success": True,
        "model_status": "remote_model",
        "model_id": request.model_id,
        "message": f"DeepEdit TorchScript inference completed on {device}",
        "mask_base64": _write_mask_base64(sitk, image, mask),
        "shape": [int(value) for value in mask.shape[:3]],
        "spacing": [float(value) for value in image.GetSpacing()[:3]],
        "origin": [float(value) for value in image.GetOrigin()[:3]],
        "direction": [float(value) for value in image.GetDirection()],
    }
