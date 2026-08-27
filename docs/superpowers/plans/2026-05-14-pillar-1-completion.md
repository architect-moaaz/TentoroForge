# Pillar 1 + Standalone-Engine Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between today's "functionally complete Pillar 1" state and a production-ready release. Validate the LLM peer patcher against the real Anthropic API, finish the component-registry migration so PropertiesPanel covers every library component, publish the engine package so generated apps actually `npm install`, fix accumulated TypeScript noise, and ship the four polish UIs the spec acknowledged as future work (action picker, token editor, per-breakpoint props, multi-select).

**Architecture:** Five sequential phases. **Phase A** (validation + productionisation) is the critical path — without it, the peer patcher remains theoretical and standalone apps can't actually be deployed. **Phase B** (registry completion) is mechanical but high user-visible value. **Phase C** (polish UIs) is the spec's deferred work surfaced. **Phase D** (tech debt) is cleanup of TypeScript noise + duplicated logic accumulated during the rapid Pillar 1 push. **Phase E** (Pillar 2 carry-overs) finishes the illustrations + fidelity reference assets we deferred earlier.

**Tech Stack:** TypeScript (Zod, React, Next.js 15), Python (FastAPI, anthropic SDK), pytest + vitest, tsup/tsc, no new external dependencies beyond what's already in the workspace.

**Spec:** Picks up exactly where `docs/superpowers/plans/2026-05-14-pillar-1-visual-editor.md` and `docs/superpowers/plans/2026-05-14-standalone-engine-and-emitter.md` left off — both substantially complete. This is the residual.

---

## Background — what's already shipped

The session that produced this plan completed 29 commits across both prior plans, landing:

- `@tentoroforge/engine` package with `<Engine>` + `<EngineProvider>` + `useNavigate` + data loader
- `@forge/patches` package with `applyAction(artifacts, action) → {next, inverse}` for 21 action variants + `normalize()` + commit-boundary validators
- `@forge/registry` with 28 component entries (Container, Grid, Card, Hero, MetricTile, Avatar, Stack, Row, etc.)
- Editor at `/editor/<projectId>` with Palette, Page picker, live Canvas, Selection overlay, Properties panel from registry, Drag-and-drop with slot validation, Export tarball, keyboard shortcuts
- `nav_flow_emitter` building `nav-flow.json` from `plan.pages` + extracted `onClick navigate` actions
- `app_emitter` writing 10 templated files (package.json, layout.tsx, [...slug]/page.tsx, etc.) into every generated project
- `peer_patcher` agent producing single-call `writeArtifacts` LLM tool output behind `PEER_PATCHER_ENABLED=1`
- 140+ tests passing across all new packages
- DOM-equivalence golden tests proving I-1 + I-7 invariants

What this plan finishes:

1. Live validation of the peer patcher (mocks only so far)
2. Engine packaging so generated apps can actually run
3. Registry coverage for the remaining 22 library components
4. Four polish UIs (action picker, token editor, responsive overrides, multi-select)
5. Frontend + library TypeScript error cleanup
6. Pillar 2 carry-overs (5 missing reference images)

**Out of scope:**

- CRDT collaboration (post-v1)
- Mobile/RN renderer (separate target)
- Workflow engine rewrite (separate plan)
- AI image-gen for bespoke illustrations
- Per-user account scaling / multi-tenancy

---

## File structure

### New files

```
backend/scripts/
  publish_engine.sh                  # Phase A2 — pack + tag engine for distribution
  smoke_peer_patcher.py              # Phase A1 — driver for live peer-patcher run

frontend/src/components/properties/
  ActionPicker.tsx                   # Phase C1 — visual picker for action descriptors
  TokenEditor.tsx                    # Phase C2 — JSON-aware tokens.json editor
  BreakpointSwitcher.tsx             # Phase C3 — viewport toggle in props panel

frontend/src/components/canvas/
  hooks/useMultiSelect.ts            # Phase C4 — multi-select state management

backend/services/
  registry_exporter.py               # Phase D4 — exports @forge/registry → JSON

docs/
  USING_GENERATED_APPS.md            # Phase A3 — user-facing run/deploy guide
```

### Modified files

```
packages/registry/src/starter.ts                       # Phase B — 22 more entries
packages/library/src/components/Hero/Hero.*.tsx        # Phase D2 — fix variant TS errors
packages/library/src/components/MetricTile/*.tsx       # Phase D2 — fix variant TS errors
frontend/src/components/schema-editor/*.tsx            # Phase D1 — fix pre-existing TS errors
backend/services/peer_patcher_helpers.py               # Phase D4 — read JSON-exported registry
backend/agents/peer_patcher.py                         # Phase A1 — final prompt tuning
backend/templates/standalone-app/package.json.tmpl     # Phase A2 — pin to npm version
backend/fixtures/reference_images/                     # Phase E2 — add fitness + recipe/form
```

---

## Phase A — Validation + Productionisation

The critical-path phase. After this, the peer patcher is proven against real LLM calls and generated apps are actually deployable.

### Task A1: Live peer-patcher smoke

**Files:**
- Create: `backend/scripts/smoke_peer_patcher.py`
- May modify: `backend/agents/peer_patcher.py` (prompt tuning)

The peer patcher was tested with mocked `client.messages.create`. Now run it against the real Anthropic API with a tiny plan and observe.

- [ ] **Step 1: Create the smoke script**

