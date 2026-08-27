# Planner Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cut the planner's LLM wall-clock from ~15 min → ~2–3 min on rich-domain generations (ATS, healthcare, marketplace) without giving up plan depth.

**Architecture:** two levers, applied together. **(1)** route the smith-arch orchestrator through Forge's existing `should_decompose` → `run_app_map_planner` → `author_all_units` decomposition adapter (currently only the classic `produce_plan` path uses it). **(2)** cap `max_tokens` at 24K + add a "prefer terse plans" nudge in the system prompt so the per-unit LLM calls finish faster. Together: a lean skeleton in ~1 min, per-unit detail in parallel (each ~30–60s), merged into a shape-identical dict downstream consumers already accept.

**Tech Stack:** Python 3.11, Anthropic Sonnet (streaming), asyncio, pytest.

---

## Context — where the ceiling actually is

Anthropic streams roughly 50–100 output tokens/second. A rich ATS plan is ~25–30K output tokens. Math: 30K ÷ 50 = 10 min at the wire, plus queue time = 15+ min observed. This ceiling is **per LLM call**. The only way past it is (a) shrink each call's output OR (b) fan out into multiple concurrent calls.

Forge already has the fan-out infrastructure (`services/app_decomposition.py`, `services/per_unit_authoring.py`) — the classic `produce_plan` path uses it when `_should_decompose(prompt)` returns True. Smith-arch (`services/smith_agent_adapters.py::orchestrate_planner`) currently bypasses this and always calls `run_planner_oneshot`. **This plan closes that gap.**

## Non-goals

- We are **not** replacing `run_planner_oneshot`. The single-call path stays as the fallback for small apps and figma-driven plans.
- We are **not** changing the plan schema. Downstream consumers (`_ensure_normalized_plan`, wire passes, validator, emitters) must receive a shape-identical plan dict.
- We are **not** downgrading the model tier. Sonnet stays; only the token cap and the fan-out topology change.
- We are **not** removing the narrative expansion. It's the reason plans are actually good now.

## File Structure

**Modify:**
- `backend/services/smith_agent_adapters.py` — teach `orchestrate_planner` to consult `should_decompose` and route through the decomposition adapter.
- `backend/agents/planner.py` — lower `max_tokens` cap 32K → 24K and add a terse-plan instruction in `_ONESHOT_SYSTEM_PROMPT`.
- `backend/services/plan_wire_pipeline.py` — no code change; call sites still receive the same shape.
- `backend/services/streaming_llm.py` — extend `emit_fn` protocol so the decomposition path can report per-unit progress ("Authoring unit 3/8: /candidates/[id]"). Payload compatible with existing frontend chip narrator.

**Create:**
- `backend/tests/test_orchestrate_planner_decomposition.py` — new file. Tests that `orchestrate_planner` invokes the decomposition adapter when the gate fires, and falls back to `run_planner_oneshot` when it doesn't.
- `backend/tests/test_planner_terse_prompt.py` — new file. Lockdown tests that the terse-plan instruction sits inside `_ONESHOT_SYSTEM_PROMPT` (analogous to `test_planner_platform_primitives_prompt.py`).

**Existing files to read (no changes):**
- `backend/services/app_decomposition.py::should_decompose` — the gate.
- `backend/agents/app_map_agent.py::run_app_map_planner` — the skeleton call.
- `backend/services/per_unit_authoring.py::author_all_units` — the parallel filler.
- `backend/routers/generate.py::produce_plan` (lines 322–356) — reference for how the classic path stitches them together.

## Task Structure

### Task 1: Read the existing decomposition adapter and confirm it emits a shape-compatible plan dict

**Files:**
- Read: `backend/services/app_decomposition.py`
- Read: `backend/agents/app_map_agent.py`
- Read: `backend/services/per_unit_authoring.py`
- Read: `backend/routers/generate.py:322-356` (the `_should_decompose` branch inside `produce_plan`)

- [ ] **Step 1: Confirm the return shape**

Trace `_author_units(skeleton, output_dir)` and confirm its return value passes through:
- `_ensure_normalized_plan`
- `build_canonical_registry`
- `apply_plan_wires` (my Slice 12 registry)
- `_sync_workflows_from_plan`

All must accept the decomposed plan as-is with no branching. Document any diffs in the plan file's structure between the one-shot output and the decomposed output.

