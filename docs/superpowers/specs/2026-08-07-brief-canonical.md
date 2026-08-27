# Brief-Canonical — Phase 3 of Design Brief (Visual Authority)

**Status**: spec'd, not implemented.
**Owner**: Smith design-quality workstream.
**Companion**: `2026-08-07-design-brief.md` (Phase 1 + 2 already shipped).
**Flag path**: gated by `FORGE_BRIEF_CANONICAL=1`; emergency restore via `FORGE_LEGACY_DESIGN_AGENT=1`.

---

## Problem

Phase 1 (`FORGE_BRIEF_AUTHOR=1`) authors `contracts/brief.json` and
Phase 2 (`FORGE_BRIEF_CONSUME=1`) injects it into 3 downstream agent
prompts (component / page / figma). But the brief has **no visual
authority** in the generated app. Live evidence (property-mgmt run
`facp2lcu`, 2026-08-07): brief authored a navy `#2D5A8E` + amber
`#E8A020` + IBM Plex + sharp corners — the rendered app shipped a
near-black sidebar, shadcn-default blue CTA, Inter-ish body, pill
inputs. Every listed anti-pattern (`dashboard_dark_blue_default`,
`blue_dashboard_chrome_default`, `rounded_pill_buttons`,
`inter_everywhere`) got hit.

**Hard constraint — no Figma drift**: for projects sourced from a Figma
design, the generated app's palette, typography, radius, and spacing
MUST match the Figma source exactly. Not "close" — exact. This rules
out any LLM in the design decision chain when Figma is the source of
truth. The brief becomes an aggregation layer; the actual values are
extracted deterministically from Figma via the existing extractor
stack (`figma_style_extractor`, `figma_typography_extractor`,
`figma_shell_extractor`, `figma_context`).

**Root cause: three unwired visual authorities**

| Layer | Written by | Reads brief? | What it produces |
|---|---|---|---|
| CSS tokens (`--color-brand-*`, `--font-*`) | `agents/design_agent.py` + `design_compiler.py` | No | `src/app/globals.css` variables |
| Shell chrome (sidebar bg/fg, nav active state) | `services/shell_templates.py` | No | `shell.json` + emitted `SideNav` props |
| Control primitives (Button, Input) | `@forge/library/dist` | No | Hardcoded shadcn indigo defaults |

`design_agent` runs its own Anthropic call ~1s after brief-author with
its own prompt (`"You are a senior UI/UX Design Researcher..."`). It
authors `contracts/design-spec.json` describing colors/typography/radius
that overlap the brief 1:1, then `design_compiler.py` writes those into
CSS. Two LLM authors, no coordination, design-agent wins.

## Solution

Make brief the **sole** visual authority. Delete `design_agent`'s LLM
call, deterministically map `brief.json → design-spec.json`, teach
shell templates + library primitives to consume tokens instead of
hardcoding.

## Non-goals

- No changes to brief author or schema — Phase 1 already shipped.
- No new LLM calls — Fix is entirely deterministic once brief exists.
- No form intelligence — that's the sibling `2026-08-07-domain-form-intelligence.md` spec.
- No Figma path yet — see risks.

## Design

### Slice 1: `services/brief_to_design_spec.py` (new, ~150 lines)

Pure mapping. Takes `DesignBrief` (already Pydantic-validated), emits
the same dict shape `design_agent` produces today, so downstream
`design_compiler.py` doesn't change.

```python
def brief_to_design_spec(brief: DesignBrief) -> dict:
    return {
        "colorPalette": {
            "brand": _shade_scale(brief.palette.brand),          # 50-950
            "accent": _shade_scale(brief.palette.accent),
            "neutral": _derive_neutrals(brief.palette),          # tint-aware
            "semantic": _default_semantic_colors(),              # success/warn/error
        },
        "typography": {
            "display": {"family": brief.typography.display_family,
                        "weights": brief.typography.display_weights},
            "body": {"family": brief.typography.body_family,
                     "weights": brief.typography.body_weights},
            "utility": {"family": brief.typography.utility_family},
            "scale": _resolve_scale(brief.typography.scale),      # tight/normal/loose
        },
        "layout": {
            "density": brief.layout.density,
            "radius": _radius_scale(brief.layout.radius),         # sharp_2 → {sm:2, md:2, lg:4}
            "grid": brief.layout.grid,
        },
        "modes": {"light": True, "dark": "dark" in brief.identity.modes},
    }
```

