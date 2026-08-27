from services.page_type_templates import template_for


def test_dashboard_template_is_domain_driven_not_fixed_shape():
    t = template_for("dashboard").lower()
    # The old rigid fixed shape (a Grid of exactly 4 MetricTiles) must be gone.
    assert "metrictile×4" not in t
    # Metrics must be derived from the domain, with an explicit anti-default directive.
    assert "domain" in t
    assert "do not default" in t or "different domains" in t


def test_dashboard_template_keeps_renderable_floor():
    # De-anchored, but still composable from registered KPI components.
    t = template_for("dashboard")
    assert "MetricTile" in t or "Stat" in t
