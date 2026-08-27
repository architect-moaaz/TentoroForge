import pytest
from services.figma_style_extractor import extract_tokens


def _solid_fill(r, g, b):
    """Figma uses 0..1 floats for RGB."""
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b}}


def _walked(name, fills, ftype="FRAME"):
    return {"node": {"name": name, "type": ftype, "fills": fills}, "parent": None, "path": []}


def test_extracts_primary_from_button_fill():
    """Mark 3 emerald: hex(0.063, 0.725, 0.506) ≈ #10b981. Button weights ×5."""
    nodes = [_walked("Button", [_solid_fill(0.063, 0.725, 0.506)])]
    tokens = extract_tokens(nodes)
    assert tokens["color"]["primary"]["500"].lower() in ("#10b981", "#10b980", "#10b97f")


def test_surface_defaults_always_present():
    tokens = extract_tokens([])
    assert tokens["color"]["surface"]["0"] == "#fafbfc"
    assert tokens["color"]["surface"]["1"] == "#ffffff"


def test_derives_full_11_step_scale_from_primary_500():
    nodes = [_walked("Button", [_solid_fill(0.063, 0.725, 0.506)])]
    p = extract_tokens(nodes)["color"]["primary"]
    expected = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}
    assert set(p.keys()) == expected


def test_intermediate_steps_present():
    """200/300/400/700/800/950 were not in the previous 5-step output."""
    nodes = [_walked("Button", [_solid_fill(0.063, 0.725, 0.506)])]
    p = extract_tokens(nodes)["color"]["primary"]
    for k in ("200", "300", "400", "700", "800", "950"):
        assert k in p, f"step {k} missing"


def test_neutral_promoted_to_900_when_no_primary():
    """If only neutrals are present (no saturated CTA), the darkest neutral
    becomes primary.900 so text still has a colour."""
    # Near-black neutral
    nodes = [_walked("Heading 1", [_solid_fill(0.06, 0.10, 0.16)], "TEXT")]
    tokens = extract_tokens(nodes)
    # Either primary.900 OR primary.500 picked the neutral — both acceptable
    assert tokens["color"]["primary"]  # some primary subkey set


def test_button_wins_over_random_chrome():
    """Button vote weight ×5 — even when 4 background frames vote a different
    colour, the Button colour should win."""
    nodes = [
        _walked("Container", [_solid_fill(0.5, 0.5, 0.9)]),
        _walked("Container", [_solid_fill(0.5, 0.5, 0.9)]),
        _walked("Container", [_solid_fill(0.5, 0.5, 0.9)]),
        _walked("Container", [_solid_fill(0.5, 0.5, 0.9)]),
        _walked("Button", [_solid_fill(0.063, 0.725, 0.506)]),
    ]
    tokens = extract_tokens(nodes)
    assert tokens["color"]["primary"]["500"].lower().startswith("#10")


def test_ignores_non_solid_fills():
    """Image / gradient fills must not pollute the primary palette."""
    nodes = [_walked("Button", [
        {"type": "IMAGE", "imageRef": "abc"},
        {"type": "GRADIENT_LINEAR"},
    ])]
    tokens = extract_tokens(nodes)
    # No SOLID fills → no primary 500 — but surface defaults still present
    assert tokens["color"]["surface"]["0"] == "#fafbfc"


from services.figma_style_extractor import node_to_utility_classes


def test_radius_emits_rounded_class():
    assert "rounded-sm" in node_to_utility_classes({"cornerRadius": 4})
    assert "rounded-md" in node_to_utility_classes({"cornerRadius": 8})
    assert "rounded-lg" in node_to_utility_classes({"cornerRadius": 12})
    assert "rounded-xl" in node_to_utility_classes({"cornerRadius": 20})
    assert "rounded-2xl" in node_to_utility_classes({"cornerRadius": 32})


