# Smith `plan_scope` + `apply_scope`

**Status:** draft — awaiting sign-off before implementation

**Branch:** `forge-v3-smith-orchestrator-v2`

## Problem

Smith currently punts on feature-add asks even when he has full context:
app map, resource registry, contracts, all page/workflow schemas, and a
grounding pre-pass that names the target entity. The user's session log
showed 11 LLM calls in 65 s ending in `"I looked at the app but
couldn't pin down…"` — for the ask *"On Candidate Profiles, I should be
able to see all the stages and as I move the candidate from one stage
to another the status should keep getting updated."*

Root cause: **Smith has info, not a decision rule.** The palette is
wide (~15 tools), the prompt biases toward reading not deciding, and no
code path maps *"feature-add verbs + entity with a status enum"* to
*"add a kanban page + a stage-transition workflow."* The model
re-derives that mapping every turn and doesn't commit.

## Non-goals

- **Not** a whole-app replan. `handoff_to_pipeline(kind="refine")` still
  covers "rip out auth, convert to a marketplace" — a scoped plan is
  the smallest-fragment answer to one ask.
- **Not** a rewrite of the ReAct loop. Smith's other paths (single-
  seam edits, code fixes via `_tool_app_modifier`, conversational
  `answer`) stay.
- **Not** yet an implementation of a wider deterministic decision
  table. That's the follow-up — this spec unlocks it by giving Smith a
  reliable "delegate the composition problem" tool.

## Contract

Two pure modules + one Smith tool.

### `services/plan_scope.py`

```python
def plan_scope(
    ask: str,
    output_dir: str,
    *,
    query_fn: QueryFn | None = None,
) -> ScopedPlan
```

`ScopedPlan` is a pydantic model, LLM-output-schema-constrained:

```python
class PageToAdd(BaseModel):
    route: str            # "/candidates/board"
    archetype: str        # must be in DETERMINISTIC_ARCHETYPES
    entity: str           # canonical registry name
    title: str | None = None
    features: list[str] | None = None
    fields: list[dict] | None = None

class PageToEdit(BaseModel):
    route: str            # existing route
    intent: str           # plain-English patch instruction for llm_edit

class WorkflowToAdd(BaseModel):
    name: str
    entity: str
    op: str               # "create" | "update" | "custom"

class EntityToAdd(BaseModel):
    name: str
    fields: list[dict]
    table: str | None = None

class MenuEntry(BaseModel):
    label: str
    route: str

class Fragment(BaseModel):
    pages_to_add:     list[PageToAdd]     = []
    pages_to_edit:    list[PageToEdit]    = []
    workflows_to_add: list[WorkflowToAdd] = []
    entities_to_add:  list[EntityToAdd]   = []
    menu_entries:     list[MenuEntry]     = []

class ScopedPlan(BaseModel):
    understanding: str              # one-sentence restatement of the ask
    fragment:      Fragment
    assumptions:   list[str] = []   # every default the planner picked
    unresolvable:  list[str] = []   # blockers → user must clarify
```

**Prompt shape** — the LLM sees:

1. **App map skeleton** (`services.app_map.render_app_map_skeleton`) —
   the same block Smith gets today.
2. **Resource registry slice** for the target entity if grounding
   matched one — pages, workflows, FKs, status enum values.
3. **Archetype catalog** — the tuple in
   `services.add_page_seam.DETERMINISTIC_ARCHETYPES` (currently
   `list, form, create, edit, detail, kanban, calendar`) plus a
   one-line "what it renders" description per archetype, read from
   `services.page_type_templates` where available. Dynamic — no
   hard-coded list.
4. **Seam contracts** — a short block naming each of `add_page`,
   `edit_page`, `add_workflow`, `add_entity` with the exact keys they
   accept. Prevents the LLM from inventing fields the applier will
   drop.
5. **The ask** — verbatim user turn.

**Rules injected into the system prompt**:

- Every `entity` MUST appear in the registry — if it doesn't, either
  emit an `entities_to_add` step for it OR list the missing entity in
  `unresolvable`.