Tested with a corpus of 10 diverse-domain snapshot briefs (Slice 7
removes hand-authored anchors; corpus briefs are LLM-authored during
test setup and pinned as JSON fixtures).

### Slice 2: Split `agents/design_agent.py` in two

- **Extract the CSS-writing mechanics** (`_hex_to_hsl_channels`,
  `_rewrite_globals_root`, `_build_google_fonts_url`,
  `_register_from_spec_fonts`, `_build_typography_block`,
  `_inject_typography_into_globals`, `_populate_entity_photos`,
  `save_design_spec`, `load_design_spec`) into
  `services/globals_writer.py` — no logic change, just relocation.
- **Delete the LLM prompt + `run_design_agent` + `extract_design_spec`**.
- **Delete callers** in `routers/generate.py` (3 sites: 1271, 1654, 3926).

### Slice 3: Pipeline rewire

Replace the `"Design"` phase in `_run_relay_pipeline` /
`_run_figma_relay_pipeline` with a synchronous ~50ms call:

```python
if os.getenv("FORGE_BRIEF_CANONICAL", "0") == "1":
    brief = load_brief_from_disk(output_dir)  # Phase 1 helper
    spec = brief_to_design_spec(brief)
    save_design_spec(output_dir, spec, plan)  # from globals_writer
    globals_writer.write_globals(output_dir, spec)
else:
    # Legacy path — unchanged
    async for evt in _stream_phase("Design", run_design_agent(...)):
        yield evt
```

The `FORGE_LEGACY_DESIGN_AGENT=1` escape hatch flips the branch back
even when `CANONICAL=1`.

### Slice 4: `shell_templates.py` reads brief palette

Today's `sidebar_dark`/`sidebar_light`/`topbar`/`rail` builders each
carry a hardcoded palette (dark navy sidebar). Change signature:

```python
def build_sidebar(brief: DesignBrief, ia: IA) -> ShellSpec:
    return ShellSpec(
        bg=_shell_bg_for(brief),     # brief.palette.brand shade-900 in dark mode,
                                     # surface_elevated in light
        fg=_shell_fg_for(brief),     # contrast-matched
        active_bg=brief.palette.accent,  # active nav uses accent
        active_stripe=brief.palette.accent,
        brand_tile_bg=brief.palette.brand,  # NOT the green square in evidence
    )
```

Emitted `SideNav` props read these instead of literal hex. ~80 lines
change in `shell_templates.py` + `select_frame.py`. Deterministic; the
existing `build_shell_deterministic` test suite covers regressions.

### Slice 5: `@forge/library` primitives read tokens

Today's `Button` component in the library ships with variant classes
that resolve to shadcn's default palette (`bg-primary` → `#3B82F6`).
Change:

```tsx
// packages/library/src/components/Button/index.tsx
<button style={{
  '--btn-bg': `var(--color-brand-500)`,
  '--btn-fg': `var(--color-brand-fg)`,
  '--btn-radius': `var(--radius-control)`,
}}>
```

`--radius-control` set from `brief.layout.radius` (`sharp_2` → `2px`).
Same for `Input`, `Select`, `Checkbox`, `Textarea` — all read
`--radius-control` instead of hardcoded `rounded-md`. ~40 lines in
library + rebuild dist + re-vendor into template.

### Slice 6: Figma authority — deterministic, no drift (mandatory, ships in first cut)

**Constraint**: for Figma-sourced projects the LLM must not be in the
design decision chain. Palette, typography, radius, and spacing come
from Figma extraction; brief is populated deterministically. Drift = 0.

The existing extractor stack already produces the raw material —
what's missing is aggregation into the brief and enforcement that
downstream authors (and Smith) don't overwrite Figma-sourced fields.

**6a — `services/brief_from_figma.py` (new, ~200 lines)**

Pure aggregator. Wraps the existing extractors and emits a
`DesignBrief` with `source="figma"` and per-field `locked=True` on
every field it fills. Called instead of `brief_author` whenever
`figma_context` is present.

