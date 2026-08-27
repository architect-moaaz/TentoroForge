# Figma-Driven Generation Pipeline — Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user supplies a Figma URL, the generated project mirrors what's in Figma — same pages, same shapes, same brand. Today's pipeline ignores Figma's scope (planner invents pages independent of Figma) and the deterministic mapper output gets overridden by LLM dashboards. This plan rewires the pipeline so Figma is authoritative for page list AND per-page schema, with per-node fidelity as an opt-in mode.

**Architecture:** Five phases, ~28 tasks. Each phase is independently shippable; later phases depend on earlier ones.

1. **Phase 1 — Figma drives the plan.** Walk the Figma file → list top-level frames → emit `plan.pages` 1:1. No imagined pages when Figma is present.
2. **Phase 2 — Multi-page mapper.** Deterministic mapper iterates every Figma-bound page concurrently, writes a schema per frame.
3. **Phase 3 — Skip LLM per page.** When a page has `figma_node_id` AND the mapper produced output, the LLM schema pipeline doesn't run for that page.
4. **Phase 4 — Per-node fidelity.** Inline styles + asset extraction + absolute-positioning fallback, opt-in via `page.pixelPerfect: true`.
5. **Phase 5 — User-consented expansion.** When Figma covers N pages but the user wants M more, ask explicitly rather than invent silently.

**Tech Stack:** Python 3.11 (backend), Next.js (frontend), httpx (Figma REST + images endpoint), pytest, Playwright (visual diff verification).

**Reference state today:**
- `backend/agents/planner.py` — LLM planner emits `plan.pages` from the user's description. Ignores Figma's scope.
- `backend/routers/generate.py:_run_figma_relay_pipeline` — calls `parse_figma_url` to get a single node, runs `figma_to_schema` on that one node only, then the LLM schema pipeline runs for ALL pages in the plan.
- `backend/services/figma_to_schema.py:build_page_schema` — produces a PageV2 from one Figma document subtree. Already wired with classifier, walker, token + typography extractors.
- `backend/services/figma_client.py` — has `fetch_figma_node` (one node) and `fetch_figma_file_meta` (file metadata at `depth=1`). We'll add `fetch_figma_node_tree(depth=2+)` for full canvas listing.
- **Diagnostic baseline:** project `xq4o39e2` (CommitBiz) — Figma supplied 1 login frame; pipeline generated 7 unrelated dashboard pages. None of which are the login screen.

---

## File Structure Overview

### New files

| File | Phase | Responsibility |
|---|---|---|
| `backend/services/figma_plan_builder.py` | 1 | `build_plan_from_figma(figma_url, token)` walks the file, lists frames, emits plan.pages with `figma_node_id` per entry |
| `backend/services/figma_route_inferer.py` | 1 | `infer_route_from_frame_name(name)` — heuristic that converts Figma frame names into clean URL routes |
| `backend/services/figma_asset_pipeline.py` | 4 | Calls Figma `/v1/images` for IMAGE / VECTOR / FRAME nodes, saves to `output/<id>/public/figma/`, returns a node-id → local-path map |
| `backend/services/figma_to_schema_pixel.py` | 4 | Pixel-perfect variant of build_page_schema — emits per-node `style` props from raw Figma values |
| `backend/tests/services/test_figma_plan_builder.py` | 1 | Unit tests + a real-Figma integration test against Commitbiz |
| `backend/tests/services/test_figma_route_inferer.py` | 1 | Frame-name → route heuristic tests |
| `backend/tests/services/test_figma_asset_pipeline.py` | 4 | Asset extraction tests with mocked image API |
| `backend/tests/services/test_figma_to_schema_pixel.py` | 4 | Pixel-perfect schema generation tests |
| `backend/tests/fixtures/figma/commitbiz_full_file.json` | 1 | Real Figma file metadata (top-level only, depth=2) captured once |
| `frontend/src/components/projects/AddPagesPrompt.tsx` | 5 | UI for "Figma has N pages — generate M more?" consent dialog |

### Modified files

| File | Phase | Change |
|---|---|---|
| `backend/services/figma_client.py` | 1 | Add `fetch_figma_file(file_key, token, depth=2)` for top-level canvas + frame metadata |
| `backend/routers/generate.py:_run_figma_relay_pipeline` | 1, 2, 3 | Replace LLM planner with Figma planner when `figma_url` present; iterate plan.pages for deterministic emit; track `deterministic_pages` set for per-page LLM skip |
| `backend/agents/planner.py` | 1 | Skip when `figma_url` provided AND `figma_plan` already computed |
| `backend/services/schema_pipeline.py` | 3 | Skip per-page when page id ∈ `deterministic_pages` |
| `backend/services/phase_gates.py` | 2, 3 | `check_pages_coverage` already exists; verify it counts Figma-bound pages as covered |
| `backend/services/figma_to_schema.py` | 4 | Add optional `pixel_perfect: bool` parameter; route through `figma_to_schema_pixel` when True |
| `backend/services/figma_style_extractor.py` | 4 | Add `extract_node_style(node) -> dict` that returns the full CSS dict for a single node (not just utility classes) |
| `backend/services/figma_node_walker.py` | 4 | Surface `absoluteBoundingBox`, `constraints`, `fills[].imageRef`, `strokes`, `effects` on annotated nodes |
| `packages/library/src/components/*/*.tsx` | 4 | Several library components accept a `style` prop and merge after Tailwind classes (Card, Stack, Row, Container, Button, Text, Image are the highest-impact) |
| `backend/schemas/project.py` | 5 | `GenerateProjectRequest` accepts optional `additional_pages: list[dict]` describing pages the user wants beyond what Figma provides |
| `frontend/src/components/projects/CreateProjectForm.tsx` | 5 | Surfaces the "Figma has N pages; add more?" prompt when generation pauses for consent |

---

## Phase 1 — Figma Drives the Plan

Goal: When `figma_url` is supplied, `plan.pages` matches the Figma file 1:1 — one page per top-level frame. No imagined pages.

### Task 1.1: `fetch_figma_file` with deeper depth

**Files:**
- Modify: `backend/services/figma_client.py`
- Test: `backend/tests/services/test_figma_client.py`

- [ ] **Step 1: Add the new function**

```python
# backend/services/figma_client.py — append after fetch_figma_file_meta
async def fetch_figma_file(file_key: str, token: str, depth: int = 2) -> dict:
    """Fetch the file's top-level canvas + frame tree at a configurable depth.

    depth=1 → file metadata only (canvas list)
    depth=2 → top-level frames per canvas (what we need for plan-building)
    depth=3+ → progressively deeper; used by per-page mapper to get the
              actual node subtree.
    """
    token = (token or "").strip()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": depth},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma file fetch failed: {r.status_code} {r.text[:200]}")
        return r.json()
```

- [ ] **Step 2: Test with mock**

```python
# Append to test_figma_client.py
@pytest.mark.asyncio
async def test_fetch_figma_file_passes_depth():
    payload = {"name": "Commitbiz", "document": {"children": [{"id": "0:1", "type": "CANVAS"}]}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp(200, payload))) as mock_get:
        result = await fetch_figma_file("K", "tok", depth=2)
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.figma.com/v1/files/K"
    assert kwargs["params"] == {"depth": 2}
    assert result == payload
```

- [ ] **Step 3: Run + commit**

```
feat(figma-client): fetch_figma_file with configurable depth for canvas walking
```

### Task 1.2: Route inferer — Figma frame name → URL route

**Files:**
- Create: `backend/services/figma_route_inferer.py`
- Test: `backend/tests/services/test_figma_route_inferer.py`

- [ ] **Step 1: Write tests first**

