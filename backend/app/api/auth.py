from fastapi import APIRouter, Depends

from backend.app.deps import get_current_user, require_roles
from backend.app.schemas.auth import LoginRequest, LoginResponse, MeResponse, UserListResponse, UserPublic
from backend.app.services.auth_service import authenticate_user, list_users


router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    result = authenticate_user(request.username, request.password)
    return LoginResponse(
        access_token=result["access_token"],
        token_type=result["token_type"],
        user=UserPublic(**result["user"]),
    )


@router.get("/me", response_model=MeResponse)
def read_me(user: dict = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user=UserPublic(**user))


@router.get("/users", response_model=UserListResponse)
def read_users(_user: dict = Depends(require_roles("admin", "reviewer"))) -> UserListResponse:
    return UserListResponse(items=[UserPublic(**item) for item in list_users()])
