"""Compositional design engine — a distinct visual language per generated app.

A fixed list of skins caps out: ship 10 and the 30th app repeats one. So the
language is COMPOSED at generation time instead — one value drawn from each
independent axis under a taste model that keeps the result coherent.

Axes (values implemented as CSS emitters):

    navShape        20   where/how navigation lives
    activeMark      12   how the selected destination is marked
    headerStyle     11   the page-header block (H1-left/buttons-right is ONE
                         of eleven, not the universal default)
    kpiAnatomy      12   how headline numbers are presented
    cardTreatment    9   surface enclosure
    radiusRegime     6   corner language
    typeClass        8   family + case + weight conventions
    density          5   gutter / gap / padding rhythm

Raw permutations run to the hundreds of millions; structural rules (a
bottom dock cannot carry a left edge-bar; a floating rounded rail cannot
full-bleed-invert) and taste rules (coherence tags, forbidden pairs, the
one-loud cap) prune that to a large but *always coherent* subspace.

Determinism: every draw is seeded from the project id, so the same project
always composes the same language.
"""
from __future__ import annotations

import hashlib

# Shared adjective vocabulary. A composition must share >= 2 tags across its
# nav / kpi / card / type picks, and must not mix antonyms.
TAGS = ("sharp", "soft", "technical", "editorial", "playful",
        "luxe", "organic", "dense", "airy")
_ANTONYMS = (("sharp", "organic"), ("dense", "airy"), ("luxe", "playful"))


# ── AXIS: navigation shape ────────────────────────────────────────────────
# `chrome` maps to a shell branch the app layout already implements.
NAV_SHAPES: dict[str, dict] = {
    "rail-flush":     {"w": 248, "inset": 0,  "chrome": "standard-rail", "side": "left",
                       "itemH": 32, "pad": 10, "radius": 6, "icons": True,
                       "labelSize": 13.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("technical", "dense", "sharp")},
    "rail-float":     {"w": 236, "inset": 12, "chrome": "floating-rail", "side": "left",
                       "itemH": 34, "pad": 10, "radius": 8, "icons": True,
                       "labelSize": 13.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("soft", "airy", "luxe")},
    "rail-icon":      {"w": 60,  "inset": 0,  "chrome": "icon-rail", "side": "left",
                       "itemH": 40, "pad": 0, "radius": 10, "icons": True,
                       "labelSize": 0, "labelWeight": 500, "labelCase": "none",
                       "tags": ("dense", "technical", "sharp")},
    "rail-sectioned": {"w": 280, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 36, "pad": 10, "radius": 7, "icons": True,
                       "labelSize": 14, "labelWeight": 500, "labelCase": "none",
                       "tags": ("editorial", "dense", "sharp")},
    "rail-right":     {"w": 232, "inset": 0,  "chrome": "right-rail", "side": "right",
                       "itemH": 34, "pad": 10, "radius": 7, "icons": True,
                       "labelSize": 13.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("sharp", "editorial", "technical")},
    "bar-top":        {"w": 0,   "inset": 0,  "chrome": "topbar", "side": "top",
                       "itemH": 32, "pad": 12, "radius": 6, "icons": False,
                       "labelSize": 13.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("airy", "sharp", "technical")},
    "bar-centered":   {"w": 0,   "inset": 0,  "chrome": "topbar", "side": "top",
                       "itemH": 34, "pad": 14, "radius": 8, "icons": False,
                       "labelSize": 14, "labelWeight": 500, "labelCase": "none",
                       "tags": ("luxe", "airy", "soft")},
    "dock-bottom":    {"w": 0,   "inset": 0,  "chrome": "dock", "side": "bottom",
                       "itemH": 56, "pad": 0, "radius": 0, "icons": True,
                       "labelSize": 10, "labelWeight": 600, "labelCase": "none",
                       "tags": ("soft", "playful", "airy")},
    "rail-cells":     {"w": 240, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 44, "pad": 14, "radius": 0, "icons": True,
                       "labelSize": 12.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("technical", "sharp", "dense")},
    "rail-index":     {"w": 244, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 34, "pad": 0, "radius": 0, "icons": False,
                       "labelSize": 13.5, "labelWeight": 450, "labelCase": "none",
                       "tags": ("editorial", "technical", "airy")},
    "rail-tree":      {"w": 252, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 28, "pad": 8, "radius": 5, "icons": True,
                       "labelSize": 13, "labelWeight": 450, "labelCase": "none",
                       "tags": ("dense", "soft", "technical")},
    "rail-blocks":    {"w": 252, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 48, "pad": 18, "radius": 0, "icons": True,
                       "labelSize": 14, "labelWeight": 600, "labelCase": "none",
                       "loud": True, "tags": ("playful", "editorial", "organic")},
    "rail-hang":      {"w": 240, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 30, "pad": 0, "radius": 0, "icons": False,
                       "labelSize": 13.5, "labelWeight": 450, "labelCase": "none",
                       "tags": ("editorial", "airy", "luxe")},
    "rail-bleed":     {"w": 232, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 38, "pad": 18, "radius": 0, "icons": True,
                       "labelSize": 13.5, "labelWeight": 500, "labelCase": "none",
                       "tags": ("sharp", "dense", "technical")},
    "rail-text":      {"w": 200, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 26, "pad": 0, "radius": 0, "icons": False,
                       "labelSize": 15, "labelWeight": 450, "labelCase": "none",
                       "tags": ("airy", "luxe", "editorial")},
    "rail-sidecar":   {"w": 228, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 32, "pad": 10, "radius": 8, "icons": True,
                       "labelSize": 13, "labelWeight": 500, "labelCase": "none",
                       "tags": ("soft", "airy", "technical")},
    "rail-caps":      {"w": 256, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 40, "pad": 16, "radius": 0, "icons": False,
                       "labelSize": 12, "labelWeight": 500, "labelCase": "uppercase",
                       "labelTrack": ".16em", "tags": ("luxe", "editorial", "sharp")},
    "rail-mono":      {"w": 216, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 26, "pad": 10, "radius": 0, "icons": False,
                       "labelSize": 12, "labelWeight": 500, "labelCase": "uppercase",
                       "labelTrack": ".02em", "mono": True,
                       "tags": ("technical", "dense", "sharp")},
    "rail-discs":     {"w": 244, "inset": 0,  "chrome": "wide-rail", "side": "left",
                       "itemH": 44, "pad": 12, "radius": 999, "icons": True,
                       "iconDisc": True, "labelSize": 14, "labelWeight": 500,
                       "labelCase": "none", "tags": ("soft", "organic", "playful")},
    "rail-glass":     {"w": 236, "inset": 14, "chrome": "floating-rail", "side": "left",
                       "itemH": 42, "pad": 14, "radius": 12, "icons": True,
                       "labelSize": 14, "labelWeight": 500, "labelCase": "none",
                       "glass": True, "loud": True, "tags": ("luxe", "soft", "airy")},
}

# ── AXIS: active-state indicator ──────────────────────────────────────────
ACTIVE_MARKS: dict[str, dict] = {
    "left-bar":     {"tags": ("sharp", "technical", "dense")},
    "right-bar":    {"tags": ("sharp", "technical", "editorial")},
    "invert":       {"needsFlush": True, "tags": ("sharp", "dense", "editorial")},
    "pill":         {"tags": ("soft", "playful", "airy")},
    "tint":         {"tags": ("soft", "technical", "dense")},
    "underline":    {"horizontalOnly": True, "tags": ("sharp", "editorial", "technical")},
    "overline":     {"horizontalOnly": True, "tags": ("sharp", "technical", "playful")},
    "chevron":      {"tags": ("playful", "technical", "editorial")},
    "dot":          {"tags": ("airy", "soft", "editorial")},
    "raised":       {"tags": ("soft", "luxe", "airy")},
    "border-box":   {"tags": ("technical", "sharp", "dense")},
    "grad-hair":    {"tags": ("luxe", "airy", "editorial")},
}

# ── AXIS: page-header treatment ───────────────────────────────────────────
# Nine of eleven relocate the action buttons away from "top right", which is
# itself one of the loudest same-generator signals.
HEADER_STYLES: dict[str, dict] = {
    "plain":        {"actions": "right",   "tags": ("technical", "dense", "sharp")},
    "eyebrow-num":  {"actions": "below",   "tags": ("editorial", "technical", "airy")},
    "rule-under":   {"actions": "right",   "tags": ("sharp", "editorial", "dense")},
    "masthead":     {"actions": "toolbar", "tags": ("editorial", "sharp", "luxe")},
    "tinted-band":  {"actions": "right",   "loud": True, "tags": ("soft", "playful", "airy")},
    "accent-tab":   {"actions": "below",   "loud": True, "tags": ("playful", "sharp", "editorial")},
    "centered":     {"actions": "center",  "tags": ("luxe", "airy", "editorial")},
    "ghost-num":    {"actions": "below",   "loud": True, "tags": ("playful", "editorial", "airy")},
    "breadcrumb":   {"actions": "right",   "tags": ("technical", "dense", "sharp")},
    "inline-stats": {"actions": "right",   "tags": ("dense", "technical", "sharp")},
    "kicker-rule":  {"actions": "right",   "tags": ("editorial", "luxe", "airy")},
}

