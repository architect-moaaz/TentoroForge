# Visual-Product-Search: Real End-to-End Pipeline Fix

**Closes:** `MCP T10-T11: live E2E on Firecrawl` (#478), `MCP-E2E-B: regenerate
visual-product-search app + verify mcp_tool_call in emitted workflow JSON` (#485).

**Non-goal:** patching an already-generated app. All fixes land in generation
pipeline code so `output/<app>/` files are downstream of source (per user rule
`feedback_bug_fixes_platform_only`).

## Symptom that motivates this

A generated visual-product-search app has:
- No `ScanProductWorkflow.json` (only bare CRUD stubs like `CreateScanSession`)
- No `FIRECRAWL_API_KEY` in `.env.local`, no MCP server registration
- LLM-authored business rule (`confidence_score must be recorded`) blocks user
  submits before the DB row is ever written

A user upload therefore reaches: workflow POST → validation rejects it → 200 OK
with `outputs.error` → page navigates as if success → nothing in DB → empty
results forever.

Runtime IS in place (`mcpClientPool.ts`, `mcp_tool_call` action, AutoRefresh,
Conditional, Table). The gap is the *authoring* side of the pipeline.

## Six slices

Order chosen so each slice adds value on its own and later slices consume
earlier ones. Slice A is the smallest true unblock; Slice C is the largest.

### Slice A — MCP env injection when archetype declares MCP externals

**File:** `backend/services/runtime_injector.py`

**Change:** After the existing `resolver.ts` + `mcpClientPool.ts` copy (around
line 773), iterate the archetype's `EXTERNALS` list. For each `{"type": "mcp",
"provider": "<name>"}`, look up the platform-level integration record for
that provider on the current org (`platform_integrations` table, added by
completed slice PINT-2). If present, write four env vars to `.env.local`:

```
MCP_SERVER_<SLUG>_URL=<from integration record>
MCP_SERVER_<SLUG>_TRANSPORT=http
MCP_SERVER_<SLUG>_AUTH_KIND=none|bearer|apikey_header
MCP_SERVER_<SLUG>_SECRET=<encrypted key, decrypted at write time>
MCP_SERVER_<SLUG>_NAME=<human name>
```

Where `<SLUG>` is `provider.upper()`. `mcpClientPool.ts` already reads this
env contract verbatim (lines 137-190 of that file).

**Guard:** when the platform has no matching integration record, log a clear
warning + skip the env write (do not silently generate broken configs).

**Test path:** Firecrawl integration on the platform → generate a
visual-product-search app → `grep MCP_SERVER_FIRECRAWL .env.local` → all 5
lines present.

**Prerequisite:** platform-level Firecrawl integration record for the org.
For today's user we can seed one directly against
`design2ui-forge-v3/backend/db` platform tables — the platform UI at
`localhost:6501/settings/integrations` already supports this per task
`PINT-5`.

**Size:** ~1-2 hours including tests.

### Slice B — `_VISUAL_SCAN` template points at `ScanProductWorkflow`

**File:** `backend/services/page_type_templates.py`

**Change:** The `_VISUAL_SCAN` template I rewrote earlier today already
prescribes `Form { workflow: "ScanProductWorkflow" }`. That was aspirational
— nothing emitted `ScanProductWorkflow` before. Slice C makes it real; this
slice is now essentially finished (already committed as part of the template
rewrite). Verify no drift with Slice C's actual emitted workflow name.

**Size:** already done, verify only. ~10 min.

### Slice C — Deterministic authoring of a real `ScanProductWorkflow.json`

**File:** new `backend/services/archetype_workflows/visual_product_search.py`
(and register it wherever `DEFAULT_WORKFLOWS` currently maps to a builder).

**Change:** When the archetype `visual-product-search` is picked and the plan
declares `ScanProductWorkflow` in `DEFAULT_WORKFLOWS`, emit a full workflow
JSON with this node graph (nodes numbered as example ids):

```
trigger (manual, args: scanSessionId, rawImageUrl)
  ↓
1. db_update scan_sessions SET status='processing' WHERE id={{scanSessionId}}
  ↓
2. ai_identify_product { image_file_id: "{{rawImageUrl}}" }
   → outputs {brand, model, category, attributes, confidence} onto ctx.variables
  ↓
3. db_insert products values: { name: "{{brand}} {{model}}", brand, model, image_url: "{{rawImageUrl}}" }
   → outputs {inserted: {id}} (bound as {{new_product.id}})
  ↓
4. db_update scan_sessions SET identifiedProductId={{new_product.id}}, confidenceScore={{confidence}}
  ↓
5. db_query retailers (list active rows)
  ↓
6. FAN-OUT per retailer (Slice D unlocks this):
     6a. mcp_tool_call firecrawl_search { query: "{{brand}} {{model}} site:{{retailer.base_url}}", limit: 3, mcp_server_name: "Firecrawl" }
     6b. db_insert price_listings values: { productId: {{new_product.id}}, retailerId: {{retailer.id}}, productUrl: {{search.result.data.web[0].url}}, price: {{__parsed_price}}, currency: "USD" }
  ↓
7. db_update scan_sessions SET status='completed'
```

Emit as a valid `workflow.json` matching `CreateScanSession.json` structure
(processVariables, definition.trigger, definition.nodes, definition.edges).

**Complexity notes:**
- The fan-out at (6) needs a `foreach` or parallel node type. Grep engine.ts
  first to see what's supported — if only sequential, unroll per known
  retailer at generation time (all real retailers are in the seed spec,
  which is finite).
- Price extraction from Firecrawl search descriptions is unreliable via
  regex. Two honest options: (a) use `firecrawl_extract` per URL with a
  price/currency extraction schema — slower (10-30s/call) but clean; (b)
  emit a `parse_firecrawl_result` custom action step in the engine (Slice D
  work) that does the parsing server-side.

**Recommendation:** ship variant (a) — one `firecrawl_extract` call per
retailer with a JSON schema `{price: number, currency: string}`. Total
workflow runtime ~30-90s for 3 retailers. Honest trade-off documented.

**Size:** 2-4 hours. Biggest slice.

### Slice D — Workflow-engine gap fixes

Two known gaps in the workflow's binding + fan-out layer:

**D1. Array-index bindings.** `{{search.result.data.web[0].url}}` will throw
`ParseError: Unexpected token: LBracket` because the workflow binding
resolver uses the same feel-lite the renderer hit in memory
`reference_renderer-binding-array-index`. Mirror that fix in the workflow
engine: route array-index paths through `walkPath` instead of feel-lite.

**File:** wherever the workflow runtime resolves `{{node.output.x}}` — most
likely `backend/templates/runtime/workflows/index.ts` or a bindings helper.

**Test:** unit test with input `{{a.b[0].c}}` against `{a:{b:[{c:"hit"}]}}`
→ expect `"hit"`.

**D2. Fan-out / foreach node.** If the engine supports no per-item iteration
today, either:
- Add a `foreach` node type: takes a list binding + subgraph, executes
  subgraph per item, collects results
- Or resolve fan-out at generation time (Slice C already does this for
  known retailers)

Recommend the second — simpler, no engine surgery, works for the archetype's
finite retailer set. Revisit if a future archetype needs true dynamic
fan-out.

**Size:** 1-3 hours depending on D2 approach.

### Slice E — Business-rules guard against blocking user submits on AI-output fields

**File:** `backend/agents/business_logic_agent.py` (or wherever rules are
generated / normalized)

**Change:** When emitting workflow-side validation rules, detect the class
"required field IS an AI output" (e.g., `confidence_score`, `identified_*Id`
from a vision node). Suppress the "must be recorded" rule for those fields
on user-triggered workflows — they're populated downstream by AI, not by
the caller.

**Concrete guard:** if a `processVariables` entry has `required: false` AND
its name matches a known-AI-output pattern (`*confidence*`, `identified*`,
`*Confidence*`), never emit a rule that treats it as required-not-empty at
the workflow entry.

**Test:** given a workflow spec with `confidence_score` process variable,
ensure no emitted rule targets it as required.

**Size:** 1 hour.

### Slice F — Live regen + validation

Generate a fresh visual-product-search app with A+B+C+D+E all landed:

1. Prompt with visual-product-search keywords
2. Wait for full pipeline (~5-10 min)
3. Confirm generated app has:
   - `MCP_SERVER_FIRECRAWL_*` in `.env.local`
   - `workflows/ScanProductWorkflow.json` with `mcp_tool_call` nodes
   - `/scan` page's Form points at `ScanProductWorkflow`
4. Log in, upload real image, click Scan
5. Watch: status transitions through processing → completed
6. Verify price_listings has real rows with real Amazon/Best Buy/Walmart URLs
7. Verify prices are real numbers (via `firecrawl_extract` schema)

**Size:** 1 hour + generation time.

## Status (2026-08-04)

- [x] Slice A — env_writer call after inject_runtime in both text + Figma pipelines (`backend/routers/generate.py:1948`)
- [x] Slice B — verified template already references `ScanProductWorkflow`
- [x] Slice C — `backend/services/archetype_workflows/visual_product_search.py` + registry in `__init__.py` + workflow_generator hook (11 nodes: mark_processing → identify → insert_product → attach_to_scan → list_retailers → search (mcp firecrawl_search) → extract (mcp firecrawl_extract) → insert_price → mark_completed → end)
- [x] Slice D1 — array-index bindings via new `_walkPath` in `backend/templates/runtime/workflows/index.ts` (mirrors renderer BIND-FIX #211)
- [x] Slice E — `_is_ai_output_field` filter in `backend/agents/rules_agent.py` drops required-not-empty rules targeting AI-populated fields
- [ ] Slice F — live regen validation (requires user to fire a generation from a visual-product-search prompt on a project whose org has Firecrawl MCP configured)

## Total effort estimate

6-10 focused hours, split across 2-3 sessions. Ordering: A → B (already done)
→ D1 → C → E → D2 (if needed) → F.

## Anti-patterns to avoid

1. **Don't** patch `output/ybbc855k/` with the workflow JSON. Pipeline emits
   the workflow; per-app patches vanish on next regen.
2. **Don't** stub the `ai_identify_product` step with a fake product. The
   preset already throws on missing API key — that's the intended behavior.
3. **Don't** hardcode Amazon/Best Buy/Walmart in the workflow JSON. Read
   from the retailers table at workflow-runtime via db_query.
4. **Don't** ship the workflow without D1 (array-index binding). It will
   silently fail to insert rows because `{{search.result.data.web[0].url}}`
   won't resolve.

## Session log entry point

Start each session by re-reading this file. Update the "Size" line with
actual elapsed time when a slice closes. Cross off slices in the top table
of the containing task list.
