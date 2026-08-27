"""Post-generate guards for the SUBMIT-AUTHORITY contract.

Slice A T7 + T8. Runs LAST in ``apply_post_generate_fixes`` — after
orphan_wiring_pass has had a chance to auto-wire what it can. Every
residual gap is a genuine violation of the contract; v1 logs warnings,
v2 will flip to a hard error that fails the pipeline.

Two symmetric guards:

* :func:`workflow_completeness_guard` — every workflow file must be the
  target of at least one page's Form.props.workflow (i.e. no orphans).
* :func:`form_target_guard` — every form-typed page must have Form.props.
  workflow set OR a plan-declared page.submit=data_api target.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class GuardResult(TypedDict):
    ok: bool
    violations: list[dict]      # [{artifact, path, reason}]


# --------------------------------------------------------------------------- #
# workflow_completeness_guard
# --------------------------------------------------------------------------- #

def workflow_completeness_guard(output_dir: str) -> GuardResult:
    """Every ``workflows/*.json`` must be the target of at least one
    page's ``Form.props.workflow`` — otherwise it's an orphan that
    can never fire from the UI."""
    out = Path(output_dir)
    wf_dir = out / "workflows"
    schemas_dir = out / "src" / "schemas"
    if not wf_dir.is_dir():
        return {"ok": True, "violations": []}

    wired_names: set[str] = set()
    if schemas_dir.is_dir():
        for sp in schemas_dir.rglob("*.json"):
            try:
                doc = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for wf_name in _collect_form_workflow_props(doc):
                wired_names.add(wf_name)
                wired_names.add(wf_name.lower())

    violations: list[dict] = []
    for wf_path in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = wf.get("name") or wf_path.stem
        if not isinstance(name, str):
            continue
        if name in wired_names or name.lower() in wired_names:
            continue
        violations.append({
            "artifact": "workflow",
            "path":     f"workflows/{wf_path.name}",
            "name":     name,
            "reason":   "orphan_workflow — no page's Form.props.workflow "
                        "targets this workflow",
        })

    if violations:
        logger.warning(
            "[submit-authority] workflow_completeness_guard: %d orphan "
            "workflow(s): %s",
            len(violations),
            ", ".join(v["name"] for v in violations),
        )
    return {"ok": not violations, "violations": violations}


# --------------------------------------------------------------------------- #
# form_target_guard
# --------------------------------------------------------------------------- #

def form_target_guard(output_dir: str) -> GuardResult:
    """Every form-typed page schema must have ``Form.props.workflow``
    (dispatches a workflow) OR live under a route with a plan-declared
    ``page.submit.kind=data_api`` target (posts to /api/data). Absent
    both, form submission goes nowhere at runtime."""
    out = Path(output_dir)
    schemas_dir = out / "src" / "schemas"
    if not schemas_dir.is_dir():
        return {"ok": True, "violations": []}

    plan = _load_plan(out)
    plan_pages_by_route = _plan_pages_by_route(plan)

    # Phase 6b (Record Authority) — the record composer decides whether
    # a form page dispatches to a workflow or to /api/data. If it wrote
    # the schema, its choice is the authority and this guard shouldn't
    # raise a violation on top of it.
    from services.artifact_authority import should_assert_only_any

    violations: list[dict] = []
    for sp in sorted(schemas_dir.rglob("*.json")):
        if sp.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if should_assert_only_any(doc):
            continue  # composer-authored — trust its submit-target decision
        form = _find_first_form(doc.get("root"))
        if form is None:
            continue  # not a form page — nothing to guard
        props = form.get("props") or {}
        if isinstance(props.get("workflow"), str) and props["workflow"]:
            continue  # dispatches a workflow — fine
        # No Form.props.workflow. Check the plan's declared submit.
        route = doc.get("route") or ""
        plan_page = plan_pages_by_route.get(route)
        if plan_page:
            submit = plan_page.get("submit")
            if isinstance(submit, dict) and submit.get("target"):
                continue  # plan declares a submit target — fine
        violations.append({
            "artifact": "page",
            "path":     f"src/schemas/{sp.relative_to(schemas_dir)}",
            "route":    route,
            "reason":   "form_without_target — Form has no props.workflow "
                        "and plan declares no submit.target for this page",
        })

    if violations:
        logger.warning(
            "[submit-authority] form_target_guard: %d form(s) without a "
            "submit target: %s",
            len(violations),
            ", ".join(v["route"] or v["path"] for v in violations),
        )
    return {"ok": not violations, "violations": violations}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _collect_form_workflow_props(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        c = node.get("component") or node.get("type") or ""
        if c == "Form":
            wf = (node.get("props") or {}).get("workflow")
            if isinstance(wf, str) and wf.strip():
                out.append(wf.strip())
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.extend(_collect_form_workflow_props(v))
    elif isinstance(node, list):
        for i in node:
            out.extend(_collect_form_workflow_props(i))
    return out


def _find_first_form(node: Any) -> dict | None:
    if isinstance(node, dict):
        c = node.get("component") or node.get("type") or ""
        if c == "Form":
            return node
        for v in node.values():
            if isinstance(v, (dict, list)):
                r = _find_first_form(v)
                if r is not None:
                    return r
    elif isinstance(node, list):
        for i in node:
            r = _find_first_form(i)
            if r is not None:
                return r
    return None


def _load_plan(out: Path) -> dict:
    plan_path = out / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return {}
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _plan_pages_by_route(plan: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in (plan.get("pages") or []):
        if isinstance(p, dict) and isinstance(p.get("route"), str):
            out[p["route"]] = p
    return out
