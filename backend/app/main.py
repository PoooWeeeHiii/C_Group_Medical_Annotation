from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api import ai, auth, cases, datasets, images, masks, tasks, upload, versions
from backend.app.core.config import PROJECT_ROOT, ensure_project_dirs
from backend.app.services.sqlite_service import ensure_sqlite_ready


ensure_project_dirs()
ensure_sqlite_ready()
try:
    from backend.app.services.model_service import ensure_builtin_models

    ensure_builtin_models()
except Exception:
    pass
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

app = FastAPI(
    title="C Group Medical Annotation Backend",
    version="0.1.0",
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
app.include_router(tasks.router)
app.include_router(upload.router)
app.include_router(cases.router)
app.include_router(images.router)
app.include_router(masks.router)
app.include_router(versions.router)
app.include_router(datasets.router)
app.include_router(ai.router)

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _frontend() -> FileResponse:
    if not FRONTEND_INDEX.exists():
        raise RuntimeError("frontend/index.html not found")
    return FileResponse(FRONTEND_INDEX)


@app.get("/")
def frontend_root() -> FileResponse:
    return _frontend()


@app.get("/{page_name}")
def frontend_page(page_name: str) -> FileResponse:
    allowed_pages = {
        "dashboard",
        "cases",
        "annotation",
        "train",
        "inference",
        "versions",
        "quality",
        "export",
        "settings",
    }
    if page_name not in allowed_pages:
        return _frontend()
    return _frontend()


@app.get("/versions/{case_id}")
@app.get("/annotation/{case_id}")
def frontend_case_page(case_id: str) -> FileResponse:
    return _frontend()
