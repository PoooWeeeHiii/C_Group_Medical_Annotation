from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserPublic(BaseModel):
    id: int
    username: str
    role: str
    create_time: str = ""


class LoginResponse(BaseModel):
    success: bool = True
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class MeResponse(BaseModel):
    success: bool = True
    user: UserPublic


class UserListResponse(BaseModel):
    success: bool = True
    items: list[UserPublic]


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = Field(default="annotator")


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=64)
    role: str | None = None


class UserPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseModel):
    success: bool = True
    user: UserPublic
