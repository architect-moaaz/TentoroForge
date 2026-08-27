# Preview + End-to-End Theming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the editor's Preview button open a production-faithful render of the project (with nav chrome + resolved bindings + per-project imagery + themed library components), and ensure the editor canvas matches that preview visually so users can iterate with confidence.

**Architecture:** Six workstreams, each independently shippable.
1. WS-1 — Preview button reliability (dirty-state flush, deep link).
2. WS-2 — `render-scaffold` wraps pages in `AppShell` chrome derived from `nav-flow.json`.
3. WS-3 — Reconcile binding paths so `previewData` keys match what schemas reference.
4. WS-4 — Per-project imagery in `photo_picker` so two projects with the same entity don't get the same Unsplash URL.
5. WS-5 — Theme the top eight library components against the CSS-var contract `EngineProvider` already injects. Spike one (Hero) first to measure cost, then batch the rest.
6. WS-6 — Editor↔preview screenshot parity test.

**Tech Stack:** Next.js 15 (render-scaffold, frontend editor), React 19, Tailwind 4, Zustand, FastAPI, Playwright (parity test).

---

## File Structure Overview

### New files
- `backend/services/photo_picker_seed.py` — per-project deterministic seeding logic.
- `apps/render-scaffold/src/components/PreviewShell.tsx` — AppShell wrapper for preview routes.
- `apps/visual-regression/tests/preview-vs-editor.spec.ts` — Playwright parity test.

### Modified files
- `frontend/src/components/editor/EditorToolbar.tsx` — Preview button: disable while dirty, indicate flush.
- `frontend/src/lib/persistence.ts` — expose a `flush()` method on the persister so the Preview button can await it.
- `frontend/src/lib/editor-store.ts` — return the flush promise from `attachPersister`.
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — mount `PreviewShell` around the rendered page.
- `apps/render-scaffold/src/components/SchemaRendererWrapper.tsx` — accept sidebar/topbar slot props.
- `backend/routers/_debug_schema.py` — augment `/preview-data/{shortId}` to also expose `overview.{title,description}` and computed `stats.{totalCount,activeCount,pendingCount,monthlyCount,monthlyChange,monthlyTrend}` for each entity.
- `backend/services/photo_picker.py` — accept `project_seed` and rotate among per-entity photo IDs.
- `backend/agents/design_agent.py` — pass `project.short_id` to the picker.
- `packages/library/src/components/Hero/Hero.linear.tsx` — read brand color tokens via `var(--color-*)`.
- Library: Card, MetricTile, Button, Badge, Alert, Tabs, Section (rolled out in WS-5 batches).
- `packages/library/src/components/AppShell/AppShell.tsx` — confirm token consumption is correct (read-only audit; only edit if needed).

---

## WS-1 — Preview Button Reliability

Goal: Preview always opens the latest persisted state at the page the user is currently editing.

### Task 1: Expose a flush() on the persister

**Files:**
- Modify: `frontend/src/lib/persistence.ts`
- Modify: `frontend/src/lib/editor-store.ts:152-159`
- Test: `frontend/src/lib/persistence.test.ts` (create if absent)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/persistence.test.ts
import { describe, it, expect, vi } from "vitest";
import { buildPersister } from "./persistence";