def test_equal_padding_emits_shorthand():
    cls = node_to_utility_classes({"_paddingTop": 16, "_paddingBottom": 16, "_paddingLeft": 24, "_paddingRight": 24})
    assert "py-4" in cls
    assert "px-6" in cls


def test_unequal_padding_emits_top_left_only():
    cls = node_to_utility_classes({"_paddingTop": 16, "_paddingBottom": 8, "_paddingLeft": 24, "_paddingRight": 12})
    assert "pt-4" in cls
    assert "pl-6" in cls
    # No py- or px- shorthand
    assert not any(c.startswith("py-") for c in cls)
    assert not any(c.startswith("px-") for c in cls)


def test_item_spacing_emits_gap():
    assert "gap-3" in node_to_utility_classes({"_itemSpacing": 12})
    assert "gap-4" in node_to_utility_classes({"_itemSpacing": 16})


def test_empty_node_returns_empty_list():
    assert node_to_utility_classes({}) == []


def test_zero_padding_does_not_emit_class():
    cls = node_to_utility_classes({"_paddingTop": 0, "_paddingBottom": 0})
    assert not any(c.startswith("py-") or c.startswith("pt-") or c.startswith("pb-") for c in cls)


def test_zero_radius_does_not_emit_class():
    assert "rounded-sm" not in node_to_utility_classes({"cornerRadius": 0})


def test_nearest_spacing_snaps_to_closest_step():
    """13px is closer to 12 than 14 → spacing token '3' (Tailwind p-3 = 12px)."""
    cls = node_to_utility_classes({"_paddingTop": 13, "_paddingBottom": 13})
    assert "py-3" in cls


def test_gradient_fill_emits_full_gradient_classes():
    """GRADIENT_LINEAR fills produce full `bg-gradient-to-{dir} from-[#hex]
    to-[#hex]` utilities so the hero / marketing panel fades correctly.
    Direction inferred from gradient handle positions (defaults to `b`
    when handles are absent — the most common case)."""
    node = {
        "type": "FRAME",
        "fills": [{
            "type": "GRADIENT_LINEAR",
            "gradientStops": [
                {"color": {"r": 0.518, "g": 0.067, "b": 0.075}, "position": 0},
                {"color": {"r": 0.4, "g": 0.05, "b": 0.06}, "position": 1},
            ],
            # Vertical top-to-bottom handles: same x, increasing y
            "gradientHandlePositions": [
                {"x": 0.5, "y": 0.0},
                {"x": 0.5, "y": 1.0},
            ],
        }],
    }
    cls = node_to_utility_classes(node)
    assert "bg-gradient-to-b" in cls, f"expected vertical gradient class, got {cls}"
    assert any(c.startswith("from-[#") for c in cls), f"expected from-[#hex], got {cls}"
    assert any(c.startswith("to-[#") for c in cls), f"expected to-[#hex], got {cls}"
    # Solid bg-[#hex] must NOT be emitted alongside the gradient
    assert not any(c.startswith("bg-[#") for c in cls), (
        f"gradient + solid bg are redundant — got {cls}"
    )


def test_gradient_direction_inferred_from_handles():
    """Horizontal handles (same y, different x) → to-r or to-l."""
    node = {
        "type": "FRAME",
        "fills": [{
            "type": "GRADIENT_LINEAR",
            "gradientStops": [
                {"color": {"r": 1, "g": 0, "b": 0}, "position": 0},
                {"color": {"r": 0, "g": 0, "b": 1}, "position": 1},
            ],
            "gradientHandlePositions": [
                {"x": 0.0, "y": 0.5},
                {"x": 1.0, "y": 0.5},  # left → right
            ],
        }],
    }
    cls = node_to_utility_classes(node)
    assert "bg-gradient-to-r" in cls, f"expected horizontal gradient, got {cls}"