# ── AXIS: KPI anatomy ─────────────────────────────────────────────────────
KPI_ANATOMY: dict[str, dict] = {
    "boxless-hairline": {"cols": "repeat(4, 1fr)", "gap": 0,  "tags": ("sharp", "editorial", "airy")},
    "shared-strip":     {"cols": "repeat(6, 1fr)", "gap": 0,  "tags": ("dense", "technical", "sharp")},
    "compartment":      {"cols": "repeat(4, 1fr)", "gap": 16, "tags": ("sharp", "playful")},
    "plaque-chamfer":   {"cols": "repeat(3, 1fr)", "gap": 24, "loud": True, "tags": ("luxe", "editorial", "sharp")},
    "tint-block":       {"cols": "repeat(4, 1fr)", "gap": 14, "loud": True, "tags": ("playful", "soft")},
    "bento-mixed":      {"cols": "repeat(4, 1fr)", "gap": 12, "tags": ("soft", "playful", "dense")},
    "ledger-leaders":   {"cols": "repeat(2, 1fr)", "gap": 0,  "tags": ("editorial", "luxe")},
    "hero-asymmetric":  {"cols": "2fr 1fr 1fr 1fr", "gap": 24, "tags": ("airy", "organic", "soft")},
    "capsule-soft":     {"cols": "repeat(2, 1fr)", "gap": 20, "tags": ("soft", "organic")},
    "glass-ribbon":     {"cols": "repeat(5, 1fr)", "gap": 0,  "loud": True, "tags": ("luxe", "soft")},
    "ruled-band":       {"cols": "repeat(4, 1fr)", "gap": 32, "tags": ("editorial", "airy", "sharp")},
    "stat-column":      {"cols": "repeat(2, 1fr)", "gap": 12, "tags": ("dense", "technical")},
}

# ── AXIS: card treatment ──────────────────────────────────────────────────
CARD_TREATMENTS: dict[str, dict] = {
    "none":        {"border": 0, "shadow": "none", "fill": "none",    "tags": ("airy", "editorial", "organic")},
    "hairline":    {"border": 1, "shadow": "none", "fill": "surface", "tags": ("sharp", "technical")},
    "thick":       {"border": 3, "shadow": "none", "fill": "surface", "tags": ("sharp", "playful")},
    "hard-offset": {"border": 3, "shadow": "offset", "fill": "surface", "loud": True, "tags": ("sharp", "playful")},
    "soft-shadow": {"border": 0, "shadow": "soft",  "fill": "surface", "tags": ("soft", "organic")},
    "layered":     {"border": 0, "shadow": "layered", "fill": "surface", "tags": ("luxe", "soft")},
    "tint-fill":   {"border": 0, "shadow": "hairline", "fill": "tint", "tags": ("playful", "soft")},
    "glass":       {"border": 1, "shadow": "glow", "fill": "glass", "loud": True, "tags": ("luxe", "soft")},
    "rules-only":  {"border": 0, "shadow": "none", "fill": "none", "topRule": True,
                    "tags": ("editorial", "sharp", "luxe")},
    # Depth by tone rather than shadow — the treatment Linear, Raycast,
    # Vercel, Datadog, PostHog, Notion, Ramp, Airtable and Mercury all use
    # (every one of them forbids shadows on cards; shadows are for popovers).
    "surface-step": {"border": 1, "shadow": "none", "fill": "step",
                     "tags": ("technical", "dense", "luxe")},
}

RADIUS_REGIMES: dict[str, dict] = {
    "square":   {"r": 0,  "tags": ("sharp", "technical", "editorial")},
    "hairline": {"r": 2,  "tags": ("sharp", "editorial")},
    "soft":     {"r": 8,  "tags": ("technical", "soft")},
    "rounded":  {"r": 14, "tags": ("soft", "playful")},
    "pillowy":  {"r": 22, "tags": ("soft", "organic", "playful")},
    "chamfer":  {"r": 0, "chamfer": True, "loud": True, "tags": ("luxe", "sharp")},
    # `corner-shape` is Chrome/Edge 139+ and degrades to the plain radius
    # everywhere else, so these ship safely as progressive enhancement.
    "squircle": {"r": 18, "corner": "squircle", "tags": ("soft", "luxe")},
    "bevel":    {"r": 12, "corner": "bevel", "loud": True, "tags": ("sharp", "technical")},
    "scoop":    {"r": 16, "corner": "scoop", "loud": True, "tags": ("playful", "organic")},
}

# ── AXIS: type class (families verified present on Google Fonts) ──────────
TYPE_CLASSES: dict[str, dict] = {
    "grotesque":     {"display": "'Inter', system-ui, sans-serif", "num": None,
                      "h1": (32, 600, "none", "-0.025em"), "labelCase": "uppercase",
                      "labelTrack": ".12em", "tags": ("sharp", "technical")},
    "humanist":      {"display": "'Source Sans 3', system-ui, sans-serif", "num": None,
                      "h1": (28, 500, "none", "-0.012em"), "labelCase": "none",
                      "labelTrack": "0", "tags": ("soft", "organic")},
    "geometric":     {"display": "'Poppins', system-ui, sans-serif",
                      # Poppins measures a 31.5% digit-width spread and ships
                      # no `tnum` — numerals can NEVER align in a column.
                      # Chivo is geometric-adjacent with uniform digits.
                      "num": "'Chivo', system-ui, sans-serif",
                      "h1": (30, 600, "none", "-0.02em"), "labelCase": "none",
                      "labelTrack": ".02em", "tags": ("playful", "soft")},
    "rounded":       {"display": "'Nunito', system-ui, sans-serif", "num": None,
                      "h1": (28, 700, "none", "-0.015em"), "labelCase": "none",
                      "labelTrack": "0", "tags": ("soft", "playful", "organic")},
    "mono":          {"display": "'JetBrains Mono', ui-monospace, monospace",
                      "num": "'JetBrains Mono', ui-monospace, monospace",
                      "h1": (16, 500, "uppercase", ".08em"), "labelCase": "uppercase",
                      "labelTrack": ".06em", "tags": ("technical", "dense", "sharp")},
    "serif-display": {"display": "'Fraunces', Georgia, serif",
                      # Fraunces ships proportional digits and no `tnum`, so a
                      # ruled ledger column will NOT align. Newsreader has
                      # uniform-width digits (verified from the font binary).
                      "num": "'Newsreader', Georgia, serif",
                      "h1": (30, 400, "none", "-0.01em"), "labelCase": "uppercase",
                      "labelTrack": ".1em", "tags": ("editorial", "luxe")},
    "condensed":     {"display": "'Archivo', 'Oswald', sans-serif",
                      # Oswald has no `tnum`; Archivo Narrow has uniform
                      # digits by default (verified).
                      "num": "'Archivo Narrow', 'Archivo', sans-serif",
                      "h1": (26, 600, "uppercase", ".16em"), "labelCase": "uppercase",
                      "labelTrack": ".18em", "tags": ("luxe", "sharp", "editorial")},
    "slab":          {"display": "'Zilla Slab', Georgia, serif",
                      "num": "'Zilla Slab', Georgia, serif",
                      "h1": (30, 700, "none", "-0.01em"), "labelCase": "uppercase",
                      "labelTrack": ".08em", "tags": ("sharp", "editorial", "dense")},
}

DENSITIES: dict[str, dict] = {
    "dense":     {"gutter": 16, "cardGap": 8,  "cardPad": 12, "sectionGap": 12, "tags": ("dense", "technical")},
    "tight":     {"gutter": 28, "cardGap": 14, "cardPad": 18, "sectionGap": 24, "tags": ("dense", "sharp")},
    "standard":  {"gutter": 40, "cardGap": 20, "cardPad": 22, "sectionGap": 32, "tags": ("soft", "technical")},
    "airy":      {"gutter": 56, "cardGap": 28, "cardPad": 28, "sectionGap": 44, "tags": ("airy", "organic")},
    "editorial": {"gutter": 72, "cardGap": 32, "cardPad": 0,  "sectionGap": 56, "tags": ("editorial", "airy", "luxe")},
}


# ── structural rules (geometry, not taste — these are hard) ───────────────
_HORIZONTAL = {"bar-top", "bar-centered", "dock-bottom"}
_ROUNDED_OR_PADDED = {"rail-float", "rail-glass", "rail-sidecar", "rail-icon",
                      "dock-bottom", "bar-centered"}
_HAS_RIGHT_WALL = {"rail-right", "rail-sectioned", "rail-cells", "rail-index",
                   "rail-blocks", "rail-bleed"}
_CHROME_FREE = {"rail-text", "rail-hang", "rail-index"}


def _mark_allowed(nav: str, mark: str) -> bool:
    n, m = NAV_SHAPES[nav], ACTIVE_MARKS[mark]
    horizontal = nav in _HORIZONTAL
    if m.get("horizontalOnly") and not horizontal:
        return False
    if mark in ("left-bar", "right-bar", "invert", "border-box") and nav in ("dock-bottom",):
        return False
    if horizontal and mark in ("left-bar", "right-bar", "invert", "border-box"):
        return False
    if mark == "invert" and nav in _ROUNDED_OR_PADDED:
        return False
    if mark == "right-bar" and nav not in _HAS_RIGHT_WALL:
        return False
    if mark == "tint" and nav in ("rail-blocks", "rail-bleed"):
        return False   # tint on tint / defeats the bleed
    if mark in ("pill", "tint", "raised", "border-box") and nav in _CHROME_FREE:
        return False   # any filled/bordered mark contradicts a chrome-free rail
    if nav == "rail-icon" and mark in ("dot", "grad-hair", "chevron"):
        return False   # nothing to anchor to in a 40px square
    return True


def _header_allowed(nav: str, header: str) -> bool:
    if nav == "rail-icon" and header == "plain":
        return False   # no labels anywhere = user is lost
    if nav in _HORIZONTAL and header in ("masthead",):
        return False
    if nav == "rail-blocks" and header in ("plain", "rule-under"):
        return False   # header vanishes beside a loud rail
    if nav == "rail-index" and header == "breadcrumb":
        return False   # duplicate locator
    if nav in ("bar-centered", "dock-bottom") and header in ("breadcrumb", "inline-stats"):
        return False
    if nav in _CHROME_FREE and header in ("tinted-band", "accent-tab"):
        return False
    return True


