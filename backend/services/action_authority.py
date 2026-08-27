"""ACTION-AUTHORITY contract — pure helpers.

Slice B of the Feature-Authoring Roadmap. Mirrors :mod:`services.submit_authority`
for non-form action buttons: the primary domain-action buttons on
detail pages / list toolbars ("Approve", "Reject", "Send for review",
"Escalate"), the buttons that aren't form submits and aren't CRUD
"New X" (Bug #3 covered that class).

Today those buttons are LLM-authored labels; ``button_audit`` heals
the confidently-labelled ones by fuzzy label→workflow / label→route
matching, but the plan itself doesn't declare "the ApplicantDetail page
has an Approve button that dispatches ApproveRequest with
applicantId=route.id". That gap explains three failure modes pages+nav
can't catch:

  1. Wrong-but-existing refs — button ``workflow`` points at the wrong
     (real) workflow. Phantom guards pass; the button silently does
     the wrong thing.
  2. Missing buttons — the plan intends an Approve action; the LLM
     forgets to author it; nothing else knows to insert it.
  3. Input-map mismatches — the workflow needs ``applicantId``,
     ``reviewerId``; the button dispatches without wiring them.

The contract:

  * ``page.actions[]`` — per-page declaration of the primary domain-
    action buttons. Each entry::

        {
          "label":  "Approve",
          "kind":   "workflow" | "navigate",
          "target": "<workflow name>" | "<route>",
          "input_map": {"<workflow_input>": {"kind": ..., ...}},
          "variant": "primary" | "secondary" | ...,      # UI hint
          "requires_confirm": true | false,               # UI hint
        }

  * The deterministic page builder consumes ``page.actions`` and emits
    buttons verbatim (Slice B follow-up).
  * The plan validator rejects a plan where a declared action's
    target doesn't resolve or a required workflow input has no source.

This module is the pure reader/validator surface. No I/O, no LLM.
"""
from __future__ import annotations

import re
from typing import Any


# The same five source kinds the form-input contract supports. Actions
# are dispatchers of workflows too, so they share the vocabulary.
_KNOWN_SOURCE_KINDS = frozenset({
    "form_field", "route", "auth", "static", "computed",
})

_KNOWN_ACTION_KINDS = frozenset({"workflow", "navigate"})

_ROUTE_PARAM_RE = re.compile(
    r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]|:([a-zA-Z_][a-zA-Z0-9_]*)"
)


# --------------------------------------------------------------------------- #
# resolve_page_actions
# --------------------------------------------------------------------------- #

def resolve_page_actions(plan: Any, page_name: str) -> list[dict]:
    """Return the normalized ``actions`` for a page, or ``[]`` when the
    page isn't declared or has no actions.

    Each returned entry has ``kind``, ``target``, ``label``, ``input_map``
    (dict — may be empty), plus any UI hints the planner declared
    (``variant``, ``requires_confirm``). Malformed entries are dropped
    silently (the validator surfaces them separately).
    """
    if not isinstance(plan, dict) or not page_name:
        return []
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return []
    for p in pages:
        if not isinstance(p, dict) or p.get("name") != page_name:
            continue
        return _normalize_actions(p.get("actions"))
    return []


def _normalize_actions(raw: Any) -> list[dict]:
    """Normalize a raw ``actions`` list from a plan page.

    Each entry becomes::

        {"label": str, "kind": "workflow"|"navigate", "target": str,
         "input_map": {input_name: source_spec}, ...ui hints}

    Entries missing a target OR with an unknown kind are dropped. The
    validator picks these up separately as errors — this reader gives
    downstream code a clean list it can trust.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label")
        kind = entry.get("kind")
        target = entry.get("target")
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(kind, str) or kind not in _KNOWN_ACTION_KINDS:
            continue
        if not isinstance(target, str) or not target.strip():
            continue
        normalized: dict = {
            "label":  label.strip(),
            "kind":   kind,
            "target": target.strip(),
            "input_map": _normalize_input_map(entry.get("input_map")),
        }
        # Passthrough UI hints so the deterministic builder can honor them.
        for key in ("variant", "requires_confirm", "icon", "confirmMessage"):
            if key in entry:
                normalized[key] = entry[key]
        out.append(normalized)
    return out


def _normalize_input_map(raw: Any) -> dict[str, dict]:
    """Normalize the per-action ``input_map``. Each value must be a
    source-spec dict with a known ``kind``; malformed entries are
    dropped."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(spec, dict):
            continue
        kind = spec.get("kind")
        if kind not in _KNOWN_SOURCE_KINDS:
            continue
        out[name] = dict(spec)
    return out


# --------------------------------------------------------------------------- #
# validate_action_targets
# --------------------------------------------------------------------------- #

