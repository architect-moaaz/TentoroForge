# Design Brief — Phase 1 (Additive)

**Status**: Phase 1 implemented; Phases 2 + 3 spec'd separately.
**Owner**: Smith design-quality workstream.
**Flag**: `FORGE_BRIEF_AUTHOR=1` (off by default).

---

## Problem

Every Forge-generated app has a design layer, but that layer today is a
mix of:
- LLM-authored `design_agent` output (non-deterministic, gravitates to
  AI-default aesthetics: cream + terracotta + serif).
- Ad-hoc `industry_design.py` domain mapping (partial, fragile).
- Figma-derived `styles.json` on the Figma path (source-dependent).

No single artifact says "this is the aesthetic contract for this app."
Downstream authors (component, page, figma) each interpret the intent,
and drift compounds.

## Solution

Introduce **`DesignBrief`** as the canonical design contract, authored
once per app, consumed by every author downstream. This spec covers
**Phase 1 only** — Phase 1 is additive: brief is authored + persisted +
snapshot-tested but not yet consumed by the pipeline. Zero risk to
existing generation.

## Non-goals (Phase 1)

- No pipeline changes beyond an optional call after discovery.
- No Smith awareness — Phase 2 adds that.
- No user-facing UI for the brief — Phase 3 adds the brief-loop card.

## Design

### Data model

`DesignBrief` is a Pydantic schema (`backend/schemas/design_brief.py`)
with enum-heavy sub-shapes:

```
DesignBrief
├── identity     Identity(domain, register[1-2], voice, modes)
├── palette      Palette(brand, accent, neutrals_base, neutrals_tint,
│                        surface_bg, surface_elevated,
│                        foreground_primary, foreground_muted)
├── typography   Typography(display_family, display_weights,
│                            body_family, body_weights,
│                            utility_family?, scale)
├── layout       Layout(density, radius, grid, whitespace)
├── signature_moves  [SignatureMove(kind, detail)]   # 1-2 required
└── anti_patterns   [str]                             # blocklist labels
```

Rationale:
- **Enum-only** where a closed vocabulary works (`Density`, `Radius`,
  `Voice`, `NeutralTint`, `Mode`). Prose is the enemy of the critic.
- **Hex codes** for every colour role — feeds the token compiler
  directly.
- **`signature_moves` capped at 2** — forces the LLM to commit; every
  visual can't be precious.
- **`anti_patterns`** is a blocklist labels list — the base list is
  always merged in (see below), domain-specific labels stack on top.

### Authoring flow

```
      Domain (classified by Discovery)
                │
                ▼
    ┌───────────────────────┐
    │ design_brief_cache.get│ ← anchors + previously-authored
    └────────┬──────────────┘
             │ hit? → return
             │
             ▼ miss
    ┌───────────────────────┐
    │ design_brief_author   │ ← LLM call with strict schema + antipatterns
    │ .author(domain, ...)  │
    └────────┬──────────────┘
             │
             ▼
    validate → merge BASE_ANTI_PATTERNS → cache → return
```

Cache mirrors `smith_recent_edits` and `app_map` cache patterns —
process-local, no DB. Anchors are always primed.

### The six anchor briefs

Hand-authored, one per canonical domain label from
`services.domain_context._classify_domain`:

| Domain | Register | Palette hint | Type pair | Density | Signature |
|---|---|---|---|---|---|
| Healthcare | trustworthy, calm | warm sage + terracotta | Fraunces + Inter | comfortable | warm serif hero + patient avatars |
| Legal | precise, authoritative | cool navy + red | Söhne + JetBrains Mono | compact | severity ribbons + sticky headers |
| Hospitality & Food | bold, fast | vermilion + black | Space Grotesk + Inter | spacious_for_touch | 56px taps + receipt totals |
| E-Commerce & Retail | editorial, confident | near-black + antique gold | Ogg + Neue Haas | spacious | product hero + wide measure |
| Human Resources | approachable, clear | indigo + orange | Söhne + Söhne | comfortable | team avatar stack |
| CRM & Sales | energetic, focused | sky-blue + orange | Söhne + Inter + JBM | compact | pipeline kanban hero |

Distinctiveness is enforced by test — no anchor shares a brand hex, at
least 3 unique display families, at least 2 densities.

### Base anti-patterns (always merged)

```python
BASE_ANTI_PATTERNS = [
    "warm_cream_plus_terracotta",
    "purple_to_blue_gradient_hero",
    "inter_everywhere",
    "cream_serif_over_beige",
    "everything_centered",
    "rounded_lg_uniformly",
    "emoji_as_section_markers",
    "dashboard_dark_blue_default",
]
```

The LLM authors domain-specific antipatterns; the base list is stapled
on. The model cannot override.

### LLM system prompt

See `services.design_brief_author._SYSTEM_PROMPT` — condensed from
Anthropic's `frontend-design` + `artifact-design` skill guidance. Key
disciplines:

1. Ground it in the subject.
2. Neutrals are chosen, not defaulted (tint toward accent).
3. Type pairing is the personality.
4. One or two signature moves.
5. Commit to a register.

Plus the hard blocklist above.

## Rollout

Phase 1 is **fully additive** — even when the flag is on, no downstream
code consumes the brief. Wire path:

1. `FORGE_BRIEF_AUTHOR=1` in env.
2. After discovery: `Project.brief = await author(domain,
   plan_summary=...)`.
3. Persist to `Project.brief` JSONB column (added via Alembic migration).
4. Dev-only endpoint: `GET /api/dev/briefs` lists cached briefs for
   eyeball review.

**No user impact.**

## Acceptance

- 29 unit tests pass (schema, anchors, cache, author cache-hit, author
  LLM path with injected `query_fn`, antipattern merging, force_llm).
- All 6 anchors parse cleanly and are distinctive on 3 axes.
- With flag on, existing generation still works (regression suite green).
- With flag on, novel-domain runs land briefs in the cache; anchors
  never trigger LLM calls.

## Follow-ups (not Phase 1)

- **Phase 2** — inject brief.antiPatterns + signatureMoves into
  component/page/figma agent prompts. First user-visible win.
- **Phase 3** — replace `design_agent`; add Smith `edit_brief` tool;
  render `DesignBriefCard` in chat.
- **Snapshot corpus** — CI job runs `author` against a fixed 20-domain
  corpus; diff against previous snapshots.
- **Voice enrichment** — feed `identity.voice` to a future content agent
  for plausible domain-specific placeholder data.
