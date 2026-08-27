"""SUBMIT-AUTHORITY contract — pure helpers.

Slice A of the Feature-Authoring Roadmap. Every form-typed page in a
plan declares ``page.submit`` naming the dispatch target (workflow OR
data engine). Every workflow declares ``workflow.source`` naming the
UI element that dispatches it. Every workflow input declares
``inputs[].source`` naming where its value comes from at dispatch
time (form field / route param / auth claim / static / computed).

This module provides the pure readers + validators. Downstream code
consumes them:

* :func:`resolve_page_submit`             — form scaffolder + deterministic
                                             page builder read the declared
                                             submit target.
* :func:`resolve_workflow_source`         — post-generate guard confirms
                                             every workflow has a UI source.
* :func:`derive_form_fields_from_workflow`
                                          — form scaffolder builds the form
                                            's field list from the workflow's
                                            declared ``form_field`` inputs
                                            (not the entity's columns).
* :func:`validate_input_sources`          — plan validator rejects any
                                             plan where a required input
                                             has no resolvable source.

No I/O, no LLM, no dependency on the plan schema evolving — just the
contract keys + defaults. Callers pass the plan dict; the helpers stay
happily oblivious to how it was loaded.
"""
from __future__ import annotations

import re
from typing import Any


# --------------------------------------------------------------------------- #
# page.submit
# --------------------------------------------------------------------------- #

def resolve_page_submit(plan: Any, page_name: str) -> dict | None:
    """Return ``{kind, target, field_map}`` for the page's declared
    submit, or ``None`` when not declared.

    ``kind`` defaults to ``"data_api"`` if the plan omits it — an older
    plan lacking submit-authority declarations should behave like the
    pre-contract world (post to /api/data/<entity>) rather than crash.

    ``field_map`` normalises to ``{}`` when omitted; downstream callers
    treat empty-map as "identity map from matching field/input names".
    """
    if not isinstance(plan, dict) or not page_name:
        return None
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return None
    for p in pages:
        if not isinstance(p, dict) or p.get("name") != page_name:
            continue
        submit = p.get("submit")
        if not isinstance(submit, dict) or not submit.get("target"):
            return None
        out = {
            "kind":      str(submit.get("kind") or "data_api").strip(),
            "target":    str(submit["target"]).strip(),
            "field_map": dict(submit.get("field_map") or {}),
        }
        # T6: workflow_resume carries a `task_id` source spec that the
        # form-completion path needs to read the taskId from. Default
        # to {kind:'route', param:'id'} — matches /tasks/[id] convention.
        if out["kind"] == "workflow_resume":
            ti = submit.get("task_id")
            if isinstance(ti, dict) and ti.get("kind"):
                out["task_id"] = {
                    "kind":  str(ti["kind"]).strip(),
                    **({"param": ti["param"]} if "param" in ti else {}),
                    **({"field": ti["field"]} if "field" in ti else {}),
                }
            else:
                out["task_id"] = {"kind": "route", "param": "id"}
        return out
    return None


# --------------------------------------------------------------------------- #
# workflow.source
# --------------------------------------------------------------------------- #

def resolve_workflow_source(plan: Any, workflow_name: str) -> dict | None:
    """Return the workflow's declared ``source`` verbatim, or ``None``
    when not declared. Case-sensitive on the name — plan.workflows[].name
    is the canonical form; callers pass it as-is."""
    if not isinstance(plan, dict) or not workflow_name:
        return None
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return None
    for wf in workflows:
        if not isinstance(wf, dict) or wf.get("name") != workflow_name:
            continue
        source = wf.get("source")
        if not isinstance(source, dict) or not source.get("kind"):
            return None
        return dict(source)
    return None


# --------------------------------------------------------------------------- #
# derive_form_fields_from_workflow
# --------------------------------------------------------------------------- #

