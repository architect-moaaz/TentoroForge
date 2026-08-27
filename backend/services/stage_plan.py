"""IRF-M5-T4 — Stage.plan(context) → StagePlan protocol.

Spec P2: every generation stage exposes a ``plan(context)`` method that
returns a ``StagePlan`` — the stage's *intent statement* before it runs.
Deterministic where possible (files_to_touch/read derived from
``plan.pages`` / ``plan.data_models`` / ``plan.workflows``); LLM-authored
otherwise (a stage that composes its own plan can return one via the
same interface).

The protocol is intentionally read-only + free-function friendly. A
stage doesn't need to be a class — ``plan_for_planner``,
``plan_for_page_schema_agent``, ``plan_for_workflow_author`` are the
three the spec's "first three stages migrated" line requires.

Callers use StagePlan to:
1. Preview what the stage will do (surface as an SSE event / a
   log line) before it runs.
2. Record an ``EditRecord`` after the stage runs, without the caller
   having to reconstruct the file list.
3. Feed the recover_ladder: if the stage's LLM output doesn't touch
   files declared in ``files_to_touch``, that's a divergence finding.

None of the three stage authors mutate the plan — they only READ it and
return a description. Safe to call from any thread; deterministic same
input → same output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# ══════════════════════════════════════════════════════════════════
# The StagePlan value type
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StagePlan:
    """Every generation stage's declared intent, before it runs.

    - ``stage_name``: canonical identifier ("planner",
      "page_schema_agent", "workflow_author").
    - ``intent``: one-line human-readable description of what the
      stage will do this call.
    - ``files_to_touch``: relative paths under ``output_dir`` the
      stage will WRITE. Empty when the stage hasn't localised its
      output yet (planner writes plan.json).
    - ``files_to_read``: relative paths the stage will READ as input
      context. Includes source-of-truth files (plan.json, registry.json,
      brief.json).
    - ``expected_bindings``: dataSource / entity names the stage's
      output should reference. Downstream binding validators use this
      as a completeness check.
    - ``expected_workflows``: workflow names the stage's output
      should trigger or wire. Same idea, workflow-scoped.
    """
    stage_name: str
    intent: str
    files_to_touch: tuple[str, ...] = ()
    files_to_read: tuple[str, ...] = ()
    expected_bindings: tuple[str, ...] = ()
    expected_workflows: tuple[str, ...] = ()


class Stage(Protocol):
    """The protocol the spec calls for. Any callable that satisfies
    ``plan(ctx) -> StagePlan`` qualifies — stages don't need to inherit
    from anything."""

    def plan(self, ctx: Any) -> StagePlan: ...  # pragma: no cover — protocol


# ══════════════════════════════════════════════════════════════════
# Concrete authors — the three "first three" from the spec
# ══════════════════════════════════════════════════════════════════


def plan_for_planner(ctx: Any) -> StagePlan:
    """Planner stage — produces ``src/contracts/plan.json`` from the
    user brief. Reads discovery outputs when present."""
    plan = _ctx_plan(ctx)
    entity_count = len(plan.get("data_models") or plan.get("entities") or [])
    return StagePlan(
        stage_name="planner",
        intent=(
            f"Author plan.json (industry={plan.get('industry') or '?'}, "
            f"~{entity_count} entities)"
            if entity_count else
            "Author plan.json from the user brief"
        ),
        files_to_touch=("src/contracts/plan.json",),
        files_to_read=(
            "src/contracts/brief.json",
            "src/contracts/design-brief.json",
        ),
    )


def plan_for_page_schema_agent(ctx: Any) -> StagePlan:
    """Page schema agent — one call per page in ``plan.pages``.
    ``files_to_touch`` enumerates the target JSON files it will
    write, one per page.

    Note: this describes the OVERALL stage, not one page-call. Callers
    that need per-call granularity build a smaller StagePlan on the fly
    with the single route's path."""
    plan = _ctx_plan(ctx)
    pages = plan.get("pages") or []
    slugs = tuple(f"src/schemas/{_slug_for(p)}.json" for p in pages if isinstance(p, dict))
    bindings = tuple(sorted({
        s for p in pages if isinstance(p, dict)
        for s in _iter_bindings(p)
    }))
    workflows = tuple(sorted({
        w for p in pages if isinstance(p, dict)
        for w in _iter_workflow_refs(p)
    }))
    return StagePlan(
        stage_name="page_schema_agent",
        intent=f"Emit {len(pages)} page schema(s)",
        files_to_touch=slugs,
        files_to_read=(
            "src/contracts/plan.json",
            "src/contracts/design-spec.json",
            "src/contracts/registry.json",
        ),
        expected_bindings=bindings,
        expected_workflows=workflows,
    )


