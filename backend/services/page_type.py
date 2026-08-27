# backend/services/page_type.py
"""Deterministic page-type inference from route + role. No LLM.

Used by the reference-bank loader to pick which exemplars to inject into the
schema agent's prompt at gen time."""
from __future__ import annotations

from typing import Literal, Protocol


PageType = Literal[
    "list", "detail", "form", "dashboard", "settings", "generic",
    "workspace", "console", "inspector", "wizard", "audit-log", "report",
]


class _BriefLike(Protocol):
    route: str
    role: str | None


def infer_page_type(page_brief: _BriefLike) -> str:
    """Infer one of: list | detail | form | dashboard | settings | generic |
    workspace | console | inspector | wizard | audit-log | report

    Resolution order: route patterns first (most reliable), then role keywords.
    New Wave 5 archetypes are checked before v1 patterns so they take priority
    when their signals are present. Form patterns (`/new`, `/edit`) still take
    precedence over detail (`[id]`) since `/users/[id]/edit` is a form."""
    route = (page_brief.route or "").lower()
    role = (page_brief.role or "").lower()

    # New archetype patterns (Wave 5) — checked before v1 patterns
    if "/workspace" in route or "workspace" in role:
        return "workspace"
    if "/console" in route or "operations console" in role:
        return "console"
    if "/inspector" in route or "/inspect" in route or "drill-in" in role:
        return "inspector"
    if route.endswith("/wizard") or "/onboarding" in route or "multi-step" in role or "wizard" in role:
        return "wizard"
    if "/audit" in route or "/history" in route or "audit log" in role or "activity log" in role:
        return "audit-log"
    if "/reports" in route or "/analytics" in route or "report" in role or "analytics" in role:
        return "report"

    # Existing v1 patterns
    # Form patterns first — they often contain `[id]` but are forms, not details
    if route.endswith("/new") or route.endswith("/edit") or route.endswith("/create"):
        return "form"
    # List patterns
    if route.endswith("/list") or route.endswith("/index") or route.endswith("/all"):
        return "list"
    # Detail patterns
    if "[id]" in route or "{id}" in route:
        return "detail"
    # Dashboard / overview
    if "/dashboard" in route or "/overview" in route or "/home" == route:
        return "dashboard"
    # Settings / profile
    if "/settings" in route or "/profile" in route or "/account" in route:
        return "settings"
    # Role-keyword fallbacks
    if "list" in role or "browse" in role or "all" in role:
        return "list"
    if "edit" in role or "create" in role or "new" in role:
        return "form"
    if "metric" in role or "kpi" in role or "dashboard" in role or "overview" in role:
        return "dashboard"
    if "settings" in role or "profile" in role or "preferences" in role:
        return "settings"
    if "detail" in role or "view" in role:
        return "detail"
    return "generic"
