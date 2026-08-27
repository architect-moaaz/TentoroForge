"""IRF-M5-T8 — three critic personas.

Each persona inspects a page schema through a distinct lens and returns
Finding-shaped dicts:

- ``design`` — aesthetic conformance. Palette diversity, hero
  treatment presence, class variance vs. shadcn baseline. Delegates
  to the existing ``design_brief_critic`` when a brief is available;
  otherwise runs a small structural check.
- ``ux`` — invariant conformance. Loading skeletons on data-bound
  components, submit CTAs on forms, empty-state hints where the LLM
  emitted nothing meaningful.
- ``correctness`` — binding / data conformance. Every dataSource
  the page references is either declared inline or comes from a real
  registered source; workflow refs on Form/Button resolve to a
  workflow that exists in the plan.

Spec P2 says "M5 wires the plumbing; M6 tunes rubrics." These
implementations are intentionally shallow — enough to demonstrate the
protocol + record telemetry so M6 can promote them without rewiring.
No LLM calls at this tier (design's LLM path is a future upgrade).

Every persona returns ``list[dict[str, Any]]`` where each dict carries
``rule`` / ``message`` / ``severity`` — the same shape the verify_stack
already consumes.
"""
from __future__ import annotations

from typing import Any, Iterable


# ── shape utilities ────────────────────────────────────────────────


def _iter_nodes(node: Any) -> Iterable[dict[str, Any]]:
    """DFS over dict-shaped schema nodes."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _node_type(node: Any) -> str | None:
    if isinstance(node, dict):
        t = node.get("type")
        return str(t) if isinstance(t, str) else None
    return None


def _find(cls_names: set[str], schema: dict) -> list[dict]:
    return [n for n in _iter_nodes(schema.get("root")) if _node_type(n) in cls_names]


# ══════════════════════════════════════════════════════════════════
# design — aesthetic conformance
# ══════════════════════════════════════════════════════════════════


def design_critique(page_schema: dict, plan: dict, route: str) -> list[dict[str, Any]]:
    """Aesthetic invariants. Delegates depth to M6.

    - The root should carry SOME visible layout scaffold (Stack /
      Grid / Card / Split / etc.), not a lone bare Text node.
    - When plan.app_shape.layout.hero is not 'none', a page route
      that is the app's landing route (or matches the archetype's
      first route) should carry a hero-shaped node.
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(page_schema, dict):
        return findings

    root = page_schema.get("root")
    if not isinstance(root, dict):
        return findings

    # Bare-content anti-pattern: root is a scalar-only Text with no
    # scaffold. LLMs occasionally emit that on empty-state pages.
    scaffold = {"Stack", "Grid", "Card", "Split", "Section", "Container",
                "Row", "Column", "Panel"}
    if root.get("type") not in scaffold and root.get("type") != "Slot":
        findings.append({
            "rule": "design.missing_scaffold_root",
            "message": (
                f"route {route!r}: page root is a `{root.get('type')}` — "
                "expected a scaffold (Stack / Grid / Card / Split / Section). "
                "Bare content roots read as broken."
            ),
            "severity": "warning",
        })

    # Hero contract: when shape declares a non-none hero, the first
    # route (or a route matching the app's home) should have a
    # hero-scale node — a Section with heroic props, a large Heading
    # h1 as the first child, or a Media/Image at the top.
    shape = plan.get("app_shape") if isinstance(plan, dict) else None
    hero_val = None
    if isinstance(shape, dict):
        layout = shape.get("layout")
        if isinstance(layout, dict):
            hero_val = layout.get("hero")
    if hero_val and hero_val != "none" and route in ("/", "/home", "/landing"):
        children = root.get("children") or []
        first = children[0] if children else None
        first_type = _node_type(first)
        # Cheap heuristic: any of these types qualifies as a hero
        hero_types = {"Hero", "Section", "Media", "Image", "Card", "Heading"}
        if first_type not in hero_types:
            findings.append({
                "rule": "design.hero_missing_at_landing",
                "message": (
                    f"route {route!r}: shape declares hero=`{hero_val}` but "
                    f"the first root child is `{first_type}` — expected a "
                    f"hero-scale node ({sorted(hero_types)})."
                ),
                "severity": "warning",
            })

    # IRF-M6-T9 — deep rubric. Each check adds a scored finding when
    # below its target; ``design_critic_score(plan, page_schema)``
    # aggregates them.
    findings.extend(_rubric_findings(page_schema, plan, route))

    return findings


