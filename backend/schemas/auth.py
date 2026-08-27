"""Pydantic schemas for auth endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    name: str
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Response for /forgot-password.

    ``message`` is always the same regardless of whether the email exists —
    we never leak account existence.

    ``reset_url`` is present ONLY when the deploy has no email provider
    wired (dev/UAT). It lets the operator hand the link to the user
    manually while the email path is being built out. Never returned in
    production once email is live — gate on ``FORGE_RESET_URL_IN_RESPONSE``.
    """
    message: str
    reset_url: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    message: str


class OrgMembership(BaseModel):
    org_id: uuid.UUID
    org_name: str
    org_slug: str
    role: str

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    created_at: datetime
    orgs: list[OrgMembership] = []

    model_config = {"from_attributes": True}