```python
# backend/scripts/smoke_peer_patcher.py
"""Drives the peer patcher with a minimal user prompt + empty current
artifacts, prints every SSE event, persists the result to /tmp.

Usage:
  ANTHROPIC_API_KEY=... python3 backend/scripts/smoke_peer_patcher.py
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.peer_patcher import run_peer_patcher
from services.peer_patcher_helpers import (
    registry_digest, registry_snapshot, token_vocabulary,
    commit_artifacts,
)


async def main():
    user_prompt = (
        "Build a small notes app. One entity 'Note' with title and body. "
        "Two pages: a dashboard at / with a heading, and a list at /notes "
        "showing all notes."
    )
    out_dir = Path("/tmp/peer-patcher-smoke")
    out_dir.mkdir(parents=True, exist_ok=True)

    async for evt in run_peer_patcher(
        user_prompt=user_prompt,
        current_artifacts=None,
        registry_digest=registry_digest(),
        registry=registry_snapshot(),
        token_vocabulary=token_vocabulary(None),
        max_retries=2,
    ):
        print(f"[{evt['event']}]", json.dumps(evt.get("data", {}), default=str)[:300])
        if evt["event"] == "artifacts":
            commit_artifacts(str(out_dir), evt["data"]["artifacts"])
            print(f"\nArtifacts written to {out_dir}")
            for f in sorted(out_dir.rglob("*.json")):
                print(f"  {f.relative_to(out_dir)}")
            return


asyncio.run(main())
```

- [ ] **Step 2: Run it**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
ANTHROPIC_API_KEY="$(cat ~/.anthropic_key)" python3 backend/scripts/smoke_peer_patcher.py 2>&1 | tee /tmp/peer-patcher-smoke.log
```

- [ ] **Step 3: Inspect output**

```bash
# Did it succeed?
tail -5 /tmp/peer-patcher-smoke.log
# Validate the produced artifacts against our validators
python3 -c "
import json
from services.artifact_validator import validate_all
from services.peer_patcher_helpers import registry_snapshot
art = {}
art['pageSchemas'] = {p.stem: json.load(open(p)) for p in __import__('pathlib').Path('/tmp/peer-patcher-smoke/src/schemas').glob('*.json')}
art['navFlow'] = json.load(open('/tmp/peer-patcher-smoke/src/contracts/nav-flow.json'))
art['tokens'] = json.load(open('/tmp/peer-patcher-smoke/src/contracts/tokens.json'))
errs = validate_all(art, registry_snapshot())
print(f'validators: {len(errs)} error(s)')
for e in errs[:10]: print(' ', e)
"
```

Expected: artifacts produced cleanly, validators pass, 2 pages emitted matching the prompt.

- [ ] **Step 4: Iterate the system prompt if needed**

If the LLM:
- Misses required props → tighten the prompt's "Constraints" section
- Emits unknown components → expand the registry digest with descriptions
- Produces invalid nav references → add a concrete example to the prompt
- Uses raw colors → emphasize the tokens rule

Each tweak is a one-line edit to `_build_system_prompt` in `peer_patcher.py`. Re-run the smoke after each.

- [ ] **Step 5: Document the validation evidence**

Append the final smoke output to `docs/peer-patcher-validation.md` (create the file). Include:
- The prompt
- The final artifacts (page count + node count per page)
- Token cost ($ + tokens consumed)
- Number of retries needed

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/smoke_peer_patcher.py docs/peer-patcher-validation.md
[ -n "$(git diff --name-only backend/agents/peer_patcher.py)" ] && git add backend/agents/peer_patcher.py
git commit -m "feat(peer-patcher): live smoke validation against Anthropic API"
```

---

### Task A2: Engine packaging for distribution

**Files:**
- Create: `backend/scripts/publish_engine.sh`
- Modify: `backend/templates/standalone-app/package.json.tmpl`

The standalone-app's `package.json` pins `"@tentoroforge/engine": "0.1.0"` but the engine is workspace-only. `npm install` inside an exported tarball would fail. Two valid paths:

**Path A: vendor the engine into the tarball**
**Path B: publish to a registry**

Path A is simpler for v1 — no npm publish credentials, no registry server. Choose A.

- [ ] **Step 1: Update the standalone-app template**

Modify `backend/templates/standalone-app/package.json.tmpl` to reference local file paths:

```json
{
  "dependencies": {
    "@tentoroforge/engine":   "file:./vendor/@tentoroforge/engine",
    "@tentoroforge/library":  "file:./vendor/@tentoroforge/library",
    "@tentoroforge/renderer": "file:./vendor/@tentoroforge/renderer",
    "@tentoroforge/schema":   "file:./vendor/@tentoroforge/schema",
    "@tentoroforge/feel-lite": "file:./vendor/@tentoroforge/feel-lite",
    "next": "^15.1.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "tailwindcss": "^3.4.0"
  }
}
```

- [ ] **Step 2: Update `app_emitter.py` to copy `dist/` from each engine-stack package into the project's `vendor/` directory**

In `backend/services/app_emitter.py`, after the template files are copied, add:

