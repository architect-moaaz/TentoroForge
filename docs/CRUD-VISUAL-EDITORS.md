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

## 2. Target — the database is the record

**Decided: the platform database is the primary source of truth. The Blueprint
is derived from it.**

This was settled after measuring what each store actually is. The Blueprint has
no table at all — it lives as `current.json` at a filesystem path, while the
platform DB has 38 tables holding 5,616 rules and 96 page definitions, scoped
by `project_id`, queryable across projects and transactional.

The four reader bugs fixed on 2026-08-30 are the argument in miniature. Every
one was path resolution — a reader at `<out>/src` while the writer used
`<out>/app/src`, a directory created empty by its own `mkdir`, a route shadowed
by another, schemas one level down. **A foreign key cannot point one directory
away.** Those are failure modes a file-backed record has and a table does not.

So the flow inverts from what this plan first proposed:

```
   visual editor ─┐
                  ├─→ platform DB (record) ─→ Blueprint document ─→ projections ─→ code
   Smith / agents ┘         │
                       change ledger
```

The Blueprint keeps its whole meaning as the living document of what the
application *is* — it is what agents reason over, what §110's tree renders,
what §113 links against, and what the projections consume. What changes is
where it is kept: emitted from the database rather than being the thing edited.

**What this buys.** The editors already do CRUD against these tables, so the
visual-editing problem is largely solved and the work moves to the engine. A
rule someone types and a rule an agent proposes land in the same rows, under
the same constraints, in one transaction. Cross-project questions become
queries. Identity is a primary key rather than an id allocator over a JSON file.

**What it costs.** The engine currently writes `current.json` and nothing else,
so every agent write path has to be redirected. Blueprint sections that have no
table need one — and `IdAllocator`'s stable `RULE-001` identifiers must survive
the move, since the generated code, `codeMap` and `changeHistory` all reference
them.

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
3. WRITE     upsert into the database; supersede rather than delete;
             record the change in the ledger
4. ACT       re-emit the Blueprint document from the rows, then seed the
             incremental DAG with the touched sections so the projections
             re-run
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

### Phase 0 — Decide the schema for what has no table

**Rule taxonomy: answered.** Measured against a Blueprint and one row of each
type. The Blueprint models two and a half of the six.

| Table type | Config | Blueprint home | Verdict |
|---|---|---|---|
| `access` 1552 | `{roles, can_edit, can_view}` | `permissions[]` `{subject, action, condition}`, `security.rbac`, `roles` | covered, different vocabulary |
| `business` 564 | `{expression, trigger}` | `businessRules[]` `{statement, expression, appliesTo}` | covered except `trigger` |
| `trigger` 921 | `{event: on_create, action: <workflow>}` | `workflows[].trigger` `{kind, detail}`, `launchedFrom` | partial — `kind` is `manual`; entity lifecycle events unexpressed |
| `validation` 1952 | `{expression, errorMessage}` on a field | field carries `required`, `type`, `enumValues` | **gap** — no cross-field expression, no message |
| `state_machine` 380 | `{states, transitions[{from,to,requires}]}` | field `enumValues` gives the states | **gap** — no transitions, no `requires` |
| `computed` 247 | `{expression}` on a field | nothing | **gap** |

**The two stores have never met.** 222 projects: 16 have a Blueprint, 137 have
rule rows, **0 have both**. Every access-heavy project — 54 rules, 27, 26 —
has no Blueprint at all.

So `project_rules` is not a parallel store diverging from the Blueprint. It is
the record for a *different generation of projects*, written by a pipeline that
no longer runs. The 16 Blueprint projects have no rule rows because the new
engine has never written one. Nothing is out of sync; the two have simply never
overlapped.

That rewrites the argument below without changing its conclusion. The three
gaps cannot be justified by "2,579 rows demand it" — those rows belong to
projects the current engine will never touch, and the six-type taxonomy is the
old generator's vocabulary, not a requirement inherited from anywhere. The
gaps stand on what they are, not on their row counts: *field-level behaviour*. `enumValues` already proves the Blueprint
reaches into a field to say which values are legal. It stops short of saying
how they may change (`transitions`), what must hold across fields
(`validation.expression`), and what is derived rather than stored (`computed`).

