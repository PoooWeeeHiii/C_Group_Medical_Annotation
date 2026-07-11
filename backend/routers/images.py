"""GET /api/image/{image_id} and slice rendering endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import imaging
from ..config import resolve_stored
from ..database import get_db
from ..models import Image
from ..schemas import ImageInfo, ImageInfoResponse

router = APIRouter(prefix="/api", tags=["images"])


def _get_image_or_404(db: Session, image_id: str) -> Image:
    image = db.query(Image).filter(Image.image_id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail=f"image {image_id} not found")
    return image


@router.get("/image/{image_id}", response_model=ImageInfoResponse)
def get_image(image_id: str, db: Session = Depends(get_db)):
    image = _get_image_or_404(db, image_id)
    abs_path = resolve_stored(image.path)
    try:
        width, height, slice_count = imaging.get_dimensions(abs_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to read image: {exc}")
    return ImageInfoResponse(
        image=ImageInfo(
            image_id=image.image_id,
            case_id=image.case_id,
            path=image.path,
            width=width,
            height=height,
            slice_count=slice_count,
        )
    )


@router.get("/image/{image_id}/slice/{slice_index}")
def get_slice(image_id: str, slice_index: int, db: Session = Depends(get_db)):
    image = _get_image_or_404(db, image_id)
    abs_path = resolve_stored(image.path)
    try:
        png_bytes = imaging.read_slice_png(abs_path, slice_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"failed to render slice: {exc}")
    return Response(content=png_bytes, media_type="image/png")
