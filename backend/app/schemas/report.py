from typing import Any

from pydantic import BaseModel, Field


class QualityReportGenerateRequest(BaseModel):
    mask_id: str
    ref_mask_id: str | None = None
    case_id: str | None = None
    include_error_slices: bool = True


class QualityReportGenerateResponse(BaseModel):
    success: bool = True
    mask_id: str
    ref_mask_id: str | None = None
    case_id: str | None = None
    title: str
    markdown: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    message: str = "quality report generated"


class ReportPolishRequest(BaseModel):
    draft_markdown: str
    tone: str = "clinical"  # clinical | concise | detailed
    case_id: str | None = None
    mask_id: str | None = None
    metrics: dict[str, Any] | None = None


class ReportPolishResponse(BaseModel):
    success: bool = True
    polished: bool = False
    markdown: str
    model: str | None = None
    message: str = ""


class ReportPolishStatusResponse(BaseModel):
    success: bool = True
    configured: bool
    model: str | None = None
    base_url: str | None = None
    message: str = ""
