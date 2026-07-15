from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import ai, auth, cases, datasets, images, labels, masks, report, surgery, tasks, train, upload, versions
from backend.app.core.config import PROJECT_ROOT, ensure_project_dirs
from backend.app.services.sqlite_service import ensure_sqlite_ready


ensure_project_dirs()
ensure_sqlite_ready()
try:
    from backend.app.services.label_service import ensure_label_schema

    ensure_label_schema()
except Exception:
    pass
try:
    from backend.app.services.surgery_service import ensure_surgery_schema

    ensure_surgery_schema()
except Exception:
    pass
try:
    from backend.app.services.model_service import ensure_builtin_models

    ensure_builtin_models()
except Exception:
    pass

# Prefer React build only when explicitly enabled; legacy frontend has the full
# annotation + 3D viewer. React lives in web/ (npm run dev / USE_REACT_FRONTEND=1).
import os

WEB_DIST = PROJECT_ROOT / "web" / "dist"
LEGACY_FRONTEND = PROJECT_ROOT / "frontend"
USE_REACT = os.getenv("USE_REACT_FRONTEND", "").strip().lower() in {"1", "true", "yes"}
FRONTEND_DIR = (
    WEB_DIST if USE_REACT and (WEB_DIST / "index.html").exists() else LEGACY_FRONTEND
)
FRONTEND_INDEX = FRONTEND_DIR / "index.html"
IS_REACT_BUILD = FRONTEND_DIR == WEB_DIST

app = FastAPI(
    title="C Group Medical Annotation Backend",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(labels.router)
app.include_router(tasks.router)
app.include_router(upload.router)
app.include_router(cases.router)
app.include_router(images.router)
app.include_router(masks.router)
app.include_router(report.router)
app.include_router(versions.router)
app.include_router(surgery.router)
app.include_router(datasets.router)
app.include_router(ai.router)
app.include_router(train.router)

if IS_REACT_BUILD:
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    # Keep /frontend for legacy volume_viewer or copied static helpers if present.
    if LEGACY_FRONTEND.exists():
        app.mount("/frontend", StaticFiles(directory=LEGACY_FRONTEND), name="frontend")
elif FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "frontend": "react" if IS_REACT_BUILD else "legacy"}


def _frontend() -> FileResponse:
    if not FRONTEND_INDEX.exists():
        raise RuntimeError(f"frontend index not found: {FRONTEND_INDEX}")
    return FileResponse(FRONTEND_INDEX)


@app.get("/")
def frontend_root() -> FileResponse:
    return _frontend()


@app.get("/{page_name}")
def frontend_page(page_name: str) -> FileResponse:
    # SPA fallback for React Router and legacy soft routes.
    if page_name.startswith("api") or page_name in {"assets", "frontend", "docs"}:
        return _frontend()
    return _frontend()


@app.get("/versions/{case_id}")
@app.get("/annotation/{case_id}")
def frontend_case_page(case_id: str) -> FileResponse:
    return _frontend()
