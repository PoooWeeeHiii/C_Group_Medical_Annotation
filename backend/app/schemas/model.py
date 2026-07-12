from typing import Any

from pydantic import BaseModel, Field


class ModelRecord(BaseModel):
    model_id: str
    version: str
    label: str = "label"
    display_name: str
    backend: str = "registered"
    description: str = ""
    dice: float | None = None
    path: str | None = None
    builtin: bool = False
    external_ready: bool = False
    create_time: str | None = None
    metrics: dict[str, Any] | None = None


class ModelListResponse(BaseModel):
    success: bool = True
    items: list[ModelRecord]
    count: int


class RegisterModelRequest(BaseModel):
    model_id: str = Field(min_length=1)
    version: str | None = None
    label: str = "label"
    display_name: str | None = None
    path: str | None = None
    dice: float | None = None
    description: str | None = None
    backend: str = "registered"


class RegisterModelResponse(BaseModel):
    success: bool = True
    model: ModelRecord
