# Visual Product Search + Price Comparison — how Forge builds it, and what it needs first

**Date:** 2026-08-01
**Status:** ideation → design
**Origin:** handwritten spec (user note) analysed with Tentoro Forge current-state capabilities

---

## 1. The target app (from the note)

> - User scans the product using mobile phone camera / uploads image
> - App identifies exact or similar-looking product
> - Gives price comparison, links to display (product display / e-commerce)
> - Admin can control the website / e-commerce access

Read literally: a **visual product search + price comparison** app. Two personas.

### 1.1 End-user journey
The scan/upload page is a Next.js route — served on **every surface**:
- Desktop browser → file picker
- Mobile browser (iOS Safari / Android Chrome) → real camera via `getUserMedia`
- Native Expo shell → device camera + gallery via `expo-camera` / `expo-image-picker`

Flow (identical on all three):
1. Open app / URL, tap "Scan"
2. Camera opens (mobile) or file picker (desktop)
3. Backend identifies the product (brand, model, category, key attributes)
4. Show a ranked list of matches from allowed retailers with price, seller, availability, product page link
5. Tap a match → outbound to retailer's product page

### 1.2 Admin journey
1. Log in to admin console
2. See a table of retail sources (Amazon, Flipkart, eBay, Myntra, custom …)
3. Toggle each source on/off, set priority, edit region
4. Optionally cap query budget or set rate limits
5. See recent scans, top identified categories, retailer coverage

Neither persona ever authors an integration. Both use pre-approved sources.

---

## 2. What Tentoro Forge can already do

| Capability | Where it lives | Ready? |
|---|---|---|
| Web app scaffold (Next.js) | `templates/app-foundation/`, `templates/standalone-app/` | ✅ |
| Mobile app scaffold (Expo) | MOBILE-A/B/C/D/E slices | ✅ |
| Camera capture + FileUpload | `CameraCapture` (W6-1), `FileUpload` (W1-5) library components | ✅ |
| File storage (disk/S3) | `forge_files` table, `/api/files` routes, storage.ts | ✅ |
| AI nodes (Claude) | `ai_generate`, `ai_classify`, `ai_extract`, `ai_decide` in runtime/workflows/ai.ts | ✅ (verify image path) |
| Workflow engine | Full deterministic engine, planner emits workflow JSON | ✅ |
| **Agent builder** — visual graph of system_prompt / tool / guardrail / memory / router / human_handoff nodes | `routers/agent_builder.py`, materialised via `code_editor` agent into `src/agents/agent-service.ts` + `POST /api/agent/chat` | ✅ (missing MCP tool_type) |
| Platform integrations catalog (org-level secrets injected as env) | `platform_integrations`, `runtime_injector`, `/settings/integrations` UI | ✅ |
| Admin CRUD + RBAC | Data engine, roles, invitation flows | ✅ |
| Self-Verify Pass (E2E test + Smith auto-fix after generation) | SV-1..SV-10 | ✅ (user-invoked) |
| Deployment (Vercel) | DVP-1..DVP-9, upload-first flow | ✅ |

**Coverage is high — ≈80% of this app is composition of existing capabilities.**

---

## 3. Gaps (all platform-level; the app itself needs no bespoke code)

### G1. `mcp` tool_type in Agent Builder
Today the Tool node in the agent-builder only supports `http`, `db`, `custom_function`. Every future integration is bespoke. The generated app needs to reach shopping-search / scrape / SERP capabilities, and the market has settled on **MCP servers** (Firecrawl, Bright Data, Apify, custom) as the delivery mechanism. Adding MCP as a first-class tool_type turns the whole MCP ecosystem into a plug-and-play toolbox for every future app-agent — not just this one.

**Blast radius:** platform. **Effort:** 3–5 days. **Unlocks:** this app + every future scrape/search/browser-automation app.

### G2. Vision input on `ai_extract`
Claude's vision API accepts images natively. Existing `ai_extract` reads PDFs — the same message-content shape should work for images with `type: "image"` blocks. Needs verification that our handler passes an image URL or bytes correctly, plus a preset prompt template *"identify the product in this image → JSON {brand, model, category, attributes}"*.

**Blast radius:** ai.ts + one preset. **Effort:** ½ day. **Unlocks:** every scan-and-find, receipt-parsing, ID-verification app.

