# Agentic Fix-Chat (Slice 3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Motivation:** the current Fix-Assistant is smart-but-scripted — one classify call, one handler, one response. It can't investigate ("read the workflow AND the form before proposing"), can't probe ("check the log first"), can't recover mid-turn ("verify failed → adjust → try again"), and can't ask a clarifying question inside a step. Users describe symptoms and it feels like a bot because it *is* a state machine.

**Goal:** replace the single-shot `_handle_fix_proposal` path with a REASONING LOOP over a curated tool palette. The agent thinks, picks a tool, observes, thinks again — until it either proposes a fix or asks a clarifying question. Same UI, same `[APPLY_FIX]` approval, same deterministic seams for actual mutations. Behind an env flag for A/B against the current handler.

**Principle:** agentic ≠ unbounded. The palette is ONLY the deterministic tools we already built (Slices 0–2). The agent cannot call Write/Bash/Edit/raw filesystem — only inspect + analyze + propose. Approval and apply still ride the existing `[APPLY_FIX]` chip flow.

**Backend tests:** from `backend/` with `/usr/local/bin/python3 -m pytest`.

---

## Design

### Tool palette (each maps to an already-built function; agent cannot escape it)

| Tool | Purpose | Existing function |
|---|---|---|
| `recall()` | "Why is this app the way it is" — plan + entities + roles + history | `services/app_recall.assemble_recall().to_prompt_block()` |
| `read_workflow(path)` | Load a workflow definition JSON | file read (relative to `output_dir`) |
| `read_page(path)` | Load a page schema JSON | file read |
| `read_column(entity, column)` | The column's SQL type + fk target + notNull | registry lookup via `fk_semantics._columns_for` |
| `list_workflows()` | Enumerate workflow files | dir listing |
| `analyze_workflow_values(path)` | Value↔column type check | `services/workflow_value_types.analyze_workflow_file` |
| `parse_error(text)` | Extract workflow/table/column from a pasted error | `agents/fix_diagnoser.parse_error` |
| `probe_logs(lines?)` | Read the app's recent server log (read-only) | `services/fix_probe.probe({"kind":"logs"})` |
| `probe_endpoint(url)` | Bounded, localhost-only GET | `services/fix_probe.probe({"kind":"read_endpoint"})` |
| `propose_fix(diagnosis)` | **Terminal**: emits `fix_proposal` SSE + persists `pending_fix` + ends the loop | reuse the existing propose path |
| `ask_user(question)` | **Terminal**: emits a message asking for more info + ends the loop | reuse `_persist_assistant_message` |

The **`Diagnosis` contract** is unchanged (Slice 1-B) so `propose_fix` composes with the existing `[APPLY_FIX]` chip flow → `_handle_apply_fix` → `apply_fix`. **Apply is NOT an agent tool** — the user's approval remains the gate.

### Loop shape

```
system: "You are Tentoro's Fix-Assistant. Diagnose broken features from a plain-language
symptom, using the tools below. Investigate first; propose ONE deterministic fix; ask a
clarifying question if you can't localize. Never guess — every proposal MUST target a real
artifact + node/pointer, validated. Prefer inspect-then-propose over immediate propose."
+ tool descriptions

user: <symptom>
+ context: recall() output up-front (cheaper than every agent starting with a recall call)

loop:
  agent → (reason + tool call)
  runner → (execute tool, return result)
  ... until agent calls propose_fix or ask_user
```

### Guardrails
- **Hard-capped iterations** (default 8). At the cap, force a terminal `ask_user` with what it learned so far.
- **Read-only tools only.** No Write/Bash/Edit. The `propose_fix` tool doesn't mutate the app — it only emits an SSE event and stashes `pending_fix`.
- **Structured tool-call log** persisted to `Conversation.metadata_["fix_agent_trace"]` for the assistant turn — so we can audit what the agent tried.
- **Approval preserved.** `apply_fix` is still gated on `[APPLY_FIX]`; the agent never applies directly.
- **Budget cap.** If the loop's cumulative model calls exceed a threshold, force `ask_user`.

### Flag-gated A/B
`FORGE_FIX_AGENT` env var (default off). When on, `_handle_fix_proposal` delegates to the agent; when off, uses the current single-shot path. Both write the same `pending_fix`, same SSE events, same approval flow — so the ONLY difference is *how* the diagnosis was reached. Log agent-mode vs single-shot in the trace metadata so we can compare cost + confidence + user-approval rate on the same symptoms.

