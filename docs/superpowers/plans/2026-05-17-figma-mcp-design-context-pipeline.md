# Figma MCP `get_design_context` Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace our deterministic Figma → schema mapper with Figma's own Dev Mode code-gen via `get_design_context`. End state: a Figma URL produces schemas that render at ~95% visual fidelity to the original design (2-column layout, real colors, real assets, exact dimensions) — vs the ~10% we have today.

**Architecture pivot:** The 5-day deterministic mapper we built (figma_to_schema + classifier + walker + style/typography extractors) produced structurally-correct but visually-stripped schemas. Figma's MCP `get_design_context` returns production React+Tailwind with exact styles, real assets, and proper layout. Our work shifts from "build a worse Figma Dev Mode" to "transform Figma's Dev Mode output to our PageV2 vocabulary."

**Three workstreams, ~8 tasks.**

1. **WS-A — JSX → PageV2 transformer.** Parse the React JSX `get_design_context` returns into our schema tree. Lift inline className/style onto schema node props. Map `<div>`/`<p>`/`<img>` to Stack/Row/Text/Heading/Image plus a few recognised composite patterns (Email Input, Sign-in Button).
2. **WS-B — Asset download pipeline.** Fetch every `figma.com/api/mcp/asset/...` URL referenced in the JSX, save to `output/<id>/public/figma/<hash>.{png,svg}`, rewrite `src` references in the emitted schema. The MCP CDN URLs expire after 7 days; we cache locally.
3. **WS-C — Pipeline integration + library validator softening.** Replace the call to `build_page_schema(doc)` in `_run_figma_relay_pipeline` with a call to a new `figma_mcp_pipeline.build_from_design_context(figma_url, node_id)`. Soften library Zod validators so partially-populated nodes render with sensible defaults instead of "⚠ invalid props".

**Tech Stack:** Python 3.11 (backend); `esprima` or a lightweight JSX-aware parser (likely just regex + a small recursive descent — the MCP output is regular). httpx for asset download. The existing `figma_plan_builder` keeps driving plan.pages; only the per-page schema source changes.

**Reference state today:**
- Old mapper at `backend/services/figma_to_schema.py` produces minimal/empty schemas — see `output/ntk7e0a0/src/schemas/*.json` rendered output for the failure mode.
- Fixture at `backend/tests/fixtures/figma/commitbiz_login_design_context.tsx` — the actual MCP output for Commitbiz login. Use this as the transformer's input.
- The MCP tool itself (`mcp__claude_ai_Figma__get_design_context`) is invoked by Claude clients with the Figma MCP server configured. For production backend use, we'll need a way to call it — see WS-C Task 6 for the integration options.

---

## File Structure Overview

### New files

| File | WS | Responsibility |
|---|---|---|
| `backend/services/jsx_to_schema.py` | A | `transform_jsx_to_schema(jsx_source, asset_path_map) -> PageV2 dict`. Pure-function transformer. |
| `backend/services/figma_asset_downloader.py` | B | `download_figma_assets(jsx_source, output_dir, ttl_hours=24*7) -> dict[str, str]`. Returns `{cdn_url: local_path}`. |
| `backend/services/figma_mcp_pipeline.py` | C | Orchestrator that ties together: get_design_context (caller-provided), asset download, JSX transformer, schema write. |
| `backend/tests/services/test_jsx_to_schema.py` | A | Unit tests for every JSX pattern: `<div>` → Stack/Row, `<p>` → Text/Heading, "Email Input" composite → Input, etc. |
| `backend/tests/services/test_figma_asset_downloader.py` | B | Tests with mocked httpx — verify URL extraction, file naming, cache reuse. |
| `backend/tests/integration/test_figma_mcp_e2e.py` | C | Feed the fixture JSX through the full pipeline, assert the emitted schema renders correctly. |

### Modified files

| File | WS | Change |
|---|---|---|
| `backend/routers/generate.py:_run_figma_relay_pipeline` | C | Replace `build_page_schema(doc)` call with `figma_mcp_pipeline.build_schema(design_context, asset_paths)`. The `figma_to_schema` mapper stays as fallback when MCP context is unavailable. |
| `packages/library/src/components/Input/Input.tsx` (and Card, Heading, Text, Button, Form, Checkbox, Link, Image) | C | Loosen Zod validators — accept missing optional props with sensible defaults (empty string, `name="field"`). Stop showing "⚠ invalid props" for partial inputs. |

---

## WS-A — JSX → PageV2 Transformer

### Task A.1: Lightweight JSX parser

**Files:**
- Create: `backend/services/jsx_to_schema.py`
- Test: `backend/tests/services/test_jsx_to_schema.py`

The MCP output is regular React with no JS expressions in JSX (except `src={imgX}` interpolation). A small recursive-descent parser handles it without needing a full JS AST.

