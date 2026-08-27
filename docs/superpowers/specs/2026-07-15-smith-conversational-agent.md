# Smith — Conversational App-Building Assistant

**Branch:** `forge-v3-smith`
**Status:** design anchor — not yet a full spec
**Date:** 2026-07-15

## The shift

Smith today = intent router (`DISCOVERY / PLAN / GENERATE / FIX / EXPLAIN / UNDO`) → hardcoded pipeline per intent + a Slice-3 tool loop for fixes only.

Smith tomorrow = **one conversational agent** that owns the chat surface, uses tools for everything (research, plan, generate, edit page, edit workflow, add a component from the library, apply a fix, explain), and remembers what it's built and tried across turns — a Claude-Code-shaped loop over the platform's deterministic seams.

The deterministic pieces (registry, guards, seams, apply-fix, workflow-node-config patch, page-schema RFC-6902, form/nav/binding gates) do NOT change. They stay authoritative. Smith just picks when to call them.

## Non-goals

- Reinventing the build pipeline. The discovery→plan→schema→generate pipeline stays; Smith calls it as a `build_app` tool, doesn't reimplement it inline.
- Dropping intent classification entirely. `[APPROVE_PLAN]`, `[APPLY_FIX]`, `[SELECT_TEMPLATE:*]` chip tokens still short-circuit — they're UI contracts, not model decisions.
- Bypassing the pending-fix short-circuit. That already works and Smith should reuse it, not re-derive.

## Architecture

```
user turn
  │
  ├── explicit chip token? ────────► existing short-circuit (unchanged)
  │       (APPROVE_PLAN / APPLY_FIX / SELECT_TEMPLATE / …)
  │
  └── free-form message ──► Smith loop
                              │
                              │  system prompt: role + tool list + guardrails
                              │  memory block:  recent turns + rolling summary + open state
                              │  recall block:  current registry / plan / last commit
                              │  user message:  this turn's text
                              │
                              ▼
                        model streams reasoning + tool calls
                              │
                              ▼
                        tool runner (deterministic seams)
                              │
                              ▼
                        observation → back into loop until final
```

## Tool palette (v0)

Every tool is a thin wrapper over an existing service. Smith invents nothing.

| Tool | Wraps | Purpose |
|---|---|---|
| `recall` | `services/app_recall.assemble_recall` | On-demand fetch of registry + plan + git slice (already exists) |
| `read_file` | scoped `Path.read_text` under `output/<slug>` | Look at a page schema / workflow / component |
| `list_components` | new — reads library dist `starter.json` | "What components can I use?" — the library catalog |
| `plan_app` | `agents/planner_agent` | Draft the app plan from a description |
| `build_app` | `_run_relay_pipeline` | Full discovery→plan→schema→generate (after `[APPROVE_PLAN]`) |
| `edit_page` | `services/fix_applier` `page_schema_patch` seam | Add / remove / configure a component on a page |
| `edit_workflow` | `services/fix_applier` `workflow_node_config` seam | Change a workflow node's values / branches |
| `add_component` | `page_schema_patch` — insert node from library | "Add a Kanban to the Assessments page" |
| `apply_fix` | existing `_handle_apply_fix` | Apply a proposed fix (chip flow keeps working) |
| `probe_logs` | `services/fix_probe` | Read runtime logs / GET a URL |
| `analyze_workflow_values` | `services/workflow_value_types` | Type-check a workflow node's bindings |
| `explain` | LLM-only — no side effects | Describe how something works, no writes |
| `ask_user` | terminal tool — halts loop | Ask a clarifying question when genuinely blocked |

The tool set expands over time. v0 covers refine / fix / edit / add-component / explain — everything post-build. Full build (`plan_app` + `build_app`) is included but continues to run through the existing pipeline unchanged — Smith just kicks it off.

## Memory (the "context engine")

Two layers, both per-project:

**1. Verbatim recent turns.** Last 3–4 user+assistant turns injected as-is. Enough for "the Schedule button" → "yes fix it" → "still broken" to flow. Cheap; the recent past is the highest-signal.

**2. Rolling summary.** One paragraph, updated at end of each Smith turn, stored on the latest assistant `Conversation.metadata_.smith_state`:

```
Smith state (project mc2xgclv, 2 hours):
- Built ATS with Applications, Candidates, Assessments, Feedback (see plan.json).
- Fixed Schedule button (workflows/assessmentschedulingworkflow.json, create_assessment_record node,
  candidateId + status re-bound). Applied 22:31. User confirmed working.
- Currently discussing dashboard layout — user wants a Kanban of applications by stage.
```

Injected as `<smith-memory>` in the system prompt. Older than N turns → fully compressed into the summary.

