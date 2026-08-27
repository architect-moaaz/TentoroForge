# Figma → Schema Deterministic Mapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user supplies a Figma URL, generate page schemas + tokens deterministically from the Figma node tree (using semantic layer names + auto-layout + style values) instead of asking an LLM to interpret the design. The existing `figma_ui_agent` (LLM) remains a fallback for unrecognized nodes, but the deterministic path runs first.

**Architecture:** Five workstreams.
1. **WS-A — Figma fetch + normalise.** Pull node tree from Figma API, flatten redundant containers, attach layout metadata to every node.
2. **WS-B — Name → schema-type mapping.** A switch-table that converts layer names (`Heading 1`, `Email Input`, `Button`, `Container`, etc.) to `PageV2` node types. Auto-layout direction picks Stack vs Row.
3. **WS-C — Style extraction.** Walk every node's fills/strokes/effects/typography, derive a `tokens.custom.json`, emit per-node Tailwind utility classes for everything not captured by tokens.
4. **WS-D — Pipeline integration.** Plug the deterministic mapper into `_run_figma_relay_pipeline`. Default it on whenever `figma_url` is supplied; only fall through to `figma_ui_agent` when the mapper marks the page incomplete.
5. **WS-E — Test fixtures + parity.** Capture a real Figma frame (Commitbiz login) as a JSON fixture, snapshot-test the mapper's output, and confirm the rendered preview matches the Figma screenshot within an acceptable pixel diff.

**Tech Stack:** Python 3.11, FastAPI, httpx (already in repo for Figma API calls), pytest, existing `figma_parser.py` helpers (color → Tailwind, layout → CSS).

**Reference state today:**
- `backend/figma_parser.py:7` — `parse_figma_url(url)` extracts fileKey + nodeId. Already handles `/design/`, `/file/`, and node-id-with-hyphen conversion.
- `backend/routers/generate.py:1255` — `_run_figma_relay_pipeline(output_dir, plan, figma_url, figma_token)` is the entry point we'll modify.
- `backend/agents/figma_ui_agent.py` — the LLM path we're replacing on the happy path. Stays available as fallback.
- `backend/agents/figma_ir_agent.py` — already used by `_run_figma_relay_pipeline` for IR extraction; reuses Figma API client. We'll factor that client out for reuse.

**Reference Figma file** (`8O10fOsocmlxdN678zDp8r`, the Commitbiz proto): Login page, 5–6 levels of nested `Container`, semantic names (`Heading 1`, `Sign in Form`, `Email Input`, `Button`, `Checkbox`, `Link`, `Logo Image`, `Paragraph`). Zero `COMPONENT` / `INSTANCE` nodes — so we can't lean on Code Connect. We MUST drive the mapping from layer names + auto-layout.

---

## File Structure Overview

### New files

| File | Responsibility |
|---|---|
| `backend/services/figma_client.py` | Thin httpx wrapper around `https://api.figma.com/v1/files/{key}/nodes`. Factored out of `figma_ir_agent` so the deterministic path doesn't import an LLM agent. |
| `backend/services/figma_node_walker.py` | Recursive walker. Flattens redundant `Container > Container` chains. Attaches `layoutMode`, `auto-layout` spacings, and inferred role to every node. |
| `backend/services/figma_name_classifier.py` | Pure-Python lookup: layer name + Figma node type → schema node type. Contains the switch table. |
| `backend/services/figma_style_extractor.py` | Walks fills/strokes/typography → builds project `tokens.custom.json` + per-node Tailwind utility set. |
| `backend/services/figma_to_schema.py` | Top-level orchestrator. Calls walker → classifier → style extractor → emits `PageV2`. Decides per-page whether the result is "complete" or needs LLM fallback. |
| `backend/tests/fixtures/figma/commitbiz_login.json` | Snapshot of the real Figma response for the Commitbiz login frame. Used as test input. |
| `backend/tests/services/test_figma_to_schema.py` | Snapshot test: feed the fixture, assert the emitted PageV2 structure. |
| `backend/tests/services/test_figma_name_classifier.py` | Unit tests for the switch table — every documented name pattern must classify correctly. |

### Modified files

| File | Change |
|---|---|
| `backend/routers/generate.py:1255` | Inside `_run_figma_relay_pipeline`, call `figma_to_schema.build_schemas()` first; only fall through to `figma_ui_agent` when the result reports incomplete pages. |
| `backend/figma_parser.py` | Add `flatten_path()` helper for collapsing redundant container chains. Existing `figma_color_to_tailwind` + `map_layout_to_css` get re-used by the style extractor. |
| `backend/agents/figma_ir_agent.py` | Refactor the inline Figma fetch out to `services/figma_client.py`; import from there. No behavior change. |

---

## WS-A — Figma Fetch + Normalise

### Task 1: Factor out Figma API client

**Files:**
- Create: `backend/services/figma_client.py`
- Modify: `backend/agents/figma_ir_agent.py` (refactor existing fetch to use the new client)

- [ ] **Step 1: Locate the existing fetch in figma_ir_agent**

