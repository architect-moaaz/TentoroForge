# Planner-as-App-Designer — SP1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make prompt-generated apps distinctive — the planner picks fitting page **archetypes** (kanban/calendar/inbox/report/wizard/audit-log/settings/timeline) and declares domain **features**, generated freely but validated to be renderable (open-with-guardrails), composing components that already exist.

**Architecture:** A pure **capability catalog** (what we can render/back) → planner emits `archetype` + `features` steered by the catalog → a deterministic **guardrail** normalizes/validates every choice with graceful fallback → per-archetype **templates** steer the schema agent to compose existing components. Plus a one-map fix so theme+layout stop collapsing to a single default.

**Tech Stack:** Python 3 (backend), pytest. No new UI components; no runtime-engine changes (those are SP2).

**Spec:** `docs/superpowers/specs/2026-06-13-planner-app-designer-sp1-design.md`

**Reference shapes (from the codebase):**
- `backend/services/page_type_templates.py`: `_TEMPLATES: dict[str,str]` (page_type → instruction-block string); `template_for(page_type) -> _TEMPLATES.get(page_type, _GENERIC)`.
- `backend/services/page_type.py`: `infer_page_type(page_brief) -> str`.
- `backend/agents/planner.py`: `_sanitize_page_actions(plan)` is the pure-sanitizer pattern to mirror; called at the end of `_annotate_page_types`. `_ONESHOT_SYSTEM_PROMPT` pages schema is `{name, route, type, entity, description, actions}`.
- `backend/services/industry_design.py`: `get_industry_design(domain)` does `DOMAIN_THEME.get(domain, "ocean")` + `DOMAIN_LAYOUT.get(domain, _DEFAULT_LAYOUT)`.
- Existing registered schema-node components (use ONLY these in templates): `Kanban, Calendar, Timeline, Chart, Tree, InspectorPanel, ApprovalStepper, ActivityFeed, DataGrid, Table, FilterBar, Tabs, Split, Stat, MetricTile, DateRangePicker, Form, Card, Grid, Row, Stack, Heading, Button`.

**Test command (from `backend/`):** `/usr/local/bin/python3 -m pytest tests/<file> -v`

---

### Task 1: Capability catalog

