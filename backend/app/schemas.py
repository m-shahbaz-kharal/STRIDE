from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class GraphCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    data: dict


class GraphUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    data: dict | None = None


class GraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    data: dict
    created_at: datetime
    updated_at: datetime