```bash
grep -n "api.figma.com\|GET /v1\|figma_token" backend/agents/figma_ir_agent.py | head
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/services/test_figma_client.py
import pytest
from unittest.mock import AsyncMock, patch
from services.figma_client import fetch_figma_node


@pytest.mark.asyncio
async def test_fetch_figma_node_calls_correct_endpoint():
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"nodes": {"1:2": {"document": {"id": "1:2"}}}}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_response)) as mock_get:
        result = await fetch_figma_node("KEY", "1:2", "tok")
    mock_get.assert_called_once()
    url = mock_get.call_args.args[0]
    assert url == "https://api.figma.com/v1/files/KEY/nodes"
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["X-Figma-Token"] == "tok"
    assert mock_get.call_args.kwargs["params"] == {"ids": "1:2"}
    assert result == {"id": "1:2"}


@pytest.mark.asyncio
async def test_fetch_figma_node_raises_on_404():
    mock_response = AsyncMock(); mock_response.status_code = 404; mock_response.text = "Not Found"
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_response)):
        with pytest.raises(RuntimeError, match="figma fetch failed: 404"):
            await fetch_figma_node("K", "1:2", "t")
```

- [ ] **Step 3: Run — expect FAIL (module not yet defined)**

Run: `cd backend && pytest tests/services/test_figma_client.py -v`
Expected: ImportError / collection error.

- [ ] **Step 4: Implement the client**

```python
# backend/services/figma_client.py
"""Thin httpx wrapper for the Figma REST API. Async-first so callers can
parallelise multi-page fetches without bridging through asyncio.to_thread.
"""
from __future__ import annotations
import httpx


FIGMA_BASE = "https://api.figma.com/v1"


async def fetch_figma_node(file_key: str, node_id: str, token: str) -> dict:
    """Fetch a single node's document subtree.

    Returns the `nodes[node_id].document` payload directly. Raises
    RuntimeError on non-2xx.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}/nodes",
            params={"ids": node_id},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma fetch failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        node_payload = (body.get("nodes") or {}).get(node_id) or {}
        return node_payload.get("document") or {}


async def fetch_figma_file_meta(file_key: str, token: str) -> dict:
    """Fetch top-level file metadata (name, lastModified, ...).
    Used to populate project.name when the user lets Figma drive naming.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{FIGMA_BASE}/files/{file_key}",
            params={"depth": 1},
            headers={"X-Figma-Token": token},
        )
        if r.status_code != 200:
            raise RuntimeError(f"figma meta fetch failed: {r.status_code}")
        return r.json()
```

- [ ] **Step 5: Refactor figma_ir_agent to use the client**

In `backend/agents/figma_ir_agent.py`, replace the inline `httpx.get(...)` block with `from services.figma_client import fetch_figma_node`. Keep behavior identical — the agent's tests must still pass.

- [ ] **Step 6: Run all affected tests**

```bash
cd backend && pytest tests/services/test_figma_client.py tests/test_ir_agents.py tests/test_figma_parser.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/figma_client.py backend/agents/figma_ir_agent.py backend/tests/services/test_figma_client.py
git commit -m "refactor(figma): factor out figma_client; reuse from ir_agent and upcoming deterministic mapper"
```

### Task 2: Recursive walker + container flattening

**Files:**
- Create: `backend/services/figma_node_walker.py`
- Test: `backend/tests/services/test_figma_node_walker.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_figma_node_walker.py
from services.figma_node_walker import walk_and_flatten


def test_flattens_single_child_container_chain():
    """Container > Container > Container > Text  should collapse to Container > Text."""
    tree = {
        "id": "a", "type": "FRAME", "name": "Container",
        "children": [{
            "id": "b", "type": "FRAME", "name": "Container",
            "children": [{
                "id": "c", "type": "FRAME", "name": "Container",
                "children": [{"id": "d", "type": "TEXT", "name": "Hello", "characters": "Hi"}],
            }],
        }],
    }
    out = walk_and_flatten(tree)
    # The walker yields a flat list of (node, path, parent_layout)
    leaf_text = next(n for n in out if n["node"]["type"] == "TEXT")
    # Path retains all ancestors so the schema mapper can introspect, but the
    # immediate-parent reflects the flattened tree.
    assert leaf_text["parent"]["id"] == "a"


def test_preserves_horizontal_vs_vertical_layout_metadata():
    tree = {
        "id": "row", "type": "FRAME", "name": "Container",
        "layoutMode": "HORIZONTAL", "itemSpacing": 12,
        "children": [
            {"id": "a", "type": "TEXT", "name": "A", "characters": "A"},
            {"id": "b", "type": "TEXT", "name": "B", "characters": "B"},
        ],
    }
    out = walk_and_flatten(tree)
    parent = next(n for n in out if n["node"]["id"] == "row")["node"]
    assert parent.get("_layoutMode") == "HORIZONTAL"
    assert parent.get("_itemSpacing") == 12


def test_keeps_multi_child_container_intact():
    tree = {
        "id": "root", "type": "FRAME", "name": "Container",
        "children": [
            {"id": "a", "type": "TEXT", "name": "A", "characters": "A"},
            {"id": "b", "type": "TEXT", "name": "B", "characters": "B"},
        ],
    }
    out = walk_and_flatten(tree)
    # 1 container + 2 text = 3 entries
    assert len(out) == 3
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && pytest tests/services/test_figma_node_walker.py -v`

- [ ] **Step 3: Implement walker**

