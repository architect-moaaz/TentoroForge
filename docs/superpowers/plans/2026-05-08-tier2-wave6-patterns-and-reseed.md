# Tier 2 Wave 6 — Schema Patterns + Reference Bank Re-seed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add gold-example schemas demonstrating enterprise patterns (master-detail, multi-step-wizard, approval-flow, reporting-dashboard, settings-grouped, audit-log) so the schema agent can imitate them. Update schema_prompt to reference these by archetype. Operationally re-seed the reference bank for all 5 registers using the new components.

**Architecture:** Pure schema authoring + prompt updates — no new components. The bank re-seed is operational (~$100 LLM cost) and runs against the existing seeder script + render-service.

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme D.

---

## File structure

### New files (gold examples)

- `backend/services/schema_examples/enterprise/master-detail.json`
- `backend/services/schema_examples/enterprise/multi-step-wizard.json`
- `backend/services/schema_examples/enterprise/approval-flow.json`
- `backend/services/schema_examples/enterprise/reporting-dashboard.json`
- `backend/services/schema_examples/enterprise/settings-grouped.json`
- `backend/services/schema_examples/enterprise/audit-log.json`

### Modified files

- `backend/services/schema_prompt.py` — load enterprise gold examples by archetype
- `backend/services/register_selector.py` — extend `describe_register` to mention Tier 2 component preferences

### Operational (manual)

- Run reference bank seeder for 5 registers × 4 domains × 5 page-types = 200 exemplars (~$100, ~30 min wall)

---

## Task 1: master-detail.json

**Files:**
- Create: `backend/services/schema_examples/enterprise/master-detail.json`

DataGrid + InspectorPanel composition: list view on the left, detail panel slides in from right when row clicked.

```json
{
  "schemaVersion": "2",
  "id": "employees/list",
  "route": "/employees",
  "meta": { "title": "Employees", "archetype": "list" },
  "dataSources": [
    { "kind": "list", "name": "employees", "table": "employees" },
    { "kind": "detail", "name": "selectedEmployee", "table": "employees",
      "filter": { "id": "{{url.inspector}}" } }
  ],
  "root": {
    "id": "root", "type": "AppShell",
    "props": {
      "topbar": { "$ref": "node:breadcrumb" },
      "actions": { "$ref": "node:add-employee-cta" }
    },
    "children": [
      {
        "id": "filter-bar", "type": "FilterBar",
        "props": {
          "showSearch": true,
          "chips": [
            { "key": "dept", "label": "Department",
              "options": [
                { "value": "eng", "label": "Engineering" },
                { "value": "design", "label": "Design" },
                { "value": "sales", "label": "Sales" }
              ]
            }
          ]
        }
      },
      {
        "id": "employees-grid", "type": "DataGrid",
        "props": {
          "columns": [
            { "key": "name", "label": "Name", "sortable": true, "frozen": true, "width": 200 },
            { "key": "department", "label": "Department", "sortable": true },
            { "key": "role", "label": "Role" },
            { "key": "status", "label": "Status", "align": "right" }
          ],
          "rows": "{{employees}}",
          "rowKey": "id",
          "selectable": true,
          "rowActions": [
            { "label": "View",
              "action": { "type": "navigate", "to": "?inspector={{row.id}}" }}
          ]
        }
      },
      {
        "id": "employee-inspector", "type": "InspectorPanel",
        "props": { "paramKey": "inspector", "title": "{{selectedEmployee.name}}", "width": "default" },
        "children": [
          { "id": "person-card", "type": "PersonCard",
            "props": {
              "name": "{{selectedEmployee.name}}",
              "role": "{{selectedEmployee.role}}",
              "department": "{{selectedEmployee.department}}",
              "email": "{{selectedEmployee.email}}",
              "status": "{{selectedEmployee.status}}",
              "manager": {
                "name": "{{selectedEmployee.manager.name}}",
                "role": "{{selectedEmployee.manager.role}}"
              },
              "layout": "expanded"
            }},
          { "id": "kv-list", "type": "KeyValueList",
            "props": {
              "items": [
                { "label": "Hire date", "value": "{{selectedEmployee.hireDate}}" },
                { "label": "Tenure", "value": "{{selectedEmployee.tenure}}" },
                { "label": "Last review", "value": "{{selectedEmployee.lastReview}}" }
              ]
            }}
        ]
      }
    ]
  }
}
```