# Pairs that simply look bad together, regardless of geometry.
# ── AXIS: page surface (the ground everything sits on) ────────────────────
# All are pure CSS/data-URI — no network, no images, no build step.
SURFACES: dict[str, dict] = {
    "plain":      {"tags": ("sharp", "technical", "luxe")},
    "grid-paper": {"minor": 20, "major": 100, "tags": ("technical", "dense")},
    "blueprint":  {"minor": 20, "major": 100, "invert": True, "loud": True,
                   "tags": ("technical", "sharp")},
    "dot-grid":   {"gap": 16, "tags": ("technical", "airy")},
    "grain":      {"freq": ".65", "alpha": ".055", "tags": ("organic", "editorial")},
    "crosshatch": {"tags": ("editorial", "organic")},
    "linen":      {"tags": ("organic", "luxe", "editorial")},
    "wash":       {"tags": ("soft", "luxe")},
    "mesh":       {"loud": True, "tags": ("soft", "playful")},
    "hairline-h": {"gap": 28, "tags": ("editorial", "dense")},
    "diagonal":   {"gap": 20, "tags": ("technical", "playful")},
}


def surface_css(kind: str, colors: dict, *, dark: bool, scope: str) -> str:
    """Emit the page ground. Textures are subtle by construction — alpha caps
    at .09 — because a loud ground fights every component above it."""
    prim = colors.get("primary", "#4F46E5")
    acc = colors.get("accent", prim)
    bg = colors.get("background", "#0B0D12" if dark else "#FFFFFF")
    ln = "rgba(255,255,255,.055)" if dark else "rgba(15,18,32,.045)"
    lnM = "rgba(255,255,255,.10)" if dark else "rgba(15,18,32,.085)"
    S = scope
    d = SURFACES.get(kind, SURFACES["plain"])
    if kind == "plain":
        return ""
    if kind == "grid-paper":
        mi, ma = d["minor"], d["major"]
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"linear-gradient(to right,{lnM} 1px,transparent 1px),"
                f"linear-gradient(to bottom,{lnM} 1px,transparent 1px),"
                f"linear-gradient(to right,{ln} 1px,transparent 1px),"
                f"linear-gradient(to bottom,{ln} 1px,transparent 1px);"
                f" background-size:{ma}px {ma}px,{ma}px {ma}px,"
                f"{mi}px {mi}px,{mi}px {mi}px; }}")
    if kind == "blueprint":
        # Only legible as a ground when the app is already dark.
        base = colors.get("surface", "#0D2438") if dark else "#0D3B66"
        return (f"{S} {{ background-color:{base}; background-image:"
                "repeating-linear-gradient(to right,rgba(255,255,255,.16) 0 1px,"
                "transparent 1px 100px),"
                "repeating-linear-gradient(to bottom,rgba(255,255,255,.16) 0 1px,"
                "transparent 1px 100px),"
                "repeating-linear-gradient(to right,rgba(255,255,255,.06) 0 1px,"
                "transparent 1px 20px),"
                "repeating-linear-gradient(to bottom,rgba(255,255,255,.06) 0 1px,"
                "transparent 1px 20px); }")
    if kind == "dot-grid":
        g = d["gap"]
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"radial-gradient(circle,{lnM} 1px,transparent 1px);"
                f" background-size:{g}px {g}px; }}")
    if kind == "grain":
        # feTurbulence as a data-URI: no request, tiles forever, kills the
        # gradient banding that makes flat fills read as cheap.
        noise = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'"
                 "%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise'"
                 f" baseFrequency='{d['freq']}' numOctaves='3' stitchTiles='stitch'/"
                 "%3E%3C/filter%3E%3Crect width='100%25' height='100%25'"
                 " filter='url(%23n)'/%3E%3C/svg%3E\")")
        # `S` may be a selector LIST ("A, B"). A naive f"{S}::before"
        # attaches the pseudo-element only to the LAST selector — the
        # grain styles (position:fixed + opacity .055) then land on the
        # first selector's REAL element, rendering the entire app at 5%
        # opacity ("everything looks like it's under an overlay").
        # Distribute ::before across every selector in the list.
        before_sel = ", ".join(f"{part.strip()}::before"
                               for part in S.split(",") if part.strip())
        return (f"{S} {{ background-color:{bg}; position:relative; }}"
                f"\n{before_sel} {{ content:''; position:fixed; inset:0;"
                f" pointer-events:none; z-index:0; background-image:{noise};"
                f" background-size:182px; opacity:{d['alpha']}; }}")
    if kind == "crosshatch":
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"repeating-linear-gradient(45deg,{ln} 0 1px,transparent 1px 6px),"
                f"repeating-linear-gradient(-45deg,{ln} 0 1px,transparent 1px 6px); }}")
    if kind == "linen":
        hi = "rgba(255,255,255,.06)" if dark else "rgba(255,255,255,.35)"
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"repeating-linear-gradient(0deg,{ln} 0 1px,transparent 1px 3px),"
                f"repeating-linear-gradient(90deg,{ln} 0 1px,transparent 1px 3px),"
                f"repeating-linear-gradient(45deg,{hi} 0 2px,transparent 2px 5px); }}")
    if kind == "wash":
        return (f"{S} {{ background:radial-gradient(ellipse 80% 50% at 50% -10%,"
                f"{prim}{'2e' if dark else '1c'},transparent),{bg}; }}")
    if kind == "mesh":
        return (f"{S} {{ background:"
                f"radial-gradient(60rem 40rem at 12% 18%,{prim}{'2a' if dark else '1e'},transparent 60%),"
                f"radial-gradient(50rem 36rem at 88% 12%,{acc}{'24' if dark else '18'},transparent 58%),"
                f"{bg}; }}")
    if kind == "hairline-h":
        g = d["gap"]
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"repeating-linear-gradient(0deg,{ln} 0 1px,transparent 1px {g}px); }}")
    if kind == "diagonal":
        g = d["gap"]
        return (f"{S} {{ background-color:{bg}; background-image:"
                f"repeating-linear-gradient(45deg,{ln} 0 1px,transparent 1px {g}px),"
                f"repeating-linear-gradient(-45deg,{ln} 0 1px,transparent 1px {g}px); }}")
    return ""


_FORBIDDEN_PAIRS: tuple[tuple[str, str], ...] = (
    ("glass", "hard-offset"), ("glass", "thick"), ("glass", "square"),
    ("chamfer", "soft-shadow"), ("chamfer", "layered"), ("chamfer", "pillowy"),
    ("chamfer", "glass"), ("hard-offset", "pillowy"), ("hard-offset", "layered"),
    ("rules-only", "pillowy"), ("rules-only", "tint-fill"), ("rules-only", "rounded"),
    ("mono", "pillowy"), ("mono", "tint-block"), ("mono", "capsule-soft"),
    ("serif-display", "shared-strip"), ("condensed", "bento-mixed"),
    ("rounded", "shared-strip"), ("rounded", "ledger-leaders"),
    ("slab", "glass-ribbon"), ("geometric", "ledger-leaders"),
    ("none", "square"),  # no enclosure AND no radius reads unfinished
    # depth contradictions
    ("glass", "rules-only"), ("layered", "hard-offset"), ("soft-shadow", "hard-offset"),
    # geometry contradictions
    ("chamfer", "capsule-soft"), ("chamfer", "bento-mixed"),
    ("square", "capsule-soft"), ("pillowy", "shared-strip"),
    # type contradictions (verified in research)
    ("mono", "radial-gauges"), ("mono", "soft-shadow"), ("mono", "glass"),
    ("rounded", "boxless-hairline"), ("rounded", "stat-column"),
    ("serif-display", "tint-block"), ("condensed", "capsule-soft"),
    ("condensed", "rounded"), ("slab", "glass"),
    # density contradictions
    ("tint-block", "tint-fill"),      # tint on tint collapses hierarchy
    ("shared-strip", "pillowy"), ("ledger-leaders", "tint-fill"),
    # A patterned ground read through a translucent card is mud — the texture
    # and the fill fight, and the text loses. One or the other.
    ("glass", "grid-paper"), ("glass", "blueprint"), ("glass", "crosshatch"),
    ("glass", "linen"), ("glass", "diagonal"), ("glass", "dot-grid"),
    ("tint-fill", "crosshatch"), ("tint-fill", "linen"), ("tint-fill", "blueprint"),
    ("none", "grid-paper"), ("none", "blueprint"), ("none", "crosshatch"),
    ("none", "diagonal"), ("rules-only", "grid-paper"), ("rules-only", "blueprint"),
    ("rules-only", "crosshatch"), ("rules-only", "diagonal"), ("rules-only", "linen"),
    ("mono", "mesh"), ("mono", "wash"), ("serif-display", "blueprint"),
    ("rounded", "blueprint"), ("rounded", "crosshatch"),
    # ── AI-SLOP TELLS (research-named; these read as generated) ───────────
    # "hairline border + wide diffuse shadow" is called out as *the*
    # recurring generated-UI signature. Every premium reference forbids
    # shadows on bordered cards. Pick one: a border OR a lift, never both.
    ("hairline", "soft-shadow"), ("hairline", "layered"),
    ("surface-step", "soft-shadow"), ("surface-step", "layered"),
    # radius >= 16 reads consumer-marketing, not premium dashboard; keep the
    # big radii away from the data-dense anatomies.
    ("pillowy", "boxless-hairline"), ("pillowy", "ledger-leaders"),
    ("pillowy", "ruled-band"), ("rounded", "ruled-band"),
)


def _pair_ok(a: str, b: str) -> bool:
    return (a, b) not in _FORBIDDEN_PAIRS and (b, a) not in _FORBIDDEN_PAIRS


def _tags(*vals: dict) -> set[str]:
    out: set[str] = set()
    for v in vals:
        out.update(v.get("tags", ()))
    return out


def _coherent(picks: dict, *, loose: bool = False) -> bool:
    """>=2 shared tags across nav/kpi/card/type, and no antonym clash.

    `loose` accepts a single shared tag — used only by the relaxation tiers,
    where a slightly weaker mood is still far better than shipping the same
    fallback language to every hard-to-satisfy app.
    """
    groups = [NAV_SHAPES[picks["navShape"]], KPI_ANATOMY[picks["kpiAnatomy"]],
              CARD_TREATMENTS[picks["cardTreatment"]], TYPE_CLASSES[picks["typeClass"]],
              SURFACES.get(picks.get("surface", "plain"), {})]
    tags = _tags(*groups)
    for a, b in _ANTONYMS:
        if a in tags and b in tags:
            return False
    # count tags shared by at least two of the four groups
    shared = sum(1 for t in TAGS
                 if sum(1 for g in groups if t in g.get("tags", ())) >= 2)
    return shared >= (1 if loose else 2)


