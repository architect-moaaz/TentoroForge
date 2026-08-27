"""Unit tests for the Figma URL parser and design transformation utilities."""

import pytest

# These are pure functions — no DB or network needed
from figma_parser import (
    parse_figma_url,
    figma_color_to_css,
    figma_color_to_tailwind,
    map_layout_to_css,
    map_effects_to_css,
)


# ---------------------------------------------------------------------------
# parse_figma_url
# ---------------------------------------------------------------------------

class TestParseFigmaUrl:
    def test_file_url(self):
        result = parse_figma_url("https://www.figma.com/file/abc123/MyDesign")
        assert result["file_key"] == "abc123"
        assert result["node_id"] is None

    def test_design_url(self):
        result = parse_figma_url("https://www.figma.com/design/XYZ789/Dashboard")
        assert result["file_key"] == "XYZ789"
        assert result["node_id"] is None

    def test_with_node_id(self):
        result = parse_figma_url(
            "https://www.figma.com/design/abc123/Title?node-id=1-2"
        )
        assert result["file_key"] == "abc123"
        assert result["node_id"] == "1:2"  # dash → colon

    def test_with_node_id_and_extra_params(self):
        result = parse_figma_url(
            "https://www.figma.com/design/abc123/Title?node-id=10-20&t=xxx"
        )
        assert result["file_key"] == "abc123"
        assert result["node_id"] == "10:20"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid Figma URL"):
            parse_figma_url("https://example.com/not-figma")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError):
            parse_figma_url("")


# ---------------------------------------------------------------------------
# figma_color_to_css
# ---------------------------------------------------------------------------

class TestFigmaColorToCss:
    def test_opaque_color(self):
        result = figma_color_to_css({"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0})
        assert result == "#ff0000"

    def test_transparent_color(self):
        result = figma_color_to_css({"r": 0.0, "g": 0.0, "b": 1.0, "a": 0.5})
        assert result.startswith("rgba(")
        assert "0, 0, 255" in result

    def test_opacity_param(self):
        result = figma_color_to_css(
            {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}, opacity=0.5
        )
        assert "rgba(" in result

    def test_black(self):
        result = figma_color_to_css({"r": 0, "g": 0, "b": 0, "a": 1.0})
        assert result == "#000000"

    def test_white(self):
        result = figma_color_to_css({"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0})
        assert result == "#ffffff"


# ---------------------------------------------------------------------------
# figma_color_to_tailwind
# ---------------------------------------------------------------------------

class TestFigmaColorToTailwind:
    def test_pure_white(self):
        result = figma_color_to_tailwind({"r": 1.0, "g": 1.0, "b": 1.0})
        assert result == "white"

    def test_pure_black(self):
        result = figma_color_to_tailwind({"r": 0.0, "g": 0.0, "b": 0.0})
        assert result == "black"

    def test_close_to_blue_500(self):
        # blue-500 = #3b82f6 = (59, 130, 246)
        result = figma_color_to_tailwind(
            {"r": 59 / 255, "g": 130 / 255, "b": 246 / 255}
        )
        assert result == "blue-500"

    def test_arbitrary_color(self):
        # A color not close to any Tailwind shade
        result = figma_color_to_tailwind(
            {"r": 0.5, "g": 0.3, "b": 0.1}
        )
        assert result.startswith("[#")


# ---------------------------------------------------------------------------
# map_layout_to_css
# ---------------------------------------------------------------------------

class TestMapLayoutToCss:
    def test_no_layout(self):
        assert map_layout_to_css({}) == {}

    def test_vertical_layout(self):
        css = map_layout_to_css({"layoutMode": "VERTICAL", "itemSpacing": 8})
        assert css["display"] == "flex"
        assert css["flex-direction"] == "column"
        assert css["gap"] == "8px"

    def test_horizontal_layout(self):
        css = map_layout_to_css({"layoutMode": "HORIZONTAL"})
        assert css["flex-direction"] == "row"

    def test_padding(self):
        css = map_layout_to_css({
            "layoutMode": "VERTICAL",
            "paddingTop": 10,
            "paddingRight": 20,
            "paddingBottom": 10,
            "paddingLeft": 20,
        })
        assert css["padding"] == "10px 20px 10px 20px"

    def test_alignment(self):
        css = map_layout_to_css({
            "layoutMode": "HORIZONTAL",
            "primaryAxisAlignItems": "CENTER",
            "counterAxisAlignItems": "CENTER",
        })
        assert css["justify-content"] == "center"
        assert css["align-items"] == "center"


# ---------------------------------------------------------------------------
# map_effects_to_css
# ---------------------------------------------------------------------------

class TestMapEffectsToCss:
    def test_empty_effects(self):
        assert map_effects_to_css([]) == {}

    def test_drop_shadow(self):
        css = map_effects_to_css([{
            "type": "DROP_SHADOW",
            "visible": True,
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.25},
            "offset": {"x": 0, "y": 4},
            "radius": 8,
            "spread": 0,
        }])
        assert "box-shadow" in css
        assert "4px" in css["box-shadow"]

    def test_inner_shadow(self):
        css = map_effects_to_css([{
            "type": "INNER_SHADOW",
            "visible": True,
            "color": {"r": 0, "g": 0, "b": 0, "a": 0.1},
            "offset": {"x": 0, "y": 2},
            "radius": 4,
            "spread": 0,
        }])
        assert "inset" in css["box-shadow"]

    def test_layer_blur(self):
        css = map_effects_to_css([{
            "type": "LAYER_BLUR",
            "visible": True,
            "radius": 10,
        }])
        assert css["filter"] == "blur(10px)"

    def test_background_blur(self):
        css = map_effects_to_css([{
            "type": "BACKGROUND_BLUR",
            "visible": True,
            "radius": 20,
        }])
        assert css["backdrop-filter"] == "blur(20px)"

    def test_invisible_effect_ignored(self):
        css = map_effects_to_css([{
            "type": "DROP_SHADOW",
            "visible": False,
            "color": {"r": 0, "g": 0, "b": 0, "a": 1},
            "offset": {"x": 0, "y": 4},
            "radius": 8,
            "spread": 0,
        }])
        assert css == {}
