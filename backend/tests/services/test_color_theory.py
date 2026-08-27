"""Tests for color-theory-derived palette generation."""
from services.color_theory import derive_palette, DerivedPalette


def test_derive_palette_from_blue_primary():
    p = derive_palette("#0EA5E9")
    assert isinstance(p, DerivedPalette)
    for v in [p.primary, p.secondary, p.accent, p.background, p.surface,
              p.text_primary, p.text_secondary, p.border, p.success, p.warning, p.error]:
        assert v.startswith("#") and len(v) == 7


def test_derive_palette_keeps_primary_exact():
    p = derive_palette("#FF5733")
    assert p.primary.upper() == "#FF5733"


def test_derive_palette_text_primary_is_dark_on_light_bg():
    p = derive_palette("#0EA5E9")
    bg_r, bg_g, bg_b = int(p.background[1:3], 16), int(p.background[3:5], 16), int(p.background[5:7], 16)
    assert (bg_r + bg_g + bg_b) / 3 > 230  # near-white
    t_r, t_g, t_b = int(p.text_primary[1:3], 16), int(p.text_primary[3:5], 16), int(p.text_primary[5:7], 16)
    assert (t_r + t_g + t_b) / 3 < 40


def test_derive_palette_uses_provided_secondary_when_given():
    p = derive_palette("#FF5733", secondary_hint="#3366FF")
    assert p.secondary.upper() == "#3366FF"


def test_derive_palette_synthesizes_secondary_when_not_given():
    p = derive_palette("#FF5733")
    assert p.secondary.upper() != "#FF5733"


# ---------------------------------------------------------------------------
# derive_scale tests
# ---------------------------------------------------------------------------
from services.color_theory import derive_scale


def test_derive_scale_returns_11_steps():
    s = derive_scale("#10b981")
    expected = {"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"}
    assert set(s.keys()) == expected


def test_derive_scale_500_is_input():
    """The input hex IS the 500 step verbatim (lowercased)."""
    assert derive_scale("#10b981")["500"].lower() == "#10b981"


def test_derive_scale_monotonic_lightness():
    s = derive_scale("#10b981")
    def L(hex_color):
        h = hex_color.lstrip("#")
        return (int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)) / 3
    keys = ["50","100","200","300","400","500","600","700","800","900","950"]
    Ls = [L(s[k]) for k in keys]
    for i in range(len(Ls) - 1):
        assert Ls[i] > Ls[i+1], f"step {keys[i]}={s[keys[i]]} not lighter than {keys[i+1]}={s[keys[i+1]]}: Ls={Ls}"


def test_derive_scale_50_near_white():
    s = derive_scale("#10b981")
    h = s["50"].lstrip("#")
    total = int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)
    assert total > 720, f"50 too dark: {s['50']} sum={total}"


def test_derive_scale_950_near_black():
    s = derive_scale("#10b981")
    h = s["950"].lstrip("#")
    total = int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)
    assert total < 200, f"950 too light: {s['950']} sum={total}"


def test_derive_scale_preserves_hue():
    """Emerald input → G channel still dominant across the scale."""
    s = derive_scale("#10b981")
    for step in ["100", "300", "500", "700", "900"]:
        h = s[step].lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        assert g >= max(r, b) - 4, f"step {step}={s[step]}: G must dominate"


def test_derive_scale_neutral_input_stays_neutral():
    """Mid-grey input → channel spread stays tight throughout the scale."""
    s = derive_scale("#737373")
    assert len(s) == 11
    for k, v in s.items():
        h = v.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        spread = max(r, g, b) - min(r, g, b)
        assert spread < 30, f"step {k}={v}: not neutral (spread={spread})"


def test_derive_scale_accepts_uppercase_hex():
    s = derive_scale("#10B981")
    assert "500" in s
