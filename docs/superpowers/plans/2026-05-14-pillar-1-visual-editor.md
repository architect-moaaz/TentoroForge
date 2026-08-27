# Pillar 1 — Visual Editor & Peer-Patcher Architecture

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Tentoro Forge to the v1.1 spec's "artifacts as system, derived view everywhere, peer patchers" architecture. The editor canvas renders the same engine the generated app uses; every modification flows through typed actions on three artifacts (N page-schemas + one nav-flow + one tokens/globals); the LLM is a peer patcher producing the same artifact shape via a single `writeArtifacts` tool call. Drag-and-drop, registry-driven properties panel, undo, and the eight invariants from spec §12 all light up.

**Architecture:** Nine workstreams in dependency order. **W1 (nav-flow)** and the existing standalone-engine plan (commit-equivalent of `docs/superpowers/plans/2026-05-14-standalone-engine-and-emitter.md`) are the foundation — everything else depends on the engine package being available. **W2 (editor canvas read-only)** delivers immediate WYSIWYG value once the engine package ships. **W3 (mutation layer)** is the load-bearing primitive: typed `EditorAction`, `applyAction`, typed inverses, undo stack. **W4 (registry consolidation)** turns the per-component schemas into the spec's single canonical registry. **W5–W7 (selection overlay, properties panel, drag-drop)** are the interactive editor surface. **W8 (LLM peer patcher)** rewrites generation as a single `writeArtifacts` tool call. **W9 (invariants)** adds golden tests for I-1 through I-8 and CI gating. Phases 1–3 (W1–W3) can land in ~1 week. Phases 4–7 (W4–W7) add another ~2 weeks. Phase 8 (LLM rewrite) and phase 9 (invariants) close v1.

**Tech Stack:** TypeScript (Zod, React, Next.js 15 app-router), tsup for engine bundling, react-dnd or @dnd-kit for drag mechanics, Python (FastAPI) for the nav-flow emitter and LLM rewrite, pytest + vitest, anyhow.

**Spec:** This plan implements the architecture documented in `/Users/m/Downloads/Tentoro_Forge_Visual_Editor_Spec_v1.1.docx`. Specifically: §1.3 (three roles: views/patchers/renderer), §1.4 (six core principles), §2 (three artifacts — adapted to N page-schemas in our codebase), §3 (mutation model), §4 (component registry), §5–§8 (editor UX), §9 (data binding), §10 (single engine two modes), §11 (LLM peer patcher), §12 (eight invariants I-1 through I-8), §13 (starter registry).

**Adaptation from spec:** Per the user's correction (session 2026-05-14), Tentoro Forge uses N page-schema files (`src/schemas/<slug>.json`) rather than a single consolidated `page-schema.json` with a `pages[]` array. Functionally equivalent — N records, just N files. The nav-flow artifact and the global tokens artifact remain singular as the spec specifies.

---

## Background — what does not exist today

Per the gap analysis (session 2026-05-14):

- **Visual editing surface** — no canvas, no drag/drop, no selection overlay, no registry-driven properties panel, no bind/literal toggle, no responsive overrides, no binding chip UI.
- **`nav-flow.json` artifact** — only `app-model.json` (entities + page metadata) and `navigation-flow.json` (office-events graph, different purpose) exist; no spec-shaped nav with `transitions`/`guards`/`initialPage`.
- **Mutation layer** — no `EditorAction` types, no `applyAction`, no inverses, no undo, no atomic multi-artifact transactions.
- **Canonical component registry** — each component has its own `.schema.ts`; no single registry with `slots`/`controls`/`groups` consumed uniformly by palette + properties + renderer + LLM.
- **Generated-app runtime parity** — no SSR for the generated app; canvas and generated-app go through different code paths (scaffold inline dispatch).
- **LLM as peer patcher** — multi-agent pipeline emits ~7 files via N agents; spec wants one LLM call producing the three artifacts via `writeArtifacts` tool.
- **Invariant enforcement** — no token-closure validator, no registry-closure validator, no round-trip `normalize()`, no DOM-equivalence golden tests.

Out of scope (future work):

- CRDT real-time collaboration
- Multi-select / lasso select
- Per-breakpoint props panel UI (responsive layout still works at the schema level)
- Action descriptor picker (action shapes remain JSON-editable in v1)
- Token-editor UI panel (tokens.json editable as raw JSON in v1)
- Mobile/RN renderer (same engine API, separate target)
- Workflow engine rewrite (out of scope — separate from rendering pipeline)

---

## File structure

### New packages

```
packages/patches/                              # mutation layer (W3)
  package.json
  src/
    index.ts                                   # public exports
    types.ts                                   # EditorAction union, Artifacts type
    apply.ts                                   # applyAction + inverse generation
    normalize.ts                               # canonical artifact normalisation
    validate.ts                                # token closure, registry closure
  tests/

packages/engine/                               # see docs/superpowers/plans/2026-05-14-standalone-engine-and-emitter.md
  # produced by that plan's Workstream A — not duplicated here

packages/registry/                             # canonical component registry (W4)
  package.json
  src/
    index.ts
    types.ts                                   # ComponentRegistryEntry + control types
    starter.ts                                 # the spec's §13 starter set
    digest.ts                                  # compact LLM-prompt summary
  tests/
```

### New backend files

```
backend/services/
  nav_flow_emitter.py                          # W1
  artifact_emitter.py                          # W8 — single LLM-call generation
  artifact_validator.py                        # W9 — token + registry closure

backend/agents/
  peer_patcher.py                              # W8 — replaces multi-agent pipeline

backend/contracts/
  nav_flow.py                                  # W1 — Pydantic shape

backend/tests/services/
  test_nav_flow_emitter.py
  test_artifact_validator.py
```

### New frontend files

```
frontend/src/components/canvas/                # W2, W5
  Canvas.tsx                                   # the engine-rendered editor canvas
  CanvasFrame.tsx                              # padding + viewport device mode
  SelectionOverlay.tsx                         # W5 — sibling overlay layer
  SelectionBox.tsx                             # W5 — selection rect + handles
  DropIndicator.tsx                            # W7 — drop preview
  hooks/
    useSelection.ts                            # W5
    useArtifacts.ts                            # W3 wrapper for editor store
    useDrop.ts                                 # W7

frontend/src/components/palette/                # W7
  Palette.tsx
  PaletteItem.tsx

frontend/src/components/properties/             # W6
  PropertiesPanel.tsx
  PropControls/                                # one component per control type
    TextControl.tsx
    SelectControl.tsx
    ToggleControl.tsx
    ColorControl.tsx
    ActionControl.tsx
  BindToggle.tsx                               # bind/literal switch

frontend/src/lib/
  editor-store.ts                              # zustand wrapper around artifacts + undo
  apply-from-frontend.ts                       # thin client wrapper around @forge/patches
```

### Modified files

```
backend/routers/generate.py                    # W1 + W8
backend/agents/{planner,design,schema,page}_agent.py  # W8 — collapse into peer_patcher
packages/library/src/components/*/index.ts     # W4 — emit registry entries
apps/render-scaffold/src/components/SchemaRendererWrapper.tsx  # W2 — use engine + nav-flow
frontend/src/app/editor/[projectId]/page.tsx   # W2 — mount Canvas, drop PreviewTab
frontend/src/components/schema-editor/SchemaEditorPanel.tsx  # W2 — collapse three tabs
```

### Public surfaces this plan produces

```ts
// @forge/patches
import { applyAction, type EditorAction, type Artifacts } from "@forge/patches";

// @forge/registry
import { registry, registryDigest } from "@forge/registry";

// @tentoroforge/engine (produced by sibling standalone-engine plan)
import { Engine, EngineProvider, useNavFlow, useNavigate } from "@tentoroforge/engine";
```

---

## Workstream 1 — Nav Flow

### Task W1.1: nav-flow Pydantic shape + Zod export

**Files:**
- Create: `backend/contracts/nav_flow.py`
- Create: `packages/schema/src/nav-flow.ts`

- [ ] **Step 1: Pydantic shape (backend authority)**

```python
# backend/contracts/nav_flow.py
"""nav-flow.json artifact: routes, initial page, transitions, guards."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class NavFlowPageEntry(BaseModel):
    id: str = Field(..., description="Stable id referenced by transitions + links")
    route: str = Field(..., description='Next.js route pattern, e.g. "/users/[id]"')
    title: str
    schema_file: str = Field(..., alias="schemaFile",
                             description="Path relative to project root")
    layout: Optional[str] = None
    guard: Optional[str] = Field(None, description="Name of a guard in NavFlow.guards")
    params: Optional[list[str]] = Field(default_factory=list,
                                        description="Dynamic-segment param names")

    class Config:
        populate_by_name = True


class NavFlowTransition(BaseModel):
    id: str
    from_page: str = Field(..., alias="from")
    trigger: str
    to: str
    params: Optional[dict] = None

    class Config:
        populate_by_name = True


class NavFlowGuard(BaseModel):
    redirect_to: str = Field(..., alias="redirectTo")
    condition: str = Field(..., description="Expression evaluated against context")

    class Config:
        populate_by_name = True


class NavFlow(BaseModel):
    version: str = "1.0"
    initial_page: str = Field(..., alias="initialPage")
    pages: list[NavFlowPageEntry]
    transitions: list[NavFlowTransition] = Field(default_factory=list)
    guards: dict[str, NavFlowGuard] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


def empty_nav_flow() -> NavFlow:
    return NavFlow(initial_page="", pages=[], transitions=[], guards={})
```

- [ ] **Step 2: Zod mirror (frontend authority)**

```ts
// packages/schema/src/nav-flow.ts
import { z } from "zod";

export const NavFlowPageEntry = z.object({
  id: z.string(),
  route: z.string(),
  title: z.string(),
  schemaFile: z.string(),
  layout: z.string().optional(),
  guard: z.string().nullable().optional(),
  params: z.array(z.string()).default([]),
});

export const NavFlowTransition = z.object({
  id: z.string(),
  from: z.string(),
  trigger: z.string(),
  to: z.string(),
  params: z.record(z.unknown()).optional(),
});

export const NavFlowGuard = z.object({
  redirectTo: z.string(),
  condition: z.string(),
});

export const NavFlow = z.object({
  version: z.literal("1.0").default("1.0"),
  initialPage: z.string(),
  pages: z.array(NavFlowPageEntry),
  transitions: z.array(NavFlowTransition).default([]),
  guards: z.record(NavFlowGuard).default({}),
});

export type NavFlowT = z.infer<typeof NavFlow>;
```

- [ ] **Step 3: Commit**

```bash
git add backend/contracts/nav_flow.py packages/schema/src/nav-flow.ts
git commit -m "feat(nav-flow): Pydantic + Zod shapes"
```

---

### Task W1.2: nav_flow_emitter — build nav-flow from plan + schemas

**Files:**
- Create: `backend/services/nav_flow_emitter.py`
- Create: `backend/tests/services/test_nav_flow_emitter.py`

- [ ] **Step 1: Tests first**