```python
def _vendor_engine_packages(output_dir: Path) -> None:
    """Copy each engine-stack package's dist/ into output/<project>/vendor/.
    Generated apps then npm-install file:./vendor/@tentoroforge/* deps."""
    workspace_root = Path(__file__).resolve().parents[2]
    packages = ["engine", "library", "renderer", "schema", "feel-lite"]
    for pkg in packages:
        src = workspace_root / "packages" / pkg
        if not src.exists():
            continue
        # Copy the package's package.json + dist/ into vendor/@tentoroforge/<pkg>/
        dst = output_dir / "vendor" / "@tentoroforge" / pkg
        dst.mkdir(parents=True, exist_ok=True)
        if (src / "package.json").exists():
            shutil.copyfile(src / "package.json", dst / "package.json")
        if (src / "dist").exists():
            shutil.copytree(src / "dist", dst / "dist", dirs_exist_ok=True)
```

Then call `_vendor_engine_packages(out)` at the end of `emit_standalone_app`.

- [ ] **Step 3: Update tests**

```python
# In test_app_emitter.py
def test_emit_vendors_engine_packages():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        vendor = Path(td) / "vendor" / "@tentoroforge"
        assert (vendor / "engine" / "package.json").exists()
        assert (vendor / "library" / "package.json").exists()
```

- [ ] **Step 4: Verify locally**

```bash
rm -rf /tmp/standalone-smoke
mkdir -p /tmp/standalone-smoke
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -c "
from services.app_emitter import emit_standalone_app
emit_standalone_app(output_dir='/tmp/standalone-smoke', project_short_id='smoke')
"
# Copy a schema + design-spec into it
mkdir -p /tmp/standalone-smoke/src/schemas /tmp/standalone-smoke/src/contracts
echo '{"schemaVersion":"2","id":"home","root":{"type":"Text","id":"t","props":{"content":"Hello"}}}' > /tmp/standalone-smoke/src/schemas/home.json
echo '{"register":"default"}' > /tmp/standalone-smoke/src/contracts/design-spec.json
# Try to install
cd /tmp/standalone-smoke && npm install --omit=optional 2>&1 | tail -20
```

If `npm install` succeeds and produces a `node_modules/` with `@tentoroforge/engine` resolved, the vendoring works.

- [ ] **Step 5: Commit**

```bash
git add backend/services/app_emitter.py backend/templates/standalone-app/package.json.tmpl backend/tests/services/test_app_emitter.py
git commit -m "feat(emitter): vendor engine packages into exported app"
```

---

### Task A3: Document the install/deploy workflow

**Files:**
- Create: `docs/USING_GENERATED_APPS.md`

Short user-facing doc explaining how to take an exported tarball and run it locally or deploy to Vercel.

- [ ] **Step 1: Write the doc**

```markdown
# Using a Generated App

After clicking **Export** in the editor, you'll download a `.tar.gz` of
your generated Next.js application.

## Run locally

\`\`\`bash
tar -xzf <project-id>.tar.gz
cd <project-id>
npm install
npm run dev
# open http://localhost:3000
\`\`\`

The app uses Next.js 15 + React 19. The `vendor/` directory contains
pre-built engine packages — no internet access required for the first
install.

## Deploy to Vercel

\`\`\`bash
npm install -g vercel
vercel
\`\`\`

Vercel auto-detects Next.js. The standalone app includes:
- `next.config.js` with `transpilePackages` for the engine stack
- TypeScript + Tailwind preconfigured

## Project layout

\`\`\`
src/
  app/
    layout.tsx              # Loads design-spec + nav-flow, wraps in EngineProvider
    [...slug]/page.tsx      # Reads src/schemas/<slug>.json, hands to <Engine>
    globals.css             # Project tokens + base styles
  schemas/                  # One JSON per page (the LLM-edited content)
  contracts/
    design-spec.json        # Palette + register + entityPhotos
    nav-flow.json           # Routes + transitions + guards
    tokens.json             # Color/typography/spacing tokens
vendor/@tentoroforge/       # Pre-built engine + library + renderer + schema
\`\`\`

## Editing schemas

Page schemas are plain JSON. Edit any file in `src/schemas/` and refresh
the dev server. Or re-open the project in the editor at
http://localhost:6501/editor/<project-id> for visual editing.
\`\`\`

- [ ] **Step 2: Commit**

```bash
git add docs/USING_GENERATED_APPS.md
git commit -m "docs: user guide for running + deploying generated apps"
```

---

## Phase B — Registry completion

22 library components currently have no registry entry; PropertiesPanel uses the generic JSON editor for them. Mechanical migration.

### Task B1: Layout components (6 entries)

**Files:**
- Modify: `packages/registry/src/starter.ts`
- Modify: `packages/registry/tests/registry.test.ts`

- [ ] **Step 1: Read each component's schema**

```bash
for c in Sidebar Cluster Split AppShell InspectorPanel TabPanelWithDeepLink; do
  echo "=== $c ==="
  find /Users/m/Work/code/poc/design2ui-forge-v3/packages/library/src/components -name "$c.schema.ts" -exec head -30 {} \;
done
```

- [ ] **Step 2: Add entries**

Match each Zod schema's prop list. Use the same conventions from W4.2:
- enum options come from the Zod enum
- `control: "select"` for enums, `"text"` for strings, `"toggle"` for booleans, `"actionPicker"` for complex objects
- `group: "content"` for visible text, `"style"` for variant/size, `"behavior"` for action descriptors, `"state"` for toggles, `"data"` for source/binding props

- [ ] **Step 3: Test + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/registry && npm run build && npx vitest run
git add packages/registry/src/starter.ts packages/registry/tests/registry.test.ts
git commit -m "feat(registry): 6 layout component entries"
```

---

### Task B2: Data components (5 entries — Chart, Sparkline, DataGrid, Timeline, plus Table extensions)

