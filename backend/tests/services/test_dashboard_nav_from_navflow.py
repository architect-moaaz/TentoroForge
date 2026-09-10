"""The standalone (dashboard) sidebar menu must be driven by nav-flow.json (the
single source of truth for pages + navigation), NOT schema-key heuristics.

These assert against the template's source text, so they track renames rather
than behaviour. `buildNavItems` was renamed `navFlowShellItems` when shell.json
became the primary menu source and nav-flow the fallback, and the top-level
depth rule became an `isDetailPage` check — so both tests failed while the
property they exist to protect never stopped holding.
"""
from pathlib import Path

_L = Path("templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text(encoding="utf-8")


def test_menu_reads_nav_flow():
    assert "nav-flow.json" in _L
    assert "navFlowShellItems" in _L


def test_schema_heuristic_is_only_a_last_resort():
    """The `<entity>/list` heuristic is still in the file, and this test used
    to demand its absence.

    It is no longer the menu — it is the third tier, reached only when
    shell.json and nav-flow both yield nothing, and it exists so the app never
    ships a blank rail. What must hold is the precedence, not the deletion.
    """
    assert _L.index("navFlowShellItems(") < _L.index("schemaRegistryItems()")
    guarded = [ln for ln in _L.splitlines() if "schemaRegistryItems()" in ln
               and "function" not in ln]
    assert guarded and all("!groups.length" in ln for ln in guarded), guarded


def test_menu_filters_to_shell_pages_only():
    # mirrors navFlowShellItems: shell only, no params, no dynamic segments,
    # no create routes, no auth routes, no detail pages
    assert "p.shell" in _L
    assert "p.params" in _L
    assert 'endsWith("/new")' in _L
    assert 'includes("[")' in _L
    assert "AUTH_ROUTES" in _L
    assert "isDetailPage" in _L