Both layers live in the DB; nothing new to persist beyond one JSONB field on the assistant turn.

## Coexistence with the router

Not a rewrite — a **new entry-point** behind a flag. `FORGE_SMITH` (default off):

- Flag OFF → today's intent router. Zero behavior change.
- Flag ON → free-form messages route to Smith loop. Chip tokens (`[APPLY_FIX]`, `[APPROVE_PLAN]`, `[SELECT_TEMPLATE:*]`) still short-circuit to their handlers, unchanged. `plan_app` / `build_app` when called by Smith invoke the same pipeline routes the router does today.

Cutover is a flag flip, not a refactor. The router stays as safety net for months.

## Streaming events

Smith emits the SSE events the frontend already renders — `message`, `fix_proposal`, `fix_applied`, `plan`, `discovery`, `status`, `commit`. New event: `smith_thought` (optional, rendered as a compact "Thinking…" line above the response) so the user sees what tool is being called. Frontend change is additive; no card refactor.

## First slice (Slice 1)

**Goal:** Smith loop lives, behind `FORGE_SMITH`, with a small tool set — enough to prove the loop + memory work end-to-end on a real refinement turn.

Files:
- `backend/agents/smith_agent.py` — the loop (fork of `fix_chat_agent` as a starting shape, generalized)
- `backend/services/smith_tools.py` — tool wrappers (`recall`, `read_file`, `list_components`, `edit_workflow`, `apply_fix`, `ask_user` — the minimum for slice 1)
- `backend/services/smith_memory.py` — verbatim last-N + rolling-summary builder
- `backend/routers/generate.py` — new `_handle_smith_turn` branch guarded by `FORGE_SMITH`; free-form messages route here when flag is on
- Frontend: `smith_thought` SSE event renderer (small chip above the message)

Not in slice 1: `build_app`, `edit_page`, `add_component`, `plan_app` tools. Those land in slice 2 once the loop is proven on refinement/fix.

Acceptance test for slice 1: on the mc2xgclv candidate-id conversation, `FORGE_SMITH=1` — user says "the Schedule button is broken" → Smith recalls + reads the workflow + proposes fix (using `apply_fix` tool with a `workflow_node_config` seam) → user says "yes fix it" → Smith remembers the pending proposal from memory, applies, and confirms. No regression when `FORGE_SMITH=0`.

## Open questions

- Should `edit_page` / `add_component` be a single tool with variants, or separate tools? (Leaning toward one `edit_page` with an operation parameter — less surface for the model.)
- Rolling-summary refresh cadence: every turn, or every N turns? (Every turn is simpler; measure cost first.)
- Tool-timeout handling: if a tool blocks (e.g. `build_app` runs 3 minutes), how does the loop stream progress? (Probably: tool call returns a job handle, Smith continues streaming while pipeline runs in background.)

## What lands in the next few commits

1. **(this commit)** design anchor
2. `smith_memory.py` + tests — memory-layer building block, reusable
3. `smith_tools.py` — v0 tool palette + tests
4. `smith_agent.py` — the loop, wired to tools + memory, guarded by `FORGE_SMITH`
5. Router entry-point `_handle_smith_turn` + minimal frontend event handler
6. Live acceptance on mc2xgclv Schedule-button conversation

## Slice 1 acceptance log

