"""Test fixtures.

Environment variables are set *before* importing the backend so that the app
uses an isolated temp SQLite DB and dataset root instead of the dev database.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

_TMP = Path(tempfile.mkdtemp(prefix="labelplatform_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["DATASET_ROOT"] = str(_TMP / "dataset")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def synthetic_nifti() -> Path:
    """A small 3D volume (20 slices) with a centered sphere."""
    D, H, W = 20, 32, 32
    zz, yy, xx = np.mgrid[0:D, 0:H, 0:W]
    r = np.sqrt((zz - D // 2) ** 2 + (yy - H // 2) ** 2 + (xx - W // 2) ** 2)
    vol = np.where(r < 8, 900, -500).astype(np.int16)
    img = sitk.GetImageFromArray(vol)
    img.SetSpacing((1.0, 1.0, 3.0))
    out = _TMP / "synthetic_ct.nii.gz"
    sitk.WriteImage(img, str(out))
    return out