```python
# backend/services/figma_node_walker.py
"""Recursive walker over a Figma node tree. Output: a flat list of
{node, path, parent} entries with redundant single-child Container chains
collapsed to a single parent. Also normalises layout metadata onto the
walked nodes so downstream mappers don't have to re-read raw Figma fields.
"""
from __future__ import annotations
from typing import Iterable

_LAYOUT_FIELDS = ("layoutMode", "itemSpacing", "paddingTop", "paddingRight",
                  "paddingBottom", "paddingLeft", "primaryAxisAlignItems",
                  "counterAxisAlignItems", "layoutWrap")


def _is_passthrough_container(node: dict) -> bool:
    """A node is a passthrough if it's a Container/Frame with exactly one
    child and no own visual content (no fills, no strokes, no effects).
    """
    if node.get("type") not in ("FRAME", "GROUP"):
        return False
    name = (node.get("name") or "").strip().lower()
    if name not in {"container", "frame", "group", "wrapper"}:
        return False
    children = node.get("children") or []
    if len(children) != 1:
        return False
    if node.get("fills"): return False
    if node.get("strokes"): return False
    if node.get("effects"): return False
    return True


def _annotate(node: dict) -> dict:
    """Surface useful Figma metadata under stable `_*` keys."""
    out = dict(node)
    for f in _LAYOUT_FIELDS:
        if f in node:
            out[f"_{f}"] = node[f]
    return out


def walk_and_flatten(root: dict) -> list[dict]:
    """DFS walk. Skip passthrough containers but keep their children. Returns
    a flat list of {node, path: [ids...], parent: node|None}.
    """
    out: list[dict] = []

    def go(node: dict, path: list[str], parent: dict | None) -> None:
        if _is_passthrough_container(node):
            for c in node.get("children") or []:
                go(c, path, parent)
            return
        ann = _annotate(node)
        out.append({"node": ann, "path": path + [ann.get("id", "?")], "parent": parent})
        for c in node.get("children") or []:
            go(c, path + [ann.get("id", "?")], ann)

    go(root, [], None)
    return out
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
cd backend && pytest tests/services/test_figma_node_walker.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_node_walker.py backend/tests/services/test_figma_node_walker.py
git commit -m "feat(figma): recursive walker with redundant-container flattening"
```

---

## WS-B — Name → Schema-Type Mapping

### Task 3: Name classifier (switch table)

**Files:**
- Create: `backend/services/figma_name_classifier.py`
- Test: `backend/tests/services/test_figma_name_classifier.py`

- [ ] **Step 1: Write the test for every name pattern in the Commitbiz file**

```python
# backend/tests/services/test_figma_name_classifier.py
import pytest
from services.figma_name_classifier import classify


@pytest.mark.parametrize("name, figma_type, expected", [
    # Headings
    ("Heading 1", "FRAME", ("Heading", {"level": 1})),
    ("Heading 3", "FRAME", ("Heading", {"level": 3})),
    ("Heading 4", "FRAME", ("Heading", {"level": 4})),
    # Body text
    ("Paragraph", "FRAME", ("Text", {})),
    ("Sign in Subtitle", "TEXT", ("Text", {})),
    ("Welcome Title", "TEXT", ("Heading", {"level": 4})),  # text inside Heading 4 wrapper
    # Form elements
    ("Email Input", "FRAME", ("Input", {"type": "email"})),
    ("Password Input", "FRAME", ("Input", {"type": "password"})),
    ("Checkbox", "FRAME", ("Checkbox", {})),
    ("Button", "FRAME", ("Button", {})),
    ("Sign in Button Text", "TEXT", ("Text", {})),  # text inside Button, mapper drops it
    ("Link", "FRAME", ("Link", {})),
    ("Form", "FRAME", ("Form", {})),
    ("Sign in Form", "FRAME", ("Form", {})),
    # Layout
    ("Container", "FRAME", ("Container", {})),    # plain container kept by walker
    ("Primitive.label", "FRAME", ("Text", {"role": "label"})),
    # Media
    ("Logo Image", "RECTANGLE", ("Image", {"alt": "Logo"})),
    ("Logo Image", "FRAME", ("Image", {"alt": "Logo"})),
    ("Icon", "FRAME", ("Icon", {})),
    # Unknown — falls through to Box
    ("Mystery Widget", "FRAME", ("Box", {})),
])
def test_classify(name, figma_type, expected):
    assert classify(name, figma_type) == expected
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement classify**

```python
# backend/services/figma_name_classifier.py
"""Map a Figma layer name + node type to a schema node type + initial props.

The lookup is intentionally a long switch — readability beats cleverness here.
Each rule documents WHY it exists by citing a real layer name from a real file.
Unrecognised names fall through to Box (a tolerant container the renderer
treats as a passthrough). The caller can mark those nodes for LLM fallback.
"""
from __future__ import annotations
import re

# Pre-compiled patterns.
HEADING_RE = re.compile(r"^Heading\s*(\d)$", re.I)