```python
def brief_from_figma(figma_ctx: dict, plan: dict, domain: str) -> DesignBrief:
    colors = figma_style_extractor.extract_palette(figma_ctx["styles"])
    typo = figma_typography_extractor.extract(figma_ctx["styles"])
    shell = figma_shell_extractor.summarize(figma_ctx["shell_tree"])

    return DesignBrief(
        identity=Identity(domain=domain, source="figma"),
        palette=Palette(
            brand=colors.primary,           # verbatim hex, no LLM
            accent=colors.accent,
            neutrals_base=colors.neutral_base,
            neutrals_tint=colors.neutral_tint,
            surface_bg=colors.surface,
            surface_elevated=colors.surface_elevated,
            foreground_primary=colors.text_primary,
            foreground_muted=colors.text_muted,
            _locked_fields={"brand", "accent", "neutrals_base",
                            "surface_bg", "surface_elevated"},
        ),
        typography=Typography(
            display_family=typo.display,     # verbatim family name
            body_family=typo.body,
            display_weights=typo.display_weights,
            body_weights=typo.body_weights,
            scale=_infer_scale_from_sizes(typo.sizes),  # deterministic map
            _locked_fields={"display_family", "body_family"},
        ),
        layout=Layout(
            density=_density_from_spacing(shell.spacings),  # px → enum
            radius=_radius_from_px(shell.radius_px),
            grid=shell.grid_hint or "sidebar_plus_12col_main",
            _locked_fields={"radius"},
        ),
        signature_moves=[],  # empty for Figma — the Figma IS the signature
        anti_patterns=BASE_ANTI_PATTERNS,
    )
```

All values are copy-from-Figma; the only "inference" is mapping
continuous px values (spacing, radius) to the brief's enum vocabulary,
and this mapping is deterministic (nearest-bucket).

**6b — Brief schema: per-field `_locked_fields` + `source`**

Extend `schemas/design_brief.py`:

```python
class Palette(BaseModel):
    ... existing fields ...
    _locked_fields: set[str] = Field(default_factory=set)

class Identity(BaseModel):
    ... existing ...
    source: Literal["authored", "figma"] = "authored"
```

Locked fields serialize; brief editor + Smith `edit_brief` respect
them (see 6c).

**6c — Smith `edit_brief` respects locks**

`services/design_brief_editor.py.apply_patch` refuses any patch that
targets a locked field. Smith's tool returns:

```json
{
  "error": "figma_locked",
  "message": "Brand color is locked from Figma source. Unlock in project settings to override.",
  "locked_fields": ["palette.brand"]
}
```

The DesignBriefCard hides tweak buttons whose target is locked (grays
them out with a "🔒 Figma" chip). Explicit unlock via a project
setting is out of scope for this spec (follow-up).

**6d — Pipeline branch in `_run_figma_relay_pipeline`**

```python
if os.getenv("FORGE_BRIEF_CANONICAL", "0") == "1":
    if figma_context:
        brief = brief_from_figma(figma_context, plan, domain)
    else:
        brief = await brief_author(domain, plan_summary)
    save_brief(output_dir, brief)
    spec = brief_to_design_spec(brief)
    save_design_spec(output_dir, spec, plan)
    globals_writer.write_globals(output_dir, spec)
```

**6e — `brief_to_design_spec` preserves Figma values byte-for-byte**

For Figma-sourced briefs, `brief_to_design_spec` must NOT run its
palette-shade-scale helper on the brand color — it must use the exact
hex Figma provided. Add a branch: if `identity.source == "figma"` and
the field is locked, use the raw value; else derive shades.

**Tests**:
- Snapshot test: known Figma styles.json → brief output must match
  golden JSON exactly. Any deviation fails the build.
- Round-trip test: `brief_from_figma → brief_to_design_spec →
  globals_writer` → rendered CSS must contain the exact Figma hexes as
  `--color-brand-500` etc.
- Lock test: `edit_brief` with a locked-field patch returns error, no
  disk mutation.

Ship 6a through 6e together in the first cut. No follow-up option.

### Slice 7 — Strip hand-authored anchors, keep cache infrastructure (~0.5 day)

