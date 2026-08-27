"""Curated correct-shape examples for LLM composers.

Why this exists — the library manifest tells composers WHICH component names
exist, but the composer's LLM has to guess prop SHAPES from names alone.
That guessing gets shape-heavy components (Table columns, FilterBar chips,
Cascader options, Chart series) wrong in high-visibility ways:

- ``FilterBar chips: [{label:"Vinyasa", value:"vinyasa"}]`` degrades because
  each chip is meant to be a filter DIMENSION with its own options list;
  the library renders every chip as ``label: Any ▾`` and the ``Any`` never
  resolves. Result: "Vinyasa: Any ▾" "Yin: Any ▾" — reads as broken.
- ``Table columns: [{key, header, ...}]`` fails zod because ColumnDef
  requires ``label`` not ``header``. The `<th>` falls back to raw
  UPPERCASED key text ("INSTRUCTORID").
- ``Cascader binding: "{{items}}"`` — Cascader wants an ``options`` tree,
  not a flat binding. Renders as an empty box.

The fix is at the source: hand the composer a compact correct example per
shape-heavy component. The LLM copies the shape verbatim instead of
inventing one. Cheap in tokens (~600-1000 for the whole examples table),
prevents a whole class of "composer emitted a broken widget" bugs.

Coverage philosophy: only add an example for components whose prop shape
is non-obvious from the name. String/scalar props (``label``, ``variant``,
``placeholder``) don't need examples — the LLM gets those right. Array-
of-object props and tree/nested props are the pain points.
"""
from __future__ import annotations
from typing import Any


