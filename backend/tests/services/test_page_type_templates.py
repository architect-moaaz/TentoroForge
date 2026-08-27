import pytest
from services.page_type_templates import template_for


@pytest.mark.parametrize("page_type", ["form", "list", "detail", "auth", "dashboard", "error"])
def test_returns_non_empty_block(page_type):
    t = template_for(page_type)
    assert isinstance(t, str)
    assert len(t) > 100


def test_form_template_demands_form_input_button():
    t = template_for("form").lower()
    assert "form" in t
    assert "input" in t
    assert "button" in t
    assert "do not" in t   # explicit exclusion clause present


def test_list_template_demands_table_or_datagrid():
    t = template_for("list").lower()
    assert "table" in t or "datagrid" in t
    assert "filterbar" in t


def test_detail_template_demands_keyvaluelist():
    t = template_for("detail").lower()
    assert "keyvaluelist" in t


def test_dashboard_template_demands_metric_tile():
    t = template_for("dashboard").lower()
    assert "metrictile" in t
    assert "hero" in t


def test_auth_template_demands_email_and_password():
    t = template_for("auth").lower()
    assert "email" in t
    assert "password" in t
    assert "form" in t


def test_error_template_demands_emptystate():
    t = template_for("error").lower()
    assert "emptystate" in t


def test_unknown_type_returns_generic():
    t = template_for("blargh")
    assert isinstance(t, str)
    assert "GENERIC" in t.upper() or "no specific template" in t.lower()


def test_each_template_contains_page_type_header():
    """Every non-generic template begins with '## PAGE TYPE:' for prompt visibility."""
    for ptype in (
        "form", "list", "detail", "auth", "dashboard", "error",
        "kanban", "calendar", "inbox", "report", "wizard", "audit-log", "settings",
    ):
        t = template_for(ptype)
        assert "## PAGE TYPE:" in t, f"Missing '## PAGE TYPE:' header in '{ptype}' template"


def test_form_template_excludes_metrictile():
    """Form pages must NOT use MetricTile."""
    t = template_for("form")
    # The "DO NOT" clause should mention MetricTile
    assert "MetricTile" in t
    # And the required-shape block should NOT contain MetricTile
    required_section = t.split("DO NOT")[0]
    assert "MetricTile" not in required_section


def test_new_archetype_templates_exist_and_name_their_components():
    cases = {
        "kanban": "Kanban", "calendar": "Calendar", "inbox": "InspectorPanel",
        "report": "Chart", "wizard": "ApprovalStepper", "audit-log": "Timeline",
        "settings": "Tabs",
    }
    for archetype, must_mention in cases.items():
        block = template_for(archetype)
        assert block and block != template_for("___nonexistent___")
        assert must_mention in block, (archetype, must_mention)


def test_unknown_still_generic():
    from services.page_type_templates import _GENERIC
    assert template_for("___nope___") == _GENERIC


# ── Slice 3: visual-product-search templates ────────────────────────────


def test_visual_scan_template_registered_and_shaped():
    """The scan page template must name CameraCapture + FileUpload + an
    agent_chat button so the planner emits the mobile-first shape (not a
    generic upload form)."""
    t = template_for("visual_scan")
    assert "## PAGE TYPE: VISUAL-SCAN" in t
    assert "CameraCapture" in t
    assert "FileUpload" in t
    assert "agent_chat" in t
    # Results are cards, not a table
    assert "Grid" in t
    # Exclusions
    assert "Table" in t and "DO NOT" in t


def test_visual_scan_template_forbids_crud_widgets_in_required_section():
    """Table/MetricTile/Chart/Form must not appear in the required-shape
    block — they belong in the DO NOT clause only."""
    t = template_for("visual_scan")
    required_section = t.split("DO NOT")[0]
    for forbidden in ("Table", "MetricTile", "Chart"):
        assert forbidden not in required_section, forbidden


def test_retail_sources_admin_template_registered_and_shaped():
    """The admin CRUD template must include the four required columns
    (name, url, enabled toggle, priority) and the create route."""
    t = template_for("retail_sources_admin")
    assert "## PAGE TYPE: RETAIL-SOURCES-ADMIN" in t
    # Required columns
    for col in ('"name"', '"url"', '"enabled"', '"priority"'):
        assert col in t, col
    # Per-row enable/disable toggle
    assert "toggle" in t
    # Edit action + create route
    assert '"Edit"' in t
    assert "/admin/retail-sources/new" in t
    # Exclusions
    assert "MetricTile" in t and "DO NOT" in t


def test_app_archetype_page_template_mapping_covers_visual_product_search():
    from services.page_type_templates import (
        APP_ARCHETYPE_PAGE_TEMPLATES, _TEMPLATES,
    )
    assert "visual-product-search" in APP_ARCHETYPE_PAGE_TEMPLATES
    for key in APP_ARCHETYPE_PAGE_TEMPLATES["visual-product-search"]:
        assert key in _TEMPLATES, key
