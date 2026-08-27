"""Pydantic schemas for project endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ProjectResponse(BaseModel):
    id: uuid.UUID
    short_id: str
    org_id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID
    status: str
    preview_port: int | None
    db_port: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class ConversationResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    role: str
    content: str
    message_type: str
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Chat / Generation requests
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    # Smith Auto-Act (S1) — current visual-editor route, if any. When the
    # user says "change the Status field" and current_route is set, the
    # smith_decide scoring gives that route +50 points, breaking the tie
    # against other pages that share the same label. Null when the chat
    # panel is the only visible surface (no editor open).
    current_route: str | None = None
    # Ids returned by POST /api/projects/{id}/attachments. Ids, not bytes:
    # a 10 MB screenshot inlined here would bloat every retry of the turn.
    attachment_ids: list[str] = []


class GenerateRequest(BaseModel):
    description: str
    plan: dict | None = None
    figma_url: str | None = None
    figma_token: str | None = None
    # Screenshots / spec documents the user attached before hitting Build.
    attachment_ids: list[str] = []


# ---------------------------------------------------------------------------
# Agent Job
# ---------------------------------------------------------------------------

class AgentJobResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    agent_type: str
    status: str
    instruction: str | None
    result: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

class VersionResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    commit_hash: str | None
    message: str
    agent_job_id: uuid.UUID | None
    files_changed: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
