# Figma Schema Refiner — Design Spec

**Date:** 2026-06-04
**Status:** Approved (brainstorming → ready for implementation plan)
**Owner:** Tentoro Forge / Figma relay pipeline

---

## 1. Problem

When generating an app from a Figma design, the **deterministic Figma→schema mapper**
(`services/figma_to_schema.py`) reproduces the frame's *content, colours, and per-element
styling* faithfully, but emits a **fixed-pixel, non-responsive layout** (e.g. `w-[1271px]`,
`h-[Npx]`, `"wrap": false`, no breakpoints). It also does not reconstruct higher-level
layout structure (card containers with border/padding, responsive grids, alignment).

Observed on the Cemex "Gate Control" frame (`0:603`): content was correct (every entry
request, driver, Emirates ID, RFID photo, validation item, Approve/Deny), but rendered as a
cramped fixed-width column that does not reflow — desktop (1440px) and mobile (390px) looked
nearly identical, with the title running into its subtitle, plate numbers wrapping mid-token,
buttons floating, and no visible cards.

A width-only post-process (`_fluidize_fixed_width_shells`, already shipped) stops horizontal
overflow but cannot restore card structure, alignment, or true reflow.

### Why this path was taken (root cause)

The Figma relay pipeline (`_run_figma_relay_pipeline`) is gated by `SCHEMA_MODE_ENABLED`
(default `true`). Because the deterministic mapper *covered* the single requested page, the
pipeline **short-circuited to schema-only and never ran any LLM UI agent**. The LLM schema
agent (`run_schema_frontend_pipeline`) only runs for pages the mapper missed.

## 2. Goal & non-goals

**Goal:** Produce a **responsive, editable, component-library Page schema** for Figma pages
that **preserves the content** the deterministic mapper captured, while restructuring the
layout (cards, responsive grids, fluid widths, mobile-first).

**Decisions locked during brainstorming:**
- Output **must stay a Page schema** rendered by the component library (keep the visual editor
  + the 99 library components). → Rules out the raw-TSX `run_figma_ui_agent` path.
- Strategy is **refine the deterministic schema** (preserve its content) rather than regenerate
  from scratch.

**Non-goals:**
- No changes to the deterministic mapper itself.
- No changes to the raw-TSX `figma_ui_agent` or the general (non-Figma) schema pipeline.
- Not pixel-perfect fidelity — responsiveness + editability + content preservation are the
  priorities, in that order.

## 3. Approach (A) — dedicated Figma Schema Refiner agent

A new, self-contained agent takes the deterministic page schema + the frame screenshot + the
component-library descriptor, and returns a refined, validated, responsive Page schema. It is
wired into the schema-mode branch of the Figma relay pipeline behind an **opt-in flag** with a
**deterministic fallback**, so it is never worse than today.

### 3.1 Component / interface

New module `backend/agents/figma_schema_refiner.py`:

```python
async def run_figma_schema_refiner(
    deterministic_schema: dict,
    screenshot_path: str,
    registry_descriptor: str,
    *,
    timeout_s: int = 120,
) -> dict | None:
    """Refine a deterministic Figma-mapped Page schema into a responsive,
    component-library Page schema, preserving all content. Returns the refined
    schema dict, or None on any failure (caller falls back to the input)."""
```

- Models its LLM call and Page-schema **validation** on the existing `agents/page_schema_agent.py`
  so output conventions stay consistent.
- Sends ONE multimodal Anthropic message:
  - **system prompt** — the refine invariants (§3.3);
  - **image block** — the frame screenshot (base64; same image-input mechanism the design
    agent uses for `reference*.png`);
  - **text** — the deterministic schema JSON + the component-library descriptor
    (`services/schema_prompt._format_library_descriptor()` — the 99-component vocabulary).
- Uses the direct `anthropic.AsyncAnthropic` SDK (same as `domain_agent` / `page_schema_agent`),
  reading `ANTHROPIC_API_KEY` from env; `asyncio.wait_for(..., timeout_s)`.

### 3.2 Data flow (pipeline hook)

Inside `_run_figma_relay_pipeline` (schema-mode branch). On by default for Figma
pages; set `FIGMA_SCHEMA_REFINE=0` to skip (e.g. very large multi-page imports
where the extra per-page LLM call is too costly):