**Problem**: Phase 1 shipped `services/design_brief_anchors.py` with 6
hand-authored `DesignBrief` objects (Healthcare, Legal, Hospitality,
E-Commerce, HR, CRM). They serve two roles today:
1. **Cache pre-prime** — matching domain returns the anchor verbatim, no
   LLM call.
2. **Few-shot examples** in the brief-author prompt.

Both are per-domain hardcoded intelligence — the same anti-pattern
called out for archetype recipes in Spec C. My guess at what property
management should look like beats the LLM's informed synthesis from
discovery output. Six domains hardcoded ≠ N domains supported.

**Fix — cache stays, hand-authored anchors go**:

- Delete `services/design_brief_anchors.py` (the 6 `DesignBrief`
  literals). Keep the module file empty or delete entirely.
- `services/design_brief_cache.py` no longer pre-primes on module
  load. Cache starts empty per-process. First encounter of any domain
  → LLM authors → result cached in-memory. Second encounter → cache
  hit.
- Persist the cache to disk (JSON) so cache survives restarts.
  Cache file: `backend/cache/design_briefs/{slug(domain)}.json`. LLM
  fires once per domain per environment, ever.
- Brief-author prompt drops the few-shot examples entirely. The
  brief schema + `BASE_ANTI_PATTERNS` + domain context from discovery
  are enough grounding. If they aren't, the LLM prompt is the fix,
  not more hand-authored examples.

**Why the cache is fine even without anchors**: cache is *storage*
of past LLM output for reuse. It's not decision-making. Adding a new
domain doesn't require a code change; the LLM handles it and the
cache remembers.

**Why the anchors were an anti-pattern**:
- Six enumerated domains — same "recipes per domain" shape.
- My guesses at Healthcare aesthetic constrain what the LLM produces
  for every Healthcare app.
- Cross-file drift: anchors + `BASE_ANTI_PATTERNS` + brief-author
  prompt all encode overlapping opinions; changes need to happen in
  three places.
- New domain support requires me to write a new anchor Python object;
  LLM already knows the domain.

**Files**:
- `backend/services/design_brief_anchors.py` — deleted (~200 lines gone)
- `backend/services/design_brief_cache.py` — drop pre-prime, add disk-persist (~40 lines change)
- `backend/services/design_brief_author.py` — drop few-shot examples from prompt (~30 lines removed)
- `backend/cache/design_briefs/.gitkeep` — new cache dir
- `backend/tests/services/test_design_brief_cache.py` — persistence test (~80 lines)

Net: **~110 lines added, ~230 lines removed**. Real cleanup.

## Files touched (estimated)

**New**
- `backend/services/brief_to_design_spec.py` (~150 lines)
- `backend/services/brief_from_figma.py` (~200 lines) — mandatory, no drift
- `backend/services/globals_writer.py` (~600 lines, extracted from design_agent Part B)
- `backend/tests/services/test_brief_to_design_spec.py` (~200 lines, 20+ cases)
- `backend/tests/services/test_brief_from_figma.py` (~300 lines — locked-field enforcement + byte-exact round-trip)
- `backend/tests/services/test_shell_templates_brief.py` (~150 lines)

**Modified**
- `backend/schemas/design_brief.py` — add `source`, `_locked_fields` (~60 lines)
- `backend/services/design_brief_editor.py` — enforce locks in `apply_patch` (~40 lines)
- `backend/services/smith_tools.py` — `edit_brief` returns `figma_locked` error (~30 lines)
- `frontend/src/components/chat/DesignBriefCard.tsx` — hide/lock tweak buttons on locked fields (~40 lines)
- `backend/agents/design_agent.py` → deleted after Slice 2 lands
- `backend/routers/generate.py` — 3 call sites replaced with figma-aware branch (~80 lines)
- `backend/services/shell_templates.py` — signature + palette reads (~80 lines)
- `backend/services/select_frame.py` — brief-aware frame picking (~30 lines)
- `packages/library/src/components/{Button,Input,Select,Checkbox,Textarea,Card,Badge}/*.tsx` — token reads (~40 lines each × 7 = ~280 lines)
- `packages/library/dist/*` — rebuild + re-vendor to `backend/templates/standalone-app/library`

