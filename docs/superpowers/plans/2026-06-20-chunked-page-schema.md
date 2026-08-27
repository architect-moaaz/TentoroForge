# Chunked Page-Schema Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate oversized page schemas in bounded chunks (skeleton + per-region fills, then assemble) so no single LLM response exceeds the output-token cap, leaving the fast single-call path unchanged for normal pages.

**Architecture:** A new pure-ish module `backend/services/chunked_schema.py` whose functions take an **injected** async `call_llm(prompt)->str` (so tests never hit the network). `page_schema_agent._generate_schema_for_page` keeps its single-call retry loop, but catches the output-overflow error to switch to chunked generation immediately, and also calls chunked generation as a final fallback before `_minimal_schema`.

**Tech Stack:** Python 3, pytest (run from `backend/` with `/usr/local/bin/python3 -m pytest`). Async tests use `asyncio.run(...)` inside sync test functions — no pytest-asyncio needed.

## Global Constraints

- Tests run from `backend/`: `/usr/local/bin/python3 -m pytest tests/<file> -v`.
- Tests MUST mock the LLM — never hit the network. Inject a fake `call_llm`.
- Preserve existing behavior: `normalize_v2_schema` (from `services.schema_normalizer`), `_validate_schema_json` (returns `None` when valid), and `_minimal_schema` fallback are used **unchanged**.
- Reused helpers (import in the new module): `from agents.feature_slice_schema_agent import _extract_json` (`(str)->dict|None`).
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Out of scope: `shell_layout_agent`, recursive chunking, the "constrain" alternative.

**Schema envelope (single-call and chunked produce the same shape):**
`{"schemaVersion":"2","id":<slug>,"route":<route>,"layout":"main","root":{"type":"Stack","id":"root","children":[...]}}`

---

### Task 1: Overflow detection + module scaffold

**Files:**
- Create: `backend/services/chunked_schema.py`
- Test: `backend/tests/services/test_chunked_schema.py`

