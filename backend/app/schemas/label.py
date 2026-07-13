from pydantic import BaseModel, Field


class LabelItem(BaseModel):
    label_id: int
    name: str
    display_name: str
    color: str
    sort_order: int = 0
    enabled: bool = True
    create_time: str = ""
    update_time: str = ""


class LabelListResponse(BaseModel):
    success: bool = True
    items: list[LabelItem]


class LabelResponse(BaseModel):
    success: bool = True
    item: LabelItem


class LabelCreateRequest(BaseModel):
    label_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    color: str = Field(default="#00e5b0", max_length=16)
    sort_order: int | None = None


class LabelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None
    enabled: bool | None = None
