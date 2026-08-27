# Page-Type Classification + Template-Guided Schema Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/login` emit a `Form` with two `Input`s, `/requests/new` emit a real form (not a dashboard), `/users/[id]` emit a detail layout, and `/users` emit a list — by classifying every route into one of six page types and feeding the schema agent a type-specific template skeleton.

**Architecture:** Three workstreams, ~7 tasks.

1. **WS-A — Page-type classifier.** Deterministic Python function that maps a route + entity hint to one of six types (`form`, `list`, `detail`, `auth`, `dashboard`, `error`). Runs as a post-processor on `plan.pages` so every page gets a `type` field.
2. **WS-B — Per-type template guidance in the schema prompt.** Map each type to a short component-skeleton instruction the LLM follows.
3. **WS-C — Validation gate.** Snapshot tests asserting `/login` → `Form{Input×2, Button}`, `/requests/new` → no `MetricTile`, `/users/[id]` → `KeyValueList` or `Heading+...`, etc.

**Tech Stack:** Python 3.11 — pure-Python classifier + prompt-builder edits, no new deps.

**Reference state today:**
- `services/schema_pipeline.py:53` already iterates `plan.pages` and calls `page_schema_agent` once per route. Per-page generation is wired.
- `agents/page_schema_agent.py:130–144` passes `page_brief.archetype` + `page_plan.page_type` from `page.get("type")` / `page.get("archetype")`. Plumbing exists but the planner doesn't populate the fields → both default to `"generic"`.
- `services/schema_prompt.py:build_schema_prompt(page_plan, page_brief=..., ...)` receives `page_brief["archetype"]` but doesn't branch on it.
- Diagnostic baseline (db17s1zl): of 14 declared pages, only 5 schemas exist on disk, and `/requests/new` was rendered as a dashboard with `Hero + Grid(MetricTile×4) + Card{Table}` instead of `Form{Input, Input, Button}`. After commits `20c35e9` + `ea5485d` + `06c6bc9` the **path resolution** is fixed; this plan addresses the **semantic** classification.

---

## File Structure Overview

### New files

| File | Responsibility |
|---|---|
| `backend/services/page_type_classifier.py` | `classify_page(route, name, description, entity) -> str` returning `"form" \| "list" \| "detail" \| "auth" \| "dashboard" \| "error"` |
| `backend/services/page_type_templates.py` | `template_for(page_type) -> str` returning a short component-skeleton instruction block injected into the prompt |
| `backend/tests/services/test_page_type_classifier.py` | Unit tests covering every classification rule |
| `backend/tests/services/test_page_type_templates.py` | Snapshot tests covering the template strings (cheap regression net) |
| `backend/tests/integration/test_route_to_template.py` | End-to-end-ish: `/login` plan entry → classifier → template selection → expected component vocabulary |

### Modified files

| File | Change |
|---|---|
| `backend/agents/planner.py` (or wherever the planner emits `plan.pages`) | After plan is built, run `classify_page` on every entry; write `type` field. |
| `backend/agents/page_schema_agent.py` | Pass `page_type` into `build_schema_prompt`. |
| `backend/services/schema_prompt.py` | Inject `template_for(page_type)` into the prompt. |
| `backend/tests/services/test_schema_prompt_registry.py` | Add a test confirming the prompt contains the template block when a `type` is given. |

---

## WS-A — Classifier

### Task 1: page_type_classifier module