**Interfaces:**
- Produces: `is_output_overflow_error(exc: BaseException) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_chunked_schema.py
from services.chunked_schema import is_output_overflow_error


def test_overflow_error_matches_cap_messages():
    for msg in [
        "Claude's response exceeded the 32000 output token maximum",
        "response exceeded the 64000 output token maximum",
        "max_tokens: prompt is too long",
        "Output token limit exceeded",
    ]:
        assert is_output_overflow_error(Exception(msg)) is True


def test_overflow_error_ignores_unrelated():
    assert is_output_overflow_error(Exception("Could not parse JSON")) is False
    assert is_output_overflow_error(ValueError("connection reset")) is False
    assert is_output_overflow_error(None) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/services/chunked_schema.py
"""Chunked page-schema generation.

Large pages overflow the model's single-response output cap. Instead of one giant
LLM response, generate the page ROOT skeleton (region placeholders), then fill each
region's subtree in a separate bounded call, then assemble. Functions take an
injected ``call_llm`` so they are unit-testable without the network.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from agents.feature_slice_schema_agent import _extract_json

CallLLM = Callable[[str], Awaitable[str]]

# Substrings that identify the API output-token overflow (case-insensitive).
_OVERFLOW_MARKERS = ("output token", "max_tokens", "too long", "token limit", "token maximum")


def is_output_overflow_error(exc: BaseException | None) -> bool:
    """True when an exception looks like the LLM output-token cap being hit."""
    if exc is None:
        return False
    msg = str(exc).lower()
    return any(m in msg for m in _OVERFLOW_MARKERS)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/chunked_schema.py backend/tests/services/test_chunked_schema.py
git commit -m "feat(schema): chunked-schema module + output-overflow detection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Skeleton pass + region extraction

**Files:**
- Modify: `backend/services/chunked_schema.py`
- Test: `backend/tests/services/test_chunked_schema.py`

**Interfaces:**
- Consumes: `_extract_json`, `CallLLM`
- Produces:
  - `SKELETON_DIRECTIVE: str`
  - `async generate_skeleton(base_prompt: str, call_llm: CallLLM) -> dict | None`
  - `region_placeholders(skeleton: dict) -> list[dict]` (each `{"id": str, "brief": str}`)

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/services/test_chunked_schema.py
import asyncio
from services.chunked_schema import generate_skeleton, region_placeholders

_SKELETON_JSON = """
{"schemaVersion":"2","root":{"type":"Stack","id":"root","children":[
  {"type":"Region","id":"kpis","brief":"KPI metric tiles"},
  {"type":"Region","id":"chart","brief":"trend chart"},
  {"type":"Region","id":"table","brief":"recent records table"}
]}}
"""


def _llm_returning(text):
    async def _fake(prompt):
        return text
    return _fake


def test_generate_skeleton_parses_and_extracts_regions():
    skel = asyncio.run(generate_skeleton("BASE PROMPT", _llm_returning(_SKELETON_JSON)))
    assert skel is not None
    regions = region_placeholders(skel)
    assert [r["id"] for r in regions] == ["kpis", "chart", "table"]
    assert regions[0]["brief"] == "KPI metric tiles"


def test_generate_skeleton_none_when_no_regions():
    bad = '{"schemaVersion":"2","root":{"type":"Stack","id":"root","children":[]}}'
    assert asyncio.run(generate_skeleton("BASE", _llm_returning(bad))) is None
    assert asyncio.run(generate_skeleton("BASE", _llm_returning("not json"))) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: FAIL — `generate_skeleton` / `region_placeholders` not defined.

- [ ] **Step 3: Implement (append to `chunked_schema.py`)**

```python
SKELETON_DIRECTIVE = """

## OUTPUT OVERRIDE — SKELETON ONLY
IGNORE any earlier instruction to output the full page schema. This page is large and is
being generated in chunks. Output ONLY the page ROOT layout with REGION PLACEHOLDERS — do
NOT expand region contents.

Output a single JSON object EXACTLY of this shape:
{
  "schemaVersion": "2",
  "root": {
    "type": "Stack",
    "id": "root",
    "props": { "direction": "vertical", "gap": "tokens.spacing.semantic.section" },
    "children": [
      { "type": "Region", "id": "<short-slug>", "brief": "<one sentence: what this region holds>" }
    ]
  }
}
Rules: 2-8 regions, one per top-level section of the page, in display order. Every child of
root MUST be a Region with a unique "id" and a "brief". No other top-level node types. No
nested children inside regions. Output ONLY the JSON object.
"""


def region_placeholders(skeleton: dict) -> list[dict]:
    """Extract [{id, brief}] for each Region child of the skeleton root."""
    root = (skeleton or {}).get("root") or {}
    out: list[dict] = []
    for child in (root.get("children") or []):
        if isinstance(child, dict) and child.get("type") == "Region" and child.get("id"):
            out.append({"id": child["id"], "brief": child.get("brief", "")})
    return out


async def generate_skeleton(base_prompt: str, call_llm: CallLLM) -> dict | None:
    """Pass 1 — emit the page root with region placeholders. None on failure."""
    raw = await call_llm(base_prompt + SKELETON_DIRECTIVE)
    skel = _extract_json(raw)
    if not isinstance(skel, dict):
        return None
    root = skel.get("root")
    if not isinstance(root, dict) or not isinstance(root.get("children"), list):
        return None
    if not region_placeholders(skel):
        return None
    return skel
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/chunked_schema.py backend/tests/services/test_chunked_schema.py
git commit -m "feat(schema): chunked skeleton pass + region extraction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Region-fill pass

**Files:**
- Modify: `backend/services/chunked_schema.py`
- Test: `backend/tests/services/test_chunked_schema.py`

**Interfaces:**
- Consumes: `_extract_json`, `CallLLM`
- Produces:
  - `REGION_DIRECTIVE: str`
  - `async fill_region(base_prompt: str, region: dict, call_llm: CallLLM) -> dict | None` (returns a single node dict; forces `node["id"]` to the region id)

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/services/test_chunked_schema.py
from services.chunked_schema import fill_region


