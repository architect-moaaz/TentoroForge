# UI/UX Pro Max — vendored knowledge base

Source: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
License: MIT (see `LICENSE` in this directory).
Vendored on 2026-08-11 from `nextlevelbuilder/ui-ux-pro-max-skill` at HEAD.

## Contents

- `skill-content.md` — the top-level skill instruction template. Consumed by
  `services/design_knowledge.py` and injected into the design agent's system
  prompt when `FORGE_UI_UX_PRO_MAX=on`.
- `data/styles.csv` — 84 UI styles with keywords, palettes, effects, best-for
  cohorts, WCAG, framework compat, AI prompt keywords, CSS keywords.
- `data/colors.csv` — 192 palettes indexed by product type (SaaS, E-commerce,
  Luxury, B2B, Wellness, Fintech, etc.) with full token slots.
- `data/typography.csv` — 74 font pairings with Google Fonts URLs + Tailwind
  configs + mood/style keywords + best-for domains.
- `data/ui-reasoning.csv` — decision rules per product type: recommended
  pattern, style priority, color mood, typography mood, key effects,
  anti-patterns.
- `data/ux-guidelines.csv` — 98 UX guidelines.
- `data/motion.csv` — motion vocabulary reference.
- `data/products.csv` — product-type taxonomy with best-fit style/color/type.

## How this is used today

**As a runtime hygiene layer** — `services/design_knowledge.py::compose_prompt`
extracts the top-relevant rows for the brief's domain and injects a compact
reference block (~3-5KB) into the design agent's system prompt. Gated behind
`FORGE_UI_UX_PRO_MAX` env var. Off by default; opt in per run.

**As designer research fuel** — the CSVs are also symlinked at
`docs/design/reference/ui-ux-pro-max-data` for the register-catalog designer
to browse when authoring the 8 hand-designed registers. Their curated palette
+ typography + style knowledge is the largest research input to the register
catalog work (`docs/superpowers/plans/2026-08-11-register-catalog.md`).

## Boundaries — what this vendor is NOT

- Not a replacement for the register catalog. The CSVs are reference data;
  the LLM still authors CSS. The register catalog turns register-picking
  into executable, deterministic CSS emission.
- Not the source of truth for our design system. Our design brief + register
  catalog stay authoritative; this is prompt-time reference.
- Not automatically updated. If the upstream repo evolves, re-vendor by
  running the bootstrap in the ATTRIBUTION comment. We pin to a snapshot
  intentionally so upstream changes never silently affect generations.