```python
# backend/tests/services/test_nav_flow_emitter.py
"""Tests for nav_flow_emitter."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from services.nav_flow_emitter import emit_nav_flow


def _seed_schema(dir_: Path, slug: str, content: dict) -> None:
    p = dir_ / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(content))


def test_emit_with_two_pages_one_transition():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {
            "schemaVersion": "2", "id": "home",
            "root": {"type": "Button", "id": "b1",
                     "props": {"label": "Sign up",
                               "onClick": {"action": "navigate",
                                           "trigger": "signupClicked"}}}
        })
        _seed_schema(out, "signup", {
            "schemaVersion": "2", "id": "signup",
            "root": {"type": "Form", "id": "f1"}
        })
        plan = {
            "pages": [
                {"name": "Home",   "route": "/",       "type": "dashboard"},
                {"name": "Signup", "route": "/signup", "type": "form"},
            ]
        }
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["initialPage"] in {"home", "Home"}
        assert len(nav["pages"]) == 2
        assert len(nav["transitions"]) == 1
        assert nav["transitions"][0]["trigger"] == "signupClicked"


def test_emit_handles_auth_guard_from_plan():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "dashboard", {"schemaVersion": "2", "id": "dashboard"})
        plan = {"pages": [{"name": "Dashboard", "route": "/dashboard",
                          "type": "dashboard", "requires_auth": True}]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        page = next(p for p in nav["pages"] if p["id"] == "dashboard")
        assert page["guard"] == "requiresAuth"
        assert "requiresAuth" in nav["guards"]


def test_emit_picks_root_route_as_initial():
    """Page with route '/' is the initial page."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {"schemaVersion": "2", "id": "home"})
        _seed_schema(out, "other", {"schemaVersion": "2", "id": "other"})
        plan = {"pages": [
            {"name": "Other", "route": "/other", "type": "generic"},
            {"name": "Home",  "route": "/",      "type": "dashboard"},
        ]}
        emit_nav_flow(str(out), plan)
        nav = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["initialPage"] == "home"


def test_emit_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        _seed_schema(out, "home", {"schemaVersion": "2", "id": "home"})
        plan = {"pages": [{"name": "Home", "route": "/", "type": "dashboard"}]}
        emit_nav_flow(str(out), plan)
        first = (out / "src" / "contracts" / "nav-flow.json").read_text()
        emit_nav_flow(str(out), plan)
        second = (out / "src" / "contracts" / "nav-flow.json").read_text()
        assert first == second
```

- [ ] **Step 2: Implementation**

```python
# backend/services/nav_flow_emitter.py
"""Build nav-flow.json from plan.pages + transitions extracted from schemas."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

from contracts.nav_flow import NavFlow, NavFlowPageEntry, NavFlowTransition, NavFlowGuard

_NAV_OUT = "src/contracts/nav-flow.json"
_SCHEMA_DIR = "src/schemas"


def _slug_from_route(route: str) -> str:
    """`/` → 'home', `/users/[id]` → 'users-detail', `/notes` → 'notes'."""
    if route in ("/", ""):
        return "home"
    cleaned = route.strip("/")
    if "[" in cleaned:
        return cleaned.replace("[id]", "detail").replace("/", "-")
    return cleaned.replace("/", "-")


def _extract_route_params(route: str) -> list[str]:
    return re.findall(r"\[(\w+)\]", route or "")


def _walk_nodes(node: Any):
    """Yield every node dict in a schema tree."""
    if isinstance(node, list):
        for n in node:
            yield from _walk_nodes(n)
        return
    if not isinstance(node, dict):
        return
    yield node
    for key in ("children", "props"):
        v = node.get(key)
        if v is not None:
            yield from _walk_nodes(v)
    slots = node.get("slots")
    if isinstance(slots, dict):
        for arr in slots.values():
            yield from _walk_nodes(arr)


def _collect_transitions(output_dir: Path, page_ids: set[str]) -> list[NavFlowTransition]:
    """Scan each page schema for onClick navigate actions; emit transition records."""
    transitions: list[NavFlowTransition] = []
    seen: set[tuple[str, str]] = set()
    schemas_dir = output_dir / _SCHEMA_DIR
    if not schemas_dir.exists():
        return transitions
    for schema_file in schemas_dir.rglob("*.json"):
        try:
            schema = json.loads(schema_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        from_id = schema.get("id") or schema_file.stem
        for node in _walk_nodes(schema):
            on_click = (node.get("props") or {}).get("onClick")
            if not isinstance(on_click, dict):
                continue
            if on_click.get("action") != "navigate":
                continue
            trigger = on_click.get("trigger") or on_click.get("to")
            if not trigger:
                continue
            # Resolve trigger to a target page id when possible
            to_id = on_click.get("to") or trigger
            if to_id not in page_ids:
                # Best effort: strip leading slash, kebab the rest
                candidate = (to_id or "").lstrip("/").replace("/", "-") or "home"
                if candidate in page_ids:
                    to_id = candidate
                else:
                    continue
            key = (from_id, trigger)
            if key in seen:
                continue
            seen.add(key)
            transitions.append(NavFlowTransition(
                id=f"t-{len(transitions)+1}", **{"from": from_id},
                trigger=trigger, to=to_id,
            ))
    return transitions


def emit_nav_flow(output_dir: str, plan: dict) -> None:
    out = Path(output_dir)
    pages = []
    guards: dict[str, NavFlowGuard] = {}
    initial = None
    for p in (plan or {}).get("pages", []):
        route = p.get("route", "/")
        slug = _slug_from_route(route)
        guard_name = None
        if p.get("requires_auth"):
            guard_name = "requiresAuth"
            guards.setdefault("requiresAuth", NavFlowGuard(
                **{"redirectTo": "login"},
                condition="global.user.isAuthenticated == true",
            ))
        pages.append(NavFlowPageEntry(
            id=slug,
            route=route,
            title=p.get("name") or slug.capitalize(),
            **{"schemaFile": f"{_SCHEMA_DIR}/{slug}.json"},
            guard=guard_name,
            params=_extract_route_params(route),
        ))
        if route in ("/", "/home") and initial is None:
            initial = slug

    if initial is None and pages:
        initial = pages[0].id

    page_ids = {p.id for p in pages}
    transitions = _collect_transitions(out, page_ids)

    nav = NavFlow(
        **{"initialPage": initial or ""},
        pages=pages,
        transitions=transitions,
        guards=guards,
    )

    nav_path = out / _NAV_OUT
    nav_path.parent.mkdir(parents=True, exist_ok=True)
    nav_path.write_text(nav.model_dump_json(by_alias=True, indent=2) + "\n")
```

- [ ] **Step 3: Run tests, 4/4 pass**

```bash
cd backend && python3 -m pytest tests/services/test_nav_flow_emitter.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/nav_flow_emitter.py backend/tests/services/test_nav_flow_emitter.py
git commit -m "feat(nav-flow): emitter builds artifact from plan + schemas"
```

---

### Task W1.3: Wire nav-flow emitter into the generation pipeline

**Files:**
- Modify: `backend/routers/generate.py`

The emitter runs once per pipeline, AFTER `app_emitter` (which writes Next.js skeleton files — see standalone-engine plan W-B4) and AFTER `post_emit_photo_injector` (so the schemas it scans have already received their photo URLs). Both schema-mode early-exits need the call.

- [ ] **Step 1: Find both schema-mode exits**

```bash
grep -n "Schema mode — skipping" backend/routers/generate.py
```

- [ ] **Step 2: Insert before the fidelity scoring block, AFTER photo injection**

```python
        # Build nav-flow.json from plan.pages + extracted onClick navigate actions.
        # Runs after schemas are emitted and photo URLs are injected so transitions
        # reference final schema state.
        try:
            from services.nav_flow_emitter import emit_nav_flow
            emit_nav_flow(output_dir, plan)
            yield sse_event("log", {"text": "[NavFlow] nav-flow.json written"})
        except Exception as _nf_exc:
            yield sse_event("log", {"text": f"[NavFlow] Skipped: {_nf_exc}"})
```

- [ ] **Step 3: Compile + commit**

```bash
python3 -m py_compile backend/routers/generate.py
git add backend/routers/generate.py
git commit -m "feat(nav-flow): wire emitter into generation pipeline (both schema-mode exits)"
```

---

### Task W1.4: Engine consumes nav-flow — context + useNavigate hook

**Files:**
- Modify: `packages/engine/src/EngineProvider.tsx` (after standalone-engine W-A5 lands)
- Create: `packages/engine/src/nav/NavFlowContext.tsx`
- Create: `packages/engine/src/nav/useNavigate.ts`
- Create: `packages/engine/tests/nav.test.tsx`

- [ ] **Step 1: Define context**

```tsx
// packages/engine/src/nav/NavFlowContext.tsx
"use client";
import * as React from "react";
import type { NavFlowT } from "@tentoroforge/schema";

export const NavFlowContext = React.createContext<NavFlowT | null>(null);

export function useNavFlow(): NavFlowT | null {
  return React.useContext(NavFlowContext);
}
```

- [ ] **Step 2: useNavigate hook**

```ts
// packages/engine/src/nav/useNavigate.ts
"use client";
import { useNavFlow } from "./NavFlowContext";
import { evalExpression } from "../data/expressions";

/**
 * Resolves a transition trigger to a navigation. Returns a function
 * the caller invokes with optional params + a router-like nav object.
 *
 * Usage in dispatch:
 *   const navigate = useNavigate(ctx);
 *   onClick: () => navigate("signupClicked");
 */
export function useNavigate(ctx: { data?: any; user?: any } = {}) {
  const navFlow = useNavFlow();

  return function navigate(
    trigger: string,
    params: Record<string, unknown> = {},
  ): { url: string } | null {
    if (!navFlow) return null;

    const t = navFlow.transitions.find(x => x.trigger === trigger);
    if (!t) return null;

    let target = navFlow.pages.find(p => p.id === t.to);
    if (!target) return null;

    if (target.guard) {
      const guard = navFlow.guards[target.guard];
      if (guard) {
        const ok = evalExpression(guard.condition, { ...ctx.data, user: ctx.user });
        if (!ok) {
          target = navFlow.pages.find(p => p.id === guard.redirectTo) ?? target;
        }
      }
    }

    let url = target.route;
    for (const [k, v] of Object.entries(params)) {
      url = url.replace(`[${k}]`, encodeURIComponent(String(v)));
    }
    return { url };
  };
}
```

- [ ] **Step 3: Tests**

```tsx
// packages/engine/tests/nav.test.tsx
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { NavFlowContext } from "../src/nav/NavFlowContext";
import { useNavigate } from "../src/nav/useNavigate";

const sample = {
  version: "1.0",
  initialPage: "home",
  pages: [
    { id: "home",      route: "/",        title: "Home",      schemaFile: "x", params: [] },
    { id: "dashboard", route: "/dash",    title: "Dashboard", schemaFile: "x", params: [], guard: "auth" },
    { id: "login",     route: "/login",   title: "Login",     schemaFile: "x", params: [] },
    { id: "user",      route: "/u/[id]",  title: "User",      schemaFile: "x", params: ["id"] },
  ],
  transitions: [
    { id: "t1", from: "home",      trigger: "go-dash",   to: "dashboard" },
    { id: "t2", from: "home",      trigger: "view-user", to: "user" },
  ],
  guards: { auth: { redirectTo: "login", condition: "global.user.authed == true" } },
} as const;

function withNav(navFlow: any) {
  return ({ children }: any) =>
    <NavFlowContext.Provider value={navFlow}>{children}</NavFlowContext.Provider>;
}

describe("useNavigate", () => {
  it("resolves trigger to page url", () => {
    const { result } = renderHook(() => useNavigate(), { wrapper: withNav(sample) });
    expect(result.current("go-dash", {})).toEqual({ url: "/login" }); // guard fails (no authed user)
  });

  it("passes guard when condition holds", () => {
    const { result } = renderHook(
      () => useNavigate({ user: { authed: true } }), { wrapper: withNav(sample) });
    expect(result.current("go-dash", {})).toEqual({ url: "/dash" });
  });

  it("substitutes route params", () => {
    const { result } = renderHook(() => useNavigate(), { wrapper: withNav(sample) });
    expect(result.current("view-user", { id: "abc-123" })).toEqual({ url: "/u/abc-123" });
  });

  it("returns null for unknown trigger", () => {
    const { result } = renderHook(() => useNavigate(), { wrapper: withNav(sample) });
    expect(result.current("nope", {})).toBeNull();
  });
});
```

- [ ] **Step 4: Wire NavFlowContext into EngineProvider**

