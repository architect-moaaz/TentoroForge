# Page-Driven Schema Emission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded "list/detail/form per entity" schema emission with one JSON per page in `plan.pages`, so the generated schemas mirror what the user actually asked for.

**Architecture:** Three workstreams. **A** (backend) introduces `run_page_schema_agent` (single page per call) and rewrites `schema_pipeline.py` to iterate `plan.pages` instead of entities. **B** (file layout + resolution) emits `src/schemas/<route-slug>.json` and updates scaffold URL resolution + auto-generated `registry.ts` + downstream gate globs. **C** (compat + editor) preserves the legacy `<entity>/<page-type>.json` layout as a read-through fallback so existing projects keep rendering, and updates the editor's Explorer pane to list pages by route. Each workstream ships incrementally and is independently testable.

**Tech Stack:** Python / FastAPI (backend); Zod / TypeScript (schema + scaffold); Vitest (frontend tests); pytest (backend tests); claude_agent_sdk (LLM dispatch).

**Spec:** This plan is its own spec — derived from the architectural discussion in session 2026-05-12.

---

## Background — what's broken today

**Current pipeline** (`backend/services/schema_pipeline.py:50`):

```python
for entity in entities:
    await run_feature_slice_schema_agent(output_dir, {**plan, "entity": entity})
```

`feature_slice_schema_agent` (`backend/agents/feature_slice_schema_agent.py:51`) is hardcoded to emit `list`, `detail`, `form` for that entity. It writes to `src/schemas/<entity_slug>/<page_type>.json`.

Result: a plan that asks for 2 pages of one entity (e.g. just `list` + `form`) gets 3 files emitted (the canonical CRUD trio). A plan with custom page routes (`/notes`, `/notes/new`, `/notes/[id]/edit`) gets translated back to the trio. `plan.pages` is ignored for schema emission.

**What we want**: 1 entry in `plan.pages` → 1 schema file emitted, named after the route.

---

## File structure

### New files
- `backend/services/route_slug.py` — pure utility: route → file path
- `backend/services/route_slug.test.py` — tests
- `backend/agents/page_schema_agent.py` — new agent: one page at a time
- `backend/tests/agents/test_page_schema_agent.py` — agent tests
- `backend/tests/services/test_route_slug.py` — slug helper tests (pytest)
- `backend/tests/services/test_schema_pipeline_page_driven.py` — pipeline integration test

### Modified files
- `backend/services/schema_pipeline.py` — iterate `plan.pages`, call new agent
- `backend/agents/feature_slice_schema_agent.py` — extract `_update_schema_registry` so the new agent can reuse it; otherwise leave it intact for the legacy fallback path
- `backend/services/phase_gates.py:check_cta_hierarchy` + `check_progressive_disclosure` — update glob from `*/*.json` to include flat `*.json` and nested paths
- `backend/services/registry_extractor.py` — same glob update
- `apps/render-scaffold/src/lib/loadSchema.ts` — try route-slug path first, fall back to legacy
- `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` — minor: pass route prefix to `loadSchema`, no other change
- `frontend/src/components/schema-editor/Explorer.tsx` (or equivalent) — list by route from a flat scan
- The auto-generated `src/schemas/registry.ts` template (emitted by `_update_schema_registry`) — keys are routes, paths are flat

---

## Design decisions (locked in before tasks)

1. **File path scheme**: route → slug by `slugify_route()`:
   - `/` → `home.json`
   - `/notes` → `notes.json`
   - `/notes/new` → `notes/new.json`
   - `/notes/[id]` → `notes/[id].json`
   - `/settings/profile` → `settings/profile.json`
   
   Mirrors the Next.js app-router file layout the generated app will produce.

2. **Entity context still flows to the agent prompt**: each page knows its entity (from `page.entity`) and the prompt builder loads the entity's field list. Filename is route-based, but the LLM still gets `entity = "Note"` so it can emit bindings like `{{item.title}}`.

3. **Legacy fallback**: the old `<entity>/<page-type>.json` layout keeps working as a read fallback in `loadSchema.ts`. Existing projects (genmetrics-1778439719, etc.) keep rendering untouched. Only fresh generations use the new layout.

4. **`plan.pages` is required**: if a plan arrives with no `pages` array, `schema_pipeline.py` falls back to the legacy entity-driven trio behavior. We don't synthesize a default page list. Planner is responsible for emitting `pages`.

5. **Custom page types**: the new agent doesn't care what `page.type` is — it passes it through to the prompt as `archetype`. Dashboards, settings, audit-log pages all use the same code path.

6. **Per-page id uniqueness**: each generated schema's `id` field is `route-slug` (matches the filename stem). Eliminates the current ambiguity where multiple entities have a page with `id: "list"`.

---

## Workstream A — Backend schema generation

### Task 1: Route → slug helper