**Files:**
- Create: `backend/services/app_design_catalog.py`
- Test: `backend/tests/services/test_app_design_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_app_design_catalog.py
from services.app_design_catalog import (
    ARCHETYPES, FEATURES, archetype_names, feature_names,
    is_renderable_archetype, is_renderable_feature, catalog_for_prompt,
)


def test_archetypes_cover_new_set_and_are_renderable():
    for a in ["kanban", "calendar", "inbox", "report", "wizard", "audit-log", "settings", "timeline"]:
        assert a in ARCHETYPES, a
        assert ARCHETYPES[a]["renderable"] is True


def test_archetypes_only_use_registered_components():
    registered = {"Kanban","Calendar","Timeline","Chart","Tree","InspectorPanel",
        "ApprovalStepper","ActivityFeed","DataGrid","Table","FilterBar","Tabs",
        "Split","Stat","MetricTile","DateRangePicker","Form","Card","Grid","Row",
        "Stack","Heading","Button","KeyValueList"}
    for name, spec in ARCHETYPES.items():
        assert set(spec["components"]) <= registered, (name, set(spec["components"]) - registered)


def test_features_map_to_primitive_and_flag_sp2():
    assert FEATURES["status-pipeline"]["primitive"] == "workflow"
    assert FEATURES["approval"]["primitive"] == "workflow"
    # SP2-only features are catalogued but flagged
    assert FEATURES["sla-escalation"]["renderable_in"] == "SP2"


def test_helpers():
    assert "kanban" in archetype_names()
    assert is_renderable_archetype("kanban") and not is_renderable_archetype("nope")
    assert is_renderable_feature("approval") and not is_renderable_feature("sla-escalation")
    assert "status-pipeline" in feature_names()
    txt = catalog_for_prompt()
    assert "kanban" in txt and "approval" in txt
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_app_design_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/services/app_design_catalog.py
"""Capability catalog — the single source of truth for what the generator can
render (page archetypes) and back (domain features). The planner is steered
toward this catalog; the guardrail validates choices against it.
"""
from __future__ import annotations

# Page archetypes. `components` MUST be drawn from already-registered schema
# nodes (no new UI). `template_key` matches a key in page_type_templates._TEMPLATES.
ARCHETYPES: dict[str, dict] = {
    # The 6 legacy types remain renderable (templates already exist).
    "list":      {"components": ["DataGrid","FilterBar","Heading","Row","Stack","Button"], "template_key": "list",      "renderable": True, "description": "Browse/filter many records", "fits": "any entity collection"},
    "detail":    {"components": ["Heading","KeyValueList","Card","Tabs","Button","Row","Stack"], "template_key": "detail", "renderable": True, "description": "One record's full view", "fits": "single entity"},
    "form":      {"components": ["Form","Card","Row","Stack","Heading","Button"], "template_key": "form",         "renderable": True, "description": "Create/edit a record", "fits": "new/edit"},
    "dashboard": {"components": ["MetricTile","Grid","Chart","Card","Stack","Heading"], "template_key": "dashboard", "renderable": True, "description": "KPIs + overview", "fits": "home/overview"},
    # New archetypes (templates added in Task 4).
    "kanban":    {"components": ["Kanban","FilterBar","Heading","Row","Stack"], "template_key": "kanban",        "renderable": True, "description": "Board of cards grouped by status", "fits": "tasks/tickets/pipeline stages"},
    "calendar":  {"components": ["Calendar","Heading","Row","Stack"], "template_key": "calendar",                "renderable": True, "description": "Month/week event grid", "fits": "appointments/bookings/schedules"},
    "inbox":     {"components": ["Split","DataGrid","InspectorPanel","Heading","Stack"], "template_key": "inbox", "renderable": True, "description": "List + reading pane", "fits": "tickets/messages/requests"},
    "report":    {"components": ["Chart","DateRangePicker","Grid","Stat","Table","Card","Heading","Row","Stack"], "template_key": "report", "renderable": True, "description": "Charts + summary analytics", "fits": "reports/analytics"},
    "wizard":    {"components": ["ApprovalStepper","Form","Row","Stack","Heading","Button"], "template_key": "wizard", "renderable": True, "description": "Multi-step guided flow", "fits": "onboarding/multi-step create"},
    "audit-log": {"components": ["Timeline","ActivityFeed","Card","Heading","Stack"], "template_key": "audit-log", "renderable": True, "description": "Chronological event history", "fits": "history/activity/audit"},
    "settings":  {"components": ["Tabs","Form","Card","Heading","Stack","Button"], "template_key": "settings",      "renderable": True, "description": "Grouped configuration", "fits": "settings/profile/account"},
    "timeline":  {"components": ["Timeline","Heading","Stack"], "template_key": "audit-log",                       "renderable": True, "description": "Vertical chronological view", "fits": "process/status history"},
}

# Domain features → the EXISTING primitive that backs them. Features needing new
# runtime are catalogued but flagged renderable_in:"SP2" (guardrail drops them).
FEATURES: dict[str, dict] = {
    "status-pipeline": {"primitive": "workflow", "renderable_in": "SP1", "description": "status field + status-change workflow"},
    "approval":        {"primitive": "workflow", "renderable_in": "SP1", "description": "approval workflow + Approve/Reject"},
    "notify":          {"primitive": "workflow", "renderable_in": "SP1", "description": "send-notification action on change"},
    "scheduled":       {"primitive": "timer",    "renderable_in": "SP1", "description": "timer/delay node"},
    "decision":        {"primitive": "decision", "renderable_in": "SP1", "description": "decision table"},
    # SP2 — need new engine wiring; not rendered in SP1.
    "sla-escalation":  {"primitive": "timer+route", "renderable_in": "SP2", "description": "deadline breach → escalate"},
    "auto-reorder":    {"primitive": "rule+workflow", "renderable_in": "SP2", "description": "threshold → create order"},
}


def archetype_names() -> set[str]:
    return set(ARCHETYPES)


def feature_names() -> set[str]:
    return set(FEATURES)


def is_renderable_archetype(name: str | None) -> bool:
    spec = ARCHETYPES.get(name) if name else None
    return bool(spec and spec.get("renderable"))


def is_renderable_feature(name: str | None) -> bool:
    spec = FEATURES.get(name) if name else None
    return bool(spec and spec.get("renderable_in") == "SP1")


def catalog_for_prompt() -> str:
    """Compact catalog text injected into the planner prompt."""
    a = "\n".join(f"  - {n}: {s['description']} (fits {s['fits']})" for n, s in ARCHETYPES.items())
    f = "\n".join(f"  - {n}: {s['description']}" for n, s in FEATURES.items() if s["renderable_in"] == "SP1")
    return f"PAGE ARCHETYPES (choose the one that fits each page):\n{a}\n\nDOMAIN FEATURES:\n{f}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_app_design_catalog.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/app_design_catalog.py backend/tests/services/test_app_design_catalog.py
git commit -m "feat(design): capability catalog of renderable archetypes + features"
```