def test_fill_region_parses_and_forces_id():
    node_json = '{"type":"Grid","id":"WRONG","children":[{"type":"MetricTile","id":"m1"}]}'
    node = asyncio.run(fill_region("BASE", {"id": "kpis", "brief": "KPI tiles"}, _llm_returning(node_json)))
    assert node is not None
    assert node["type"] == "Grid"
    assert node["id"] == "kpis"          # forced to the region id


def test_fill_region_none_on_bad_output():
    assert asyncio.run(fill_region("BASE", {"id": "x", "brief": "y"}, _llm_returning("nope"))) is None
    assert asyncio.run(fill_region("BASE", {"id": "x", "brief": "y"}, _llm_returning('{"no":"type"}'))) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: FAIL — `fill_region` not defined.

- [ ] **Step 3: Implement (append to `chunked_schema.py`)**

```python
REGION_DIRECTIVE = """

## OUTPUT OVERRIDE — SINGLE REGION ONLY
IGNORE any earlier instruction to output the full page schema. Output ONLY the subtree for
ONE region of this page. Use the design tokens, data bindings, components, and archetype
guidance from above.

Region id: {id}
Region brief: {brief}

Output a single JSON object: ONE node (e.g. {{"type":"Card"|"Stack"|"Grid", "id":"{id}",
"props":{{...}}, "children":[...]}}) that fully renders this region's content. Set the top
node's "id" to "{id}". Output ONLY the JSON object.
"""


async def fill_region(base_prompt: str, region: dict, call_llm: CallLLM) -> dict | None:
    """Pass 2 — emit one region's subtree. None on failure."""
    directive = REGION_DIRECTIVE.format(id=region.get("id", ""), brief=region.get("brief", ""))
    raw = await call_llm(base_prompt + directive)
    node = _extract_json(raw)
    if not isinstance(node, dict) or not node.get("type"):
        return None
    node["id"] = region.get("id") or node.get("id")
    return node
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/chunked_schema.py backend/tests/services/test_chunked_schema.py
git commit -m "feat(schema): chunked region-fill pass

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Assembly (with per-region fallback)

**Files:**
- Modify: `backend/services/chunked_schema.py`
- Test: `backend/tests/services/test_chunked_schema.py`

**Interfaces:**
- Consumes: `region_placeholders`
- Produces: `assemble(skeleton: dict, filled: list[dict | None], page_brief: dict) -> dict`
  - `page_brief` keys used: `"id"` (slug) and `"route"`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/services/test_chunked_schema.py
import json
from services.chunked_schema import assemble


def _skeleton():
    return {"schemaVersion": "2", "root": {"type": "Stack", "id": "root", "children": [
        {"type": "Region", "id": "kpis", "brief": "KPI tiles"},
        {"type": "Region", "id": "chart", "brief": "trend chart"},
    ]}}


def test_assemble_splices_filled_regions_in_order():
    filled = [
        {"type": "Grid", "id": "kpis", "children": []},
        {"type": "Card", "id": "chart", "children": []},
    ]
    out = assemble(_skeleton(), filled, {"id": "overview", "route": "/overview"})
    assert out["schemaVersion"] == "2" and out["id"] == "overview" and out["route"] == "/overview"
    kids = out["root"]["children"]
    assert [k["type"] for k in kids] == ["Grid", "Card"]
    assert [k["id"] for k in kids] == ["kpis", "chart"]
    # No Region placeholders survive
    assert all(k["type"] != "Region" for k in kids)


def test_assemble_failed_region_becomes_placeholder():
    out = assemble(_skeleton(), [{"type": "Grid", "id": "kpis"}, None], {"id": "p", "route": "/p"})
    kids = out["root"]["children"]
    assert kids[0]["type"] == "Grid"                     # good region kept
    assert kids[1]["type"] in ("Card", "Stack")          # failed region → placeholder node
    assert "trend chart" in json.dumps(kids[1])          # brief carried into placeholder
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: FAIL — `assemble` not defined.

- [ ] **Step 3: Implement (append to `chunked_schema.py`)**

```python
def _placeholder_node(region: dict) -> dict:
    """Minimal renderable node for a region whose fill failed."""
    rid = region.get("id") or "region"
    brief = (region.get("brief") or "Section").strip()[:80]
    return {
        "type": "Card",
        "id": rid,
        "children": [
            {"type": "Heading", "id": f"{rid}-h", "props": {"level": 2, "content": brief}},
        ],
    }


