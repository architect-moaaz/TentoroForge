"""A data-bound widget must be bound to data, in the shape it asked for.

Two live symptoms on opmk18qr /dashboard, one cause repeated:

  **"Team Coverage Health" reads 0%.** The Gauge's props are
  ``{min, max, unit, showValue, label}`` — no ``value``, no binding. It was
  never wired to anything. A Gauge asked to draw nothing draws zero, and zero
  on a dial labelled Coverage reads as a measurement: nobody is covered. That
  is worse than an empty card, because it is a number a person will act on.

  **"Recent Activity" reads "Someone" ten times.** ActivityFeed's contract is
  ``{actor:{name}, action, target, timestamp}``. It is bound to Notification,
  whose columns are ``{recipientName, type, message, createdAt}``. Not one
  field lines up, so every row falls through to the component's placeholder.

Same shape as the delta bug and the percent bug: two components each holding
a plausible half of a contract, with nothing between them checking they agree.

So the two halves are introduced. For the feed, the real columns are read
from the registry and mapped onto the contract by role — a person-ish column
becomes the actor, a time-ish column the timestamp — and the map travels with
the node so the component reads the right fields instead of guessing. For the
gauge there is nothing to introduce it to: inventing a coverage figure would
mean choosing a numerator and denominator nobody wrote, so it is replaced
with the empty state and logged, leaving the missing metric visible as work
rather than hidden behind a plausible 0%.
"""

from __future__ import annotations

import re
from typing import Any

# Widgets that render a single number on a dial or tile and are meaningless
# without one.
_VALUE_WIDGETS = {"Gauge", "SplitArc", "Progress"}

_ID_SUFFIX = re.compile(r"(^|[a-z])(Id|ID|_id)$")


def _is_id(col: str) -> bool:
    return bool(_ID_SUFFIX.search(col)) or col.lower() == "id"


def _pick(cols: list[str], *patterns: str, exclude_ids: bool = True) -> str | None:
    """First column whose name contains one of `patterns`, in pattern order."""
    for pat in patterns:
        for c in cols:
            if exclude_ids and _is_id(c):
                continue
            if pat.lower() in c.lower():
                return c
    return None


def feed_field_map(columns: list[str]) -> dict[str, str]:
    """Map real entity columns onto ActivityFeed's contract, by role.

    Only maps what it can actually find. A missing key means the component
    keeps its own fallback, which is honest; a wrong key would put the wrong
    text on screen with full confidence.
    """
    cols = [c for c in (columns or []) if isinstance(c, str)]
    out: dict[str, str] = {}

    # Who. An explicit name beats a qualified one (name > recipientName), and
    # an id column is never a person's name however it is spelled.
    actor = _pick(cols, "name")
    if actor:
        # Prefer the shortest match — "name" over "recipientName" — because the
        # bare column is the entity's own name rather than a relation's.
        candidates = [c for c in cols if not _is_id(c) and "name" in c.lower()]
        actor = min(candidates, key=len) if candidates else actor
        out["actor"] = actor

    # When.
    ts = _pick(cols, "createdAt", "occurredAt", "timestamp", "date", "at")
    if ts:
        out["timestamp"] = ts

    # What kind of thing happened.
    action = _pick(cols, "type", "action", "event", "status")
    if action:
        out["action"] = action

    # What it was about — the prose column, not the kind column.
    target = _pick(cols, "message", "title", "description", "subject", "detail")
    if target:
        out["target"] = target

    return out


def has_value_binding(node: dict) -> bool:
    """True when this widget was actually given something to display."""
    props = (node or {}).get("props") or {}
    for key in ("value", "percent", "ratio", "data"):
        v = props.get(key)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return True          # a literal 0 counts: the author wrote it
    return False


def _empty_state(title: str) -> dict:
    subject = (title or "this metric").strip()
    return {
        "type": "EmptyState",
        "props": {
            "title": f"{subject} is not measured yet",
            "description": "Connect this metric to a data source to see it here.",
        },
        "id": "unbound-metric-empty",
    }


