"""Pydantic schemas for AI features endpoints."""

from pydantic import BaseModel


class AIConfigSave(BaseModel):
    """Save AI configuration for a project."""
    provider: str = "anthropic"
    primaryModel: str = "claude-haiku-4-5-20251001"
    embeddingModel: str = "text-embedding-3-small"
    costTrackingEnabled: bool = True
    monthlyBudget: float | None = None
    rateLimits: dict | None = None
    fallback: dict | None = None


class SemanticSearchConfigSave(BaseModel):
    """Save semantic search config for a model."""
    model: str
    embeddingColumn: str = "embedding"
    sourceColumns: list[str]
    searchRoute: str
    embeddingModel: str = "text-embedding-3-small"
    dimensions: int = 1536
    hybridSearch: bool = True
    keywordColumns: list[str] = []


class AIComponentConfigSave(BaseModel):
    """Save AI component config."""
    type: str
    page: str | None = None
    component: str | None = None
    model: str | None = None
    sourceFields: list[str] = []
    prompt: str | None = None


class SmartFieldTestRequest(BaseModel):
    """Test a smart field configuration."""
    smartConfig: dict
    sampleData: dict


class ScheduledAIConfigSave(BaseModel):
    """Save scheduled AI task config."""
    type: str
    schedule: str
    dataQuery: str | None = None
    prompt: str | None = None
    deliverTo: str | None = None
    action: str | None = None
    tables: list[str] = []