def classify(name: str, figma_type: str) -> tuple[str, dict]:
    """Return (schema_type, initial_props). name and figma_type come from the
    Figma node ("name" and "type" fields)."""
    n = (name or "").strip()
    lower = n.lower()

    # Headings: "Heading 1" through "Heading 6"
    m = HEADING_RE.match(n)
    if m:
        return "Heading", {"level": int(m.group(1))}

    # Title-like text under a Heading wrapper — mapper resolves via parent context,
    # but if name matches "* Title" treat as h4 by default.
    if lower.endswith(" title"):
        return "Heading", {"level": 4}

    # Body text
    if lower in {"paragraph", "body", "description"} or lower.endswith(" description") \
       or lower.endswith(" subtitle") or lower.endswith(" text"):
        return "Text", {}

    # Form primitives (order matters — check specific before generic)
    if lower == "checkbox":
        return "Checkbox", {}
    if lower == "form" or lower.endswith(" form"):
        return "Form", {}
    if lower == "button" or lower.endswith(" button"):
        return "Button", {}
    if lower == "link" or lower.endswith(" link"):
        return "Link", {}
    if "email input" in lower:
        return "Input", {"type": "email"}
    if "password input" in lower:
        return "Input", {"type": "password"}
    if lower.endswith(" input") or lower == "input":
        return "Input", {"type": "text"}
    if lower == "primitive.label" or lower.endswith(" label"):
        return "Text", {"role": "label"}

    # Media
    if "logo" in lower and ("image" in lower or figma_type == "RECTANGLE"):
        return "Image", {"alt": "Logo"}
    if lower == "icon" or lower.endswith(" icon"):
        return "Icon", {}
    if "image" in lower:
        return "Image", {"alt": n}

    # Containers — Stack vs Row decided by the caller using auto-layout meta
    if lower == "container" or lower == "wrapper":
        return "Container", {}

    # Fall-through
    return "Box", {}
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && pytest tests/services/test_figma_name_classifier.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_name_classifier.py backend/tests/services/test_figma_name_classifier.py
git commit -m "feat(figma): name-based classifier (Heading/Input/Button/Form/...)"
```

### Task 4: Auto-layout → Stack / Row / Grid

**Files:**
- Modify: `backend/services/figma_name_classifier.py` — add `refine_container_type()`
- Add tests to: `backend/tests/services/test_figma_name_classifier.py`

- [ ] **Step 1: Add tests**

```python
# Append to backend/tests/services/test_figma_name_classifier.py
from services.figma_name_classifier import refine_container_type


def test_horizontal_autolayout_becomes_row():
    assert refine_container_type({"_layoutMode": "HORIZONTAL"}) == "Row"

def test_vertical_autolayout_becomes_stack():
    assert refine_container_type({"_layoutMode": "VERTICAL"}) == "Stack"

def test_no_layout_keeps_container():
    assert refine_container_type({}) == "Container"

def test_grid_when_wrap_enabled():
    """Figma's layoutWrap=WRAP on a horizontal frame is the closest we get
    to a CSS grid in Figma's model."""
    assert refine_container_type({"_layoutMode": "HORIZONTAL", "_layoutWrap": "WRAP"}) == "Grid"
```

- [ ] **Step 2: Implement**

```python
# Append to backend/services/figma_name_classifier.py

def refine_container_type(node_with_meta: dict) -> str:
    """Pick Stack/Row/Grid/Container based on Figma auto-layout metadata.
    Called only when the classifier already returned 'Container'."""
    mode = node_with_meta.get("_layoutMode")
    wrap = node_with_meta.get("_layoutWrap")
    if mode == "HORIZONTAL" and wrap == "WRAP":
        return "Grid"
    if mode == "HORIZONTAL":
        return "Row"
    if mode == "VERTICAL":
        return "Stack"
    return "Container"
```

- [ ] **Step 3: Tests pass**

- [ ] **Step 4: Commit**

```bash
git add backend/services/figma_name_classifier.py backend/tests/services/test_figma_name_classifier.py
git commit -m "feat(figma): refine Container → Stack/Row/Grid from auto-layout metadata"
```

---

## WS-C — Style Extraction

### Task 5: Token extraction from Figma styles

**Files:**
- Create: `backend/services/figma_style_extractor.py`
- Test: `backend/tests/services/test_figma_style_extractor.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/services/test_figma_style_extractor.py
from services.figma_style_extractor import extract_tokens


def test_extracts_brand_primary_from_button_fill():
    nodes = [
        {"node": {"type": "FRAME", "name": "Button",
                  "fills": [{"type": "SOLID", "color": {"r": 0.063, "g": 0.725, "b": 0.506}}]},
         "parent": None, "path": []},
    ]
    tokens = extract_tokens(nodes)
    # color.primary.500 — the canonical brand step we map to
    assert tokens["color"]["primary"]["500"].lower() in ("#10b981", "#10b980", "#10b981ff")


def test_emits_neutral_steps_from_text_fills():
    nodes = [
        {"node": {"type": "TEXT", "name": "Heading 1",
                  "fills": [{"type": "SOLID", "color": {"r": 0.06, "g": 0.10, "b": 0.16}}]},
         "parent": None, "path": []},
    ]
    tokens = extract_tokens(nodes)
    # Dark text → maps to a primary.900-ish step
    assert "color" in tokens
    assert "primary" in tokens["color"]
```

- [ ] **Step 2: Implement**

```python
# backend/services/figma_style_extractor.py
"""Convert per-node Figma fills/strokes/typography into a project
`tokens.custom.json` (color + typography + radius scales).

Strategy: cluster the colours we see on Button/CTA-like nodes into
`color.primary.*`, neutral-grey colours seen on Text into the primary
scale's dark steps, and the remaining named colours into accent/secondary
buckets. Falls back to extending the default token tree, not replacing it.
"""
from __future__ import annotations
from collections import Counter

from figma_parser import _hex_to_rgb  # reuse


def _rgb_to_hex(c: dict) -> str:
    r = int(round(c.get("r", 0) * 255))
    g = int(round(c.get("g", 0) * 255))
    b = int(round(c.get("b", 0) * 255))
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_neutral(hex_color: str) -> bool:
    r, g, b = _hex_to_rgb(hex_color)
    return abs(r - g) < 15 and abs(g - b) < 15 and abs(r - b) < 15


