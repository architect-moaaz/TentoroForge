"""Tests for the A2UI catalog generated from Forge's own component library.

The catalog is what constrains the composer, so every gap in it becomes a
class of broken page. Three shipped before these tests existed:

  * no ``required`` → MetricTile with no ``format``, rendering a blank value
  * no enum members → ``direction: "column"``, which Forge's node rejects
  * no props at all for Text → the composer invented ``{text, variant}``

All three trace to the same root: the catalog was reading a summarised
manifest instead of the generated Zod contract. These tests pin the contract
as the authority.
"""

import json

import pytest

from services.a2ui_catalog import (
    COMPOSITION_SET,
    build_a2ui_catalog,
    load_contracts,
    props_for,
)


@pytest.fixture(scope="module")
def catalog():
    return build_a2ui_catalog()


def body(catalog, name):
    """The component's own schema body (third entry of its allOf)."""
    return catalog["components"][name]["allOf"][2]


# ------------------------------------------------------------------ authority

def test_contracts_file_is_readable():
    c = load_contracts()
    assert c, "component-contracts.json missing — catalog would silently thin out"
    assert isinstance(c.get("MetricTile"), dict)


def test_enum_members_come_from_the_contract_not_a_hand_list():
    """Regression on a real defect: the hand-maintained list had format
    accepting "text", which the Zod contract does not. A hand-copied contract
    drifts by construction."""
    fmt = props_for("MetricTile", load_contracts())["format"]
    assert fmt["enum"] == ["number", "currency", "percent", "duration"]
    assert "text" not in fmt["enum"]


def test_primitives_without_a_contract_still_get_props():
    """Stack/Row/Grid/Container/Text are declared in packages/schema, not the
    library, so the registry extractor never sees them. Text having no props
    is why the composer invented {text, variant}."""
    c = load_contracts()
    for name in ("Stack", "Row", "Grid", "Container", "Text"):
        assert props_for(name, c), f"{name} would author against nothing"
    assert set(props_for("Text", c)) == {"content", "as"}


# ------------------------------------------------------------------- required

def test_metrictile_declares_its_required_props(catalog):
    b = body(catalog, "MetricTile")
    assert set(b["required"]) == {"component", "format", "label", "value"}


def test_chart_declares_series_required(catalog):
    """The composer omitted `series` and the chart plotted nothing. It could
    not have known — the catalog never said."""
    assert "series" in body(catalog, "Chart")["required"]
    assert "chartType" in body(catalog, "Chart")["required"]


def test_optional_props_are_not_required(catalog):
    b = body(catalog, "Stack")
    assert b["required"] == ["component"]
    assert "direction" in b["properties"]


# ---------------------------------------------------------------------- enums

def test_direction_is_an_enum_not_a_bare_string(catalog):
    """Told only that direction is a string, a composer reasonably emits CSS's
    "column"."""
    assert body(catalog, "Stack")["properties"]["direction"] == {
        "enum": ["vertical", "horizontal"]
    }


def test_charttype_carries_every_real_variant(catalog):
    members = body(catalog, "Chart")["properties"]["chartType"]["enum"]
    # radar was missing from the hand-written list.
    assert {"bar", "line", "area", "pie", "donut", "funnel", "radar"} <= set(members)


# -------------------------------------------------------------- catalog shape

def test_every_composition_component_is_present_or_reported(catalog):
    wanted = {n for g in COMPOSITION_SET.values() for n in g}
    present = set(catalog["components"])
    missing = set(catalog["$defs"]["_missing"])
    assert present | missing == wanted
    assert not (present & missing)


def test_containers_accept_children_and_leaves_do_not(catalog):
    assert "children" in body(catalog, "Stack")["properties"]
    assert "children" not in body(catalog, "MetricTile")["properties"]


def test_identity_and_styling_props_are_never_authorable(catalog):
    """The composer must not author ids, classNames or inline style — those
    belong to the binder, the design layer and the renderer."""
    for name in catalog["components"]:
        props = set(body(catalog, name)["properties"])
        assert not (props & {"id", "style", "className", "args", "dataJourney"}), name


def test_catalog_serialises(catalog):
    json.dumps(catalog)
