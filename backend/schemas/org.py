"""Pydantic schemas for org management endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class OrgCreate(BaseModel):
    name: str
    slug: str
    logo_url: str | None = None


class OrgUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    logo_url: str | None = None
    settings: dict | None = None


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None
    settings: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Invite
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


class InviteResponse(BaseModel):
    id: uuid.UUID
    invite_email: str | None
    role: str
    invite_status: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------

class DepartmentCreate(BaseModel):
    name: str
    description: str | None = None
    parent_id: uuid.UUID | None = None
    head_person_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    head_person_id: uuid.UUID | None = None


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    head_person_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

class TeamCreate(BaseModel):
    name: str
    description: str | None = None
    department_id: uuid.UUID | None = None
    lead_person_id: uuid.UUID | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    department_id: uuid.UUID | None = None
    lead_person_id: uuid.UUID | None = None


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    department_id: uuid.UUID | None
    lead_person_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------

class PersonCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    title: str | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None


class PersonUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    is_active: bool | None = None


class PersonResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    title: str | None
    department_id: uuid.UUID | None
    team_id: uuid.UUID | None
    manager_id: uuid.UUID | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: dict | None = None


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: dict | None = None


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    permissions: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class GroupMembersUpdate(BaseModel):
    person_ids: list[uuid.UUID]


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Bulk Import
# ---------------------------------------------------------------------------

class ImportColumnMapping(BaseModel):
    """Maps CSV/JSON source columns to person fields.

    Defaults assume column names match field names.
    Set a field to null to skip that column.
    """
    email: str = "email"
    first_name: str = "first_name"
    last_name: str = "last_name"
    title: str = "title"
    department: str = "department"
    team: str = "team"
    manager_email: str = "manager_email"


class ImportRowError(BaseModel):
    row: int
    field: str
    message: str
    value: str | None = None


class ImportResult(BaseModel):
    total_rows: int
    imported: int
    skipped: int
    errors: list[ImportRowError]
