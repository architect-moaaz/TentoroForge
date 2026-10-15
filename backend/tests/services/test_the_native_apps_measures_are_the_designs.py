"""The native app's measures - radii, spacing, shadows, type scale, hairline - are the design system's."""
from services.blueprint import native_engineer, native_projection, native_tokens as tk

DOC = {"designSystem": {
    "radius": {"sm": "8px", "md": "12px", "lg": "20px"},
    "spacing": {"space-1": "0.25rem", "space-2": "0.5rem", "space-3": "0.75rem", "space-4": "1rem",
                "space-6": "1.5rem", "space-8": "2rem", "page-padding": "1.25rem"},
    "elevation": {"shadow-sm": "0 1px 2px 0 rgba(15, 23, 42, 0.06)"},
    "informationDensity": "comfortable", "borders": {"border-width": "2px"},
    "typography": {"baseSize": "18px"},
}}


def test_radii_come_from_the_design_and_fall_back_to_the_kits():
    assert tk.radii(DOC) == {"sm": 8, "md": 12, "lg": 20}
    assert tk.radii({}) == tk.DEFAULT_RADII
    assert tk.radii({"designSystem": {"radius": "12px"}})["md"] == 12


def test_spacing_is_the_designs_scale_by_density():
    assert tk.spacing(DOC)["lg"] == 16 and tk.page_padding(DOC) == 20
    compact = {"designSystem": {**DOC["designSystem"], "informationDensity": "compact"}}
    assert tk.spacing(compact)["lg"] == 13
    assert tk.spacing({}) == tk.DEFAULT_SPACING


def test_a_box_shadow_becomes_a_native_shadow():
    s = tk.shadows(DOC)[1]
    assert s["shadowColor"] == "#0f172a" and s["shadowOpacity"] == 0.06 and s["shadowOffset"]["height"] == 1
    assert tk.shadows(DOC)[2] == tk.DEFAULT_SHADOWS[2]


def test_the_type_scale_and_hairline_follow_the_design():
    assert tk.type_scale(DOC) == 1.125 and tk.border_width(DOC) == 2
    assert tk.type_scale({}) == 1 and tk.border_width({}) == 1


def test_the_theme_module_carries_the_measures():
    out = native_projection.theme_module(DOC)
    for name in ("radii", "spacing", "pagePadding", "shadows", "typeScale", "borderWidth"):
        assert f"export const {name}" in out


def test_a_screen_with_invented_measures_is_refused():
    bad = ('import { Text } from "react-native";\n'
           'const s = { padding: 12, borderRadius: 8, fontSize: 14, shadowOpacity: 0.1 };\n')
    found = " ".join(native_engineer._native_findings(bad))
    for word in ("padding", "corner radius", "fontSize", "shadow", "Text"):
        assert word in found
    clean = native_engineer._native_findings("const s = { padding: space.md };\n")
    assert not [f for f in clean if "default export" not in f]


def test_headings_follow_the_design_and_default_to_the_kits_look():
    doc = {"designSystem": {"typography": {"headingWeight": "400", "headingColor": "primary", "titleSize": "36px"}}}
    assert tk.heading(doc) == {"weight": "regular", "tone": "primary", "titleSize": 36}
    assert tk.heading({}) == tk.DEFAULT_HEADING
    assert "export const heading" in native_projection.theme_module(doc)


def test_the_icon_is_the_first_letter_centred_on_the_primary_colour(tmp_path):
    from PIL import Image

    doc = {"application": {"name": "Crew Jobs"}, "designSystem": {"colors": {"primary": "#0f5a63"}}}
    native_projection._placeholder_icons(doc, tmp_path)
    for name in ("icon.png", "adaptive-icon.png"):
        img = Image.open(tmp_path / "assets" / name).convert("RGB")
        assert img.getpixel((4, 4)) == (15, 90, 99)
        box = img.point(lambda v: 255 if v > 200 else 0).convert("L").getbbox()
        assert abs((box[0] + box[2]) / 2 - 512) < 20 and abs((box[1] + box[3]) / 2 - 512) < 20
        assert (box[2] - box[0]) < 0.62 * 1024