# Each entry is the **props** subtree only (not the full node envelope).
# Kept minimal — one realistic instance of every prop that has non-scalar
# shape. Bindings use ``{{dataSourceName}}`` where the composer would
# substitute a real dataSource name from the plan.
COMPONENT_EXAMPLES: dict[str, dict[str, Any]] = {
    # ── Data + list ──────────────────────────────────────────────────
    "Table": {
        "dataSource": "items",
        "rowKey": "id",
        "columns": [
            {"key": "name", "label": "Name", "width": "40%"},
            {"key": "status", "label": "Status", "format": "badge"},
            {"key": "createdAt", "label": "Created", "format": "date"},
        ],
        "emptyDescription": "No items yet.",
        "rowActions": [
            {"label": "Open", "navigate": "/items/{id}"},
        ],
    },
    "DataGrid": {
        "dataSource": "rows",
        "columns": [{"key": "name", "label": "Name"}, {"key": "email", "label": "Email"}],
    },
    "List": {
        "dataSource": "items",
        "itemKey": "id",
        "primary": "{{item.name}}",
        "secondary": "{{item.description}}",
    },
    "DescriptionList": {
        "orientation": "horizontal",
        "items": [
            {"label": "Plan", "value": "{{record.planName}}"},
            {"label": "Status", "value": "{{record.status}}"},
            {"label": "Renews", "value": "{{record.renewsAt}}"},
        ],
    },
    "Kanban": {
        "dataSource": "cards",
        "groupBy": "status",
        "columns": [
            {"key": "todo", "label": "To do"},
            {"key": "doing", "label": "Doing"},
            {"key": "done", "label": "Done"},
        ],
    },
    "Timeline": {
        "dataSource": "events",
        "titleKey": "title",
        "timeKey": "occurredAt",
        "descriptionKey": "description",
    },
    "ActivityFeed": {
        "dataSource": "activity",
        "titleKey": "actor",
        "descriptionKey": "action",
        "timeKey": "createdAt",
    },
    # ── Filter + selection ───────────────────────────────────────────
    "FilterBar": {
        # Each chip is a filter DIMENSION with its own options list. The
        # library renders as `<label>: <current-value> ▾`. Do NOT flatten
        # a list of quick-filter tags into chips — use SegmentedControl
        # or Cluster+Tag for that pattern.
        "showSearch": True,
        "chips": [
            {
                "key": "status",
                "label": "Status",
                "options": [
                    {"value": "active", "label": "Active"},
                    {"value": "archived", "label": "Archived"},
                ],
            },
            {
                "key": "role",
                "label": "Role",
                "options": [
                    {"value": "admin", "label": "Admin"},
                    {"value": "member", "label": "Member"},
                ],
            },
        ],
    },
    "SegmentedControl": {
        # For "one-of-N quick-toggle" filters (Upcoming | Past | Cancelled)
        # this is what you want — not FilterBar with 3 chips.
        "value": "upcoming",
        "options": [
            {"value": "upcoming", "label": "Upcoming"},
            {"value": "past", "label": "Past"},
            {"value": "cancelled", "label": "Cancelled"},
        ],
    },
    "Cascader": {
        # Cascader needs an OPTIONS TREE, not a flat binding. When the
        # data lives in a dataSource, still pre-shape it into the tree
        # form via a client-side derived source; do NOT pass a plain
        # `binding: "{{items}}"` — the widget renders empty.
        "options": [
            {
                "value": "engineering",
                "label": "Engineering",
                "children": [
                    {"value": "frontend", "label": "Frontend"},
                    {"value": "backend", "label": "Backend"},
                ],
            },
            {"value": "design", "label": "Design"},
        ],
        "value": "engineering/frontend",
    },
    "TreeSelect": {
        "options": [
            {"value": "root", "label": "Root", "children": [
                {"value": "child", "label": "Child"},
            ]},
        ],
    },
    "Tree": {
        "nodes": [
            {"id": "1", "label": "Root", "children": [{"id": "1.1", "label": "Child"}]},
        ],
    },
    "Select": {
        "value": "{{form.status}}",
        "placeholder": "Choose a status",
        "options": [
            {"value": "active", "label": "Active"},
            {"value": "archived", "label": "Archived"},
        ],
    },
    "RadioGroup": {
        "value": "{{form.plan}}",
        "options": [
            {"value": "monthly", "label": "Monthly"},
            {"value": "yearly", "label": "Yearly"},
        ],
    },
    "Combobox": {
        "value": "{{form.tag}}",
        "options": [
            {"value": "urgent", "label": "Urgent"},
            {"value": "normal", "label": "Normal"},
        ],
    },
    # ── Metrics + charts ─────────────────────────────────────────────
    "MetricTile": {
        # For a real data-bound metric, `value` is a binding string; the
        # library formats via the `format` prop, not by wrapping in {{}}.
        "label": "Revenue",
        "value": "{{stats.revenue}}",
        "format": "currency",
        "hint": "This month",
    },
    "Chart": {
        # Prefer op:"series" dataSources so the runtime returns
        # [{label, value}] pre-shaped — Chart binds via dataSource, not
        # by hard-coding numbers.
        "chartType": "bar",
        "dataSource": "revenueByMonth",
        "xKey": "label",
        "yKey": "value",
    },
    "Gauge": {
        "value": "{{stats.utilization}}",
        "min": 0,
        "max": 100,
        "format": "percent",
    },
    # ── Layout dimensioning ──────────────────────────────────────────
    "Split": {
        # ratio "2:1" makes the second child a narrow context rail.
        # Both children must be authored — an empty second child
        # renders as a blank vertical band next to the primary.
        "ratio": "2:1",
        "breakpoint": "lg",
    },
    "Grid": {
        "columns": 3,
        "gap": "md",
    },
    # ── Forms ────────────────────────────────────────────────────────
    "Form": {
        # Composer authors the Form envelope; inputs go inside as
        # children. `workflow` names the workflow that runs on submit.
        "workflow": "CreateItem",
        "submitLabel": "Create",
    },
    "KeyValueInput": {
        "value": {"key1": "value1"},
        "placeholder": "Add key/value pair",
    },
    # ── Conditional / repetition ─────────────────────────────────────
    "Conditional": {
        # `when` is a truthy-check on a binding. First child renders
        # when truthy, second when falsy. Do NOT pair a Table (with
        # its own empty state) with an EmptyStateRich second child —
        # they'll both show, one from Table's built-in empty and one
        # from Conditional's else branch. Use ONE data-rendering
        # component per Conditional branch.
        "when": "{{items.length}}",
    },
    "Repeat": {
        # For one bound list, use EITHER a Table OR a Repeat, never
        # both — they render the same rows twice.
        #
        # `source` is the prop the renderer reads. This example taught
        # `dataSource`, which it does not read, and 18 corpus nodes copied it
        # into an empty list.
        "as": "item",
        "source": "items",
    },
    # ── Empty state ──────────────────────────────────────────────────
    "EmptyStateRich": {
        "heading": "No items yet",
        "body": "Create your first item to get started.",
        "icon": "plus",
        "action": {"label": "Create item", "navigate": "/items/new"},
    },
}


def example_for(component_name: str) -> dict[str, Any] | None:
    """Return the curated shape example for a component, or None."""
    return COMPONENT_EXAMPLES.get(component_name)


__all__ = ["COMPONENT_EXAMPLES", "example_for"]