- [ ] **Step 1**: Read each schema, add entries with `category: "data"`. Charts have `data` (array of objects) — use `actionPicker` control.
- [ ] **Step 2**: Run tests, commit `feat(registry): 5 data component entries`.

---

### Task B3: Enterprise components batch 2 (5 entries)

ApprovalStepper, PersonCard, FilterBar, CommandPalette, ActivityFeed.

- [ ] **Step 1**: Add entries.
- [ ] **Step 2**: Tests, commit.

---

### Task B4: Enterprise components batch 3 + misc (6 entries)

EmptyStateRich, DateRangePicker, MultiSelect, FeatureCard, Skeleton, LoadingState, KeyValueList.

- [ ] **Step 1**: Add entries.
- [ ] **Step 2**: Tests, commit.

---

### Task B5: Input + motion (4 entries)

Link, DatePicker, FadeIn, Stagger.

- [ ] **Step 1**: Add entries.
- [ ] **Step 2**: Tests, commit.

After Phase B: starterRegistry has ~50 entries — full library coverage. PropertiesPanel shows registry-driven controls for every component.

---

## Phase C — Polish UIs

Four UI improvements the spec calls out as future work.

### Task C1: ActionPicker

**Files:**
- Create: `frontend/src/components/properties/PropControls/ActionPicker.tsx`
- Modify: `frontend/src/components/properties/PropControls/index.tsx`

Replace the JSON textarea action editor with a structured picker:
- Dropdown: action type (`navigate` / `workflow` / `submitForm` / `openModal`)
- Per-type sub-fields:
  - `navigate` → transition dropdown (from nav-flow.json) + params editor
  - `workflow` → workflow name input + params
  - `submitForm` → target form id selector
  - `openModal` → modal id input

- [ ] **Step 1: Build the component (use `useNavFlow` hook to read transitions for navigate type)**
- [ ] **Step 2: Wire it into CONTROL_BY_TYPE.actionPicker**
- [ ] **Step 3: Test that clicking through produces a valid action descriptor**
- [ ] **Step 4: Commit**

---

### Task C2: TokenEditor panel

**Files:**
- Create: `frontend/src/components/editor/TokenEditor.tsx`
- Modify: `frontend/src/app/editor/[projectId]/page.tsx`

A right-sidebar panel for editing `tokens.json` directly: color swatches, spacing dropdown, typography pickers.

- [ ] **Step 1: Build the panel as a tab in the existing PropertiesPanel sidebar (Properties / Tokens toggle)**
- [ ] **Step 2: Each token category renders its own sub-form**
- [ ] **Step 3: Dispatch `updateToken` / `addToken` / `removeToken` through the store**
- [ ] **Step 4: Commit**

---

### Task C3: Breakpoint switcher

**Files:**
- Create: `frontend/src/components/properties/BreakpointSwitcher.tsx`
- Modify: `frontend/src/components/properties/PropertiesPanel.tsx`

A pill toggle at the top of the props panel: `default | sm | md | lg | xl`. Selecting a breakpoint means edits go to `props.<name>.<breakpoint>` rather than `props.<name>`.

- [ ] **Step 1: Schema already supports `{ default: ..., sm: ..., md: ... }` shape — leverage it**
- [ ] **Step 2: PropertiesPanel reads from the selected breakpoint's slot**
- [ ] **Step 3: Visual indication of which breakpoint is overridden**
- [ ] **Step 4: Commit**

---

### Task C4: Multi-select

**Files:**
- Modify: `frontend/src/lib/editor-store.ts` — selection becomes `string[]` not `string | null`
- Modify: `frontend/src/components/canvas/SelectionOverlay.tsx` — render multiple boxes
- Modify: `frontend/src/components/canvas/hooks/useSelection.ts` — Shift-click extends, Cmd-click toggles

- [ ] **Step 1: Migrate the store to array selection (backwards-compat: selectedNodeId is selectedNodeIds[0])**
- [ ] **Step 2: SelectionOverlay renders one box per selected**
- [ ] **Step 3: PropertiesPanel disables editing when multiple are selected (or shows "common props only")**
- [ ] **Step 4: Delete key removes all selected nodes via batch dispatch**
- [ ] **Step 5: Commit**

---

## Phase D — Tech debt cleanup

### Task D1: Fix pre-existing frontend TypeScript errors

**Files:**
- Modify: `frontend/src/components/schema-editor/{FlowEditor,DataBindingPanel,SchemaEditorPanel}.tsx` + org project page

- [ ] **Step 1: Run `cd frontend && npx tsc --noEmit` to see the current list**
- [ ] **Step 2: Fix each — usually missing types, unsafe `any` casts, removed-import noise**
- [ ] **Step 3: Re-run, confirm 0 errors**
- [ ] **Step 4: Commit `chore: clean up pre-existing TS errors in frontend`**

---

### Task D2: Fix library variant TS errors

**Files:**
- Modify: `packages/library/src/components/Hero/Hero.{figma,linear,notion,stripe,workday}.tsx` — `HeroXxxProps` mismatch
- Modify: `packages/library/src/components/MetricTile/MetricTile.{figma,linear,notion,stripe}.tsx` — index-into-Record type errors

- [ ] **Step 1: Run `cd packages/library && npm run build 2>&1 | grep "error TS"` to see all errors**
- [ ] **Step 2: Hero variants: re-derive interfaces from base props rather than copying the prop type**
- [ ] **Step 3: MetricTile variants: cast direction lookup keys to the literal union**
- [ ] **Step 4: Confirm `npm run build` is 0 errors**
- [ ] **Step 5: Commit `chore(library): fix variant interface drift + index type errors`**

