# Resume after restart

Everything you need to pick up exactly where you left off.

## Quick start (one command)

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
./start-all.sh
```

That brings up all 4 services. Wait ~30 seconds for everything to settle, then open the view URLs below.

## What's running

| Port | Service | Process | Cwd |
|---|---|---|---|
| 6500 | Backend API | `python3 -m uvicorn main:app --port 6500 --host 0.0.0.0 --reload` | `backend/` |
| 6501 | Main frontend (editor) | `next dev -p 6501` | `frontend/` |
| 6502 | Render service (vision eval) | `python3 -m services.render_service` | `backend/` |
| 6503 | Render scaffold (schema preview) | `next dev -p 6503` | `apps/render-scaffold/` |

## URLs to view the work-in-progress

The test project from today's session is `genmetrics-1778439719` (a "team task tracker").

- **List view (most polished):** http://localhost:6503/p/genmetrics-1778439719/tasks/list
- Detail: http://localhost:6503/p/genmetrics-1778439719/tasks/detail
- Form:   http://localhost:6503/p/genmetrics-1778439719/tasks/form
- Users:  http://localhost:6503/p/genmetrics-1778439719/users/list

Other existing projects you can browse for comparison:
- http://localhost:6503/p/w9595ngp/leaverequests/list (pre-fixes baseline)
- http://localhost:6503/p/test-app/products/list

## Critical state (don't lose this)

| File | What it holds |
|---|---|
| `backend/.env` | `ANTHROPIC_API_KEY` — already gitignored. **Rotate the current key**, then put the new one here. |
| `output/genmetrics-1778439719/` | Today's generated project. Schemas, design-spec, fixtures-cache, all there. |
| `packages/{schema,renderer,library}/dist/` | Compiled output. Rebuilt by `tsc` if missing — see "If something feels stale" below. |

## What was changed in the platform today (high-level)

Permanent improvements that apply to all future generations:

**Reliability**
- `packages/schema/src/page.ts` — `NodeV2` switched to `z.discriminatedUnion` (fixes the OOM on Mark 2 schemas)
- `packages/schema/src/tokens.ts` + `nodes/*.ts` + `style-slot.ts` — schema validation loosened to match what the LLM actually emits
- `packages/renderer/src/runtime/{interpolate,dispatch}.tsx` — date + snake-case humanizer in Text, prefix-icon detection
- `packages/renderer/src/nodes/layout/{Grid,Stack,Row}.tsx` — gap tokens mapped to real Tailwind classes (was silently 0)
- `apps/render-scaffold/.../page.tsx` — production-style URL fallback (`/tasks/<id>` → detail page)
- `apps/render-scaffold/tailwind.config.ts` — library packages added to `content` (was missing → no compiled CSS for library classes)

**Generation pipeline**
- `backend/agents/planner.py` — added `run_planner_oneshot()` for headless generation (12s vs 4m 20s conversational planner)
- `backend/services/register_selector.py` — LLM-driven register classification (with rule-based fallback)
- `backend/services/fixtures/{llm_gen,cache,dispatcher}.py` — LLM-generated preview fixtures, cached per project
- `backend/routers/_debug_schema.py` — preview-data enrichment (FK joins with person aliases, semantic field aliases, stat aliases, metadata defaults)

**Visual polish (Tier S/M/L partial)**
- `apps/render-scaffold/tailwind.config.ts` — type scale tokens (`text-page-title`/section/card-title/body/caption/micro) + spacing rhythm tokens (`rhythm-tight`/`-comfortable`/`-loose`)
- `packages/library/src/icons/index.ts` — Lucide icon resolver + semantic inference (NEW file)
- `packages/library/src/components/{Hero,Card,MetricTile,Badge,Section,Button}/...` — converted to use new tokens + icons + WCAG-AA contrast

## If something feels stale after restart

If you make a code change and don't see it reflected:

```bash
# Rebuild the schema/renderer/library packages
cd packages/schema   && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
cd ../renderer       && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
cd ../library        && /Users/m/Work/code/poc/design2ui-forge-v3/node_modules/.bin/tsc
# Clear the scaffold's compiled CSS cache (forces Tailwind to re-scan)
rm -rf apps/render-scaffold/.next
# Restart scaffold
pkill -9 -f "next dev -p 6503"
# (then ./start-all.sh again)
```

The library's `tsc` reports pre-existing TS errors in `PersonCard`, `Tabs`, `resolveStyle` — those are unrelated to today's work; the affected components still emit valid JS.

## What's still pending (next session)

From the Tier S/M/L plan that's ~50% complete:

1. **Tier S**: Radius scale unification (Card uses `rounded-xl`, Buttons `rounded-md`, Badges `rounded-full` — pick one system), Heading component conversion to type-scale tokens.
2. **Tier L**: Icon prop on Button, primary/secondary CTA hierarchy in design-spec, progressive disclosure schema patterns, schema-prompt proximity training.
3. **Tier M**: Keyboard-nav audit, aria-labels on icon-only Button variants, semantic markup (`<dl>` for KeyValueList).
4. **Reference bank**: Seeder still needs prompt work — current attempts score 1-2/10. Without this, the fidelity loop has nothing to ground against.
5. **Schema-mode generation produces no seed.ts** — the seed-plan exists but the script wasn't compiled. Generated apps can't run with seeded data; user must signup manually.

## What's burned that you should rotate

You pasted an Anthropic API key in chat. It's in `backend/.env` now. **Rotate it at https://console.anthropic.com/settings/keys**, replace the value in `backend/.env`, and don't reuse the pasted one in any other system.
