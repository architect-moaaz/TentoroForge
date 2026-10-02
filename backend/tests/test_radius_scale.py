"""design_compiler radius scale: the register decides the corner family, an
explicit choice overrides it, and the numeric radius always carries its scale.

SHARP IS A REAL ANSWER NOW. This file used to say "every app emits a curved
(non-sharp) radius.scale" and asserted that a sharp register floored to soft.
That floor existed to mask a merge bug — `tokens.radius` was emitted without
its `scale`, so a sharp family rendered as pointy corners with nothing to say
otherwise. `compile()` always emits radius WITH its scale now, the floor was
removed, and squared corners are a deliberate part of the fintech, dev-tools,
logistics and legal archetypes. The floor's removal is the change; these tests
kept asserting the mask.
"""
import pytest

from services.design_compiler import _resolve_radius_scale, _map_radius


@pytest.mark.parametrize("register,expected", [
    ("workday", "sharp"),  # a sharp register stays sharp
    ("linear", "sharp"),
    ("stripe", "soft"),
    ("notion", "round"),
    ("figma", "round"),
    ("unknown", "soft"),   # default
    ("", "soft"),
])
def test_the_register_decides_the_corner_family(register, expected):
    assert _resolve_radius_scale({"register": register}) == expected


def test_explicit_override_wins():
    assert _resolve_radius_scale({"register": "workday", "radiusScale": "round"}) == "round"
    # ...including an explicit "sharp", which is no longer floored.
    assert _resolve_radius_scale({"radiusScale": "sharp"}) == "sharp"
    # A round register asked to be sharp is sharp: the override is the answer
    # whichever direction it points.
    assert _resolve_radius_scale({"register": "notion", "radiusScale": "sharp"}) == "sharp"


def test_a_nonsense_override_falls_back_to_the_register():
    """Only the three families are honoured; anything else is not a choice."""
    assert _resolve_radius_scale({"register": "linear", "radiusScale": "pointy"}) == "sharp"
    assert _resolve_radius_scale({"register": "notion", "radiusScale": ""}) == "round"


def test_the_scale_always_travels_with_the_numbers():
    """The fix that made the floor unnecessary: radius is never emitted without
    the family that says how to read it."""
    for scale in ("sharp", "soft", "round"):
        assert _map_radius({}, scale=scale)["scale"] == scale


def test_map_radius_always_carries_scale_and_numeric():
    out = _map_radius({"lg": "1rem"}, scale="round")
    assert out["scale"] == "round"
    assert out["lg"] == "1rem"            # spec value preserved
    assert out["md"] == "0.5rem"          # default filled in
    assert set(out) >= {"sm", "md", "lg", "xl", "full", "scale"}


def test_map_radius_empty_spec_still_complete():
    out = _map_radius({}, scale="soft")
    assert out["scale"] == "soft"
    assert out["md"] == "0.5rem"
