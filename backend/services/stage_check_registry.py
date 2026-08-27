"""IRF-M5-T5 wire-up — verify_stack check registry for page schemas.

``services.verify_stack.run_stack`` accepts a ``check_registry`` mapping
check names → callables. This module ships the concrete callables for
the 3 cheap checks that make sense on a rendered page schema:

- ``static`` — schema JSON well-formedness (returns a dict with type +
  root); catches "the LLM emitted a non-object".
- ``structural`` — required-field / required-tree presence (the shape
  the renderer expects: ``schemaVersion``, ``id``, ``root``).
- ``domain_conformance`` — the existing shape-conformance check
  (delegates to ``services.domain_conformance.check_page``).

Expensive checks (``design_conformance``, ``runtime``) are NOT in this
registry — they need LLM calls or a dev-server boot, both of which are
opt-in and belong in per-stage wire-ups, not the default page-schema
stack.

Callers do:

    from services.stage_check_registry import PAGE_SCHEMA_REGISTRY
    from services.verify_stack import run_stack

    report = run_stack(
        stage="page_schema_agent",
        output={"plan": plan, "route": route, "schema": schema_dict},
        context=session_context,
        checks=("static", "structural", "domain_conformance"),
        check_registry=PAGE_SCHEMA_REGISTRY,
    )
"""
from __future__ import annotations

from typing import Any

from services.domain_conformance import check_page
from services.shape_profile import Finding


# ── check implementations ───────────────────────────────────────────


def _check_static(output: dict[str, Any], context: Any) -> dict[str, Any]:
    """Well-formedness — did the stage return a dict-shaped schema at all?"""
    schema = output.get("schema") if isinstance(output, dict) else None
    findings: list[dict[str, Any]] = []
    if not isinstance(schema, dict):
        findings.append({
            "rule": "static.schema_not_dict",
            "message": f"page schema must be a dict, got {type(schema).__name__}",
            "severity": "error",
        })
    return {"findings": findings}


_REQUIRED_KEYS = ("schemaVersion", "id", "root")


def _check_structural(output: dict[str, Any], context: Any) -> dict[str, Any]:
    """Required-key presence — a schema without ``root`` won't render."""
    schema = output.get("schema") if isinstance(output, dict) else None
    findings: list[dict[str, Any]] = []
    if not isinstance(schema, dict):
        return {"findings": []}  # static check already fired
    for key in _REQUIRED_KEYS:
        if key not in schema:
            findings.append({
                "rule": f"structural.missing_{key}",
                "message": f"page schema missing required key {key!r}",
                "severity": "error",
                "key": key,
            })
    root = schema.get("root")
    if root is not None and not isinstance(root, dict):
        findings.append({
            "rule": "structural.root_not_dict",
            "message": f"page schema `root` must be a dict, got {type(root).__name__}",
            "severity": "error",
        })
    return {"findings": findings}


def _check_domain_conformance(output: dict[str, Any], context: Any) -> dict[str, Any]:
    """Delegate to services.domain_conformance."""
    plan = output.get("plan") if isinstance(output, dict) else None
    route = output.get("route") if isinstance(output, dict) else None
    schema = output.get("schema") if isinstance(output, dict) else None
    if not isinstance(plan, dict) or not isinstance(route, str) or not isinstance(schema, dict):
        return {"findings": []}
    findings_raw = check_page(plan, route, schema)
    findings: list[dict[str, Any]] = []
    for f in findings_raw:
        if isinstance(f, Finding):
            findings.append({
                "rule": f.rule,
                "message": f.message,
                "severity": f.severity,
                "axis": f.axis,
            })
        elif isinstance(f, dict):
            findings.append(f)
    return {"findings": findings}


# ── the default registry ────────────────────────────────────────────


PAGE_SCHEMA_REGISTRY = {
    "static": _check_static,
    "structural": _check_structural,
    "domain_conformance": _check_domain_conformance,
}


__all__ = ["PAGE_SCHEMA_REGISTRY"]