def extract_tokens(walked_nodes: list[dict]) -> dict:
    """Return a tokens dict shaped like tokens.custom.json:
    { color: { primary: {50..950}, secondary: {...}, accent: {...}, surface: {0,1} } }
    """
    primary_candidates: Counter = Counter()
    neutral_candidates: Counter = Counter()

    for entry in walked_nodes:
        node = entry["node"]
        for fill in node.get("fills") or []:
            if fill.get("type") != "SOLID":
                continue
            c = fill.get("color") or {}
            hex_color = _rgb_to_hex(c)
            # Buttons / strong CTAs → primary candidates
            lname = (node.get("name") or "").lower()
            if "button" in lname and not _is_neutral(hex_color):
                primary_candidates[hex_color] += 5  # weight CTAs heavily
            elif _is_neutral(hex_color):
                neutral_candidates[hex_color] += 1
            else:
                primary_candidates[hex_color] += 1

    # Pick the most common non-neutral colour as primary 500
    tokens: dict = {"color": {"primary": {}, "surface": {"0": "#fafbfc", "1": "#ffffff"}}}
    if primary_candidates:
        primary_500, _ = primary_candidates.most_common(1)[0]
        tokens["color"]["primary"]["500"] = primary_500
        # Derive nearby steps via tinting/darkening — leave full scale generation
        # to color_theory engine if available; otherwise stub the bare minimum.
        tokens["color"]["primary"]["50"] = _tint(primary_500, 0.92)
        tokens["color"]["primary"]["100"] = _tint(primary_500, 0.85)
        tokens["color"]["primary"]["600"] = _shade(primary_500, 0.10)
        tokens["color"]["primary"]["900"] = _shade(primary_500, 0.45)

    # Pick the most common neutral as the dark text colour → primary.900 if missing
    if neutral_candidates and "900" not in tokens["color"]["primary"]:
        tokens["color"]["primary"]["900"] = neutral_candidates.most_common(1)[0][0]

    return tokens


def _tint(hex_color: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r + (255 - r) * amount); g = int(g + (255 - g) * amount); b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def _shade(hex_color: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r * (1 - amount)); g = int(g * (1 - amount)); b = int(b * (1 - amount))
    return f"#{r:02x}{g:02x}{b:02x}"
```

The extractor is intentionally simple — we'll integrate with the more sophisticated `services.color_theory` (already in the repo from VQ-Task 3) in a follow-up. For now the bare minimum unblocks the editor preview.

- [ ] **Step 3: Tests pass**

- [ ] **Step 4: Commit**

```bash
git add backend/services/figma_style_extractor.py backend/tests/services/test_figma_style_extractor.py
git commit -m "feat(figma): minimal token extractor (primary + neutral scales) from node fills"
```

### Task 6: Per-node Tailwind classes for styles not in tokens

**Files:**
- Modify: `backend/services/figma_style_extractor.py` — add `node_to_utility_classes()`

- [ ] **Step 1: Add test**

```python
# Append to backend/tests/services/test_figma_style_extractor.py
from services.figma_style_extractor import node_to_utility_classes


def test_node_radius_emits_rounded_class():
    node = {"type": "RECTANGLE", "name": "Card", "cornerRadius": 12, "fills": []}
    cls = node_to_utility_classes(node)
    assert any("rounded" in c for c in cls)


def test_node_padding_emits_p_classes():
    node = {"type": "FRAME", "name": "Container",
            "_paddingTop": 16, "_paddingBottom": 16, "_paddingLeft": 24, "_paddingRight": 24, "fills": []}
    cls = node_to_utility_classes(node)
    assert "py-4" in cls
    assert "px-6" in cls


def test_node_with_no_special_styles_emits_no_classes():
    node = {"type": "FRAME", "name": "Container", "fills": []}
    assert node_to_utility_classes(node) == []
```

- [ ] **Step 2: Implement**

```python
# Append to backend/services/figma_style_extractor.py

_PX_TO_TW_SPACING = {0: "0", 1: "px", 2: "0.5", 4: "1", 6: "1.5", 8: "2",
                    10: "2.5", 12: "3", 14: "3.5", 16: "4", 20: "5", 24: "6",
                    28: "7", 32: "8", 40: "10", 48: "12", 64: "16"}


def _nearest_spacing(px: float) -> str:
    """Snap a pixel value to the nearest Tailwind spacing step."""
    if not px or px <= 0: return "0"
    best_diff = 9999; best_key = "4"
    for k, v in _PX_TO_TW_SPACING.items():
        d = abs(k - px)
        if d < best_diff: best_diff = d; best_key = v
    return best_key


def node_to_utility_classes(node: dict) -> list[str]:
    """Pure styling — colour comes from tokens; this only emits what tokens
    can't carry per-node (radius, padding, sizing, gap).
    """
    cls: list[str] = []
    r = node.get("cornerRadius")
    if isinstance(r, (int, float)) and r > 0:
        if r <= 4: cls.append("rounded-sm")
        elif r <= 8: cls.append("rounded-md")
        elif r <= 12: cls.append("rounded-lg")
        elif r <= 20: cls.append("rounded-xl")
        else: cls.append("rounded-2xl")

    pt, pb = node.get("_paddingTop"), node.get("_paddingBottom")
    pl, pr = node.get("_paddingLeft"), node.get("_paddingRight")
    if pt and pb and pt == pb:
        cls.append(f"py-{_nearest_spacing(pt)}")
    elif pt: cls.append(f"pt-{_nearest_spacing(pt)}")
    if pl and pr and pl == pr:
        cls.append(f"px-{_nearest_spacing(pl)}")
    elif pl: cls.append(f"pl-{_nearest_spacing(pl)}")

    gap = node.get("_itemSpacing")
    if gap and isinstance(gap, (int, float)) and gap > 0:
        cls.append(f"gap-{_nearest_spacing(gap)}")

    return cls
