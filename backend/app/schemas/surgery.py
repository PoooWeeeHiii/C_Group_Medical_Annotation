from pydantic import BaseModel, Field


class CutPlaneModel(BaseModel):
    origin: list[float]
    normal: list[float]
    keepSign: int | None = 1
    keep_sign: int | None = None
    polygon: list[list[float]] = Field(default_factory=list)


class OrganInfoModel(BaseModel):
    label_id: int | None = None
    name: str | None = None
    display_name: str | None = None
    color: str | None = None


class SaveSurgeryResultRequest(BaseModel):
    case_id: str
    image_id: str
    mask_id: str | None = None
    label_id: int
    organ_name: str | None = None
    organ_display_name: str | None = None
    organ_color: str | None = None
    organ: OrganInfoModel | dict | None = None
    roi_margin_pct: float = 18
    knife_radius: int = 2
    cuboid_min: list[float]
    cuboid_max: list[float]
    cut_planes: list[CutPlaneModel | dict] = Field(default_factory=list)
    carved_voxels: int = 0
    note: str | None = None


class SurgeryResultRecord(BaseModel):
    result_id: str
    case_id: str
    image_id: str
    mask_id: str | None = None
    label_id: int
    organ_name: str | None = None
    organ_display_name: str | None = None
    organ_color: str | None = None
    organ: dict | None = None
    roi_margin_pct: float
    knife_radius: int
    cuboid_min: list[float]
    cuboid_max: list[float]
    cut_planes: list[dict]
    carved_voxels: int
    user_id: int | None = None
    username: str | None = None
    note: str | None = None
    create_time: str
    update_time: str | None = None


class SaveSurgeryResultResponse(BaseModel):
    success: bool
    result_id: str
    item: SurgeryResultRecord
    message: str | None = None


class SurgeryResultListResponse(BaseModel):
    success: bool
    case_id: str | None = None
    image_id: str | None = None
    count: int
    items: list[SurgeryResultRecord]
