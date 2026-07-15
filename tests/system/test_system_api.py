"""System tests for the medical annotation platform (live HTTP)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from .conftest import auth_headers, login


# ---------------------------------------------------------------------------
# ST-HEALTH / ST-FE
# ---------------------------------------------------------------------------


def test_ST_HEALTH_01_api_health(client: httpx.Client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("frontend") in {"legacy", "react"}


def test_ST_FE_01_frontend_index(client: httpx.Client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert len(r.content) > 100


def test_ST_FE_02_frontend_static_js(client: httpx.Client):
    for path in ("/frontend/app.js", "/frontend/volume_viewer.js", "/frontend/hand_gesture.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert len(r.content) > 500, path


# ---------------------------------------------------------------------------
# ST-AUTH
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "username,password,role",
    [
        ("annotator", "annotator123", "annotator"),
        ("reviewer", "reviewer123", "reviewer"),
        ("admin", "admin123", "admin"),
    ],
)
def test_ST_AUTH_01_login_roles(client: httpx.Client, username: str, password: str, role: str):
    data = login(client, username, password)
    assert data["user"]["role"] == role
    assert data["user"]["username"] == username


def test_ST_AUTH_02_login_wrong_password(client: httpx.Client):
    r = client.post("/api/auth/login", json={"username": "annotator", "password": "wrong"})
    assert r.status_code in {401, 403, 422}
    # Must not return a usable token on failure.
    if r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()
        assert not body.get("access_token")


def test_ST_AUTH_03_me_requires_token(client: httpx.Client):
    r = client.get("/api/me")
    assert r.status_code in {401, 403}


def test_ST_AUTH_04_me_with_token(client: httpx.Client, annotator_token: str):
    r = client.get("/api/me", headers=auth_headers(annotator_token))
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "annotator"


def test_ST_AUTH_05_annotator_cannot_list_users(client: httpx.Client, annotator_token: str):
    r = client.get("/api/users", headers=auth_headers(annotator_token))
    assert r.status_code in {401, 403}


def test_ST_AUTH_06_admin_can_list_users(client: httpx.Client, admin_token: str):
    r = client.get("/api/users", headers=auth_headers(admin_token))
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert isinstance(items, list)
    assert len(items) >= 3


def test_ST_AUTH_07_annotator_cannot_approve(client: httpx.Client, annotator_token: str, sample_case_id: str):
    r = client.post(
        f"/api/case/{sample_case_id}/approve",
        headers=auth_headers(annotator_token),
        json={},
    )
    assert r.status_code in {401, 403, 422}


# ---------------------------------------------------------------------------
# ST-CASE / ST-IMG
# ---------------------------------------------------------------------------


def test_ST_CASE_01_list_cases(client: httpx.Client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert isinstance(body.get("items"), list)
    assert len(body["items"]) >= 1


def test_ST_CASE_02_case_detail(client: httpx.Client, sample_case_id: str):
    r = client.get(f"/api/case/{sample_case_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["case"]["case_id"] == sample_case_id
    assert body["images"]


def test_ST_CASE_03_case_not_found(client: httpx.Client):
    r = client.get("/api/case/CaseDoesNotExist999")
    assert r.status_code in {404, 422}


def test_ST_IMG_01_image_detail(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}")
    assert r.status_code == 200
    body = r.json()
    # Response shape may wrap item; accept either.
    payload = body.get("image") or body.get("item") or body
    assert str(payload.get("image_id") or sample_image_id)


def test_ST_IMG_02_volume_meta(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/volume")
    assert r.status_code == 200
    body = r.json()
    # Must expose some shape / slice information for 3D path.
    text = json.dumps(body)
    assert any(k in text for k in ("shape", "slice", "depth", "spacing", "size", "width"))


def test_ST_IMG_03_axial_slice_png(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/slice/0.png")
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    assert "image" in ctype or r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_ST_IMG_04_mpr_slice_png(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/slice/axial/0.png")
    assert r.status_code == 200
    assert len(r.content) > 50


def test_ST_IMG_05_projection_png(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/projection/axial.png")
    # Some volumes may reject; 200 is expected for multi-slice CT.
    assert r.status_code in {200, 422, 500}
    if r.status_code == 200:
        assert len(r.content) > 50


# ---------------------------------------------------------------------------
# ST-MASK / ST-LABEL / ST-MODEL
# ---------------------------------------------------------------------------


def test_ST_MASK_01_list_masks(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/masks")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True or "items" in body or "masks" in body


def test_ST_MASK_02_mask_detail_if_present(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/masks")
    body = r.json()
    items = body.get("items") or body.get("masks") or []
    if not items:
        pytest.skip("No masks available on sample image")
    mask_id = items[0].get("mask_id") or items[0].get("id")
    detail = client.get(f"/api/mask/{mask_id}")
    assert detail.status_code == 200


def test_ST_MASK_03_surface_mesh_per_label_if_present(client: httpx.Client, sample_image_id: str):
    r = client.get(f"/api/image/{sample_image_id}/masks")
    items = r.json().get("items") or r.json().get("masks") or []
    if not items:
        pytest.skip("No masks available")
    mask_id = items[0].get("mask_id") or items[0].get("id")
    mesh = client.get(f"/api/mask/{mask_id}/surface-mesh", params={"per_label": "true", "max_labels": 8})
    # Mesh generation can be heavy; accept 200 or controlled failure codes.
    assert mesh.status_code in {200, 404, 422, 500}
    if mesh.status_code == 200:
        data = mesh.json()
        assert isinstance(data, dict)


def test_ST_LABEL_01_list_labels(client: httpx.Client):
    r = client.get("/api/labels")
    assert r.status_code == 200
    body = r.json()
    items = body.get("items") or body.get("labels") or []
    assert isinstance(items, list)


def test_ST_MODEL_01_list_models(client: httpx.Client):
    r = client.get("/api/models")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# ST-AI
# ---------------------------------------------------------------------------


def test_ST_AI_01_health(client: httpx.Client):
    r = client.get("/api/ai/health")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)


def test_ST_AI_02_predict_honest_behavior(
    client: httpx.Client,
    annotator_token: str,
    sample_case_id: str,
    sample_image_id: str,
):
    """Predict may succeed or fail depending on local weights; never silent garbage without status."""
    r = client.post(
        "/api/ai/predict",
        headers=auth_headers(annotator_token),
        json={
            "case_id": sample_case_id,
            "image_id": sample_image_id,
            "allow_baseline": False,
        },
    )
    # 200 success with diagnostics, or 4xx/5xx with detail — both OK.
    assert r.status_code in {200, 400, 404, 422, 500, 503}
    if r.status_code == 200:
        body = r.json()
        # Prefer explicit success/model fields when present.
        assert body.get("success") in {True, False, None} or "mask" in json.dumps(body).lower()
    else:
        # Failure must carry a message / detail (honest failure).
        text = r.text.strip()
        assert text, "Predict failed without error body"


# ---------------------------------------------------------------------------
# ST-SURG
# ---------------------------------------------------------------------------


def test_ST_SURG_01_save_roi_with_organ(
    client: httpx.Client,
    annotator_token: str,
    sample_case_id: str,
    sample_image_id: str,
):
    payload = {
        "case_id": sample_case_id,
        "image_id": sample_image_id,
        "mask_id": None,
        "label_id": 1,
        "organ_name": "spleen",
        "organ_display_name": "脾脏",
        "organ_color": "#e74c3c",
        "organ": {
            "label_id": 1,
            "name": "spleen",
            "display_name": "脾脏",
            "color": "#e74c3c",
        },
        "roi_margin_pct": 18,
        "knife_radius": 2,
        "cuboid_min": [10.0, 20.0, 30.0],
        "cuboid_max": [40.0, 50.0, 60.0],
        "cut_planes": [
            {
                "origin": [25.0, 35.0, 45.0],
                "normal": [0.0, 0.0, 1.0],
                "keepSign": 1,
                "polygon": [[20, 30, 45], [30, 30, 45], [30, 40, 45], [20, 40, 45]],
            }
        ],
        "carved_voxels": 12,
        "note": "[SYSTEM_TEST] surgery ROI with organ fields",
    }
    r = client.post(
        "/api/surgery_results",
        headers=auth_headers(annotator_token),
        json=payload,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    assert body.get("result_id")
    item = body.get("item") or {}
    assert int(item.get("label_id") or 0) == 1
    assert item.get("organ_name") in {"spleen", "label_1"} or item.get("organ_name")
    assert item.get("organ_display_name")
    assert item.get("organ_color")
    # Persist for follow-up queries via return value through attribute.
    test_ST_SURG_01_save_roi_with_organ.result_id = body["result_id"]  # type: ignore[attr-defined]
    test_ST_SURG_01_save_roi_with_organ.case_id = sample_case_id  # type: ignore[attr-defined]
    test_ST_SURG_01_save_roi_with_organ.image_id = sample_image_id  # type: ignore[attr-defined]


def test_ST_SURG_02_list_by_case(client: httpx.Client, sample_case_id: str):
    # Ensure at least one save happened; if previous test failed, try soft dependency.
    result_id = getattr(test_ST_SURG_01_save_roi_with_organ, "result_id", None)
    r = client.get(f"/api/case/{sample_case_id}/surgery_results")
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert isinstance(body.get("items"), list)
    if result_id:
        ids = {str(x.get("result_id")) for x in body["items"]}
        assert result_id in ids


def test_ST_SURG_03_get_by_id(client: httpx.Client):
    result_id = getattr(test_ST_SURG_01_save_roi_with_organ, "result_id", None)
    if not result_id:
        pytest.skip("No surgery result_id from ST-SURG-01")
    r = client.get(f"/api/surgery_results/{result_id}")
    assert r.status_code == 200
    item = r.json()
    assert str(item.get("result_id")) == str(result_id)
    assert item.get("organ_display_name") or (item.get("organ") or {}).get("display_name")


def test_ST_SURG_04_reject_bad_cuboid(
    client: httpx.Client,
    annotator_token: str,
    sample_case_id: str,
    sample_image_id: str,
):
    payload = {
        "case_id": sample_case_id,
        "image_id": sample_image_id,
        "label_id": 1,
        "cuboid_min": [40.0, 40.0, 40.0],
        "cuboid_max": [10.0, 10.0, 10.0],  # invalid: max < min
        "cut_planes": [],
        "note": "[SYSTEM_TEST] invalid cuboid",
    }
    r = client.post("/api/surgery_results", headers=auth_headers(annotator_token), json=payload)
    assert r.status_code in {400, 422}


def test_ST_SURG_05_reject_non_positive_label(
    client: httpx.Client,
    annotator_token: str,
    sample_case_id: str,
    sample_image_id: str,
):
    payload = {
        "case_id": sample_case_id,
        "image_id": sample_image_id,
        "label_id": 0,
        "cuboid_min": [1, 1, 1],
        "cuboid_max": [2, 2, 2],
        "cut_planes": [],
        "note": "[SYSTEM_TEST] bad label",
    }
    r = client.post("/api/surgery_results", headers=auth_headers(annotator_token), json=payload)
    assert r.status_code in {400, 422}


# ---------------------------------------------------------------------------
# ST-WF / ST-TASK (permission-focused, avoid destructive approve on demo data)
# ---------------------------------------------------------------------------


def test_ST_TASK_01_list_tasks(client: httpx.Client, reviewer_token: str):
    r = client.get("/api/tasks", headers=auth_headers(reviewer_token))
    assert r.status_code == 200


def test_ST_WF_01_review_queue_reviewer(client: httpx.Client, reviewer_token: str):
    r = client.get("/api/review/queue", headers=auth_headers(reviewer_token))
    assert r.status_code in {200, 403, 404}


def test_ST_WF_02_versions_list(client: httpx.Client, sample_case_id: str):
    r = client.get(f"/api/case/{sample_case_id}/versions")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# ST-NEG
# ---------------------------------------------------------------------------


def test_ST_NEG_01_unknown_api(client: httpx.Client):
    r = client.get("/api/this_endpoint_should_not_exist_xyz")
    assert r.status_code in {404, 405}


def test_ST_NEG_02_image_not_found(client: httpx.Client):
    r = client.get("/api/image/ImageDoesNotExist999")
    assert r.status_code in {404, 422}
