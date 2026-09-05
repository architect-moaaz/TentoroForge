"""Turn a picture of a chart into a chart.

`vision.classify` says a rectangle is a bar chart of `Record.amount` over
`Record.occurredAt`, with 0.93 confidence and a title read off the drawing.
This is the step that acts on that: the Image subtree is replaced by a `Chart`
node bound to a real `dataSources` entry, so the page stops being a photograph
of a dashboard and starts being one.

WHAT IS EXCHANGED, AND WHY IT IS A FAIR TRADE. The drawn chart is exact and
dead: it shows the numbers the designer typed, forever. The generated chart is
live and approximate: it shows this application's data, in the shape the design
asked for, and it will look slightly different because real data is not sample
data. Only the second one is an application. That is the whole trade, and it is
worth making only where the classification is confident and the binding
resolves — everywhere else the drawing stays, which is why an unreplaced region
is a normal outcome and not a failure.

WHY CONFIDENCE GATES IT (§17). A wrong replacement is worse than no
replacement: it removes something correct and puts something wrong in its
place, and it looks deliberate. Below the threshold the drawing survives and
the classification is still recorded, so a person can see what was considered
and disagree.

NESTED REGIONS RESOLVE BY CONTAINMENT, NOT BY ARGUMENT. `regions` deliberately
emits a card and the chart inside it, and one real frame produced three
identically-sized wrappers for the same table. Replacing the outermost first
and skipping anything inside it needs no rule about which was "the" region: the
subtree is gone, so its children are no longer there to replace.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.figma.vision import ACTIONABLE

logger = logging.getLogger(__name__)

#: §17's RECORD_ASSUMPTION band. Below this the drawing is kept.
MIN_CONFIDENCE = 0.70

_CHART_KIND = {
    "bar_chart": "bar",
    "line_chart": "line",
    "area_chart": "area",
    "pie_chart": "pie",
    "donut_chart": "donut",
}


def _source_name(title: str, entity: str, node_id: str) -> str:
    """A stable, readable name for the dataSource this region needs.

    Derived from the title the model read off the drawing — "Total Product
    Sales" becomes `totalProductSales` — because that is the only human name
    this design has anywhere. Falls back to the node id, which is unique but
    says nothing.
    """
    base = re.sub(r"[^a-zA-Z0-9]+", " ", title or "").strip()
    if not base:
        base = f"{entity} {node_id}"
    parts = base.split()
    head = parts[0].lower()
    return head + "".join(p.capitalize() for p in parts[1:])


def _label_for(field: str) -> str:
    """`occurredAt` → `Occurred At`. Column headers are read by people."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", field.replace("_", " "))
    return spaced[:1].upper() + spaced[1:]


def _chart(entry: dict, source: str) -> dict:
    series_name = entry.get("valueField") or "value"
    return {
        "type": "Chart",
        "props": {
            "chartType": _CHART_KIND[entry["kind"]],
            "data": f"{{{{{source}}}}}",
            "xKey": "label",
            "series": [{"dataKey": "value", "name": _label_for(series_name)}],
            "height": 260,
            "showGrid": entry["kind"] not in ("pie_chart", "donut_chart"),
            "showLegend": True,
            "showTooltip": True,
            **({"title": entry["title"]} if entry.get("title") else {}),
        },
        "children": [],
    }


def _table(entry: dict, source: str) -> dict:
    columns = [{"key": c, "label": _label_for(c)} for c in entry["columns"]]
    return {
        "type": "Table",
        "props": {
            "columns": columns,
            "data": f"{{{{{source}}}}}",
            **({"title": entry["title"]} if entry.get("title") else {}),
        },
        "children": [],
    }


def _series_source(entry: dict, name: str) -> dict:
    """`op: series` — grouped counts or sums, the shape a Chart's xKey/series
    expects. `agg.field` is only meaningful for a sum, so it is omitted for the
    count that a chart without a value field asks for."""
    agg: dict[str, Any] = ({"fn": "sum", "field": entry["valueField"]}
                           if entry.get("valueField") else {"fn": "count"})
    return {"name": name, "op": "series", "entity": entry["entity"],
            "groupBy": entry["xField"], "agg": agg}


