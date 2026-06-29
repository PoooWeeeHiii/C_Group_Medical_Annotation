from fastapi import APIRouter

from backend.app.schemas.image import ImageDetailResponse
from backend.app.services.case_service import get_image


router = APIRouter(prefix="/api", tags=["images"])


@router.get("/image/{image_id}", response_model=ImageDetailResponse)
def read_image(image_id: str) -> ImageDetailResponse:
    return ImageDetailResponse(success=True, image=get_image(image_id))