- [ ] **Step 1: Write the parser tests**

```python
# backend/tests/services/test_jsx_to_schema.py
from services.jsx_to_schema import parse_jsx_tree, JSXElement


def test_parses_simple_div():
    src = '<div className="flex">hello</div>'
    tree = parse_jsx_tree(src)
    assert tree.tag == "div"
    assert tree.attrs["className"] == "flex"
    assert tree.children == ["hello"]


def test_parses_nested_elements():
    src = '<div><p>hi</p><img src="x" /></div>'
    tree = parse_jsx_tree(src)
    assert tree.tag == "div"
    assert len(tree.children) == 2
    assert tree.children[0].tag == "p"
    assert tree.children[1].tag == "img"
    assert tree.children[1].attrs["src"] == "x"


def test_parses_data_attrs():
    src = '<div data-node-id="1:2" data-name="Login">x</div>'
    tree = parse_jsx_tree(src)
    assert tree.attrs["data-node-id"] == "1:2"
    assert tree.attrs["data-name"] == "Login"


def test_parses_style_object():
    src = '<div style={{ backgroundColor: "red" }}>x</div>'
    tree = parse_jsx_tree(src)
    assert tree.attrs["style"] == {"backgroundColor": "red"}


def test_parses_style_with_linear_gradient():
    src = '<div style={{ backgroundImage: "linear-gradient(90deg, red, blue)" }}>x</div>'
    tree = parse_jsx_tree(src)
    assert "linear-gradient" in tree.attrs["style"]["backgroundImage"]


def test_parses_src_interpolation():
    """src={imgLogo} should be normalised to the value of imgLogo constant."""
    src = '''
    const imgLogo = "https://cdn/abc.png";
    function App() {
      return <img src={imgLogo} alt="" />;
    }
    '''
    tree = parse_jsx_tree(src)
    # find img descendant
    img = tree.find_descendant(lambda n: hasattr(n, "tag") and n.tag == "img")
    assert img.attrs["src"] == "https://cdn/abc.png"
```

- [ ] **Step 2: Implement the parser**