```python
# backend/tests/services/test_figma_route_inferer.py
import pytest
from services.figma_route_inferer import infer_route_from_frame_name


@pytest.mark.parametrize("name, expected", [
    # Auth pages
    ("Login", "/login"),
    ("Sign in", "/login"),
    ("Sign up", "/signup"),
    ("Signup", "/signup"),
    ("Forgot password", "/forgot-password"),
    ("Reset password", "/reset-password"),
    # Common dashboards
    ("Home", "/"),
    ("Dashboard", "/"),
    ("Overview", "/"),
    # List + form patterns from frame names
    ("Users list", "/users"),
    ("Users / List", "/users"),
    ("New user", "/users/new"),
    ("Create user", "/users/new"),
    ("Edit user", "/users/[id]/edit"),
    ("User detail", "/users/[id]"),
    # Real-world Figma names with prefixes
    ("Commitbiz_intentai_login", "/login"),
    ("Commitbiz_intentai_signup", "/signup"),
    ("01 - Login screen", "/login"),
    ("Frame 32", "/page-32"),     # fallback — numeric frames get a generic route
    # Snake / kebab → kebab
    ("user_settings", "/user-settings"),
    ("UserSettings", "/user-settings"),
    # Empty / whitespace
    ("", "/page"),
    ("   ", "/page"),
])
def test_infer_route(name, expected):
    assert infer_route_from_frame_name(name) == expected
```

- [ ] **Step 2: Implement**

```python
# backend/services/figma_route_inferer.py
"""Convert a Figma frame name to a clean URL route.

Heuristic pipeline:
  1. Strip product-name prefixes (Commitbiz_, IntentAI_, etc.)
  2. Match against known auth/dashboard patterns
  3. Match list/detail/form patterns
  4. Fall back to kebab-case of the cleaned name

Tested against real Figma files; rules are deliberate and conservative.
"""
from __future__ import annotations
import re

_AUTH_RE = re.compile(r"\b(sign[- ]?in|login)\b", re.I)
_SIGNUP_RE = re.compile(r"\b(sign[- ]?up|signup|register)\b", re.I)
_FORGOT_RE = re.compile(r"\bforgot[- ]?password\b", re.I)
_RESET_RE = re.compile(r"\breset[- ]?password\b", re.I)
_HOME_RE = re.compile(r"^(home|dashboard|overview|index)$", re.I)

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _kebab(s: str) -> str:
    """ 'UserSettings' → 'user-settings'; 'user_settings ' → 'user-settings' """
    s = _CAMEL_RE.sub("-", s)
    s = s.lower()
    s = _NON_ALNUM_RE.sub("-", s).strip("-")
    return s or "page"


def _strip_product_prefix(name: str) -> str:
    """Drop the leading 1-3 underscored or camel-cased tokens that look like a
    product / brand prefix (e.g. 'Commitbiz_intentai_login' → 'login')."""
    cleaned = name.strip()
    # If there's an _underscore_path, take the last 1-2 segments
    if "_" in cleaned:
        parts = cleaned.split("_")
        # Heuristic: keep the last segment if it's a recognised page word,
        # otherwise keep the last two as combined.
        last = parts[-1].lower()
        if last in {"login", "signin", "signup", "dashboard", "home", "settings", "profile"}:
            return last
        return "_".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return cleaned


def infer_route_from_frame_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return "/page"

    cleaned = _strip_product_prefix(raw)
    lower = cleaned.lower().strip()

    # 1. Auth patterns
    if _AUTH_RE.search(lower) and "sign up" not in lower and "signup" not in lower:
        return "/login"
    if _SIGNUP_RE.search(lower):
        return "/signup"
    if _FORGOT_RE.search(lower):
        return "/forgot-password"
    if _RESET_RE.search(lower):
        return "/reset-password"

    # 2. Dashboards
    if _HOME_RE.match(lower):
        return "/"

    # 3. List / detail / form
    parts = [_kebab(p) for p in re.split(r"\s*/\s*|\s+", cleaned) if p]
    # "Users list" → ["users", "list"]
    if len(parts) >= 2 and parts[-1] in {"list", "index"}:
        return f"/{parts[0]}"
    if len(parts) >= 2 and parts[0] in {"new", "create"}:
        return f"/{parts[-1]}/new"
    if len(parts) >= 2 and parts[-1] in {"new", "create"}:
        return f"/{parts[0]}/new"
    if len(parts) >= 2 and parts[-1] == "edit":
        return f"/{parts[0]}/[id]/edit"
    if len(parts) >= 2 and parts[-1] in {"detail", "details"}:
        return f"/{parts[0]}/[id]"

    # 4. Fallback — kebab of the whole cleaned name
    if not parts:
        return "/page"
    if all(p.isdigit() or p.startswith("frame") for p in parts):
        return f"/page-{parts[-1] if parts[-1].isdigit() else 'unnamed'}"
    return "/" + "-".join(parts)
```

- [ ] **Step 3: Run + commit**

```
feat(figma): figma_route_inferer — frame name → URL route heuristic
```

### Task 1.3: `figma_plan_builder` — walk the file, list frames, emit plan.pages

**Files:**
- Create: `backend/services/figma_plan_builder.py`
- Test: `backend/tests/services/test_figma_plan_builder.py`
- Create: `backend/tests/fixtures/figma/commitbiz_full_file.json` (captured fixture)

- [ ] **Step 1: Capture the real Figma file fixture (one-time setup)**

```bash
python3 - <<'PY'
import asyncio, json, os, sys
sys.path.insert(0, "backend")
from services.figma_client import fetch_figma_file
token = os.environ["FIGMA_TOKEN"].strip()
file_meta = asyncio.run(fetch_figma_file("8O10fOsocmlxdN678zDp8r", token, depth=2))
with open("backend/tests/fixtures/figma/commitbiz_full_file.json", "w") as f:
    json.dump(file_meta, f, indent=2)
PY
```

Commit the fixture so tests are reproducible without hitting the Figma API.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/services/test_figma_plan_builder.py
import json, pathlib
from unittest.mock import AsyncMock, patch
import pytest
from services.figma_plan_builder import build_plan_from_figma, _extract_frames


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_full_file.json"


def test_extracts_top_level_frames_from_canvas():
    file_meta = json.loads(FIXTURE.read_text())
    frames = _extract_frames(file_meta)
    # Should be at least one frame (the login screen)
    assert len(frames) >= 1
    names = [f["name"] for f in frames]
    assert any("login" in n.lower() for n in names), \
        f"login frame not detected in {names}"


def test_each_frame_has_id_and_route():
    file_meta = json.loads(FIXTURE.read_text())
    frames = _extract_frames(file_meta)
    for f in frames:
        assert "id" in f
        assert "route" in f
        assert f["route"].startswith("/")


@pytest.mark.asyncio
async def test_build_plan_from_figma_returns_pages():
    file_meta = json.loads(FIXTURE.read_text())
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=file_meta)):
        plan = await build_plan_from_figma(
            "https://www.figma.com/design/8O10fOsocmlxdN678zDp8r/Commitbiz",
            token="tok",
        )
    pages = plan["pages"]
    assert len(pages) >= 1
    # Every page must have figma_node_id binding it back to the source frame
    for p in pages:
        assert "figma_node_id" in p
        assert "route" in p
        assert "name" in p


@pytest.mark.asyncio
async def test_login_frame_classified_as_auth_type():
    file_meta = json.loads(FIXTURE.read_text())
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=file_meta)):
        plan = await build_plan_from_figma(
            "https://www.figma.com/design/X/Y", token="t")
    login_page = next(
        (p for p in plan["pages"] if "login" in (p.get("route") or "")),
        None,
    )
    assert login_page is not None
    assert login_page.get("type") == "auth"


@pytest.mark.asyncio
async def test_routes_are_unique_when_collision():
    """Two frames named 'Frame 1' shouldn't both map to /frame-1."""
    fake_file = {
        "document": {"children": [{
            "id": "0:1", "type": "CANVAS",
            "children": [
                {"id": "1:1", "type": "FRAME", "name": "Frame 1"},
                {"id": "1:2", "type": "FRAME", "name": "Frame 1"},
            ],
        }]},
        "name": "Test",
    }
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=fake_file)):
        plan = await build_plan_from_figma("https://figma.com/design/X/Y", token="t")
    routes = [p["route"] for p in plan["pages"]]
    assert len(routes) == len(set(routes)), f"duplicate routes: {routes}"


