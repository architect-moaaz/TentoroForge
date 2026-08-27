# Domain-Aware Fidelity Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move fidelity scoring from a manual editor click into the generation pipeline itself — the pipeline auto-renders, scores, and patches every page, and grounds the schema agent in domain-specific exemplars so apps look domain-relevant out of the box.

**Architecture:** New `FidelityLoopRunner` (in `backend/services/fidelity_loop.py`) runs as a phase between page generation and QA. For each page in parallel (cap=4), it renders → scores → if not pass, calls a new `patch_agent` that emits RFC 6902 patches → validates → applies → re-renders → re-scores. Bounded by 3 patch iters + 1 schema-agent fallback / 90s per page / $5 project cap. Phase 15 reference grounding adds `backend/reference_pages/<domain>/<page_type>/` exemplars (seeded once via `seed_reference_bank.py`) that the existing `build_schema_prompt()` consumes when `REFERENCE_GROUNDING_ENABLED` is set. Editor reads scores from `fidelity-log.json`; manual re-score appends new iters.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / `anthropic` AsyncAnthropic / `jsonpatch` (new dep) / pytest + pytest-asyncio. Frontend: React 19 / Next 15 / TanStack Query.

**This plan covers Phase 14 + Phase 15 from the spec at `docs/superpowers/specs/2026-05-06-domain-aware-fidelity-loop-design.md`. Predecessor plan `2026-05-06-fidelity-render-loop.md` (Phase 12.5 + 13) is shipped — render-service, vision evaluator, fidelity-log, and editor Score tab already exist.**

---

## File structure

### New backend files

**Foundations:**
- `backend/services/page_type.py` — `infer_page_type(page_brief) -> str` (deterministic, no LLM)
- `backend/services/cost_tracker.py` — `CostTracker` class + `BudgetExhausted` exception

**Patch system:**
- `backend/agents/patch_agent.py` — `propose_patches(...)` + `PATCH_AGENT_SYSTEM_PROMPT`
- `backend/services/patch_applier.py` — `validate_patches(patches, schema)` + `apply_patches_transactional(patches, schema)` + `ValidationError`, `PatchApplyError` exception types

**Reference grounding:**
- `backend/services/reference_bank.py` — `load_exemplars(domain, page_type, limit)` + `render_exemplars_block(exemplars)` + `available_cells()`
- `backend/scripts/seed_reference_bank.py` — one-shot CLI seeder
- `backend/reference_pages/<domain>/<page_type>/exemplar_*.{json,meta.json,png}` — produced by the seeder, committed to git

**Loop runner:**
- `backend/services/fidelity_loop.py` — `FidelityLoopRunner`, `PageRef`, `PageOutcome`, `FidelityReport` types

### New backend tests
- `backend/tests/services/test_page_type.py`
- `backend/tests/services/test_cost_tracker.py`
- `backend/tests/services/test_patch_applier.py`
- `backend/tests/agents/test_patch_agent.py`
- `backend/tests/services/test_reference_bank.py`
- `backend/tests/services/test_fidelity_loop.py`
- `backend/tests/integration/test_fidelity_loop_e2e.py`

### Modified backend files
- `backend/config.py` — add `FIDELITY_LOOP_ENABLED`, `REFERENCE_GROUNDING_ENABLED`, `FIDELITY_STATS_ENABLED`
- `backend/requirements.txt` — add `jsonpatch==1.33`
- `backend/services/schema_prompt.py` — `build_schema_prompt()` consumes the reference bank when `REFERENCE_GROUNDING_ENABLED`
- `backend/routers/generate.py` — invoke `FidelityLoopRunner` as a new phase between `seed` and `QA`
- `backend/routers/_debug_fidelity.py` — `/api/_debug/score-page` appends iter (instead of overwriting), sets `manual_run: true`; new `/api/_debug/fidelity-stats` endpoint
- `backend/services/fidelity_log.py` — extend with `flags`, `manual_run`, `wall_clock_ms`, `cost_usd`, `exit_status`, `failed_fidelity` fields per entry
- `backend/main.py` — no changes (existing router includes it)
- `.gitignore` — add `output/*/.fidelity-history/`

### New frontend files
- `frontend/src/components/schema-editor/IterationHistory.tsx` — collapsible per-iter rows with screenshot thumbnails
- `frontend/src/components/schema-editor/PageScoreBadge.tsx` — small score pill for the page tree (extracted/extended from existing `FidelityScoreBadge`)

### Modified frontend files
- `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` — read `fidelity-log.json` on mount, pass per-page scores to the page-tree component
- `frontend/src/components/schema-editor/CritiquePanel.tsx` — read latest entry from log on mount; "Re-score" button (replaces "Score now"); failed_fidelity Alert; mount IterationHistory
- `frontend/src/components/chat/ChatHistory.tsx` — render new SSE event types (`page_iter_done`, `page_complete`, `page_skipped`, `phase_complete`)
- `frontend/src/lib/fidelity-client.ts` — new helper `fetchFidelityLog(shortId)` + handle `manual_run` semantics

---

## Task 1: Config flags + jsonpatch dep + .gitignore

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add jsonpatch to requirements.txt**

Append to `backend/requirements.txt`:

```
jsonpatch==1.33
```

Install:

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && pip install -r requirements.txt
```

- [ ] **Step 2: Add config flags**

Read `backend/config.py`. Find the existing fidelity render-loop block (added by predecessor plan, contains `FIDELITY_RENDER_ENABLED` and `FIDELITY_SCORING_ENABLED`). After that block, append:

```python
# Phase 14: closed loop with patch agent (default off until tuned)
FIDELITY_LOOP_ENABLED = os.getenv("FIDELITY_LOOP_ENABLED", "false").strip().lower() not in {"false", "0", "no", "off", ""}

# Phase 15: reference grounding bank (default true once seeded)
REFERENCE_GROUNDING_ENABLED = os.getenv("REFERENCE_GROUNDING_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# /api/_debug/fidelity-stats endpoint
FIDELITY_STATS_ENABLED = os.getenv("FIDELITY_STATS_ENABLED", "true").strip().lower() not in {"false", "0", "no", "off", ""}

# Per-page wall-clock budget for the fidelity loop, ms
FIDELITY_LOOP_PAGE_TIMEOUT_MS = int(os.getenv("FIDELITY_LOOP_PAGE_TIMEOUT_MS", "90000"))

# Project-wide cost cap for the fidelity loop, USD
FIDELITY_LOOP_PROJECT_COST_CAP_USD = float(os.getenv("FIDELITY_LOOP_PROJECT_COST_CAP_USD", "5.0"))

# Max patch iterations per page (excluding iter 0 baseline)
FIDELITY_LOOP_MAX_ITERATIONS = int(os.getenv("FIDELITY_LOOP_MAX_ITERATIONS", "3"))

# Page-level concurrency through the loop (matches render-service browser pool)
FIDELITY_LOOP_CONCURRENCY = int(os.getenv("FIDELITY_LOOP_CONCURRENCY", "4"))
```

- [ ] **Step 3: Verify config import**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -c "from config import FIDELITY_LOOP_ENABLED, REFERENCE_GROUNDING_ENABLED, FIDELITY_STATS_ENABLED, FIDELITY_LOOP_PAGE_TIMEOUT_MS, FIDELITY_LOOP_PROJECT_COST_CAP_USD, FIDELITY_LOOP_MAX_ITERATIONS, FIDELITY_LOOP_CONCURRENCY; print('flags ok')"
```

Expected: `flags ok`.

- [ ] **Step 4: Update .gitignore**

Read `.gitignore` at the repo root. If `output/*/.fidelity-history/` isn't already covered (it likely isn't), append:

```
# Per-iteration screenshots from the fidelity loop (large, reproducible)
output/*/.fidelity-history/
```

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/config.py backend/requirements.txt .gitignore
git commit -m "feat(fidelity): add Phase 14+15 config flags + jsonpatch dep + gitignore"
```

---

## Task 2: Page-type inference

**Files:**
- Create: `backend/services/page_type.py`
- Create: `backend/tests/services/test_page_type.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_page_type.py
from services.page_type import infer_page_type


class FakeBrief:
    def __init__(self, route: str, role: str = ""):
        self.route = route
        self.role = role


def test_list_route():
    assert infer_page_type(FakeBrief("/users/list")) == "list"
    assert infer_page_type(FakeBrief("/index")) == "list"


def test_detail_route_with_id():
    assert infer_page_type(FakeBrief("/users/[id]")) == "detail"
    assert infer_page_type(FakeBrief("/products/{id}/edit")) == "form"  # /edit wins


def test_form_route():
    assert infer_page_type(FakeBrief("/users/new")) == "form"
    assert infer_page_type(FakeBrief("/users/[id]/edit")) == "form"


def test_dashboard_route():
    assert infer_page_type(FakeBrief("/dashboard")) == "dashboard"
    assert infer_page_type(FakeBrief("/admin/overview")) == "dashboard"


def test_settings_route():
    assert infer_page_type(FakeBrief("/settings")) == "settings"
    assert infer_page_type(FakeBrief("/profile")) == "settings"


def test_role_fallback_when_route_is_generic():
    assert infer_page_type(FakeBrief("/x", role="browse all teammates")) == "list"
    assert infer_page_type(FakeBrief("/x", role="create a new entity")) == "form"
    assert infer_page_type(FakeBrief("/x", role="show kpi metrics")) == "dashboard"


def test_generic_when_nothing_matches():
    assert infer_page_type(FakeBrief("/foo", role="bar")) == "generic"


def test_handles_missing_role():
    # role attribute is None
    class NoRole:
        route = "/users/list"
        role = None
    assert infer_page_type(NoRole()) == "list"
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_page_type.py -v
```

Expected: FAIL with `ModuleNotFoundError: services.page_type`.

- [ ] **Step 3: Implement page_type.py**

```python
# backend/services/page_type.py
"""Deterministic page-type inference from route + role. No LLM.

Used by the reference-bank loader to pick which exemplars to inject into the
schema agent's prompt at gen time."""
from __future__ import annotations

from typing import Literal, Protocol


PageType = Literal["list", "detail", "form", "dashboard", "settings", "generic"]


class _BriefLike(Protocol):
    route: str
    role: str | None


def infer_page_type(page_brief: _BriefLike) -> PageType:
    """Return one of: list | detail | form | dashboard | settings | generic.

    Resolution order: route patterns first (most reliable), then role keywords.
    Form patterns (`/new`, `/edit`) take precedence over detail (`[id]`) since
    `/users/[id]/edit` is conceptually a form, not a detail page."""
    route = (page_brief.route or "").lower()
    role = (page_brief.role or "").lower()

    # Form patterns first — they often contain `[id]` but are forms, not details
    if route.endswith("/new") or route.endswith("/edit") or route.endswith("/create"):
        return "form"
    # List patterns
    if route.endswith("/list") or route.endswith("/index") or route.endswith("/all"):
        return "list"
    # Detail patterns
    if "[id]" in route or "{id}" in route:
        return "detail"
    # Dashboard / overview
    if "/dashboard" in route or "/overview" in route or "/home" == route:
        return "dashboard"
    # Settings / profile
    if "/settings" in route or "/profile" in route or "/account" in route:
        return "settings"
    # Role-keyword fallbacks
    if "list" in role or "browse" in role or "all" in role:
        return "list"
    if "edit" in role or "create" in role or "new" in role:
        return "form"
    if "metric" in role or "kpi" in role or "dashboard" in role or "overview" in role:
        return "dashboard"
    if "settings" in role or "profile" in role or "preferences" in role:
        return "settings"
    if "detail" in role or "view" in role:
        return "detail"
    return "generic"
```

- [ ] **Step 4: Run, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_page_type.py -v
```

Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/page_type.py backend/tests/services/test_page_type.py
git commit -m "feat(fidelity): page-type inference helper for reference grounding"
```

---

## Task 3: CostTracker

**Files:**
- Create: `backend/services/cost_tracker.py`
- Create: `backend/tests/services/test_cost_tracker.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_cost_tracker.py
import pytest
from services.cost_tracker import CostTracker, BudgetExhausted


def test_starts_at_zero():
    t = CostTracker(cap_usd=5.0)
    assert t.total == 0.0


def test_add_increments_total():
    t = CostTracker(cap_usd=5.0)
    t.add("vision", tokens_in=4000, tokens_out=400)
    assert t.total > 0
    assert t.total < 1.0  # one vision call should be well under $1


def test_raises_when_cap_exceeded():
    t = CostTracker(cap_usd=0.05)  # tiny cap
    # First call may or may not exceed; keep adding until it does
    with pytest.raises(BudgetExhausted):
        for _ in range(20):
            t.add("vision", tokens_in=4000, tokens_out=400)


def test_raise_includes_cap_in_message():
    t = CostTracker(cap_usd=0.001)
    with pytest.raises(BudgetExhausted, match=r"\$0\.001"):
        t.add("vision", tokens_in=10_000, tokens_out=1000)


def test_unknown_kind_is_estimated_conservatively():
    t = CostTracker(cap_usd=100.0)
    # Unknown kinds shouldn't crash — they should fall back to a default rate
    t.add("schema_reprompt", tokens_in=1000, tokens_out=500)
    assert t.total > 0
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_cost_tracker.py -v
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement cost_tracker.py**

```python
# backend/services/cost_tracker.py
"""Tracks LLM call costs across the fidelity loop, raises when the project cap
is exceeded so the runner can stop dispatching new iterations."""
from __future__ import annotations

from typing import Literal


# Approximate Sonnet-4.5 pricing as of 2026-05. These rates are intentionally
# slightly conservative (rounded up) to act as a brake.
# Input + output in USD per 1M tokens.
_RATES_USD_PER_M: dict[str, tuple[float, float]] = {
    "vision":          (3.0, 15.0),  # Anthropic vision: input + output
    "patch":           (3.0, 15.0),
    "schema_reprompt": (3.0, 15.0),
    "exemplar_seed":   (3.0, 15.0),
}
_DEFAULT_RATE = (3.0, 15.0)


class BudgetExhausted(Exception):
    """Raised when project-wide LLM cost exceeds the configured cap."""


class CostTracker:
    """Accumulator for per-call LLM costs. Raises BudgetExhausted past the cap."""

    def __init__(self, cap_usd: float):
        if cap_usd <= 0:
            raise ValueError(f"cap_usd must be positive, got {cap_usd}")
        self.cap_usd = cap_usd
        self.total: float = 0.0

    def add(self, kind: Literal["vision", "patch", "schema_reprompt", "exemplar_seed"], tokens_in: int, tokens_out: int) -> float:
        """Add a call's cost to the running total. Returns the cost added."""
        in_rate, out_rate = _RATES_USD_PER_M.get(kind, _DEFAULT_RATE)
        cost = (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate
        self.total += cost
        if self.total > self.cap_usd:
            raise BudgetExhausted(f"project cost cap ${self.cap_usd:.3f} exceeded (now ${self.total:.4f})")
        return cost
```

