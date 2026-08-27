"""Pydantic schemas for template endpoints."""

import uuid

from pydantic import BaseModel


class TemplateResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    category: str
    icon: str | None
    tags: list[str] | None
    complexity: str | None
    is_published: bool

    model_config = {"from_attributes": True}


class TemplateDetailResponse(TemplateResponse):
    plan: dict | None


class TemplateListResponse(BaseModel):
    templates: list[TemplateResponse]
    categories: list[str]


class SuggestedTemplateResponse(BaseModel):
    template: TemplateResponse
    score: float
    matching_departments: list[str]
    reason: str


class SuggestedTemplatesResponse(BaseModel):
    suggestions: list[SuggestedTemplateResponse]
    org_departments: list[str]


class CreateFromTemplateRequest(BaseModel):
    template_slug: str
    name: str
    customizations: dict | None = None
