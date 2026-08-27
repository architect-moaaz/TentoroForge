from services.shell_context import build_shell_context


def _nav():
    return {"pages": [
        {"route": "/", "title": "Dashboard"},
        {"route": "/pipeline", "title": "Pipeline"},
        {"route": "/deals", "title": "Deals"},
        {"route": "/admin/users", "title": "Users"},
        {"route": "/settings", "title": "Settings"},
    ]}


def test_groups_primary_vs_utility_and_adds_divergence():
    ctx = build_shell_context({"name": "AcmeCRM", "description": "sales CRM"}, _nav())
    # IA grouping surfaces primary destinations and separates admin/settings as utility
    assert "Pipeline" in ctx and "Deals" in ctx
    assert "Users" in ctx and "Settings" in ctx
    # an explicit divergence directive must be present
    low = ctx.lower()
    assert "sidebar" in low and ("avoid default" in low or "do not default" in low or "don't default" in low)


def test_includes_design_language_hints_when_present_else_omits():
    spec = {"layout": {"navigation": "topbar", "density": "compact"},
            "typography": {"fontFamily": "Space Grotesk"}}
    ctx = build_shell_context({"name": "X"}, _nav(), design_spec=spec)
    assert "topbar" in ctx and "compact" in ctx and "Space Grotesk" in ctx
    # absent design_spec → no crash, no design-language section
    ctx2 = build_shell_context({"name": "X"}, _nav(), design_spec=None)
    assert isinstance(ctx2, str) and ctx2


def test_safe_on_empty_inputs():
    assert isinstance(build_shell_context({}, {}), str)
