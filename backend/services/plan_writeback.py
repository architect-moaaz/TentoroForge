"""Plan writeback — the plan stays the source of truth AFTER repairs
(item 7, the roadmap's last piece).

Every pass in the post-gen tail may change shipped reality: routes
collapse into aliases, pages get reclassified by what they actually
render, density gets derived. Until now none of that flowed back into
``src/contracts/plan.json`` — so the next consumer of the plan (Smith,
a regen, the delivery gate's kind check, the coverage critic) read a
document that described an app that no longer exists. The audit's
"/ is planned as dashboard but ships as an upload form" finding was
exactly this: reality moved, the plan never did.

Reconciliations (all deterministic, all recorded):
  - **kind drift** — a plan page whose SHIPPED job (from
    route_dedup.page_signature, structural) lands in a different
    equivalence class than its planned kind gets its ``kind``
    corrected. Classes group synonyms (create/upload/form…) so
    vocabulary variation is never "drift"; kinds outside the known
    vocabulary are left alone (unknown intent is not ours to rewrite).
  - **aliases** — routes the dedup pass collapsed get ``alias_of``
    stamped on their plan page, so no consumer ever builds on top of
    an alias again.
  - **density** — the per-page density decision is mirrored onto the
    plan page for composers that read the plan, not the schema.

What is deliberately NOT written back: missing pages are never removed
(the plan records intent — the delivery gate enforces it; silently
deleting the promise would hide the gap), and workflows are untouched.

Every change lands in ``plan["writeback"]["changes"]`` and the pass
runs immediately BEFORE the delivery gate, so the gate judges the
reconciled plan: kind-drift warnings clear, planned-page-missing
errors survive.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.binding_validator import _read_schema_tables, _SlugResolver
from services.delivery_gate import _load_page_schemas, _norm_route
from services.route_dedup import page_signature

logger = logging.getLogger(__name__)

# Synonym classes: variation inside a class is vocabulary, not drift.
_KIND_CLASSES: dict[str, set[str]] = {
    "create":    {"create", "upload", "form", "new", "add", "submit"},
    "list":      {"list", "table", "collection", "index", "browse"},
    "detail":    {"detail", "record", "view", "show", "profile"},
    "edit":      {"edit", "update"},
    "dashboard": {"dashboard", "overview", "home", "landing", "stats",
                  "analytics"},
    "search":    {"search", "find", "lookup"},
}


def _class_of(kind: str | None) -> str | None:
    k = (kind or "").strip().lower()
    for cls, members in _KIND_CLASSES.items():
        if k in members:
            return cls
    return None


def _load_dedup_aliases(root: Path) -> dict[str, str]:
    """loser route → winner route from the dedup pass's report."""
    try:
        rep = json.loads(
            (root / "contracts" / "route-dedup.json").read_text())
    except Exception:  # noqa: BLE001
        return {}
    return {
        _norm_route(c["loser"]): c["winner"]
        for c in rep.get("collapsed") or []
        if isinstance(c, dict) and c.get("loser") and c.get("winner")
    }


def write_back_plan(output_dir: str | Path) -> dict:
    """Reconcile plan.json with shipped reality. Returns
    ``{"changes": [...]}``; empty when nothing drifted. Never raises."""
    root = Path(output_dir)
    plan_path = root / "src" / "contracts" / "plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"changes": []}
    if not isinstance(plan, dict):
        return {"changes": []}

    resolver = _SlugResolver(_read_schema_tables(str(root)))
    docs_by_route = {_norm_route(r): doc for r, doc in _load_page_schemas(root)}
    aliases = _load_dedup_aliases(root)

    changes: list[dict] = []
    for page in plan.get("pages") or []:
        if not isinstance(page, dict) or not page.get("route"):
            continue
        route = _norm_route(str(page["route"]))
        doc = docs_by_route.get(route)

        # Alias stamp — a page the dedup pass collapsed.
        winner = aliases.get(route)
        if winner and page.get("alias_of") != winner:
            page["alias_of"] = winner
            changes.append({"route": route, "field": "alias_of",
                            "to": winner})

        if doc is None or winner:
            continue  # unshipped (gate's job) or alias (job is the winner's)

        sig = page_signature(str(page["route"]), doc, resolver)
        shipped_job = sig[1] if sig else None

        # Kind drift — only when BOTH sides map to known classes and
        # they differ, or when the plan never declared a kind at all.
        planned_kind = page.get("kind") or page.get("type")
        planned_cls = _class_of(planned_kind if isinstance(planned_kind, str)
                                else None)
        if shipped_job:
            if planned_cls is None and not planned_kind:
                page["kind"] = shipped_job
                changes.append({"route": route, "field": "kind",
                                "from": None, "to": shipped_job})
            elif planned_cls is not None and planned_cls != shipped_job:
                changes.append({"route": route, "field": "kind",
                                "from": planned_kind, "to": shipped_job})
                page["kind"] = shipped_job

        # Density mirror — derived by density_frames onto the schema doc.
        density = doc.get("density")
        if isinstance(density, str) and page.get("density") != density:
            page["density"] = density
            changes.append({"route": route, "field": "density",
                            "to": density})

    if changes:
        plan["writeback"] = {"changes": changes}
        try:
            plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
            logger.info("[plan-writeback] reconciled %d field(s): %s",
                        len(changes),
                        ", ".join(f"{c['route']}:{c['field']}"
                                  for c in changes[:6]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[plan-writeback] could not write plan: %s", exc)
            return {"changes": []}
    return {"changes": changes}


__all__ = ["write_back_plan"]