def assemble(skeleton: dict, filled: list, page_brief: dict) -> dict:
    """Replace each region placeholder in the skeleton root with its filled subtree
    (or a minimal placeholder when that region failed). Returns the final Page envelope."""
    regions = region_placeholders(skeleton)
    root = dict(skeleton.get("root") or {"type": "Stack", "id": "root"})
    children: list[dict] = []
    for i, region in enumerate(regions):
        node = filled[i] if i < len(filled) else None
        if isinstance(node, dict) and node.get("type"):
            children.append(node)
        else:
            children.append(_placeholder_node(region))
    root["children"] = children
    slug = page_brief.get("id") or "home"
    route = page_brief.get("route") or (f"/{slug}" if slug != "home" else "/")
    return {"schemaVersion": "2", "id": slug, "route": route, "layout": "main", "root": root}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/chunked_schema.py backend/tests/services/test_chunked_schema.py
git commit -m "feat(schema): chunked assembly with per-region fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Orchestrator

**Files:**
- Modify: `backend/services/chunked_schema.py`
- Test: `backend/tests/services/test_chunked_schema.py`

**Interfaces:**
- Consumes: `generate_skeleton`, `region_placeholders`, `fill_region`, `assemble`, `CallLLM`
- Produces: `async generate_chunked_schema(base_prompt: str, page_brief: dict, call_llm: CallLLM) -> dict | None`
  - Returns the assembled Page dict, or `None` when the skeleton pass fails (caller then uses `_minimal_schema`). NOTE: the returned dict is **not** yet normalized/validated — the caller runs `normalize_v2_schema` + `_validate_schema_json`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/services/test_chunked_schema.py
from services.chunked_schema import generate_chunked_schema


def _router_llm(skeleton_json, region_json_by_id):
    """Fake call_llm: returns skeleton for the skeleton directive, else the region's JSON."""
    async def _fake(prompt):
        if "SKELETON ONLY" in prompt:
            return skeleton_json
        for rid, payload in region_json_by_id.items():
            if f"Region id: {rid}" in prompt:
                return payload
        return "{}"
    return _fake


def test_orchestrator_assembles_multi_region_schema():
    skel = _SKELETON_JSON
    regions = {
        "kpis": '{"type":"Grid","id":"kpis","children":[]}',
        "chart": '{"type":"Card","id":"chart","children":[]}',
        "table": '{"type":"Table","id":"table","children":[]}',
    }
    out = asyncio.run(generate_chunked_schema("BASE", {"id": "ov", "route": "/ov"},
                                              _router_llm(skel, regions)))
    assert out is not None
    assert [k["type"] for k in out["root"]["children"]] == ["Grid", "Card", "Table"]
    assert out["id"] == "ov"


def test_orchestrator_none_when_skeleton_fails():
    async def _bad(prompt):
        return "not json"
    assert asyncio.run(generate_chunked_schema("BASE", {"id": "p", "route": "/p"}, _bad)) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: FAIL — `generate_chunked_schema` not defined.

- [ ] **Step 3: Implement (append to `chunked_schema.py`)**

