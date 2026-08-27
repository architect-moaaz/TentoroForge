"""Wire a form to a workflow — deterministic seam.

Slice C of the Feature-Authoring Roadmap (2026-07-20). Reads a page
schema + workflow definition, decides how to wire them together, and
returns the patches both artifacts need. The seam function `wire_form_
to_workflow` (Task 2) then applies these patches atomically.

This module is pure: no file I/O, no LLM, no plan.json reads. Callers
supply the dicts; the resolver returns what should change. Keeps unit
tests fast and the wiring logic auditable.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class ResolveResult(TypedDict):
    """Output of :func:`_resolve_wiring`. All keys always present so
    callers can trust the shape; ``error`` is None on success."""

    error:                 str | None
    field_map:             dict[str, str]        # form_field -> workflow_input
    input_sources:         dict[str, dict]       # workflow_input -> source spec
    form_props_patch:      dict[str, Any]        # merges into Form.props
    workflow_source_patch: dict[str, Any]        # goes to plan.workflows[wf].source


# --------------------------------------------------------------------------- #
# Public resolver
# --------------------------------------------------------------------------- #

def _resolve_wiring(
    page: dict,
    workflow: dict,
    *,
    field_map: dict[str, str] | None = None,
) -> ResolveResult:
    """Decide how ``workflow`` gets dispatched by the Form on ``page``.

    Args:
        page: A page schema dict — must have ``route`` and ``root``.
        workflow: A workflow definition dict — reads ``name`` and
            ``processVariables``.
        field_map: Optional explicit form-field → workflow-input mapping.
            When None, an identity map is derived from matching names.

    Returns:
        A :class:`ResolveResult`. On any failure, ``error`` is a
        colon-prefixed reason ("unresolved_input:candidateId",
        "trigger_not_found:no Form component", etc.) and the caller
        should NOT proceed with writes.
    """
    wf_name = str(workflow.get("name") or "").strip()
    page_route = str(page.get("route") or "").strip()

    # Locate the Form component + its child fields.
    _forms = find_forms(page.get("root"))
    if len(_forms) > 1:
        # Only the first form is wired by this seam (register WFW-3). Say so —
        # silently wiring one of several is what made the others look wired in
        # the editor while dispatching nothing at runtime.
        logger.warning(
            "wire_form_workflow: %s contains %d Form components; this seam wires "
            "only the FIRST. The other %d will not dispatch %s — wire them "
            "explicitly with a field_map.",
            page_route or "<page>", len(_forms), len(_forms) - 1, wf_name or "a workflow",
        )
    form_node = _forms[0] if _forms else None
    if form_node is None:
        return _empty_result(
            error=f"trigger_not_found:no Form component on {page_route!r}",
        )
    form_fields = _collect_form_fields(form_node)

    # Duplicate field names are ambiguous, not harmless (register WFW-4).
    #
    # Two controls with the same `props.name` mean the payload carries ONE of
    # them and the other is silently lost — which of the two is decided by DOM
    # order, not by intent. The identity field-map cannot tell them apart
    # either. Wiring still proceeds (refusing would be worse), but the
    # ambiguity is named instead of passing through unnoticed.
    _dupes = sorted({f for f in form_fields if form_fields.count(f) > 1})
    if _dupes:
        logger.warning(
            "wire_form_workflow: %s has %d duplicated form field name(s): %s. "
            "Only one control per name reaches the workflow; the others are "
            "dropped by the browser.",
            page_route or "<page>", len(_dupes), ", ".join(_dupes),
        )

    # Extract the workflow's input schema.
    inputs = _workflow_inputs(workflow)

    # Build field_map: explicit wins, otherwise identity for matching names.
    resolved_map: dict[str, str] = {}
    if field_map:
        # Explicit — validated below in _build_input_sources.
        resolved_map = dict(field_map)
    else:
        wf_input_names = {i["name"] for i in inputs}
        for f in form_fields:
            if f in wf_input_names:
                resolved_map[f] = f

    # For each workflow input, derive its source (form_field / route / auth).
    route_params = _route_params(page_route)
    input_sources, unresolved = _build_input_sources(
        inputs, resolved_map, form_fields, route_params,
    )
    if unresolved:
        return {
            "error": f"unresolved_input:{','.join(unresolved)}",
            "field_map": resolved_map,
            "input_sources": input_sources,
            "form_props_patch": {},
            "workflow_source_patch": {},
        }

    return {
        "error": None,
        "field_map": resolved_map,
        "input_sources": input_sources,
        "form_props_patch": {"workflow": wf_name},
        "workflow_source_patch": {"kind": "form", "page": page_route},
    }


# --------------------------------------------------------------------------- #
# Helpers — page walker
# --------------------------------------------------------------------------- #

def find_forms(node: Any) -> list[dict]:
    """EVERY Form component in a depth-first walk of ``node``.

    `_find_first_form` returns only the first one, so on a page with more than
    one form — a create form beside a filter form, or a tabbed page — only the
    first was ever wired and the others were left dispatching nothing, with no
    report (register WFW-3). Callers that must handle every form use this;
    `_find_first_form` remains for the single-form seam and is now defined in
    terms of it so the two cannot disagree about what a Form is.
    """
    out: list[dict] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c == "Form":
                out.append(n)
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return out


def _find_first_form(node: Any) -> dict | None:
    """First Form component in a depth-first walk of ``node``. Handles
    both ``component`` and ``type`` keys since real schemas use both."""
    if isinstance(node, dict):
        c = node.get("component") or node.get("type") or ""
        if c == "Form":
            return node
        for v in node.values():
            if isinstance(v, (dict, list)):
                found = _find_first_form(v)
                if found is not None:
                    return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_form(item)
            if found is not None:
                return found
    return None


_FIELD_COMPONENTS = frozenset({
    "Input", "Textarea", "Select", "Checkbox", "Switch", "RadioGroup",
    "DatePicker", "TimePicker", "FileUpload", "NumberInput", "Slider",
    "Combobox", "MaskedInput", "Rating", "InputOTP", "ColorPicker",
    "RichTextEditor", "KeyValueInput", "Cascader", "Transfer", "Tree",
})


def _collect_form_fields(form_node: dict) -> list[str]:
    """Every named field component under this Form node."""
    out: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c in _FIELD_COMPONENTS:
                name = (n.get("props") or {}).get("name")
                if isinstance(name, str) and name:
                    out.append(name)
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    for v in form_node.values():
        if isinstance(v, (dict, list)):
            walk(v)
    return out


# --------------------------------------------------------------------------- #
# Helpers — workflow input schema
# --------------------------------------------------------------------------- #

def _workflow_inputs(workflow: dict) -> list[dict]:
    """Return the workflow's declared inputs as
    ``[{name, type, required}, ...]``.

    Real runtime workflows carry inputs under ``processVariables``; some
    older shapes use ``inputs`` at the top level. Prefer processVariables
    when it's a non-empty list; fall back to ``inputs``. Empty/missing
    → ``[]`` (no inputs — dispatch takes no data)."""
    pv = workflow.get("processVariables")
    if isinstance(pv, list) and pv:
        return [i for i in pv if isinstance(i, dict) and i.get("name")]
    ins = workflow.get("inputs")
    if isinstance(ins, list) and ins:
        return [i for i in ins if isinstance(i, dict) and i.get("name")]
    return []


# --------------------------------------------------------------------------- #
# Helpers — route params
# --------------------------------------------------------------------------- #

# Next-style route params. Handles `[id]`, `:id` AND the catch-all forms
# `[...slug]` / `[[...slug]]` (register WFW-5) — the leading dots meant the
# name never matched, so a catch-all route reported ZERO params and every
# input that should have bound to one was declared unresolvable, blocking the
# whole wiring for that page.
_ROUTE_PARAM_RE = re.compile(
    r"\[{1,2}(?:\.\.\.)?([a-zA-Z_][a-zA-Z0-9_]*)\]{1,2}|:([a-zA-Z_][a-zA-Z0-9_]*)"
)


def _route_params(route: str) -> set[str]:
    """Every param name declared in a Next-style route. Handles both
    ``[id]`` and ``:id`` conventions since generated apps use both."""
    if not route:
        return set()
    return {m.group(1) or m.group(2) for m in _ROUTE_PARAM_RE.finditer(route)}


# --------------------------------------------------------------------------- #
# Helpers — input source derivation
# --------------------------------------------------------------------------- #

def _build_input_sources(
    inputs: list[dict],
    field_map: dict[str, str],
    form_fields: list[str],
    route_params: set[str],
) -> tuple[dict[str, dict], list[str]]:
    """For each workflow input, resolve a source; collect the required
    inputs we couldn't resolve.

    Precedence: explicit field_map → identity form-field → route param.
    Auth/static/computed sources are v2 — for v1 they must be authored
    into the workflow's ``inputs[].source`` upstream (plan_and_apply
    slice), not derived here."""
    form_fields_set = set(form_fields)
    reverse_map: dict[str, str] = {v: k for k, v in field_map.items()}

    sources: dict[str, dict] = {}
    unresolved: list[str] = []
    dropped_optional: list[str] = []
    for inp in inputs:
        name = inp.get("name")
        if not isinstance(name, str) or not name:
            continue
        required = bool(inp.get("required"))

        # Precedence 1 — an explicit field_map entry targets this input.
        if name in reverse_map:
            form_field = reverse_map[name]
            if form_field not in form_fields_set:
                # Explicit map points at a field the form doesn't have.
                unresolved.append(name)
                continue
            sources[name] = {"kind": "form_field", "field": form_field}
            continue

        # Precedence 2 — route param name matches the input name.
        if name in route_params:
            sources[name] = {"kind": "route", "param": name}
            continue

        # Precedence 3 — identity form-field match (already in field_map
        # when the caller didn't pass one; but rechecking covers the case
        # where an explicit field_map partially covers inputs).
        if name in form_fields_set:
            sources[name] = {"kind": "form_field", "field": name}
            continue

        # No source found.
        #
        # A required input is an error. An OPTIONAL one used to vanish in total
        # silence (register WFW-2), so a workflow input the form was supposed
        # to supply simply never arrived and nothing anywhere said why — the
        # field looked wired in the editor and was absent at runtime. Dropping
        # it is still right; doing so invisibly is not.
        if required:
            unresolved.append(name)
        else:
            dropped_optional.append(name)

    if dropped_optional:
        logger.warning(
            "wire_form_workflow: %d optional workflow input(s) had no source and "
            "were dropped: %s. The form will not send them.",
            len(dropped_optional), ", ".join(sorted(dropped_optional)),
        )
    return sources, unresolved


# --------------------------------------------------------------------------- #
# Result builder
# --------------------------------------------------------------------------- #

def _empty_result(*, error: str | None) -> ResolveResult:
    return {
        "error": error,
        "field_map": {},
        "input_sources": {},
        "form_props_patch": {},
        "workflow_source_patch": {},
    }


# --------------------------------------------------------------------------- #
# Public seam — atomic file I/O
# --------------------------------------------------------------------------- #

class WireResult(TypedDict):
    applied:      bool
    error:        str | None
    page_path:    str | None      # repo-relative
    wf_path:      str | None
    changes:      list[dict]      # per-file summary


def wire_form_to_workflow(
    output_dir: str,
    *,
    page_route: str,
    workflow_name: str,
    field_map: dict[str, str] | None = None,
    git: bool = True,
) -> WireResult:
    """Wire a form's submit to a workflow. Reads both artifacts, calls
    the resolver, patches both files atomically. Rollback on any failure.

    Args:
        output_dir: The generated app root.
        page_route: Route of the form-carrying page, e.g. ``/candidates/new``.
        workflow_name: Name of the workflow to dispatch, e.g.
            ``ParseCvWorkflow``.
        field_map: Optional explicit form-field → workflow-input map.
        git: Whether to commit + stash-restore. ``False`` in tests.

    Returns:
        A :class:`WireResult`. ``applied=True`` iff both files were
        written and (when ``git=True``) committed as one atomic op.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return _empty_wire_result(error=f"output_dir_missing:{output_dir}")

    # Locate the page schema file.
    page_rel = _find_page_schema_file(out, page_route)
    if page_rel is None:
        return _empty_wire_result(error=f"page_not_found:{page_route}")

    # Locate the workflow file (real files use lowercase name.json).
    wf_rel = _find_workflow_file(out, workflow_name)
    if wf_rel is None:
        return _empty_wire_result(error=f"workflow_not_found:{workflow_name}")

    # Read both.
    try:
        page = json.loads((out / page_rel).read_text(encoding="utf-8"))
        wf = json.loads((out / wf_rel).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _empty_wire_result(error=f"read_failed:{exc}")

    # Resolve — pure function, no side effects.
    r = _resolve_wiring(page, wf, field_map=field_map)
    if r["error"] is not None:
        return {
            "applied": False,
            "error": r["error"],
            "page_path": page_rel,
            "wf_path": wf_rel,
            "changes": [],
        }

    # Build patched artifacts.
    new_page = copy.deepcopy(page)
    _apply_form_props_patch(new_page, r["form_props_patch"])

    new_wf = copy.deepcopy(wf)
    _apply_workflow_patch(new_wf, r["workflow_source_patch"])

    page_content = json.dumps(new_page, indent=2) + "\n"
    wf_content = json.dumps(new_wf, indent=2) + "\n"

    # Atomic apply — rolls back both on any failure.
    from services.atomic_apply import BundleOp, apply_bundle
    result = apply_bundle(
        output_dir,
        [
            BundleOp(path=page_rel, content=page_content, kind="page-schema"),
            BundleOp(path=wf_rel,   content=wf_content,   kind="workflow"),
        ],
        commit_message=(
            f"wire: {workflow_name} ← {page_route}"
        ),
        git=git,
    )

    if not result.applied:
        return {
            "applied": False,
            "error": result.reason or "apply_bundle_failed",
            "page_path": page_rel,
            "wf_path": wf_rel,
            "changes": [],
        }

    changes: list[dict] = [
        {"path": page_rel, "kind": "form_props_patch",
         "patch": r["form_props_patch"]},
        {"path": wf_rel,   "kind": "workflow_source_patch",
         "patch": r["workflow_source_patch"]},
    ]

    # Mirror the wiring back to plan.json so the plan stays authoritative.
    # Soft-fail — page + workflow writes are the primary artifacts; the
    # plan mirror is best-effort. Callers see any warning in `changes`.
    mirror_change = _mirror_to_plan(
        out=out,
        page_route=page_route,
        workflow_name=workflow_name,
        field_map=r["field_map"],
        input_sources=r["input_sources"],
        workflow_source=r["workflow_source_patch"],
    )
    if mirror_change is not None:
        changes.append(mirror_change)

    return {
        "applied": True,
        "error": None,
        "page_path": page_rel,
        "wf_path": wf_rel,
        "changes": changes,
    }


# --------------------------------------------------------------------------- #
# Helpers — plan.json mirror
# --------------------------------------------------------------------------- #

def _mirror_to_plan(
    *,
    out: Path,
    page_route: str,
    workflow_name: str,
    field_map: dict[str, str],
    input_sources: dict[str, dict],
    workflow_source: dict,
) -> dict | None:
    """Update plan.json to reflect the wiring. Returns a change record
    (either a success mirror or a soft-fail warning). Never raises."""
    plan_path = out / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return {
            "path": "src/contracts/plan.json",
            "kind": "plan_mirror_warning",
            "patch": {"reason": "plan.json not found — mirror skipped"},
        }
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "path": "src/contracts/plan.json",
            "kind": "plan_mirror_warning",
            "patch": {"reason": f"plan.json unreadable: {exc}"},
        }

    if not isinstance(plan, dict):
        return {
            "path": "src/contracts/plan.json",
            "kind": "plan_mirror_warning",
            "patch": {"reason": "plan.json is not a dict — mirror skipped"},
        }

    # (1) page.submit
    pages = plan.get("pages")
    page_updated = False
    if isinstance(pages, list):
        for pg in pages:
            if isinstance(pg, dict) and pg.get("route") == page_route:
                pg["submit"] = {
                    "kind":      "workflow",
                    "target":    workflow_name,
                    "field_map": dict(field_map),
                }
                page_updated = True
                break

    # (2) workflow.source + (3) workflow.inputs[].source
    workflows = plan.get("workflows")
    wf_updated = False
    if isinstance(workflows, list):
        for wf in workflows:
            if not isinstance(wf, dict):
                continue
            if wf.get("name") != workflow_name:
                continue
            wf["source"] = dict(workflow_source)
            # Merge input sources — preserve existing input entries;
            # attach .source per input the resolver mapped.
            existing_inputs = wf.get("inputs")
            if not isinstance(existing_inputs, list):
                existing_inputs = []
            # Merge by name — preserve order; append inputs the plan
            # didn't have but the resolver mapped.
            by_name = {i.get("name"): i for i in existing_inputs
                       if isinstance(i, dict) and i.get("name")}
            for inp_name, src in input_sources.items():
                if inp_name in by_name:
                    by_name[inp_name]["source"] = dict(src)
                else:
                    entry = {"name": inp_name, "source": dict(src)}
                    existing_inputs.append(entry)
                    by_name[inp_name] = entry
            wf["inputs"] = existing_inputs
            wf_updated = True
            break

    try:
        plan_path.write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "path": "src/contracts/plan.json",
            "kind": "plan_mirror_warning",
            "patch": {"reason": f"plan.json write failed: {exc}"},
        }

    return {
        "path": "src/contracts/plan.json",
        "kind": "plan_mirror",
        "patch": {
            "page_updated": page_updated,
            "workflow_updated": wf_updated,
        },
    }