### What stays identical
- The chat is still the existing `/api/projects/{id}/chat`.
- The `FIX` intent is still classified upstream.
- The pending-proposal context awareness we just landed (apply-intent detection + re-emit-pending) runs BEFORE the agent — no reason to rediscover it inside the loop.
- The `[APPLY_FIX]` chip + `_handle_apply_fix` + `fix_applier` chain is unchanged.
- The `Diagnosis` contract is unchanged.
- The frontend cards are unchanged.

---

## Tasks

### Task 3-A: Tool palette adapters (`services/fix_agent_tools.py`)

**Files:** create `backend/services/fix_agent_tools.py`; test.

Thin, well-typed wrappers around the already-built functions. Each returns JSON-serializable data with a short docstring the LLM sees.

- [ ] **Step 1: failing tests** — each tool returns the expected shape on real `mc2xgclv` inputs. Read-only; never raises (returns `{"error":...}` on bad input).
- [ ] **Step 2: verify fail. Step 3: implement.** Wrap: `recall`, `read_workflow`, `read_page`, `read_column`, `list_workflows`, `analyze_workflow_values`, `parse_error`, `probe_logs`, `probe_endpoint`. Path arguments are relative to `output_dir` (never absolute; reject path traversal). **Step 4: pass. Step 5: commit.**

### Task 3-B: The agent (`agents/fix_agent.py`)

**Files:** create `backend/agents/fix_agent.py`; test.

- [ ] **Step 1: failing tests** — an injectable `query_fn(system, messages, tools) -> stream of tool_call events` (mirrors the pattern in `agents/fix_diagnoser.py`). Test scenarios (canned tool-call sequences, NO real model):
  - Two-step happy path: agent calls `read_workflow` → then `propose_fix` → terminates → returns a valid Diagnosis + the tool trace.
  - Investigate-then-propose: `parse_error` → `read_workflow` → `analyze_workflow_values` → `propose_fix` (validates the diagnosis matches the analyzer's finding).
  - Clarifying: agent calls `ask_user` → terminates with a message, no Diagnosis.
  - Iteration cap: canned stream exceeds cap → forced `ask_user`.
  - Guardrail: agent attempts an unknown tool → runner rejects → agent must recover or terminate.
- [ ] **Step 2: verify fail. Step 3: implement.** `run_fix_agent(symptom, output_dir, recall_block, *, query_fn=None, max_iters=8) -> {"diagnosis"?, "question"?, "trace":[...]}`. Uses Claude Agent SDK when `query_fn` is None, mirroring how `refiner.py` sets up tools. Prompt: system + tool list + recall context injected up front + symptom. Loop bounded; each tool call appended to trace. **Step 4: pass. Step 5: commit.**

### Task 3-C: Wire into `/chat` behind a flag

**Files:** modify `backend/routers/generate.py` (`_handle_fix_proposal`); test.

- [ ] **Step 1: failing tests** — with `FORGE_FIX_AGENT=1`, `_handle_fix_proposal` invokes `run_fix_agent` (stubbed) instead of the direct `diagnose` call; emits the same `fix_proposal` event when the agent returns a Diagnosis; emits a `message` event when the agent returns a `question`; writes `fix_agent_trace` into the assistant turn's metadata. With the flag off, current behavior unchanged.
- [ ] **Step 2: verify fail. Step 3: implement.** The pending-fix + apply-intent short-circuit (from `ff617c7`) runs BEFORE the agent — no change. When invoking the agent, pass a recall block already assembled (agent doesn't need to call `recall()` first; still available as a tool for re-checks). **Step 4: pass. Step 5: commit.**

### Task 3-D: Live A/B against the candidate_id acceptance case

- [ ] With `FORGE_FIX_AGENT=1`, drive the symptom "In Assessment Scheduling, the Schedule button isn't working" against `mc2xgclv` in the same live-chain harness we used for Slice 1-F. Confirm the agent: recalls, reads the workflow, runs `analyze_workflow_values`, and `propose_fix`es the same rebind. Report the trace vs the single-shot handler on cost/turns. Commit the transcript as a fixture.

### Task 3-E: (optional stretch) proactive symptom surfacing
Not in this slice — noted for later. The agent could, on request, run `analyze_workflow_values` on every workflow and offer fixes for anything that looks off.

---

## Self-review
- Every "mutation" still routes through a deterministic seam via `[APPLY_FIX]` → `apply_fix`. The agent NEVER writes files.
- Flag-off = current behavior byte-identical.
- The agent gets the fix-assistant's *reasoning* upgrade (investigate + iterate + ask) without any expansion of the mutation surface.
- Same UI, same commit-per-apply, same git-undo.
