"""FEEL-lite cross-engine conformance — Python side.

The condition→FEEL compiler runs in the BROWSER (frontend/src/lib/condition-to-feel.ts)
but the rules it produces evaluate SERVER-SIDE. So the two FEEL engines
(backend/runtime/feel_lite [py] and frontend/src/lib/feel-lite [ts]) MUST agree,
or a condition that reads true in the editor playground reads false in the shipped
app. There was no test proving they agree — this is that test's Python half.

The shared fixtures (tests/fixtures/feel_conformance.json) carry expr+data+expected
across the exact FEEL vocabulary the compiler emits (=, !=, <, <=, >, >=, in,
not(..in..), = null, != null, matches/contains/starts_with/ends_with, and/or/not
groups) plus the risky edges (absent-field null semantics, numeric-string coercion).
The TS half (frontend/src/__tests__/feel-conformance.test.ts) asserts the SAME
fixtures — if both pass, the engines agree.
"""
import json
import pathlib

import pytest

from runtime.feel_lite.evaluator import evaluate_expression

_FIXTURES = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "feel_conformance.json").read_text()
)


@pytest.mark.parametrize("case", _FIXTURES, ids=lambda c: f"{c['expr']}|{c['data']}")
def test_feel_conformance_python(case):
    if "error" in case:
        with pytest.raises(Exception):
            evaluate_expression(case["expr"], case["data"])
        return
    assert evaluate_expression(case["expr"], case["data"]) == case["expected"]


def test_fixture_set_is_substantial():
    """Guard against the fixture file being emptied/truncated — the conformance
    guarantee is only as good as its coverage."""
    assert len(_FIXTURES) >= 30
    exprs = " ".join(c["expr"] for c in _FIXTURES)
    for token in ("in [", "= null", "!= null", "contains(", "starts_with(",
                  "ends_with(", "matches(", " and ", " or ", "not("):
        assert token in exprs, f"conformance fixtures don't cover {token!r}"