NOTE: schema validation may need slight adjustments depending on how `dataSources` are bound. Adjust as needed.

- [ ] **Commit at end of all 6 example tasks**

---

## Tasks 2-6: Other gold examples

Same pattern as Task 1 — author each schema demonstrating the relevant pattern. The implementer can adapt the structure but must include:

**Task 2: multi-step-wizard.json**
- ApprovalStepper at top showing 3 steps (Personal Info / Job Details / Review)
- TabPanelWithDeepLink with tab IDs matching step IDs
- Each tab body: a Form section
- Final tab: review summary + submit button
- Form action: workflow that emits audit log entries

**Task 3: approval-flow.json**
- DataGrid of pending requests (filtered by `status=pending`)
- Click row → InspectorPanel with full request detail + ApprovalStepper showing current stage status + Timeline of audit log entries
- Action buttons: Approve / Reject / Reassign (each triggers a workflow)

**Task 4: reporting-dashboard.json**
- AppShell with rightRail = ActivityFeed
- Top section: 4 MetricTiles (one with `importance: primary`, others secondary)
- Mid section: FilterBar + DateRangePicker + Chart (line chart of metric over time)
- Bottom section: DataGrid with sparkline-enriched cells

**Task 5: settings-grouped.json**
- AppShell with sidebar = vertical nav of sections
- Main: TabPanelWithDeepLink with 4-5 sections (Profile / Notifications / Security / Billing)
- Each tab body: a Card with grouped Form fields

**Task 6: audit-log.json**
- AppShell
- Main: FilterBar + DateRangePicker + ActivityFeed (full-width)
- Right rail (optional): MultiSelect for filtering by actor/action category

Each schema is roughly 80-120 lines of JSON. Use existing `backend/services/schema_examples/{detail,list}/*.json` as structural references.

- [ ] **Combined commit after all 6 schemas:**

```bash
git add backend/services/schema_examples/enterprise/
git commit -m "feat(schema-examples): 6 enterprise patterns (master-detail / wizard / approval-flow / reporting / settings / audit-log)"
```

---

## Task 7: schema_prompt loads enterprise patterns by archetype

**Files:**
- Modify: `backend/services/schema_prompt.py`

The existing function `load_gold_example(page_type, archetype)` returns a single gold example. Extend it (or add a new helper) to also load from the `enterprise/` directory based on archetype keywords:

```python
def load_enterprise_pattern(archetype_or_role: str) -> dict | None:
    """Load an enterprise pattern by best-match keyword."""
    PATTERNS_DIR = Path(__file__).parent / "schema_examples" / "enterprise"
    if not PATTERNS_DIR.exists():
        return None

    keyword_map = {
        "master-detail": ["list", "detail", "browse", "manage"],
        "multi-step-wizard": ["wizard", "onboarding", "create", "multi-step"],
        "approval-flow": ["approval", "review", "request"],
        "reporting-dashboard": ["report", "analytics", "dashboard", "kpi"],
        "settings-grouped": ["settings", "profile", "preferences"],
        "audit-log": ["audit", "history", "activity", "log"],
    }

    role = (archetype_or_role or "").lower()
    for pattern_name, keywords in keyword_map.items():
        if any(kw in role for kw in keywords):
            path = PATTERNS_DIR / f"{pattern_name}.json"
            if path.exists():
                try:
                    return json.loads(path.read_text())
                except json.JSONDecodeError:
                    continue
    return None
```

In `build_schema_prompt`, after the existing exemplars block, append the enterprise pattern when matched:

```python
enterprise_pattern = load_enterprise_pattern(page_brief.get("role", "") if page_brief else "")
if enterprise_pattern:
    prompt += "\n\n## ENTERPRISE PATTERN (gold example for this archetype)\n\n"
    prompt += "```json\n"
    prompt += json.dumps(enterprise_pattern, indent=2)
    prompt += "\n```\n"
    prompt += "Adapt this structure to the specific entities + brief above.\n"
