# Smith Orchestrator — Complete Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Smith from a single-file editor that claims success into an orchestrator that reasons across the whole app, delegates changes to specialist agents, verifies system-wide coherence, and loops on the guard suite until the app is actually working — or rolls back and reports honestly.

**Architecture:** Smith's turn becomes an inner Actor–Critic loop. Smith is the actor. The existing guard suite (`apply_post_generate_fixes`) is the critic. Every edit runs impact analysis → delegates to specialist seams → runs the guard suite → parses failures → retries with corrective context until green (bounded ~15 turns) or rolls back and reports the residual breakage.

**Tech Stack:** Python 3.11 (backend), TypeScript (runtime templates), pytest, FastAPI, Claude Sonnet via `anthropic.AsyncAnthropic`. All new code lives under `backend/services/` and `backend/agents/`. Feature-flagged behind `FORGE_SMITH_ORCH=1` so the current Smith stays live during rollout.

---

## Why this is needed

Three live failure modes prove the current Smith architecture is too shallow:

1. **"Believes he did it" lie.** Smith generates the `answer` text from what he intended to change, not from what he actually changed. Live example: user asked "Upload CV should be a file upload"; Smith's diff renamed the label from "Latest CV Attachment" to "Upload CV" while leaving `type: Select` untouched; Smith answered *"changed from a dropdown Select to a FileUpload component"*. The prose describes the intent; the diff executes something else.

