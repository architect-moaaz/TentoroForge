# Post-Generation Validate → Repair Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** A user-triggered, post-generation action that BOOTS the generated app, drives a headless browser to crawl every route and click every actionable button, produces a structured findings report, feeds the findings into deterministic guards + a fix agent, and re-validates until clean (or N rounds).

**Why:** QA and `next build` only see source; a click's correctness lives in the runtime chain (has-action → target-resolves → dispatch-wired → feedback). Only a real boot + click-through observes it. This is the single mechanism that catches the "buttons do nothing / 404 on click" class.

**Architecture:** Four layers — (1) a deterministic *static* auditor that catches most dead-button/dead-nav cases with no browser (Slice 0), (2) a runtime harness that boots the app + Playwright-crawls it into a findings report (Slice 1), (3) a repair dispatcher that routes each finding to a deterministic guard or a scoped fix agent (Slice 2), (4) the loop + user trigger + report UI (Slice 3).

**Tech:** Python pipeline (backend/services) + Playwright (Node, runs against the booted Next app) + existing guards (nav_guard, schema_binding canonicalizer). Backend tests: `/usr/local/bin/python3 -m pytest` from `backend/`. The browser/boot layers can't be unit-tested here — verified by running against a real generated app.

---

## Findings schema (the contract between validate and repair)

```json
{ "findings": [
  { "type": "route_404", "route": "/calendar", "source": "nav", "detail": "no page schema" },
  { "type": "dead_button", "route": "/reservations", "buttonLabel": "Approve", "reason": "no action prop" },
  { "type": "workflow_unresolved", "route": "/requests", "workflow": "createLeaveRequest", "detail": "not in runtime cache" },
  { "type": "render_error", "route": "/timeline", "detail": "console: Cannot read 'map' of undefined" },
  { "type": "dispatch_failed", "route": "/requests", "buttonLabel": "Approve", "status": 404, "detail": "Workflow not found" },
  { "type": "form_insert_failed", "route": "/reservations/new", "entity": "Reservation", "detail": "null value in checkInDate" }
] }
```

## Repair routing (finding → fixer)

| Finding | Fixer | Kind |
|---|---|---|
| route_404 (nav) | `nav_guard.guard_nav_targets` | deterministic |
| workflow_unresolved | `schema_binding.canonicalize_and_guard_workflow_buttons` | deterministic |
| dead_button (no action) | `button_audit` static wire, else flag | deterministic + report |
| form_insert_failed | binding validators + registry field check | deterministic |
| render_error / other | scoped **fix agent** (given the route + error) | LLM |

---

### Slice 0: Deterministic button-action auditor (no browser) — DO FIRST

**Files:** Create `backend/services/button_audit.py`, `backend/tests/test_button_audit.py`.

Catches the biggest "buttons do nothing" cause statically: an actionable-looking Button with NO resolvable action. Auto-wires the confident cases; reports the rest.

- [ ] **Step 1: failing test** — `audit_button_actions(schema, known_routes, workflow_index)` returns findings + auto-wires.

```python
from services.button_audit import audit_button_actions
IDX = {"exact": ["CreateReservation"], "norm": {"createreservation": "CreateReservation"}}
ROUTES = ["/reservations", "/reservations/new", "/reservations/[id]"]

def _btn(label, **p): return {"type":"Button","props":{"label":label, **p}}
def _tree(*b): return {"root":{"type":"Stack","children":list(b)}}

def test_flags_button_with_no_action():
    s=_tree(_btn("Approve"))                       # no navigate/workflow/submit
    out,f = audit_button_actions(s, ROUTES, IDX)
    assert any(x["type"]=="dead_button" and x["buttonLabel"]=="Approve" for x in f)

def test_autowires_new_button_to_create_route():
    s=_tree(_btn("New Reservation"))
    out,f = audit_button_actions(s, ROUTES, IDX)
    assert out["root"]["children"][0]["props"].get("navigate")=="/reservations/new"

def test_ok_button_not_flagged():
    s=_tree(_btn("Guests", navigate="/reservations"))
    out,f = audit_button_actions(s, ROUTES, IDX)
    assert f==[]
```

- [ ] **Step 2** run → fail. **Step 3** implement: a Button is "actionable" if it isn't purely display; it's OK if it has `navigate` (resolvable), `workflow` (resolvable via index), `submit`, `onClick`, or is a Cancel/Back in a form. No action → try to wire: label "New/Add <Entity>" + a matching `/entity/new` route → set navigate; label matches a workflow name → set workflow; else emit a `dead_button` finding. **Step 4** run → pass. **Step 5** wire into the binding pass (after nav-guard) + commit.

### Slice 1: Runtime validation harness (boot + crawl)

**Files:** Create `backend/services/validate_harness.py` + `backend/scripts/crawl.mjs` (Playwright).

- [ ] Boot the app: run `start.sh` in the app dir, poll `http://localhost:PORT` until ready (or fail with logs). Reuse the app's own DB (seeded).
- [ ] `crawl.mjs`: read `src/schemas/registry.ts` route list; for each route — `page.goto`, collect console errors + HTTP 404s; find every `[data-*]` button/link, click, capture nav result + network response for `/api/workflows/*` and `/api/data/*`; emit findings JSON to stdout.
- [ ] `validate_harness.run(app_dir) -> findings`: orchestrate boot → crawl → teardown; structural test asserts it shells out + parses findings; real validation by running on `output/4h9jckmc`.

### Slice 2: Repair dispatcher

**Files:** Create `backend/services/repair_dispatcher.py` + tests.

- [ ] `dispatch_repairs(app_dir, findings) -> summary`: route each finding per the table above; deterministic fixers run in-process; `render_error`/unknown go to a scoped fix agent (prompt = route + error + the page schema). Idempotent; returns per-finding disposition. TDD the routing with synthetic findings (deterministic fixers only; agent mocked).

### Slice 3: Loop + trigger + report

**Files:** Modify `backend/routers/generate.py` (or a new `routers/validate.py`), add SSE events + UI action.

- [ ] `validate_and_repair(app_dir, max_rounds=3)`: loop `run harness → dispatch_repairs → if clean or no-progress stop`. Guard against thrash (stop if the same finding recurs). Stream progress + a final report.
- [ ] Expose a **"Test run & validate"** action after generation completes; surface the report (pages OK/broken, buttons fixed, remaining issues).
- [ ] End-to-end: run on a fresh generation; confirm dead buttons + 404s drop to ~0 across rounds.

---

## Risks
- **Boot cost** (~1–2 min) + Playwright dep — opt-in only, never blocks generation.
- **Fix-agent thrash** — cap rounds + stop on recurring findings; prefer deterministic fixers first.
- **Flaky clicks** — crawl is best-effort per button; log skips, never fail the whole run on one button.
- **Env**: needs Node/Playwright + a running Postgres; degrade gracefully (report "harness unavailable") if absent.
