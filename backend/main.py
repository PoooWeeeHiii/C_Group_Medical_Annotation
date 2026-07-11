"""FastAPI application entrypoint.

Run with:  uvicorn backend.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import RAW_DIR
from .database import init_db
from .routers import cases, images, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="C Group Medical Annotation Platform", version="0.1.0", lifespan=lifespan
)

# The Vue frontend runs on a separate dev origin; allow all during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(upload.router)
app.include_router(cases.router)
app.include_router(images.router)
