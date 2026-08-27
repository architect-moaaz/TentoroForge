# Chunked Page-Schema Generation — Design

**Date:** 2026-06-20
**Status:** Design approved, pre-implementation
**Branch:** forge-v3

## Problem

In schema mode (the default, `SCHEMA_MODE_ENABLED=true`), each page's schema JSON is
produced by a **single LLM text response** — `page_schema_agent._generate_schema_for_page`
calls `_collect_llm_text(prompt)` ([page_schema_agent.py:304](../../../backend/agents/page_schema_agent.py))
and parses the whole blob. Large pages (analytics/intelligence/report dashboards)
reach **150–315 KB ≈ 40–80k tokens** of JSON in one response and overflow the model's
output-token cap (`Claude's response exceeded the … output token maximum`). Raising
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` to 64000 (already done) covers typical pages but **not**
the largest (≈70–80k tokens), and going higher hits the model ceiling.

Every other heavy agent (`page_agent`, `component_agent`, `code_generator`, `api_agent`,
`seed_generator`, `schema_agent`, `business_logic_agent`) writes files incrementally via
the **Write tool**, so each turn is bounded — they cannot hit this cap. Only the
schema-mode page generator (and its shared core in `feature_slice_schema_agent`) returns
one monolithic blob.

## Goal

Generate large page schemas in **bounded chunks** so no single LLM response approaches the
cap, while leaving the fast single-call path unchanged for normal pages and preserving the
existing validation / normalization / fallback behavior exactly.

## Key insight

The schema envelope is `{schemaVersion, id, route, root: {type:"Stack", id:"root",
children:[...]}}`. The **root's `children` ARE the page's top-level regions.** That makes a
two-pass "skeleton then fill regions" strategy natural: generate the root layout with region
placeholders, then fill each region's subtree independently, then splice them in.

## Architecture

New module **`backend/services/chunked_schema.py`** (keeps `page_schema_agent` focused),
exposing one orchestrator plus small pure helpers. `page_schema_agent` calls it only on the
chunk trigger; everything else is unchanged.

### Data flow

```
single-call attempt (existing) ──ok──► validated schema (fast path, unchanged)
        │ overflow detected  │ OR retry loop exhausted
        ▼
chunked generation:
  Pass 1  skeleton call  → root layout with region placeholders [{id, brief}]
  Pass 2  per region: fill call → that region's subtree (bounded)
  Assemble: replace each placeholder with its filled subtree → final root
  normalize_v2_schema + _validate_schema_json   (existing, unchanged)
        │ ok                          │ fail
        ▼                              ▼
   validated schema           _minimal_schema (existing fallback)
```

## Components

### 1. Trigger (hybrid) — in `page_schema_agent._generate_schema_for_page`

The single-call path stays the default. Two routes into chunked mode:

- **Overflow fast-route:** wrap the `_collect_llm_text(...)` call; if it raises an error
  whose message matches the output-cap signature (e.g. contains `output token` /
  `exceeded` / `max_tokens`), switch to chunked generation **immediately** (no wasted
  retries).
- **Backstop:** if the normal retry loop exhausts without a valid schema (any cause),
  attempt chunked generation **once** before returning `_minimal_schema`.

Detection is a small pure helper `is_output_overflow_error(exc) -> bool` (string match,
case-insensitive) so it is unit-testable and easy to widen.

### 2. Skeleton pass — `chunked_schema.generate_skeleton(...)`

One LLM call. Reuses the page's existing prompt **context** (tokens, design brief, binding
context, archetype template, shell rules) but replaces the OUTPUT instruction with a
**skeleton directive**: emit ONLY the page root (`Stack`/`Container`) whose children are
**region placeholders**, each `{ "type": "Region", "id": "<slug>", "brief": "<one line
describing the content of this region>" }`. No deep content, no nested component trees.
Returns the parsed skeleton dict (root with N placeholder children). This response is small
and cannot overflow.

A `_region_placeholders(skeleton) -> list[{id, brief}]` helper extracts the regions.

### 3. Region-fill pass — `chunked_schema.fill_region(...)`

One LLM call per region. Reuses the same context plus a **region directive**: "Emit ONLY
the subtree (a single node with its children) for region `<id>`. Brief: `<brief>`. Use the
design tokens / bindings / components above." Returns the parsed subtree node. Each region
is far below the cap.

Regions are filled with **bounded concurrency** (reuse the project's existing async patterns)
so a many-region page doesn't serialize N slow calls; order is preserved by index.

### 4. Assembly — `chunked_schema.assemble(skeleton, filled) -> dict`

Pure function. Walk the skeleton root's children; for each placeholder, substitute the
corresponding filled subtree (matched by region id/index). Produce the final
`{schemaVersion, id, route, root}` envelope (carry the id/route/schemaVersion from the page
brief, identical to the single-call envelope). No LLM. Fully unit-testable.

### 5. Validation — unchanged

Run the **existing** `normalize_v2_schema` then `_validate_schema_json` on the assembled
schema. If it fails, return `_minimal_schema` (today's behavior). No new validator.

## Error handling — degrade, never abort

- **One region fails** (LLM error, unparseable, or invalid subtree): replace that region
  with a minimal placeholder node (a `Card`/`Stack` containing a `Heading` derived from the
  region brief) and keep all other regions. The page still renders, missing only one
  section's richness.
- **Skeleton call fails** (error or unparseable): abandon chunking, return today's
  `_minimal_schema(slug, page_type)` — exactly the current fallback, no regression.
- **Assembled schema fails validation**: same `_minimal_schema` fallback.
- The whole chunked path is wrapped so any unexpected exception degrades to `_minimal_schema`
  — chunking can never make generation worse than today.

## Out of scope

- `shell_layout_agent` (also blob-returned, but ≤ ~30 KB — well under the cap).
- Recursive chunking (a single region exceeding the cap is implausible; one level only).
- Changing `build_schema_prompt`'s existing single-call output contract for normal pages.
- The "constrain / node-count cap" approach (was the alternative option; not chosen).
- The standalone-app SSR render blocker (GF-1) and other unrelated items.

## Testing (TDD)

- `is_output_overflow_error`: matches the cap message variants; returns False for unrelated
  errors.
- `generate_skeleton` (mocked LLM): parses a skeleton, extracts region placeholders.
- `fill_region` (mocked LLM): parses a region subtree.
- `assemble`: splices filled subtrees into the skeleton in order; envelope fields correct.
- Failed region → minimal placeholder substituted, other regions intact.
- Skeleton failure → `_minimal_schema` returned.
- Overflow on the single call routes into chunked mode (trigger test with a raising mock).
- Assembled schema passes the existing `_validate_schema_json`.
- Integration (mocked LLM end-to-end): a page that overflows the single call yields a valid
  assembled multi-region schema.

## Success criteria

A page whose single-call schema would exceed the output cap is instead generated as a
skeleton + per-region fills and assembled into a valid Page schema that passes the existing
validator — with normal/small pages still taking the single fast call (zero behavior
change), and every failure mode degrading to today's `_minimal_schema` rather than aborting
generation.
