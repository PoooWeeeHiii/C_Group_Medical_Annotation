"""System-test fixtures: live HTTP client against running uvicorn."""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

BASE_URL = os.getenv("SYSTEM_TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SYSTEM_TEST_TIMEOUT", "60"))


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def client(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as c:
        try:
            r = c.get("/api/health")
        except httpx.HTTPError as exc:
            pytest.exit(
                f"System under test unreachable at {base_url}: {exc}. "
                "Start backend: uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
                returncode=2,
            )
        if r.status_code != 200:
            pytest.exit(f"/api/health returned {r.status_code}: {r.text}", returncode=2)
        yield c


def login(client: httpx.Client, username: str, password: str) -> dict[str, Any]:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("success") is True
    assert data.get("access_token")
    return data


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def annotator_token(client: httpx.Client) -> str:
    return login(client, "annotator", "annotator123")["access_token"]


@pytest.fixture(scope="session")
def reviewer_token(client: httpx.Client) -> str:
    return login(client, "reviewer", "reviewer123")["access_token"]


@pytest.fixture(scope="session")
def admin_token(client: httpx.Client) -> str:
    return login(client, "admin", "admin123")["access_token"]


@pytest.fixture(scope="session")
def sample_case(client: httpx.Client) -> dict[str, Any]:
    """Prefer a multi-slice case suitable for volume APIs."""
    cases = client.get("/api/cases").json()["items"]
    assert cases, "No cases in system under test"
    preferred = {"Case0002", "Case0003", "Case0004"}
    for item in cases:
        if item["case_id"] in preferred:
            detail = client.get(f"/api/case/{item['case_id']}").json()
            assert detail["success"] is True
            return detail
    detail = client.get(f"/api/case/{cases[0]['case_id']}").json()
    assert detail["success"] is True
    return detail


@pytest.fixture(scope="session")
def sample_image_id(sample_case: dict[str, Any]) -> str:
    images = sample_case["images"]
    assert images, "Selected case has no images"
    return str(images[0]["image_id"])


@pytest.fixture(scope="session")
def sample_case_id(sample_case: dict[str, Any]) -> str:
    return str(sample_case["case"]["case_id"])