def derive_form_fields_from_workflow(plan: Any, workflow_name: str) -> list[dict]:
    """Return the form's field list derived from the workflow's declared
    ``form_field``-sourced inputs.

    Each returned field dict carries::

        {
          "name":            <what the form control's name should be>,
          "type":            <input.type, e.g. "uuid", "integer", "text">,
          "required":        <input.required, default False>,
          "workflow_input":  <the workflow's input name>,
        }

    ``name`` comes from ``source.field`` (the form-control name), so a
    workflow that reads a form field with a different name (e.g. workflow
    input ``cvUrl`` sourced from form field ``resume``) picks the form
    name — matches what the runtime dispatcher will look up. The
    workflow input name is preserved as ``workflow_input`` so the
    scaffolder can annotate the form.
    """
    if not isinstance(plan, dict) or not workflow_name:
        return []
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return []
    for wf in workflows:
        if not isinstance(wf, dict) or wf.get("name") != workflow_name:
            continue
        inputs = wf.get("inputs") or []
        if not isinstance(inputs, list):
            return []
        fields: list[dict] = []
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            source = inp.get("source")
            if not isinstance(source, dict) or source.get("kind") != "form_field":
                continue
            field_name = source.get("field") or inp.get("name")
            if not isinstance(field_name, str) or not field_name:
                continue
            fields.append({
                "name":           field_name,
                "type":           inp.get("type") or "text",
                "required":       bool(inp.get("required")),
                "workflow_input": inp.get("name"),
            })
        return fields
    return []


# --------------------------------------------------------------------------- #
# validate_input_sources
# --------------------------------------------------------------------------- #

_KNOWN_SOURCE_KINDS = frozenset({
    "form_field", "route", "auth", "static", "computed",
})

_ROUTE_PARAM_RE = re.compile(
    r"\[([a-zA-Z_][a-zA-Z0-9_]*)\]|:([a-zA-Z_][a-zA-Z0-9_]*)"
)


def validate_input_sources(
    workflow: dict, page: dict, *, route: str,
) -> list[dict]:
    """Return a list of source-declaration errors for ``workflow``.

    Each error::

        {"kind": "<error kind>", "input": "<input name>", "detail": "..."}

    Error kinds:
      - ``missing_source`` — required input has no ``source`` key
      - ``unknown_source_kind`` — ``source.kind`` isn't one of the five
        allowed variants
      - ``route_param_missing`` — ``source.kind=route`` names a param
        the page's ``route`` doesn't declare
      - ``form_field_missing`` — ``source.kind=form_field`` names a
        field the target page doesn't have (checked upstream where
        the form fields are indexed; NOT checked here)
    """
    if not isinstance(workflow, dict):
        return []
    inputs = workflow.get("inputs") or []
    if not isinstance(inputs, list):
        return []

    route_params = {
        m.group(1) or m.group(2)
        for m in _ROUTE_PARAM_RE.finditer(route or "")
    }
    errors: list[dict] = []
    for inp in inputs:
        if not isinstance(inp, dict):
            continue
        name = inp.get("name")
        if not isinstance(name, str) or not name:
            continue
        required = bool(inp.get("required"))
        source = inp.get("source")

        if not isinstance(source, dict) or not source.get("kind"):
            if required:
                errors.append({
                    "kind":   "missing_source",
                    "input":  name,
                    "detail": "required input has no `source` declaration",
                })
            continue

        kind = source.get("kind")
        if kind not in _KNOWN_SOURCE_KINDS:
            errors.append({
                "kind":   "unknown_source_kind",
                "input":  name,
                "detail": f"source.kind={kind!r} — must be one of "
                          f"{sorted(_KNOWN_SOURCE_KINDS)}",
            })
            continue

        if kind == "route":
            param = source.get("param")
            if not isinstance(param, str) or param not in route_params:
                errors.append({
                    "kind":   "route_param_missing",
                    "input":  name,
                    "detail": f"source.param={param!r} not declared by "
                              f"route {route!r}",
                })

    return errors
