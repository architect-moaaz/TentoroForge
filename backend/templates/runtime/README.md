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