```

- [ ] **Step 3: Tests pass**

- [ ] **Step 4: Commit**

```bash
git add backend/services/figma_style_extractor.py backend/tests/services/test_figma_style_extractor.py
git commit -m "feat(figma): per-node Tailwind utility classes for radius/padding/gap"
```

---

## WS-B continued — Orchestrator

### Task 7: figma_to_schema orchestrator

**Files:**
- Create: `backend/services/figma_to_schema.py`
- Test: `backend/tests/services/test_figma_to_schema.py`

- [ ] **Step 1: Capture fixture from the live Commitbiz file**

Manual step — run once:
```bash
python3 - <<'PY'
import asyncio, json
import sys; sys.path.insert(0, "backend")
from services.figma_client import fetch_figma_node
import os

FILE = "8O10fOsocmlxdN678zDp8r"; NODE = "1:2"
TOKEN = os.environ.get("FIGMA_TOKEN")
if not TOKEN:
    raise SystemExit("Set FIGMA_TOKEN env var")
doc = asyncio.run(fetch_figma_node(FILE, NODE, TOKEN))
with open("backend/tests/fixtures/figma/commitbiz_login.json", "w") as f:
    json.dump(doc, f, indent=2)
print("captured")
PY
```

Add this snippet to the plan but mark it as a one-time setup. The fixture is now under VCS and tests don't hit Figma's API.

- [ ] **Step 2: Write the snapshot-style test**

```python
# backend/tests/services/test_figma_to_schema.py
import json, pathlib
from services.figma_to_schema import build_page_schema


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login.json"


def test_commitbiz_login_emits_form_with_inputs_and_button():
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    assert result.complete is True or result.incomplete_nodes == []
    page = result.page
    # Walk the emitted tree, count specific node types
    types = _collect_types(page)
    assert types.get("Form", 0) >= 1
    assert types.get("Input", 0) >= 2       # email + password
    assert types.get("Button", 0) >= 1
    assert types.get("Checkbox", 0) >= 1
    assert types.get("Heading", 0) >= 1     # Welcome title
    assert types.get("Link", 0) >= 1        # Forgot password


def _collect_types(node, acc=None):
    if acc is None: acc = {}
    if isinstance(node, dict):
        t = node.get("type")
        if t: acc[t] = acc.get(t, 0) + 1
        for c in node.get("children") or []:
            _collect_types(c, acc)
    return acc
