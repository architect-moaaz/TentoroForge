"""The run acting on what its own agents told it.

§30 gives an agent a way to say that the fault is in somebody else's section:
a `ChangeRequest` naming the section and the reason. Every agent could raise
one and the run collected them into the report, where a person might read them
afterwards. Nothing acted.

On a calculator whose requirements say nothing is stored, `entity_fields`
raised exactly the right one — "CalculatorSession is transient, browser-only,
non-persisted state, but it is required to be modelled here as a database
entity; recommend removing this entity" — at confidence 0.35, and the observer
agreed twice. The run then spent seven minutes authoring that table's columns,
declined the page three times for having no records to summarise, and produced
an application that cannot work. Three agents identified the fault and none of
them could do anything about it.

WHAT IS ACTED ON, AND WHAT IS NOT. Only a request that names an artifact by id
and asks for it to be RETIRED. That is a decision the document can carry out
exactly — set its status and say who asked — where "this section is wrong"
cannot be. Prose is still recorded for a person to read; it is not guessed at.

Retiring is not deleting. §92 keeps the artifact and its history; what changes
is that nothing downstream builds on it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Sections an agent may ask to have something retired from, and where they
#: live in the document. Named rather than derived: a change request that can
#: retire anything at all is a way for one agent to delete another's work by
#: accident, and these are the ones a downstream stage can genuinely know are
#: wrong — the records, the processes, the screens and the rules it was handed.
RETIRABLE: dict[str, tuple[str, ...]] = {
    "data.entities": ("data", "entities"),
    "entities": ("data", "entities"),
    "workflows": ("workflows",),
    "pages": ("pages",),
    "businessRules": ("businessRules",),
    "business_rules": ("businessRules",),
    "apis": ("apis",),
    "integrations": ("integrations",),
}

#: Already retired, so a second request is a no-op rather than a change.
_RETIRED = ("DEPRECATED", "SUPERSEDED")


def _rows(doc: dict, path: tuple[str, ...]) -> list[dict]:
    node: Any = doc
    for step in path:
        node = (node or {}).get(step) if isinstance(node, dict) else None
    return [r for r in (node or []) if isinstance(r, dict)]


def _asked(cr: Any) -> tuple[str, str, str]:
    """(section, reason, id-to-retire) from a request in either shape."""
    if isinstance(cr, dict):
        return (str(cr.get("section") or ""), str(cr.get("reason") or ""),
                str(cr.get("retire") or ""))
    return (str(getattr(cr, "section", "") or ""),
            str(getattr(cr, "reason", "") or ""),
            str(getattr(cr, "retire", "") or
                (getattr(cr, "proposed", None) or {}).get("retire") or ""))


def actionable(change_requests: Any, doc: dict) -> list[dict]:
    """The requests this run can carry out itself, as {section, id, reason}.

    A request is actionable when it names a retirable section, names an id
    that section really holds, and that artifact is still live. Anything else
    — a section nobody owns, an id that does not exist, an artifact already
    retired — is left for the report, because acting on a guess is worse than
    not acting.
    """
    out: list[dict] = []
    for cr in change_requests or []:
        section, reason, wanted = _asked(cr)
        path = RETIRABLE.get(section.strip())
        if not path or not wanted:
            continue
        for row in _rows(doc, path):
            if str(row.get("id")) != wanted.strip():
                continue
            if str(row.get("status") or "") in _RETIRED:
                break
            out.append({"section": section, "path": path, "id": wanted.strip(),
                        "reason": reason.strip(), "name": str(row.get("name") or "")})
            break
    return out


def apply_corrections(svc: Any, change_requests: Any, *, asked_by: str = "") -> list[str]:
    """Retire what an agent asked to have retired. Returns what was retired.

    Committed like any other change, so the history says which stage asked and
    why — an artifact that vanishes with no record is indistinguishable from
    one that was never there.
    """
    acts = actionable(change_requests, svc.doc)
    if not acts:
        return []
    before = svc.snapshot()
    done: list[str] = []
    for act in acts:
        for row in _rows(svc.doc, act["path"]):
            if str(row.get("id")) == act["id"]:
                row["status"] = "DEPRECATED"
                done.append(act["id"])
                logger.info("[corrections] retired %s (%s) at %s's request: %s",
                            act["id"], act["name"] or "unnamed", asked_by or "an agent",
                            act["reason"][:160])
                break
    if not done:
        return []
    try:
        svc.validate()
        svc.commit(
            user_request=f"retire {', '.join(done)}",
            smith_interpretation=(
                f"{asked_by or 'a later stage'} reported these contradict the "
                f"requirements: {'; '.join(a['reason'] for a in acts if a['reason'])[:400]}"),
            before=before,
            affected=done,
        )
    except Exception as exc:  # noqa: BLE001 — a correction must not fail the run
        logger.warning("[corrections] could not commit the retirement: %s", exc)
        svc.doc = before
        return []
    return done


__all__ = ["RETIRABLE", "actionable", "apply_corrections"]
