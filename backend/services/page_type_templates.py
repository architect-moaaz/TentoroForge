"""Per-page-type template guidance for the schema prompt.

Each template names the required components AND the DO-NOT-USE components
so the LLM follows them literally when composing a page schema.
"""
from __future__ import annotations

_FORM = """\
## PAGE TYPE: FORM

You MUST emit a `Form` component containing the fields the user needs to
fill in for this page's intent. Use `Input` (with `type` matching the
field's data type: email, password, number, text, date), `Textarea` for
long text, `Select` for enums, `Checkbox` for booleans, and `DatePicker`
for date fields. Wrap submit + cancel in a `Row` at the bottom.

Required shape (compose around it — don't deviate):
```
Stack {
  Heading { level: 2, content: <page name> }
  Text { content: <one-line description> }      // optional
  Form {
    Input { label, type, name }                 // one per scalar field
    Textarea { label, name }                    // for long text
    Select { label, name, options }             // for enums
    Row { Button { label: "Cancel", variant: "ghost" } Button { label: "Submit", variant: "primary" } }
  }
}
```

DO NOT use `MetricTile`, `Hero`, `Table`, `Chart` on a form page —
those belong on dashboards and lists.
"""

_LIST = """\
## PAGE TYPE: LIST

You MUST emit either a `Table` or a `DataGrid` listing the entity's
records, preceded by a `FilterBar` for searching/filtering, and followed
by `Pagination` if the dataset is large. A `Heading` + small action `Row`
(create / export buttons) sits at the top.

Required shape:
```
Stack {
  Row { Heading { content: <page name> }  Button { label: "+ New", navigate: "<route>/new" } }
  FilterBar { /* search, status, date range */ }
  Table { columns, source: <entity binding> }     // or DataGrid for large datasets
}
```

DO NOT put a `Form` or `MetricTile` on a list page.
"""

_DETAIL = """\
## PAGE TYPE: DETAIL

You MUST emit a header (`Heading` or `Hero`), the entity's key fields via
`KeyValueList`, a related-data section in a `Card`, and an action `Row`
with edit / delete buttons. Bind the page to a single record using
`bind: "{{entity}}"` not a list source.

Required shape:
```
Stack {
  Heading { content: "{{entity.name}}" }
  Row { Button { label: "Edit", navigate: "<route>/edit" }  Button { label: "Delete", variant: "danger" } }
  KeyValueList { items: [ <every meaningful field on the entity> ] }
  Card { /* related records or audit log */ }
}
```

DO NOT put a `MetricTile` grid or a top-level `Table` on a detail page —
those belong on dashboards and lists.
"""

_AUTH = """\
## PAGE TYPE: AUTH

You MUST emit a centered card containing the auth form with email +
password inputs (or email + name + password for signup), a primary
submit button, and a link to the alternate route (signup ↔ login).
Wrap the whole layout in a `Section` that centers vertically — auth
pages are full-viewport.

Required shape:
```
Section {
  Card {
    Heading { level: 2, content: "Sign in" }       // or "Sign up"
    Form {
      Input { label: "Email", type: "email", name: "email" }
      Input { label: "Password", type: "password", name: "password" }
      Button { label: "Sign in", variant: "primary" }
    }
    Link { label: "Don't have an account? Sign up", navigate: "/signup" }
  }
}
```

DO NOT put a sidebar, dashboard chrome, MetricTile, or Hero on an auth page.
"""

_DASHBOARD = """\
## PAGE TYPE: DASHBOARD

This is the operator's home screen. Derive its content from THIS domain's real
signals — what would someone running this specific app check first thing in the
morning? Name CONCRETE domain metrics, not generic "total records" counts:
- a clinic → today's appointments, beds occupied, lab results pending review
- a logistics app → shipments in transit, on-time %, exceptions to resolve
- a sales CRM → pipeline value by stage, deals closing this week, quota attainment

Choose the widget mix the domain calls for — do NOT default to "4 MetricTiles + a
Table" for every app. Pick from registered components: `MetricTile` / `Stat` for
KPIs, `Chart` for trends, `ActivityFeed` for event-heavy domains, `Calendar` for
schedule-centric ones, a compact `Table` / `DataGrid` for the most actionable
records, a `Kanban` summary for pipeline domains. Two dashboards in DIFFERENT
domains should surface different metrics AND a different widget mix.

Renderability floor (keep it composable): emit a header (`Hero` or `Heading`), at
least 3 domain KPIs (`MetricTile` / `Stat`), and at least one content widget
(`Chart`, `Table`, `ActivityFeed`, `Calendar`, …). This is the page type where
`MetricTile` and `Chart` belong at the top level.
"""

