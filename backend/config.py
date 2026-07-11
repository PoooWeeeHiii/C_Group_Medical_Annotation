"""Central configuration for the backend.

Paths are resolved relative to the repository root so the app behaves the same
regardless of the current working directory. Values can be overridden with
environment variables to ease deployment.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATASET_ROOT = Path(os.environ.get("DATASET_ROOT", PROJECT_ROOT / "dataset")).resolve()
RAW_DIR = DATASET_ROOT / "raw"

DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'label_platform.db'}"
)

# Default status for a freshly imported case (docs/01 case status vocabulary).
DEFAULT_CASE_STATUS = "unannotated"


def stored_rel(abs_path: Path) -> str:
    """Convert an absolute path under DATASET_ROOT into the value stored in the
    DB and returned to clients, e.g. ``dataset/raw/Case0001/image/foo.nii.gz``.

    Works regardless of where DATASET_ROOT lives (it need not be inside the repo).
    """
    rel = Path(abs_path).resolve().relative_to(DATASET_ROOT).as_posix()
    return f"{DATASET_ROOT.name}/{rel}"


def resolve_stored(rel_path: str) -> Path:
    """Resolve a stored path (see ``stored_rel``) back to an absolute path."""
    return DATASET_ROOT.parent / rel_path