---

### Task 2: Guardrail / normalizer

**Files:**
- Create: `backend/services/app_design_guardrail.py`
- Test: `backend/tests/services/test_app_design_guardrail.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_app_design_guardrail.py
from services.app_design_guardrail import normalize_app_design


def _plan(pages):
    return {"pages": pages}


def test_unknown_archetype_falls_back_to_type():
    plan, report = normalize_app_design(_plan([
        {"route": "/x", "type": "list", "archetype": "hologram", "features": []},
    ]))
    p = plan["pages"][0]
    assert p["archetype"] == "list"                 # fell back to page type
    assert report["pages"][0]["substituted"] == ("hologram", "list")


def test_known_archetype_passes_through():
    plan, report = normalize_app_design(_plan([
        {"route": "/t", "type": "list", "archetype": "kanban", "features": []},
    ]))
    assert plan["pages"][0]["archetype"] == "kanban"
    assert report["pages"][0]["substituted"] is None


def test_drops_unsupported_and_sp2_features():
    plan, report = normalize_app_design(_plan([
        {"route": "/r", "type": "list", "archetype": "report",
         "features": ["approval", "sla-escalation", "ghost"]},
    ]))
    assert plan["pages"][0]["features"] == ["approval"]
    assert set(report["pages"][0]["dropped_features"]) == {"sla-escalation", "ghost"}


def test_missing_archetype_uses_type():
    plan, _ = normalize_app_design(_plan([{"route": "/q", "type": "detail"}]))
    assert plan["pages"][0]["archetype"] == "detail"


def test_failure_leaves_plan_unchanged():
    # non-dict pages → returned as-is, no crash
    plan, report = normalize_app_design({"pages": "nope"})
    assert plan == {"pages": "nope"} and report["pages"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_app_design_guardrail.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/services/app_design_guardrail.py
"""Open-with-guardrails: validate the planner's archetype/feature choices against
the capability catalog. Un-renderable choices fall back gracefully (never a broken
page); unsupported/SP2 features are dropped. Returns (plan, report)."""
from __future__ import annotations

from services.app_design_catalog import (
    ARCHETYPES, is_renderable_archetype, is_renderable_feature,
)

# Cheap alias map for near-miss archetype names the LLM might invent.
_ALIAS = {
    "board": "kanban", "task-board": "kanban", "pipeline": "kanban",
    "schedule": "calendar", "agenda": "calendar",
    "split-pane": "inbox", "mailbox": "inbox", "messages": "inbox",
    "analytics": "report", "reports": "report", "charts": "report",
    "stepper": "wizard", "onboarding": "wizard", "multi-step": "wizard",
    "history": "audit-log", "activity": "audit-log", "log": "audit-log",
    "config": "settings", "preferences": "settings", "profile": "settings",
}


def _resolve_archetype(page: dict) -> tuple[str, tuple[str, str] | None]:
    raw = page.get("archetype")
    if is_renderable_archetype(raw):
        return raw, None
    aliased = _ALIAS.get((raw or "").strip().lower()) if raw else None
    if is_renderable_archetype(aliased):
        return aliased, (raw, aliased)
    fallback = page.get("type") if is_renderable_archetype(page.get("type")) else "list"
    return fallback, ((raw, fallback) if raw and raw != fallback else None)


def normalize_app_design(plan: dict) -> tuple[dict, dict]:
    pages = plan.get("pages") if isinstance(plan, dict) else None
    report = {"pages": []}
    if not isinstance(pages, list):
        return plan, report
    for page in pages:
        if not isinstance(page, dict):
            continue
        archetype, sub = _resolve_archetype(page)
        page["archetype"] = archetype
        kept, dropped = [], []
        for f in page.get("features") or []:
            (kept if is_renderable_feature(f) else dropped).append(f)
        page["features"] = kept
        report["pages"].append({
            "route": page.get("route"), "archetype": archetype,
            "substituted": sub, "kept_features": kept, "dropped_features": dropped,
        })
    return plan, report
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_app_design_guardrail.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/app_design_guardrail.py backend/tests/services/test_app_design_guardrail.py
git commit -m "feat(design): app-design guardrail (validate/normalize archetypes+features)"
```

