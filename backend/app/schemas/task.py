from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    case_id: str
    assignee_id: int
    deadline: str | None = None
    note: str | None = None


class TaskUpdateRequest(BaseModel):
    status: str | None = None
    assignee_id: int | None = None
    deadline: str | None = None
    note: str | None = None


class TaskRecord(BaseModel):
    task_id: str
    case_id: str
    assignee_id: int
    assignee_username: str | None = None
    assignee_role: str | None = None
    assigner_id: int | None = None
    assigner_username: str | None = None
    deadline: str | None = None
    status: str = "open"
    note: str | None = None
    create_time: str | None = None
    update_time: str | None = None


class TaskResponse(BaseModel):
    success: bool = True
    task: TaskRecord


class TaskListResponse(BaseModel):
    success: bool = True
    items: list[TaskRecord]


class CaseWorkflowRequest(BaseModel):
    note: str | None = Field(default=None, description="Optional review note")


class CaseWorkflowResponse(BaseModel):
    success: bool = True
    case_id: str
    status: str
    message: str