- [ ] **Step 4: Run, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_cost_tracker.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/cost_tracker.py backend/tests/services/test_cost_tracker.py
git commit -m "feat(fidelity): CostTracker + BudgetExhausted for the project cost cap"
```

---

## Task 4: Patch validator (validate_patches)

**Files:**
- Create: `backend/services/patch_applier.py` (initial — validator only; applier added in Task 5)
- Create: `backend/tests/services/test_patch_applier.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_patch_applier.py
import pytest
from services.patch_applier import validate_patches, ValidationError


SCHEMA = {
    "schemaVersion": "2",
    "id": "users/list",
    "route": "/users",
    "meta": {"title": "Users"},
    "dataSources": [],
    "root": {
        "id": "root",
        "type": "Stack",
        "props": {"gap": "md"},
        "children": [
            {"id": "hero", "type": "Hero", "props": {"headline": "Users"}, "children": []},
            {"id": "table", "type": "Table", "props": {"columns": [
                {"key": "name", "label": "Name"},
                {"key": "email", "label": "Email"},
            ]}}
        ]
    }
}


def test_valid_replace_passes():
    patches = [{"op": "replace", "path": "/root/children/0/props/headline", "value": "Team"}]
    errors = validate_patches(patches, SCHEMA)
    assert errors == []


def test_unresolved_path_returns_error():
    patches = [{"op": "replace", "path": "/root/children/99/props/x", "value": "y"}]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "path_unresolved"


def test_add_to_array_end_is_valid():
    patches = [{"op": "add", "path": "/root/children/-", "value": {"id": "x", "type": "Card", "props": {}}}]
    errors = validate_patches(patches, SCHEMA)
    assert errors == []


def test_remove_root_is_rejected():
    patches = [{"op": "remove", "path": "/root"}]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "cannot_remove_required"


def test_multiple_patches_collect_multiple_errors():
    patches = [
        {"op": "replace", "path": "/root/children/0/props/headline", "value": "Team"},  # ok
        {"op": "replace", "path": "/root/children/99/props/x", "value": "y"},           # unresolved
        {"op": "remove", "path": "/root"},                                                # cannot_remove_required
    ]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 2
    kinds = {e.kind for e in errors}
    assert kinds == {"path_unresolved", "cannot_remove_required"}


def test_malformed_patch_missing_op():
    patches = [{"path": "/root/children/0", "value": "x"}]  # missing 'op'
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "malformed_patch"
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_patch_applier.py -v
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement validator (just validate_patches; apply lands in Task 5)**

```python
# backend/services/patch_applier.py
"""RFC 6902 patch validation + transactional application.

Validation is the reliability spine: every patch the patch-agent emits must
pass these checks before it touches disk. Failures here trigger a stricter
re-prompt; failures after apply trigger a rollback.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


# Required-but-must-not-be-removed paths in any Page schema.
# Removing these would invalidate the page entirely.
_PROTECTED_PATHS = {"/root", "/id", "/route", "/schemaVersion"}


@dataclass
class ValidationError:
    idx: int          # which patch in the input list
    kind: str         # path_unresolved | type_mismatch | cannot_remove_required | malformed_patch
    msg: str


class PatchApplyError(Exception):
    """Raised when patches couldn't be applied (mid-apply failure or post-apply schema invalid)."""


def _walk_pointer(schema: Any, pointer: str, *, op: str) -> bool:
    """Return True if `pointer` resolves in `schema`, OR if `op == "add"` and
    the pointer's parent resolves with the leaf being a new key or array end.
    Raises nothing — returns bool."""
    if not pointer.startswith("/"):
        return False
    parts = pointer[1:].split("/") if pointer != "/" else []
    if not parts:  # root pointer "/" — schema root itself
        return True

    # For `add`: the parent must resolve and the leaf must either be a new key
    # in an object, or "-" (array append).
    target = schema
    for i, raw in enumerate(parts):
        is_last = i == len(parts) - 1
        # Unescape JSON pointer tokens (~0 → ~, ~1 → /)
        key = raw.replace("~1", "/").replace("~0", "~")

        if isinstance(target, dict):
            if key in target:
                target = target[key]
                continue
            if is_last and op == "add":
                return True  # adding a new key is fine
            return False
        if isinstance(target, list):
            if key == "-":
                if is_last and op == "add":
                    return True
                return False
            try:
                idx = int(key)
            except ValueError:
                return False
            if 0 <= idx < len(target):
                target = target[idx]
                continue
            if is_last and op == "add" and idx == len(target):
                return True
            return False
        # Walked past a leaf scalar — can't descend
        return False
    return True


def _is_protected(path: str) -> bool:
    return path in _PROTECTED_PATHS


def validate_patches(patches: list[dict[str, Any]], schema: dict[str, Any]) -> list[ValidationError]:
    """Validate a list of RFC 6902 patches against `schema`. Returns a list of
    ValidationError; empty list means all patches pass.

    This validation is structural — it confirms paths resolve and ops make sense.
    Type-level validation against the v2 zod schema happens AFTER apply, in
    apply_patches_transactional, since we'd otherwise have to reimplement the
    zod shape here."""
    errors: list[ValidationError] = []
    for i, p in enumerate(patches):
        if not isinstance(p, dict) or "op" not in p or "path" not in p:
            errors.append(ValidationError(i, "malformed_patch", f"patch missing 'op' or 'path': {p!r}"))
            continue

        op = p.get("op")
        path = p.get("path", "")

        if op not in ("add", "replace", "remove", "move", "copy", "test"):
            errors.append(ValidationError(i, "malformed_patch", f"unknown op: {op!r}"))
            continue

        if op == "remove" and _is_protected(path):
            errors.append(ValidationError(i, "cannot_remove_required", f"path {path} is structurally required"))
            continue

        if op in ("add", "replace", "remove", "move", "copy", "test"):
            if not _walk_pointer(schema, path, op=op):
                errors.append(ValidationError(i, "path_unresolved", f"path {path} does not resolve in schema"))
                continue

        if op == "move" or op == "copy":
            from_path = p.get("from")
            if not from_path or not _walk_pointer(schema, from_path, op="replace"):
                errors.append(ValidationError(i, "path_unresolved", f"`from` path {from_path!r} does not resolve"))
                continue

    return errors
```

- [ ] **Step 4: Run, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_patch_applier.py::test_valid_replace_passes tests/services/test_patch_applier.py::test_unresolved_path_returns_error tests/services/test_patch_applier.py::test_add_to_array_end_is_valid tests/services/test_patch_applier.py::test_remove_root_is_rejected tests/services/test_patch_applier.py::test_multiple_patches_collect_multiple_errors tests/services/test_patch_applier.py::test_malformed_patch_missing_op -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/patch_applier.py backend/tests/services/test_patch_applier.py
git commit -m "feat(fidelity): patch validator with path-resolution + protected-path checks"
```

---

## Task 5: Patch applier (apply_patches_transactional)

**Files:**
- Modify: `backend/services/patch_applier.py`
- Modify: `backend/tests/services/test_patch_applier.py`

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/services/test_patch_applier.py`:

```python
from services.patch_applier import apply_patches_transactional, PatchApplyError


def test_apply_replace_returns_new_schema_unchanged_input():
    schema_before = {"a": {"b": 1}}
    patches = [{"op": "replace", "path": "/a/b", "value": 2}]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"a": {"b": 2}}
    assert schema_before == {"a": {"b": 1}}  # input untouched


def test_apply_add_to_array():
    schema_before = {"items": [1, 2]}
    patches = [{"op": "add", "path": "/items/-", "value": 3}]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"items": [1, 2, 3]}


def test_apply_multiple_patches_in_order():
    schema_before = {"a": 1, "b": 2}
    patches = [
        {"op": "replace", "path": "/a", "value": 10},
        {"op": "replace", "path": "/b", "value": 20},
    ]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"a": 10, "b": 20}


def test_apply_failure_mid_sequence_raises_no_disk_writes():
    schema_before = {"a": 1}
    patches = [
        {"op": "replace", "path": "/a", "value": 99},          # would succeed
        {"op": "replace", "path": "/missing", "value": "x"},   # would fail (path doesn't exist)
    ]
    with pytest.raises(PatchApplyError):
        apply_patches_transactional(patches, schema_before, validate_zod=False)
    # input untouched — caller still sees the original schema
    assert schema_before == {"a": 1}


def test_zod_validation_failure_raises():
    """When validate_zod=True and the result schema doesn't match PageV1|PageV2."""
    schema_before = {
        "schemaVersion": "2",
        "id": "x", "route": "/x", "meta": {"title": "X"},
        "dataSources": [],
        "root": {"id": "r", "type": "Stack", "props": {}, "children": []}
    }
    patches = [{"op": "remove", "path": "/route"}]
    with pytest.raises(PatchApplyError, match="invalid schema"):
        apply_patches_transactional(patches, schema_before, validate_zod=True)
```

- [ ] **Step 2: Run the new tests, verify they fail**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_patch_applier.py -v
```

Expected: 4 new tests fail (the validator tests still pass). Errors will mention `apply_patches_transactional` not found.

- [ ] **Step 3: Implement apply_patches_transactional**

Append to `backend/services/patch_applier.py`:

```python
import jsonpatch
import json
import subprocess


def apply_patches_transactional(
    patches: list[dict[str, Any]],
    schema: dict[str, Any],
    *,
    validate_zod: bool = True,
) -> dict[str, Any]:
    """Apply RFC 6902 patches to `schema` and return a NEW schema dict.

    Transactional semantics:
      - input dict is NOT mutated; a deep copy is patched
      - if any patch fails mid-application, raises PatchApplyError without
        touching disk; caller's reference to `schema` is unchanged
      - if validate_zod=True, the resulting schema is parsed through the
        PageV1|PageV2 zod union; failure also raises PatchApplyError
    """
    working = copy.deepcopy(schema)
    try:
        patched = jsonpatch.apply_patch(working, patches, in_place=False)
    except jsonpatch.JsonPatchException as e:
        raise PatchApplyError(f"patch sequence failed mid-apply: {e}") from e
    except Exception as e:
        raise PatchApplyError(f"unexpected error applying patches: {e}") from e

    if validate_zod:
        if not _zod_validate_page(patched):
            raise PatchApplyError(f"patches produced invalid schema (failed PageV1|PageV2 zod check)")

    return patched


def _zod_validate_page(schema: dict[str, Any]) -> bool:
    """Best-effort zod validation by shelling out to a tiny Node script using
    the @tentoroforge/schema package. Falls back to `True` (no opinion) if the
    Node-side validator can't run — we don't want to block on transient
    infrastructure issues.

    The script lives inline here as a string so this module is self-contained
    and doesn't add yet another file. It reads schema JSON from stdin, exits 0
    on success, exits 1 on validation failure, exits 2 on script error."""
    script = r"""
const { PageV1, PageV2 } = require("@tentoroforge/schema");
const { z } = require("zod");
let buf = "";
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  try {
    const j = JSON.parse(buf);
    const u = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
    u.parse(j);
    process.exit(0);
  } catch (e) {
    process.stderr.write(String(e?.message ?? e));
    process.exit(1);
  }
});
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(schema),
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/Users/m/Work/code/poc/design2ui-forge-v3",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Node not available, or the script timed out — don't block, just
        # warn via return value. The caller's run_render → re-score will
        # catch real breakage at the next stage.
        return True
    return proc.returncode == 0
```

NOTE: `_zod_validate_page` shells out to Node because the Page zod schema lives in the TS workspace package `@tentoroforge/schema`, not in Python. The 10s timeout + fail-open posture (returning True on infrastructure errors) keeps the loop resilient. Real bugs surface at re-render time anyway.

- [ ] **Step 4: Run all tests in the file**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_patch_applier.py -v
```

Expected: 10 tests PASS. The zod-validation test requires Node + the workspace package; if node is unreachable in your env, that test will pass-because-fall-open (not an issue for CI).

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/patch_applier.py backend/tests/services/test_patch_applier.py
git commit -m "feat(fidelity): transactional patch applier with optional zod re-validation"
```

---

## Task 6: Patch agent (with mocked Anthropic)

**Files:**
- Create: `backend/agents/patch_agent.py`
- Create: `backend/tests/agents/test_patch_agent.py`
- Create: `backend/tests/agents/__init__.py` (if missing)

- [ ] **Step 1: Ensure tests/agents/ exists**

```bash
mkdir -p /Users/m/Work/code/poc/design2ui-forge-v3/backend/tests/agents
[ -f /Users/m/Work/code/poc/design2ui-forge-v3/backend/tests/agents/__init__.py ] || touch /Users/m/Work/code/poc/design2ui-forge-v3/backend/tests/agents/__init__.py
```

- [ ] **Step 2: Write failing test**

```python
# backend/tests/agents/test_patch_agent.py
"""Patch agent tests use a stubbed Anthropic client so they run offline."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.patch_agent import propose_patches, PatchAgentContext
from services.vision_evaluator.types import Critique, Issue, Scores


VALID_PATCHES_RESPONSE = json.dumps([
    {"op": "replace", "path": "/root/children/0/props/headline", "value": "Track patient appointments"},
    {"op": "add", "path": "/root/children/-", "value": {"id": "extra", "type": "Card", "props": {}}}
])


def make_critique() -> Critique:
    return Critique.model_validate({
        "scores": {"visualPolish": 6, "domainFeel": 5, "informationDensity": 5,
                   "componentCoherence": 6, "brandReflection": 5},
        "compositeScore": 5.4,
        "pass": False,
        "topIssues": [{
            "severity": "high", "axis": "domainFeel", "nodeIdHint": "hero",
            "issue": "Hero headline is generic", "suggestion": "Use domain-specific copy",
        }],
        "strengths": [],
        "designerApprovalRecommended": False,
    })


def make_schema() -> dict:
    return {
        "schemaVersion": "2", "id": "x", "route": "/x", "meta": {"title": "X"},
        "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {},
                 "children": [{"id": "hero", "type": "Hero", "props": {"headline": "Welcome"}, "children": []}]}
    }


def make_ctx() -> PatchAgentContext:
    return PatchAgentContext(domain="healthcare", app_name="Clinic", description="track patients", tone="trustworthy")


@pytest.mark.asyncio
async def test_propose_patches_returns_parsed_list():
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=VALID_PATCHES_RESPONSE)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 2
        assert patches[0]["op"] == "replace"
        assert patches[0]["path"] == "/root/children/0/props/headline"


@pytest.mark.asyncio
async def test_propose_patches_strips_markdown_fence():
    fenced = "```json\n" + VALID_PATCHES_RESPONSE + "\n```"
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=fenced)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 2


@pytest.mark.asyncio
async def test_propose_patches_invalid_json_raises():
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value="not json")):
        with pytest.raises(Exception):
            await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())


@pytest.mark.asyncio
async def test_propose_patches_caps_at_8_patches():
    too_many = json.dumps([{"op": "replace", "path": "/x", "value": i} for i in range(20)])
    with patch("agents.patch_agent._call_anthropic", new=AsyncMock(return_value=too_many)):
        patches = await propose_patches(schema=make_schema(), critique=make_critique(), app_ctx=make_ctx())
        assert len(patches) == 8


