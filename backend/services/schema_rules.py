"""Rules-as-data for the schema prompt.

build_schema_prompt() consumes this catalogue and emits each rule
followed immediately by its example_snippet and a scope hint, so the
LLM encounters each binding rule in close proximity to a correct
example and the entity context the rule applies to.

Each Rule has:
  - name           : kebab-case identifier (also used for opt-out via
                     SCHEMA_RULES_DISABLED env var)
  - body           : the rule itself in plain language
  - example_snippet: a short (≤ 15 lines) JSON snippet illustrating
                     the rule in action
  - applies_when   : predicate (entity_dict, page_type) -> bool — gates
                     whether the rule is emitted for this prompt

Scope helpers (_always, _on_list, _on_form, _on_detail) keep the
predicate set small and consistent across rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Rule:
    name: str
    body: str
    example_snippet: str
    applies_when: Callable[[dict, str], bool]


# ---------------------------------------------------------------------------
# Scope predicates — keep these small and named so rules read fluently.
# ---------------------------------------------------------------------------
def _always(entity: dict, page_type: str) -> bool:
    return True


def _on_list(entity: dict, page_type: str) -> bool:
    return page_type == "list"


def _on_form(entity: dict, page_type: str) -> bool:
    return page_type == "form"


def _on_detail(entity: dict, page_type: str) -> bool:
    return page_type == "detail"


def _on_dashboard(entity: dict, page_type: str) -> bool:
    return page_type == "dashboard"


# ---------------------------------------------------------------------------
# Rule catalogue — each entry is one "binding rule" the schema LLM must
# follow, paired with a single-shot example demonstrating it.
# Examples are kept ≤ 15 lines each so the rule + example block stays
# short enough that the proximity training signal is strong.
# ---------------------------------------------------------------------------
RULES: list[Rule] = [
    Rule(
        name="no-generator-tells",
        body=(
            "Copy discipline — these read as machine output and are BANNED: "
            "(1) mechanically singularized series names ('Matche', 'Statu') — "
            "use the entity's real display name or the metric name; "
            "(2) reusing the SAME image seed/URL on multiple pages — every "
            "hero/photo url must embed this page's slug in its seed; "
            "(3) a titled ActivityFeed nested inside a titled Card (double "
            "header) — give the Card no title OR pass title to the feed only; "
            "(4) do NOT end every dashboard with an info-tip callout."
        ),
        example_snippet="""{
  "type": "Chart",
  "props": { "series": [ { "name": "Matches", "dataKey": "value" } ] }
}""",
        applies_when=_always,
    ),
    Rule(
        name="vary-chart-shapes",
        body=(
            "Chart variety: do NOT default the second chart to a donut. "
            "Choose chart types from what the DATA wants — time series -> "
            "area/line, categorical comparison -> bar (horizontal when labels "
            "are long), part-of-whole with <=5 slices -> donut, distribution "
            "-> bar. Two charts on one page must use two different types."
        ),
        example_snippet="""{
  "type": "Chart",
  "props": { "chartType": "bar", "showLegend": false }
}""",
        applies_when=_on_dashboard,
    ),
    Rule(
        name="metric-tile-for-stats",
        body=(
            "Prefer MetricTile over plain Stat layouts. MetricTile expresses "
            "label + numeric value + optional delta + icon with consistent "
            "rhythm and respects importance: primary/secondary/tertiary. "
            "Include `delta` ONLY when the dataSource actually provides a "
            "comparison value — NEVER invent a hardcoded delta (fabricated "
            "'+12%' arrows on every tile are an instant credibility kill). "
            "A tile with no comparison simply omits delta."
        ),
        example_snippet="""{
  "type": "MetricTile",
  "props": {
    "label": "Open tasks",
    "value": "{{stats.openCount}}",
    "format": "number",
    "importance": "primary",
    "delta": { "direction": "up", "value": 0.12 }
  }
}""",
        applies_when=_on_list,
    ),
    Rule(
        name="button-icon-only-aria",
        body=(
            "Icon-only Buttons MUST set aria-label so screen readers can "
            "announce them. If a Button has `icon` set and no `label`, "
            "an `aria-label` prop is required."
        ),
        example_snippet="""{
  "type": "Button",
  "props": {
    "icon": "more-horizontal",
    "aria-label": "More actions"
  }
}""",
        applies_when=_always,
    ),
    Rule(
        name="repeat-for-collections",
        body=(
            "When iterating over a collection from dataSources (table rows, "
            "card grids, recent items), wrap children in a `Repeat` node "
            "with `bind` pointing at the dataSource name. Each iteration "
            "scopes `item` to the current row, so children reference "
            "`{{item.field}}` — never copy-paste static rows."
        ),
        example_snippet="""{
  "type": "Repeat",
  "bind": "recentRequests",
  "children": [
    { "type": "Card", "children": [
      { "type": "Heading", "props": { "content": "{{item.employee.name}}" } },
      { "type": "Badge",   "props": { "content": "{{item.status}}" } }
    ]}
  ]
}""",
        applies_when=_on_list,
    ),
    Rule(
        name="form-fields-required-name",
        body=(
            "Every Input / Select / Textarea / Checkbox / DatePicker MUST "
            "set a `name` prop matching a field on the bound entity. The "
            "name drives form state, validation, and workflow submission."
        ),
        example_snippet="""{
  "type": "Form",
  "children": [
    { "type": "Input",  "props": { "name": "email",    "label": "Email",    "type": "email" } },
    { "type": "Select", "props": { "name": "role",     "label": "Role",
                                     "options": [
                                       { "value": "admin",  "label": "Admin" },
                                       { "value": "member", "label": "Member" }
                                     ] } }
  ]
}""",
        applies_when=_on_form,
    ),
    Rule(
        name="form-declarative-default",
        body=(
            "For standard CRUD forms, use declarative Form: pass `workflow` + "
            "`fields` array as props and omit children. Each field must have "
            "`kind` (\"text\"|\"email\"|\"number\"|\"textarea\"|\"select\"|\"checkbox\"|\"date\"), "
            "`name`, and `label`. Use container mode (empty props + child "
            "Inputs) ONLY when the layout cannot be expressed declaratively "
            "(multi-column grids, conditional fields, grouped Accordion sections)."
        ),
        example_snippet="""{
  "type": "Form",
  "props": {
    "workflow": "createNote",
    "submitLabel": "Save",
    "fields": [
      { "kind": "text",     "name": "title", "label": "Title", "required": true },
      { "kind": "textarea", "name": "body",  "label": "Body",  "rows": 6 }
    ]
  }
}""",
        applies_when=_on_form,
    ),
    Rule(
        name="binding-double-mustache",
        body=(
            "Bind dynamic per-record values with `{{entity.field}}` syntax. "
            "Never inline literal entity-specific values (names, dates, "
            "statuses) and never use other template syntaxes (`<%= %>`, "
            "`${...}`, `{field}`). The runtime resolves `{{...}}` against "
            "the page's dataSources at render time."
        ),
        example_snippet="""{
  "type": "Heading",
  "props": { "content": "{{employee.name}} — {{employee.department}}" }
}""",
        applies_when=_always,
    ),
    Rule(
        name="hero-on-list",
        body=(
            "List pages should open with a Hero (role: \"inline\" is the "
            "common choice for list pages) containing the entity collection "
            "name and the primary CTA for creating a new record. This "
            "anchors the page identity above the data table."
        ),
        example_snippet="""{
  "type": "Hero",
  "props": {
    "role": "inline",
    "headline": "Tasks",
    "ctas": [
      { "label": "New task", "action": { "type": "navigate", "to": "/tasks/new" }, "variant": "primary" }
    ]
  }
}""",
        applies_when=_on_list,
    ),
    Rule(
        name="detail-key-value-list",
        body=(
            "Detail pages should surface the entity's scalar fields via "
            "`KeyValueList` (label + value pairs) inside a Card, rather "
            "than a freeform Stack of Text nodes. This keeps spacing and "
            "alignment consistent and lets the runtime render copyable "
            "values where helpful."
        ),
        example_snippet="""{
  "type": "Card",
  "children": [
    { "type": "KeyValueList",
      "props": {
        "items": [
          { "label": "Owner",  "value": "{{record.owner.name}}" },
          { "label": "Status", "value": "{{record.status}}" }
        ]
      }
    }
  ]
}""",
        applies_when=_on_detail,
    ),
    Rule(
        name="auth-page-illustration",
        body=(
            "Login / signup pages should use a 2-column split layout: form on "
            "one side, illustration on the other. Call list_illustrations(tags=["
            "'auth', 'login', '<domain>']) via the illustrations MCP to find a "
            "matching slug, then set Hero.illustration or Section.illustration to "
            "{slug, alt}. The schema-emit step bundles the SVG into the project "
            "automatically."
        ),
        example_snippet="""{
  "type": "Section",
  "props": {
    "variant": "split",
    "illustration": { "slug": "running-athlete", "alt": "Welcome" }
  },
  "children": []
}""",
        applies_when=_on_form,
    ),
    Rule(
        name="dashboard-density",
        body=(
            "Dashboard pages MUST emit at least 4 MetricTile nodes, at least one "
            "Chart (line/bar/area) or Sparkline, and at least one list-style "
            "container (ActivityFeed, DataGrid, or Repeat-over-Card). Avoid sparse "
            "dashboards — readers expect KPI-rich at-a-glance layouts."
        ),
        example_snippet="""{
  "type": "Grid",
  "props": { "columns": 4 },
  "children": [
    { "type": "MetricTile", "props": { "label": "Users",   "value": "83K",  "format": "number", "delta": { "value": "+12%", "direction": "up" }, "icon": "users" } },
    { "type": "MetricTile", "props": { "label": "Sessions","value": "240K", "format": "number", "delta": { "value": "+8%",  "direction": "up" }, "icon": "activity" } },
    { "type": "MetricTile", "props": { "label": "Engaged", "value": "2m",   "format": "duration", "delta": { "value": "+5s",  "direction": "up" }, "icon": "clock" } },
    { "type": "MetricTile", "props": { "label": "Revenue", "value": "$253K","format": "currency", "delta": { "value": "+15%", "direction": "up" }, "icon": "dollar-sign" } }
  ]
}""",
        applies_when=_on_dashboard,
    ),
]
