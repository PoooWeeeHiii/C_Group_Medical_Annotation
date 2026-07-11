"""Pydantic request/response models matching docs/04_api_design.md."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class UploadResponse(BaseModel):
    success: bool = True
    case_id: str
    image_id: str
    patient_id: Optional[str] = None
    modality: Optional[str] = None
    path: str
    width: Optional[int] = None
    height: Optional[int] = None
    message: str = "upload success"


class CaseListItem(BaseModel):
    case_id: str
    patient_id: Optional[str] = None
    modality: Optional[str] = None
    create_time: Optional[datetime] = None
    image_count: int = 0
    mask_count: int = 0
    status: str = "unannotated"


class CaseListResponse(BaseModel):
    success: bool = True
    items: List[CaseListItem]


class CaseDetail(BaseModel):
    case_id: str
    patient_id: Optional[str] = None
    modality: Optional[str] = None
    create_time: Optional[datetime] = None


class ImageBrief(BaseModel):
    image_id: str
    path: str
    width: Optional[int] = None
    height: Optional[int] = None


class CaseDetailResponse(BaseModel):
    success: bool = True
    case: CaseDetail
    images: List[ImageBrief]


class ImageInfo(BaseModel):
    image_id: str
    case_id: Optional[str] = None
    path: str
    width: Optional[int] = None
    height: Optional[int] = None
    slice_count: int = 1


class ImageInfoResponse(BaseModel):
    success: bool = True
    image: ImageInfo
