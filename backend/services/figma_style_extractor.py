# backend/services/figma_style_extractor.py
"""Build a project tokens.custom.json from the fills found across a walked
Figma node tree. Intentionally simple — generates color.primary.* (50, 100,
500, 600, 900) plus color.surface.{0,1}. A follow-up will wire in
services.color_theory for fuller scale generation.
"""
from __future__ import annotations
from collections import Counter

from figma_parser import _hex_to_rgb


def _rgb_to_hex(c: dict) -> str:
    """Figma stores RGB as 0..1 floats."""
    r = max(0, min(255, int(round(c.get("r", 0) * 255))))
    g = max(0, min(255, int(round(c.get("g", 0) * 255))))
    b = max(0, min(255, int(round(c.get("b", 0) * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


def _is_neutral(hex_color: str) -> bool:
    """R, G, B within 15 of each other → neutral grey."""
    r, g, b = _hex_to_rgb(hex_color)
    return abs(r - g) < 15 and abs(g - b) < 15 and abs(r - b) < 15


def _tint(hex_color: str, amount: float) -> str:
    """Lighten toward white. amount=0 returns input, amount=1 returns white."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def _shade(hex_color: str, amount: float) -> str:
    """Darken toward black. amount=0 returns input, amount=1 returns black."""
    r, g, b = _hex_to_rgb(hex_color)
    r = int(r * (1 - amount))
    g = int(g * (1 - amount))
    b = int(b * (1 - amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_tokens(walked_nodes: list[dict]) -> dict:
    primary_counter: Counter = Counter()
    neutral_counter: Counter = Counter()

    for entry in walked_nodes:
        node = entry["node"]
        name_lower = (node.get("name") or "").lower()
        weight = 5 if "button" in name_lower else 1
        for fill in node.get("fills") or []:
            if fill.get("type") != "SOLID":
                continue
            color = fill.get("color") or {}
            hex_color = _rgb_to_hex(color)
            if _is_neutral(hex_color):
                neutral_counter[hex_color] += weight
            else:
                primary_counter[hex_color] += weight

    tokens: dict = {"color": {"primary": {}, "surface": {"0": "#fafbfc", "1": "#ffffff"}}}

    if primary_counter:
        primary_500, _ = primary_counter.most_common(1)[0]
        from services.color_theory import derive_scale
        tokens["color"]["primary"] = derive_scale(primary_500)

    if neutral_counter and "900" not in tokens["color"]["primary"]:
        tokens["color"]["primary"]["900"] = neutral_counter.most_common(1)[0][0]

    return tokens


_PX_TO_TW_SPACING = {0: "0", 1: "px", 2: "0.5", 4: "1", 6: "1.5", 8: "2",
                    10: "2.5", 12: "3", 14: "3.5", 16: "4", 20: "5", 24: "6",
                    28: "7", 32: "8", 40: "10", 48: "12", 64: "16"}


def _nearest_spacing(px: float) -> str:
    """Snap a pixel value to the nearest Tailwind spacing step. Returns the
    Tailwind suffix (e.g. '4' for p-4 → 16px)."""
    if not isinstance(px, (int, float)) or px <= 0:
        return "0"
    best_diff = float("inf")
    best = "4"
    for k, v in _PX_TO_TW_SPACING.items():
        d = abs(k - px)
        if d < best_diff:
            best_diff = d
            best = v
    return best


def _gradient_classes(node: dict) -> list[str]:
    """Emit `bg-gradient-to-{dir} from-[#hex] to-[#hex]` for a GRADIENT_LINEAR
    fill with at least two stops.

    Direction is inferred from the gradient handle positions:
      handle[0] → handle[1] defines the gradient vector
      |dy| > |dx| → vertical (to-b if dy > 0, to-t otherwise)
      else        → horizontal (to-r if dx > 0, to-l otherwise)

    Falls back to `to-b` when handles are missing (a vertical gradient is
    the most common case — hero panels, marketing CTA backgrounds).

    Returns [] for non-gradient or single-stop fills so the caller's
    `_first_solid_fill_hex` path still kicks in for those.
    """
    for fill in node.get("fills") or []:
        if fill.get("visible") is False:
            continue
        if fill.get("type") != "GRADIENT_LINEAR":
            continue
        stops = fill.get("gradientStops") or []
        if len(stops) < 2:
            continue
        start = stops[0].get("color") if isinstance(stops[0], dict) else None
        end = stops[-1].get("color") if isinstance(stops[-1], dict) else None
        if not (isinstance(start, dict) and isinstance(end, dict)):
            continue

        direction = "b"  # default top-to-bottom
        handles = fill.get("gradientHandlePositions") or []
        if len(handles) >= 2:
            h0 = handles[0] or {}
            h1 = handles[1] or {}
            dx = (h1.get("x") or 0) - (h0.get("x") or 0)
            dy = (h1.get("y") or 0) - (h0.get("y") or 0)
            if abs(dx) > abs(dy):
                direction = "r" if dx > 0 else "l"
            else:
                direction = "b" if dy > 0 else "t"

        return [
            f"bg-gradient-to-{direction}",
            f"from-[{_rgb_to_hex(start)}]",
            f"to-[{_rgb_to_hex(end)}]",
        ]
    return []


# Figma's auto-layout axis-alignment values → Tailwind utilities.
# Figma names the axes "primary" (the main flex axis — vertical for VERTICAL
# layoutMode, horizontal for HORIZONTAL) and "counter" (the perpendicular
# axis). Tailwind's flexbox names them "justify-*" (main) and "items-*"
# (cross). The mapping is direction-independent because flex utility names
# also flip semantics with direction.
_PRIMARY_AXIS_CLASS: dict[str, str] = {
    "MIN":           "justify-start",
    "CENTER":        "justify-center",
    "MAX":           "justify-end",
    "SPACE_BETWEEN": "justify-between",
}
_COUNTER_AXIS_CLASS: dict[str, str] = {
    "MIN":     "items-start",
    "CENTER":  "items-center",
    "MAX":     "items-end",
    "BASELINE": "items-baseline",
}


def _alignment_classes(node: dict) -> list[str]:
    """Emit justify-* / items-* from Figma's auto-layout axis alignments.

    Only fires for nodes with a real layoutMode (HORIZONTAL/VERTICAL) — those
    are the auto-layout frames where alignment is meaningful. Frames without
    auto-layout (layoutMode = NONE or unset) leave alignment to the bbox-
    based row inference path.
    """
    mode = node.get("_layoutMode")
    if mode not in ("HORIZONTAL", "VERTICAL"):
        return []
    out: list[str] = []
    primary = node.get("_primaryAxisAlignItems")
    counter = node.get("_counterAxisAlignItems")
    if isinstance(primary, str) and primary in _PRIMARY_AXIS_CLASS:
        out.append(_PRIMARY_AXIS_CLASS[primary])
    if isinstance(counter, str) and counter in _COUNTER_AXIS_CLASS:
        out.append(_COUNTER_AXIS_CLASS[counter])
    return out


def _rgba(color: dict) -> str:
    """Figma color (r/g/b/a as 0..1 floats) → CSS rgba(R, G, B, A) string."""
    r = max(0, min(255, int(round((color.get("r") or 0) * 255))))
    g = max(0, min(255, int(round((color.get("g") or 0) * 255))))
    b = max(0, min(255, int(round((color.get("b") or 0) * 255))))
    a = color.get("a")
    if a is None:
        a = 1.0
    # Round alpha to 2 decimals — keeps the class string readable.
    a_str = f"{a:.2f}".rstrip("0").rstrip(".") or "0"
    return f"rgba({r},{g},{b},{a_str})"


def _effect_classes(node: dict) -> list[str]:
    """Emit shadow / blur utilities from Figma's effects[] array.

    Handles three effect types per Figma's API:
      DROP_SHADOW    → shadow-[Xpx_Ypx_blurpx_spreadpx_rgba(...)]
      INNER_SHADOW   → shadow-[inset_Xpx_Ypx_blurpx_spreadpx_rgba(...)]
      LAYER_BLUR     → blur-[Npx]
      BACKGROUND_BLUR→ backdrop-blur-[Npx]

    Effects with visible=false are skipped. Multiple drop shadows merge
    into a single comma-separated shadow utility per CSS spec.
    """
    drop_shadows: list[str] = []
    inner_shadows: list[str] = []
    out: list[str] = []

    for eff in node.get("effects") or []:
        if not isinstance(eff, dict):
            continue
        if eff.get("visible") is False:
            continue
        etype = eff.get("type")
        if etype in ("DROP_SHADOW", "INNER_SHADOW"):
            color = eff.get("color") or {}
            offset = eff.get("offset") or {}
            radius = eff.get("radius") or 0
            spread = eff.get("spread") or 0
            x = int(round(offset.get("x") or 0))
            y = int(round(offset.get("y") or 0))
            blur = int(round(radius))
            sp = int(round(spread))
            parts = [f"{x}px", f"{y}px", f"{blur}px"]
            if sp:
                parts.append(f"{sp}px")
            parts.append(_rgba(color))
            shadow_value = "_".join(parts)
            if etype == "INNER_SHADOW":
                inner_shadows.append(f"inset_{shadow_value}")
            else:
                drop_shadows.append(shadow_value)
        elif etype == "LAYER_BLUR":
            radius = eff.get("radius")
            if isinstance(radius, (int, float)) and radius > 0:
                out.append(f"blur-[{int(round(radius))}px]")
        elif etype == "BACKGROUND_BLUR":
            radius = eff.get("radius")
            if isinstance(radius, (int, float)) and radius > 0:
                out.append(f"backdrop-blur-[{int(round(radius))}px]")

    # CSS shadow stacks combine via comma-separated values. Tailwind
    # arbitrary values support that via comma-with-no-spaces inside the
    # brackets, but the underscore-as-space convention requires we use a
    # single shadow- utility per stack. Emit one combined utility.
    combined = drop_shadows + inner_shadows
    if combined:
        out.append(f"shadow-[{','.join(combined)}]")
    return out


def _typography_extra_classes(node: dict) -> list[str]:
    """Emit `tracking-[Nem]` (letter-spacing) and `leading-[Npx]`
    (line-height) for TEXT nodes. Figma's text style block carries:
      letterSpacing: {value: float, unit: "PIXELS"|"PERCENT"}
                     OR sometimes just a bare float (pixels)
      lineHeightPx:  always pixels — the computed line height
      lineHeightUnit / lineHeightPercentFontSize: percent variants
                     (we prefer the absolute Px value when present)
    """
    if node.get("type") != "TEXT":
        return []
    out: list[str] = []
    style = node.get("style") or {}

    ls = style.get("letterSpacing")
    if isinstance(ls, dict):
        val = ls.get("value")
        unit = ls.get("unit")
        if isinstance(val, (int, float)) and abs(val) > 0.001:
            if unit == "PERCENT":
                # Percent letter-spacing → em (Figma percent is relative to
                # font size, which matches em semantics in CSS).
                em = round(val / 100.0, 4)
                out.append(f"tracking-[{em}em]")
            else:
                out.append(f"tracking-[{val}px]")
    elif isinstance(ls, (int, float)) and abs(ls) > 0.001:
        # Bare numeric letterSpacing — treat as pixels (Figma's older format).
        out.append(f"tracking-[{ls}px]")

    lh = style.get("lineHeightPx")
    if isinstance(lh, (int, float)) and lh > 0:
        out.append(f"leading-[{int(round(lh))}px]")
    return out


def _corner_radius_classes(node: dict) -> list[str]:
    """Emit per-corner radius utilities from rectangleCornerRadii[tl,tr,br,bl]
    when the corners differ. Returns one utility per corner that's > 0.

    Falls back to uniform `rounded-[Npx]` when all four corners equal but
    cornerRadius didn't set them (which the uniform-radius path further
    up already handles — this function is the asymmetric-corner case).
    """
    rcr = node.get("rectangleCornerRadii")
    if not isinstance(rcr, list) or len(rcr) != 4:
        return []
    tl, tr, br, bl = rcr
    if not all(isinstance(v, (int, float)) for v in (tl, tr, br, bl)):
        return []
    # All four equal — let the uniform cornerRadius path handle it.
    if tl == tr == br == bl:
        return []
    out: list[str] = []
    if tl > 0:
        out.append(f"rounded-tl-[{int(round(tl))}px]")
    if tr > 0:
        out.append(f"rounded-tr-[{int(round(tr))}px]")
    if br > 0:
        out.append(f"rounded-br-[{int(round(br))}px]")
    if bl > 0:
        out.append(f"rounded-bl-[{int(round(bl))}px]")
    return out


def _first_solid_fill_hex(node: dict) -> str | None:
    """Return the first visible fill colour as `#rrggbb`, or None.

    Handles three Figma fill types in priority order:
      1. SOLID — direct colour
      2. GRADIENT_LINEAR / GRADIENT_RADIAL — uses the first gradient stop's
         colour (approximates the gradient as a solid; designers often pick
         a subtle gradient over a base brand colour, so the first stop is a
         reasonable solid representation)
      3. IMAGE — skipped (no usable solid equivalent)
    """
    for fill in node.get("fills") or []:
        if fill.get("visible") is False:
            continue
        ft = fill.get("type") or ""
        if ft == "SOLID":
            color = fill.get("color")
            if isinstance(color, dict):
                return _rgb_to_hex(color)
            continue
        if ft.startswith("GRADIENT_"):
            for stop in fill.get("gradientStops") or []:
                color = (stop or {}).get("color")
                if isinstance(color, dict):
                    return _rgb_to_hex(color)
            continue
        # IMAGE / EMOJI / other types — no colour equivalent
    return None


def _first_solid_fill_opacity(node: dict) -> float:
    """Combined opacity of the first visible solid fill, * node.opacity.

    Figma stores fill alpha in three places:
      1. fill.opacity         — explicit per-fill alpha (most common when the
                                designer drops a colour to 15% on a hover chip)
      2. fill.color.a         — RGBA alpha baked into the colour
      3. node.opacity         — the layer's own opacity (multiplies through)

    Returns 1.0 when no opacity info is present so the existing `bg-[#hex]`
    path stays unchanged for fully-opaque fills.
    """
    layer = node.get("opacity")
    layer_a = float(layer) if isinstance(layer, (int, float)) else 1.0
    for fill in node.get("fills") or []:
        if fill.get("visible") is False:
            continue
        if fill.get("type") != "SOLID":
            continue
        fa = fill.get("opacity")
        ca = (fill.get("color") or {}).get("a")
        a = 1.0
        if isinstance(fa, (int, float)):
            a *= float(fa)
        if isinstance(ca, (int, float)):
            a *= float(ca)
        return max(0.0, min(1.0, a * layer_a))
    return max(0.0, min(1.0, layer_a))


def _sizing_classes(node: dict) -> list[str]:
    """Emit width / height / flex utilities driven by Figma's sizing
    semantics (FIXED / FILL / HUG) and the absoluteBoundingBox.

    Three modes per axis:
      - FIXED → `w-[Npx]` / `h-[Npx]` from the bbox so the node renders at
        the exact pixel size the designer set.
      - FILL  → `flex-1` (when inside an auto-layout parent) or `w-full`.
        Mapped to flex-1 so siblings share the row/column proportionally.
      - HUG / unset → no utility; the node grows with content.

    Skipped for TEXT nodes — text layout collapses to its character box
    naturally, and emitting `w-[Npx]` on a text wrapper truncates the run.
    """
    if node.get("type") == "TEXT":
        return []
    out: list[str] = []
    bbox = node.get("absoluteBoundingBox") or {}
    w = bbox.get("width"); h = bbox.get("height")
    hmode = node.get("_layoutSizingHorizontal")
    vmode = node.get("_layoutSizingVertical")
    grow = node.get("_layoutGrow")

    # Horizontal
    if hmode == "FIXED" and isinstance(w, (int, float)) and w > 0:
        out.append(f"w-[{int(round(w))}px]")
    elif hmode == "FILL" or grow == 1:
        out.append("flex-1")
    # HUG / unspecified → no class (default hug-content)

    # Vertical
    if vmode == "FIXED" and isinstance(h, (int, float)) and h > 0:
        # FRAME nodes are containers — use min-h so they hold the designer-
        # set height when content is sparse but GROW when content is rich.
        # Without this, a card with a fixed 419px height in Figma stays
        # locked at 419px in the rendered output even if only one row of
        # content extracted, producing huge empty boxes. RECTANGLE/VECTOR
        # leaves keep exact h-[Npx] (they're actual sized image assets).
        ftype = node.get("type")
        prefix = "min-h-" if ftype == "FRAME" else "h-"
        out.append(f"{prefix}[{int(round(h))}px]")
    elif vmode == "FILL":
        # On a row, vertical FILL means `self-stretch` (the parent already
        # gives the row its height). Plain h-full only works when the
        # parent has an explicit height.
        out.append("self-stretch")

    return out


def node_to_utility_classes(node: dict) -> list[str]:
    """Emit Tailwind utility classes for per-node styles that don't fit in
    tokens — radius, padding (equal axes get shorthand), gap, background /
    text colour, font-size and font-weight, plus explicit width / height
    from Figma's sizing semantics (FIXED / FILL / HUG).

    For TEXT nodes the first solid fill is treated as the text colour; for
    every other Figma type the fill is a background colour. Figma stores
    these as raw RGB floats, so the result is always an arbitrary-value
    Tailwind utility (`bg-[#hex]`, `text-[#hex]`) — the tailwind.config
    `content` glob already scans `output/**/*.json` so JIT emits a rule
    for any hex the schema references at runtime.
    """
    cls: list[str] = []

    # Sizing first so it's visible at the start of className strings.
    cls.extend(_sizing_classes(node))

    # Per-corner radius takes priority over uniform — only fires when the
    # four corners differ (rectangleCornerRadii). Uniform corners fall
    # through to the cornerRadius path below.
    per_corner = _corner_radius_classes(node)
    if per_corner:
        cls.extend(per_corner)
    else:
        r = node.get("cornerRadius")
        if isinstance(r, (int, float)) and r > 0:
            if r <= 4: cls.append("rounded-sm")
            elif r <= 8: cls.append("rounded-md")
            elif r <= 12: cls.append("rounded-lg")
            elif r <= 20: cls.append("rounded-xl")
            else: cls.append("rounded-2xl")

    pt = node.get("_paddingTop"); pb = node.get("_paddingBottom")
    pl = node.get("_paddingLeft"); pr = node.get("_paddingRight")
    if pt is not None and pb is not None and pt > 0 and pt == pb:
        cls.append(f"py-{_nearest_spacing(pt)}")
    elif pt is not None and pt > 0:
        cls.append(f"pt-{_nearest_spacing(pt)}")
    if pl is not None and pr is not None and pl > 0 and pl == pr:
        cls.append(f"px-{_nearest_spacing(pl)}")
    elif pl is not None and pl > 0:
        cls.append(f"pl-{_nearest_spacing(pl)}")

    gap = node.get("_itemSpacing")
    if isinstance(gap, (int, float)) and gap > 0:
        cls.append(f"gap-{_nearest_spacing(gap)}")

    # Auto-layout axis alignment — Figma's primary/counterAxisAlignItems
    # → Tailwind justify-*/items-*. Only fires for HORIZONTAL/VERTICAL
    # layoutMode frames where alignment is meaningful.
    cls.extend(_alignment_classes(node))

    # Gradient fill (GRADIENT_LINEAR) takes priority over solid extraction.
    # Common case: hero / marketing panels with a vertical fade. Emits
    # `bg-gradient-to-{b,t,r,l} from-[#hex] to-[#hex]`.
    if node.get("type") != "TEXT":
        grad = _gradient_classes(node)
        if grad:
            cls.extend(grad)

    # Fill colour — text-[#hex] for TEXT nodes, bg-[#hex] for everything else.
    # Figma represents text colour as a fill on the TEXT node itself. Only
    # emits bg-[#hex] when no gradient was already produced — gradient wins.
    #
    # White fills (#ffffff) ARE emitted now: dashboard pages typically have a
    # gray page bg with white cards on top — silently dropping the card's
    # white fill makes every card blend into the page. Tailwind's `bg-white`
    # is cheap so let it through.
    #
    # Fill opacity (per-fill, per-color-alpha, or layer opacity) is combined
    # and emitted as Tailwind's `/NN` suffix on arbitrary values — e.g. a 15%
    # teal icon chip renders as `bg-[#3dcbd2]/15`, keeping the icon stroke
    # visible against a soft tint instead of clashing on a solid swatch.
    hex_color = _first_solid_fill_hex(node)
    if hex_color:
        is_text = (node.get("type") == "TEXT")
        already_has_gradient = any(c.startswith("bg-gradient-") for c in cls)
        opacity = _first_solid_fill_opacity(node)
        # Snap opacity to the nearest Tailwind percent (5% granularity reads
        # cleanly in className strings without losing visual fidelity).
        op_pct = int(round(opacity * 100 / 5) * 5)
        op_suffix = "" if op_pct >= 100 else f"/{op_pct}"
        if is_text:
            cls.append(f"text-[{hex_color}]{op_suffix}")
        elif not already_has_gradient:
            cls.append(f"bg-[{hex_color}]{op_suffix}")

    # Typography utilities for TEXT nodes — pull font-size + weight off
    # node.style. These come from Figma's text style block (set by the
    # designer on each text layer). The walker preserves the raw `style`
    # field via dict() copy in figma_node_walker._annotate.
    if node.get("type") == "TEXT":
        style = node.get("style") or {}
        fs = style.get("fontSize")
        if isinstance(fs, (int, float)) and fs > 0:
            cls.append(f"text-[{int(round(fs))}px]")
        fw = style.get("fontWeight")
        if isinstance(fw, (int, float)):
            if fw >= 700:
                cls.append("font-bold")
            elif fw >= 600:
                cls.append("font-semibold")
            elif fw >= 500:
                cls.append("font-medium")
        # letterSpacing + lineHeightPx — finer typography metrics.
        cls.extend(_typography_extra_classes(node))

    # Effects (drop shadows, inner shadows, layer / backdrop blurs) emit
    # `shadow-[…]` and `blur-[…]` utilities so cards no longer look flat
    # and modal overlays carry their designer-set blur.
    cls.extend(_effect_classes(node))

    return cls