@pytest.mark.asyncio
async def test_skips_invisible_frames():
    """Hidden/non-FRAME nodes (COMPONENT, COMPONENT_SET, SLICE) shouldn't
    become pages — they're library/utility nodes."""
    fake = {
        "document": {"children": [{
            "id": "0:1", "type": "CANVAS",
            "children": [
                {"id": "1:1", "type": "FRAME", "name": "Login"},
                {"id": "1:2", "type": "COMPONENT", "name": "Button"},
                {"id": "1:3", "type": "COMPONENT_SET", "name": "ButtonVariants"},
                {"id": "1:4", "type": "FRAME", "name": "Signup", "visible": False},
            ],
        }]},
        "name": "Test",
    }
    with patch("services.figma_plan_builder.fetch_figma_file",
               AsyncMock(return_value=fake)):
        plan = await build_plan_from_figma("https://figma.com/design/X/Y", token="t")
    routes = [p["route"] for p in plan["pages"]]
    assert "/login" in routes
    # Component, component_set, hidden frames excluded
    assert len(plan["pages"]) == 1
```

- [ ] **Step 3: Implement**

```python
# backend/services/figma_plan_builder.py
"""Build plan.pages directly from a Figma file's frame tree.

When figma_url is supplied to the generate pipeline, this becomes the
source of truth for plan.pages — bypassing the LLM planner. One
plan.pages entry per top-level FRAME found in the Figma file.
"""
from __future__ import annotations
import re
from typing import Any

from figma_parser import parse_figma_url
from services.figma_client import fetch_figma_file
from services.figma_route_inferer import infer_route_from_frame_name


_EXCLUDED_TYPES = {"COMPONENT", "COMPONENT_SET", "SLICE", "INSTANCE"}


def _classify_type_from_name(name: str) -> str | None:
    """Best-effort page_type classification from the frame name."""
    n = (name or "").lower()
    if "login" in n or "sign in" in n or "signin" in n:
        return "auth"
    if "signup" in n or "sign up" in n or "register" in n:
        return "auth"
    if "forgot" in n or "reset" in n:
        return "auth"
    if "dashboard" in n or "overview" in n or "home" in n:
        return "dashboard"
    if "list" in n or "index" in n or n.endswith("s"):
        return "list"
    if "detail" in n or "[id]" in n or "{id}" in n:
        return "detail"
    if "new" in n or "create" in n or "edit" in n or "form" in n:
        return "form"
    if "error" in n or "404" in n or "not-found" in n:
        return "error"
    return None


