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


class AgentDebugRun(BaseModel):
    """One message of the builder's live run: the app's real chat loop, as a chosen person, streamed.

    ``graph`` is the agent as drawn (edits not saved yet); with ``use_draft`` the app runs THAT, otherwise the
    agent as installed. ``allow_changes`` lets tools that change data really run; off, they are reported as not run."""
    app_url: str
    message: str
    as_user_id: str
    session_id: str | None = None
    conversation_id: str | None = None
    allow_changes: bool = False
    use_draft: bool = False
    graph: AgentDefinitionSave | None = None


class AgentScenarioSave(BaseModel):
    """The saved test conversations for one agent (see services/agent_scenarios.py)."""
    scenarios: list[dict] = []


class AgentScenarioRun(BaseModel):
    """Run scenarios against the agent as drawn (``graph`` may hold edits that are not saved yet).
    ``scenarios`` omitted means the saved ones."""
    graph: AgentDefinitionSave
    scenarios: list[dict] | None = None
