# Figma Typography Extraction + Full Colour Scale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two follow-ups to the deterministic Figma → schema mapper:
1. Extract typography (font family, size scale, weights, line-height, letter-spacing) from Figma TEXT nodes into `tokens.custom.json`.
2. Replace the 5-step minimal colour scale (50/100/500/600/900) with a full 11-step scale (50/100/200/300/400/500/600/700/800/900/950) by adding a `derive_scale()` helper to `services.color_theory`.

**Architecture:** Three workstreams, ~5 tasks.
- **WS-A — Colour scale.** Add `derive_scale(primary_hex) -> dict[str, str]` to `services.color_theory`. Wire into `figma_style_extractor.extract_tokens()` replacing the current 5-step tint/shade.
- **WS-B — Typography extraction.** New `figma_typography_extractor.py` module. Walks TEXT nodes, clusters by role (heading-named → heading family/weight, plain TEXT → body), emits the `typography.font/weight/scale/lineHeight/letterSpacing` tree.
- **WS-C — Wire-up.** `figma_to_schema.build_page_schema` calls both extractors and merges into one tokens dict.

**Tech Stack:** Python 3.11, pytest. No new deps. Reuse existing `colorsys` (already imported in `color_theory`).

**Reference state today:**
- `services.color_theory.DerivedPalette` produces role-keyed colours (primary, secondary, …) — NOT a scale. No `derive_scale()` exists yet; we add it.
- `services.figma_style_extractor.extract_tokens()` currently emits only `color.primary.{50,100,500,600,900}` via local `_tint`/`_shade`. Replace those with `color_theory.derive_scale(primary_500)`.
- `tokens.custom.json` canonical scale shape (from project db17s1zl):
  ```json
  "primary": { "50":"#f1fefa", "100":"#defcf2", "200":"#c2fae7", "300":"#98f6d7",
               "400":"#69f2c5", "500":"#10b981", "600":"#0ea170", "700":"#0c875e",
               "800":"#0a6f4d", "900":"#08573d", "950":"#053727" }
  ```
- Existing typography token shape (target):
  ```json
  "typography": {
    "font":          { "body": "Inter", "heading": "Inter" },
    "weight":        { "body": "400", "heading": "600" },
    "scale":         { "xs":"0.75rem", "sm":"0.875rem", "base":"1rem", "lg":"1.125rem",
                       "xl":"1.25rem", "2xl":"1.5rem", "3xl":"1.875rem", "4xl":"2.25rem" },
    "lineHeight":    { "tight": "1.25", "normal": "1.5" },
    "letterSpacing": { "heading": "-0.02em", "body": "0" }
  }
  ```

Figma TEXT nodes carry style under `node.style`: `fontFamily`, `fontSize` (px), `fontWeight`, `lineHeightPx`, `letterSpacing`.

---

## File Structure Overview

### New files
| File | Responsibility |
|---|---|
| `backend/services/figma_typography_extractor.py` | `extract_typography(walked_nodes) -> dict` |
| `backend/tests/services/test_figma_typography_extractor.py` | Unit tests for the extractor |

### Modified files
| File | Change |
|---|---|
| `backend/services/color_theory.py` | Add `derive_scale(primary_hex) -> dict[str, str]` returning 11-step scale |
| `backend/tests/services/test_color_theory.py` | New file (or extend existing if present) — tests for `derive_scale` |
| `backend/services/figma_style_extractor.py` | Replace local `_tint`/`_shade`-based 5-step scale with `color_theory.derive_scale` call |
| `backend/tests/services/test_figma_style_extractor.py` | Update assertions to expect 11 steps |
| `backend/services/figma_to_schema.py` | Call both extractors, merge tokens |
| `backend/tests/services/test_figma_to_schema.py` | Add typography-presence assertion |

---

## WS-A — Full Colour Scale

### Task 1: Add `derive_scale()` to color_theory

**Files:**
- Modify: `backend/services/color_theory.py`
- Test: `backend/tests/services/test_color_theory.py`

- [ ] **Step 1: Check whether `test_color_theory.py` exists**