In `packages/engine/src/EngineProvider.tsx`, accept `navFlow` prop and wrap children:

```tsx
export interface EngineProviderProps {
  designSpec?: DesignSpec;
  navFlow?: NavFlowT | null;
  children: React.ReactNode;
}

export function EngineProvider({ designSpec, navFlow, children }: EngineProviderProps) {
  // ...existing register/tokens...
  return (
    <div data-tentoro-engine="" data-register={register}>
      <NavFlowContext.Provider value={navFlow ?? null}>
        <TokensProvider register={register as any} tokens={tokens as any}>
          {children}
        </TokensProvider>
      </NavFlowContext.Provider>
    </div>
  );
}
```

- [ ] **Step 5: Run tests, commit**

```bash
cd packages/engine && npx vitest run tests/nav.test.tsx
git add packages/engine/src/nav packages/engine/src/EngineProvider.tsx packages/engine/tests/nav.test.tsx
git commit -m "feat(engine): NavFlowContext + useNavigate hook"
```

---

### Task W1.5: Dispatch wires Button.onClick navigate through useNavigate

**Files:**
- Modify: `packages/renderer/src/runtime/dispatch.tsx`

When a Button (or any node) has `onClick: { action: "navigate", trigger: "..." }`, dispatch should turn that into a router push (Next.js).

- [ ] **Step 1: Add handler in dispatch.tsx**

In the action-handling branch (near where today's `onClick` props are converted to functions), add:

```ts
function buildClickHandler(action: any, navigate: ReturnType<typeof useNavigate>, router: any) {
  if (!action || typeof action !== "object") return undefined;
  if (action.action === "navigate" && navigate) {
    return () => {
      const r = navigate(action.trigger ?? action.to ?? "", action.params ?? {});
      if (r && router) router.push(r.url);
    };
  }
  // ...existing handlers (workflow, submitForm, etc.)
}
```

- [ ] **Step 2: Use Next.js router via useRouter import inside dispatch components**

Dispatch lives in the renderer; importing from `next/navigation` only works in Next.js apps. Solution: dispatch accepts an optional `router` via context (Engine provides it on Next.js platforms). For non-Next.js platforms (tests, RN) a noop router is fine.

```ts
// add: const RouterContext = createContext<{push:(url:string)=>void}|null>(null);
// in Engine: <RouterContext.Provider value={typeof window!=="undefined"?{push:url=>(window.location.href=url)}:null}>
// in dispatch: const router = useContext(RouterContext);
```

Test that a button with `onClick: { action: "navigate", trigger: "go-dash" }` renders an element whose click handler calls `router.push("/dash")` (mocked).

- [ ] **Step 3: Commit**

```bash
git add packages/renderer/src/runtime/dispatch.tsx
git commit -m "feat(renderer): dispatch navigate actions through useNavigate"
```

---

### Task W1.6: Standalone-app layout reads + provides nav-flow

**Files:**
- Modify: `backend/templates/standalone-app/src/app/layout.tsx`

After standalone-engine W-B1, layout.tsx already loads design-spec. Add nav-flow load:

```tsx
async function loadNavFlow() {
  try {
    const p = path.join(process.cwd(), "src", "contracts", "nav-flow.json");
    return JSON.parse(await fs.readFile(p, "utf8"));
  } catch { return null; }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const designSpec = await loadDesignSpec();
  const navFlow = await loadNavFlow();
  return (
    <html lang="en">
      <body>
        <EngineProvider designSpec={designSpec} navFlow={navFlow}>
          {children}
        </EngineProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 1: Edit + commit**

```bash
git add backend/templates/standalone-app/src/app/layout.tsx
git commit -m "feat(standalone): layout loads nav-flow and passes to EngineProvider"
```

---

## Workstream 2 — Editor Canvas (Stage 1: read-only live render)

### Task W2.1: Canvas component using the engine

**Files:**
- Create: `frontend/src/components/canvas/Canvas.tsx`
- Create: `frontend/src/components/canvas/CanvasFrame.tsx`
- Create: `frontend/src/components/canvas/hooks/useArtifacts.ts`

After standalone-engine W-A6 (Engine component) lands, this is a 30-line wrapper.

- [ ] **Step 1: useArtifacts hook — pulls schema + design-spec + nav-flow + preview data**

```ts
// frontend/src/components/canvas/hooks/useArtifacts.ts
"use client";
import { useQuery } from "@tanstack/react-query";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(path);
    if (!r.ok) return null;
    return r.json() as Promise<T>;
  } catch { return null; }
}

export function useArtifacts(projectId: string, pagePath: string) {
  const schema = useQuery({
    queryKey: ["schema", projectId, pagePath],
    queryFn: () => fetchJson(`${API}/api/projects/${projectId}/files/src/schemas/${pagePath}.json`),
    enabled: !!pagePath,
  });
  const designSpec = useQuery({
    queryKey: ["design-spec", projectId],
    queryFn: () => fetchJson(`${API}/api/projects/${projectId}/files/src/contracts/design-spec.json`),
  });
  const navFlow = useQuery({
    queryKey: ["nav-flow", projectId],
    queryFn: () => fetchJson(`${API}/api/projects/${projectId}/files/src/contracts/nav-flow.json`),
  });
  const previewData = useQuery({
    queryKey: ["preview-data", projectId],
    queryFn: () => fetchJson(`${API}/api/_debug/preview-data/${projectId}`) ?? {},
  });
  return { schema: schema.data, designSpec: designSpec.data,
           navFlow: navFlow.data, previewData: previewData.data ?? {},
           isLoading: schema.isLoading };
}
```

- [ ] **Step 2: Canvas component**

```tsx
// frontend/src/components/canvas/Canvas.tsx
"use client";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { useArtifacts } from "./hooks/useArtifacts";
import { CanvasFrame } from "./CanvasFrame";

export interface CanvasProps {
  projectId: string;
  pagePath: string;        // e.g. "home" or "users/detail"
  device?: "mobile" | "tablet" | "desktop";
}

export function Canvas({ projectId, pagePath, device = "desktop" }: CanvasProps) {
  const { schema, designSpec, navFlow, previewData, isLoading } =
    useArtifacts(projectId, pagePath);

  if (isLoading) {
    return <div className="p-12 text-muted-foreground">Loading {pagePath}…</div>;
  }
  if (!schema) {
    return <div className="p-12 text-muted-foreground">No schema at {pagePath}</div>;
  }

  return (
    <CanvasFrame device={device}>
      <EngineProvider designSpec={designSpec ?? {}} navFlow={navFlow}>
        <Engine schema={schema as any} previewData={previewData} />
      </EngineProvider>
    </CanvasFrame>
  );
}
```

- [ ] **Step 3: CanvasFrame — viewport device modes**

```tsx
// frontend/src/components/canvas/CanvasFrame.tsx
"use client";
import { ReactNode } from "react";

const DEVICE_WIDTH = { mobile: 375, tablet: 768, desktop: 1280 };