```

- [ ] **Commit:**

```bash
git add backend/services/schema_prompt.py
git commit -m "feat(schema-prompt): load enterprise pattern by archetype keyword match"
```

---

## Task 8: register_selector descriptions mention Tier 2 components

**Files:**
- Modify: `backend/services/register_selector.py`

Update `describe_register` to mention Tier 2 component preferences per register:

```python
def describe_register(name: RegisterName) -> str:
    descriptions = {
        "default":  "neutral shadcn-default",
        "workday":  ("corporate enterprise — dense data, navy primary, structured grays. "
                     "Heavy use of DataGrid + ApprovalStepper + Timeline + KeyValueList. "
                     "Approval flows feature parallel approvers + delegation."),
        "linear":   ("monochrome neutral, sharp, single accent — SaaS / dev tools. "
                     "Heavy use of CommandPalette + DataGrid (compact) + Sparkline. "
                     "Workflows are lightweight; emphasis on keyboard navigation."),
        "stripe":   ("two-tone with gradient hero, layered shadows — fintech / payments. "
                     "Heavy use of Chart + DataGrid + InspectorPanel for transaction detail. "
                     "Reporting dashboards prominent."),
        "notion":   ("soft, airy, content-first — wikis / docs / knowledge bases. "
                     "Heavy use of Section/Card composition; minimal DataGrid; "
                     "TabPanelWithDeepLink common for sectioned content."),
        "figma":    ("vibrant, friendly, playful — design tools / creative apps. "
                     "Heavy use of FeatureCard + EmptyStateRich; minimal data tables."),
    }
    return descriptions.get(name, "unknown register")
```

- [ ] **Commit:**

```bash
git add backend/services/register_selector.py
git commit -m "feat(registers): describe_register mentions Tier 2 component preferences per register"
```

---

## Task 9: Final verification

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_schema_prompt.py tests/services/test_register_selector.py tests/integration/test_schema_migration.py -v 2>&1 | tail -10
```

Expected: all pass.

---

## Task 10 — Operational: reference bank re-seed (DEFERRED)

This task is **not code** — it's running the seeder for ~$100 in LLM costs. Deferred to a manual operational step the user runs when ready:

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend

# Make sure render-service + scaffold are running
# Then for each register × domain × page-type cell:
for REGISTER in workday linear stripe notion figma; do
  for DOMAIN in general healthcare fintech hr; do
    for PAGETYPE in list detail form dashboard settings; do
      python3 -m scripts.seed_reference_bank \
        --register "$REGISTER" --domain "$DOMAIN" --page-type "$PAGETYPE" \
        --target-count 2 --max-attempts 8 --seeder-version v2
    done
  done
done

git add backend/reference_pages/
git commit -m "feat(reference-bank): seed v2 exemplars for all 5 registers (post Tier 2)"
```

Cost: 5 × 4 × 5 = 100 cells × ~$1/cell = ~$100. Wall time: ~30-45 min depending on render-service speed.

Output: 5 × 4 × 5 × 2 = 200 exemplars in `backend/reference_pages/<register>/<domain>/<page_type>/`.

After re-seeding, the schema agent will see register-tuned exemplars that demonstrate the new Tier 2 components (DataGrid + Chart + InspectorPanel + ApprovalStepper + etc.) — significantly improving generation quality.

---

## Self-review

| Spec section | Tasks |
|---|---|
| 6 enterprise gold examples | 1-6 |
| schema_prompt loads patterns | 7 |
| register_selector descriptions | 8 |
| Verification | 9 |
| Bank re-seed (operational) | 10 (deferred) |

✓ All Wave 6 code scope. Re-seeding is operational and runs when ready.

---

## Out of scope

- **Cron-driven escalations** — Wave 5 ships the helper module; the actual cron setup is per-deployment
- **Workflow-engine + data-engine TypeScript-side tests** — generated apps have their own test setup; template-side smoke tests in Python are enough for this wave
- **Multi-tenancy in saved-views** — Wave 5 saved-views.ts is per-userId only; multi-tenant scoping is a platform concern
