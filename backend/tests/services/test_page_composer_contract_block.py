"""The composer must be told the expression language, and warned off ghost props.

Two live classes on 6q7oqejv that the existing checks let through:

* ``{{!warehouses.length}}`` and ``{{!locations.length}}`` — bindings are
  evaluated by FEEL-lite, not JavaScript. `!x` is a parse error, swallowed,
  evaluating to false, so the guarded node never renders. The model reached
  for negation because nothing told it `Conditional` already has a falsy
  branch.
* ``props.binding`` on five Input/Select/Switch nodes. The binding checks
  only verify that a binding's VALUE resolves; nothing verified the prop
  NAME exists, so an invented prop whose value happened to resolve passed
  validation and was then dropped silently by Zod at render time.
"""
from __future__ import annotations

import pytest

from services.page_composer import (_BINDING_SYNTAX_BLOCK,
                                    _validate_page_schema)

PLAN = {"entities": [{"name": "Warehouse", "fields": [{"name": "name"}]}]}

MANIFEST = {"components": {
    "Stack": {"category": "layout", "key_props": [{"name": "gap"}]},
    "Input": {"category": "input",
              "key_props": [{"name": "bind"}, {"name": "label"},
                            {"name": "name"}]},
}}


def _page(props: dict) -> dict:
    return {
        "schemaVersion": "2", "id": "p", "route": "/warehouses",
        "dataSources": [{"name": "warehouses", "entity": "Warehouse"}],
        "root": {"type": "Stack", "props": {"gap": "md"},
                 "children": [{"type": "Input", "props": props}]},
    }


class TestSyntaxBlockStatesTheContract:
    def test_names_the_expression_language(self):
        assert "FEEL-lite" in _BINDING_SYNTAX_BLOCK
        assert "not JavaScript" in _BINDING_SYNTAX_BLOCK

    @pytest.mark.parametrize("bad", ["!x", "&&", "? :", ".map("])
    def test_lists_the_unsupported_forms(self, bad):
        assert bad in _BINDING_SYNTAX_BLOCK

    def test_gives_the_empty_state_recipe_instead_of_negation(self):
        # The fix for `{{!x.length}}` is the two-branch Conditional, so the
        # block must show it rather than merely banning `!`.
        assert "Conditional" in _BINDING_SYNTAX_BLOCK
        assert '"when":"{{warehouses.length}}"' in _BINDING_SYNTAX_BLOCK
        assert "EmptyStateRich" in _BINDING_SYNTAX_BLOCK

    def test_warns_that_unknown_props_are_dropped_silently(self):
        assert "dropped silently" in _BINDING_SYNTAX_BLOCK

    def test_stays_within_a_sane_token_budget(self):
        assert len(_BINDING_SYNTAX_BLOCK) / 4 < 400


class TestUnknownPropsAreSurfaced:
    def test_ghost_prop_warns(self):
        ok, errors, warnings = _validate_page_schema(
            _page({"binding": "{{warehouses.name}}", "name": "n"}),
            PLAN, MANIFEST)
        assert any("Input.props.binding" in w for w in warnings)
        # A hint list is not exhaustive, so this must not fail composition.
        assert ok and errors == []

    def test_real_prop_is_silent(self):
        _, _, warnings = _validate_page_schema(
            _page({"bind": "{{warehouses.name}}", "name": "n"}),
            PLAN, MANIFEST)
        assert not any("Input.props" in w for w in warnings)

    @pytest.mark.parametrize("prop", ["className", "style", "id",
                                      "data-journey"])
    def test_universal_and_data_props_are_never_flagged(self, prop):
        _, _, warnings = _validate_page_schema(
            _page({"name": "n", prop: "x"}), PLAN, MANIFEST)
        assert not any(f"props.{prop}" in w for w in warnings)

    def test_component_absent_from_the_contract_is_not_flagged(self):
        """No contract for a component means no basis to judge its props.

        Stack is a layout primitive with no contract entry at all.
        """
        page = _page({"name": "n"})
        page["root"]["children"].append(
            {"type": "Stack", "props": {"whatever": 1}})
        _, _, warnings = _validate_page_schema(
            page, PLAN, {"components": {"Stack": {"category": "layout"},
                                        "Input": MANIFEST["components"]["Input"]}})
        assert not any("whatever" in w for w in warnings)

    def test_check_reads_the_contract_not_the_capped_key_props(self):
        """Pins the fix for the Form false positives.

        `key_props` is ranked and capped at 4, so `Form.workflow` and
        `Form.submitLabel` — both real, both in the contract — fall off it.
        Judging props by key_props flagged them and buried the true
        positives; judging by the contract does not.
        """
        page = {
            "schemaVersion": "2", "id": "p", "route": "/products/new",
            "dataSources": [],
            "root": {"type": "Stack", "props": {"gap": "md"}, "children": [
                {"type": "Form",
                 "props": {"workflow": "CreateProduct", "submitLabel": "Save"}},
            ]},
        }
        # A manifest whose key_props deliberately OMITS both real props.
        manifest = {"components": {
            "Stack": {"key_props": [{"name": "gap"}]},
            "Form": {"key_props": [{"name": "fields"}, {"name": "autoSave"}]},
        }}
        _, _, warnings = _validate_page_schema(page, PLAN, manifest)
        assert not any("Form.props.workflow" in w for w in warnings)
        assert not any("Form.props.submitLabel" in w for w in warnings)
