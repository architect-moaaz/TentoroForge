"""The substance floor for dashboards — the one page kind nothing was checking.

Why this exists
---------------
``page_anatomy`` enforces a per-job UX floor, but only for jobs that
``page_signature`` can name, and that function returns ``None`` unless it can
attribute the page to an *entity*. A dashboard belongs to no single entity, so
every dashboard fell through the ``continue`` and was never judged at all.

Measured across the 223-app output corpus: of the 125 apps carrying a
dashboard, **15 shipped with zero KPI tiles and 43 with zero charts**. Two of
the thirty most recent (``zhebvtqk``, ``dxlc5m31``) ship a dashboard that is
chrome and nothing else. All of them passed every gate, because no gate had an
opinion.

The rules
---------
Three of them are about slots — a dashboard has to answer "how are we doing"
(KPIs), "how is it trending" (a chart), and "what just happened" (a recent
activity surface). The fourth is about legibility: a ``series`` grouped on a
foreign key renders one bar per UUID with UUID axis labels, and one grouped on
a free-text name renders one bar per row, which is a list drawn as a chart.
Seven of those shipped.

Slots are matched by the JOB a component does, not by one blessed component
name — ``Stat`` counts as a KPI, ``Gauge`` as a chart, ``ActivityFeed`` as
activity. Pinning the rule to a single type would just push authors toward
satisfying the letter of it.

Shape
-----
A pure predicate, deliberately: ``page_anatomy`` calls it to report, and
``delivery_gate`` calls it to block. One rule with two consumers, rather than
each re-deriving "what a dashboard needs" — which is exactly the drift this
codebase keeps paying for.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Three KPIs is the floor a scanning reader needs before a row reads as a
# summary rather than a stray number. Four is the common shipped shape.
KPI_FLOOR = 3

# Routes that serve the "how are we doing" job. Dashboards are named by route,
# never by entity — that is the whole reason they slipped the existing floor.
_DASHBOARD_ROUTES = {"/", "/home", "/dashboard", "/overview", "/index"}
_DASHBOARD_LEAF = re.compile(r"/(home|dashboard|overview)$")

_KPI_TYPES = frozenset({"MetricTile", "Stat", "KpiTile", "SplitArc"})
_CHART_TYPES = frozenset({"Chart", "Gauge", "Heatmap", "Sparkline", "Schematic"})
_ACTIVITY_TYPES = frozenset({
    "Table", "List", "Timeline", "ActivityFeed", "Kanban", "DescriptionList",
    "ResourceTimeline", "Calendar",
})

# Column names that read as free text even when the SQL type does not say so.
# Grouping on any of these produces one bucket per row.
_FREE_TEXT_HINTS = ("name", "title", "label", "description", "notes", "summary",
                    "comment", "address", "email", "phone", "slug", "code")

# SQL types that can never make a sane GROUP BY axis.
_UNGROUPABLE_TYPES = frozenset({"uuid", "json", "jsonb", "text"})


def is_dashboard_route(route: str) -> bool:
    """Whether `route` serves the dashboard job."""
    r = "/" + (route or "").strip("/")
    if r == "/":
        return True
    r = r.rstrip("/")
    return r in _DASHBOARD_ROUTES or bool(_DASHBOARD_LEAF.search(r))


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def page_root(doc: Any) -> dict | None:
    """The component tree of `doc`, across both schema shapes.

    v2 nests it under ``root``. An older shape — still on disk for 10 of the
    125 dashboards in the corpus — makes the page itself the root node, with
    ``type``/``props``/``children`` at the top level. Reading only ``root``
    silently scored those as flawless, which is the precise failure this
    module exists to stop.
    """
    if not isinstance(doc, dict):
        return None
    root = doc.get("root")
    if isinstance(root, dict):
        return root
    if isinstance(doc.get("children"), list) or doc.get("type"):
        return doc
    return None


def _types_present(root: dict) -> set[str]:
    return {str(n.get("type")) for n in _walk(root) if n.get("type")}


def _count_of(root: dict, kinds: frozenset[str]) -> int:
    return sum(1 for n in _walk(root) if str(n.get("type")) in kinds)


def _column(registry: Any, entity: str, name: str) -> dict | None:
    ents = ((registry or {}).get("entities") or {})
    cols = (ents.get(entity) or {}).get("columns") or []
    for c in cols:
        if isinstance(c, dict) and c.get("name") == name:
            return c
    return None


def _finding(rule: str, route: str, detail: str, slot: str,
             ref: str | None = None) -> dict:
    """`ref` names the dataSource the finding is about, when there is one.

    A caller that wants to salvage a page needs to know WHICH widget failed,
    and reading it back out of the prose is a parser waiting to break. The
    one caller that repairs (a2ui_authority) prunes on this field.
    """
    out = {
        "rule": rule,
        "route": route,
        "slot": slot,
        "severity": "error",
        "action": "reported",
        "detail": detail,
    }
    if ref:
        out["ref"] = ref
    return out


def dashboard_findings(route: str, doc: Any, registry: Any) -> list[dict]:
    """Substance violations for one dashboard. Empty list means it holds up.

    Non-dashboard routes always return ``[]`` — this module has no opinion
    about them, and pretending otherwise would double-judge pages that
    ``page_anatomy`` already covers.
    """
    if not is_dashboard_route(route):
        return []

    root = page_root(doc)
    if root is None:
        # A dashboard we cannot read is a finding, never silence. Returning []
        # here would report "clean" for a page nobody has actually checked —
        # the same shape of lie as a chart that renders zero bars.
        return [_finding(
            "dashboard_unreadable", route, slot="page",
            detail=("dashboard schema has no readable component tree (no "
                    "'root' and no top-level type/children) — it cannot be "
                    "checked, so it must not pass."),
        )]

    out: list[dict] = []
    present = _types_present(root)

    kpis = _count_of(root, _KPI_TYPES)
    if kpis < KPI_FLOOR:
        out.append(_finding(
            "dashboard_no_kpis", route, slot="kpis",
            detail=(f"dashboard has {kpis} KPI tile(s); the floor is "
                    f"{KPI_FLOOR}. A summary row is how a reader answers "
                    f"'how are we doing' without reading the tables."),
        ))

    if not (present & _CHART_TYPES):
        out.append(_finding(
            "dashboard_no_chart", route, slot="chart",
            detail=("dashboard has no chart. Counts alone cannot answer "
                    "'is this getting better or worse'."),
        ))

    if not (present & _ACTIVITY_TYPES):
        out.append(_finding(
            "dashboard_no_activity", route, slot="activity",
            detail=("dashboard has no recent-activity surface (table, list, "
                    "timeline or feed) — nothing answers 'what just "
                    "happened'."),
        ))

    out.extend(_groupby_findings(route, doc, registry))
    return out


def _groupby_findings(route: str, doc: dict, registry: Any) -> list[dict]:
    """Series whose GROUP BY column cannot make a readable axis."""
    out: list[dict] = []
    for src in doc.get("dataSources") or []:
        if not isinstance(src, dict) or src.get("op") != "series":
            continue
        col_name = src.get("groupBy")
        entity = src.get("entity")
        if not col_name or not entity:
            continue
        col = _column(registry, str(entity), str(col_name))
        # No registry entry means no basis for a verdict. A false positive
        # here teaches people to ignore the gate, which costs more than the
        # miss.
        if col is None:
            continue
        # An enum is the ideal axis; say so before anything else can veto it.
        if col.get("enum"):
            continue
        why = None
        if col.get("fk"):
            why = (f"'{col_name}' is a foreign key — the chart renders one bar "
                   f"per UUID with UUID axis labels")
        elif str(col.get("type", "")).lower() in _UNGROUPABLE_TYPES:
            why = (f"'{col_name}' is {col.get('type')} — not a groupable "
                   f"dimension")
        elif any(h in str(col_name).lower() for h in _FREE_TEXT_HINTS):
            why = (f"'{col_name}' is free text — the chart renders one bar per "
                   f"row, which is a list drawn as a chart")
        if why:
            out.append(_finding(
                "dashboard_groupby_unreadable", route, slot="chart",
                ref=str(src.get("name") or ""),
                detail=(f"dataSource '{src.get('name')}' groups by {why}. "
                        f"Group by a status/enum or a bucketed date instead."),
            ))
    return out
