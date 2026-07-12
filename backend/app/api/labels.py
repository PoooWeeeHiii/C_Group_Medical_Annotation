from fastapi import APIRouter, Depends, Query

from backend.app.deps import get_optional_user, require_roles
from backend.app.schemas.label import (
    LabelCreateRequest,
    LabelItem,
    LabelListResponse,
    LabelResponse,
    LabelUpdateRequest,
)
from backend.app.services import label_service


router = APIRouter(prefix="/api", tags=["labels"])


@router.get("/labels", response_model=LabelListResponse)
def read_labels(
    enabled_only: bool = Query(default=False),
    include_background: bool = Query(default=True),
    _user: dict | None = Depends(get_optional_user),
) -> LabelListResponse:
    label_service.ensure_label_schema()
    items = label_service.list_labels(
        enabled_only=enabled_only,
        include_background=include_background,
    )
    return LabelListResponse(items=[LabelItem(**item) for item in items])


@router.post("/labels", response_model=LabelResponse)
def create_label(
    request: LabelCreateRequest,
    _user: dict = Depends(require_roles("admin")),
) -> LabelResponse:
    item = label_service.create_label(
        label_id=request.label_id,
        name=request.name,
        display_name=request.display_name,
        color=request.color,
        sort_order=request.sort_order,
    )
    return LabelResponse(item=LabelItem(**item))


@router.put("/labels/{label_id}", response_model=LabelResponse)
def update_label(
    label_id: int,
    request: LabelUpdateRequest,
    _user: dict = Depends(require_roles("admin")),
) -> LabelResponse:
    item = label_service.update_label(
        label_id,
        name=request.name,
        display_name=request.display_name,
        color=request.color,
        sort_order=request.sort_order,
        enabled=request.enabled,
    )
    return LabelResponse(item=LabelItem(**item))


@router.delete("/labels/{label_id}", response_model=LabelResponse)
def delete_label(
    label_id: int,
    hard: bool = Query(default=False),
    _user: dict = Depends(require_roles("admin")),
) -> LabelResponse:
    item = label_service.delete_label(label_id, hard=hard)
    # soft-delete returns updated item; hard-delete returns snapshot with deleted flag
    payload = {k: v for k, v in item.items() if k in LabelItem.model_fields}
    return LabelResponse(item=LabelItem(**payload))
