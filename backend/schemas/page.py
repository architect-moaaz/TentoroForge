"""Pydantic schemas for page definitions."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PageCreate(BaseModel):
    name: str
    route: str = "/"
    html: str = ""
    css: str = ""
    data_bindings: dict = {}


class PageUpdate(BaseModel):
    name: str | None = None
    route: str | None = None
    html: str | None = None
    css: str | None = None
    data_bindings: dict | None = None


class PageResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    route: str
    html: str
    css: str
    data_bindings: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