```bash
ls backend/tests/services/test_color_theory.py 2>/dev/null || echo "absent — create new"
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/services/test_color_theory.py (create if absent, append if exists)
from services.color_theory import derive_scale


def test_derive_scale_returns_11_steps():
    s = derive_scale("#10b981")
    expected_keys = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}
    assert set(s.keys()) == expected_keys


def test_derive_scale_500_is_input():
    """The input hex IS the 500 step — no rounding/normalising shifts it."""
    s = derive_scale("#10b981")
    assert s["500"].lower() == "#10b981"


def test_derive_scale_progressively_lighter_below_500_darker_above_500():
    """50 must be the lightest, 950 the darkest. Monotonic ordering."""
    s = derive_scale("#10b981")
    def lightness(hex_color):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r + g + b) / 3  # crude L proxy
    # Lightnesses ordered: 50 > 100 > 200 > ... > 900 > 950
    ls = [lightness(s[k]) for k in ["50","100","200","300","400","500","600","700","800","900","950"]]
    for a, b in zip(ls, ls[1:]):
        assert a > b, f"step lightness must monotonically decrease, got {ls}"


def test_derive_scale_50_close_to_white():
    """50 should be very near-white (sum > ~720 of 765)."""
    s = derive_scale("#10b981")
    h = s["50"].lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    assert (r + g + b) > 720


def test_derive_scale_950_close_to_black():
    s = derive_scale("#10b981")
    h = s["950"].lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    assert (r + g + b) < 200


def test_derive_scale_preserves_hue():
    """A clearly emerald input → every step's hue should still be emerald-ish
    (G dominant). Sanity check that we don't accidentally desaturate to grey."""
    s = derive_scale("#10b981")
    for step in ["100", "300", "500", "700", "900"]:
        h = s[step].lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        # Green channel dominates the others by at least a few units across the scale.
        assert g >= max(r, b) - 4, f"step {step}={s[step]}: hue drifted (G must dominate)"


def test_derive_scale_with_neutral_input_returns_grey_scale():
    """A neutral input shouldn't crash and should produce a sensible grey ramp."""
    s = derive_scale("#737373")  # mid-grey
    assert len(s) == 11
    # All steps roughly neutral — channel spread < 25 each step
    for k, v in s.items():
        h = v.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        spread = max(r, g, b) - min(r, g, b)
        assert spread < 30, f"step {k}={v}: drifted from neutral ({spread})"
```

- [ ] **Step 3: Run test — expect FAIL**

```bash
cd backend && pytest tests/services/test_color_theory.py -v
```

Expected: ImportError on `derive_scale`.

- [ ] **Step 4: Implement**

Add to `backend/services/color_theory.py`:

```python
# Step targets (lightness L, in HSL 0..1) for each scale key.
# Calibrated to match Tailwind's default colour palette feel — 50 is
# near-white, 500 keeps the input's lightness, 950 is near-black.
_SCALE_LIGHTNESS = {
    "50":  0.97, "100": 0.93, "200": 0.85, "300": 0.74, "400": 0.60,
    # 500 is kept at the input's actual lightness — see derive_scale.
    "600": 0.36, "700": 0.28, "800": 0.21, "900": 0.15, "950": 0.09,
}


def derive_scale(primary_hex: str) -> dict[str, str]:
    """Return a Tailwind-style 11-step colour scale derived from a single
    primary hex. The input hex is anchored at the 500 step; all other steps
    are computed in HSL space holding hue + saturation constant and adjusting
    lightness to the targets in `_SCALE_LIGHTNESS`.

    For neutral inputs (very low saturation), the result is a grey ramp —
    saturation stays near zero so neighbouring steps don't accidentally
    introduce a colour cast.
    """
    h, s, l = _hex_to_hsl(primary_hex)
    out: dict[str, str] = {"500": primary_hex.lower()}
    # Cap saturation slightly above the input so high-step (dark) variants
    # don't drift towards desaturated muddy hues.
    sat = max(s, 0.05) if s > 0.05 else s  # preserve true greys
    for key, target_l in _SCALE_LIGHTNESS.items():
        out[key] = _hsl_to_hex(h, sat, target_l)
    return out
```

