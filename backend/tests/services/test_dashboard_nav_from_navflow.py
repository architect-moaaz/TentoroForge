"""The standalone (dashboard) sidebar menu must be driven by nav-flow.json (the single
source of truth for pages + navigation), NOT schema-key heuristics."""
from pathlib import Path

_L = Path("templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()


def test_menu_reads_nav_flow():
    assert "nav-flow.json" in _L
    assert "buildNavItems" in _L
    # the old broken heuristic must be gone
    assert 'endsWith("/list")' not in _L


def test_menu_filters_to_top_level_shell_pages():
    # mirrors build_nav_items: shell only, no params, no /new, top-level
    assert "p.shell" in _L
    assert "p.params" in _L
    assert '"/new"' in _L
    assert "split(\"/\").filter(Boolean).length > 1" in _L
