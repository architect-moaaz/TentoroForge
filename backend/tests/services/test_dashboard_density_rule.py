from services.schema_rules import RULES


def test_dashboard_density_rule_exists():
    rule = next((r for r in RULES if r.name == "dashboard-density"), None)
    assert rule is not None
    assert "MetricTile" in rule.body
    assert "Chart" in rule.body or "Sparkline" in rule.body


def test_dashboard_density_rule_fires_only_on_dashboard():
    rule = next(r for r in RULES if r.name == "dashboard-density")
    entity = {"name": "Account", "fields": []}
    assert rule.applies_when(entity, "dashboard") is True
    assert rule.applies_when(entity, "list") is False
    assert rule.applies_when(entity, "form") is False
    assert rule.applies_when(entity, "detail") is False
