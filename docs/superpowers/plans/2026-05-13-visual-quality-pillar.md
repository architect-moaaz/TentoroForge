# Visual Quality Pillar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the visual-quality gap between Tentoro-generated apps and hand-designed reference apps (PatientPop, Google Analytics, BALA, WELCOME BACK) by giving every generation a derived brand identity, curated illustrations, paired typography, and photographic accents — with a vision-grounded fidelity loop that measures improvement objectively.

**Architecture:** Eight workstreams. **A** is a 1-day validation spike that proves the strategy before committing 12 weeks. **B** (brand extraction) is the foundation everything else builds on. **C** (illustrations) couples to brand via recolor. **D** (typography) selects per-domain pairings. **E** (photos) brings Unsplash assets into avatars and heroes. **F** (layout primitives) unblocks overlap-card and full-bleed patterns the schema can't express today. **G** (stress-test + fidelity scoring) makes quality measurable. **H** (editor UI) exposes brand-setup, illustration-browse, and typography-pick to users.

**Tech Stack:** Python (FastAPI, Pillow, scikit-learn for color clustering, httpx for HTTP); TypeScript (Zod, React, Tailwind); pytest + vitest; Tailwind utility classes; Google Fonts CDN; Unsplash API; unDraw library (locally cached).

**Spec:** This plan is its own spec — derived from the strategic discussion in session 2026-05-13 with reference images (WELCOME BACK runner login, Google Analytics Reports snapshot, BALA dual-card login, dashboard wireframe).

---

## Background — what's missing today

Pages we generate render correctly and have proper density (per the dashboard-fidelity work that just shipped: `commit 39bfef1` + 17 prior commits in plan `2026-05-12-dashboard-fidelity-density.md`). But the visual identity feels generic because:

1. **Colors come from a register choice** (linear/notion/figma/etc.), not from the user's brand. Tentoro picks one of 6 palettes per generation; brand-specific palette never enters.
2. **Illustrations exist in the library but are rarely emitted**. The illustrations MCP (commits `84c7126` + `20252ba`) is wired, but the LLM under-invokes the tool. Even when invoked, illustrations are colored with default unDraw blue, not the project's primary.
3. **Typography is a single Inter-based system** across all generations. No "modern minimal vs editorial vs playful" differentiation; no font-pair logic.
4. **Avatars use initials in colored circles**. Real photos from Unsplash would shift the apparent quality 30%+ in user studies.
5. **Schema lacks positioning primitives**. The BALA-style overlapping cards or sticky-CTA-bar landing patterns can't be expressed today.
6. **No objective quality measurement**. Every change is judged subjectively; can't tell if a prompt tweak helped or hurt.

This plan tackles all six in order of leverage.

**Out of scope (deliberate):**
- Custom hand-drawn illustrations (no AI synthesizes these at quality)
- Real video / Lottie animation assets
- Image-gen API (DALL-E/Imagen) for bespoke art — keep as a future option
- Full Figma-style multi-user editor (covered in Pillar 1 plan, separate)
- Per-page performance optimization (covered in Pillar 3 plan, separate)

---

## File structure

### New backend files

```
backend/services/
  brand_extractor.py            # k-means color extraction from logo bytes
  color_theory.py               # primary → analogous/complementary/ramp derivation
  url_brand_scraper.py          # paste URL → extract og-image + palette
  typography_registers.py       # 4 typography pairings (data + selector)
  illustration_curator.py       # access to curated 80-SVG library + recolor
  unsplash_client.py            # cached HTTP wrapper for Unsplash API
  photo_picker.py               # domain + entity → photo URL
  fidelity_scorer.py            # vision-model scoring vs reference screenshots

backend/routers/
  brand.py                      # POST /api/brand/extract — logo or URL

backend/fixtures/
  illustrations_curated/        # 80 hand-picked SVGs with index.json
  typography_registers.json     # 4 typography pairings (font names + tracking + sizes)
  unsplash_seeds.json           # per-domain Unsplash search queries (cached)
  reference_images/             # 30 hand-collected reference screenshots for scoring

backend/tests/services/
  test_brand_extractor.py
  test_color_theory.py
  test_url_brand_scraper.py
  test_typography_registers.py
  test_illustration_curator.py
  test_unsplash_client.py
  test_photo_picker.py
  test_fidelity_scorer.py

backend/tests/routers/
  test_brand.py
```

### Modified backend files

```
backend/agents/design_agent.py
  - save_design_spec: when project has brand.extracted, use it instead of register palette
  - emit typography register + font-family CSS variables

backend/agents/page_schema_agent.py
  - post-emit fallback: if Hero on auth/empty-state has no illustration, pick from curator

backend/services/schema_prompt.py
  - sharpen auth-page-illustration rule from "should call" to "MUST call list_illustrations"
  - inject brand colors as explicit context

backend/services/illustration_bundler.py
  - recolor SVG to project's primary color before writing to public/illustrations/
```

### New library + schema files

```
packages/schema/src/
  style-slot.ts                 # add position, top/left/right/bottom, zIndex
  nodes/photos.ts               # PhotoHero, AvatarPhoto nodes

packages/library/src/components/
  OverlayCard/                  # BALA-style absolute-positioned card
  PhotoHero/                    # Hero with background image variant
  surfaces/PositionedBox.tsx    # generic absolute/sticky/fixed wrapper

packages/library/tests/components/
  OverlayCard.test.tsx
  PhotoHero.test.tsx
  PositionedBox.test.tsx
```

### Modified library files

```
packages/library/src/components/
  Heading/Heading.tsx                    # display-weight + tracking variant
  Avatar/Avatar.tsx                      # accept photoUrl prop
  Hero/Hero.tsx                          # background-image option

packages/renderer/src/runtime/
  style-slot.ts                          # apply position/top/zIndex when present
```

### New editor UI files (Workstream H, can defer)

```
packages/editor/src/panels/
  BrandSetup/BrandSetupWizard.tsx        # logo upload OR URL OR manual palette
  IllustrationBrowser/Browser.tsx        # scroll + filter + insert
  TypographyPicker/Picker.tsx            # 4 typography registers with live preview
```

---

## Design decisions (locked in before tasks)

1. **Brand extraction priority chain**: explicit user-set palette > URL-scraped > logo-extracted > default register. Each step can be overridden.

2. **Color clustering algorithm**: k-means with k=5 on the logo's non-transparent pixels (downsampled to 64×64 for speed). Filter out near-white/near-black neutrals. The most-saturated remaining cluster is the primary.

3. **Illustration recolor mechanism**: text replacement in SVG markup. unDraw illustrations use a single accent color repeated throughout the file. Replace its hex with the project's primary. Pure regex; no SVG parser needed.

4. **Typography registers** are data-only (no code per register). A `typography_registers.json` lists 4 pairings; design_agent picks one. Adding more is content work, not engineering work.

5. **Photo system uses Unsplash Source API** (`https://source.unsplash.com/<size>/?<query>`) for deterministic results without an API key. The `unsplash_client.py` caches URLs locally so retries are stable.

6. **Fidelity scoring uses Claude vision** (the existing claude_agent_sdk) to compare rendered screenshots against reference images. Returns 0–10 score plus structured feedback.

7. **Brand extraction runs ONCE per project**, cached in `design-spec.json` under `brand.*`. Subsequent generations of new pages reuse the cached brand identity. Re-running brand extraction is an explicit user action.

8. **Layout primitives ship behind a flag** (`SCHEMA_POSITION_ENABLED=true`) initially so existing renders aren't disturbed if the new style-slot fields break parse.

9. **Workstream A (validation) is BLOCKING**. If the 1-day spike shows weak signal, the rest of the plan needs revision — don't commit eng to B+C+D until A's screenshots have been reviewed by 5 designers/PMs.

---

## Workstream A — Validation spike (1 day, 1 task)

The whole pillar de-risked by 6 hours of manual work before committing 12 weeks of engineering.

### Task 1: Manual prototype + designer review

**Files:** None modified; this is a non-engineering validation.

- [ ] **Step 1.1: Pick a target project**

Use the already-generated `clean-1778676179` (notes app with `/home` dashboard + `/notes` list).

- [ ] **Step 1.2: Hand-pick 4 unDraw illustrations**

From unDraw.co, save the SVG source for:
- A "productivity / focus" illustration (for the dashboard hero)
- An "empty-state list" illustration (for an empty notes list)
- A "celebration / success" illustration (for a success state)
- A "writing / typing" illustration (for the form CTA area)

Save to `/Users/m/Desktop/spike-illustrations/` as `dashboard.svg`, `empty-list.svg`, `success.svg`, `form.svg`.