export function CanvasFrame({
  device, children,
}: { device: "mobile"|"tablet"|"desktop"; children: ReactNode }) {
  const w = DEVICE_WIDTH[device];
  return (
    <div className="bg-muted/40 min-h-screen p-8 overflow-auto">
      <div
        className="mx-auto bg-background shadow-lg border rounded-md overflow-hidden"
        style={{ width: w, minHeight: 600 }}
        data-canvas-frame=""
      >
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/canvas
git commit -m "feat(editor): Canvas component renders schema via @tentoroforge/engine"
```

---

### Task W2.2: Mount Canvas in the editor route + page picker

**Files:**
- Modify: `frontend/src/app/editor/[projectId]/page.tsx`
- Create: `frontend/src/components/editor/PagePicker.tsx`

The editor's current 3-tab layout (Editor / Preview / Score) collapses to: Canvas (main) + sidebar (page picker + later: properties panel).

- [ ] **Step 1: PagePicker — lists pages from nav-flow**

```tsx
// frontend/src/components/editor/PagePicker.tsx
"use client";
import { useQuery } from "@tanstack/react-query";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export function PagePicker({
  projectId, value, onChange,
}: { projectId: string; value: string; onChange: (slug: string) => void }) {
  const { data: navFlow } = useQuery({
    queryKey: ["nav-flow", projectId],
    queryFn: async () => {
      const r = await fetch(`${API}/api/projects/${projectId}/files/src/contracts/nav-flow.json`);
      return r.ok ? r.json() : { pages: [] };
    },
  });
  const pages = navFlow?.pages ?? [];
  return (
    <nav className="w-56 border-r p-2 space-y-1 bg-muted/30">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground px-2 py-1">
        Pages
      </h3>
      {pages.map((p: any) => (
        <button
          key={p.id}
          onClick={() => onChange(p.id)}
          className={`w-full text-left px-2 py-1.5 rounded text-sm ${
            p.id === value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
          }`}
        >
          {p.title}
          <div className="text-xs opacity-70">{p.route}</div>
        </button>
      ))}
    </nav>
  );
}
```

- [ ] **Step 2: Editor route layout**

```tsx
// frontend/src/app/editor/[projectId]/page.tsx
"use client";
import { use, useState } from "react";
import { PagePicker } from "@/components/editor/PagePicker";
import { Canvas } from "@/components/canvas/Canvas";

export default function EditorPage({
  params,
}: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  const [pageSlug, setPageSlug] = useState<string>("home");
  const [device, setDevice] = useState<"mobile"|"tablet"|"desktop">("desktop");

  return (
    <div className="flex h-screen">
      <PagePicker projectId={projectId} value={pageSlug} onChange={setPageSlug} />
      <main className="flex-1 flex flex-col">
        <header className="border-b px-4 py-2 flex gap-2">
          {(["mobile","tablet","desktop"] as const).map(d =>
            <button key={d} onClick={() => setDevice(d)}
              className={`text-sm px-3 py-1 rounded ${device===d?"bg-primary text-primary-foreground":""}`}>
              {d}
            </button>
          )}
        </header>
        <div className="flex-1 overflow-auto">
          <Canvas projectId={projectId} pagePath={pageSlug} device={device} />
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/editor/[projectId]/page.tsx frontend/src/components/editor/PagePicker.tsx
git commit -m "feat(editor): mount Canvas + PagePicker (drop old 3-tab layout)"
```

---

### Task W2.3: Drop the screenshot Preview tab + Playwright render-service round-trip

**Files:**
- Modify: `frontend/src/components/schema-editor/SchemaEditorPanel.tsx` (delete or repurpose)
- Modify: `frontend/src/components/schema-editor/PreviewTab.tsx` (delete)

- [ ] **Step 1: Audit usages**

```bash
grep -rn "PreviewTab\|SchemaEditorPanel" frontend/src 2>/dev/null
```

- [ ] **Step 2: Delete dead code; keep `CritiquePanel` + `PageScoreBadge` since they're orthogonal (vision-based scoring, different concern)**

```bash
rm frontend/src/components/schema-editor/PreviewTab.tsx
# SchemaEditorPanel can stay if other routes import it, otherwise delete
```

- [ ] **Step 3: Commit**

```bash
git add -A frontend/src/components/schema-editor
git commit -m "refactor(editor): drop screenshot PreviewTab — canvas is the live preview"
```

---

### Task W2.4: Smoke against Mark 3 + spike + validation projects

Verifies the editor canvas actually renders today's projects, end-to-end.

- [ ] **Step 1: Start the editor**

```bash
# Frontend already running on 6501 (per start-all.sh)
open http://localhost:6501/editor/db17s1zl
# Sign in if needed (admin@example.com / password123)
```

- [ ] **Step 2: Confirm canvas shows the same render as scaffold**

For each of `home`, `tasks`, `requests`, `approvals`: editor canvas (6501) and scaffold (6503) should look pixel-identical (modulo viewport device mode chrome).

- [ ] **Step 3: Confirm device modes work** — mobile/tablet/desktop toggle resizes the frame.

If anything diverges, file an issue. Note: the canvas must NOT use Playwright for this — it's the engine running in the browser directly.

---

## Workstream 3 — Mutation Layer (`@forge/patches`)

### Task W3.1: Patches package skeleton

**Files:**
- Create: `packages/patches/package.json`
- Create: `packages/patches/tsconfig.json`
- Create: `packages/patches/src/index.ts`

- [ ] **Step 1: package.json**

```json
{
  "name": "@forge/patches",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "module": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "files": ["dist"],
  "scripts": {
    "build": "tsup",
    "test": "vitest run"
  },
  "dependencies": {
    "@tentoroforge/schema": "workspace:*",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "tsup": "^8.0.0",
    "typescript": "^5.0.0",
    "vitest": "^1.0.0"
  }
}
```

- [ ] **Step 2: tsconfig + tsup mirror engine package**, commit

```bash
git add packages/patches
git commit -m "feat(patches): package skeleton"
```

---

### Task W3.2: Artifacts + EditorAction types

**Files:**
- Create: `packages/patches/src/types.ts`

- [ ] **Step 1: Type definitions**

```ts
// packages/patches/src/types.ts
import type { NavFlowT } from "@tentoroforge/schema";

export type NodeId = string;
export type PageId = string;

export interface SchemaNode {
  id: NodeId;
  type: string;
  props?: Record<string, unknown>;
  children?: SchemaNode[];
  slots?: Record<string, SchemaNode[]>;
  visibleIf?: string;
}

export interface PageSchema {
  schemaVersion: "2";
  id: PageId;
  route?: string;
  layout?: string;
  meta?: Record<string, unknown>;
  dataSources?: Array<{ name: string; source?: string; op?: string }>;
  root: SchemaNode;
}

export interface Tokens {
  color: Record<string, Record<string, string>>;
  typography: { fontFamily?: Record<string, string>; scale?: Record<string, number> };
  spacing: Record<string, number>;
  radius: Record<string, number>;
  shadow: Record<string, string>;
  motion: Record<string, string>;
  breakpoints: Record<string, number>;
}

/**
 * The full artifact set. Per Tentoro Forge convention, page schemas live
 * as N separate files keyed by page id; we represent them here as an
 * in-memory map for editor convenience. Persistence writes one file per
 * page back to src/schemas/.
 */
export interface Artifacts {
  pageSchemas: Record<PageId, PageSchema>;
  navFlow: NavFlowT;
  tokens: Tokens;
}

// ---------------- EditorAction union ----------------

export type PropPath = string;          // e.g. "label" or "style.color"
export type PropValue = unknown;

export type EditorAction =
  | { type: "insertNode"; pageId: PageId; parentId: NodeId; index: number; node: SchemaNode }
  | { type: "removeNode"; pageId: PageId; nodeId: NodeId }
  | { type: "moveNode"; pageId: PageId; nodeId: NodeId; newParentId: NodeId; newIndex: number }
  | { type: "duplicateNode"; pageId: PageId; nodeId: NodeId }
  | { type: "updateProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; value: PropValue }
  | { type: "bindProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; binding: string }
  | { type: "unbindProp"; pageId: PageId; nodeId: NodeId; propName: PropPath; literalValue: PropValue }
  | { type: "addPage"; pageId: PageId; route: string; title: string; root: SchemaNode }
  | { type: "removePage"; pageId: PageId }
  | { type: "renamePage"; pageId: PageId; title: string }
  | { type: "updateRoute"; pageId: PageId; route: string }
  | { type: "setInitialPage"; pageId: PageId }
  | { type: "addTransition"; transition: NavFlowT["transitions"][number] }
  | { type: "removeTransition"; transitionId: string }
  | { type: "setGuard"; pageId: PageId; guard: string | null }
  | { type: "updateToken"; path: string[]; value: unknown }
  | { type: "addToken"; path: string[]; value: unknown }
  | { type: "removeToken"; path: string[] }
  | { type: "renameToken"; oldPath: string[]; newPath: string[] }
  | { type: "replaceArtifacts"; artifacts: Artifacts; rationale?: string };

export interface ApplyResult {
  next: Artifacts;
  inverse: EditorAction;
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/patches/src/types.ts
git commit -m "feat(patches): EditorAction union + Artifacts type"
```

---

### Task W3.3: applyAction + inverse generation

**Files:**
- Create: `packages/patches/src/apply.ts`
- Create: `packages/patches/tests/apply.test.ts`

This is the load-bearing function. Each action type has its own apply + inverse. Tests-first.

- [ ] **Step 1: Tests covering each action (~20 tests)**

```ts
// packages/patches/tests/apply.test.ts
import { describe, it, expect } from "vitest";
import { applyAction } from "../src/apply";
import type { Artifacts } from "../src/types";

function fixture(): Artifacts {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2", id: "home", route: "/",
        root: {
          id: "n1", type: "Stack", children: [
            { id: "n2", type: "Text", props: { text: "Hello" } },
          ],
        },
      },
    },
    navFlow: {
      version: "1.0", initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [], guards: {},
    },
    tokens: { color: {}, typography: {}, spacing: {}, radius: {}, shadow: {}, motion: {}, breakpoints: {} } as any,
  };
}

describe("applyAction", () => {
  it("updateProp updates a prop", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "World"
    });
    expect((next.pageSchemas.home.root.children![0].props as any).text).toBe("World");
    expect(inverse).toEqual({
      type: "updateProp", pageId: "home", nodeId: "n2", propName: "text", value: "Hello"
    });
  });

  it("updateProp on missing node throws", () => {
    expect(() => applyAction(fixture(), {
      type: "updateProp", pageId: "home", nodeId: "missing", propName: "x", value: 1
    })).toThrow();
  });

  it("insertNode inserts at the given index", () => {
    const node = { id: "n3", type: "Text", props: { text: "Two" } };
    const { next } = applyAction(fixture(), {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1, node
    });
    expect(next.pageSchemas.home.root.children!.length).toBe(2);
    expect(next.pageSchemas.home.root.children![1].id).toBe("n3");
  });

  it("insertNode's inverse removes the inserted node", () => {
    const node = { id: "n3", type: "Text", props: { text: "Two" } };
    const { next, inverse } = applyAction(fixture(), {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1, node
    });
    expect(inverse).toEqual({ type: "removeNode", pageId: "home", nodeId: "n3" });
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children!.length).toBe(1);
  });

  it("removeNode round-trips with its inverse", () => {
    const start = fixture();
    const { next, inverse } = applyAction(start, {
      type: "removeNode", pageId: "home", nodeId: "n2",
    });
    expect(next.pageSchemas.home.root.children!.length).toBe(0);
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children![0].id).toBe("n2");
  });

  it("moveNode updates parent + index", () => {
    const start = fixture();
    // First add a sibling container
    const withCol = applyAction(start, {
      type: "insertNode", pageId: "home", parentId: "n1", index: 1,
      node: { id: "n3", type: "Stack", children: [] }
    }).next;
    const { next, inverse } = applyAction(withCol, {
      type: "moveNode", pageId: "home", nodeId: "n2", newParentId: "n3", newIndex: 0
    });
    expect(next.pageSchemas.home.root.children![0].children).toEqual([]);
    expect(next.pageSchemas.home.root.children![1].children![0].id).toBe("n2");
    expect(inverse).toEqual({
      type: "moveNode", pageId: "home", nodeId: "n2", newParentId: "n1", newIndex: 0
    });
  });

  it("addPage adds to both pageSchemas and navFlow atomically", () => {
    const { next } = applyAction(fixture(), {
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "ar", type: "Stack", children: [] }
    });
    expect(next.pageSchemas.about).toBeDefined();
    expect(next.navFlow.pages.find(p => p.id === "about")).toBeDefined();
  });

  it("addPage inverse removes from both", () => {
    const { next, inverse } = applyAction(fixture(), {
      type: "addPage", pageId: "about", route: "/about", title: "About",
      root: { id: "ar", type: "Stack", children: [] }
    });
    expect(inverse).toEqual({ type: "removePage", pageId: "about" });
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.about).toBeUndefined();
    expect(undone.navFlow.pages.find(p => p.id === "about")).toBeUndefined();
  });

  it("renameToken cascades through pageSchemas", () => {
    const start = fixture();
    start.tokens.color = { brand: { primary: "#13A8A8" } };
    start.pageSchemas.home.root.children![0].props = { color: "color.brand.primary" };
    const { next, inverse } = applyAction(start, {
      type: "renameToken",
      oldPath: ["color", "brand", "primary"],
      newPath: ["color", "brand", "main"],
    });
    expect((next.pageSchemas.home.root.children![0].props as any).color)
      .toBe("color.brand.main");
    // Inverse rewrites back
    const { next: undone } = applyAction(next, inverse);
    expect((undone.pageSchemas.home.root.children![0].props as any).color)
      .toBe("color.brand.primary");
  });

  it("replaceArtifacts wholesale + inverse restores prior", () => {
    const start = fixture();
    const fresh: Artifacts = JSON.parse(JSON.stringify(start));
    fresh.pageSchemas.home.root.children = [];
    const { next, inverse } = applyAction(start, {
      type: "replaceArtifacts", artifacts: fresh
    });
    expect(next.pageSchemas.home.root.children).toEqual([]);
    expect(inverse.type).toBe("replaceArtifacts");
    const { next: undone } = applyAction(next, inverse);
    expect(undone.pageSchemas.home.root.children![0].id).toBe("n2");
  });
});
```

- [ ] **Step 2: Implementation skeleton**

```ts
// packages/patches/src/apply.ts
import type {
  Artifacts, EditorAction, ApplyResult, SchemaNode, NodeId, PageId,
} from "./types";

// ---------------------------------------------------------------------------
// Helper: find a node + its parent in a page.
// ---------------------------------------------------------------------------
function findNode(
  root: SchemaNode, nodeId: NodeId,
  parent: SchemaNode | null = null,
): { node: SchemaNode; parent: SchemaNode | null; index: number } | null {
  if (root.id === nodeId) return { node: root, parent, index: -1 };
  const kids = root.children || [];
  for (let i = 0; i < kids.length; i++) {
    if (kids[i].id === nodeId) return { node: kids[i], parent: root, index: i };
    const inner = findNode(kids[i], nodeId, root);
    if (inner) return inner;
  }
  return null;
}

// Deep clone — keeps applyAction pure by mutating only the clone.
function clone<T>(x: T): T { return JSON.parse(JSON.stringify(x)); }

// Rewrite a token reference everywhere in a schema tree.
function rewriteTokenRefs(node: SchemaNode, from: string, to: string) {
  if (node.props) {
    for (const k of Object.keys(node.props)) {
      const v = node.props[k];
      if (typeof v === "string" && v === from) node.props[k] = to;
    }
  }
  (node.children || []).forEach(c => rewriteTokenRefs(c, from, to));
}

