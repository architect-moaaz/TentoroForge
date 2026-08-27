"""Pydantic schemas for rules & access control endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Project Rules
# ---------------------------------------------------------------------------

class RuleCreate(BaseModel):
    name: str
    rule_type: str  # validation, access, business, computed, state_machine, trigger
    model_name: str | None = None
    field_name: str | None = None
    config: dict = {}
    is_active: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    model_name: str | None = None
    field_name: str | None = None
    config: dict | None = None
    is_active: bool | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    rule_type: str
    model_name: str | None
    field_name: str | None
    config: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# App Access Policies
# ---------------------------------------------------------------------------

class AccessPolicyCreate(BaseModel):
    target_type: str  # role, group, department, person
    target_id: uuid.UUID
    access_level: str = "user"  # user, admin, none


class AccessPolicyResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    access_level: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Field Access Policies
# ---------------------------------------------------------------------------

class FieldAccessCreate(BaseModel):
    model_name: str
    field_name: str
    target_type: str  # role, group, department, person
    target_id: uuid.UUID
    can_view: bool = True
    can_edit: bool = True
    condition: str | None = None


class FieldAccessUpdate(BaseModel):
    can_view: bool | None = None
    can_edit: bool | None = None
    condition: str | None = None


class FieldAccessResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    model_name: str
    field_name: str
    target_type: str
    target_id: uuid.UUID
    can_view: bool
    can_edit: bool
    condition: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FieldAccessMatrixCell(BaseModel):
    """Single cell in the field access matrix."""
    field_name: str
    target_id: uuid.UUID
    target_type: str
    can_view: bool
    can_edit: bool


class FieldAccessMatrixResponse(BaseModel):
    """Full matrix: all fields × all roles for a given model."""
    model_name: str
    fields: list[str]
    targets: list[dict]  # [{ id, type, name }]
    cells: list[FieldAccessMatrixCell]