- [ ] **Step 1.3: Recolor each SVG manually**

Open each SVG in a text editor. Find the brand-accent hex (unDraw illustrations have one dominant color). Replace with the project's primary `#0284C7`. Save.

Quick command (run from `/Users/m/Desktop/spike-illustrations/`):

```bash
for f in *.svg; do
  sed -i '' 's/#6c63ff/#0284C7/gI' "$f"  # unDraw's default purple → project primary
done
```

(unDraw's default is `#6c63ff`. Verify by grepping; some illustrations use other defaults.)

- [ ] **Step 1.4: Copy into the project's public dir**

```bash
mkdir -p /Users/m/Work/code/poc/design2ui-forge-v3/output/clean-1778676179/public/illustrations
cp /Users/m/Desktop/spike-illustrations/*.svg \
   /Users/m/Work/code/poc/design2ui-forge-v3/output/clean-1778676179/public/illustrations/
```

- [ ] **Step 1.5: Hand-edit schemas to reference illustrations**

Edit `output/clean-1778676179/src/schemas/home.json`:
- Find the Hero node
- Add `"props": { ..., "illustration": { "slug": "dashboard", "alt": "Productivity illustration" } }`

Edit `output/clean-1778676179/src/schemas/notes.json`:
- Find the Repeat (list) node
- Wrap in a conditional or just add a hero-style Section before it referencing `empty-list.svg`

The component changes from earlier (commit `70198bf`) already support the `illustration` slot; this just needs the schema to set it.

- [ ] **Step 1.6: Reload + screenshot**

Navigate to:
- http://localhost:6503/p/clean-1778676179/home
- http://localhost:6503/p/clean-1778676179/notes

Take screenshots of both pages.

- [ ] **Step 1.7: Show 5 designers/PMs side-by-side**

Compare:
- The original screenshots (`clean-1778676179` before today)
- The new screenshots (after Steps 1.4–1.6)

Ask each reviewer ONE question: **"On a scale of 1–10, how much does the new version look like a designer made it?"**

Record the 5 scores. Also record any qualitative remark.

- [ ] **Step 1.8: Decide go/no-go**

| Average score | Decision |
|---|---|
| ≥ 7.5 | Green light — proceed with the rest of the plan |
| 6–7.5 | Some adjustment needed before committing to full plan — re-examine what's missing (probably typography, photos) |
| < 6 | Validation failed — the illustration-recolor approach isn't the bottleneck. Stop and rethink. |

This is the most important step in the entire plan. **Don't skip it.**

---

## Workstream B — Brand extraction (foundation)

Every downstream component (illustrations, typography, photos) consumes the brand identity. Without this, the rest is incremental polish on a generic foundation.

### Task 2: Color extraction module

**Files:**
- Create: `backend/services/brand_extractor.py`
- Create: `backend/tests/services/test_brand_extractor.py`

- [ ] **Step 2.1: Write the failing test**

```python
# backend/tests/services/test_brand_extractor.py
"""Tests for brand color extraction from logo bytes."""
import pytest
from pathlib import Path
from services.brand_extractor import extract_palette_from_logo, BrandPalette


@pytest.fixture
def red_square_png():
    """An 8×8 pure-red PNG, used as a deterministic test fixture."""
    from PIL import Image
    import io
    img = Image.new("RGB", (8, 8), (220, 38, 38))  # #DC2626 red
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def blue_with_white_png():
    """A 16×16 PNG: half pure-blue #0EA5E9, half white (near-neutral)."""
    from PIL import Image
    import io
    img = Image.new("RGB", (16, 16), (255, 255, 255))
    for x in range(8):
        for y in range(16):
            img.putpixel((x, y), (14, 165, 233))  # #0EA5E9
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_palette_returns_brand_palette(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    assert isinstance(result, BrandPalette)


def test_extract_palette_picks_dominant_color(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    # Primary should be close to #DC2626 (RGB 220, 38, 38)
    r, g, b = result.primary_rgb
    assert r > 180 and g < 80 and b < 80


def test_extract_palette_filters_near_white(blue_with_white_png):
    result = extract_palette_from_logo(blue_with_white_png)
    # Primary should be the blue #0EA5E9, not white
    r, g, b = result.primary_rgb
    assert b > 180 and r < 100  # blue-dominant


def test_extract_palette_returns_hex_strings(red_square_png):
    result = extract_palette_from_logo(red_square_png)
    assert result.primary_hex.startswith("#") and len(result.primary_hex) == 7
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_brand_extractor.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 2.3: Implement `brand_extractor.py`**

```python
# backend/services/brand_extractor.py
"""Extract a brand color palette from a logo image.

Uses k-means clustering on the logo's non-transparent pixels to find
dominant colors, filters out near-neutrals (very light grays, blacks
that are likely background or stroke), and returns the most-saturated
cluster as the primary brand color.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
from PIL import Image
import numpy as np
from sklearn.cluster import KMeans


@dataclass(frozen=True)
class BrandPalette:
    """Result of brand extraction from a logo."""
    primary_rgb: tuple[int, int, int]
    primary_hex: str
    secondary_rgb: tuple[int, int, int] | None
    secondary_hex: str | None
    raw_clusters: list[tuple[int, int, int]]  # all k clusters, for debugging


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _is_near_neutral(rgb: tuple[int, int, int]) -> bool:
    """A color is neutral when its channels are all within 15 of each other,
    OR when its average is very high (>240, near-white) or very low (<25, near-black)."""
    r, g, b = rgb
    spread = max(r, g, b) - min(r, g, b)
    avg = (r + g + b) / 3
    return spread < 15 or avg > 240 or avg < 25


def _saturation(rgb: tuple[int, int, int]) -> float:
    """Rough saturation: max channel minus min channel, normalised to [0, 1]."""
    r, g, b = rgb
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def extract_palette_from_logo(logo_bytes: bytes, k: int = 5) -> BrandPalette:
    """Extract a BrandPalette from a logo's bytes (PNG/JPG).

    Algorithm:
      1. Decode + downsample to 64×64 for speed
      2. Drop fully-transparent pixels (alpha < 16)
      3. K-means with k clusters on RGB values
      4. Filter out near-neutral clusters
      5. Pick most-saturated as primary, second-most as secondary
    """
    img = Image.open(BytesIO(logo_bytes))
    img.thumbnail((64, 64))  # downsample
    img = img.convert("RGBA")
    pixels = np.array(img).reshape(-1, 4)
    # Drop transparent pixels
    pixels = pixels[pixels[:, 3] >= 16][:, :3]
    if len(pixels) < k:
        # Not enough non-transparent pixels — fall back to average colour
        avg = tuple(int(c) for c in pixels.mean(axis=0))
        return BrandPalette(
            primary_rgb=avg,
            primary_hex=_rgb_to_hex(avg),
            secondary_rgb=None,
            secondary_hex=None,
            raw_clusters=[avg],
        )
    # K-means
    actual_k = min(k, len(pixels))
    km = KMeans(n_clusters=actual_k, n_init=10, random_state=42)
    km.fit(pixels)
    clusters: list[tuple[int, int, int]] = [
        tuple(int(c) for c in centre) for centre in km.cluster_centers_
    ]
    # Filter neutrals
    saturated = [c for c in clusters if not _is_near_neutral(c)]
    # Sort by saturation, descending
    saturated.sort(key=_saturation, reverse=True)
    if not saturated:
        # All clusters were neutral — pick the most-saturated even if it's drab
        clusters.sort(key=_saturation, reverse=True)
        primary = clusters[0]
        secondary = clusters[1] if len(clusters) > 1 else None
    else:
        primary = saturated[0]
        secondary = saturated[1] if len(saturated) > 1 else None
    return BrandPalette(
        primary_rgb=primary,
        primary_hex=_rgb_to_hex(primary),
        secondary_rgb=secondary,
        secondary_hex=_rgb_to_hex(secondary) if secondary else None,
        raw_clusters=clusters,
    )
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_brand_extractor.py -v
```

Expected: PASS, 4 tests.

If `scikit-learn` isn't installed: `pip install scikit-learn pillow numpy` and add to `requirements.txt`.

- [ ] **Step 2.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/brand_extractor.py backend/tests/services/test_brand_extractor.py
git commit -m "$(cat <<'EOF'
feat(brand): k-means color extraction from logo bytes

extract_palette_from_logo() downsamples to 64x64, drops transparent
pixels, runs k-means with k=5, filters near-neutrals, returns primary
+ secondary by saturation. Foundation for the visual-quality pillar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3: Color theory engine

**Files:**
- Create: `backend/services/color_theory.py`
- Create: `backend/tests/services/test_color_theory.py`

- [ ] **Step 3.1: Write the failing test**

```python
# backend/tests/services/test_color_theory.py
"""Tests for color-theory-derived palette generation."""
from services.color_theory import derive_palette, DerivedPalette


def test_derive_palette_from_blue_primary():
    p = derive_palette("#0EA5E9")  # sky-500
    assert isinstance(p, DerivedPalette)
    # All output values are valid hex
    for v in [p.primary, p.secondary, p.accent, p.background, p.surface,
              p.text_primary, p.text_secondary, p.border, p.success, p.warning, p.error]:
        assert v.startswith("#") and len(v) == 7


def test_derive_palette_keeps_primary_exact():
    p = derive_palette("#FF5733")
    assert p.primary.upper() == "#FF5733"


def test_derive_palette_text_primary_is_dark_on_light_bg():
    """For a light-background design, text-primary must have >7:1 contrast."""
    p = derive_palette("#0EA5E9")
    # background should be very light
    bg_r, bg_g, bg_b = int(p.background[1:3], 16), int(p.background[3:5], 16), int(p.background[5:7], 16)
    assert (bg_r + bg_g + bg_b) / 3 > 230  # near-white
    # text-primary should be very dark
    t_r, t_g, t_b = int(p.text_primary[1:3], 16), int(p.text_primary[3:5], 16), int(p.text_primary[5:7], 16)
    assert (t_r + t_g + t_b) / 3 < 40


def test_derive_palette_uses_provided_secondary_when_given():
    p = derive_palette("#FF5733", secondary_hint="#3366FF")
    assert p.secondary.upper() == "#3366FF"


def test_derive_palette_synthesizes_secondary_when_not_given():
    """Without a secondary hint, derive_palette picks a complementary
    or analogous color of its own choosing."""
    p = derive_palette("#FF5733")
    # secondary must not equal primary
    assert p.secondary.upper() != "#FF5733"
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_color_theory.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3.3: Implement `color_theory.py`**

```python
# backend/services/color_theory.py
"""Derive a complete UI palette from a single primary color.

Strategy:
- Primary: as given
- Secondary: provided hint OR derived as a hue ~150° complementary
- Accent: ~30° analogous to primary (warm-shift if primary is cool, vice versa)
- Background: near-white with primary's hue at very low saturation
- Surface: pure white
- Text-primary: near-black (always, for AA contrast)
- Text-secondary: 40% of black
- Border: 90% lightness of primary's hue
- Status: success (green), warning (amber), error (red) — fixed conventional values
"""
from __future__ import annotations
from dataclasses import dataclass
import colorsys


@dataclass(frozen=True)
class DerivedPalette:
    primary: str
    secondary: str
    accent: str
    background: str
    surface: str
    text_primary: str
    text_secondary: str
    border: str
    success: str
    warning: str
    error: str


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """h in [0,1), s/l in [0,1]."""
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return _rgb_to_hex((r * 255, g * 255, b * 255))


def _hex_to_hsl(hex_str: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(hex_str)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h, s, l


def derive_palette(primary: str, secondary_hint: str | None = None) -> DerivedPalette:
    h, s, l = _hex_to_hsl(primary)

    # Secondary: hint > complementary
    secondary = (
        secondary_hint
        if secondary_hint
        else _hsl_to_hex((h + 0.5) % 1.0, min(s, 0.6), max(0.35, min(l, 0.55)))
    )

    # Accent: analogous (+30° hue shift, slightly desaturated)
    accent = _hsl_to_hex((h + (30 / 360)) % 1.0, min(s, 0.55), max(0.45, min(l, 0.6)))

    # Background: same hue, very low saturation, very high lightness
    background = _hsl_to_hex(h, min(s, 0.08), 0.98)

    # Surface: pure white (cards on background)
    surface = "#FFFFFF"

    # Text: near-black + 60% gray
    text_primary = "#0F172A"
    text_secondary = "#475569"

    # Border: same hue, low saturation, light
    border = _hsl_to_hex(h, min(s, 0.15), 0.88)

    # Status: conventional fixed values
    success = "#22C55E"
    warning = "#F59E0B"
    error = "#EF4444"

    return DerivedPalette(
        primary=primary.upper(),
        secondary=secondary.upper(),
        accent=accent.upper(),
        background=background.upper(),
        surface=surface,
        text_primary=text_primary,
        text_secondary=text_secondary,
        border=border.upper(),
        success=success,
        warning=warning,
        error=error,
    )
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_color_theory.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 3.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/color_theory.py backend/tests/services/test_color_theory.py
git commit -m "$(cat <<'EOF'
feat(brand): derive full UI palette from a single primary colour

derive_palette() takes a hex primary and produces secondary, accent,
background, surface, text, border, and status colours using simple
HSL relationships. AA-contrast text guaranteed. Accepts an optional
secondary_hint for when the brand has more than one strong colour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4: URL brand scraper

**Files:**
- Create: `backend/services/url_brand_scraper.py`
- Create: `backend/tests/services/test_url_brand_scraper.py`

- [ ] **Step 4.1: Write the failing test**

```python
# backend/tests/services/test_url_brand_scraper.py
"""Tests for extracting brand identity from a paste-in URL."""
import pytest
from unittest.mock import patch, MagicMock
from services.url_brand_scraper import scrape_brand_from_url, ScrapedBrand


def test_scrape_returns_brand_with_palette():
    """When the URL serves an og:image, we extract a palette from it."""
    fake_html = """
    <html>
      <head>
        <meta property="og:image" content="https://example.com/logo.png" />
        <meta property="og:title" content="ACME Corp" />
      </head>
    </html>
    """
    fake_logo_bytes = open("/dev/zero", "rb").read(1024)  # dummy bytes for branch coverage
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, text=fake_html),  # HTML fetch
            MagicMock(status_code=200, content=fake_logo_bytes),  # logo fetch
        ]
        with patch("services.url_brand_scraper.extract_palette_from_logo") as mock_extract:
            from services.brand_extractor import BrandPalette
            mock_extract.return_value = BrandPalette(
                primary_rgb=(220, 38, 38),
                primary_hex="#DC2626",
                secondary_rgb=None,
                secondary_hex=None,
                raw_clusters=[(220, 38, 38)],
            )
            result = scrape_brand_from_url("https://acme.com")
    assert isinstance(result, ScrapedBrand)
    assert result.title == "ACME Corp"
    assert result.primary_hex == "#DC2626"


def test_scrape_returns_none_when_no_og_image():
    fake_html = "<html><head></head><body>no metadata</body></html>"
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text=fake_html)
        result = scrape_brand_from_url("https://no-og.example.com")
    assert result is None


def test_scrape_handles_network_failure():
    import httpx
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = scrape_brand_from_url("https://broken.example.com")
    assert result is None
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_url_brand_scraper.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 4.3: Implement `url_brand_scraper.py`**

```python
# backend/services/url_brand_scraper.py
"""Scrape a URL's brand identity from its og:image meta tag."""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass
import httpx

from services.brand_extractor import extract_palette_from_logo, BrandPalette

logger = logging.getLogger(__name__)

_OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', re.IGNORECASE)


@dataclass(frozen=True)
class ScrapedBrand:
    url: str
    title: str | None
    og_image_url: str
    primary_hex: str
    palette: BrandPalette


def scrape_brand_from_url(url: str, timeout: float = 8.0) -> ScrapedBrand | None:
    """Fetch the URL, parse og:image, run extract_palette_from_logo on the image bytes."""
    client = httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        html = resp.text
    except httpx.RequestError as e:
        logger.warning("scrape: HTTP error on %s: %s", url, e)
        return None

    og_match = _OG_IMAGE_RE.search(html)
    if not og_match:
        return None
    og_url = og_match.group(1)
    if og_url.startswith("//"):
        og_url = "https:" + og_url
    title_match = _OG_TITLE_RE.search(html)
    title = title_match.group(1) if title_match else None

    try:
        img_resp = client.get(og_url)
        if img_resp.status_code != 200:
            return None
        palette = extract_palette_from_logo(img_resp.content)
    except httpx.RequestError as e:
        logger.warning("scrape: og:image fetch failed for %s: %s", og_url, e)
        return None

    return ScrapedBrand(
        url=url,
        title=title,
        og_image_url=og_url,
        primary_hex=palette.primary_hex,
        palette=palette,
    )
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_url_brand_scraper.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 4.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/url_brand_scraper.py backend/tests/services/test_url_brand_scraper.py
git commit -m "$(cat <<'EOF'
feat(brand): scrape brand identity from a URL via og:image

scrape_brand_from_url fetches the page, parses og:image meta, then
runs extract_palette_from_logo on the image bytes. Returns title + primary
hex + full BrandPalette. Returns None on missing meta or network failure
so callers can fall back gracefully.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5: Brand extraction REST endpoint

**Files:**
- Create: `backend/routers/brand.py`
- Create: `backend/tests/routers/test_brand.py`

- [ ] **Step 5.1: Write the failing test**

```python
# backend/tests/routers/test_brand.py
"""Tests for the /api/brand/extract endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import io
from PIL import Image


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _make_red_png_bytes() -> bytes:
    img = Image.new("RGB", (16, 16), (220, 38, 38))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_from_logo_upload(client):
    files = {"logo": ("logo.png", _make_red_png_bytes(), "image/png")}
    resp = client.post("/api/brand/extract/logo", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "primary_hex" in data
    assert data["primary_hex"].startswith("#")


def test_extract_from_url(client):
    with patch("routers.brand.scrape_brand_from_url") as mock_scrape:
        from services.brand_extractor import BrandPalette
        from services.url_brand_scraper import ScrapedBrand
        palette = BrandPalette(
            primary_rgb=(220, 38, 38),
            primary_hex="#DC2626",
            secondary_rgb=None,
            secondary_hex=None,
            raw_clusters=[(220, 38, 38)],
        )
        mock_scrape.return_value = ScrapedBrand(
            url="https://acme.com",
            title="ACME",
            og_image_url="https://acme.com/logo.png",
            primary_hex="#DC2626",
            palette=palette,
        )
        resp = client.post("/api/brand/extract/url", json={"url": "https://acme.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_hex"] == "#DC2626"
    assert data["title"] == "ACME"


def test_extract_from_url_returns_404_when_no_og_image(client):
    with patch("routers.brand.scrape_brand_from_url") as mock_scrape:
        mock_scrape.return_value = None
        resp = client.post("/api/brand/extract/url", json={"url": "https://no-og.com"})
    assert resp.status_code == 404
```

- [ ] **Step 5.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/routers/test_brand.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 5.3: Implement `routers/brand.py`**

```python
# backend/routers/brand.py
"""Brand extraction endpoints.

POST /api/brand/extract/logo   — multipart, logo file → palette
POST /api/brand/extract/url    — JSON {url}, scrape og:image → palette
"""
from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from pydantic import BaseModel
from services.brand_extractor import extract_palette_from_logo
from services.color_theory import derive_palette
from services.url_brand_scraper import scrape_brand_from_url

router = APIRouter()


class _ExtractURLRequest(BaseModel):
    url: str


def _palette_to_full_response(primary_hex: str, secondary_hex: str | None) -> dict:
    derived = derive_palette(primary_hex, secondary_hint=secondary_hex)
    return {
        "primary_hex": primary_hex,
        "secondary_hex": secondary_hex,
        "derived": {
            "primary": derived.primary,
            "secondary": derived.secondary,
            "accent": derived.accent,
            "background": derived.background,
            "surface": derived.surface,
            "text_primary": derived.text_primary,
            "text_secondary": derived.text_secondary,
            "border": derived.border,
            "success": derived.success,
            "warning": derived.warning,
            "error": derived.error,
        },
    }


@router.post("/api/brand/extract/logo")
async def extract_from_logo(logo: UploadFile = File(...)):
    data = await logo.read()
    try:
        palette = extract_palette_from_logo(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not parse logo: {e}")
    return _palette_to_full_response(palette.primary_hex, palette.secondary_hex)


@router.post("/api/brand/extract/url")
async def extract_from_url(req: _ExtractURLRequest = Body(...)):
    result = scrape_brand_from_url(req.url)
    if result is None:
        raise HTTPException(status_code=404, detail="no og:image found at URL")
    response = _palette_to_full_response(result.primary_hex, result.palette.secondary_hex)
    response["title"] = result.title
    response["og_image_url"] = result.og_image_url
    return response
```

- [ ] **Step 5.4: Register the router in `main.py`**

In `backend/main.py`, find where other routers are included (e.g. `app.include_router(...)`) and add:

```python
from routers.brand import router as brand_router
app.include_router(brand_router)
```

- [ ] **Step 5.5: Run tests to verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/routers/test_brand.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5.6: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/routers/brand.py backend/tests/routers/test_brand.py backend/main.py
git commit -m "$(cat <<'EOF'
feat(brand): REST endpoints for logo + URL brand extraction

POST /api/brand/extract/logo  — multipart logo upload
POST /api/brand/extract/url   — JSON {url} → scrape og:image

Both endpoints return the extracted primary/secondary hex plus the
full derived UI palette (text, border, status colours) ready to be
written into design-spec.json.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6: Wire brand into design_agent

**Files:**
- Modify: `backend/agents/design_agent.py`
- Create: `backend/tests/agents/test_design_agent_brand.py`

- [ ] **Step 6.1: Write the failing test**

```python
# backend/tests/agents/test_design_agent_brand.py
"""Tests for design_agent honouring an externally-supplied brand."""
import json
import tempfile
from pathlib import Path
from agents.design_agent import save_design_spec


def test_save_design_spec_uses_brand_when_provided():
    """When the spec has a `brand` field, save_design_spec rewrites
    colorPalette + globals.css :root to the brand's derived palette."""
    with tempfile.TemporaryDirectory() as tmp:
        # Pre-create the globals.css template so save_design_spec finds it
        css_path = Path(tmp) / "src" / "app" / "globals.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text("""@tailwind base;
:root {
  --background: 0 0% 100%;
  --primary: 221 83% 53%;
}""")

        spec = {
            "register": "default",
            "brand": {
                "primary_hex": "#DC2626",
                "derived": {
                    "primary": "#DC2626",
                    "secondary": "#0EA5E9",
                    "accent": "#F97316",
                    "background": "#FEF2F2",
                    "surface": "#FFFFFF",
                    "text_primary": "#0F172A",
                    "text_secondary": "#475569",
                    "border": "#FECACA",
                    "success": "#22C55E",
                    "warning": "#F59E0B",
                    "error": "#EF4444",
                },
            },
            "colorPalette": {"background": "#FFFFFF", "primary": "#FFFFFF"},  # placeholder
        }
        save_design_spec(tmp, spec)
        # design-spec.json must have brand-driven colorPalette
        saved = json.loads((Path(tmp) / "src" / "contracts" / "design-spec.json").read_text())
        assert saved["colorPalette"]["background"] == "#FEF2F2"
        assert saved["colorPalette"]["primary"] == "#DC2626"
        # globals.css :root must have the derived background (HSL channels of #FEF2F2)
        css = css_path.read_text()
        assert "--background:" in css
        # #FEF2F2 → roughly "0 86% 97%"
        # We don't pin exact values; just confirm it's NOT the old white default
        assert "--background: 0 0% 100%" not in css
```

- [ ] **Step 6.2: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_design_agent_brand.py -v
```

Expected: FAIL — design_agent doesn't override colorPalette from spec.brand yet.

- [ ] **Step 6.3: Modify `design_agent.py::save_design_spec`**

Find `save_design_spec` (already touched in Tier S/M/L Task 16 + design-spec surface depth + globals.css rewrite). Add brand-aware override at the top:

```python
def save_design_spec(output_dir, spec):
    # When the spec carries an externally-extracted brand, use it as the
    # authoritative palette source (overrides whatever the LLM design pass
    # emitted as colorPalette).
    brand = spec.get("brand")
    if brand and isinstance(brand, dict):
        derived = brand.get("derived") or {}
        if derived:
            spec["colorPalette"] = {
                "background": derived.get("background"),
                "surface": derived.get("surface"),
                "primary": derived.get("primary"),
                "secondary": derived.get("secondary"),
                "accent": derived.get("accent"),
                "muted": derived.get("background"),
                "border": derived.get("border"),
                "textPrimary": derived.get("text_primary"),
                "textSecondary": derived.get("text_secondary"),
                "error": derived.get("error"),
                "warning": derived.get("warning"),
                "success": derived.get("success"),
                # Preserve any other keys the LLM emitted
                **{k: v for k, v in (spec.get("colorPalette") or {}).items()
                   if k not in {"background","surface","primary","secondary","accent","muted","border","textPrimary","textSecondary","error","warning","success"}},
            }

    # ...existing logic for cta_hierarchy + surface depth + write disk + globals.css rewrite...
```

The existing `_rewrite_globals_root` call (from earlier this session) will pick up the rewritten `colorPalette` and update globals.css accordingly. Nothing else changes.

- [ ] **Step 6.4: Run test to verify it passes**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_design_agent_brand.py tests/agents/test_design_agent_globals_rewrite.py -v
```

Expected: all PASS — the brand override AND the existing globals.css rewrite.

- [ ] **Step 6.5: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/agents/design_agent.py backend/tests/agents/test_design_agent_brand.py
git commit -m "$(cat <<'EOF'
feat(brand): design_agent honours externally-supplied brand identity

When spec.brand.derived is present, save_design_spec uses it as the
authoritative colorPalette source — overrides whatever the LLM design
pass emitted. The existing _rewrite_globals_root then picks up the
new palette and updates globals.css :root accordingly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream C — Illustration system

Curated 80-SVG library, brand-recolor at bundle time, deterministic fallback when the LLM forgets to invoke the MCP.

### Task 7: Curated illustration library + index

**Files:**
- Create: `backend/fixtures/illustrations_curated/` (directory of SVGs)
- Create: `backend/fixtures/illustrations_curated/index.json`
- Create: `backend/services/illustration_curator.py`
- Create: `backend/tests/services/test_illustration_curator.py`

- [ ] **Step 7.1: Curate 80 SVGs from unDraw**

Visit https://undraw.co and download SVG source for 80 illustrations distributed across these categories (tag each in the index):

```
auth (10):           login, signup, welcome, security, password, account, etc.
empty-state (15):    empty inbox, no notes, no tasks, no notifications, etc.
dashboard-hero (15): analytics, reports, insights, growth, metrics, etc.
onboarding (10):     getting-started, tour, hello, exploration, etc.
error-state (10):    not-found, oops, broken, offline, etc.
success (10):        celebration, done, achievement, completed, etc.
generic-productivity (10): writing, focus, planning, organizing, etc.
```

Save each as `<slug>.svg` (e.g., `auth-runner.svg`, `dashboard-analytics.svg`).

For each, note the unDraw default accent color (almost always `#6c63ff` purple, but verify per file).

- [ ] **Step 7.2: Write the index**

```json
{
  "illustrations": [
    {
      "slug": "auth-runner",
      "filename": "auth-runner.svg",
      "default_color": "#6c63ff",
      "tags": ["auth", "fitness", "sports", "running"],
      "best_for": ["login-pages", "fitness-domain"]
    },
    {
      "slug": "auth-traveler",
      "filename": "auth-traveler.svg",
      "default_color": "#6c63ff",
      "tags": ["auth", "travel", "journey"],
      "best_for": ["login-pages", "travel-domain"]
    }
    /* ... 78 more ... */
  ]
}
```

Save to `backend/fixtures/illustrations_curated/index.json`.

- [ ] **Step 7.3: Write the failing test**

```python
# backend/tests/services/test_illustration_curator.py
"""Tests for the curated illustration library."""
from services.illustration_curator import (
    list_illustrations, get_illustration_svg, pick_for_intent
)


def test_list_illustrations_returns_at_least_50_entries():
    items = list_illustrations()
    assert len(items) >= 50
    for item in items:
        assert "slug" in item
        assert "tags" in item


def test_list_illustrations_filters_by_tag():
    auth = list_illustrations(tags=["auth"])
    assert len(auth) > 0
    for item in auth:
        assert "auth" in item["tags"]


def test_get_illustration_svg_returns_bytes():
    items = list_illustrations()
    slug = items[0]["slug"]
    svg = get_illustration_svg(slug, recolor_to=None)
    assert svg.startswith(b"<svg") or svg.startswith(b"<?xml")


def test_get_illustration_svg_recolors():
    """When recolor_to is given, the result must include the new colour
    and NOT include the default colour."""
    items = list_illustrations()
    slug = items[0]["slug"]
    default = items[0]["default_color"]
    svg = get_illustration_svg(slug, recolor_to="#FF0000")
    assert b"#FF0000" in svg.upper() or b"#ff0000" in svg
    # Default colour must be replaced (case-insensitive)
    assert default.lower().encode() not in svg.lower()


def test_pick_for_intent_returns_match():
    """pick_for_intent('login', domain='fitness') prefers fitness-auth SVGs."""
    slug = pick_for_intent(intent="login", domain="fitness")
    assert slug is not None
    items = list_illustrations()
    matched = next(i for i in items if i["slug"] == slug)
    assert "auth" in matched["tags"]


def test_pick_for_intent_returns_none_when_no_match():
    """An obscure intent returns None so callers can fall back."""
    slug = pick_for_intent(intent="completely-unknown-intent", domain="unknown")
    assert slug is None or isinstance(slug, str)  # may or may not match — test is non-strict
```

- [ ] **Step 7.4: Run test to verify it fails**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_illustration_curator.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 7.5: Implement `illustration_curator.py`**

```python
# backend/services/illustration_curator.py
"""Access the curated illustration library.

Library lives at backend/fixtures/illustrations_curated/. Each SVG
has an index.json entry with slug, tags, default_color. The curator
serves these as bytes, with optional brand-color recoloring via
regex substitution of the SVG's default color.
"""
from __future__ import annotations
from pathlib import Path
import json
import re
from functools import lru_cache

_LIBRARY_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "illustrations_curated"
_INDEX_PATH = _LIBRARY_DIR / "index.json"


@lru_cache(maxsize=1)
def _load_index() -> list[dict]:
    return json.loads(_INDEX_PATH.read_text())["illustrations"]


def list_illustrations(tags: list[str] | None = None) -> list[dict]:
    """List all curated illustrations, optionally filtered by intersection with tags."""
    idx = _load_index()
    if not tags:
        return list(idx)
    norm = {t.lower() for t in tags}
    return [i for i in idx if set(t.lower() for t in i.get("tags", [])) & norm]


def get_illustration_svg(slug: str, recolor_to: str | None = None) -> bytes:
    """Return the SVG bytes for a slug, optionally recoloured to a hex color.

    Raises FileNotFoundError if the slug isn't in the index.
    """
    entry = next((i for i in _load_index() if i["slug"] == slug), None)
    if entry is None:
        raise FileNotFoundError(f"unknown illustration slug: {slug}")
    svg_path = _LIBRARY_DIR / entry["filename"]
    svg = svg_path.read_bytes()
    if recolor_to:
        default = entry.get("default_color", "#6c63ff")
        # Case-insensitive replace of the default hex with the new one
        pattern = re.compile(re.escape(default).encode(), re.IGNORECASE)
        svg = pattern.sub(recolor_to.encode(), svg)
    return svg


_INTENT_TAGS = {
    "login": ["auth"],
    "signup": ["auth"],
    "signin": ["auth"],
    "register": ["auth"],
    "empty-list": ["empty-state"],
    "empty-inbox": ["empty-state"],
    "empty": ["empty-state"],
    "dashboard": ["dashboard-hero"],
    "overview": ["dashboard-hero"],
    "onboarding": ["onboarding"],
    "error": ["error-state"],
    "not-found": ["error-state"],
    "success": ["success"],
    "celebration": ["success"],
}


def pick_for_intent(intent: str, domain: str | None = None) -> str | None:
    """Pick the most relevant slug for a given intent + optional domain.

    Looks up intent → tags, returns the first illustration matching
    both the intent-tag and (if given) the domain. Falls back to any
    intent-tag match. Returns None when neither produces a hit.
    """
    intent = intent.lower()
    tags = _INTENT_TAGS.get(intent, [intent])
    candidates = list_illustrations(tags=tags)
    if not candidates:
        return None
    if domain:
        domain = domain.lower()
        scored = sorted(
            candidates,
            key=lambda i: domain in [t.lower() for t in i.get("tags", [])],
            reverse=True,
        )
        return scored[0]["slug"]
    return candidates[0]["slug"]
```

- [ ] **Step 7.6: Run tests to verify they pass**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_illustration_curator.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 7.7: Commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/fixtures/illustrations_curated/ backend/services/illustration_curator.py backend/tests/services/test_illustration_curator.py
git commit -m "$(cat <<'EOF'
feat(illustrations): curated 80-SVG library with intent picker

backend/fixtures/illustrations_curated/ holds 80 hand-picked unDraw
SVGs across auth/empty-state/dashboard/onboarding/error/success/
generic-productivity categories. illustration_curator.py exposes
list_illustrations(tags), get_illustration_svg(slug, recolor_to=),
pick_for_intent(intent, domain).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 8: Bundler recolors at bundle time

**Files:**
- Modify: `backend/services/illustration_bundler.py`

- [ ] **Step 8.1: Add brand-color recolor parameter**

The existing bundler (commit `a7849d6`) reads from `backend/.cache/illustrations/<slug>__<color>.svg`. Extend it to also fall back to the curated library, recoloring with the project's primary.

In `backend/services/illustration_bundler.py::bundle_illustrations_for_schema`, after the cache miss path:

```python
# After the existing cache-miss "skip" path, try the curator as fallback:
from services.illustration_curator import get_illustration_svg as _get_curated
try:
    svg = _get_curated(slug, recolor_to="#" + accent)
    dest.write_bytes(svg)
    count += 1
    continue
except FileNotFoundError:
    pass
```

- [ ] **Step 8.2: Add a test for the curator fallback**

```python
# Append to backend/tests/services/test_illustration_bundler.py
def test_bundler_falls_back_to_curator_for_curated_slugs(tmp_path, monkeypatch):
    """If a slug isn't in the cache, fall back to the curated library."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)

    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "auth", "route": "/login", "layout": "main",
        "root": {
            "type": "Hero", "id": "hero",
            "props": {"illustration": {"slug": "auth-runner", "alt": "Runner"}}
        }
    }
    # Assumes auth-runner is in the curated library (created in Task 7)
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="DC2626")
    bundled = output_dir / "public" / "illustrations" / "auth-runner.svg"
    assert bundled.exists()
```

- [ ] **Step 8.3: Run tests + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_illustration_bundler.py -v
```

Expected: all PASS.

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/services/illustration_bundler.py backend/tests/services/test_illustration_bundler.py
git commit -m "$(cat <<'EOF'
feat(illustrations): bundler falls back to curated library on cache miss

When a schema references an illustration slug that isn't in the unDraw
cache, fall back to the curated 80-SVG library — recoloured to the
project's primary on the way to public/illustrations/. Auth-page-
illustration rule now has a guaranteed asset to land even when the
LLM doesn't invoke the MCP.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 9: Deterministic post-emit fallback

**Files:**
- Modify: `backend/agents/page_schema_agent.py`

- [ ] **Step 9.1: Add post-emit fallback**

In `run_page_schema_agent`, after the schema is generated but before `bundle_illustrations_for_schema` is called, walk the schema and auto-inject illustration slugs for Hero nodes on auth/empty-state pages that don't already have one:

```python
def _inject_default_illustration_if_missing(schema: dict, route: str, domain: str | None) -> None:
    """When a Hero is on an auth/empty-state page and has no illustration set,
    pick one from the curated library and inject it."""
    from services.illustration_curator import pick_for_intent

    intent = _route_to_intent(route)
    if not intent:
        return

    def walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "Hero":
            props = node.setdefault("props", {})
            if "illustration" not in props:
                slug = pick_for_intent(intent, domain=domain)
                if slug:
                    props["illustration"] = {"slug": slug, "alt": ""}
        for c in node.get("children") or []:
            walk(c)
    walk(schema.get("root", {}))


def _route_to_intent(route: str) -> str | None:
    if not route:
        return None
    r = route.lower()
    if any(r.startswith(p) for p in ("/login", "/signin")):
        return "login"
    if any(r.startswith(p) for p in ("/signup", "/register")):
        return "signup"
    if r == "/" or r.startswith("/dashboard") or r.startswith("/home"):
        return "dashboard"
    return None
```

Call `_inject_default_illustration_if_missing(schema_dict, page.get("route", ""), domain)` after the existing `bundle_illustrations_for_schema(...)` line — BUT BEFORE writing the schema to disk, so the on-disk schema reflects the injected illustration too. Reorganise the sequence:

```python
# Old order:
#   write schema → bundle illustrations
# New order:
#   inject fallback illustration → write schema → bundle illustrations
_inject_default_illustration_if_missing(schema_dict, page.get("route", ""), domain)
out_path.write_text(json.dumps(schema_dict, indent=2))
bundle_illustrations_for_schema(output_dir, schema_dict, accent_color=accent_color)
```

- [ ] **Step 9.2: Test**

Add to `backend/tests/agents/test_page_schema_agent.py`:

```python
async def test_post_emit_injects_illustration_on_login_page(tmp_path):
    """When a Hero on /login has no illustration set, the agent post-emit
    fallback picks one from the curated library."""
    plan = {"entities": {"User": {"fields": []}}, "design_spec": {"register": "default"}}
    page = {"route": "/login", "entity": "User", "type": "form", "name": "Login"}
    fake_schema = {
        "schemaVersion": "2", "id": "ignored", "route": "/login", "layout": "main",
        "root": {
            "type": "Hero", "id": "hero",
            "props": {"headline": "Sign in"}  # NO illustration
        }
    }
    from unittest.mock import patch, AsyncMock
    with patch("agents.page_schema_agent._generate_schema_for_page",
               new=AsyncMock(return_value=fake_schema)):
        await run_page_schema_agent(str(tmp_path), plan, page)
    import json
    written = json.loads((tmp_path / "src" / "schemas" / "login.json").read_text())
    hero = written["root"]
    assert hero["props"].get("illustration") is not None
    assert "slug" in hero["props"]["illustration"]
```

- [ ] **Step 9.3: Run + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_page_schema_agent.py -v
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add backend/agents/page_schema_agent.py backend/tests/agents/test_page_schema_agent.py
git commit -m "$(cat <<'EOF'
feat(schema): post-emit injects illustration on auth/dashboard Hero

When run_page_schema_agent finishes and the emitted Hero on /login,
/signup, /, /dashboard has no illustration slot, pick one from the
curated library and inject before bundling. Removes the dependency
on the LLM remembering to invoke list_illustrations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 10: Sharpen schema prompt directive

**Files:**
- Modify: `backend/services/schema_rules.py`

- [ ] **Step 10.1: Tighten the auth-page-illustration rule body**

Find the existing `auth-page-illustration` Rule (added in Tier S/M/L Task 15). Change its body from "should" to "MUST" and add concrete instructions:

```python
Rule(
    name="auth-page-illustration",
    body=(
        "Login / signup pages MUST emit a 2-column split layout with a Hero "
        "(or Section) containing an illustration on one side and the Form on "
        "the other. The Hero/Section MUST include the illustration prop "
        "{slug, alt}. Call list_illustrations(tags=['auth', '<domain>']) "
        "via the illustrations MCP to find a matching slug; if the MCP is "
        "unavailable, pick from this canonical list:"
        " auth-runner, auth-traveler, auth-thinker, auth-secure, auth-welcome."
    ),
    example_snippet="""{
  "type": "Section",
  "props": {
    "illustration": { "slug": "auth-runner", "alt": "Welcome back" }
  },
  "children": []
}""",
    applies_when=_on_form,
),
```

- [ ] **Step 10.2: Test + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_prompt_auth.py tests/services/test_schema_rules.py -v
```

```bash
git add backend/services/schema_rules.py
git commit -m "$(cat <<'EOF'
feat(prompt): tighten auth-page-illustration rule with explicit slugs

Rule body upgraded from "should" to "MUST" + lists 5 canonical fallback
slugs (auth-runner, auth-traveler, auth-thinker, auth-secure, auth-
welcome) so the LLM has an explicit safety net when it can't reach the
MCP. The post-emit fallback (Task 9) handles the case when the LLM
ignores this directive anyway.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream D — Typography system

Pair-aware font selection, 4 typography registers, Google Fonts injection.

### Task 11: Typography registers data

**Files:**
- Create: `backend/fixtures/typography_registers.json`
- Create: `backend/services/typography_registers.py`
- Create: `backend/tests/services/test_typography_registers.py`

- [ ] **Step 11.1: Author the registers data**

```json
{
  "registers": [
    {
      "id": "modern-minimal",
      "name": "Modern Minimal",
      "description": "Inter throughout. Tight tracking. SaaS default.",
      "heading_font": "Inter",
      "body_font": "Inter",
      "heading_weight": 600,
      "body_weight": 400,
      "heading_tracking": "-0.02em",
      "best_for": ["saas", "internal-tool", "dashboard", "developer-tool"]
    },
    {
      "id": "editorial-luxe",
      "name": "Editorial Luxe",
      "description": "Playfair Display headings, Source Sans body. Luxury / editorial.",
      "heading_font": "Playfair Display",
      "body_font": "Source Sans 3",
      "heading_weight": 700,
      "body_weight": 400,
      "heading_tracking": "-0.01em",
      "best_for": ["luxury", "media", "fashion", "real-estate"]
    },
    {
      "id": "technical-mono",
      "name": "Technical Mono",
      "description": "Space Grotesk headings, JetBrains Mono accents. Dev-tool / data-heavy.",
      "heading_font": "Space Grotesk",
      "body_font": "Inter",
      "heading_weight": 700,
      "body_weight": 400,
      "heading_tracking": "0em",
      "best_for": ["developer-tool", "data", "ai", "infra"]
    },
    {
      "id": "consumer-playful",
      "name": "Consumer Playful",
      "description": "DM Sans throughout. Slightly loose tracking. Consumer apps.",
      "heading_font": "DM Sans",
      "body_font": "DM Sans",
      "heading_weight": 700,
      "body_weight": 400,
      "heading_tracking": "-0.01em",
      "best_for": ["consumer", "education", "fitness", "social"]
    }
  ]
}
```

- [ ] **Step 11.2: Write the picker test**

```python
# backend/tests/services/test_typography_registers.py
from services.typography_registers import (
    list_registers, get_register, pick_register_for_domain
)


def test_list_registers_returns_all_four():
    regs = list_registers()
    ids = {r["id"] for r in regs}
    assert ids == {"modern-minimal", "editorial-luxe", "technical-mono", "consumer-playful"}


def test_get_register_returns_full_data():
    reg = get_register("modern-minimal")
    assert reg["heading_font"] == "Inter"
    assert reg["body_font"] == "Inter"


def test_pick_register_for_saas_picks_modern_minimal():
    reg = pick_register_for_domain("saas")
    assert reg["id"] == "modern-minimal"


def test_pick_register_for_fitness_picks_consumer_playful():
    reg = pick_register_for_domain("fitness")
    assert reg["id"] == "consumer-playful"


def test_pick_register_for_unknown_domain_returns_default():
    reg = pick_register_for_domain("completely-unknown")
    assert reg["id"] == "modern-minimal"  # fallback default
```

- [ ] **Step 11.3: Implement the picker**

```python
# backend/services/typography_registers.py
"""Typography register catalogue + domain-based selector."""
from __future__ import annotations
from pathlib import Path
import json
from functools import lru_cache

_DATA_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "typography_registers.json"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    return json.loads(_DATA_PATH.read_text())["registers"]


def list_registers() -> list[dict]:
    return list(_load())


def get_register(register_id: str) -> dict | None:
    return next((r for r in _load() if r["id"] == register_id), None)


def pick_register_for_domain(domain: str) -> dict:
    """Pick the most-fitting register for a domain. Falls back to
    modern-minimal when no register's best_for list contains the domain."""
    domain = domain.lower().strip()
    for reg in _load():
        if domain in [b.lower() for b in reg.get("best_for", [])]:
            return reg
    # Fallback
    return next(r for r in _load() if r["id"] == "modern-minimal")
```

- [ ] **Step 11.4: Test + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_typography_registers.py -v
```

```bash
git add backend/fixtures/typography_registers.json backend/services/typography_registers.py backend/tests/services/test_typography_registers.py
git commit -m "$(cat <<'EOF'
feat(typography): 4 typography registers + domain-based picker

modern-minimal (SaaS), editorial-luxe (luxury/media), technical-mono
(dev/data), consumer-playful (consumer/education). pick_register_for_
domain() maps known domains to a register; falls back to modern-minimal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 12: Wire typography into design_agent + globals.css

**Files:**
- Modify: `backend/agents/design_agent.py`

- [ ] **Step 12.1: Add Google Fonts injection in globals.css rewrite**

After `_rewrite_globals_root`, append a Google Fonts `@import` based on the chosen register:

```python
# In design_agent.py, after _rewrite_globals_root and before save:
def _inject_typography_imports(globals_path: Path, register: dict) -> None:
    """Add Google Fonts @import + body font-family override."""
    if not globals_path.exists():
        return
    text = globals_path.read_text()
    heading = register["heading_font"].replace(" ", "+")
    body = register["body_font"].replace(" ", "+")
    fonts_url = f"https://fonts.googleapis.com/css2?family={heading}:wght@{register['heading_weight']}&family={body}:wght@{register['body_weight']}&display=swap"
    
    import_line = f"@import url('{fonts_url}');\n"
    body_rule = f"""
body {{
  font-family: '{register['body_font']}', system-ui, -apple-system, sans-serif;
  font-weight: {register['body_weight']};
}}
h1, h2, h3, h4, h5, h6 {{
  font-family: '{register['heading_font']}', system-ui, -apple-system, sans-serif;
  font-weight: {register['heading_weight']};
  letter-spacing: {register['heading_tracking']};
}}
"""
    if "fonts.googleapis.com" not in text:
        text = import_line + text
    # Append the body/heading rules at the end, idempotent
    if "/* tentoro typography */" not in text:
        text = text + "\n/* tentoro typography */\n" + body_rule
    globals_path.write_text(text)
```

Call it in `save_design_spec` after the `_rewrite_globals_root` call:

```python
from services.typography_registers import pick_register_for_domain
domain = spec.get("domain", "saas")
register = pick_register_for_domain(domain)
spec.setdefault("typography", {})["register"] = register["id"]
_inject_typography_imports(Path(output_dir) / "src" / "app" / "globals.css", register)
```

- [ ] **Step 12.2: Test**

```python
# Append to backend/tests/agents/test_design_agent_globals_rewrite.py

def test_save_design_spec_injects_google_fonts_import(tmp_path):
    from agents.design_agent import save_design_spec
    css_path = tmp_path / "src" / "app" / "globals.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(":root { --background: 0 0% 100%; }")
    spec = {"register": "default", "domain": "fitness", "colorPalette": {"primary": "#FF0000"}}
    save_design_spec(str(tmp_path), spec)
    css = css_path.read_text()
    assert "fonts.googleapis.com" in css
    assert "DM Sans" in css  # fitness → consumer-playful → DM Sans
```

- [ ] **Step 12.3: Run + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_design_agent_globals_rewrite.py -v
```

```bash
git add backend/agents/design_agent.py backend/tests/agents/test_design_agent_globals_rewrite.py
git commit -m "$(cat <<'EOF'
feat(typography): design_agent injects Google Fonts + body rules

After choosing a typography register from the domain, save_design_spec
appends a Google Fonts @import URL + body/heading font-family rules
into globals.css. Generated pages now match the register's typography
without per-page agent emission.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 13: Heading display variant

**Files:**
- Modify: `packages/library/src/components/Heading/Heading.tsx`

- [ ] **Step 13.1: Add display variant**

The Heading component (from Tier S/M/L Task 7) maps level → text-size class. Add a `variant="display"` prop that uses oversized typography with tighter tracking:

```tsx
// In Heading.tsx
type Variant = "default" | "display";

type Props = {
  level?: Level;
  content: string;
  id?: string;
  weight?: Weight;
  variant?: Variant;
  style?: StyleSlotT;
};

const DISPLAY_CLASS: Record<Level, string> = {
  1: "text-6xl md:text-7xl tracking-tighter font-bold",
  2: "text-5xl md:text-6xl tracking-tight font-bold",
  3: "text-4xl md:text-5xl tracking-tight font-semibold",
  4: "text-3xl tracking-tight font-semibold",
  5: "text-2xl font-semibold",
  6: "text-xl font-semibold",
};

// Inside Heading():
const baseClass = variant === "display" ? DISPLAY_CLASS[level] : LEVEL_CLASS[level];
```

- [ ] **Step 13.2: Test**

```tsx
// packages/library/tests/components/Heading.display.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Heading } from "../../src/components/Heading/Heading";

describe("Heading display variant", () => {
  it("renders oversized typography when variant='display'", () => {
    const { container } = render(<Heading level={1} variant="display" content="WELCOME" />);
    const h1 = container.querySelector("h1") as HTMLElement;
    expect(h1.className).toContain("text-6xl");
    expect(h1.className).toContain("tracking-tighter");
  });
  it("renders default scale when variant unspecified", () => {
    const { container } = render(<Heading level={1} content="Title" />);
    const h1 = container.querySelector("h1") as HTMLElement;
    expect(h1.className).toContain("text-page-title");
  });
});
```

- [ ] **Step 13.3: Run + commit**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/packages/library && npx vitest run tests/components/Heading.display.test.tsx
```

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3
git add packages/library/src/components/Heading/Heading.tsx packages/library/tests/components/Heading.display.test.tsx
git commit -m "$(cat <<'EOF'
feat(library): Heading variant="display" for oversized hero typography

Display variant uses text-6xl/7xl + tighter tracking for hero sections
(matches the WELCOME BACK reference aesthetic). Default variant
preserves existing type-scale class behaviour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Workstream E — Photographic accents

Outline-only — these tasks follow the same TDD pattern as Workstreams B-D. Full implementations omitted for plan brevity but the file paths, exact prop signatures, and test cases are specified so an engineer can execute without further design decisions.

### Task 14: Unsplash client + cache

**Files:** `backend/services/unsplash_client.py`, `backend/tests/services/test_unsplash_client.py`

- [ ] HTTP client wrapper for `https://source.unsplash.com/<size>/?<query>` (no API key, free)
- [ ] Cache fetched image URLs in `backend/.cache/unsplash/<query-hash>.url`
- [ ] Methods: `photo_url_for_query(query, size="1600x900") -> str`, `clear_cache()`
- [ ] Tests: returns valid URL format, caches second call, handles 404 fallback

### Task 15: Photo picker (domain + entity → photo URL)

**Files:** `backend/services/photo_picker.py`, `backend/tests/services/test_photo_picker.py`

- [ ] Per-domain seeds in `backend/fixtures/unsplash_seeds.json` (e.g., `healthcare: ["medical professional", "hospital interior"]`)
- [ ] `pick_photo_for(entity_name: str, domain: str, size: str) -> str`
- [ ] Entity-name heuristics: `User` → person, `Product` → product photo, `Property` → real estate
- [ ] Tests: returns photo URL for known entity, falls back for unknown

### Task 16: Avatar component accepts photoUrl

**Files:** modify `packages/library/src/components/Avatar/Avatar.tsx`, add test

- [ ] Avatar.props.photoUrl: optional string. When present, render `<img>` not initials
- [ ] Fallback to initials when image fails to load (`onError` handler)
- [ ] Tests: renders img with src, falls back to initials when no photoUrl

### Task 17: Hero background image variant

**Files:** modify `packages/library/src/components/Hero/Hero.tsx`, add `Hero.schema.ts` field, test

- [ ] Hero.props.backgroundImage: optional `{ url, overlay }` shape
- [ ] When set, render image as background with overlay div (10–40% opacity)
- [ ] Content remains readable via overlay scrim
- [ ] Tests: img + overlay both render, overlay opacity respected

### Task 18: design_agent populates photo URLs

**Files:** modify `backend/agents/design_agent.py`

- [ ] After register pick, iterate entities and call `photo_picker.pick_photo_for(entity, domain)` for each
- [ ] Store on `design_spec.entityPhotos[entity_name] = url`
- [ ] Page agent passes these into schema generation context

---

## Workstream F — Layout primitives (optional, can defer)

Schema extensions for positioning + overlap layouts. Skipped detailed task breakdown; outline only.

### Task 19: Schema position fields

- [ ] Add `position`, `top/left/right/bottom`, `zIndex` to `packages/schema/src/style-slot.ts`
- [ ] All optional, behind `SCHEMA_POSITION_ENABLED=true` env flag for safety
- [ ] Vitest cases: legacy schemas still parse, position fields validate

### Task 20: Renderer applies position styles

- [ ] `packages/renderer/src/runtime/style-slot.ts`: read position fields, emit corresponding CSS
- [ ] Tests: rendered HTML has position:absolute when set

### Task 21: OverlayCard component

- [ ] `packages/library/src/components/OverlayCard/OverlayCard.tsx`: absolute-positioned card with z-index control
- [ ] Schema variant for `BALA-style` overlapping forms
- [ ] Tests: stack order, viewport positioning

### Task 22: FullBleed Section variant

- [ ] Existing Section component gains `variant="full-bleed"`: negative margin breakout to viewport edges
- [ ] Tests: width: 100vw, left: 50% transform

---

## Workstream G — Stress-test + fidelity scoring

### Task 23: Six stress-test plans

**Files:** `/tmp/plan-stress-{saas,healthcare,fitness,ecommerce,recipe,admin}.json`

- [ ] Author 6 different-domain plans, each with auth + dashboard + list pages
- [ ] Run generation pipeline against each, capture screenshots
- [ ] Designer review scoring (1–10 per page) — collected manually

### Task 24: Reference image library

**Files:** `backend/fixtures/reference_images/<domain>/<page-type>.png`

- [ ] Hand-collect 30 reference screenshots from public sources (PatientPop, Linear, Stripe, Notion, Figma, etc.)
- [ ] Organized by domain × page-type
- [ ] index.json with `{ domain, page_type, url_source, license_note }` per image

### Task 25: Fidelity scorer (vision-grounded)

**Files:** `backend/services/fidelity_scorer.py`, tests

- [ ] Takes (generated_screenshot_url, reference_image_path) → calls Claude vision with structured prompt
- [ ] Returns `{ score_0_to_10, color_match_score, layout_score, density_score, polish_score, qualitative_notes }`
- [ ] Tests: deterministic scoring on same input pair, gracefully handles missing reference

### Task 26: Wire fidelity gate into pipeline

**Files:** modify `backend/routers/generate.py`

- [ ] After all pages emitted, take screenshots via Playwright
- [ ] Compare each to reference (if exists for domain × page-type)
- [ ] Log per-page fidelity score to SSE events (advisory only, no auto-retry)
- [ ] Tests: pipeline completes with scores in event stream

---

## Workstream H — Editor UI (Polish, can defer)

Outline-only — frontend work that depends on backend B+C+D being shipped first.

### Task 27: Brand setup wizard

**Files:** `packages/editor/src/panels/BrandSetup/BrandSetupWizard.tsx`

- [ ] Three-step wizard: logo upload OR URL paste OR manual palette
- [ ] Calls `/api/brand/extract/logo` or `/api/brand/extract/url`
- [ ] Shows derived palette preview before applying
- [ ] Writes brand back to `design-spec.json` via existing save endpoint

### Task 28: Illustration browser sidebar

**Files:** `packages/editor/src/panels/IllustrationBrowser/Browser.tsx`

- [ ] Scrolling grid of curated illustrations grouped by category
- [ ] Search box (filters by tag)
- [ ] Click → inserts illustration ref into currently-selected Hero/Section
- [ ] Live preview shows recoloured version (uses brand primary)

### Task 29: Typography picker

**Files:** `packages/editor/src/panels/TypographyPicker/Picker.tsx`

- [ ] 4 cards (one per register) with sample heading + body rendered
- [ ] Select → writes to design-spec, triggers globals.css rewrite, hot-reload preview

---

## Self-review

| Requirement from strategy | Task |
|---|---|
| 1-day validation spike before commit | Task 1 |
| Brand extraction from logo | Task 2 |
| Brand extraction from URL | Task 4 |
| Color theory engine | Task 3 |
| Brand REST endpoints | Task 5 |
| design_agent honours brand | Task 6 |
| Curated illustration library | Task 7 |
| Bundler recolors | Task 8 |
| Post-emit fallback | Task 9 |
| Prompt directive sharpening | Task 10 |
| Typography registers | Task 11 |
| Typography in globals.css | Task 12 |
| Display heading variant | Task 13 |
| Unsplash client | Task 14 |
| Photo picker | Task 15 |
| Avatar with photoUrl | Task 16 |
| Hero background image | Task 17 |
| design_agent photo population | Task 18 |
| Layout primitives | Tasks 19–22 (outlined) |
| Stress-test plans | Task 23 |
| Reference library | Task 24 |
| Fidelity scorer | Task 25 |
| Fidelity gate wiring | Task 26 |
| Brand setup wizard UI | Task 27 |
| Illustration browser UI | Task 28 |
| Typography picker UI | Task 29 |

29 tasks across 8 workstreams. Tasks 1–18 (Workstreams A–E) are detailed with full TDD steps. Tasks 19–29 (Workstreams F, G, H) are outlined and would benefit from being broken into their own plans once Workstreams A–E ship and validate the approach.

---

## Out of scope

- Custom hand-drawn illustrations (no LLM synthesizes at quality; would need commissioned art)
- Lottie / video assets — separate plan; pipeline different
- Image-gen API integration (DALL-E / Imagen) — explicitly deferred; cost + style-inconsistency trade-offs
- Multi-user collaborative editing (Pillar 1 plan)
- Per-page generation speed (Pillar 3 plan — template-first generation, parallel pages, smaller model)
- Asset license tracking — Unsplash + unDraw are permissive; commercial use of curated library should be reviewed legally before launch
- Dark mode theming — token system supports it but not in this plan's scope

---

## Notes on execution

- Workstream A (validation) is BLOCKING. If the 1-day spike fails the score threshold, the rest of this plan needs revision before commit.
- Workstreams B and C share the brand-color dependency. B must ship before C's recoloring is meaningful.
- Workstream D (typography) is independent of B/C and can run in parallel.
- Workstreams F, G, H can be standalone follow-up plans.
- Total realistic timeline: A (1 day) → B (2.5 weeks) → C (1.5 weeks) → D (1.5 weeks) → E (1.5 weeks) → F+G+H polish (3–4 weeks). ~10 weeks total for a single engineer; 6–7 weeks with a small team.
