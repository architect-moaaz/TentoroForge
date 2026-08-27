# Design System Overhaul — Wave 5: Polish, Motion, Observability

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Production-grade polish work — motion micro-interactions, page-archetype taxonomy expansion, per-domain rubric tuning, critique-of-critique pass, visual diff viewer in the editor, cost dashboard UI, and auto-promotion of high-scoring real generations into the reference bank.

**Architecture:** Each task is largely independent — they can ship in any order after Phase 3 (Workday register) is in place. Most are localized polish: a new component (visual diff viewer), an analytics endpoint (cost dashboard), a config knob (per-domain weights), a curation queue (auto-promotion).

**Spec:** `docs/superpowers/specs/2026-05-08-design-system-overhaul-design.md` § Phase 6.

---

## File structure

### New files
- `packages/library/src/style/motion-tokens.ts` — motion-level → animation env mapping
- `packages/schema/src/page-archetypes.ts` — expanded archetype taxonomy (workspace/console/inspector/wizard/audit-log/report)
- `frontend/src/components/schema-editor/IterationDiffViewer.tsx` — side-by-side iter-N vs iter-(N-1) screenshot
- `frontend/src/app/admin/fidelity-cost/page.tsx` — cost dashboard
- `backend/services/critique_meta_eval.py` — critique-of-critique sanity pass
- `backend/services/bank_promotion.py` — auto-promote high-scoring schemas

### Modified files
- `packages/library/src/components/{FadeIn,Stagger}/...` — read motion-level token
- `backend/services/vision_evaluator/types.py` — `compute_composite_for_domain(scores, domain)` weighted variant
- `backend/agents/planner.py` — emit `archetype` per page from the expanded taxonomy
- `backend/services/schema_prompt.py` — pass archetype + per-domain weights through to evaluator
- `frontend/src/components/schema-editor/CritiquePanel.tsx` — wire IterationDiffViewer
- `backend/routers/_debug_fidelity.py` — `/api/_debug/bank-candidates` endpoint listing high-scoring promotable schemas

---

## Task 1: Motion micro-interactions tied to motionLevel token

**Files:**
- Create: `packages/library/src/style/motion-tokens.ts`
- Modify: `packages/library/src/components/FadeIn/FadeIn.tsx`
- Modify: `packages/library/src/components/Stagger/Stagger.tsx`

### Step 1: Motion token mapping

```ts
// packages/library/src/style/motion-tokens.ts
import type { Motion } from "../theme/token-types";

/**
 * Motion-level → animation envelope mapping. Components reading the
 * motionLevel token consult this to pick durations, easings, and
 * stagger gaps.
 */
export const MOTION_ENVELOPE: Record<Motion, {
  duration: number;          // ms
  ease: string;
  staggerGap: number;        // ms — for Stagger
  enabled: boolean;
}> = {
  none: {
    duration: 0,
    ease: "linear",
    staggerGap: 0,
    enabled: false,
  },
  subtle: {
    duration: 200,
    ease: "cubic-bezier(0.4, 0, 0.2, 1)",
    staggerGap: 30,
    enabled: true,
  },
  expressive: {
    duration: 400,
    ease: "cubic-bezier(0.34, 1.56, 0.64, 1)",   // overshoot for playful tier
    staggerGap: 80,
    enabled: true,
  },
};
```

### Step 2: Wire FadeIn + Stagger

For each, read `useMotionLevel()` and use `MOTION_ENVELOPE` to pick the animation:

```tsx
// packages/library/src/components/FadeIn/FadeIn.tsx — modify
import { useMotionLevel } from "../../theme/tokens-context";
import { MOTION_ENVELOPE } from "../../style/motion-tokens";

// Inside the component:
const motionLevel = useMotionLevel();
const env = MOTION_ENVELOPE[motionLevel];

// If env.enabled is false, render children without animation:
if (!env.enabled) return <>{children}</>;

// Otherwise apply transition:
return (
  <div
    style={{
      transition: `opacity ${env.duration}ms ${env.ease}`,
      opacity: visible ? 1 : 0,
    }}
  >
    {children}
  </div>
);
```

Same pattern for `Stagger` — use `env.staggerGap` to space child appearances.