def _loud_count(picks: dict) -> int:
    return sum(1 for table, key in (
        (NAV_SHAPES, "navShape"), (KPI_ANATOMY, "kpiAnatomy"),
        (CARD_TREATMENTS, "cardTreatment"), (RADIUS_REGIMES, "radiusRegime"),
        (HEADER_STYLES, "headerStyle"),
    ) if table[picks[key]].get("loud")) + (
        1 if SURFACES.get(picks.get("surface", "plain"), {}).get("loud") else 0)


# Archetype affinity — weights the draw toward domain-appropriate moods.
ARCHETYPE_AFFINITY: dict[str, tuple[str, ...]] = {
    "fintech":       ("technical", "sharp", "luxe"),
    "healthcare":    ("soft", "organic", "airy"),
    "consumer-warm": ("soft", "playful", "organic"),
    "legal":         ("editorial", "luxe", "sharp"),
    "creative":      ("playful", "luxe", "airy"),
    "developer":     ("technical", "dense", "sharp"),
    "logistics":     ("technical", "dense", "sharp"),
    "education":     ("playful", "soft", "airy"),
    "hospitality":   ("luxe", "editorial", "organic"),
    "hr-people":     ("soft", "organic", "airy"),
    "commerce":      ("playful", "sharp", "soft"),
    "industrial":    ("technical", "sharp", "dense"),
    "analytics":     ("technical", "dense", "editorial"),
    "fitness":       ("sharp", "playful", "dense"),
    "default-saas":  ("technical", "soft", "sharp"),
}


def _weighted_keys(table: dict, affinity: tuple[str, ...]) -> list[str]:
    """Keys repeated once per matching affinity tag (+1 base) so the draw
    leans domain-appropriate without ever excluding a value outright."""
    out: list[str] = []
    for k, v in table.items():
        weight = 1 + sum(1 for t in affinity if t in v.get("tags", ()))
        out.extend([k] * weight)
    return out


def _byte(seed: bytes, salt: int) -> int:
    """Draw a decorrelated byte for `salt` from the whole seed.

    This used to be `seed[salt % len(seed)]`, which meant every axis read a
    single byte of a 32-byte digest: two projects that happened to share the
    handful of bytes the composer samples produced byte-identical design
    languages however different the rest of the seed was. Observed live —
    a pet-grooming app and a school portal drew the same signature. Hashing
    (seed, salt) spends the full digest on every draw position instead.
    """
    return hashlib.sha256(seed + salt.to_bytes(4, "big")).digest()[0]


# ── brief-aware veto ──────────────────────────────────────────────────────
#
# Same class of gate as ``services.aesthetic_profile_picker._is_vetoed_by_brief``
# (task #595). The design_language pooler used to draw brutalist moves from the
# full pick tables regardless of brief tone; a warm/calm/soft brief could
# therefore land on grid-paper + hard-offset + JetBrains-Mono
# ("lang190bc97b" on the 4noe2jyh yoga app, task #661). Vetoing the offending
# pick VALUES BEFORE the seed-driven draw guarantees the seed never even sees
# them, so the composed language stays deterministic in (archetype, seed, brief)
# without changing the seed space for enterprise / technical briefs.
#
# Pick values classed as brutalist for a warm brief:
#   SURFACES:        hard-patterned grounds (grid, blueprint, dot-grid,
#                    crosshatch, hairline-h, diagonal, mesh)
#   CARD_TREATMENTS: chunky-border / hard-offset / dashboard-step (hard-offset,
#                    thick, surface-step) — the ones that emit 3px borders or
#                    the 4px offset shadow
#   TYPE_CLASSES:    mono / condensed / slab — force uppercase + technical air
#   RADIUS_REGIMES:  square, hairline — sharp corners on a soft brief
#
# Kept as frozensets so a new brutalist entry in the pick table only needs
# adding here to fall under the veto.


_BRUTALIST_SURFACES: frozenset[str] = frozenset({
    "grid-paper", "blueprint", "dot-grid", "crosshatch",
    "hairline-h", "diagonal", "mesh",
})
_BRUTALIST_CARDS: frozenset[str] = frozenset({
    "hard-offset", "thick", "surface-step",
})
_BRUTALIST_TYPES: frozenset[str] = frozenset({
    "mono", "condensed", "slab",
})
_SHARP_RADII: frozenset[str] = frozenset({"square", "hairline"})


def _is_warm_brief(brief: object | None) -> bool:
    """Return True when ``brief`` reads warm/calm/soft.

    Delegates to
    :func:`services.aesthetic_profile_picker._brief_stance_words` so both
    veto layers (aesthetic profile + design language) share ONE brief-tone
    reader — a change to snake_case handling or a new calm-signal word
    only needs to land there. Safe on any shape: missing brief, dict,
    pydantic model, or malformed blob all fall through as "not warm" so
    the picker stays permissive when it has no signal.

    Slice A (2026-08-13) — an active ``visual_lock`` short-circuits the
    stance heuristics: the lock is an explicit commitment to a specific
    look, and brutalist surfaces (grid-paper, blueprint, crosshatch)
    would clash with EVERY preset (wellness/creative/data/admin). Rather
    than encode preset-specific vetoes, we treat any lock as "warm-safe"
    so the brutalist pool is filtered out. Callers who want brutalist
    are the ones who leave the lock empty.
    """
    if brief is None:
        return False
    # Slice A — lock present ⇒ veto brutalist pools regardless of stance.
    _lock = getattr(brief, "visual_lock", None)
    if _lock is not None:
        try:
            if _lock.is_active():
                return True
        except Exception:  # noqa: BLE001 — malformed lock never crashes composition
            pass
    try:
        from services.aesthetic_profile_picker import (
            _brief_stance_words as _read_stance,
            _CALM_STANCE_WORDS,
        )
    except Exception:  # noqa: BLE001 — never let the veto crash composition
        return False
    words, temperature = _read_stance(brief)
    if temperature == "cool":
        return False
    if temperature == "warm":
        return True
    return bool(words & _CALM_STANCE_WORDS)


def _veto_brutalist_pool(pool: dict[str, dict], brutalist: frozenset[str]) -> dict[str, dict]:
    """Return a copy of ``pool`` with brutalist entries removed.

    Preserves order + preserves every non-vetoed entry unchanged. If the
    veto would empty the pool (shouldn't happen with current sets but
    stays safe), the original pool is returned so composition can still
    complete rather than crashing on an empty draw.
    """
    kept = {k: v for k, v in pool.items() if k not in brutalist}
    return kept or pool


def _veto_brutalist_fallbacks(fallbacks: tuple[dict, ...]) -> tuple[dict, ...]:
    """Return the subset of ``_FALLBACKS`` that contains no brutalist axis.

    Fallbacks are last-resort presets; if EVERY fallback happens to be
    brutalist under the current axis sets the caller keeps the original
    tuple (safer to ship a slightly brutalist fallback than to crash on
    an empty pool).
    """
    kept: list[dict] = []
    for fb in fallbacks:
        if fb.get("surface") in _BRUTALIST_SURFACES:
            continue
        if fb.get("cardTreatment") in _BRUTALIST_CARDS:
            continue
        if fb.get("typeClass") in _BRUTALIST_TYPES:
            continue
        kept.append(fb)
    return tuple(kept) or fallbacks