_ERROR = """\
## PAGE TYPE: ERROR

You MUST emit a centered `EmptyState` or `EmptyStateRich` with the error
code, a friendly message, and a primary `Button` linking back to the
home route. Keep it minimal — no sidebar, no metric tiles, no forms.

Required shape:
```
Section {
  EmptyState {
    title: "Page not found",
    description: "The page you're looking for doesn't exist.",
    action: Button { label: "Back to home", navigate: "/" }
  }
}
```
"""

_GENERIC = """\
## PAGE TYPE: GENERIC

No specific template — emit whatever composition best fits the page
description. Prefer composing from primitives (Stack, Row, Grid, Card)
plus a small set of display components (Heading, Text, Button).
"""

_KANBAN = """\
## PAGE TYPE: KANBAN

KANBAN BOARD page. Structure:
Stack { Row { Heading, FilterBar }, Kanban }
- Kanban: bind a list dataSource; group columns by the entity's `status` field;
  each card shows the record's title + a key field.
- DO NOT use: Table, DataGrid, Form, MetricTile.
"""

_CALENDAR = """\
## PAGE TYPE: CALENDAR

CALENDAR page. Structure:
Stack { Heading, Calendar }
- Calendar is in EVENT mode. Bind its `events` prop to the list dataSource with the
  `{{...}}` binding syntax — NOT `bind`, NOT a bare dataSource name. Set `dateField`
  to the entity's date column, `titleField` to its label, `colorField` to status.
  Exact contract (copy this shape):
  ```
  Calendar {
    events: "{{<listDataSource>}}"   // e.g. "{{assessments}}" — NEVER bind:"assessmentsList"
    dateField: "<dateColumn>"        // e.g. "scheduledAt"
    titleField: "<labelColumn>"      // e.g. "title"
    colorField: "<statusColumn>"     // e.g. "status" (if present)
  }
  ```
- DO NOT use: Table, DataGrid, Form, MetricTile.
"""

_INBOX = """\
## PAGE TYPE: INBOX

INBOX (split list + reading pane) page. Structure:
Split { left: DataGrid(bind list, compact), right: InspectorPanel(selected record) }
- Heading above the Split.
- DO NOT use: full-width Table, MetricTile grid, Form at top level.
"""

_REPORT = """\
## PAGE TYPE: REPORT

REPORT / ANALYTICS page. Structure:
Stack { Row { Heading, DateRangePicker }, Grid { Stat x3-4 }, Card { Chart }, Card { Table } }
- Chart: pick line/bar/area to fit the metric. Stats summarise; Table shows detail.
- DO NOT use: Form, Kanban, single big KeyValueList.
"""

_WIZARD = """\
## PAGE TYPE: WIZARD

WIZARD (multi-step) page. Structure:
Stack { ApprovalStepper(steps), Form(current-step fields), Row { Button:Back, Button:Next } }
- One Form section per step; ApprovalStepper shows progress.
- DO NOT use: Table, DataGrid, MetricTile.
"""

_AUDIT_LOG = """\
## PAGE TYPE: AUDIT-LOG

AUDIT-LOG / TIMELINE page. Structure:
Stack { Heading, Timeline }
- Timeline: bind a list dataSource ordered by time; each entry shows timestamp,
  actor, action. Optionally a Card { ActivityFeed } alongside.
- DO NOT use: Form, editable Table.
"""

_SETTINGS = """\
## PAGE TYPE: SETTINGS

SETTINGS page. Structure:
Stack { Heading, Tabs { per-group Card { Form fields } }, Button:Save }
- Group related settings into tabs; each tab is a small Form.
- DO NOT use: DataGrid, Kanban, MetricTile.
"""