// ---------------------------------------------------------------------------
// Main apply switch.
// ---------------------------------------------------------------------------
export function applyAction(
  artifacts: Artifacts, action: EditorAction,
): ApplyResult {
  const next = clone(artifacts);

  switch (action.type) {
    case "updateProp": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`unknown page ${action.pageId}`);
      const hit = findNode(page.root, action.nodeId);
      if (!hit) throw new Error(`unknown node ${action.nodeId}`);
      hit.node.props = hit.node.props || {};
      const prev = hit.node.props[action.propName];
      hit.node.props[action.propName] = action.value;
      return { next, inverse: { ...action, value: prev } };
    }

    case "insertNode": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.parentId);
      if (!hit) throw new Error(`unknown parent ${action.parentId}`);
      hit.node.children = hit.node.children || [];
      hit.node.children.splice(action.index, 0, clone(action.node));
      return { next, inverse: {
        type: "removeNode", pageId: action.pageId, nodeId: action.node.id,
      }};
    }

    case "removeNode": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.nodeId);
      if (!hit || !hit.parent) throw new Error(`cannot remove root`);
      hit.parent.children!.splice(hit.index, 1);
      return { next, inverse: {
        type: "insertNode", pageId: action.pageId, parentId: hit.parent.id,
        index: hit.index, node: clone(hit.node),
      }};
    }

    case "moveNode": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.nodeId);
      if (!hit || !hit.parent) throw new Error(`cannot move root`);
      const oldParentId = hit.parent.id;
      const oldIndex = hit.index;
      const removed = hit.parent.children!.splice(hit.index, 1)[0];
      const newParent = findNode(page.root, action.newParentId);
      if (!newParent) throw new Error(`unknown new parent`);
      newParent.node.children = newParent.node.children || [];
      newParent.node.children.splice(action.newIndex, 0, removed);
      return { next, inverse: {
        type: "moveNode", pageId: action.pageId, nodeId: action.nodeId,
        newParentId: oldParentId, newIndex: oldIndex,
      }};
    }

    case "duplicateNode": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.nodeId);
      if (!hit || !hit.parent) throw new Error(`cannot dup root`);
      const copy = clone(hit.node);
      copy.id = `${copy.id}-copy-${Date.now().toString(36)}`;
      // Re-id children too — left as an exercise in normalize() later
      hit.parent.children!.splice(hit.index + 1, 0, copy);
      return { next, inverse: {
        type: "removeNode", pageId: action.pageId, nodeId: copy.id,
      }};
    }

    case "bindProp": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.nodeId);
      if (!hit) throw new Error(`unknown node`);
      hit.node.props = hit.node.props || {};
      const prev = hit.node.props[action.propName];
      hit.node.props[action.propName] = { $binding: action.binding };
      return { next, inverse: {
        type: "unbindProp", pageId: action.pageId, nodeId: action.nodeId,
        propName: action.propName, literalValue: prev,
      }};
    }

    case "unbindProp": {
      const page = next.pageSchemas[action.pageId];
      const hit = findNode(page.root, action.nodeId);
      if (!hit) throw new Error(`unknown node`);
      hit.node.props = hit.node.props || {};
      const prev = hit.node.props[action.propName];
      hit.node.props[action.propName] = action.literalValue;
      const binding = (prev as any)?.$binding;
      return { next, inverse: {
        type: "bindProp", pageId: action.pageId, nodeId: action.nodeId,
        propName: action.propName, binding: binding ?? "",
      }};
    }

    case "addPage": {
      next.pageSchemas[action.pageId] = {
        schemaVersion: "2", id: action.pageId, route: action.route, root: action.root,
      };
      next.navFlow.pages.push({
        id: action.pageId, route: action.route, title: action.title,
        schemaFile: `src/schemas/${action.pageId}.json`, params: [],
      });
      return { next, inverse: { type: "removePage", pageId: action.pageId }};
    }

    case "removePage": {
      const page = next.pageSchemas[action.pageId];
      if (!page) throw new Error(`unknown page`);
      const navEntry = next.navFlow.pages.find(p => p.id === action.pageId)!;
      delete next.pageSchemas[action.pageId];
      next.navFlow.pages = next.navFlow.pages.filter(p => p.id !== action.pageId);
      // Also scrub transitions that reference this page
      const removedTransitions = next.navFlow.transitions.filter(
        t => t.from === action.pageId || t.to === action.pageId
      );
      next.navFlow.transitions = next.navFlow.transitions.filter(
        t => t.from !== action.pageId && t.to !== action.pageId
      );
      return { next, inverse: {
        type: "addPage", pageId: action.pageId, route: navEntry.route,
        title: navEntry.title, root: page.root,
      }};
    }

    case "renamePage": {
      const navEntry = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navEntry) throw new Error(`unknown page`);
      const prev = navEntry.title;
      navEntry.title = action.title;
      return { next, inverse: { ...action, title: prev }};
    }

    case "updateRoute": {
      const navEntry = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navEntry) throw new Error(`unknown page`);
      const prev = navEntry.route;
      navEntry.route = action.route;
      const page = next.pageSchemas[action.pageId];
      if (page) page.route = action.route;
      return { next, inverse: { ...action, route: prev }};
    }

    case "setInitialPage": {
      const prev = next.navFlow.initialPage;
      next.navFlow.initialPage = action.pageId;
      return { next, inverse: { ...action, pageId: prev }};
    }

    case "addTransition": {
      next.navFlow.transitions.push(action.transition);
      return { next, inverse: {
        type: "removeTransition", transitionId: action.transition.id,
      }};
    }

    case "removeTransition": {
      const removed = next.navFlow.transitions.find(t => t.id === action.transitionId);
      if (!removed) throw new Error(`unknown transition`);
      next.navFlow.transitions = next.navFlow.transitions.filter(
        t => t.id !== action.transitionId);
      return { next, inverse: { type: "addTransition", transition: removed }};
    }

    case "setGuard": {
      const navEntry = next.navFlow.pages.find(p => p.id === action.pageId);
      if (!navEntry) throw new Error(`unknown page`);
      const prev = navEntry.guard ?? null;
      navEntry.guard = action.guard ?? undefined;
      return { next, inverse: { ...action, guard: prev }};
    }

    case "updateToken": {
      const get = (o: any, path: string[]): any =>
        path.reduce((acc, k) => acc?.[k], o);
      const set = (o: any, path: string[], v: unknown): void => {
        let cur = o;
        for (let i = 0; i < path.length - 1; i++) {
          cur[path[i]] = cur[path[i]] || {};
          cur = cur[path[i]];
        }
        cur[path[path.length - 1]] = v;
      };
      const prev = get(next.tokens, action.path);
      set(next.tokens, action.path, action.value);
      return { next, inverse: { ...action, value: prev }};
    }

    case "renameToken": {
      const fromRef = action.oldPath.join(".");
      const toRef = action.newPath.join(".");
      Object.values(next.pageSchemas).forEach(p => rewriteTokenRefs(p.root, fromRef, toRef));
      // Also move the token value
      const get = (o: any, path: string[]): any => path.reduce((a, k) => a?.[k], o);
      const set = (o: any, path: string[], v: unknown) => {
        let cur = o;
        for (let i = 0; i < path.length - 1; i++) {
          cur[path[i]] = cur[path[i]] || {}; cur = cur[path[i]];
        }
        cur[path[path.length - 1]] = v;
      };
      const v = get(next.tokens, action.oldPath);
      set(next.tokens, action.newPath, v);
      // Remove old
      const parent = action.oldPath.slice(0, -1).reduce((a: any, k) => a[k], next.tokens);
      delete parent[action.oldPath[action.oldPath.length - 1]];
      return { next, inverse: {
        type: "renameToken", oldPath: action.newPath, newPath: action.oldPath,
      }};
    }

    case "addToken":
    case "removeToken":
      // Similar to updateToken/renameToken — skeleton; fill in per token shape.
      throw new Error(`addToken/removeToken — implement when first needed`);

    case "replaceArtifacts": {
      return { next: clone(action.artifacts), inverse: {
        type: "replaceArtifacts", artifacts: artifacts,
        rationale: "undo replaceArtifacts",
      }};
    }
  }
}
```

- [ ] **Step 3: Run tests — all ~10 cases pass**

```bash
cd packages/patches && npx vitest run
```

- [ ] **Step 4: Commit**

```bash
git add packages/patches/src/apply.ts packages/patches/tests/apply.test.ts
git commit -m "feat(patches): applyAction + typed inverses for every action type"
```

---

### Task W3.4: Undo stack hook

**Files:**
- Create: `frontend/src/lib/editor-store.ts`

- [ ] **Step 1: Zustand-style store wrapping artifacts + undo/redo**

```ts
// frontend/src/lib/editor-store.ts
import { create } from "zustand";
import { applyAction, type Artifacts, type EditorAction } from "@forge/patches";

interface State {
  artifacts: Artifacts | null;
  undoStack: EditorAction[];    // inverses
  redoStack: EditorAction[];

  setInitial: (a: Artifacts) => void;
  dispatch: (action: EditorAction) => void;
  undo: () => void;
  redo: () => void;
}

export const useEditorStore = create<State>((set, get) => ({
  artifacts: null,
  undoStack: [],
  redoStack: [],

  setInitial: (a) => set({ artifacts: a, undoStack: [], redoStack: [] }),

  dispatch: (action) => {
    const cur = get().artifacts;
    if (!cur) return;
    const { next, inverse } = applyAction(cur, action);
    set(s => ({
      artifacts: next,
      undoStack: [...s.undoStack, inverse],
      redoStack: [],   // any new action clears redo
    }));
  },

  undo: () => {
    const { artifacts, undoStack } = get();
    if (!artifacts || undoStack.length === 0) return;
    const inv = undoStack[undoStack.length - 1];
    const { next, inverse: redoInv } = applyAction(artifacts, inv);
    set(s => ({
      artifacts: next,
      undoStack: s.undoStack.slice(0, -1),
      redoStack: [...s.redoStack, redoInv],
    }));
  },

  redo: () => {
    const { artifacts, redoStack } = get();
    if (!artifacts || redoStack.length === 0) return;
    const redoAction = redoStack[redoStack.length - 1];
    const { next, inverse } = applyAction(artifacts, redoAction);
    set(s => ({
      artifacts: next,
      redoStack: s.redoStack.slice(0, -1),
      undoStack: [...s.undoStack, inverse],
    }));
  },
}));
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/editor-store.ts
git commit -m "feat(editor): zustand store with undo/redo via @forge/patches"
```

---

### Task W3.5: Persistence — auto-save after debounce

**Files:**
- Create: `frontend/src/lib/persistence.ts`

After each dispatch, debounce 500ms and POST changed artifacts to the backend.

- [ ] **Step 1: Persistence helper**

```ts
// frontend/src/lib/persistence.ts
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

async function saveFile(projectId: string, relPath: string, content: string) {
  await fetch(`${API}/api/projects/${projectId}/files`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: relPath, content }),
  });
}

export function buildPersister(projectId: string) {
  let timer: number | null = null;
  return (artifacts: any) => {
    if (timer) clearTimeout(timer);
    timer = window.setTimeout(async () => {
      // Write each page schema individually
      for (const [pageId, page] of Object.entries(artifacts.pageSchemas || {})) {
        await saveFile(projectId, `src/schemas/${pageId}.json`, JSON.stringify(page, null, 2));
      }
      await saveFile(projectId, "src/contracts/nav-flow.json",
        JSON.stringify(artifacts.navFlow, null, 2));
      await saveFile(projectId, "src/contracts/tokens.json",
        JSON.stringify(artifacts.tokens, null, 2));
    }, 500);
  };
}
```

- [ ] **Step 2: Wire into the store as a subscriber + commit**

```ts
// in editor-store.ts after store definition:
let unsubscribe: (() => void) | null = null;
export function attachPersister(projectId: string) {
  if (unsubscribe) unsubscribe();
  const persist = buildPersister(projectId);
  unsubscribe = useEditorStore.subscribe(state => {
    if (state.artifacts) persist(state.artifacts);
  });
}
```

```bash
git add frontend/src/lib/persistence.ts frontend/src/lib/editor-store.ts
git commit -m "feat(editor): debounced auto-save of artifacts after each dispatch"
```

---

## Workstream 4 — Component Registry (canonical)

### Task W4.1: Registry types + starter set

**Files:**
- Create: `packages/registry/src/types.ts`
- Create: `packages/registry/src/starter.ts`

The registry is the single source of truth for component metadata. The palette renders from it, the properties panel derives controls from it, the engine maps node.type to React components via it, and the LLM is constrained to it.

- [ ] **Step 1: Types**

```ts
// packages/registry/src/types.ts
export type ControlType =
  | "text" | "textarea" | "number" | "select" | "toggle"
  | "color" | "spacing" | "binding" | "actionPicker" | "iconPicker";

