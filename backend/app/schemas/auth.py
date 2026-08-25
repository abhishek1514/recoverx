from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=6)


class UserProfile(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    role: str
    merchant_id: int
    merchant_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None
    user: UserProfile


class RefreshTokenRequest(BaseModel):
    refresh_token: str

