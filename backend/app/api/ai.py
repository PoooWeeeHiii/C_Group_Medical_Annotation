from fastapi import APIRouter

from backend.app.schemas.ai import AIPredictRequest, AIPredictResponse
from backend.app.schemas.model import ModelListResponse, ModelRecord, RegisterModelRequest, RegisterModelResponse
from backend.app.services.ai_service import run_ai_prediction
from backend.app.services.model_service import list_models, register_model


router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/models", response_model=ModelListResponse)
def read_models() -> ModelListResponse:
    items = [ModelRecord(**item) for item in list_models()]
    return ModelListResponse(success=True, items=items, count=len(items))


@router.post("/models", response_model=RegisterModelResponse)
def create_model(request: RegisterModelRequest) -> RegisterModelResponse:
    model = register_model(
        model_id=request.model_id,
        version=request.version,
        label=request.label,
        display_name=request.display_name,
        path=request.path,
        dice=request.dice,
        description=request.description,
        backend=request.backend,
    )
    return RegisterModelResponse(model=ModelRecord(**model))


@router.post("/ai/predict", response_model=AIPredictResponse)
def run_ai_predict(request: AIPredictRequest) -> AIPredictResponse:
    return run_ai_prediction(request)