**Deleted**
- `backend/agents/design_agent.py` (1030 lines)
- `backend/tests/agents/test_design_agent.py` (if exists)

**Total scope revision**: ~1.5 days (up from 1) — Slice 6 grew from a
follow-up hint into a mandatory extractor pipeline with lock enforcement
across brief editor, Smith tool, and frontend card.

## Rollout

1. Ship Slice 1 + 2 (extract, no behavior change) — merge behind flag off.
2. Ship Slice 3 (pipeline branch) — flag still off.
3. Ship Slice 4 + 5 (shell + library) — flag still off, no visual change with flag off.
4. Enable `FORGE_BRIEF_CANONICAL=1` on UAT. Eyeball 5 novel-domain apps.
5. If no regression in 1 week, delete `design_agent.py` and the legacy branch.
6. If regression, `FORGE_LEGACY_DESIGN_AGENT=1` restores instantly.

## Testing

- **Snapshot tests**: 10 pinned JSON brief fixtures spanning diverse
  domains (Slice 7 removes hand-authored anchors; fixtures are
  captured LLM output persisted as test data) → assert
  `brief_to_design_spec` output stable.
- **Golden-render tests**: render a sample form + dashboard against each
  fixture brief's tokens, snapshot the resulting CSS-var values (not
  pixels — reduces flake).
- **Live acceptance (non-Figma)**: rebuild property-mgmt app, verify
  `#2D5A8E` sidebar, `#E8A020` CTA, IBM Plex body, sharp 2px inputs.
- **Figma round-trip (CI gate)**: 3 fixture Figma projects with known
  styles.json → run `brief_from_figma → brief_to_design_spec →
  globals_writer` → assert rendered `--color-brand-500` and `--font-body`
  values match the Figma source **byte-for-byte**. Any deviation fails
  the build.
- **Lock enforcement tests**: `design_brief_editor.apply_patch` with
  a locked-field patch returns error and does not mutate disk.
  Smith's `edit_brief` returns `figma_locked` shape.
- **Frontend lock rendering**: DesignBriefCard with a locked palette
  field shows the lock chip and disables the corresponding tweak
  button.

## Rollback

- Any regression: `FORGE_BRIEF_CANONICAL=0` (drops back to `design_agent`).
- If design_agent already deleted: `FORGE_LEGACY_DESIGN_AGENT=1` uses a
  frozen copy at `backend/agents/_legacy_design_agent.py` (kept 30 days
  post-canonical).

## Risks

- **Library primitive breakage**: changing `Button`/`Input` variants
  could regress non-brief apps that had shipped. Mitigated by
  `--color-brand-*` and `--radius-control` defaulting to the shadcn
  values when tokens absent.
- **Post-generation self-heal**: `smith` and `verify` passes may compute
  color/typography fixes assuming the design_agent shape. Audit
  `services/smith_tools.py` and `services/self_verify_pass.py` for
  `design-spec.json` reads.
- **Figma extractor completeness**: `figma_style_extractor` returns a
  palette but the mapping to brief fields (surface_bg vs surface_elevated,
  neutrals_base vs neutrals_tint) is heuristic. If Figma provides
  ambiguous style names, extractor picks something plausible but wrong.
  Mitigation: brief editor's `_locked_fields` lets a user unlock and
  correct a specific field without unlocking all of them (via a
  follow-up "unlock" flow, not in this spec).
- **Figma without design tokens**: some Figma files have no defined
  color/text styles — just raw hex/family per element. Extractor
  handles this by clustering repeated values, but the "brand" pick is
  frequency-based (most-used non-neutral) and can be wrong for accent-
  heavy designs. Mitigation: emit `--figma-palette-confidence: low`
  in the brief when the extractor's confidence is below threshold; UI
  surfaces a warning card.

## Non-negotiables

- **Zero Figma drift**: for any project with `figma_context` present,
  the rendered CSS `--color-brand-500`, `--font-body`, `--radius-*`
  values must match the Figma source byte-for-byte. This is a CI gate,
  not a hope — the round-trip test in Slice 6e must be a required
  check.
- **No LLM in the Figma design chain**: if a project has Figma source,
  no Anthropic call decides colors/typography/radius/spacing. Every
  value traces to a Figma node.
