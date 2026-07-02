from fastapi import APIRouter

from backend.app.schemas.ai import AIPredictRequest, AIPredictResponse
from backend.app.services.ai_service import predict_placeholder


router = APIRouter(prefix="/api", tags=["ai"])


@router.post("/ai/predict", response_model=AIPredictResponse)
def run_ai_predict(request: AIPredictRequest) -> AIPredictResponse:
    return predict_placeholder(request)