def _list_source(entry: dict, name: str) -> dict:
    return {"name": name, "op": "list", "entity": entry["entity"], "limit": 25}


def _bindable(entry: dict) -> bool:
    """Whether this classification has everything a live component needs.

    A chart needs something to group by; a table needs columns to show. A
    verdict missing either is a real observation about the drawing and a
    useless instruction to a component, so it stops here rather than producing
    an empty widget that reads as a data outage.
    """
    if entry.get("kind") not in ACTIONABLE or not entry.get("entity"):
        return False
    if entry["kind"] in _CHART_KIND:
        return bool(entry.get("xField"))
    if entry["kind"] == "table":
        return bool(entry.get("columns"))
    return False


def _replace(node: Any, wanted: dict[str, dict], done: set[str]) -> Any:
    """Rebuild the tree, swapping any node whose Figma id was classified.

    Returns the node, replaced or not. Descends only into nodes it did NOT
    replace, so a region inside a replaced region is never visited — which is
    how the card/chart and the three-identical-wrappers cases resolve without a
    containment rule.
    """
    if not isinstance(node, dict):
        return node

    node_id = str((node.get("props") or {}).get("_figmaNodeId") or "")
    entry = wanted.get(node_id)
    if entry is not None and node_id not in done:
        done.add(node_id)
        return entry["_node"]

    children = node.get("children")
    if isinstance(children, list):
        node["children"] = [_replace(c, wanted, done) for c in children]
    return node


def realize(root: dict, classifications: list[dict], *,
            min_confidence: float = MIN_CONFIDENCE) -> tuple[dict, list[dict], list[dict]]:
    """Apply the confident, bindable classifications to ``root``.

    Returns ``(root, dataSources, applied)``. ``applied`` is what changed, for
    the Blueprint to record — a design decision nobody can see is a design
    decision nobody can correct.
    """
    if not classifications:
        return root, [], []

    # Largest first is already `regions`' order and is the order that makes
    # containment work: an outer card is replaced before anything inside it is
    # considered, and `_replace` then never descends into it.
    ordered = [c for c in classifications
               if _bindable(c) and c.get("confidence", 0) >= min_confidence]

    wanted: dict[str, dict] = {}
    sources: list[dict] = []
    applied: list[dict] = []
    used: set[str] = set()

    for entry in ordered:
        name = _source_name(entry.get("title", ""), entry["entity"],
                            entry["nodeId"])
        # Two regions reading the same title — three wrappers around one table
        # on a real frame — must not declare the same source twice.
        suffix = 2
        while name in used:
            name, suffix = f"{name}{suffix}", suffix + 1
        used.add(name)

        if entry["kind"] in _CHART_KIND:
            component, source = _chart(entry, name), _series_source(entry, name)
        else:
            component, source = _table(entry, name), _list_source(entry, name)

        wanted[entry["nodeId"]] = {**entry, "_node": component}
        sources.append(source)
        applied.append({"nodeId": entry["nodeId"], "kind": entry["kind"],
                        "entity": entry["entity"], "source": name,
                        "confidence": entry.get("confidence", 0.0),
                        "title": entry.get("title", "")})

    done: set[str] = set()
    root = _replace(root, wanted, done)

    # A source whose region was never found would bind nothing. That happens
    # when a classified wrapper sat inside another that was replaced first —
    # correct, and its source has to go with it.
    kept = {wanted[n]["_node"] is not None and n in done for n in wanted}
    if not all(kept):
        live = {a["nodeId"] for a in applied if a["nodeId"] in done}
        sources = [s for s, a in zip(sources, applied) if a["nodeId"] in live]
        applied = [a for a in applied if a["nodeId"] in live]

    logger.info("[figma-realize] replaced %d region(s) with live components",
                len(applied))
    return root, sources, applied