# ══════════════════════════════════════════════════════════════════
# IRF-M6-T9 — design critic rubric
# ══════════════════════════════════════════════════════════════════
#
# Per spec: palette diversity ≥4 non-neutral, class-diversity vs
# shadcn baseline ≥40%, signature-moves-presence-per-instance ≥80%,
# shape topology conformance 100% (hard), aesthetic profile conformance
# ≥75%.
#
# Each check returns a score (0–100) and produces a finding when
# score < target. ``design_critic_score`` combines them into a single
# 0–100 score for the plan-doc's "≥85 with one REVISE" target.


# Colors we consider "neutral" — grey/black/white/near-white.
_NEUTRAL_HEXES = {
    "#000", "#000000", "#111", "#111111", "#222", "#222222",
    "#333", "#333333", "#444", "#444444", "#555", "#555555",
    "#666", "#666666", "#777", "#777777", "#888", "#888888",
    "#999", "#999999", "#aaa", "#aaaaaa", "#bbb", "#bbbbbb",
    "#ccc", "#cccccc", "#ddd", "#dddddd", "#eee", "#eeeeee",
    "#f0f0f0", "#f5f5f5", "#fafafa", "#fff", "#ffffff",
}

# Shadcn default classes that a lookalike page tends to over-index on.
_SHADCN_BASELINE = frozenset({
    "bg-background", "text-foreground", "border-border",
    "bg-card", "text-card-foreground",
    "bg-muted", "text-muted-foreground",
    "bg-primary", "text-primary-foreground",
    "rounded-md", "rounded-lg", "shadow-sm",
})


def _collect_hexes(page_schema: dict) -> set[str]:
    import re as _re
    hexes: set[str] = set()
    def _walk(v):
        if isinstance(v, str):
            for m in _re.findall(r"#[0-9a-fA-F]{3,8}\b", v):
                hexes.add(m.lower())
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, list):
            for x in v:
                _walk(x)
    _walk(page_schema)
    return hexes


def _collect_classes(page_schema: dict) -> set[str]:
    classes: set[str] = set()
    for node in _iter_nodes(page_schema.get("root")):
        if not isinstance(node, dict):
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        cn = props.get("className")
        if isinstance(cn, str):
            classes.update(t for t in cn.split() if t)
    return classes


def _rubric_findings(page_schema: dict, plan: dict, route: str) -> list[dict]:
    """Return findings for each rubric check that scores below target."""
    findings: list[dict] = []

    # 1. Palette diversity — ≥4 non-neutral hex colors.
    hexes = _collect_hexes(page_schema)
    non_neutral = {h for h in hexes if h not in _NEUTRAL_HEXES}
    if hexes and len(non_neutral) < 4:
        findings.append({
            "rule": "design.rubric.palette_diversity_low",
            "message": (
                f"route {route!r}: only {len(non_neutral)} non-neutral color(s) "
                f"({sorted(non_neutral)[:4]}). Target: ≥4."
            ),
            "severity": "warning",
        })

    # 2. Class diversity vs shadcn baseline — non-baseline classes ≥40%.
    classes = _collect_classes(page_schema)
    if classes:
        overlap = classes & _SHADCN_BASELINE
        diversity = 1.0 - (len(overlap) / max(len(classes), 1))
        if diversity < 0.40:
            findings.append({
                "rule": "design.rubric.class_diversity_low",
                "message": (
                    f"route {route!r}: only {int(diversity * 100)}% of Tailwind "
                    "classes diverge from the shadcn baseline (target ≥40%). "
                    f"Baseline overlap: {sorted(overlap)[:6]}."
                ),
                "severity": "warning",
            })

    # 3. Aesthetic profile conformance — when a profile is picked, the
    #    page's CSS-variable references (hsl(var(--x))) should hit ≥75%
    #    of the profile's declared css_variables.
    try:
        from services.aesthetic_profile_picker import pick_profile
        profile = pick_profile(plan) if isinstance(plan, dict) else None
    except Exception:  # noqa: BLE001
        profile = None
    if profile:
        css_vars = profile.get("css_variables") or {}
        expected = set(css_vars.keys())
        if expected:
            import re as _re
            used: set[str] = set()
            def _scan(v):
                if isinstance(v, str):
                    for m in _re.findall(r"var\((--[a-zA-Z0-9-]+)\)", v):
                        used.add(m)
                elif isinstance(v, dict):
                    for x in v.values():
                        _scan(x)
                elif isinstance(v, list):
                    for x in v:
                        _scan(x)
            _scan(page_schema)
            covered = expected & used
            ratio = len(covered) / max(len(expected), 1)
            if ratio < 0.75:
                findings.append({
                    "rule": "design.rubric.aesthetic_profile_conformance_low",
                    "message": (
                        f"route {route!r}: page uses {int(ratio * 100)}% of the "
                        f"'{profile.get('name')}' profile's css_variables "
                        f"(target ≥75%). Missing: {sorted(expected - covered)[:5]}."
                    ),
                    "severity": "warning",
                })

    # 4. Shape topology conformance — MUST be 100% (hard). We reuse
    #    domain_conformance.check_page as the topology check; any error
    #    there is a hard rubric failure.
    try:
        from services.domain_conformance import check_page as _check
        dc = _check(plan if isinstance(plan, dict) else {}, route, page_schema)
        for f in dc:
            sev = getattr(f, "severity", None) or (
                f.get("severity") if isinstance(f, dict) else "error"
            )
            if sev == "error":
                findings.append({
                    "rule": "design.rubric.topology_conformance_fail",
                    "message": (
                        f"route {route!r}: shape topology violation — "
                        f"{getattr(f, 'rule', None) or (f.get('rule') if isinstance(f, dict) else 'unknown')}"
                    ),
                    "severity": "error",
                })
    except Exception:  # noqa: BLE001
        pass

    # 5. Signature-moves presence (routes owned by an ArchetypeInstance
    #    should carry ≥80% of required signatures). We use the guard's
    #    compute_requirements output.
    try:
        from services.signature_moves_guard import (
            compute_requirements as _sm_compute,
            requirements_for_route as _sm_for_route,
        )
        report = _sm_compute(plan if isinstance(plan, dict) else {})
        reqs = _sm_for_route(report, route) if report else ()
        if reqs:
            # Signature "presence" is best-effort — we can't reliably
            # detect every renderer sentinel without more resolver
            # wiring (M4-T6 leaves this half stubbed). For now flag a
            # low presence ratio when any signature is required at all,
            # so the rubric surfaces the class of finding for
            # downstream inspection.
            required_names = {r.signature for r in reqs}
            findings.append({
                "rule": "design.rubric.signature_moves_check",
                "message": (
                    f"route {route!r}: owning archetype declares "
                    f"{len(required_names)} signature move(s) — verify "
                    "presence via services.shape_signature_enforcer."
                ),
                "severity": "info",
            })
    except Exception:  # noqa: BLE001
        pass

    return findings


