"""The composer's validator is as strict as the one that judges its output.

A2UI validates every surface against the catalog Forge hands it, and retries up
to three times when its own validation fails. That loop is the cheapest place
any composition fault can be fixed — it happens inside the composer, before a
page is returned, at no cost to the run.

It never fired for a whole class of fault. Each component was emitted without
`additionalProperties`, which in JSON Schema means "extra properties are fine",
while Forge's catalog sets `additionalProperties: false` for the same
components. So A2UI declared `density` on a Card and `variant` on a Text valid,
returned them, and Forge refused the page three minutes later.

Two catalogs describing one component library, disagreeing about what a
component is.
"""
from __future__ import annotations

import json

from services.a2ui_catalog import build_a2ui_catalog
from services.blueprint.page_planner import load_catalog


def _a2ui(name: str) -> dict:
    return (build_a2ui_catalog().get("components") or {})[name]


def test_a_component_admits_no_property_it_does_not_declare():
    for name in ("Card", "Text", "Table", "Heading", "Button"):
        assert _a2ui(name).get("unevaluatedProperties") is False, (
            f"{name} accepts anything, so A2UI's own retry never sees the fault"
        )


def test_it_is_unevaluated_and_not_additional():
    """The component is an `allOf` over two `$ref`s and a local body.
    `additionalProperties` is evaluated per subschema, so it cannot see the
    properties the refs contribute and would reject `id` along with the junk.
    `unevaluatedProperties` is evaluated across the whole composition — that is
    what draft 2020-12 added it for, and A2UI builds a Draft202012Validator.
    """
    card = _a2ui("Card")
    assert "allOf" in card
    assert "additionalProperties" not in card
    body = next(p for p in card["allOf"] if "properties" in p)
    assert "additionalProperties" not in body


def test_the_two_catalogs_agree_on_strictness():
    """Forge's catalog has always been strict. This is the other half."""
    forge = load_catalog()
    for name in ("Card", "Text", "Table", "Heading", "Button"):
        assert (forge[name].get("props") or {}).get("additionalProperties") is False
        assert _a2ui(name).get("unevaluatedProperties") is False


def test_strictness_arrives_with_a_positive_requirement():
    """Strictness alone made things worse once: `additionalProperties: false`
    rejected `Button.action` without saying what to write instead, the retry
    guessed again, and a page died having guessed three times. `_COMPOSE_ONE_OF`
    is what supplies the missing half — a Button must carry one of the four
    real ways to act — so a refusal now comes with somewhere to go."""
    button = _a2ui("Button")
    body = next(p for p in button["allOf"] if "properties" in p)
    assert body.get("anyOf"), "nothing states what a Button must have instead"
    required = {tuple(o["required"]) for o in body["anyOf"]}
    assert ("workflow",) in required or ("navigate",) in required


def test_a_declared_property_is_still_accepted():
    """The check that this is a constraint and not a wall: everything the
    catalog does declare must still validate."""
    from jsonschema import Draft202012Validator

    body = next(p for p in _a2ui("Card")["allOf"] if "properties" in p)
    v = Draft202012Validator({**body, "unevaluatedProperties": False})
    assert not list(v.iter_errors({"component": "Card", "title": "Sittings"}))
    assert list(v.iter_errors(
        {"component": "Card", "title": "Sittings", "density": "compact"}))


def test_a_form_must_say_where_it_submits():
    """`functional_completeness._ACTIONABLE` is ("Button", "Form"), so a Form
    with no action has always been refused — and only Button carried an
    `anyOf`, so the composer had no way to know the requirement existed until
    the page came back rejected. Twice on the last full build, both on create
    pages."""
    body = next(p for p in _a2ui("Form")["allOf"] if "properties" in p)
    assert body.get("anyOf") == [{"required": ["workflow"]}]


def test_the_form_requirement_is_one_the_form_can_meet():
    """Derived from the intersection of the action props and what the Form
    contract offers, not enumerated by hand — the mistake recorded above
    Button, where the list held four of the six the catalog had.

    `onSuccess` and `onError` are what happens after the action; `autoSave`
    carries a workflow of its own for drafts. `workflow` is the only member of
    the union a Form actually has."""
    from services.a2ui_catalog import _COMPOSE_ONE_OF

    actions = {p for choices in _COMPOSE_ONE_OF.values() for p in choices}
    body = next(p for p in _a2ui("Form")["allOf"] if "properties" in p)
    offered = set(body.get("properties") or {})
    assert offered & actions == {"workflow"}


def test_adding_form_changed_no_existing_verdict():
    """`_action_props()` is the union of this table, and `workflow` was already
    in it via Button — so nothing that passed before fails now. What changed is
    that the requirement is stated where the composer reads it."""
    from services.blueprint.functional_completeness import _action_props

    assert _action_props() == {"workflow", "navigate", "submit", "onClick",
                               "opensDialog", "togglesSidebar"}