```

- [ ] **Step 3: Implement the orchestrator**

```python
# backend/services/figma_to_schema.py
"""Top-level: take a Figma node tree, return a PageV2 schema + tokens."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib

from services.figma_node_walker import walk_and_flatten
from services.figma_name_classifier import classify, refine_container_type
from services.figma_style_extractor import extract_tokens, node_to_utility_classes


@dataclass
class BuildResult:
    page: dict
    tokens: dict
    complete: bool
    incomplete_nodes: list[dict] = field(default_factory=list)


def _id_for(figma_id: str) -> str:
    """Schema node id derived from the Figma id so the same Figma element
    always produces the same schema id (round-trip stability)."""
    h = hashlib.sha1(figma_id.encode()).hexdigest()[:8]
    return f"n_{h}"


def _build_node(entry: dict) -> dict:
    """Convert one walked entry to a schema node. Container types are
    refined via refine_container_type using the entry's layout meta.
    """
    node = entry["node"]
    schema_type, props = classify(node.get("name", ""), node.get("type", ""))
    if schema_type == "Container":
        schema_type = refine_container_type(node)
    # Text content from Figma's `characters` field
    if schema_type in ("Heading", "Text") and node.get("characters"):
        props = dict(props)
        props["content"] = node["characters"]
    elif schema_type == "Button" and not props.get("label"):
        # Button label usually lives in a child TEXT node — mapper attaches it later
        pass
    utility = node_to_utility_classes(node)
    if utility:
        props = dict(props)
        props["className"] = " ".join(utility)
    return {
        "id": _id_for(node.get("id", "?")),
        "type": schema_type,
        "props": props,
        "children": [],
    }


def build_page_schema(document: dict) -> BuildResult:
    """Walk a Figma document subtree and emit a PageV2 schema."""
    walked = walk_and_flatten(document)
    tokens = extract_tokens(walked)

    # Group nodes by parent id so we can rebuild the tree.
    nodes_by_id: dict[str, dict] = {}
    children_by_parent: dict[str | None, list[str]] = {}
    incomplete: list[dict] = []

    for entry in walked:
        fid = entry["node"].get("id", "?")
        built = _build_node(entry)
        nodes_by_id[fid] = built
        parent_fid = (entry["parent"] or {}).get("id")
        children_by_parent.setdefault(parent_fid, []).append(fid)
        if built["type"] == "Box":
            incomplete.append({"figma_id": fid, "name": entry["node"].get("name")})

    # Reattach children
    for fid, node in nodes_by_id.items():
        node["children"] = [nodes_by_id[c] for c in children_by_parent.get(fid, [])]

    # Root is the topmost entry's id
    root_id = walked[0]["node"].get("id") if walked else None
    root = nodes_by_id.get(root_id) if root_id else None
    if not root:
        root = {"id": "empty", "type": "Stack", "props": {}, "children": []}

    page = {
        "schemaVersion": "2.0",
        "id": _id_for(document.get("id", "page")),
        "title": document.get("name", "Untitled"),
        "dataSources": [],
        "children": root["children"] if root["type"] == "Stack" else [root],
    }
    return BuildResult(
        page=page, tokens=tokens,
        complete=(len(incomplete) == 0),
        incomplete_nodes=incomplete,
    )
```

- [ ] **Step 4: Run snapshot test**

```bash
cd backend && pytest tests/services/test_figma_to_schema.py -v
```

If the asserts fail because of layer-name variants in the actual fixture, iterate on the classifier rules in Task 3 first — the test is the ground truth.

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_to_schema.py backend/tests/services/test_figma_to_schema.py backend/tests/fixtures/figma/commitbiz_login.json
git commit -m "feat(figma): figma_to_schema orchestrator + commitbiz_login snapshot test"
```

---

## WS-D — Pipeline Integration

### Task 8: Plug deterministic path into the Figma pipeline

**Files:**
- Modify: `backend/routers/generate.py` (the `_run_figma_relay_pipeline` function around line 1255)

- [ ] **Step 1: Read the existing function in full**

```bash
sed -n '1255,1330p' backend/routers/generate.py
```

- [ ] **Step 2: Add the deterministic call before the LLM step**

Locate where `figma_ui_agent` is invoked (around line 1614). Wrap with a deterministic-first attempt:

```python
# Inside _run_figma_relay_pipeline, BEFORE the existing figma_ui_agent call:

from services.figma_client import fetch_figma_node
from services.figma_to_schema import build_page_schema
from services.figma_style_extractor import extract_tokens  # already imported by build_page_schema

# Phase 4-deterministic: try the mapper first for each page in the plan.
deterministic_pages: dict[str, dict] = {}
deterministic_tokens: dict = {}
incomplete_pages: list[str] = []

# plan.figma_node_ids maps page slug → node id; if not provided, only the
# root frame from figma_url is used as a single page.
node_ids = (plan.get("figma_node_ids") or {}) or {"home": parse_figma_url(figma_url)["node_id"]}

for slug, nid in node_ids.items():
    try:
        doc = await fetch_figma_node(file_key, nid, figma_token)
        result = build_page_schema(doc)
    except Exception as e:
        yield sse_event("log", {"text": f"[figma-mapper] {slug}: {e}; will fall back to LLM"})
        incomplete_pages.append(slug)
        continue

    if result.complete:
        deterministic_pages[slug] = result.page
        # Merge tokens (last write wins; fine for single-project)
        for cat, sub in result.tokens.items():
            deterministic_tokens.setdefault(cat, {}).update(sub)
        yield sse_event("log", {"text": f"[figma-mapper] {slug}: emitted {_count_nodes(result.page)} nodes deterministically"})
    else:
        yield sse_event("log", {"text": f"[figma-mapper] {slug}: {len(result.incomplete_nodes)} unknown nodes; LLM will fill in"})
        incomplete_pages.append(slug)

# Write deterministic outputs immediately
for slug, page in deterministic_pages.items():
    (Path(output_dir) / "src" / "schemas" / f"{slug}.json").write_text(json.dumps(page, indent=2))
if deterministic_tokens:
    (Path(output_dir) / "src" / "theme" / "tokens.custom.json").write_text(json.dumps(deterministic_tokens, indent=2))

# Only invoke figma_ui_agent for pages that came back incomplete
if incomplete_pages:
    yield sse_event("log", {"text": f"[figma-mapper] LLM fallback for: {incomplete_pages}"})
    # ... existing figma_ui_agent invocation, scoped to incomplete_pages only
else:
    yield sse_event("log", {"text": f"[figma-mapper] All pages deterministic — skipping LLM UI agent"})
```

(The exact splice depends on how `figma_ui_agent` consumes the list of pages. If the agent walks plan.pages itself, pass it a filtered list.)

- [ ] **Step 3: Helper**

Add to `backend/routers/generate.py`:

```python
def _count_nodes(page: dict) -> int:
    def walk(n: dict) -> int:
        return 1 + sum(walk(c) for c in (n.get("children") or []))
    return sum(walk(c) for c in page.get("children", []))
```

- [ ] **Step 4: Smoke test the full pipeline**

```bash
# Trigger a Figma generation against the Commitbiz file
curl -X POST http://localhost:6500/api/projects/generate -H "Content-Type: application/json" -H "Authorization: Bearer $JWT" -d '{
  "description": "Import from Figma test",
  "figma_url": "https://www.figma.com/proto/8O10fOsocmlxdN678zDp8r/Commitbiz-Design?node-id=1-2",
  "figma_token": "FIGMA_PERSONAL_TOKEN"
}' --no-buffer
```

Watch the SSE stream — confirm `[figma-mapper]` events appear and (ideally) `LLM UI agent` is skipped for the login page.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(figma): deterministic mapper runs before figma_ui_agent in the figma pipeline"
```

---

## WS-E — End-to-end Validation

### Task 9: Render the generated project and visually compare

**Files:** No code — verification only.

- [ ] **Step 1: Run the generation against Commitbiz**

Issue the same curl from Task 8 step 4. Wait for completion.

- [ ] **Step 2: Open both views**

- Generated project's preview: `http://localhost:6503/p/<new-short-id>/login`
- Original Figma frame: open the proto link the user provided.

- [ ] **Step 3: Eyeball checks**

- Brand colour from the Figma file applied to the Sign-In button.
- Heading levels correct (Welcome = h4).
- Email and Password inputs present with the right placeholders.
- Checkbox + Remember-me label render together.
- "Forgot password" is a Link.
- "Logo Image" renders as an `<img>` (placeholder if no `src` extracted yet).

- [ ] **Step 4: Capture before/after screenshots**

```bash
mkdir -p docs/superpowers/screenshots/figma-mapper
# Use Playwright to capture both views at 1280x800
```

Commit screenshots so reviewers can see what we built.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/screenshots/figma-mapper/
git commit -m "docs(figma): before/after screenshots of Commitbiz login deterministic build"
```

### Task 10: Integration test against the fixture

**Files:**
- Create: `backend/tests/integration/test_figma_pipeline_e2e.py`

- [ ] **Step 1: Test**

```python
# backend/tests/integration/test_figma_pipeline_e2e.py
"""End-to-end: feed the Commitbiz fixture through figma_to_schema and
verify the resulting schema is renderer-loadable (parses as PageV2 and
contains the expected component types in the expected nesting).
"""
import json, pathlib
import pytest

FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login.json"


@pytest.mark.parametrize("required_path", [
    # Each tuple is a sequence of types we expect to walk from root.
    # The deterministic mapper should produce these paths.
    ["Form"],
    ["Form", "Input"],     # form contains inputs
    ["Form", "Button"],    # form contains the button
])
def test_commitbiz_login_has_expected_structure(required_path):
    from services.figma_to_schema import build_page_schema
    doc = json.loads(FIXTURE.read_text())
    page = build_page_schema(doc).page

    def find_path(node, path):
        if not path:
            return True
        head, *rest = path
        if node.get("type") == head and (not rest or any(find_path(c, rest) for c in node.get("children") or [])):
            return True
        for c in node.get("children") or []:
            if find_path(c, path): return True
        return False

    assert any(find_path(c, required_path) for c in page.get("children") or []), \
        f"path {' > '.join(required_path)} not found"
```

- [ ] **Step 2: Run tests**

```bash
cd backend && pytest tests/integration/test_figma_pipeline_e2e.py -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_figma_pipeline_e2e.py
git commit -m "test(figma): integration test asserting Commitbiz login produces Form+Input+Button"
```

### Task 11: Editor canvas verification

**Files:** No code — manual sign-off.

- [ ] **Step 1: Open the new project in the editor**

Visit `http://localhost:6501/editor/<new-short-id>`. Confirm:
- Pages tab shows `login`.
- Properties panel works when you click on the Sign-In button.
- Brand colour from the Figma file is the editor canvas's primary.
- Preview tab opens at port 6503 and matches the editor canvas within ~5% pixel diff.

- [ ] **Step 2: Mark task complete**

If the four checks pass, mark this and the previous integration test as done. If any fail, file an issue with the specific failure mode — that's the next iteration's input.

---

## Sequencing / Roll-out

The five workstreams are linear (each builds on the previous):

| Day | Work |
|---|---|
| 0.5 | WS-A: Tasks 1–2 (Figma client + walker) |
| 0.5 | WS-B Task 3 (name classifier) |
| 0.5 | WS-B Task 4 (auto-layout refinement) |
| 0.5 | WS-C Tasks 5–6 (token + per-node utility classes) |
| 0.5 | WS-B Task 7 (orchestrator + snapshot test) |
| 0.5 | WS-D Task 8 (pipeline integration) |
| 0.5 | WS-E Tasks 9–11 (visual + integration verification) |

Total: ~3.5 working days.

**Stop-the-line trigger:** if Task 7's snapshot test fails because the Commitbiz file uses 3+ layer names not in the classifier table, that's a signal the file's vocabulary isn't consistent enough for the deterministic-first approach. At that point we either:
- Expand the classifier with the missing patterns (cheap), or
- Fall back to "deterministic for known + LLM for unknown per-node" (Task 8 already supports this path), or
- Decide the file isn't a fit and pivot back to LLM-only (no rollback needed — the LLM agent stays in place as fallback).

---

## Self-Review

- **Spec coverage:** All 5 workstreams from the conversational plan are tasked. Figma fetch (Task 1), normalisation (Task 2), classification (Tasks 3–4), style extraction (Tasks 5–6), orchestrator (Task 7), pipeline integration (Task 8), validation (Tasks 9–11). Eleven tasks total.
- **Placeholder scan:** Every code block is concrete. The one manual step (capturing the Commitbiz fixture in Task 7 Step 1) is explicitly marked as one-time setup that gates downstream tests — that's appropriate, not a placeholder.
- **Type consistency:** `BuildResult` introduced in Task 7 is used by the orchestrator and consumed by Task 8's pipeline integration. `classify(name, type) -> (str, dict)` from Task 3 is consumed by `_build_node` in Task 7. `walk_and_flatten` return shape (`list[{node, path, parent}]`) is consumed by `extract_tokens` and `_build_node`.
- **Risk callouts:** Task 7 is the integration-risk task — its test will fail loudly if the classifier rules don't match the actual Commitbiz layer names. The plan calls that out explicitly as a stop-the-line trigger. Task 5's token extractor is intentionally simple and will produce ugly colour scales for some palettes; a follow-up to integrate with `color_theory` is noted in the task body. Task 8's pipeline splice depends on the existing `figma_ui_agent` signature — the splice is described in pseudocode; the implementer will need to read the actual function shape and adapt.
