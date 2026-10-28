"""Who each agent is, as people meet them: a name, a title, a few words of
introduction and the Foundry room they work in.

One file (`agent_personas.json`) for every place an agent is shown — the
Foundry, the cockpit's agent dashboard, the spend charts. Before this each
kept its own label ("Data Modeler" in the office, `page_code:ui_engineer`
in the charts, a stage verb in the build strip) and they drifted. The
frontend carries a copy (`frontend/src/lib/agent-personas.json`); a test keeps
the two the same.

Names are display only: no prompt carries them, so renaming an agent changes
nothing an agent does.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PERSONAS_FILE = Path(__file__).with_name("agent_personas.json")

@lru_cache(maxsize=1)
def _doc() -> dict[str, Any]:
    return json.loads(PERSONAS_FILE.read_text("utf-8"))


def personas() -> dict[str, dict[str, Any]]:
    """`{agent: {name, title, room, intro}}`."""
    return _doc()["personas"]


def aliases() -> dict[str, str]:
    """Work recorded under a name that is not an agent's own key — the checks
    run as services and their usage rows name the service — and the agent
    it is: `app_check` → `testing`."""
    return _doc()["aliases"]


def agent_of(key: str) -> str | None:
    """The agent a usage row, a DAG node or a ledger names, or None.

    `page_code:ui_engineer` (a build's usage row) → `ui_engineer`;
    `app_check` → `testing`; `page_code` (a DAG node) → `ui_engineer`."""
    key = str(key or "").strip()
    if not key:
        return None
    known = personas()
    if ":" in key:
        # `node:agent`, `node:agent:edit` (an observer's repair): the agent is
        # the part that names one, read from the right.
        for part in reversed(key.split(":")):
            found = agent_of(part) if part and part != "edit" else None
            if found:
                return found
        return None
    key = key if key in known else key.lower()
    if key in known:
        return key
    if key in aliases():
        return aliases()[key]
    try:
        from services.blueprint.orchestrator import DAG
        node = DAG.get(key)
        if node is not None and node.agent in known:
            return node.agent
    except Exception:  # noqa: BLE001 — a name that cannot be placed is just not placed
        pass
    try:
        from services.office_events import LEGACY_AGENT_ALIAS
        legacy = LEGACY_AGENT_ALIAS.get(key)
        if legacy in known:
            return legacy
    except Exception:  # noqa: BLE001
        pass
    return None


def persona_for(key: str) -> dict[str, Any] | None:
    """`{agent, name, title, room, intro}` for anything `agent_of` places."""
    agent = agent_of(key)
    if agent is None:
        return None
    return {"agent": agent, **personas()[agent]}


__all__ = ["PERSONAS_FILE", "agent_of", "aliases", "persona_for", "personas"]