---

### Task 3: Planner emits + sanitizes archetype/features

**Files:**
- Modify: `backend/agents/planner.py`
- Test: `backend/tests/agents/test_planner_design.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/test_planner_design.py
from agents.planner import _sanitize_page_design


def test_sanitize_keeps_renderable_drops_invalid():
    plan = {"pages": [
        {"route": "/t", "type": "list", "archetype": "kanban",
         "features": ["approval", "ghost", "sla-escalation"]},
        {"route": "/x", "type": "detail", "archetype": "made-up"},
    ]}
    out = _sanitize_page_design(plan)
    assert out["pages"][0]["archetype"] == "kanban"
    assert out["pages"][0]["features"] == ["approval"]
    # invalid archetype normalized to the page type
    assert out["pages"][1]["archetype"] == "detail"
    assert out["pages"][1]["features"] == []


def test_sanitize_safe_without_pages():
    assert _sanitize_page_design({}) == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/agents/test_planner_design.py -v`
Expected: FAIL with `ImportError: cannot import name '_sanitize_page_design'`.

- [ ] **Step 3: Implement the sanitizer + wire it + extend the prompt**

Add to `backend/agents/planner.py` (near `_sanitize_page_actions`):

```python
def _sanitize_page_design(plan: dict) -> dict:
    """Normalize per-page `archetype` + `features` against the capability catalog
    (mirrors the guardrail; runs at plan time so the schema agent sees clean
    values). Invalid archetype → the page's `type`; unsupported features dropped."""
    from services.app_design_guardrail import normalize_app_design
    if not isinstance(plan.get("pages"), list):
        return plan
    plan, _ = normalize_app_design(plan)
    return plan
```

Call it at the END of `_annotate_page_types`, right after the existing
`plan = _sanitize_page_actions(plan)` line (find it) and before `return plan`:

```python
    plan = _sanitize_page_design(plan)
    return plan
```

Then extend BOTH the `_ONESHOT_SYSTEM_PROMPT` and `PLANNER_SYSTEM_PROMPT` page
schemas. Locate the `"pages": [ ... ]` example in each and (a) add `archetype` +
`features` to the page object, (b) inject the catalog. For the oneshot prompt,
change the page example to:

```
  "pages": [
    {"name": "RequestsBoard", "route": "/requests", "type": "list",
     "archetype": "kanban", "entity": "Request",
     "features": ["status-pipeline", "approval"],
     "description": "Board of requests grouped by status",
     "actions": [{"label": "Approve", "workflow": "ApproveRequest", "kind": "row_action"}]}
  ],
```

And add a rules block to the prompt (after the PAGE RULES section), built from the
catalog so the model sees the menu. Append to the system prompt string:

```python
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + (
    "DESIGN THE APP — don't make every page a list. For each page pick the "
    "`archetype` that fits its purpose, and add `features` that fit the entity. "
    "Prefer these catalog names (others are allowed but will be normalized):\n"
    + __import__("services.app_design_catalog", fromlist=["catalog_for_prompt"]).catalog_for_prompt()
)
```

(Do the analogous append for `PLANNER_SYSTEM_PROMPT`.)

- [ ] **Step 4: Run to verify it passes + planner still parses**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/agents/test_planner_design.py tests/agents/test_planner.py tests/agents/test_planner_actions.py -v`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -c "import ast; ast.parse(open('agents/planner.py').read()); print('planner OK')"`
Expected: tests PASS; `planner OK`.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/planner.py backend/tests/agents/test_planner_design.py
git commit -m "feat(design): planner emits + sanitizes per-page archetype + features"
```

---

### Task 4: Archetype templates

**Files:**
- Modify: `backend/services/page_type_templates.py`
- Test: `backend/tests/services/test_page_type_templates.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_page_type_templates.py
from services.page_type_templates import template_for


def test_new_archetype_templates_exist_and_name_their_components():
    cases = {
        "kanban": "Kanban", "calendar": "Calendar", "inbox": "InspectorPanel",
        "report": "Chart", "wizard": "ApprovalStepper", "audit-log": "Timeline",
        "settings": "Tabs",
    }
    for archetype, must_mention in cases.items():
        block = template_for(archetype)
        assert block and block != template_for("___nonexistent___")
        assert must_mention in block, (archetype, must_mention)


