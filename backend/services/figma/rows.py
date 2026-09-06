"""A drawn list, bound as drawn.

A designer draws a list as a few example rows: a time, a day, a title, a
room, a status chip — laid out the way the product should show them.
Realizing that region as a Table kept the data and threw the drawing away.
The rows are the drawing; the records are what changes. So the first drawn
row becomes the template of a `Repeat` over the entity's list source, its
text leaves bound to the record's fields, and the other example rows go.

WHICH LEAF IS WHICH FIELD IS A READING, NOT A RULE. "10:00 / الإثنين / 1
سبتمبر / جلسة لجنة المالية — الموازنة 2027 / قاعة المالية / لجنة" maps to
`startsAt` three times with three formats, then `title`, `location`,
`status`. Order in the code is not order on the screen (right-to-left,
two-line cells), and a caption can look like a field. The mapping is asked
of the model, with the leaves and the entity's fields, and a leaf it cannot
place stays the literal it was drawn as. A row it cannot map at all leaves
the region to the Table path.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

FORMATTERS = ("time", "date", "weekday", "number", "percent", "currency", "relative")

MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["leaves"],
    "properties": {
        "leaves": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "field"],
                "properties": {
                    "index": {"type": "integer"},
                    # "" when the leaf is a literal — a caption, a fixed label.
                    "field": {"type": "string"},
                    "formatter": {"type": "string", "enum": list(FORMATTERS) + [""]},
                },
            },
        }
    },
}

_SYSTEM = (
    "You bind the text of one drawn list row to the fields of a record.\n\n"
    "You are given the row's text leaves in document order, numbered, and the "
    "entity's fields with their types. For each leaf say which field it shows, "
    "copying the field name exactly, or \"\" when it is a fixed label or "
    "caption rather than a value. One field may be shown by several leaves — "
    "a timestamp drawn as a time, a weekday and a date is the same field "
    "three times with formatters `time`, `weekday` and `date`. Use a "
    "formatter only when the leaf's shape calls for one; leave it \"\" "
    "otherwise. Do not invent fields."
)


def _shape(node: Any) -> str:
    """A subtree's structure without its words: type, then children's shapes."""
    if not isinstance(node, dict):
        return ""
    kids = [c for c in node.get("children") or [] if isinstance(c, dict)]
    return node.get("type", "?") + "(" + ",".join(_shape(c) for c in kids) + ")"


def _leaves(node: Any, out: list[dict]) -> list[dict]:
    if isinstance(node, dict):
        props = node.get("props") or {}
        text = props.get("content") if node.get("type") in ("Text", "Heading") else None
        if isinstance(text, str) and text.strip():
            out.append(node)
        for c in node.get("children") or []:
            _leaves(c, out)
    return out


def row_blocks(region: dict) -> tuple[dict, list[dict]] | None:
    """The list container inside a region and its rows: the first run of two
    or more consecutive siblings that share a shape and carry text. Searched
    top-down, so the outermost list wins — the rows, not the cells in them."""
    if not isinstance(region, dict):
        return None
    kids = [c for c in region.get("children") or [] if isinstance(c, dict)]
    shapes = [_shape(c) for c in kids]
    for i, shape in enumerate(shapes):
        # A ROW IS A CONTAINER. Two labels side by side — a card's title and
        # its "view all" — share a shape too, and are one line, not a list.
        if not shape or kids[i].get("type") in ("Text", "Heading") or not kids[i].get("children"):
            continue
        if not _leaves(kids[i], []):
            continue
        run = [kids[i]]
        for j in range(i + 1, len(kids)):
            if shapes[j] == shape:
                run.append(kids[j])
            else:
                break
        if len(run) >= 2:
            return region, run
    for c in kids:
        found = row_blocks(c)
        if found:
            return found
    return None


def map_row(ask: Callable[..., str], leaves: Sequence[str], entity: dict) -> list[dict]:
    """``[{"index", "field", "formatter"}]`` for the leaves the model placed."""
    fields = [f for f in entity.get("fields") or [] if f.get("name")]
    if not leaves or not fields:
        return []
    user = (
        "The row's leaves, in document order:\n"
        + "\n".join(f"  {i}: {t}" for i, t in enumerate(leaves))
        + f"\n\nThe entity `{entity.get('name')}` has these fields:\n"
        + "\n".join(f"  {f['name']} ({f.get('type') or 'string'})" for f in fields)
        + "\n\nReturn one entry per leaf."
    )
    try:
        raw = ask(system=_SYSTEM, user=user, schema=MAP_SCHEMA)
        # A bare str or a `ModelReply` carrying usage, as the classifier reads it.
        data = json.loads(getattr(raw, "text", raw))
    except Exception as exc:  # noqa: BLE001 — a row that cannot be read is left drawn
        logger.info("[figma-rows] row mapping failed: %s", exc)
        return []
    known = {f["name"] for f in fields}
    out = []
    for item in (data or {}).get("leaves") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "")
        if field and field not in known:
            continue
        out.append({"index": int(item.get("index", -1)), "field": field,
                    "formatter": str(item.get("formatter") or "")})
    return out


def bind_rows(region: dict, rows: list[dict], mapping: Sequence[dict], *,
              source: str, as_name: str = "item", locale: str = "") -> dict | None:
    """The region with its list rows replaced by one Repeat over ``source``,
    whose template is the first row with its mapped leaves bound. None when
    nothing was mapped: a Repeat of literals would show one drawn row per
    record, which is worse than the drawing."""
    by_index = {m["index"]: m for m in mapping if m.get("field")}
    if not by_index:
        return None
    template = json.loads(json.dumps(rows[0]))
    leaves = _leaves(template, [])
    for i, leaf in enumerate(leaves):
        m = by_index.get(i)
        if not m:
            continue
        expr = f"{as_name}.{m['field']}"
        if m.get("formatter"):
            expr += "|" + m["formatter"]
            # A date is written in the application's language — the
            # Blueprint's `product.locale` — not the viewer's or the server's,
            # which differ and made React refuse to hydrate the page.
            if locale and m["formatter"] in ("time", "date", "weekday"):
                expr += ":" + locale
        props = dict(leaf.get("props") or {})
        props["content"] = "{{" + expr + "}}"
        leaf["props"] = props
    repeat = {"type": "Repeat", "props": {"source": source, "as": as_name}, "children": [template]}
    first = rows[0]
    out = dict(region)
    kids = []
    placed = False
    for c in region.get("children") or []:
        if c is first:
            kids.append(repeat)
            placed = True
        elif any(c is r for r in rows):
            continue
        else:
            kids.append(c)
    if not placed:
        return None
    out["children"] = kids
    return out