_COMPUTATIONAL = """\
## PAGE TYPE: COMPUTATIONAL — READ EVERY WORD

Standalone tool page: inputs → formula → result. Purely client-side, NO
persistence, NO auth, NO API routes, NO workflow_tasks.

**MANDATORY: every interactive Button MUST carry `onClick`.** A Button
without `onClick` is inert visual chrome and defeats the entire purpose.
The two only-allowed onClick shapes on this page type:

  1. Reactive computed field  (typed-input calculators, EMI/BMI/tip)
     Preferred — no button needed; the result field recomputes as the
     user types.
     ```
     { "type": "Input",
       "props": { "label": "Monthly EMI", "name": "emi",
                  "kind": "number", "readOnly": true,
                  "interaction": { "computed": {
                    "formula": "principal * rate / 12", "readOnly": true }}}}
     ```

  2. Imperative compute button  (keypad calculators, "=" key, "Calculate")
     ```
     { "type": "Button",
       "props": { "label": "3",
                  "onClick": { "kind": "compute", "target": "display",
                               "formula": "concat(display, '3')" }}}
     ```

═══════════════════════════════════════════════════════════════════════
COMPLETE COPY-PASTE EXAMPLE — a working keypad calculator.
Emit STRUCTURALLY this — same nesting, same `onClick` on every keypad
Button, same `interaction.computed` on the display, same helpers.
Change only the tokens/labels for the specific tool.
═══════════════════════════════════════════════════════════════════════

```json
{
  "schemaVersion": "2", "id": "home", "route": "/",
  "root": {
    "type": "Section",
    "children": [
      { "type": "Card",
        "children": [
          { "type": "Heading",
            "props": { "level": 2, "content": "Calculator" }},
          { "type": "Form",
            "props": { "fields": [
              { "name": "display", "kind": "text", "label": "",
                "readOnly": true, "defaultValue": "0" }
            ]},
            "children": [
              { "type": "Card",
                "props": { "className": "p-4 bg-muted text-right" },
                "children": [
                  { "type": "Text",
                    "props": { "content": "{{display}}",
                               "className": "text-3xl font-mono" }}
                ]},
              { "type": "Grid",
                "props": { "cols": 4, "gap": "sm" },
                "children": [
                  { "type": "Button",
                    "props": { "label": "AC", "variant": "danger",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "'0'" }}},
                  { "type": "Button",
                    "props": { "label": "(", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '(')" }}},
                  { "type": "Button",
                    "props": { "label": ")", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, ')')" }}},
                  { "type": "Button",
                    "props": { "label": "÷", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '/')" }}},

                  { "type": "Button",
                    "props": { "label": "7",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '7')" }}},
                  { "type": "Button",
                    "props": { "label": "8",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '8')" }}},
                  { "type": "Button",
                    "props": { "label": "9",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '9')" }}},
                  { "type": "Button",
                    "props": { "label": "×", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '*')" }}},

                  { "type": "Button",
                    "props": { "label": "4",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '4')" }}},
                  { "type": "Button",
                    "props": { "label": "5",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '5')" }}},
                  { "type": "Button",
                    "props": { "label": "6",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '6')" }}},
                  { "type": "Button",
                    "props": { "label": "−", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '-')" }}},

                  { "type": "Button",
                    "props": { "label": "1",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '1')" }}},
                  { "type": "Button",
                    "props": { "label": "2",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '2')" }}},
                  { "type": "Button",
                    "props": { "label": "3",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '3')" }}},
                  { "type": "Button",
                    "props": { "label": "+", "variant": "secondary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '+')" }}},

                  { "type": "Button",
                    "props": { "label": "0", "className": "col-span-2",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '0')" }}},
                  { "type": "Button",
                    "props": { "label": ".",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "concat(display, '.')" }}},
                  { "type": "Button",
                    "props": { "label": "=", "variant": "primary",
                      "onClick": { "kind": "compute", "target": "display",
                                   "formula": "evalExpression(display)" }}}
                ]}
            ]}
        ]}
    ]}
}
```

═══════════════════════════════════════════════════════════════════════

RULES you MUST follow — the calculator only works if every one holds:

1. The whole keypad MUST be inside a `Form` — buttons need
   FormComputeContext (provided by Form) to call setValue on the
   display field. A Form-less keypad = dead buttons.

2. The Form MUST declare a `display` field (or whatever target-field
   name you pick, keep it consistent) with `readOnly: true`.

3. Every digit and operator Button MUST have
   `onClick: { kind: "compute", target: "display",
               formula: "concat(display, '<the char>')" }`.
   The `<the char>` is what to APPEND — not the button label. `×`
   labels append `'*'`; `÷` labels append `'/'`; `−` appends `'-'`.

4. The `=` Button MUST have
   `onClick: { kind: "compute", target: "display",
               formula: "evalExpression(display)" }`.
   `evalExpression` is a safe arithmetic evaluator (registered helper);
   it turns `"2+3*4"` into `"14"` and `"5/0"` into `"Error"`.

5. The `AC`/`Clear` Button MUST have
   `onClick: { kind: "compute", target: "display", formula: "'0'" }`
   (a bare string literal in quotes → resets to "0").

6. The display Text/Heading MUST bind to `{{display}}` (double
   curly braces, no `bind:` prefix).

Helpers available in `formula:` strings — use these, don't invent others:
  concat, evalExpression, upper, lower, round, sum, min, max, abs,
  ifElse, coalesce, formatCurrency, formatNumber.

═══════════════════════════════════════════════════════════════════════

DO NOT emit ON THIS PAGE:
  * MetricTile, Chart, DataGrid, Table, KeyValueList, ActivityFeed,
    FeatureCard, ValidationChecklist — these are dashboard/CRUD chrome.
  * `dataSource` or `bind:` props — computational apps read nothing
    from the DB.
  * A submit button (`submit: true`) or any button with `navigate` — the
    tool never leaves this page and never POSTs.
  * A hardcoded literal in the display area (e.g. `"8+3"` as Text
    content) — the display MUST bind to `{{display}}` so the buttons
    can update it.

For typed-input calculators (EMI/BMI/tip) — SAME rules but simpler:
Form has typed input fields + one result Input with
`interaction.computed`; no keypad Grid, no `=` button needed.
"""