2. **Cheapest-edit-wins.** `edit_file` on one line is safer than restructuring a component node (which requires knowing the new component's prop contract). Smith reliably picks the safe edit. Verified on three consecutive Smith turns for the same class of ask (label change, label change, label change).

3. **Local-reasoning failure.** A field-type change isn't local. "Upload CV → FileUpload" touches: the create page, the edit page, the detail page, the workflows that consume the field, the data-engine API path, the `.env.local` storage config, the seed synthesizer, the contracts, the FK-integrity check, and the validation rules. Smith today treats it as a single-file substring edit.

The fix is not new agents. It's composition of existing services (planner, page_schema_agent, workflow_generator, add_entity_seam, seed_synthesizer, guard suite) behind a Smith orchestrator that (a) knows the blast radius of a change and (b) loops on the guard suite until the whole system is coherent.

---

## Non-goals

- Build a new agent type. Every specialist Smith delegates to already exists.
- Replace Smith's ReACT loop entirely. The outer loop stays; the inner Actor-Critic + delegation is what's new.
- Handle arbitrary open-domain refactors. The plan targets the well-typed change classes: field-type change, add/remove field, add/remove workflow step, add/rename entity, add page, add component, storage / env change. Anything outside this closed set falls through to today's Smith and, if that fails, `handoff_to_pipeline`.

---

## File structure — what gets created / modified

**New files (backend)**
- `backend/services/impact_analysis.py` — reverse index over the registry + file tree; answers "what depends on X?".
- `backend/services/guard_result.py` — structured guard-suite result: `{green: bool, failures: [{guard, kind, artifact, message, evidence}]}`.
- `backend/services/edit_workflow_seam.py` — the missing sibling of `add_workflow_seam.py`: scoped edit of an existing workflow (add/remove/modify step, rename, edit trigger inputs).
- `backend/services/smith_orchestrator.py` — the new orchestrator loop. Wraps `run_smith_agent` in the Actor-Critic-with-guards shape.
- `backend/services/smith_recall_enrich.py` — augments Smith's recall with component-contract summaries, data-engine endpoint signatures, workflow-node type catalog.

**Modified files (backend)**
- `backend/services/post_generate_fixes.py` — refactor `apply_post_generate_fixes` to return a structured result (in addition to logging) that `guard_result.py` can parse.
- `backend/agents/smith_agent.py` — new prompt section: "routing rules — direct edit is last resort"; add `impact_analysis`, `edit_workflow`, `run_guards` as tools; make `answer` refuse to fire when the pending plan has red guards.
- `backend/services/smith_tools.py` — register the new tools in `READONLY_HANDLERS` / `WRITE_HANDLERS`.
- `backend/routers/generate.py` — when `FORGE_SMITH_ORCH=1`, `_handle_smith_turn` routes through `smith_orchestrator.run` instead of `run_smith_agent` directly.
- `backend/services/self_healing.py` — same flag; runtime-exception healing also goes through the orchestrator.

**New tests**
- `backend/tests/test_impact_analysis.py`
- `backend/tests/test_guard_result.py`
- `backend/tests/test_edit_workflow_seam.py`
- `backend/tests/test_smith_orchestrator.py`
- `backend/tests/test_smith_recall_enrich.py`
- `backend/tests/integration/test_smith_orchestrator_e2e.py` — full CV-field convergence test with mocked LLM.

---

## Slice map

Eight bite-sized slices, each shippable and testable independently. Behind `FORGE_SMITH_ORCH=1` throughout.

### Slice 1 — Structured guard result

The current guard suite logs and mutates files but returns nothing structured. To loop on it Smith needs a machine-readable verdict.

**Files:**
- Create: `backend/services/guard_result.py`
- Modify: `backend/services/post_generate_fixes.py`
- Test: `backend/tests/test_guard_result.py`

- [ ] **Step 1: Write the failing test — result shape**

```python
def test_guard_result_shape():
    """When every guard passes, result must be green with empty failures."""
    from services.guard_result import GuardResult
    r = GuardResult.from_guard_run([
        {"guard": "action_contract_guard", "level": "info",
         "message": "resolved 5, unresolved 0"},
    ])
    assert r.green is True
    assert r.failures == []

def test_guard_result_captures_failure():
    from services.guard_result import GuardResult
    r = GuardResult.from_guard_run([
        {"guard": "workflow_mutation_guard", "level": "warning",
         "message": "11 mutation value(s) still need a trigger input"},
    ])
    assert r.green is False
    assert len(r.failures) == 1
    assert r.failures[0].guard == "workflow_mutation_guard"
    assert "trigger input" in r.failures[0].message
```

Run: `pytest tests/test_guard_result.py -v`
Expected: FAIL (module not defined).

- [ ] **Step 2: Implement `GuardResult`**

```python
# backend/services/guard_result.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class GuardFailure:
    guard: str          # e.g. "workflow_mutation_guard"
    kind: str           # "warning" | "error"
    message: str        # human-readable
    artifact: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

@dataclass
class GuardResult:
    green: bool
    failures: list[GuardFailure]
    raw_lines: list[dict]  # keep the raw log line for provenance

    @classmethod
    def from_guard_run(cls, log_lines: list[dict]) -> "GuardResult":
        failures: list[GuardFailure] = []
        for line in log_lines:
            lvl = str(line.get("level", "info")).lower()
            if lvl not in {"warning", "error"}:
                continue
            failures.append(GuardFailure(
                guard=line.get("guard", "unknown"),
                kind=lvl,
                message=str(line.get("message", "")),
                artifact=line.get("artifact"),
                evidence=line.get("evidence", {}),
            ))
        return cls(green=len(failures) == 0, failures=failures, raw_lines=list(log_lines))

    def to_prompt(self) -> str:
        """Render for Smith's next-turn corrective context."""
        if self.green:
            return "GUARD SUITE: all green."
        lines = [f"GUARD SUITE: {len(self.failures)} failure(s) — fix each before answering:"]
        for i, f in enumerate(self.failures, 1):
            loc = f" in {f.artifact}" if f.artifact else ""
            lines.append(f"  {i}. [{f.guard}]{loc}: {f.message}")
        return "\n".join(lines)
```

- [ ] **Step 3: Refactor `post_generate_fixes` to also return the structured result**

Modify `apply_post_generate_fixes` to return `GuardResult` (in addition to writing logs, unchanged behavior).

```python
# services/post_generate_fixes.py
def apply_post_generate_fixes(output_dir: str) -> "GuardResult":
    """Run every guard. Returns structured result. Writes-to-disk side effects
    unchanged — callers that ignore the return value keep working."""
    log_records: list[dict] = []
    class _Capturer(logging.Handler):
        def emit(self, record):
            if record.name.startswith("services.post_generate_fixes") \
               or record.name.startswith("services.") and record.levelno >= logging.WARNING:
                log_records.append({
                    "guard": record.name.rsplit(".", 1)[-1],
                    "level": record.levelname.lower(),
                    "message": record.getMessage(),
                })
    cap = _Capturer()
    logger.addHandler(cap)
    try:
        # ... existing guard invocations unchanged ...
        pass
    finally:
        logger.removeHandler(cap)

    from services.guard_result import GuardResult
    return GuardResult.from_guard_run(log_records)
```

- [ ] **Step 4: Run tests + a smoke against a real generated app**

```bash
pytest tests/test_guard_result.py -v
# Then on a fixture app:
python -c "
from services.post_generate_fixes import apply_post_generate_fixes
r = apply_post_generate_fixes('/Users/m/Work/code/poc/design2ui-forge-v3/output/pbhfpamw')
print(r.to_prompt())
"
```
Expected: all guard failures visible as structured entries.

- [ ] **Step 5: Commit**

```bash
git add backend/services/guard_result.py backend/services/post_generate_fixes.py backend/tests/test_guard_result.py
git commit -m "feat(smith-orch S1): structured GuardResult from post_generate_fixes"
```

---

### Slice 2 — Impact analysis service + tool

Smith needs to know the blast radius of a change *before* he acts. This service walks the registry + file tree and answers "what depends on X?".

**Files:**
- Create: `backend/services/impact_analysis.py`
- Modify: `backend/services/smith_tools.py` (add tool registration)
- Test: `backend/tests/test_impact_analysis.py`

- [ ] **Step 1: Write failing tests — three target kinds**

```python
def test_impact_of_entity_field(tmp_path):
    """Given an entity field, list every page/workflow that reads or writes it."""
    from services.impact_analysis import analyze_impact
    # fixture: 1 entity Candidate with field latestCvAttachmentId
    # 2 pages: create + detail — both bind to it
    # 1 workflow: reads {{input.latestCvAttachmentId}}
    _write_fixture(tmp_path)
    impact = analyze_impact(str(tmp_path), target={"entity": "Candidate", "field": "latestCvAttachmentId"})
    assert {p["path"] for p in impact.pages_reading} >= {"src/schemas/candidates/[id].json"}
    assert {p["path"] for p in impact.pages_writing} >= {"src/schemas/candidates/new.json"}
    assert {w["id"] for w in impact.workflows_reading} >= {"process_cv"}

def test_impact_of_page(tmp_path):
    """Given a page path, list every workflow the page's actions fire + entities the page reads."""

def test_impact_of_workflow(tmp_path):
    """Given a workflow id, list every page that fires it + every entity its steps write."""
```

- [ ] **Step 2: Implement `analyze_impact`**

```python
# backend/services/impact_analysis.py
from dataclasses import dataclass
from typing import Any
import json, os, re

@dataclass
class ImpactReport:
    target: dict
    pages_reading:      list[dict]   # [{path, node_id, binding}]
    pages_writing:      list[dict]   # [{path, form_field}]
    workflows_reading:  list[dict]   # [{id, step_id, binding}]
    workflows_writing:  list[dict]   # [{id, step_id, config_path}]
    api_routes_touching: list[dict]
    contracts_impacted:  list[str]
    env_requirements:    list[str]

    def summary(self) -> str:
        """One-block text summary — Smith reads this before planning."""
        ...

_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_$][\w$\-\.]*)\s*\}\}")

def analyze_impact(output_dir: str, target: dict) -> ImpactReport:
    """
    target ∈ {
      {"entity": "Candidate", "field": "latestCvAttachmentId"},
      {"page":   "candidates/new"},
      {"workflow": "process_cv"},
    }
    Walks registry.json + src/schemas + workflows/ + src/app/api.
    """
    ...
```

Extract the walk helpers from `schema_references.py` (`_iter_nodes`) so the two modules share the traversal.

- [ ] **Step 3: Register as a Smith tool**

```python
# backend/services/smith_tools.py
def impact_analysis_tool(output_dir: str, args: dict) -> dict:
    from services.impact_analysis import analyze_impact
    try:
        report = analyze_impact(output_dir, args)
        return {"impact": report.__dict__, "summary": report.summary()}
    except Exception as exc:
        return {"error": str(exc)}

READONLY_HANDLERS["impact_analysis"] = impact_analysis_tool
```

Add to the tool catalog in the system prompt:
```
- impact_analysis(target: {entity, field?} | {page} | {workflow})
    → Returns every artifact that would need to change for this target.
    → CALL THIS FIRST for any modification request. Use its output to plan.
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_impact_analysis.py -v
```

- [ ] **Step 5: Commit**

---

### Slice 3 — edit_workflow seam

`add_workflow` exists. The edit sibling is missing — right now Smith direct-edits workflow JSONs with `edit_file`, which is exactly the kind of freehand edit that causes drift.

**Files:**
- Create: `backend/services/edit_workflow_seam.py`
- Modify: `backend/services/smith_tools.py`
- Test: `backend/tests/test_edit_workflow_seam.py`

- [ ] **Step 1: Write failing test**

```python
def test_add_trigger_input_to_existing_workflow(tmp_path):
    """Add a new input to an existing workflow's trigger — the exact fix
    the corrective loop would need after impact_analysis flags a missing input."""
    from services.edit_workflow_seam import edit_workflow
    _write_workflow_fixture(tmp_path, "process_cv", trigger_inputs=[])

    result = edit_workflow(str(tmp_path), workflow_id="process_cv", changes={
        "add_trigger_input": {"name": "cvId", "type": "uuid", "required": True},
    })

    assert result["success"]
    data = json.load(open(tmp_path / "workflows" / "process_cv.json"))
    inputs = data["nodes"][0]["data"]["config"]["inputs"]
    assert {"name": "cvId", "type": "uuid", "required": True} in inputs

def test_change_step_config_field(tmp_path):
    """Change a single field of a step's config (e.g. update a where-binding)."""

def test_rename_workflow(tmp_path):
    """Rename a workflow id + update every page.action.workflow ref."""
```

- [ ] **Step 2: Implement `edit_workflow`**

Structured `changes` payload — no free-form string edits:
```python
changes = {
    "add_trigger_input":   {name, type, required},
    "remove_trigger_input": name,
    "set_step_config":     {step_id, path, value},   # JSON-pointer path within step.config
    "add_step":            {step_id, type, config, after: step_id},
    "remove_step":         step_id,
    "rewire":              {step_id, next?: step_id, branches?: {label: step_id}},
    "rename":              new_id,
}
```

The seam VALIDATES its own output — it runs V2 validator + connectivity checks on the modified workflow before writing, and refuses if invalid.

- [ ] **Step 3: Register as Smith tool** (WRITE_HANDLERS).

- [ ] **Step 4: Tests pass, commit.**

---

### Slice 4 — Smith orchestrator loop

The heart of the plan. Wraps `run_smith_agent` in the Actor–Critic-with-guards shape.

**Files:**
- Create: `backend/services/smith_orchestrator.py`
- Modify: `backend/routers/generate.py` (route via flag)
- Modify: `backend/services/self_healing.py` (route via flag)
- Test: `backend/tests/test_smith_orchestrator.py`

- [ ] **Step 1: Design the loop state machine**

```
Orchestrator.run(ask, project) -> Result

state.turn = 0
state.max_turns = 15
state.applied_edits = []      # for rollback
state.guard_history = []      # each iteration's GuardResult
state.corrective_context = "" # appended to Smith's next-turn context

LOOP:
  state.turn += 1
  if state.turn > state.max_turns: goto FALLBACK

  smith_result = run_smith_agent(
      user_message=ask + "\n\n" + state.corrective_context,
      output_dir=project.output_dir,
      recall_block=enriched_recall(project),
      max_iters=8,   # smaller since orchestrator wraps
  )

  if smith_result.terminal == "ask_user":
      return Result(ask_user=smith_result.question)
  if smith_result.terminal == "handoff_to_pipeline":
      return Result(handoff=smith_result.handoff)

  if not smith_result.edited_paths:
      # no edits — treat as answer (info request)
      return Result(answer=smith_result.answer)

  state.applied_edits.extend(smith_result.edited_paths)

  guard_result = apply_post_generate_fixes(project.output_dir)
  state.guard_history.append(guard_result)

  if guard_result.green:
      # convergence
      commit(state.applied_edits)
      return Result(answer=synthesize_from_diff(state.applied_edits, ask))

  # red — build corrective context, loop
  state.corrective_context = build_corrective_context(guard_result, state.turn)

FALLBACK:
  rollback_all(state.applied_edits)   # git revert
  return Result(answer=honest_failure_report(state.guard_history[-1], state.turn))
```

- [ ] **Step 2: Write failing tests — the four terminal cases**

```python
def test_orchestrator_converges_when_first_edit_passes():
    """Simulate a Smith agent that edits and the guards pass immediately."""

def test_orchestrator_retries_on_guard_failure_and_succeeds():
    """First edit produces guard failure. Second turn (with corrective
    context) produces edits that pass. Orchestrator returns success."""

def test_orchestrator_rolls_back_on_max_turns():
    """Guards never green. Orchestrator hits max_turns, git-reverts,
    returns honest failure report — NEVER answers 'Done!'."""

def test_orchestrator_passes_through_ask_user_and_handoff():
    """Terminal is ask_user or handoff — no guard-loop entered."""
```

Tests inject a mock Smith via a `smith_fn` seam so the LLM isn't called.

- [ ] **Step 3: Implement `smith_orchestrator.py`**

- [ ] **Step 4: `synthesize_from_diff`**

```python
def synthesize_from_diff(edited_paths: list[str], ask: str) -> str:
    """Generate Smith's answer text FROM THE ACTUAL DIFF, not from prose.
    Kills the 'believes he did it' class."""
    # For each edited path: compute git diff, extract structural changes:
    #   - "changed type: Select → FileUpload on latestCvAttachmentId in candidates/new.json"
    #   - "added trigger input 'cvId' to process_cv workflow"
    # Return a bullet list of these + a one-line summary tying back to the ask.
```

- [ ] **Step 5: `honest_failure_report`**

```python
def honest_failure_report(last_guard: GuardResult, turns: int) -> str:
    return (
        f"I tried {turns} iterations to fix this. The following guard failures "
        f"remain after my last attempt (all my edits have been reverted so the "
        f"app is in its pre-change state):\n\n"
        + last_guard.to_prompt()
        + "\n\nCan you clarify: [specific question inferred from failures] "
          "OR grant me permission to try a broader change?"
    )
```

- [ ] **Step 6: Wire behind flag**

```python
# routers/generate.py :: _handle_smith_turn
if os.environ.get("FORGE_SMITH_ORCH") == "1":
    from services.smith_orchestrator import run as smith_orch_run
    result = smith_orch_run(user_message, project)
else:
    result = await asyncio.to_thread(run_smith_agent, ...)  # today's path
```

Same in `self_healing._run_heal_attempt`.

- [ ] **Step 7: Run tests + commit**

---

### Slice 5 — Recall enrichment

Smith needs the specialist catalog + component contracts in his context so `impact_analysis` output is actionable.

**Files:**
- Create: `backend/services/smith_recall_enrich.py`
- Modify: `backend/services/app_recall.py` (compose enriched block)
- Test: `backend/tests/test_smith_recall_enrich.py`

- [ ] **Step 1: Failing tests**

```python
def test_recall_includes_component_prop_contracts():
    from services.smith_recall_enrich import enriched_recall_block
    blob = enriched_recall_block("/tmp/fixture_app")
    assert "FileUpload" in blob
    assert "accept" in blob and "maxSize" in blob
    assert "Select" in blob and "options" in blob

def test_recall_includes_data_engine_endpoints():
    blob = enriched_recall_block("/tmp/fixture_app")
    assert "POST /api/files/upload" in blob
    assert "POST /api/data/[entity]" in blob

def test_recall_includes_workflow_node_catalog():
    blob = enriched_recall_block("/tmp/fixture_app")
    assert "db_update" in blob and "db_insert" in blob
    assert "ai_extract" in blob
```

- [ ] **Step 2: Implement — three sources**

```python
def enriched_recall_block(output_dir: str) -> str:
    parts = [
        _base_recall(output_dir),         # existing assemble_recall
        _component_catalog(output_dir),   # from library dist/starter.json
        _data_engine_surface(output_dir), # from runtime templates
        _workflow_node_catalog(),         # static — from backend/services/workflow_generator
        _specialist_seams_catalog(),      # what each Smith seam accepts
    ]
    return "\n\n".join(parts)
```

- [ ] **Step 3: Wire into orchestrator** — pass `enriched_recall_block(project.output_dir)` as the recall.

- [ ] **Step 4: Tests + commit.**

---

### Slice 6 — Routing prompt: specialists over direct-edit

Smith's system prompt gets a new REQUIRED SECTION near the top, describing the routing rule and demoting `edit_file` to last-resort.

**Files:**
- Modify: `backend/agents/smith_agent.py` (prompt)
- Test: `backend/tests/test_smith_orchestrator.py` (add: on a "change field type" ask, orchestrator picks the specialist, not `edit_file`)

- [ ] **Step 1: Draft the routing rule**

```
ROUTING RULES — pick the specialist that owns the artifact BEFORE reaching for edit_file.

  Field on a form/page             → page_schema_patch(page, target, change)
  Workflow trigger inputs / steps  → edit_workflow(workflow_id, changes)
  Add a whole page                 → add_page(entity, kind, route)
  Add a whole workflow             → add_workflow(name, spec)
  Add a whole entity               → add_entity(name, fields)
  Add a library component          → add_component(name, from_library)
  Storage / env vars               → env_upsert(key, value)
  Runtime code (src/lib/**/*.ts)   → edit_file (last resort — used by self-heal only)

FIRST call impact_analysis on any modification ask. Its output tells you WHICH
specialists you'll need, in what order. Never edit_file when a specialist owns
the artifact — the specialist knows the correct shape and props.
```

- [ ] **Step 2: Wire the rule into the system prompt**

Position: right after the persona block, before the tool list.

- [ ] **Step 3: Tests — mock LLM asked for "change field type on page X"**

Assert the trace contains a `page_schema_patch` call, NOT an `edit_file` call.

- [ ] **Step 4: Commit.**

---

### Slice 7 — Answer-from-diff hard-gate

`answer` is refused when there are pending edits and no guard-green state yet. The orchestrator generates the answer text from the actual diff.

**Files:**
- Modify: `backend/agents/smith_agent.py` (answer handler)
- Test: existing `test_smith_orchestrator.py` extends

- [ ] **Step 1: Gate the answer terminal**

```python
# in smith_agent.py answer handler
if tool_name == "answer":
    # If there are unverified edits, refuse.
    edited_since_last_verify = _edits_without_matching_verify(trace)
    if edited_since_last_verify:
        messages.append({"role": "tool", "tool": "answer", "content": json.dumps({
            "error": (
                f"You edited {edited_since_last_verify} but did not call "
                f"verify_promise or run_guards after. Verify your edit before answering."
            )
        })})
        continue
    ...
```

- [ ] **Step 2: Orchestrator overrides Smith's `answer` when convergence is reached**

Even if Smith emits an `answer`, the orchestrator's `synthesize_from_diff` replaces it. Smith's prose becomes advisory, not authoritative.

- [ ] **Step 3: Tests — "believes he did it" scenario**

Mock Smith emits `answer("changed to FileUpload")` when the diff only changed the label. Orchestrator's `synthesize_from_diff` produces `"changed label on latestCvAttachmentId from 'Latest CV Attachment' to 'Upload CV'"`. The lie is impossible.

- [ ] **Step 4: Commit.**

---

### Slice 8 — Live acceptance: CV field converges in ≤5 turns

Prove the whole thing on the exact ask that's been failing for three tries.

**Steps:**

- [ ] **Step 1: Reset the app**

`git -C output/pbhfpamw checkout HEAD~1 -- src/schemas/candidates/new.json` — restore the pre-Smith broken Select state.

- [ ] **Step 2: Enable the flag**

```bash
export FORGE_SMITH_ORCH=1
```

Restart backend.

- [ ] **Step 3: Send the ask through chat**

*"In Add Candidate Page, the Upload CV should be a file upload not a dropdown"*

- [ ] **Step 4: Observe the orchestrator loop**

Trace should show:
1. `impact_analysis(entity=Candidate, field=latestCvAttachmentId)` → report
2. `page_schema_patch(candidates/new, target=latestCvAttachmentId, change_type=FileUpload)` → applied
3. Guards run → red on `workflow_mutation_guard` or `read_binding_guard` (if any)
4. If red: corrective turn — `edit_workflow(process_cv, ...)` if needed OR `page_schema_patch(candidates/[id], ...)`
5. Guards re-run → green
6. Commit + answer generated from diff

Acceptance: field is `type: "FileUpload"` on disk, guards all green, answer text matches actual diff, chat shows machine-generated summary.

- [ ] **Step 5: Failure-path acceptance**

Ask something malformed to prove the honest-failure path works too. E.g. "make Candidate an Applicant" — a rename that touches many things; verify that after N turns without green, all edits revert and Smith answers honestly with the residual failure list.

- [ ] **Step 6: Commit + tag the branch**

`git tag smith-orch-live-verified`

---

## Tests plan

Each slice adds tests in its own `tests/test_<slice>.py`. Slice 8 adds `tests/integration/test_smith_orchestrator_e2e.py` with a mocked LLM (canned tool-call sequence) that exercises the full loop end-to-end.

**Total new test count** — target ≥ 40 across the 8 slices.

Run after every slice:
```bash
pytest tests/test_guard_result.py tests/test_impact_analysis.py \
       tests/test_edit_workflow_seam.py tests/test_smith_orchestrator.py \
       tests/test_smith_recall_enrich.py -v
```

Regression sweep after every slice (must stay 100% green):
```bash
pytest tests/test_smith_edit_tools.py tests/test_smith_agent.py \
       tests/test_patch_coherence.py tests/test_self_healing.py \
       tests/test_plan_validator.py tests/test_plan_critic.py -q
```

---

## Rollout & risk

- **Feature flag `FORGE_SMITH_ORCH=1`.** Default off. The current Smith stays live during rollout — every user-facing behavior is opt-in.
- **Kill switch.** If the orchestrator hits max_turns on a real user turn, rollback + honest-failure answer + `logger.warning("[smith-orch] converged=False")`. Grep for those to find regressions.
- **Cost cap.** `max_turns=15`, each Smith turn max 8 tool calls → ~120 tool calls upper bound per user ask. Real convergence should hit in 3-5 turns; the cap is a safety net not a target.
- **Rollback plan.** Turn the flag off. All existing code paths are unchanged; the orchestrator sits alongside `run_smith_agent`, doesn't replace it.

---

## Success criteria

1. **CV field ask converges in ≤5 orchestrator turns** — the exact ask that has failed three times today, on the same app, works.
2. **No "Done!" lies.** Smith's answer text is generated from `git diff`, never from Smith's own prose.
3. **Rollback on failure.** When guards can't converge, every Smith-touched file is reverted. The app is in a known-good state either way.
4. **Zero regressions in the existing test suite.** All current Smith / patch-coherence / self-healing tests stay green.
5. **Runtime-exception self-heal also uses the orchestrator.** The `stageadvanceworkflow` fix we verified earlier converges again through the orchestrator path.
6. **Honest failure report.** When we can't fix it, the chat message names what's still broken, in the user's language, with no cheerleading.

---

## What's explicitly out of scope

- Redesigning the intent classifier. Smith intercept stays as-is.
- Adding new LLM agents. Every piece composes existing services.
- Changing how `add_page` / `add_workflow` / `add_entity` seams work internally. Orchestrator just calls them.
- Frontend UX — the orchestrator's activity streams as existing `smith_thought` events. No new event types (yet).
- Multi-user isolation — orchestrator inherits self-healing's per-project semaphore.

## Files created / modified — final tally

**New (6 files)**
- `backend/services/impact_analysis.py`
- `backend/services/guard_result.py`
- `backend/services/edit_workflow_seam.py`
- `backend/services/smith_orchestrator.py`
- `backend/services/smith_recall_enrich.py`
- `docs/superpowers/plans/2026-07-17-smith-orchestrator.md` (this file)

**Modified (4 files)**
- `backend/services/post_generate_fixes.py` (return GuardResult)
- `backend/agents/smith_agent.py` (routing rules, answer gate, tool registration)
- `backend/services/smith_tools.py` (new tools in READONLY/WRITE HANDLERS)
- `backend/routers/generate.py` + `backend/services/self_healing.py` (flag-gated routing)

**Test files (6 new)**
- `backend/tests/test_guard_result.py`
- `backend/tests/test_impact_analysis.py`
- `backend/tests/test_edit_workflow_seam.py`
- `backend/tests/test_smith_orchestrator.py`
- `backend/tests/test_smith_recall_enrich.py`
- `backend/tests/integration/test_smith_orchestrator_e2e.py`

Total new lines of Python: ~1500. Tests: ~800. Feature-flagged. Rollback = flip the flag.