def compose_language(archetype: str, seed: bytes, *, brief: object | None = None,
                     attempts: int = 64, _relax: int = 0) -> dict:
    """Draw a coherent design language for this project.

    Deterministic in (archetype, seed). Walks the seed space until a draw
    satisfies the structural rules, the taste model and the one-loud cap.

    If no draw survives, the constraints RELAX in tiers rather than falling
    back to a constant — a single shared fallback made every hard-to-satisfy
    app identical, which is precisely the failure this engine exists to fix.
    Tier 1 drops the surface to plain (its pair rules are the strictest),
    tier 2 accepts looser coherence, tier 3 lifts the one-loud cap. Every
    tier still enforces the structural rules, so nothing incoherent ships.
    """
    aff = ARCHETYPE_AFFINITY.get(archetype, ARCHETYPE_AFFINITY["default-saas"])
    aff_set = set(aff)
    # Chrome is a FIRST-CLASS draw, not inherited from whichever nav shape is
    # picked. 12 of 20 nav shapes are left-rails, so inheriting chrome from the
    # shape made ~60% of every domain's apps wide-rail and top-nav/dock/right
    # almost never appeared — the shell looked "the same every time". Group the
    # shapes by chrome family, draw the family with an even base weight plus a
    # small affinity tilt (so every chrome stays reachable while domain-fit
    # ones lead slightly), then draw a nav shape WITHIN the chosen family.
    _families: dict[str, list[str]] = {}
    for _nm, _sp in NAV_SHAPES.items():
        _families.setdefault(_sp["chrome"], []).append(_nm)
    chrome_pool: list[str] = []
    for _ch, _shapes in _families.items():
        _tags = set().union(*(set(NAV_SHAPES[n].get("tags", ())) for n in _shapes))
        chrome_pool += [_ch] * (2 + min(2, len(aff_set & _tags)))

    # Brief-aware veto — remove brutalist pick VALUES from the pools BEFORE
    # weighting/drawing when the brief signals warm/calm/soft (task #661).
    # Filtering upstream keeps the seed deterministic AND guarantees the
    # draw never even sees ``hard-offset`` / ``grid-paper`` / ``mono`` etc
    # on a wellness brief. Enterprise/technical briefs are unaffected — the
    # veto is a no-op when ``brief`` is None or reads cool/technical.
    _warm = _is_warm_brief(brief)
    _cards_pool = (_veto_brutalist_pool(CARD_TREATMENTS, _BRUTALIST_CARDS)
                   if _warm else CARD_TREATMENTS)
    _types_pool = (_veto_brutalist_pool(TYPE_CLASSES, _BRUTALIST_TYPES)
                   if _warm else TYPE_CLASSES)
    _surfs_pool = (_veto_brutalist_pool(SURFACES, _BRUTALIST_SURFACES)
                   if _warm else SURFACES)
    _radii_pool = (_veto_brutalist_pool(RADIUS_REGIMES, _SHARP_RADII)
                   if _warm else RADIUS_REGIMES)

    kpis = _weighted_keys(KPI_ANATOMY, aff)
    cards = _weighted_keys(_cards_pool, aff)
    radii = _weighted_keys(_radii_pool, aff)
    types = _weighted_keys(_types_pool, aff)
    dens = _weighted_keys(DENSITIES, aff)
    surfs = _weighted_keys(_surfs_pool, aff)
    heads = list(HEADER_STYLES)
    marks = list(ACTIVE_MARKS)

    for attempt in range(attempts):
        o = attempt * 7          # walk the seed for each retry
        _chrome = chrome_pool[_byte(seed, 30 + o) % len(chrome_pool)]
        _fam_navs = _weighted_keys(
            {n: NAV_SHAPES[n] for n in _families[_chrome]}, aff)
        picks = {
            "navShape":       _fam_navs[_byte(seed, 39 + o) % len(_fam_navs)],
            "kpiAnatomy":     kpis[_byte(seed, 31 + o) % len(kpis)],
            "cardTreatment":  cards[_byte(seed, 32 + o) % len(cards)],
            "radiusRegime":   radii[_byte(seed, 33 + o) % len(radii)],
            "typeClass":      types[_byte(seed, 34 + o) % len(types)],
            "density":        dens[_byte(seed, 35 + o) % len(dens)],
            "surface":         surfs[_byte(seed, 38 + o) % len(surfs)],
        }
        nav = picks["navShape"]
        ok_marks = [m for m in marks if _mark_allowed(nav, m)]
        ok_heads = [h for h in heads if _header_allowed(nav, h)]
        if not ok_marks or not ok_heads:
            continue
        picks["activeMark"] = ok_marks[_byte(seed, 36 + o) % len(ok_marks)]
        picks["headerStyle"] = ok_heads[_byte(seed, 37 + o) % len(ok_heads)]

        # taste gates
        if not _pair_ok(picks["cardTreatment"], picks["radiusRegime"]):
            continue
        if not _pair_ok(picks["typeClass"], picks["kpiAnatomy"]):
            continue
        if not _pair_ok(picks["typeClass"], picks["radiusRegime"]):
            continue
        # A borderless / rules-only card has no fill to separate it from a
        # patterned ground, so the texture runs straight through the content.
        if not _pair_ok(picks["cardTreatment"], picks["surface"]):
            continue
        if not _pair_ok(picks["typeClass"], picks["surface"]):
            continue
        if _relax >= 1:
            picks["surface"] = "plain"
        if not _coherent(picks, loose=_relax >= 2):
            continue
        # The one-loud cap is NEVER relaxed. It is the single rule doing the
        # most work to keep a composed app from reading as a circus.
        if _loud_count(picks) > 1:
            continue
        return _materialise(picks)

    if _relax < 2:
        return compose_language(archetype, seed, brief=brief, attempts=attempts,
                                _relax=_relax + 1)

    # Exhausted every tier. Rather than one shared constant, pick a preset
    # from the seed so even this last resort still varies per app. On a warm
    # brief the fallback pool is pre-filtered so no brutalist preset can
    # slip through the last-resort branch either.
    _fb_pool = _veto_brutalist_fallbacks(_FALLBACKS) if _is_warm_brief(brief) else _FALLBACKS
    fb = _fb_pool[_byte(seed, 29) % len(_fb_pool)]
    return _materialise(dict(fb))


# Last-resort languages. NOT hand-written — hand-written presets silently
# violated the structural rules, so these were found by searching the space
# for fully-valid draws and greedily picking the eight most mutually distinct
# (min 5 of 6 axes differ between any two). `_assert_fallbacks_valid()` below
# re-checks them at import so they can never drift out of legality.
_FALLBACKS: tuple[dict, ...] = (
    {"navShape": "rail-bleed", "kpiAnatomy": "stat-column", "cardTreatment": "surface-step", "radiusRegime": "scoop", "typeClass": "condensed", "density": "tight", "activeMark": "raised", "headerStyle": "plain", "surface": "grid-paper"},
    {"navShape": "rail-blocks", "kpiAnatomy": "hero-asymmetric", "cardTreatment": "soft-shadow", "radiusRegime": "rounded", "typeClass": "geometric", "density": "editorial", "activeMark": "invert", "headerStyle": "eyebrow-num", "surface": "grain"},
    {"navShape": "rail-tree", "kpiAnatomy": "glass-ribbon", "cardTreatment": "layered", "radiusRegime": "square", "typeClass": "serif-display", "density": "airy", "activeMark": "tint", "headerStyle": "breadcrumb", "surface": "hairline-h"},
    {"navShape": "rail-sectioned", "kpiAnatomy": "shared-strip", "cardTreatment": "hairline", "radiusRegime": "pillowy", "typeClass": "slab", "density": "airy", "activeMark": "raised", "headerStyle": "kicker-rule", "surface": "wash"},
    {"navShape": "rail-right", "kpiAnatomy": "boxless-hairline", "cardTreatment": "thick", "radiusRegime": "soft", "typeClass": "grotesque", "density": "airy", "activeMark": "left-bar", "headerStyle": "kicker-rule", "surface": "mesh"},
    {"navShape": "rail-sidecar", "kpiAnatomy": "ledger-leaders", "cardTreatment": "none", "radiusRegime": "squircle", "typeClass": "humanist", "density": "tight", "activeMark": "border-box", "headerStyle": "accent-tab", "surface": "dot-grid"},
    {"navShape": "rail-cells", "kpiAnatomy": "bento-mixed", "cardTreatment": "tint-fill", "radiusRegime": "chamfer", "typeClass": "mono", "density": "airy", "activeMark": "tint", "headerStyle": "inline-stats", "surface": "diagonal"},
    {"navShape": "rail-mono", "kpiAnatomy": "compartment", "cardTreatment": "tint-fill", "radiusRegime": "rounded", "typeClass": "grotesque", "density": "editorial", "activeMark": "chevron", "headerStyle": "eyebrow-num", "surface": "grid-paper"},
)


def _materialise(picks: dict) -> dict:
    """Expand the axis picks into the concrete geometry the emitters read."""
    nav = NAV_SHAPES[picks["navShape"]]
    kpi = KPI_ANATOMY[picks["kpiAnatomy"]]
    card = CARD_TREATMENTS[picks["cardTreatment"]]
    rad = RADIUS_REGIMES[picks["radiusRegime"]]
    typ = TYPE_CLASSES[picks["typeClass"]]
    den = DENSITIES[picks["density"]]
    return {
        **picks,
        "chrome": nav["chrome"],
        "navWidth": nav["w"], "navInset": nav["inset"], "navSide": nav["side"],
        "kpiTemplate": kpi["cols"], "kpiGap": kpi["gap"],
        "cardBorder": card["border"], "cardShadow": card["shadow"], "cardFill": card["fill"],
        "radius": rad["r"], "chamfer": bool(rad.get("chamfer")),
        "cornerShape": rad.get("corner"),
        "gutter": den["gutter"], "cardGap": den["cardGap"],
        "cardPad": den["cardPad"], "sectionGap": den["sectionGap"],
        "display": typ["display"], "numFamily": typ.get("num"),
        "h1": typ["h1"], "labelCase": typ["labelCase"], "labelTrack": typ["labelTrack"],
        "signature": design_signature(picks),
    }


def design_signature(picks: dict) -> str:
    """The five axes a user actually perceives. Two apps sharing this look
    like one product; the generator treats a repeat as a collision."""
    return "·".join((picks["navShape"], picks["kpiAnatomy"],
                     picks["cardTreatment"], picks["radiusRegime"],
                     picks["typeClass"], picks.get("surface", "plain")))


def seed_for(project_id: str, domain: str = "") -> bytes:
    return hashlib.sha256(f"{project_id}::{domain}".encode()).digest()


# ===========================================================================
# CSS EMISSION
#
# Everything is scoped under [data-skin="<signature-hash>"] which the app
# layout stamps on a div wrapping the whole shell — (0,2,0)+ specificity, so
# it beats every Tailwind utility (v3 emits no cascade layers) without
# !important, except for the audited inline-style hazards flagged inline.
# ===========================================================================

def _shadow_css(kind: str, ink: str, prim: str) -> str:
    return {
        "none":     "none",
        "hairline": "0 1px 2px rgba(0,0,0,.05)",
        "soft":     "0 2px 8px rgba(20,20,30,.07)",
        "layered":  "0 1px 2px rgba(20,20,30,.04), 0 4px 12px rgba(20,20,30,.06),"
                    " 0 12px 32px rgba(20,20,30,.05)",
        "offset":   f"6px 6px 0 0 {ink}",
        "glow":     f"0 4px 16px {prim}1f, inset 0 1px 0 rgba(255,255,255,.7)",
    }.get(kind, "none")


_CHAMFER = ("polygon(10px 0, 100% 0, 100% calc(100% - 10px),"
            " calc(100% - 10px) 100%, 0 100%, 0 10px)")


