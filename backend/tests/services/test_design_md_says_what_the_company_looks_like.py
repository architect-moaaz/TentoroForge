"""design.md — generated from the profile, never authored beside it.

The document is what the agents are actually shown, so what it says has to be
what the structure holds. A renderer that drifts from the fields is a document
that tells a model the wrong colour while Settings shows the right one.
"""
from __future__ import annotations

import re

from services.brand_discovery import design_md


PROFILE = {
    "company_name": "Northwind",
    "source_url": "https://northwind.test",
    "identity": {
        "who_you_are": "A family bakery supplying cafes across the region.",
        "what_you_do": "We bake sourdough overnight and deliver it by six.",
        "how_you_do_it": "Long ferments, one bakery, no franchises.",
        "industry": "food production",
        "audience": "independent cafes",
        "tone": "plain, warm, unhurried",
        "voice": "Say it the way you'd say it across the counter.",
    },
    "design": {
        "colors": {"primary": "#1B7F5A", "accent": "#F59E0B",
                   "background": "#FFFFFF", "foreground": "#0F172A"},
        "typography": {"fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces"},
        "radius": {"md": "8px"},
        "elevation": {"md": "none"},
        "informationDensity": "spacious",
    },
    "evidence": {"rendered": True, "brandFrom": "the background of its buttons (6 elements)"},
}


def test_every_value_the_structure_holds_appears_in_the_document():
    out = design_md.render(PROFILE)
    for value in ("#1B7F5A", "#F59E0B", "#FFFFFF", "#0F172A",
                  "Inter", "Fraunces", "8px", "spacious", "Northwind"):
        assert value in out, value
    for sentence in PROFILE["identity"].values():
        assert sentence in out


def test_the_three_questions_are_the_document_s_spine():
    out = design_md.render(PROFILE)
    assert "Who they are" in out
    assert "What they do" in out
    assert "How they do it" in out


def test_a_number_says_where_it_came_from():
    """A palette nobody can argue with is a palette nobody can correct."""
    out = design_md.render(PROFILE)
    assert "the background of its buttons" in out
    assert "https://northwind.test" in out


def test_a_source_only_read_does_not_pass_itself_off_as_a_rendered_one():
    thin = {**PROFILE, "evidence": {**PROFILE["evidence"], "rendered": False}}
    out = design_md.render(thin)
    assert "could only be read as source" in out


def test_it_says_plainly_that_it_is_not_a_specification():
    """The failure this guards is a requirements agent turning "we bake
    sourdough" into a requirement that the application bake sourdough."""
    out = design_md.render(PROFILE)
    assert "says nothing about what the application DOES" in out


def test_an_empty_profile_says_the_design_is_open_rather_than_inventing_one():
    out = design_md.render({"company_name": "", "identity": {}, "design": {}})
    assert "Nothing could be read" in out
    assert "This company" in out
    # No invented hex anywhere: a heading's `#` is markdown, a colour's is a
    # decision, and this profile contains no decisions to state.
    assert not re.search(r"#[0-9a-fA-F]{6}\b", out)


def test_the_same_profile_renders_the_same_bytes():
    """Stored in the database and copied into every build: a renderer that
    produced a slightly different file each time would make every project's
    diff noise."""
    assert design_md.render(PROFILE) == design_md.render(PROFILE)
    assert design_md.render(PROFILE).endswith("\n")


def test_a_flat_company_and_a_lifted_one_read_differently():
    flat = design_md.render(PROFILE)
    assert "flat, separated by hairlines" in flat
    lifted = design_md.render({
        **PROFILE,
        "design": {**PROFILE["design"], "elevation": {"md": "0 4px 6px rgb(0 0 0 / .08)"}},
    })
    assert "lifted off the ground" in lifted


def test_a_square_cornered_company_is_described_as_one():
    square = design_md.render({
        **PROFILE, "design": {**PROFILE["design"], "radius": {"md": "0px"}}})
    assert "does not round its corners" in square