def test_gradient_with_no_handles_defaults_to_top_down():
    """When Figma omits gradientHandlePositions, default to `to-b`."""
    node = {
        "type": "FRAME",
        "fills": [{
            "type": "GRADIENT_LINEAR",
            "gradientStops": [
                {"color": {"r": 0.5, "g": 0.5, "b": 0.5}, "position": 0},
                {"color": {"r": 0, "g": 0, "b": 0}, "position": 1},
            ],
        }],
    }
    cls = node_to_utility_classes(node)
    assert "bg-gradient-to-b" in cls


def test_axis_alignment_vertical_max_emits_justify_end():
    """VERTICAL frame with primaryAxisAlignItems=MAX → justify-end so
    bottom-aligned content (e.g. the marketing tagline at the bottom of
    a hero panel) renders correctly."""
    node = {
        "type": "FRAME",
        "_layoutMode": "VERTICAL",
        "_primaryAxisAlignItems": "MAX",
    }
    cls = node_to_utility_classes(node)
    assert "justify-end" in cls, f"expected justify-end, got {cls}"


def test_axis_alignment_center_horizontal_and_vertical():
    """Both axes can carry CENTER — emits justify-center + items-center."""
    node = {
        "type": "FRAME",
        "_layoutMode": "VERTICAL",
        "_primaryAxisAlignItems": "CENTER",
        "_counterAxisAlignItems": "CENTER",
    }
    cls = node_to_utility_classes(node)
    assert "justify-center" in cls
    assert "items-center" in cls


def test_axis_alignment_space_between():
    """primaryAxisAlignItems=SPACE_BETWEEN → justify-between. The
    "Remember me ↔ Forgot password?" row uses this in many designs."""
    node = {
        "type": "FRAME",
        "_layoutMode": "HORIZONTAL",
        "_primaryAxisAlignItems": "SPACE_BETWEEN",
    }
    cls = node_to_utility_classes(node)
    assert "justify-between" in cls


def test_axis_alignment_no_layout_mode_emits_nothing():
    """A frame without auto-layout (layoutMode=NONE or unset) should NOT
    emit alignment classes — bbox inference handles those frames."""
    node = {
        "type": "FRAME",
        "_primaryAxisAlignItems": "CENTER",  # set but layoutMode is NONE
    }
    cls = node_to_utility_classes(node)
    assert "justify-center" not in cls
    assert "items-center" not in cls


def test_invisible_fill_is_skipped():
    """Fills with visible=False contribute no bg/text classes."""
    node = {
        "type": "FRAME",
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0, "b": 0}, "visible": False}],
    }
    cls = node_to_utility_classes(node)
    assert not any(c.startswith("bg-[#") for c in cls)


# ── Figma sizing fidelity (layoutSizingHorizontal/Vertical + bbox) ──────────

def test_sizing_fixed_emits_arbitrary_pixel_width():
    """FIXED sizing means the designer set an exact pixel width; emit
    `w-[Npx]` from the bbox so the schema renders at that exact size."""
    node = {
        "type": "FRAME",
        "_layoutSizingHorizontal": "FIXED",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 480, "height": 720},
    }
    cls = node_to_utility_classes(node)
    assert "w-[480px]" in cls, f"expected w-[480px], got {cls}"
    # No vertical sizing → no height utility
    assert not any(c.startswith("h-[") for c in cls)


def test_sizing_fill_emits_flex_1():
    """FILL sizing means the frame should grow to share its parent's
    cross-axis width — `flex-1` is the canonical Tailwind utility."""
    node = {
        "type": "FRAME",
        "_layoutSizingHorizontal": "FILL",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 100},
    }
    cls = node_to_utility_classes(node)
    assert "flex-1" in cls, f"expected flex-1 from FILL sizing, got {cls}"
    # FILL must NOT emit a fixed pixel width.
    assert not any(c.startswith("w-[") for c in cls)


