"""The register's type ramp and depth ramp must reach a rendered page.

`look_scale` works out a modular type scale and a shadow ramp per application
and `project_design_tokens` writes them to `tokens.css`. Nothing read them.

Two causes, both measured on Claimsdesk (a freight-claims back-office built on
d2aa15b3, 2026-11-04):

1. The Tailwind config that SHIPS is `templates/standalone-app/tailwind.config.ts`
   — the later layer in `assembly._template_dirs()`, so it overwrites
   app-foundation's. It mapped `colors`, `fontFamily` and `borderRadius` and
   nothing else. `app-foundation/src/theme/tailwind-tokens.ts` has mapped
   `--shadow-*` since it was written; the copy that wins never did, so
   `shadow-md` was Tailwind's stock value in a `flat` console and a `dramatic`
   luxe product alike. `text-h1` was not a class at all.
2. tokens.css set the sizes on bare `h1/h2/h3`, which any `text-2xl` on the
   element beats on specificity — and 28 of Claimsdesk's 28 headings carried
   one, because `_look()` told the writer to pick the nearest `text-Nxl`.

So: the steps are named classes, the writer is told to ask by role, and a stated
`titleSize` is honoured instead of quietly replaced by the ramp's own h1.
"""
import re
from pathlib import Path

from services.blueprint import look_scale

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
SHIPPED = TEMPLATES / "standalone-app/tailwind.config.ts"
BASE = TEMPLATES / "app-foundation/src/theme/tailwind-tokens.ts"


def _vars(typography=None, elevation=None, colors=None):
    design = {"typography": typography or {}, "elevation": elevation,
              "colors": colors or {}}
    return dict(line.strip().rstrip(";").split(": ", 1)
                for line in look_scale.look_vars(design))


def _px(value: str) -> float:
    return round(float(value.removesuffix("rem")) * 16, 1)


# --- the classes exist, in the config that actually ships -------------------

def test_the_shipped_config_maps_the_type_ramp_and_the_depth_ramp():
    text = SHIPPED.read_text("utf-8")
    for key in ("fontSize:", "boxShadow:", "letterSpacing:", "spacing:"):
        assert key in text, f"{key} missing from the config that overwrites every other"
    for step in ("display", "h1", "h2", "h3", "body", "caption"):
        assert f"var(--text-{step}," in text, step
    for step in ("sm", "md", "lg", "xl"):
        assert f"var(--shadow-{step}," in text, step


def test_both_configs_name_the_same_steps():
    """The shipped copy is the third producer of this mapping and the one that
    fell behind; its own comment says so. Hold the two together."""
    shipped, base = SHIPPED.read_text("utf-8"), BASE.read_text("utf-8")
    for step in ("display", "h1", "h2", "h3", "body", "caption"):
        assert f"var(--text-{step}," in base, f"{step} missing from the base layer"
        assert f"var(--text-{step}," in shipped, f"{step} missing from the shipped layer"


def test_every_var_carries_a_fallback():
    """A bare `var()` with nothing behind it makes the whole declaration invalid
    at computed time, so a tree with no projected tokens would render with no
    shadow and no size at all (the lesson of the font-family fallback above it)."""
    text = SHIPPED.read_text("utf-8")
    bare = [m.group(0) for m in re.finditer(r"var\(--(?:text|shadow|tracking|space)-[\w-]+\)", text)]
    assert bare == [], bare


# --- and the ramp is worth reaching for -------------------------------------

def test_a_page_title_is_not_the_same_size_in_every_application():
    tight = _px(_vars({"scaleMode": "tight"})["--text-h1"])
    editorial = _px(_vars({"scaleMode": "editorial"})["--text-h1"])
    assert tight < 34 and editorial > 56, (tight, editorial)


def test_there_is_a_size_above_a_page_title():
    """`h1` was the top of the ramp, so a product whose type carries the page had
    nothing to carry it with."""
    for mode in ("tight", "comfortable", "expressive", "editorial"):
        v = _vars({"scaleMode": mode})
        assert _px(v["--text-display"]) > _px(v["--text-h1"]), mode
        assert _px(v["--text-display"]) <= 72, mode  # a title, not a poster


def test_the_heading_track_reaches_where_a_display_face_sits():
    """It ran -0.0089em to -0.0159em — narrower than Tailwind's own
    `tracking-tight` (-0.025em), so the register could not be seen in it."""
    def em(mode, key="--tracking-tight"):
        return float(_vars({"scaleMode": mode})[key].removesuffix("em"))
    assert em("editorial") < -0.03 < em("tight")
    assert em("editorial", "--tracking-display") < -0.045  # a designed display head


