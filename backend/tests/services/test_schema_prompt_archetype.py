"""Test that a page's `archetype` field drives template_for() selection
in build_schema_prompt, taking precedence over the legacy `page_type`.

The kanban template contains the text "KANBAN BOARD" — so when archetype
is "kanban" (and page_type is "list"), the kanban template must appear in
the built prompt, not the list template.
"""
import services.schema_prompt as sp
from services.schema_prompt import build_schema_prompt


def test_archetype_drives_template_block(monkeypatch):
    """Archetype 'kanban' must override page_type 'list' for template selection."""
    # Disable fidelity/grounding so we don't need Node/design-spec on disk.
    # Use monkeypatch (function-scoped) so the flags aren't frozen for the
    # whole pytest process — module-level os.environ mutation broke sibling tests.
    monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
    monkeypatch.setattr(sp, "REFERENCE_GROUNDING_ENABLED", False)

    plan = {
        "description": "Test app",
        "entity": {"name": "Task", "fields": []},
        "page_type": "list",     # legacy type — should be overridden by archetype
        "entities": {},
        "pages": [],
    }
    page_brief = {
        "route": "/board",
        "archetype": "kanban",
        "page_type": "list",     # legacy type carried alongside
    }
    prompt = build_schema_prompt(
        plan,
        page_brief=page_brief,
        domain="general",
        design_spec={},          # skip disk I/O
        tokens={},               # skip Node subprocess
    )
    # The kanban template block contains "KANBAN BOARD"
    assert "KANBAN" in prompt, (
        "Expected kanban template text in prompt when archetype='kanban', "
        f"but got prompt starting with: {prompt[:300]!r}"
    )
    # And the list-specific "DO NOT put a Form or MetricTile on a list page"
    # text should NOT appear (it's overridden by kanban template)
    assert "DO NOT put a `Form` or `MetricTile` on a list page" not in prompt, (
        "List template should be suppressed when archetype='kanban'"
    )


def test_fallback_to_page_type_when_no_archetype(monkeypatch):
    """Without archetype, page_type still drives template selection."""
    monkeypatch.setattr(sp, "FIDELITY_MODE_ENABLED", False)
    monkeypatch.setattr(sp, "REFERENCE_GROUNDING_ENABLED", False)

    plan = {
        "description": "Test app",
        "entity": {"name": "Task", "fields": []},
        "page_type": "list",
        "entities": {},
        "pages": [],
    }
    page_brief = {
        "route": "/tasks",
        "page_type": "list",
        # no archetype key
    }
    prompt = build_schema_prompt(
        plan,
        page_brief=page_brief,
        domain="general",
        design_spec={},
        tokens={},
    )
    # The list template should be selected
    assert "PAGE TYPE: LIST" in prompt, (
        "Expected list template when no archetype is set"
    )