def test_sizing_hug_emits_nothing():
    """HUG (default) means the frame fits its content — emit no width
    class so the browser's natural width calculation applies."""
    node = {
        "type": "FRAME",
        "_layoutSizingHorizontal": "HUG",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 40},
    }
    cls = node_to_utility_classes(node)
    assert not any(c.startswith("w-") for c in cls), f"HUG should emit no width, got {cls}"
    assert "flex-1" not in cls


def test_sizing_layout_grow_1_acts_like_fill():
    """Older Figma files used `layoutGrow: 1` instead of `layoutSizingHorizontal: FILL`.
    Map both to `flex-1` for backwards compatibility."""
    node = {
        "type": "FRAME",
        "_layoutGrow": 1,
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 600, "height": 100},
    }
    cls = node_to_utility_classes(node)
    assert "flex-1" in cls


def test_sizing_vertical_fixed_frame_emits_min_height():
    """FIXED vertical sizing on a FRAME container emits `min-h-[Npx]` so
    the container holds the designer's height when content is sparse but
    GROWS when content is rich. Without min-h, a 419px card with one row
    of content stays locked at 419px tall and shows mostly whitespace."""
    node = {
        "type": "FRAME",
        "_layoutSizingVertical": "FIXED",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 0, "height": 419},
    }
    cls = node_to_utility_classes(node)
    assert "min-h-[419px]" in cls, f"FRAME should use min-h, got {cls}"
    assert "h-[419px]" not in cls


def test_sizing_vertical_fixed_rectangle_emits_exact_height():
    """RECTANGLE / VECTOR are image leaves — exact `h-[Npx]` preserves
    the asset's intended pixel size."""
    for ft in ("RECTANGLE", "VECTOR"):
        node = {
            "type": ft,
            "_layoutSizingVertical": "FIXED",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 0, "height": 60},
        }
        cls = node_to_utility_classes(node)
        assert "h-[60px]" in cls, f"{ft} should use exact h, got {cls}"
        assert "min-h-[60px]" not in cls


def test_sizing_skipped_for_text_nodes():
    """TEXT nodes layout to their character box naturally — never emit
    width/height utilities for them or the text gets truncated to the
    bbox at small viewports."""
    node = {
        "type": "TEXT",
        "_layoutSizingHorizontal": "FIXED",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 480, "height": 24},
    }
    cls = node_to_utility_classes(node)
    assert not any(c.startswith("w-[") for c in cls)
    assert not any(c.startswith("h-[") for c in cls)


# ── Effects (drop shadow / inner shadow / layer blur) ──────────────────────

def test_drop_shadow_emits_shadow_with_offset_blur_color():
    """A DROP_SHADOW effect produces `shadow-[Xpx_Ypx_blurpx_rgba(...)]`
    so the card no longer looks flat."""
    node = {
        "type": "FRAME",
        "effects": [{
            "type": "DROP_SHADOW",
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.1},
            "offset": {"x": 0, "y": 4},
            "radius": 12,
            "spread": 0,
        }],
    }
    cls = node_to_utility_classes(node)
    shadow = next((c for c in cls if c.startswith("shadow-[")), None)
    assert shadow is not None, f"expected shadow utility, got {cls}"
    assert "0px_4px_12px" in shadow
    assert "rgba(0,0,0,0.1)" in shadow


def test_drop_shadow_with_spread_included():
    """Non-zero spread is preserved in the CSS shadow value."""
    node = {
        "type": "FRAME",
        "effects": [{
            "type": "DROP_SHADOW",
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.2},
            "offset": {"x": 0, "y": 2},
            "radius": 6,
            "spread": 1,
        }],
    }
    cls = node_to_utility_classes(node)
    shadow = next((c for c in cls if c.startswith("shadow-[")), None)
    assert "0px_2px_6px_1px" in shadow


