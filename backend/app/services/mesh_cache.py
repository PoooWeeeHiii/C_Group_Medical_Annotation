"""Disk + memory cache for expensive VTK surface-mesh responses."""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

from backend.app.core.config import DATASET_DIR

MESH_CACHE_DIR = DATASET_DIR / "cache" / "meshes"
_MEM_CACHE: dict[str, dict[str, Any]] = {}
_MEM_LOCK = threading.RLock()
_MAX_MEM = 24


def _ensure_dir() -> Path:
    MESH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return MESH_CACHE_DIR


def cache_key(kind: str, object_id: str, params: dict[str, Any]) -> str:
    payload = json.dumps(params, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha1(f"{kind}:{object_id}:{payload}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}_{object_id}_{digest}"


def _path_for(key: str) -> Path:
    return _ensure_dir() / f"{key}.json.gz"


def load_mesh_cache(key: str) -> dict[str, Any] | None:
    with _MEM_LOCK:
        hit = _MEM_CACHE.get(key)
        if hit is not None:
            return hit
    path = _path_for(key)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not data.get("success"):
            return None
        with _MEM_LOCK:
            _MEM_CACHE[key] = data
            while len(_MEM_CACHE) > _MAX_MEM:
                _MEM_CACHE.pop(next(iter(_MEM_CACHE)))
        return data
    except Exception:
        return None


def save_mesh_cache(key: str, data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or not data.get("success"):
        return
    path = _path_for(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(path)
        with _MEM_LOCK:
            _MEM_CACHE[key] = data
            while len(_MEM_CACHE) > _MAX_MEM:
                _MEM_CACHE.pop(next(iter(_MEM_CACHE)))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def cached_mesh(
    kind: str,
    object_id: str,
    params: dict[str, Any],
    builder: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    key = cache_key(kind, object_id, params)
    cached = load_mesh_cache(key)
    if cached is not None:
        out = dict(cached)
        out["cache_hit"] = True
        out["cache_key"] = key
        return out
    built = builder()
    save_mesh_cache(key, built)
    out = dict(built)
    out["cache_hit"] = False
    out["cache_key"] = key
    return out