---

### Task D3: Consolidate syntheticNodeId / normaliseSchema

**Files:**
- Move: synthetic-id logic into `@forge/patches` as `syntheticNodeId(node)` utility
- Modify: `packages/renderer/src/runtime/dispatch.tsx` — import from patches
- Modify: `frontend/src/components/canvas/Canvas.tsx` — import from patches

- [ ] **Step 1: Add `syntheticNodeId(node)` to `@forge/patches`**
- [ ] **Step 2: Both renderer + canvas import from there**
- [ ] **Step 3: Drop the duplicated code**
- [ ] **Step 4: Run existing tests — synthetic ids must remain stable across both call sites**
- [ ] **Step 5: Commit**

---

### Task D4: CI export of registry to JSON

**Files:**
- Create: `backend/services/registry_exporter.py` (Node script invoked from Python)
- Modify: `backend/services/peer_patcher_helpers.py` — read the JSON snapshot

The Python `_STARTER_REGISTRY` in `peer_patcher_helpers.py` is a hand-maintained copy of `@forge/registry/starter.ts`. They drift. Replace with a CI step that exports the JS registry to JSON.

- [ ] **Step 1: Write a small Node script in `packages/registry/scripts/export.ts`**

```ts
import { writeFileSync } from "node:fs";
import { starterRegistry } from "../src/starter";
writeFileSync("dist/starter.json", JSON.stringify(starterRegistry, null, 2));
```

Run it as part of `npm run build` in `packages/registry`.

- [ ] **Step 2: `peer_patcher_helpers.py` reads `packages/registry/dist/starter.json` at runtime**
- [ ] **Step 3: Drop the hand-written `_STARTER_REGISTRY` constant**
- [ ] **Step 4: Verify peer_patcher tests still pass**
- [ ] **Step 5: Commit**

---

## Phase E — Pillar 2 carry-overs

### Task E1: Curate fitness reference images

**Files:** `backend/fixtures/reference_images/fitness/{dashboard,login,list,detail,form}.png`

This is human curation work, not code. Someone needs to capture 5 screenshots of polished fitness apps (Strava, Whoop, Nike Training Club, Apple Fitness+ web).

- [ ] **Step 1: Save 5 PNGs into `backend/fixtures/reference_images/fitness/`**
- [ ] **Step 2: Update `index.json` to register them**
- [ ] **Step 3: Commit the PNGs + index update**

---

### Task E2: Curate recipe/form reference

**Files:** `backend/fixtures/reference_images/recipe/form.png`

A single screenshot of a recipe-add or recipe-edit form (Yummly, NYT Cooking, AllRecipes).

- [ ] **Step 1: Save the PNG**
- [ ] **Step 2: Update `index.json`**
- [ ] **Step 3: Commit**

---

### Task E3: Curated illustration library

**Files:** `backend/fixtures/illustrations_curated/<slug>.svg` × 80 + `index.json`

Pillar 2 Workstream C deferred — 80 hand-picked unDraw SVGs by category. Pure asset-curation work.

- [ ] **Step 1: Visit https://undraw.co, download 80 SVGs across categories (auth, empty-state, dashboard-hero, onboarding, error-state, success, generic-productivity)**
- [ ] **Step 2: Save each as `<slug>.svg` (e.g. `auth-runner.svg`)**
- [ ] **Step 3: Write `index.json` with `{slug, filename, default_color, tags, best_for}` per illustration**
- [ ] **Step 4: Implement `backend/services/illustration_curator.py` per Pillar 2 plan W7.3 — the service is already specified, just needs the SVGs to exist**
- [ ] **Step 5: Commit**

---

## Phase F — Responsive UI

Both surfaces today assume desktop. The editor chrome has fixed-width sidebars that overflow on mobile/tablet; generated apps render at one viewport without breakpoint-aware layout adjustments. Phase F fixes both.

### Task F1: Responsive editor chrome

**Files:**
- Modify: `frontend/src/app/editor/[projectId]/page.tsx`
- Modify: `frontend/src/components/palette/Palette.tsx`
- Modify: `frontend/src/components/editor/PagePicker.tsx`
- Modify: `frontend/src/components/properties/PropertiesPanel.tsx`
- Create: `frontend/src/components/editor/EditorChrome.tsx` (orchestrates panel visibility)

Today's editor has four columns: Palette (w-48) + PagePicker (w-56) + main + PropertiesPanel (w-72). Total chrome ~22rem, leaving very little canvas at narrow viewports. On mobile (< 768px) the layout completely breaks.