### G3. Shopping-domain planner recipe
No planner example today produces this app shape (scan → identify → compare → outbound). Without a recipe, the planner will hallucinate a generic image-upload CRUD. Add:
- An entity exemplar for `scan_events` (image_id, identified_product, matches[], timestamp, user_id)
- An entity exemplar for `retail_sources` (name, enabled, priority, source_key, region) — the admin-controlled list
- An agent-graph exemplar wiring identify → mcp:search → filter-by-enabled-sources → return
- An "app archetype" tag `visual-product-search` in the planner catalog so this shape is recognised

**Blast radius:** planner examples + archetype catalog. **Effort:** 1 day. **Unlocks:** this class of apps generates in one shot.

### G4. Mobile camera → agent chat glue
`CameraCapture` + `FileUpload` + `POST /api/agent/chat` all exist. Needs a canonical page schema exemplar wiring them:
- Camera capture → upload to `forge_files` → return `file_id`
- Agent-chat call with `{ user_message: "Identify this", attachments: [file_id] }`
- Render structured `matches[]` as a `Grid` of `Card`s with price, seller, outbound button

**Blast radius:** schema exemplar in planner examples. **Effort:** ½ day. **Unlocks:** every app that uses camera-to-agent flow.

### G5. Result rendering starter
Optional: a `PriceCompareTable` starter (Table + outbound-link buttons + price sort + seller badge). Existing Table + Card cover it; a named starter just makes the planner emit it consistently.

**Blast radius:** planner exemplar only, no new library component. **Effort:** ½ day.

---

## 4. How the generated app will be built (after the slices land)

```
┌──────────────────────────────────────────────────────────────────┐
│  Generation input                                                 │
│  "an app where users scan a product with their phone camera,     │
│   the app identifies it, shows prices from multiple retailers,   │
│   and admin can toggle which retailers are searched"              │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  Planner                       │
              │  - archetype: visual-product-search
              │  - entities: scan_events, retail_sources, users
              │  - agent-graph: identify + mcp:search
              │  - integrations: Firecrawl-MCP (or SerpAPI)
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  Deterministic emit            │
              │  - Drizzle schema              │
              │  - Auth/RBAC (user, admin)     │
              │  - CRUD for retail_sources     │
              │  - Camera+upload page (mobile) │
              │  - Results-render page         │
              │  - Admin dashboard             │
              │  - Agent JSON definition       │
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  code_editor agent            │
              │  materialises the agent-graph │
              │  → src/agents/agent-service.ts│
              │  → POST /api/agent/chat       │
              │  wiring MCP tool node calls   │
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  Self-Verify Pass (user-invoked)
              │  Playwright drives:           │
              │  - login as admin, toggle a source
              │  - login as user, scan image, verify results
              │  - Smith auto-fixes any faults │
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  Deploy (Vercel + Expo build) │
              └───────────────────────────────┘
```

The **agent-graph** the planner emits looks roughly like:

```
system_prompt: "You identify products from images and return live prices
                from admin-approved retailers. Return JSON: {product, matches[]}"
  │
  ▼
tool: identify_product (custom → ai_extract with vision)
  │
  ▼
router: confidence >= 0.5  ── no ──▶ return "not identifiable"
  │ yes
  ▼
tool: search_prices (mcp → firecrawl.search)
  │
  ▼
guardrail: filter results whose seller ∉ retail_sources WHERE enabled=true
  │
  ▼
memory: cache by image hash (24h TTL)
  │
  ▼
return {product, matches: [{title, price, currency, seller, url, image}, ...]}
```

Every arrow above is a node in the existing agent-builder. The only *new* node type is the `mcp` tool.

---

## 5. Slices (revised, ordered, atomic)

