from fastapi import APIRouter, HTTPException

from backend.app.schemas.report import (
    QualityReportGenerateRequest,
    QualityReportGenerateResponse,
    ReportPolishRequest,
    ReportPolishResponse,
    ReportPolishStatusResponse,
)
from backend.app.services.report_service import (
    generate_quality_report,
    polish_report,
    polish_status,
)


router = APIRouter(prefix="/api", tags=["quality-report"])


@router.get("/quality/report/polish/status", response_model=ReportPolishStatusResponse)
def read_polish_status() -> ReportPolishStatusResponse:
    return ReportPolishStatusResponse(**polish_status())


@router.post("/quality/report/generate", response_model=QualityReportGenerateResponse)
def create_quality_report(request: QualityReportGenerateRequest) -> QualityReportGenerateResponse:
    result = generate_quality_report(
        request.mask_id,
        ref_mask_id=request.ref_mask_id,
        case_id=request.case_id,
        include_error_slices=request.include_error_slices,
    )
    return QualityReportGenerateResponse(**result)


@router.post("/quality/report/polish", response_model=ReportPolishResponse)
def polish_quality_report(request: ReportPolishRequest) -> ReportPolishResponse:
    result = polish_report(
        request.draft_markdown,
        tone=request.tone,
        case_id=request.case_id,
        mask_id=request.mask_id,
        metrics=request.metrics,
    )
    if not result.get("success") and not result.get("markdown"):
        raise HTTPException(status_code=400, detail=result.get("message") or "polish failed")
    return ReportPolishResponse(**result)
