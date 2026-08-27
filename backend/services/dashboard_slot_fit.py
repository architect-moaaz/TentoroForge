"""A widget's slot must fit what the widget actually holds.

The dashboard composer lays each section out as an equal-width Grid and then
drops widgets into the cells without asking what the cells need to hold. Two
things wreck a grid row, and opmk18qr /dashboard showed both:

  A wide table in a narrow cell **bleeds**. "Approvals Due Today" is a
  four-column table in a third of the page; the header renders as
  "AVG DURATION (DAY" and the Dates and Status columns are sliced off. The
  scroll box added earlier stops it widening the card, which is the right
  containment — but a column cut mid-word still reads as broken, and the
  honest fix is to stop putting a four-column table in a third of the width.

  An unbounded list in a cell **strands white space**. "Trends & Activity" is
  Chart | Gauge | ActivityFeed; the feed renders ten rows, roughly twice its
  neighbours' height, and a grid row is as tall as its tallest child. Two
  thirds of that row is empty.

Both follow from the same omission, so both are decided here: a grid row is as
wide as its narrowest column and as tall as its tallest child, and the layout
has to respect what it is being asked to carry.

This narrows and caps; it never widens a grid the author deliberately made
narrow, and never overrides a limit an author set.
"""

from __future__ import annotations

from typing import Any

# Widgets whose height grows with the row count. Beside anything else they
# decide the row's height, so they get capped.
_UNBOUNDED_LISTS = {"ActivityFeed", "List", "Timeline", "KeyValueList",
                    "DescriptionList", "Feed"}

# How many rows a capped list shows. Enough to read as a feed, short enough to
# sit beside a chart without towering over it.
_ROW_CAP = 5

# Columns a table needs before a third of the page stops being enough. Three
# columns fit; the live bleed started at three and was unreadable at four, so
# three is the threshold at which the grid must give it more room.
_WIDE_TABLE_COLUMNS = 3

_TABULAR = {"Table", "DataGrid"}


def widget_min_columns(node: dict) -> int:
    """How many of the grid's columns this widget needs to render honestly.

    1 means "a single cell is fine". 2 means "give it at least half".
    """
    if not isinstance(node, dict):
        return 1
    if node.get("type") not in _TABULAR:
        return 1
    cols = (node.get("props") or {}).get("columns")
    n = len(cols) if isinstance(cols, list) else 0
    return 2 if n >= _WIDE_TABLE_COLUMNS else 1


def columns_that_fit(declared: int, widgets: list[dict]) -> int:
    """The column count this row can actually use.

    Only ever narrows: an author who asked for a single column meant it.
    """
    try:
        declared = int(declared)
    except (TypeError, ValueError):
        return 1
    if declared <= 1:
        return max(1, declared)
    need = max((widget_min_columns(w) for w in widgets), default=1)
    if need <= 1:
        return declared
    # `need` is a share of the row, not a divisor. A widget wanting half the
    # width caps the row at two columns; one wanting the whole row caps it at
    # one. (Dividing instead — 3 // 2 — would collapse a two-up row to one and
    # waste half the page.)
    cap = 1 if need >= 3 else 2
    return max(1, min(declared, cap))


def row_cap_for(node: dict, columns: int) -> int | None:
    """The row limit this widget needs, or None to leave it alone."""
    if not isinstance(node, dict) or node.get("type") not in _UNBOUNDED_LISTS:
        return None
    if columns <= 1:
        return None            # full width: nothing beside it to strand
    props = node.get("props") or {}
    for declared in ("limit", "maxRows", "pageSize"):
        if props.get(declared) is not None:
            return None        # the author already decided
    return _ROW_CAP


def _widgets_under(node: Any, out: list[dict]) -> None:
    """The leaf widgets in one grid cell (a Card usually wraps them)."""
    if isinstance(node, dict):
        if node.get("type") not in {"Card", "Stack", "Section", "Row", "Grid"}:
            out.append(node)
        for c in (node.get("children") or []):
            _widgets_under(c, out)
    elif isinstance(node, list):
        for c in node:
            _widgets_under(c, out)


def fit_dashboard_slots(page: dict) -> dict[str, Any]:
    """Narrow over-packed grids and cap towering lists. Mutates `page`."""
    notes: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for c in node:
                visit(c)
            return
        if not isinstance(node, dict):
            return

        if node.get("type") == "Grid":
            props = node.setdefault("props", {})
            declared = props.get("columns")
            cells = node.get("children") or []
            widgets: list[dict] = []
            for cell in cells:
                _widgets_under(cell, widgets)

            if isinstance(declared, int):
                fitted = columns_that_fit(declared, widgets)
                if fitted != declared:
                    props["columns"] = fitted
                    wide = [w.get("type") for w in widgets
                            if widget_min_columns(w) > 1]
                    notes.append(
                        f"grid {declared}->{fitted} columns: "
                        f"{', '.join(wide)} needs more than 1/{declared} width")
                    declared = fitted

            effective = declared if isinstance(declared, int) else len(cells)
            for w in widgets:
                cap = row_cap_for(w, effective)
                if cap is not None:
                    w.setdefault("props", {})["limit"] = cap
                    notes.append(
                        f"{w.get('type')} capped at {cap} rows — it sat beside "
                        f"{effective - 1} other widget(s) and set the row height")

        for c in (node.get("children") or []):
            visit(c)

    visit(page.get("root"))
    return {"changed": len(notes), "notes": notes}
