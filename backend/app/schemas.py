from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# Maximum serialised size of a saved graph. Defaults to 5 MiB which fits
# a multi-thousand-node graph with sizeable embedded params; tune via
# env for graphs that ship inline binary blobs.
MAX_GRAPH_BYTES = int(os.getenv("STRIDE_MAX_GRAPH_BYTES", str(5 * 1024 * 1024)))


def _check_graph_size(value: dict | None) -> dict | None:
    if value is None:
        return None
    encoded = json.dumps(value, default=str)
    if len(encoded) > MAX_GRAPH_BYTES:
        raise ValueError(
            f"graph data exceeds {MAX_GRAPH_BYTES} bytes "
            f"(got {len(encoded)}); split into smaller graphs or bump STRIDE_MAX_GRAPH_BYTES"
        )
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=512)
    display_name: str | None = Field(default=None, max_length=120)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(max_length=512)


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
    description: str | None = Field(default=None, max_length=2000)
    data: dict

    @field_validator("data")
    @classmethod
    def _validate_data(cls, value: dict) -> dict:
        return _check_graph_size(value)


class GraphUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    data: dict | None = None

    @field_validator("data")
    @classmethod
    def _validate_data(cls, value: dict | None) -> dict | None:
        return _check_graph_size(value)


class GraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    data: dict
    created_at: datetime
    updated_at: datetime