def test_a_stated_title_size_is_the_title_size():
    """The design agent is asked for `titleSize` in px and the ramp ignored it:
    an application could ask for 40px and be given 31px."""
    assert _px(_vars({"scaleMode": "tight", "titleSize": "40px"})["--text-h1"]) == 40
    assert _px(_vars({"scaleMode": "tight", "titleSize": "2.5rem"})["--text-h1"]) == 40
    # and nonsense leaves the ramp standing
    assert (_vars({"scaleMode": "tight", "titleSize": "big"})["--text-h1"]
            == _vars({"scaleMode": "tight"})["--text-h1"])


# --- depth carries the brand ------------------------------------------------

def test_the_rich_schemes_cast_the_brand_colour():
    """Neutral black under every app is the same depth tell the ramps were
    written to break."""
    clay = _vars(elevation={"scheme": "layered"}, colors={"primary": "#B5563C"})
    assert "rgb(181 86 60 /" in clay["--shadow-md"]
    plum = _vars(elevation={"scheme": "layered"}, colors={"primary": "#3D1566"})
    assert "rgb(61 21 102 /" in plum["--shadow-md"]
    assert clay["--shadow-md"] != plum["--shadow-md"]


def test_a_flat_tool_keeps_its_grey_and_the_design_overrules_either_way():
    assert "rgb(0 0 0 /" in _vars(elevation={"scheme": "flat"},
                                  colors={"primary": "#B5563C"})["--shadow-md"]
    assert "rgb(0 0 0 /" in _vars(elevation={"scheme": "layered", "tint": "neutral"},
                                  colors={"primary": "#B5563C"})["--shadow-md"]
    assert "rgb(181 86 60 /" in _vars(elevation={"scheme": "soft", "tint": "brand"},
                                      colors={"primary": "#B5563C"})["--shadow-md"]


def test_a_colour_that_is_not_one_leaves_the_ramp_alone():
    for colour in (None, "", "teal", "#12", "rgb(1,2,3)"):
        v = _vars(elevation={"scheme": "layered"}, colors={"primary": colour})
        assert "rgb(0 0 0 /" in v["--shadow-md"], colour


def test_an_explicit_shadow_still_wins_over_the_tint():
    v = _vars(elevation={"scheme": "layered", "sm": "none"}, colors={"primary": "#B5563C"})
    assert v["--shadow-sm"] == "none"


# --- and the writer is told -------------------------------------------------

def test_the_page_writer_is_told_to_ask_by_role():
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, _look
    assert "text-display" in DESIGN_PRINCIPLES and "text-caption" in DESIGN_PRINCIPLES
    look = _look({"designSystem": {"colors": {"primary": "#B5563C"},
                                   "typography": {"titleSize": "44px"}}})
    assert "`text-h1`" in look
    assert "text-4xl is 36px" not in look, "naming a px sends the writer to Tailwind's scale"


def test_the_design_agent_is_asked_for_a_corner_and_a_title_that_can_carry_a_page():
    from services.blueprint.executors import NODE_TASKS
    task = NODE_TASKS["design_system"]
    assert "28 to 64" in task, "the cap was 40px; no product could ask for a display title"
    assert "`radius`" in task, "radius had no guidance at all, so every app was cut the same"
    assert '"tint": "neutral"' in task


def test_an_escape_beside_a_value_is_caught_at_last():
    """The rule looked for `>…\\uXXXX…<` with no brace between the tags, and
    every real case has one: the escape sits beside a value. SnapIT's home read
    "app \\u2014 verified listings" (2026-10-01) and Stay's lead card
    "Nov 1 – Nov 1 \\u00b7 0 nights" (2026-11-04) with the rule in place both
    times."""
    from services.blueprint.ui_engineer import escaped_in_jsx_text

    assert escaped_in_jsx_text('<span>\\u00b7 {nightsLabel}</span>')
    assert escaped_in_jsx_text('<p>{a} \\u2014 verified listings</p>')
    assert escaped_in_jsx_text('<img alt="a \\u2014 b" />')
    assert escaped_in_jsx_text('<p>plain \\u20b9 text</p>')      # the old form still caught
    # a real JavaScript string is not JSX text
    assert not escaped_in_jsx_text('<p>{facts.join(" \\u00b7 ")}</p>')
    assert not escaped_in_jsx_text('const dash = `${a} \\u2013 ${b}`;')
    # and a whole component is not swallowed by the brace-stripping
    assert not escaped_in_jsx_text(
        'export function X({ a }: P) { return (<div><span>{a}</span></div>); }')
