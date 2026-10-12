"""After a build: what one agent could not settle alone, settled in a huddle.

Three things a build leaves undecided, each read from its own report:

  * a finding still wrong after the observer's rounds (`unrepaired`) — the
    node's author tried twice; the fix may lie in another agent's part, or
    the finding may ask for what the definition already does;
  * a node that stopped to ask (`blocked_because`);
  * a request for a change to another agent's part (`change_requests`) —
    collected, and until now never acted on.

Each becomes one huddle of the owners of what it names, the node's own agent
first, chaired by the observer, at most MAX_HUDDLES a build: the ones that
involve the most owners first, since those are the ones no single repair can
reach. It runs before the pages are repaired and the processes tried, so the
definition is settled before any code is mended to it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from services.huddle.room import Huddle, Room, carry_out, owners_named

logger = logging.getLogger(__name__)

#: The most deadlock huddles one build convenes.
MAX_HUDDLES = 4


def _agent_of(node: str) -> str:
    from services.blueprint.orchestrator import DAG
    n = DAG.get(node)
    return n.agent if n is not None else ""


def candidates(report: Any) -> list[dict]:
    """What the report leaves undecided, as huddles to convene — most owners
    first, then in the order the report has them."""
    from services.blueprint.verification import SECTION_OWNER
    out: list[dict] = []
    for label, why in (getattr(report, "unrepaired", None) or {}).items():
        node, _, subject = str(label).partition(":")
        agent = _agent_of(node)
        where = f"{node} ({subject})" if subject else node
        out.append({"kind": "unrepaired", "node": node, "subject": subject,
                    "topic": f"What the observer could not get right in {where} after its repair rounds",
                    "evidence": str(why), "participants": owners_named(str(why), also=agent)})
    for node, why in (getattr(report, "blocked_because", None) or {}).items():
        out.append({"kind": "blocked", "node": node, "subject": "",
                    "topic": f"{node} stopped to ask before it could decide",
                    "evidence": str(why), "participants": owners_named(str(why), also=_agent_of(node))})
    for cr in getattr(report, "change_requests", None) or []:
        if not isinstance(cr, dict):
            cr = {"section": getattr(cr, "section", ""), "reason": getattr(cr, "reason", ""),
                  "raisedBy": getattr(cr, "raised_by", "")}
        section, reason = str(cr.get("section") or ""), str(cr.get("reason") or "")
        raiser = str(cr.get("raisedBy") or "")
        node = raiser.split(":", 1)[1] if raiser.startswith("observer:") else ""
        owner = SECTION_OWNER.get(section, "")
        people = owners_named(reason, also=owner)
        asker = _agent_of(node) if node else raiser
        if asker and asker not in people:
            people = (people + [asker])[:3]
        out.append({"kind": "change_request", "node": node, "subject": "",
                    "topic": f"A change asked of {section or 'another part'}: {reason[:160]}",
                    "evidence": reason, "participants": people})
    seen: set[str] = set()
    unique = []
    for c in out:
        key = c["evidence"][:300]
        if c["participants"] and key not in seen:
            seen.add(key)
            unique.append(c)
    return sorted(unique, key=lambda c: -len(c["participants"]))


def client() -> Any:
    """The chair's and the participants' model: the observer's."""
    from services.blueprint.executors import AnthropicModel
    from services.blueprint.observer import OBSERVER_MODEL_ENV
    chosen = os.environ.get(OBSERVER_MODEL_ENV, "").strip()
    return AnthropicModel(model=chosen, effort="medium") if chosen else AnthropicModel(effort="medium")


def settle_deadlocks(svc: Any, output_dir: str, report: Any, *, app_root: str | None = None,
                     emit: Callable[[str, dict], None] | None = None, model: Any = None,
                     executor: Any = None, reasoning: Any = None) -> list[Huddle]:
    """Convene and carry out the build's deadlock huddles. Never fatal: a
    huddle that cannot run is said and the build's own result stands."""
    if (svc.doc.get("application") or {}).get("huddles") is False:
        return []
    todo = candidates(report)[:MAX_HUDDLES]
    if not todo:
        return []
    usage = None
    try:
        from services.blueprint.executors import RunUsage
        usage = RunUsage.for_app(svc, phase="huddle")
    except Exception:  # noqa: BLE001 — cost is recorded when it can be
        pass
    room = Room(output_dir, model if model is not None else client(), usage=usage, emit=emit)
    done: list[Huddle] = []
    for c in todo:
        try:
            h = room.convene(svc.doc, kind="deadlock", topic=c["topic"], participants=c["participants"],
                             evidence=c["evidence"],
                             trigger={k: c[k] for k in ("kind", "node", "subject")})
            h = carry_out(svc, h, app_root=app_root, reasoning=reasoning, executor=executor, hint=c["node"])
            done.append(h)
            logger.info("[huddle] %s %s: %s — %s", Path(output_dir).name, h.id, h.status,
                        h.decision.get("decision", "")[:160])
        except Exception:  # noqa: BLE001
            logger.warning("[huddle] %s: a huddle failed", Path(output_dir).name, exc_info=True)
    return done


__all__ = ["candidates", "settle_deadlocks", "client", "MAX_HUDDLES"]
