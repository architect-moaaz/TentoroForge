# backend/services/crud_actions.py
"""Deterministic CRUD action derivation per page-type.

Given a page + its entity + the set of workflows that actually exist, return the
standard action buttons: navigate (New/Edit) and workflow (Delete). These merge
into the plan page's actions[] for the binding pass to wire. CRUD only — domain
process actions stay LLM-declared.
"""
from __future__ import annotations

import json
import logging
import os
import re

from services.entity_names import EntityNameError, entity_key

logger = logging.getLogger(__name__)


def build_workflow_index(output_dir: str | os.PathLike) -> dict:
    """Read `workflows/*.json` → an index of the identifiers the runtime cache is
    keyed by, so the binding pass can canonicalize/guard button workflow refs.

    The runtime (`src/lib/workflows/index.ts`) caches each workflow by BOTH
    `definition.id` and `definition.name`. This mirrors that:
      - `exact`: sorted list of every id/name (the exact cache keys),
      - `norm`:  {normalized-key → canonical name} where the normalized key strips
                 casing/separators, so `createLeaveRequest` resolves to the real
                 `CreateLeaveRequest`. Canonical target prefers `name`, then `id`,
                 then the filename stem.

    Best-effort + I/O-safe: a missing dir or unparseable file yields an empty
    (no-op) index rather than raising.
    """
    wf_dir = os.path.join(str(output_dir), "workflows")
    exact: set[str] = set()
    norm: dict[str, str] = {}
    ambiguous: dict[str, set] = {}
    if not os.path.isdir(wf_dir):
        return {"exact": [], "norm": norm, "ambiguous": {}}
    for fn in sorted(os.listdir(wf_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(wf_dir, fn), encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001 — a bad file must not break the pipeline
            continue
        if not isinstance(d, dict):
            continue
        wid = d.get("id")
        wname = d.get("name")
        stem = fn[:-5]
        canonical = wname or wid or stem
        for key in (wname, wid, stem):
            if key and isinstance(key, str):
                exact.add(key)
                nk = re.sub(r"[^a-z0-9]", "", key.lower())
                if not nk:
                    continue
                prev = norm.get(nk)
                if prev is None:
                    norm[nk] = canonical
                elif prev != canonical:
                    # A normalised-key COLLISION.
                    #
                    # `setdefault` kept whichever workflow was read off disk
                    # first, so `Create_Order` and `CreateOrder` — two genuinely
                    # different workflows — collapsed to one and a button could
                    # dispatch the wrong one. Which is "right" is unknowable
                    # here, so record the ambiguity and resolve to NEITHER;
                    # callers fall back to an exact match, which is always safe.
                    ambiguous.setdefault(nk, {prev}).add(canonical)
    for nk in ambiguous:
        norm.pop(nk, None)
    if ambiguous:
        logger.warning(
            "crud_actions: %d workflow name(s) collide after normalisation and "
            "will only resolve on an EXACT match: %s",
            len(ambiguous),
            "; ".join(f"{k} -> {sorted(v)}" for k, v in sorted(ambiguous.items())),
        )
    return {
        "exact": sorted(exact),
        "norm": norm,
        "ambiguous": {k: sorted(v) for k, v in ambiguous.items()},
    }


def resolvable_workflow_names(output_dir) -> set[str]:
    """Every string the RUNTIME will resolve to a workflow.

    Use this instead of a set of filename stems. `loadWorkflows` caches each
    workflow under both `definition.id` and `definition.name` (KT Part 8), so a
    file named `delete_order.json` declaring `name: "DeleteOrder"` resolves
    perfectly at runtime — but a stem-based check could not see it and withheld
    the Delete button entirely (register BA-1)."""
    return set(build_workflow_index(output_dir).get("exact") or [])


def _form_route(entity: str, pages: list[dict], kind: str) -> str | None:
    """Find a form page route for this entity ('new'/'edit' heuristics).

    Preference order:
      - 'new': a route mentioning 'new' (or any non-'edit' form route).
      - 'edit': a route mentioning 'edit'; else fall back to any form route for
        the entity (a single shared form page handles both new and edit).
    """
    want = "new" if kind == "new" else "edit"
    fallback: str | None = None
    # Entity match is by CANONICAL KEY, not string equality (register BA-7).
    # `p["entity"] == entity` meant one character of drift — "Orders" on the
    # page vs "Order" in the plan — matched nothing, and every navigate action
    # on the page silently disappeared. entity_names is the authority for this.
    want_key = _safe_key(entity)
    for p in pages or []:
        if p.get("type") != "form":
            continue
        if _safe_key(p.get("entity")) != want_key:
            continue
        route = p.get("route")
        r = (route or "").lower()
        if want in r:
            return route
        # ONE-WAY exclusion: `new` must never fall back to an edit route.
        #
        # The old condition accepted any route not containing "edit" and
        # otherwise fell through to `fallback`, which could be the edit route
        # itself — so with only an edit form present, "New" opened the EDIT
        # form for whatever record happened to be in context (register BA-8).
        # Editing an arbitrary or absent record is a genuine wrong action.
        #
        # The reverse is NOT symmetric and must stay allowed: falling back from
        # `edit` to a `/new` route is the documented shared-form behaviour —
        # one form page commonly serves both create and edit — and it lands the
        # user somewhere sane.
        if want == "new" and "edit" in r:
            continue
        if fallback is None:
            fallback = route
    return fallback


def _safe_key(name) -> str | None:
    """Canonical entity key, or None when the value cannot be keyed."""
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        return entity_key(name)
    except EntityNameError:
        return None


def derive_crud_actions(page: dict, entity: str | None, existing_workflows: set,
                        pages: list[dict]) -> list[dict]:
    """Standard CRUD actions for a page. Each action is
    {label, kind, workflow?, to?}. Only emits Delete when Delete<Entity> exists;
    nav actions only when a target route exists."""
    if not entity:
        return []
    ptype = (page.get("type") or "").lower()
    out: list[dict] = []
    delete_wf = f"Delete{entity}"

    if ptype == "list":
        new_route = _form_route(entity, pages, "new")
        if new_route:
            out.append({"label": "New", "kind": "navigate", "to": new_route})
        if delete_wf in existing_workflows:
            out.append({"label": "Delete", "kind": "row_action", "workflow": delete_wf})
    elif ptype == "detail":
        edit_route = _form_route(entity, pages, "edit")
        if edit_route:
            out.append({"label": "Edit", "kind": "navigate", "to": edit_route})
        if delete_wf in existing_workflows:
            out.append({"label": "Delete", "kind": "page_action", "workflow": delete_wf})
    return out


def merge_crud_into_page(page: dict, plan: dict, existing_workflows: set) -> dict:
    """Return a COPY of page whose actions[] include derived CRUD actions
    (appended, de-duped by (label, kind)). Non-mutating."""
    import copy as _copy
    entity = page.get("entity")
    derived = derive_crud_actions(page, entity, existing_workflows,
                                  (plan or {}).get("pages") or [])
    out = _copy.deepcopy(page)

    # A malformed `actions` must not raise (register BA-10).
    #
    # `existing + [...]` raised TypeError when `actions` was a dict or a bare
    # string, and one call site swallowed the exception — so the page silently
    # ended up with ZERO derived actions and every CRUD button was missing,
    # with nothing logged.
    raw = out.get("actions")
    if raw is None:
        existing: list = []
    elif isinstance(raw, list):
        existing = raw
    else:
        logger.error(
            "crud_actions: page %r has `actions` of type %s, not a list — it is "
            "being replaced with the derived actions. Anything it declared is lost.",
            out.get("route") or out.get("entity"), type(raw).__name__,
        )
        existing = []

    # De-dup on (label, kind) ONLY when the existing action is real.
    #
    # A placeholder that carries neither a workflow nor a target is a phantom:
    # it renders a button that does nothing. Counting it as "already present"
    # suppressed the real derived action, so the phantom won and the page
    # shipped a dead button (register BA-9).
    seen = {
        (a.get("label"), a.get("kind"))
        for a in existing
        if isinstance(a, dict) and _is_real_action(a)
    }
    out["actions"] = existing + [
        a for a in derived if (a["label"], a["kind"]) not in seen
    ]
    return out


def _is_real_action(action: dict) -> bool:
    """Does this action actually do something? A phantom carries no workflow,
    no navigation target and no handler."""
    return any(
        action.get(k) for k in ("workflow", "to", "href", "route", "onClick", "action")
    )