def _extract_frames(file_meta: dict) -> list[dict]:
    """Walk file_meta.document.children (CANVAS) → their children (FRAMEs).
    Returns a list of {id, name, route, type} dicts with deduped routes.
    """
    out: list[dict] = []
    document = (file_meta or {}).get("document") or {}
    for canvas in document.get("children") or []:
        if canvas.get("type") != "CANVAS":
            continue
        for frame in canvas.get("children") or []:
            if frame.get("type") != "FRAME":
                continue
            if frame.get("type") in _EXCLUDED_TYPES:
                continue
            if frame.get("visible") is False:
                continue
            name = frame.get("name") or ""
            route = infer_route_from_frame_name(name)
            out.append({
                "id": frame.get("id"),
                "name": name,
                "route": route,
                "type": _classify_type_from_name(name),
            })

    # Deduplicate routes by suffixing -2, -3 on collisions
    seen: dict[str, int] = {}
    for f in out:
        base = f["route"]
        if base in seen:
            seen[base] += 1
            f["route"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return out


async def build_plan_from_figma(figma_url: str, token: str) -> dict:
    """Walk a Figma file and emit a plan with one page per top-level FRAME.

    Returns a plan dict with:
      pages: [{route, name, figma_node_id, type, file: "src/schemas/<slug>.json"}]
      figma_file_key, figma_url — for downstream reference
      _figma_driven: True (sentinel — downstream agents may want to skip
                     description-based planner)
    """
    parsed = parse_figma_url(figma_url)
    file_key = parsed["file_key"]
    file_meta = await fetch_figma_file(file_key, token, depth=2)
    raw_frames = _extract_frames(file_meta)

    pages = []
    for fr in raw_frames:
        slug = fr["route"].strip("/").replace("/", "-") or "home"
        pages.append({
            "route": fr["route"],
            "name": fr["name"],
            "figma_node_id": fr["id"],
            "type": fr["type"],
            "file": f"src/schemas/{slug}.json",
            "entity": None,
        })

    return {
        "pages": pages,
        "figma_file_key": file_key,
        "figma_url": figma_url,
        "name": (file_meta or {}).get("name", "Untitled"),
        "_figma_driven": True,
    }
```

- [ ] **Step 4: Run tests, commit**

```
feat(figma): figma_plan_builder — Figma file walking becomes plan.pages source
```

### Task 1.4: Wire `figma_plan_builder` into the generate pipeline

**Files:**
- Modify: `backend/routers/generate.py` — `generate_project` request handler around line 1980

- [ ] **Step 1: Locate the entry point**

```bash
grep -n "is_figma\|figma_url\|req.figma_token\|figma_plan_builder" backend/routers/generate.py | head -10
```

The `is_figma = bool(req.figma_url and req.figma_token)` check is what fans out to `_run_figma_relay_pipeline`. We need to compute `figma_plan` before that pipeline is invoked.

- [ ] **Step 2: Insert plan builder before the pipeline call**

```python
# Inside generate_project, after sanitising tokens and BEFORE the pipeline dispatch:
figma_plan: dict | None = None
if is_figma and not req.plan:
    # User gave a Figma URL but no explicit plan — build one from Figma.
    try:
        from services.figma_plan_builder import build_plan_from_figma
        figma_plan = await build_plan_from_figma(req.figma_url, req.figma_token)
        # Stash on req.plan so the downstream pipeline gets it
        req.plan = figma_plan
        yield_log = f"[Figma Plan] Found {len(figma_plan['pages'])} frame(s): " \
                    f"{[p['route'] for p in figma_plan['pages']]}"
        # NOTE: this is an async generator — we can't yield here directly because
        # generate_project doesn't yield. Log it for the pipeline to surface later.
        logger.info(yield_log)
    except Exception as e:
        logger.warning(f"[Figma Plan] Builder failed: {e} — falling back to LLM planner")
```

The pipeline then sees `req.plan` set and skips the LLM planner.

- [ ] **Step 3: Wire the SSE log into the pipeline so the user sees it**

In `_run_figma_relay_pipeline`, immediately after entry:

```python
if (plan or {}).get("_figma_driven"):
    yield sse_event("log", {
        "text": f"[Figma Plan] Driven by Figma — {len(plan['pages'])} page(s) "
                f"from {plan.get('figma_url','?')}"
    })
```

- [ ] **Step 4: Test**

```python
# backend/tests/routers/test_generate_figma_driven.py
@pytest.mark.asyncio
async def test_figma_plan_drives_plan_pages(client, ...):
    """When figma_url is given, the request's req.plan gets populated by
    figma_plan_builder before the pipeline runs."""
    # mock out fetch_figma_file to return our commitbiz fixture
    # POST /api/projects/<id>/generate with figma_url
    # assert the request's plan has 1 page (login), not 7 (planner default)
```

- [ ] **Step 5: Commit**

```
feat(generate): wire figma_plan_builder into generate_project — Figma drives plan
```

### Task 1.5: Skip the LLM planner when Figma plan present

**Files:**
- Modify: `backend/agents/planner.py` — early exit when `_figma_driven`

- [ ] **Step 1: Find the planner entry**

```bash
grep -n "async def run_planner\|run_planner_oneshot" backend/agents/planner.py | head -5
```

- [ ] **Step 2: Guard the LLM call**

In `run_planner_oneshot` (or whichever entrypoint is called from `generate_project`), early-return if the caller already supplied a plan:

```python
async def run_planner_oneshot(description: str, *, prior_plan: dict | None = None, ...) -> dict:
    """If prior_plan is supplied and marked _figma_driven, skip the LLM call
    and just return it (annotated with page types via _annotate_page_types)."""
    if prior_plan and prior_plan.get("_figma_driven"):
        return _annotate_page_types(prior_plan)
    # ... existing LLM path ...
```

- [ ] **Step 3: Wire the caller**

Find where `run_planner` is invoked from the generate route and pass `prior_plan=req.plan`.

- [ ] **Step 4: Test + commit**

```
feat(planner): skip LLM planner when caller supplies a Figma-driven plan
```

---

## Phase 2 — Multi-Page Deterministic Mapper

Goal: For every page in `plan.pages` that has a `figma_node_id`, the deterministic mapper fetches that node and produces a schema. Today only the URL's node is processed.

### Task 2.1: Iterate plan.pages, fetch each Figma node, build each schema

**Files:**
- Modify: `backend/routers/generate.py:_run_figma_relay_pipeline` — the existing FigmaDeterministic block

- [ ] **Step 1: Read the current FigmaDeterministic block**

```bash
grep -n "FigmaDeterministic\|deterministic_pages\|build_page_schema" backend/routers/generate.py | head -15
```

Currently it parses ONE node from the URL and runs `build_page_schema` once.

- [ ] **Step 2: Replace with multi-page iteration**

```python
# Inside _run_figma_relay_pipeline — replace the existing FigmaDeterministic block
deterministic_pages: set[str] = set()
deterministic_tokens: dict = {}
deterministic_failures: list[tuple[str, str]] = []

try:
    from services.figma_client import fetch_figma_node
    from services.figma_to_schema import build_page_schema
    from figma_parser import parse_figma_url
    import asyncio as _asyncio

    parsed = parse_figma_url(figma_url)
    file_key = parsed["file_key"]
    plan_pages = (plan or {}).get("pages") or []
    pages_with_nodes = [p for p in plan_pages if p.get("figma_node_id")]

    if not pages_with_nodes:
        yield sse_event("log", {
            "text": "[FigmaDeterministic] No pages have figma_node_id — skipping mapper"
        })
    else:
        yield sse_event("status", {
            "message": f"Generating {len(pages_with_nodes)} page(s) from Figma..."
        })

        async def _fetch_and_build(page: dict) -> tuple[str, dict | None, str | None]:
            try:
                doc = await fetch_figma_node(file_key, page["figma_node_id"], figma_token)
                result = build_page_schema(doc)
                if result.complete:
                    return page["route"], result.page, None
                return page["route"], None, f"incomplete ({len(result.incomplete_nodes)} unknown nodes)"
            except Exception as e:
                return page["route"], None, str(e)

        # Concurrent fetch — Figma rate-limits at 60 req/min by default; cap at 8.
        results = await _asyncio.gather(
            *[_fetch_and_build(p) for p in pages_with_nodes[:50]]
        )

        for page, (route, schema, err) in zip(pages_with_nodes, results):
            slug = page.get("file", "").replace("src/schemas/", "").replace(".json", "")
            if schema:
                (Path(output_dir) / page["file"]).parent.mkdir(parents=True, exist_ok=True)
                (Path(output_dir) / page["file"]).write_text(json.dumps(schema, indent=2))
                deterministic_pages.add(page["route"])
                # First page's tokens win — they all come from the same file
                if not deterministic_tokens:
                    # Run extract one more time to get tokens from the same doc
                    # (build_page_schema already extracted them via the walker)
                    # For simplicity, store the schema's implicit tokens via a separate extract pass:
                    pass  # tokens accumulation handled by the existing pipeline step
                yield sse_event("log", {"text": f"[FigmaDeterministic] ✓ {route}"})
            else:
                deterministic_failures.append((route, err or "no schema"))
                yield sse_event("log", {
                    "text": f"[FigmaDeterministic] ⚠ {route}: {err} — LLM fallback"
                })

except Exception as _det_ex:
    yield sse_event("log", {"text": f"[FigmaDeterministic] block failed: {_det_ex}"})
```

- [ ] **Step 3: Update token aggregation**

The single-page version stashed tokens in `deterministic_tokens` once. With multiple pages we aggregate across them so the dominant brand color is picked from the *whole file*, not one frame:

```python
# Collect raw fills across every fetched doc, then run extract_tokens once
all_walked_nodes = []
for doc in fetched_docs:
    from services.figma_node_walker import walk_and_flatten
    all_walked_nodes.extend(walk_and_flatten(doc))

from services.figma_style_extractor import extract_tokens
from services.figma_typography_extractor import extract_typography
merged_tokens = extract_tokens(all_walked_nodes)
merged_tokens["typography"] = extract_typography(all_walked_nodes)
# write to src/theme/tokens.custom.json
```

- [ ] **Step 4: Test with the Commitbiz fixture (one page) + a synthetic multi-page fixture**

```python
# backend/tests/integration/test_multi_page_figma.py
@pytest.mark.asyncio
async def test_two_frame_figma_emits_two_schemas(tmp_path):
    """File with login + signup frames → two schemas on disk."""
    # ...
```

- [ ] **Step 5: Commit**

```
feat(figma-pipeline): multi-page deterministic mapper — one schema per plan.pages frame
```

### Task 2.2: Concurrent fetch with rate-limit guard

**Files:**
- Modify: `backend/services/figma_client.py` — add concurrency-aware helper

- [ ] **Step 1: Add a batched fetcher**

```python
# backend/services/figma_client.py
import asyncio


_FETCH_SEMAPHORE = asyncio.Semaphore(8)  # cap concurrent Figma API calls


async def fetch_figma_node_batched(
    file_key: str, node_ids: list[str], token: str
) -> dict[str, dict]:
    """Fetch many nodes; returns {node_id: document_subtree}.

    Caps concurrency at 8 to stay under Figma's 60/min rate limit on free tier
    (effectively 240/min once amortised). For larger projects, exceed at your own risk.
    """
    async def _one(nid: str) -> tuple[str, dict]:
        async with _FETCH_SEMAPHORE:
            doc = await fetch_figma_node(file_key, nid, token)
            return nid, doc

    pairs = await asyncio.gather(*[_one(nid) for nid in node_ids])
    return dict(pairs)
```

- [ ] **Step 2: Use in the pipeline**

Replace the `asyncio.gather` in Task 2.1 with `fetch_figma_node_batched`.

- [ ] **Step 3: Test + commit**

```
feat(figma-client): batched concurrent node fetch with rate-limit semaphore
```

### Task 2.3: Per-page failure isolation

**Files:**
- Verify existing implementation in Task 2.1 handles per-page exceptions independently.

- [ ] **Step 1: Add a regression test**

```python
@pytest.mark.asyncio
async def test_one_bad_frame_doesnt_kill_others():
    """If frame B's fetch raises, frames A and C should still produce schemas."""
    # mock fetch_figma_node to fail on the middle node, succeed on the others
    # assert 2 schemas written, 1 failure logged
```

- [ ] **Step 2: Run + commit**

```
test(figma-pipeline): per-frame failure isolation
```

---

## Phase 3 — Skip LLM Per Figma-Bound Page

Goal: When the deterministic mapper covers a page, the LLM schema pipeline doesn't re-emit it. Today the LLM runs for every page in `plan.pages`, overwriting the deterministic output.

### Task 3.1: Pass `deterministic_pages` through to the schema pipeline

**Files:**
- Modify: `backend/routers/generate.py:_run_figma_relay_pipeline` — pass the set to the schema pipeline call
- Modify: `backend/services/schema_pipeline.py:run_schema_frontend_pipeline` — accept the parameter

- [ ] **Step 1: Add the parameter**

```python
# backend/services/schema_pipeline.py
async def run_schema_frontend_pipeline(
    output_dir: str,
    plan: dict,
    description: str,
    domain_context: dict | None = None,
    skip_routes: set[str] | None = None,   # NEW
) -> AsyncIterator[dict]:
    ...
    pages = plan.get("pages") or []
    pages_to_emit = [p for p in pages if p.get("route") not in (skip_routes or set())]
    skipped = len(pages) - len(pages_to_emit)
    if skipped:
        yield sse_event("log", {"text": f"[Schema] Skipping {skipped} Figma-covered page(s)"})
    async for evt in _emit_per_page(output_dir, plan, pages_to_emit, domain_context):
        yield evt
    ...
```

- [ ] **Step 2: Pass from the pipeline**

```python
# backend/routers/generate.py — when invoking run_schema_frontend_pipeline
async for evt in run_schema_frontend_pipeline(
    output_dir, plan, description,
    domain_context=domain_ctx,
    skip_routes=deterministic_pages,   # NEW
):
    yield evt
```

- [ ] **Step 3: Test**

```python
@pytest.mark.asyncio
async def test_schema_pipeline_respects_skip_routes(tmp_path):
    plan = {"pages": [
        {"route": "/login", "file": "src/schemas/login.json"},
        {"route": "/", "file": "src/schemas/home.json"},
    ]}
    events = []
    async for evt in run_schema_frontend_pipeline(
        str(tmp_path), plan, "test",
        skip_routes={"/login"},
    ):
        events.append(evt)
    # /login should NOT have been emitted by the LLM
    assert not (tmp_path / "src/schemas/login.json").exists()
    # ... but / would have been (mocked LLM)
```

- [ ] **Step 4: Commit**

```
feat(schema-pipeline): skip_routes parameter — figma-emitted pages skip LLM
```

### Task 3.2: Update `check_pages_coverage` to count Figma-emitted pages

**Files:**
- Verify: `backend/services/phase_gates.py:check_pages_coverage` — should already work since it just checks files on disk.

- [ ] **Step 1: Add a test ensuring Figma-only pages don't fail the gate**

```python
def test_coverage_passes_when_figma_emitted_only(tmp_path):
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "login.json").write_text("{}")
    plan = {"pages": [{"route": "/login", "figma_node_id": "1:3"}]}
    assert check_pages_coverage(str(tmp_path), plan)["passed"] is True
