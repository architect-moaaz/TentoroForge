"""The tokens the sign-in page paints with must arrive in the form it reads.

`tokens.css` is where the design system becomes CSS variables, and the
scaffold's sign-in page reads three of them in ways that fail silently when
the form is wrong: `hsl(var(--accent))` needs a bare HSL triplet, not hex; and
`var(--font-heading)` needs to exist at all. A hex accent produced
`hsl(#c9a84c)` — invalid, dropped, fallback grey — and no `--font-heading`
was ever emitted, so a design's serif headings became system-ui everywhere.
Both bugs left the page looking unrelated to the design it was generated from.
"""
from services.blueprint.projection import project_design_tokens


def _css(tmp_path, design):
    project_design_tokens({"designSystem": design}, tmp_path)
    return (tmp_path / "src" / "app" / "tokens.css").read_text()


def test_the_accent_is_an_hsl_triplet(tmp_path):
    css = _css(tmp_path, {"colors": {"accent": "#c9a84c", "primary": "#c9a84c"}})
    line = next(l for l in css.splitlines() if l.strip().startswith("--accent:"))
    assert "#" not in line and "%" in line, line


def test_every_scaffold_wrapped_role_is_a_triplet(tmp_path):
    roles = ["background", "foreground", "primary", "accent", "muted",
             "mutedForeground", "border", "input", "ring", "destructive"]
    css = _css(tmp_path, {"colors": {r: "#336699" for r in roles}})
    for l in css.splitlines():
        if l.strip().startswith("--") and l.split(":")[0].strip().lstrip("-").replace("-", "") in {r.lower() for r in roles}:
            assert "#" not in l, l


def test_a_role_the_scaffold_does_not_wrap_keeps_its_hex(tmp_path):
    """`--sidebar-background` is ours alone; the rail reads it as a colour."""
    css = _css(tmp_path, {"colors": {"sidebarBackground": "#110f0c"}})
    assert "--sidebar-background: #110f0c;" in css


def test_the_heading_face_is_emitted_under_the_name_the_scaffold_reads(tmp_path):
    css = _css(tmp_path, {"typography": {"fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces"}})
    assert "--font-heading: Fraunces;" in css
    assert "--font-body: Inter;" in css
    assert "--font-family-base: Inter;" in css


def test_the_tokens_outrank_the_scaffolds_root_block(tmp_path):
    """Tailwind v3's `@layer base` is not a cascade layer, so the scaffold's
    later `:root` beat this file by source order. `html:root` outranks both
    `:root` and `.dark` by one point of specificity — enough, and no more."""
    css = _css(tmp_path, {"colors": {"accent": "#c9a84c"}})
    assert "html:root {" in css
    assert "\n:root {" not in css
