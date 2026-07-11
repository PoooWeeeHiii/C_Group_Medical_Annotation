"""Per-case ``metadata.json`` helpers (docs/01 section 8).

Attributes that are not part of the eight core tables (status, spacing, ...) are
persisted here, one JSON file per case under ``dataset/raw/<case_id>/``.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import RAW_DIR, DEFAULT_CASE_STATUS


def metadata_path(case_id: str) -> Path:
    return RAW_DIR / case_id / "metadata.json"


def write_metadata(case_id: str, data: dict) -> None:
    path = metadata_path(case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def read_metadata(case_id: str) -> dict:
    path = metadata_path(case_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def get_status(case_id: str) -> str:
    return read_metadata(case_id).get("annotation_status", DEFAULT_CASE_STATUS)
