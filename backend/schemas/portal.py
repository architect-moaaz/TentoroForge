"""Pydantic schemas for portal, export, and monitoring endpoints."""

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Portal
# ---------------------------------------------------------------------------

class PortalAppBadges(BaseModel):
    pending_tasks: int = 0
    alerts: int = 0
    new_items: int = 0


class PortalApp(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str
    icon: str | None = None
    preview_port: int | None = None
    badges: PortalAppBadges = PortalAppBadges()


class PortalTask(BaseModel):
    id: str
    app_id: str
    app_name: str
    title: str
    description: str | None = None
    status: str = "pending"
    assignee_type: str = "person"
    due_at: str | None = None
    created_at: str
    workflow_name: str | None = None


class PortalActivity(BaseModel):
    id: str
    app_id: str
    app_name: str
    type: str
    title: str
    description: str | None = None
    actor_name: str | None = None
    created_at: str


class PortalDashboard(BaseModel):
    apps: list[PortalApp] = []
    tasks: list[PortalTask] = []
    activity: list[PortalActivity] = []


class PortalStats(BaseModel):
    total_apps: int = 0
    active_apps: int = 0
    pending_tasks: int = 0
    total_versions: int = 0
    recent_activity_count: int = 0


class SuggestedApp(BaseModel):
    department_id: str
    department_name: str
    suggestion: str


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportRequest(BaseModel):
    format: str = "zip"  # zip | dockerfile | git
    include_readme: bool = True
    include_docker_compose: bool = True
    include_env_example: bool = True
    git_remote_url: str | None = None
    git_branch: str | None = None


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------

class CostEntry(BaseModel):
    date: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    agent_type: str = ""


class ProjectCostSummary(BaseModel):
    project_id: str
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    daily: list[CostEntry] = []
    by_agent: dict[str, dict] = {}


class ErrorLogEntry(BaseModel):
    id: str
    project_id: str
    type: str
    message: str
    details: str | None = None
    agent_type: str | None = None
    resolved: bool = False
    created_at: str
