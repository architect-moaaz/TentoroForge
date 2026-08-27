"""Tests for button_compute_spec — validator for `onClick: {compute}`."""

from __future__ import annotations

from services.button_compute_spec import validate_compute_action


class TestHappy:
    def test_simple_compute(self):
        fields = [{"name": "a"}, {"name": "b"}, {"name": "result"}]
        r = validate_compute_action(
            {"kind": "compute", "target": "result", "formula": "a + b"},
            fields,
        )
        assert r.ok, r.errors
        assert r.canonical["target"] == "result"
        assert r.canonical["formula"] == "a + b"
        assert set(r.canonical["reads"]) == {"a", "b"}

    def test_helper_functions(self):
        fields = [{"name": "principal"}, {"name": "rate"}, {"name": "n"}, {"name": "emi"}]
        r = validate_compute_action(
            {
                "kind": "compute",
                "target": "emi",
                "formula": "round(principal * rate * pow(1 + rate, n) / (pow(1 + rate, n) - 1), 2)",
            },
            fields,
        )
        assert r.ok, r.errors


class TestErrors:
    def test_bad_kind(self):
        r = validate_compute_action({"kind": "navigate", "target": "x"}, [{"name": "x"}])
        assert not r.ok
        assert "kind must be 'compute'" in r.errors[0]

    def test_missing_target(self):
        r = validate_compute_action(
            {"kind": "compute", "formula": "1+1"}, [{"name": "x"}]
        )
        assert not r.ok
        assert any("target" in e for e in r.errors)

    def test_missing_formula(self):
        r = validate_compute_action(
            {"kind": "compute", "target": "x"}, [{"name": "x"}]
        )
        assert not r.ok
        assert any("formula" in e for e in r.errors)

    def test_unknown_target_suggests(self):
        r = validate_compute_action(
            {"kind": "compute", "target": "resutl", "formula": "1"},
            [{"name": "result"}],
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "result" in joined  # suggestion

    def test_unknown_function_suggests(self):
        r = validate_compute_action(
            {"kind": "compute", "target": "r", "formula": "rond(a, 2)"},
            [{"name": "r"}, {"name": "a"}],
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "round" in joined  # suggestion

    def test_unknown_sibling_suggests(self):
        r = validate_compute_action(
            {"kind": "compute", "target": "r", "formula": "principle * rate"},
            [{"name": "r"}, {"name": "principal"}, {"name": "rate"}],
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "principal" in joined  # suggestion

    def test_non_dict(self):
        r = validate_compute_action("nope", [])
        assert not r.ok
