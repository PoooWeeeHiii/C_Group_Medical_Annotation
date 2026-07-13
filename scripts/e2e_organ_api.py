"""End-to-end API check for Plan A organ nnUNet (heart/liver/lung/kidney).

Usage:
  D:\\anaconda\\python.exe scripts\\e2e_organ_api.py
  D:\\anaconda\\python.exe scripts\\e2e_organ_api.py --organ liver --predict
  D:\\anaconda\\python.exe scripts\\e2e_organ_api.py --organ all --predict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORGAN_META = {
    "heart": {"model_id": "Model0010", "case_id": "Case9010", "image_id": "Image9010", "label": "heart"},
    "liver": {"model_id": "Model0011", "case_id": "Case9011", "image_id": "Image9011", "label": "liver"},
    "lung": {"model_id": "Model0012", "case_id": "Case9012", "image_id": "Image9012", "label": "lung"},
    "kidney": {"model_id": "Model0013", "case_id": "Case9013", "image_id": "Image9013", "label": "kidney"},
}


def _check_one(client, organ: str, do_predict: bool) -> int:
    meta = ORGAN_META[organ]
    print(f"\n--- e2e organ={organ} ---")
    case = client.get(f"/api/case/{meta['case_id']}")
    print("GET /api/case", case.status_code)
    if case.status_code != 200:
        print(
            "Case not registered. Run:\n"
            f"  python scripts/smoke_organ_predict.py --organ {organ} --case spleen_10 --register --skip-predict"
        )
        return 1

    if not do_predict:
        print("skip predict (pass --predict to run full inference via API)")
        return 0

    print("POST /api/ai/predict ... may take several minutes")
    pred = client.post(
        "/api/ai/predict",
        json={
            "case_id": meta["case_id"],
            "image_id": meta["image_id"],
            "model_id": meta["model_id"],
            "label": meta["label"],
        },
    )
    print("POST /api/ai/predict", pred.status_code)
    print(json.dumps(pred.json(), ensure_ascii=False, indent=2))
    assert pred.status_code == 200
    body = pred.json()
    assert body.get("success") is True
    assert body.get("version") == "v2_ai"
    assert body.get("label") == meta["label"]
    mask_path = ROOT / body["mask_path"]
    assert mask_path.exists(), mask_path

    masks = client.get(f"/api/image/{meta['image_id']}/masks")
    print("GET masks", masks.status_code, "count=", masks.json().get("count"))
    assert masks.status_code == 200
    assert masks.json().get("count", 0) >= 1
    print(f"E2E_OK_{organ.upper()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Also call POST /api/ai/predict (slow)",
    )
    parser.add_argument(
        "--organ",
        default="liver",
        choices=["heart", "liver", "lung", "kidney", "all"],
    )
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    print("=== e2e organ API ===")

    health = client.get("/api/health")
    print("GET /api/health", health.status_code, health.json())
    assert health.status_code == 200

    ai_health = client.get("/api/ai/health")
    print("GET /api/ai/health", ai_health.status_code, ai_health.json())
    assert ai_health.status_code == 200
    assert ai_health.json().get("ready") is True
    msg = ai_health.json().get("message") or ""
    assert "organ nnUNet" in msg, msg

    organs = list(ORGAN_META.keys()) if args.organ == "all" else [args.organ]
    worst = 0
    for organ in organs:
        worst = max(worst, _check_one(client, organ, args.predict))
    if worst == 0:
        print("\nE2E_OK")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