**Files:**
- Create: `backend/services/page_type_classifier.py`
- Test: `backend/tests/services/test_page_type_classifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/services/test_page_type_classifier.py
import pytest
from services.page_type_classifier import classify_page

# Auth — matched by exact route or "login/signup/forgot/reset" tokens
@pytest.mark.parametrize("route", ["/login", "/signup", "/forgot-password", "/reset-password", "/auth/login"])
def test_auth(route):
    assert classify_page(route, name="", description="", entity=None) == "auth"

# Forms — last segment is new/create/edit, OR description says "form"
@pytest.mark.parametrize("route", ["/requests/new", "/users/new", "/products/create", "/requests/123/edit"])
def test_form_by_route(route):
    assert classify_page(route, name="", description="", entity=None) == "form"

def test_form_by_description():
    """Description trumps when the route is otherwise ambiguous."""
    assert classify_page("/contact", name="Contact", description="Contact form for inquiries", entity=None) == "form"

# Detail — dynamic segment ([id], :id, [slug])
@pytest.mark.parametrize("route", ["/users/[id]", "/products/[slug]", "/orders/:orderId", "/users/[id]/profile"])
def test_detail(route):
    assert classify_page(route, name="", description="", entity="User") == "detail"

# List — plural entity at end, or "list" in description
@pytest.mark.parametrize("route", ["/users", "/products", "/orders", "/leave-requests"])
def test_list(route):
    assert classify_page(route, name="", description="List of items", entity="User") == "list"

# Dashboard — root or explicit /dashboard, or description mentions overview/metrics
def test_dashboard_root():
    assert classify_page("/", name="", description="", entity=None) == "dashboard"

def test_dashboard_explicit():
    assert classify_page("/dashboard", name="", description="", entity=None) == "dashboard"

def test_dashboard_by_description():
    """Single-segment routes with overview-style copy → dashboard."""
    assert classify_page("/analytics", name="", description="Overview of usage metrics", entity=None) == "dashboard"

# Error / not-found
@pytest.mark.parametrize("route", ["/error", "/not-found", "/404", "/500"])
def test_error(route):
    assert classify_page(route, name="", description="", entity=None) == "error"

# Fallback — when nothing else matches, default to "list" (safest default
# for routes like /settings or /about that we don't have explicit handling for)
def test_fallback_to_list():
    assert classify_page("/settings", name="", description="", entity=None) == "list"

# Precedence: error > auth > form > detail > list > dashboard > fallback
def test_error_beats_form():
    """An /error/new route is still an error page."""
    assert classify_page("/error", name="", description="user creation form", entity="User") == "error"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd backend && pytest tests/services/test_page_type_classifier.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/services/page_type_classifier.py
"""Deterministic classification of a plan.pages entry into one of six page
types. Drives template selection in the schema prompt so the LLM emits a
form on /login, a list on /users, a detail on /users/[id], etc. — not a
dashboard everywhere.

Precedence (first match wins):
  error > auth > form > detail > list-or-dashboard > fallback(list)
"""
from __future__ import annotations
import re
from typing import Literal


PageType = Literal["form", "list", "detail", "auth", "dashboard", "error"]


_AUTH_RE = re.compile(
    r"(?:^|/)(?:login|signup|sign-?in|sign-?up|forgot[- ]?password|reset[- ]?password|register)(?:$|/)",
    re.I,
)
_FORM_SUFFIX_RE = re.compile(r"/(?:new|create|edit)$", re.I)
_DYNAMIC_SEG_RE = re.compile(r"\[\w+\]|:\w+")
_ERROR_ROUTES = {"/error", "/not-found", "/404", "/500"}

_DASHBOARD_KEYWORDS = ("dashboard", "overview", "summary", "metrics", "analytics")
_FORM_KEYWORDS = ("form", " form", "input", "create", "submit")
_LIST_KEYWORDS = ("list", "browse", "catalog", "directory")


def classify_page(
    route: str,
    name: str = "",
    description: str = "",
    entity: str | None = None,
) -> PageType:
    r = (route or "").strip()
    desc_lower = (description or "").lower()

    # 1. Error pages — never reclassify.
    if r in _ERROR_ROUTES or r.lstrip("/") in {"error", "not-found"}:
        return "error"

    # 2. Auth pages.
    if _AUTH_RE.search(r):
        return "auth"

    # 3. Form pages — route suffix wins; description is a softer signal.
    if _FORM_SUFFIX_RE.search(r):
        return "form"
    if any(k in desc_lower for k in _FORM_KEYWORDS):
        return "form"

    # 4. Detail — dynamic route segment.
    if _DYNAMIC_SEG_RE.search(r):
        return "detail"

    # 5. Dashboard — root, explicit, or overview-style description.
    if r in ("/", "/home", "/dashboard"):
        return "dashboard"
    if any(k in desc_lower for k in _DASHBOARD_KEYWORDS):
        return "dashboard"

    # 6. List vs fallback.
    if any(k in desc_lower for k in _LIST_KEYWORDS):
        return "list"
    # Routes with an entity hint AND a plural-looking segment → list
    if entity and r.rstrip("/").split("/")[-1].endswith("s"):
        return "list"

    # Fallback — settings / about / generic single-segment routes.
    return "list"
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && pytest tests/services/test_page_type_classifier.py -v
```