def language_css(lang: dict, colors: dict, *, dark: bool = False,
                 scope: str | None = None) -> str:
    """The app's complete component stylesheet, composed from its language."""
    S = scope or '[data-skin="%s"]' % lang.get("skinKey", "app")
    ink, surf = colors["textPrimary"], colors["surface"]
    prim, acc = colors["primary"], colors["accent"]
    line = "rgba(255,255,255,0.12)" if dark else "rgba(20,20,30,0.12)"
    hair = "rgba(255,255,255,0.07)" if dark else "rgba(20,20,30,0.07)"
    glass = "rgba(23,23,33,.55)" if dark else "rgba(255,255,255,.62)"

    KPI = f"{S} .grid:has([data-metric-tile]), {S} .grid:has([data-importance])"
    TILE = f"{S} :where([data-metric-tile], [data-importance])"
    # Target the MetricTile's explicit hooks, NOT <p> positions. The register
    # variants (linear/workday/…) nest the label in a header row, so BOTH the
    # label and value are `p:first-of-type` in their own parent — the old
    # `p:first-of-type` label selector matched the value too and shrank the big
    # number down to label size (seen live on LedgerFlow: a 24px value rendered
    # at 12px small-caps). data-metric-label / data-metric-value are unambiguous.
    LABEL = f"{TILE} :where([data-metric-label])"
    VALUE = f"{TILE} :where([data-metric-value])"
    CARD = f"{S} :where([data-card])"
    HEAD = f"{CARD} > :where([data-slot='header'])"

    h1_size, h1_weight, h1_case, h1_track = lang["h1"]
    rad = f'{lang["radius"]}px'
    step = ("rgba(255,255,255,.035)" if dark else "rgba(20,20,30,.022)")
    fill = {"none": "transparent", "surface": surf, "step": step,
            "tint": f"{prim}12", "glass": glass}[lang["cardFill"]]
    shadow = _shadow_css(lang["cardShadow"], ink, prim)
    border_col = ink if lang["cardBorder"] == 3 else line

    r: list[str] = [f"/* language: {lang['signature']} */"]

    # Delta colours, contrast-verified. emerald-600 (#059669) measures
    # 3.77:1 on white and fails AA; #047857 measures 5.48:1.
    pos, neg, mut = ("#34D399", "#F87171", "#94A3B8") if dark else \
                    ("#047857", "#B91C1C", "#475569")
    r.append(f"{S} {{ --sk-pos:{pos}; --sk-neg:{neg}; --sk-mut:{mut}; }}")
    r.append(f"{S} [data-delta-direction='up'] {{ color: var(--sk-pos); }}")
    r.append(f"{S} [data-delta-direction='down'] {{ color: var(--sk-neg); }}")
    r.append(f"{S} [data-delta-direction='flat'] {{ color: var(--sk-mut); }}")

    # variables the shell reads (nav width/inset, page rhythm)
    r.append(
        f"{S} {{ --sk-ink: {ink}; --sk-line: {line}; --sk-primary: {prim};"
        f" --sk-accent: {acc}; --sk-surface: {surf};"
        f" --sk-nav-w: {lang['navWidth']}px; --sk-nav-inset: {lang['navInset']}px;"
        f" --sk-gutter: {lang['gutter']}px; --sk-card-gap: {lang['cardGap']}px;"
        f" --sk-radius: {rad}; }}")

    # page rhythm — responsive: mobile gets a compact 12px gutter, then a
    # midpoint at ≥640, then the design's full gutter at ≥1024. Without this
    # step the design-language emits e.g. 72px padding at 375px viewport,
    # which crushes content into a ~230px strip and centres it far to the
    # right of the visible area (docs vault on iPhone-XR: mobile broke).
    _gut = lang['gutter']
    _gut_sm = min(_gut, 24)   # ≥640
    _gut_xs = min(_gut, 12)   # <640 — tighter than sm so mobile isn't gappy
    # Section-gap is responsive on the same beats: the design's rhythm
    # (often 40–72px) reads as excessive whitespace on mobile where the
    # viewport is already narrow. Step it 16 → 24 → full.
    _sg = lang['sectionGap']
    _sg_sm = min(_sg, 24)
    _sg_xs = min(_sg, 16)
    r.append(f"{S} main > div {{ padding: {_gut_xs}px; }}")
    r.append(f"@media (min-width: 640px) {{ {S} main > div {{ padding: {_gut_sm}px; }} }}")
    r.append(f"@media (min-width: 1024px) {{ {S} main > div {{ padding: {_gut}px; }} }}")
    r.append(f"{S} main > div > * {{ margin-bottom: {_sg_xs}px; }}")
    r.append(f"@media (min-width: 640px) {{ {S} main > div > * {{ margin-bottom: {_sg_sm}px; }} }}")
    r.append(f"@media (min-width: 1024px) {{ {S} main > div > * {{ margin-bottom: {_sg}px; }} }}")

    # type voice
    r.append(f"{S} :where(h1, h2, [data-slot='header']) {{ font-family: {lang['display']}; }}")
    r.append(f"{S} :where(main h1) {{ font-size: {h1_size}px; font-weight: {h1_weight};"
             f" text-transform: {h1_case}; letter-spacing: {h1_track}; }}")

    # ── KPI band ──────────────────────────────────────────────────────────
    # Column COUNT is the composer's call (schema Grid columns=N), not the
    # skin's: the old `grid-template-columns: … !important` here beat the
    # composed 4-up KPI grid into the anatomy's 2-col mosaic at EVERY
    # width — including phones, where it defeated responsive stacking
    # (live on cwx1stzz: ledger-leaders collapsed a 4-KPI dashboard to a
    # gapless 2×2 no CSS could override). The skin keeps rhythm (gap,
    # clamped ≥8px so 'gap:0' anatomies can't fuse tiles) and all visual
    # treatment below; it no longer dictates track count.
    r.append(f"{KPI} {{ gap: {max(int(lang['kpiGap']), 8)}px; }}")
    r.append(f"{LABEL} {{ text-transform: {lang['labelCase']};"
             f" letter-spacing: {lang['labelTrack']}; font-size: 11px; }}")
    if lang["numFamily"]:
        r.append(f"{VALUE} {{ font-family: {lang['numFamily']} !important; }}")
    # Proportional digits break every ruled/right-aligned KPI column.
    r.append(f"{VALUE} {{ font-variant-numeric: tabular-nums; }}")

    a = lang["kpiAnatomy"]
    if a == "boxless-hairline":
        r += [f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              " padding:18px 24px; }",
              f"{TILE}:not(:first-child) {{ border-left:1px solid {line}; }}",
              f"{KPI} {{ border-top:1px solid {ink}; border-bottom:1px solid {line}; }}",
              f"{VALUE} {{ font-size:40px; font-weight:500 !important; }}"]
    elif a == "shared-strip":
        r += [f"{KPI} {{ border:1px solid {line}; }}",
              f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              " padding:10px 12px; }",
              f"{TILE}:not(:first-child) {{ border-left:1px solid {line}; }}",
              f"{VALUE} {{ font-size:22px; font-weight:500 !important; }}"]
    elif a == "compartment":
        r += [f"{TILE} {{ border:3px solid {ink}; border-radius:10px;"
              f" box-shadow:5px 5px 0 0 {ink}; background:{surf}; padding:0; overflow:hidden; }}",
              f"{LABEL} {{ background:{prim}1f; border-bottom:3px solid {ink};"
              " margin:0; padding:8px 14px; font-weight:800; }",
              f"{VALUE} {{ padding:12px 14px 16px; margin:0; font-size:40px;"
              " font-weight:800 !important; }"]
    elif a == "plaque-chamfer":
        r += [f"{TILE} {{ border:1px solid {ink}; border-radius:0; box-shadow:none;"
              f" background:{surf}; padding:20px; text-align:center;"
              f" clip-path:{_CHAMFER}; border-top:3px solid {acc}; }}",
              f"{LABEL}, {VALUE} {{ text-align:center; }}",
              f"{VALUE} {{ font-size:42px; font-weight:500 !important; }}"]
    elif a == "tint-block":
        r += [f"{TILE} {{ border:0; border-radius:0; box-shadow:none; padding:18px;"
              f" min-height:128px; display:flex; flex-direction:column;"
              f" justify-content:space-between; background:{prim}1a; }}",
              f"{TILE}:nth-child(2) {{ background:{acc}1a; }}",
              f"{TILE}:nth-child(3) {{ background:{prim}26; }}",
              f"{TILE}:nth-child(4) {{ background:{acc}26; }}",
              f"{LABEL} {{ align-self:flex-start; background:{ink}; color:{surf};"
              " border-radius:999px; padding:3px 10px; font-weight:800; }",
              f"{VALUE} {{ font-size:46px; font-weight:900 !important; }}"]
    elif a == "bento-mixed":
        r += [f"{TILE} {{ border:0; border-radius:22px; box-shadow:0 1px 2px rgba(0,0,0,.05);"
              f" background:{prim}12; padding:20px; }}",
              f"{KPI} {{ grid-auto-rows:104px; }}",
              f"{TILE}:first-child {{ grid-column:span 2; grid-row:span 2; }}",
              f"{TILE}:nth-child(4) {{ grid-column:span 2; }}",
              f"{VALUE} {{ font-size:38px; font-weight:600 !important; }}"]
    elif a == "ledger-leaders":
        # A tight ledger row: small-caps label directly over a prominent value,
        # closed by a hairline rule (the financial-statement look). flex-col is
        # forced ON PURPOSE and space-between is avoided — the component ships a
        # `flex-col` class, and a bare `display:flex`+`space-between` inherited
        # that column direction and blew the label/value apart into big vertical
        # gaps (seen live on LedgerFlow). Explicit direction + gap wins.
        r += [f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              f" border-bottom:1px dotted {line}; padding:12px 0 10px; display:flex;"
              " flex-direction:column; align-items:flex-start; justify-content:flex-start;"
              " gap:3px; }",
              f"{LABEL} {{ font-variant:small-caps; text-transform:none; font-size:12px;"
              f" letter-spacing:.03em; color:{ink}; opacity:.62; }}",
              f"{VALUE} {{ text-align:left; font-size:26px; line-height:1.05;"
              f" font-weight:600 !important; }}"]
    elif a == "hero-asymmetric":
        r += [f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              " padding:8px 0; display:flex; flex-direction:column-reverse;"
              " justify-content:flex-end; }",
              f"{LABEL} {{ border-top:1px solid {hair}; padding-top:8px; margin-top:10px;"
              " opacity:.7; }",
              f"{VALUE} {{ font-size:56px; font-weight:300 !important; }}",
              f"{TILE}:not(:first-child) :where(p:nth-of-type(2)) {{ font-size:30px; }}"]
    elif a == "capsule-soft":
        r += [f"{TILE} {{ border:0; border-radius:18px;"
              " box-shadow:0 2px 6px rgba(60,50,35,.06), inset 0 1px 0 rgba(255,255,255,.7);"
              f" background:{surf}; padding:16px 18px; }}",
              f"{LABEL} {{ font-variant:small-caps; text-transform:none; }}",
              f"{VALUE} {{ font-size:30px; font-weight:600 !important; }}"]
    elif a == "glass-ribbon":
        r += [f"{KPI} {{ background:{glass}; backdrop-filter:blur(18px);"
              f" border:1px solid {'rgba(255,255,255,.14)' if dark else 'rgba(255,255,255,.6)'};"
              " border-radius:20px; padding:6px; }",
              f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              " padding:14px 16px; text-align:center; }",
              f"{TILE}:not(:first-child) {{ border-left:1px solid {hair}; }}",
              f"{VALUE} {{ font-size:28px; font-weight:600 !important; }}"]
    elif a == "ruled-band":
        r += [f"{TILE} {{ border:0; border-radius:0; box-shadow:none; background:transparent;"
              f" padding:16px 0; border-top:2px solid {ink}; }}",
              f"{VALUE} {{ font-size:38px; font-weight:500 !important; }}"]
    elif a == "stat-column":
        # Tight bordered column stat — same flex-col caveat as the ledger:
        # force the direction and avoid space-between so label and value sit
        # together instead of being pushed to opposite ends of the tile.
        r += [f"{TILE} {{ border:1px solid {line}; border-radius:0; box-shadow:none;"
              f" background:{surf}; padding:14px 16px; display:flex;"
              " flex-direction:column; align-items:flex-start; justify-content:flex-start;"
              " gap:4px; }",
              f"{VALUE} {{ font-size:24px; line-height:1.05; font-weight:600 !important; }}"]

    # ── cards ─────────────────────────────────────────────────────────────
    card_rule = (f"{CARD}, {S} :where([data-table], [data-activity-feed])"
                 f" {{ border-width:{lang['cardBorder']}px; border-color:{border_col};"
                 f" border-radius:{rad}; box-shadow:{shadow}; background:{fill};")
    if lang["chamfer"]:
        card_rule += f" clip-path:{_CHAMFER};"
    if lang["cardFill"] == "glass":
        card_rule += " backdrop-filter:blur(16px);"
    if CARD_TREATMENTS[lang["cardTreatment"]].get("topRule"):
        # An INK rule, never an accent one — a coloured edge-tab on a card is
        # the single most recognisable AI-generated-UI tell.
        card_rule += f" border-top:2px solid {ink};"
    r.append(card_rule + " }")
    if lang["cardPad"]:
        r.append(f"{CARD} > :where([data-slot='body']) {{ padding:{lang['cardPad']}px; }}")

    # card header follows the type voice
    if lang["labelCase"] == "uppercase":
        r.append(f"{HEAD} {{ background:transparent; border-bottom:1px solid {line};"
                 f" text-transform:uppercase; letter-spacing:{lang['labelTrack']};"
                 " font-size:12px; }")
    else:
        r.append(f"{HEAD} {{ background:transparent; border-bottom:none;"
                 " text-transform:none; letter-spacing:0; font-size:15px; }")

    # ── page header treatment ─────────────────────────────────────────────
    H = f"{S} main h1"
    hs = lang["headerStyle"]
    if hs == "rule-under":
        r.append(f"{H} {{ padding-bottom:12px; border-bottom:1px solid {line}; }}")
    elif hs == "masthead":
        r.append(f"{H} {{ border-top:3px solid {ink}; padding-top:14px; }}")
        r.append(f"{H} + p {{ border-bottom:1px solid {line}; padding-bottom:12px; }}")
    elif hs == "eyebrow-num":
        # Section counter — increments per h2 on the page so each SECTION
        # gets its own ordinal (01, 02, 03…), not "01" on every h1
        # (previous behaviour: hardcoded '01' on the page h1 which sits
        # once per page, so every page read as "01 Overview", "01 Users",
        # "01 Analytics" — visual noise, not editorial rhythm).
        r.append(f"{S} main {{ counter-reset: forge-section; }}")
        r.append(f"{S} main h2::before {{ counter-increment: forge-section;"
                 f" content: counter(forge-section, decimal-leading-zero);"
                 f" display:block; margin-bottom:6px; font-size:11px;"
                 f" font-weight:600; letter-spacing:.14em; opacity:.5; }}")
    elif hs == "accent-tab":
        r.append(f"{S} main h1::before {{ content:''; display:block; width:34px; height:4px;"
                 f" border-radius:2px; background:{acc}; margin-bottom:14px; }}")
    elif hs == "ghost-num":
        r.append(f"{S} main h1 {{ position:relative; }}")
        r.append(f"{S} main h1::after {{ content:''; position:absolute; right:0; top:-10px;"
                 f" width:110px; height:60px; background:{prim}0d; border-radius:8px;"
                 " z-index:-1; }")
    elif hs == "centered":
        r.append(f"{H} {{ text-align:center; }}")
        r.append(f"{H} + p {{ text-align:center; }}")
    elif hs == "tinted-band":
        r.append(f"{H} {{ background:{prim}12; margin:-{lang['gutter']}px"
                 f" -{lang['gutter']}px 20px; padding:{lang['gutter']}px; }}")
    elif hs == "kicker-rule":
        r.append(f"{S} main h1::after {{ content:''; display:block; width:44px; height:2px;"
                 f" background:{acc}; margin-top:10px; }}")

    # ── buttons ───────────────────────────────────────────────────────────
    btn_r = "999px" if lang["radiusRegime"] == "pillowy" else rad
    r.append(f"{S} :where(button) {{ border-radius:{btn_r}; }}")
    if lang["cardTreatment"] == "hard-offset":
        r += [f"{S} :where(button) {{ border:3px solid {ink}; box-shadow:4px 4px 0 0 {ink};"
              " font-weight:800; transition:transform 80ms, box-shadow 80ms; }",
              f"{S} :where(button:hover) {{ transform:translate(-2px,-2px);"
              f" box-shadow:6px 6px 0 0 {ink}; }}",
              f"{S} :where(button:active) {{ transform:translate(2px,2px); box-shadow:none; }}"]
    elif lang["cardFill"] == "glass":
        r.append(f"{S} :where(button.bg-primary, button[data-variant='primary'])"
                 f" {{ background:linear-gradient(180deg, {prim}, {acc});"
                 f" box-shadow:0 2px 8px {prim}4d; }}")
    if lang["typeClass"] == "mono":
        r.append(f"{S} :where(button) {{ font-family:{lang['display']};"
                 " text-transform:uppercase; letter-spacing:.06em; font-size:11px; }")
    elif lang["typeClass"] == "condensed":
        r.append(f"{S} :where(button) {{ text-transform:uppercase; letter-spacing:.14em; }}")

    # ── tables ────────────────────────────────────────────────────────────
    T = f"{S} [data-table]"
    if lang["typeClass"] == "mono":
        r += [f"{T} :where(th, td) {{ border:1px solid {line}; font-family:{lang['display']};"
              " font-size:11px; padding:4px 8px; }"]
    elif lang["cardTreatment"] in ("none", "rules-only"):
        r += [f"{T} :where(thead) {{ background:transparent; }}",
              f"{T} :where(thead th) {{ border-bottom:2px solid {ink};"
              f" letter-spacing:{lang['labelTrack']}; }}",
              f"{T} :where(tbody tr) {{ border-bottom:1px solid {hair}; }}"]
    elif lang["cardTreatment"] in ("thick", "hard-offset"):
        r += [f"{T} :where(thead) {{ background:{ink}; }}",
              f"{T} :where(thead th) {{ color:{surf}; font-weight:800; }}"]
    else:
        r += [f"{T} :where(thead) {{ background:transparent; }}",
              f"{T} :where(thead th) {{ text-transform:{lang['labelCase']};"
              f" letter-spacing:{lang['labelTrack']}; font-size:12px; }}",
              f"{T} :where(tbody tr) {{ border-bottom:1px solid {hair}; }}"]

    # Row height tracks the app's density rhythm. A 48px toolbar over 32px
    # rows reads broken — Carbon documents the coupling explicitly.
    _row = {"dense": 32, "tight": 40, "standard": 48, "airy": 56, "editorial": 52}
    r.append(f"{T} :where(tbody tr) {{ height:{_row[lang['density']]}px; }}")
    # Horizontal rules only: no major design system ships vertical cell
    # dividers outside spreadsheet contexts.
    if lang["typeClass"] != "mono":
        r.append(f"{T} :where(td) {{ border-left:0; border-right:0; }}")
    # Financial anatomies close with the accounting double rule
    # (single rule = subtotal, double = grand total).
    if lang["kpiAnatomy"] in ("ledger-leaders", "ruled-band"):
        r.append(f"{T} :where(tbody tr:last-child td) {{ border-top:1px solid {ink};"
                 f" border-bottom:3px double {ink}; font-weight:600; }}")

    # Zero-gap anatomies (ledger, shared-strip, glass-ribbon) separate cells
    # with rules or a shared fill rather than gutters, so the cells need their
    # own inline padding or one cell's delta butts straight against the next
    # cell's label. Emitted AFTER the anatomy block on purpose: these are all
    # :where() selectors with zero specificity, so the anatomy's `padding`
    # shorthand would otherwise reset it. Caught by rendering, not by a test.
    if lang["kpiGap"] == 0:
        r.append(f"{TILE} {{ padding-inline: 18px; }}")
        r.append(f"{TILE}:first-child {{ padding-inline-start: 0; }}")

    # ── page surface ─────────────────────────────────────────────────────
    # The ground the whole app sits on. A blueprint grid, a paper grain and
    # a flat fill read as three different pieces of software before a single
    # component renders — this is the widest-reaching axis in the engine.
    _surf = surface_css(lang.get("surface", "plain"), colors, dark=dark,
                        scope=f"{S} [data-shell-main], {S} main")
    if _surf:
        r.append(_surf)

    # ── modern corner geometry ───────────────────────────────────────────
    # `corner-shape` is Chrome/Edge 139+; everywhere else silently renders
    # the plain border-radius, so this is safe progressive enhancement.
    if lang.get("cornerShape"):
        cs = lang["cornerShape"]
        r.append("@supports (corner-shape: bevel) {"
                 f" {CARD}, {TILE}, {S} :where([data-chip], .badge)"
                 f" {{ corner-shape:{cs}; }} }}")

    # ── micro-craft: the details that separate crafted from generated ────
    # Focus ring. `outline` (not box-shadow) because box-shadow rings vanish
    # entirely in forced-colors mode, and outline now follows border-radius
    # in every current browser. WCAG 2.4.11 wants >=2px at >=3:1.
    _fr = {"square": "0", "hairline": "1px", "bevel": "2px"}.get(
        lang["radiusRegime"], f'{min(lang["radius"], 12)}px')
    r += [f"{S} :where(a,button,input,select,textarea,summary,[tabindex])"
          f":focus-visible {{ outline:2px solid {acc}; outline-offset:2px;"
          f" border-radius:{_fr}; }}",
          f"@media (forced-colors: active) {{ {S} :focus-visible"
          " { outline:2px solid CanvasText; outline-offset:2px; } }"]

    # Selection. Authoring ::selection means owning its contrast, so both
    # halves are set explicitly — inheriting `color` is what produces the
    # unreadable pairs you see on generated sites.
    _sel_bg = f"{acc}33" if dark else f"{acc}26"
    r.append(f"{S} ::selection {{ background:{_sel_bg}; color:{ink};"
             " text-shadow:none; }")

    # Scrollbars, keyed to the app's own line colour rather than the OS grey.
    r.append(f"{S} {{ scrollbar-width:thin; scrollbar-color:{line} transparent; }}")

    # Reduced motion is honoured for the whole scope, not per-component.
    # Built as one f-string so the brace count is unambiguous: `{{`/`}}` are
    # the two literal rule braces, and the trailing ` }` closes the @media.
    # (A prior mixed f-string + plain-string version emitted a stray third `}`
    # — `}} }` in a NON-f-string is two literal braces, not one — which broke
    # the whole stylesheet with "Unexpected }". Caught on the first real app.)
    r.append(
        f"@media (prefers-reduced-motion: reduce) {{ {S} *, {S} *::before,"
        f" {S} *::after {{ animation-duration:.01ms !important;"
        f" transition-duration:.01ms !important; }} }}"
    )

    return "/* tentoro:skin */\n" + "\n".join(r) + "\n/* /tentoro:skin */"