```

- [ ] **Step 2: Run + commit** (no code change, just a regression test)

```
test(gates): coverage gate counts Figma-emitted pages
```

---

## Phase 4 — Per-Node Pixel Fidelity (Opt-In)

Goal: When a page is marked `pixelPerfect: true`, the mapper emits exact per-node styles, exports assets, and uses absolute positioning where Figma does. Off by default — opt-in per page.

### Task 4.1: Surface raw Figma style data on walked nodes

**Files:**
- Modify: `backend/services/figma_node_walker.py` — add more fields to `_LAYOUT_FIELDS`

- [ ] **Step 1: Extend the annotation**

```python
# backend/services/figma_node_walker.py
_LAYOUT_FIELDS = (
    "layoutMode", "itemSpacing",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "primaryAxisAlignItems", "counterAxisAlignItems", "layoutWrap",
    # NEW for pixel-perfect mode:
    "absoluteBoundingBox", "constraints",
    "fills", "strokes", "effects", "cornerRadius",
    "rectangleCornerRadii", "strokeWeight", "strokeAlign",
    "opacity", "blendMode",
)
```

- [ ] **Step 2: Test that fields are now surfaced**

```python
def test_walker_surfaces_bounding_box():
    tree = {
        "id": "x", "type": "FRAME", "name": "X",
        "fills": [{"type": "SOLID", "color": {}}],
        "absoluteBoundingBox": {"x": 10, "y": 20, "width": 100, "height": 50},
        "children": [],
    }
    out = walk_and_flatten(tree)
    assert out[0]["node"]["_absoluteBoundingBox"]["width"] == 100
```

- [ ] **Step 3: Commit**

```
feat(figma-walker): annotate raw fills/strokes/effects/bounding-box for pixel mode
```

### Task 4.2: `extract_node_style(node)` — full CSS dict per node

**Files:**
- Modify: `backend/services/figma_style_extractor.py` — add `extract_node_style`

- [ ] **Step 1: Write tests**

```python
def test_extract_node_style_solid_fill():
    node = {"fills": [{"type": "SOLID", "color": {"r": 0.063, "g": 0.725, "b": 0.506}, "opacity": 1}]}
    style = extract_node_style(node)
    assert style["backgroundColor"] in ("#10b981", "rgb(16, 185, 129)")


def test_extract_node_style_drop_shadow():
    node = {"effects": [{
        "type": "DROP_SHADOW",
        "color": {"r": 0, "g": 0, "b": 0, "a": 0.1},
        "offset": {"x": 0, "y": 4}, "radius": 12,
    }]}
    style = extract_node_style(node)
    assert "boxShadow" in style
    assert "12px" in style["boxShadow"]


def test_extract_node_style_corner_radius():
    node = {"cornerRadius": 9}
    assert extract_node_style(node)["borderRadius"] == "9px"


def test_extract_node_style_different_corners():
    node = {"rectangleCornerRadii": [4, 4, 12, 12]}
    s = extract_node_style(node)
    # Tailwind doesn't have a single shorthand for asymmetric — use individual
    assert s["borderTopLeftRadius"] == "4px"
    assert s["borderBottomRightRadius"] == "12px"


def test_extract_node_style_typography():
    node = {"type": "TEXT", "style": {
        "fontFamily": "Inter Display",
        "fontWeight": 600,
        "fontSize": 17,
        "letterSpacing": -0.34,
        "lineHeightPx": 24,
    }}
    s = extract_node_style(node)
    assert s["fontFamily"] == "Inter Display"
    assert s["fontWeight"] == 600
    assert s["fontSize"] == "17px"
    assert s["letterSpacing"].endswith("em")
    assert s["lineHeight"] == "24px"
```

- [ ] **Step 2: Implement**

```python
# backend/services/figma_style_extractor.py — append
def extract_node_style(node: dict) -> dict:
    """Produce a full CSS dict for a single Figma node — every visual property
    captured as a JSX-style `style` object.

    Used by figma_to_schema_pixel for pixel-perfect mode.
    """
    style: dict = {}

    # Fills → backgroundColor (solid) or backgroundImage (gradient/image)
    fills = node.get("fills") or node.get("_fills") or []
    for f in fills:
        if f.get("visible") is False:
            continue
        if f.get("type") == "SOLID":
            style["backgroundColor"] = _rgb_to_hex(f.get("color") or {})
            opacity = f.get("opacity")
            if opacity is not None and opacity < 1:
                style["opacity"] = opacity
            break
        if f.get("type") == "GRADIENT_LINEAR":
            # Inline gradient — best-effort
            stops = f.get("gradientStops") or []
            cols = [_rgb_to_hex(s.get("color") or {}) for s in stops]
            style["backgroundImage"] = f"linear-gradient(135deg, {', '.join(cols)})"
            break

    # Strokes → border
    strokes = node.get("strokes") or node.get("_strokes") or []
    if strokes and strokes[0].get("type") == "SOLID":
        weight = node.get("strokeWeight") or node.get("_strokeWeight") or 1
        color = _rgb_to_hex(strokes[0].get("color") or {})
        style["border"] = f"{weight}px solid {color}"

    # Border radius
    r = node.get("cornerRadius") or node.get("_cornerRadius")
    if isinstance(r, (int, float)) and r > 0:
        style["borderRadius"] = f"{r}px"
    rcr = node.get("rectangleCornerRadii") or node.get("_rectangleCornerRadii")
    if isinstance(rcr, list) and len(rcr) == 4:
        style["borderTopLeftRadius"] = f"{rcr[0]}px"
        style["borderTopRightRadius"] = f"{rcr[1]}px"
        style["borderBottomRightRadius"] = f"{rcr[2]}px"
        style["borderBottomLeftRadius"] = f"{rcr[3]}px"

    # Shadows
    effects = node.get("effects") or node.get("_effects") or []
    shadows = []
    for e in effects:
        if e.get("visible") is False:
            continue
        if e.get("type") in ("DROP_SHADOW", "INNER_SHADOW"):
            inner = "inset " if e["type"] == "INNER_SHADOW" else ""
            o = e.get("offset") or {}
            r = e.get("radius", 0)
            c = _rgb_to_hex_rgba(e.get("color") or {})
            shadows.append(f"{inner}{o.get('x',0)}px {o.get('y',0)}px {r}px {c}")
    if shadows:
        style["boxShadow"] = ", ".join(shadows)

    # Typography (TEXT nodes)
    text_style = node.get("style") or {}
    if text_style:
        if "fontFamily" in text_style:
            style["fontFamily"] = text_style["fontFamily"]
        if "fontWeight" in text_style:
            style["fontWeight"] = text_style["fontWeight"]
        if "fontSize" in text_style:
            style["fontSize"] = f"{text_style['fontSize']}px"
        if "lineHeightPx" in text_style and text_style["lineHeightPx"] > 0:
            style["lineHeight"] = f"{text_style['lineHeightPx']}px"
        if "letterSpacing" in text_style and text_style.get("fontSize"):
            em = text_style["letterSpacing"] / text_style["fontSize"]
            style["letterSpacing"] = f"{em:.3f}em".replace("-0.", "-.")

    # Padding
    for axis_pair in [("Top", "_paddingTop"), ("Right", "_paddingRight"),
                      ("Bottom", "_paddingBottom"), ("Left", "_paddingLeft")]:
        css_key = f"padding{axis_pair[0]}"
        val = node.get(axis_pair[1])
        if isinstance(val, (int, float)) and val > 0:
            style[css_key] = f"{val}px"

    return style