```python
async def generate_chunked_schema(base_prompt: str, page_brief: dict, call_llm: CallLLM) -> dict | None:
    """Two-pass chunked generation. Returns an assembled (un-normalized) Page dict, or
    None when the skeleton pass fails so the caller can fall back to _minimal_schema.
    Each region fill is isolated — a failing region degrades to a placeholder, never aborts."""
    try:
        skeleton = await generate_skeleton(base_prompt, call_llm)
    except Exception:
        skeleton = None
    if skeleton is None:
        return None

    regions = region_placeholders(skeleton)

    async def _safe_fill(region: dict) -> dict | None:
        try:
            return await fill_region(base_prompt, region, call_llm)
        except Exception:
            return None

    filled = await asyncio.gather(*[_safe_fill(r) for r in regions])
    return assemble(skeleton, list(filled), page_brief)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/chunked_schema.py backend/tests/services/test_chunked_schema.py
git commit -m "feat(schema): chunked-generation orchestrator (skeleton -> fills -> assemble)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Wire the hybrid trigger into the page schema agent

**Files:**
- Modify: `backend/agents/page_schema_agent.py` (the `_generate_schema_for_page` retry loop, lines ~296-314)
- Test: `backend/tests/agents/test_page_schema_chunk_trigger.py`

**Interfaces:**
- Consumes: `is_output_overflow_error`, `generate_chunked_schema` (from `services.chunked_schema`), existing `_collect_llm_text`, `normalize_v2_schema`, `_validate_schema_json`, `_minimal_schema`.

READ `backend/agents/page_schema_agent.py:296-314` first. Replace the retry loop + final fallback with the version below. The single-call path is unchanged except: (a) the `_collect_llm_text` call is wrapped so an output-overflow error breaks to chunked mode immediately, and (b) after the loop, chunked generation is attempted before `_minimal_schema`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/test_page_schema_chunk_trigger.py
import asyncio
import agents.page_schema_agent as psa


def _patch(monkeypatch, *, raise_overflow=False, single_text=None, chunked=None):
    async def fake_collect(prompt, *a, **k):
        if raise_overflow:
            raise Exception("Claude's response exceeded the 64000 output token maximum")
        return single_text or ""
    monkeypatch.setattr(psa, "_collect_llm_text", fake_collect)

    async def fake_chunked(base_prompt, page_brief, call_llm):
        return chunked
    monkeypatch.setattr("services.chunked_schema.generate_chunked_schema", fake_chunked)


def _valid_chunked():
    return {"schemaVersion": "2", "id": "rep", "route": "/rep", "layout": "main",
            "root": {"type": "Stack", "id": "root",
                     "children": [{"type": "Heading", "id": "h", "props": {"level": 1, "content": "Report"}}]}}


def test_overflow_routes_to_chunked(monkeypatch):
    _patch(monkeypatch, raise_overflow=True, chunked=_valid_chunked())
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    assert out["id"] == "rep"
    assert out["root"]["children"][0]["props"]["content"] == "Report"


def test_chunked_used_as_fallback_when_single_call_unparseable(monkeypatch):
    # single call returns junk every retry → falls through to chunked
    _patch(monkeypatch, single_text="not json at all", chunked=_valid_chunked())
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    assert out["id"] == "rep"


def test_minimal_schema_when_chunked_also_fails(monkeypatch):
    _patch(monkeypatch, single_text="junk", chunked=None)   # chunked skeleton failed → None
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    # _minimal_schema shape
    assert out["root"]["type"] == "Stack" and out["id"] == "rep"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/agents/test_page_schema_chunk_trigger.py -v`
Expected: FAIL (current code has no chunked path; the overflow exception propagates out unhandled).

- [ ] **Step 3: Implement**

In `backend/agents/page_schema_agent.py`, replace the retry loop + final `return` (currently lines ~296-314) with:

```python
    last_error: str | None = None
    schema_dict: dict | None = None
    overflowed = False
    for attempt in range(max_retries + 1):
        retry_suffix = (
            f"\n\nPrevious attempt failed validation:\n{last_error}\n"
            "Fix the issue and output the corrected JSON."
            if last_error else ""
        )
        try:
            raw_text = await _collect_llm_text(prompt + retry_suffix)
        except Exception as exc:  # noqa: BLE001 — classify, then route
            from services.chunked_schema import is_output_overflow_error
            if is_output_overflow_error(exc):
                overflowed = True
                break  # too large for one response — go straight to chunked
            last_error = f"LLM error: {exc}"
            continue
        schema_dict = _extract_json(raw_text)
        if schema_dict is None:
            last_error = f"Could not parse JSON: {raw_text[:200]}"
            continue
        schema_dict = normalize_v2_schema(schema_dict)
        if (err := _validate_schema_json(schema_dict)) is not None:
            last_error = err
            continue
        return schema_dict

    # Single-call path overflowed or exhausted retries → try chunked generation
    # before giving up to the minimal fallback. _ = overflowed (kept for clarity).
    from services.chunked_schema import generate_chunked_schema
    try:
        chunked = await generate_chunked_schema(
            prompt, {"id": slug, "route": page.get("route", f"/{slug}")}, _collect_llm_text
        )
    except Exception:  # noqa: BLE001 — never let chunking abort generation
        chunked = None
    if chunked is not None:
        chunked = normalize_v2_schema(chunked)
        if _validate_schema_json(chunked) is None:
            return chunked

    return schema_dict or _minimal_schema(slug, page.get("type", "generic"))
```