def _empty_wire_result(*, error: str) -> WireResult:
    return {
        "applied": False,
        "error": error,
        "page_path": None,
        "wf_path": None,
        "changes": [],
    }


# --------------------------------------------------------------------------- #
# Helpers — locate files on disk
# --------------------------------------------------------------------------- #

def _find_page_schema_file(out: Path, route: str) -> str | None:
    """Map a route to its schema file relative path. Tries nested layout
    first (``/candidates/new`` → ``src/schemas/candidates/new.json``),
    falls back to flat (``/apply`` → ``src/schemas/apply.json``)."""
    schemas_dir = out / "src" / "schemas"
    if not schemas_dir.exists() or not route or route == "/":
        return None
    parts = [p for p in route.strip("/").split("/") if p]
    if not parts:
        return None
    # Nested — /candidates/new → candidates/new.json
    nested = schemas_dir / "/".join(parts[:-1]) / f"{parts[-1]}.json"
    if nested.is_file():
        return str(nested.relative_to(out))
    # Flat — /apply → apply.json
    flat = schemas_dir / f"{'/'.join(parts)}.json"
    if flat.is_file():
        return str(flat.relative_to(out))
    # Dynamic segment normalize — [id] → :id — the schemas dir may name
    # either; try both. Real gen usually uses ``[id]`` inside the file
    # tree, but ``:id`` in the route strings. Callers may pass either.
    normalized = [re.sub(r"^:", "", p).lstrip("[").rstrip("]") for p in parts]
    alt = schemas_dir / "/".join(normalized[:-1]) / f"{normalized[-1]}.json"
    if alt.is_file():
        return str(alt.relative_to(out))
    return None


