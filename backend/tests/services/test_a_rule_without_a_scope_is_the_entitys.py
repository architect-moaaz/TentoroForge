"""A business rule that names no scope is enforced on every write.

The projection used to write `scope: "form"` for a rule that said nothing,
and a form-scoped rule is skipped by every server write — so "reject an
order under 10" refused nobody. Unscoped, a rule is the entity's: the
server runs it on a write, and the form still gets its hints from it. A
rule that names `form` keeps it."""
from __future__ import annotations

import json

from services.blueprint.projection import project_business_rules

DOC = {
    "data": {"entities": [{"id": "ENTITY-001", "name": "Order"}]},
    "businessRules": [
        {"id": "BR-001", "name": "Minimum order", "kind": "condition_action", "entity": "ENTITY-001",
         "when": "total < 10", "then": [{"type": "show_error", "message": "An order is at least 10."}]},
        {"id": "BR-002", "name": "Hint only", "kind": "condition_action", "entity": "ENTITY-001",
         "when": "true", "then": [{"type": "set_required", "field": "note"}], "scope": "form"},
    ],
}


def _rows(tmp_path):
    project_business_rules(DOC, tmp_path)
    return {r["id"]: r for r in json.loads((tmp_path / "rules" / "blueprint-rules.json").read_text())}


def test_an_unscoped_rule_is_the_entitys(tmp_path):
    assert _rows(tmp_path)["BR-001"]["config"]["scope"] == "entity"


def test_a_rule_that_names_form_keeps_it(tmp_path):
    assert _rows(tmp_path)["BR-002"]["config"]["scope"] == "form"
