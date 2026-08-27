"""design_compiler radius scale: every app emits a curved (non-sharp) radius.scale
so surfaces never render with pointy corners, and the numeric radius is kept."""
import pytest

from services.design_compiler import _resolve_radius_scale, _map_radius


@pytest.mark.parametrize("register,expected", [
    ("workday", "soft"),   # sharp register floors to soft
    ("linear", "soft"),    # sharp register floors to soft
    ("stripe", "soft"),
    ("notion", "round"),   # round register preserved
    ("figma", "round"),
    ("unknown", "soft"),   # default
    ("", "soft"),
])
def test_scale_never_sharp(register, expected):
    assert _resolve_radius_scale({"register": register}) == expected


def test_explicit_override_wins():
    assert _resolve_radius_scale({"register": "workday", "radiusScale": "round"}) == "round"
    # ...but an explicit "sharp" still floors to soft.
    assert _resolve_radius_scale({"radiusScale": "sharp"}) == "soft"


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