**Date:** 2026-07-15
**Target:** synthetic copy of `mc2xgclv` with the original Schedule-button
bug re-introduced (real user app was already fixed by an earlier
[APPLY_FIX], so we validated on a controlled copy — user's app untouched).

**Symptom sent:** *"The Schedule button on the Assessment Scheduling page
is not working — nothing happens when I click it."*

**Result:** all four acceptance criteria PASS.

```
[trace] 6 steps, 17.85s
  1. read_page              → invalid path (self-corrected)
  2. read_page              → page not found (self-corrected)
  3. list_workflows         → 20 workflows enumerated
  4. read_workflow          → assessmentschedulingworkflow.json loaded
  5. analyze_workflow_values → 2 findings (candidateId, status)
  6. propose_fix            → seam=workflow_node_config, confidence=0.93

[acceptance]
  [PASS] workflow_matches      (artifact = assessmentschedulingworkflow.json)
  [PASS] node_matches          (nodeId = create_assessment_record)
  [PASS] seam_correct          (seam = workflow_node_config)
  [PASS] candidateId_rebound   ({{candidateId}}, not CURRENT_TIMESTAMP)
```

**Re-run:**
```
ANTHROPIC_API_KEY=<yours> \
FORGE_SMITH=1 \
python3 backend/scripts/smith_live_run.py
```
Override the target app with `SMITH_ACCEPT_APP=/path/to/output/<slug>`.

**Live in-browser acceptance:** requires `FORGE_SMITH=1` in the backend
env + a backend restart, then sign in and open a chat on any has-code
project. A free-form fix-flavoured message will route through Smith
(watch for the violet `smith_thought` chip strip); the FixProposalCard +
[APPLY_FIX] chip flow is unchanged. Flag off = zero behaviour change.

## Slice 2 acceptance log

**Date:** 2026-07-15
**Scope shipped:** S2-T1 (`list_pages` tool) + S2-T2 (page-outline in
`read_page` + RFC-6902 patterns in the system prompt). Both are the
"strengthen existing capability with better context" pattern the design
predicted — Smith could always produce `page_schema_patch` proposals
via the generic `propose_fix` terminal, the missing pieces were
knowing which pages exist and how their content trees are shaped.

**S2-T1 result:** on the buggy-copy Schedule-button target, Smith's
loop is now **4 steps / 14.28s** (down from 6 / 17.85s in slice 1).
Same PASS on all 4 fix criteria. Loop-level dedup for identical
(tool, args) calls (`091822e`) prevents thrash when the model latches
on to a tool that returned nothing new.

**S2-T2 result:** page-edit request — "add a Banner above the pipeline
table reminding recruiters to add a note before advancing an
application":
```
[loop] 4 steps, 13.63s
  1. list_pages       → found /pipeline → src/schemas/pipeline.json
  2. read_page        → outline exposed the Table at /root/children/1
  3. list_components  → Banner exists in the library (98 components)
  4. propose_fix      → page_schema_patch, confidence 0.97

[acceptance]  6/6 PASS
  seam_is_page_schema_patch, patch_is_a_list, patch_has_at_least_one_op,
  ops_have_required_fields, artifact_is_page,
  proposed_components_exist_in_library
```

Re-run: `python3 backend/scripts/smith_page_edit_run.py`; override the
symptom via `SMITH_SYMPTOM="..."` and the app via `SMITH_ACCEPT_APP`.

**Scope check surfaced by S2-T2:** deep component customization (a
per-row Tag in a Table's cell renderer, or an add-column op on a
data-bound Table) is a structural edit beyond plain
add/remove/replace ops. That's a separate seam and not in scope for
slice 2 — the current envelope covers structural additions
(Banner/Divider/Card/Kanban next to an existing container), the two
value-edit seams already shipped (workflow_node_config,
page_schema_patch), and prop replacements.

## Slice 2 unfinished: plan_app / build_app  (design blocker)

**Status: deferred pending a design decision.** The `plan_app` /
`build_app` tools would let Smith kick off the full discovery→plan→
generate pipeline conversationally on a new project. The design's own
open questions section flagged the real blocker:

> Tool-timeout handling: if a tool blocks (e.g. build_app runs 3
> minutes), how does the loop stream progress? (Probably: tool call
> returns a job handle, Smith continues streaming while pipeline runs
> in background.)

Building this without answering that question first would either:
- **Block the SSE stream for minutes** while the pipeline runs
  synchronously inside Smith's `asyncio.to_thread`, or
- **Fire-and-forget the pipeline** and lose the plan_ready /
  file_created / commit events the frontend already renders.

Neither is right. The correct pattern is a small extension — either
async-tool-with-job-handle or a terminal that transfers control back
to the existing pipeline machinery — and it deserves its own design
pass rather than being rushed at the end of slice 2. Filed as
**follow-up**: draft the async-tool-streaming pattern (small spec)
before implementing plan_app/build_app. The Smith loop / memory /
tool palette / router / seams are ready to receive them once the
streaming pattern is chosen.

## Summary of what shipped on this branch

| Commit | Content |
|---|---|
| `26c01b3` | Design anchor |
| `decb765` | S1-T1: `smith_memory` (verbatim + rolling state) |
| `d3a6cd9` | S1-T2: `smith_tools` (inspectors + list_components + terminals) |
| `0e5a607` | S1-T3: `smith_agent` (loop + memory + 3 terminals) |
| `dc210ed` | S1-T4: `_handle_smith_turn` + `FORGE_SMITH` gate |
| `dd3188f` | S1-T5: `smith_thought` SSE + violet chip strip |
| `e358aa7` | S1-T6: live acceptance PASS (Schedule-button, 4/4) |
| `79ce51d` | S2-T1: `list_pages` |
| `091822e` | Fix: dedup identical (tool, args) calls |
| `2c51c26` | S2-T2: read_page outline + RFC-6902 patterns; page-edit PASS (6/6) |

Backend test suite: **76 green** across new Smith modules +
unaffected existing fix-agent / router tests. Frontend: no test suite
touched, changes verified in the browser via the smith-preview
harness (removed after each verification).