### Step 3: Verify + commit

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npm run dev -- -p 6501 > /tmp/frontend-w5-motion.log 2>&1 &
sleep 12
cd /Users/m/Work/code/poc/design2ui-forge-v3/apps/visual-regression
npx playwright test
lsof -ti:6501 | xargs kill -9 2>/dev/null || true
```

Expected: 18/18 PASS — playground uses default motion (subtle), which matches today's existing animation.

```bash
git add packages/library/src/style/motion-tokens.ts \
        packages/library/src/components/{FadeIn,Stagger}/
git commit -m "feat(motion): FadeIn + Stagger consume motionLevel token via MOTION_ENVELOPE"
```

---

## Task 2: Page-archetype taxonomy expansion

**Files:**
- Create: `packages/schema/src/page-archetypes.ts`
- Modify: `backend/agents/planner.py` — emit archetype per page
- Modify: `backend/services/page_type.py` — expand `infer_page_type` mapping

### Step 1: Define the taxonomy

```ts
// packages/schema/src/page-archetypes.ts
/**
 * Page archetype taxonomy.
 *
 * Beyond the v1 list/detail/form/dashboard/settings, this expands to
 * patterns that real enterprise + SaaS apps use:
 *
 *   workspace     list + inspector pane + filter bar (Linear / Notion-tier)
 *   console       KPI grid + chart + activity feed (Stripe / Workday-tier)
 *   inspector     master/detail/sub-detail nesting (any register)
 *   wizard        multi-step form with progress indicator (Workday onboarding)
 *   audit-log     timeline + filters + drill-in (compliance / HR review)
 *   report        filter bar + chart + table + export (BI / analytics)
 */
export const PAGE_ARCHETYPES = [
  // Originals (v1)
  "list", "detail", "form", "dashboard", "settings", "generic",
  // New (Wave 5)
  "workspace", "console", "inspector", "wizard", "audit-log", "report",
] as const;

export type PageArchetype = typeof PAGE_ARCHETYPES[number];

export const ARCHETYPE_DESCRIPTIONS: Record<PageArchetype, string> = {
  list:        "index/list page for browsing many records, with sorting + filters",
  detail:      "record-detail page showing one item's full information",
  form:        "create/edit form with proper validation feedback",
  dashboard:   "overview with KPI tiles, recent activity, status",
  settings:    "settings/profile page with grouped configuration controls",
  generic:     "uncategorised — falls back to default treatment",
  workspace:   "list + inspector pane + filter bar (Linear-style)",
  console:     "KPI grid + chart + activity feed (operations dashboard)",
  inspector:   "master/detail/sub-detail nested view",
  wizard:      "multi-step form with progress + save-draft + back nav",
  "audit-log": "timeline + filters + drill-in for compliance / history review",
  report:      "filter bar + chart + table + export for BI / analytics",
};
```

### Step 2: Update infer_page_type

Modify `backend/services/page_type.py` to recognise the new archetypes via route + role keywords:

```python
def infer_page_type(page_brief) -> str:
    """Infer one of: list | detail | form | dashboard | settings | generic |
    workspace | console | inspector | wizard | audit-log | report"""
    route = (page_brief.route or "").lower()
    role = (page_brief.role or "").lower()

    # New archetype patterns
    if "/workspace" in route or "workspace" in role:
        return "workspace"
    if "/console" in route or "operations console" in role:
        return "console"
    if "/inspector" in route or "/inspect" in route or "drill-in" in role:
        return "inspector"
    if route.endswith("/wizard") or "/onboarding" in route or "multi-step" in role or "wizard" in role:
        return "wizard"
    if "/audit" in route or "/history" in route or "audit log" in role or "activity log" in role:
        return "audit-log"
    if "/reports" in route or "/analytics" in route or "report" in role or "analytics" in role:
        return "report"

    # Existing v1 patterns
    if route.endswith("/new") or route.endswith("/edit") or route.endswith("/create"):
        return "form"
    if route.endswith("/list") or route.endswith("/index") or route.endswith("/all"):
        return "list"
    if "[id]" in route or "{id}" in route:
        return "detail"
    if "/dashboard" in route or "/overview" in route:
        return "dashboard"
    if "/settings" in route or "/profile" in route or "/account" in route:
        return "settings"
    if "list" in role or "browse" in role:
        return "list"
    if "edit" in role or "create" in role or "new" in role:
        return "form"
    if "metric" in role or "kpi" in role or "dashboard" in role:
        return "dashboard"
    if "settings" in role or "profile" in role:
        return "settings"
    if "detail" in role or "view" in role:
        return "detail"
    return "generic"