**Files:**
- Create: `backend/services/route_slug.py`
- Test:   `backend/tests/services/test_route_slug.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# backend/tests/services/test_route_slug.py
import pytest
from services.route_slug import slugify_route, route_from_slug

@pytest.mark.parametrize("route,expected", [
    ("/",                  "home"),
    ("/notes",             "notes"),
    ("/notes/new",         "notes/new"),
    ("/notes/[id]",        "notes/[id]"),
    ("/notes/[id]/edit",   "notes/[id]/edit"),
    ("/settings/profile",  "settings/profile"),
    ("//double//slash/",   "double/slash"),       # normalisation
    ("",                   "home"),                # empty → home
    ("/users-list",        "users-list"),         # hyphens preserved
])
def test_slugify_route(route, expected):
    assert slugify_route(route) == expected

def test_slugify_route_rejects_unsafe():
    # No path traversal, no absolute outside /, no shell chars
    with pytest.raises(ValueError):
        slugify_route("/notes/../etc/passwd")
    with pytest.raises(ValueError):
        slugify_route("/notes; rm -rf /")

@pytest.mark.parametrize("slug,expected", [
    ("home",               "/"),
    ("notes",              "/notes"),
    ("notes/new",          "/notes/new"),
    ("notes/[id]/edit",    "/notes/[id]/edit"),
])
def test_route_from_slug_roundtrip(slug, expected):
    assert route_from_slug(slug) == expected
    # And the round-trip works
    assert slugify_route(route_from_slug(slug)) == slug
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/services/test_route_slug.py -v`
Expected: FAIL — module not found.

- [ ] **Step 1.3: Implement the helper**

```python
# backend/services/route_slug.py
"""Route ↔ file-path slug conversion.

A route like `/notes/new` maps to file `notes/new.json` under
`src/schemas/`. Routes outside the allowed character set are rejected to
prevent path traversal and shell injection — we treat schema paths as
file paths on disk, not as URLs.
"""
from __future__ import annotations
import re

_HOME_SLUG = "home"
# Allowed: lowercase alphanumerics, hyphen, underscore, square brackets (dynamic
# route params), forward slash. Reject everything else.
_SAFE_SEGMENT = re.compile(r"^[a-z0-9_\-\[\]]+$")


def slugify_route(route: str) -> str:
    """Convert a Next.js app-router-style route to a file path slug.

    Rules:
      - "/" or "" → "home"
      - Leading/trailing slashes stripped
      - Repeated slashes collapsed
      - Each segment must match _SAFE_SEGMENT or ValueError is raised

    Example:
        slugify_route("/notes/new") == "notes/new"
        slugify_route("/notes/[id]") == "notes/[id]"
    """
    if not route or route == "/":
        return _HOME_SLUG
    # Strip leading/trailing slashes, collapse repeats
    segments = [seg for seg in route.split("/") if seg]
    for seg in segments:
        if not _SAFE_SEGMENT.match(seg):
            raise ValueError(f"route segment {seg!r} contains unsafe characters")
    return "/".join(segments)


def route_from_slug(slug: str) -> str:
    """Inverse of slugify_route. Used when scanning files back to routes."""
    if slug == _HOME_SLUG:
        return "/"
    return "/" + slug
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/services/test_route_slug.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 1.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/route_slug.py backend/tests/services/test_route_slug.py
git commit -m "$(cat <<'EOF'
feat(schema): route ↔ slug helper for page-driven schema paths

slugify_route("/notes/new") → "notes/new". Used by the upcoming
page_schema_agent to derive output filenames from plan.pages routes.
Rejects path-traversal + shell-injection candidates at the boundary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2: Page schema agent (one page per call)

**Files:**
- Create: `backend/agents/page_schema_agent.py`
- Test:   `backend/tests/agents/test_page_schema_agent.py`

- [ ] **Step 2.1: Write the failing test**

```python
# backend/tests/agents/test_page_schema_agent.py
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from agents.page_schema_agent import run_page_schema_agent


@pytest.mark.asyncio
async def test_emits_one_file_at_route_path(tmp_path):
    plan = {
        "entities": {"Note": {"fields": [{"name": "title", "type": "string"}]}},
    }
    page = {"route": "/notes", "entity": "Note", "type": "list", "name": "NoteList"}

    fake_schema = {
        "schemaVersion": "2", "id": "ignored",
        "route": "/notes", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []},
    }
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)

    written = tmp_path / "src" / "schemas" / "notes.json"
    assert written.exists()
    on_disk = json.loads(written.read_text())
    # id is overwritten to the slug so the file is self-describing
    assert on_disk["id"] == "notes"
    assert on_disk["route"] == "/notes"


@pytest.mark.asyncio
async def test_nested_route_creates_subdirectories(tmp_path):
    plan = {"entities": {"Note": {"fields": []}}}
    page = {"route": "/notes/new", "entity": "Note", "type": "form", "name": "NewNote"}
    fake_schema = {"schemaVersion": "2", "id": "x", "route": "/notes/new", "layout": "main",
                   "root": {"type": "Stack", "id": "r", "children": []}}
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)
    assert (tmp_path / "src" / "schemas" / "notes" / "new.json").exists()


