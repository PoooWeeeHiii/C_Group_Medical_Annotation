from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.app.services.sqlite_service import connect, ensure_sqlite_ready, get_record, list_records, upsert_record


BUILTIN_MODELS: list[dict[str, Any]] = [
    {
        "model_id": "totalseg_organs",
        "version": "totalsegmentator_v2",
        "label": "organs",
        "display_name": "多器官 TotalSegmentator (Organs ~24)",
        "backend": "totalsegmentator",
        "description": "一次预测约 24 个腹部/胸部器官（脾肝肾肺叶等），每个器官单独存一条 v2_ai mask。推荐默认。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_total",
        "version": "totalsegmentator_v2",
        "label": "total",
        "display_name": "全量 TotalSegmentator (100+ 结构)",
        "backend": "totalsegmentator",
        "description": "一次跑 TotalSeg 全部分类（骨骼/肌肉等也包含），每个非空结构一条 mask。最慢，CPU 建议开 TOTALSEG_FAST。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_spleen",
        "version": "totalsegmentator_v2",
        "label": "spleen",
        "display_name": "脾脏 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "官方 TotalSegmentator（roi_subset=spleen）。需 TOTALSEG_PYTHON 已安装 TotalSegmentator；首次会下载权重。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_liver",
        "version": "totalsegmentator_v2",
        "label": "liver",
        "display_name": "肝脏 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "官方 TotalSegmentator（roi_subset=liver）。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_lung",
        "version": "totalsegmentator_v2",
        "label": "lung",
        "display_name": "肺部 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "官方 TotalSegmentator（五叶肺合并为一个 lung mask）。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_heart",
        "version": "totalsegmentator_v2",
        "label": "heart",
        "display_name": "心脏 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "官方 TotalSegmentator（roi_subset=heart）。与 DeepEdit label=heart 对齐。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_kidney",
        "version": "totalsegmentator_v2",
        "label": "kidney",
        "display_name": "双肾 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "官方 TotalSegmentator（左右肾合并为一个 kidney mask；也可用 left_kidney/right_kidney）。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_left_lung",
        "version": "totalsegmentator_v2",
        "label": "left_lung",
        "display_name": "左肺 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "左肺上下叶合并，对齐 DeepEdit label=left_lung。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "totalseg_right_lung",
        "version": "totalsegmentator_v2",
        "label": "right_lung",
        "display_name": "右肺 TotalSegmentator",
        "backend": "totalsegmentator",
        "description": "右肺三叶合并，对齐 DeepEdit label=right_lung。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "spleen_nnunetv2_task506",
        "version": "task506_3d_fullres",
        "label": "spleen",
        "display_name": "脾脏 nnU-Net v2 (Task506 3d_fullres)",
        "backend": "external_command_or_baseline",
        "description": "优先使用本地 SPLEEN_NNUNET_PYTHON/checkpoint（默认 3d_fullres）；否则 SPLEEN_NNUNET_PREDICT_COMMAND；再回退脾脏 CT baseline。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "Model0002",
        "version": "task506_3d_fullres",
        "label": "spleen",
        "display_name": "脾脏 nnU-Net (Model0002 / Person B)",
        "backend": "spleen_nnunet_local",
        "description": "Person B 注册的脾脏模型别名，映射到 Dataset506 本地 3d_fullres 权重。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "builtin_lung",
        "version": "baseline",
        "label": "lung",
        "display_name": "肺部 CT Baseline",
        "backend": "builtin_ct_threshold",
        "description": "低密度连通域肺部 baseline，仅用于流程演示。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "builtin_bone",
        "version": "baseline",
        "label": "bone",
        "display_name": "骨骼 CT Baseline",
        "backend": "builtin_ct_threshold",
        "description": "高密度骨骼 baseline。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
    {
        "model_id": "builtin_ct_threshold",
        "version": "baseline",
        "label": "label",
        "display_name": "通用 CT Foreground Baseline",
        "backend": "builtin_ct_threshold",
        "description": "通用前景阈值 baseline。",
        "dice": None,
        "path": None,
        "builtin": True,
    },
]


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _parse_metrics(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"raw": raw}
        except json.JSONDecodeError:
            return {"raw": raw}
    return None


def ensure_builtin_models() -> None:
    ensure_sqlite_ready()
    for item in BUILTIN_MODELS:
        existing = get_record("models", "model_id", item["model_id"])
        metrics = {
            "label": item["label"],
            "display_name": item["display_name"],
            "backend": item["backend"],
            "description": item["description"],
            "builtin": True,
            "external_ready": bool(os.getenv("SPLEEN_NNUNET_PREDICT_COMMAND"))
            if "spleen" in item["model_id"] and item.get("backend") != "totalsegmentator"
            else (
                bool(os.getenv("TOTALSEG_PYTHON") or True)
                if item.get("backend") == "totalsegmentator"
                else False
            ),
        }
        if existing is None:
            upsert_record(
                "models",
                {
                    "model_id": item["model_id"],
                    "version": item["version"],
                    "dice": item.get("dice"),
                    "path": item.get("path"),
                    "metrics_json": metrics,
                    "create_time": _now_iso(),
                },
            )
        else:
            current_metrics = _parse_metrics(existing.get("metrics_json")) or {}
            merged = {**current_metrics, **metrics}
            if existing.get("dice") is not None:
                merged["dice"] = existing.get("dice")
            upsert_record(
                "models",
                {
                    **existing,
                    "version": existing.get("version") or item["version"],
                    "metrics_json": merged,
                },
            )


def _model_public(record: dict[str, Any]) -> dict[str, Any]:
    metrics = _parse_metrics(record.get("metrics_json")) or {}
    model_id = str(record.get("model_id") or "")
    builtin_meta = next((item for item in BUILTIN_MODELS if item["model_id"] == model_id), None)
    label = str(metrics.get("label") or (builtin_meta or {}).get("label") or "label")
    display_name = str(
        metrics.get("display_name")
        or (builtin_meta or {}).get("display_name")
        or model_id
    )
    backend = str(metrics.get("backend") or (builtin_meta or {}).get("backend") or "registered")
    description = str(metrics.get("description") or (builtin_meta or {}).get("description") or "")
    external_ready = bool(metrics.get("external_ready"))
    if backend == "totalsegmentator":
        python_path = os.getenv("TOTALSEG_PYTHON") or str(
            Path(os.getenv("SPLEEN_NNUNET_ROOT", r"D:\hm_2_spleen"))
            / "venv_nnunet_cpu"
            / "Scripts"
            / "python.exe"
        )
        external_ready = Path(python_path).exists()
    elif "spleen" in model_id.lower() and backend != "totalsegmentator":
        external_ready = bool(os.getenv("SPLEEN_NNUNET_PREDICT_COMMAND"))
    return {
        "model_id": model_id,
        "version": str(record.get("version") or model_id),
        "label": label,
        "display_name": display_name,
        "backend": backend,
        "description": description,
        "dice": record.get("dice") if record.get("dice") is not None else metrics.get("dice"),
        "path": record.get("path"),
        "builtin": bool(metrics.get("builtin") or builtin_meta is not None),
        "external_ready": external_ready,
        "create_time": record.get("create_time"),
        "metrics": metrics,
    }


def list_models() -> list[dict[str, Any]]:
    ensure_builtin_models()
    records = list_records("models")
    by_id = {str(item.get("model_id")): item for item in records}
    ordered: list[dict[str, Any]] = []
    for builtin in BUILTIN_MODELS:
        if builtin["model_id"] in by_id:
            ordered.append(_model_public(by_id.pop(builtin["model_id"])))
    for leftover in sorted(by_id.values(), key=lambda item: str(item.get("create_time") or ""), reverse=True):
        model_id = str(leftover.get("model_id") or "")
        metrics = _parse_metrics(leftover.get("metrics_json")) or {}
        # Hide internal bookkeeping rows written by promote/refine pipelines.
        if model_id.startswith("promoted_from:") or model_id.startswith("deepedit_") or model_id.startswith("label_propagation"):
            continue
        if not metrics.get("display_name") and not metrics.get("label") and leftover.get("path") is None:
            # Skip placeholder / empty registry rows unless they look like real models.
            if "Model" in model_id and model_id != "ModelPlaceholder":
                continue
            if model_id == "ModelPlaceholder":
                continue
        ordered.append(_model_public(leftover))
    return ordered


def get_model(model_id: str) -> dict[str, Any]:
    ensure_builtin_models()
    record = get_record("models", "model_id", model_id)
    if record is None:
        builtin = next((item for item in BUILTIN_MODELS if item["model_id"] == model_id), None)
        if builtin is None:
            raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
        return _model_public(
            {
                "model_id": builtin["model_id"],
                "version": builtin["version"],
                "dice": builtin.get("dice"),
                "path": builtin.get("path"),
                "metrics_json": builtin,
                "create_time": _now_iso(),
            }
        )
    return _model_public(record)


def register_model(
    *,
    model_id: str,
    version: str | None = None,
    label: str = "label",
    display_name: str | None = None,
    path: str | None = None,
    dice: float | None = None,
    description: str | None = None,
    backend: str = "registered",
) -> dict[str, Any]:
    model_id = model_id.strip()
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")
    metrics = {
        "label": label or "label",
        "display_name": display_name or model_id,
        "backend": backend,
        "description": description or "",
        "builtin": False,
    }
    upsert_record(
        "models",
        {
            "model_id": model_id,
            "version": version or model_id,
            "dice": dice,
            "path": path,
            "metrics_json": metrics,
            "create_time": _now_iso(),
        },
    )
    return get_model(model_id)


def resolve_predict_label(model_id: str | None, label: str | None) -> tuple[str, str]:
    resolved_model = (model_id or "builtin_ct_threshold").strip() or "builtin_ct_threshold"
    try:
        model = get_model(resolved_model)
        resolved_label = (label or model.get("label") or "label").strip() or "label"
    except HTTPException:
        resolved_label = (label or "label").strip() or "label"
    return resolved_model, resolved_label
