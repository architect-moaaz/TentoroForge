# Figma → Shippable App — Next Phase Plan

> **Status**: brainstorm / strategy. Not a task-by-task implementation plan yet — written to decide WHAT to build next, then we draft per-pillar plans.

## North Star

"Paste a Figma URL. Get a working web app. Iterate on it visually or via AI prompts. Ship it."

The MCP pipeline shipped this session covers step 1 → render. The remaining gap is render → edit → ship.

---

## What just landed (context for what's next)

- `figma_mcp_pipeline.build_schema_from_jsx` — JSX → PageV2 schema
- `figma_mcp_agent.fetch_jsx_via_mcp` — calls local Figma Dev Mode MCP from backend
- Wired into `_run_figma_relay_pipeline` after the deterministic mapper
- Transformer hardened across two test designs: login (~92%), dashboard (~85%) fidelity
- Library + renderer components accept Figma-derived `className`/`style` passthrough

What this means: a fresh Figma URL → backend run → rendered page at `/p/<id>/<route>` already works. The user has not yet driven a full generation through the UI — that's the V.1 prod-flow check.

---

## Pillars

### Pillar 1 — Editor parity for Figma-derived schemas
**Goal**: every MCP-generated schema opens cleanly in the existing visual editor with usable controls.

The editor already exists (P1 W5-W7: selection overlay, properties panel, drag-and-drop palette, AI edit loop). It was built against schemas the LLM produces. Figma-derived schemas look different in a few ways the editor may not handle gracefully:

- Arbitrary `className` strings (`bg-[rgba(255,255,255,0.2)]`, `gap-[12px]`) — does the properties panel show a usable affordance, or just a string field?
- Heavily nested Stack/Row/Container trees from Figma — does the selection tree stay readable?
- `_figmaNodeId` props — preserved by transformer, but does the editor use them as breadcrumbs back to the source design?

**Work units**:
1. Smoke-test: load every existing MCP-generated schema in the editor; collect failures
2. Properties panel pivot: high-level controls (padding, color, size) that compile down to className tokens, instead of raw className textarea
3. Round-trip integrity: edit → save → re-render → DOM equivalence (P1 W9 covers non-Figma; add Figma-derived case)
4. _figmaNodeId surfaced in editor — "this came from frame 1:74" label + jump-back link to the Figma file

**Estimate**: 1-2 weeks.
**Leverage**: high — the editor is the differentiator vs. "Figma → static HTML" tools.

### Pillar 2 — Make Figma designs interactive
**Goal**: turn the static rendered surface into a functioning app skeleton.

Figma designs are static by nature. To go from rendered → working, we need:

- **Button workflows**: classify `Sign in` button → `onClick="workflow:auth.signIn"`; `View Analytics` → `navigate:/analytics`. Use the same name classifier we built for nodes
- **Multi-page nav-flow**: the Commitbiz file has 4 frames (login + 3 dashboards). The `figma_route_inferer` already infers routes; we need to emit a nav-flow connecting them so the rendered app routes correctly
- **Form binding**: `Email Input` → `name="email"` + form submit → workflow
- **Mock data sources**: the "Intent Signals" feed shows 5 mock entries. Emit a `dataSources` entry with the static data so the schema is consistent with our PageV2 data-driven render path
- **Icon resolution**: Figma SVG decorative icons currently inline; semantic icons (Search, Bell, Brain) should map to the library's icon registry

**Work units**:
1. Action-classifier: pass Button labels/data-names through a small dictionary → workflow/navigate inference
2. Nav-flow emitter: per-project nav-flow from inferred routes; render-scaffold's `PreviewShell` already consumes nav-flow
3. Form-binding inference: from `Email Input` data-name + Form ancestor → name/workflow props
4. Static dataSources from repeating card structures (5 signal cards → mock dataSource entry)
5. Semantic icon detection: if Figma node name matches a known icon (Search, Bell, Settings), swap the SVG for the library icon component

**Estimate**: 1 week.
**Leverage**: high — turns a pixel-faithful render into something a user can actually use. The nav-flow piece is the biggest unlock.

### Pillar 3 — Code emission ("export this as a real Next.js app")
**Goal**: user can download a tarball that's a runnable, deployable Next.js project — Tailwind-configured, assets bundled, schemas inlined.

`Engine W-C` already added an export tarball endpoint. Need to verify it works with MCP-derived schemas, since they have different shape than LLM-generated ones:

- Tailwind config in emitted app must compile Figma's arbitrary-value classes (we solved this in scaffold via `output/**/*.json` content path — emitted app needs equivalent)
- Figma assets in `public/figma/` must bundle into the tarball
- Asset URLs use `/api/asset/<projectId>/figma/<file>` in scaffold; emitted app needs a different path (just `/figma/<file>` since the projectId scoping won't exist)
- README + `npm run dev` should "just work"

**Work units**:
1. Audit `Engine W-C` tarball output against an MCP project; list gaps
2. Asset path rewrite at export time (scaffold path → bundled path)
3. Tailwind config in emitted app: include schema JSON in content paths
4. Optional: one-click Vercel deploy via API

**Estimate**: 1 week.
**Leverage**: medium — proves the project ships, but most users want to iterate before exporting.

### Pillar 4 — AI design adjustment loop
**Goal**: natural-language editing of Figma-imported designs.

`peer_patcher` (P1 W8) already handles "change Button color to blue" type edits. Should work on MCP-derived schemas since they're valid PageV2.

Things to validate:
- Does peer_patcher's prompt include enough context about Figma-derived className blobs?
- "Make the brand panel narrower" — does it find the right node? `_figmaNodeId` helps here
- "Use a different color scheme" — multi-node edit; current peer_patcher might struggle

**Work units**:
1. Smoke test peer_patcher on the Commitbiz login schema with 5 representative prompts
2. Augment prompt with Figma-derived className awareness if needed
3. Brand-token-level edits: detect `bg-[#841013]` recurring across schema → expose as `brand.primary` token; user edits the token, all references update

**Estimate**: 3-5 days.
**Leverage**: medium-high — differentiator if it works smoothly; can defer to v2.

### Pillar 5 — Fidelity hardening (ongoing)
**Goal**: stay ahead of regressions and build a "what's hard for us" catalogue.

**Work units**:
1. Corpus: 10 diverse Figma files (auth, dashboard, marketing, settings, modal, table, wizard, empty-state, error, profile)
2. Visual regression: golden screenshot per page; CI flags drift
3. Pattern catalogue: when a design renders poorly, document the Figma pattern + add a transformer fix
4. Optional: fidelity score per project, surfaced in UI

**Estimate**: ongoing — start with 3 fixtures + screenshot tests in week 1.

---

## Sequencing recommendation

Most-leverage first:
1. **Pillar 2 (interactivity)** — turns "pretty static page" into "I can actually click around the app I designed." Nav-flow is the killer feature.
2. **Pillar 1 (editor parity)** — the editor is already built; just need it to work on Figma schemas.
3. **Pillar 3 (code emission)** — needed for ship-ability; less urgent if users want to iterate in-app first.
4. **Pillar 4 (AI edits)** — magical when it works; cheaper to land after we've shaken out Pillars 1-3.
5. **Pillar 5 (hardening)** — concurrent throughout. Add a fixture every time we touch the transformer.

Total estimate to "paste URL → iteratable app you can ship": ~3-4 weeks of focused work.

---

## Open questions worth resolving before drafting per-pillar plans

1. **Editor positioning on Figma-derived schemas**: do we preserve Figma's arbitrary classNames (high fidelity, harder to edit) or normalize to library variant props (canonical, may lose pixel-perfect)? My guess: preserve for now, add "normalize" action user can invoke.

2. **Asset lifecycle**: Figma MCP asset CDN URLs expire in 7 days. Do we re-fetch on schedule, or bake into emitted tarballs as permanent files? Probably the latter for production.

3. **Multi-page handoff**: when Figma has 4 frames, do we always produce 4 pages? Or expose a "which frames to convert" picker? The deterministic plan_builder already lists all frames; user could check/uncheck.

4. **Auth flow**: Commitbiz login → dashboard flow needs at least a mock auth handler. Do we inject one automatically, or require the user to wire it post-import?

5. **Design tokens**: extract repeated colors/spacing into a token map at import time? This makes Pillar 4 (AI edits) and theme changes dramatically easier — change one token, all uses update. Worth doing early.

---

## What I'd build next, concretely

If I had a week starting tomorrow:

- **Day 1-2**: Pillar 2 unit 1+2 — action-classifier + nav-flow emitter. Get Commitbiz's 4 pages routing to each other on click.
- **Day 3**: Pillar 5 — 3 more Figma fixtures + screenshot regression test.
- **Day 4**: Pillar 1 unit 1 — open MCP-derived Commitbiz in the editor; fix whatever breaks first.
- **Day 5**: Pillar 1 unit 2 (start) — properties panel pivot for Stack/Row/Container nodes.

That gets us from "pretty rendered page" to "rendered + routes between pages + opens in editor" in a week, which is the threshold where this becomes shippable to a friendly first user.