@pytest.mark.asyncio
async def test_home_route_writes_home_json(tmp_path):
    plan = {"entities": {}}
    page = {"route": "/", "entity": None, "type": "dashboard", "name": "Home"}
    fake_schema = {"schemaVersion": "2", "id": "x", "route": "/", "layout": "main",
                   "root": {"type": "Stack", "id": "r", "children": []}}
    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(return_value=fake_schema),
    ):
        await run_page_schema_agent(str(tmp_path), plan, page)
    assert (tmp_path / "src" / "schemas" / "home.json").exists()
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/agents/test_page_schema_agent.py -v`
Expected: FAIL — module not found.

- [ ] **Step 2.3: Implement the agent**

```python
# backend/agents/page_schema_agent.py
"""Page Schema Agent — generates ONE JSON Page schema for a single page entry.

Replaces feature_slice_schema_agent's hardcoded list/detail/form trio. Each
call handles one page from plan.pages and writes one file. Routes determine
the on-disk path.

Signature mirrors the rest of the agent layer:
  run_page_schema_agent(output_dir, plan, page, domain_context=None) -> None
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from services.route_slug import slugify_route
from services.schema_prompt import build_schema_prompt
from services.schema_validator import SchemaValidationError, invalid_ref_pct, validate_token_refs
from services.schema_normalizer import normalize_v2_schema

logger = logging.getLogger(__name__)


async def run_page_schema_agent(
    output_dir: str,
    plan: dict,
    page: dict,
    domain_context: dict | None = None,
) -> None:
    """Generate a single Page JSON schema and write it to disk.

    Args:
        output_dir: Absolute path to the app output directory.
        plan: The full project plan dict (entities, design, etc).
        page: A single page entry from plan.pages — must have:
              - 'route': "/notes" / "/notes/new" / "/notes/[id]"
              - 'entity': name of the primary entity bound on this page
                         (or None for entity-free pages like dashboards)
              - 'type': "list" | "detail" | "form" | "dashboard" | "settings"
              - 'name': human-readable name
        domain_context: Optional domain-specific context injected into prompts.
    """
    os.environ.pop("CLAUDECODE", None)
    route = page.get("route") or "/"
    slug = slugify_route(route)
    out_path = Path(output_dir) / "src" / "schemas" / f"{slug}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    schema_dict = await _generate_schema_for_page(plan, page, slug, domain_context)
    # Self-describing id matches the file path so debug logs are unambiguous.
    schema_dict["id"] = slug
    schema_dict.setdefault("schemaVersion", "2")

    out_path.write_text(json.dumps(schema_dict, indent=2))
    logger.info("[Schema] wrote %s", out_path)


async def _generate_schema_for_page(
    plan: dict,
    page: dict,
    slug: str,
    domain_context: dict | None,
    max_retries: int = 2,
) -> dict:
    """LLM call. Returns a validated Page schema dict."""
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import Message

    # Construct the page brief the prompt builder expects.
    page_brief = {
        "route": page.get("route", f"/{slug}"),
        "role": page.get("role") or "",
        "archetype": page.get("archetype") or page.get("type") or "generic",
    }
    # Inject the focal entity into the plan for the prompt's binding-context block.
    entity_name = page.get("entity")
    entity_def = (plan.get("entities") or {}).get(entity_name) if entity_name else None
    page_plan = {
        **plan,
        "page_type": page.get("type") or "generic",
        "entity": {"name": entity_name, **(entity_def or {})} if entity_def else {},
        "page": page,
    }
    domain = (
        plan.get("domain")
        or (domain_context or {}).get("domain")
        or "general"
    )
    prompt = build_schema_prompt(page_plan, page_brief=page_brief, domain=domain,
                                 design_spec=plan.get("design_spec"))
    if domain_context:
        prompt = f"Domain context: {json.dumps(domain_context)}\n\n{prompt}"

    last_error: str | None = None
    schema_dict: dict | None = None
    for attempt in range(max_retries + 1):
        retry_suffix = (
            f"\n\nPrevious attempt failed validation:\n{last_error}\n"
            "Fix the issue and output the corrected JSON."
            if last_error else ""
        )
        raw_text = await _collect_llm_text(prompt + retry_suffix)
        schema_dict = _extract_json(raw_text)
        if schema_dict is None:
            last_error = f"Could not parse JSON: {raw_text[:200]}"
            continue
        schema_dict = normalize_v2_schema(schema_dict)
        if (err := _validate_schema_json(schema_dict)) is not None:
            last_error = err
            continue
        return schema_dict
    # Fallback: return last attempt even if invalid (renderer is tolerant)
    return schema_dict or _minimal_schema(slug, page.get("type", "generic"))


async def _collect_llm_text(prompt: str) -> str:
    """Run claude_agent_sdk.query and collect all text content blocks.

    Lifted from feature_slice_schema_agent — same shape. The two agents
    co-exist so that legacy plans (entity-only, no pages) keep working
    via the older path.
    """
    from agents.feature_slice_schema_agent import _collect_llm_text as _shared
    return await _shared(prompt)


def _extract_json(text: str) -> dict | None:
    from agents.feature_slice_schema_agent import _extract_json as _shared
    return _shared(text)


def _validate_schema_json(schema_dict: dict) -> str | None:
    from agents.feature_slice_schema_agent import _validate_schema_json as _shared
    return _shared(schema_dict)


def _minimal_schema(slug: str, page_type: str) -> dict:
    return {
        "schemaVersion": "2",
        "id": slug,
        "route": f"/{slug}" if slug != "home" else "/",
        "layout": "main",
        "root": {
            "type": "Stack",
            "id": "root",
            "children": [{
                "type": "Heading",
                "id": "title",
                "props": {"level": 1, "content": page_type.capitalize()},
            }],
        },
    }
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/agents/test_page_schema_agent.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 2.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/agents/page_schema_agent.py backend/tests/agents/test_page_schema_agent.py
git commit -m "$(cat <<'EOF'
feat(schema): page_schema_agent emits one JSON per page route

Replaces the entity-driven trio (list/detail/form) with a per-page
caller contract. Reuses _collect_llm_text / _extract_json /
_validate_schema_json from feature_slice_schema_agent so we don't fork
LLM dispatch + JSON parsing. Path scheme: src/schemas/<route-slug>.json.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3: Rewrite `schema_pipeline.py` to iterate `plan.pages`

**Files:**
- Modify: `backend/services/schema_pipeline.py`
- Test:   `backend/tests/services/test_schema_pipeline_page_driven.py`

- [ ] **Step 3.1: Write the failing test**

```python
# backend/tests/services/test_schema_pipeline_page_driven.py
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from services.schema_pipeline import run_schema_frontend_pipeline


@pytest.mark.asyncio
async def test_emits_one_file_per_plan_page(tmp_path):
    plan = {
        "entities": {"Note": {"fields": []}},
        "pages": [
            {"route": "/notes",     "entity": "Note", "type": "list", "name": "List"},
            {"route": "/notes/new", "entity": "Note", "type": "form", "name": "New"},
        ],
    }
    captured = []
    async def fake_agent(output_dir, plan_in, page, domain_context=None):
        captured.append(page["route"])
        Path(output_dir, "src", "schemas", page["route"].lstrip("/").replace("/", "_") + ".json").parent.mkdir(parents=True, exist_ok=True)
        # Simulate the agent writing a file (so the pipeline can finalize registry.ts)
        out = Path(output_dir) / "src" / "schemas" / (page["route"].lstrip("/") or "home")
        out_path = Path(str(out) + ".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("{}")

    with patch("agents.page_schema_agent.run_page_schema_agent", new=fake_agent):
        events = []
        async for evt in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="test",
        ):
            events.append(evt)

    assert captured == ["/notes", "/notes/new"]
    assert (tmp_path / "src" / "schemas" / "notes.json").exists()
    assert (tmp_path / "src" / "schemas" / "notes" / "new.json").exists()


@pytest.mark.asyncio
async def test_no_plan_pages_falls_back_to_entity_trio(tmp_path):
    """When plan.pages is empty, fall back to the legacy entity-driven path
    so existing plans keep working."""
    plan = {"entities": {"Note": {"fields": []}}, "pages": []}
    legacy_calls = []
    async def fake_legacy(output_dir, plan_in, domain_context=None):
        legacy_calls.append(plan_in.get("entity", {}).get("name"))

    with patch("agents.feature_slice_schema_agent.run_feature_slice_schema_agent", new=fake_legacy):
        async for _ in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="test",
        ):
            pass

    assert legacy_calls == ["Note"]
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/services/test_schema_pipeline_page_driven.py -v`
Expected: FAIL — pipeline still iterates entities only.

- [ ] **Step 3.3: Rewrite `run_schema_frontend_pipeline`**

```python
# backend/services/schema_pipeline.py — full replacement of run_schema_frontend_pipeline
"""Schema Pipeline — generates frontend as JSON Page schemas instead of TSX.