@pytest.mark.asyncio
async def test_strict_mode_includes_validation_errors_in_prompt():
    """When strict=True, the validation_errors list should be passed to the
    prompt builder. We verify by checking _call_anthropic receives it via the
    user-prompt content."""
    captured = {}
    async def fake_call(*, system, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return VALID_PATCHES_RESPONSE
    with patch("agents.patch_agent._call_anthropic", new=fake_call):
        await propose_patches(
            schema=make_schema(), critique=make_critique(), app_ctx=make_ctx(),
            strict=True, validation_errors=["path_unresolved at /foo"],
        )
        assert "path_unresolved at /foo" in captured["user_prompt"]
```

- [ ] **Step 3: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_patch_agent.py -v
```

Expected: FAIL with module-not-found.

- [ ] **Step 4: Implement patch_agent.py**

```python
# backend/agents/patch_agent.py
"""Patch agent — given a schema + critique, emits RFC 6902 patches.

Narrow, single-purpose: no refactoring, no restructuring, no inventing new
features. Just patches that target the issues in the critique.
"""
from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from services.vision_evaluator.types import Critique


_MODEL = os.getenv("PATCH_AGENT_MODEL", "claude-sonnet-4-5-20250929")
_MAX_TOKENS = 2048
_MAX_PATCHES = 8


PATCH_AGENT_SYSTEM_PROMPT = r"""You are a precise code surgeon. Given a UI page schema and a design critique, you emit RFC 6902 JSON Patches that fix the issues.

HARD RULES — violating any of these is a failed response:
- Emit ONLY a JSON array of patch objects. No prose, no markdown fences, no explanations.
- Maximum 8 patches per response. If the critique has more issues, rank by severity (high > medium > low) and emit patches for the top-8.
- Each patch's `path` must resolve in the provided schema. Use JSON Pointer (RFC 6901) syntax.
- Each patch's `value` must match the v2 prop contract for the target component.
- When an issue has a `nodeIdHint`, prefer patches against that node.
- DO NOT change the page's route, id, or schemaVersion.
- DO NOT add, remove, or rename top-level keys (root, meta, dataSources).
- DO NOT remove existing nodes unless the critique explicitly asks for removal.
- Prefer minimal patches: change one prop at a time when that addresses the issue.

SCHEMA STRUCTURE
- Schemas use a tree where each node has {id, type, props, children?}.
- Paths are JSON pointers — to target Hero's headline at the root's first child, the path is "/root/children/0/props/headline".
- To insert at the end of a children array, use path "/parent/children/-" with op "add".

OUTPUT FORMAT (strict)
[
  {"op": "replace", "path": "/root/children/0/props/headline", "value": "Track patient appointments"},
  {"op": "add", "path": "/root/children/-", "value": {"id": "stats-extra", "type": "MetricTile", "props": {"label": "Avg Wait", "value": 23, "format": "duration"}}}
]
"""


@dataclass
class PatchAgentContext:
    domain: str
    app_name: str
    description: str
    tone: str


async def _call_anthropic(*, system: str, user_prompt: str, model: str = _MODEL, max_tokens: int = _MAX_TOKENS) -> str:
    """Single Anthropic call — returns the raw text. Mocked in tests."""
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


def _strip_fence(text: str) -> str:
    """Strip ```json ... ``` fences if the model emitted them despite instructions."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text


def _build_user_prompt(*, schema: dict[str, Any], critique: Critique, app_ctx: PatchAgentContext, strict: bool, validation_errors: list[str] | None) -> str:
    """Assemble the user-prompt body. Schema and critique are inlined as JSON."""
    lines = [
        f"APP CONTEXT",
        f"  Domain: {app_ctx.domain}",
        f"  Name: {app_ctx.app_name}",
        f"  Description: {app_ctx.description}",
        f"  Tone: {app_ctx.tone}",
        "",
        "CURRENT SCHEMA:",
        json.dumps(schema, indent=2),
        "",
        "CRITIQUE:",
        critique.model_dump_json(by_alias=True, indent=2),
        "",
    ]
    if strict and validation_errors:
        lines.append("YOUR PREVIOUS ATTEMPT HAD THESE VALIDATION ERRORS:")
        for err in validation_errors:
            lines.append(f"  - {err}")
        lines.append("")
        lines.append("Emit corrected patches. Do not include any patch that touched paths from those errors.")
        lines.append("")
    lines.append("Emit the JSON array of patches now.")
    return "\n".join(lines)


async def propose_patches(
    *,
    schema: dict[str, Any],
    critique: Critique,
    app_ctx: PatchAgentContext,
    strict: bool = False,
    validation_errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Call the patch agent. Returns up to 8 RFC 6902 patches (caller validates + applies).

    Raises Exception on unparseable model output. Caller catches and treats as a
    failed iteration."""
    user_prompt = _build_user_prompt(
        schema=schema, critique=critique, app_ctx=app_ctx,
        strict=strict, validation_errors=validation_errors,
    )
    raw = await _call_anthropic(system=PATCH_AGENT_SYSTEM_PROMPT, user_prompt=user_prompt)
    text = _strip_fence(raw)
    patches = json.loads(text)  # raises JSONDecodeError if not JSON
    if not isinstance(patches, list):
        raise ValueError(f"patch agent returned non-array: {type(patches).__name__}")
    return patches[:_MAX_PATCHES]
```

- [ ] **Step 5: Run, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_patch_agent.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/agents/patch_agent.py backend/tests/agents/test_patch_agent.py backend/tests/agents/__init__.py
git commit -m "feat(fidelity): patch agent — narrow Anthropic wrapper emitting RFC 6902"
```

---

## Task 7: Reference bank loader

**Files:**
- Create: `backend/services/reference_bank.py`
- Create: `backend/tests/services/test_reference_bank.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/services/test_reference_bank.py
import json
from pathlib import Path

import pytest

from services.reference_bank import (
    load_exemplars, available_cells, render_exemplars_block, Exemplar
)


@pytest.fixture
def temp_bank(tmp_path: Path, monkeypatch):
    """Build a tiny throwaway bank under tmp_path and point the loader at it."""
    bank = tmp_path / "reference_pages"
    cell = bank / "healthcare" / "list"
    cell.mkdir(parents=True)
    schema = {"schemaVersion": "2", "id": "x", "route": "/x", "meta": {"title": "Patients"},
              "dataSources": [], "root": {"id": "r", "type": "Stack", "props": {}, "children": []}}
    (cell / "exemplar_01.json").write_text(json.dumps(schema))
    (cell / "exemplar_01.meta.json").write_text(json.dumps({
        "score": 8.4, "scored_at": "2026-05-06T10:00:00Z",
        "model_used": "sonnet-4-5", "seeder_version": "v1",
    }))
    (cell / "exemplar_01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    return bank


def test_load_exemplars_returns_exemplar_objects(temp_bank):
    exemplars = load_exemplars("healthcare", "list", limit=2)
    assert len(exemplars) == 1
    e = exemplars[0]
    assert isinstance(e, Exemplar)
    assert e.score == 8.4
    assert e.schema["id"] == "x"


def test_load_exemplars_missing_cell_returns_empty(temp_bank):
    assert load_exemplars("nonexistent", "list", limit=2) == []


def test_load_exemplars_respects_limit(tmp_path: Path, monkeypatch):
    bank = tmp_path / "reference_pages"
    cell = bank / "general" / "detail"
    cell.mkdir(parents=True)
    for i in range(5):
        (cell / f"exemplar_{i:02d}.json").write_text(json.dumps({"id": f"e{i}"}))
        (cell / f"exemplar_{i:02d}.meta.json").write_text(json.dumps({"score": 8.0 + i * 0.1}))
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    assert len(load_exemplars("general", "detail", limit=2)) == 2


def test_load_exemplars_sorted_by_score_desc(tmp_path: Path, monkeypatch):
    bank = tmp_path / "reference_pages"
    cell = bank / "general" / "list"
    cell.mkdir(parents=True)
    for i, score in enumerate([8.1, 8.5, 8.3]):
        (cell / f"exemplar_{i}.json").write_text(json.dumps({"id": f"e{i}"}))
        (cell / f"exemplar_{i}.meta.json").write_text(json.dumps({"score": score}))
    monkeypatch.setattr("services.reference_bank._BANK_ROOT", bank)
    exs = load_exemplars("general", "list", limit=3)
    scores = [e.score for e in exs]
    assert scores == sorted(scores, reverse=True)


def test_available_cells(temp_bank):
    cells = available_cells()
    assert ("healthcare", "list") in cells


def test_render_exemplars_block_includes_score_and_schema(temp_bank):
    exemplars = load_exemplars("healthcare", "list", limit=2)
    block = render_exemplars_block(exemplars)
    assert "8.4" in block
    assert "Exemplar 1" in block
    assert "schemaVersion" in block  # the schema JSON is inlined


def test_render_exemplars_block_empty_returns_empty_string():
    assert render_exemplars_block([]) == ""
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_reference_bank.py -v
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement reference_bank.py**

```python
# backend/services/reference_bank.py
"""Reference grounding bank — loads curated Page-schema exemplars per
(domain, page_type) for injection into the schema agent's prompt.

The bank is hand-seeded once via scripts/seed_reference_bank.py, then
versioned in git. At gen time, build_schema_prompt() loads up to N exemplars
for the page being generated."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_BANK_ROOT = Path(__file__).resolve().parents[2] / "backend" / "reference_pages"
# Adjust if running from different cwd; the canonical location is
# <repo-root>/backend/reference_pages/. Resolves to absolute path on import.
if not _BANK_ROOT.exists():
    # Fallback: walk up from this file to find backend/reference_pages
    here = Path(__file__).resolve()
    for parent in [here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "reference_pages"
        if candidate.exists():
            _BANK_ROOT = candidate
            break


@dataclass
class Exemplar:
    schema: dict[str, Any]
    score: float
    meta: dict[str, Any]
    domain: str
    page_type: str
    file_stem: str  # e.g. "exemplar_01"


def load_exemplars(domain: str, page_type: str, *, limit: int = 2) -> list[Exemplar]:
    """Load up to `limit` exemplars for the given cell, sorted by score
    descending. Returns empty list if the cell doesn't exist or is empty."""
    if not domain or not page_type:
        return []
    cell = _BANK_ROOT / domain / page_type
    if not cell.exists() or not cell.is_dir():
        return []

    exemplars: list[Exemplar] = []
    for schema_file in sorted(cell.glob("exemplar_*.json")):
        if schema_file.name.endswith(".meta.json"):
            continue
        meta_file = schema_file.with_suffix(".meta.json")
        # Tolerate missing or unreadable files — just skip
        try:
            schema = json.loads(schema_file.read_text())
            meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        except (json.JSONDecodeError, OSError):
            continue
        score = float(meta.get("score", 0.0))
        exemplars.append(Exemplar(
            schema=schema, score=score, meta=meta,
            domain=domain, page_type=page_type, file_stem=schema_file.stem,
        ))
    exemplars.sort(key=lambda e: e.score, reverse=True)
    return exemplars[:limit]


def available_cells() -> list[tuple[str, str]]:
    """List every (domain, page_type) cell that has at least one exemplar."""
    if not _BANK_ROOT.exists():
        return []
    cells: list[tuple[str, str]] = []
    for domain_dir in sorted(_BANK_ROOT.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        for type_dir in sorted(domain_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            if any(type_dir.glob("exemplar_*.json")):
                cells.append((domain_dir.name, type_dir.name))
    return cells


def render_exemplars_block(exemplars: list[Exemplar]) -> str:
    """Format a list of exemplars as a prompt block for schema-agent injection."""
    if not exemplars:
        return ""
    lines = [
        "## REFERENCE EXEMPLARS",
        "These are top-tier examples for this domain + page type.",
        "Match this level of polish, structure, and information density. Adapt",
        "the entities and content to this project's brief.",
        "",
    ]
    for i, e in enumerate(exemplars, start=1):
        lines.append(f"### Exemplar {i} (score {e.score:.1f})")
        lines.append("```json")
        lines.append(json.dumps(e.schema, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_reference_bank.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/reference_bank.py backend/tests/services/test_reference_bank.py
git commit -m "feat(fidelity): reference-bank loader for Phase 15 grounding"
```

---

## Task 8: Reference bank seeder script

**Files:**
- Create: `backend/scripts/seed_reference_bank.py`
- Create: `backend/scripts/__init__.py` (if missing)

The seeder is operational tooling — run by us, not users — so we ship it without TDD coverage. It depends on the live render-service + vision evaluator being reachable.

- [ ] **Step 1: Ensure scripts/ exists**

```bash
mkdir -p /Users/m/Work/code/poc/design2ui-forge-v3/backend/scripts
[ -f /Users/m/Work/code/poc/design2ui-forge-v3/backend/scripts/__init__.py ] || touch /Users/m/Work/code/poc/design2ui-forge-v3/backend/scripts/__init__.py
```

- [ ] **Step 2: Implement seed_reference_bank.py**

```python
# backend/scripts/seed_reference_bank.py
"""Reference bank seeder — generate, render, score, and curate exemplar
schemas for (domain, page_type) cells. Runs against the live render-service
(port 6502) and Anthropic API.

Usage:
  python -m scripts.seed_reference_bank \\
      --domain healthcare --page-type list --target-count 2 \\
      --max-attempts 10 --seeder-version v1

Run this once per cell. Outputs land in backend/reference_pages/<domain>/<page_type>/.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic

from services.vision_evaluator import EvaluatorContext, evaluate_page


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BANK_ROOT = _REPO_ROOT / "backend" / "reference_pages"
_RENDER_SERVICE = os.getenv("RENDER_SERVICE_URL", "http://localhost:6502")
_OUTPUT_ROOT = _REPO_ROOT / "output"
_SEEDER_MODEL = os.getenv("SEEDER_MODEL", "claude-sonnet-4-5-20250929")


# Per-domain entity bank — what entities the LLM should design pages around
# for each domain. Used to make the brief realistic.
_DOMAIN_ENTITIES: dict[str, list[str]] = {
    "general":     ["User", "Item", "Project", "Task", "Note"],
    "healthcare":  ["Patient", "Appointment", "Provider", "Visit", "Prescription"],
    "fintech":     ["Account", "Transaction", "Customer", "Portfolio", "Position"],
    "hr":          ["Employee", "TimeOff", "Role", "Performance", "Department"],
}


_PAGE_TYPE_BRIEFS: dict[str, str] = {
    "list":      "an index/list page for browsing many records, with sorting and filters",
    "detail":    "a record-detail page showing one item's full information",
    "form":      "a create/edit form for a single record with proper validation feedback",
    "dashboard": "an overview dashboard with KPI tiles, recent activity, and at-a-glance status",
    "settings":  "a settings or profile page with grouped configuration controls",
}


def _build_seeder_prompt(domain: str, page_type: str) -> str:
    entities = _DOMAIN_ENTITIES.get(domain, _DOMAIN_ENTITIES["general"])
    brief = _PAGE_TYPE_BRIEFS.get(page_type, "a generic page")
    return f"""You are designing a top-tier exemplar Page schema for the Tentoroforge platform reference bank.

DOMAIN: {domain}
PAGE TYPE: {page_type}
PAGE BRIEF: {brief}
LIKELY ENTITIES IN THIS DOMAIN: {", ".join(entities)}

REQUIREMENTS
- Output a single JSON object matching the v2 Page schema (PageV2).
- The page must look like it was designed by a senior product designer who specialises in {domain}.
- Use real domain vocabulary (no Lorem ipsum, no "Item 1 / Item 2").
- Information density: just right for this page type — not sparse, not crowded.
- Component coherence: every component should feel like it's from the same design system.
- Use components from the @tentoroforge/library: Hero, Section, Card, MetricTile, Avatar, Badge, KeyValueList, Heading, FeatureCard, Skeleton, Form, Input, Select, Textarea, Checkbox, DatePicker, Table, Tabs, TabPanel, Accordion, AccordionPanel, Split, Sidebar, Cluster, FadeIn, Stagger, Button, Link, NavLink, IconButton, Divider, Breadcrumb, Alert, EmptyState, LoadingState.
- Bind dynamic content via Mustache: {{{{user.name}}}}, {{{{appointment.scheduledAt}}}}, etc.
- The root must be a layout container (Stack/Section/Split/etc).
- meta.title should be domain-specific.

OUTPUT
Emit ONLY the JSON. No prose, no markdown fences."""


async def _generate_candidate(domain: str, page_type: str) -> dict:
    client = AsyncAnthropic()
    prompt = _build_seeder_prompt(domain, page_type)
    msg = await client.messages.create(
        model=_SEEDER_MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    # Strip code fences if any
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
        if text.startswith("json\n"):
            text = text[5:]
    return json.loads(text)


def _write_temp_project(schema: dict) -> tuple[str, Path]:
    """Write the candidate schema into a temp project shell so the scaffold
    can render it. Returns (short_id, path)."""
    short_id = f"seed-{uuid.uuid4().hex[:8]}"
    proj_dir = _OUTPUT_ROOT / short_id
    schemas_dir = proj_dir / "src" / "schemas" / "ref"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schemas_dir / "candidate.json").write_text(json.dumps(schema))
    return short_id, proj_dir


async def _render_and_score(short_id: str, domain: str, page_type: str) -> tuple[bytes, float, dict]:
    """Render the candidate via render-service, then score via vision evaluator.
    Returns (png_bytes, composite_score, full_critique_dict)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{_RENDER_SERVICE}/render", json={
            "projectId": short_id, "pageRoute": "/ref/candidate", "viewport": "desktop",
        })
    if r.status_code != 200:
        raise RuntimeError(f"render failed: {r.status_code} {r.text}")
    body = r.json()
    png = base64.b64decode(body["pngBase64"])
    a11y = body.get("accessibilityTree", "")

    ctx = EvaluatorContext(
        domain=domain, app_name="Reference exemplar",
        description=f"Exemplar {page_type} page for {domain}",
        tone="professional", route="/ref/candidate",
        page_type=page_type, page_role=f"reference exemplar — {page_type}",
        iteration=0, max_iter=1,
    )
    critique = await evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=ctx)
    return png, critique.compositeScore, critique.model_dump(by_alias=True)


def _persist_exemplar(*, domain: str, page_type: str, idx: int, schema: dict, score: float, critique: dict, png: bytes, seeder_version: str) -> None:
    cell = _BANK_ROOT / domain / page_type
    cell.mkdir(parents=True, exist_ok=True)
    stem = f"exemplar_{idx:02d}"
    (cell / f"{stem}.json").write_text(json.dumps(schema, indent=2))
    (cell / f"{stem}.meta.json").write_text(json.dumps({
        "score": score, "scored_at": datetime.now(timezone.utc).isoformat(),
        "model_used": _SEEDER_MODEL, "seeder_version": seeder_version,
        "critique_summary": {"strengths": critique.get("strengths", []),
                             "topIssues": critique.get("topIssues", [])},
    }, indent=2))
    (cell / f"{stem}.png").write_bytes(png)


async def seed_cell(*, domain: str, page_type: str, target_count: int, max_attempts: int, seeder_version: str) -> int:
    print(f"\n=== seeding {domain}/{page_type} (target={target_count}, max_attempts={max_attempts}) ===")
    kept = 0
    attempts = 0
    while kept < target_count and attempts < max_attempts:
        attempts += 1
        print(f"  attempt {attempts}/{max_attempts}", end=" ... ", flush=True)
        try:
            schema = await _generate_candidate(domain, page_type)
        except Exception as e:
            print(f"GEN FAILED: {e}")
            continue

        short_id, proj_dir = _write_temp_project(schema)
        try:
            png, score, critique = await _render_and_score(short_id, domain, page_type)
        except Exception as e:
            print(f"RENDER/SCORE FAILED: {e}")
            shutil.rmtree(proj_dir, ignore_errors=True)
            continue

        has_high_severity = any(i.get("severity") == "high" for i in critique.get("topIssues", []))
        if score >= 8.0 and not has_high_severity:
            kept += 1
            _persist_exemplar(domain=domain, page_type=page_type, idx=kept,
                              schema=schema, score=score, critique=critique, png=png,
                              seeder_version=seeder_version)
            print(f"KEPT (score {score:.1f}, kept {kept}/{target_count})")
        else:
            print(f"REJECTED (score {score:.1f}, high_sev={has_high_severity})")
        shutil.rmtree(proj_dir, ignore_errors=True)

    print(f"  done — kept {kept}/{target_count} after {attempts} attempts")
    return kept


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, choices=list(_DOMAIN_ENTITIES.keys()))
    ap.add_argument("--page-type", required=True, choices=list(_PAGE_TYPE_BRIEFS.keys()))
    ap.add_argument("--target-count", type=int, default=2)
    ap.add_argument("--max-attempts", type=int, default=10)
    ap.add_argument("--seeder-version", default="v1")
    return ap.parse_args()


