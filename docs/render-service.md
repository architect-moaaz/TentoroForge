# Render Service & Fidelity Scoring

## Architecture

Three processes:

1. **render-scaffold** (Next.js, port 6503) — minimal app that renders any
   project's schemas via `/p/<projectId>/<page-route>`. Reads schemas from
   `output/<id>/src/schemas/` and tokens from
   `output/<id>/src/theme/tokens.custom.json`.

2. **render-service** (FastAPI + Playwright, port 6502) — drives Playwright
   at the scaffold and returns PNGs + a11y trees.

3. **vision-evaluator** (in-process Python lib, no separate service) — calls
   Claude vision with a fixed rubric, returns structured critique JSON.

## Running locally

```bash
# Terminal 1: scaffold
cd apps/render-scaffold && npm install --legacy-peer-deps && npm run dev

# Terminal 2: render-service
cd backend && python3 -m playwright install chromium  # one-time
cd backend && python3 -m services.render_service

# Terminal 3: backend (already integrated)
cd backend && python3 -m uvicorn main:app --port 6500 --reload

# Terminal 4: frontend
cd frontend && npm run dev -- -p 6501
```

## Endpoints

- `GET  http://localhost:6502/health` — render service liveness
- `POST http://localhost:6502/render` — render a single page (returns base64 PNG)
- `DELETE http://localhost:6502/cache` — invalidate cached renders

Backend debug endpoints (require ANTHROPIC_API_KEY):

- `POST /api/_debug/render-page/<short_id>?page_route=/x&viewport=desktop`
- `POST /api/_debug/score-page/<short_id>?page_route=/x&page_path=x/y&domain=hr&...`

## Editor UI

The schema editor's right panel has three sub-tabs:
- **Editor** — the existing visual / code editor
- **Preview** — fetches a screenshot from the render service
- **Score** — runs the vision evaluator + displays the structured critique

## Configuration

Environment variables (read by `backend/config.py`):

- `FIDELITY_RENDER_ENABLED` (default `true`) — gates the Preview tab + render endpoint
- `FIDELITY_SCORING_ENABLED` (default `true`) — gates the Score tab + score endpoint
- `RENDER_SERVICE_URL` (default `http://localhost:6502`)
- `RENDER_SCAFFOLD_URL` (default `http://localhost:6503`)
- `VISION_EVALUATOR_MODEL` (default `claude-sonnet-4-5-20250929`)

## Cost notes

Single-shot scoring: roughly $0.03–0.05 per page (one Claude vision call).
A 20-page project costs ~$0.60–$1.00 to fully score once.

## Troubleshooting

- **Preview shows "Render service unreachable"** — check that `python3 -m services.render_service` is running on port 6502.
- **Render returns 422 with "navigation failed"** — usually means the scaffold isn't running on port 6503, or the project's schema file doesn't exist.
- **Vision evaluator raises ValidationError** — the model's response didn't match the Pydantic schema. The evaluator already retries once; persistent failures usually indicate the prompt needs tuning.

## Phase 14 + 15 — Closed loop with reference grounding

The fidelity loop runs as a phase in the generation pipeline. Set
`FIDELITY_LOOP_ENABLED=true` and `REFERENCE_GROUNDING_ENABLED=true`, then
generate any project. Results land in `output/<id>/src/contracts/fidelity-log.json`.

### What runs at gen time

1. Schema agent prompt is augmented with up to 2 high-quality exemplars per
   `(domain, page_type)` cell, loaded from `backend/reference_pages/`.
2. After the seed phase, `FidelityLoopRunner` renders + scores every page.
3. Pages below pass get up to 3 patch iterations + 1 schema-agent fallback.
4. Soft-fail: pipeline always succeeds; failed pages flagged in the editor.

### Editor surface

- Page tree shows score pills next to every page name.
- Score tab opens with the gen-time critique pre-populated; "Re-score" button
  appends a new iter with `manual_run: true`.
- Iteration history with screenshot thumbnails per iter (in
  `output/<id>/.fidelity-history/`).

### Seeding the reference bank

```bash
cd backend
for D in general healthcare fintech hr; do
  for T in list detail form dashboard settings; do
    python -m scripts.seed_reference_bank --domain "$D" --page-type "$T" \
      --target-count 2 --max-attempts 8 --seeder-version v1
  done
done
```

Cost: roughly $20 one-time. Cells that don't reach target_count after
max_attempts will end up under-quota; the loader falls back to `general/`
exemplars at gen time.

### Observability

- `GET /api/_debug/fidelity-stats?since=2026-05-01` aggregates pass rates,
  patch acceptance rates, and cost distributions across recent generations.
- Each project's `fidelity-log.json` records which flags were active at gen
  time so quality differences are attributable.

### Cost shape

Per project (12-page typical): ~$1-2 with both flags on. Hard cap at $5
(`FIDELITY_LOOP_PROJECT_COST_CAP_USD`). Pages remaining when the cap fires
are marked `fidelity_skipped: budget_exhausted`.

### Re-seeding for a register

The reference bank can be seeded per (register, domain, page-type) cell:

```bash
cd backend
for D in general healthcare fintech hr; do
  for T in list detail form dashboard settings; do
    python -m scripts.seed_reference_bank \
      --register workday --domain "$D" --page-type "$T" \
      --target-count 2 --max-attempts 8 --seeder-version v1
  done
done
git add backend/reference_pages/workday/
git commit -m "feat(reference-bank): seed Workday-tier exemplars (v1)"
```

Cost: ~$20 one-time per register. Output: `backend/reference_pages/<register>/<domain>/<page_type>/exemplar_*.{json,meta.json,png}`.

When a project is generated for a domain that doesn't have register-specific
exemplars seeded, the reference_bank loader falls back through:
  register/general/page_type → default/domain/page_type → default/general/page_type → legacy paths
