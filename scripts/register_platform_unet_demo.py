"""Register finished platform U-Net checkpoint into model list."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from backend.app.services.model_service import register_model

ROOT = Path(__file__).resolve().parents[1]
metrics_path = ROOT / "ai" / "runs" / "ModelUNet_PersonB_Demo_metrics.json"
metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
print("best", metrics.get("best_val_dice"), "epochs", metrics.get("epochs"))
register_model(
    model_id=str(metrics["model_id"]),
    version=str(metrics["model_id"]),
    label="multiclass",
    display_name=f"Platform U-Net 2.5D ({metrics['model_id']})",
    path=metrics.get("checkpoint"),
    dice=float(metrics["best_val_dice"]) if metrics.get("best_val_dice") is not None else None,
    description=f"Trained on {metrics.get('dataset_id')}; Person B demo platform U-Net.",
    backend="platform_unet",
)
print("registered", metrics["model_id"])

raw = urllib.request.urlopen("http://127.0.0.1:8000/api/train").read().decode()
data = json.loads(re.sub(r"\bNaN\b", "null", raw))
for job in data.get("items") or []:
    mid = str(job.get("model_id") or "")
    jid = str(job.get("job_id") or "")
    if "PersonB_Demo" in mid or "Platform_ModelUNet" in jid:
        print(
            jid,
            job.get("status"),
            "val",
            job.get("val_dice"),
            "best",
            (job.get("metrics") or {}).get("best_val_dice"),
        )
