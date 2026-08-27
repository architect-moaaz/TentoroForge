"""Deterministic label → sidebar-icon-name map.

Used by :mod:`services.shell_menu_sync` when it derives the shell.json
menu from ``contracts/nav-flow.json``. No LLM, no per-app tuning — the
same label always resolves to the same icon.

Icon names are the Lucide/Feather subset the runtime shell already
renders (`user`, `calendar`, `briefcase`, `bar-chart`, `clipboard`,
`file`, `settings`, `home`, `folder`). Adding a new icon means adding a
new bucket here + adding the icon to the runtime.
"""
from __future__ import annotations

import re
from typing import Optional


# Priority order: earlier buckets win when a label mentions words from
# multiple buckets (e.g. "Interview Feedback" — 'interview' wins over
# 'feedback' → calendar, not clipboard). Bucket names picked to line up
# with common domain vocabulary; extend as needed.
_BUCKETS: list[tuple[str, frozenset[str]]] = [
    ("home",       frozenset({"home", "overview"})),
    ("user",       frozenset({
        "user", "users", "member", "members", "candidate", "candidates",
        "recruiter", "recruiters", "interviewer", "interviewers",
        "person", "people", "team", "employee", "employees", "staff",
        "customer", "customers", "contact", "contacts",
    })),
    ("calendar",   frozenset({
        "interview", "interviews", "meeting", "meetings",
        "appointment", "appointments", "schedule", "event", "events",
        "session", "sessions", "booking", "bookings",
    })),
    ("briefcase",  frozenset({
        "drive", "drives", "campaign", "campaigns",
        "project", "projects", "mission", "missions", "task", "tasks",
    })),
    ("bar-chart",  frozenset({
        "analytic", "analytics", "report", "reports",
        "dashboard", "metric", "metrics", "insight", "insights", "stat", "stats",
    })),
    ("clipboard",  frozenset({
        "audit", "log", "logs", "activity",
        "communication", "communications", "history",
        "notification", "notifications", "message", "messages",
    })),
    ("file",       frozenset({
        "file", "files", "document", "documents",
        "upload", "uploads", "attachment", "attachments",
        "cv", "cvs", "resume", "resumes",
    })),
    ("settings",   frozenset({
        "setting", "settings", "configuration", "config",
        "preference", "preferences", "admin",
    })),
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def icon_for(label: Optional[str]) -> str:
    """Return the icon name for a menu label or route slug.

    Case-insensitive; splits on non-alphanumeric so ``"CV Uploads"``,
    ``"cv_uploads"``, ``"cv-uploads"``, and ``"/cv-uploads"`` all map
    the same way. Falls back to ``"folder"`` when no bucket matches."""
    if not isinstance(label, str) or not label.strip():
        return "folder"
    tokens = _TOKEN_RE.findall(label.lower())
    for icon, vocab in _BUCKETS:
        if any(t in vocab for t in tokens):
            return icon
    return "folder"


# --------------------------------------------------------------------------- #
# Spec D Wave 5 — LLM nav-icon fallback (additive, flag-gated).               #
# The keyword classifier remains the primary path. When it falls all the way  #
# through to ``folder`` and FORGE_FIGMA_LLM is set, we ask the LLM to pick    #
# from the 60-icon Lucide subset. Registry-safety is enforced inside          #
# ``choose_nav_icon_llm`` — the LLM cannot invent an icon that isn't in the   #
# closed set. The Lucide PascalCase result is normalized to the                #
# lowercase-kebab convention this module has always emitted, so the           #
# shell renderer sees the shape it already handles.                           #
# --------------------------------------------------------------------------- #

_PASCAL_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _lucide_to_kebab(name: str) -> str:
    """``"BarChart"`` → ``"bar-chart"``. Preserves existing all-lowercase
    Feather names unchanged (``"folder"`` → ``"folder"``)."""
    if not name:
        return "folder"
    return "-".join(_PASCAL_SPLIT_RE.split(name)).lower()


def icon_for_with_llm(
    label: Optional[str],
    *,
    neighbors: Optional[list[str]] = None,
    domain: str = "",
) -> str:
    """Keyword-first icon pick. When the keyword classifier returns
    ``"folder"`` (its "I don't know" default) AND the Wave 5 LLM path is
    eligible (``FORGE_FIGMA_LLM`` set), ask the LLM to pick from the
    closed 60-icon Lucide subset. Result is normalized to kebab-case
    lowercase so downstream renderers see the historical shape.
    """
    keyword_pick = icon_for(label)
    if keyword_pick != "folder":
        return keyword_pick
    if not isinstance(label, str) or not label.strip():
        return keyword_pick

    from .figma_llm_ctx import (
        figma_llm_enabled,
        get_nav_icon_query_fn,
    )
    if not figma_llm_enabled():
        return keyword_pick

    try:
        from .nav_icon_llm import choose_nav_icon_llm
        choice = choose_nav_icon_llm(
            label,
            neighbors=list(neighbors or []),
            domain=domain,
            query_fn=get_nav_icon_query_fn(),
        )
        if choice.icon and choice.icon != "Folder":
            return _lucide_to_kebab(choice.icon)
    except Exception:  # noqa: BLE001
        pass
    return keyword_pick
