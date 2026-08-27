"""Materialize ``plan['wizards']`` into concrete multi-step form pages.

The fifth primitive in the wire-pass pattern (see
:mod:`services.audit_trail_wire` for the pilot).

Runtime pairing
---------------
Unlike the 4 pure-declarative primitives before it, wizard needs a
matching runtime component to *actually* step through the fields.
That component is
:file:`backend/templates/app-foundation/src/lib/WizardShell.tsx`;
it reads the ``wizard`` metadata this pass emits.

Plan slot
---------
::

    "wizards": [
        {
            "name": "candidate_application",
            "route": "/candidate/apply",
            "entity": "Candidate",
            "workflow": "submit_candidate_application",
            "steps": [
                {"title": "Personal Info",
                 "fields": ["full_name", "email", "phone"]},
                {"title": "Documents",
                 "fields": ["cv", "passport"]},
                {"title": "Preferences",
                 "fields": ["base_location", "willing_to_relocate"]},
            ],
        },
    ]

Fields:
  * ``name`` (required): unique wizard name; page uses it verbatim.
  * ``route`` (required): the URL path for the wizard page.
  * ``entity`` (required): the entity the wizard collects data for.
  * ``workflow`` (optional): the submit workflow id. When absent the
    downstream form-submit builder falls back to its existing
    inference (usually the entity's create workflow).
  * ``steps`` (required): list of steps, each ``{title, fields}``.
    ``fields`` is a list of field-name strings referring to columns
    on the entity.

Malformed / partial entries are silently dropped.

Emitted page shape
------------------
For each valid declaration this pass adds a page::

    {
      "route": "<route>",
      "archetype": "form",
      "entity": "<entity>",
      "wizard": {
        "steps": [
          {"title": "Personal Info", "field_names": ["full_name", ...]},
          ...
        ],
      },
      "fields": [
        {"name": "full_name",  "wizard_step": 0},
        {"name": "email",      "wizard_step": 0},
        ...
      ],
      "actions": [
        {"kind": "form_submit", "workflow": "<workflow>"}
      ],
    }

Downstream form-page builders see a normal ``archetype: form`` page;
the WizardShell runtime intercepts on ``page.wizard`` and drives the
step machinery client-side.
"""
from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_wizard_enabled() -> bool:
    return os.getenv("FORGE_WIZARD", "").lower() in (
        "1", "true", "yes", "on",
    )


def wire_wizards(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a new plan with wizard declarations materialized as
    wizard-shaped form pages."""
    if not isinstance(plan, dict):
        return plan
    declarations = _read_declarations(plan)
    if not declarations:
        return dict(plan)

    new_plan = copy.deepcopy(plan)
    pages = new_plan.get("pages")
    if not isinstance(pages, list):
        pages = []
        new_plan["pages"] = pages

    existing_routes = {
        p.get("route") for p in pages
        if isinstance(p, dict) and isinstance(p.get("route"), str)
    }
    for d in declarations:
        if d["route"] in existing_routes:
            continue  # Idempotency + never clobber an author's page.
        pages.append(_build_wizard_page(d))
        existing_routes.add(d["route"])
    return new_plan


# ────────────────────────────────────────────────────────────
# Declaration normalization
# ────────────────────────────────────────────────────────────

def _read_declarations(plan: dict) -> list[dict]:
    raw = plan.get("wizards")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        route = item.get("route")
        entity = item.get("entity")
        steps_raw = item.get("steps")
        if not (isinstance(name, str) and name.strip()):
            continue
        if not (isinstance(route, str) and route.startswith("/")):
            continue
        if not (isinstance(entity, str) and entity.strip()):
            continue
        if not isinstance(steps_raw, list) or not steps_raw:
            continue

        steps = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                continue
            title = s.get("title") or f"Step {i + 1}"
            fields_raw = s.get("fields") or []
            if not isinstance(fields_raw, list):
                continue
            fields = [f.strip() for f in fields_raw
                      if isinstance(f, str) and f.strip()]
            if not fields:
                continue
            steps.append({"title": str(title), "fields": fields})
        if not steps:
            continue

        wf = item.get("workflow")
        out.append({
            "name":     name.strip(),
            "route":    route.strip(),
            "entity":   entity.strip(),
            "workflow": wf.strip() if isinstance(wf, str) and wf.strip() else None,
            "steps":    steps,
        })
    return out


# ────────────────────────────────────────────────────────────
# Page emission
# ────────────────────────────────────────────────────────────

def _build_wizard_page(decl: dict) -> dict:
    fields: list[dict] = []
    steps_meta: list[dict] = []
    for step_i, step in enumerate(decl["steps"]):
        steps_meta.append({
            "title":       step["title"],
            "field_names": list(step["fields"]),
        })
        for fname in step["fields"]:
            fields.append({"name": fname, "wizard_step": step_i})

    actions: list[dict] = []
    if decl["workflow"]:
        actions.append({"kind": "form_submit", "workflow": decl["workflow"]})

    return {
        "route":     decl["route"],
        "archetype": "form",
        "entity":    decl["entity"],
        "wizard":    {"steps": steps_meta},
        "fields":    fields,
        "actions":   actions,
        "name":      decl["name"],
    }