```

### Step 3: Update tests + commit

```python
# backend/tests/services/test_page_type.py — append
def test_workspace():
    class B: route, role = "/workspace", ""
    assert infer_page_type(B()) == "workspace"

def test_wizard():
    class B: route, role = "/onboarding/step-1", "multi-step"
    assert infer_page_type(B()) == "wizard"

def test_audit_log():
    class B: route, role = "/audit", "compliance log"
    assert infer_page_type(B()) == "audit-log"

def test_report():
    class B: route, role = "/reports/headcount", ""
    assert infer_page_type(B()) == "report"

def test_console():
    class B: route, role = "/console", "operations console"
    assert infer_page_type(B()) == "console"
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_page_type.py -v 2>&1 | tail -10
```

Expected: existing 8 + 5 new = 13 PASS.

```bash
git add packages/schema/src/page-archetypes.ts backend/services/page_type.py \
        backend/tests/services/test_page_type.py
git commit -m "feat(archetypes): expand taxonomy to workspace/console/inspector/wizard/audit-log/report"
```

---

## Task 3: Per-domain rubric weight tuning

**Files:**
- Modify: `backend/services/vision_evaluator/types.py`

### Step 1: Add per-domain weights

```python
# backend/services/vision_evaluator/types.py — append

DOMAIN_COMPOSITE_WEIGHTS: dict[str, dict[Axis, float]] = {
    "default": COMPOSITE_WEIGHTS,  # the existing weights

    # HR / corporate admin — information density matters more
    "hr": {
        "visualPolish":       0.20,
        "domainFeel":         0.25,
        "informationDensity": 0.25,  # bumped from 0.15
        "componentCoherence": 0.20,
        "brandReflection":    0.10,  # dropped from 0.15
    },

    # Fintech — domain feel and brand reflection matter most
    "fintech": {
        "visualPolish":       0.20,
        "domainFeel":         0.30,  # bumped
        "informationDensity": 0.15,
        "componentCoherence": 0.20,
        "brandReflection":    0.15,
    },

    # Healthcare — visual polish + domain feel critical
    "healthcare": {
        "visualPolish":       0.30,  # bumped
        "domainFeel":         0.30,  # bumped
        "informationDensity": 0.15,
        "componentCoherence": 0.15,
        "brandReflection":    0.10,
    },

    # Content/wiki/blog — brand reflection + polish dominate
    "content": {
        "visualPolish":       0.30,  # bumped
        "domainFeel":         0.15,
        "informationDensity": 0.10,
        "componentCoherence": 0.20,
        "brandReflection":    0.25,  # bumped
    },
}


def compute_composite_for_domain(scores: Scores, domain: str) -> float:
    """Same as compute_composite but uses domain-specific weights when
    available. Falls back to the default weights for unknown domains."""
    weights = DOMAIN_COMPOSITE_WEIGHTS.get(domain.lower(), COMPOSITE_WEIGHTS)
    total = sum(getattr(scores, axis) * weight for axis, weight in weights.items())
    return round(total, 2)
```

### Step 2: Wire into evaluator + tests

Find where `compute_composite(scores)` is called in `backend/services/vision_evaluator/`. Replace with `compute_composite_for_domain(scores, ctx.domain)`.

Add tests:

```python
# backend/tests/services/test_vision_evaluator.py — append (or test_vision_validator.py)
from services.vision_evaluator.types import (
    Scores, compute_composite, compute_composite_for_domain
)


def test_composite_for_unknown_domain_falls_back_to_default():
    s = Scores(visualPolish=8, domainFeel=8, informationDensity=8,
               componentCoherence=8, brandReflection=8)
    assert compute_composite_for_domain(s, "unknown") == compute_composite(s)


def test_hr_domain_weights_information_density_higher():
    # 10/10 on info density should be valued more under HR weights than default
    high_density = Scores(visualPolish=5, domainFeel=5, informationDensity=10,
                           componentCoherence=5, brandReflection=5)
    default_score = compute_composite(high_density)
    hr_score = compute_composite_for_domain(high_density, "hr")
    assert hr_score > default_score
```

### Step 3: Commit

```bash
git add backend/services/vision_evaluator/types.py \
        backend/tests/services/test_vision_evaluator.py
