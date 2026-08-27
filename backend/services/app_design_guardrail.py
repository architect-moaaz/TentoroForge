# backend/services/app_design_guardrail.py
"""Open-with-guardrails: validate the planner's archetype/feature choices against
the capability catalog. Un-renderable choices fall back gracefully (never a broken
page); unsupported/SP2 features are dropped. Returns (plan, report)."""
from __future__ import annotations

from services.app_design_catalog import (
    is_renderable_archetype, is_renderable_feature,
)

# Cheap alias map for near-miss archetype names the LLM might invent.
_ALIAS = {
    "board": "kanban", "task-board": "kanban", "pipeline": "kanban",
    "schedule": "calendar", "agenda": "calendar",
    "split-pane": "inbox", "mailbox": "inbox", "messages": "inbox",
    "analytics": "report", "reports": "report", "charts": "report",
    "stepper": "wizard", "onboarding": "wizard", "multi-step": "wizard",
    "history": "audit-log", "activity": "audit-log", "log": "audit-log",
    "config": "settings", "preferences": "settings", "profile": "settings",
    # Standalone tool aliases — planner may name the archetype by shape
    # ("tool", "calculator") or specific instance ("emi", "bmi"). All map
    # to the single `computational` archetype the templates understand.
    "calculator": "computational", "converter": "computational",
    "estimator": "computational", "tool": "computational",
    "compute": "computational", "formula": "computational",
    "emi": "computational", "bmi": "computational", "tip": "computational",
    "loan": "computational", "unit-converter": "computational",
    "quiz": "computational", "scorer": "computational",
}


def _resolve_archetype(page: dict) -> tuple[str, tuple[str, str] | None]:
    original = page.get("archetype")
    raw = (original or "").strip().lower() or None
    if is_renderable_archetype(raw):
        return raw, None
    aliased = _ALIAS.get(raw) if raw else None
    if is_renderable_archetype(aliased):
        return aliased, (original, aliased)
    fallback = page.get("type") if is_renderable_archetype(page.get("type")) else "list"
    return fallback, ((original, fallback) if original and original != fallback else None)


def _snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def ensure_entity_reachability(plan: dict) -> tuple[dict, dict]:
    """Guardrail for the relaxed CRUD mandate (SP3.2).

    Once the planner is free to skip full list/detail/form pages for supporting
    entities, an entity can end up with no page. That's fine *if* it's reachable
    inline — i.e. another entity references it via a relation, so it surfaces as a
    dropdown / nested form in a parent's create page. But an entity with NEITHER a
    page NOR a relation is orphaned: its data can never be reached or edited. The
    guard PROMOTES such entities with a minimal list page (it never drops one).

    Returns (plan, report) where report classifies every entity as primary (has its
    own page(s)), supporting_inline (reachable via a relation), or promoted (was
    orphaned, given a page here).
    """
    report: dict = {"primary": [], "supporting_inline": [], "promoted": []}
    if not isinstance(plan, dict):
        return plan, report
    entities = [
        e["name"] for e in (plan.get("entities") or [])
        if isinstance(e, dict) and e.get("name")
    ]
    pages = plan.get("pages")
    if not isinstance(pages, list):
        pages = []
        plan["pages"] = pages
    paged = {p.get("entity") for p in pages if isinstance(p, dict) and p.get("entity")}
    related: set = set()
    for r in plan.get("relations") or []:
        if isinstance(r, dict):
            if r.get("from"):
                related.add(r["from"])
            if r.get("to"):
                related.add(r["to"])
    for name in entities:
        if name in paged:
            report["primary"].append(name)
        elif name in related:
            report["supporting_inline"].append(name)
        else:
            slug = _snake(name)
            pages.append({
                "route": f"/{slug}",
                "name": f"{name}ListPage",
                "entity": name,
                "archetype": "list",
                "features": [],
                "description": (
                    f"List of {name} records with create, view, edit, and delete "
                    f"actions. (Auto-added: this entity had no other reachable page.)"
                ),
            })
            report["promoted"].append(name)
    return plan, report


def normalize_app_design(plan: dict) -> tuple[dict, dict]:
    pages = plan.get("pages") if isinstance(plan, dict) else None
    report = {"pages": []}
    if not isinstance(pages, list):
        return plan, report
    for page in pages:
        if not isinstance(page, dict):
            continue
        archetype, sub = _resolve_archetype(page)
        page["archetype"] = archetype
        kept, dropped = [], []
        for f in page.get("features") or []:
            (kept if is_renderable_feature(f) else dropped).append(f)
        page["features"] = kept
        report["pages"].append({
            "route": page.get("route"), "archetype": archetype,
            "substituted": sub, "kept_features": kept, "dropped_features": dropped,
        })
    return plan, report