def plan_for_workflow_author(ctx: Any) -> StagePlan:
    """Workflow author — one workflow JSON per entry in
    ``plan.workflows``."""
    plan = _ctx_plan(ctx)
    workflows = plan.get("workflows") or []
    names = tuple(str(w.get("name", "")) for w in workflows if isinstance(w, dict) and w.get("name"))
    files = tuple(f"src/workflows/{_slug(n)}.json" for n in names)
    return StagePlan(
        stage_name="workflow_author",
        intent=f"Author {len(names)} workflow definition(s)",
        files_to_touch=files,
        files_to_read=(
            "src/contracts/plan.json",
            "src/contracts/registry.json",
        ),
        expected_workflows=names,
    )


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════


def _ctx_plan(ctx: Any) -> dict:
    """Extract the plan dict from a SessionContext or fall through to
    an empty dict. Duck-typed so callers can pass a plan dict directly."""
    if isinstance(ctx, dict):
        return ctx
    plan = getattr(ctx, "plan", None)
    return plan if isinstance(plan, dict) else {}


def _slug(name: str) -> str:
    """kebab-case slug for filenames; mirrors what the writers do."""
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(name or "")).strip("-").lower()
    return s or "unnamed"


def _slug_for(page: dict) -> str:
    """A page schema's file slug — id > route-tail > name."""
    if isinstance(page.get("id"), str) and page["id"].strip():
        return _slug(page["id"])
    route = page.get("route")
    if isinstance(route, str) and route.strip():
        tail = [seg for seg in route.split("/") if seg]
        if tail:
            return _slug(tail[-1])
    if isinstance(page.get("name"), str):
        return _slug(page["name"])
    return "page"


def _iter_bindings(page: dict):
    """Yield dataSource / entity slugs the page declares. Deep walk
    over ``dataSources`` + node ``bind`` / ``dataSource`` props."""
    for src in page.get("dataSources") or []:
        if isinstance(src, dict) and isinstance(src.get("name"), str):
            yield src["name"]
    for node in _iter_nodes(page.get("root")):
        if not isinstance(node, dict):
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        for key in ("dataSource", "bind"):
            val = props.get(key)
            if isinstance(val, str) and val.strip():
                yield val.strip().rstrip("[]").split(".")[0].strip("{{}}")


def _iter_workflow_refs(page: dict):
    """Yield workflow names referenced by Form / Button props."""
    for node in _iter_nodes(page.get("root")):
        if not isinstance(node, dict):
            continue
        t = node.get("type")
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        if t == "Form":
            wf = props.get("workflow")
            if isinstance(wf, str) and wf.strip():
                yield wf.strip()
        if t == "Button":
            action = props.get("action")
            if isinstance(action, dict):
                wf = action.get("workflow")
                if isinstance(wf, str) and wf.strip():
                    yield wf.strip()


def _iter_nodes(node: Any):
    """DFS every dict node in a schema tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


__all__ = [
    "StagePlan",
    "Stage",
    "plan_for_planner",
    "plan_for_page_schema_agent",
    "plan_for_workflow_author",
]