- [ ] **Step 2: Note the emit_fn signature the classic path uses**

`produce_plan` accepts `emit` and threads it through. Confirm what stage names are emitted during decomposition (e.g. `app_map_start`, `unit_authored`). We need to preserve these when calling from smith-arch.

- [ ] **Step 3: Commit (no code changes — just notes in this plan)**

Add a "Return-shape audit — findings" subsection here summarizing what you found. No git commit; the plan doc is source of truth.

**Return-shape audit — findings (2026-07-20)**

Read the three modules in place:

| Function | Signature | Sync/async | Return shape |
|---|---|---|---|
| `should_decompose(prompt, skeleton=None, threshold=None)` | prompt-only in practice | sync | `bool`. Never raises. Threshold from `FORGE_DECOMPOSE_THRESHOLD` (default 20 entities). |
| `run_app_map_planner(prompt, domain_context)` | — | sync | Skeleton dict (plan-shaped with lean `pages` list + `data_models` + `workflows` + `roles`). |
| `author_all_units(skeleton, output_dir, *, concurrency=5)` | `concurrency` accepted but IGNORED | **sync** | Assembled plan dict (shape-identical to a one-shot plan). |

**Key finding — current author_all_units is sequential, not parallel.** Its docstring is explicit: *"SEQUENTIAL — chosen over the semaphore fan-out for simplicity + determinism; `concurrency` is accepted for the wiring task's signature but the pass is I/O-light per page and order-stable this way."*

**Implication for Task 3:** routing smith-arch through this adapter without also parallelizing it can make things WORSE, not better. For a 20-page ATS at 15-30s per page authored sequentially = 5-10 minutes JUST for the units, plus the 1-min skeleton = 6-11 min. Similar to today's one-shot.

**Adjusted approach for Task 3 (below):** either (a) genuinely parallelize `author_all_units` with `asyncio.gather` + a semaphore, or (b) accept the sequential path for correctness but couple it with Task 2's smaller max_tokens so each unit call is smaller/faster. Task 4's per-unit SSE events help either way.

Task 2 is a pure win regardless of Task 3 status — it shrinks a single 30K plan to ~20K, which is roughly 30% wall-clock reduction on the current one-shot path.

### Task 2: Lower planner max_tokens 32K → 24K + add terse-plan instruction

**Files:**
- Modify: `backend/agents/planner.py:2088-2103` (planner streaming call max_tokens=32000)
- Modify: `backend/agents/planner.py:1608-1849` (`_ONESHOT_SYSTEM_PROMPT` — add a `TERSENESS` section near the existing `TIMING` section around line 1845)
- Test: `backend/tests/test_planner_terse_prompt.py`

- [ ] **Step 1: Write the failing lockdown test**

```python
"""Lockdown for the terse-plan instruction that keeps per-unit and
one-shot planner outputs from ballooning past the max_tokens cap."""
from agents.planner import _ONESHOT_SYSTEM_PROMPT


def test_prompt_teaches_terseness():
    lower = _ONESHOT_SYSTEM_PROMPT.lower()
    assert "terse" in lower or "concise" in lower or "no redundant" in lower


def test_prompt_names_max_tokens_ceiling_as_a_reason_to_be_lean():
    """The model should know WHY it needs to be concise — output
    tokens are the wall-clock bottleneck. Otherwise a well-behaved
    model expands to fill the space it's given."""
    lower = _ONESHOT_SYSTEM_PROMPT.lower()
    assert "output tokens" in lower or "wall-clock" in lower \
        or "24000" in lower or "budget" in lower


def test_prompt_still_documents_platform_primitive_slots():
    """Terseness must not remove the primitive-slot documentation
    from Slice 12 (that's what makes plans domain-rich)."""
    for slot in ("audit_trail", "immutability", "field_visibility",
                 "capacity_constraints", "wizards"):
        assert slot in _ONESHOT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run and confirm it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_planner_terse_prompt.py -v`
Expected: FAIL on `test_prompt_teaches_terseness` (no "terse" or "concise" in prompt yet).

- [ ] **Step 3: Add the TERSENESS section to `_ONESHOT_SYSTEM_PROMPT`**

Inside `_ONESHOT_SYSTEM_PROMPT`, right after `TIMING:` (around line 1849), add:

```
TERSENESS:
- The plan flows through downstream deterministic emitters that DO NOT
  need prose descriptions. Every field's `description` and every entity's
  `description` costs output tokens without adding capability — you have
  a hard cap and streaming is the wall-clock bottleneck (~50-100 tokens/
  second).
- Prefer NO description at all unless a name is genuinely ambiguous.
  Names carry their own semantics ("Feedback" is a Feedback).
- Do NOT include example values, sample data, or "e.g." illustrations
  inside JSON strings. Real seed rows come from a later stage.
- If you catch yourself writing a sentence explaining something the
  planner reader would already know from the entity/field name, DELETE
  it before emitting.
- Your 24000-token output budget is a hard ceiling. Truncated JSON =
  parse failure = generation restart. Better a lean plan than a rich
  one that got cut mid-sentence.
```

- [ ] **Step 4: Lower `max_tokens=32000` to `max_tokens=24000`**

At line 2088 in `agents/planner.py` (inside the streaming branch), change:
```python
max_tokens=32000,
```
to:
```python
max_tokens=24000,
```

Update the comment above it to match. Also change the same value in the non-streaming fallback branch at line 2107.

- [ ] **Step 5: Run test to verify PASS**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_planner_terse_prompt.py -v`
Expected: PASS (all 3).

Also re-run the primitive prompt lockdown to confirm no regression:
Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_planner_platform_primitives_prompt.py -v`
Expected: PASS (all 11).

- [ ] **Step 6: Commit**

```bash
git add backend/agents/planner.py backend/tests/test_planner_terse_prompt.py
git commit -m "feat(planner): terse-plan instruction + 24K cap"
```

### Task 3: Route smith-arch's orchestrate_planner through the decomposition adapter when the gate fires

**Files:**
- Modify: `backend/services/smith_agent_adapters.py:364-450` (`orchestrate_planner`)
- Test: `backend/tests/test_orchestrate_planner_decomposition.py`

- [ ] **Step 1: Write the failing behavioral test**

```python
"""Tests for orchestrate_planner's decomposition routing. The
smith-arch path used to always call run_planner_oneshot; it now
consults should_decompose and routes through the decomposition
adapter for large prompts to cut wall-clock time by ~3-5x."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from services.smith_agent_adapters import orchestrate_planner


def _plan_shape() -> dict:
    """Minimal plan shape that survives plan_dict_to_artifact +
    apply_plan_wires without exploding."""
    return {
        "actors":      [],
        "data_models": [{"name": "Thing", "fields": [{"name": "id"}]}],
        "workflows":   [],
        "pages":       [],
    }


def test_decomposition_adapter_used_when_gate_fires(monkeypatch):
    """A big prompt should trigger the two-stage path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", return_value={"pages": []},
    ) as m_skel, patch(
        "services.per_unit_authoring.author_all_units",
        return_value=_plan_shape(),
    ) as m_units, patch(
        "agents.planner.run_planner_oneshot", return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="A big rich domain prompt with lots of entities",
            output_dir="/tmp/test-decomp-abc",
        ))
        assert m_skel.called,   "should call the skeleton planner"
        assert m_units.called,  "should call the per-unit authoring"
        assert not m_oneshot.called, "one-shot must NOT run when decomposition fires"
        assert art is not None


def test_oneshot_used_when_gate_declines(monkeypatch):
    """Small prompts stay on the fast one-shot path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with patch(
        "services.app_decomposition.should_decompose", return_value=False,
    ), patch(
        "agents.planner.run_planner_oneshot", return_value=_plan_shape(),
    ) as m_oneshot, patch(
        "agents.app_map_agent.run_app_map_planner",
    ) as m_skel:
        art = asyncio.run(orchestrate_planner(
            description="tiny prompt",
            output_dir="/tmp/test-oneshot-abc",
        ))
        assert m_oneshot.called
        assert not m_skel.called
        assert art is not None


def test_decomposition_failure_falls_back_to_oneshot(monkeypatch):
    """If the two-stage path raises, we degrade gracefully — a
    broken decomposition must NEVER kill generation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def _boom(*_a, **_kw):
        raise RuntimeError("skeleton broke")

    with patch(
        "services.app_decomposition.should_decompose", return_value=True,
    ), patch(
        "agents.app_map_agent.run_app_map_planner", side_effect=_boom,
    ), patch(
        "agents.planner.run_planner_oneshot", return_value=_plan_shape(),
    ) as m_oneshot:
        art = asyncio.run(orchestrate_planner(
            description="big prompt", output_dir="/tmp/test-fallback-abc",
        ))
        assert m_oneshot.called, "must fall back to one-shot on decomposition error"
        assert art is not None
```

