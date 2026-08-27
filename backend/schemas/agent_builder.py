"""Pydantic schemas for agent builder endpoints."""

from pydantic import BaseModel


class AgentDefinitionSave(BaseModel):
    """Save an agent definition (JSON blob) to the project."""
    id: str
    name: str
    description: str | None = None
    nodes: list[dict] = []
    edges: list[dict] = []
    config: dict | None = None


class AgentListItem(BaseModel):
    id: str
    name: str
    description: str | None
    node_count: int


class AgentTestRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
