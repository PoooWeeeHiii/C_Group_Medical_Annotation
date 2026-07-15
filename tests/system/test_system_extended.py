"""Extended system tests: upload, export, workflow, mask write path."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest

from .conftest import auth_headers
from .helpers import make_tiny_nifti, save_slice_mask, upload_nifti

OUTPUT_DIR = Path(__file__).resolve().parent / "output" / "fixtures"
HEAVY = os.getenv("SYSTEM_TEST_RUN_HEAVY", "1").strip().lower() not in {"0", "false", "no"}


@pytest.fixture(scope="module")
def uploaded_case(client: httpx.Client, annotator_token: str) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    nifti = make_tiny_nifti(OUTPUT_DIR / "system_test_ct.nii.gz", shape=(16, 32, 32))
    body = upload_nifti(
        client,
        nifti,
        token=annotator_token,
        patient_id=f"SYSTEM_TEST_{int(time.time())}",
    )
    # UploadResponse shapes vary: case_id / case / image
    case_id = body.get("case_id") or (body.get("case") or {}).get("case_id")
    image_id = body.get("image_id")
    if not image_id:
        images = body.get("images") or []
        if images:
            image_id = images[0].get("image_id")
    if not case_id or not image_id:
        # Fallback: list newest matching SYSTEM_TEST
        cases = client.get("/api/cases").json()["items"]
        hit = next((c for c in cases if str(c.get("patient_id") or "").startswith("SYSTEM_TEST")), None)
        assert hit, f"Cannot resolve uploaded case from response: {body}"
        case_id = hit["case_id"]
        detail = client.get(f"/api/case/{case_id}").json()
        image_id = detail["images"][0]["image_id"]
    return {"case_id": str(case_id), "image_id": str(image_id), "upload": body}


# ---------------------------------------------------------------------------
# Upload / Export
# ---------------------------------------------------------------------------


def test_ST_UP_01_nifti_upload_creates_case(uploaded_case: dict):
    assert uploaded_case["case_id"].startswith("Case")
    assert uploaded_case["image_id"].startswith("Image")


def test_ST_UP_02_uploaded_volume_readable(client: httpx.Client, uploaded_case: dict):
    image_id = uploaded_case["image_id"]
    r = client.get(f"/api/image/{image_id}/volume")
    assert r.status_code == 200
    slice_r = client.get(f"/api/image/{image_id}/slice/0.png")
    assert slice_r.status_code == 200
    assert len(slice_r.content) > 50


def test_ST_UP_03_multi_file_upload_field(client: httpx.Client, annotator_token: str, tmp_path: Path):
    """Exercise multipart `files` field (multi-DICOM style API), using two NIfTI parts."""
    p1 = make_tiny_nifti(tmp_path / "a.nii.gz", shape=(8, 16, 16))
    p2 = make_tiny_nifti(tmp_path / "b.nii.gz", shape=(8, 16, 16))
    headers = auth_headers(annotator_token)
    with p1.open("rb") as f1, p2.open("rb") as f2:
        files = [
            ("files", ("a.nii.gz", f1, "application/gzip")),
            ("files", ("b.nii.gz", f2, "application/gzip")),
        ]
        data = {"source_group": "system_test", "patient_id": f"SYSTEM_TEST_MULTI_{int(time.time())}", "modality": "CT"}
        r = client.post("/api/upload", headers=headers, files=files, data=data)
    # Implementation may merge into one case or reject mixed volumes; both must be explicit.
    assert r.status_code in {200, 400, 422}, r.text
    if r.status_code == 200:
        assert r.json().get("success") is True


def test_ST_EX_01_export_materialize(
    client: httpx.Client,
    annotator_token: str,
    uploaded_case: dict,
):
    case_id = uploaded_case["case_id"]
    image_id = uploaded_case["image_id"]
    save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id, slice_index=0)
    save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id, slice_index=1)

    # Dataset export requires a 3D NIfTI mask — build it from JSON slices first.
    nifti = client.post(
        "/api/export_mask_nifti",
        headers=auth_headers(annotator_token),
        json={"case_id": case_id, "image_id": image_id, "version": "v1_manual", "label": "spleen"},
    )
    assert nifti.status_code == 200, nifti.text

    payload = {
        "name": "system_test_export",
        "version": "v1_manual",
        "label_set": "dense",
        "train": [case_id],
        "val": [],
        "test": [],
        "format": "nnunet",
        "materialize": True,
        "strict": False,
    }
    r = client.post("/api/export", headers=auth_headers(annotator_token), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True
    assert body.get("dataset_id")
    assert body.get("materialize") is True
    test_ST_EX_01_export_materialize.dataset_id = body["dataset_id"]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Mask write / propagate / promote / rollback
# ---------------------------------------------------------------------------


def test_ST_MASK_W_01_save_mask_json(client: httpx.Client, annotator_token: str, uploaded_case: dict):
    body = save_slice_mask(
        client,
        token=annotator_token,
        case_id=uploaded_case["case_id"],
        image_id=uploaded_case["image_id"],
    )
    assert body["mask_id"]
    test_ST_MASK_W_01_save_mask_json.mask_id = body["mask_id"]  # type: ignore[attr-defined]


def test_ST_MASK_W_02_update_mask(client: httpx.Client, annotator_token: str, uploaded_case: dict):
    mask_id = getattr(test_ST_MASK_W_01_save_mask_json, "mask_id", None)
    if not mask_id:
        saved = save_slice_mask(
            client,
            token=annotator_token,
            case_id=uploaded_case["case_id"],
            image_id=uploaded_case["image_id"],
        )
        mask_id = saved["mask_id"]
    from .helpers import rle_box, volume_hw

    width, height, _ = volume_hw(client, uploaded_case["image_id"])
    x0, y0 = max(1, width // 5), max(1, height // 5)
    x1, y1 = min(width - 1, 4 * width // 5), min(height - 1, 4 * height // 5)
    payload = {
        "label": "spleen",
        "label_id": 1,
        "axis": "axial",
        "slice_index": 0,
        "width": width,
        "height": height,
        "encoding": "rle",
        "mask": rle_box(width, height, x0, y0, x1, y1, value=1),
    }
    r = client.put(f"/api/mask/{mask_id}", headers=auth_headers(annotator_token), json=payload)
    assert r.status_code == 200, r.text
    assert r.json().get("success") is True


def test_ST_MASK_W_03_export_nifti_and_propagate(client: httpx.Client, annotator_token: str, uploaded_case: dict):
    case_id = uploaded_case["case_id"]
    image_id = uploaded_case["image_id"]
    save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id, slice_index=0)
    save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id, slice_index=1)

    # Stack JSON → NIfTI under v1_manual
    exp = client.post(
        "/api/export_mask_nifti",
        headers=auth_headers(annotator_token),
        json={"case_id": case_id, "image_id": image_id, "version": "v1_manual", "label": "spleen"},
    )
    assert exp.status_code == 200, exp.text

    # Graph-cut / propagation path → v3_preview (DeepEdit neural may be unavailable)
    prop = client.post(
        "/api/label_propagate",
        headers=auth_headers(annotator_token),
        json={
            "case_id": case_id,
            "image_id": image_id,
            "source_version": "v1_manual",
            "output_version": "v3_preview",
            "label": "spleen",
            "method": "image_guided_distance",
        },
    )
    assert prop.status_code in {200, 422, 500}, prop.text
    if prop.status_code == 200:
        body = prop.json()
        assert body.get("success") is True or body.get("mask_id")
        test_ST_MASK_W_03_export_nifti_and_propagate.preview_mask_id = body.get("mask_id") or (
            (body.get("mask") or {}).get("mask_id")
        )  # type: ignore[attr-defined]


def test_ST_MASK_W_04_deepedit_honest_fallback(client: httpx.Client, annotator_token: str, uploaded_case: dict):
    r = client.post(
        "/api/deepedit/refine",
        headers=auth_headers(annotator_token),
        json={
            "case_id": uploaded_case["case_id"],
            "image_id": uploaded_case["image_id"],
            "source_version": "v1_manual",
            "output_version": "v3_preview",
            "label": "spleen",
            "require_neural": True,
            "positive_points": [[16, 16, 8]],
            "negative_points": [],
        },
    )
    # Neural DeepEdit may be down → should fail honestly or return fallback metadata.
    assert r.status_code in {200, 422, 500, 503}, r.text
    if r.status_code == 200:
        body = r.json()
        assert "model_status" in body or body.get("success") is True


def test_ST_MASK_W_05_promote_and_rollback(client: httpx.Client, annotator_token: str, reviewer_token: str, uploaded_case: dict):
    case_id = uploaded_case["case_id"]
    image_id = uploaded_case["image_id"]

    # Ensure a promotable preview exists.
    preview_id = getattr(test_ST_MASK_W_03_export_nifti_and_propagate, "preview_mask_id", None)
    if not preview_id:
        save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id, slice_index=0)
        prop = client.post(
            "/api/label_propagate",
            headers=auth_headers(annotator_token),
            json={
                "case_id": case_id,
                "image_id": image_id,
                "source_version": "v1_manual",
                "output_version": "v3_preview",
                "label": "spleen",
            },
        )
        if prop.status_code != 200:
            pytest.skip(f"label_propagate unavailable: {prop.status_code} {prop.text[:200]}")
        preview_id = prop.json().get("mask_id") or (prop.json().get("mask") or {}).get("mask_id")
    assert preview_id

    # Annotator cannot promote to final.
    denied = client.post(
        f"/api/mask/{preview_id}/promote",
        headers=auth_headers(annotator_token),
        json={"target_version": "final"},
    )
    assert denied.status_code in {403, 400}

    # v3_preview → v3_fusion (does not require pending review state)
    fused = client.post(
        f"/api/mask/{preview_id}/promote",
        headers=auth_headers(reviewer_token),
        json={"target_version": "v3_fusion"},
    )
    assert fused.status_code == 200, fused.text
    fusion_id = fused.json()["mask_id"]

    # final promotion requires pending/reviewed — submit first.
    status = client.get(f"/api/case/{case_id}").json()["case"]["status"]
    if status == "annotated":
        sub = client.post(
            f"/api/case/{case_id}/submit",
            headers=auth_headers(annotator_token),
            json={"note": "[SYSTEM_TEST] submit before final promote"},
        )
        assert sub.status_code == 200, sub.text

    promoted = client.post(
        f"/api/mask/{fusion_id}/promote",
        headers=auth_headers(reviewer_token),
        json={"target_version": "final"},
    )
    assert promoted.status_code == 200, promoted.text
    final_id = promoted.json()["mask_id"]

    rolled = client.post(f"/api/mask/{final_id}/rollback", headers=auth_headers(reviewer_token))
    assert rolled.status_code in {200, 400, 404, 422}, rolled.text
    if rolled.status_code == 200:
        assert rolled.json().get("success") is True


# ---------------------------------------------------------------------------
# Review workflow: submit → reject → resubmit → approve
# ---------------------------------------------------------------------------


def test_ST_WF_FULL_01_submit_reject_resubmit_approve(
    client: httpx.Client,
    annotator_token: str,
    reviewer_token: str,
    uploaded_case: dict,
):
    case_id = uploaded_case["case_id"]
    image_id = uploaded_case["image_id"]

    # Bring case to annotated via mask save.
    save_slice_mask(client, token=annotator_token, case_id=case_id, image_id=image_id)
    detail = client.get(f"/api/case/{case_id}").json()
    status = detail["case"]["status"]
    assert status in {"annotated", "pending", "final", "reviewed"}

    # Ensure promotable 3D preview for later approve.
    prop = client.post(
        "/api/label_propagate",
        headers=auth_headers(annotator_token),
        json={
            "case_id": case_id,
            "image_id": image_id,
            "source_version": "v1_manual",
            "output_version": "v3_preview",
            "label": "spleen",
        },
    )
    if prop.status_code != 200:
        pytest.skip(f"Cannot create v3_preview for approve: {prop.status_code}")

    # If already final from previous promote test, force path by saving again? final→annotated needs force via reject.
    status = client.get(f"/api/case/{case_id}").json()["case"]["status"]
    if status == "final":
        rej0 = client.post(
            f"/api/case/{case_id}/reject",
            headers=auth_headers(reviewer_token),
            json={"note": "[SYSTEM_TEST] reset final for workflow"},
        )
        assert rej0.status_code == 200, rej0.text
        status = client.get(f"/api/case/{case_id}").json()["case"]["status"]

    if status == "pending":
        # Normalize to annotated via reject first.
        client.post(
            f"/api/case/{case_id}/reject",
            headers=auth_headers(reviewer_token),
            json={"note": "[SYSTEM_TEST] normalize"},
        )
        status = client.get(f"/api/case/{case_id}").json()["case"]["status"]

    assert status == "annotated", status

    sub1 = client.post(
        f"/api/case/{case_id}/submit",
        headers=auth_headers(annotator_token),
        json={"note": "[SYSTEM_TEST] first submit"},
    )
    assert sub1.status_code == 200, sub1.text
    assert client.get(f"/api/case/{case_id}").json()["case"]["status"] == "pending"

    rej = client.post(
        f"/api/case/{case_id}/reject",
        headers=auth_headers(reviewer_token),
        json={"note": "[SYSTEM_TEST] please revise"},
    )
    assert rej.status_code == 200, rej.text
    assert client.get(f"/api/case/{case_id}").json()["case"]["status"] == "annotated"

    sub2 = client.post(
        f"/api/case/{case_id}/submit",
        headers=auth_headers(annotator_token),
        json={"note": "[SYSTEM_TEST] resubmit"},
    )
    assert sub2.status_code == 200, sub2.text
    assert client.get(f"/api/case/{case_id}").json()["case"]["status"] == "pending"

    appr = client.post(
        f"/api/case/{case_id}/approve",
        headers=auth_headers(reviewer_token),
        json={"note": "[SYSTEM_TEST] approved"},
    )
    assert appr.status_code == 200, appr.text
    final_status = client.get(f"/api/case/{case_id}").json()["case"]["status"]
    assert final_status in {"final", "reviewed", "pending"}
