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


class AgentWatch(BaseModel):
    """Watch the running app's real chats live. ``graph`` (the agent as drawn) lets the platform say which box on the
    canvas each tool and step belongs to."""
    app_url: str
    graph: AgentDefinitionSave | None = None
    #: Whose chats to watch: everyone's (neither), those of everyone holding a role, or one person's (outranks a role).
    role: str | None = None
    user_id: str | None = None


class AgentScenarioSave(BaseModel):
    """The saved test conversations for one agent (see services/agent_scenarios.py)."""
    scenarios: list[dict] = []


class AgentBlastInvent(BaseModel):
    """Have an AI invent tricky tests ("bombs") for the agent as drawn. ``bombs`` limits the kinds (all when omitted)."""
    graph: AgentDefinitionSave
    bombs: list[str] | None = None
    per_bomb: int = 2


class AgentBlastRun(BaseModel):
    """Throw tests at the agent as drawn (edits that are not saved yet included): invented bombs and saved tests alike.
    ``repeats`` runs each more than once, since answers vary."""
    graph: AgentDefinitionSave
    tests: list[dict] = []
    repeats: int = 1


class AgentBlastFixes(BaseModel):
    """Propose fixes for the tests that exploded."""
    graph: AgentDefinitionSave
    results: list[dict] = []
