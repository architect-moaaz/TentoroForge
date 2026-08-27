"""Virtual office visualization — enriched SSE event helpers.

Provides factory functions for agent-lifecycle events that the frontend
virtual-office view can consume alongside the existing phase/status events.
"""

from __future__ import annotations

import json
from typing import Optional


# ---------------------------------------------------------------------------
# Phase → agent/room mappings
# ---------------------------------------------------------------------------

PHASE_TO_AGENTS: dict[str, list[str]] = {
    "planning": ["planner"],
    "contract": ["contract_writer"],
    "schema": ["schema_designer"],
    "auth": ["auth_agent"],
    "api": ["api_generator"],
    "business_logic": ["bizlogic_agent"],
    "components": ["component_builder", "ui_styler"],
    "pages": ["page_assembler", "navigator"],
    "seed": ["seed_generator"],
    "qa": ["qa_tester"],
    "validation": ["validator"],
    "indexing": ["indexer"],
}

PHASE_TO_ROOM: dict[str, str] = {
    "planning": "planning",
    "contract": "planning",
    "schema": "design_studio",
    "auth": "security",
    "api": "dev_api",
    "business_logic": "dev_logic",
    "components": "dev_ui",
    "pages": "dev_ui",
    "seed": "shipping",
    "qa": "qa_lab",
    "validation": "qa_lab",
    "indexing": "library",
}


# ---------------------------------------------------------------------------
# Event factory helpers — each returns a plain dict ready for sse_event()
# ---------------------------------------------------------------------------

def agent_start_event(agent_id: str, room: str) -> dict:
    """An agent has started working in a room."""
    return {"type": "agent_start", "agent": agent_id, "room": room}


def agent_status_event(agent_id: str, status: str, progress: Optional[float] = None) -> dict:
    """Progress update for a running agent."""
    evt: dict = {"type": "agent_status", "agent": agent_id, "status": status}
    if progress is not None:
        evt["progress"] = progress
    return evt


def agent_handoff_event(from_agent: str, to_agent: str, artifact: Optional[str] = None) -> dict:
    """One agent hands off work to another."""
    evt: dict = {"type": "agent_handoff", "from": from_agent, "to": to_agent}
    if artifact is not None:
        evt["artifact"] = artifact
    return evt


def agent_complete_event(agent_id: str, files_generated: int = 0) -> dict:
    """An agent has finished its work."""
    return {"type": "agent_complete", "agent": agent_id, "files_generated": files_generated}


def parallel_start_event(agent_ids: list[str]) -> dict:
    """Multiple agents are starting work in parallel."""
    return {"type": "parallel_start", "agents": agent_ids}


def build_success_event(total_files: int = 0, total_lines: int = 0) -> dict:
    """The entire build completed successfully."""
    return {"type": "build_success", "total_files": total_files, "total_lines": total_lines}
