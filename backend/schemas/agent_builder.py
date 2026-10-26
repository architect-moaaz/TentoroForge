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


class AgentBlastWrite(BaseModel):
    """Have an AI write everyday test cases (not attacks) for the agent as drawn, each with a note on what a good reply is."""
    graph: AgentDefinitionSave
    count: int = 10


class AgentBlastTool(BaseModel):
    """Have an AI study ONE tool of the agent as drawn and write the tests that would break it: normal use, bad input,
    extremes, hidden orders, permission, secrets, failure, truthfulness. ``angles`` limits them (all when omitted)."""
    graph: AgentDefinitionSave
    tool: str
    angles: list[str] | None = None
    per_angle: int = 2


class AgentRecordingSend(BaseModel):
    """Chats recorded in Watch live, sent to Find problems as saved tests and (when ``fix``) to the fixer."""
    chats: list[dict] = []
    fix: bool = False
    #: The assistant as drawn. Needed only when ``fix`` is set.
    graph: AgentDefinitionSave | None = None


class AgentBlastFixes(BaseModel):
    """Propose fixes for the tests that exploded."""
    graph: AgentDefinitionSave
    results: list[dict] = []


class AgentBriefChange(BaseModel):
    """A change the assistant of a workflow step may propose: the workflow it asks to run, and why."""
    tool: str
    why: str = ""


class AgentBrief(BaseModel):
    """What a workflow step's assistant is for, in a few lines: the build draws the assistant from it."""
    purpose: str
    reads: list[str] = []
    mayChange: list[AgentBriefChange] = []
    instructions: str | None = None


class AgentFromBrief(BaseModel):
    """Make the workflow-only assistant a workflow step needs, from its brief (see services/agent_suggest.agent_for_brief).
    ``workflowId`` and ``stepId`` say which step it is for, when the caller knows (the id the assistant gets, and the
    workflow it must not be able to start again, come from them)."""
    brief: AgentBrief
    workflowId: str | None = None
    stepId: str | None = None
    name: str | None = None