def test_unknown_still_generic():
    from services.page_type_templates import _GENERIC
    assert template_for("___nope___") == _GENERIC
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_page_type_templates.py -v`
Expected: FAIL — new archetypes return `_GENERIC` (so `must_mention` not present).

- [ ] **Step 3: Implement**

In `backend/services/page_type_templates.py`, add these template strings (mirror the existing `_LIST`/`_DASHBOARD` format — each names required components + DO-NOT-USE), then register them in `_TEMPLATES`:

```python
_KANBAN = """\
KANBAN BOARD page. Structure:
Stack { Row { Heading, FilterBar }, Kanban }
- Kanban: bind a list dataSource; group columns by the entity's `status` field;
  each card shows the record's title + a key field.
- DO NOT use: Table, DataGrid, Form, MetricTile.
"""

_CALENDAR = """\
CALENDAR page. Structure:
Stack { Heading, Calendar }
- Calendar: bind a list dataSource; map the entity's date field to events; colour
  by status if present.
- DO NOT use: Table, DataGrid, Form, MetricTile.
"""

_INBOX = """\
INBOX (split list + reading pane) page. Structure:
Split { left: DataGrid(bind list, compact), right: InspectorPanel(selected record) }
- Heading above the Split.
- DO NOT use: full-width Table, MetricTile grid, Form at top level.
"""

_REPORT = """\
REPORT / ANALYTICS page. Structure:
Stack { Row { Heading, DateRangePicker }, Grid { Stat x3-4 }, Card { Chart }, Card { Table } }
- Chart: pick line/bar/area to fit the metric. Stats summarise; Table shows detail.
- DO NOT use: Form, Kanban, single big KeyValueList.
"""

_WIZARD = """\
WIZARD (multi-step) page. Structure:
Stack { ApprovalStepper(steps), Form(current-step fields), Row { Button:Back, Button:Next } }
- One Form section per step; ApprovalStepper shows progress.
- DO NOT use: Table, DataGrid, MetricTile.
"""

_AUDIT_LOG = """\
AUDIT-LOG / TIMELINE page. Structure:
Stack { Heading, Timeline }
- Timeline: bind a list dataSource ordered by time; each entry shows timestamp,
  actor, action. Optionally a Card { ActivityFeed } alongside.
- DO NOT use: Form, editable Table.
"""

_SETTINGS = """\
SETTINGS page. Structure:
Stack { Heading, Tabs { per-group Card { Form fields } }, Button:Save }
- Group related settings into tabs; each tab is a small Form.
- DO NOT use: DataGrid, Kanban, MetricTile.
"""
```

Then extend `_TEMPLATES`:

```python
_TEMPLATES = {
    **_TEMPLATES,
    "kanban": _KANBAN, "calendar": _CALENDAR, "inbox": _INBOX,
    "report": _REPORT, "wizard": _WIZARD, "audit-log": _AUDIT_LOG,
    "timeline": _AUDIT_LOG, "settings": _SETTINGS,
}
```

(If `_TEMPLATES` is defined as a literal, add the keys directly into that literal instead of the spread.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_page_type_templates.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/page_type_templates.py backend/tests/services/test_page_type_templates.py
git commit -m "feat(design): archetype templates (kanban/calendar/inbox/report/wizard/audit-log/settings)"
```

---

### Task 5: Wire `archetype` into the schema prompt

**Files:**
- Modify: `backend/services/schema_prompt.py` (where `template_for(page_type)` is called)
- Modify: `backend/agents/page_schema_agent.py` (pass `archetype` through the page brief)

READ both files first. In `schema_prompt.build_schema_prompt`, find where `template_for(...)` is called with the page type. Change it to prefer the page's `archetype`:

```python
    _arch = (page_brief or {}).get("archetype") or page.get("archetype")
    _template_key = _arch if _arch else page_type    # archetype wins, else legacy type
    template_block = template_for(_template_key)
```

