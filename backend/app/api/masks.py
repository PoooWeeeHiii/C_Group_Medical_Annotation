from fastapi import APIRouter

from backend.app.schemas.mask import (
    MaskDetailResponse,
    MaskListResponse,
    SaveMaskRequest,
    SaveMaskResponse,
)
from backend.app.services.mask_service import get_mask, list_masks_for_image, save_mask


router = APIRouter(prefix="/api", tags=["masks"])


@router.post("/save_mask", response_model=SaveMaskResponse)
def save_image_mask(request: SaveMaskRequest) -> SaveMaskResponse:
    return save_mask(request)


@router.get("/mask/{mask_id}", response_model=MaskDetailResponse)
def read_mask(mask_id: str) -> MaskDetailResponse:
    return MaskDetailResponse(success=True, mask=get_mask(mask_id))


@router.get("/image/{image_id}/masks", response_model=MaskListResponse)
@router.get("/images/{image_id}/masks", response_model=MaskListResponse)
def list_image_masks(image_id: str) -> MaskListResponse:
    matched = list_masks_for_image(image_id)
    return MaskListResponse(
        success=True,
        image_id=image_id,
        count=len(matched),
        items=matched,
        masks=matched,
    )