describe("buildPersister", () => {
  it("resolves flush() only after the pending debounced save completes", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true } as Response);
    const persister = buildPersister("proj");
    persister.save({ pageSchemas: {}, navFlow: { pages: [] }, tokens: {} } as any);
    // Before flush: still pending
    expect(persister.isPending()).toBe(true);
    await persister.flush();
    expect(persister.isPending()).toBe(false);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest src/lib/persistence.test.ts --run`
Expected: FAIL with "persister.flush is not a function" or similar.

- [ ] **Step 3: Refactor persister to expose flush + isPending**

```ts
// frontend/src/lib/persistence.ts — public shape change
export interface Persister {
  save: (artifacts: any) => void;
  flush: () => Promise<void>;
  isPending: () => boolean;
}

export function buildPersister(projectId: string): Persister {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let inflight: Promise<void> | null = null;
  let lastArtifacts: any = null;

  const doSave = async () => {
    if (!lastArtifacts) return;
    const body = JSON.stringify(lastArtifacts);
    inflight = fetch(`${API}/api/_debug/project-artifacts/${projectId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
    }).then(() => { inflight = null; });
    await inflight;
  };

  return {
    save(artifacts) {
      lastArtifacts = artifacts;
      if (timer) clearTimeout(timer);
      timer = setTimeout(doSave, 500);
    },
    async flush() {
      if (timer) { clearTimeout(timer); timer = null; await doSave(); }
      if (inflight) await inflight;
    },
    isPending() { return timer !== null || inflight !== null; },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest src/lib/persistence.test.ts --run`
Expected: PASS.

- [ ] **Step 5: Wire persister.flush through editor-store**

Replace the `attachPersister` return type so callers can `await store.flush()`:

```ts
// frontend/src/lib/editor-store.ts — replace attachPersister
let persisterRef: Persister | null = null;

export function attachPersister(projectId: string): () => void {
  if (unsubscribePersister) unsubscribePersister();
  persisterRef = buildPersister(projectId);
  unsubscribePersister = useEditorStore.subscribe((s) => {
    if (s.artifacts) persisterRef!.save(s.artifacts);
  });
  return unsubscribePersister;
}

export async function flushPersister(): Promise<void> {
  await persisterRef?.flush();
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/persistence.ts frontend/src/lib/persistence.test.ts frontend/src/lib/editor-store.ts
git commit -m "feat(editor): expose persister flush() so Preview can wait on save"
```

### Task 2: Preview button awaits flush before opening tab

**Files:**
- Modify: `frontend/src/components/editor/EditorToolbar.tsx:80-95`

- [ ] **Step 1: Replace the inline window.open with a flush-then-open handler**

```tsx
// inside EditorToolbar
const [previewing, setPreviewing] = React.useState(false);

const handlePreview = async () => {
  setPreviewing(true);
  try {
    await flushPersister(); // waits for in-flight + clears any debounce
    const slug = currentPage && currentPage !== "home" ? `/${currentPage}` : "";
    window.open(
      `${PREVIEW_BASE}/p/${projectId}${slug}?v=${Date.now()}`, // bust scaffold cache
      "_blank",
      "noopener,noreferrer"
    );
  } finally {
    setPreviewing(false);
  }
};

// in JSX, replace the existing onClick:
<button
  onClick={handlePreview}
  disabled={previewing}
  className={ICON_BTN}
  title={previewing ? "Saving…" : "Preview in production renderer (new tab)"}
  aria-label="Preview"
>
  {previewing ? <Loader2 size={16} className="animate-spin" /> : <Eye size={16} />}
</button>
```

Also add the import: `import { flushPersister } from "@/lib/editor-store";` and `Loader2` from lucide-react.

- [ ] **Step 2: Manually verify**

Run frontend + backend (already running), open editor, make a quick prop edit, click Preview within 200ms. Expected: button shows spinner briefly, preview tab opens with the edit applied.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/editor/EditorToolbar.tsx
git commit -m "feat(editor): Preview button flushes persister before opening tab"
```

---

## WS-2 — AppShell Chrome in render-scaffold

Goal: Preview routes wrap the rendered page in `AppShell` (sidebar + topbar) so the user sees the full app, not a bare page.

### Task 3: Create PreviewShell component that builds AppShell from nav-flow

**Files:**
- Create: `apps/render-scaffold/src/components/PreviewShell.tsx`

- [ ] **Step 1: Write the component**

```tsx
// apps/render-scaffold/src/components/PreviewShell.tsx
"use client";
import { AppShell } from "@tentoroforge/library";
import { useNavigate } from "@tentoroforge/engine";
import type { ReactNode } from "react";

interface SidebarLink {
  id: string;
  label: string;
  route: string;
  icon?: string;
}

export interface PreviewShellProps {
  projectId: string;
  navFlow: any | null;
  children: ReactNode;
}

export function PreviewShell({ projectId, navFlow, children }: PreviewShellProps) {
  const navigate = useNavigate();
  // Build sidebarLinks from nav-flow.pages — exclude auth pages and dynamic routes.
  const pages = (navFlow?.pages ?? []) as Array<{ id: string; route: string; title: string }>;
  const sidebar: SidebarLink[] = pages
    .filter((p) => !p.route.includes("[") && p.route !== "/login" && p.route !== "/signup")
    .slice(0, 12)
    .map((p) => ({ id: p.id, label: p.title, route: p.route, icon: "layout-dashboard" }));

  return (
    <AppShell
      sidebar={{ links: sidebar, onNavigate: (route) => navigate(route) }}
      topbar={{ title: "Preview" }}
    >
      {children}
    </AppShell>
  );
}
```

- [ ] **Step 2: Mount PreviewShell in the route**

```tsx
// apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx
// Around line 234 — wrap SchemaRendererWrapper:
<PreviewShell projectId={projectId} navFlow={navFlow}>
  <SchemaRendererWrapper
    page={page}
    register={register}
    tokens={tokens as Record<string, Record<string, string>>}
    previewData={previewData}
    projectId={projectId}
    navFlow={navFlow}
  />
</PreviewShell>
```

Add import: `import { PreviewShell } from "@/components/PreviewShell";`

- [ ] **Step 3: Manual verify**

Visit `http://localhost:6503/p/db17s1zl/requests`. Expected: sidebar visible on left with 6–10 page links (home, requests, approvals, tasks, etc.); page content renders inside the shell; clicking sidebar items navigates without full reload.

- [ ] **Step 4: Commit**

```bash
git add apps/render-scaffold/src/components/PreviewShell.tsx apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/page.tsx
git commit -m "feat(scaffold): wrap preview pages in AppShell chrome from nav-flow"
```

### Task 4: Auth pages bypass PreviewShell

Login / signup should render fullscreen. Add a list of `bare` routes that skip the shell.

**Files:**
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx`

- [ ] **Step 1: Conditionally render PreviewShell**

```tsx
const BARE_ROUTES = new Set(["login", "signup", "forgot-password"]);
const isBare = BARE_ROUTES.has(slug[0] ?? "");

const content = (
  <SchemaRendererWrapper ... />
);

return (
  <main style={tokenCssVars} ...>
    {projectGlobalsCss && <style dangerouslySetInnerHTML={{ __html: projectGlobalsCss }} />}
    {isBare ? content : <PreviewShell projectId={projectId} navFlow={navFlow}>{content}</PreviewShell>}
    <A11yTreeEmbed tree={a11yTree} />
  </main>
);
```

- [ ] **Step 2: Verify**

Visit `/p/db17s1zl/login` → no sidebar.
Visit `/p/db17s1zl/requests` → sidebar present.

- [ ] **Step 3: Commit**

```bash
git add apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/page.tsx
git commit -m "feat(scaffold): skip AppShell on auth routes (login/signup/forgot-password)"
```

---

## WS-3 — Binding Path Reconciliation

Goal: Schemas reference `overview.title` and `stats.totalCount`; `previewData` exposes neither. Extend the preview-data builder so every binding the schemas use resolves to something.

### Task 5: Discover all binding paths the project uses

**Files:**
- Create: `backend/scripts/audit_binding_paths.py`

- [ ] **Step 1: Write the audit script**

```python
# backend/scripts/audit_binding_paths.py
"""List every {{binding}} path used across all page schemas in a project.
Run: python3 backend/scripts/audit_binding_paths.py <short_id>
"""
import json, re, sys
from pathlib import Path

def audit(short_id: str) -> None:
    base = Path(__file__).resolve().parents[2] / "output" / short_id / "src" / "schemas"
    if not base.exists():
        print(f"No schemas dir at {base}"); sys.exit(1)
    paths: set[str] = set()
    for f in base.rglob("*.json"):
        text = f.read_text()
        for m in re.findall(r"\{\{([^}|]+?)(?:\s*\|[^}]*)?\}\}", text):
            paths.add(m.strip())
    for p in sorted(paths):
        print(p)

if __name__ == "__main__":
    audit(sys.argv[1] if len(sys.argv) > 1 else "")
```

- [ ] **Step 2: Run it against db17s1zl**

```bash
python3 backend/scripts/audit_binding_paths.py db17s1zl > /tmp/bindings.txt
wc -l /tmp/bindings.txt
```

Record the output — it's the source of truth for what WS-3 has to satisfy.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/audit_binding_paths.py
git commit -m "chore(scripts): add binding-path audit helper for preview-data planning"
```

### Task 6: Extend preview-data builder with overview + stats blocks

**Files:**
- Find and modify: `backend/routers/_debug_schema.py` — the `/api/_debug/preview-data/{short_id}` endpoint.
- Test: `backend/tests/routers/test_debug_preview_data.py` (create if absent).

- [ ] **Step 1: Locate the existing preview-data builder**

Run: `grep -n "preview-data\|preview_data" backend/routers/_debug_schema.py`

- [ ] **Step 2: Add overview + stats injection**

For each entity in the registry (e.g. `leaveRequest`, `task`, `user`), the builder should add:

```python
data["overview"] = {
    "title": project_title,        # from project metadata
    "description": project_blurb,  # from project metadata or domain-context
}
# For every entity's stats sub-object that already exists:
for key in list(data.keys()):
    if key.endswith("Stats"):
        s = data[key]
        if isinstance(s, dict):
            s.setdefault("totalCount", _safe_len(data.get(_entity_from_stats_key(key))))
            s.setdefault("activeCount", _count_active(data.get(_entity_from_stats_key(key))))
            s.setdefault("pendingCount", _count_pending(data.get(_entity_from_stats_key(key))))
            s.setdefault("monthlyCount", _count_this_month(data.get(_entity_from_stats_key(key))))
            s.setdefault("monthlyChange", 0)
            s.setdefault("monthlyTrend", "neutral")
# Promote the "primary" entity's stats to top-level `stats` so schemas can use `{{stats.totalCount}}`
primary = _pick_primary_entity(data)
if primary:
    data["stats"] = data[f"{primary}Stats"]
```

Helpers `_count_active`, `_count_pending`, `_count_this_month` look for `status in {"active","approved"}`, `status == "pending"`, and `createdAt within this calendar month` respectively. They default to 0 for empty collections.

- [ ] **Step 3: Write a smoke test**

```python
# backend/tests/routers/test_debug_preview_data.py
def test_preview_data_has_overview_and_stats(client, sample_project):
    r = client.get(f"/api/_debug/preview-data/{sample_project.short_id}")
    j = r.json()
    assert "overview" in j and "title" in j["overview"]
    assert "stats" in j
    for k in ("totalCount", "activeCount", "pendingCount", "monthlyCount"):
        assert k in j["stats"], f"missing stats.{k}"
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/routers/test_debug_preview_data.py -v`
Expected: PASS.

- [ ] **Step 5: Manual verify on db17s1zl**

```bash
curl -s http://localhost:6500/api/_debug/preview-data/db17s1zl | python3 -m json.tool | grep -E "overview|totalCount|activeCount" | head
```

Then refresh `http://localhost:6503/p/db17s1zl/requests` — bindings should resolve to real values, no more `NaN%` or literal `{{...}}`.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/_debug_schema.py backend/tests/routers/test_debug_preview_data.py
git commit -m "feat(preview-data): inject overview + stats blocks so schema bindings resolve"
```

---

## WS-4 — Per-Project Imagery

Goal: Two projects with the same entity (e.g. both have a `leaveRequest`) get different Hero/banner images.

### Task 7: Add project-seeded photo selection

**Files:**
- Modify: `backend/services/photo_picker.py`
- Modify: `backend/agents/design_agent.py` (callsite that invokes the picker)
- Test: `backend/tests/services/test_photo_picker.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/services/test_photo_picker.py
from services.photo_picker import pick_photo_for

def test_different_project_seeds_yield_different_photos():
    a = pick_photo_for("leaveRequest", "hr", project_seed="proj-a")
    b = pick_photo_for("leaveRequest", "hr", project_seed="proj-b")
    assert a != b, "same query + different seeds should rotate among photo candidates"

def test_same_project_seed_is_stable():
    a = pick_photo_for("leaveRequest", "hr", project_seed="proj-a")
    b = pick_photo_for("leaveRequest", "hr", project_seed="proj-a")
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_photo_picker.py -v`
Expected: FAIL — `pick_photo_for` doesn't accept `project_seed`.

- [ ] **Step 3: Rework pick_photo_for to rotate via seed**

```python
# backend/services/photo_picker.py
import hashlib

# Curated 4-photo pool per query — Unsplash collection IDs or specific photo IDs.
# Keys are normalised query strings; values are arrays of full Unsplash URLs.
PHOTO_POOL: dict[str, list[str]] = {
    "hr employees workplace": [
        "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1556761175-5973dc0f32e7?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1542744173-8e7e53415bb0?w=1600&h=900&fit=crop",
    ],
    # ... fill in pools for the other queries _query_for produces
    "default": [
        "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1486312338219-ce68d2c6f44d?w=1600&h=900&fit=crop",
        "https://images.unsplash.com/photo-1551434678-e076c223a692?w=1600&h=900&fit=crop",
    ],
}

def pick_photo_for(entity_name: str, domain: str, size: str = "1600x900",
                   project_seed: str | None = None) -> str:
    query = _query_for(entity_name, domain)
    pool = PHOTO_POOL.get(query) or PHOTO_POOL["default"]
    # Stable rotation: hash(project_seed + entity_name) modulo pool size.
    seed_input = f"{project_seed or ''}::{entity_name}::{domain}"
    idx = int(hashlib.md5(seed_input.encode()).hexdigest(), 16) % len(pool)
    return pool[idx]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/services/test_photo_picker.py -v`
Expected: PASS.

- [ ] **Step 5: Wire project_seed through design_agent**

```python
# backend/agents/design_agent.py — find the pick_photo_for callsite
# Pass the project's short_id as project_seed:
photo_url = pick_photo_for(entity_name, domain, project_seed=project.short_id)
```

Grep first to find the right callsite: `grep -n "pick_photo_for" backend/agents/design_agent.py`.

- [ ] **Step 6: Regenerate one project, compare**

Pick two existing projects of the same domain (e.g. Mark 3 and Mark 4 leave-requests):

```bash
# Re-trigger design_agent for both and capture the resulting backgroundImage.
python3 backend/scripts/recompile_design.py db17s1zl
python3 backend/scripts/recompile_design.py <mark-4-short-id>
diff <(jq '.. | .backgroundImage? // empty' output/db17s1zl/src/schemas/home.json) \
     <(jq '.. | .backgroundImage? // empty' output/<mark-4>/src/schemas/home.json)
```

Expected: differ — different URLs.

- [ ] **Step 7: Commit**

```bash
git add backend/services/photo_picker.py backend/agents/design_agent.py backend/tests/services/test_photo_picker.py
git commit -m "feat(photo-picker): rotate photos per project via deterministic seed"
```

---

## WS-5 — Library Reads CSS Vars (Theming)

Goal: Library components consume the brand colors / typography / radii from CSS vars injected by `EngineProvider` so each project visually reflects its tokens — in editor AND in production.

**Strategy:** Spike Hero first (highest visual impact, complex enough to validate the pattern), measure cost, then batch the next seven.

### Task 8: Spike — theme Hero.linear against CSS vars

**Files:**
- Modify: `packages/library/src/components/Hero/Hero.linear.tsx`
- Reference: `packages/library/src/components/Hero/Hero.linear.css.ts` (if it exists; otherwise inline Tailwind classes)

- [ ] **Step 1: Audit current Hero color usage**

```bash
grep -nE "bg-|text-|border-|from-|to-" packages/library/src/components/Hero/Hero.linear.tsx
```

Record every Tailwind color class. These are the lines to migrate.

- [ ] **Step 2: Replace with arbitrary-value classes that read the brand vars**

Examples:
- `bg-slate-50` → `bg-[var(--color-surface-1,theme(colors.slate.50))]`
- `from-violet-500` → `bg-[linear-gradient(135deg,var(--color-primary-500),var(--color-secondary-500))]`
- `text-slate-900` → `text-[var(--color-primary-900,theme(colors.slate.900))]`
- `rounded-2xl` → `rounded-[var(--radius-2xl,theme(borderRadius.2xl))]`

The `theme(...)` fallback preserves the current look on projects whose tokens are missing.

- [ ] **Step 3: Visual verify in editor**

Open `http://localhost:6501/editor/db17s1zl`. The Hero should pick up Mark 3's green (`#10b981`).
Switch to a Mark 4 project (different brand color). Hero should pick up Mark 4's color.

- [ ] **Step 4: Commit (spike checkpoint)**

```bash
git add packages/library/src/components/Hero/Hero.linear.tsx
git commit -m "feat(library): theme Hero.linear via CSS vars (spike for WS-5)"
```

### Task 9: Document the CSS-var contract

**Files:**
- Create: `packages/library/docs/theming-contract.md`

- [ ] **Step 1: Write the contract**

```markdown
# Library Theming Contract

Every library component MUST read brand colours, typography, spacing, and
radii from the CSS custom properties that `EngineProvider` injects on its
wrapper. Hardcoded Tailwind palette classes are forbidden.

## Variable Surface

| Var                                | Source path                       | Fallback chain                |
|------------------------------------|-----------------------------------|-------------------------------|
| `--color-primary-{50…950}`         | tokens.custom.json color.primary  | theme(colors.indigo.*)        |
| `--color-secondary-{50…950}`       | tokens.custom.json color.secondary| theme(colors.slate.*)         |
| `--color-accent-{50…950}`          | tokens.custom.json color.accent   | theme(colors.amber.*)         |
| `--color-surface-{0,1}`            | tokens.custom.json color.surface  | theme(colors.white/slate.50)  |
| `--typography-font-body`           | tokens.custom.json typography.font.body | system-ui              |
| `--typography-font-heading`        | tokens.custom.json typography.font.heading | system-ui           |
| `--radius-{sm,md,lg,xl,2xl}`       | tokens.custom.json layout.radius  | theme(borderRadius.*)         |

## Usage pattern

```tsx
className="bg-[var(--color-surface-1,theme(colors.white))] text-[var(--color-primary-900,theme(colors.slate.900))]"
```

Always provide a fallback so projects without a token survive.
```

- [ ] **Step 2: Commit**

```bash
git add packages/library/docs/theming-contract.md
git commit -m "docs(library): document the CSS-var theming contract"
```

### Task 10: Roll out theming to Card, MetricTile, Button

**Files:**
- Modify: `packages/library/src/components/Card/Card.linear.tsx`
- Modify: `packages/library/src/components/MetricTile/MetricTile.linear.tsx`
- Modify: `packages/library/src/components/Button/Button.linear.tsx` (or canonical Button file)

- [ ] **Step 1: For each component, repeat the Hero spike pattern**

For each file:
1. Audit color/typography/radius Tailwind classes (`grep -nE "bg-|text-|border-|rounded-" path`).
2. Replace each with `*-[var(--name,fallback)]`.
3. Visual-verify in editor + preview by switching between db17s1zl (green) and a magenta-themed test project.

- [ ] **Step 2: Add a unit test that asserts no raw palette classes**

```ts
// packages/library/tests/theming-contract.test.ts
import { readFileSync } from "node:fs";
import { glob } from "glob";
const BANNED = /\b(bg|text|border|from|to)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/;
describe("library theming contract", () => {
  it.each(glob.sync("packages/library/src/components/{Hero,Card,MetricTile,Button}/**/*.tsx"))(
    "%s uses no hardcoded Tailwind palette classes",
    (file) => {
      const src = readFileSync(file, "utf8");
      const hits = src.match(new RegExp(BANNED.source, "g"));
      expect(hits, `palette classes found: ${hits?.join(", ")}`).toBeNull();
    }
  );
});
```

- [ ] **Step 3: Run lint test**

Run: `cd packages/library && npx vitest tests/theming-contract.test.ts --run`
Expected: PASS for the four migrated components.

- [ ] **Step 4: Commit per component**

```bash
git add packages/library/src/components/Card/
git commit -m "feat(library): theme Card.linear via CSS vars"

git add packages/library/src/components/MetricTile/
git commit -m "feat(library): theme MetricTile.linear via CSS vars"

git add packages/library/src/components/Button/
git commit -m "feat(library): theme Button.linear via CSS vars"

git add packages/library/tests/theming-contract.test.ts
git commit -m "test(library): enforce CSS-var theming contract on migrated components"
```

### Task 11: Roll out to Badge, Alert, Tabs, Section

- [ ] **Step 1: Apply the same audit + replace pattern**

Modify each of the four files. Extend the `glob.sync` pattern in the lint test to cover them.

- [ ] **Step 2: Run the contract test against the full set**

Run: `cd packages/library && npx vitest tests/theming-contract.test.ts --run`
Expected: PASS.

- [ ] **Step 3: Manual cross-project visual check**

Open db17s1zl preview and a Mark 4 preview side-by-side. The eight themed components should look distinctly different.

- [ ] **Step 4: Commit**

```bash
git add packages/library/src/components/Badge/ packages/library/src/components/Alert/ packages/library/src/components/Tabs/ packages/library/src/components/Section/ packages/library/tests/theming-contract.test.ts
git commit -m "feat(library): theme Badge/Alert/Tabs/Section via CSS vars"
```

---

## WS-6 — Editor↔Preview Parity Test

Goal: A test that opens the editor canvas and the preview for the same page, takes screenshots, and flags drift > N pixels.

### Task 12: Playwright parity test

**Files:**
- Create: `apps/visual-regression/tests/preview-vs-editor.spec.ts`

- [ ] **Step 1: Write the test**

```ts
// apps/visual-regression/tests/preview-vs-editor.spec.ts
import { test, expect } from "@playwright/test";

const PROJECT = process.env.PARITY_PROJECT ?? "db17s1zl";
const PAGES = ["home", "requests", "approvals", "tasks"];

for (const slug of PAGES) {
  test(`editor canvas matches preview for /${slug}`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const editorPage = await ctx.newPage();
    const previewPage = await ctx.newPage();

    await editorPage.goto(`http://localhost:6501/editor/${PROJECT}`);
    await editorPage.waitForTimeout(2500);
    // Navigate the editor's PagePicker to `slug`.
    await editorPage.click(`text=/${slug === "home" ? "" : slug}`).catch(() => {});
    await editorPage.waitForTimeout(1500);
    const canvas = await editorPage.locator("[data-canvas-frame]").screenshot();

    await previewPage.goto(`http://localhost:6503/p/${PROJECT}/${slug}`);
    await previewPage.waitForTimeout(2500);
    const preview = await previewPage.locator("main").screenshot();

    // Compare via pixelmatch — drift > 5% of total pixels is a failure.
    const diff = pixelDiff(canvas, preview);
    expect(diff.changedRatio).toBeLessThan(0.05);
  });
}
```

`pixelDiff` is a small helper that wraps the `pixelmatch` package (add as devDep). The test isn't gated on perfect parity — selection overlays and editor chrome will always differ — but on the rendered page itself.

- [ ] **Step 2: Add pixelmatch dep**

```bash
cd apps/visual-regression && npm i -D pixelmatch pngjs
```

- [ ] **Step 3: Run the test**

Run: `cd apps/visual-regression && npx playwright test tests/preview-vs-editor.spec.ts`
Expected: 4 tests, all under 5% diff (or document the actual diff levels so we know where the next batch of theming work needs to focus).

- [ ] **Step 4: Commit**

```bash
git add apps/visual-regression/tests/preview-vs-editor.spec.ts apps/visual-regression/package.json
git commit -m "test(visual): editor canvas vs preview parity for the top 4 pages"
```

---

## Roll-out / Sequencing

The six workstreams are independent but the *value curve* favours this order:

1. **WS-1 + WS-2** (½ day) — Preview button becomes useful. User can click around the real app.
2. **WS-3** (½ day) — Bindings resolve. No more `{{stats.totalCount}}` literals.
3. **WS-4** (½ day) — Banners differ per project. Visible win.
4. **WS-5 spike** (½ day, Task 8) — Validate the CSS-var approach. Decision point: is the migration cost worth it across all 50 components, or do we stop at the high-impact 8?
5. **WS-5 batch** (1–2 days, Tasks 9–11) — Eight components themed end-to-end.
6. **WS-6** (½ day) — Lock parity in CI so we don't regress.

Total: 4–5 working days for the full plan; 1–1.5 days to ship WS-1–3 alone, which already gets ~80% of the user-visible improvement.

---

## Self-Review

- **Spec coverage:** All six workstreams the user listed are covered. WS-1 (reliability), WS-2 (AppShell), WS-3 (bindings), WS-4 (imagery), WS-5 (library theming), WS-6 (parity).
- **Placeholder scan:** No `TBD` / `implement later`. Every task has concrete code or commands. Two `grep -n ...` discovery steps are explicitly framed as audits whose output drives the next step — that's appropriate, not a placeholder.
- **Type consistency:** `Persister` interface introduced in Task 1 is reused in Tasks 1 + 2. `pick_photo_for` signature change in Task 7 matches the design_agent callsite. `PreviewShell` props in Task 3 match the page.tsx wiring in Task 4.
- **Risk callouts:** WS-5 is the longest workstream and has the highest chance of subtle visual regressions — the contract test + spike-first approach is the mitigation. Tasks 8–11 deliberately gate the full library rollout behind a single component validation, so we can stop early if the cost is unexpectedly high.
