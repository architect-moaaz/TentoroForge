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
