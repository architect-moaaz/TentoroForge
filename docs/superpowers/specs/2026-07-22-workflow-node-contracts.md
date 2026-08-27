# Workflow Node Contracts — declared inputs/outputs + mapping UX

**Date:** 2026-07-22
**Branch:** forge-v3-smith-orchestrator-v2
**Status:** approved (design), pending implementation

## Problem

The workflow Properties panel today models each action type with an
ad-hoc bag of config fields (`values`, `to`, `subject`, `query`, …). Two
consequences bit users in this session:

1. **Fields drift silently**: `db_insert` was added to the palette but the
   Properties block was never authored → panel rendered empty. Same class
   of bug hid `send_email`'s message field for months.
2. **No first-class model of what a node consumes vs. produces**. Downstream
   nodes can't discover an upstream node's outputs. Users author variable
   references from memory (`{{create_user.output.inserted.id}}`) and the
   editor gives no autocomplete. Required vs. optional inputs are invisible.

Meanwhile the runtime already routes through `input-assembly.ts` and the
`workflow_execution_log` shape is straightforward to add. The gap is
purely declarative: no schema declares *what a node consumes and produces*.

## The idea (locked with the user)

Every action type declares a **contract** — a typed list of inputs it
needs and outputs it will produce:

```
        [ input mapping ]        [ output mapping ]
process ──────────────►  node  ─────────────► process
variables               ─────                  variables
                       runs
```

### Three rules

1. **Inputs are always required-first**. The declared required inputs
   auto-populate the panel on node select. Users bind each to a source:
   process variable, literal, or expression. Optional inputs sit under
   "+ Add".
2. **Output mapping is opt-in, not mandatory**. Every declared output is
   always accessible downstream as `<nodeId>.output.<field>` (permissive
   default — no ceremony to reference something). Users *optionally*
   promote outputs to named process variables when they want a clean
   handle like `{{newUserId}}` instead of the full path.
3. **Runtime logs every step's actual inputs + outputs**. Powers "why did
   this fail?" debugging without adding a per-node breakpoint UI.

## Decisions locked

| Decision | Choice |
|---|---|
| Input contract source | Declarative catalog per action type (evolved from `actionFieldSpecs.ts`) |
| Values-per-column expansion | For DB actions, the contract expands based on the target table's columns (from `appModel`) |
| Output mapping | Opt-in — blank means "don't promote to process var"; raw path still works |
| Downstream variable access | Both named process vars AND `<nodeId>.output.<field>` are legal — VariablePicker shows both, named first |
| Required inputs | Auto-visible on node select; empty ones get a red asterisk |
| Runtime observability | New `workflow_execution_log` table; every node execution records `{inputs, outputs, error?, ts}` |
| Back-compat | Existing `values: {...}` / `to: "..."` on disk still runs. Migration is one-way at write time: when user re-saves a node, the panel writes the contract-shaped form. |

## Architecture

### Contract shape

```ts
// frontend/src/components/workflow/actionContracts.ts

export interface ParamContract {
  name: string;             // "email" | "values.role" | "inserted.id"
  type: ParamType;          // "string" | "number" | "email" | "uuid" | "object" | "array" | "boolean" | "enum"
  required?: boolean;       // inputs only; outputs are declared, always produced
  options?: string[];       // for type="enum"
  help?: string;
  /** Where does this input come from schematically?
   *  "column:users.email" → resolved against the target-table's schema for db_insert/update.
   *  "static"             → user-provided literal / mapping only.
   */
  source?: string;
}

export interface ActionContract {
  label: string;
  inputs: ParamContract[];
  outputs: ParamContract[];
  /** For DB actions: expands the `values`/`where` inputs from the target
   *  table's columns at runtime. UI reads `appModel.entities[table]`. */
  expandFromTable?: {
    tableInputName: string;   // "table"
    into: string;             // "values" | "where"
    mode: "all-columns" | "no-primary-key";
  };
}
```

### Runtime input shape (on disk)

```json
{
  "type": "action",
  "config": {
    "actionType": "db_insert",
    // Inputs — user's mapping. Each entry is:
    //   { name, source: "variable"|"literal"|"expression", value }
    "inputMappings": [
      { "name": "table",         "source": "literal",   "value": "users" },
      { "name": "values.email",  "source": "variable",  "value": "trigger.email" },
      { "name": "values.role",   "source": "literal",   "value": "recruiter" }
    ],
    // Output mapping — sparse; only promoted outputs appear.
    "outputMappings": [
      { "output": "inserted.id", "processVar": "newUserId" }
    ]
  }
}
```

### Legacy shape (still runs; migrated on next save)

```json
{
  "config": {
    "actionType": "db_insert",
    "table": "users",
    "values": { "email": "{{email}}", "role": "recruiter" }
  }
}
```

Runtime accepts BOTH shapes — a small adapter (`toInputMappings()` in the
existing `input-assembly.ts`) converts legacy → contract shape at
execution time. New writes always emit the contract shape.

### Execution log table