def validate_action_targets(plan: Any) -> list[dict]:
    """Validate every declared action across every page. Returns a flat
    list of error dicts::

        {"kind": "<error kind>", "page": "<page name>",
         "label": "<action label>", "detail": "..."}

    Error kinds:
      * ``unknown_action_kind``    — ``kind`` not workflow|navigate
      * ``missing_action_target``  — no ``target`` on the entry
      * ``phantom_workflow_target`` — ``kind=workflow`` but the workflow
                                      doesn't exist in ``plan.workflows``
      * ``phantom_navigate_target`` — ``kind=navigate`` but the target
                                      route isn't declared in
                                      ``plan.pages``
      * ``route_param_missing``    — an input's ``source.kind=route``
                                     names a param the containing
                                     page's route doesn't declare
      * ``unknown_source_kind``    — an input's source kind is bogus
    """
    if not isinstance(plan, dict):
        return []
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return []

    workflow_names: set[str] = set()
    for wf in plan.get("workflows") or []:
        if isinstance(wf, dict):
            name = wf.get("name")
            if isinstance(name, str) and name.strip():
                workflow_names.add(name.strip())

    known_routes: set[str] = set()
    for p in pages:
        if isinstance(p, dict):
            route = p.get("route")
            if isinstance(route, str) and route.strip():
                known_routes.add(route.strip())

    errors: list[dict] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_name = page.get("name") or ""
        page_route = page.get("route") or ""
        raw_actions = page.get("actions")
        if raw_actions is None:
            continue
        if not isinstance(raw_actions, list):
            errors.append({
                "kind":   "invalid_actions_type",
                "page":   page_name,
                "detail": f"page.actions must be a list, got {type(raw_actions).__name__}",
            })
            continue
        route_params = {
            m.group(1) or m.group(2)
            for m in _ROUTE_PARAM_RE.finditer(page_route)
        }
        for entry in raw_actions:
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or "(unlabeled)"
            kind = entry.get("kind")
            target = entry.get("target")
            if kind not in _KNOWN_ACTION_KINDS:
                errors.append({
                    "kind":   "unknown_action_kind",
                    "page":   page_name, "label": label,
                    "detail": f"kind must be one of {sorted(_KNOWN_ACTION_KINDS)}, got {kind!r}",
                })
                continue
            if not isinstance(target, str) or not target.strip():
                errors.append({
                    "kind":   "missing_action_target",
                    "page":   page_name, "label": label,
                    "detail": "target is required",
                })
                continue
            target = target.strip()
            if kind == "workflow" and target not in workflow_names:
                errors.append({
                    "kind":   "phantom_workflow_target",
                    "page":   page_name, "label": label,
                    "detail": f"workflow {target!r} not declared in plan.workflows",
                })
            elif kind == "navigate" and target not in known_routes:
                errors.append({
                    "kind":   "phantom_navigate_target",
                    "page":   page_name, "label": label,
                    "detail": f"route {target!r} not declared in plan.pages",
                })
            # Input-map source validation. Only route-param existence is
            # cheaply checkable here; form_field / auth / static /
            # computed are validated downstream when their target
            # context is available.
            input_map = entry.get("input_map")
            if not isinstance(input_map, dict):
                continue
            for inp_name, spec in input_map.items():
                if not isinstance(spec, dict):
                    continue
                s_kind = spec.get("kind")
                if s_kind not in _KNOWN_SOURCE_KINDS:
                    errors.append({
                        "kind":   "unknown_source_kind",
                        "page":   page_name, "label": label,
                        "input":  inp_name,
                        "detail": (
                            f"source.kind must be one of "
                            f"{sorted(_KNOWN_SOURCE_KINDS)}, got {s_kind!r}"
                        ),
                    })
                    continue
                if s_kind == "route":
                    param = spec.get("param")
                    if not isinstance(param, str) or not param:
                        errors.append({
                            "kind":   "route_param_missing",
                            "page":   page_name, "label": label,
                            "input":  inp_name,
                            "detail": "route source requires a `param` key",
                        })
                    elif param not in route_params:
                        errors.append({
                            "kind":   "route_param_missing",
                            "page":   page_name, "label": label,
                            "input":  inp_name,
                            "detail": (
                                f"route param {param!r} not declared in "
                                f"page.route {page_route!r} "
                                f"(known: {sorted(route_params)})"
                            ),
                        })
    return errors


# --------------------------------------------------------------------------- #
# derive_button_props
# --------------------------------------------------------------------------- #

def derive_button_props(action: dict) -> dict:
    """Turn one normalized action into a Button node's ``props``.

    Used by the deterministic page builder (Slice B follow-up) so the
    builder never has to know the action shape — it just calls this and
    plugs the returned dict into ``{"type": "Button", "props": ...}``.

    Shape:
      * ``kind=workflow`` → ``{"label", "workflow", "input_map", "variant"?}``
      * ``kind=navigate`` → ``{"label", "navigate", "variant"?}``
    """
    if not isinstance(action, dict):
        return {}
    kind = action.get("kind")
    label = action.get("label") or ""
    target = action.get("target") or ""
    props: dict = {"label": label}
    if kind == "workflow":
        props["workflow"] = target
        im = action.get("input_map")
        if isinstance(im, dict) and im:
            props["input_map"] = dict(im)
    elif kind == "navigate":
        props["navigate"] = target
    else:
        return {"label": label}
    for hint_key in ("variant", "requires_confirm", "icon", "confirmMessage"):
        if hint_key in action:
            props[hint_key] = action[hint_key]
    return props