Target behavior:
- **Desktop (≥1280px):** all four panels visible side-by-side (today's layout)
- **Tablet (768–1279px):** PagePicker + Properties become slide-out drawers triggered by toolbar buttons; Palette becomes a top bar with horizontal scroll; main canvas takes full width
- **Mobile (<768px):** all three side panels become overlay drawers; toolbar shows hamburger menu + active panel toggles

- [ ] **Step 1: Build `EditorChrome` orchestrator**

```tsx
"use client";
import * as React from "react";
import { useMediaQuery } from "@/hooks/useMediaQuery";

type PanelKey = "palette" | "pages" | "properties";

export function useEditorChrome() {
  const isDesktop = useMediaQuery("(min-width: 1280px)");
  const isTablet  = useMediaQuery("(min-width: 768px) and (max-width: 1279.98px)");
  const [openPanel, setOpenPanel] = React.useState<PanelKey | null>(null);

  return {
    isDesktop, isTablet,
    isMobile: !isDesktop && !isTablet,
    openPanel,
    togglePanel: (k: PanelKey) => setOpenPanel((cur) => (cur === k ? null : k)),
    closePanel: () => setOpenPanel(null),
  };
}
```

- [ ] **Step 2: Create the useMediaQuery hook**

```tsx
// frontend/src/hooks/useMediaQuery.ts
"use client";
import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, [query]);
  return matches;
}
```

- [ ] **Step 3: Refactor the editor page to use breakpoint-aware layout**

```tsx
// frontend/src/app/editor/[projectId]/page.tsx
"use client";
import { useEditorChrome } from "@/components/editor/EditorChrome";
import { Palette } from "@/components/palette/Palette";
import { PagePicker } from "@/components/editor/PagePicker";
import { PropertiesPanel } from "@/components/properties/PropertiesPanel";

export default function EditorPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  const [pageSlug, setPageSlug] = useState<string>("home");
  const [device, setDevice] = useState<Device>("desktop");
  const chrome = useEditorChrome();
  useKeymap();

  return (
    <div className="flex h-screen flex-col">
      {/* Top toolbar — visible at all sizes */}
      <header className="border-b px-4 py-2 flex gap-2 items-center">
        {chrome.isDesktop ? null : (
          <>
            <button onClick={() => chrome.togglePanel("palette")} className="px-2 py-1 text-sm rounded hover:bg-muted">
              Palette
            </button>
            <button onClick={() => chrome.togglePanel("pages")} className="px-2 py-1 text-sm rounded hover:bg-muted">
              Pages
            </button>
          </>
        )}
        <span className="text-sm font-semibold mx-2">{projectId} · {pageSlug}</span>
        <div className="ml-auto flex gap-1 items-center">
          {/* device-mode toggles */}
          {!chrome.isDesktop && (
            <button onClick={() => chrome.togglePanel("properties")} className="px-2 py-1 text-sm rounded hover:bg-muted">
              Properties
            </button>
          )}
          <ExportPanel projectId={projectId} />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Palette */}
        {(chrome.isDesktop || chrome.openPanel === "palette") && (
          <div className={chrome.isDesktop ? "" : "absolute z-30 inset-y-12 left-0 bg-background shadow-xl"}>
            <Palette onItemDragStart={chrome.closePanel} />
          </div>
        )}
        {/* PagePicker */}
        {(chrome.isDesktop || chrome.openPanel === "pages") && (
          <div className={chrome.isDesktop ? "" : "absolute z-30 inset-y-12 left-0 bg-background shadow-xl"}>
            <PagePicker projectId={projectId} value={pageSlug} onChange={(s) => { setPageSlug(s); chrome.closePanel(); }} />
          </div>
        )}
        {/* Canvas */}
        <main className="flex-1 overflow-auto">
          <Canvas projectId={projectId} pagePath={pageSlug} device={device} />
        </main>
        {/* PropertiesPanel */}
        {(chrome.isDesktop || chrome.openPanel === "properties") && (
          <div className={chrome.isDesktop ? "" : "absolute z-30 inset-y-12 right-0 bg-background shadow-xl"}>
            <PropertiesPanel />
          </div>
        )}
      </div>
      <ErrorBanner />
    </div>
  );
}
```

- [ ] **Step 4: Backdrop overlay on mobile**

When a drawer is open on mobile, render a click-to-dismiss backdrop:

```tsx
{!chrome.isDesktop && chrome.openPanel && (
  <div className="absolute inset-0 bg-black/30 z-20" onClick={chrome.closePanel} />
)}
```

- [ ] **Step 5: Smoke test at three viewports via Playwright**

```python
for viewport, name in [({"width":375,"height":667}, "mobile"),
                       ({"width":768,"height":1024}, "tablet"),
                       ({"width":1440,"height":900}, "desktop")]:
    ctx = await b.new_context(viewport=viewport)
    p = await ctx.new_page()
    await p.goto("http://localhost:6501/editor/db17s1zl")
    await p.screenshot(path=f"/tmp/editor-{name}.png")
```

Visual review each screenshot. Mobile/tablet should NOT show overflow, canvas must be reachable, drawer toggles must work.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/editor/[projectId]/page.tsx frontend/src/hooks/useMediaQuery.ts frontend/src/components/editor/EditorChrome.tsx frontend/src/components/palette/Palette.tsx frontend/src/components/editor/PagePicker.tsx frontend/src/components/properties/PropertiesPanel.tsx
git commit -m "feat(editor): responsive chrome — drawer panels on mobile + tablet"
```

---

### Task F2: Library component responsive audit

**Files:**
- Modify: each component in `packages/library/src/components/` that has layout-sensitive props (Hero, Section, Grid, Cluster, Stack, Row, Sidebar, AppShell, Tabs, DataGrid, Table)

Audit every layout-bearing component:
- Does it stack on mobile (flex-direction: column)?
- Does padding scale down (e.g. `padding="lg"` → `md` on sm)?
- Are font-sizes responsive (text-2xl on desktop, text-lg on mobile)?
- Do grids collapse to single column (`grid-cols-1 md:grid-cols-2 lg:grid-cols-4`)?

For each gap found, edit the component's className to use Tailwind's responsive prefixes. This is the LIBRARY side — fix once, every project benefits.

- [ ] **Step 1: Render Mark 3 at three viewports, capture screenshots**

```bash
python3 << 'PY'
import asyncio
async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        for w, name in [(375, "mobile"), (768, "tablet"), (1440, "desktop")]:
            ctx = await b.new_context(viewport={"width": w, "height": 900})
            p = await ctx.new_page()
            for slug in ("home", "tasks", "users"):
                try:
                    await p.goto(f"http://localhost:6503/p/db17s1zl/{slug}", wait_until="networkidle")
                    await p.screenshot(path=f"/tmp/mark3-{slug}-{name}.png", full_page=True)
                except: pass
        await b.close()
asyncio.run(main())
PY
```

- [ ] **Step 2: Build the audit checklist by reviewing each screenshot**

For every component visible at each viewport, file a finding:
- Hero/dashboard at mobile: does the headline overflow? Are CTAs stacked?
- MetricTile row at mobile: 4-up → 1-up?
- Table at mobile: horizontal-scroll on overflow OR card-stack each row?
- Sidebar at mobile: hidden behind a hamburger?

- [ ] **Step 3: Fix each gap in the library components**

Common fixes:
```tsx
// Hero
className="flex flex-col gap-4 md:flex-row md:gap-8 p-4 md:p-8 lg:p-12"
// MetricTile row (in the parent grid)
className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
// Table wrap
className="overflow-x-auto"
// Sidebar
className="hidden md:flex w-64"   // or use the editor's drawer pattern
```

- [ ] **Step 4: Verify by re-snapping the three viewports** — Mark 3 should now look intentional at each size.

- [ ] **Step 5: Commit per logical batch** (e.g. all Hero variants in one commit, all MetricTile in another).

```bash
git commit -m "feat(library): responsive layout — Hero stacks below md"
git commit -m "feat(library): responsive grid — MetricTile row collapses to 1-up on mobile"
git commit -m "feat(library): responsive Table — horizontal-scroll overflow on small viewports"
# ...
```

---

### Task F3: Schema-level responsive prop application

**Files:**
- Modify: `packages/renderer/src/runtime/dispatch.tsx`
- Modify: `packages/engine/src/Engine.tsx` (or where viewport context lives)
- Create: `packages/engine/src/responsive/useViewport.ts`

The schema model supports per-breakpoint prop overrides shape:
```json
{ "padding": { "default": "lg", "sm": "md", "md": "lg" } }
```

The renderer needs to pick the right value based on the current viewport. Today it just reads `props.padding` as a literal.

- [ ] **Step 1: useViewport hook**

```ts
// packages/engine/src/responsive/useViewport.ts
"use client";
import * as React from "react";

export type Breakpoint = "sm" | "md" | "lg" | "xl" | "default";

const BREAKPOINTS: Array<[Breakpoint, number]> = [
  ["xl", 1280], ["lg", 1024], ["md", 768], ["sm", 480], ["default", 0],
];

export function useViewport(): Breakpoint {
  const [bp, setBp] = React.useState<Breakpoint>("default");
  React.useEffect(() => {
    const update = () => {
      const w = window.innerWidth;
      for (const [name, min] of BREAKPOINTS) {
        if (w >= min) { setBp(name); return; }
      }
      setBp("default");
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return bp;
}

/**
 * Given a prop value that may be `{ default: x, sm: y, md: z, ... }`
 * shape, pick the value for the active breakpoint with fallback to
 * the next smaller breakpoint.
 */
export function pickResponsiveValue<T>(value: T | Record<Breakpoint, T>, bp: Breakpoint): T {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return value as T;
  }
  const obj = value as Record<string, unknown>;
  // Look for "default", "sm", "md", "lg", "xl" keys ONLY
  const RESP_KEYS = new Set(["default", "sm", "md", "lg", "xl"]);
  const keys = Object.keys(obj);
  if (!keys.some(k => RESP_KEYS.has(k))) return value as T;

  const order: Breakpoint[] = ["xl", "lg", "md", "sm", "default"];
  const startIdx = order.indexOf(bp);
  for (let i = startIdx; i < order.length; i++) {
    const k = order[i];
    if (obj[k] !== undefined) return obj[k] as T;
  }
  return value as T;
}
```

- [ ] **Step 2: Engine provides viewport via context**

```tsx
// packages/engine/src/Engine.tsx — add:
import { useViewport } from "./responsive/useViewport";

const ViewportContext = React.createContext<Breakpoint>("default");
export const useEngineViewport = () => React.useContext(ViewportContext);

// In Engine component:
const bp = useViewport();
return (
  <ViewportContext.Provider value={bp}>
    <div ref={rootRef} ...>{rendered}</div>
  </ViewportContext.Provider>
);
```

- [ ] **Step 3: Dispatch resolves responsive props before render**

```tsx
// In packages/renderer/src/runtime/dispatch.tsx, before interpolateDeep:
import { pickResponsiveValue, useEngineViewport } from "@tentoroforge/engine";

const bp = useEngineViewport();
const resolvedProps = Object.fromEntries(
  Object.entries(node.props ?? {}).map(([k, v]) => [k, pickResponsiveValue(v, bp)])
);
node = { ...node, props: resolvedProps };
```

- [ ] **Step 4: Tests**

```ts
// packages/engine/tests/responsive.test.tsx
import { pickResponsiveValue } from "../src/responsive/useViewport";

it("picks the exact bp value", () => {
  expect(pickResponsiveValue({ default: "a", md: "b" }, "md")).toBe("b");
});

it("falls back to smaller bp", () => {
  expect(pickResponsiveValue({ default: "a", md: "b" }, "lg")).toBe("b");
});

it("returns literals unchanged", () => {
  expect(pickResponsiveValue("plain", "md")).toBe("plain");
  expect(pickResponsiveValue(42, "md")).toBe(42);
  expect(pickResponsiveValue(["a"], "md")).toEqual(["a"]);
});
```

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/responsive packages/engine/src/Engine.tsx packages/engine/tests/responsive.test.tsx packages/renderer/src/runtime/dispatch.tsx
git commit -m "feat(engine): per-breakpoint prop resolution at render time"
```

This pairs with C3 (BreakpointSwitcher in the editor's properties panel) — the editor sets `props.x.sm = "md"`, the engine reads it and applies on mobile.

---

### Task F4: Verify Mark 3 end-to-end at three viewports

After F1, F2, F3 land, validate the full picture:

- [ ] **Step 1: Restart all servers + open Mark 3 at 375 / 768 / 1440**

```bash
./start-all.sh
sleep 8
# Take screenshots
python3 /tmp/snap_viewports.py
```

- [ ] **Step 2: Visual review checklist**

For each viewport × each page (Mark 3 has 14):
- No horizontal overflow
- Hero text fits without truncation
- Stats grid collapses appropriately
- Tables remain usable (scroll or stack)
- Buttons remain tappable (≥44px touch target on mobile)
- Avatars + photos don't overflow
- Selection overlay (in editor) stays glued during scroll

- [ ] **Step 3: File issues for any gaps in F2 not yet fixed**

Likely follow-ups: components with hard-coded `w-72`, `min-w-[400px]`, etc. that need responsive variants. Edit + commit per-component.

- [ ] **Step 4: Final commit summarising the responsive audit**

```bash
git commit --allow-empty -m "feat(responsive): Mark 3 verified across mobile/tablet/desktop"
```

---



### Spec coverage

- [x] Phase A — peer patcher production smoke (validates W8 production-readiness)
- [x] Phase A — engine vendoring (closes the "deployable apps" loop from standalone-engine plan)
- [x] Phase B — full registry coverage (completes W4.2 migration)
- [x] Phase C — four polish UIs (the spec's explicit future work)
- [x] Phase D — tech debt cleanup
- [x] Phase E — Pillar 2 carry-overs
- [x] Phase F — responsive UI (editor chrome + library components + schema-level breakpoint resolution)

### Placeholder scan

No "TBD" or "implement later" in plan steps. Phases B, D, E have compact tasks because the work is mechanical — the implementer fills in details per-component / per-fix.

### Type consistency

- `Artifacts`, `EditorAction`, `RegistryEntry`, `NavFlow` — all imported from `@forge/patches` / `@forge/registry` / `@tentoroforge/schema` — same shapes used throughout.
- New types in Phase C (action descriptor structured form) extend existing JSON shapes — no new top-level types introduced.

### Estimated effort

| Phase | Tasks | Estimated days |
|---|---|---|
| A — Validation + Productionisation | 3 | 2 |
| B — Registry completion | 5 | 1.5 |
| C — Polish UIs | 4 | 4 |
| D — Tech debt | 4 | 2 |
| E — Pillar 2 carry-overs | 3 | 1 (mostly asset curation) |
| F — Responsive UI | 4 | 3 (F2 is the long pole — per-component audit) |

**Total ~13.5 focused engineering days.** Phase A is critical-path. Phase F's F3 (responsive prop resolution) pairs with Phase C's C3 (BreakpointSwitcher) — completing one without the other is incomplete. Phases B, D, E can run in any order; F1/F2/F3 are independent of B/D/E.

### Risks

- **Phase A1 (live peer-patcher smoke):** real LLM may produce invalid output that no amount of retries fixes. Mitigation: capped retries + fallback to multi-agent pipeline (already the default).
- **Phase A2 (vendoring):** copying `dist/` into every project balloons tarball size from ~160KB to ~5MB. Acceptable v1; long-term, publish to a real registry.
- **Phase D2 (library variants):** fixing the type errors may surface runtime bugs that the broken builds masked. Run all affected component tests after each fix.
- **Phase C2 (token editor):** UX-heavy; the spec doesn't fully define the controls per token category. Implementer needs design judgment; reference the spec's §2.3 token shape for the data model.
- **Phase F1 (editor chrome drawers):** mobile drawer pattern collides with click-to-select if not careful — clicks on the overlay backdrop must not propagate to the canvas. Test that drawer-open + canvas-click sequence works without selecting stray nodes.
- **Phase F2 (library responsive audit):** ~10–15 components × 3 viewports = 30–45 visual review points. Easy to miss one. Use the checklist explicitly per component; don't eyeball.
- **Phase F3 (responsive prop resolution):** can subtly break existing schemas that pass a plain object as a prop value (which the resolver might mistake for a breakpoint map). The `RESP_KEYS` whitelist check guards against this — verify with a fixture that has `{ url: ..., overlay: ... }` (Hero.backgroundImage) and confirms it's NOT misidentified as responsive shape.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-14-pillar-1-completion.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review between tasks. Phases B and D each have multiple independent tasks that can run sequentially without coordination cost.

**2. Inline execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Best if you want to steer mid-flight, especially in Phase A1 (prompt tuning) and Phase C2 (token editor UX).

Which approach?