git commit -m "feat(rubric): per-domain composite weights (HR / fintech / healthcare / content)"
```

---

## Task 4: Critique-of-critique sanity pass

**Files:**
- Create: `backend/services/critique_meta_eval.py`

A second-pass evaluator that checks whether a vision evaluator's critique is itself reasonable — not for production use, but for tuning telemetry.

```python
# backend/services/critique_meta_eval.py
"""Critique-of-critique sanity pass.

Reads recent fidelity-log entries, samples critiques, and asks a model
'is this critique well-formed and actionable?' to surface degenerate
critique patterns (e.g. evaluator giving 9/10 on every page, or always
flagging the same trivial issue regardless of content).

Run manually as a tuning tool, not in the production loop.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sample_critiques(output_root: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Sample iter-0 critiques across recent projects."""
    samples: list[dict[str, Any]] = []
    for proj_dir in sorted(output_root.iterdir())[-30:]:  # last ~30 projects
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        if not log_path.exists():
            continue
        try:
            log = json.loads(log_path.read_text())
        except json.JSONDecodeError:
            continue
        for page_path, entry in log.items():
            iters = entry.get("iterations", [])
            if iters:
                samples.append({
                    "project": proj_dir.name,
                    "page": page_path,
                    "score": iters[0].get("score"),
                    "issues": iters[0].get("issues", []),
                })
            if len(samples) >= limit:
                return samples
    return samples


