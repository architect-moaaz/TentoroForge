"""A company's design language, counted off its own rendered page.

The reading is deterministic and it is the part nobody can check by eye —
a palette that is silently one hue off is a palette every application
inherits. So these hold the reading to what the page actually stated.
"""
from __future__ import annotations

from services.brand_discovery import design as reader
from services.brand_discovery.site import Reading, _normalise_color, normalise_url
from services.brand_discovery.site import SiteUnreadable

import pytest


def _page(**counts) -> Reading:
    """A census, written the way a page would have produced one."""
    r = Reading(url="https://acme.test", rendered=True)
    for role, uses in counts.items():
        for value, n in uses:
            for _ in range(n):
                r.note(value, role)
    return r


def test_the_brand_is_the_colour_on_the_thing_a_page_wants_clicked():
    """A button's background is the least ambiguous statement a page makes —
    and it wins over a colour used twenty times as often somewhere else."""
    r = _page(
        action_bg=[("rgb(27,127,90)", 6)],
        background=[("#FFFFFF", 200), ("#F59E0B", 40)],
        text=[("#0F172A", 120)],
    )
    design, evidence = reader.design_system_from(r)
    assert design["colors"]["primary"] == "#1B7F5A"
    assert "background of its buttons" in evidence["brandFrom"]
    # White is the ground, slate is the ink, and the orange is the accent —
    # the second voice, not the brand.
    assert design["colors"]["background"] == "#FFFFFF"
    assert design["colors"]["foreground"] == "#0F172A"
    assert design["colors"]["accent"] == "#F59E0B"


def test_body_text_is_never_mistaken_for_a_second_brand_colour():
    """`#0F172A` is saturated enough to look like a colour and is the ink of
    half the web. An accent read off it would put slate on every button."""
    r = _page(
        action_bg=[("#1B7F5A", 6)],
        background=[("#FFFFFF", 200)],
        text=[("#0F172A", 300)],
    )
    design, _ = reader.design_system_from(r)
    assert design["colors"].get("accent") != "#0F172A"


def test_a_company_whose_buttons_are_black_has_said_what_its_brand_is():
    """The monochrome brand. Rejecting a dark button as "neutral" would send
    this down to the most-used-colour fallback, which on these sites returns
    whatever hue the illustrations happen to use."""
    r = _page(
        action_bg=[("rgb(0,0,0)", 9)],
        background=[("#FFFFFF", 150)],
        text=[("#111111", 90)],
    )
    design, _ = reader.design_system_from(r)
    assert design["colors"]["primary"] == "#000000"
    assert design["colors"]["primaryForeground"] == "#FFFFFF"
    # No derived accent: black has no hue to build a scheme around, and two
    # greys written here would overwrite a design agent's real choices.
    assert "accent" not in design["colors"]
    assert "secondary" not in design["colors"]


def test_a_light_brand_gets_dark_text_on_it():
    """Contrast is not a preference — the token contract's contrast edge
    rejects a primary whose foreground fails AA."""
    r = _page(action_bg=[("#FDE047", 8)], background=[("#FFFFFF", 100)])
    design, _ = reader.design_system_from(r)
    assert design["colors"]["primary"] == "#FDE047"
    assert design["colors"]["primaryForeground"] == "#0F172A"


def test_a_page_that_said_nothing_produces_nothing_to_say():
    """An empty reading must not assert that this company is flat, white and
    comfortable. A design decision made by a failed network request is worse
    than no design decision."""
    design, evidence = reader.design_system_from(Reading(url="https://acme.test"))
    assert design == {}
    assert "no colour" in evidence["brandFrom"]


def test_a_typeface_the_site_did_not_choose_is_not_a_typeface():
    """A stack of `sans-serif` is the absence of a choice. Recording it would
    override a design agent's considered face with nothing."""
    r = _page(action_bg=[("#1B7F5A", 5)])
    r.fonts.update(["sans-serif"] * 40)
    design, _ = reader.design_system_from(r)
    assert "typography" not in design

    r.fonts.update(["Inter"] * 12)
    r.heading_fonts.update(["Fraunces"] * 4)
    design, _ = reader.design_system_from(r)
    assert design["typography"] == {
        "fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces"}


def test_a_token_a_site_points_at_is_not_the_name_of_a_typeface():
    """A site built with Elementor hands back
    `var( --e-global-typography-text-font-family )` — itself pointing at a
    token, which resolves to nothing for a reader who never loaded that
    stylesheet. It was recorded as a family and shown to a new customer
    during onboarding as the font their company uses.

    The fallback inside a reference IS a name, and is taken."""
    from services.brand_discovery.site import _first_family

    assert _first_family("var( --e-global-typography-text-font-family )") == "sans-serif"
    assert _first_family("--brand-font") == "sans-serif"
    assert _first_family("var(--brand-font, Inter)") == "Inter"
    assert _first_family('var(--x, "Playfair Display", serif)') == "Playfair Display"
    assert _first_family('"Inter", -apple-system, sans-serif') == "Inter"

    # And nothing that names only a reference reaches the design system.
    r = _page(action_bg=[("#1B7F5A", 5)])
    r.fonts.update([_first_family("var( --e-global-typography-text-font-family )")] * 40)
    design, _ = reader.design_system_from(r)
    assert "typography" not in design


def test_the_corner_is_the_decision_not_the_hundred_elements_inheriting_it():
    """`0px` is every element nobody styled; it must not outvote the radius
    the site actually chose for its controls."""
    r = _page(action_bg=[("#1B7F5A", 5)])
    r.radii.update(["0px"] * 90 + ["8px"] * 30)
    design, _ = reader.design_system_from(r)
    assert design["radius"]["md"] == "8px"
    assert design["radius"]["sm"] == "4px" and design["radius"]["card"] == "12px"


def test_density_is_read_off_the_body_size():
    for size, expected in (("13px", "compact"), ("16px", "comfortable"),
                           ("19px", "spacious")):
        r = _page(action_bg=[("#1B7F5A", 5)])
        r.font_sizes.update([size] * 20)
        design, _ = reader.design_system_from(r)
        assert design["informationDensity"] == expected, size


def test_the_same_page_read_twice_is_the_same_design():
    """Two colours used the same number of times must not swap places between
    reads — the swap would rewrite the brand of every app built afterwards."""
    def build():
        return _page(action_bg=[("#1B7F5A", 4), ("#B71B5A", 4)],
                     background=[("#FFFFFF", 50)])
    first, _ = reader.design_system_from(build())
    second, _ = reader.design_system_from(build())
    assert first == second


def test_a_transparent_background_is_not_black():
    """`rgba(0,0,0,0)` is the computed background of most elements on most
    pages. Counting it would make black the ground of the whole internet."""
    assert _normalise_color("rgba(0, 0, 0, 0)") is None
    assert _normalise_color("transparent") is None
    assert _normalise_color("rgb(27, 127, 90)") == "#1B7F5A"
    assert _normalise_color("#1b7") == "#11BB77"
    assert _normalise_color("") is None


def test_the_url_a_form_supplies_cannot_read_this_machine():
    """The address comes from a text box, and a fetcher that will fetch
    anything it is given is a way to read the platform's own network."""
    assert normalise_url("acme.com") == "https://acme.com"
    assert normalise_url(" https://acme.com/about ") == "https://acme.com/about"
    for refused in ("http://localhost:6500", "http://127.0.0.1/admin",
                    "http://192.168.1.1", "http://10.0.0.4",
                    "file:///etc/passwd", "redis.internal", "", "notahost"):
        with pytest.raises(SiteUnreadable):
            normalise_url(refused)