export interface PropDescriptor {
  type: "string" | "number" | "boolean" | "enum" | "action" | "binding";
  default?: unknown;
  options?: readonly string[];          // for enum
  control: ControlType;
  group: "content" | "style" | "state" | "behavior" | "data";
  description?: string;
}

export type SlotRule =
  | { type: "leaf" }
  | { type: "single"; accepts?: readonly string[] }
  | { type: "list";   accepts?: readonly string[]; rejects?: readonly string[]; maxChildren?: number };

export interface RegistryEntry {
  name: string;
  category: "layout" | "input" | "display" | "navigation" | "feedback" | "data";
  icon?: string;
  description?: string;
  slots: SlotRule;
  props: Record<string, PropDescriptor>;
}

export type Registry = Record<string, RegistryEntry>;
```

- [ ] **Step 2: Starter set — mirror spec §13**

```ts
// packages/registry/src/starter.ts
import type { Registry } from "./types";

export const starterRegistry: Registry = {
  Container: {
    name: "Container", category: "layout", icon: "Square",
    description: "Flex layout container",
    slots: { type: "list" },
    props: {
      direction: { type:"enum", options:["vertical","horizontal"], default:"vertical", control:"select", group:"style" },
      gap:       { type:"enum", options:["xs","sm","md","lg","xl"], default:"md", control:"select", group:"style" },
      padding:   { type:"enum", options:["none","xs","sm","md","lg","xl"], default:"md", control:"select", group:"style" },
      align:     { type:"enum", options:["start","center","end","stretch"], default:"stretch", control:"select", group:"style" },
      justify:   { type:"enum", options:["start","center","end","between","around"], default:"start", control:"select", group:"style" },
      wrap:      { type:"boolean", default:false, control:"toggle", group:"style" },
    },
  },
  Heading: {
    name: "Heading", category: "display", icon: "Type",
    slots: { type: "leaf" },
    props: {
      content: { type:"string", default:"Heading", control:"text", group:"content" },
      level:   { type:"enum", options:["1","2","3","4"], default:"1", control:"select", group:"style" },
    },
  },
  Input: {
    name: "Input", category: "input", icon: "MousePointer",
    slots: { type: "leaf" },
    props: {
      label:       { type:"string", default:"", control:"text", group:"content" },
      placeholder: { type:"string", default:"", control:"text", group:"content" },
      type:        { type:"enum", options:["text","email","password","number"], default:"text", control:"select", group:"behavior" },
      binding:     { type:"binding", default:null, control:"binding", group:"data" },
    },
  },
  Button: {
    name: "Button", category: "input", icon: "MousePointer",
    slots: { type: "leaf" },
    props: {
      label:    { type:"string", default:"Button", control:"text", group:"content" },
      variant:  { type:"enum", options:["primary","secondary","ghost"], default:"primary", control:"select", group:"style" },
      size:     { type:"enum", options:["sm","md","lg"], default:"md", control:"select", group:"style" },
      disabled: { type:"boolean", default:false, control:"toggle", group:"state" },
      onClick:  { type:"action", default:null, control:"actionPicker", group:"behavior" },
    },
  },
  // ... continue with Form, Select, Card, Grid, Avatar, Hero, Section, etc.
  // Use spec §13 as the reference list.
};
```

- [ ] **Step 3: Build digest function for LLM prompts**

```ts
// packages/registry/src/digest.ts
import type { Registry } from "./types";

export function registryDigest(registry: Registry): string {
  return Object.values(registry).map(e => {
    const slots = e.slots.type === "list" ? "[…children]"
                : e.slots.type === "single" ? "[child]"
                : "(leaf)";
    const props = Object.entries(e.props).map(([n, d]) =>
      d.type === "enum" ? `${n}:${(d.options||[]).join("|")}` : `${n}:${d.type}`
    ).join(", ");
    return `${e.name} ${slots}  { ${props} }`;
  }).join("\n");
}
```

- [ ] **Step 4: Commit**

```bash
git add packages/registry
git commit -m "feat(registry): canonical types + starter set + digest"
```

---

### Task W4.2: Migrate component .schema.ts files to registry entries

**Files:**
- Modify: `packages/library/src/components/*/index.ts`

For each component: add `export const registryEntry: RegistryEntry = { ... }` derived from the existing Zod schema. The single registry imports them all.

This is mechanical — automate via a script if needed.

- [ ] **Step 1: Pattern for one component (Button)**

```ts
// packages/library/src/components/Button/index.ts
export { Button } from "./Button";
export type { ButtonProps } from "./Button";
export { ButtonPropsSchema } from "./Button.schema";

// NEW: registry entry
import type { RegistryEntry } from "@forge/registry";
export const buttonRegistryEntry: RegistryEntry = {
  name: "Button", category: "input", icon: "MousePointer",
  slots: { type: "leaf" },
  props: { /* same as starter.ts */ },
};
```

- [ ] **Step 2: Aggregate**

```ts
// packages/library/src/registry.ts
import { buttonRegistryEntry } from "./components/Button";
import { heroRegistryEntry } from "./components/Hero";
// ... etc
export const libraryRegistry = {
  Button: buttonRegistryEntry,
  Hero: heroRegistryEntry,
  // ...
};
```

- [ ] **Step 3: Commit per-batch (don't try to do all 30+ in one commit)**

---

## Workstream 5 — Selection Overlay (Stage 2)

### Task W5.1: Engine emits stable data-node-id on every rendered element

**Files:**
- Modify: `packages/renderer/src/runtime/dispatch.tsx`

Every node already has an `id`. We just need the rendered DOM element to carry it.

- [ ] **Step 1: Wrap the rendered output with the id**

```tsx
function renderNode(node: any, ctx: any): ReactNode {
  // ... existing rendering ...
  return (
    <div data-node-id={node.id} className="contents">
      {originalRendered}
    </div>
  );
}
```

The `className="contents"` keeps layout unchanged — the wrapper participates in the DOM tree but inherits parent layout. This is what enables `getBoundingClientRect` lookup without layout drift.

Verify: spike + Mark 3 renders are unchanged visually.

- [ ] **Step 2: Commit**

```bash
git add packages/renderer/src/runtime/dispatch.tsx
git commit -m "feat(renderer): wrap nodes in display:contents div with data-node-id"
```

---

### Task W5.2: useSelection hook + click-to-select

**Files:**
- Create: `frontend/src/components/canvas/hooks/useSelection.ts`
- Modify: `frontend/src/lib/editor-store.ts` (add selection state)

- [ ] **Step 1: Add selection slice to the store**

```ts
// inside editor-store.ts state:
selectedNodeId: string | null,
setSelection: (id: string | null) => void,
```

- [ ] **Step 2: useSelection — finds nearest data-node-id under click target**

```ts
// frontend/src/components/canvas/hooks/useSelection.ts
import { useEditorStore } from "@/lib/editor-store";

export function useCanvasClick() {
  const set = useEditorStore(s => s.setSelection);
  return (e: React.MouseEvent) => {
    const t = (e.target as HTMLElement).closest("[data-node-id]") as HTMLElement | null;
    if (t) {
      e.preventDefault();
      e.stopPropagation();
      set(t.getAttribute("data-node-id"));
    }
  };
}
```

- [ ] **Step 3: Mount on Canvas wrapping div, commit**

```tsx
// in CanvasFrame:
<div onClick={useCanvasClick()}>{children}</div>
```

```bash
git commit -am "feat(editor): click-to-select via data-node-id"
```

---

### Task W5.3: SelectionOverlay — bounding box + handles

**Files:**
- Create: `frontend/src/components/canvas/SelectionOverlay.tsx`

Renders an absolutely-positioned overlay on top of the canvas with the selection rect drawn around the selected node's bounding box. Re-measures via `ResizeObserver` so resizes (e.g. text length change) keep the rect tight.

- [ ] **Step 1: Implementation**

```tsx
"use client";
import { useEffect, useState } from "react";
import { useEditorStore } from "@/lib/editor-store";

export function SelectionOverlay({ canvasRef }: { canvasRef: React.RefObject<HTMLElement> }) {
  const selectedId = useEditorStore(s => s.selectedNodeId);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (!selectedId || !canvasRef.current) { setRect(null); return; }
    const el = canvasRef.current.querySelector<HTMLElement>(`[data-node-id="${selectedId}"]`);
    if (!el) { setRect(null); return; }

    const update = () => setRect(el.getBoundingClientRect());
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => { ro.disconnect();
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update); };
  }, [selectedId, canvasRef]);

  if (!rect) return null;
  return (
    <div className="pointer-events-none fixed z-50 ring-2 ring-primary ring-offset-1"
         style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
         data-tentoro-selection-overlay="" />
  );
}
```

- [ ] **Step 2: Mount in Canvas + commit**

```bash
git commit -am "feat(editor): SelectionOverlay with ResizeObserver re-measure"
```

---

## Workstream 6 — Properties Panel from Registry

### Task W6.1: PropControls — one component per control type

**Files:**
- Create: `frontend/src/components/properties/PropControls/{Text,Select,Toggle,Color,Action}Control.tsx`

- [ ] **Step 1: Stub controls (text shown — others mirror)**

```tsx
// TextControl.tsx
export function TextControl({ value, onChange, label }:
  { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <input className="border rounded px-2 py-1" value={value ?? ""}
             onChange={e => onChange(e.target.value)} />
    </label>
  );
}
```

Repeat for Select (HTML select), Toggle (checkbox), Color (color picker), Action (textarea for JSON action descriptor — proper picker comes later).

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/properties/PropControls
git commit -m "feat(properties): individual control components"
```

---

### Task W6.2: PropertiesPanel reads selection + dispatches updateProp

**Files:**
- Create: `frontend/src/components/properties/PropertiesPanel.tsx`

- [ ] **Step 1: Implementation**

```tsx
"use client";
import { useEditorStore } from "@/lib/editor-store";
import { libraryRegistry } from "@tentoroforge/library/registry";
import { TextControl, SelectControl, ToggleControl } from "./PropControls";

const CONTROL = {
  text: TextControl, select: SelectControl, toggle: ToggleControl,
  // color, actionPicker, ... fall back to text for v1
} as const;

export function PropertiesPanel() {
  const { artifacts, selectedNodeId, dispatch } = useEditorStore(s => s);
  if (!artifacts || !selectedNodeId) return <aside className="w-72 border-l p-4 text-sm text-muted-foreground">Select a node</aside>;

  // Walk all page schemas, find the selected node
  let foundPageId: string | null = null;
  let foundNode: any = null;
  for (const [pid, page] of Object.entries(artifacts.pageSchemas)) {
    const stack = [page.root];
    while (stack.length) {
      const n = stack.pop()!;
      if (n.id === selectedNodeId) { foundNode = n; foundPageId = pid; break; }
      if (n.children) stack.push(...n.children);
    }
    if (foundNode) break;
  }
  if (!foundNode || !foundPageId) return <aside>Node not found</aside>;

  const entry = libraryRegistry[foundNode.type];
  if (!entry) return <aside>No registry entry for {foundNode.type}</aside>;

  const groups = ["content", "style", "state", "behavior", "data"];
  return (
    <aside className="w-72 border-l p-4 space-y-4 overflow-y-auto">
      <h3 className="text-sm font-semibold">{foundNode.type}</h3>
      <p className="text-xs text-muted-foreground">{foundNode.id}</p>
      {groups.map(group => {
        const propsInGroup = Object.entries(entry.props).filter(([, d]) => d.group === group);
        if (propsInGroup.length === 0) return null;
        return (
          <fieldset key={group} className="space-y-2">
            <legend className="text-xs uppercase tracking-wide text-muted-foreground">{group}</legend>
            {propsInGroup.map(([name, descriptor]) => {
              const Control = (CONTROL as any)[descriptor.control] ?? TextControl;
              const value = (foundNode.props as any)?.[name] ?? descriptor.default;
              return (
                <Control key={name} label={name} value={value}
                  options={descriptor.options}
                  onChange={(v: any) => dispatch({
                    type: "updateProp", pageId: foundPageId!,
                    nodeId: selectedNodeId, propName: name, value: v,
                  })} />
              );
            })}
          </fieldset>
        );
      })}
    </aside>
  );
}
```

