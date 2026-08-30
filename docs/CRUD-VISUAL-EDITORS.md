# CRUD Visual Editors on the Living Blueprint

**Status:** plan, nothing built. Written 2026-08-30.

The Blueprint is the living document for what the application *is*. Every
artifact it describes — UI, workflows, data model, pages and navigation, rules
— must be editable through a visual editor, and every such edit must land in
the Blueprint rather than beside it.

This is a plan for getting there with the editors that already exist. It is
not a proposal to build new ones.

---

## 1. What is already built

Nine editor families ship today, and they are substantial:

| Directory | Files | Reads |
|---|---|---|
| `components/workflow` | 18 | `/workflows`, `/workflows/{id}`, `/workflows/{id}/apply` |
| `components/rules` | 17 | `/rules`, `/rules/{id}`, `/access-policies` |
| `components/data-model` | 16 | `/app-model` |
| `components/visual-editor` | 10 | `/schemas`, `/visual-edit/*`, `/registry/*` |
| `components/editor` | 10 | `_debug/project-file` |
| `components/ir-editor` | 7 | `_debug/project-file` |
| `components/canvas` | 6 | `_debug/project-file` |
| `components/business-rules` | 5 | `/rules` |
| `components/design-editor` | 2 | `_debug/project-file` |

`/app-model` is the single most-called endpoint (6 call sites), and it is the
data-model editor's only source.

**Almost none of these read the Blueprint.** They read legacy DB tables
(`project_rules`, `page_definitions`) and files on disk via
`_debug/project-file`. The engine writes neither table.

The exception is `/app-model`, and it matters. `app-model.json` is written
during the run by `services/app_model_builder.py` from the same material the
Blueprint holds — a projection, not a parallel store — so the data-model
editor is already reading the truth, one hop removed. Verified on a
Blueprint-built project: one table with typed columns, three pages, four
workflows, all present.

That distinction is the whole diagnosis. A projection regenerates when the
Blueprint changes; a table nothing writes never fills. The panels that open
empty are the ones backed by the second kind.

### 1.1 The reads fixed today, and what they prove

Four commits on 2026-08-30 fixed readers that pointed one directory away from
their writer — workflows (`285ecec`), the pages route collision (`680d67f`),
editor files (`785e636`), schemas (`e9e4399`). Every one returned success while
finding nothing.

The lesson generalises and is the reason for this plan: **an editor reading a
store the engine does not write cannot fail loudly.** It renders an empty state,
which is indistinguishable from an application that has not been generated. Six
separate instances of this shape were found in one day.

---

## 2. Target

One writer, one identity scheme, one change ledger.

```
   visual editor ─┐
                  ├─→ BlueprintService.upsert() ─→ Blueprint ─→ projections ─→ code
   Smith ─────────┘                                    │
                                                  changeHistory
```

A visual edit and an agent edit are the same operation. `upsert(section,
artifact, natural_key)` already allocates ids through `IdAllocator`, already
refuses an id that belongs to another artifact, and is what every agent node
uses. Nothing new is needed for the write itself.

**Editing the Blueprint is not editing the app.** The generated code changes
when the projections that depend on the edited section re-run. The orchestrator
already does this for Smith: `sections_of` → seeds → `descendants`. A visual
edit must seed that same graph. Writing files directly from an editor puts the
Blueprint and the code out of step, which is what §76 forbids and what a living
document cannot survive.

---

## 3. The Smith edit protocol

Per the standing instruction: **validate against what exists, update the
Blueprint, then act.** In that order, and the order is the point.

```
1. READ      load the current artifact from the Blueprint
2. VALIDATE  check the proposed change against it
                - does the artifact exist? (an edit to nothing is a create)
                - does the change keep it schema-valid?
                - do its references still resolve — entities, workflows,
                  pages, requirements?
                - do the §75 verification edges still hold?
3. WRITE     upsert into the Blueprint; supersede rather than delete;
             record the change in changeHistory
4. ACT       seed the incremental DAG with the touched sections and let
             the projections re-emit
```