1. Deterministic mapper runs first, **unchanged** → writes content-faithful page schema(s) and
   already fetches/exports the frame PNG (reuse that asset for the screenshot; if absent, fetch
   the node image via the Figma image API using the `figma_token` + file key the pipeline holds).
2. If the flag is on, for each page the deterministic mapper produced
   (`route in deterministic_pages`): call `run_figma_schema_refiner(...)`.
3. **Validate** the refined output (same validator `page_schema_agent` uses):
   - valid → overwrite the on-disk page schema with the refined one;
   - `None` / invalid / timeout → **keep the deterministic schema** (safe fallback) and log it.
4. Photo injection, nav-flow emit, and app emit run unchanged on the resulting schema.

The short-circuit that skips the LLM when the mapper covers all pages is bypassed **only** when
`FIGMA_SCHEMA_REFINE` is on; otherwise behaviour is identical to today.

### 3.3 Refiner prompt contract (invariants)

- **Preserve exactly:** every text value, every binding (`{{...}}`), `dataSources`, and every
  image/photo URL present in the input schema.
- **Restructure layout:** real `Card` containers (border / padding / shadow), responsive grids
  and `flex-wrap`, `w-full` / `max-w-[…]` / `mx-auto`; drop fixed `w-[Npx]` / `h-[Npx]`;
  mobile-first (stacks on small screens, columns on large).
- **Vocabulary:** use ONLY registered component types from the provided descriptor.
- **Output:** a single Page schema object, `schemaVersion 2`, same top-level shape as the input
  (`schemaVersion`, `type`, `props`, `dataSources`, `children`, `id`).

## 4. Error handling & safety

- **Validated-or-fallback:** the deterministic schema is the floor; a bad refine never ships.
- **Retry-on-content-loss:** a recoverable failure (unparseable JSON, structurally invalid,
  dropped content, or a real Zod rejection) feeds the model a corrective instruction — for
  content loss, the exact dropped bindings/URLs/text — and retries up to `max_attempts`
  (default 2) before falling back. An API error / timeout is NOT retried.
- **On by default, opt-out:** runs for Figma pages by default; `FIGMA_SCHEMA_REFINE=0`
  disables it. Because it's validate-or-fallback, the worst case is identical to the
  pre-refiner deterministic output — the only cost of "on by default" is the extra
  per-page LLM call.
- **Per-page isolation:** one page failing to refine does not affect other pages.
- **Streaming + timeout:** refined schemas are large, so the call streams; each attempt has a
  `timeout_s` (default 600s) ceiling, so worst-case wall time is `max_attempts * timeout_s`.

## 5. Testing (TDD)

**Golden fixture:** the real deterministic `gate-mangement-3` schema (copy into
`backend/tests/fixtures/`), plus a small synthetic fixture for fast unit tests.

**Unit tests (LLM mocked):**
- valid refined output is used; invalid/`None`/timeout falls back to the deterministic input.
- **content-preservation** assertion helper: key tokens survive end-to-end — a plate
  (`DXB-T-12345`), an Emirates-ID-shaped string, `Approve Entry`, and a validation label
  (e.g. `Valid RFID`) all appear in the refined output.
- **responsiveness** assertion: refined output contains `w-full` / `max-w-[` / `flex-wrap`
  and has strictly fewer fixed `w-[Npx]` tokens than the input.
- prompt assembly: the message includes an image block + the registry descriptor + the input
  schema JSON.

**Integration (manual):** re-run Gate Control with `FIGMA_SCHEMA_REFINE=1`, render the page at
1440 / 768 / 390 px (Playwright), and compare against the Figma + the pre-refine render.

## 6. Scope guard (YAGNI)

Only: the refiner module + its prompt, the flagged pipeline hook, and the tests. No changes to
the deterministic mapper, the TSX agent, or the general schema pipeline.

## 7. Risks

- **LLM drops content** despite the invariant → mitigated by the content-preservation test and
  the deterministic fallback (we can also reject a refine that loses key tokens).
- **Validator coupling** — the refiner must use the same Page-schema validation the renderer
  trusts; reuse `page_schema_agent`'s validator rather than re-implementing.
- **Screenshot availability** — depends on the mapper's exported PNG or a fresh Figma image
  fetch; if neither is available the refiner runs text-only (schema + descriptor) or is skipped.
- **Cost/latency** — one extra LLM call per Figma page; acceptable, and opt-in.