- [ ] **Step 5: Commit**

```
feat(schema): page-type classifier — route+description → form/list/detail/auth/dashboard/error
```
HEREDOC + Co-Authored-By trailer.

### Task 2: Wire classifier into the planner output

**Files:**
- Modify: `backend/agents/planner.py` (find where `plan.pages` is finalised)
- Add: tests covering the wire-up

- [ ] **Step 1: Locate the planner output point**

```bash
grep -n "pages\b\|plan\[.pages.\]\|plan.pages\|emit_plan\|return plan" backend/agents/planner.py | head -20
```

Find the place where `pages` is added/finalised on the plan dict.

- [ ] **Step 2: Add a `_annotate_page_types(plan)` post-pass**

After plan is built and before it's returned/written, run:

```python
from services.page_type_classifier import classify_page

def _annotate_page_types(plan: dict) -> dict:
    """Add `type` to every page entry that doesn't already have one.
    Idempotent — pages with an explicit `type` are preserved."""
    for p in plan.get("pages") or []:
        if not isinstance(p, dict): continue
        if p.get("type"): continue
        p["type"] = classify_page(
            route=p.get("route", ""),
            name=p.get("name", ""),
            description=p.get("description", ""),
            entity=p.get("entity"),
        )
    return plan
```

Call it in whatever function builds and returns the final plan.

- [ ] **Step 3: Test the wire-up**

In `backend/tests/agents/test_planner.py` (create or extend):

```python
def test_planner_annotates_page_types():
    """Pages emitted by the planner gain a type field via the classifier."""
    from agents.planner import _annotate_page_types
    plan = {"pages": [
        {"route": "/", "name": "Home", "description": "", "entity": None},
        {"route": "/login", "name": "Login", "description": "", "entity": None},
        {"route": "/users/new", "name": "Create user", "description": "", "entity": "User"},
        {"route": "/users/[id]", "name": "User detail", "description": "", "entity": "User"},
        {"route": "/users", "name": "Users", "description": "Browse users", "entity": "User"},
    ]}
    annotated = _annotate_page_types(plan)
    types = [p["type"] for p in annotated["pages"]]
    assert types == ["dashboard", "auth", "form", "detail", "list"]


def test_annotate_preserves_explicit_type():
    from agents.planner import _annotate_page_types
    plan = {"pages": [{"route": "/x", "type": "custom"}]}
    annotated = _annotate_page_types(plan)
    assert annotated["pages"][0]["type"] == "custom"
```

- [ ] **Step 4: Run tests, commit**

```
feat(planner): annotate plan.pages with page_type via classifier
```

---

## WS-B — Template Guidance in the Prompt

### Task 3: page_type_templates module