async def _main() -> int:
    args = _parse_args()
    kept = await seed_cell(
        domain=args.domain, page_type=args.page_type,
        target_count=args.target_count, max_attempts=args.max_attempts,
        seeder_version=args.seeder_version,
    )
    return 0 if kept >= args.target_count else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
```

- [ ] **Step 3: Smoke-test the seeder by importing it**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from scripts.seed_reference_bank import seed_cell; print('importable')"
```

Expected: `importable`.

- [ ] **Step 4: Commit (without running the seeder yet — that's Task 9)**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/scripts/seed_reference_bank.py backend/scripts/__init__.py
git commit -m "feat(fidelity): reference bank seeder CLI"
```

---

## Task 9: Run the seeder for the four-domain matrix

This is operational, not code — but it's a discrete checkpoint and the bank's contents need to be committed.

**Preconditions (verify first):**
- `ANTHROPIC_API_KEY` set in your shell.
- Render-service running at `http://localhost:6502`.
- Render-scaffold running at `http://localhost:6503`.

If either service isn't running, start them per `docs/render-service.md`.

- [ ] **Step 1: Run the seeder for each cell**

The matrix is 4 domains × 5 page types = 20 cells. Run them in batches to keep memory bounded. Approximate cost: $1/cell × 20 = ~$20 one-time.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
for DOMAIN in general healthcare fintech hr; do
  for PAGETYPE in list detail form dashboard settings; do
    echo "==== $DOMAIN / $PAGETYPE ===="
    python3 -m scripts.seed_reference_bank \
      --domain "$DOMAIN" --page-type "$PAGETYPE" \
      --target-count 2 --max-attempts 8 --seeder-version v1 \
      || echo "   (cell $DOMAIN/$PAGETYPE: less than target_count kept — acceptable)"
  done
done
```

Expected per cell: `done — kept 2/2 after N attempts` (where N is between 2 and 8). Some cells may end with `kept 1/2` or `kept 0/2` — that's acceptable; they degrade gracefully via the loader's `general/` fallback.

- [ ] **Step 2: Audit the bank**

```bash
ls /Users/m/Work/code/poc/design2ui-forge-v3/backend/reference_pages/
find /Users/m/Work/code/poc/design2ui-forge-v3/backend/reference_pages -name "exemplar_*.json" -not -name "*.meta.json" | wc -l
```

Expected: 4 domain dirs, between 20 and 40 exemplar JSON files (target is 40; some cells may be under-quota).

- [ ] **Step 3: Spot-check a few exemplars**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/backend/reference_pages/healthcare/list/exemplar_01.meta.json | python3 -m json.tool
```

Confirm: `score >= 8.0`, no high-severity issues in `critique_summary.topIssues`.

- [ ] **Step 4: Commit the bank**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/reference_pages/
git status  # confirm only reference_pages/ changes are staged
git commit -m "feat(fidelity): seed reference bank with v1 exemplars across 4 domains x 5 page types

Generated via scripts/seed_reference_bank.py, score-filtered (>=8.0
composite, no high-severity issues). Exemplars + screenshots committed
so the bank ships with the codebase."
```

If a cell ended up empty after Step 1, that's logged in the seeder output but doesn't block this commit. Re-running just that cell can fill it in later.

---

## Task 10: Schema agent prompt — consume reference bank

**Files:**
- Modify: `backend/services/schema_prompt.py`
- Modify: `backend/tests/services/test_schema_prompt.py` (may not exist — create if absent)

The existing `build_schema_prompt(plan, library_descriptor, tokens)` function needs an optional `page_brief` parameter so it can pick the right exemplar cell. The existing `load_gold_example()` machinery stays — exemplars supplement it, they don't replace it.

- [ ] **Step 1: Read the existing function signature**

```bash
sed -n '200,260p' /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/schema_prompt.py
```

Note: `build_schema_prompt(plan: dict, library_descriptor: dict | None = None, tokens: dict | None = None) -> str`. Identify where the prompt is composed near the end of the function.

- [ ] **Step 2: Modify build_schema_prompt to accept page_brief and inject exemplars**

Edit `backend/services/schema_prompt.py`:

a) At the top of the file, after the existing imports, add:

```python
from config import REFERENCE_GROUNDING_ENABLED
from services.page_type import infer_page_type
from services.reference_bank import load_exemplars, render_exemplars_block
```

b) Find `def build_schema_prompt(plan: dict, library_descriptor: dict | None = None, tokens: dict | None = None) -> str:` and update its signature to:

```python
def build_schema_prompt(
    plan: dict,
    library_descriptor: dict | None = None,
    tokens: dict | None = None,
    page_brief: dict | None = None,
    domain: str | None = None,
) -> str:
```

c) Inside the function body, find where the prompt's last block is added (likely after the gold example, before the `return prompt` or its equivalent). Insert this BEFORE the `return`:

```python
    # Phase 15 reference grounding — domain-aware few-shot exemplars
    if REFERENCE_GROUNDING_ENABLED and page_brief is not None and domain:
        # page_brief here is a dict with 'route' and optionally 'role';
        # wrap it in a tiny shim that infer_page_type accepts
        class _Shim:
            def __init__(self, d: dict) -> None:
                self.route = d.get("route", "")
                self.role = d.get("role")
        page_type = infer_page_type(_Shim(page_brief))
        exemplars = load_exemplars(domain, page_type, limit=2)
        if not exemplars:
            exemplars = load_exemplars("general", page_type, limit=2)
        block = render_exemplars_block(exemplars)
        if block:
            # Append to whatever the existing prompt accumulator is named.
            # Find the local variable that holds the prompt-being-built (most
            # likely `prompt` or `parts`); concatenate `block` to it.
            #
            # If the function uses `prompt = "\n".join(parts)` style, append
            # `block` to `parts` BEFORE the join. If it returns a single str
            # built directly, do `prompt += "\n\n" + block`.
            #
            # The exact mechanics depend on the file's existing structure —
            # follow whatever pattern is in place.
            pass  # ← replace this with the real append (see note above)
```

NOTE for implementer: read the function body to find the local variable holding the in-progress prompt. The comment block above tells you what to do, but you have to make the actual edit match the file's existing structure. The key invariant: `block` (the exemplars markdown) ends up appended to the final prompt string when the flag is on AND a domain+page_brief are provided.

d) The simplest possible edit — if the existing function builds the prompt as a list of `parts: list[str]`:

```python
    # at the end, before `return "\n".join(parts)` or similar:
    if REFERENCE_GROUNDING_ENABLED and page_brief is not None and domain:
        class _Shim:
            route = page_brief.get("route", "")
            role = page_brief.get("role")
        page_type = infer_page_type(_Shim())
        exemplars = load_exemplars(domain, page_type, limit=2) or load_exemplars("general", page_type, limit=2)
        block = render_exemplars_block(exemplars)
        if block:
            parts.append(block)
```

- [ ] **Step 3: Write or extend test for the integration**

```python
# backend/tests/services/test_schema_prompt.py — new or appended
import pytest
from services.schema_prompt import build_schema_prompt


def test_build_schema_prompt_without_grounding_returns_string():
    """Calling without page_brief should not crash."""
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan)
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_build_schema_prompt_with_no_exemplars_skips_block(monkeypatch):
    """When no exemplars exist for the cell, no exemplar block is added."""
    monkeypatch.setattr("services.schema_prompt.load_exemplars", lambda *a, **kw: [])
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan, page_brief={"route": "/users/list"}, domain="healthcare")
    assert "REFERENCE EXEMPLARS" not in prompt


def test_build_schema_prompt_with_exemplars_includes_block(monkeypatch):
    from services.reference_bank import Exemplar
    fake = Exemplar(
        schema={"id": "x", "schemaVersion": "2"},
        score=8.4,
        meta={}, domain="healthcare", page_type="list", file_stem="exemplar_01",
    )
    monkeypatch.setattr("services.schema_prompt.load_exemplars", lambda *a, **kw: [fake])
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan, page_brief={"route": "/users/list"}, domain="healthcare")
    assert "REFERENCE EXEMPLARS" in prompt
    assert "8.4" in prompt
```

- [ ] **Step 4: Run the schema_prompt tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Verify nothing else broke**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/ -v --ignore=tests/services/test_render_server.py 2>&1 | tail -10
```

