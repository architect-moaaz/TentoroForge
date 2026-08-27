"""Binding-prop normalizer — canonical binding spelling for data widgets.

The page composer (and occasionally the LLM page agent) emits component-
level ``props.dataSource: "documents"`` — a bare dataSource *name*. The
renderer contract is a Mustache binding on the component's canonical
data prop: ``Table.rows = "{{documents}}"``, ``ActivityFeed.entries``,
``Chart.data``. The result of the mismatch is a page whose API returns
rows while every table/feed/chart renders empty (atb0m97x class).

This pass normalizes, per page schema:

* ``Table`` / ``ActivityFeed`` / ``Chart`` nodes carrying a string
  ``props.dataSource`` that names a page dataSource (bare or already
  ``{{wrapped}}``) get the canonical prop set to ``"{{name}}"`` —
  only when the canonical prop is absent/empty, never clobbering an
  authored binding.
* ``DescriptionList`` keeps ``dataSource`` as its canonical prop but
  needs a *bound value* — a bare name is wrapped to ``"{{name}}"``.
* Bare ``Select`` nodes (no ``options``, no ``optionsFrom``) get their
  enum options backfilled from plan ``enum_values`` via
  ``plan_field_lookup`` (entity resolved from the enclosing Form, else
  by unique column match across plan entities). Unfillable Selects are
  reported, not guessed.

Additive + idempotent. Report written to contracts/binding-normalize.json.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# component type -> canonical binding prop (all accept "{{name}}" strings)
CANONICAL_PROP: dict[str, str] = {
    "Table": "rows",
    "ActivityFeed": "entries",
    "Chart": "data",
}

_BINDING_RE = re.compile(r"^\{\{\s*([A-Za-z0-9_.\[\]]+)\s*\}\}$")


def _bare_name(value: Any) -> str | None:
    """Return the dataSource name a string refers to, unwrapping ``{{ }}``."""
    if not isinstance(value, str) or not value.strip():
        return None
    m = _BINDING_RE.match(value.strip())
    if m:
        return m.group(1)
    return value.strip()


def _iter_nodes(node: Any, form_entity: str | None = None):
    """Yield (node, nearest_form_entity) for every dict node in the tree."""
    if isinstance(node, dict):
        if node.get("type") == "Form":
            ent = (node.get("props") or {}).get("entity")
            if isinstance(ent, str) and ent:
                form_entity = ent
        yield node, form_entity
        for v in node.values():
            yield from _iter_nodes(v, form_entity)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v, form_entity)


def _unique_enum_entity(plan: dict | None, column: str) -> str | None:
    """Entity name if exactly ONE plan entity declares enum_values for column."""
    if not plan:
        return None
    from services.plan_field_lookup import get_enum_values, _iter_entities  # noqa: PLC0415
    # dedupe by folded name — _iter_entities yields an entity once per
    # plan shape it appears in (entities dict AND data_models list)
    hits: dict[str, str] = {}
    for name, _ent in _iter_entities(plan):
        if name and get_enum_values(plan, name, column):
            hits[name.strip().lower()] = name
    return next(iter(hits.values())) if len(hits) == 1 else None


def normalize_binding_props(output_dir: str | Path) -> dict:
    """Run the normalizer over every page schema. Returns the report."""
    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    report: dict[str, Any] = {
        "normalized": [], "selects_filled": [], "unresolved": [],
        "summary": {"normalized": 0, "selects_filled": 0, "unresolved": 0},
    }
    if not schemas_dir.is_dir():
        return report

    plan: dict | None = None
    try:
        from services.plan_field_lookup import load_plan, get_enum_options
        plan = load_plan(str(root))
    except Exception as e:  # noqa: BLE001
        logger.warning("binding-normalize: plan load failed: %s", e)
        get_enum_options = None  # type: ignore[assignment]

    for path in sorted(schemas_dir.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        ds_names = {
            d.get("name") for d in (doc.get("dataSources") or [])
            if isinstance(d, dict) and d.get("name")
        }
        rel = str(path.relative_to(schemas_dir))
        dirty = False

        for node, form_entity in _iter_nodes(doc.get("root") or doc):
            ntype = node.get("type")
            props = node.get("props")
            if not isinstance(props, dict):
                continue

            # 1) dataSource-name → canonical binding prop
            canon = CANONICAL_PROP.get(ntype)
            if canon:
                name = _bare_name(props.get("dataSource"))
                existing = props.get(canon)
                empty = existing in (None, "", [])
                if name and name in ds_names and empty:
                    props[canon] = "{{" + name + "}}"
                    dirty = True
                    report["normalized"].append(
                        {"page": rel, "type": ntype, "prop": canon,
                         "binding": props[canon]})

            # 2) DescriptionList bare dataSource → wrapped binding
            if ntype == "DescriptionList":
                raw = props.get("dataSource")
                if (isinstance(raw, str) and raw.strip()
                        and not _BINDING_RE.match(raw.strip())):
                    props["dataSource"] = "{{" + raw.strip() + "}}"
                    dirty = True
                    report["normalized"].append(
                        {"page": rel, "type": ntype, "prop": "dataSource",
                         "binding": props["dataSource"]})

            # 3) bare Select → enum backfill from plan
            if ntype == "Select" and not props.get("options") \
                    and not props.get("optionsFrom"):
                col = props.get("name")
                opts = None
                if isinstance(col, str) and col and plan and get_enum_options:
                    entity = form_entity or _unique_enum_entity(plan, col)
                    if entity:
                        opts = get_enum_options(plan, entity, col)
                if opts:
                    props["options"] = opts
                    dirty = True
                    report["selects_filled"].append(
                        {"page": rel, "name": col,
                         "options": [o["value"] for o in opts]})
                else:
                    report["unresolved"].append(
                        {"page": rel, "type": "Select", "name": col,
                         "reason": "no plan enum_values found"})

        if dirty:
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    s = report["summary"]
    s["normalized"] = len(report["normalized"])
    s["selects_filled"] = len(report["selects_filled"])
    s["unresolved"] = len(report["unresolved"])

    contracts = root / "contracts"
    try:
        contracts.mkdir(parents=True, exist_ok=True)
        (contracts / "binding-normalize.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("binding-normalize: report write failed: %s", e)
    return report