Step 2 is the one that does not exist today and matters most. Smith currently
reasons about a change and hands off; it does not first check the change
against the artifact it is changing. That is how a workflow reference to
`markPlantWateredToday` reached a shipped page: nothing compared the new value
against the set of workflows that exist.

The validators for step 2 are already written and already used elsewhere —
`functional_completeness.functional_findings`, `verification`'s ten edges,
`agent_contract.check_pattern_templates`. This protocol points them at a
proposed edit rather than only at a finished run.

**A failed validation is a conversation, not an error.** §16 says Smith asks
rather than assumes. "That workflow does not exist — did you mean X?" is the
correct outcome of step 2 failing, for a visual edit as much as a chat message.

---

## 4. Phases

Each phase ships something usable and is independently revertible.

### Phase 1 — Read from the Blueprint

Extend `services/blueprint_to_editor.py` (written, unwired) and point the
existing endpoints at it: Blueprint first, DB rows as fallback for
hand-authored records.

- `/rules` ← `businessRules` — **the real gap: 0 rows against 13 rules**
  *(adapter written)*
- `/pages` ← `pages` + `pageLayouts` — rows exist only where a legacy run
  happened to fire `_sync_pages_from_app_model` *(adapter written)*
- `/workflows` ← `workflows`. Reads projected files today and works; the
  Blueprint additionally carries `launchedFrom`, `trigger` and `requirements`,
  so this is an enrichment rather than a repair
- ~~`/app-model`~~ — **no work needed.** Already Blueprint-derived through
  `app_model_builder`; measured populated on a real project
- nav ← `nav-flow.json`'s projection inputs: `transitions`, `entries`,
  `gatedEntry`, `initialPage`

Every panel shows the truth after this phase. Nothing is writable yet.

### Phase 2 — Be honest about what cannot be saved

A Blueprint-derived record must not look editable while it is not. `config
.blueprintId` and `data_bindings.blueprintId` are already in the adapter for
exactly this: they key "this came from the Blueprint" without a second request.

Disable edit and delete for those records in `RulesPanel`,
`BusinessRulesPanel`, `RuleFormDialog` and the workflow and data-model panels.

**This phase is not optional and must not be deferred.** Phase 1 without it
produces rows that 404 on save — a silent failure, the exact defect class this
whole plan exists to remove.

### Phase 3 — Writes, one family at a time

Order chosen by blast radius:

1. **Rules** — no layout consequences; a changed rule re-emits validators
2. **Data model** — entity changes cascade to migrations, APIs, forms
3. **Workflows** — steps and references; validation matters most here
4. **Pages and nav** — last, because editing these re-composes UI

Each: route POST/PUT/DELETE through the §3 protocol, then seed the incremental
DAG. Retire the corresponding legacy table once its family is migrated.

### Phase 4 — Retire the second stores

`project_rules` and `page_definitions` go, along with
`_sync_pages_from_app_model` — a legacy bridge reachable only from
`routers/generate.py` that no Blueprint path calls. Needs a migration for
projects holding hand-authored rows.

---

## 5. Decisions still open

1. **Synchronous or handed to Smith?** Does a visual edit re-run projections
   immediately, or become a change request Smith executes? §114's modification
   model suggests the latter, and it gives every edit one audit trail. It also
   makes edits slower and less direct.
2. **Conflict handling.** Two editors, or an editor and a running DAG, touching
   one artifact. `IdAllocator` refuses identity collisions; it says nothing
   about concurrent field edits.
3. **Confidence and status on hand-authored artifacts.** An agent-written rule
   carries `confidence` and `status: PROPOSED`. What does a human-authored one
   carry — and does approving it in a panel mean the same as approving it at the
   §25 gate?
4. **Migration for existing projects** with rows in the legacy tables.

---

## 6. First step

Phase 1 for `/rules`, with phase 2 for the same panels in the same change.

It is the only endpoint measured actually empty against a populated Blueprint —
zero rows against thirteen rules — and its adapter is already written. Rules
also have no layout consequences, which makes them the safest family to take
writes on first in phase 3.

`/app-model` was the original candidate here, chosen on call-site count. It
turned out not to be broken, which is the argument for measuring an endpoint
before planning work on it: reach is not the same as brokenness.