(Adjust variable names to the file's actuals — the goal: `template_for` receives the archetype when present.) If `reference_bank.load_exemplars(...)` is called with a page_type, pass `_template_key` there too so archetype-keyed exemplars (Task 6) load; if none exist it must return an empty list (graceful).

In `page_schema_agent.run_page_schema_agent` / `_generate_schema_for_page`, ensure the `page` dict's `archetype` reaches `build_schema_prompt` (it already passes `page`/`page_brief`; just confirm `archetype` is carried — add it to the `page_brief` dict if that dict is constructed by selecting fields).

- [ ] **Step 1: Verify the wiring carries archetype (add a focused test)**

```python
# backend/tests/services/test_schema_prompt_archetype.py
from services.schema_prompt import build_schema_prompt


def test_archetype_drives_template_block():
    plan = {"name": "X", "entities": {}, "pages": []}
    page_plan = {**plan, "page_type": "list", "entity": {},
                 "page": {"route": "/b", "type": "list", "archetype": "kanban"}}
    prompt = build_schema_prompt(page_plan, page_brief={"route": "/b", "archetype": "kanban", "page_type": "list"}, domain="general")
    assert "KANBAN BOARD" in prompt        # the kanban template block was injected
```

(Adjust the `build_schema_prompt` call to the real signature you find in the file. The assertion that matters: when archetype="kanban", the kanban template text appears in the prompt.)

- [ ] **Step 2: Run to verify it fails, then wire, then pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_schema_prompt_archetype.py -v`
Expected: FAIL first (kanban text absent), PASS after wiring.

- [ ] **Step 3: Verify nothing regressed + parses**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_schema_pipeline.py tests/services/test_schema_pipeline_page_driven.py tests/agents/test_page_schema_agent_shell.py -v`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -c "import ast; ast.parse(open('services/schema_prompt.py').read()); ast.parse(open('agents/page_schema_agent.py').read()); print('OK')"`
Expected: PASS + `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/services/schema_prompt.py backend/agents/page_schema_agent.py backend/tests/services/test_schema_prompt_archetype.py
git commit -m "feat(design): wire page archetype into the schema prompt template selection"
```

---

### Task 6: Domain-mapping fix (theme + layout stop collapsing)

**Files:**
- Modify: `backend/services/industry_design.py`
- Test: `backend/tests/services/test_industry_design_alias.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_industry_design_alias.py
from services.industry_design import get_industry_design


def test_coarse_domains_no_longer_all_ocean():
    themes = {d: get_industry_design(d)["theme"] for d in ["general","hr","fintech","healthcare","saas"]}
    assert themes["hr"] == "hr"
    assert themes["fintech"] == "finance"
    assert themes["healthcare"] == "healthcare"
    assert themes["saas"] == "sharp"
    # at least 3 distinct themes across the coarse domains (no longer all "ocean")
    assert len(set(themes.values())) >= 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_industry_design_alias.py -v`
Expected: FAIL — all coarse domains currently resolve to `"ocean"`.

- [ ] **Step 3: Implement**

In `backend/services/industry_design.py`, add a coarse→canonical alias map and apply it at the top of `get_industry_design`:

```python
# Planner emits coarse lowercase domains; map them to the Title-Case keys used by
# DOMAIN_THEME / DOMAIN_LAYOUT so theme + layout stop collapsing to the default.
_DOMAIN_ALIAS: dict[str, str] = {
    "hr": "Human Resources",
    "fintech": "Finance & Banking",
    "finance": "Finance & Banking",
    "healthcare": "Healthcare",
    "saas": "Government",        # "sharp" theme — crisp, dense SaaS look
    "ecommerce": "E-Commerce & Retail",
    "logistics": "Logistics & Supply Chain",
    "education": "Education",
    "crm": "CRM",
    "sales": "Sales",
    # "general" intentionally has no alias → keeps the neutral "ocean" default.
}
```

Then at the start of `get_industry_design(domain)`:

```python
    domain = _DOMAIN_ALIAS.get((domain or "").strip().lower(), domain)
```

(Note: `Government` maps to the `"sharp"` theme in `DOMAIN_THEME` — verify; if not, point `saas` at whichever existing key resolves to a distinct crisp theme. The test asserts `saas → "sharp"`.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_industry_design_alias.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/industry_design.py backend/tests/services/test_industry_design_alias.py
git commit -m "fix(design): map coarse planner domains to themes/layouts (stop default-collapse)"
```

---

### Task 7: Pipeline wiring + design report

**Files:**
- Modify: `backend/routers/generate.py` (after the planner result is available in the prompt pipeline) — OR `backend/services/schema_pipeline.py` if the plan is normalized closer to page emit.

The planner already runs `_sanitize_page_design` (Task 3), so the plan reaching the pipeline is clean. This task just **writes the report** for inspection. READ where `_run_relay_pipeline` obtains the `plan` and `output_dir`. After the plan is finalized (before the frontend/schema phase), add:

```python
        # Emit the app-design report (archetypes + features chosen, after guardrail).
        try:
            from services.app_design_guardrail import normalize_app_design
            import json as _json
            _plan2, _design_report = normalize_app_design(plan)
            (Path(output_dir) / "app-design-report.json").write_text(_json.dumps(_design_report, indent=2))
            _archs = {p.get("archetype") for p in (plan.get("pages") or [])}
            yield sse_event("log", {"text": f"[Design] archetypes: {sorted(a for a in _archs if a)}"})
        except Exception as _d_ex:
            yield sse_event("log", {"text": f"[Design] report skipped: {_d_ex}"})
```

- [ ] **Step 1: Add the block + verify parse/import**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -c "import ast; ast.parse(open('routers/generate.py').read()); print('generate.py OK')"`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -c "from services.app_design_guardrail import normalize_app_design; print('ok')"`
Expected: both OK.

- [ ] **Step 2: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(design): emit app-design-report.json in the prompt pipeline"
```

---

### Task 8: End-to-end integration test

**Files:**
- Test: `backend/tests/services/test_app_design_guardrail.py` (add a catalog↔guardrail↔template integration test)

- [ ] **Step 1: Write the test**

```python
def test_planner_choices_flow_to_renderable_template():
    from services.app_design_guardrail import normalize_app_design
    from services.page_type_templates import template_for
    # A "help desk"-style plan the planner might emit
    plan = {"pages": [
        {"route": "/tickets", "type": "list", "archetype": "inbox", "features": ["status-pipeline","sla-escalation"]},
        {"route": "/reports", "type": "list", "archetype": "analytics", "features": []},   # alias → report
        {"route": "/board", "type": "list", "archetype": "kanban", "features": []},
    ]}
    plan, report = normalize_app_design(plan)
    archetypes = [p["archetype"] for p in plan["pages"]]
    assert archetypes == ["inbox", "report", "kanban"]            # alias normalized
    assert plan["pages"][0]["features"] == ["status-pipeline"]    # sla-escalation (SP2) dropped
    # every chosen archetype has a real template
    for a in archetypes:
        assert "DO NOT use" in template_for(a)
```

- [ ] **Step 2: Run the full SP1 suite**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_app_design_catalog.py tests/services/test_app_design_guardrail.py tests/services/test_page_type_templates.py tests/services/test_industry_design_alias.py tests/agents/test_planner_design.py tests/services/test_schema_prompt_archetype.py -v`
Expected: ALL pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/test_app_design_guardrail.py
git commit -m "test(design): end-to-end archetype/feature flow (catalog→guardrail→template)"
```

---

## Manual verification (after all tasks)

1. Restart the backend (loads the planner + pipeline changes).
2. Generate two contrasting prompt apps — e.g. **"a help desk / support ticket system"** and **"a warehouse inventory tracker."**
3. At plan time, confirm the plans carry *different* `archetype`s (e.g. inbox/kanban/report vs report/timeline) and `features`.
4. Inspect `output/<id>/app-design-report.json` — see the chosen archetypes, any substitutions, kept/dropped features.
5. Open the generated page schemas: confirm the chosen archetypes rendered (a Kanban/Calendar/Timeline/Chart present, not list/detail/form everywhere) and the binding/CRUD still works.
6. Confirm the two apps no longer look/behave identical, and theme differs by domain.

## Deferred within SP1 (fast-follow, not blocking)

- **Archetype exemplars** (`backend/fixtures/exemplars/*.json`) and **schema_rules**
  entries per archetype. The spec lists these alongside templates; this plan ships
  the **templates** (the primary steering mechanism — they name the exact
  components + structure, which is what makes the schema agent compose the
  archetype). Exemplars/rules are additive *fidelity* boosters and can land as a
  quick fast-follow once a live run shows where the schema agent needs extra
  nudging. Task 5 already makes `reference_bank` archetype-aware with graceful
  empty fallback, so adding exemplars later requires no rewiring.

## Out of scope (later sub-projects)

- New runtime engine features (SLA-breach escalation, auto-reorder) — **SP2**.
- IA / nav-grouping / dashboard-module composition variety — **SP3**.
- Figma path; new UI components.