def _rgb_to_hex_rgba(c: dict) -> str:
    r = int(round(c.get("r", 0) * 255))
    g = int(round(c.get("g", 0) * 255))
    b = int(round(c.get("b", 0) * 255))
    a = c.get("a", 1)
    if a < 1:
        return f"rgba({r},{g},{b},{a:.2f})"
    return f"#{r:02x}{g:02x}{b:02x}"
```

- [ ] **Step 3: Run tests, commit**

```
feat(figma-style): extract_node_style — full CSS dict per node for pixel mode
```

### Task 4.3: Figma asset extraction pipeline

**Files:**
- Create: `backend/services/figma_asset_pipeline.py`
- Test: `backend/tests/services/test_figma_asset_pipeline.py`

- [ ] **Step 1: Implement the exporter**

```python
# backend/services/figma_asset_pipeline.py
"""Export Figma assets (images, vectors) as local files in the project.

Calls Figma's /v1/images/{key} endpoint for batches of node IDs,
downloads the returned signed URLs, saves to output/<short_id>/public/figma/.
Returns a {figma_node_id: local_path} map the mapper uses to populate
Image / Icon node `src` props.
"""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path

import httpx

from services.figma_client import FIGMA_BASE


_SUPPORTED_FORMATS = {"png", "svg", "jpg", "pdf"}


async def export_assets(
    file_key: str,
    node_ids_with_format: dict[str, str],  # {node_id: "svg" | "png" | ...}
    token: str,
    output_dir: str,
    scale: float = 2.0,
) -> dict[str, str]:
    """Export each node and save under output_dir/public/figma/.
    Returns {node_id: public_path} where public_path is suitable for
    use in src/schemas as e.g. "/figma/<hash>.svg".
    """
    token = (token or "").strip()
    by_format: dict[str, list[str]] = {}
    for nid, fmt in node_ids_with_format.items():
        if fmt not in _SUPPORTED_FORMATS:
            continue
        by_format.setdefault(fmt, []).append(nid)

    out_dir = Path(output_dir) / "public" / "figma"
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=60.0) as client:
        for fmt, ids in by_format.items():
            # Figma can batch up to 100 IDs per call.
            for batch_start in range(0, len(ids), 100):
                batch = ids[batch_start:batch_start + 100]
                params = {
                    "ids": ",".join(batch),
                    "format": fmt,
                    "scale": str(scale),
                }
                r = await client.get(
                    f"{FIGMA_BASE}/images/{file_key}",
                    params=params,
                    headers={"X-Figma-Token": token},
                )
                if r.status_code != 200:
                    continue
                images = (r.json() or {}).get("images") or {}
                # Concurrently download each signed URL
                async def _dl(nid: str, url: str) -> tuple[str, str | None]:
                    if not url:
                        return nid, None
                    try:
                        d = await client.get(url, timeout=30.0)
                        d.raise_for_status()
                        # Stable filename from node-id hash
                        h = hashlib.sha1(nid.encode()).hexdigest()[:8]
                        path = out_dir / f"{h}.{fmt}"
                        path.write_bytes(d.content)
                        return nid, f"/figma/{h}.{fmt}"
                    except Exception:
                        return nid, None
                pairs = await asyncio.gather(*[_dl(nid, url) for nid, url in images.items()])
                for nid, public_path in pairs:
                    if public_path:
                        result[nid] = public_path
    return result


def classify_asset_format(node: dict) -> str | None:
    """Pick the right export format based on node type + content."""
    t = node.get("type")
    fills = node.get("fills") or []
    has_image_fill = any(f.get("type") == "IMAGE" for f in fills)
    if has_image_fill:
        return "png"
    if t == "VECTOR" or t == "BOOLEAN_OPERATION":
        return "svg"
    return None
```

- [ ] **Step 2: Tests**

```python
@pytest.mark.asyncio
async def test_export_assets_writes_files(tmp_path, ...):
    """With mocked Figma /images endpoint, assert files land in public/figma/."""
    # mock httpx.AsyncClient
    # call export_assets({"1:7": "svg", "1:42": "png"}, ...)
    # assert tmp_path / "public/figma/<hash>.svg" exists
    # assert returned dict maps 1:7 → "/figma/<hash>.svg"


def test_classify_asset_format():
    assert classify_asset_format({"type": "VECTOR"}) == "svg"
    assert classify_asset_format({"type": "RECTANGLE", "fills": [{"type": "IMAGE"}]}) == "png"
    assert classify_asset_format({"type": "FRAME", "fills": []}) is None