`_hex_to_hsl` already exists at line ~49 — reuse it. `_hsl_to_hex` also exists.

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd backend && pytest tests/services/test_color_theory.py -v
```

If `test_derive_scale_950_close_to_black` fails because the 0.09 target is too light: nudge `_SCALE_LIGHTNESS["950"]` to 0.07. Likewise tweak any target by ±0.02 to satisfy the monotonic-lightness test on first PASS. Document each tweak in the commit message.

- [ ] **Step 6: Regression**

```bash
cd backend && pytest tests/services/ -v
```

- [ ] **Step 7: Commit**

```
feat(color-theory): derive_scale — Tailwind-style 11-step palette from a primary hex
```
HEREDOC + Co-Authored-By trailer.

### Task 2: Replace 5-step scale in figma_style_extractor

**Files:**
- Modify: `backend/services/figma_style_extractor.py`
- Modify: `backend/tests/services/test_figma_style_extractor.py`

- [ ] **Step 1: Update tests**

Find and update these existing tests to expect 11 keys:

```python
def test_derives_50_100_600_900_from_primary_500():
    """Renamed: test_derives_full_11_step_scale_from_primary_500."""
    nodes = [_walked("Button", [_solid_fill(0.063, 0.725, 0.506)])]
    tokens = extract_tokens(nodes)
    p = tokens["color"]["primary"]
    expected = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}
    assert set(p.keys()) == expected
```

Add a new test asserting 200/400/700/800/950 are all present (the new steps that weren't there before):

```python
def test_new_intermediate_steps_present():
    nodes = [_walked("Button", [_solid_fill(0.063, 0.725, 0.506)])]
    p = extract_tokens(nodes)["color"]["primary"]
    for k in ("200", "300", "400", "700", "800", "950"):
        assert k in p
```

- [ ] **Step 2: Replace the implementation**

In `backend/services/figma_style_extractor.py`, replace this block:

```python
    if primary_counter:
        primary_500, _ = primary_counter.most_common(1)[0]
        tokens["color"]["primary"]["500"] = primary_500
        tokens["color"]["primary"]["50"]  = _tint(primary_500, 0.92)
        tokens["color"]["primary"]["100"] = _tint(primary_500, 0.85)
        tokens["color"]["primary"]["600"] = _shade(primary_500, 0.10)
        tokens["color"]["primary"]["900"] = _shade(primary_500, 0.45)
```

With:

```python
    if primary_counter:
        primary_500, _ = primary_counter.most_common(1)[0]
        from services.color_theory import derive_scale
        tokens["color"]["primary"] = derive_scale(primary_500)
```

Leave the neutral-promotion fallback (`if neutral_counter and "900" not in tokens["color"]["primary"]`) AS-IS — `derive_scale` always populates 900, so the fallback only fires when there was no primary candidate at all.

The local `_tint` and `_shade` helpers can stay (they're used in test scaffolding) but mark them as deprecated in a one-line docstring.

- [ ] **Step 3: Run tests**

```bash
cd backend && pytest tests/services/test_figma_style_extractor.py -v
```

All 14 tests should pass. If any of the old 5-step assertions still exist outside the ones we updated, update them too.

- [ ] **Step 4: Regression**

```bash
cd backend && pytest tests/services/ tests/integration/ -v
```

- [ ] **Step 5: Commit**

```
feat(figma): wire color_theory.derive_scale into token extractor — full 11-step palette
```
HEREDOC + Co-Authored-By trailer.

---

## WS-B — Typography Extraction

### Task 3: figma_typography_extractor module

**Files:**
- Create: `backend/services/figma_typography_extractor.py`
- Test: `backend/tests/services/test_figma_typography_extractor.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/services/test_figma_typography_extractor.py
from services.figma_typography_extractor import extract_typography


def _text_node(name, style):
    return {"node": {"name": name, "type": "TEXT", "style": style}, "parent": None, "path": []}


def test_picks_heading_font_from_heading_named_text():
    walked = [
        _text_node("IntentAI Title", {"fontFamily": "Inter Display", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40, "letterSpacing": -0.5}),
        _text_node("Welcome Title", {"fontFamily": "Inter Display", "fontWeight": 600, "fontSize": 24, "lineHeightPx": 32, "letterSpacing": -0.3}),
    ]
    typo = extract_typography(walked)
    assert typo["font"]["heading"] == "Inter Display"
    assert typo["weight"]["heading"] in ("600", "700")  # most common heading weight


def test_picks_body_font_from_plain_text():
    walked = [
        _text_node("Sign in Subtitle", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
        _text_node("Platform Description", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 14, "lineHeightPx": 20}),
    ]
    typo = extract_typography(walked)
    assert typo["font"]["body"] == "Inter"
    assert typo["weight"]["body"] == "400"


