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

import json
import logging
import re
from typing import Callable, Sequence, Any

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
        # THE FALLBACK IS SANITISED TOO. A title in Arabic strips to nothing,
        # the entity + node id took over, and the node id's colon went into
        # the name: `member1:205`. The renderer reads a colon in a template
        # as the start of a format modifier, so `{{member1:205.value}}` was
        # never resolved and the card showed its own template.
        base = re.sub(r"[^a-zA-Z0-9]+", " ", f"{entity} {node_id}").strip()
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
    # The labels the designer wrote head the columns when they are known
    # ("Case No", not "Case Number"); a row link makes each row the "View →"
    # the designer drew beside it.
    labels = entry.get("columnLabels") or {}
    columns = [{"key": c, "label": labels.get(c) or _label_for(c)} for c in entry["columns"]]
    return {
        "type": "Table",
        "props": {
            "columns": columns,
            "data": f"{{{{{source}}}}}",
            **({"title": entry["title"]} if entry.get("title") else {}),
            **({"rowHref": entry["rowHref"]} if entry.get("rowHref") else {}),
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


def _metric(entry: dict, source: str) -> dict:
    """The drawn number as a live Stat: the card's title is its label, the
    value is the aggregate the source computes."""
    return {"type": "Stat", "props": {"label": entry.get("title") or _label_for(entry["entity"]),
                                       "value": f"{{{{{source}.value}}}}"}}


def _metric_source(entry: dict, name: str) -> dict:
    fn = entry.get("fn") or "count"
    metric: dict = {"fn": fn}
    if fn != "count" and entry.get("valueField"):
        metric["field"] = entry["valueField"]
    return {"name": name, "op": "aggregate", "entity": entry["entity"], "metrics": {"value": metric}}


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
    if entry["kind"] == "metric":
        # A count needs only its entity; a sum or average needs the field.
        fn = entry.get("fn") or "count"
        return fn == "count" or bool(entry.get("valueField"))
    return False


# Western or Arabic-Indic digits; ASCII or Arabic decimal (U+066B) and
# thousands (U+066C) separators; an optional percent sign of either script.
_NUMBER_RE = re.compile(r"^\s*[\d\u0660-\u0669][\d\u0660-\u0669,.\u066b\u066c\s]*\s*[%\u066a]?\s*$")


def _bind_number(node: dict, template: str) -> dict | None:
    """The drawn tile with only its number replaced.

    A metric tile is a fill, an icon, a label, a number and a caption; the
    number is the one thing the data layer computes. Replacing the whole
    tile with a Stat component threw away everything the designer drew
    around it. The first text leaf that is only a number — Western or Arabic
    digits, a separator, a percent sign — becomes the template; the rest of
    the tile is returned as drawn. None when the tile draws no number.
    """
    found = False

    def walk(n: Any) -> Any:
        nonlocal found
        if not isinstance(n, dict):
            return n
        out = dict(n)
        props = dict(n.get("props") or {})
        text = props.get("content")
        if (not found and n.get("type") in ("Heading", "Text")
                and isinstance(text, str) and _NUMBER_RE.match(text)):
            found = True
            props["content"] = template
            out["props"] = props
            return out
        kids = n.get("children")
        if isinstance(kids, list):
            out["children"] = [walk(c) for c in kids]
        return out

    bound = walk(node)
    return bound if found else None


def _swap(root: Any, target: dict, replacement: dict) -> Any:
    """The tree with one subtree (by identity) replaced."""
    if root is target:
        return replacement
    if not isinstance(root, dict):
        return root
    out = dict(root)
    kids = root.get("children")
    if isinstance(kids, list):
        out["children"] = [_swap(c, target, replacement) for c in kids]
    return out


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
        if entry.get("_bind"):
            bound = _bind_number(node, entry["_bind"])
            if bound is not None:
                return bound
        if entry.get("_rows"):
            # A DRAWN LIST STAYS DRAWN. Its example rows become one Repeat
            # over the entity's list source, the first row as the template
            # with its leaves bound; the Table is what a region with no
            # readable rows becomes.
            from services.figma import rows as _rows
            source, mapper = entry["_rows"]
            try:
                found = _rows.row_blocks(node)
                if found:
                    container, drawn = found
                    leaves = [str((leaf.get("props") or {}).get("content") or "")
                              for leaf in _rows._leaves(drawn[0], [])]
                    mapping = mapper(leaves, entry["entity"])
                    bound_list = _rows.bind_rows(container, drawn, mapping, source=source)
                    if bound_list is not None:
                        return _swap(node, container, bound_list)
            except Exception as exc:  # noqa: BLE001 — a row that cannot be read leaves the Table
                logger.info("[figma-realize] rows of %s not bound: %s", node_id, exc)
        return entry["_node"]

    children = node.get("children")
    if isinstance(children, list):
        node["children"] = [_replace(c, wanted, done) for c in children]
    return node


def realize(root: dict, classifications: list[dict], *,
            min_confidence: float = MIN_CONFIDENCE,
            row_mapper: Callable[[Sequence[str], str], Sequence[dict]] | None = None,
            ) -> tuple[dict, list[dict], list[dict]]:
    """Apply the confident, bindable classifications to ``root``.

    Returns ``(root, dataSources, applied)``. ``applied`` is what changed, for
    the Blueprint to record — a design decision nobody can see is a design
    decision nobody can correct.
    """
    if not classifications:
        return root, [], []
    # THE INPUT IS NOT TOUCHED. `_replace` rebuilds nodes as it goes, but it
    # rebuilt them into the caller's tree; a failure halfway — a row mapper
    # raising after the metric tiles were rewritten — left the page binding
    # sources this function never returned, and the page was refused.
    root = json.loads(json.dumps(root))

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
        elif entry["kind"] == "metric":
            component, source = _metric(entry, name), _metric_source(entry, name)
        else:
            component, source = _table(entry, name), _list_source(entry, name)

        wanted[entry["nodeId"]] = {**entry, "_node": component,
                                   "_bind": f"{{{{{name}.value}}}}" if entry["kind"] == "metric" else None,
                                   "_rows": (name, row_mapper) if entry["kind"] == "table" and row_mapper else None}
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
    kept = {n in done for n in wanted}
    if not all(kept):
        live = {a["nodeId"] for a in applied if a["nodeId"] in done}
        sources = [s for s, a in zip(sources, applied) if a["nodeId"] in live]
        applied = [a for a in applied if a["nodeId"] in live]

    logger.info("[figma-realize] replaced %d region(s) with live components",
                len(applied))
    return root, sources, applied
