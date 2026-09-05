"""A table drawn as text becomes a table bound to data.

WHY THE VISION PASS DID NOT COVER THIS. `vision` looks at a picture and says
what it is; it exists for designs flattened to images, where the drawing is
all there is. This dashboard's table is not flattened: Dev Mode wrote a
`Table` layer with a `Table Row` of header labels and fifty-four `Table
Cell`s at pixel positions, every word readable. Composed faithfully it was a
picture all the same — six cases the designer typed, a "View →" per row
with no record to open — because nothing read the words.

WHAT IS READ. The header labels, the first rows, and the title of the card
the table sits in ("Active Cases"). That is enough to ask which entity the
table shows and which field each column is, and the answer is validated the
way the vision answer is: an entity the application does not define is no
entity; a field the entity does not have is dropped. Unbound, the drawing
stays exactly as it was.

WHAT COMES OUT. The same classification shape `realize` already consumes,
plus the drawn column labels (so "Case No" stays "Case No" rather than
becoming "Case Number") and the row link — the entity's detail route — so
the "View →" the designer drew per row is the row.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

_LEFT = re.compile(r"\bleft-(?:\[(-?[\d.]+)px\]|(0))(?=\s|$)")
_TOP = re.compile(r"\btop-(?:\[(-?[\d.]+)px\]|(0))(?=\s|$)")
_ARROW = re.compile(r"(→|↗|›|»|➜|⟶)\s*$|^\s*[Vv]iew\b")

#: Rows closer than this in `top` are one row; Figma rounds.
ROW_TOLERANCE = 8.0
#: Sample rows shown to the model. Three say what the columns hold.
SAMPLE_ROWS = 3
#: A table needs this many drawn columns to be one.
MIN_COLUMNS = 2


@dataclass
class DrawnTable:
    node_id: str
    title: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)
    has_row_action: bool = False


# --------------------------------------------------------------- extraction

def _text(node: Any) -> str:
    from services.jsx_to_schema import _descendant_text
    return _descendant_text(node)


def _first_words(element: Any) -> str:
    from services.jsx_to_schema import JSXElement
    for c in element.children:
        if isinstance(c, str) and re.search(r"[A-Za-z0-9]", c):
            return c.strip()
        if isinstance(c, JSXElement):
            t = _first_words(c)
            if t:
                return t
    return ""


def _offset(cn: str, rx: re.Pattern) -> float | None:
    m = rx.search(cn or "")
    return float(m.group(1) or 0) if m else None


def drawn_tables(code: str) -> list[DrawnTable]:
    """Every table the frame draws, with its header, first rows and title."""
    from services.jsx_to_schema import JSXElement, parse_jsx_tree

    root = parse_jsx_tree(code)
    out: list[DrawnTable] = []

    def walk(node: Any, ancestors: list) -> None:
        if not isinstance(node, JSXElement):
            return
        kids = [c for c in node.children if isinstance(c, JSXElement)]
        cells = [k for k in kids if k.attrs.get("data-name") == "Table Cell"]
        header_row = next((k for k in kids if k.attrs.get("data-name") == "Table Row"), None)
        if header_row is not None and len(cells) >= MIN_COLUMNS:
            headers = [t for t in _texts_of(header_row) if t]
            rows = _rows_of(cells)
            title = next((_first_words(a) for a in reversed(ancestors)
                          if any(t.startswith("bg-") for t in (a.attrs.get("className") or "").split())), "")
            has_action = any(_ARROW.search(c) for r in rows for c in r)
            if len(headers) >= MIN_COLUMNS:
                out.append(DrawnTable(
                    node_id=str(node.attrs.get("data-node-id") or ""),
                    title=title, headers=headers,
                    rows=rows[:SAMPLE_ROWS], has_row_action=has_action))
                return
        for k in kids:
            walk(k, ancestors + [node])

    walk(root, [])
    return [t for t in out if t.node_id]


def _texts_of(element: Any) -> list[str]:
    from services.jsx_to_schema import JSXElement
    out: list[str] = []
    for c in element.children:
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
        elif isinstance(c, JSXElement):
            t = _text(c)
            if t:
                out.append(t)
    return out


def _rows_of(cells: Sequence[Any]) -> list[list[str]]:
    """Cells grouped by their `top` into rows, each row read left to right."""
    placed = []
    for c in cells:
        cn = c.attrs.get("className") or ""
        top, left = _offset(cn, _TOP), _offset(cn, _LEFT)
        if top is None or left is None:
            continue
        placed.append((top, left, _text(c)))
    placed.sort()
    rows: list[dict] = []
    for top, left, text in placed:
        if rows and abs(top - rows[-1]["top"]) <= ROW_TOLERANCE:
            rows[-1]["cells"].append((left, text))
        else:
            rows.append({"top": top, "cells": [(left, text)]})
    return [[t for _l, t in sorted(r["cells"])] for r in rows]


# ------------------------------------------------------------ classification

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["tables"],
    "properties": {"tables": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["nodeId", "entity", "columns", "confidence", "reason"],
        "properties": {
            "nodeId": {"type": "string"},
            "entity": {"type": "string"},
            "columns": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["label", "field"],
                "properties": {"label": {"type": "string"}, "field": {"type": "string"}}}},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        }}}},
}

_SYSTEM = (
    "You read a table a designer drew and say which stored entity it lists "
    "and which field each column shows. Use only the entity and field names "
    "given; a column that matches no field is omitted. Give a confidence "
    "from 0 to 1 and a one-line reason. If no entity fits, return an empty "
    "entity with confidence 0."
)


def describe(table: DrawnTable) -> str:
    lines = [f"nodeId {table.node_id}" + (f' — in a card titled "{table.title}"' if table.title else ""),
             "  columns: " + " | ".join(table.headers)]
    for r in table.rows:
        lines.append("  row: " + " | ".join(r))
    return "\n".join(lines)


def classify_tables(ask: Callable[..., Any], tables: Sequence[DrawnTable],
                    entities: Sequence[dict]) -> list[dict]:
    """The realiser's classification entries for the tables the model could
    bind; registry-safe like the vision answer."""
    if not tables or not entities:
        return []
    from services.figma.vision import _entity_brief
    user = ("These tables were drawn on one screen.\n\n"
            + "\n\n".join(describe(t) for t in tables)
            + "\n\nThe application stores these entities. Field names are "
              "exact; copy them.\n\n" + _entity_brief(entities))
    try:
        raw = ask(system=_SYSTEM, user=user, schema=REPLY_SCHEMA)
        found = json.loads(getattr(raw, "text", raw)).get("tables") or []
    except Exception as exc:  # noqa: BLE001 — an enrichment
        logger.warning("[figma-tables] classification failed: %s", exc)
        return []
    by_id = {t.node_id: t for t in tables}
    by_name = {str(e.get("name") or ""): e for e in entities}
    out: list[dict] = []
    for entry in found:
        if not isinstance(entry, dict):
            continue
        table = by_id.get(str(entry.get("nodeId") or ""))
        entity = str(entry.get("entity") or "").strip()
        if table is None or entity not in by_name:
            continue
        known = {str(f.get("name") or "") for f in (by_name[entity].get("fields") or [])}
        columns, labels = [], {}
        for col in entry.get("columns") or []:
            fld = str((col or {}).get("field") or "")
            if fld in known and fld not in columns:
                columns.append(fld)
                labels[fld] = str(col.get("label") or "").strip() or fld
        if not columns:
            continue
        out.append({
            "nodeId": table.node_id, "kind": "table", "title": table.title,
            "confidence": float(entry.get("confidence") or 0.0),
            "reason": str(entry.get("reason") or "").strip(),
            "entity": entity, "xField": "", "valueField": "",
            "columns": columns, "columnLabels": labels,
            "hasRowAction": table.has_row_action,
        })
    return out


def detail_route_for_entity(doc: dict, entity_name: str) -> str | None:
    """The page that opens one record of this entity: `/cases/[id]`."""
    ents = (doc.get("data") or {}).get("entities") or []
    ent_id = next((e.get("id") for e in ents if e.get("name") == entity_name), None)
    candidates = [str(p.get("route") or "") for p in doc.get("pages") or []
                  if str(p.get("route") or "").endswith("/[id]")
                  and (p.get("data") or {}).get("primaryEntity") in (ent_id, entity_name)]
    if not candidates:
        return None
    # THE ENTITY'S OWN PAGE, NOT THE FIRST PAGE ABOUT IT. Several screens
    # open one case — the front desk's, the GM's review — and the first in
    # page order was the front desk. The route named after the entity is
    # the record's page; the others are somebody's view of it.
    stem = re.sub(r"[^a-z]", "", entity_name.lower())
    own = [r for r in candidates if stem and stem in re.sub(r"[^a-z]", "", r.split("/")[1].lower())]
    return (own or candidates)[0]


def row_link(route: str) -> str:
    """A route's `[id]` as the Table's row template `{{id}}` — the form the
    component fills from the row (`/orders/{{id}}` throughout the catalog)."""
    return route.replace("[id]", "{{id}}")

