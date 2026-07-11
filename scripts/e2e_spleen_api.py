"""End-to-end API check for spleen AI prediction.

Usage:
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\e2e_spleen_api.py
  D:\\hm_2_spleen\\venv_nnunet_cpu\\Scripts\\python.exe scripts\\e2e_spleen_api.py --predict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Also call POST /api/ai/predict (slow on CPU, several minutes)",
    )
    parser.add_argument("--case-id", default="Case9001")
    parser.add_argument("--image-id", default="Image9001")
    args = parser.parse_args()

    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    print("=== e2e spleen API ===")

    health = client.get("/api/health")
    print("GET /api/health", health.status_code, health.json())
    assert health.status_code == 200

    ai_health = client.get("/api/ai/health")
    print("GET /api/ai/health", ai_health.status_code, ai_health.json())
    assert ai_health.status_code == 200
    assert ai_health.json().get("ready") is True

    cases = client.get("/api/cases")
    print("GET /api/cases", cases.status_code, "count=", len(cases.json().get("items") or cases.json().get("cases") or []))
    assert cases.status_code == 200

    case = client.get(f"/api/case/{args.case_id}")
    print("GET /api/case", case.status_code)
    if case.status_code != 200:
        print(
            "Case not registered. Run:\n"
            "  python scripts/smoke_spleen_predict.py --case spleen_59 --register --skip-predict"
        )
        return 1

    volume = client.get(f"/api/image/{args.image_id}/volume")
    print("GET /api/image/.../volume", volume.status_code, volume.json() if volume.headers.get("content-type", "").startswith("application/json") else "ok-binary-or-meta")
    # volume endpoint may be metadata or render; accept 200
    if volume.status_code != 200:
        meta = client.get(f"/api/image/{args.image_id}/meta")
        print("fallback GET meta", meta.status_code, meta.text[:300])
        # try known metadata route from images API
        from backend.app.api import images as images_api  # noqa: F401

    if args.predict:
        print("POST /api/ai/predict ... this may take several minutes on CPU")
        pred = client.post(
            "/api/ai/predict",
            json={
                "case_id": args.case_id,
                "image_id": args.image_id,
                "model_id": "Model0002",
                "label": "spleen",
            },
        )
        print("POST /api/ai/predict", pred.status_code)
        print(json.dumps(pred.json(), ensure_ascii=False, indent=2))
        assert pred.status_code == 200
        body = pred.json()
        assert body.get("success") is True
        assert body.get("version") == "v2_ai"
        assert body.get("label") == "spleen"
        mask_path = ROOT / body["mask_path"]
        assert mask_path.exists(), mask_path

        masks = client.get(f"/api/image/{args.image_id}/masks")
        print("GET masks", masks.status_code, "count=", masks.json().get("count"))
        assert masks.status_code == 200
        assert masks.json().get("count", 0) >= 1

        versions = client.get(f"/api/case/{args.case_id}/versions")
        print("GET versions", versions.status_code, versions.json())
        assert versions.status_code == 200
    else:
        print("skip predict (pass --predict to run full inference via API)")

    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