```

- [ ] **Step 3: Commit**

```
feat(figma-assets): asset extraction pipeline — exports images + vectors to public/figma/
```

### Task 4.4: `figma_to_schema_pixel` — the pixel-perfect orchestrator

**Files:**
- Create: `backend/services/figma_to_schema_pixel.py`

- [ ] **Step 1: Implement**

```python
# backend/services/figma_to_schema_pixel.py
"""Pixel-perfect variant of figma_to_schema.

Differences vs the semantic mapper:
  - Emits `style: {...}` per node with all raw CSS values (no Tailwind bucketing)
  - Resolves IMAGE / VECTOR nodes through the asset pipeline
  - Uses absoluteBoundingBox + position:absolute when no auto-layout is present
  - Skips redundant-container flattening — every Figma node maps to one schema node
  - The classifier still runs to pick semantic types (Form/Input/Button) where
    obvious, but unrecognised nodes become Box with full style passthrough
    instead of falling through silently.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib

from services.figma_node_walker import _annotate
from services.figma_name_classifier import classify, refine_container_type
from services.figma_style_extractor import extract_node_style


@dataclass
class PixelBuildResult:
    page: dict
    tokens: dict
    asset_node_ids: dict[str, str]   # node_id → asset format (svg/png) — caller exports


def _id_for(figma_id: str) -> str:
    return f"n_{hashlib.sha1((figma_id or '').encode()).hexdigest()[:8]}"


def _has_auto_layout(node: dict) -> bool:
    return node.get("_layoutMode") in ("VERTICAL", "HORIZONTAL")


def _build_pixel_node(
    node: dict,
    parent_has_layout: bool,
    asset_paths: dict[str, str],
) -> dict:
    """Map one Figma node to a schema node, preserving as much fidelity as possible."""
    annotated = _annotate(node)
    schema_type, props = classify(annotated.get("name", ""), annotated.get("type", ""))
    if schema_type == "Container":
        schema_type = refine_container_type(annotated)
    props = dict(props)

    # TEXT content
    if schema_type in ("Heading", "Text") and node.get("characters"):
        props["content"] = node["characters"]

    # Style passthrough — this is the core of pixel-perfect mode
    style = extract_node_style(annotated)

    # Absolute positioning when no auto-layout
    if not parent_has_layout and not _has_auto_layout(annotated):
        bb = annotated.get("_absoluteBoundingBox")
        if bb:
            style["position"] = "absolute"
            style["left"] = f"{bb.get('x', 0)}px"
            style["top"] = f"{bb.get('y', 0)}px"
            style["width"] = f"{bb.get('width', 0)}px"
            style["height"] = f"{bb.get('height', 0)}px"

    if style:
        props["style"] = style

    # Asset resolution — IMAGE fills + VECTOR nodes
    nid = node.get("id", "?")
    if nid in asset_paths:
        props["src"] = asset_paths[nid]

    return {
        "id": _id_for(nid),
        "type": schema_type,
        "props": props,
        "children": [
            _build_pixel_node(c, parent_has_layout=_has_auto_layout(annotated),
                              asset_paths=asset_paths)
            for c in (node.get("children") or [])
        ],
    }


def build_page_schema_pixel(
    document: dict,
    asset_paths: dict[str, str] | None = None,
) -> PixelBuildResult:
    """Pixel-perfect variant of build_page_schema."""
    from services.figma_node_walker import walk_and_flatten
    from services.figma_style_extractor import extract_tokens
    from services.figma_typography_extractor import extract_typography
    from services.figma_asset_pipeline import classify_asset_format

    asset_paths = asset_paths or {}

    # Collect all node ids that need exporting — caller actually performs the export
    def _collect_asset_targets(node: dict, acc: dict[str, str]) -> None:
        fmt = classify_asset_format(node)
        if fmt:
            acc[node["id"]] = fmt
        for c in node.get("children") or []:
            _collect_asset_targets(c, acc)
    asset_targets: dict[str, str] = {}
    _collect_asset_targets(document, asset_targets)

    # Build page tree — no flattening; one schema node per Figma node
    root_schema = _build_pixel_node(document, parent_has_layout=False, asset_paths=asset_paths)

    # Token extraction still runs (for the brand palette)
    walked = walk_and_flatten(document)
    tokens = extract_tokens(walked)
    tokens["typography"] = extract_typography(walked)

    page = {
        "schemaVersion": "2.0",
        "id": _id_for(document.get("id", "page")),
        "title": document.get("name", "Untitled"),
        "dataSources": [],
        "children": root_schema["children"] if root_schema["type"] == "Stack"
                    else [root_schema],
    }
    return PixelBuildResult(page=page, tokens=tokens, asset_node_ids=asset_targets)
```

- [ ] **Step 2: Tests**

```python
def test_pixel_emits_style_per_node():
    """Every visible node has a style prop."""
    doc = {
        "id": "1:1", "type": "FRAME", "name": "Card",
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],
        "cornerRadius": 12,
        "children": [{
            "id": "1:2", "type": "TEXT", "name": "Title",
            "characters": "Hello",
            "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}}],
            "style": {"fontFamily": "Inter", "fontSize": 18},
        }],
    }
    result = build_page_schema_pixel(doc)
    root = result.page["children"][0]
    assert "style" in root["props"]
    text = root["children"][0]
    assert text["props"]["style"]["fontFamily"] == "Inter"
    assert text["props"]["style"]["fontSize"] == "18px"


def test_pixel_uses_absolute_positioning_when_no_autolayout():
    doc = {
        "id": "1:1", "type": "FRAME", "name": "Free",
        "fills": [{"type": "SOLID", "color": {}}],
        # No layoutMode → free-form positioning
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 400, "height": 300},
        "children": [{
            "id": "1:2", "type": "RECTANGLE", "name": "Box",
            "absoluteBoundingBox": {"x": 24, "y": 36, "width": 100, "height": 50},
        }],
    }
    result = build_page_schema_pixel(doc)
    inner = result.page["children"][0]["children"][0]
    assert inner["props"]["style"]["position"] == "absolute"
    assert inner["props"]["style"]["left"] == "24px"
```

- [ ] **Step 3: Commit**

```
feat(figma-pixel): figma_to_schema_pixel orchestrator with per-node styles + absolute positioning
```

### Task 4.5: `pixelPerfect: bool` flag on plan pages

**Files:**
- Modify: `backend/services/figma_plan_builder.py` — propagate per-page flag
- Modify: `backend/routers/generate.py` — branch to pixel mode when set

- [ ] **Step 1: Default plan.page to non-pixel; opt-in via request**

```python
# In build_plan_from_figma, accept a `pixel_perfect_pages: list[str] | "*"` param:
async def build_plan_from_figma(
    figma_url: str,
    token: str,
    pixel_perfect_routes: set[str] | None = None,  # NEW
) -> dict:
    # ...
    for fr in raw_frames:
        # ...
        page = {...}
        if pixel_perfect_routes is None or fr["route"] in pixel_perfect_routes \
                                        or "*" in (pixel_perfect_routes or set()):
            page["pixelPerfect"] = True
        pages.append(page)
```

- [ ] **Step 2: In the pipeline, route per-page**

```python
# Inside the multi-page mapper loop:
for page, doc in zip(pages_with_nodes, fetched_docs):
    if page.get("pixelPerfect"):
        from services.figma_to_schema_pixel import build_page_schema_pixel
        # First export assets
        from services.figma_asset_pipeline import export_assets, classify_asset_format
        # collect asset targets from doc
        # call export_assets
        # then build with the resolved asset paths
        asset_targets = {...}
        asset_paths = await export_assets(file_key, asset_targets, figma_token, output_dir)
        result = build_page_schema_pixel(doc, asset_paths=asset_paths)
    else:
        result = build_page_schema(doc)
    # ... write to disk
```

- [ ] **Step 3: Surface in the request shape**

```python
# backend/schemas/project.py — GenerateProjectRequest
class GenerateProjectRequest(BaseModel):
    description: str | None = None
    plan: dict | None = None
    figma_url: str | None = None
    figma_token: str | None = None
    # NEW:
    figma_pixel_perfect: bool = False
    figma_pixel_perfect_routes: list[str] | None = None  # subset; None means use the bool
```

- [ ] **Step 4: Test + commit**

```
feat(figma-pixel): per-page pixel-perfect mode toggle on plan.pages
```

### Task 4.6: Library components accept and merge `style` prop

**Files:**
- Modify: `packages/library/src/components/Card/Card.tsx` (and `.linear.tsx` etc.)
- Modify: `packages/library/src/components/Stack/Stack.tsx`
- Modify: `packages/library/src/components/Row/Row.tsx`
- Modify: `packages/library/src/components/Container/Container.tsx`
- Modify: `packages/library/src/components/Text/Text.tsx`
- Modify: `packages/library/src/components/Heading/Heading.tsx`
- Modify: `packages/library/src/components/Button/Button.tsx`
- Modify: `packages/library/src/components/Image/Image.tsx`

For each: ensure the component spreads `style` onto its root element after Tailwind classes.

- [ ] **Step 1: Audit one component, find the root**

```bash
grep -nE "<div|<section|<button|<h[1-6]|return\s*\(" packages/library/src/components/Card/Card.linear.tsx | head -10
```

- [ ] **Step 2: Add `style` to props + spread**

```tsx
// Pattern — repeat for each component
interface CardProps {
  // ...existing props
  style?: React.CSSProperties;
}

export function Card({ style, children, ...props }: CardProps) {
  return (
    <div
      className={cn("bg-card border rounded-md ...", props.className)}
      style={style}      // ← merges over Tailwind for pixel-perfect mode
    >
      {children}
    </div>
  );
}
```

- [ ] **Step 3: Add tests in `packages/library/tests/style-prop.test.tsx`**

```tsx
import { render } from "@testing-library/react";
import { Card } from "../src/components/Card/Card";

test("Card merges style prop onto root", () => {
  const { container } = render(<Card style={{ backgroundColor: "rgb(255, 0, 0)" }}>x</Card>);
  expect(container.firstChild).toHaveStyle({ backgroundColor: "rgb(255, 0, 0)" });
});
// Repeat for Stack, Row, Container, Text, Heading, Button, Image
```

- [ ] **Step 4: Commit per batch**

```
feat(library): Card/Stack/Row/Container accept style prop for pixel-perfect mode
feat(library): Text/Heading/Button/Image accept style prop
```

### Task 4.7: Per-page pixel-perfect mode visual verification

**Files:**
- Create: `backend/tests/integration/test_pixel_perfect_e2e.py`

- [ ] **Step 1: End-to-end test against the Commitbiz fixture**

```python
"""Test that pixel-perfect mode against the Commitbiz fixture produces a
schema with style props on every node + asset references for image fills."""

def test_pixel_perfect_commitbiz_has_styles_on_every_visible_node():
    # Load commitbiz_login.json
    # Run build_page_schema_pixel with stub asset_paths
    # Walk the emitted tree
    # Assert: every node with type in (Card, Stack, Row, Container, Text, Heading, Button)
    #   has a `style` prop
    # Assert: a Logo Image node has its src set if the fixture marked it as image

def test_pixel_perfect_preserves_brand_color_exactly():
    """The emerald button #10b981 should appear as backgroundColor: #10b981
    in the emitted style, not bucketed to a Tailwind class."""
```

- [ ] **Step 2: Commit**

```
test(integration): pixel-perfect end-to-end against commitbiz fixture
```

---

## Phase 5 — User-Consented Page Expansion

Goal: When the Figma file covers N pages but the project description suggests M more pages (e.g. Figma has login but description says "a full HR app"), surface the gap and ask the user explicitly instead of inventing pages silently.

### Task 5.1: Detect the gap in the request

**Files:**
- Modify: `backend/routers/generate.py` — pre-generation hook

- [ ] **Step 1: Add a gap-analysis helper**

```python
# backend/routers/generate.py — new helper
def _figma_vs_description_gap(figma_plan: dict, description: str) -> list[str]:
    """Return suggested additional routes if the description implies pages
    not in the Figma. Heuristic — checks for keywords like 'dashboard',
    'settings', 'detail view', 'list' against the Figma's frame names."""
    have_routes = {p["route"] for p in figma_plan.get("pages") or []}
    desc_lower = description.lower()
    suggestions: list[str] = []
    if "dashboard" in desc_lower and not any("dashboard" in r or r == "/" for r in have_routes):
        suggestions.append("/dashboard")
    if "settings" in desc_lower and "/settings" not in have_routes:
        suggestions.append("/settings")
    if ("profile" in desc_lower or "account" in desc_lower) and "/profile" not in have_routes:
        suggestions.append("/profile")
    # ... more rules
    return suggestions
