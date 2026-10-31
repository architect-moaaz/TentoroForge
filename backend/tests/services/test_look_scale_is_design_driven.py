"""Depth, type scale and motion follow the design — not one fixed default.

The point of `look_scale` is that two apps differ in depth and rhythm, not only
hue and typeface. These lock the contract the projector and the scaffold rely
on: the var NAMES, that a named scheme expands to a full set, that explicit
values win, and that `motion none` genuinely stops animation.
"""
from __future__ import annotations

from services.blueprint import look_scale


def _vars(lines: list[str]) -> dict[str, str]:
    out = {}
    for ln in lines:
        k, _, v = ln.strip().rstrip(";").partition(":")
        out[k.strip()] = v.strip()
    return out


def test_every_scheme_emits_the_full_shadow_ramp():
    for scheme in ("flat", "soft", "layered", "dramatic"):
        v = _vars(look_scale.elevation_vars(scheme))
        assert set(v) == {"--shadow-sm", "--shadow-md", "--shadow-lg", "--shadow-xl"}
        assert all(v.values())


def test_the_schemes_actually_differ_in_depth():
    flat = _vars(look_scale.elevation_vars("flat"))["--shadow-lg"]
    dramatic = _vars(look_scale.elevation_vars("dramatic"))["--shadow-lg"]
    assert flat != dramatic  # a flat app and a dramatic one are not the same depth


def test_an_unknown_or_missing_elevation_is_the_soft_default():
    assert look_scale.elevation_vars(None) == look_scale.elevation_vars("soft")
    assert look_scale.elevation_vars("nonsense") == look_scale.elevation_vars("soft")


def test_explicit_shadow_values_win_over_the_scheme():
    v = _vars(look_scale.elevation_vars({"scheme": "flat", "lg": "0 0 0 1px red"}))
    assert v["--shadow-lg"] == "0 0 0 1px red"
    assert v["--shadow-sm"] == _vars(look_scale.elevation_vars("flat"))["--shadow-sm"]


def test_type_scale_is_a_modular_ramp_bigger_ratio_bigger_h1():
    comfortable = _vars(look_scale.type_scale_vars({"scaleMode": "comfortable"}))
    editorial = _vars(look_scale.type_scale_vars({"scaleMode": "editorial"}))
    assert set(comfortable) >= {"--text-caption", "--text-body", "--text-h3", "--text-h2", "--text-h1", "--tracking-tight"}
    assert comfortable["--text-body"] == "1.0rem"
    # The editorial register gives a markedly larger display size than a dense one.
    h1 = lambda d: float(d["--text-h1"].rstrip("rem"))
    assert h1(editorial) > h1(comfortable) > 1.0


def test_base_size_in_px_anchors_the_body_rem():
    v = _vars(look_scale.type_scale_vars({"baseSize": "18px"}))
    assert v["--text-body"] == "1.125rem"  # 18/16


def test_explicit_scale_ratio_overrides_the_named_mode():
    v = _vars(look_scale.type_scale_vars({"scaleMode": "tight", "scaleRatio": "1.5"}))
    # h1 is base * 1.5**4
    assert abs(float(v["--text-h1"].rstrip("rem")) - 1.5 ** 4) < 1e-6


def test_motion_none_stops_animation():
    v = _vars(look_scale.motion_vars("none"))
    assert v["--motion-duration-fast"] == "0ms" and v["--motion-duration-normal"] == "0ms"
    assert v["--motion-level"] == "none"


def test_motion_expressive_is_longer_than_subtle():
    subtle = _vars(look_scale.motion_vars("subtle"))
    expressive = _vars(look_scale.motion_vars("expressive"))
    ms = lambda s: int(s.rstrip("ms"))
    assert ms(expressive["--motion-duration-normal"]) > ms(subtle["--motion-duration-normal"])


def test_look_vars_bundles_all_three_families():
    v = _vars(look_scale.look_vars({"elevation": "layered", "typography": {"scaleMode": "editorial"}, "motion": "expressive"}))
    assert "--shadow-md" in v and "--text-h1" in v and "--motion-easing" in v