- [ ] **Step 2: Run — expect FAIL on all three tests (no branching exists yet)**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_orchestrate_planner_decomposition.py -v`
Expected: FAIL on `test_decomposition_adapter_used_when_gate_fires` — currently orchestrate_planner always calls run_planner_oneshot.

- [ ] **Step 3: Add the decomposition branch in `orchestrate_planner`**

Right before the `# ── Turn 0: initial plan` marker (currently around line 411), add:

```python
# Decomposition branch — for large prompts we want per-unit parallel
# authoring instead of one big streaming call. Uses the same adapter
# the classic `produce_plan` path uses (Forge's existing infrastructure);
# just calls it from smith-arch too. Fall back to one-shot on ANY
# error so a broken decomposition never blocks planning.
try:
    from services.app_decomposition import should_decompose
    from agents.app_map_agent import run_app_map_planner
    from services.per_unit_authoring import author_all_units
    _decompose = bool(should_decompose(description))
except Exception:  # noqa: BLE001
    logger.exception("orchestrate_planner: should_decompose crashed; using one-shot")
    _decompose = False

if _decompose and output_dir is not None:
    try:
        skeleton = run_app_map_planner(description, domain_context)
        plan_dict = author_all_units(skeleton, output_dir)
        plan_dict = apply_plan_wires(plan_dict)
        return _pack(plan_dict)
    except Exception:  # noqa: BLE001
        logger.exception(
            "orchestrate_planner: decomposition failed; falling back to one-shot"
        )
        _emit(
            "planner_fallback",
            "Decomposition failed, falling back to one-shot planner",
        )
```

The existing `plan_dict = await run_planner_oneshot(...)` call becomes the fallback when either the gate declines or decomposition raises.

- [ ] **Step 4: Run to verify all three tests pass**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_orchestrate_planner_decomposition.py -v`
Expected: 3/3 PASS.

- [ ] **Step 5: Run the whole smith-adapter test file to catch regressions**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_smith_agent_adapters.py -v`
Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/services/smith_agent_adapters.py backend/tests/test_orchestrate_planner_decomposition.py
git commit -m "feat(smith-arch): route orchestrate_planner through the decomposition adapter"
```

### Task 4: Thread per-unit progress into the SSE stream

**Files:**
- Modify: `backend/services/per_unit_authoring.py` (add `emit_fn` param, emit `unit_authored` per completed unit)
- Modify: `backend/services/smith_agent_adapters.py` (pass `emit_fn` down)
- Modify: `frontend/src/stores/chat.ts` (route `unit_authored` through the smithThoughts chip channel)
- Modify: `frontend/src/components/chat/smithNarration.ts` (case for `unit_authored`)

- [ ] **Step 1: Read `per_unit_authoring.py` and confirm where the parallel loop lives**

Look for the `asyncio.gather` / `parallel` call that fans out per-unit work. That's where we hook `emit_fn`.

- [ ] **Step 2: Add optional `emit_fn` to `author_all_units`**

Signature change:
```python
async def author_all_units(
    skeleton: dict, output_dir: str, *, emit_fn: Any = None,
) -> dict:
```

Inside the parallel loop, wrap each unit-authoring call so that on completion it invokes:
```python
if emit_fn is not None:
    try:
        emit_fn("unit_authored", {
            "text":       f"+ {unit_name}",
            "unit_name":  unit_name,
            "completed":  n_done + 1,
            "total":      n_total,
        })
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 3: Pass `emit_fn` down from `orchestrate_planner`**

At the decomposition branch site, update:
```python
plan_dict = author_all_units(skeleton, output_dir, emit_fn=emit_fn)
```

- [ ] **Step 4: Frontend — route `unit_authored` through the chip channel**

In `frontend/src/stores/chat.ts`, add `unit_authored` to the same case-block as the other planner streaming events (near the `planner_call_semantic` handler).

- [ ] **Step 5: Frontend — narrator entry**

In `frontend/src/components/chat/smithNarration.ts`, add:
```typescript
case "unit_authored": {
  return { icon: "➕", text: s || "Unit authored" };
}
```

