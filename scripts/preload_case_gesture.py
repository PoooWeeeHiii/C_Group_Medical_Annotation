#!/usr/bin/env python3
"""Precompute Case0003 (or any case) AI-mask selection + VTK surface meshes for fast gesture/surgery.

Usage (backend must be running on :8000):
  python scripts/preload_case_gesture.py
  python scripts/preload_case_gesture.py --case Case0003
  python scripts/preload_case_gesture.py --case Case0003 --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def http_json(method: str, url: str, timeout: float = 600.0) -> Any:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Preload CT/mask surface meshes for gesture demo")
    parser.add_argument("--case", default="Case0003")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--max-dim", type=int, default=176)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"[preload] health -> {base}/api/health")
    try:
        health = http_json("GET", f"{base}/api/health", timeout=30)
        print("[preload] health:", health)
    except Exception as exc:
        print(f"[preload] ERROR: backend not reachable: {exc}")
        return 1

    detail = http_json("GET", f"{base}/api/case/{urllib.parse.quote(args.case)}", timeout=60)
    if not isinstance(detail, dict):
        print(f"[preload] ERROR: unexpected case detail for {args.case}")
        return 1
    images = detail.get("images") or []
    if not images:
        print(f"[preload] ERROR: no images under {args.case}")
        return 1
    image = images[0]
    image_id = image.get("image_id")
    print(f"[preload] image_id={image_id}")

    masks_payload = http_json("GET", f"{base}/api/image/{image_id}/masks", timeout=120)
    if isinstance(masks_payload, dict):
        masks = masks_payload.get("items") or masks_payload.get("masks") or []
    else:
        masks = masks_payload or []
    organs = next(
        (
            m
            for m in sorted(
                masks,
                key=lambda x: str(x.get("create_time") or ""),
                reverse=True,
            )
            if str(m.get("label") or "") == "全部标注" and m.get("version") == "v2_ai"
        ),
        None,
    )
    if organs is None:
        organs = next((m for m in masks if m.get("version") == "v2_ai"), None)
    if organs is None:
        print("[preload] ERROR: no v2_ai mask found. Open UI once and run TotalSeg, or predict first.")
        return 2
    mask_id = organs["mask_id"]
    print(f"[preload] organs mask_id={mask_id} label={organs.get('label')}")

    ct_queries = [
        f"protocol=body&max_dim={args.max_dim}&min_component_voxels=2000&max_components=1&max_triangles=70000&target_reduction=0.45&smooth_iterations=12",
        f"protocol=lung&max_dim={args.max_dim}&min_component_voxels=900&max_components=4&max_triangles=70000&target_reduction=0.46&smooth_iterations=12",
        f"protocol=soft&max_dim={args.max_dim}&min_component_voxels=1200&max_components=8&max_triangles=110000&target_reduction=0.42&smooth_iterations=14",
        f"protocol=bone&max_dim={args.max_dim}&min_component_voxels=512&max_components=3&max_triangles=110000&target_reduction=0.38&smooth_iterations=14",
    ]
    for q in ct_queries:
        url = f"{base}/api/image/{image_id}/surface-mesh?{q}"
        t0 = time.time()
        try:
            data = http_json("GET", url, timeout=600)
            hit = data.get("cache_hit")
            print(f"[preload] CT mesh ok protocol={data.get('protocol')} cache_hit={hit} {time.time()-t0:.1f}s tris={data.get('triangle_count')}")
        except urllib.error.HTTPError as exc:
            print(f"[preload] CT mesh FAIL {q[:40]}... -> {exc}")

    mesh_q = (
        "per_label=true&max_labels=24&min_component_voxels=96&max_components=8"
        "&max_triangles=140000&target_reduction=0.45&smooth_iterations=10"
        "&remove_thin=true&constrain_to_body=true&constrain_to_source_roi=true&source_roi_margin_mm=45"
    )
    url = f"{base}/api/mask/{mask_id}/surface-mesh?{mesh_q}"
    t0 = time.time()
    try:
        data = http_json("GET", url, timeout=900)
        layers = data.get("layers") or []
        print(
            f"[preload] mask mesh ok cache_hit={data.get('cache_hit')} "
            f"{time.time()-t0:.1f}s layers={len(layers)} tris={data.get('triangle_count')}"
        )
    except urllib.error.HTTPError as exc:
        print(f"[preload] mask mesh FAIL -> {exc}")
        return 3

    # second hit should be cache
    t0 = time.time()
    data2 = http_json("GET", url, timeout=120)
    print(f"[preload] mask mesh 2nd call cache_hit={data2.get('cache_hit')} {time.time()-t0:.1f}s")
    print("[preload] done. Next UI「开始手势控制」should reuse masks + cached meshes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
