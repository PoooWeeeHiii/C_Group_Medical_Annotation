"""Export a contract-aligned MONAI 3D UNet init checkpoint for DeepEdit.

Creates models/deepedit/deepedit_unet.pth matching ai/deepedit_config.example.json
so /health can report model_loaded=true before any training.

Usage:
  python scripts/export_deepedit_init_checkpoint.py
  python scripts/export_deepedit_init_checkpoint.py --config models/deepedit/config.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "models" / "deepedit" / "config.json"
EXAMPLE_CONFIG = PROJECT_ROOT / "ai" / "deepedit_config.example.json"


def _load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"Config must be a JSON object: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Export DeepEdit MONAI init checkpoint")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG,
        help="Path to DeepEdit config JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output .pth path (default: config.path or models/deepedit/deepedit_unet.pth)",
    )
    args = parser.parse_args()

    try:
        import torch
        from monai.networks.nets import UNet
    except ImportError as exc:
        raise SystemExit(
            "torch and monai are required. Install from requirements.txt "
            "(e.g. pip install torch monai)."
        ) from exc

    config = _load_config(args.config.resolve())
    in_channels = int(config.get("in_channels", 4))
    out_channels = int(config.get("out_channels", 2))
    channels = tuple(int(v) for v in config.get("channels", [16, 32, 64, 128, 256]))
    strides = tuple(int(v) for v in config.get("strides", [2, 2, 2, 2]))
    num_res_units = int(config.get("num_res_units", 2))

    output = args.output
    if output is None:
        raw = config.get("path") or "models/deepedit/deepedit_unet.pth"
        output = Path(raw)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    model = UNet(
        spatial_dims=3,
        in_channels=in_channels,
        out_channels=out_channels,
        channels=channels,
        strides=strides,
        num_res_units=num_res_units,
    )
    model.eval()

    payload = {
        "state_dict": model.state_dict(),
        "config": {
            "format": "monai_unet_checkpoint",
            "in_channels": in_channels,
            "out_channels": out_channels,
            "channels": list(channels),
            "strides": list(strides),
            "num_res_units": num_res_units,
        },
        "note": "random-init checkpoint; train with scripts/train_deepedit.py for usable DeepEdit",
    }
    torch.save(payload, str(output))

    # Smoke forward to verify shapes.
    dummy = torch.zeros(1, in_channels, 32, 64, 64)
    with torch.inference_mode():
        out = model(dummy)
    print(f"Wrote {output}")
    print(f"UNet in={in_channels} out={out_channels} channels={channels} strides={strides}")
    print(f"Smoke forward: input {tuple(dummy.shape)} -> output {tuple(out.shape)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