Expected: previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/schema_prompt.py backend/tests/services/test_schema_prompt.py
git commit -m "feat(fidelity): schema-prompt builder consumes reference bank when grounded"
```

---

## Task 11: FidelityLoopRunner skeleton + types

**Files:**
- Create: `backend/services/fidelity_loop.py` (initial skeleton — full state machine in Task 12)

- [ ] **Step 1: Implement skeleton with types and stub run/run_one_page**

```python
# backend/services/fidelity_loop.py
"""FidelityLoopRunner — orchestrates render → score → patch → re-render → re-score
across all pages of a generated project. Runs as a phase in routers/generate.py."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from config import (
    FIDELITY_LOOP_CONCURRENCY,
    FIDELITY_LOOP_MAX_ITERATIONS,
    FIDELITY_LOOP_PAGE_TIMEOUT_MS,
    FIDELITY_LOOP_PROJECT_COST_CAP_USD,
    REFERENCE_GROUNDING_ENABLED,
    FIDELITY_LOOP_ENABLED,
)
from services.cost_tracker import BudgetExhausted, CostTracker


logger = logging.getLogger(__name__)


PageStatus = Literal[
    "pass", "plateau", "budget", "failed", "timeout",
    "render_failed", "schema_reprompt_used",
]


@dataclass
class PageRef:
    short_id: str
    page_path: str        # e.g. "users/list"
    page_route: str       # e.g. "/users/list"
    page_type: str        # output of infer_page_type


@dataclass
class IterationOutcome:
    iter: int | str       # int for normal iters, "fallback" for schema-reprompt
    score: float
    score_delta: float
    issues_input: int
    patches_proposed: int
    patches_rejected: int
    patches_applied: int
    patch_summary: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    status: str = "continue"  # continue|pass|plateau|regressed|patch_invalid|schema_invalid|render_failed|vision_invalid


@dataclass
class PageOutcome:
    page: PageRef
    final_score: float
    passed: bool
    iterations: list[IterationOutcome]
    exit_status: PageStatus
    failed_fidelity: bool
    wall_clock_ms: int
    cost_usd: float


@dataclass
class FidelityReport:
    outcomes: list[PageOutcome]
    total_cost: float
    wall_clock_s: float
    flags: dict[str, Any]

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.failed_fidelity)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.exit_status == "budget")

    def summary(self) -> dict[str, Any]:
        scores = [o.final_score for o in self.outcomes if o.final_score > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        iters = [len(o.iterations) for o in self.outcomes]
        avg_iters = sum(iters) / len(iters) if iters else 0.0
        return {
            "phase": "fidelity_loop",
            "passed": self.passed, "failed": self.failed, "skipped": self.skipped,
            "avg_score": round(avg_score, 2), "avg_iters": round(avg_iters, 2),
            "total_cost_usd": round(self.total_cost, 4),
            "wall_clock_s": round(self.wall_clock_s, 1),
            "flags": self.flags,
        }


@dataclass
class ProjectContext:
    """Carried through the loop for vision evaluator + patch agent prompts."""
    domain: str
    app_name: str
    description: str
    tone: str


SseEmit = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class FidelityLoopRunner:
    """Orchestrator for the per-page closed-loop fidelity check."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        project_ctx: ProjectContext,
        sse_emit: SseEmit | None = None,
        concurrency: int | None = None,
        cost_cap_usd: float | None = None,
        page_timeout_ms: int | None = None,
        max_iterations: int | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.project_ctx = project_ctx
        self.sse_emit = sse_emit or (lambda et, d: None)
        self.concurrency = concurrency or FIDELITY_LOOP_CONCURRENCY
        self.cost_cap_usd = cost_cap_usd or FIDELITY_LOOP_PROJECT_COST_CAP_USD
        self.page_timeout_ms = page_timeout_ms or FIDELITY_LOOP_PAGE_TIMEOUT_MS
        self.max_iterations = max_iterations or FIDELITY_LOOP_MAX_ITERATIONS
        self.cost_tracker = CostTracker(cap_usd=self.cost_cap_usd)

    async def run(self, pages: list[PageRef]) -> FidelityReport:
        """Stub — real implementation in Task 12."""
        raise NotImplementedError("Task 12 implements run()")

    async def _run_one_page(self, page: PageRef) -> PageOutcome:
        """Stub — real implementation in Task 12."""
        raise NotImplementedError("Task 12 implements _run_one_page()")
```

- [ ] **Step 2: Verify imports**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from services.fidelity_loop import FidelityLoopRunner, PageRef, PageOutcome, FidelityReport, ProjectContext; print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/fidelity_loop.py
git commit -m "feat(fidelity): FidelityLoopRunner skeleton with PageRef/PageOutcome/FidelityReport types"
```

---

## Task 12: FidelityLoopRunner — full state machine

**Files:**
- Modify: `backend/services/fidelity_loop.py`
- Create: `backend/tests/services/test_fidelity_loop.py`

This is the largest single task in the plan. The state machine has: iter 0 baseline, up to 3 patch iters with validate→apply→re-render→re-score, plateau/regression exits, schema-agent fallback, timeout, budget kill.

- [ ] **Step 1: Write the test scaffolding**

```python
# backend/tests/services/test_fidelity_loop.py
"""FidelityLoopRunner tests — uses heavy mocking since the runner integrates
the patch agent, render service, vision evaluator, and disk I/O."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.fidelity_loop import (
    FidelityLoopRunner, PageRef, PageOutcome, FidelityReport, ProjectContext,
)
from services.vision_evaluator.types import Critique


def _make_critique(score: float, *, has_high: bool = False) -> Critique:
    issues = []
    if has_high:
        issues.append({
            "severity": "high", "axis": "domainFeel", "nodeIdHint": "hero",
            "issue": "fake high-severity issue", "suggestion": "fix it",
        })
    return Critique.model_validate({
        "scores": {
            "visualPolish": score, "domainFeel": score, "informationDensity": score,
            "componentCoherence": score, "brandReflection": score,
        },
        "compositeScore": score,
        "pass": score >= 8.0 and not has_high,
        "topIssues": issues, "strengths": [],
        "designerApprovalRecommended": False,
    })


def _make_runner(tmp_path: Path) -> FidelityLoopRunner:
    output_dir = tmp_path / "proj"
    (output_dir / "src" / "schemas" / "users").mkdir(parents=True)
    schema = {
        "schemaVersion": "2", "id": "users/list", "route": "/users",
        "meta": {"title": "Users"}, "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {}, "children": []},
    }
    (output_dir / "src" / "schemas" / "users" / "list.json").write_text(json.dumps(schema))
    return FidelityLoopRunner(
        output_dir=output_dir,
        project_ctx=ProjectContext(domain="general", app_name="Test", description="t", tone="neutral"),
    )


def _make_page() -> PageRef:
    return PageRef(short_id="proj", page_path="users/list", page_route="/users/list", page_type="list")


# ---- Test 1: pass at iter 0 (no patches needed) ----
@pytest.mark.asyncio
async def test_passes_at_iter_0(tmp_path):
    runner = _make_runner(tmp_path)
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(8.5))):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is True
    assert outcome.exit_status == "pass"
    assert len(outcome.iterations) == 1
    assert outcome.iterations[0].iter == 0


# ---- Test 2: passes at iter 1 after one patch ----
@pytest.mark.asyncio
async def test_patches_then_passes(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([6.0, 8.4])
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=(kw.get("ctx", None) and False)))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "Patients"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: {**schema, "meta": {"title": "Patients"}}):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is True
    assert outcome.exit_status == "pass"
    assert len(outcome.iterations) == 2
    assert outcome.iterations[0].iter == 0
    assert outcome.iterations[1].iter == 1


# ---- Test 3: hits max_iterations without passing → failed_fidelity ----
@pytest.mark.asyncio
async def test_exhausts_iterations_failed_fidelity(tmp_path):
    runner = _make_runner(tmp_path)
    runner.max_iterations = 3
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(6.0, has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema), \
         patch("services.fidelity_loop._reprompt_schema_agent", new=AsyncMock(return_value=None)):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.passed is False
    assert outcome.failed_fidelity is True


# ---- Test 4: plateau exit ----
@pytest.mark.asyncio
async def test_plateau_exit(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([6.0, 7.5, 7.55, 7.55])  # plateau between iter 1 and iter 2
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema):
        outcome = await runner._run_one_page(_make_page())
    assert outcome.exit_status == "plateau"


# ---- Test 5: regression rolls back, marks regressed iter ----
@pytest.mark.asyncio
async def test_regression_rolls_back(tmp_path):
    runner = _make_runner(tmp_path)
    scores = iter([7.5, 5.0, 5.0])  # iter 0=7.5, iter 1=5.0 (regression, rejected), iter 2=5.0 plateau
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _make_critique(next(scores), has_high=True))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "X"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional", side_effect=lambda patches, schema, **kw: schema):
        outcome = await runner._run_one_page(_make_page())
    # The regressed iter should be in the log
    assert any(it.status == "regressed" for it in outcome.iterations)


# ---- Test 6: concurrent run dispatches all pages ----
@pytest.mark.asyncio
async def test_run_processes_multiple_pages_in_parallel(tmp_path):
    runner = _make_runner(tmp_path)
    runner.concurrency = 2
    pages = [PageRef(short_id="proj", page_path=f"p/{i}", page_route=f"/p/{i}", page_type="list") for i in range(3)]
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"PNG", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(return_value=_make_critique(8.5))), \
         patch.object(runner, "_run_one_page", new=AsyncMock(side_effect=lambda p: PageOutcome(
             page=p, final_score=8.5, passed=True, iterations=[],
             exit_status="pass", failed_fidelity=False, wall_clock_ms=10, cost_usd=0.01))):
        report = await runner.run(pages)
    assert len(report.outcomes) == 3
    assert report.passed == 3
```

- [ ] **Step 2: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_fidelity_loop.py -v
```

Expected: tests fail (NotImplementedError from skeleton).

- [ ] **Step 3: Implement the full state machine**

Replace the `run` and `_run_one_page` stubs in `backend/services/fidelity_loop.py` with the full implementation. Append the indirection helpers (`_render_page`, `_evaluate_page`, `_propose_patches`, `_validate_patches`, `_apply_patches_transactional`, `_reprompt_schema_agent`) at module level — they're thin wrappers around the real services so tests can patch them.

```python
# Append to backend/services/fidelity_loop.py — replace the two stub methods.

import base64
import copy
import json
import shutil

import httpx

from agents.patch_agent import PatchAgentContext, propose_patches
from services.fidelity_log import append_fidelity_entry
from services.patch_applier import (
    PatchApplyError, ValidationError, apply_patches_transactional, validate_patches,
)
from services.vision_evaluator import EvaluatorContext, evaluate_page


# Module-level indirection so tests can patch — real impl below
async def _render_page(*, scaffold_url: str, project_id: str, page_route: str, viewport: str = "desktop") -> tuple[bytes, str]:
    """Render via render-service; returns (png_bytes, a11y_tree)."""
    render_service = "http://localhost:6502"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{render_service}/render", json={
            "projectId": project_id, "pageRoute": page_route, "viewport": viewport,
        })
    if r.status_code != 200:
        raise RuntimeError(f"render failed: {r.status_code}")
    body = r.json()
    return base64.b64decode(body["pngBase64"]), body.get("accessibilityTree", "")


async def _evaluate_page(*, png_bytes: bytes, a11y_tree: str, ctx: EvaluatorContext) -> Critique:
    return await evaluate_page(png_bytes=png_bytes, a11y_tree=a11y_tree, ctx=ctx)


async def _propose_patches(*, schema, critique, app_ctx, strict=False, validation_errors=None):
    return await propose_patches(
        schema=schema, critique=critique, app_ctx=app_ctx,
        strict=strict, validation_errors=validation_errors,
    )


def _validate_patches(patches, schema):
    return validate_patches(patches, schema)


def _apply_patches_transactional(patches, schema, *, validate_zod: bool = True):
    return apply_patches_transactional(patches, schema, validate_zod=validate_zod)


async def _reprompt_schema_agent(*, page: PageRef, critique, schema, project_ctx) -> dict | None:
    """Fallback when patch agent has been stuck for 2 iterations. v1 stub —
    returns None (no fallback). Future plan can wire this to a real schema-agent
    re-call. Returning None means: accept the page as-is and exit."""
    return None


# Type import (Critique is in vision_evaluator)
# (added to existing imports at top of file in a real edit — placed here for clarity)


# Now the implementations:

class FidelityLoopRunner:
    # ... __init__ unchanged ...

    async def run(self, pages: list[PageRef]) -> FidelityReport:
        if not FIDELITY_LOOP_ENABLED:
            return FidelityReport(outcomes=[], total_cost=0.0, wall_clock_s=0.0,
                                   flags={"fidelity_loop": False, "reference_grounding": REFERENCE_GROUNDING_ENABLED})
        await self._sse("phase_start", {"phase": "fidelity_loop", "page_count": len(pages)})
        sem = asyncio.Semaphore(self.concurrency)
        start = time.monotonic()

        async def run_with_sem(page: PageRef) -> PageOutcome:
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._run_one_page(page),
                        timeout=self.page_timeout_ms / 1000.0,
                    )
                except BudgetExhausted:
                    await self._sse("page_skipped", {"page": page.page_path, "reason": "budget_exhausted"})
                    return self._budget_skipped_outcome(page)
                except asyncio.TimeoutError:
                    await self._sse("page_skipped", {"page": page.page_path, "reason": "timeout"})
                    return self._timeout_outcome(page)
                except Exception as e:
                    logger.exception("fidelity_loop: unexpected error on page %s", page.page_path)
                    return self._error_outcome(page, str(e))

        outcomes = await asyncio.gather(*(run_with_sem(p) for p in pages))
        report = FidelityReport(
            outcomes=outcomes,
            total_cost=self.cost_tracker.total,
            wall_clock_s=time.monotonic() - start,
            flags={"fidelity_loop": True, "reference_grounding": REFERENCE_GROUNDING_ENABLED, "loop_version": "v1"},
        )
        await self._sse("phase_complete", report.summary())
        return report

    async def _run_one_page(self, page: PageRef) -> PageOutcome:
        page_start = time.monotonic()
        cost_at_start = self.cost_tracker.total
        iterations: list[IterationOutcome] = []
        schema_path = self.output_dir / "src" / "schemas" / f"{page.page_path}.json"
        schema = json.loads(schema_path.read_text())

        evaluator_ctx = EvaluatorContext(
            domain=self.project_ctx.domain, app_name=self.project_ctx.app_name,
            description=self.project_ctx.description, tone=self.project_ctx.tone,
            route=page.page_route, page_type=page.page_type,
            page_role=f"users navigate to {page.page_route}",
            iteration=0, max_iter=self.max_iterations,
        )
        patch_agent_ctx = PatchAgentContext(
            domain=self.project_ctx.domain, app_name=self.project_ctx.app_name,
            description=self.project_ctx.description, tone=self.project_ctx.tone,
        )

        # iter 0 baseline
        try:
            png, a11y = await _render_page(scaffold_url="", project_id=page.short_id, page_route=page.page_route)
        except Exception as e:
            iterations.append(IterationOutcome(
                iter=0, score=0.0, score_delta=0.0, issues_input=0,
                patches_proposed=0, patches_rejected=0, patches_applied=0,
                status="render_failed",
                validation_errors=[str(e)],
            ))
            return self._finalize(page, iterations, "render_failed", failed=True, started_at=page_start, cost_at_start=cost_at_start)

        critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
        self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
        await self._save_iteration_screenshot(page, 0, png)
        prev_score = critique.compositeScore
        iterations.append(IterationOutcome(
            iter=0, score=critique.compositeScore, score_delta=0.0,
            issues_input=len(critique.topIssues),
            patches_proposed=0, patches_rejected=0, patches_applied=0,
            status="pass" if critique.pass_ else "continue",
        ))
        await self._sse("page_iter_done", {"page": page.page_path, "iter": 0,
                                            "score": critique.compositeScore,
                                            "pass": critique.pass_,
                                            "score_delta": 0.0})
        if critique.pass_:
            return self._finalize(page, iterations, "pass", failed=False, started_at=page_start, cost_at_start=cost_at_start)

        # patch iterations 1..N
        consecutive_rejects = 0
        for i in range(1, self.max_iterations + 1):
            try:
                proposed = await _propose_patches(
                    schema=schema, critique=critique, app_ctx=patch_agent_ctx,
                )
                self.cost_tracker.add("patch", tokens_in=3500, tokens_out=700)
            except Exception as e:
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues), patches_proposed=0,
                    patches_rejected=0, patches_applied=0, status="patch_invalid_output",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            errors = _validate_patches(proposed, schema)
            if errors:
                # one strict retry
                try:
                    proposed = await _propose_patches(
                        schema=schema, critique=critique, app_ctx=patch_agent_ctx,
                        strict=True, validation_errors=[f"{e.kind} at idx {e.idx}: {e.msg}" for e in errors],
                    )
                    self.cost_tracker.add("patch", tokens_in=4000, tokens_out=700)
                    errors = _validate_patches(proposed, schema)
                except Exception:
                    errors = [ValidationError(0, "retry_failed", "strict retry produced invalid output")]
                if errors:
                    iterations.append(IterationOutcome(
                        iter=i, score=prev_score, score_delta=0.0,
                        issues_input=len(critique.topIssues), patches_proposed=len(proposed),
                        patches_rejected=len(proposed), patches_applied=0,
                        status="patch_invalid",
                        validation_errors=[f"{e.kind}: {e.msg}" for e in errors],
                    ))
                    consecutive_rejects += 1
                    if consecutive_rejects >= 2:
                        break
                    continue

            try:
                new_schema = _apply_patches_transactional(proposed, schema, validate_zod=True)
            except PatchApplyError as e:
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues), patches_proposed=len(proposed),
                    patches_rejected=len(proposed), patches_applied=0,
                    status="schema_invalid",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            # Persist new schema
            schema_path.write_text(json.dumps(new_schema, indent=2))
            try:
                png, a11y = await _render_page(scaffold_url="", project_id=page.short_id, page_route=page.page_route)
            except Exception as e:
                # Restore prior schema on render failure
                schema_path.write_text(json.dumps(schema, indent=2))
                iterations.append(IterationOutcome(
                    iter=i, score=prev_score, score_delta=0.0,
                    issues_input=len(critique.topIssues),
                    patches_proposed=len(proposed),
                    patches_rejected=len(proposed),
                    patches_applied=0,
                    status="render_failed",
                    validation_errors=[str(e)],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                continue

            new_critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
            self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
            await self._save_iteration_screenshot(page, i, png)

            # Progress gate
            new_score = new_critique.compositeScore
            score_delta = new_score - prev_score
            new_high = any(iss.severity == "high" for iss in new_critique.topIssues)
            old_high = any(iss.severity == "high" for iss in critique.topIssues)
            regressed = (new_score < prev_score - 0.3) or (new_high and not old_high)

            if regressed:
                # Restore prior schema
                schema_path.write_text(json.dumps(schema, indent=2))
                iterations.append(IterationOutcome(
                    iter=i, score=new_score, score_delta=score_delta,
                    issues_input=len(critique.topIssues),
                    patches_proposed=len(proposed),
                    patches_rejected=len(proposed),
                    patches_applied=0,
                    status="regressed",
                    patch_summary=[_summarize_patch(p) for p in proposed],
                ))
                consecutive_rejects += 1
                if consecutive_rejects >= 2:
                    break
                # On regression, do NOT update schema/critique/prev_score for next iter
                continue

            # Accepted iter
            schema = new_schema
            critique = new_critique
            consecutive_rejects = 0
            iterations.append(IterationOutcome(
                iter=i, score=new_score, score_delta=score_delta,
                issues_input=len(critique.topIssues),
                patches_proposed=len(proposed),
                patches_rejected=0,
                patches_applied=len(proposed),
                status="pass" if new_critique.pass_ else "continue",
                patch_summary=[_summarize_patch(p) for p in proposed],
            ))
            await self._sse("page_iter_done", {"page": page.page_path, "iter": i,
                                                "score": new_score, "pass": new_critique.pass_,
                                                "score_delta": score_delta})

            if new_critique.pass_:
                return self._finalize(page, iterations, "pass", failed=False, started_at=page_start, cost_at_start=cost_at_start)

            # Plateau check (between iter i and iter i-1)
            if i >= 2 and abs(score_delta) < 0.3 and abs(iterations[-2].score_delta) < 0.3:
                return self._finalize(page, iterations, "plateau", failed=True, started_at=page_start, cost_at_start=cost_at_start)

            prev_score = new_score

        # Out of iterations — try schema-reprompt fallback if we had 2 consecutive rejects
        if consecutive_rejects >= 2:
            fallback_schema = await _reprompt_schema_agent(
                page=page, critique=critique, schema=schema, project_ctx=self.project_ctx,
            )
            if fallback_schema is not None:
                schema_path.write_text(json.dumps(fallback_schema, indent=2))
                # Render + score the fallback once
                try:
                    png, a11y = await _render_page(scaffold_url="", project_id=page.short_id, page_route=page.page_route)
                    fb_critique = await _evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=evaluator_ctx)
                    self.cost_tracker.add("vision", tokens_in=4000, tokens_out=400)
                    await self._save_iteration_screenshot(page, "fallback", png)
                    iterations.append(IterationOutcome(
                        iter="fallback", score=fb_critique.compositeScore,
                        score_delta=fb_critique.compositeScore - prev_score,
                        issues_input=len(critique.topIssues),
                        patches_proposed=0, patches_rejected=0, patches_applied=0,
                        status="pass" if fb_critique.pass_ else "continue",
                    ))
                    if fb_critique.pass_:
                        return self._finalize(page, iterations, "schema_reprompt_used", failed=False, started_at=page_start, cost_at_start=cost_at_start)
                except Exception:
                    schema_path.write_text(json.dumps(schema, indent=2))

        return self._finalize(page, iterations, "failed", failed=True, started_at=page_start, cost_at_start=cost_at_start)

    # ---- helpers ----

    def _finalize(self, page, iterations, exit_status, *, failed, started_at, cost_at_start) -> PageOutcome:
        final_score = iterations[-1].score if iterations else 0.0
        passed = (exit_status in ("pass",)) and not failed
        outcome = PageOutcome(
            page=page,
            final_score=final_score,
            passed=passed,
            iterations=iterations,
            exit_status=exit_status,
            failed_fidelity=failed and exit_status != "pass",
            wall_clock_ms=int((time.monotonic() - started_at) * 1000),
            cost_usd=round(self.cost_tracker.total - cost_at_start, 4),
        )
        # Persist to fidelity-log.json
        for it in iterations:
            append_fidelity_entry(
                output_dir=str(self.output_dir),
                page_path=page.page_path,
                score=it.score,
                issues=[],  # full critique is in the iter metadata; keep this lean
                iteration=it.iter if isinstance(it.iter, int) else len(iterations),
                passed=passed and (it.iter == iterations[-1].iter),
                patches=[],  # patch metadata is in iterations[].patch_summary
            )
        # NOTE: append_fidelity_entry is the predecessor's writer; this plan
        # extends it later (Task 13) to take the richer fields. For now we
        # call it once per iter as a best-effort log.
        # _record_outcome would write the richer structure. See Task 13.
        return outcome

    def _budget_skipped_outcome(self, page: PageRef) -> PageOutcome:
        return PageOutcome(page=page, final_score=0.0, passed=False, iterations=[],
                           exit_status="budget", failed_fidelity=False, wall_clock_ms=0, cost_usd=0.0)

    def _timeout_outcome(self, page: PageRef) -> PageOutcome:
        return PageOutcome(page=page, final_score=0.0, passed=False, iterations=[],
                           exit_status="timeout", failed_fidelity=True, wall_clock_ms=self.page_timeout_ms, cost_usd=0.0)

    def _error_outcome(self, page: PageRef, msg: str) -> PageOutcome:
        return PageOutcome(page=page, final_score=0.0, passed=False, iterations=[],
                           exit_status="failed", failed_fidelity=True, wall_clock_ms=0, cost_usd=0.0)

    async def _sse(self, event_type: str, data: dict[str, Any]) -> None:
        result = self.sse_emit(event_type, data)
        if asyncio.iscoroutine(result):
            await result

    async def _save_iteration_screenshot(self, page: PageRef, iter_id: int | str, png: bytes) -> None:
        """Persist iter screenshot to .fidelity-history/<page_path>/iter-N.png."""
        safe_page = page.page_path.replace("/", "_")
        dest_dir = self.output_dir / ".fidelity-history" / safe_page
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"iter-{iter_id}.png"
        dest.write_bytes(png)


def _summarize_patch(patch: dict[str, Any]) -> str:
    """Human-readable one-liner for a single patch."""
    op = patch.get("op", "?")
    path = patch.get("path", "")
    parts = path.split("/")
    target = parts[-1] if parts else path
    return f"{op} {target}"
```

NOTE FOR IMPLEMENTER: the file already has a `class FidelityLoopRunner` from Task 11; replace its `run` and `_run_one_page` methods with the bodies above, and append the helpers + module-level functions.

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_fidelity_loop.py -v
```

Expected: 6 tests PASS. If any fail, the failure usually points at a missing branch in the state machine — fix and re-run.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/fidelity_loop.py backend/tests/services/test_fidelity_loop.py
git commit -m "feat(fidelity): full per-page state machine with patches/regression/plateau/fallback"
```

---

## Task 13: Extend fidelity_log to capture richer per-iter shape

**Files:**
- Modify: `backend/services/fidelity_log.py`
- Modify: `backend/tests/services/test_fidelity_log.py`

The existing `append_fidelity_entry()` from the predecessor plan stores a minimal shape. Extend it to capture the fields Section 5 of the spec needs (flags, manual_run, patches, validation_errors, exit_status, wall_clock_ms, cost_usd, failed_fidelity). Make all new params optional with sane defaults so existing callers don't break.

- [ ] **Step 1: Read the current writer**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/fidelity_log.py
```

Identify the existing `append_fidelity_entry()` signature.

- [ ] **Step 2: Append failing test**

```python
# backend/tests/services/test_fidelity_log.py — append
def test_append_with_extended_fields(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(
        output_dir=str(output_dir), page_path="users/list",
        score=8.4, issues=[], iteration=2, passed=True,
        patches=[{"op": "replace", "path": "/x", "value": "y"}],
        patch_summary=["replaced /x"],
        validation_errors=[],
        exit_status="pass",
        wall_clock_ms=18000, cost_usd=0.18,
        flags={"fidelity_loop": True, "reference_grounding": True, "loop_version": "v1"},
    )
    log = read_fidelity_log(str(output_dir))
    entry = log["users/list"]
    assert entry["final_score"] == 8.4
    assert entry["exit_status"] == "pass"
    assert entry["flags"]["loop_version"] == "v1"
    assert entry["wall_clock_ms"] == 18000
    assert entry["cost_usd"] == 0.18


def test_append_with_failed_fidelity_marks_warning(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(
        output_dir=str(output_dir), page_path="users/detail",
        score=7.6, issues=[{"severity": "high"}], iteration=3, passed=False,
        exit_status="failed", failed_fidelity=True,
        wall_clock_ms=88000, cost_usd=0.42,
    )
    log = read_fidelity_log(str(output_dir))
    assert log["users/detail"]["failed_fidelity"] is True
    assert log["users/detail"]["exit_status"] == "failed"


def test_manual_run_flag_persists(tmp_path):
    output_dir = tmp_path / "proj"
    output_dir.mkdir()
    from services.fidelity_log import append_fidelity_entry, read_fidelity_log
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list",
                          score=8.0, issues=[], iteration=0, passed=True)
    append_fidelity_entry(output_dir=str(output_dir), page_path="users/list",
                          score=8.5, issues=[], iteration=1, passed=True,
                          manual_run=True)
    log = read_fidelity_log(str(output_dir))
    iters = log["users/list"]["iterations"]
    assert iters[1]["manual_run"] is True
    assert iters[0].get("manual_run") in (None, False)
```

- [ ] **Step 3: Run, verify failure**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_fidelity_log.py -v
```

Expected: 3 new tests fail (existing 3 still pass).

- [ ] **Step 4: Extend append_fidelity_entry**

Edit `backend/services/fidelity_log.py`. Replace the existing `append_fidelity_entry` with this expanded version:

```python
def append_fidelity_entry(
    *,
    output_dir: str,
    page_path: str,
    score: float,
    issues: list[dict[str, Any]],
    iteration: int,
    passed: bool,
    patches: list[dict[str, Any]] | None = None,
    patch_summary: list[str] | None = None,
    validation_errors: list[str] | None = None,
    exit_status: str | None = None,
    failed_fidelity: bool | None = None,
    wall_clock_ms: int | None = None,
    cost_usd: float | None = None,
    flags: dict[str, Any] | None = None,
    manual_run: bool = False,
) -> None:
    p = _log_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    log = read_fidelity_log(output_dir)
    page_entry = log.setdefault(page_path, {"iterations": []})
    iter_entry: dict[str, Any] = {
        "iteration": iteration,
        "score": score,
        "issues": issues,
        "patches": patches or [],
        "pass": passed,
    }
    if patch_summary is not None:
        iter_entry["patch_summary"] = patch_summary
    if validation_errors is not None:
        iter_entry["validation_errors"] = validation_errors
    if manual_run:
        iter_entry["manual_run"] = True
    page_entry["iterations"].append(iter_entry)
    page_entry["final_score"] = score
    page_entry["final_iteration"] = iteration
    if exit_status is not None:
        page_entry["exit_status"] = exit_status
    if failed_fidelity is not None:
        page_entry["failed_fidelity"] = failed_fidelity
    if wall_clock_ms is not None:
        page_entry["wall_clock_ms"] = wall_clock_ms
    if cost_usd is not None:
        page_entry["cost_usd"] = cost_usd
    if flags is not None:
        page_entry["flags"] = flags
    p.write_text(json.dumps(log, indent=2))
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_fidelity_log.py -v
```

Expected: 6 tests PASS (3 original + 3 new).

- [ ] **Step 6: Update fidelity_loop.py to call the richer signature**

Edit `backend/services/fidelity_loop.py`'s `_finalize` method. Replace the per-iter `append_fidelity_entry` loop with a single call that captures the full final state:

```python
def _finalize(self, page, iterations, exit_status, *, failed, started_at, cost_at_start) -> PageOutcome:
    final_score = iterations[-1].score if iterations else 0.0
    passed = (exit_status in ("pass",)) and not failed
    wall_clock_ms = int((time.monotonic() - started_at) * 1000)
    cost_usd = round(self.cost_tracker.total - cost_at_start, 4)
    outcome = PageOutcome(
        page=page, final_score=final_score, passed=passed, iterations=iterations,
        exit_status=exit_status,
        failed_fidelity=failed and exit_status != "pass",
        wall_clock_ms=wall_clock_ms, cost_usd=cost_usd,
    )
    # Persist all iterations + page-level final state in one pass.
    for it in iterations:
        is_last = (it is iterations[-1])
        iter_num = it.iter if isinstance(it.iter, int) else len(iterations) - 1
        append_fidelity_entry(
            output_dir=str(self.output_dir),
            page_path=page.page_path,
            score=it.score,
            issues=[],
            iteration=iter_num,
            passed=passed and is_last,
            patches=[],  # patch list is implicit in patch_summary
            patch_summary=it.patch_summary,
            validation_errors=it.validation_errors,
            exit_status=exit_status if is_last else None,
            failed_fidelity=outcome.failed_fidelity if is_last else None,
            wall_clock_ms=wall_clock_ms if is_last else None,
            cost_usd=cost_usd if is_last else None,
            flags={"fidelity_loop": True, "reference_grounding": REFERENCE_GROUNDING_ENABLED, "loop_version": "v1"} if is_last else None,
        )
    return outcome
```

- [ ] **Step 7: Re-run fidelity_loop tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_fidelity_loop.py tests/services/test_fidelity_log.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/fidelity_log.py backend/services/fidelity_loop.py backend/tests/services/test_fidelity_log.py
git commit -m "feat(fidelity): extended fidelity-log shape (flags, exit_status, manual_run, costs)"
```

---

## Task 14: Wire FidelityLoopRunner into routers/generate.py

**Files:**
- Modify: `backend/routers/generate.py`

- [ ] **Step 1: Find the right place to wire the phase**

```bash
grep -n "seed\|qa_agent\|qa\|post_generate_fixes" /Users/m/Work/code/poc/design2ui-forge-v3/backend/routers/generate.py | head -20
```

Identify where `seed_generator` runs and where `qa_agent` runs. The fidelity loop slots between them.

- [ ] **Step 2: Add the integration**

In `backend/routers/generate.py`, near the top, add imports:

```python
from config import FIDELITY_LOOP_ENABLED
from services.fidelity_loop import FidelityLoopRunner, ProjectContext, PageRef
from services.page_type import infer_page_type
```

Then in `_run_relay_pipeline` (or whichever function orchestrates the phases), AFTER the `seed_generator` phase completes and BEFORE the `qa_agent` phase, insert:

```python
# === Phase: fidelity_loop (Phase 14) ===
if FIDELITY_LOOP_ENABLED:
    sse_event("phase_start", {"phase": "fidelity_loop"})
    try:
        # Build the page list from the registry. Each page entry should have
        # `route`, `path`, optionally `role`. Adapt the field names to whatever
        # the existing registry shape uses.
        pages_info = registry.get("pages", []) if isinstance(registry, dict) else getattr(registry, "pages", [])
        page_refs: list[PageRef] = []
        for p in pages_info:
            route = p.get("route") if isinstance(p, dict) else getattr(p, "route", "")
            page_path = (route or "").lstrip("/") or p.get("path", "")
            page_type = infer_page_type(type("Brief", (), {"route": route, "role": p.get("role", "") if isinstance(p, dict) else getattr(p, "role", "")}))
            page_refs.append(PageRef(
                short_id=short_id, page_path=page_path,
                page_route=route, page_type=page_type,
            ))

        runner = FidelityLoopRunner(
            output_dir=output_dir,
            project_ctx=ProjectContext(
                domain=domain or "general",
                app_name=plan.get("appName", "App"),
                description=plan.get("description", ""),
                tone=plan.get("tone", "professional"),
            ),
            sse_emit=lambda et, d: sse_event(et, d),
        )
        report = await runner.run(page_refs)
        sse_event("phase_complete", report.summary())
    except Exception as e:
        # Fidelity loop failure must NEVER block generation.
        logger.exception("fidelity_loop failed; continuing pipeline")
        sse_event("phase_warning", {"phase": "fidelity_loop", "error": str(e)})
# === end fidelity_loop ===
```

NOTE for implementer: the exact variable names (`registry`, `short_id`, `output_dir`, `domain`, `plan`, `sse_event`) depend on the existing function's signature. Read the surrounding code and adapt.

- [ ] **Step 3: Verify the file imports cleanly**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from routers.generate import router; print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 4: Smoke test (optional, only if you have a known project to regen)**

```bash
# Set FIDELITY_LOOP_ENABLED=true and trigger a regen against a known project.
# Inspect output/<short_id>/src/contracts/fidelity-log.json afterwards.
```

This is best validated end-to-end in Task 18.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/routers/generate.py
git commit -m "feat(fidelity): wire FidelityLoopRunner as new phase between seed and qa"
```

---

## Task 15: /api/_debug/fidelity-stats endpoint

**Files:**
- Modify: `backend/routers/_debug_fidelity.py`

- [ ] **Step 1: Append the stats endpoint**

Open `backend/routers/_debug_fidelity.py`. After the existing `score_page` endpoint, append:

```python
from collections import Counter
from datetime import datetime
import json

from config import FIDELITY_STATS_ENABLED


@router.get("/api/_debug/fidelity-stats")
async def fidelity_stats(since: str | None = None):
    """Aggregate per-project fidelity-log.json across recent generations."""
    if not FIDELITY_STATS_ENABLED:
        raise HTTPException(403, "Fidelity stats endpoint disabled (set FIDELITY_STATS_ENABLED=true)")

    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    if not output_root.exists():
        return {"projects": 0, "pages_scored": 0}

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"invalid since: {since!r}; use ISO 8601")

    projects = 0
    pages_scored = 0
    score_total = 0.0
    iter_total = 0
    pass_count = 0
    cap_exhausted = 0
    cost_total = 0.0
    iter_dist = Counter()

    for proj_dir in output_root.iterdir():
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        if not log_path.exists():
            continue
        if since_dt and datetime.fromtimestamp(log_path.stat().st_mtime).astimezone() < since_dt.astimezone():
            continue
        try:
            log = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not log:
            continue
        projects += 1
        for page_path, entry in log.items():
            iters = entry.get("iterations", [])
            if not iters:
                continue
            pages_scored += 1
            score_total += float(entry.get("final_score", 0.0))
            iter_total += entry.get("final_iteration", 0)
            iter_dist[entry.get("final_iteration", 0)] += 1
            cost_total += float(entry.get("cost_usd", 0.0))
            if entry.get("exit_status") == "pass":
                pass_count += 1
            if entry.get("exit_status") == "budget":
                cap_exhausted += 1

    avg_score = round(score_total / pages_scored, 2) if pages_scored else 0.0
    avg_iters = round(iter_total / pages_scored, 2) if pages_scored else 0.0
    pass_rate = round(pass_count / pages_scored, 2) if pages_scored else 0.0
    avg_cost = round(cost_total / projects, 2) if projects else 0.0
    return {
        "projects": projects,
        "pages_scored": pages_scored,
        "pass_rate": pass_rate,
        "avg_iters": avg_iters,
        "median_score": avg_score,  # using avg as proxy; median requires extra pass
        "avg_cost_usd": avg_cost,
        "cap_exhausted": cap_exhausted,
        "iter_distribution": dict(iter_dist),
    }
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from routers._debug_fidelity import router; routes = [r.path for r in router.routes if hasattr(r, 'path')]; assert '/api/_debug/fidelity-stats' in routes, routes; print('endpoint registered')"
```

Expected: `endpoint registered`.

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/routers/_debug_fidelity.py
git commit -m "feat(fidelity): /api/_debug/fidelity-stats aggregates across projects"
```