- Every `route` in `pages_to_edit` MUST match an existing schema file.
- Every `archetype` in `pages_to_add` MUST be in the catalog.
- Populate `assumptions` for every default picked (column choice, route
  name, feature flag) — user needs the transparency.
- Populate `unresolvable` for anything the app can't express (e.g. ask
  wants a component that isn't in the library).

**Model / effort**: Sonnet 4.5. One shot. If the returned JSON fails
schema validation → single retry with the validator error appended to
the prompt. If retry also fails → return `ScopedPlan(understanding=…,
fragment=Fragment(), unresolvable=["planner_json_invalid: <err>"])`.
Smith sees the empty fragment + unresolvable, falls through to
`ask_user`.

### `services/apply_scope.py`

```python
def apply_scope(
    plan: ScopedPlan,
    output_dir: str,
) -> ApplyResult
```

Pure dispatcher, no LLM:

```python
class ApplyStep(BaseModel):
    kind:    str              # "add_page" | "edit_page" | …
    target:  str              # route | workflow name | entity name
    ok:      bool
    error:   str | None = None
    changes: list[dict] = []  # from the seam's changes[]

class ApplyResult(BaseModel):
    steps:         list[ApplyStep]
    edited_paths:  list[str]   # deduped across all steps
    all_succeeded: bool
```

**Order** — fixed so downstream steps see upstream results:

1. `entities_to_add` → `services.fix_applier._apply_add_entity`
2. `pages_to_add`    → `services.fix_applier._apply_add_page`
3. `pages_to_edit`   → `services.llm_edit.smart_edit_page` (each
   `intent` becomes an `edit_page` LLM call — one per edited page)
4. `workflows_to_add` → `services.fix_applier._apply_add_workflow`
5. `menu_entries`    → `services.shell_menu_sync.sync_shell_menu`
   (single call at the end; menu is idempotent)

**Partial apply**: each step is try/except; a failure records
`ok=False, error=<msg>` and the dispatcher continues. `all_succeeded`
is `False` when any step failed. Caller decides what to do with the
partial state (Smith reports it, user re-asks).

**Commit strategy**: `apply_scope` does NOT commit. It hands
`edited_paths` back to Smith's turn-end commit path (same shape the
existing seams return). Preserves the invariant that one Smith turn =
one git commit.

### Smith tool: `plan_and_apply`

Register in `services/smith_tools.py` `TOOL_CATALOG`:

```python
{
  "name": "plan_and_apply",
  "description": (
    "Delegate a multi-artifact feature-add to the scoped planner. "
    "Use for asks that need coordinated page(s) + workflow(s) + menu "
    "entries — e.g. 'kanban view of candidates with drag transitions'. "
    "Do NOT use for single-artifact asks — use add_page / edit_page / "
    "add_workflow directly."
  ),
  "input_schema": { "type": "object",
    "properties": { "ask": { "type": "string" } },
    "required": ["ask"] },
}
```

Handler `_smith_plan_and_apply(output_dir, args)`:

```python
plan   = plan_scope(args["ask"], output_dir)
result = apply_scope(plan, output_dir)
return {
    "understanding": plan.understanding,
    "assumptions":   plan.assumptions,
    "unresolvable":  plan.unresolvable,
    "steps":         [s.model_dump() for s in result.steps],
    "edited_paths":  result.edited_paths,
    "all_succeeded": result.all_succeeded,
}
```

### Smith routing prompt update

`agents/smith_agent.py::_ROUTING_RULES` — add a row above the current
`add_page` row:

```
Ask class                                 → Preferred FIRST tool
Feature-add needing MULTIPLE artifacts    → plan_and_apply(ask=<verbatim>)
  (a page + a workflow + menu entry;
  e.g. "kanban view of X with drag
  transitions", "add a review-and-approve
  flow for Y")
Single new page (archetype + entity      → add_page(archetype, entity, route)
  already decided)
```

Plus a "REPORTING RESULTS" block: when `plan_and_apply` returns,
Smith's `answer` MUST include (a) what was applied, (b) the
`assumptions` list verbatim, (c) any `unresolvable` items as a follow-
up question.

## Why this beats current paths