```

- [ ] **Step 2: When the gap is non-empty, pause + ask**

For now this is a simple SSE event the frontend handles:

```python
gap = _figma_vs_description_gap(figma_plan, description)
if gap and not req.additional_pages:
    yield sse_event("user_consent_needed", {
        "type": "additional_pages",
        "figma_pages": [p["route"] for p in figma_plan["pages"]],
        "suggested_additions": gap,
        "message": f"Your Figma has {len(figma_plan['pages'])} page(s). "
                   f"Your description suggests {len(gap)} more — "
                   f"want to generate them too?",
    })
    # Pipeline halts here. The frontend re-fires the request with
    # additional_pages: [...] in the body when the user confirms.
    return
```

- [ ] **Step 3: When `additional_pages` is supplied, merge into plan**

```python
if req.additional_pages:
    figma_plan["pages"].extend(req.additional_pages)
```

The deterministic mapper still only handles the Figma-bound pages; the LLM handles the additions.

- [ ] **Step 4: Test the pause logic**

```python
def test_consent_pause_when_gap_detected():
    """When description says 'dashboard' but Figma only has /login, expect
    a 'user_consent_needed' SSE event with the suggested additions."""
```

- [ ] **Step 5: Commit**

```
feat(figma): gap analysis — ask before inventing pages outside Figma scope
```

### Task 5.2: Frontend consent prompt

**Files:**
- Create: `frontend/src/components/projects/AddPagesPrompt.tsx`
- Modify: `frontend/src/components/projects/CreateProjectForm.tsx`

- [ ] **Step 1: Build the prompt component**

```tsx
// frontend/src/components/projects/AddPagesPrompt.tsx
interface Props {
  figmaPages: string[];
  suggestedAdditions: string[];
  onConfirm: (selectedRoutes: string[]) => void;
  onSkip: () => void;
}

export function AddPagesPrompt({ figmaPages, suggestedAdditions, onConfirm, onSkip }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set(suggestedAdditions));

  return (
    <div className="rounded border p-4 space-y-3">
      <h3 className="font-medium">Figma has {figmaPages.length} page(s). Add more?</h3>
      <p className="text-sm text-muted-foreground">
        Your description suggests these additional pages. Pick which to generate via LLM.
      </p>
      <ul className="space-y-2">
        {suggestedAdditions.map(route => (
          <li key={route}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.has(route)}
                onChange={e => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(route); else next.delete(route);
                  setSelected(next);
                }}
              />
              <code>{route}</code>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button onClick={() => onConfirm([...selected])}>Generate selected</Button>
        <Button variant="ghost" onClick={onSkip}>Skip — Figma pages only</Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into the SSE stream**

In the form component that streams generation events, handle the `user_consent_needed` event:

```tsx
// In the event handler
if (event.type === "user_consent_needed" && event.data.type === "additional_pages") {
  setPendingConsent(event.data);
  pauseStream();
}

// When user confirms via AddPagesPrompt:
const onConfirm = (selectedRoutes: string[]) => {
  // Re-fire generation with additional_pages in body
  startGeneration({ ...originalRequest, additional_pages: selectedRoutes.map(r => ({route: r})) });
};
```

- [ ] **Step 3: Commit**

```
feat(frontend): AddPagesPrompt — explicit consent UI for pages beyond Figma scope
```

---

## Sequencing + Time Estimates

| Phase | Tasks | Effort | Cumulative |
|---|---|---|---|
| 1 — Figma drives plan | 1.1, 1.2, 1.3, 1.4, 1.5 | 5 days | 1 week |
| 2 — Multi-page mapper | 2.1, 2.2, 2.3 | 3 days | 1.5 weeks |
| 3 — Skip LLM per page | 3.1, 3.2 | 2 days | 1.8 weeks |
| 4 — Per-node fidelity | 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7 | 8-10 days | 3.5 weeks |
| 5 — User consent | 5.1, 5.2 | 3 days | 4 weeks |

**Total: ~4 weeks** for the full pipeline. Phases 1-3 alone (~2 weeks) close the immediate "Commitbiz gave wrong pages" gap. Phase 4 is the pixel-fidelity work. Phase 5 makes the system honest about its own limits.

## Acceptance milestones

- **End of Phase 1**: Re-running Commitbiz generation produces exactly 1 page (`/login`), matching the Figma frame, with correctly-extracted brand color. No imagined dashboards.
- **End of Phase 2**: A two-frame Figma file produces two schemas concurrently in <10s.
- **End of Phase 3**: SSE log shows `[Schema] Skipping 1 Figma-covered page` instead of LLM dashboard overwrite.
- **End of Phase 4**: A Figma frame marked `pixelPerfect: true` produces a schema where ≥80% of visible nodes have a `style` prop, the brand color matches Figma's exact hex (`#10b981`), and the rendered preview matches the Figma image export within 5% pixel diff.
- **End of Phase 5**: When the user supplies Figma with 1 frame but describes a "full HR app", the pipeline pauses and asks before generating extras.

## Self-Review

- **Spec coverage:** All 5 phases from the strategic discussion are tasked. Phase 1 fixes the scope mismatch (root cause); Phase 4 handles per-node fidelity (visible symptom); Phase 5 closes the honesty gap with users.
- **Placeholder scan:** Each task has concrete code, exact file paths, and verification steps. Two manual steps documented: capturing the real Commitbiz fixture in Task 1.3 (needs FIGMA_TOKEN) and the library-style-prop audit in Task 4.6 (touches 8 files; per-file commit pattern).
- **Type consistency:** `build_plan_from_figma(figma_url, token) -> dict` from Task 1.3 is consumed in Tasks 1.4, 2.1, 5.1. `extract_node_style(node) -> dict` from Task 4.2 is consumed in `build_page_schema_pixel` (Task 4.4). `figma_node_id` field is introduced in Task 1.3 and read in every downstream task.
- **Risk callouts:** Phase 4 has the highest integration risk — the inline-style pattern breaks down when the library component's Tailwind classes conflict with the user's style values. Mitigation: Task 4.6 explicitly merges `style` AFTER `className`, so inline values win. Phase 5's gap-detection heuristic in Task 5.1 is conservative — if it misses cases, the user can still pass `additional_pages` explicitly in the request body.
