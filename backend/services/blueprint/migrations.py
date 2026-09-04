"""Blueprint document migrations — deterministic rewrites applied on load.

A migration changes vocabulary, never meaning. Each is idempotent, so loading
an already-migrated document is a no-op, and each returns what it changed so
the caller can record it in the version's ``migrations`` list (§91).
"""
from __future__ import annotations

from typing import Any

#: Blueprint step words that predate the workflow node catalog -> the catalog
#: node that means the same thing, plus the config the variant needs.
_STEP_TYPES: dict[str, tuple[str, dict[str, Any]]] = {
    "human_task": ("user_task", {}),
    "notification": ("action", {"actionType": "send_notification"}),
    "timer": ("wait", {}),
    "integration": ("action", {"actionType": "http_call"}),
}

_TRIGGER_KINDS: dict[str, str] = {"event": "api_event", "condition": "db_change"}


def migrate_workflow_vocabulary(doc: dict) -> list[str]:
    """Rewrite workflow steps and triggers into the workflow node catalog's words.

    Before the catalog, the Blueprint had its own step vocabulary, and the
    projection carried a translation table into the editor's. The table was
    where drift lived: ``human_task`` rendered as an unstyled box, and
    ``notification`` fell to the executor's unknown-type default and blocked
    the run as a human task. The Blueprint now speaks the catalog's vocabulary
    directly; this is the one-time rewrite of documents that predate it.

    ``start`` steps are dropped — the workflow's ``trigger`` is the start —
    and edges into them are redirected to what they pointed at.
    """
    changed: list[str] = []
    for wf in doc.get("workflows") or []:
        wid = wf.get("id") or wf.get("name") or "?"
        trigger = wf.get("trigger")
        if isinstance(trigger, dict) and trigger.get("kind") in _TRIGGER_KINDS:
            trigger["kind"] = _TRIGGER_KINDS[trigger["kind"]]
            changed.append(f"{wid}: trigger.kind -> {trigger['kind']}")

        steps = [s for s in (wf.get("steps") or []) if isinstance(s, dict)]
        starts = {s.get("key"): list(s.get("next") or []) for s in steps if s.get("type") == "start"}
        if starts:
            wf["steps"] = steps = [s for s in steps if s.get("type") != "start"]
            for s in steps:
                nxt = list(s.get("next") or [])
                if any(k in starts for k in nxt):
                    s["next"] = [t for k in nxt for t in (starts.get(k) or [k])]
            changed.append(f"{wid}: dropped {len(starts)} start step(s)")

        for s in steps:
            stype = s.get("type")
            if stype in _STEP_TYPES:
                ntype, extra = _STEP_TYPES[stype]
                s["type"] = ntype
                cfg = s.get("config") if isinstance(s.get("config"), dict) else {}
                for k, val in extra.items():
                    cfg.setdefault(k, val)
                s["config"] = cfg
                changed.append(f"{wid}/{s.get('key')}: {stype} -> {ntype}")
            cfg = s.get("config") if isinstance(s.get("config"), dict) else None
            if cfg and ("trueBranch" in cfg or "falseBranch" in cfg):
                # Branch order is carried by `next`: then first, else second.
                ordered = [cfg.pop("trueBranch", None), cfg.pop("falseBranch", None)]
                ordered = [k for k in ordered if k]
                rest = [k for k in (s.get("next") or []) if k not in ordered]
                s["next"] = ordered + rest
                changed.append(f"{wid}/{s.get('key')}: branches -> next order")
    return changed


MIGRATIONS = (migrate_workflow_vocabulary,)


def migrate(doc: dict) -> list[str]:
    """Apply every migration in order; return what changed."""
    changed: list[str] = []
    for m in MIGRATIONS:
        changed.extend(m(doc))
    return changed
