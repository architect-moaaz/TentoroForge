# Authoring guide — aesthetic profile

**Files:** `backend/design/aesthetic_profiles/<name>.json` + a matching entry in `aesthetic_profile_picker.py` tie-break order (if you want it selected before its alphabetical neighbours).
**Read first:** existing profiles (glass-dark, carbon, polaris, material-3, fluent-2, clean-editorial) — they are the vocabulary you are extending.

An aesthetic profile is a **CSS-scope bundle** — tokens + CSS variables + a `surface_treatment` block, keyed by `.aesthetic-<name>` in the generated app's global stylesheet. When the picker selects your profile, the app's `<body>` gets `class="aesthetic-<name>"` and the standard shadcn/library components take on your look via existing `className` slots. No new component TS is needed.

## When to add one

The gap review promoted a repeated visual identity or mood the existing six profiles can't express well — e.g. "glass-dark" is right for consumer-utility but wrong for a heavy government form; "clean-editorial" is right for content but wrong for a real-time trader dashboard.

Do NOT add a profile just because you personally prefer a different accent hue. Every profile costs planner and critic attention; six is a considered floor.

## Anatomy

```json
{
  "name": "kebab-case-name",
  "gloss": "One sentence — the mood and where it belongs.",
  "when_to_use": {
    "identity.usageMode": ["returning-personal", ...],
    "layout.hero": ["kpi-strip", ...],
    "layout.density": ["compact"],
    "layout.shell": ["sidebar"],
    "layout.primaryInteraction": ["dashboard"],
    "industry": ["finance-personal", "workspace-analytics"]
  },
  "tokens": {
    "color": {"background": "#...", "foreground": "#...", "primary": "#...", "accent": "#...", "muted": "#...", "border": "#..."},
    "typography": {"display": "'Font', system-ui, ...", "body": "'Font', ...", "mono": "'Font', ..."},
    "radius": {"sm": "4px", "md": "8px", "lg": "12px"},
    "shadow": {"sm": "...", "md": "...", "lg": "..."}
  },
  "css_variables": {
    "--aesthetic-surface": "...",
    "--aesthetic-surface-elevated": "...",
    "--aesthetic-ring": "..."
  },
  "surface_treatment": {
    "card": {"className": "shadow-md rounded-xl border-2"},
    "button_primary": {"className": "font-semibold tracking-wide"},
    "heading_h1": {"className": "font-display tracking-tighter"}
  }
}
```

## `when_to_use` — the scoring surface

The picker awards one point per matched value across the listed dimensions, then breaks ties in a fixed order. Broaden `when_to_use` to become the default for a shape family; narrow it to reserve the profile for niche apps.

Any dimension you omit is treated as "wildcard, no bonus" — matches don't add points and misses don't subtract. Do NOT list every enum value; list the ones you actually want to *win* for.

## Tie-break order

Update `TIE_BREAK_ORDER` in `backend/services/aesthetic_profile_picker.py` so your profile has a defined slot. Insert it where it *should* win among equally-scoring profiles. Not doing this leaves your profile losing every tie to the older bundles.

## `surface_treatment`

Additive className hints layered onto the LLM-authored schema during the post-gen `surface_treatment_pass`. Keep them:
- **Idempotent** — the pass must be safe to re-run.
- **Profile-swap safe** — remove old-profile hints before writing new ones (the pass does this by pattern, so make your classNames identifiable).
- **Small** — 1–3 classes per slot. Don't restyle the world here; that's what `.aesthetic-<name>` CSS in `globals.css` is for.

## After adding

1. `pytest backend/tests/services/test_irf_m6_batch.py` — the profile-count and picker tests should pass without edits.
2. Regen a canonical app under conditions your `when_to_use` targets and eyeball the result.
3. Add a snapshot fixture if this profile should anchor a specific canonical app.
