from fastapi import APIRouter, Depends

from backend.app.deps import get_current_user, require_roles
from backend.app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    UserCreateRequest,
    UserListResponse,
    UserPasswordRequest,
    UserPublic,
    UserResponse,
    UserUpdateRequest,
)
from backend.app.services.auth_service import (
    authenticate_user,
    create_user,
    delete_user,
    list_users,
    reset_user_password,
    update_user,
)


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


@router.post("/users", response_model=UserResponse)
def create_user_route(
    request: UserCreateRequest,
    _user: dict = Depends(require_roles("admin")),
) -> UserResponse:
    user = create_user(request.username, request.password, request.role)
    return UserResponse(user=UserPublic(**user))


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user_route(
    user_id: int,
    request: UserUpdateRequest,
    _user: dict = Depends(require_roles("admin")),
) -> UserResponse:
    user = update_user(user_id, username=request.username, role=request.role)
    return UserResponse(user=UserPublic(**user))


@router.post("/users/{user_id}/password", response_model=UserResponse)
def reset_password_route(
    user_id: int,
    request: UserPasswordRequest,
    _user: dict = Depends(require_roles("admin")),
) -> UserResponse:
    user = reset_user_password(user_id, request.password)
    return UserResponse(user=UserPublic(**user))


@router.delete("/users/{user_id}", response_model=UserResponse)
def delete_user_route(
    user_id: int,
    actor: dict = Depends(require_roles("admin")),
) -> UserResponse:
    user = delete_user(user_id, actor_id=int(actor["id"]))
    return UserResponse(user=UserPublic(**user))