def _find_workflow_file(out: Path, workflow_name: str) -> str | None:
    """Map a workflow name to its file relative path. Real gen writes
    lowercase (``parsecvworkflow.json``) OR the original name camel-cased
    (``CreateCandidateProfile.json``) — try both."""
    wf_dir = out / "workflows"
    if not wf_dir.exists() or not workflow_name:
        return None
    for candidate in (workflow_name, workflow_name.lower()):
        p = wf_dir / f"{candidate}.json"
        if p.is_file():
            return str(p.relative_to(out))
    return None


# --------------------------------------------------------------------------- #
# Helpers — apply patches to loaded artifacts
# --------------------------------------------------------------------------- #

def _apply_form_props_patch(page: dict, patch: dict) -> None:
    """Merge ``patch`` into the first Form component's props."""
    form_node = _find_first_form(page.get("root"))
    if form_node is None:
        return
    props = form_node.setdefault("props", {})
    if not isinstance(props, dict):
        return
    props.update(patch)


def _apply_workflow_patch(workflow: dict, source_patch: dict) -> None:
    """Update the workflow's trigger + record its source under a
    top-level ``source`` key (SUBMIT-AUTHORITY contract).

    - definition.trigger.type ← "form"
    - source ← source_patch verbatim (Slice A's contract shape)
    """
    if not source_patch:
        return
    defn = workflow.setdefault("definition", {})
    if isinstance(defn, dict):
        trigger = defn.setdefault("trigger", {})
        if isinstance(trigger, dict):
            trigger["type"] = source_patch.get("kind", "form")
    workflow["source"] = dict(source_patch)