- [ ] **Step 2: Mount in editor route, commit**

```bash
git add frontend/src/components/properties/PropertiesPanel.tsx
git commit -m "feat(properties): registry-driven panel that dispatches updateProp"
```

---

### Task W6.3: Bind/Literal toggle

**Files:**
- Create: `frontend/src/components/properties/BindToggle.tsx`

- [ ] **Step 1: Toggle button next to every prop control**

```tsx
export function BindToggle({
  isBound, onToggle,
}: { isBound: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle}
      className={`text-xs px-1.5 py-0.5 rounded ${isBound ? "bg-primary text-primary-foreground" : "border"}`}
      title={isBound ? "Bound — click to unbind" : "Literal — click to bind"}>
      {isBound ? "{ }" : "Aa"}
    </button>
  );
}
```

Wired into PropertiesPanel: clicking dispatches `bindProp` or `unbindProp`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/properties/BindToggle.tsx
git commit -m "feat(properties): bind/literal toggle per prop"
```

---

## Workstream 7 — Drag-and-Drop Palette

### Task W7.1: Palette component reads registry

**Files:**
- Create: `frontend/src/components/palette/Palette.tsx`

- [ ] **Step 1: Implementation**

```tsx
"use client";
import { libraryRegistry } from "@tentoroforge/library/registry";

