# Stateful single-page pattern

**One page, N states.** Uses `Conditional` root + top-level `poll` block to
render different children based on live data — no navigation between states.

Canonical use: scan-and-compare, chat-with-typing-indicator, upload-with-progress,
build-with-log-tail, checkout-with-payment-processing.

Reference schema: [`backend/services/schema_examples/stateful_scan_page.json`](../../../backend/services/schema_examples/stateful_scan_page.json).

## When to use

| Fits | Doesn't fit |
|---|---|
| Workflow completes in seconds (2–30s) | Workflow takes hours (multi-day jobs) |
| User expects to stay on the page | User navigates away and returns later |
| Result belongs on the same route as the trigger | Result is a shareable/bookmarkable detail page |
| 2–5 distinct states with clean predicates | Complex branching or wizard-style flows |

If it doesn't fit, use page-per-state (the default): `/scan` → dispatch → `/scans/[id]`.

## The shape

```json
{
  "route": "/scan",
  "poll": {
    "interval": 2500,
    "stopWhen": "scan.status IN ('completed','failed')"
  },
  "dataSources": [
    { "name": "scan", "entity": "Scan", "op": "latestForUser" }
  ],
  "root": {
    "type": "Conditional",
    "branches": [
      { "if": "!scan",                       "node": { /* initial */ } },
      { "if": "scan.status === 'processing'", "node": { /* spinner */ } },
      { "if": "scan.status === 'completed'",  "node": { /* results */ } },
      { "if": "scan.status === 'failed'",     "node": { /* error  */ } }
    ]
  }
}
```

## Runtime contract

- **`poll.interval`** (ms, default 3000, minimum 500) — how often to re-run
  the RSC path.
- **`poll.stopWhen`** — expression evaluated client-side against the latest
  `previewData` snapshot. When true, polling stops (no more network calls).

Supported `stopWhen` expressions (implementation:
[`AutoRefresh._evalStopWhen`](../../../backend/templates/app-foundation/src/lib/AutoRefresh.tsx)):

| Form | Example |
|---|---|
| Strict equality | `scan.status === 'completed'` |
| Loose equality  | `scan.status == 'completed'` |
| IN list         | `scan.status IN ('completed','failed')` |
| IS (NOT) NULL   | `scan.result IS NOT NULL` |
| Negation        | `!scan` |

Anything more complex is out of scope by design — keep the expression
narrow so the client evaluator stays small and predictable.

## Wiring — how the runtime uses it

1. `schema-page.tsx` sees the `poll` object at the top of the page schema.
2. Wraps the rendered tree in `<AutoRefresh poll={...} previewData={...}>`.
3. On mount, `AutoRefresh` calls `router.refresh()` every `interval` ms.
4. `router.refresh()` re-runs the RSC path → dataSources re-resolve → the
   `Conditional` root re-evaluates → the visible branch swaps.
5. When the new `previewData` satisfies `stopWhen`, `AutoRefresh` clears
   its interval on the next render.

No client-side data-fetch code, no SWR, no useEffect on the schema author's
side — the whole pattern is a schema fact.

## Authoring by the planner

The `visual_product_search` archetype declares
`PREFERS_STATEFUL_SINGLE_PAGE = True` +
`STATEFUL_PAGES = [{ route, polls_entity, status_field, terminal_states, example_schema }]`.

Planner recipes for archetypes that opt in should:
1. Emit a single page at the declared `route` instead of the
   `/scan` + `/scans/[id]` split.
2. Include `poll: { interval: 2500, stopWhen: "<entity>.<status_field> IN (<terminal_states>)" }`.
3. Use a `Conditional` root with branches for each state the workflow
   transitions through.
4. Reference `example_schema` when unsure of the exact shape.

## Authoring by Smith

When the user says one of:

- "keep the results on the same page"
- "show a loading state and then the results"
- "stay on the scan page while it works"
- "convert this to a single-page flow"

Smith should convert the current page (or the target route's page) into
this shape via `edit_page`. Steps:

1. Read the current page's dataSources and workflow-triggering button.
2. Wrap the current root in a `Conditional`; move the current content into
   the "initial" branch (`if: !<entity>`).
3. Add a "processing" branch with a `Progress`/`Spinner` and copy the
   entity title.
4. Add a "completed" branch with the results view (typically a `Repeat`
   over related rows).
5. Add a `poll` block at the top level referencing the entity's status
   field.

## Failure modes to watch

- **No entity yet**: the `!scan` branch handles "user hasn't submitted"
  cleanly. Don't try to gate on `scan.id === null` — dataSources can also
  return null on error.
- **Stuck workflow**: without `stopWhen`, poll runs forever. Always
  include the terminal-states check.
- **Auth-scoped entities**: `op: "latestForUser"` must be implemented in
  the data engine to filter by session user, otherwise you'll show
  another user's scan. Fallback: `op: "get"` with an id from the URL.

## Files

- Runtime: [`AutoRefresh.tsx`](../../../backend/templates/app-foundation/src/lib/AutoRefresh.tsx)
- Wire-in: [`schema-page.tsx`](../../../backend/templates/app-foundation/src/lib/schema-page.tsx)
- Example: [`stateful_scan_page.json`](../../../backend/services/schema_examples/stateful_scan_page.json)
- Archetype flag: [`visual_product_search.py`](../../../backend/services/archetypes/visual_product_search.py)
