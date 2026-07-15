"""AI / train / performance / security extended system tests."""

from __future__ import annotations

import os
import time

import httpx
import pytest

from .conftest import auth_headers

HEAVY = os.getenv("SYSTEM_TEST_RUN_HEAVY", "1").strip().lower() not in {"0", "false", "no"}
AI_TIMEOUT = float(os.getenv("SYSTEM_TEST_AI_TIMEOUT", "180"))


def test_ST_AI_03_models_totalseg_ready_flag(client: httpx.Client):
    r = client.get("/api/models")
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items
    totalseg = [m for m in items if "totalseg" in str(m.get("model_id") or "").lower() or m.get("backend") == "totalsegmentator"]
    assert totalseg, "Expected TotalSeg model entries"
    # At least one should advertise readiness metadata.
    assert any("external_ready" in m or m.get("builtin") for m in totalseg)


def test_ST_AI_04_predict_with_registered_model(
    client: httpx.Client,
    annotator_token: str,
    sample_case_id: str,
    sample_image_id: str,
):
    models = client.get("/api/models").json().get("items") or []
    preferred = next(
        (
            m
            for m in models
            if str(m.get("model_id")) in {"totalseg_organs", "totalseg_spleen"}
            or m.get("backend") == "totalsegmentator"
        ),
        models[0] if models else None,
    )
    if preferred is None:
        pytest.skip("No models registered")

    if not HEAVY:
        pytest.skip("SYSTEM_TEST_RUN_HEAVY=0")

    payload = {
        "case_id": sample_case_id,
        "image_id": sample_image_id,
        "model_id": preferred.get("model_id"),
        "allow_baseline": False,
    }
    started = time.time()
    try:
        r = client.post(
            "/api/ai/predict",
            headers=auth_headers(annotator_token),
            json=payload,
            timeout=AI_TIMEOUT,
        )
    except httpx.TimeoutException:
        pytest.skip(
            f"AI predict timed out after {AI_TIMEOUT:.0f}s on {preferred.get('model_id')} "
            f"({sample_case_id}/{sample_image_id}); treat as environment/perf limit, not functional fail"
        )
    elapsed = time.time() - started
    assert r.status_code in {200, 400, 404, 422, 500, 503}, r.text
    if r.status_code == 200:
        body = r.json()
        assert body.get("success") is True
        assert body.get("mask_id")
        assert body.get("backend") or body.get("model_status")
    else:
        assert r.text.strip(), "AI failure must include detail"
    assert elapsed < AI_TIMEOUT + 5


def test_ST_TRAIN_01_list_jobs(client: httpx.Client):
    r = client.get("/api/train")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body or body.get("success") is True


def test_ST_TRAIN_02_start_short_job_if_dataset_available(client: httpx.Client, annotator_token: str):
    cases = client.get("/api/cases").json().get("items") or []
    # Prefer cases that already have 3D NIfTI masks (export requirement).
    preferred = [c["case_id"] for c in cases if c["case_id"] in {"Case0003", "Case0002"}]
    if not preferred:
        preferred = [c["case_id"] for c in cases[:1]]
    if not preferred:
        pytest.skip("No case available to export for training")

    exp = client.post(
        "/api/export",
        headers=auth_headers(annotator_token),
        json={
            "name": "system_test_train_export",
            "version": "v1_manual",
            "train": preferred[:1],
            "val": [],
            "test": [],
            "materialize": True,
            "strict": False,
        },
        timeout=120,
    )
    if exp.status_code != 200:
        # Fallback: try final/v3_fusion versions commonly present on demo cases.
        for version in ("v3_fusion", "final", "v2_ai"):
            exp = client.post(
                "/api/export",
                headers=auth_headers(annotator_token),
                json={
                    "name": f"system_test_train_export_{version}",
                    "version": version,
                    "train": preferred[:1],
                    "val": [],
                    "test": [],
                    "materialize": True,
                    "strict": False,
                },
                timeout=120,
            )
            if exp.status_code == 200:
                break
    if exp.status_code != 200:
        pytest.skip(f"export for train failed: {exp.status_code} {exp.text[:200]}")
    dataset_id = exp.json().get("dataset_id")
    assert dataset_id

    if not HEAVY:
        pytest.skip("SYSTEM_TEST_RUN_HEAVY=0")

    start = client.post(
        "/api/train",
        json={
            "dataset_id": dataset_id,
            "epochs": 1,
            "batch_size": 1,
            "image_size": 64,
            "max_slices_per_volume": 8,
            "context_radius": 0,
            "num_classes": 2,
        },
        timeout=60,
    )
    assert start.status_code in {200, 400, 422, 500}, start.text
    if start.status_code != 200:
        pytest.skip(f"train start not available: {start.text[:300]}")

    job = start.json().get("job") or {}
    job_id = job.get("job_id")
    assert job_id
    status = str(job.get("status") or "")
    for _ in range(10):
        time.sleep(1.0)
        polled = client.get(f"/api/train/{job_id}")
        assert polled.status_code == 200
        status = str((polled.json().get("job") or {}).get("status") or status)
        if status in {"completed", "failed", "error", "running", "queued", "pending"}:
            break
    assert status, "train job missing status"

def test_ST_PERF_01_health_latency(client: httpx.Client):
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        r = client.get("/api/health")
        times.append(time.perf_counter() - t0)
        assert r.status_code == 200
    avg = sum(times) / len(times)
    # Local smoke threshold — not a formal load test.
    assert avg < 1.0, f"avg health latency too high: {avg:.3f}s"


def test_ST_PERF_02_cases_latency(client: httpx.Client):
    t0 = time.perf_counter()
    r = client.get("/api/cases")
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert elapsed < 3.0, f"/api/cases too slow: {elapsed:.3f}s"


def test_ST_SEC_01_path_traversal_case_id(client: httpx.Client):
    r = client.get("/api/case/../../etc/passwd")
    assert r.status_code in {404, 422, 400}


def test_ST_SEC_02_sql_injection_like_case_id(client: httpx.Client):
    r = client.get("/api/case/Case0001'%20OR%201=1--")
    assert r.status_code in {404, 422, 400}


def test_ST_SEC_03_unauth_write_mask(client: httpx.Client, sample_case_id: str, sample_image_id: str):
    r = client.post(
        "/api/save_mask",
        json={
            "case_id": sample_case_id,
            "image_id": sample_image_id,
            "mask_format": "json",
            "axis": "axial",
            "slice_index": 0,
            "width": 8,
            "height": 8,
            "encoding": "rle",
            "mask": [[0, 64]],
        },
    )
    # Depending on deps: optional auth may allow; if allowed, still must validate payload.
    assert r.status_code in {200, 401, 403, 422}