**Files:**
- Create: `backend/services/page_type_templates.py`
- Test: `backend/tests/services/test_page_type_templates.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/services/test_page_type_templates.py
import pytest
from services.page_type_templates import template_for


@pytest.mark.parametrize("page_type", ["form", "list", "detail", "auth", "dashboard", "error"])
def test_returns_non_empty_block(page_type):
    t = template_for(page_type)
    assert isinstance(t, str)
    assert len(t) > 100


def test_form_template_demands_form_input_button():
    t = template_for("form").lower()
    assert "form" in t
    assert "input" in t
    assert "button" in t


def test_list_template_demands_table_or_datagrid():
    t = template_for("list").lower()
    assert "table" in t or "datagrid" in t


def test_detail_template_demands_keyvaluelist_or_heading():
    t = template_for("detail").lower()
    assert "keyvaluelist" in t or "heading" in t


def test_dashboard_template_demands_metric_tile():
    t = template_for("dashboard").lower()
    assert "metrictile" in t


def test_auth_template_demands_two_inputs():
    t = template_for("auth").lower()
    # auth pages need email + password inputs at minimum
    assert "input" in t


def test_error_template_demands_emptystate():
    t = template_for("error").lower()
    assert "emptystate" in t


def test_unknown_type_returns_generic():
    """Unknown page_type doesn't crash — emits a generic skeleton."""
    t = template_for("generic")
    assert isinstance(t, str)
    assert len(t) > 0
```

- [ ] **Step 2: Implement**

```python
# backend/services/page_type_templates.py
"""Per-page-type template guidance injected into the schema prompt.

Each function returns a short instruction block (not a full schema) that
nudges the LLM toward the right component vocabulary AND the right tree
shape. We keep the templates short — the LLM still has full creative
control over content, copy, ordering inside the skeleton.
"""
from __future__ import annotations


_FORM = """
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

_LIST = """
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

_DETAIL = """
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

_AUTH = """
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

_DASHBOARD = """
## PAGE TYPE: DASHBOARD

You MUST emit a `Hero` header, a `Grid` of `MetricTile`s for the top
KPIs, and one or more `Card`s with `Table` / `Chart` / `ActivityFeed`
for time-series or recent-activity content. This is the only page type
where `MetricTile` and `Chart` make sense at the top level.

Required shape:
```
Stack {
  Hero { headline, subhead, ctas }
  Grid { columns: 4, children: [ MetricTile×4 with delta/trend ] }
  Card { Heading + Table }                       // recent records
  Card { Heading + ActivityFeed }                // recent events (optional)
}
```
"""

_ERROR = """
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

_GENERIC = """
## PAGE TYPE: GENERIC

No specific template — emit whatever composition best fits the page
description. Prefer composing from primitives (Stack, Row, Grid, Card)
plus a small set of display components (Heading, Text, Button).
"""


_TEMPLATES = {
    "form": _FORM,
    "list": _LIST,
    "detail": _DETAIL,
    "auth": _AUTH,
    "dashboard": _DASHBOARD,
    "error": _ERROR,
}


def template_for(page_type: str) -> str:
    return _TEMPLATES.get(page_type, _GENERIC)
```

- [ ] **Step 3: Tests pass, commit**

```
feat(schema): per-page-type template guidance — form/list/detail/auth/dashboard/error
```

### Task 4: Inject template into build_schema_prompt

**Files:**
- Modify: `backend/services/schema_prompt.py` — `build_schema_prompt`
- Modify: `backend/agents/page_schema_agent.py` — pass `page_type` through

- [ ] **Step 1: Modify build_schema_prompt to accept + inject a page_type**

In `schema_prompt.py`, near where `build_schema_prompt` builds the final prompt string, find a stable insertion point AFTER the library descriptor / tier-2 components guidance and BEFORE the final user-task block. Inject:

```python
from services.page_type_templates import template_for
# ...
page_type = (page_brief or {}).get("page_type") or page_plan.get("page_type") or "generic"
if page_type and page_type != "generic":
    prompt += "\n\n" + template_for(page_type)
```

