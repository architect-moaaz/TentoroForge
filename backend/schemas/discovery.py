"""Pydantic schemas for discovery endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class DiscoveryStartRequest(BaseModel):
    message: str


class DiscoveryMessageRequest(BaseModel):
    message: str


class DiscoveryMessageResponse(BaseModel):
    role: str
    content: str


class DiscoverySessionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    discovery_type: str | None
    title: str | None
    messages: list[dict] | None
    brief: dict | None
    project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscoveryConvertRequest(BaseModel):
    name: str | None = None