- [ ] **Step 4: Run to verify it passes + no regression**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/agents/test_page_schema_chunk_trigger.py -v`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -c "import ast; ast.parse(open('agents/page_schema_agent.py').read()); print('OK')"`
Run regression on existing page-schema tests: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/agents/test_page_schema_agent_shell.py -v` (run whichever `tests/agents/test_page_schema*` files exist).
Expected: PASS + `OK`, no regression.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/page_schema_agent.py backend/tests/agents/test_page_schema_chunk_trigger.py
git commit -m "feat(schema): page agent routes oversized pages to chunked generation

Catch the output-token overflow to chunk immediately; also use chunked generation as a
final fallback before _minimal_schema. Single-call fast path unchanged for normal pages.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: End-to-end integration test (mocked LLM)

**Files:**
- Test: `backend/tests/services/test_chunked_schema.py` (add an integration test that runs orchestrator output through the REAL validator)

**Interfaces:**
- Consumes: `generate_chunked_schema`; `from agents.feature_slice_schema_agent import _validate_schema_json`; `from services.schema_normalizer import normalize_v2_schema`

- [ ] **Step 1: Write the test**

```python
# add to backend/tests/services/test_chunked_schema.py
def test_assembled_schema_passes_real_validator():
    from agents.feature_slice_schema_agent import _validate_schema_json
    from services.schema_normalizer import normalize_v2_schema
    skel = _SKELETON_JSON
    regions = {
        "kpis":  '{"type":"Grid","id":"kpis","props":{"columns":3},"children":[{"type":"Heading","id":"k1","props":{"level":2,"content":"KPIs"}}]}',
        "chart": '{"type":"Card","id":"chart","children":[{"type":"Heading","id":"c1","props":{"level":2,"content":"Trend"}}]}',
        "table": '{"type":"Card","id":"table","children":[{"type":"Heading","id":"t1","props":{"level":2,"content":"Recent"}}]}',
    }
    out = asyncio.run(generate_chunked_schema("BASE", {"id": "ov", "route": "/ov"},
                                              _router_llm(skel, regions)))
    out = normalize_v2_schema(out)
    assert _validate_schema_json(out) is None      # passes the existing validator
```

NOTE: If `_validate_schema_json` rejects this minimal-but-valid tree for a reason specific to the real schema (e.g. it requires a particular root prop), adjust the region JSON in the test to satisfy the real validator — the assertion that matters is that an assembled chunked schema CAN pass `_validate_schema_json`. Do NOT weaken the validator.

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py -v`
Expected: PASS (11 tests).

- [ ] **Step 3: Run the full new suite together**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && /usr/local/bin/python3 -m pytest tests/services/test_chunked_schema.py tests/agents/test_page_schema_chunk_trigger.py -v`
Expected: ALL pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/services/test_chunked_schema.py
git commit -m "test(schema): assembled chunked schema passes the real validator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manual verification (after all tasks)

The unit/integration suite (mocked LLM) fully covers the logic. A true live check needs a
real generation of a large page (analytics/intelligence dashboard) on the backend; confirm
its `src/schemas/<page>.json` is a valid multi-region schema and the run log shows no
"exceeded … output token maximum" error. (Requires the backend running outside this session
+ a user-triggered generation; not blocking for merge.)

## Out of scope (restated)

- `shell_layout_agent` blob output (≤ ~30 KB, under the cap).
- Recursive chunking (one level only).
- The "constrain / node-count cap" alternative.
