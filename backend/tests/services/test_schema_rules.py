"""Tests for the schema_rules catalogue (Task 20)."""
from services.schema_rules import RULES, Rule


def test_every_rule_has_required_fields():
    for r in RULES:
        assert isinstance(r, Rule)
        assert r.name and isinstance(r.name, str)
        assert r.body and isinstance(r.body, str)
        assert r.example_snippet and isinstance(r.example_snippet, str)
        assert callable(r.applies_when)


def test_rule_names_unique():
    names = [r.name for r in RULES]
    assert len(names) == len(set(names))


def test_applies_when_dispatches_on_page_type():
    entity = {"name": "X", "fields": []}
    metric = next(r for r in RULES if r.name == "metric-tile-for-stats")
    assert metric.applies_when(entity, "list") is True
    assert metric.applies_when(entity, "form") is False