def nav_language_css(lang: dict, colors: dict, *, dark: bool = False,
                     scope: str | None = None) -> str:
    """Navigation identity: shape geometry + the active-state indicator."""
    S = scope or '[data-skin="%s"]' % lang.get("skinKey", "app")
    N = f"{S} [data-shell-nav]"
    I = f"{N} [data-nav-item]"
    A = f"{I}[data-active='true']"
    ink, surf = colors["textPrimary"], colors["surface"]
    prim, acc = colors["primary"], colors["accent"]
    line = "rgba(255,255,255,0.12)" if dark else "rgba(20,20,30,0.12)"
    nav = NAV_SHAPES[lang["navShape"]]

    r: list[str] = [f"/* nav: {lang['navShape']} + {lang['activeMark']} */"]

    # shape geometry
    item = (f"{I} {{ height:{nav['itemH']}px; padding-left:{nav['pad']}px;"
            f" padding-right:{nav['pad']}px; border-radius:{nav['radius']}px;"
            f" font-size:{nav['labelSize']}px; font-weight:{nav['labelWeight']};"
            f" text-transform:{nav['labelCase']};")
    if nav.get("labelTrack"):
        item += f" letter-spacing:{nav['labelTrack']};"
    if nav.get("mono"):
        item += " font-family:ui-monospace, monospace;"
    r.append(item + " }")

    if not nav["icons"]:
        r.append(f"{N} [data-nav-icon] {{ display:none; }}")
    if nav.get("iconDisc"):
        r.append(f"{N} [data-nav-icon] {{ background:{prim}22; border-radius:999px;"
                 " padding:.35rem; }")

    # shape signatures
    if lang["navShape"] == "rail-index":
        r += [f"{N} {{ counter-reset:navidx; }}",
              f"{I} {{ counter-increment:navidx; }}",
              f"{I}::before {{ content:counter(navidx, decimal-leading-zero);"
              " width:26px; flex:none; font-size:11px; opacity:.5;"
              " letter-spacing:.02em; }"]
    elif lang["navShape"] == "rail-hang":
        r.append(f"{N} [data-nav-group-label] {{ margin-left:-16px; }}")
        r.append(f"{I} {{ border-left:1px solid {line}; margin-left:8px;"
                 " padding-left:14px; }")
    elif lang["navShape"] == "rail-cells":
        r.append(f"{I} {{ border:1px solid {line}; margin-bottom:-1px; }}")
    elif lang["navShape"] == "rail-blocks":
        r += [f"{I} {{ margin:0; border-radius:0; }}",
              f"{I}:nth-child(4n+1) {{ background:{prim}0f; }}",
              f"{I}:nth-child(4n+2) {{ background:{acc}0f; }}",
              f"{I}:nth-child(4n+3) {{ background:{prim}1a; }}",
              f"{I}:nth-child(4n+4) {{ background:{acc}1a; }}"]
    elif lang["navShape"] == "rail-tree":
        r.append(f"{N} [data-nav-group-label] + * {{ margin-left:12px;"
                 f" padding-left:12px; border-left:1px solid {line}; }}")

    # active-state indicator
    m = lang["activeMark"]
    if m == "left-bar":
        r += [f"{A} {{ font-weight:600; }}",
              f"{A}::before {{ content:''; position:absolute; left:0; top:50%;"
              f" transform:translateY(-50%); width:3px; height:60%; background:{acc};"
              " border-radius:0 3px 3px 0; }",
              f"{I} {{ position:relative; }}"]
    elif m == "right-bar":
        r += [f"{A} {{ font-weight:600; }}", f"{I} {{ position:relative; }}",
              f"{A}::after {{ content:''; position:absolute; right:0; top:0; bottom:0;"
              f" width:2px; background:{acc}; }}"]
    elif m == "invert":
        r.append(f"{A} {{ background:{ink}; color:{surf}; border-radius:0; font-weight:600; }}")
    elif m == "pill":
        r.append(f"{A} {{ background:{acc}; color:{surf}; border-radius:999px;"
                 " font-weight:600; }")
    elif m == "tint":
        r.append(f"{A} {{ background:{prim}20; color:{prim}; font-weight:600; }}")
    elif m == "underline":
        r += [f"{I} {{ position:relative; }}",
              f"{A}::after {{ content:''; position:absolute; left:10px; right:10px;"
              f" bottom:-1px; height:2px; background:{acc}; }}"]
    elif m == "overline":
        r += [f"{I} {{ position:relative; }}",
              f"{A}::before {{ content:''; position:absolute; left:22%; right:22%;"
              f" top:0; height:2.5px; background:{acc}; }}"]
    elif m == "chevron":
        r += [f"{I} {{ position:relative; padding-left:18px; }}",
              f"{A}::before {{ content:'\\203A'; position:absolute; left:4px;"
              f" color:{acc}; font-weight:600; }}"]
    elif m == "dot":
        r += [f"{I} {{ position:relative; padding-left:20px; }}",
              f"{A}::before {{ content:''; position:absolute; left:6px; top:50%;"
              f" transform:translateY(-50%); width:5px; height:5px;"
              f" border-radius:50%; background:{acc}; }}"]
    elif m == "raised":
        r.append(f"{A} {{ background:{surf}; border-radius:9px;"
                 " box-shadow:0 1px 2px rgba(0,0,0,.05), 0 3px 8px rgba(0,0,0,.06);"
                 " font-weight:600; }")
    elif m == "border-box":
        r.append(f"{A} {{ box-shadow:inset 0 0 0 1px {acc}; font-weight:600; }}")
    elif m == "grad-hair":
        r += [f"{I} {{ position:relative; }}", f"{A} {{ font-weight:550; }}",
              f"{A}::after {{ content:''; position:absolute; left:0; right:0; bottom:0;"
              f" height:1px; background:linear-gradient(90deg, {acc}, transparent); }}"]

    return "/* tentoro:nav */\n" + "\n".join(r) + "\n/* /tentoro:nav */"


def _assert_fallbacks_valid() -> None:
    """The fallback presets bypass the composer's gates, so they are the one
    place an illegal language could reach a real app. Re-verify at import."""
    for i, fb in enumerate(_FALLBACKS):
        why = ""
        if not _mark_allowed(fb["navShape"], fb["activeMark"]):
            why = f'mark {fb["activeMark"]} illegal on {fb["navShape"]}'
        elif not _header_allowed(fb["navShape"], fb["headerStyle"]):
            why = f'header {fb["headerStyle"]} illegal on {fb["navShape"]}'
        elif _loud_count(fb) > 1:
            why = f"{_loud_count(fb)} loud moves"
        elif not _coherent(fb):
            why = "incoherent tag set"
        else:
            for a, b in (("cardTreatment", "radiusRegime"), ("typeClass", "kpiAnatomy"),
                         ("typeClass", "radiusRegime"), ("cardTreatment", "surface"),
                         ("typeClass", "surface")):
                if not _pair_ok(fb[a], fb[b]):
                    why = f"forbidden pair {fb[a]}+{fb[b]}"
                    break
        if why:
            raise AssertionError(f"design_language fallback preset {i}: {why}")


_assert_fallbacks_valid()
