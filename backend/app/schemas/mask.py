from pydantic import BaseModel


class MaskRecord(BaseModel):
    mask_id: str
    annotation_id: str
    path: str
    version: str | None = None
    label: str | None = None