| Path | What it gives us | Where it falls short |
|------|------------------|----------------------|
| Smith adds items one-by-one via `add_page` + `add_workflow` | Precise seam calls | Smith has to decide all args unaided; observed to punt on multi-artifact asks |
| `handoff_to_pipeline(kind="refine")` | Handles anything | Whole-app replan; expensive; blast radius |
| `_tool_app_modifier` | Sub-agent w/ tools | Peer agent, no planner smarts; edits code, not schema fragments |
| **`plan_and_apply`** | LLM handles composition; deterministic apply; scoped | New surface — needs testing before it's the default |

## Success criteria

1. Live: Candidate Kanban ask completes in ≤3 Smith LLM turns
   end-to-end (`understand_ask` → `plan_and_apply` → `answer`), no
   `ask_user` fallback.
2. User's reply on that ask includes: the plan understanding, the
   assumptions list, the diff summary — nothing generic.
3. `/candidates/board` renders in the generated app; drag → status
   update wires through to the workflow.
4. On a deliberately un-decidable ask (e.g. "make it a WhatsApp") the
   `unresolvable` list is populated and Smith asks a specific
   follow-up, not the generic "couldn't pin down."

## Testing plan

**Unit — `plan_scope.py`**
- Fake `query_fn` returns valid JSON → `ScopedPlan` parses.
- Fake returns malformed JSON → single retry with validator error.
- Fake returns unknown `archetype` → schema validation rejects; retry.
- Fake returns unknown `entity` in `pages_to_add` → validator error
  routed to `unresolvable`.

**Unit — `apply_scope.py`**
- Fake seams; fragment with 1 add_page + 1 add_workflow → both
  called in order, both `ok=True`, `all_succeeded=True`.
- add_page raises → step recorded `ok=False`, dispatch continues,
  `all_succeeded=False`.
- Empty fragment → no seam calls, `all_succeeded=True`, `steps=[]`.

**Unit — Smith wiring**
- `TOOL_CATALOG` contains `plan_and_apply`.
- Handler invokes `plan_scope` + `apply_scope` and shapes the result.

**Live E2E** — task PS-T4. Fire the Candidate Kanban ask on a fresh
project; verify success criteria 1–3.

## Open decisions (want your call)

1. **`pages_to_edit` intent shape** — pass free-text intent to
   `llm_edit.smart_edit_page` (current recommendation), OR require
   structured JSON-Patch-shaped edits? Free-text is faster to author
   but relies on `smart_edit_page`'s reliability; structured is
   auditable but heavier.
   *Recommend: free-text.*

2. **Retry policy on `plan_scope`** — one retry vs. zero vs. adaptive?
   *Recommend: one retry with validator error appended. Match the
   existing planner-retry pattern.*

3. **Archetype catalog freshness** — read dynamically from
   `DETERMINISTIC_ARCHETYPES` at prompt time (current recommendation),
   OR bake into the prompt template? Dynamic is drift-proof but adds
   an import.
   *Recommend: dynamic.*

4. **When to fire `plan_and_apply` vs. `add_page` directly** — should
   this be Smith's judgment (prompt guidance) or a deterministic
   pre-check ("if ask names ≥2 artifact types, use plan_and_apply")?
   *Recommend: Smith's judgment for v1; add deterministic router in
   the follow-up work.*

## Files

**New:**
- `backend/services/plan_scope.py` (~250 LOC)
- `backend/services/apply_scope.py` (~180 LOC)
- `backend/tests/services/test_plan_scope.py`
- `backend/tests/services/test_apply_scope.py`

**Modified:**
- `backend/services/smith_tools.py` — add `plan_and_apply` to
  `TOOL_CATALOG` + handler in `TOOL_HANDLERS`
- `backend/agents/smith_agent.py` — routing rule + reporting block in
  `_ROUTING_RULES`
- `backend/tests/test_smith_agent.py` — one canned test that verifies
  Smith picks `plan_and_apply` for a multi-artifact ask

## Rollout

- Land behind no flag — additive tool, doesn't remove anything.
- If it destabilises: revert the two prompt changes; the modules stay
  unused.
