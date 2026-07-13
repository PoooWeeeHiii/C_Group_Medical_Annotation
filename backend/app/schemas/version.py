from pydantic import BaseModel


class VersionRecord(BaseModel):
    case_id: str
    version: str
    annotation: str | None = None
    model: str | None = None
    dataset: str | None = None
    create_time: str | None = None


class SaveVersionRequest(BaseModel):
    case_id: str
    version: str
    annotation: str | None = None
    model: str | None = None
    dataset: str | None = None


class SaveVersionResponse(BaseModel):
    success: bool
    version: str
    item: VersionRecord


class VersionListResponse(BaseModel):
    success: bool
    case_id: str
    count: int
    items: list[VersionRecord]