Iterates plan.pages (one JSON per page). Falls back to the legacy
entity-driven trio when plan.pages is absent or empty.

Feature-flagged via SCHEMA_MODE_ENABLED env var (defaults to true).
"""
from __future__ import annotations
import os
import time
from typing import Any, AsyncIterator

from sse_helpers import sse_event

SCHEMA_MODE_ENABLED = os.getenv("SCHEMA_MODE_ENABLED", "true").lower() in ("true", "1", "yes")


async def run_schema_frontend_pipeline(
    output_dir: str,
    plan: dict[str, Any],
    description: str,
    domain_context: dict[str, Any] | None = None,
) -> AsyncIterator[dict]:
    """Run schema-mode frontend generation.

    Primary path: iterate plan.pages, one LLM call per page.
    Fallback: if plan.pages is empty, iterate entities (legacy trio).
    """
    start = time.time()
    yield sse_event("status", {"message": "Generating frontend via schema agent..."})
    yield sse_event("log", {"text": "[Schema] Using schema-mode (Phase 4) — emits JSON Page schemas"})

    pages = plan.get("pages") or []
    if pages:
        async for evt in _emit_per_page(output_dir, plan, pages, domain_context):
            yield evt
    else:
        async for evt in _emit_legacy_entity_trio(output_dir, plan, domain_context):
            yield evt

    # Regenerate the route-keyed registry.ts after all files are on disk
    _regenerate_route_registry(output_dir)

    duration_ms = int((time.time() - start) * 1000)
    yield sse_event("log", {"text": f"[Schema] Completed in {duration_ms}ms"})


async def _emit_per_page(
    output_dir: str, plan: dict, pages: list[dict], domain_context: dict | None
) -> AsyncIterator[dict]:
    from agents.page_schema_agent import run_page_schema_agent
    yield sse_event("log", {"text": f"[Schema] {len(pages)} page{'s' if len(pages) != 1 else ''} to emit"})
    for page in pages:
        if not isinstance(page, dict):
            yield sse_event("log", {"text": f"[Schema] ⚠ Skipping malformed page entry: {page!r}"})
            continue
        route = page.get("route", "?")
        yield sse_event("status", {"message": f"Generating schema for {route}..."})
        try:
            await run_page_schema_agent(output_dir, plan, page, domain_context=domain_context)
            yield sse_event("log", {"text": f"[Schema] ✓ {route}"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Schema] ⚠ {route} failed: {e}"})


async def _emit_legacy_entity_trio(
    output_dir: str, plan: dict, domain_context: dict | None
) -> AsyncIterator[dict]:
    """Legacy path — used only when plan.pages is empty. Same code as before."""
    from agents.feature_slice_schema_agent import run_feature_slice_schema_agent
    raw_entities = plan.get("data_models") or plan.get("entities") or []
    if isinstance(raw_entities, dict):
        entities: list[dict] = [
            {"name": name, **(defn if isinstance(defn, dict) else {})}
            for name, defn in raw_entities.items()
        ]
    else:
        entities = raw_entities
    yield sse_event("log", {"text": f"[Schema] (legacy trio) {len(entities)} entit{'y' if len(entities)==1 else 'ies'} to process"})
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = entity.get("name", "Unknown")
        if entity.get("legacy_tsx_mode") is True:
            continue
        entity_plan = {**plan, "entity": entity}
        yield sse_event("status", {"message": f"Generating schemas for {name}..."})
        try:
            await run_feature_slice_schema_agent(output_dir, entity_plan, domain_context=domain_context)
            yield sse_event("log", {"text": f"[Schema] ✓ {name} schemas emitted"})
        except Exception as e:
            yield sse_event("log", {"text": f"[Schema] ⚠ {name} failed: {e}"})


def _regenerate_route_registry(output_dir: str) -> None:
    """Scan src/schemas/**/*.json and write registry.ts keyed by route."""
    from pathlib import Path
    from services.route_slug import route_from_slug

    schemas_root = Path(output_dir) / "src" / "schemas"
    if not schemas_root.exists():
        return
    registry_path = schemas_root / "registry.ts"

    entries: list[str] = []
    for json_file in sorted(schemas_root.rglob("*.json")):
        rel = json_file.relative_to(schemas_root)
        slug = str(rel.with_suffix(""))
        route = route_from_slug(slug)
        rel_import = "./" + str(rel)
        entries.append(f'  "{route}": () => import("{rel_import}"),')

    body = "\n".join(entries) if entries else ""
    registry_path.write_text(
        '// Auto-generated by schema_pipeline — do not edit by hand.\n'
        '// Keys are routes (with leading slash). Paths mirror src/schemas/.\n\n'
        'import { loadSchema } from "./load";\n\n'
        'export const schemas: Record<string, () => Promise<unknown>> = {\n'
        f'{body}\n'
        '};\n\n'
        'export async function getSchema(route: string): Promise<ReturnType<typeof loadSchema>> {\n'
        '  const loader = schemas[route];\n'
        '  if (!loader) throw new Error(`unknown route \'${route}\'`);\n'
        '  const raw = await loader();\n'
        '  return loadSchema(route, (raw as any).default ?? raw);\n'
        '}\n'
    )
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/services/test_schema_pipeline_page_driven.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 3.5: Run all existing schema tests to confirm no regression**

Run: `cd backend && python3 -m pytest tests/services/test_schema_prompt.py tests/services/test_schema_prompt_cta.py tests/services/test_schema_prompt_exemplars.py tests/services/test_validate_cta_hierarchy.py tests/services/test_validate_progressive_disclosure.py -v`
Expected: all PASS (48+ tests).

- [ ] **Step 3.6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/schema_pipeline.py backend/tests/services/test_schema_pipeline_page_driven.py
git commit -m "$(cat <<'EOF'
refactor(schema): pipeline iterates plan.pages, falls back to entity trio

run_schema_frontend_pipeline now dispatches one page_schema_agent call
per plan.pages entry. Empty/missing plan.pages preserves the legacy
entity-driven trio so existing plans keep working untouched.
Registry.ts emitted by the pipeline is now keyed by route, not by
entity/page-type pair.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream B — File layout + path resolution

### Task 4: Scaffold `loadSchema.ts` tries route-slug path first

**Files:**
- Modify: `apps/render-scaffold/src/lib/loadSchema.ts`
- Test:   `apps/render-scaffold/src/lib/loadSchema.test.ts` (NEW)

- [ ] **Step 4.1: Read existing loadSchema**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/apps/render-scaffold/src/lib/loadSchema.ts
```

Note the current signature. The new behavior layers on top — it doesn't replace the old.

- [ ] **Step 4.2: Write failing test**

Place test at the location that matches the scaffold's vitest config (likely `apps/render-scaffold/tests/loadSchema.test.ts` — adjust based on what `apps/render-scaffold/vitest.config.ts` says about `include`).

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { promises as fs } from "node:fs";
import path from "node:path";

vi.mock("node:fs", async () => {
  const actual = await vi.importActual<typeof import("node:fs")>("node:fs");
  return { ...actual, promises: { readFile: vi.fn() } };
});

import { loadSchema } from "../src/lib/loadSchema";

describe("loadSchema route-slug resolution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("prefers <slug>.json over legacy <entity>/<type>.json when both exist", async () => {
    const readFile = vi.mocked(fs.readFile);
    readFile.mockImplementation(async (p: any) => {
      if (String(p).endsWith("notes.json")) return JSON.stringify({ id: "notes", route: "/notes" });
      if (String(p).endsWith("notes/list.json")) return JSON.stringify({ id: "notes/list", route: "/notes" });
      throw new Error("ENOENT");
    });
    const result = await loadSchema("/project-root", "notes");
    expect((result as any).id).toBe("notes");  // new path wins
  });

  it("falls back to legacy <entity>/<type>.json when new path missing", async () => {
    const readFile = vi.mocked(fs.readFile);
    readFile.mockImplementation(async (p: any) => {
      if (String(p).endsWith("notes/list.json")) return JSON.stringify({ id: "notes/list" });
      throw new Error("ENOENT");
    });
    const result = await loadSchema("/project-root", "notes/list");
    expect((result as any).id).toBe("notes/list");
  });

  it("returns null when neither path exists", async () => {
    vi.mocked(fs.readFile).mockRejectedValue(new Error("ENOENT"));
    const result = await loadSchema("/project-root", "nonexistent");
    expect(result).toBeNull();
  });
});
```

- [ ] **Step 4.3: Run test, verify FAIL**

Run: `cd apps/render-scaffold && npx vitest run tests/loadSchema.test.ts`
Expected: FAIL — current loadSchema doesn't try the new path layout.

- [ ] **Step 4.4: Modify `loadSchema.ts`**

```ts
// apps/render-scaffold/src/lib/loadSchema.ts
import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Load a schema JSON from a project's src/schemas/ directory.
 *
 * Tries two paths in order:
 *   1. <pagePath>.json                (new route-slug layout)
 *   2. <pagePath>/list.json etc.      (legacy entity/page-type — handled by caller's fallback rules)
 *
 * Returns the parsed JSON or null if neither exists.
 */
export async function loadSchema(
  projectRoot: string,
  pagePath: string,
): Promise<unknown | null> {
  const schemasRoot = path.join(projectRoot, "src", "schemas");
  const candidates = [
    path.join(schemasRoot, `${pagePath}.json`),                          // new
    path.join(schemasRoot, pagePath, "list.json"),                       // legacy list shortcut
  ];
  for (const candidate of candidates) {
    try {
      const text = await fs.readFile(candidate, "utf8");
      return JSON.parse(text);
    } catch {
      // try next
    }
  }
  return null;
}
```

- [ ] **Step 4.5: Run test, verify PASS**

Run: `cd apps/render-scaffold && npx vitest run tests/loadSchema.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 4.6: Commit**

```bash
git add apps/render-scaffold/src/lib/loadSchema.ts apps/render-scaffold/tests/loadSchema.test.ts
git commit -m "$(cat <<'EOF'
feat(scaffold): loadSchema tries route-slug path before legacy layout

<project>/src/schemas/notes.json is preferred over
<project>/src/schemas/notes/list.json. Legacy path remains a fallback
so existing projects render untouched. Caller-side detail/form
fallback rules in [...slug]/page.tsx are unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5: Update `[...slug]/page.tsx` fallback chain

**Files:**
- Modify: `apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx`

- [ ] **Step 5.1: Update the resolver chain**

Find the existing fallback block (around lines 87-100). Replace the resolution logic so it tries:
1. The literal slug as a route-slug path (`notes.json`, `notes/new.json`) — handled inside `loadSchema`
2. If still null and slug looks like a dynamic-param URL (`notes/abc-123`), rewrite the last segment to `[id]` and try `notes/[id].json`
3. Then the existing `new`/`create` → `form` and last-segment → `detail` rules as last-resort fallbacks for legacy projects

```tsx
// Resolution chain — newest layout first, legacy fallbacks last.
const rawSlug = slug.join("/");
let pagePath = rawSlug;
let raw = await loadSchema(projectRoot!, pagePath);

// New layout: dynamic-route placeholder. /notes/abc-123 → /notes/[id]
if (!raw && slug.length >= 2) {
  const dynPath = [...slug.slice(0, -1), "[id]"].join("/");
  raw = await loadSchema(projectRoot!, dynPath);
  if (raw) pagePath = dynPath;
}

// Legacy fallback: <entity>/<page-type>.json patterns
if (!raw && slug.length >= 2) {
  const last = slug[slug.length - 1];
  const entityPath = slug.slice(0, -1).join("/");
  const candidate =
    last === "new" || last === "create"
      ? `${entityPath}/form`
      : `${entityPath}/detail`;
  raw = await loadSchema(projectRoot!, candidate);
  if (raw) pagePath = candidate;
}

if (!raw) notFound();
```

- [ ] **Step 5.2: Smoke check — visit the existing project URLs to confirm legacy still works**

Open in browser:
- http://localhost:6503/p/genmetrics-1778439719/tasks/list  (legacy layout — must still render)
- http://localhost:6503/p/genmetrics-1778439719/tasks/detail
- http://localhost:6503/p/genmetrics-1778439719/users/list

Each must render exactly as before.

- [ ] **Step 5.3: Commit**

```bash
git add apps/render-scaffold/src/app/p/\[projectId\]/\[...slug\]/page.tsx
git commit -m "$(cat <<'EOF'
feat(scaffold): resolver tries [id] dynamic route before legacy fallback

URL /tasks/abc-123 now tries tasks/[id].json before falling through to
the old tasks/detail.json fallback. Legacy projects keep rendering;
new page-driven projects pick up dynamic routes naturally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6: Update phase_gates glob to scan both layouts

**Files:**
- Modify: `backend/services/phase_gates.py:check_cta_hierarchy` and `check_progressive_disclosure`

The current glob is `schemas_dir.glob("*/*.json")` — only finds files exactly one level deep. New layout has files at root level (`notes.json`) and arbitrary depth (`notes/new.json`, `settings/profile.json`).

- [ ] **Step 6.1: Find the existing globs**

```bash
grep -n 'glob("\*/\*\.json")\|rglob' /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/phase_gates.py
```

Should find two sites — one in `check_cta_hierarchy`, one in `check_progressive_disclosure`.

- [ ] **Step 6.2: Replace `glob("*/*.json")` with `rglob("*.json")` and skip `registry.ts`-adjacent helpers**

```python
# In both check_cta_hierarchy and check_progressive_disclosure:
for path in schemas_dir.rglob("*.json"):
    # Skip any meta files (auto-generated)
    if path.name in ("registry.json", "load.json"):
        continue
    try:
        page = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        continue
    # page_type — read from the schema if present, else infer from path
    page["page_type"] = page.get("page_type") or path.stem  # list/detail/form/notes/etc.
    for err in validate_cta_hierarchy(page, cta):
        rel = path.relative_to(schemas_dir).with_suffix("")
        issues.append(f"{rel}: {err}")
```

- [ ] **Step 6.3: Run all gate tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_validate_cta_hierarchy.py tests/services/test_validate_progressive_disclosure.py -v
```

Expected: all PASS.

- [ ] **Step 6.4: Commit**

```bash
git add backend/services/phase_gates.py
git commit -m "$(cat <<'EOF'
fix(gates): phase gates rglob both layouts (route-slug + entity-trio)

check_cta_hierarchy and check_progressive_disclosure now walk
schemas/**/*.json instead of schemas/*/*.json. Picks up both
notes.json (new) and notes/list.json (legacy) layouts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 7: Update registry_extractor scan pattern

**Files:**
- Modify: `backend/services/registry_extractor.py`

- [ ] **Step 7.1: Locate the existing scan**

```bash
grep -n "schemas\|glob\|rglob" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/registry_extractor.py
```

- [ ] **Step 7.2: Update the glob to `rglob("*.json")`**

Same change as Task 6 — `rglob` so both layouts are scanned. The extracted entries should key on the route (read from schema's `route` field) instead of the legacy `<entity>/<page-type>` filename pair.

- [ ] **Step 7.3: Run registry tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/ -k "registry" -v
```

Expected: all PASS.

- [ ] **Step 7.4: Commit**

```bash
git add backend/services/registry_extractor.py
git commit -m "$(cat <<'EOF'
fix(registry): extractor scans both schema layouts via rglob

Keys extracted from schema.route field (or filename stem as fallback)
so route-slug and entity-trio layouts are unified in the registry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream C — Editor + integration

### Task 8: Editor Explorer pane — flat route listing

**Files:**
- Modify: whichever component lists schema files in the editor (`frontend/src/components/schema-editor/Explorer.tsx` or equivalent — grep to find)

- [ ] **Step 8.1: Locate the Explorer pane**

```bash
grep -rln "schemas\|schemaList\|src/schemas" /Users/m/Work/code/poc/design2ui-forge-v3/frontend/src/components/schema-editor/ 2>/dev/null
```

Find the component that lists schemas in the left sidebar.

- [ ] **Step 8.2: Add a backend endpoint that lists pages by route**

If one doesn't exist already:

```python
# backend/routers/_debug_schema.py (or add a new route)
@router.get("/api/projects/{project_id}/schema-list")
async def list_schemas(project_id: str):
    """Return all schemas as [{route, slug, page_type, entity}]."""
    from pathlib import Path
    import json
    from services.route_slug import route_from_slug

    schemas_root = Path("output") / project_id / "src" / "schemas"
    if not schemas_root.exists():
        return []
    entries = []
    for f in sorted(schemas_root.rglob("*.json")):
        if f.name in ("registry.json", "load.json"):
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        rel = f.relative_to(schemas_root).with_suffix("")
        slug = str(rel)
        entries.append({
            "route": data.get("route") or route_from_slug(slug),
            "slug": slug,
            "page_type": data.get("page_type") or f.stem,
            "entity": data.get("entity"),
            "id": data.get("id", slug),
        })
    return entries
```

- [ ] **Step 8.3: Update the Explorer to consume the endpoint and list by route**

Replace the existing entity-grouped tree view (if any) with a flat sorted route list. Example:

```tsx
// Explorer.tsx — fetch + render
useEffect(() => {
  fetch(`/api/projects/${projectId}/schema-list`)
    .then(r => r.json())
    .then(setEntries);
}, [projectId]);

return (
  <ul>
    {entries.map(e => (
      <li key={e.slug}>
        <a onClick={() => openSchema(e.slug)}>
          <code>{e.route}</code>
          <span className="text-xs text-muted-foreground ml-2">{e.page_type}</span>
        </a>
      </li>
    ))}
  </ul>
);
```

- [ ] **Step 8.4: Smoke-test in the browser**

Open http://localhost:6501/editor/genmetrics-1778439719 — sidebar lists 9-10 entries by route, click any → editor loads it.

- [ ] **Step 8.5: Commit**

```bash
git add backend/routers/_debug_schema.py frontend/src/components/schema-editor/Explorer.tsx
git commit -m "$(cat <<'EOF'
feat(editor): Explorer lists schemas by route (flat) instead of entity/page

New endpoint /api/projects/:id/schema-list returns every schema with
route + slug + page_type. Explorer renders a flat sorted list so the
user sees "I have 9 pages" instead of "3 entities each with 3 page
types". Works against both new (route-slug) and legacy (entity-trio)
layouts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 9: End-to-end integration test

**Files:**
- Test: `backend/tests/integration/test_page_driven_generation.py`

- [ ] **Step 9.1: Write the integration test**

```python
# backend/tests/integration/test_page_driven_generation.py
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services.schema_pipeline import run_schema_frontend_pipeline


@pytest.mark.asyncio
async def test_two_page_plan_emits_exactly_two_files(tmp_path):
    plan = {
        "name": "Notes",
        "entities": {"Note": {"fields": [{"name": "title", "type": "string"}]}},
        "pages": [
            {"route": "/notes",     "entity": "Note", "type": "list", "name": "List"},
            {"route": "/notes/new", "entity": "Note", "type": "form", "name": "New"},
        ],
        "design_spec": {"register": "default"},
    }

    def make_fake_schema(slug: str) -> dict:
        return {
            "schemaVersion": "2", "id": slug,
            "route": "/" + slug if slug != "home" else "/",
            "layout": "main",
            "root": {"type": "Stack", "id": "r", "children": []},
        }

    async def fake_generate(plan_in, page, slug, domain_context):
        return make_fake_schema(slug)

    with patch(
        "agents.page_schema_agent._generate_schema_for_page",
        new=AsyncMock(side_effect=fake_generate),
    ):
        async for _ in run_schema_frontend_pipeline(
            output_dir=str(tmp_path), plan=plan, description="x",
        ):
            pass

    # Exactly 2 schema files emitted, no list/detail/form trio
    found = sorted([
        str(p.relative_to(tmp_path / "src" / "schemas"))
        for p in (tmp_path / "src" / "schemas").rglob("*.json")
    ])
    assert found == ["notes.json", "notes/new.json"], f"unexpected files: {found}"

    # registry.ts is keyed by route
    registry = (tmp_path / "src" / "schemas" / "registry.ts").read_text()
    assert '"/notes": () => import("./notes.json"),' in registry
    assert '"/notes/new": () => import("./notes/new.json"),' in registry
```

- [ ] **Step 9.2: Run test, verify PASS**

Run: `cd backend && python3 -m pytest tests/integration/test_page_driven_generation.py -v`
Expected: PASS, 1 test.

- [ ] **Step 9.3: Commit**

```bash
git add backend/tests/integration/test_page_driven_generation.py
git commit -m "$(cat <<'EOF'
test(integration): 2-page plan emits exactly 2 schema files

End-to-end: plan with 2 pages → 2 JSON files at route-slug paths +
registry.ts keyed by route. Asserts the trio is NOT emitted when
plan.pages is present. Mocks the LLM call (we're testing the pipeline
plumbing, not the agent's output quality).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 10: Live smoke run on a 2-page plan

**Files:**
- None — this is a verification step against the running stack.

- [ ] **Step 10.1: Confirm services are up**

```bash
lsof -i :6500 -i :6501 -i :6503 | grep LISTEN
```

If anything's missing: `./start-all.sh`

- [ ] **Step 10.2: Run the metrics script with the existing 2-page plan**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
set -a; source .env; set +a
SHORT_ID=pagedriven-2p-$(date +%s)
python3 -m scripts.generate_with_metrics_v2 \
  --description "Minimal notes app — list + new-note form" \
  --plan-file /tmp/plan-2pages.json \
  --short-id "$SHORT_ID"
```

- [ ] **Step 10.3: Verify exactly 2 schema files emitted**

```bash
ls /Users/m/Work/code/poc/design2ui-forge-v3/output/$SHORT_ID/src/schemas/
# Expected:
#   notes.json
#   notes/
#       new.json
#   registry.ts
#   load.ts
```

If the legacy trio is also emitted (any of `notes/list.json` `notes/detail.json` `notes/form.json` present), the pipeline didn't take the new path — debug `_emit_per_page` invocation.

- [ ] **Step 10.4: Open both pages in the scaffold**

- http://localhost:6503/p/$SHORT_ID/notes        — should render the list schema
- http://localhost:6503/p/$SHORT_ID/notes/new    — should render the form schema

- [ ] **Step 10.5: Open the editor**

http://localhost:6501/editor/$SHORT_ID — Explorer pane should show 2 entries: `/notes` and `/notes/new`.

- [ ] **Step 10.6: Capture timing + page count**

Update `RESUME.md` (or note in the session) with:
- Wall-clock duration
- Files emitted (count + paths)
- Any deviations from expected behavior

No commit on this task — it's purely verification.

---

## Self-review

| Spec requirement | Task |
|---|---|
| `plan.pages` drives schema emission | Tasks 2 + 3 |
| One JSON file per page | Tasks 2 + 9 |
| File path = route slug (`/notes/new` → `notes/new.json`) | Task 1 + 2 |
| Editor lists pages by route, not entity | Task 8 |
| Scaffold renders new layout | Task 4 + 5 |
| Legacy projects keep working | Tasks 3 (fallback) + 4 (loadSchema) + 5 (resolver) |
| CTA / progressive-disclosure gates scan both layouts | Task 6 |
| Registry extractor scans both layouts | Task 7 |
| Tests at each step | Every task |
| Final integration test | Task 9 |

Coverage looks complete. Two notes:

1. **Migration of existing projects is out of scope.** The legacy fallback in `loadSchema.ts` (Task 4) and the pipeline's empty-`plan.pages` fallback (Task 3) ensure existing projects keep working without migration. A separate one-shot script could be written later to convert `output/<id>/src/schemas/<entity>/<page-type>.json` → `output/<id>/src/schemas/<route-slug>.json` based on the project's `app-model.json`, but that's a separate plan.

2. **The 88-min schema phase issue from yesterday's run is orthogonal** — that's the schema agent retrying inside `feature_slice_schema_agent`. The new `page_schema_agent` carries the same retry loop (max 2). If the underlying issue is in `build_schema_prompt` or the LLM call, this refactor surfaces it sooner (one bad page fails one file, not the whole entity batch).

---

## Out of scope

- **Migrating existing projects** to the new layout — separate one-shot script
- **Auto-emitting `plan.pages`** when the planner doesn't supply it — planner-side concern
- **Page-level edit-and-save from the editor** — already works because the editor loads one file at a time; UI listing change is Task 8
- **Dynamic-route schema generation** (`/notes/[id]`) — supported by Task 5's resolver, but the agent emitting bindings like `{{item.id}}` correctly for dynamic routes is its existing prompt concern
- **Removing the legacy `feature_slice_schema_agent`** — left in place as the empty-`plan.pages` fallback. Can be deleted later once all consumers emit `pages`.
