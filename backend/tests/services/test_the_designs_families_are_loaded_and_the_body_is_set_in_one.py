"""A font token nobody reads sets nothing.

`--font-body: Inter` was projected and no rule used it, so the body ran in
the browser's default, and a viewer without Inter installed had no way to
get it. The token sheet now requests every family the design system names
from Google Fonts and sets the body in the base family.
"""
import json
from pathlib import Path

from services.blueprint.projection import project_design_tokens


def _tokens(tmp_path, design_system):
    doc = {"designSystem": design_system}
    project_design_tokens(doc, tmp_path)
    return (tmp_path / "src" / "app" / "tokens.css").read_text()


def test_the_families_are_requested_first():
    import tempfile
    css = _tokens(Path(tempfile.mkdtemp()), {"typography": {
        "fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces", "fontFamilyNumeric": "JetBrains Mono"}})
    assert "@import url(\"https://fonts.googleapis.com/css2?" in css
    assert css.index("@import") < css.index("html:root"), "an import must precede every rule"
    assert "family=Inter:" in css and "family=Fraunces:" in css and "family=JetBrains+Mono:" in css


def test_the_body_is_set_in_the_base_family():
    import tempfile
    css = _tokens(Path(tempfile.mkdtemp()), {"typography": {"fontFamilyBase": "Inter"}})
    assert "body {\n  font-family: var(--font-body), ui-sans-serif, system-ui, sans-serif;\n}" in css


def test_a_design_with_no_typography_requests_nothing():
    import tempfile
    css = _tokens(Path(tempfile.mkdtemp()), {"colors": {"primary": "#c9a84c"}})
    assert "googleapis" not in css and "body {" not in css


def test_a_prose_rationale_in_a_scale_is_not_a_token():
    """A rationale nested in the radius scale is metadata, not a length.

    The Blueprint types `radius` as an open string->string map, so a design
    pass can drop a whole sentence beside the real steps. Emitted as a custom
    property, its `;` ends the declaration early and `next build` dies on
    `tokens.css Unknown word`. Only the dimension-valued steps are tokens.
    """
    import tempfile
    css = _tokens(Path(tempfile.mkdtemp()), {"radius": {
        "none": "0px", "sm": "3px", "md": "5px", "pill": "999px",
        "rationale": "Small radii read as tooling rather than consumer "
                     "software; status badges stay near-square so they align "
                     "cleanly in dense table columns"}})
    assert "--radius-sm: 3px;" in css and "--radius-pill: 999px;" in css
    assert "--radius-rationale" not in css, "prose is not a scale step"
    assert "--radius: 5px;" in css, "the bare --radius still resolves from md"
    # No emitted custom-property value carries a `;` that would end the
    # declaration early — the failure mode this guards.
    for line in css.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            assert stripped.count(";") == 1, f"broken declaration: {line!r}"


def test_a_spacing_scale_drops_prose_too():
    import tempfile
    css = _tokens(Path(tempfile.mkdtemp()), {"spacing": {
        "sm": "8px", "lg": "24px", "note": "generous; airy"}})
    assert "--space-sm: 8px;" in css and "--space-lg: 24px;" in css
    assert "--space-note" not in css
