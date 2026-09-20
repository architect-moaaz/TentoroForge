"""A page that names one form factor must not cost the whole node.

`page_details` was re-run from scratch on a one-page calculator because the
agent wrote `responsive: {desktop: "primary"}` — a perfectly sensible thing to
say about a page — and `tablet` and `mobile` were declared required. The
contract already stated what those two should be when absent; the defaults
just sat at the object level, where they only applied to a `responsive` that
was missing entirely rather than to the partial one an agent actually writes.

Measured on that run: 74s for the node, about half of it redoing work that was
never wrong, for two keys the contract was already willing to assume.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest
from jsonschema import Draft7Validator

SCHEMA = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "contracts"
     / "blueprint.schema.json").read_text("utf-8"))

_PAGE = {
    "id": "PAGE-001", "name": "Calculator", "route": "/",
    "purpose": "Let the user perform arithmetic.", "pattern": "tool",
    "access": "public",
}


def _responsive_errors(responsive) -> list[str]:
    """Contract errors mentioning `responsive`, validated as part of a whole
    document — the sub-schema's `$ref`s resolve against the root."""
    doc = {
        "application": {"id": "APP-001", "name": "Calculator", "domain": "Tools"},
        "pages": [dict(copy.deepcopy(_PAGE), responsive=responsive)],
    }
    return [f"{'/'.join(map(str, e.path))}: {e.message}"
            for e in Draft7Validator(SCHEMA).iter_errors(doc)
            if "responsive" in "/".join(map(str, e.path))]


@pytest.mark.parametrize("responsive", [
    {"desktop": "primary"},                 # the exact body that was refused
    {"mobile": "primary"},
    {"tablet": "supported", "mobile": "adaptive"},
    {},
    {"desktop": "primary", "tablet": "supported", "mobile": "adaptive"},
])
def test_a_partial_responsive_is_completed_not_refused(responsive):
    assert _responsive_errors(responsive) == []


def test_a_form_factor_nobody_declared_is_still_refused():
    """Permissive about what is ABSENT, not about what is wrong. A value
    outside the enum is a mistake the defaults cannot stand in for."""
    assert _responsive_errors({"desktop": "smartwatch"})
    assert _responsive_errors({"desktop": "primary", "tv": "supported"})


def test_the_defaults_are_the_ones_the_contract_already_stated():
    """Per-key and object-level must agree. Two spellings of the same
    assumption is how a page silently becomes mobile-first."""
    responsive = (SCHEMA["properties"]["pages"]["items"]
                  ["properties"]["responsive"])
    assert "required" not in responsive
    assert responsive["default"] == {
        "desktop": "primary", "tablet": "supported", "mobile": "adaptive"}
    per_key = {k: v["default"] for k, v in responsive["properties"].items()}
    assert per_key == responsive["default"]
