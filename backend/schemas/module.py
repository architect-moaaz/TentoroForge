"""Pydantic schemas for module endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class ModuleCreate(BaseModel):
    name: str
    description: str | None = None
    dependencies: list[uuid.UUID] = Field(default_factory=list)


class ModuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ModuleFileResponse(BaseModel):
    id: uuid.UUID
    module_id: uuid.UUID
    file_path: str
    file_type: str

    model_config = {"from_attributes": True}


class ModuleDependencyResponse(BaseModel):
    id: uuid.UUID
    module_id: uuid.UUID
    depends_on_id: uuid.UUID
    dependency_type: str

    model_config = {"from_attributes": True}


class ModuleResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    config: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModuleDetailResponse(ModuleResponse):
    dependencies: list[ModuleDependencyResponse] = []
    files: list[ModuleFileResponse] = []


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class DependencyUpdate(BaseModel):
    depends_on_id: uuid.UUID
    dependency_type: str = "uses"


class DependenciesUpdateRequest(BaseModel):
    dependencies: list[DependencyUpdate]


# ---------------------------------------------------------------------------
# Connections map
# ---------------------------------------------------------------------------

class ModuleConnectionNode(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    file_count: int = 0


class ModuleConnectionEdge(BaseModel):
    id: uuid.UUID
    source_module_id: uuid.UUID
    target_module_id: uuid.UUID
    dependency_type: str


class ModuleConnectionsResponse(BaseModel):
    nodes: list[ModuleConnectionNode]
    edges: list[ModuleConnectionEdge]