_VISUAL_SCAN = """\
## PAGE TYPE: VISUAL-SCAN  (stateful single-page pattern)

VISUAL PRODUCT SCAN — ONE page, N states, no navigation. User captures
an image, hits Scan, the workflow runs, results appear inline on the same
page as the workflow writes them. No /scans/[id] redirect, no separate
results screen.

The runtime supports this natively via `AutoRefresh` — the schema
declares a top-level `poll` block, and the runtime re-runs the RSC path
every N ms so the Conditional root re-evaluates with the workflow's
latest status. See docs/superpowers/patterns/stateful-single-page.md
for the full contract.

Required shape:
```
{
  "route": "/scan",
  "poll": { "interval": 2500, "stopWhen": "scan.status IN ('completed','failed')" },
  "dataSources": [
    { "name": "scan",   "entity": "Scan",        "op": "latestForUser" },
    { "name": "prices", "entity": "PriceResult", "op": "list",
      "where": { "scanId": "{{scan.id}}" },
      "orderBy": [{ "field": "price", "direction": "asc" }] }
  ],
  "root": {
    "type": "Conditional",
    "branches": [
      { "if": "!scan", "node":
        Stack {
          Heading { level: 1, content: "Scan a product" }
          Text { content: "Take a photo or upload an image. We'll identify the product and find prices across retailers.", variant: "muted" }
          Form { workflow: "ScanProductWorkflow" }
            Stack { gap: "tokens.spacing.4" }
              CameraCapture { name: "imageUrl", label: "Take photo", uploadTo: "forge_files" }
              FileUpload    { name: "imageUrl", label: "Or upload image", accept: "image/*" }
              Button        { label: "Scan", variant: "primary", submit: true }
        }
      },
      { "if": "scan.status === 'pending' || scan.status === 'processing'", "node":
        Stack { gap: "tokens.spacing.6", align: "center" }
          Heading  { level: 2, content: "Scanning..." }
          Progress { indeterminate: true }
          Text     { content: "Identifying the product and checking prices across retailers. This usually takes 10–20 seconds.", variant: "muted" }
      },
      { "if": "scan.status === 'failed'", "node":
        Stack { gap: "tokens.spacing.4" }
          Banner { variant: "error", content: "Scan failed. Try again with a clearer image." }
          Button { label: "Try again", variant: "primary", navigate: "/scan?reset=1" }
      },
      { "if": "scan.status === 'completed'", "node":
        Stack { gap: "tokens.spacing.6" }
          Card
            Row { gap: "tokens.spacing.4", align: "center" }
              Image { src: "{{scan.imageUrl}}", width: 96, alt: "scanned image" }
              Stack { gap: "tokens.spacing.1" }
                Heading { level: 3, content: "Scan result" }
                Text    { content: "Compare prices below", variant: "muted" }
          Repeat { bind: "prices" }
            Card
              Row { justify: "between", align: "center" }
                Stack { gap: "tokens.spacing.1" }
                  Text { content: "{{item.retailerId}}", weight: "medium" }
                  Text { content: "{{item.currency}} {{item.price}}", variant: "muted" }
                Link { label: "Open →", navigate: "{{item.productUrl}}", external: true }
          Button { label: "Scan another", variant: "ghost", navigate: "/scan?reset=1" }
      }
    ]
  }
}
```

MANDATORY:
- Emit the top-level `poll` block VERBATIM: interval 2500, stopWhen
  referring to `scan.status IN ('completed','failed')`. Without it the
  page will not transition when the workflow finishes.
- Use `Conditional` as the ROOT node — not a Stack that hides/shows
  children. The runtime's Conditional re-evaluates on every re-render;
  a Stack with conditional visibility would flicker.
- Both `dataSources` are REQUIRED: `scan` (drives the state machine)
  and `prices` (the completed-branch content).
- The Form's `workflow` prop MUST be `"ScanProductWorkflow"` — this is
  the workflow the ScanProduct archetype ships.
- Both `CameraCapture` AND `FileUpload` MUST bind to the SAME field
  name (`imageUrl`) so mobile and desktop users write to one place.
- The retry Button uses `navigate: "/scan?reset=1"` — same route, the
  reset param tells the dataSource to skip the latest scan (renderer
  convention).

DO NOT:
- Emit a `/scans/[id]` route or `navigate` to a per-scan detail page
  after submit — the whole point of this pattern is that navigation
  goes away. The submit Button is `submit: true`, nothing more.
- Emit `onClick: { kind: "agent_chat" }` on the submit — that's the
  OLD synchronous design. The new flow is workflow-triggered with a
  polled DB row.
- Use a `Grid` bound to `{{agent.matches}}` — results come from the
  `prices` dataSource, driven by scanId, populated by the workflow.
- Use Table/MetricTile/Chart — this is a state-machine page, not a
  dashboard.
"""