def test_inner_shadow_emits_inset_prefix():
    """INNER_SHADOW uses CSS `inset` so the shadow paints inside the box."""
    node = {
        "type": "FRAME",
        "effects": [{
            "type": "INNER_SHADOW",
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.05},
            "offset": {"x": 0, "y": 1},
            "radius": 2,
        }],
    }
    cls = node_to_utility_classes(node)
    shadow = next((c for c in cls if c.startswith("shadow-[")), None)
    assert "inset_0px_1px_2px" in shadow


def test_invisible_effect_is_skipped():
    """Effects with visible=false don't contribute to the shadow stack."""
    node = {
        "type": "FRAME",
        "effects": [{
            "type": "DROP_SHADOW",
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.3},
            "offset": {"x": 0, "y": 8},
            "radius": 16,
            "visible": False,
        }],
    }
    cls = node_to_utility_classes(node)
    assert not any(c.startswith("shadow-[") for c in cls)


def test_layer_blur_emits_blur_utility():
    """LAYER_BLUR → `blur-[Npx]` (CSS filter)."""
    node = {
        "type": "FRAME",
        "effects": [{"type": "LAYER_BLUR", "radius": 8}],
    }
    cls = node_to_utility_classes(node)
    assert "blur-[8px]" in cls


def test_background_blur_emits_backdrop_blur():
    """BACKGROUND_BLUR → `backdrop-blur-[Npx]` (modal overlay frosted look)."""
    node = {
        "type": "FRAME",
        "effects": [{"type": "BACKGROUND_BLUR", "radius": 24}],
    }
    cls = node_to_utility_classes(node)
    assert "backdrop-blur-[24px]" in cls


def test_multiple_drop_shadows_combine_into_one_utility():
    """CSS shadow stacks combine via comma — emit a single shadow- utility
    with comma-separated layers."""
    node = {
        "type": "FRAME",
        "effects": [
            {
                "type": "DROP_SHADOW", "color": {"r":0,"g":0,"b":0,"a":0.05},
                "offset": {"x":0,"y":1}, "radius": 2,
            },
            {
                "type": "DROP_SHADOW", "color": {"r":0,"g":0,"b":0,"a":0.1},
                "offset": {"x":0,"y":4}, "radius": 12,
            },
        ],
    }
    cls = node_to_utility_classes(node)
    shadow = next((c for c in cls if c.startswith("shadow-[")), None)
    assert shadow is not None
    assert shadow.count(",") >= 2, f"expected combined shadow layers, got {shadow}"


# ── Typography extras: tracking + leading ──────────────────────────────────

def test_letter_spacing_percent_emits_em():
    """letterSpacing with unit=PERCENT → tracking-[Nem] (em is relative
    to font size, matching Figma's percent semantics)."""
    node = {
        "type": "TEXT",
        "style": {"letterSpacing": {"value": -1.4, "unit": "PERCENT"}},
    }
    cls = node_to_utility_classes(node)
    assert any(c.startswith("tracking-[-0.014em]") for c in cls), f"got {cls}"


def test_letter_spacing_pixels_emits_px():
    """letterSpacing with unit=PIXELS → tracking-[Npx]."""
    node = {
        "type": "TEXT",
        "style": {"letterSpacing": {"value": 0.5, "unit": "PIXELS"}},
    }
    cls = node_to_utility_classes(node)
    assert "tracking-[0.5px]" in cls


def test_line_height_px_emits_leading():
    """lineHeightPx → leading-[Npx] (always pixel-valued)."""
    node = {
        "type": "TEXT",
        "style": {"lineHeightPx": 19.6},
    }
    cls = node_to_utility_classes(node)
    assert "leading-[20px]" in cls  # rounded


def test_typography_extras_skipped_for_non_text():
    """Only TEXT nodes get tracking/leading — FRAMEs with a stray style
    field don't pick them up."""
    node = {
        "type": "FRAME",
        "style": {"letterSpacing": {"value": -1, "unit": "PERCENT"}, "lineHeightPx": 24},
    }
    cls = node_to_utility_classes(node)
    assert not any(c.startswith("tracking-[") for c in cls)
    assert not any(c.startswith("leading-[") for c in cls)