def _columns_of(registry: dict, entity: str) -> list[str]:
    ents = (registry or {}).get("entities") or {}
    ent = ents.get(entity) or {}
    return [c.get("name") for c in (ent.get("columns") or []) if c.get("name")]


def _entity_for_source(page: dict, name: str) -> str | None:
    for ds in page.get("dataSources") or []:
        if isinstance(ds, dict) and ds.get("name") == name:
            return ds.get("entity")
    return None


def _source_of(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not (s.startswith("{{") and s.endswith("}}")):
        return None
    return s[2:-2].strip().split(".")[0] or None


def reconcile_widget_data(page: dict, registry: dict) -> dict[str, Any]:
    """Give feeds a field map; stop value-less dials claiming a number."""
    notes: list[str] = []

    def visit(node: Any, card_title: str = "") -> None:
        if isinstance(node, list):
            for c in node:
                visit(c, card_title)
            return
        if not isinstance(node, dict):
            return

        if node.get("type") == "Card":
            card_title = (node.get("props") or {}).get("title") or card_title
            kids = node.get("children") or []
            # A dial with nothing behind it is decoration that reads as data.
            for k in list(kids):
                if isinstance(k, dict) and k.get("type") in _VALUE_WIDGETS \
                        and not has_value_binding(k):
                    node["children"] = [_empty_state(card_title)]
                    notes.append(
                        f"{card_title!r}: {k.get('type')} had no value binding — "
                        f"it was drawing 0 as if measured; replaced with an "
                        f"empty state so the missing metric stays visible")
                    return

        if node.get("type") == "ActivityFeed":
            props = node.setdefault("props", {})
            if "fields" not in props:
                src = _source_of(props.get("entries"))
                entity = _entity_for_source(page, src) if src else None
                cols = _columns_of(registry, entity) if entity else []
                mapping = feed_field_map(cols) if cols else {}
                if mapping:
                    props["fields"] = mapping
                    notes.append(
                        f"ActivityFeed on {entity}: mapped {mapping} — its "
                        f"contract wants actor/action/target/timestamp and the "
                        f"entity has none of those names")

        for c in (node.get("children") or []):
            visit(c, card_title)

    visit(page.get("root"))
    return {"changed": len(notes), "notes": notes}


def entity_columns_from_app(app_root: str) -> dict[str, Any]:
    """Registry-shaped column info read from the app's own Drizzle schema.

    `contracts/registry.json` is not always written, and plan.json lists
    entity NAMES without columns — opmk18qr has both gaps, which is why the
    field map had nothing to work from and the feed kept saying "Someone".
    The Drizzle schema is the one place the real names always exist, because
    the database is built from it.

    Entity keys are singular and capitalised to match what a dataSource
    declares (`entity: "Notification"` for table `notifications`).
    """
    import re as _re
    from pathlib import Path as _Path

    out: dict[str, dict] = {}
    schema_dir = _Path(app_root, "src", "db", "schema")
    if not schema_dir.is_dir():
        return {"entities": {}}

    table_re = _re.compile(
        r'export const (\w+) = pgTable\(\s*["\'`](\w+)["\'`]\s*,\s*\{(.*?)\n\}\)',
        _re.S)
    for f in schema_dir.glob("*.ts"):
        if f.name.startswith("_forge"):
            continue          # platform tables, never a domain entity
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        for _var, table, body in table_re.findall(src):
            cols = _re.findall(r'^\s*(\w+)\s*:', body, _re.M)
            if not cols:
                continue
            entity = _singular(table)
            out[entity] = {"columns": [{"name": c} for c in cols]}
    return {"entities": out}


def _singular(table: str) -> str:
    """`notifications` -> `Notification`, matching how dataSources name it."""
    name = table.replace("_", " ").title().replace(" ", "")
    for suffix, repl in (("ies", "y"), ("ses", "s"), ("s", "")):
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            return name[: -len(suffix)] + repl
    return name