def diagnose_distribution(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Quick statistical sanity checks. No LLM call."""
    if not samples:
        return {"sample_size": 0, "warnings": ["no samples available"]}
    scores = [s["score"] for s in samples if s["score"] is not None]
    issue_axes = []
    for s in samples:
        for i in s["issues"]:
            issue_axes.append(i.get("axis", "unknown"))

    warnings: list[str] = []
    if scores:
        avg = sum(scores) / len(scores)
        # Suspicious patterns
        if avg > 9.0:
            warnings.append(f"avg score {avg:.2f} — evaluator may be too lenient")
        if avg < 4.0:
            warnings.append(f"avg score {avg:.2f} — evaluator may be too harsh")
        if max(scores) - min(scores) < 0.5:
            warnings.append(f"score range {min(scores):.2f}–{max(scores):.2f} — evaluator may not be discriminating")
    if issue_axes:
        from collections import Counter
        axis_dist = Counter(issue_axes)
        top_axis, top_count = axis_dist.most_common(1)[0]
        if top_count > len(issue_axes) * 0.7:
            warnings.append(f"{top_axis} flagged in {top_count}/{len(issue_axes)} issues — evaluator may be biased")

    return {
        "sample_size": len(samples),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "score_range": [min(scores), max(scores)] if scores else None,
        "issue_axis_distribution": dict(Counter(issue_axes)) if issue_axes else {},
        "warnings": warnings,
    }
```

Add a debug endpoint to expose this:

```python
# backend/routers/_debug_fidelity.py — append
from services.critique_meta_eval import sample_critiques, diagnose_distribution


@router.get("/api/_debug/critique-meta-eval")
async def critique_meta_eval(limit: int = 20):
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    samples = sample_critiques(output_root, limit=limit)
    return diagnose_distribution(samples)
```

Tests:

```python
# backend/tests/services/test_critique_meta_eval.py — new
from services.critique_meta_eval import diagnose_distribution


def test_empty_samples():
    out = diagnose_distribution([])
    assert out["sample_size"] == 0


def test_lenient_evaluator_warning():
    samples = [{"score": 9.5, "issues": []} for _ in range(10)]
    out = diagnose_distribution(samples)
    assert any("lenient" in w for w in out["warnings"])


def test_low_discrimination_warning():
    samples = [{"score": 7.0, "issues": []} for _ in range(10)]
    out = diagnose_distribution(samples)
    assert any("discriminating" in w for w in out["warnings"])
```

Commit:

```bash
git add backend/services/critique_meta_eval.py \
        backend/tests/services/test_critique_meta_eval.py \
        backend/routers/_debug_fidelity.py
git commit -m "feat(observability): critique-of-critique sanity diagnostics"
```

---

## Task 5: Visual diff viewer in CritiquePanel

**Files:**
- Create: `frontend/src/components/schema-editor/IterationDiffViewer.tsx`
- Modify: `frontend/src/components/schema-editor/CritiquePanel.tsx`

### Step 1: Create IterationDiffViewer

```tsx
// frontend/src/components/schema-editor/IterationDiffViewer.tsx
"use client";

interface DiffViewerProps {
  shortId: string;
  pagePath: string;
  iterFrom: number | string;
  iterTo: number | string;
  patchSummary?: string[];
}

export function IterationDiffViewer({
  shortId, pagePath, iterFrom, iterTo, patchSummary,
}: DiffViewerProps) {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
  const safePage = pagePath.replace(/\//g, "_");
  const fromUrl = `${apiBase}/api/_debug/project-file/${shortId}/.fidelity-history/${safePage}/iter-${iterFrom}.png`;
  const toUrl   = `${apiBase}/api/_debug/project-file/${shortId}/.fidelity-history/${safePage}/iter-${iterTo}.png`;

  return (
    <div className="rounded border bg-card p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
        Iter {iterFrom} → Iter {iterTo}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <figure>
          <figcaption className="text-[10px] uppercase text-muted-foreground mb-1">Before</figcaption>
          <img src={fromUrl} alt={`iter ${iterFrom}`} className="w-full rounded border" />
        </figure>
        <figure>
          <figcaption className="text-[10px] uppercase text-muted-foreground mb-1">After</figcaption>
          <img src={toUrl} alt={`iter ${iterTo}`} className="w-full rounded border" />
        </figure>
      </div>
      {patchSummary && patchSummary.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
          {patchSummary.map((s, i) => (<li key={i}>↳ {s}</li>))}
        </ul>
      )}
    </div>
  );
}
```

### Step 2: Wire into CritiquePanel

In `frontend/src/components/schema-editor/CritiquePanel.tsx`, inside the IterationHistory section's expanded-detail view (added in Wave 1), add:

```tsx
import { IterationDiffViewer } from "./IterationDiffViewer";

// Inside the expanded-iter detail block:
{iterIndex > 0 && (
  <IterationDiffViewer
    shortId={shortId}
    pagePath={pagePath}
    iterFrom={iterations[iterIndex - 1].iteration}
    iterTo={iter.iteration}
    patchSummary={iter.patch_summary}
  />
)}
```

NOTE for implementer: integration depends on the existing IterationHistory structure. Adapt to the file's actual shape.

### Step 3: Verify + commit

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/frontend
npx tsc --noEmit 2>&1 | head -10 || true

git add frontend/src/components/schema-editor/IterationDiffViewer.tsx \
        frontend/src/components/schema-editor/CritiquePanel.tsx
git commit -m "feat(editor): visual diff viewer for iter-N vs iter-(N-1) screenshots"
```

---

## Task 6: Cost dashboard UI

**Files:**
- Create: `frontend/src/app/admin/fidelity-cost/page.tsx`

A simple admin page reading `/api/_debug/fidelity-stats`.

```tsx
// frontend/src/app/admin/fidelity-cost/page.tsx
"use client";

import { useEffect, useState } from "react";

export default function FidelityCostPage() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
    fetch(`${apiBase}/api/_debug/fidelity-stats`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setStats(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <main className="p-8 text-sm text-muted-foreground">Loading…</main>;
  if (!stats) return <main className="p-8 text-sm text-destructive">Stats endpoint unreachable.</main>;

  return (
    <main className="bg-background min-h-screen p-8">
      <h1 className="text-2xl font-semibold mb-1">Fidelity Cost Dashboard</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Per-project + per-page costs from `/api/_debug/fidelity-stats`.
      </p>

      <div className="grid grid-cols-4 gap-3 mb-6">
        <Stat label="Projects" value={stats.projects} />
        <Stat label="Pages scored" value={stats.pages_scored} />
        <Stat label="Pass rate" value={`${(stats.pass_rate * 100).toFixed(0)}%`} />
        <Stat label="Avg cost" value={`$${stats.avg_cost_usd?.toFixed(2) ?? "0.00"}`} />
      </div>

      <h2 className="text-sm font-semibold mb-3">Iteration Distribution</h2>
      <div className="grid grid-cols-4 gap-3 mb-6">
        {Object.entries(stats.iter_distribution || {}).map(([iter, count]: [string, any]) => (
          <Stat key={iter} label={`Iter ${iter}`} value={count} />
        ))}
      </div>

      <h2 className="text-sm font-semibold mb-3">Health Signals</h2>
      <ul className="space-y-1 text-xs text-muted-foreground">
        <li>Median score: {stats.median_score}</li>
        <li>Avg iters: {stats.avg_iters}</li>
        <li>Cap exhausted: {stats.cap_exhausted}</li>
      </ul>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded border bg-card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold mt-1 tabular-nums">{value ?? "—"}</p>
    </div>
  );
}
```

Commit:

```bash
git add frontend/src/app/admin/fidelity-cost/page.tsx
git commit -m "feat(editor): fidelity cost dashboard at /admin/fidelity-cost"
```

---

## Task 7: Auto-promotion of high-scoring real generations

**Files:**
- Create: `backend/services/bank_promotion.py`
- Modify: `backend/routers/_debug_fidelity.py`

When a page in production scores ≥ 8.5 with no high-severity issues, it's a candidate to be promoted into the reference bank for future generations.

### Step 1: Implement bank_promotion.py

```python
# backend/services/bank_promotion.py
"""Auto-promotion of high-scoring real generations into the reference bank.

Daily/manual scan over output/<id>/src/contracts/fidelity-log.json files.
Pages scoring >= 8.5 with no high-severity issues land in
backend/reference_pages/<register>/<domain>/<page_type>/.candidates/
for human review before being promoted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PROMOTE_SCORE_THRESHOLD = 8.5


def find_candidates(output_root: Path) -> list[dict[str, Any]]:
    """Scan all projects' fidelity-log.json. Return candidates that meet
    the auto-promotion criteria but haven't been promoted yet."""
    candidates: list[dict[str, Any]] = []
    if not output_root.exists():
        return candidates

    for proj_dir in sorted(output_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        spec_path = proj_dir / "src" / "contracts" / "design-spec.json"
        if not log_path.exists():
            continue

        try:
            log = json.loads(log_path.read_text())
            spec = json.loads(spec_path.read_text()) if spec_path.exists() else {}
        except json.JSONDecodeError:
            continue

        register = spec.get("register", "default")
        domain = spec.get("domain", "general")

        for page_path, entry in log.items():
            final_score = entry.get("final_score", 0.0)
            if final_score < _PROMOTE_SCORE_THRESHOLD:
                continue
            iters = entry.get("iterations", [])
            if not iters:
                continue
            last_iter = iters[-1]
            issues = last_iter.get("issues", [])
            has_high = any(i.get("severity") == "high" for i in issues)
            if has_high:
                continue
            # Find the schema file
            schema_path = proj_dir / "src" / "schemas" / f"{page_path}.json"
            if not schema_path.exists():
                continue
            candidates.append({
                "project_id": proj_dir.name,
                "page_path": page_path,
                "register": register,
                "domain": domain,
                "page_type": _infer_page_type_from_path(page_path),
                "score": final_score,
                "schema_path": str(schema_path),
            })

    return candidates


def _infer_page_type_from_path(page_path: str) -> str:
    if page_path.endswith("/list") or page_path.endswith("/index"):
        return "list"
    if page_path.endswith("/new") or page_path.endswith("/edit"):
        return "form"
    if "/dashboard" in page_path or page_path.endswith("/overview"):
        return "dashboard"
    if "/settings" in page_path:
        return "settings"
    if page_path.endswith("/detail") or "[id]" in page_path:
        return "detail"
    return "generic"


def promote_candidate(candidate: dict[str, Any], bank_root: Path) -> Path:
    """Copy the candidate schema + screenshot into the reference bank."""
    register = candidate["register"]
    domain = candidate["domain"]
    page_type = candidate["page_type"]

    cell = bank_root / register / domain / page_type
    cell.mkdir(parents=True, exist_ok=True)

    # Find next exemplar number
    existing = sorted(cell.glob("exemplar_*.json"))
    next_idx = len(existing) + 1
    stem = f"exemplar_{next_idx:02d}"

    schema_text = Path(candidate["schema_path"]).read_text()
    (cell / f"{stem}.json").write_text(schema_text)
    (cell / f"{stem}.meta.json").write_text(json.dumps({
        "score": candidate["score"],
        "promoted_from": candidate["project_id"],
        "promoted_page": candidate["page_path"],
        "auto_promoted": True,
    }, indent=2))

    return cell / f"{stem}.json"
```

### Step 2: Add candidate-listing endpoint

```python
# backend/routers/_debug_fidelity.py — append
from services.bank_promotion import find_candidates


@router.get("/api/_debug/bank-candidates")
async def bank_candidates_list():
    """List schemas eligible for promotion into the reference bank.
    Manual review step — does NOT promote automatically."""
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    return {"candidates": find_candidates(output_root)}
```

### Step 3: Tests

```python
# backend/tests/services/test_bank_promotion.py — new
import json
from pathlib import Path

import pytest

from services.bank_promotion import find_candidates, promote_candidate


def _make_project(root: Path, project_id: str, register: str, domain: str,
                   page_path: str, score: float, has_high: bool = False):
    proj = root / project_id
    proj.mkdir(parents=True)
    (proj / "src" / "contracts").mkdir(parents=True)
    (proj / "src" / "contracts" / "design-spec.json").write_text(
        json.dumps({"register": register, "domain": domain})
    )
    issues = [{"severity": "high"}] if has_high else []
    (proj / "src" / "contracts" / "fidelity-log.json").write_text(json.dumps({
        page_path: {
            "final_score": score,
            "iterations": [{"score": score, "issues": issues, "pass": score >= 8.5}],
        }
    }))
    schema_dir = proj / "src" / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / f"{page_path}.json").parent.mkdir(parents=True, exist_ok=True)
    (schema_dir / f"{page_path}.json").write_text(json.dumps({
        "schemaVersion": "2", "id": page_path, "route": f"/{page_path}",
        "meta": {}, "dataSources": [], "root": {"id": "r", "type": "Stack", "props": {}, "children": []}
    }))


def test_find_candidates_above_threshold(tmp_path):
    output_root = tmp_path / "output"
    output_root.mkdir()
    _make_project(output_root, "proj1", "workday", "hr", "users_list", 8.7)
    _make_project(output_root, "proj2", "workday", "hr", "users_detail", 7.9)  # below
    _make_project(output_root, "proj3", "workday", "hr", "leave_dashboard", 8.6, has_high=True)  # high-sev

    candidates = find_candidates(output_root)
    assert len(candidates) == 1
    assert candidates[0]["project_id"] == "proj1"


def test_promote_candidate_writes_to_bank(tmp_path):
    output_root = tmp_path / "output"
    output_root.mkdir()
    _make_project(output_root, "proj1", "workday", "hr", "users_list", 8.7)
    candidates = find_candidates(output_root)
    assert candidates

    bank_root = tmp_path / "reference_pages"
    promoted = promote_candidate(candidates[0], bank_root)
    assert promoted.exists()
    assert promoted.parent.name == "list"  # inferred page_type
    assert promoted.parent.parent.name == "hr"
    assert promoted.parent.parent.parent.name == "workday"

    meta = json.loads((promoted.parent / promoted.name.replace(".json", ".meta.json")).read_text())
    assert meta["score"] == 8.7
    assert meta["auto_promoted"] is True
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_bank_promotion.py -v 2>&1 | tail -10
```

Expected: 2 PASS.

```bash
git add backend/services/bank_promotion.py \
        backend/tests/services/test_bank_promotion.py \
        backend/routers/_debug_fidelity.py
git commit -m "feat(promotion): bank-candidate scanner + promote_candidate helper"
```

---

## Self-review

### Spec coverage

| Spec section | Tasks |
|---|---|
| Motion micro-interactions | 1 |
| Page-archetype taxonomy expansion | 2 |
| Per-domain rubric weight tuning | 3 |
| Critique-of-critique sanity pass | 4 |
| Visual diff viewer | 5 |
| Cost dashboard UI | 6 |
| Auto-promotion | 7 |

✓ All Phase 6 spec items covered.

### Type consistency

- `PageArchetype` defined in `packages/schema/src/page-archetypes.ts`, used by `infer_page_type`
- `DOMAIN_COMPOSITE_WEIGHTS` matches `Axis` enum keys
- `Motion` enum from token-types drives `MOTION_ENVELOPE`
- All new endpoints follow existing `/api/_debug/...` convention

✓ Consistent.

---

## Out of scope (deferred to follow-up plans)

- **Real user research** — Tier 3 work; not in this plan
- **Accessibility audit + remediation** — Tier 3 work
- **Mobile responsive design** — Tier 3 work
- **Performance optimisations** (table virtualization, lazy-loading) — Tier 3 work
- **Custom iconography + illustrations** — Tier 3 work
- **Operational seeding for the 4 new registers** — manual step (~$80 total)
- **Workday-grade missing components** (DataGrid, Chart, Sparkline, Timeline, ApprovalStepper, etc.) — Tier 2 follow-up plan