### Slice 1 — `mcp` tool_type in Agent Builder (unblocks everything)
**Effort:** 3–5 days
**Files:**
- `frontend/src/components/agent-builder/ToolNodeConfig.tsx` — add `mcp` option, fields: `server_url`, `transport`, `auth`, dynamic `tool_name` picker (populated from server's `tools/list`)
- `backend/routers/agent_builder.py::_build_agent_instruction` — new branch for `tool_type == "mcp"`, emits MCP-client-invocation code
- `backend/templates/standalone-app/package.json.tmpl` — add `@modelcontextprotocol/sdk`
- `backend/templates/standalone-app/src/agents/lib/mcpClientPool.ts` — new file, memoised MCP clients with reconnect
- `backend/services/node_config_specs.py` — declare `tool_type=mcp` spec so validator + editor recognise it
- `backend/services/platform_integrations` — add `mcp_servers` provider category (server URL + auth token per server)
- Tests: unit for pool, integration for codegen path, e2e apply

**Acceptance:** create an agent in the builder with an MCP tool → apply → generated app has working `agent-service.ts` that talks to Firecrawl MCP.

### Slice 2 — Vision preset on `ai_extract`
**Effort:** ½ day
**Files:**
- `backend/templates/runtime/workflows/ai.ts` — verify image content block is passed to Claude; add mime-detection
- `backend/services/node_config_specs.py` — add `ai_identify_product` preset (or `inputKind: image` on ai_extract)
- Test with real image
- Prompt library: add `identify_product_from_image` template

**Acceptance:** in the workflow editor, an `ai_identify_product` node fed a `forge_files` id returns `{brand, model, category, attributes}` JSON.

### Slice 3 — Planner recipe: visual-product-search archetype
**Effort:** 1 day
**Files:**
- `backend/services/app_design_catalog.py` — add `visual-product-search` archetype
- `backend/services/page_type_templates.py` — add scan-page + results-page templates
- Planner examples (`backend/services/planner_examples/`) — add a visual-product-search exemplar showing entities, agent-graph, integrations
- `backend/services/domain_context.py` — add category context

**Acceptance:** generation from the note's exact prompt produces the entities + agent-graph + integrations block without hallucination.

### Slice 4 — Mobile camera → agent chat exemplar
**Effort:** ½ day
**Files:**
- Planner exemplar page schema wiring `CameraCapture` → `FileUpload` → agent-chat call → result render
- (Optional) small `useAgentChat()` React hook in `templates/app-foundation/src/hooks/`

**Acceptance:** generated scan-page renders on mobile, captures image, uploads, calls agent, shows matches within 5s.

### Slice 4.5 — Auto-install app agent from `plan.agent_graph`
**Effort:** ½–1 day
**Status:** implemented

**Problem:** the planner already emits an `agent_graph` block on
archetypes flagged `has_agent: true`, but nothing in the generation
pipeline reads it. Generated apps ship with entities/pages/workflows
but no live agent — the user has to open the Agent Builder UI and
recreate the same graph by hand every time.

**Files:**
- `backend/services/agent_from_plan.py` — new service:
  - `build_agent_definition_from_plan(plan, org_id, db) -> Optional[dict]`
    reads `plan['agent_graph']` and returns an AgentDefinition JSON in
    the exact shape the Agent Builder saves (see §5.5). MCP tools are
    resolved by `mcp_server_name` against `platform_mcp_servers`
    scoped to `org_id`; unresolved MCP tools are dropped with a
    WARN log, and if every tool was an unresolved MCP tool the whole
    build is skipped (return None) — we don't ship an agent that
    can only think and never act.
  - `install_agent_from_plan(output_dir, plan, org_id, db) -> Optional[dict]`
    writes `<output>/agent-definitions/<agent_id>.json` (idempotent —
    the agent_id is a UUIDv5 derived from `plan.name + agent.name`, so
    re-running generation updates the same file), then calls
    `run_code_editor` with the same instruction the Builder's Apply
    button uses. Validator/indexer run afterwards from the outer
    pipeline.
- `backend/routers/generate.py` — hook in `_run_relay_pipeline` AND
  `_run_figma_relay_pipeline`, right after the binding gate and just
  before `build_success_event()`. Wrapped in a broad `try/except`:
  a failure here is non-fatal — the user can still deploy the app and
  re-generate the agent from the Builder UI.
- `backend/services/schema_examples/visual_product_search.json` —
  replaced the legacy prose-level `agent` object with a concrete
  `agent_graph` block matching the §5.5 shape.
- `backend/agents/planner.py` — planner prompt paragraph telling
  the model to emit `agent_graph` when the archetype has
  `has_agent: true`, with a one-shot compacted example.
- `backend/tests/services/test_agent_from_plan.py` — unit tests
  (no-agent-graph, single tool, MCP resolved / not-resolved,
  multi-tool, guardrails).
- `backend/tests/routers/test_agent_from_plan_pipeline.py` —
  integration-lite: mocks `run_code_editor` to a no-op and asserts
  the JSON file lands with the expected shape.
- Snapshot test in `test_agent_builder_mcp_codegen.py` — the
  plan-derived AgentDefinition produces the SAME
  `_build_agent_instruction` output the frontend Builder would.

**Acceptance:** generation from the note's exact prompt produces an
`<output>/agent-definitions/<id>.json` + a working
`src/agents/agent-service.ts` + `POST /api/agent/chat` without any
Builder-UI interaction.

### Slice 5 — Live E2E on real prompt
**Effort:** ½ day + waiting
**Files:** none — pure acceptance
**Steps:**
1. Admin adds Firecrawl MCP + api key in `/settings/integrations`
2. Generate the app from the note's prompt
3. Publish to Vercel
4. Login as admin → toggle a source
5. Login as user → scan a real product photo → verify results appear
6. Run Self-Verify Pass with `fix=true`, let it catch and repair any drift

**Acceptance:** app works end-to-end without hand-editing.

---

## 5.5 `agent_graph` plan contract

The planner emits a top-level `agent_graph` block on any plan whose
archetype has `has_agent: true` (see
`services.app_design_catalog.APP_ARCHETYPES`). The block is the
canonical hand-off between the planner and Slice 4.5's
`services.agent_from_plan` — every field below is what
`build_agent_definition_from_plan` reads, and any extra keys the
planner emits are ignored (forwards-compatible with future node
types).

```json
{
  "agent_graph": {
    "name": "PriceScanAgent",
    "description": "Identifies products and gets prices via Firecrawl.",
    "system_prompt": {
      "prompt": "You are ...",
      "model": "claude-sonnet-4-5",
      "temperature": 0.2
    },
    "tools": [
      {
        "name": "identify_product",
        "tool_type": "function",
        "code": "// TS body — code_editor materialises this",
        "description": "Given a file_id, identify the product via Claude vision"
      },
      {
        "name": "search_prices",
        "tool_type": "mcp",
        "mcp_server_name": "Firecrawl",
        "mcp_tool_name": "firecrawl_search",
        "args_mapping": {
          "query": "{{identify_product.brand}} {{identify_product.model}}"
        }
      }
    ],
    "guardrails": [
      {
        "name": "confidence_gate",
        "guardrail_type": "output_filter",
        "rules": [
          { "name": "min_confidence", "type": "threshold",
            "expr": "identify_product.confidence >= 0.5" }
        ]
      }
    ],
    "memory": { "memory_type": "conversation", "capacity": 20 },
    "router": null,
    "human_handoff": null
  }
}
```

### Field notes

- **`name` / `description`** — free-text; used as the AgentDefinition
  envelope's name+description.
- **`system_prompt.prompt` / `.model` / `.temperature` / `.max_tokens`** —
  copied verbatim into the `system_prompt` node's `config`. The
  synthesised node is always the `is_entry_point`.
- **`tools[].tool_type`** — one of `function | api_call | db_query |
  workflow | data_engine | external | mcp`. Anything the frontend
  `ToolType` enum accepts round-trips.
- **`tools[]` with `tool_type: "mcp"`** — the planner references the
  server by NAME (`mcp_server_name`), not by uuid. Slice 4.5 resolves
  the name against `platform_mcp_servers` scoped to the project's
  `org_id`; unresolved names are dropped with a WARN log. Every other
  MCP field (`mcp_tool_name`, `args_mapping`) is copied through.
- **`guardrails[].rules[].expr`** — human-readable expression the
  code_editor turns into runtime logic. Also accepts `expression`
  (frontend spelling).
- **`memory` / `router` / `human_handoff`** — optional; omit or set to
  `null` when the agent doesn't need them.

### Edge auto-wiring (deterministic)

`build_agent_definition_from_plan` lays out the graph as::

    system_prompt → tool_1 → tool_2 → ... → tool_N
                                              ├─ guardrail_1 ─┐
                                              ├─ guardrail_2 ─┤
                                              ├─ memory       ├─→ human_handoff (if any)
                                              └─ router       ┘

The tool column is threaded serially; guardrails / memory / router
fan out in parallel from the last tool; `human_handoff` (when
present) is the terminal node that every tail chains into. Layout is
trivial (fixed columns + row step) — a human can rearrange the
canvas in the Builder afterwards and their positions round-trip.

### Idempotency

The agent id is a UUIDv5 in the URL namespace, seeded from
`plan.name + agent_graph.name`. Re-running generation with the same
plan therefore overwrites the same `<output>/agent-definitions/<id>.json`
file — no orphaned copies.

## 6. Open questions / risks

| Question | Impact | Note |
|---|---|---|
| Which MCP server for shopping? Firecrawl vs. Bright Data vs. Apify | Cost / data quality | Recommend Firecrawl for slice-1 (cheapest, has "scrape" + "search" tools). Bright Data is enterprise-grade fallback. |
| Legal — outbound links to Amazon/Flipkart | Affiliate revenue opportunity | Amazon Associates, Flipkart Affiliate can be layered later; not a blocker |
| Rate limits / cost budget per user | Runaway costs | Add per-user daily quota on agent-chat endpoint before public launch |
| Similar-product ranking | UX quality | Claude identify already returns similarity; MCP search returns Google-ranked results. Should be enough for MVP |
| Which retailers must be first-class? | Roadmap | Ask the customer. Default set: Amazon, Flipkart, Myntra, Ajio, Nykaa (region-appropriate) |
| Confidence threshold for "no match" | UX | Start at 0.5, tune from real data |
| Mobile-only or also web? | Scope | Note says "mobile phone camera" — Expo build is primary; web-mobile view is free from Next.js |

---

## 7. What we are NOT building (yet)

- Scraping our own retailer sites — always via MCP servers (which handle proxies, anti-bot, CAPTCHA)
- OCR-only mode (image → text → text search) — vision-native is better
- Barcode scanner as primary input — already have `Scanner` component (W6-2); can add as secondary flow later
- Real-time price alerts, wishlist, cart — out of scope, but existing cart/notification runtime can plug in later
- Custom-trained image models — Claude vision is more than sufficient for MVP; DINO/CLIP later if cost matters

---

## 7a. Local device testing — how the customer tries the generated app on their phone

The generated app has three shipping surfaces, each with a different install path:

| Path | Time to first-run on device | What the user installs | Prereqs | Best for |
|---|---|---|---|---|
| **A. Web on the phone browser** | 0 min — visit the deployed Vercel URL | Nothing (uses `getUserMedia`) | None | Fastest sanity check; no signing certs needed |
| **B. Expo Go** — user runs `npx expo start` inside emitted `mobile/`, scans QR | 2 min | Expo Go app (App Store / Play Store) | Node on their laptop, `mobile/` dir | Iteration during dev; JS-only reload |
| **C. EAS Development / Production build** — platform Publish dialog → Mobile tab | 10–15 min per platform | The generated `.apk` (Android sideload) or `.ipa` (via TestFlight or dev-provisioned device) | Apple Dev + Google Play credentials in `platform_integrations` | Real distributable build for testers |
| **D. Local native build** — `npx expo run:android` / `run:ios` in emitted `mobile/` | 5–10 min first time | Debug `.apk` on connected device or emulator | Android Studio (Android) or Xcode + macOS (iOS) | Debugging native modules |

**Recommendation for this app:** Path A for the customer demo (works with the Vercel URL we already have — camera works in mobile browser), Path C when they want a real APK to hand out. The Publish dialog already exists (MOBILE-D); a signed APK download URL lands ~10 minutes after clicking "Build for Android".

iOS quirk: Apple forbids direct `.ipa` install for anyone outside your dev team — a real device install requires TestFlight OR an ad-hoc provisioning profile with the tester's UDID. Not a Forge limitation; Apple's rule. Android has no such restriction.

## 7b. Small platform TODOs surfaced by these questions

Not blockers for the slice plan, but worth noting:
- **Verify path A actually works on iOS Safari for `CameraCapture`** — Safari has stricter `getUserMedia` permission rules than Chrome. Should test on a real iPhone before promising it.
- **Confirm the Publish dialog's Android APK path is still healthy on UAT** — MOBILE-D landed but has had few real customers. Worth a smoke pass alongside Slice 5.
- **Document "how to test on my phone" in the app dashboard** — a small info card near the Publish button with the three paths above would save every customer a support ticket.

## 8. Bottom line

Forge is one platform slice (`mcp` tool_type) away from generating this app end-to-end in a single prompt. Everything else is composition of what already exists.

Suggested week:
- **Days 1–4:** Slice 1 (`mcp` tool_type)
- **Day 5 AM:** Slice 2 (vision preset)
- **Day 5 PM:** Slices 3–4 (planner recipe + exemplar)
- **Day 6:** Slice 5 (live E2E)

By end of week: a paying customer could describe *"scan and price-compare app for [any vertical]"* and have a working web + mobile app inside 30 minutes.