```sql
CREATE TABLE workflow_execution_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      TEXT NOT NULL,             -- the workflow-run id
  workflow_id TEXT NOT NULL,
  node_id     TEXT NOT NULL,             -- the node inside the workflow
  step_index  INTEGER NOT NULL,          -- ordinal within the run
  inputs      JSONB NOT NULL,            -- fully-resolved inputs at exec time
  outputs     JSONB,                     -- null if the node errored
  error       TEXT,                      -- stringified error if failed
  duration_ms INTEGER,
  created_at  TIMESTAMP NOT NULL DEFAULT now(),
  INDEX (run_id, step_index),
  INDEX (workflow_id, node_id, created_at DESC)
);
```

Runtime hook: `input-assembly.ts` writes one row per node execution.

## UI

### Input Mapping section (auto-populated on node select)

```
┌ Inputs ─────────────────────────────────────────────────────┐
│ table *          [Table select ▼] users                     │
│ values.email *   [Source: variable ▼] {{trigger.email}}     │
│ values.name  *   [Source: variable ▼] {{trigger.name}}      │
│ values.role  *   [Source: literal  ▼] "recruiter"           │
│ values.password  [Source: literal  ▼] "invited-…"           │
│                                                             │
│ + Add optional input                                        │
└─────────────────────────────────────────────────────────────┘
```

- Required inputs marked with red asterisk; blank ones get a red border
- Source picker per row: **variable** (dropdown of legal vars) /
  **literal** (typed control) / **expression** (FEEL-lite textarea)
- For `db_insert` targeting `users`, rows for each column of `users` are
  auto-materialized via `expandFromTable`
- Optional inputs collapsed under an "+ Add" affordance

### Output Mapping section

```
┌ Outputs ────────────────────────────────────────────────────┐
│ ○ inserted.id     — always available as create_user.output.inserted.id │
│   ↳ promote to process variable: [newUserId          ]      │
│ ○ inserted.email  — always available (unmapped)             │
│ ○ inserted.name   — always available (unmapped)             │
└─────────────────────────────────────────────────────────────┘
```

- Every declared output shown with muted state
- Toggle any output to reveal a "process variable name" input
- Blank name = not promoted; still available via full path

### VariablePicker upgrade

- Suggests **named process variables first** (`{{newUserId}}`)
- Falls back to **node-output paths** (`{{create_user.output.inserted.id}}`)
- Grouped by source (trigger / prior nodes / promoted vars)

### Execution log tab (per node)

- Small "History" affordance on the Properties panel: last N runs of this
  node showing `inputs → outputs` diff, error if any, duration
- Read from `/api/projects/{id}/workflow-runs?nodeId=<id>&limit=20`

## Slice plan (5 slices, ~1 week)

| # | Slice | Effort | Files |
|---|---|---|---|
| **NC-1** | `actionContracts.ts` — replace `actionFieldSpecs.ts` with typed input/output contracts; expand-from-table for DB actions | ~1 day | frontend/src/components/workflow/actionContracts.ts, hooks/useNodeContract.ts |
| **NC-2** | Input Mapping section — auto-populate required inputs, source picker per row (var/literal/expr), red asterisk for empty required | ~2 days | NodePropertiesPanel refactor |
| **NC-3** | Output Mapping section — declared outputs list; toggle-to-promote to named process var; downstream VariablePicker consumes both named + raw paths | ~1 day | NodePropertiesPanel, VariablePicker |
| **NC-4** | Runtime execution log — `workflow_execution_log` table migration + `input-assembly.ts` writes one row per node exec + read endpoint | ~1 day | backend/models, backend/alembic, backend/templates/runtime/workflows/input-assembly.ts, backend/routers/workflow_runs.py |
| **NC-5** | History affordance on Properties panel — small tab, last 20 runs of this node, inputs/outputs diff | ~1 day | frontend/src/components/workflow/NodeHistoryTab.tsx |

Each slice ships independently:
- NC-1+2+3 = UX complete without runtime log
- NC-4+5 = observability without needing NC-1..3
- Existing workflows keep running via the legacy adapter throughout

## Migration / back-compat

- Runtime handler reads legacy shape (`config.values` / `config.to`) OR
  contract shape (`config.inputMappings`) — both work.
- Legacy → contract shape is a one-way migration: **on next save of a node
  via the panel**, the write path emits the new shape.
- After NC-2 ships, we can add a background pass to rewrite existing
  workflow JSON files on disk (opt-in per project).

## Non-goals (v1)

- **Multi-node output composition** ("map inserted.id + inserted.email
  into an object then pass downstream"). Users can do this with a
  `custom` node's expression; a dedicated "compose" UI is v2.
- **Type-checking at author time**. The contract has type info but v1
  doesn't validate that a variable's inferred type matches an input's
  declared type. Later slice: warning badge on the source picker.
- **Retention policy for `workflow_execution_log`**. Table can grow
  unbounded in v1. Add a nightly prune job in a later slice.
- **Input-parameter reordering** in the panel. Order = spec order.
- **Custom output shapes** for `custom` action. Its output is whatever
  the expression returned; we surface it as `<nodeId>.output.value`.

## Out of scope, later

- Sub-workflow reuse (call another workflow with mapped inputs/outputs)
- Loop nodes (map over an array, per-iteration inputs)
- Compensation handlers (BPMN-style rollback logic)
- Sensitive-data redaction in the execution log (`hidden` flag on
  ParamContract for secrets)