- [ ] **Step 6: Test — run the browser smoke**

Run the frontend at http://localhost:6501 and confirm no console errors after the edits.

- [ ] **Step 7: Commit**

```bash
git add backend/services/per_unit_authoring.py backend/services/smith_agent_adapters.py frontend/src/stores/chat.ts frontend/src/components/chat/smithNarration.ts
git commit -m "feat(planner): per-unit progress events during decomposition"
```

### Task 5: Live acceptance — measure wall-clock on a rich-domain generation

**Files:**
- Read: `backend/routers/generate.py` (find the SSE stream endpoint)
- Modify: only if timing instrumentation is missing.

- [ ] **Step 1: Ensure the existing pipeline logs planner elapsed time**

Grep for `[smith-arch] bootstrap stage=planning` in `services/smith_architect_wire.py` — this event should carry an elapsed-seconds number OR the log line before it should. If it doesn't, add one.

- [ ] **Step 2: Kick off a fresh ATS generation via the UI**

The prompt is your existing "Design the ATS for the Cabin Crew Recruitment for the Aviation Industry" one. Approve the discovery card. Watch the chip stream — you should see:

- Discovery ~2 min
- Narrative expansion ~30-90s (chip stream monotonic char counts)
- Skeleton planner call ~30-60s (no chunk chips — small call)
- Per-unit chips (`+ /candidates`, `+ /candidates/[id]`, `+ /audit`, …) fanning out
- Wire passes (audit_trail, wizards, etc.)
- Post-generate fixes

- [ ] **Step 3: Record actual wall-clock and compare**

Before/after target:
- Before: ~15 min (single 30K-token call streaming sequentially)
- After: expected ~2–3 min (1 min skeleton + max(parallel unit calls) ≈ 60-90s)

If wall-clock is not under 5 min, the fan-out concurrency is being throttled somewhere (Anthropic tier limits, or per_unit_authoring uses an asyncio.Semaphore that's too small). Investigate: check tier from `anthropic.AsyncAnthropic().beta.usage.list()` OR the semaphore parameter to `author_all_units`.

- [ ] **Step 4: Document result**

Append a new section to this plan file called "Acceptance measurement" with:
- The commit SHA of the generation
- The prompt
- Actual wall-clock for narrative + planner
- Any concurrency knobs you had to raise

- [ ] **Step 5: Commit acceptance notes**

```bash
git add docs/superpowers/plans/2026-07-20-planner-parallelization.md
git commit -m "docs(planner-parallel): acceptance notes from ATS run"
```

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Decomposed plan omits cross-references (workflow names entity that doesn't exist yet in the skeleton) | Medium | Skeleton must fix the naming contract BEFORE unit calls. This is what `run_app_map_planner` already does — verify in Task 1. |
| Per-unit calls hit Anthropic tier concurrency limit | Medium | If observed, add a semaphore (start with 6) inside `author_all_units`. |
| Terse instruction (Task 2) drops the primitive-slot declarations | Low | Task 2 test `test_prompt_still_documents_platform_primitive_slots` guards against this. |
| Decomposition breaks the wire passes (they expect the one-shot shape) | Low | Task 1's return-shape audit + the existing `_ensure_normalized_plan` should catch this. If not, Slice 12 wire passes are shape-tolerant (they check per-slot). |
| Backend hot-reload during a live generation kills it mid-run | Certain, on any edit | Do the whole implementation with backend down. Only restart at Task 5. |

## Out of scope (do not implement)

- Replacing `run_planner_oneshot`. It stays as fallback.
- Streaming from the decomposed skeleton call (small enough to just await).
- Frontend chip visual redesign — reuse the existing SSEStatusBar layout.
- Rewriting `should_decompose` — inherit whatever heuristic is there.

## Self-review checklist

Before shipping:
- [ ] All 5 tasks committed on a single branch.
- [ ] `test_planner_terse_prompt.py` — 3/3 pass.
- [ ] `test_planner_platform_primitives_prompt.py` — 11/11 pass (no regression).
- [ ] `test_orchestrate_planner_decomposition.py` — 3/3 pass.
- [ ] A live ATS generation completes in under 5 min for the planner phase.
- [ ] The decomposed plan carries the same primitive declarations (`audit_trail`, `wizards`, etc.) as the one-shot would.
- [ ] Chip stream during decomposition shows per-unit `+ …` events.