export function Palette({ onDragStart }: { onDragStart: (componentName: string) => void }) {
  const byCategory = Object.values(libraryRegistry).reduce((acc, e) => {
    (acc[e.category] = acc[e.category] || []).push(e);
    return acc;
  }, {} as Record<string, typeof libraryRegistry[keyof typeof libraryRegistry][]>);

  return (
    <aside className="w-48 border-r p-2 space-y-3 overflow-y-auto">
      {Object.entries(byCategory).map(([cat, entries]) => (
        <div key={cat}>
          <h4 className="text-xs uppercase tracking-wide text-muted-foreground px-1 py-1">{cat}</h4>
          {entries.map(e => (
            <div key={e.name}
              draggable
              onDragStart={ev => { ev.dataTransfer.setData("text/x-forge-component", e.name); onDragStart(e.name); }}
              className="px-2 py-1.5 rounded cursor-grab hover:bg-muted text-sm">
              {e.name}
            </div>
          ))}
        </div>
      ))}
    </aside>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/palette
git commit -m "feat(palette): registry-driven drag sources"
```

---

### Task W7.2: Drop zones + drop validation

**Files:**
- Create: `frontend/src/components/canvas/hooks/useDrop.ts`

- [ ] **Step 1: Hook**

```ts
// useDrop.ts
import { libraryRegistry } from "@tentoroforge/library/registry";
import { useEditorStore } from "@/lib/editor-store";

export function useCanvasDrop() {
  const dispatch = useEditorStore(s => s.dispatch);

  return (ev: React.DragEvent) => {
    ev.preventDefault();
    const componentName = ev.dataTransfer.getData("text/x-forge-component");
    if (!componentName) return;

    const targetEl = (ev.target as HTMLElement).closest("[data-node-id]") as HTMLElement | null;
    const parentId = targetEl?.getAttribute("data-node-id");
    if (!parentId) return;

    // Find parent node + validate slot rule
    const { artifacts } = useEditorStore.getState();
    const parentNode = /* walk pageSchemas to find */ null as any;
    const parentEntry = libraryRegistry[parentNode?.type];
    if (!parentEntry || parentEntry.slots.type === "leaf") {
      console.warn("drop rejected: leaf parent");
      return;
    }
    if (parentEntry.slots.type === "list" && parentEntry.slots.accepts) {
      if (!parentEntry.slots.accepts.includes(componentName)) {
        console.warn(`drop rejected: ${parentEntry.name} doesn't accept ${componentName}`);
        return;
      }
    }

    // Dispatch insertNode
    const newId = `n-${Date.now().toString(36)}`;
    const draggedEntry = libraryRegistry[componentName];
    const defaultProps = Object.fromEntries(
      Object.entries(draggedEntry.props).map(([n, d]) => [n, d.default])
    );
    dispatch({
      type: "insertNode",
      pageId: /* current page from store */ "home",
      parentId,
      index: (parentNode.children?.length ?? 0),
      node: { id: newId, type: componentName, props: defaultProps, children: [] },
    });
  };
}
```

- [ ] **Step 2: Wire onDragOver/onDrop on canvas + DropIndicator overlay, commit**

```bash
git add frontend/src/components/canvas
git commit -m "feat(canvas): drag-from-palette with slot-rule validation"
```

---

### Task W7.3: Keyboard equivalents

**Files:**
- Create: `frontend/src/lib/keymap.ts`

Delete = removeNode. Cmd+Z = undo. Cmd+Shift+Z = redo. Cmd+D = duplicateNode.

- [ ] **Step 1: Global keymap subscribing to selection**

```ts
"use client";
import { useEffect } from "react";
import { useEditorStore } from "./editor-store";

export function useKeymap() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useEditorStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "z" && !e.shiftKey) { e.preventDefault(); s.undo(); return; }
      if (mod && (e.key === "Z" || (e.shiftKey && e.key === "z"))) { e.preventDefault(); s.redo(); return; }
      if (e.key === "Delete" || e.key === "Backspace") {
        if (s.selectedNodeId) {
          // find pageId for selected (similar walk to properties panel)
          s.dispatch({ type:"removeNode", pageId:"home", nodeId: s.selectedNodeId });
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/keymap.ts
git commit -m "feat(editor): keyboard shortcuts for undo/redo/delete"
```

---

## Workstream 8 — LLM as Peer Patcher

### Task W8.1: writeArtifacts tool schema (Zod → JSON Schema)

**Files:**
- Create: `backend/agents/peer_patcher_schemas.py`

The Pydantic shapes for `Artifacts` mirror `@forge/patches` types. We feed the JSON Schema export to Claude as a tool.

- [ ] **Step 1: Pydantic Artifacts shape + JSON Schema export**

```python
# backend/agents/peer_patcher_schemas.py
from __future__ import annotations
from typing import Optional, Any
from pydantic import BaseModel, Field

from contracts.nav_flow import NavFlow


class SchemaNode(BaseModel):
    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list["SchemaNode"] = Field(default_factory=list)
    slots: dict[str, list["SchemaNode"]] = Field(default_factory=dict)
    visibleIf: Optional[str] = None


class PageSchema(BaseModel):
    schemaVersion: str = "2"
    id: str
    route: Optional[str] = None
    layout: Optional[str] = None
    meta: dict = Field(default_factory=dict)
    dataSources: list[dict] = Field(default_factory=list)
    root: SchemaNode


class Tokens(BaseModel):
    color: dict = Field(default_factory=dict)
    typography: dict = Field(default_factory=dict)
    spacing: dict = Field(default_factory=dict)
    radius: dict = Field(default_factory=dict)
    shadow: dict = Field(default_factory=dict)
    motion: dict = Field(default_factory=dict)
    breakpoints: dict = Field(default_factory=dict)


class Artifacts(BaseModel):
    pageSchemas: dict[str, PageSchema]
    navFlow: NavFlow
    tokens: Tokens


def artifacts_json_schema() -> dict:
    """Used as the writeArtifacts tool's input_schema."""
    return Artifacts.model_json_schema()
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/peer_patcher_schemas.py
git commit -m "feat(peer-patcher): Pydantic Artifacts shape"
```

---

### Task W8.2: peer_patcher agent — single LLM call with writeArtifacts tool

**Files:**
- Create: `backend/agents/peer_patcher.py`

- [ ] **Step 1: Implementation**

```python
# backend/agents/peer_patcher.py
"""LLM as peer patcher: one tool call, full artifact bundle."""
from __future__ import annotations
import json
from typing import AsyncIterator, Optional

from anthropic import AsyncAnthropic
from agents.peer_patcher_schemas import artifacts_json_schema, Artifacts


async def run_peer_patcher(
    *, user_prompt: str,
    current_artifacts: Optional[dict],
    registry_digest: str,
    token_vocabulary: str,
) -> AsyncIterator[dict]:
    """Yield SSE-shaped events as the LLM produces its artifact bundle.

    Yields:
        {"event":"status", "data": {...}}
        {"event":"log",    "data": {"text": "..."}}
        {"event":"artifacts", "data": <Artifacts dict>}  -- terminal
    """
    yield {"event":"status", "data":{"message":"Generating artifacts via peer patcher..."}}

    system = _build_system_prompt(registry_digest, token_vocabulary, current_artifacts)

    client = AsyncAnthropic()
    tool_schema = artifacts_json_schema()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16_000,
        system=system,
        messages=[{"role":"user","content":user_prompt}],
        tools=[{
            "name": "writeArtifacts",
            "description": "Commit a complete updated artifact bundle. Call exactly once.",
            "input_schema": tool_schema,
        }],
        tool_choice={"type":"tool","name":"writeArtifacts"},
    )

    # Extract tool_use block
    artifacts = None
    rationale_parts = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "writeArtifacts":
            artifacts = block.input
        elif block.type == "text":
            rationale_parts.append(block.text)

    if artifacts is None:
        yield {"event":"log","data":{"text":"[PeerPatcher] No tool call produced — failing"}}
        raise RuntimeError("LLM did not call writeArtifacts")

    # Validate
    try:
        Artifacts.model_validate(artifacts)
    except Exception as e:
        yield {"event":"log","data":{"text":f"[PeerPatcher] Validation failed: {e}"}}
        raise

    yield {"event":"log","data":{"text":"[PeerPatcher] Artifacts validated"}}
    yield {"event":"artifacts","data":{"artifacts":artifacts,"rationale":"\n".join(rationale_parts)}}


def _build_system_prompt(registry_digest: str, tokens: str, current: Optional[dict]) -> str:
    return f"""You are Tentoro Forge's peer patcher. Produce an updated artifact bundle via writeArtifacts.

Component registry — ONLY use these components, ONLY these props:
{registry_digest}

Available tokens — every color/spacing/typography value MUST reference one of these:
{tokens}

Current artifacts (null = greenfield):
{json.dumps(current, indent=2) if current else 'null'}

Constraints:
- Call writeArtifacts exactly once.
- Every node has a globally unique id.
- Every component name in pageSchemas exists in the registry.
- Every prop matches the registry descriptor.
- Every visual value references a token; no raw hex, no raw px.
- pageSchemas keys match navFlow.pages[].id.
- Any onClick navigate action's trigger matches a navFlow.transitions[].trigger.
"""
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/peer_patcher.py
git commit -m "feat(peer-patcher): single-call LLM agent with writeArtifacts tool"
```

---

### Task W8.3: Validate-retry loop

**Files:**
- Create: `backend/services/artifact_validator.py`

Token closure + registry closure + ID uniqueness checks. On failure, the peer patcher retries up to 2× with the errors as corrective feedback.

- [ ] **Step 1: Validator**

```python
# backend/services/artifact_validator.py
"""Closure + uniqueness validators for the three artifacts."""
from __future__ import annotations
import re
from typing import Any

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
_PX_RE = re.compile(r"\b\d+px\b")


def _walk(node: dict[str, Any]):
    yield node
    for c in node.get("children", []) or []: yield from _walk(c)
    for arr in (node.get("slots") or {}).values():
        for c in arr: yield from _walk(c)


def validate_token_closure(artifacts: dict) -> list[str]:
    errs = []
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        for n in _walk(page["root"]):
            for prop, val in (n.get("props") or {}).items():
                s = str(val) if not isinstance(val, dict) else ""
                if _HEX_RE.search(s): errs.append(f"{pid}/{n['id']}.{prop} contains raw hex: {val}")
                if _PX_RE.search(s):  errs.append(f"{pid}/{n['id']}.{prop} contains raw px: {val}")
    return errs


def validate_registry_closure(artifacts: dict, registry: dict) -> list[str]:
    errs = []
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        for n in _walk(page["root"]):
            t = n.get("type")
            if t not in registry:
                errs.append(f"{pid}/{n['id']} unknown component: {t}")
                continue
            entry = registry[t]
            for prop_name in (n.get("props") or {}).keys():
                if prop_name not in entry["props"]:
                    errs.append(f"{pid}/{n['id']}.{prop_name} unknown prop on {t}")
    return errs


def validate_id_uniqueness(artifacts: dict) -> list[str]:
    errs = []
    seen = set()
    for pid, page in (artifacts.get("pageSchemas") or {}).items():
        for n in _walk(page["root"]):
            nid = n.get("id")
            if not nid: errs.append(f"{pid}/<unknown>: missing id")
            elif nid in seen: errs.append(f"duplicate node id: {nid}")
            seen.add(nid)
    return errs


def validate_all(artifacts: dict, registry: dict) -> list[str]:
    return (
        validate_id_uniqueness(artifacts)
        + validate_registry_closure(artifacts, registry)
        + validate_token_closure(artifacts)
    )
```

- [ ] **Step 2: Wrap peer_patcher with retry**

In `run_peer_patcher`, after validation fails, retry up to 2× with `user_prompt = original + f"\n\nPrevious attempt failed with errors:\n{errors}"`.

- [ ] **Step 3: Tests + commit**

```bash
git add backend/services/artifact_validator.py backend/agents/peer_patcher.py
git commit -m "feat(peer-patcher): validate-retry loop with token + registry closure"
```

---

### Task W8.4: Wire peer_patcher into generate.py as the new default path

Behind feature flag `PEER_PATCHER_ENABLED=1` so the multi-agent pipeline keeps working for fallback.

- [ ] **Step 1: New branch in generate.py**

```python
if os.environ.get("PEER_PATCHER_ENABLED") == "1":
    from agents.peer_patcher import run_peer_patcher
    from packages_registry import registry_digest_string  # serialise from packages/registry
    async for evt in run_peer_patcher(
        user_prompt=description,
        current_artifacts=_load_existing_artifacts(output_dir),
        registry_digest=registry_digest_string(),
        token_vocabulary=_load_existing_tokens(output_dir) or DEFAULT_TOKENS_PROMPT,
    ):
        if evt["event"] == "artifacts":
            _commit_artifacts(output_dir, evt["data"]["artifacts"])
        else:
            yield sse_event(evt["event"], evt["data"])
    return
```

The `_commit_artifacts` helper writes each page schema, nav-flow.json, and tokens.json into the project's output_dir — same persistence path the editor uses.

- [ ] **Step 2: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(generate): PEER_PATCHER_ENABLED flag for single-call LLM path"
```

---

## Workstream 9 — Invariants + Golden Tests

### Task W9.1: normalize() function for round-trip identity (I-2)

**Files:**
- Create: `packages/patches/src/normalize.ts`

Deterministically orders children, sorts prop keys alphabetically, removes empty arrays/objects, etc. Both the editor's commit path and the peer_patcher's commit path call `normalize()` before writing — so `parse(serialize(parse(x))) ≡ parse(x)`.

- [ ] **Step 1: Implementation + tests**

```ts
// packages/patches/src/normalize.ts
import type { Artifacts, SchemaNode } from "./types";

function sortKeys(obj: any): any {
  if (Array.isArray(obj)) return obj.map(sortKeys);
  if (obj && typeof obj === "object") {
    return Object.keys(obj).sort().reduce((acc, k) => {
      acc[k] = sortKeys(obj[k]);
      return acc;
    }, {} as any);
  }
  return obj;
}

function normalizeNode(n: SchemaNode): SchemaNode {
  const out: SchemaNode = {
    id: n.id,
    type: n.type,
    props: n.props ? sortKeys(n.props) : undefined,
    children: n.children ? n.children.map(normalizeNode) : undefined,
  };
  if (n.slots) (out as any).slots = sortKeys(
    Object.fromEntries(Object.entries(n.slots).map(([k, v]) => [k, v.map(normalizeNode)]))
  );
  if (n.visibleIf) (out as any).visibleIf = n.visibleIf;
  return out;
}

export function normalize(a: Artifacts): Artifacts {
  return {
    pageSchemas: Object.fromEntries(
      Object.entries(a.pageSchemas).sort(([a],[b]) => a.localeCompare(b))
        .map(([id, p]) => [id, { ...p, root: normalizeNode(p.root) }])
    ),
    navFlow: {
      ...a.navFlow,
      pages: [...a.navFlow.pages].sort((x,y) => x.id.localeCompare(y.id)),
      transitions: [...a.navFlow.transitions].sort((x,y) => x.id.localeCompare(y.id)),
    },
    tokens: sortKeys(a.tokens),
  };
}
```

- [ ] **Step 2: Round-trip identity test**

```ts
// packages/patches/tests/normalize.test.ts
import { normalize } from "../src/normalize";

it("normalize is idempotent", () => {
  const a = /* sample artifacts */;
  expect(JSON.stringify(normalize(a))).toBe(JSON.stringify(normalize(normalize(a))));
});

it("two paths to same logical state produce same bytes", () => {
  // editor path
  let A = empty();
  A = applyAction(A, { type:"insertNode", ... }).next;
  A = applyAction(A, { type:"updateProp", ... }).next;
  // LLM path
  const B: Artifacts = /* hand-crafted equivalent */;
  expect(JSON.stringify(normalize(A))).toBe(JSON.stringify(normalize(B)));
});
```

- [ ] **Step 3: Commit**

```bash
git add packages/patches/src/normalize.ts packages/patches/tests/normalize.test.ts
git commit -m "feat(patches): normalize() + round-trip identity invariant (I-2)"
```

---

### Task W9.2: DOM equivalence golden test (I-1, I-7)

**Files:**
- Create: `packages/engine/tests/golden-dom.test.tsx`

For a fixed set of "golden" artifacts, render via the engine in JIT mode and compare snapshot. Run the same artifacts through the standalone-app emitter + a headless next-server-side render and compare DOM. Modulo the editor overlay sibling, the DOMs must be structurally identical.

- [ ] **Step 1: 5 golden fixtures** — minimal, list, detail, form, dashboard.

- [ ] **Step 2: JIT-vs-SSR comparison** — use Next.js `renderToString` against the standalone-app's `[...slug]/page.tsx`. The engine package's `<Engine>` itself is identical, so the comparison reduces to "does our SSR wrapper produce the same DOM as our CSR wrapper."

- [ ] **Step 3: CI integration**

```yaml
# in CI workflow
- name: Golden invariants
  run: |
    cd packages/engine && npm run test -- tests/golden-dom.test.tsx
    cd ../patches && npm run test -- tests/normalize.test.ts
```

- [ ] **Step 4: Commit**

```bash
git add packages/engine/tests/golden-dom.test.tsx .github/workflows
git commit -m "feat(invariants): DOM equivalence + round-trip golden tests in CI"
```

---

### Task W9.3: Apply validators at every commit boundary

- [ ] **Step 1: editor-store rejects invalid artifacts** — after `applyAction`, run `validate_all` (a TypeScript port of the Python validator); if errors, revert and surface them in a toast.

- [ ] **Step 2: peer_patcher already retries on validator failure (W8.3)**.

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(invariants): enforce closure validators at commit boundary"
```

---

## Self-review

### Spec coverage

- [x] §1.4.1 Three artifacts as only persisted state — W1 (nav-flow), W3 (Artifacts type), W8 (peer patcher persists)
- [x] §1.4.2 Derived view everywhere — W2 (canvas IS the engine)
- [x] §1.4.3 Modifications flow through artifacts — W3 (`applyAction`)
- [x] §1.4.4 Two peer patchers — W8 (LLM produces same artifacts editor does)
- [x] §1.4.5 Constrained generation — W4 (registry), W8 (digest in prompt), W9 (closure validators)
- [x] §1.4.6 Declarative over imperative — registry has no free-form props
- [x] §2 Three artifacts (adapted: N page-schemas per Tentoro convention) — W1 nav-flow + W4 tokens via registry
- [x] §3 Mutation model — W3 full implementation
- [x] §3.4 Editor-action ↔ artifact mapping — W3.2 + W3.3
- [x] §3.6 Atomic transactions — applyAction validates end-to-end before commit
- [x] §3.7 First-time vs update — W8 peer_patcher handles null currentArtifacts
- [x] §3.8 LLM and editor as peer patchers — W8
- [x] §4 Component registry — W4
- [x] §5 Editor UX architecture — W2 (canvas) + W5 (selection)
- [x] §6 Drag-and-drop — W7
- [x] §7 Properties panel — W6
- [x] §9 Data binding & placeholders — engine already has interpolate (standalone-engine plan W-A3); editor binding chips covered in W6.3
- [x] §10 Single engine two modes — standalone-engine plan W-A6 + emitter W-B (referenced)
- [x] §11 LLM peer patcher — W8
- [x] §12 Invariants — W9 (I-1, I-2, I-5, I-6, I-7, I-8 covered; I-3 and I-4 derive from W3 + W8 design)
- [x] §13 Component registry starter set — W4.1

### Dependencies on the standalone-engine plan

This plan REQUIRES the following from `docs/superpowers/plans/2026-05-14-standalone-engine-and-emitter.md`:

- W-A1–A7 (Engine package) — needed by W2, W5, W8.
- W-B1–B5 (Standalone-app emitter) — needed for SSR side of I-1 golden test (W9.2).
- W-C1–C3 (Editor wiring + export) — orthogonal; can land later.
- W-D1–D2 (Scaffold uses engine) — orthogonal; can land later.

**Recommendation:** execute the standalone-engine plan's Workstream A FIRST, then this plan's W1, W2, W3 in parallel, then W4–W9 sequentially.

### Placeholder scan

No `TBD` or `implement later` in plan steps. Some test fixtures referenced as `/* sample artifacts */` — these are intentionally elided to keep the plan readable; the test files themselves must materialise them. The implementer task is to write the fixture inline, not invent it.

### Type consistency

`Artifacts` defined once in W3.2; consumed unchanged by W3.3, W3.4, W5.2, W6.2, W7.2, W8.1, W9.1. `RegistryEntry` defined in W4.1; consumed unchanged by W4.2, W6.2, W7.1, W7.2, W8.2.

### Estimated effort

- W1 (nav-flow): 1 day
- W2 (canvas read-only): 1 day (blocked on engine package)
- W3 (mutation layer): 2–3 days (test-heavy)
- W4 (registry): 1–2 days (mostly mechanical migration)
- W5 (selection overlay): 1 day
- W6 (properties panel): 1.5 days
- W7 (drag-drop): 1.5 days
- W8 (peer patcher): 2 days (LLM tuning may extend)
- W9 (invariants): 1 day

**Total: ~12–14 focused engineering days.** Realistically 3 weeks calendar time given iteration on the LLM peer-patcher's prompt + golden test failures.

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-14-pillar-1-visual-editor.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, two-stage review between tasks, fast iteration. Best fit for this plan because tasks are largely independent within each workstream and W1–W3 can parallelise after the engine package ships.

**2. Inline execution** — Tasks executed in this session with checkpoints between workstreams. Slower but lets you steer mid-flight.

Which approach?
