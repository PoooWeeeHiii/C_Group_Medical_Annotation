from fastapi import APIRouter

from backend.app.schemas.ai import AiHealthResponse, AiPredictRequest, AiPredictResponse
from backend.app.services.ai_service import get_ai_health, run_ai_predict


router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai/health", response_model=AiHealthResponse)
def ai_health() -> AiHealthResponse:
    return get_ai_health()


@router.post("/ai/predict", response_model=AiPredictResponse)
def ai_predict(request: AiPredictRequest) -> AiPredictResponse:
    return run_ai_predict(request)