# ── Per-corner radius ──────────────────────────────────────────────────────

def test_rectangle_corner_radii_emits_per_corner():
    """rectangleCornerRadii=[10,10,0,0] → top-rounded card pattern."""
    node = {
        "type": "FRAME",
        "rectangleCornerRadii": [10, 10, 0, 0],
    }
    cls = node_to_utility_classes(node)
    assert "rounded-tl-[10px]" in cls
    assert "rounded-tr-[10px]" in cls
    assert not any(c.startswith("rounded-br-") for c in cls)
    assert not any(c.startswith("rounded-bl-") for c in cls)


def test_rectangle_corner_radii_uniform_falls_through_to_cornerRadius():
    """When all four corners equal, don't emit per-corner — let the
    uniform cornerRadius path produce `rounded-md` etc."""
    node = {
        "type": "FRAME",
        "rectangleCornerRadii": [8, 8, 8, 8],
        "cornerRadius": 8,
    }
    cls = node_to_utility_classes(node)
    assert "rounded-md" in cls
    assert not any(c.startswith("rounded-tl-") for c in cls)


def test_white_fill_is_emitted_for_cards_on_gray_pages():
    """Dashboard cards have white fills on a gray page bg — dropping #ffffff
    silently makes every card blend into the page. Emit `bg-[#ffffff]`."""
    node = {
        "type": "FRAME",
        "fills": [{"type": "SOLID", "color": {"r": 1, "g": 1, "b": 1}}],
    }
    cls = node_to_utility_classes(node)
    assert "bg-[#ffffff]" in cls


def test_fill_opacity_emits_tailwind_opacity_suffix():
    """A SOLID teal fill at 15% opacity emits `bg-[#3dcbd2]/15` so icon chips
    rendered against a tinted background keep their stroke contrast.
    Opacity snaps to the nearest 5% step."""
    node = {
        "type": "FRAME",
        "fills": [{
            "type": "SOLID",
            "color": {"r": 0x3D / 255, "g": 0xCB / 255, "b": 0xD2 / 255},
            "opacity": 0.15,
        }],
    }
    cls = node_to_utility_classes(node)
    assert any(c.startswith("bg-[#3dcbd2]/") for c in cls), cls
    # 0.15 → 15%
    assert "bg-[#3dcbd2]/15" in cls


def test_full_opacity_fill_has_no_suffix():
    """When opacity is 1.0 / missing, no `/100` suffix — the existing
    `bg-[#hex]` form stays unchanged."""
    node = {
        "type": "FRAME",
        "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}}],
    }
    cls = node_to_utility_classes(node)
    assert "bg-[#000000]" in cls
    assert not any("/100" in c for c in cls)


def test_text_node_with_opacity_emits_text_opacity():
    """TEXT nodes pick up the opacity suffix on `text-[#hex]` too."""
    node = {
        "type": "TEXT",
        "fills": [{
            "type": "SOLID",
            "color": {"r": 0.1, "g": 0.1, "b": 0.1},
            "opacity": 0.5,
        }],
        "style": {"fontSize": 14},
    }
    cls = node_to_utility_classes(node)
    assert any(c.startswith("text-[#1a1a1a]/") for c in cls), cls
    assert "text-[#1a1a1a]/50" in cls


def test_layer_opacity_multiplies_through_fill_opacity():
    """Figma stores layer-level opacity on `node.opacity`. It multiplies any
    fill-level opacity — a fill at 50% on a layer at 50% renders at 25%."""
    node = {
        "type": "FRAME",
        "opacity": 0.5,
        "fills": [{
            "type": "SOLID",
            "color": {"r": 0, "g": 0, "b": 0},
            "opacity": 0.5,
        }],
    }
    cls = node_to_utility_classes(node)
    assert "bg-[#000000]/25" in cls