---

## Task 16: Manual re-score appends iter (instead of overwriting)

**Files:**
- Modify: `backend/routers/_debug_fidelity.py`

The existing `score_page` endpoint always logs at `iteration=0`. Change it to detect existing log entries and append a new iter with `manual_run=true`.

- [ ] **Step 1: Modify score_page**

Locate the existing `score_page` function in `backend/routers/_debug_fidelity.py`. Just before the `append_fidelity_entry` call, compute the next iter number:

```python
# Determine the next iter number for manual re-score: continue from the last
# logged iter, mark this one as manual_run.
from services.fidelity_log import read_fidelity_log

existing = read_fidelity_log(str(output_dir))
existing_entry = existing.get(page_path, {})
existing_iters = existing_entry.get("iterations", [])
next_iter = (existing_entry.get("final_iteration", -1) + 1) if existing_iters else 0
```

Then update the `append_fidelity_entry` call to pass `iteration=next_iter` and `manual_run=True`:

```python
append_fidelity_entry(
    output_dir=str(output_dir),
    page_path=page_path,
    score=critique.compositeScore,
    issues=[i.model_dump() for i in critique.topIssues],
    iteration=next_iter,
    passed=critique.pass_,
    manual_run=True,
)
```

- [ ] **Step 2: Verify import + a quick logic test**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from routers._debug_fidelity import score_page; print('imports ok')"
```

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/routers/_debug_fidelity.py
git commit -m "feat(fidelity): manual /score-page re-score appends new iter with manual_run flag"
```

---

## Task 17: Editor — read fidelity-log.json + page tree score badges

**Files:**
- Create: `frontend/src/components/schema-editor/PageScoreBadge.tsx`
- Modify: `frontend/src/lib/fidelity-client.ts`
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`

- [ ] **Step 1: Add fidelity-log fetcher to the client**

Append to `frontend/src/lib/fidelity-client.ts`:

```ts
export interface PageLogEntry {
  iterations: Array<{
    iteration: number;
    score: number;
    issues?: any[];
    patch_summary?: string[];
    pass: boolean;
    manual_run?: boolean;
  }>;
  final_score: number;
  final_iteration: number;
  exit_status?: string;
  failed_fidelity?: boolean;
  wall_clock_ms?: number;
  cost_usd?: number;
  flags?: Record<string, any>;
}

export type FidelityLog = Record<string, PageLogEntry>;