(Exact placement depends on the function's current shape — read the file and find where `prompt += "\n\n" + TIER2_COMPONENTS_GUIDANCE` lands, then insert the new line right after that.)

- [ ] **Step 2: page_schema_agent threads page_type into page_brief**

In `page_schema_agent.py` at the `page_brief = {...}` construction, ADD:

```python
page_brief = {
    "route": page.get("route", f"/{slug}"),
    "role": page.get("role") or "",
    "archetype": page.get("archetype") or page.get("type") or "generic",
    "page_type": page.get("type") or "generic",   # NEW
}
```

- [ ] **Step 3: Test the prompt actually contains the template**

In `backend/tests/services/test_schema_prompt_registry.py`, add:

```python
def test_prompt_includes_form_template_for_form_pages():
    from services.schema_prompt import build_schema_prompt
    page_plan = {"pages": [], "page_type": "form", "page": {"route": "/users/new"}}
    page_brief = {"route": "/users/new", "role": "", "archetype": "form", "page_type": "form"}
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: FORM" in prompt
    assert "MetricTile" in prompt or "MetricTile`" in prompt   # in the "DO NOT" section


def test_prompt_includes_auth_template_for_auth_pages():
    from services.schema_prompt import build_schema_prompt
    page_plan = {"pages": [], "page_type": "auth", "page": {"route": "/login"}}
    page_brief = {"route": "/login", "role": "", "archetype": "auth", "page_type": "auth"}
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: AUTH" in prompt


def test_no_template_block_for_generic():
    from services.schema_prompt import build_schema_prompt
    page_plan = {"pages": [], "page_type": "generic", "page": {"route": "/about"}}
    page_brief = {"route": "/about", "role": "", "archetype": "generic", "page_type": "generic"}
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE:" not in prompt
```

- [ ] **Step 4: Commit**

```
feat(schema): inject per-page-type template into build_schema_prompt
```

---

## WS-C — Validation

### Task 5: Coverage gate — every plan.pages route has a schema file

**Files:**
- Create: `backend/services/phase_gates.py` (extend if present) — add `check_pages_coverage(output_dir, plan) -> dict`
- Modify: `backend/routers/generate.py` — call the gate after `run_schema_frontend_pipeline`

- [ ] **Step 1: Test + impl**

In `phase_gates.py` add:

```python
def check_pages_coverage(output_dir: str, plan: dict) -> dict:
    """Every page declared in plan.pages must have a schema file on disk.
    Returns {"passed": bool, "missing": [route, ...]}.
    """
    from pathlib import Path
    out = Path(output_dir)
    pages = (plan or {}).get("pages") or []
    missing: list[str] = []
    for p in pages:
        if not isinstance(p, dict): continue
        route = p.get("route", "")
        # Re-derive the schema file from the route in the same way as nav_flow_emitter
        from services.nav_flow_emitter import _schema_file_from_route
        sf = _schema_file_from_route(route)
        if not (out / sf).exists():
            missing.append(route)
    return {"passed": not missing, "missing": missing}
```

Add a test asserting it correctly flags missing pages.

- [ ] **Step 2: Wire the gate**

In `routers/generate.py`'s `_run_relay_pipeline` (in the SCHEMA_MODE_ENABLED branch around line 690), after the existing CTA and PD gates, add:

```python
        try:
            from services.phase_gates import check_pages_coverage
            cov = check_pages_coverage(output_dir, plan)
            if not cov["passed"]:
                yield sse_event("log", {
                    "text": f"[Coverage Gate] {len(cov['missing'])} page(s) have no schema: {cov['missing']}"
                })
                # Optional: re-run schema_frontend_pipeline once with the
                # missing pages emphasised. For now we just log.
            else:
                yield sse_event("log", {"text": "[Coverage Gate] ✓ Every plan.pages route has a schema"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Coverage Gate] check failed: {e}"})
```

- [ ] **Step 3: Commit**

```
feat(gates): check_pages_coverage — every plan route must have a schema file
```

### Task 6: Integration smoke

**Files:**
- Create: `backend/tests/integration/test_page_type_end_to_end.py`

- [ ] **Step 1: Test**

```python
"""Integration: classifier + planner annotation + prompt building chain.
This is NOT a real LLM call — it just verifies the data flow is correct."""

def test_form_route_flows_through_to_prompt():
    from agents.planner import _annotate_page_types
    from services.schema_prompt import build_schema_prompt

    plan = {"pages": [{"route": "/requests/new", "name": "New Request", "description": "", "entity": "LeaveRequest"}]}
    _annotate_page_types(plan)
    page = plan["pages"][0]
    assert page["type"] == "form"

    page_brief = {"route": page["route"], "role": "", "archetype": "form", "page_type": "form"}
    page_plan = {**plan, "page_type": "form", "page": page}
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain="general")
    assert "PAGE TYPE: FORM" in prompt


def test_login_route_picks_up_auth_template():
    from agents.planner import _annotate_page_types
    from services.schema_prompt import build_schema_prompt

    plan = {"pages": [{"route": "/login", "name": "Login", "description": "Login page", "entity": None}]}
    _annotate_page_types(plan)
    assert plan["pages"][0]["type"] == "auth"

    page = plan["pages"][0]
    prompt = build_schema_prompt(
        {**plan, "page_type": "auth", "page": page},
        page_brief={"route": "/login", "role": "", "archetype": "auth", "page_type": "auth"},
        domain="general",
    )
    assert "PAGE TYPE: AUTH" in prompt
```

- [ ] **Step 2: Run + commit**

```
test(integration): page-type classifier flows through to prompt template
```

---

## Manual verification (Task 7 — defer to a single dispatch)

After all the commits land, fire a real generation against any project (e.g. db17s1zl) and inspect:

1. `output/<short_id>/src/schemas/login.json` — should contain `Form` with two `Input`s.
2. `output/<short_id>/src/schemas/signup.json` — same shape.
3. `output/<short_id>/src/schemas/requests/new.json` — should contain `Form` with leave-request fields (NOT a `Hero + MetricTile` grid).
4. `output/<short_id>/src/schemas/users/detail.json` — should contain `KeyValueList`.
5. SSE log should show `[Coverage Gate] ✓ Every plan.pages route has a schema`.

If `/requests/new` still emits a dashboard, the LLM is ignoring the template — likely root cause: the template block is being placed too early or too late in the prompt. Iterate the placement in WS-B Task 4 Step 1.

---

## Sequencing

| Step | Time | Notes |
|---|---|---|
| WS-A T1 (classifier) | 30 min | Pure-Python, TDD, low risk |
| WS-A T2 (planner wire-up) | 15 min | One-line addition where plan is finalised |
| WS-B T3 (templates) | 30 min | 6 string constants + dict lookup |
| WS-B T4 (prompt injection) | 30 min | Touches schema_prompt + page_schema_agent |
| WS-C T5 (coverage gate) | 20 min | Reuses _schema_file_from_route |
| WS-C T6 (integration smoke) | 15 min | Pure-Python end-to-end |
| Manual verify (T7) | 15 min | Real generation |

**Total: ~2.5 hours.**

---

## Self-Review

- **Spec coverage:** Six rules in the classifier (auth/form/detail/list/dashboard/error/fallback), six templates in the prompt, one coverage gate. Maps to the diagnosis: forms ARE generated for form routes; lists for list routes; details for detail routes.
- **Placeholder scan:** No `TBD`. Two manual-judgement steps documented: WS-B T4 prompt-injection placement (the implementer reads the existing prompt to choose the right insertion point), and WS-C T6 manual schema audit.
- **Type consistency:** `classify_page(route, name, description, entity) -> PageType` literal stays consistent across the classifier, planner annotation, prompt builder, and coverage gate. `template_for(page_type) -> str` returns whatever string the prompt builder appends.
- **Risk callouts:** WS-B T4 has the highest integration risk — placing the template block in the wrong spot of the prompt can cause the LLM to ignore it. Mitigation: the prompt tests in WS-B T4 Step 3 assert `"PAGE TYPE: FORM" in prompt` (presence), but a smarter test would assert it appears in the LAST 20% of the prompt where instructions weigh most. Add that if the first manual generation run shows the template being ignored.