```python
# backend/services/jsx_to_schema.py — first half
"""Minimal JSX parser tailored to Figma MCP get_design_context output.

The output format is restricted: regular HTML-like tags, className strings,
inline style={{...}} objects, no JSX expressions other than {imgVar} src
interpolations. A recursive-descent tokenizer handles it without needing
a full JS AST parser.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JSXElement:
    tag: str
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)  # list of JSXElement or str

    def find_descendant(self, predicate):
        if predicate(self):
            return self
        for c in self.children:
            if isinstance(c, JSXElement):
                hit = c.find_descendant(predicate)
                if hit: return hit
        return None


def _extract_const_assignments(source: str) -> dict[str, str]:
    """Find `const foo = "value";` declarations at module scope.
    Used to resolve src={imgFoo} interpolations to literal URLs."""
    consts: dict[str, str] = {}
    for m in re.finditer(r'const\s+(\w+)\s*=\s*"([^"]+)";', source):
        consts[m.group(1)] = m.group(2)
    return consts


def _parse_style_object(s: str) -> dict[str, str]:
    """Parse a JS object literal like `{ backgroundColor: "red", padding: "12px" }`.
    Keys can be quoted or bare. Values are strings."""
    out: dict[str, str] = {}
    # Strip outer braces
    s = s.strip()
    if s.startswith("{"): s = s[1:]
    if s.endswith("}"): s = s[:-1]
    # Match key: "value" pairs, accounting for nested parens in values
    for m in re.finditer(r'(\w+|"[^"]+"):\s*"([^"]+)"', s):
        key = m.group(1).strip('"')
        out[key] = m.group(2)
    return out


def parse_jsx_tree(source: str) -> JSXElement:
    """Parse the first JSX expression in `source`. Resolves {varName}
    src interpolations against module-level const declarations."""
    consts = _extract_const_assignments(source)
    # Find the first JSX root — look for `return (` or `return <`
    idx = source.find("return (")
    if idx == -1: idx = source.find("return <")
    if idx == -1:
        # Treat the whole input as JSX
        jsx = source.strip()
    else:
        # Slice from `<` onwards
        jsx = source[source.find("<", idx):]
    return _parse_element(jsx, consts)[0]


def _parse_element(src: str, consts: dict[str, str]) -> tuple[JSXElement, int]:
    """Parse one element starting at `src[0]` (must be `<`). Returns the
    element and the index just past its closing tag."""
    # ... implementation walks the string char-by-char, balancing < > and tracking
    # attribute parsing for className=, style={{...}}, src={...}, data-*=...
    # Length: ~120 lines. Full implementation deferred to source.
    raise NotImplementedError("see source for full parser body")
```

The full parser body is ~150 lines — too long for this plan doc. Treat the above as the public-API contract and implement the body to satisfy the tests.

- [ ] **Step 3: Run tests, iterate, commit**

```
feat(figma): lightweight JSX parser for MCP get_design_context output
```

### Task A.2: JSX tree → PageV2 schema

**Files:**
- Continue editing: `backend/services/jsx_to_schema.py`
- Continue editing: `backend/tests/services/test_jsx_to_schema.py`

- [ ] **Step 1: Tests for the transformer**

```python
def test_simple_div_becomes_stack():
    src = '<div className="flex flex-col gap-4">hi</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Stack"
    assert schema["props"].get("className") == "flex flex-col gap-4"


def test_flex_row_becomes_row():
    src = '<div className="flex flex-row">hi</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Row"


def test_grid_becomes_grid():
    src = '<div className="grid grid-cols-2">x</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Grid"


def test_p_with_heading_class_becomes_heading():
    """A <p> with a large font-size class lifts to Heading."""
    src = '<p className="text-[30px] font-bold">IntentAI</p>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Heading"
    assert schema["props"]["content"] == "IntentAI"


def test_p_default_becomes_text():
    src = '<p className="text-[14px]">Description</p>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Text"
    assert schema["props"]["content"] == "Description"


def test_img_becomes_image():
    src = '<img src="https://cdn/x.png" alt="Logo" />'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Image"
    assert schema["props"]["src"] == "https://cdn/x.png"


def test_div_with_data_name_email_input_becomes_input():
    """When data-name='Email Input' wraps a single <p> with placeholder
    text, emit an Input node with that as the placeholder."""
    src = '<div data-name="Email Input"><p>demo@x.com</p></div>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Input"
    assert schema["props"]["type"] == "email"
    assert schema["props"]["placeholder"] == "demo@x.com"


def test_div_with_data_name_button_becomes_button():
    src = '<div data-name="Button"><p>Sign in</p></div>'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Button"
    assert schema["props"]["label"] == "Sign in"


def test_div_with_data_name_checkbox_becomes_checkbox():
    src = '<div data-name="Checkbox" />'
    schema = transform_jsx_to_schema(src)
    assert schema["type"] == "Checkbox"


def test_style_object_attached_to_props():
    src = '<div style={{ backgroundColor: "red" }}>x</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["props"]["style"]["backgroundColor"] == "red"


def test_data_node_id_preserved():
    src = '<div data-node-id="1:5">x</div>'
    schema = transform_jsx_to_schema(src)
    # data-node-id becomes the schema node id (so AI edit / selection align)
    assert schema["id"].endswith("1:5") or schema.get("_figmaNodeId") == "1:5"


def test_fixture_round_trip():
    """Load the Commitbiz fixture, transform it, check the result has the
    expected high-level shape."""
    import pathlib
    fixture_path = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login_design_context.tsx"
    src = fixture_path.read_text()
    schema = transform_jsx_to_schema(src)
    # Walk the tree, count specific types
    types: dict[str, int] = {}
    def walk(n):
        if isinstance(n, dict):
            t = n.get("type")
            if t: types[t] = types.get(t, 0) + 1
            for c in n.get("children") or []: walk(c)
    walk(schema)
    # Expected at minimum:
    assert types.get("Heading", 0) >= 2     # IntentAI + Welcome
    assert types.get("Input", 0) >= 2       # Email + Password
    assert types.get("Button", 0) >= 1      # Sign in
    assert types.get("Checkbox", 0) >= 1
    assert types.get("Image", 0) >= 1       # Logo (or vector imgs)
    assert types.get("Text", 0) >= 3
    # Two-column layout — there should be a Grid OR two flanking Stacks
    has_two_col = types.get("Grid", 0) >= 1 or types.get("Row", 0) >= 1
    assert has_two_col
```

- [ ] **Step 2: Implement the transformer**

```python
# backend/services/jsx_to_schema.py — append after parser

# Component recognition patterns — keyed by data-name attribute
_DATA_NAME_TO_TYPE = {
    "Email Input": ("Input", {"type": "email"}),
    "Password Input": ("Input", {"type": "password"}),
    "Search Input": ("Input", {"type": "text"}),
    "Input": ("Input", {"type": "text"}),
    "Button": ("Button", {}),
    "Checkbox": ("Checkbox", {}),
    "Link": ("Link", {}),
    "Form": ("Form", {}),
    "Sign in Form": ("Form", {}),
    "Logo Image": ("Image", {"alt": "Logo"}),
    "Primitive.label": ("Text", {"role": "label"}),
}

_HEADING_NAME_RE = re.compile(r"^Heading\s+(\d)$", re.I)


def _classify_div(elem: JSXElement) -> tuple[str, dict]:
    """Decide whether a <div> becomes Stack, Row, Grid, Container, or one
    of the recognised composite types (Input, Button, etc.)."""
    data_name = elem.attrs.get("data-name", "")
    if data_name in _DATA_NAME_TO_TYPE:
        return _DATA_NAME_TO_TYPE[data_name]
    m = _HEADING_NAME_RE.match(data_name)
    if m:
        return ("Heading", {"level": int(m.group(1))})

    cls = elem.attrs.get("className", "")
    if "grid grid-cols" in cls or "grid-cols-" in cls:
        return ("Grid", {})
    if " flex-row" in cls or " flex-row " in cls or cls.endswith(" flex"):
        # flex without flex-col → row
        return ("Row", {})
    if "flex-col" in cls or " flex " in cls:
        return ("Stack", {})
    return ("Container", {})


def _classify_paragraph(elem: JSXElement) -> tuple[str, dict]:
    """Pick between Text and Heading based on font-size class."""
    cls = elem.attrs.get("className", "")
    # Large fonts → heading; threshold ~ 18px (text-[18px] or larger)
    big_font = re.search(r"text-\[(\d+)px\]", cls)
    if big_font and int(big_font.group(1)) >= 18:
        return ("Heading", {"level": 2 if int(big_font.group(1)) >= 24 else 4})
    if "font-bold" in cls or "font-semibold" in cls:
        return ("Heading", {"level": 3})
    return ("Text", {})


def _strip_jsx_text(value) -> str:
    """Children may be JSXElement | str | a {`template`} expression. Return
    the concatenated plain text content."""
    if isinstance(value, str):
        return value
    if isinstance(value, JSXElement):
        out = []
        for c in value.children:
            out.append(_strip_jsx_text(c))
        return "".join(out)
    return ""


def _build_schema_node(elem: JSXElement) -> dict:
    """Convert one JSX element to a PageV2 schema node."""
    if elem.tag == "img":
        node = {"type": "Image", "props": {}, "children": []}
        if "src" in elem.attrs:
            node["props"]["src"] = elem.attrs["src"]
        if "alt" in elem.attrs:
            node["props"]["alt"] = elem.attrs["alt"]
        return node

    if elem.tag == "p":
        schema_type, base_props = _classify_paragraph(elem)
        content = _strip_jsx_text(elem)
        node = {"type": schema_type, "props": {**base_props, "content": content}, "children": []}
        # Style passthrough
        if elem.attrs.get("className"):
            node["props"]["className"] = elem.attrs["className"]
        return node

    # Default: <div> or any other container
    schema_type, base_props = _classify_div(elem)
    node = {"type": schema_type, "props": dict(base_props), "children": []}

    # Style passthrough
    if elem.attrs.get("className"):
        node["props"]["className"] = elem.attrs["className"]
    if elem.attrs.get("style"):
        node["props"]["style"] = elem.attrs["style"]

    # Composite recognition: when we lift a div to Input/Button/etc.,
    # pull the descendant TEXT for label / placeholder.
    descendant_text = _strip_jsx_text(elem).strip()
    if schema_type == "Input" and descendant_text:
        node["props"]["placeholder"] = descendant_text
        return node  # don't recurse — children are the placeholder text
    if schema_type == "Button" and descendant_text:
        node["props"]["label"] = descendant_text
        return node
    if schema_type == "Link" and descendant_text:
        node["props"]["label"] = descendant_text
        return node

    # Recurse for non-composite containers
    for child in elem.children:
        if isinstance(child, JSXElement):
            node["children"].append(_build_schema_node(child))
        elif isinstance(child, str) and child.strip():
            node["children"].append({"type": "Text", "props": {"content": child.strip()}, "children": []})
    return node


def transform_jsx_to_schema(jsx_source: str, asset_paths: dict[str, str] | None = None) -> dict:
    """Top-level: parse the JSX source, transform to a PageV2 schema dict.

    asset_paths is an optional {cdn_url: local_path} map produced by the
    asset downloader. When provided, every img src referencing a CDN URL
    is rewritten to the local path.
    """
    asset_paths = asset_paths or {}
    tree = parse_jsx_tree(jsx_source)
    root = _build_schema_node(tree)

    # Asset path rewriting — walk the tree, rewrite src props
    def rewrite_srcs(node):
        if isinstance(node, dict):
            props = node.get("props") or {}
            src = props.get("src")
            if isinstance(src, str) and src in asset_paths:
                props["src"] = asset_paths[src]
            for c in node.get("children") or []:
                rewrite_srcs(c)
    rewrite_srcs(root)

    # Wrap as PageV2
    return {
        "schemaVersion": "2.0",
        "id": "figma-mcp-root",
        "title": "Figma-derived",
        "dataSources": [],
        "children": [root],
    }
```

- [ ] **Step 3: Run all tests including the fixture round-trip**

Run: `cd backend && pytest tests/services/test_jsx_to_schema.py -v`. Iterate the classifier rules until the fixture test passes.

- [ ] **Step 4: Commit**

```
feat(figma): jsx_to_schema transformer — MCP React output → PageV2
```

---

## WS-B — Asset Download Pipeline

### Task B.1: Extract asset URLs + download

**Files:**
- Create: `backend/services/figma_asset_downloader.py`
- Test: `backend/tests/services/test_figma_asset_downloader.py`

- [ ] **Step 1: Tests**

```python
# backend/tests/services/test_figma_asset_downloader.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.figma_asset_downloader import extract_asset_urls, download_figma_assets


def test_extract_asset_urls_from_jsx():
    jsx = '''
    const imgLogo = "https://www.figma.com/api/mcp/asset/abc-123";
    const imgVector = "https://www.figma.com/api/mcp/asset/def-456";
    function App() { return <img src={imgLogo} />; }
    '''
    urls = extract_asset_urls(jsx)
    assert "https://www.figma.com/api/mcp/asset/abc-123" in urls
    assert "https://www.figma.com/api/mcp/asset/def-456" in urls
    assert len(urls) == 2


def test_extract_only_mcp_asset_urls():
    """Skip other URLs (logos hosted elsewhere, etc.) so we don't try to
    cache the whole internet."""
    jsx = '''
    const cdnA = "https://www.figma.com/api/mcp/asset/abc";
    const externalB = "https://cdn.example.com/random.png";
    function App() { return <img src={cdnA} />; }
    '''
    urls = extract_asset_urls(jsx)
    assert urls == ["https://www.figma.com/api/mcp/asset/abc"]


@pytest.mark.asyncio
async def test_download_creates_local_files(tmp_path):
    """Mocked fetch — verify files land at output_dir/public/figma/<hash>."""
    urls = ["https://www.figma.com/api/mcp/asset/abc-123"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<svg>fake</svg>"
    mock_response.headers = {"content-type": "image/svg+xml"}
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_response)):
        result = await download_figma_assets(urls, str(tmp_path))
    assert len(result) == 1
    local_path = result["https://www.figma.com/api/mcp/asset/abc-123"]
    assert local_path.startswith("/figma/")
    on_disk = tmp_path / "public" / local_path.lstrip("/")
    assert on_disk.exists()
    assert on_disk.read_bytes() == b"<svg>fake</svg>"


@pytest.mark.asyncio
async def test_idempotent_skips_existing_files(tmp_path):
    """Re-running the download against the same URL doesn't refetch."""
    out_dir = tmp_path / "public" / "figma"
    out_dir.mkdir(parents=True)
    # Pre-place a file matching the hash this URL produces
    import hashlib
    h = hashlib.sha1("https://www.figma.com/api/mcp/asset/already-here".encode()).hexdigest()[:12]
    existing = out_dir / f"{h}.svg"
    existing.write_bytes(b"cached")

    mock = AsyncMock()
    with patch("httpx.AsyncClient.get", mock):
        result = await download_figma_assets(
            ["https://www.figma.com/api/mcp/asset/already-here"],
            str(tmp_path),
        )
    # GET was NOT called
    mock.assert_not_called()
    # Path returned
    assert result["https://www.figma.com/api/mcp/asset/already-here"].endswith(f"{h}.svg")
```

- [ ] **Step 2: Implementation**

```python
# backend/services/figma_asset_downloader.py
"""Download Figma MCP asset URLs to the project's public/figma/ directory.

The MCP CDN URLs (https://www.figma.com/api/mcp/asset/<uuid>) expire
after 7 days, so we cache locally + rewrite src references in the
emitted schema to use the local paths.
"""
from __future__ import annotations
import asyncio
import hashlib
import re
from pathlib import Path

import httpx


_MCP_ASSET_URL_RE = re.compile(r'"(https://www\.figma\.com/api/mcp/asset/[a-zA-Z0-9-]+)"')


def extract_asset_urls(jsx_source: str) -> list[str]:
    """Return unique MCP asset URLs referenced in the JSX source."""
    urls = _MCP_ASSET_URL_RE.findall(jsx_source)
    return sorted(set(urls))


def _local_path_for_url(url: str, content_type: str | None = None) -> str:
    """Compute the relative output path for a CDN URL. Stable across runs."""
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    # Best-effort extension from content-type (svg vs png vs jpg). Fallback to .svg
    # since Figma vectors are the common case.
    ext = "svg"
    if content_type:
        if "png" in content_type: ext = "png"
        elif "jpeg" in content_type or "jpg" in content_type: ext = "jpg"
        elif "svg" in content_type: ext = "svg"
    return f"/figma/{h}.{ext}"


async def download_figma_assets(
    urls: list[str],
    output_dir: str,
    concurrency: int = 8,
) -> dict[str, str]:
    """Download each URL to output_dir/public/figma/. Returns {url: public_path}
    where public_path starts with `/figma/` (suitable for the browser).
    Skips downloads for URLs whose cached file already exists.
    """
    public_root = Path(output_dir) / "public"
    public_root.mkdir(parents=True, exist_ok=True)
    (public_root / "figma").mkdir(exist_ok=True)

    result: dict[str, str] = {}
    sem = asyncio.Semaphore(concurrency)

    async def _one(url: str, client: httpx.AsyncClient) -> None:
        async with sem:
            # Idempotency: check if a file matching the hash already exists
            # (in any extension).
            h = hashlib.sha1(url.encode()).hexdigest()[:12]
            for ext in ("svg", "png", "jpg"):
                candidate = public_root / "figma" / f"{h}.{ext}"
                if candidate.exists():
                    result[url] = f"/figma/{h}.{ext}"
                    return
            # Download fresh
            try:
                r = await client.get(url, timeout=30.0, follow_redirects=True)
                if r.status_code != 200:
                    return
                local_path = _local_path_for_url(url, r.headers.get("content-type"))
                on_disk = public_root / local_path.lstrip("/")
                on_disk.write_bytes(r.content)
                result[url] = local_path
            except Exception:
                pass  # one bad asset shouldn't kill the batch

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_one(u, client) for u in urls])

    return result
```

- [ ] **Step 3: Tests pass + commit**

```
feat(figma): asset downloader for MCP CDN URLs — cache + rewrite src to /figma/
```

---

## WS-C — Pipeline Integration + Validator Softening

### Task C.1: `figma_mcp_pipeline` orchestrator

**Files:**
- Create: `backend/services/figma_mcp_pipeline.py`

- [ ] **Step 1: Skeleton**

```python
# backend/services/figma_mcp_pipeline.py
"""End-to-end Figma-MCP pipeline: receive a JSX design-context payload,
download its assets to the project, transform to PageV2 schema with
rewritten asset paths.

Doesn't call the MCP server directly — that's the caller's job (different
patterns for backend pipeline vs interactive Claude). This module is a
pure pipeline: jsx_source + output_dir → schema dict.
"""
from __future__ import annotations
from typing import Any

from services.figma_asset_downloader import extract_asset_urls, download_figma_assets
from services.jsx_to_schema import transform_jsx_to_schema


async def build_schema_from_jsx(
    jsx_source: str,
    output_dir: str,
) -> tuple[dict, dict[str, str]]:
    """Returns (schema, asset_paths) — schema is PageV2-shaped, asset_paths
    is {original_cdn_url: local_path} for the caller to log / verify."""
    urls = extract_asset_urls(jsx_source)
    asset_paths = await download_figma_assets(urls, output_dir) if urls else {}
    schema = transform_jsx_to_schema(jsx_source, asset_paths)
    return schema, asset_paths
```

- [ ] **Step 2: End-to-end test against the fixture**

```python
# backend/tests/integration/test_figma_mcp_e2e.py
import pathlib
import pytest
from services.figma_mcp_pipeline import build_schema_from_jsx


FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login_design_context.tsx"


@pytest.mark.asyncio
async def test_commitbiz_fixture_end_to_end(tmp_path, monkeypatch):
    # Mock the downloader so we don't hit Figma's CDN in CI
    from services import figma_asset_downloader
    async def fake_download(urls, output_dir, concurrency=8):
        # Pretend every URL resolved
        return {u: f"/figma/asset_{i}.svg" for i, u in enumerate(urls)}
    monkeypatch.setattr(figma_asset_downloader, "download_figma_assets", fake_download)
    monkeypatch.setattr("services.figma_mcp_pipeline.download_figma_assets", fake_download)

    src = FIXTURE.read_text()
    schema, asset_paths = await build_schema_from_jsx(src, str(tmp_path))

    # The schema must have the structural pieces we expect from the Commitbiz design
    types: dict[str, int] = {}
    def walk(n):
        if isinstance(n, dict):
            t = n.get("type")
            if t: types[t] = types.get(t, 0) + 1
            for c in n.get("children") or []: walk(c)
    walk(schema)
    assert types.get("Image", 0) >= 1
    assert types.get("Heading", 0) >= 2
    assert types.get("Input", 0) >= 2
    assert types.get("Button", 0) >= 1
    # Assets were downloaded (mocked) and src rewriting happened
    assert len(asset_paths) >= 13  # 1 logo + 12 vectors in the fixture
```

- [ ] **Step 3: Commit**

```
feat(figma): figma_mcp_pipeline — orchestrate jsx → assets → schema
```

### Task C.2: Wire into `_run_figma_relay_pipeline`

**Files:**
- Modify: `backend/routers/generate.py:_run_figma_relay_pipeline`

The wiring depends on how we obtain the MCP `get_design_context` output in the backend. The MCP server runs as a separate process; the backend can invoke it via the Anthropic SDK with the MCP tool configured.

- [ ] **Step 1: Decide the runtime call pattern**

Two paths:

**Path 1 (preferred)** — use `claude_agent_sdk.query` with the Figma MCP server registered as an MCP server in `ClaudeAgentOptions.mcp_servers`. The agent is instructed to call `get_design_context` for each node and return the JSX. Single agent call, output is JSX text. This is consistent with how the backend already calls Claude agents.

**Path 2 (sidecar)** — run Figma's MCP server as a long-lived subprocess and call it via SSE/HTTP. More work, but no LLM cost per call.

Go with **Path 1** — it reuses existing agent infrastructure and the cost is bounded by token count of the input (small).

- [ ] **Step 2: Implement a `run_figma_mcp_agent`**

```python
# backend/agents/figma_mcp_agent.py — NEW
"""Agent that fetches Figma get_design_context output for one node and
returns the JSX as a string. Used by _run_figma_relay_pipeline as the
source of truth for visual fidelity."""
from claude_agent_sdk import query, ClaudeAgentOptions


async def run_figma_mcp_agent(file_key: str, node_id: str, figma_token: str) -> str | None:
    """Returns the JSX string from get_design_context, or None on failure."""
    options = ClaudeAgentOptions(
        model="claude-sonnet-4-20250514",
        mcp_servers={
            "figma": {
                "type": "stdio",
                "command": "npx",
                "args": ["@figma/figma-mcp", "--stdio"],  # or however the user has it
                "env": {"FIGMA_API_KEY": figma_token},
            },
        },
        allowed_tools=["mcp__figma__get_design_context"],
        max_turns=2,
        permission_mode="bypass",
    )
    prompt = (
        f"Call mcp__figma__get_design_context with fileKey={file_key!r} and "
        f"nodeId={node_id!r}. Return ONLY the raw text of the tool result — "
        f"no markdown, no extra explanation."
    )
    output_chunks: list[str] = []
    async for msg in query(prompt, options=options):
        if hasattr(msg, "content"):
            for block in msg.content or []:
                if hasattr(block, "text"):
                    output_chunks.append(block.text)
    full = "".join(output_chunks)
    # Strip any wrapping the LLM added — find the first `<div ` or `function `
    for marker in ("export default function", "function CommitbizIntentaiLogin", "const imgLogo"):
        idx = full.find(marker)
        if idx != -1:
            return full[idx:]
    return full if full else None
```

The MCP server configuration (`@figma/figma-mcp`) requires the Figma MCP package — the user installs it locally per the Figma MCP setup docs. If the MCP server isn't reachable, the agent will fail and we fall back to the old deterministic mapper.

- [ ] **Step 3: Replace the schema build call**

In `_run_figma_relay_pipeline`, the FigmaDeterministic block currently calls `build_page_schema(doc)`. Replace with:

```python
from agents.figma_mcp_agent import run_figma_mcp_agent
from services.figma_mcp_pipeline import build_schema_from_jsx

for page in pages_with_nodes[:50]:
    route = page.get("route", "?")
    file_path = Path(output_dir) / page.get("file", f"src/schemas/{route.strip('/').replace('/', '-') or 'home'}.json")
    try:
        # Path 1: try MCP first (high fidelity)
        jsx = await run_figma_mcp_agent(file_key, page["figma_node_id"], figma_token)
        if jsx:
            schema, asset_paths = await build_schema_from_jsx(jsx, output_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(json.dumps(schema, indent=2))
            deterministic_pages.add(route)
            yield sse_event("log", {
                "text": f"[FigmaMCP] ✓ {route} — {len(asset_paths)} assets cached"
            })
            continue
    except Exception as e:
        yield sse_event("log", {"text": f"[FigmaMCP] {route}: MCP failed ({e}) — trying deterministic mapper"})

    # Path 2 (fallback): old deterministic mapper
    doc = docs.get(page["figma_node_id"]) or {}
    if not doc:
        yield sse_event("log", {"text": f"[FigmaDeterministic] ⚠ {route}: fetch failed"})
        continue
    result = build_page_schema(doc)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(result.page, indent=2))
    deterministic_pages.add(route)
    yield sse_event("log", {"text": f"[FigmaDeterministic] ✓ {route} (fallback)"})
```

- [ ] **Step 4: Commit**

```
feat(figma-pipeline): use MCP get_design_context as primary source; deterministic mapper as fallback
```

### Task C.3: Soften library Zod validators

**Files:**
- Modify: `packages/library/src/components/Input/Input.tsx`
- Modify: `packages/library/src/components/Button/Button.tsx`
- Modify: `packages/library/src/components/Card/Card.tsx`
- Modify: `packages/library/src/components/Heading/Heading.tsx`
- Modify: `packages/library/src/components/Text/Text.tsx`
- Modify: `packages/library/src/components/Form/Form.tsx`
- Modify: `packages/library/src/components/Checkbox/Checkbox.tsx`
- Modify: `packages/library/src/components/Link/Link.tsx`
- Modify: `packages/library/src/components/Image/Image.tsx`

The current Zod validators reject schemas missing required props. The MCP-derived schemas have less metadata than the LLM-emitted ones; we soften so partial inputs render with defaults instead of "⚠ invalid props".

- [ ] **Step 1: Audit current validator behaviour for each component**

```bash
grep -n "validateProps\|invalid props\|z.object" packages/library/src/components/Input/Input.tsx
```

For each component:
- Identify which props are currently `required`
- Decide which can be optional with a default

Examples:
- `Input`: `name` becomes optional, default `"field"`; `label` optional, default `""`; `type` optional, default `"text"`
- `Button`: `label` optional, default `"Action"`
- `Heading`: `content` optional, default `""`; `level` optional, default `2`

- [ ] **Step 2: Per-component edit**

Pattern:
```ts
// before
export const InputProps = z.object({
  name: z.string(),
  type: z.enum([...]),
  label: z.string(),
});

// after
export const InputProps = z.object({
  name: z.string().default("field"),
  type: z.enum([...]).default("text"),
  label: z.string().default(""),
  placeholder: z.string().optional(),
  className: z.string().optional(),
});
```

The Zod default values flow through `validateProps` so the runtime never sees `undefined`.

- [ ] **Step 3: Manual render verification**

After softening, re-build the library + re-render the Commitbiz fixture's emitted schema. No `⚠ invalid props` placeholders should appear.

- [ ] **Step 4: Commit per batch (3-4 components per commit so reviews stay manageable)**

```
feat(library): soften Input/Button/Heading validators — partial schemas render with defaults
```

---

## Verification — end-to-end on Commitbiz

### Task V.1: Manual generation check

- [ ] Re-fire your Commitbiz generation through the editor's chat-approval flow.
- [ ] Watch SSE log for `[FigmaMCP] ✓ /login — N assets cached`.
- [ ] Open `http://localhost:6503/p/<short_id>/login`.
- [ ] Expected: two-column layout with dark red left panel + Commitbiz logo + IntentAI heading + brain icon, white right panel with Welcome + Email/Password form + Sign-in button. Visually approximating the Figma within ~5-10% pixel diff.
- [ ] Capture before/after screenshots as `docs/superpowers/screenshots/figma-mcp/`.

If the rendered output materially matches the Figma, the pivot is validated. If gaps remain (specific styling, specific components), file follow-ups but the architectural choice stands.

---

## Sequencing + Time Estimates

| Phase | Tasks | Effort |
|---|---|---|
| WS-A — JSX → PageV2 transformer | A.1 parser, A.2 transformer | 2 days |
| WS-B — Asset download pipeline | B.1 downloader | 0.5 day |
| WS-C.1 — pipeline orchestrator | C.1 | 0.5 day |
| WS-C.2 — MCP agent wiring | C.2 | 1 day |
| WS-C.3 — Library validator softening | C.3 | 1 day (9 components × ~30 min each) |
| Verification V.1 | manual | 0.5 day |

**Total: ~5 days.**

---

## What this retires

Phase 4 of the previous plan (per-node fidelity tasks T150–156) is **retired**. The MCP path delivers per-node fidelity for free via Figma's own code-gen.

The deterministic mapper (`figma_to_schema`, `figma_name_classifier`, `figma_style_extractor`, `figma_typography_extractor`) stays as a **fallback** for users who can't run the Figma MCP server locally — but it's no longer the primary path.

---

## Self-Review

- **Spec coverage:** Three workstreams covering JSX parsing (A), asset caching (B), pipeline + library integration (C). All concrete with tests.
- **Placeholder scan:** The parser body in A.1 is summarised, not fully inlined (~150 LOC). Acceptable for a plan doc — the implementer fills it in from the tests. The MCP-agent invocation pattern in C.2 depends on the user's Figma MCP installation; documented as a known integration constraint.
- **Type consistency:** `parse_jsx_tree(source: str) -> JSXElement` → consumed by `transform_jsx_to_schema(source, asset_paths) -> dict`. `extract_asset_urls(jsx)` produces input for `download_figma_assets(urls, output_dir) -> {url: local_path}`. The orchestrator `build_schema_from_jsx(jsx, output_dir) -> (schema, asset_paths)` ties them together.
- **Risk callouts:** The biggest risk is C.2 — the MCP server runtime invocation. If the user's environment doesn't have the Figma MCP server installed or callable from `claude_agent_sdk`, this path fails and we fall back to the deterministic mapper. Mitigation: fallback is built into the pipeline; failure mode is "back to today's behaviour" rather than "broken pipeline".