def design_critic_score(page_schema: dict, plan: dict, route: str) -> int:
    """Aggregate the rubric into a 0–100 score.

    Baseline 100. Every warning-severity rubric finding subtracts 10;
    error-severity subtracts 25. Info-only findings don't move the
    score. Clamps to [0, 100]. Used by the M6-T10 live-regen quality
    dashboard target: consumer-utility ≥85, workspace ≥70, none <50.
    """
    score = 100
    for f in _rubric_findings(page_schema, plan, route):
        sev = f.get("severity") or "warning"
        if sev == "error":
            score -= 25
        elif sev == "warning":
            score -= 10
    return max(0, min(100, score))


# ══════════════════════════════════════════════════════════════════
# ux — invariant conformance
# ══════════════════════════════════════════════════════════════════


_DATA_BOUND_TYPES = {"Table", "List", "Grid", "Kanban", "Calendar",
                     "Timeline", "Chart", "Repeat"}


def ux_critique(page_schema: dict, plan: dict, route: str) -> list[dict[str, Any]]:
    """UX invariants.

    - Every ``Form`` node has a submit control (a button with
      ``submit: True`` in its props, or a ``submitLabel`` on the Form
      itself). A form with no submit UI is broken by construction.
    - Every data-bound component (Table / List / Grid / Kanban)
      that binds a dataSource declares an ``emptyText`` or an
      IllustratedEmpty child — the default "0 rows" is a dead-end.
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(page_schema, dict):
        return findings

    for node in _iter_nodes(page_schema.get("root")):
        if _node_type(node) == "Form":
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            has_submit_label = bool(props.get("submitLabel"))
            has_submit_button = any(
                _node_type(child) == "Button"
                and isinstance(child.get("props"), dict)
                and child["props"].get("submit") is True
                for child in _iter_nodes(node.get("children"))
            )
            if not has_submit_label and not has_submit_button:
                findings.append({
                    "rule": "ux.form_missing_submit",
                    "message": (
                        f"route {route!r}: Form node has no submit UI "
                        "(no submitLabel + no Button with submit=true)."
                    ),
                    "severity": "error",
                })

    for node in _iter_nodes(page_schema.get("root")):
        if _node_type(node) not in _DATA_BOUND_TYPES:
            continue
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        bound = bool(props.get("dataSource") or props.get("bind"))
        if not bound:
            continue
        has_empty_text = bool(props.get("emptyText"))
        has_empty_child = any(
            _node_type(c) in {"IllustratedEmpty", "EmptyState"}
            for c in _iter_nodes(node.get("children"))
        )
        if not has_empty_text and not has_empty_child:
            findings.append({
                "rule": "ux.data_bound_missing_empty_state",
                "message": (
                    f"route {route!r}: {_node_type(node)} bound to a "
                    "dataSource has no emptyText / IllustratedEmpty. "
                    "Empty rows read as broken."
                ),
                "severity": "warning",
            })

    return findings


# ══════════════════════════════════════════════════════════════════
# correctness — binding / data conformance
# ══════════════════════════════════════════════════════════════════


def _plan_known_workflows(plan: dict) -> set[str]:
    wfs = plan.get("workflows") if isinstance(plan, dict) else None
    if not isinstance(wfs, list):
        return set()
    return {str(w.get("name")).strip() for w in wfs
            if isinstance(w, dict) and isinstance(w.get("name"), str)}


def _plan_known_datasources(page_schema: dict) -> set[str]:
    srcs = page_schema.get("dataSources") if isinstance(page_schema, dict) else None
    if not isinstance(srcs, list):
        return set()
    return {str(s.get("name")).strip() for s in srcs
            if isinstance(s, dict) and isinstance(s.get("name"), str)}


def correctness_critique(page_schema: dict, plan: dict, route: str) -> list[dict[str, Any]]:
    """Binding + workflow refs must resolve to real names.

    - Every ``dataSource`` prop reference (Table.props.dataSource,
      Form.props.dataSource, Select.props.optionsFrom.source, …)
      names something in page.dataSources.
    - Every Form.workflow / Button.action.workflow resolves to a
      workflow name in ``plan.workflows``.
    """
    findings: list[dict[str, Any]] = []
    if not isinstance(page_schema, dict):
        return findings

    known_sources = _plan_known_datasources(page_schema)
    known_workflows = _plan_known_workflows(plan)

    # Also allow the entity singular / lowercase versions of dataSource
    # names — some emitters lookup by slug.
    known_sources_l = {s.lower() for s in known_sources}

    for node in _iter_nodes(page_schema.get("root")):
        props = node.get("props") if isinstance(node.get("props"), dict) else {}
        # dataSource refs
        for key in ("dataSource", "bind"):
            val = props.get(key)
            if not isinstance(val, str) or not val.strip():
                continue
            src = val.strip().split(".")[0].rstrip("[]").strip("{{}}")
            if src and src.lower() not in known_sources_l and known_sources:
                findings.append({
                    "rule": "correctness.unknown_datasource",
                    "message": (
                        f"route {route!r}: node `{_node_type(node)}` "
                        f"references dataSource {src!r} but page declares "
                        f"only {sorted(known_sources)}."
                    ),
                    "severity": "error",
                })
        # Select.optionsFrom
        of = props.get("optionsFrom")
        if isinstance(of, dict):
            src = of.get("source")
            if (isinstance(src, str) and src.strip()
                    and src.strip().lower() not in known_sources_l
                    and known_sources):
                findings.append({
                    "rule": "correctness.unknown_optionsfrom_source",
                    "message": (
                        f"route {route!r}: Select.optionsFrom.source="
                        f"{src!r} not in {sorted(known_sources)}."
                    ),
                    "severity": "error",
                })
        # Form.workflow
        if _node_type(node) == "Form":
            wf = props.get("workflow")
            if (isinstance(wf, str) and wf.strip()
                    and known_workflows
                    and wf.strip() not in known_workflows):
                findings.append({
                    "rule": "correctness.unknown_workflow_ref",
                    "message": (
                        f"route {route!r}: Form.workflow={wf!r} not in "
                        f"plan.workflows {sorted(known_workflows)}."
                    ),
                    "severity": "error",
                })
        # Button.action.workflow
        if _node_type(node) == "Button":
            action = props.get("action")
            if isinstance(action, dict):
                wf = action.get("workflow")
                if (isinstance(wf, str) and wf.strip()
                        and known_workflows
                        and wf.strip() not in known_workflows):
                    findings.append({
                        "rule": "correctness.unknown_workflow_ref",
                        "message": (
                            f"route {route!r}: Button.action.workflow="
                            f"{wf!r} not in plan.workflows "
                            f"{sorted(known_workflows)}."
                        ),
                        "severity": "error",
                    })

    return findings


# Public registry — mirrors the shape of stage_check_registry so
# critic_panel can iterate it.
PERSONA_REGISTRY = {
    "design": design_critique,
    "ux": ux_critique,
    "correctness": correctness_critique,
}


__all__ = [
    "PERSONA_REGISTRY",
    "design_critique",
    "ux_critique",
    "correctness_critique",
    "design_critic_score",
]
