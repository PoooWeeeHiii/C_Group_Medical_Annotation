from pydantic import BaseModel, Field


class AiPredictRequest(BaseModel):
    case_id: str
    image_id: str
    model_id: str = "Model0002"
    label: str = Field(default="spleen", min_length=1)


class AiPredictResponse(BaseModel):
    success: bool
    annotation_id: str | None = None
    mask_id: str
    version: str
    model_id: str
    label: str
    dice: float | None = None
    mask_path: str
    message: str = "ai predict success"


class AiHealthResponse(BaseModel):
    success: bool
    ready: bool
    model_id: str = "Model0002"
    label: str = "spleen"
    checkpoint: str | None = None
    nnunet_python: str | None = None
    message: str