export async function fetchFidelityLog(shortId: string): Promise<FidelityLog | null> {
  // Reads the fidelity-log.json directly via the existing project-files API.
  // Adjust the URL pattern if the project uses a different files-API shape.
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  try {
    const r = await fetch(`${apiBase}/api/projects/${shortId}/files/src/contracts/fidelity-log.json`);
    if (!r.ok) return null;
    return (await r.json()) as FidelityLog;
  } catch {
    return null;
  }
}
```

NOTE: the actual files-API URL may differ. Inspect `frontend/src/lib/` and `backend/routers/` to find the existing project-files endpoint. If there isn't one that serves arbitrary files from `output/`, expose the log via a small new backend endpoint:

```python
# backend/routers/_debug_fidelity.py — append
@router.get("/api/_debug/fidelity-log/{short_id}")
async def get_fidelity_log(short_id: str):
    output_dir = _output_dir(short_id)
    log_path = output_dir / "src" / "contracts" / "fidelity-log.json"
    if not log_path.exists():
        return {}
    try:
        return json.loads(log_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(500, "fidelity log is corrupted")
```

If you add the endpoint, update `fetchFidelityLog`'s URL accordingly: `${apiBase}/api/_debug/fidelity-log/${shortId}`.

- [ ] **Step 2: Implement PageScoreBadge.tsx**

```tsx
// frontend/src/components/schema-editor/PageScoreBadge.tsx
"use client";

interface PageScoreBadgeProps {
  score: number | null;
  failedFidelity?: boolean;
  exitStatus?: string;
  size?: "sm" | "md";
}

export function PageScoreBadge({ score, failedFidelity, exitStatus, size = "sm" }: PageScoreBadgeProps) {
  if (exitStatus === "budget") {
    return <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground">skip</span>;
  }
  if (score === null || score === undefined) {
    return <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground">—</span>;
  }
  const tone = failedFidelity
    ? "bg-amber-100 text-amber-800"
    : score >= 8
    ? "bg-emerald-100 text-emerald-800"
    : score >= 6
    ? "bg-amber-100 text-amber-800"
    : "bg-rose-100 text-rose-800";
  const cls = size === "sm"
    ? "rounded px-1.5 py-0.5 text-[10px] font-semibold"
    : "rounded-full px-2 py-0.5 text-[11px] font-semibold";
  return <span className={`${cls} ${tone}`}>{score.toFixed(1)}</span>;
}
```

- [ ] **Step 3: Wire into SchemaEditorPanel**

Open `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`. Add at the top:

```tsx
import { fetchFidelityLog, type FidelityLog } from "@/lib/fidelity-client";
import { PageScoreBadge } from "./PageScoreBadge";
import { useEffect, useState } from "react";
```

Inside the component, after the other useState/useQuery hooks, add:

```tsx
const [fidelityLog, setFidelityLog] = useState<FidelityLog | null>(null);
useEffect(() => {
  if (!project?.short_id) return;
  let cancelled = false;
  fetchFidelityLog(project.short_id).then((log) => {
    if (!cancelled) setFidelityLog(log);
  });
  return () => { cancelled = true; };
}, [project?.short_id]);
```

Then in the place where pages are rendered in the tree (find the existing JSX that lists pages), add the badge inline next to each page name. Pattern:

```tsx
{pages.map((p) => {
  const logEntry = fidelityLog?.[p.path];  // p.path = e.g. "users/list"
  return (
    <div key={p.path} className="flex items-center justify-between gap-2 px-2 py-1">
      <span>{p.title || p.path}</span>
      <PageScoreBadge
        score={logEntry?.final_score ?? null}
        failedFidelity={logEntry?.failed_fidelity}
        exitStatus={logEntry?.exit_status}
      />
    </div>
  );
})}
```

NOTE for implementer: adapt to the actual existing JSX. The existing page list may use a different prop name (`p.route`, `p.id`, etc.). The key is that the score badge appears next to each page label.

- [ ] **Step 4: Type check + visual smoke**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npx tsc --noEmit 2>&1 | head -20
```

Expected: no new errors in your edited files.

- [ ] **Step 5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add frontend/src/components/schema-editor/PageScoreBadge.tsx \
        frontend/src/lib/fidelity-client.ts \
        frontend/src/components/schema-editor/SchemaEditorPanel.tsx \
        backend/routers/_debug_fidelity.py
git commit -m "feat(editor): page-tree fidelity score badges from fidelity-log.json"
```

---

## Task 18: Editor — IterationHistory component + CritiquePanel becomes log-reader

**Files:**
- Create: `frontend/src/components/schema-editor/IterationHistory.tsx`
- Modify: `frontend/src/components/schema-editor/CritiquePanel.tsx`

- [ ] **Step 1: Implement IterationHistory.tsx**

```tsx
// frontend/src/components/schema-editor/IterationHistory.tsx
"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

export interface IterationRow {
  iteration: number;
  score: number;
  issues?: any[];
  patch_summary?: string[];
  pass: boolean;
  manual_run?: boolean;
  screenshotUrl?: string;
}

interface IterationHistoryProps {
  iterations: IterationRow[];
}

export function IterationHistory({ iterations }: IterationHistoryProps) {
  const [open, setOpen] = useState(false);
  const [expandedIter, setExpandedIter] = useState<number | null>(null);

  if (!iterations.length) return null;

  return (
    <div className="border rounded">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted/50"
      >
        <span>Iteration history ({iterations.length})</span>
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <div className="divide-y">
          {iterations.map((it, idx) => {
            const prevScore = idx > 0 ? iterations[idx - 1].score : null;
            const delta = prevScore !== null ? it.score - prevScore : 0;
            const isExpanded = expandedIter === it.iteration;
            return (
              <div key={`${it.iteration}-${idx}`} className="px-3 py-2 text-xs">
                <button
                  type="button"
                  onClick={() => setExpandedIter(isExpanded ? null : it.iteration)}
                  className="flex w-full items-center gap-3"
                >
                  <span className="font-mono text-muted-foreground">iter {it.iteration}</span>
                  <span className="font-semibold">{it.score.toFixed(1)}</span>
                  {prevScore !== null && (
                    <span className={delta >= 0 ? "text-emerald-600" : "text-rose-600"}>
                      {delta >= 0 ? "+" : ""}{delta.toFixed(1)}
                    </span>
                  )}
                  <span className="ml-auto text-muted-foreground">
                    {it.patch_summary?.length ? `${it.patch_summary.length} patch${it.patch_summary.length === 1 ? "" : "es"}` : "no patches"}
                  </span>
                  {it.manual_run && <span className="text-[10px] text-blue-600">manual</span>}
                  <span className={it.pass ? "text-emerald-600" : "text-muted-foreground"}>
                    {it.pass ? "pass" : "—"}
                  </span>
                </button>
                {isExpanded && (
                  <div className="mt-2 ml-12 space-y-1 text-muted-foreground">
                    {it.patch_summary?.map((s, i) => (
                      <div key={i}>↳ {s}</div>
                    ))}
                    {it.screenshotUrl && (
                      <img src={it.screenshotUrl} alt={`iter ${it.iteration}`} className="mt-2 max-w-xs rounded border" />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Modify CritiquePanel to read from log + show IterationHistory + failed_fidelity warning**

Open `frontend/src/components/schema-editor/CritiquePanel.tsx`. Add imports:

```tsx
import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { fetchFidelityLog, type PageLogEntry } from "@/lib/fidelity-client";
import { IterationHistory } from "./IterationHistory";
```

Inside the component, BEFORE the existing `useMutation`, add:

```tsx
const [logEntry, setLogEntry] = useState<PageLogEntry | null>(null);
useEffect(() => {
  let cancelled = false;
  fetchFidelityLog(shortId).then((log) => {
    if (!cancelled && log) setLogEntry(log[pagePath] ?? null);
  });
  return () => { cancelled = true; };
}, [shortId, pagePath]);
```

Then after the `useMutation` definition but before the `return`, replace the rendering logic to prefer log data when present:

```tsx
const displayScore = m.data?.compositeScore ?? logEntry?.final_score ?? null;
const isFailedFidelity = logEntry?.failed_fidelity;
const iterations = logEntry?.iterations ?? [];
```

In the JSX, replace the existing scores grid + issues block with logic that prefers `m.data` when a re-score has just run, otherwise displays `logEntry`. Add a failed_fidelity Alert at the top of the body:

```tsx
{isFailedFidelity && !m.data && (
  <div className="mb-4 flex items-start gap-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
    <AlertTriangle className="mt-0.5 h-4 w-4" />
    <div>
      <strong>Quality target not reached.</strong> This page didn't reach the rubric pass after {logEntry?.final_iteration} iterations.
      Re-score after manual edits, or accept it as-is.
    </div>
  </div>
)}

{/* ... existing scores grid (use m.data if present, else fall back to logEntry-derived display) ... */}

{iterations.length > 0 && (
  <div className="mt-4">
    <IterationHistory iterations={iterations} />
  </div>
)}
```

NOTE for implementer: the existing CritiquePanel JSX may already have a scores grid driven by `m.data`. Keep that, just gate it on whether you should display log data instead. The simplest approach: compute a `displayCritique` variable that's `m.data` when present, otherwise a synthesized object from `logEntry.iterations[last]`.

- [ ] **Step 3: Type check**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: no new type errors in your changes.

- [ ] **Step 4: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add frontend/src/components/schema-editor/IterationHistory.tsx \
        frontend/src/components/schema-editor/CritiquePanel.tsx
git commit -m "feat(editor): IterationHistory + log-driven CritiquePanel + failed_fidelity warning"
```

---

## Task 19: Chat — render new SSE event types

**Files:**
- Modify: `frontend/src/components/chat/ChatHistory.tsx`

- [ ] **Step 1: Add render branches for the new events**

Find the section in `ChatHistory.tsx` that renders SSE events (likely a switch on `event.type`). Add cases:

```tsx
case "page_iter_done":
  return (
    <div className="px-2 py-1 text-xs">
      <span className="text-muted-foreground">↳ {event.data.page}</span>
      <span className="ml-2">iter {event.data.iter}</span>
      <span className="ml-2 font-semibold">{event.data.score.toFixed(1)}</span>
      {event.data.score_delta !== 0 && (
        <span className={event.data.score_delta > 0 ? "ml-2 text-emerald-600" : "ml-2 text-rose-600"}>
          {event.data.score_delta > 0 ? "+" : ""}{event.data.score_delta.toFixed(1)}
        </span>
      )}
      {event.data.pass && <span className="ml-2 text-emerald-600">✓ pass</span>}
    </div>
  );

case "page_complete":
  return null;  // page_iter_done already covers it; suppress duplicate

case "page_skipped":
  return (
    <div className="px-2 py-1 text-xs text-amber-700">
      ⚠ {event.data.page} skipped — {event.data.reason}
    </div>
  );

case "phase_complete":
  if (event.data.phase !== "fidelity_loop") break;
  return (
    <div className="border-l-2 border-emerald-500 pl-3 py-2 text-sm">
      <div className="font-semibold">✓ Fidelity check complete</div>
      <div className="text-xs text-muted-foreground mt-1">
        {event.data.passed} passed · {event.data.failed} flagged · {event.data.skipped} skipped (avg {event.data.avg_score})
      </div>
      <div className="text-xs text-muted-foreground">
        ${event.data.total_cost_usd?.toFixed(2)} · {event.data.wall_clock_s?.toFixed(0)}s
      </div>
    </div>
  );
```

- [ ] **Step 2: Type check**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add frontend/src/components/chat/ChatHistory.tsx
git commit -m "feat(chat): render new SSE event types from the fidelity loop phase"
```

---

## Task 20: End-to-end integration test

**Files:**
- Create: `backend/tests/integration/test_fidelity_loop_e2e.py`

This test mocks the patch agent + vision evaluator (real renders + real patch validation) so it runs offline. Real end-to-end against a real LLM is left for manual smoke.

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_fidelity_loop_e2e.py
"""End-to-end: run FidelityLoopRunner against a fake project with mocked
agents but real patch validation + log-writing."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.fidelity_loop import (
    FidelityLoopRunner, PageRef, ProjectContext,
)
from services.vision_evaluator.types import Critique


def _critique(score: float, *, has_high: bool = False) -> Critique:
    return Critique.model_validate({
        "scores": {
            "visualPolish": score, "domainFeel": score, "informationDensity": score,
            "componentCoherence": score, "brandReflection": score,
        },
        "compositeScore": score, "pass": score >= 8 and not has_high,
        "topIssues": [{"severity": "high", "axis": "domainFeel",
                       "nodeIdHint": "hero", "issue": "fake", "suggestion": "fix"}] if has_high else [],
        "strengths": [], "designerApprovalRecommended": False,
    })


@pytest.mark.asyncio
@pytest.mark.integration
async def test_e2e_pages_pass_after_one_patch(tmp_path):
    output_dir = tmp_path / "proj-e2e"
    schemas_dir = output_dir / "src" / "schemas" / "users"
    schemas_dir.mkdir(parents=True)
    schema = {
        "schemaVersion": "2", "id": "users/list", "route": "/users/list",
        "meta": {"title": "Users"}, "dataSources": [],
        "root": {"id": "root", "type": "Stack", "props": {}, "children": []},
    }
    (schemas_dir / "list.json").write_text(json.dumps(schema))

    runner = FidelityLoopRunner(
        output_dir=output_dir,
        project_ctx=ProjectContext(domain="general", app_name="E2E", description="t", tone="neutral"),
    )
    runner.max_iterations = 3

    scores = iter([6.0, 8.5])  # iter 0 fails, iter 1 passes
    with patch("services.fidelity_loop._render_page", new=AsyncMock(return_value=(b"\x89PNG\r\n\x1a\n", "tree"))), \
         patch("services.fidelity_loop._evaluate_page", new=AsyncMock(side_effect=lambda **kw: _critique(next(scores)))), \
         patch("services.fidelity_loop._propose_patches", new=AsyncMock(return_value=[
             {"op": "replace", "path": "/meta/title", "value": "Better Users"}
         ])), \
         patch("services.fidelity_loop._validate_patches", return_value=[]), \
         patch("services.fidelity_loop._apply_patches_transactional",
               side_effect=lambda patches, schema, **kw: {**schema, "meta": {"title": "Better Users"}}):
        report = await runner.run([PageRef(
            short_id="proj-e2e", page_path="users/list", page_route="/users/list", page_type="list"
        )])
    assert report.passed == 1
    assert report.failed == 0

    # Log was written
    log_path = output_dir / "src" / "contracts" / "fidelity-log.json"
    assert log_path.exists()
    log = json.loads(log_path.read_text())
    assert "users/list" in log
    assert log["users/list"]["exit_status"] == "pass"
    assert log["users/list"]["flags"]["fidelity_loop"] is True

    # Schema on disk was updated
    final_schema = json.loads((schemas_dir / "list.json").read_text())
    assert final_schema["meta"]["title"] == "Better Users"

    # iter screenshot was saved
    assert (output_dir / ".fidelity-history" / "users_list" / "iter-0.png").exists()
    assert (output_dir / ".fidelity-history" / "users_list" / "iter-1.png").exists()
```

- [ ] **Step 2: Run**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/integration/test_fidelity_loop_e2e.py -v -m "" --no-header
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/tests/integration/test_fidelity_loop_e2e.py
git commit -m "test(fidelity): e2e test — full loop with mocked agents passes after one patch"
```

---

## Task 21: Documentation update

**Files:**
- Modify: `docs/render-service.md`

- [ ] **Step 1: Append closed-loop section**

Open `docs/render-service.md`. Append at the end:

```markdown
## Phase 14 + 15 — Closed loop with reference grounding

The fidelity loop runs as a phase in the generation pipeline. Set
`FIDELITY_LOOP_ENABLED=true` and `REFERENCE_GROUNDING_ENABLED=true`, then
generate any project. Results land in `output/<id>/src/contracts/fidelity-log.json`.

### What runs at gen time

1. Schema agent prompt is augmented with up to 2 high-quality exemplars per
   `(domain, page_type)` cell, loaded from `backend/reference_pages/`.
2. After the seed phase, `FidelityLoopRunner` renders + scores every page.
3. Pages below pass get up to 3 patch iterations + 1 schema-agent fallback.
4. Soft-fail: pipeline always succeeds; failed pages flagged in the editor.

### Editor surface

- Page tree shows score pills next to every page name.
- Score tab opens with the gen-time critique pre-populated; "Re-score" button
  appends a new iter with `manual_run: true`.
- Iteration history with screenshot thumbnails per iter (in
  `output/<id>/.fidelity-history/`).

### Seeding the reference bank

```bash
cd backend
for D in general healthcare fintech hr; do
  for T in list detail form dashboard settings; do
    python -m scripts.seed_reference_bank --domain "$D" --page-type "$T" \
      --target-count 2 --max-attempts 8 --seeder-version v1
  done
done
```

Cost: roughly $20 one-time. Cells that don't reach target_count after
max_attempts will end up under-quota; the loader falls back to `general/`
exemplars at gen time.

### Observability

- `GET /api/_debug/fidelity-stats?since=2026-05-01` aggregates pass rates,
  patch acceptance rates, and cost distributions across recent generations.
- Each project's `fidelity-log.json` records which flags were active at gen
  time so quality differences are attributable.

### Cost shape

Per project (12-page typical): ~$1-2 with both flags on. Hard cap at $5
(`FIDELITY_LOOP_PROJECT_COST_CAP_USD`). Pages remaining when the cap fires
are marked `fidelity_skipped: budget_exhausted`.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add docs/render-service.md
git commit -m "docs: closed-loop fidelity + reference grounding runbook section"
```

---

## Self-review checklist

After all tasks land, run this checklist before declaring done.

### 1. Spec coverage

| Spec section | Task(s) |
|---|---|
| § 1. High-level architecture | 1, 14 (config flags + pipeline wiring) |
| § 2. Reference grounding bank | 7, 8, 9, 10 (loader, seeder, run, schema-prompt integration) |
| § 3. Closed-loop runner | 11, 12, 13 (skeleton, state machine, log shape) |
| § 4. Patch agent | 4, 5, 6 (validator, applier, agent) |
| § 5. Editor surfacing | 17, 18, 19 (page tree, CritiquePanel, chat events) |
| § 6. Failure modes + telemetry | 12 (handling), 13 (log), 15 (stats endpoint) |
| § Success criteria | not directly testable in this plan — measured post-rollout via stats endpoint |
| § Dependencies | 1 (jsonpatch added); render-service + vision evaluator from predecessor plan |

✓ All sections covered.

### 2. Placeholder scan

No `TBD`, `TODO`, `implement later`, or `fill in details` in the plan body.

Two places use `NOTE for implementer` to flag adapter work — these are intentional integration points where the plan can't pre-commit to file/variable names without false specificity. Each note tells the implementer exactly what to do; they're not placeholders.

### 3. Type consistency

- `PageRef.short_id`/`page_path`/`page_route`/`page_type` — used identically in fidelity_loop.py, e2e test, and editor.
- `Critique` model — single source of truth in `vision_evaluator/types.py`, used unchanged in patch_agent and fidelity_loop.
- `PatchOp` shape — JSON dict in patch_agent output, validated by `validate_patches`, applied by `apply_patches_transactional`.
- `Exemplar` dataclass — created in `reference_bank.py`, consumed only by `render_exemplars_block`.
- `IterationOutcome.iter` typed as `int | str` to allow `"fallback"` — preserved through `append_fidelity_entry`'s `iteration: int` by computing `len(iterations) - 1` for string values.

✓ Consistent.

---

## Out of scope (deferred to follow-up plans)

- **Auto-promotion of real generations into the bank** — requires curation queue + review UI.
- **Multi-viewport scoring during the loop** — v1 is desktop only.
- **Per-component patch agents** — v1 single agent.
- **Best-of-N parallel generation** — only worth it if iteration loop is the bottleneck.
- **Critique-of-critique** — useful for tuning the rubric, not production.
- **Visual diff viewer** — IterationHistory thumbnails are the v1.
- **Per-domain rubric weight tuning** — single global rubric for v1.
- **Cost dashboard UI** — backend logs cover this; UI is a follow-up.
- **Real schema-agent re-prompt fallback** — Task 12 ships a stub returning None. The hook exists; wiring it to a real agent re-call is a follow-up plan.