def test_heading_and_body_can_differ():
    walked = [
        _text_node("Heading 1", {"fontFamily": "Cal Sans", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40}),
        _text_node("Sign in Subtitle", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    typo = extract_typography(walked)
    assert typo["font"]["heading"] == "Cal Sans"
    assert typo["font"]["body"] == "Inter"


def test_scale_collects_unique_font_sizes():
    """Multiple distinct font-sizes across nodes should become scale steps."""
    walked = [
        _text_node("Heading 1", {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40}),
        _text_node("Heading 4", {"fontFamily": "Inter", "fontWeight": 600, "fontSize": 18, "lineHeightPx": 24}),
        _text_node("Paragraph", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
        _text_node("Email Label", {"fontFamily": "Inter", "fontWeight": 500, "fontSize": 12, "lineHeightPx": 16}),
    ]
    typo = extract_typography(walked)
    sizes_rem = set(typo["scale"].values())
    # 12px → 0.75rem, 16px → 1rem, 18px → 1.125rem, 32px → 2rem
    assert "0.75rem" in sizes_rem
    assert "1rem" in sizes_rem
    assert "2rem" in sizes_rem


def test_line_height_derived_from_body_node():
    walked = [
        _text_node("Paragraph", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    typo = extract_typography(walked)
    # 24/16 = 1.5 → typography.lineHeight.normal
    assert typo["lineHeight"]["normal"] == "1.5"


def test_letter_spacing_from_heading():
    """Headings often have tight letter-spacing (negative). Capture if present."""
    walked = [
        _text_node("Heading 1", {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40, "letterSpacing": -0.5}),
    ]
    typo = extract_typography(walked)
    # -0.5px on 32px → -0.5/32 = -0.015625em → rounded display
    val = typo["letterSpacing"]["heading"]
    assert val.endswith("em")
    assert val.startswith("-")  # negative


def test_empty_walked_returns_safe_defaults():
    """No TEXT nodes → safe defaults so downstream renderer doesn't break."""
    typo = extract_typography([])
    assert typo["font"]["body"]
    assert typo["font"]["heading"]
    assert typo["weight"]["body"]
    assert typo["weight"]["heading"]


def test_ignores_non_text_nodes():
    """Frames / Rectangles without `style.fontFamily` must not crash."""
    walked = [
        {"node": {"name": "Container", "type": "FRAME"}, "parent": None, "path": []},
        _text_node("Body", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    typo = extract_typography(walked)
    assert typo["font"]["body"] == "Inter"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

```python
# backend/services/figma_typography_extractor.py
"""Extract typography tokens from Figma TEXT nodes.

Strategy:
  - Heading-named text nodes ("Heading N", "* Title", "* Header") vote
    for the heading family / weight / letter-spacing.
  - All other TEXT nodes vote for the body family / weight.
  - Every unique fontSize becomes a `typography.scale` entry, named by
    Tailwind's t-shirt sizing (xs/sm/base/lg/xl/2xl/3xl/4xl/5xl) closest
    to the px value.
  - lineHeight.normal derives from the most common body line-height ratio.
  - letterSpacing.heading is captured from the most common heading
    letterSpacing (converted px → em relative to that node's fontSize).
"""
from __future__ import annotations
from collections import Counter
import re

HEADING_NAME_RE = re.compile(r"^(heading\s*\d|.+\s+title|.+\s+header)$", re.I)

# px → Tailwind size name (snap to nearest)
_SIZE_TO_NAME = [
    (10, "xs",   "0.625rem"),
    (12, "xs",   "0.75rem"),
    (14, "sm",   "0.875rem"),
    (16, "base", "1rem"),
    (18, "lg",   "1.125rem"),
    (20, "xl",   "1.25rem"),
    (24, "2xl",  "1.5rem"),
    (30, "3xl",  "1.875rem"),
    (36, "4xl",  "2.25rem"),
    (48, "5xl",  "3rem"),
    (60, "6xl",  "3.75rem"),
]

_DEFAULTS = {
    "font":          {"body": "Inter", "heading": "Inter"},
    "weight":        {"body": "400", "heading": "600"},
    "scale":         {},
    "lineHeight":    {"tight": "1.25", "normal": "1.5"},
    "letterSpacing": {"heading": "0", "body": "0"},
}


def _is_heading(name: str) -> bool:
    return bool(HEADING_NAME_RE.match((name or "").strip()))


def _nearest_size_name(px: float) -> tuple[str, str]:
    best = _SIZE_TO_NAME[0]; best_diff = abs(_SIZE_TO_NAME[0][0] - px)
    for entry in _SIZE_TO_NAME:
        d = abs(entry[0] - px)
        if d < best_diff: best_diff = d; best = entry
    return best[1], best[2]


def extract_typography(walked_nodes: list[dict]) -> dict:
    fam_heading: Counter = Counter()
    fam_body: Counter = Counter()
    wt_heading: Counter = Counter()
    wt_body: Counter = Counter()
    sizes_px: set[float] = set()
    body_line_ratios: list[float] = []
    heading_letter_em: Counter = Counter()

    for entry in walked_nodes:
        node = entry["node"]
        if node.get("type") != "TEXT":
            continue
        style = node.get("style") or {}
        fam = style.get("fontFamily")
        weight = style.get("fontWeight")
        font_size = style.get("fontSize")
        line_h_px = style.get("lineHeightPx")
        letter_sp = style.get("letterSpacing")
        name = node.get("name") or ""
        is_h = _is_heading(name)

        if fam:
            (fam_heading if is_h else fam_body)[fam] += 1
        if weight:
            (wt_heading if is_h else wt_body)[str(weight)] += 1
        if isinstance(font_size, (int, float)) and font_size > 0:
            sizes_px.add(float(font_size))
        if isinstance(font_size, (int, float)) and isinstance(line_h_px, (int, float)) and font_size > 0:
            ratio = line_h_px / font_size
            if not is_h: body_line_ratios.append(ratio)
        if is_h and isinstance(letter_sp, (int, float)) and isinstance(font_size, (int, float)) and font_size > 0:
            em = letter_sp / font_size
            heading_letter_em[f"{em:.3f}em".replace("-0.", "-.")] += 1

    out: dict = {k: dict(v) for k, v in _DEFAULTS.items()}

    if fam_heading: out["font"]["heading"] = fam_heading.most_common(1)[0][0]
    if fam_body:    out["font"]["body"]    = fam_body.most_common(1)[0][0]
    # If only one was found, use it for both (common in single-family designs)
    if fam_heading and not fam_body: out["font"]["body"] = out["font"]["heading"]
    if fam_body and not fam_heading: out["font"]["heading"] = out["font"]["body"]

    if wt_heading: out["weight"]["heading"] = wt_heading.most_common(1)[0][0]
    if wt_body:    out["weight"]["body"]    = wt_body.most_common(1)[0][0]

    # Scale — collect unique sizes, snap each to a Tailwind name
    for px in sorted(sizes_px):
        name, rem = _nearest_size_name(px)
        out["scale"][name] = rem

    if body_line_ratios:
        avg = sum(body_line_ratios) / len(body_line_ratios)
        out["lineHeight"]["normal"] = f"{avg:.2f}".rstrip("0").rstrip(".")

    if heading_letter_em:
        out["letterSpacing"]["heading"] = heading_letter_em.most_common(1)[0][0]

    return out
```

- [ ] **Step 4: Run tests, expect PASS**

If any test fails, iterate on the implementation. Likely culprits: the `lineHeight.normal` formatting (e.g. `1.5` vs `1.50`) — use `f"{avg:.2f}".rstrip("0").rstrip(".")` to drop trailing zeros.

- [ ] **Step 5: Commit**

```
feat(figma): typography extractor — font family / weight / scale / lineHeight / letterSpacing
```
HEREDOC + Co-Authored-By trailer.

---

## WS-C — Wire-up

### Task 4: figma_to_schema merges typography tokens

**Files:**
- Modify: `backend/services/figma_to_schema.py`
- Modify: `backend/tests/services/test_figma_to_schema.py`

- [ ] **Step 1: Update orchestrator**

In `backend/services/figma_to_schema.py`, change the `build_page_schema` body around the `extract_tokens` call:

```python
def build_page_schema(document: dict) -> BuildResult:
    walked = walk_and_flatten(document)
    colour_tokens = extract_tokens(walked)
    from services.figma_typography_extractor import extract_typography
    typography_tokens = extract_typography(walked)
    # Merge — colour_tokens already has `color` + `surface`; add typography.
    tokens = dict(colour_tokens)
    tokens["typography"] = typography_tokens
    # ... rest unchanged
```

- [ ] **Step 2: Add a test**

Append to `backend/tests/services/test_figma_to_schema.py`:

```python
def test_emits_typography_tokens():
    """The Commitbiz fixture must yield a typography block alongside colour."""
    import json
    doc = json.loads(FIXTURE.read_text())
    result = build_page_schema(doc)
    typo = result.tokens.get("typography") or {}
    assert "font" in typo
    assert typo["font"]["body"]
    assert typo["font"]["heading"]
    assert "scale" in typo
```

**Note:** the existing fixture (`commitbiz_login.json`) doesn't include `style` blocks on its TEXT nodes — they were synthesised in T7 without typography metadata. Either:
- (a) Add minimal `style` blocks to the fixture (recommended — keeps the fixture realistic), or
- (b) Make the test tolerant of defaults.

Pick (a). Open the fixture file and add `"style": {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40, "letterSpacing": -0.5}` to "IntentAI Title", and similar realistic styles to "Welcome Title" (24/600), "Sign in Subtitle" (16/400), "Sign in Button Text" (16/600), at least one label (12/500).

- [ ] **Step 3: Run tests**

```bash
cd backend && pytest tests/services/test_figma_to_schema.py tests/services/test_figma_typography_extractor.py -v
```

- [ ] **Step 4: Regression**

```bash
cd backend && pytest tests/services/ tests/integration/ -v
```

- [ ] **Step 5: Commit**

```
feat(figma): orchestrator merges typography tokens; fixture augmented with realistic styles
```
HEREDOC + Co-Authored-By trailer.

### Task 5: Verify EngineProvider picks up typography vars

**Files:** No code — verification only.

- [ ] **Step 1: Inspect what CSS vars get injected in the editor canvas**

The engine's `tokensToCssVars` walks the token tree and emits `--typography-font-body`, `--typography-font-heading`, `--typography-weight-heading`, `--typography-scale-base`, etc. With the new typography block in `tokens.custom.json`, these vars should appear automatically (no engine change needed).

Run via Playwright (after running a Figma-driven generation):

```python
python3 - <<'PY'
import asyncio
async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context()
        p = await ctx.new_page()
        await p.goto("http://localhost:6501/editor/<new-short-id>", wait_until="networkidle")
        await p.wait_for_timeout(3000)
        info = await p.evaluate("""() => {
            const w = document.querySelector('[data-tentoro-engine]');
            const cs = getComputedStyle(w);
            return {
                fontBody: cs.getPropertyValue('--typography-font-body').trim(),
                fontHeading: cs.getPropertyValue('--typography-font-heading').trim(),
                scaleBase: cs.getPropertyValue('--typography-scale-base').trim(),
            };
        }""")
        print(info)
asyncio.run(main())
PY
```

Expected: non-empty values for all three.

- [ ] **Step 2: Mark plan complete**

If the verification check passes, this plan is done. Commit any supporting notes.

---

## Sequencing

| Step | Time | Notes |
|---|---|---|
| WS-A T1 (derive_scale) | 30 min | Pure-Python, test-driven, no integration risk |
| WS-A T2 (wire into extractor) | 15 min | Replaces 5 lines |
| WS-B T3 (typography extractor) | 1 h | New module, ~150 LOC + tests |
| WS-C T4 (merge in orchestrator) | 20 min | Two-file edit |
| WS-C T5 (visual verify) | 15 min | Manual |

**Total: ~2.5 hours.**

---

## Self-Review

- **Spec coverage:** Both follow-ups from the previous summary are tasked: full 11-step colour scale (Tasks 1–2) and typography extraction with merge into the orchestrator's tokens output (Tasks 3–4). Task 5 is the manual sanity check.
- **Placeholder scan:** No `TBD`. Two places the implementer needs to choose: in T1 if lightness targets need ±0.02 tweaks (documented as part of the task), and in T4 step 2 between options (a) and (b) for fixture augmentation (option (a) recommended in-line).
- **Type consistency:** `derive_scale(primary_hex: str) -> dict[str, str]` introduced in T1 is used in T2. `extract_typography(walked_nodes) -> dict` introduced in T3 is consumed in T4. `tokens.custom.json` shape (top keys: color, typography) matches the existing convention from project db17s1zl.
- **Risk callouts:** T1's lightness curve may need calibration to satisfy the "preserves hue" test on edge inputs (very saturated reds / blues). The plan documents the tweak path. T3's `lineHeight.normal` and `letterSpacing.heading` numeric formatting (trailing zeros, `em` vs `rem`) is the kind of detail that often needs one quick iteration — the test is the ground truth.
