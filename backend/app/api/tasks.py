from fastapi import APIRouter, Depends, Query

from backend.app.deps import get_current_user
from backend.app.schemas.task import (
    CaseWorkflowRequest,
    CaseWorkflowResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskRecord,
    TaskResponse,
    TaskUpdateRequest,
)
from backend.app.services import task_service, workflow_service


router = APIRouter(prefix="/api", tags=["tasks-workflow"])


@router.post("/tasks", response_model=TaskResponse)
def create_task(request: TaskCreateRequest, user: dict = Depends(get_current_user)) -> TaskResponse:
    task = task_service.create_task(
        case_id=request.case_id,
        assignee_id=request.assignee_id,
        assigner=user,
        deadline=request.deadline,
        note=request.note,
    )
    return TaskResponse(task=TaskRecord(**task))


@router.get("/tasks", response_model=TaskListResponse)
def read_tasks(
    case_id: str | None = Query(default=None),
    assignee_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
) -> TaskListResponse:
    items = task_service.list_tasks(
        case_id=case_id,
        assignee_id=assignee_id,
        status=status,
        current_user=user,
    )
    return TaskListResponse(items=[TaskRecord(**item) for item in items])


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def patch_task(
    task_id: str,
    request: TaskUpdateRequest,
    user: dict = Depends(get_current_user),
) -> TaskResponse:
    task = task_service.update_task(
        task_id,
        current_user=user,
        status=request.status,
        assignee_id=request.assignee_id,
        deadline=request.deadline,
        note=request.note,
    )
    return TaskResponse(task=TaskRecord(**task))


@router.post("/case/{case_id}/submit", response_model=CaseWorkflowResponse)
def submit_case(
    case_id: str,
    request: CaseWorkflowRequest | None = None,
    user: dict = Depends(get_current_user),
) -> CaseWorkflowResponse:
    payload = request or CaseWorkflowRequest()
    case = workflow_service.submit_case(case_id, user, note=payload.note)
    return CaseWorkflowResponse(
        case_id=case_id,
        status=str(case.get("status")),
        message="submitted for review",
    )


@router.post("/case/{case_id}/approve", response_model=CaseWorkflowResponse)
def approve_case(
    case_id: str,
    request: CaseWorkflowRequest | None = None,
    user: dict = Depends(get_current_user),
) -> CaseWorkflowResponse:
    payload = request or CaseWorkflowRequest()
    case = workflow_service.approve_case(case_id, user, note=payload.note)
    return CaseWorkflowResponse(
        case_id=case_id,
        status=str(case.get("status")),
        message="approved",
    )


@router.post("/case/{case_id}/reject", response_model=CaseWorkflowResponse)
def reject_case(
    case_id: str,
    request: CaseWorkflowRequest | None = None,
    user: dict = Depends(get_current_user),
) -> CaseWorkflowResponse:
    payload = request or CaseWorkflowRequest()
    case = workflow_service.reject_case(case_id, user, note=payload.note)
    return CaseWorkflowResponse(
        case_id=case_id,
        status=str(case.get("status")),
        message="rejected",
    )