So the schema change is one addition in the place the constrained thing already
lives — a `constraints` block on the entity field — not three new top-level
sections, and not widening `businessRules` to six types. `businessRules` stays
a statement about the product rather than becoming a home for field mechanics.

Two smaller changes fall out:

- `businessRules[]` gains `trigger`, to hold what the table's `business` rows
  carry.
- `workflows[].trigger.kind` admits entity lifecycle events (`on_create`,
  `on_update`) beside `manual`.

**The caveat could not be discharged, and that is the finding.** The mapping
above was read from one Blueprint — the Reading List, `rbac: false`, no
authentication — and the plan was to confirm `access` against a larger,
authenticated project. No such project exists: with zero overlap, there is no
application that has both access rules and a Blueprint to compare them to.

So the `access` row in the table is inference, not measurement, and it stays
that way until a Blueprint application with real authentication is built. That
is the thing to build before the schema change is written — not a query.

**Still open in phase 0:** the sections with no table at all — requirements,
pages, workflows, apis, pageLayouts, nav. See decision 2.

### Phase 1 — Engine writes to the database

Redirect `BlueprintService.upsert` to write rows, keeping `IdAllocator`'s
identifiers as a column so `RULE-001` still means what it means in `codeMap`,
`changeHistory` and every generated file.

`current.json` continues to be written — emitted from the rows after each
upsert — so the projections and every existing reader keep working unchanged
throughout. Nothing downstream notices this phase.

### Phase 2 — Editors write directly

Largely already true: the panels do CRUD against these tables today. What they
need is for a save to re-emit the Blueprint and seed the incremental DAG, so an
edit reaches the generated application instead of stopping at the row.

### Phase 3 — Retire `current.json` as a record

It becomes a build artifact: emitted, consumed by projections, never edited.
At that point "two stores that nothing synchronises" is gone — the condition
that produced every empty panel in this document.

### Superseded — the Blueprint-first work already committed

`dfcb7c2` made `/rules` read the Blueprint ahead of the table and refuse edits
to Blueprint-owned rules with a 409. That was phase 1 and 2 of the earlier,
Blueprint-primary plan and it is **backwards under this decision**: those rules
belong in the table and must be editable.

**Revised.** With zero overlap between the stores, the two paths cannot
collide: a Blueprint project has no rows, so the adapter is its only source of
rules; a legacy project has no Blueprint, so the adapter falls through and the
rows answer untouched. It is not backwards — it is the only thing serving those
16 projects, and it is what makes their rules visible at all.

What still has to go is the 409, once phase 1 gives Blueprint rules a row to
write to. Until then it refuses a write that would genuinely fail, which is
the honest answer rather than a placeholder.

## 5. Decisions still open

1. ~~**Rule taxonomy**~~ — answered in phase 0. Neither: three types are
   already covered, and the three that are not are field-level behaviour and
   belong on the entity field as a `constraints` block. Confirm against a
   larger, authenticated project first.
2. **Sections with no table.** Requirements, pages, workflows, apis,
   pageLayouts, nav all need one, or a documents table holding them as JSONB —
   which buys transactions and cross-project queries without a column per field.
3. **Synchronous or handed to Smith?** Does a visual edit re-run projections
   immediately, or become a change request Smith executes? §114 suggests the
   latter, and it gives every edit one audit trail.
4. **Concurrency.** Two editors, or an editor and a running DAG, touching one
   artifact. A row-level constraint answers this far better than a JSON file
   could, which is a point in favour of the decision.
5. ~~**Migration**~~ — mostly dissolved. With zero overlap there is nothing to
   reconcile: the 5,616 rules belong to 137 legacy projects, and the 16
   Blueprint projects have none. They stay where they are. What remains is
   narrower — whether a legacy project can ever be adopted by the new engine,
   and if so what happens to its rows then.

## 6. First step

Phase 0, decision 1: the rule taxonomy. It is the smallest question that blocks
everything and it is answerable by inspection — read what the six types
actually contain in the 5,616 rows, and check whether the Blueprint already
models them elsewhere (`security` for access, entity field constraints for
validation, workflow steps for triggers).

Two earlier candidates were chosen without measuring and both were wrong.
`/app-model` was picked on call-site count and turned out not to be broken.
The Blueprint-first direction was picked before anyone checked that the
Blueprint has no table and the "legacy" one holds 5,616 rows. Measure first.