_RETAIL_SOURCES_ADMIN = """\
## PAGE TYPE: RETAIL-SOURCES-ADMIN

ADMIN CRUD page for the `retail_sources` entity (the allow-list of
retailers the app-agent is permitted to query). Only accessible to the
admin role.

Required shape:
```
Stack {
  Row { Heading { content: "Retail sources" }
        Button { label: "+ Add source", navigate: "/admin/retail-sources/new" } }
  FilterBar { fields: [ "name", "enabled", "region" ] }
  Table {
    source: "{{retailSources}}",
    columns: [
      { field: "name",     label: "Name" },
      { field: "url",      label: "URL" },
      { field: "enabled",  label: "Enabled",  render: "toggle",
        onToggle: { kind: "workflow", workflow: "toggleRetailSource",
                    args: { id: "{{row.id}}", enabled: "{{value}}" } } },
      { field: "priority", label: "Priority", render: "number" },
      { field: "region",   label: "Region" },
      { field: "actions",  label: "",
        render: "actions",
        actions: [
          { label: "Edit",   navigate: "/admin/retail-sources/{{row.id}}/edit" },
          { label: "Delete", variant: "danger",
            onClick: { kind: "workflow", workflow: "deleteRetailSource",
                       args: { id: "{{row.id}}" } } }
        ]
      }
    ]
  }
}
```

MANDATORY:
- Include a per-row `enabled` `toggle` control — the whole point of this
  page is turning sources on/off without leaving the list.
- Include `priority` (numeric ordering the app-agent respects) and
  `region` (routing hint) as columns.
- The `+ Add source` button MUST navigate to `/admin/retail-sources/new`
  (the standard create route the CRUD scaffolder emits).

DO NOT use: MetricTile grid, Chart, Kanban, Calendar — this is a plain
admin list. DO NOT put a `Form` at the top level — edits happen on the
create/edit route.
"""

_TEMPLATES: dict[str, str] = {
    "form": _FORM,
    "list": _LIST,
    "detail": _DETAIL,
    "auth": _AUTH,
    "dashboard": _DASHBOARD,
    "error": _ERROR,
    "kanban": _KANBAN,
    "calendar": _CALENDAR,
    "inbox": _INBOX,
    "report": _REPORT,
    "wizard": _WIZARD,
    "audit-log": _AUDIT_LOG,
    "timeline": _AUDIT_LOG,
    "settings": _SETTINGS,
    "computational": _COMPUTATIONAL,
    "visual_scan": _VISUAL_SCAN,
    "retail_sources_admin": _RETAIL_SOURCES_ADMIN,
}


# App-archetype → page-type templates it composes. Consumed by the planner
# when it seeds pages for an app-level archetype (e.g. visual-product-search
# → a /scan page uses `visual_scan`, /admin/retail-sources uses
# `retail_sources_admin`). Kept next to `_TEMPLATES` so the two stay in sync.
APP_ARCHETYPE_PAGE_TEMPLATES: dict[str, list[str]] = {
    "visual-product-search": ["visual_scan", "retail_sources_admin"],
}


def template_for(page_type: str) -> str:
    """Return a short instruction block the schema prompt appends.

    Each template names the required components AND the DO-NOT-USE
    components so the LLM follows them literally when composing a page.
    Unknown page types return the generic fallback block.
    """
    return _TEMPLATES.get(page_type, _GENERIC)
