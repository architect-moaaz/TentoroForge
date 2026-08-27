# Smith-as-Architect — Migration Plan

**Companion to:** [../specs/2026-07-17-smith-as-architect.md](../specs/2026-07-17-smith-as-architect.md)

**Purpose:** The rewrite ships in a series of additive commits (S1-S8),
none of which touched the running system. This document is the
cutover plan for the destructive slice — S10 — that removes the
tactical Smith stack and switches the HTTP path to `SmithSession`.
It intentionally lives as a plan rather than being executed at
implementation time: deleting the running Smith without a supervised
switch would break every open chat session.

---

## What's already landed (safe, additive)

| Slice | Commit | What it adds |
|---|---|---|
| Spec | `01ac0625` | Design doc |
| S1 | `52aa077` | Blueprint dataclass + file persistence |
| S2 | `d90eea4` | Blueprint context renderer + slicer seam |
| S3 | `0b99e55` | Ground-truth verification module |
| S4+S5 | `f8d3aeb`* | Chat router + narrator artifact contracts |
| S6+S7+S9 | `18ea78e` | SmithSession — the architect service |
| S8 | `0e849a6` | Optimistic locking + editor mirror |

*(commit hashes as of this doc; verify with `git log --oneline` if
retrying.)

Total: 62 new tests, 8 new modules, 0 changes to any existing code
path. The tactical Smith stack from earlier this session
(`smith_orchestrator.py`, `smith_agent.py`, coherence gate,
understand_ask, propose_fix bridge) is still what the running
backend uses.

## What's still to do — the S10 cutover

### Step 1 — Real narrator-mode agent adapters

Write adapters that call the existing discovery / planner / generator
agents and normalize their outputs into `DiscoveryArtifact` /
`PlannerArtifact` / `GeneratorArtifact`. Two options:

- **Option A (fast, low quality):** Extract fields from the current
  agent outputs post-hoc using a small model call. Ships in a day but
  the extraction quality caps at whatever the current agents produce.
- **Option B (correct, slower):** Rewrite each agent's prompt to
  emit only the target JSON. Regression suite (existing end-to-end
  generation tests) must still pass. Ships in a week but produces
  the tight coupling the spec envisions.

**Recommendation:** Option A for the cutover to unblock the endpoint
switch; schedule Option B as a follow-up.

Files:
- `backend/services/smith_agent_adapters.py` (new) — 3 adapter fns
- Tests exercise each against a canned agent output

### Step 2 — Real `understand_ask` + `iteration_move_fn`

The current `SmithSession` accepts these as seams. Prod needs:

- `understand_ask_fn`: a single Opus call with the ask + a scoped
  blueprint slice as context, returning the structured dict shape
  `SmithSession.run_iteration` expects. This replaces every "smith
  thinks about the ask" step in the current agent loop.
- `iteration_move_fn`: given the understanding, dispatch to the
  right existing seam (`add_page_seam`, `edit_workflow_seam`, direct
  `edit_page` via `_apply_page_schema_patch`, etc.). Returns an
  `IterationMove`. The move implementations are all kept from the
  current stack — only the *dispatcher* is new.

Files:
- `backend/services/smith_understand.py` (new)
- `backend/services/smith_move_dispatcher.py` (new)

### Step 3 — Wire `POST /chat/message`

- New handler in `backend/routers/chat_v2.py` (or extend existing
  router with a v2 subpath).
- Loads the blueprint for the project.
- Runs `route_chat_message` (S4) to decide bootstrap vs iteration.
- Instantiates `SmithSession` with the real seams from Steps 1-2.
- Streams `TurnResult` back to the frontend using the existing
  SSE event shapes (`smith_thought` becomes narrator lines).
- Behind a feature flag `FORGE_SMITH_ARCHITECT=1` so we can toggle
  per-project during live testing.

### Step 4 — Live acceptance

With the flag on for one test project:
- Build a fresh ATS end-to-end through chat → success = a running
  generated app + a populated blueprint.
- Iterate: "Add Candidate CV should be FileUpload" → success = the
  actual field changes on disk, the blueprint's change_log records
  the move, the running app renders FileUpload.
- Test failure paths: ask something ambiguous → get a specific
  clarifying question. Ask for a wrong-file edit → get options,
  no silent commit.

### Step 5 — Migrate existing projects

Every already-generated app needs a bootstrap blueprint. A one-off
migration script reads each `output/<project_id>/`, invokes the
narrator-mode adapters over the registry + existing schemas, and
writes an initial `<output_dir>/.forge/blueprint.json`.

Files:
- `backend/scripts/migrate_project_to_blueprint.py`
- Idempotent; safe to re-run.

### Step 6 — Delete the tactical stack

Only after Steps 1-5 pass on real projects.

**Files to delete:**
- `backend/agents/smith_agent.py`
- `backend/agents/fix_chat_agent.py`
- `backend/services/smith_orchestrator.py`
- `backend/services/smith_recall_enrich.py`
- `backend/services/patch_coherence.py`  *(check for other callers first)*
- `backend/services/smith_tools.py`  *(everything except the seams that
  are still called through the move dispatcher)*
- `backend/services/guard_result.py`  *(rolled into `ground_truth.py`)*
- `backend/services/impact_analysis.py`  *(no longer needed — ground
  truth replaces its role)*
- `backend/services/edit_workflow_seam.py`  *(actually — KEEP; still used
  as a move)*
- `backend/tests/test_smith_orchestrator.py`
- `backend/tests/test_smith_agent.py`
- `backend/tests/test_guard_result.py`
- `backend/tests/test_smith_recall_enrich.py`

**Frontend cleanup:**
- Remove the `smith_thought` narrator-mode chip specific to the old
  fix-chat trace format (if it exists). Replace with a simpler
  "Smith is thinking" indicator.

### Step 7 — Delete the deprecated endpoints

- `POST /generate/*` — mark deprecated for one release cycle, then
  remove.
- `POST /chat/*` (v1) — same treatment.

## Rollback plan

If S10 goes badly on live acceptance:

1. Toggle `FORGE_SMITH_ARCHITECT=0`; traffic returns to the tactical
   stack immediately (nothing was deleted yet at Step 4).
2. Investigate; either fix forward and re-toggle, or roll back the
   `POST /chat/message` handler wiring (Step 3 alone).

Deletion (Step 6) is intentionally the LAST step so rollback stays
cheap up until that point.

## Open decision — DB index row

The spec's §6.1 second half (DB index row alongside the file
blueprint) is not yet built. Two paths:

- **A: build it now as S1b.** One small module (Drizzle-style migration
  + a `SmithProjectIndex` model). Enables admin queries but adds a DB
  dep the backend doesn't currently have for platform state.
- **B: defer until an admin use case actually needs it.** File-only
  is enough for correctness; the index is only for cross-project
  queries.

Recommend **B** unless the admin use case lands in the next sprint.

## Timeline (rough)

| Step | Rough size | Dependencies |
|---|---|---|
| 1 — narrator-mode adapters (Option A) | 1 day | none |
| 2 — understand + dispatcher | 1 day | S1-S8 done ✅ |
| 3 — wire `POST /chat/message` | 0.5 day | Steps 1-2 |
| 4 — live acceptance | 0.5-2 days | Step 3 |
| 5 — migrate existing projects | 0.5 day | Step 4 |
| 6 — delete tactical stack | 0.5 day | Step 5 green |
| 7 — endpoint deprecation | 0.5 day | Step 6 |

Total: ~4-6 days of focused work after S1-S8 are in.
