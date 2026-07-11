"""End-to-end tests for the milestone-1 API (upload → query → slice)."""
from __future__ import annotations


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_creates_case_and_image(client, synthetic_nifti):
    with open(synthetic_nifti, "rb") as f:
        resp = client.post(
            "/api/upload",
            files={"file": ("synthetic_ct.nii.gz", f, "application/gzip")},
            data={"patient_id": "SYNTH-001", "modality": "CT"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["case_id"].startswith("Case")
    assert body["image_id"].startswith("Image")
    assert body["width"] == 32 and body["height"] == 32
    assert body["patient_id"] == "SYNTH-001"


def test_list_cases_and_filters(client):
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    first = items[0]
    assert first["image_count"] == 1
    assert first["status"] == "unannotated"

    # keyword filter
    resp = client.get("/api/cases", params={"keyword": "SYNTH-001"})
    assert any(i["patient_id"] == "SYNTH-001" for i in resp.json()["items"])

    # non-matching status filter yields nothing
    resp = client.get("/api/cases", params={"status": "exported"})
    assert resp.json()["items"] == []


def test_case_and_image_detail(client):
    case_id = client.get("/api/cases").json()["items"][0]["case_id"]
    resp = client.get(f"/api/case/{case_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["case"]["case_id"] == case_id
    assert len(detail["images"]) == 1

    image_id = detail["images"][0]["image_id"]
    resp = client.get(f"/api/image/{image_id}")
    assert resp.status_code == 200
    info = resp.json()["image"]
    assert info["slice_count"] == 20
    assert info["width"] == 32


def test_slice_png_and_bounds(client):
    image_id = (
        client.get("/api/cases").json()["items"][0]["case_id"].replace("Case", "Image")
    )
    resp = client.get(f"/api/image/{image_id}/slice/10")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    # out of range
    assert client.get(f"/api/image/{image_id}/slice/999").status_code == 404


def test_not_found(client):
    assert client.get("/api/case/Case9999").status_code == 404
    assert client.get("/api/image/Image9999").status_code == 404
