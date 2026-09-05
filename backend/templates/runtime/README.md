# Tentoro Forge Runtime

This directory contains the **embedded runtime** that gets copied into every generated Next.js app. It provides:

- **Workflow execution** — runs the workflow definitions designed in the workflow editor
- **Rule evaluation** — validates form inputs, checks access policies, computes derived fields
- **FEEL-lite expressions** — the same expression language used in the visual editors

## Files

```
runtime/
├── feel-lite/              # FEEL-lite expression engine
│   ├── tokenizer.ts        # Lexer
│   ├── parser.ts           # AST parser
│   ├── ast.ts              # AST node types
│   ├── evaluator.ts        # AST evaluator
│   ├── validator.ts        # Expression validator
│   └── index.ts            # Public API
├── workflows/              # Workflow execution engine
│   ├── types.ts            # WorkflowDefinition, Node, Edge types
│   ├── engine.ts           # Node walker / executor
│   └── index.ts            # Public API (triggerWorkflow, etc.)
├── rules/                  # Rule evaluation engine
│   ├── types.ts            # ProjectRule types
│   ├── engine.ts           # Validation, access, computed, state machine
│   └── index.ts            # Public API (validateField, canAccessField, etc.)
├── runtime-loader.ts       # initializeRuntime() — call once at boot
└── README.md
```

## How It's Used in Generated Apps

These files are copied to `src/lib/` in every generated Next.js app:

```
output/myapp/
├── src/
│   ├── lib/
│   │   ├── feel-lite/
│   │   ├── workflows/
│   │   ├── rules/
│   │   └── runtime-loader.ts
│   ├── app/
│   │   └── api/
│   │       ├── workflows/[id]/execute/route.ts  # Generated
│   │       └── surveys/route.ts                  # Generated, calls runtime
│   └── components/
│       └── WorkflowTriggerButton.tsx             # Generated
├── workflows/
│   └── *.json                                     # Workflow definitions
└── rules/
    └── *.json                                     # Rule definitions
```

## Event Layer (events/)

Durable eventing so generated apps support "when X happens, do Y" and
schedules (R1/R2/R3):

- `events/bus.ts` — Postgres event bus over the `forge_events` table.
  `emitEvent(type, {entity, entityId, payload})` inserts a row;
  `processPendingEvents(limit)` claims rows (`FOR UPDATE SKIP LOCKED`) and
  (a) starts workflows whose top-level `trigger: {kind:"event", event}`
  matches, (b) resumes runs paused on a `wait_for_event` node. Processing
  runs inline after emit (fire-and-forget) and from `/api/cron/tick` as a
  sweeper. Emission is strictly non-fatal.
- `events/cron.ts` — self-written 5-field cron matcher (numbers, `*`,
  steps, commas, ranges; UTC) + `isDue` fire-once-per-window logic.
- `events/scheduler.ts` — `runDueSchedules(now)` fires workflows with
  `trigger: {kind:"schedule", cron}` against `forge_schedules` last-run state.
- `events/triggers.ts` — pure trigger-contract helpers
  (`getTriggerContract`, `findWorkflowsForEvent`, `buildResumeInput`).
- `events/emit-node.ts` — `emit_event` workflow-node handler factory.

The data engine emits `"<entitySlug>.created|updated|deleted"` after every
successful insert/update/delete. Workflow nodes: `emit_event` publishes a
custom event; `wait_for_event` pauses through the SAME persistence as
human tasks (`workflow_tasks`, task_type `wait_for_event`).

Tests: `__tests__/run-event-tests.sh` (cron matcher + trigger matching +
emit/wait nodes through the real engine).

## Row-level Scoping (data-engine.ts + ownership-rules.ts)

Authentication answers *who is calling*; `src/lib/ownership-rules.ts` answers
what the engine does with a column that names the acting user. It is projected
from the Blueprint's `security.ownershipRules`, where an object rule names an
entity, a column, whether the column holds the actor's user id or their
workspace id, and its **kind**. Prose entries in the same list document policy
and enforce nothing.

Both kinds are filled from the session in `create()`, so a request body never
decides who a row is attributed to. They differ in one thing:

| kind | filled on create | filters reads and writes |
| --- | --- | --- |
| `scope` (default) | yes | **yes** — `ownerId`, `workspaceId` |
| `attribution` | yes | no — `createdByUserId`, `changedByUserId` |

That distinction is load-bearing. An ATS fills `createdByUserId` on every
candidate and still means every recruiter to see every row; scoping on it would
narrow an application designed to be shared, silently, across every list, detail
route, KPI tile and chart at once. The Blueprint says which is which — nothing
here infers it from the column name.

`scopeConditions()` turns a `scope` rule into a WHERE predicate, and every path
that touches rows applies it: `query`, `findById`, `stats`, `resolveAggregate`,
`resolveSeries`, `resolveSearch`, `update` and `remove`. It lives in the engine
rather than in the API route because the server render calls these functions
directly, without passing through the route.

An entity with no rule is **not** scoped — correct for an app authorised by role
rather than by record. A rule that cannot be applied (no actor, or a column the
table does not carry) matches nothing and logs why: drift fails closed.

Tests: `__tests__/run-ownership-tests.sh` (renders the manifest with the real
projection, then runs the shipped `data-engine.ts` against it with `drizzle-orm`
and `@/db` stubbed — no bundler, no `node_modules`).

`__tests__/run-insert-tests.sh` runs the shipped `workflows/index.ts`
`_finalizeInsert` the same way: a value is shaped by drizzle's own `dataType`
(a Date for `timestamp()`, text for a string-mode `date()`), because
postgres.js has no serializer for a Date on a text-bound parameter and throws
from `Buffer.byteLength` — the Create Case insert failed on its due date.

## API Route Example

```ts
// src/app/api/surveys/route.ts
import { db } from "@/db";
import { surveys } from "@/db/schema";
import { initializeRuntime } from "@/lib/runtime-loader";
import { validateEntity } from "@/lib/rules";
import { triggerWorkflowEvent } from "@/lib/workflows";

await initializeRuntime();

export async function POST(req: Request) {
  const body = await req.json();

  // 1. Validate against rules
  const validation = await validateEntity("Survey", body);
  if (!validation.valid) {
    return Response.json({ errors: validation.errors }, { status: 400 });
  }

  // 2. Insert
  const [created] = await db.insert(surveys).values(body).returning();

  // 3. Trigger workflows listening for this event
  await triggerWorkflowEvent("survey_created", { surveyId: created.id });

  return Response.json(created);
}
```

## Form Component Example

```tsx
// src/components/SurveyForm.tsx
"use client";
import { validateField } from "@/lib/rules";

export function SurveyForm() {
  const [title, setTitle] = useState("");
  const [errors, setErrors] = useState<string[]>([]);

  const handleTitleChange = async (value: string) => {
    setTitle(value);
    const result = await validateField("Survey", "title", value);
    setErrors(result.errors);
  };

  // ...
}
```
