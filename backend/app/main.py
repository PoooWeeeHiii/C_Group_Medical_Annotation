from fastapi import FastAPI

from backend.app.api import cases, images, masks, upload
from backend.app.core.config import ensure_project_dirs


ensure_project_dirs()

app = FastAPI(
    title="C Group Medical Annotation Backend",
    version="0.1.0",
)

app.include_router(upload.router)
app.include_router(cases.router)
app.include_router(images.router)
app.include_router(masks.router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

