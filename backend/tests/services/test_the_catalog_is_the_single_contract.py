"""One vocabulary, three consumers, held together here.

Three tables describe what a page may contain, and each was maintained by hand:

    contracts/component-catalog.json   what the Forge engine can render (166)
    a2ui_catalog.build_a2ui_catalog()  what A2UI may compose         ( 93)
    page_kind_anatomy._*_TYPES         what the floors look for

Drift between them does not fail loudly. It fails as a page refused for
lacking something it was never offered, or accepted carrying something that
cannot render — and the run reports success either way.

Measured when this was written: `_LIST_TYPES` named `CardGrid`, which exists in
neither the registry nor the catalog, so no page could ever satisfy that floor
by carrying one. `_ACTION_TYPES` named `AddToCart` and `StickyPrimaryCta`,
which the A2UI composer cannot emit at all.

The live bug this class produced: A2UI validated a `Form` against its own
catalog, passed with `warnings=0`, and Forge's floor then refused the page for
having no submit — because `_ACTION_TYPES` listed only child-node controls and
did not know that a `Form` carries its submit as a prop. Both were right about
their own table. The tables disagreed.
"""
import json
import pathlib

import pytest

from services.a2ui_catalog import _COMPOSE_ONE_OF, build_a2ui_catalog
from services.blueprint.functional_completeness import _action_props
from services.page_kind_anatomy import (
    _ACTION_TYPES, _BODY_TYPES, _FIELD_TYPES, _LIST_TYPES, _ROUTING_ONLY,
)

_REGISTRY = (pathlib.Path(__file__).resolve().parents[2]
             / "contracts" / "component-catalog.json")

#: Types `a2ui_to_forge` creates that no composer emits, so they are absent
#: from the A2UI catalog and present in the tree the floors judge. Derived
#: from the translator's own behaviour, not a licence to add names here.
TRANSLATOR_MINTED = frozenset({"Repeat", "Stack"})


def _registry() -> set[str]:
    raw = json.loads(_REGISTRY.read_text())["components"]
    return set(raw) if isinstance(raw, dict) else {c["name"] for c in raw}


def _catalog() -> set[str]:
    return set(build_a2ui_catalog(workflows=["FLOW-001"])["components"])


def test_a2ui_can_only_compose_what_the_engine_can_render():
    """The composer's menu must be a subset of the renderer's. A component
    A2UI may emit and the engine cannot render is a page that composes,
    validates, projects, and then fails in the browser."""
    unrenderable = sorted(_catalog() - _registry())
    assert unrenderable == [], (
        f"A2UI may compose components the engine cannot render: {unrenderable}"
    )


@pytest.mark.parametrize("name,types", [
    ("_ACTION_TYPES", _ACTION_TYPES),
    ("_FIELD_TYPES", _FIELD_TYPES),
    ("_BODY_TYPES", _BODY_TYPES),
    ("_LIST_TYPES", _LIST_TYPES),
    ("_ROUTING_ONLY", _ROUTING_ONLY),
])
def test_every_floor_name_is_something_that_can_exist(name, types):
    """A floor naming a component nothing can produce is a rule that can never
    be satisfied that way — it reads as an offered alternative and is not."""
    known = _registry() | TRANSLATOR_MINTED
    ghosts = sorted(set(types) - known)
    assert ghosts == [], (
        f"{name} names components that are in neither the engine registry nor "
        f"the translator's output: {ghosts}"
    )


def test_the_floors_and_the_composer_agree_on_what_an_action_is():
    """`functional_completeness` reads the action props from the composer's own
    contract rather than listing them. This holds that wiring in place: a
    hand-copied list is how `opensDialog` came to be refused on a modal create
    form while the catalog offered it."""
    assert _action_props() == {p for c in _COMPOSE_ONE_OF.values() for p in c}


def test_a_form_declares_its_action_the_way_the_catalog_says_it_does():
    """The exact disagreement that refused every create page: the catalog
    requires a `Form` to carry `workflow`, so the floor must accept that as its
    submit rather than demanding a separate Button."""
    assert _COMPOSE_ONE_OF["Form"] == ("workflow",)
    form = build_a2ui_catalog(workflows=["FLOW-001"])["components"]["Form"]
    body = form["allOf"][2]
    assert body.get("anyOf") == [{"required": ["workflow"]}]
    assert "workflow" in body["properties"]
