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

def _members(spec: dict) -> list:
    """The literal members an enum prop accepts, whether or not it also
    accepts a binding."""
    if "enum" in spec:
        return spec["enum"]
    return next(b["enum"] for b in spec["anyOf"] if "enum" in b)


def test_direction_is_an_enum_not_a_bare_string(catalog):
    """Told only that direction is a string, a composer reasonably emits CSS's
    "column"."""
    assert _members(body(catalog, "Stack")["properties"]["direction"]) == [
        "vertical", "horizontal"
    ]


def test_an_enum_prop_also_accepts_a_binding(catalog):
    """A status badge whose colour follows the row is the ordinary case.
    Described as a bare enum, A2UI bound {'path': '/plant/statusVariant'},
    its own validator refused it three times, and the page fell back."""
    spec = body(catalog, "Badge")["properties"]["variant"]
    assert "anyOf" in spec
    assert any("$ref" in b for b in spec["anyOf"]), "no binding alternative"
    assert "success" in _members(spec)


def test_charttype_carries_every_real_variant(catalog):
    members = _members(body(catalog, "Chart")["properties"]["chartType"])
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
        assert not (props & {"id", "style", "className", "dataJourney"}), name


def test_dispatch_args_are_authorable(catalog):
    """`args` is the only channel a control has for saying what to act on.

    It sat in the skip list beside `className` for as long as this test pinned
    it there, so no composed control ever carried one and every workflow was
    dispatched with `{input: {}}` — which is how a "Mark as watered" button
    inserted a row with a null plant_id. It is not styling and not identity:
    Button/Link/IconButton hand it to `fallbackDispatch(workflow, args)`.
    """
    for name in ("Button", "Link", "IconButton"):
        if name not in catalog["components"]:
            continue
        spec = body(catalog, name)["properties"].get("args")
        assert spec, f"{name} cannot say what its workflow acts on"
        # Described, not merely present. `{"type": "object"}` is true and
        # tells a composer nothing about when to write one.
        assert "workflow" in spec.get("description", "").lower(), name


def test_catalog_serialises(catalog):
    json.dumps(catalog)


# --- the catalog carries what a composer needs to get a prop right ----------


def test_array_props_carry_their_item_shape():
    """component-contracts.json stops at {"type": "array"}. The Zod catalog
    carries the item schema — Chart.series items require name and dataKey —
    and A2UI composed a series with neither, because nothing it was shown said
    they existed."""
    from services.a2ui_catalog import load_contracts, props_for

    series = props_for("Chart", load_contracts()).get("series") or {}
    items = series.get("items") or {}
    assert set(items.get("required") or []) >= {"name", "dataKey"}


def test_the_merge_keeps_the_contract_s_structural_props():
    """Merged, not swapped. Stack's align/direction/gap live in the contract
    and not in the Zod catalog, because the renderer dispatches Stack directly
    rather than registering it. Taking either source alone loses constraints."""
    from services.a2ui_catalog import load_contracts, props_for

    assert {"align", "direction", "gap"} <= set(props_for("Stack", load_contracts()))


def test_a_prop_with_no_zod_shape_is_left_as_the_contract_has_it():
    from services.a2ui_catalog import _prop_schema

    assert _prop_schema("tags", {"type": "array"}) == {"type": "array"}


def test_list_requires_items_at_composition_time():
    """`items` is z.array(Item).default([]), so an empty list renders as an
    empty list — correct at runtime, useless as a composition. A2UI, given a
    component with no declared place for its content, put children on it and
    the page was rejected for taking children it does not accept."""
    from services.a2ui_catalog import build_a2ui_catalog

    body = [b for b in build_a2ui_catalog()["components"]["List"]["allOf"]
            if "properties" in b][0]
    assert "items" in body["required"]
    assert "children" not in body["properties"], "List accepts no children"


def test_a_render_time_default_does_not_become_a_compose_time_option():
    """The distinction _COMPOSE_REQUIRED exists to hold: Chart.series carries
    a default too and is required by the contract already, so it needs no
    entry here."""
    from services.a2ui_catalog import build_a2ui_catalog

    body = [b for b in build_a2ui_catalog()["components"]["Chart"]["allOf"]
            if "properties" in b][0]
    assert "series" in body["required"]


def test_series_is_a_descriptor_not_a_binding():
    """`data` is the measurement; `series` says how to plot it. Described as a
    binding, A2UI sent a pointer and a2ui_to_forge had to notice and
    synthesise a descriptor — it already prefers a literal list
    (`already_shaped`) and calls series config, not measurement. The catalog
    was asking for the wrong thing."""
    from services.a2ui_catalog import build_a2ui_catalog

    body = [b for b in build_a2ui_catalog()["components"]["Chart"]["allOf"]
            if "properties" in b][0]
    series = body["properties"]["series"]
    assert series["type"] == "array"
    assert set(series["items"]["required"]) == {"name", "dataKey"}
    assert series["items"]["additionalProperties"] is False


def test_the_real_bindings_are_still_described_as_data():
    """rows and data are pointers — the composer must not invent their values."""
    from services.a2ui_catalog import build_a2ui_catalog

    body = [b for b in build_a2ui_catalog()["components"]["Chart"]["allOf"]
            if "properties" in b][0]
    assert "description" in body["properties"]["data"]
    assert "items" not in body["properties"]["data"]


# ---------------------------------------------------------------------------
# A chart has to name its data.
#
# One run shipped three charts carrying chartType, series, xKey and showGrid
# and no `data` at all — a dataset's columns described without ever naming a
# dataset. ChartNode coerces a missing `data` to [] so the chart renders empty
# rather than invalid, which is right for the renderer and blind for everyone
# else: it cannot tell "still loading" from "never bound".
# ---------------------------------------------------------------------------

def _required(name: str) -> set:
    from services.a2ui_catalog import build_a2ui_catalog
    body = build_a2ui_catalog()["components"][name]["allOf"][2]
    return set(body.get("required") or ())


def test_every_chart_must_be_given_its_data():
    assert "data" in _required("Chart")
    assert "data" in _required("Sparkline")
    assert "data" in _required("Heatmap")
    # A gauge reads one number rather than a series.
    assert "value" in _required("Gauge")


def test_requiring_data_does_not_disturb_the_charts_own_props():
    """`chartType` and `series` are required by the Zod contract itself; the
    compose contract adds to that list rather than replacing it."""
    assert {"chartType", "series"} <= _required("Chart")


def test_a_button_must_declare_how_it_acts():
    """Four optional ways to act meant a button could declare none, and a
    composer reading that invents the prop the schema seems to be missing —
    `Button.action`, which is neither ours nor A2UI's. It cost a whole page."""
    from services.a2ui_catalog import build_a2ui_catalog

    body = build_a2ui_catalog()["components"]["Button"]["allOf"][2]
    # All six the catalog offers. The first version of this list held four,
    # and a Button written with `opensDialog` — which a modal page needs — was
    # refused for declaring an action that was not on it.
    assert {tuple(a["required"]) for a in body["anyOf"]} == {
        ("workflow",), ("navigate",), ("submit",), ("onClick",),
        ("opensDialog",), ("togglesSidebar",)}
    # Still not required outright — which of the four is the composer's call.
    assert "workflow" not in (body.get("required") or [])


def test_components_with_one_obvious_action_are_left_alone():
    from services.a2ui_catalog import build_a2ui_catalog

    assert "anyOf" not in build_a2ui_catalog()["components"]["Text"]["allOf"][2]


def test_the_layout_primitives_say_which_way_they_go():
    """Stack and Row have no component file, so the summary extractor found no
    doc comment and the manifest fell back to "Stack (layout)". A2UI could see
    Row, needed the vertical counterpart, and wrote `Column` — on almost every
    page of every run, costing an attempt each time."""
    from services.a2ui_catalog import build_a2ui_catalog

    comps = build_a2ui_catalog()["components"]
    stack = comps["Stack"]["allOf"][2]["description"]
    assert "Vertical" in stack
    assert "Column" in stack        # names the thing it keeps reaching for
    assert "counterpart is Stack" in comps["Row"]["allOf"][2]["description"]


def test_row_says_repeated_records_belong_to_the_list_components():
    """`repeat` is a closed enum over page-contract lists (actions), and the
    only item references are $item.label/value/id — there is no per-row repeat
    over entity data. A2UI hand-built a row per plant and pointed each Badge at
    {"path": "statusVariant"}, which has nothing to resolve against; the page
    failed the enum and did not ship."""
    from services.a2ui_catalog import build_a2ui_catalog

    row = build_a2ui_catalog()["components"]["Row"]["allOf"][2]["description"]
    assert "not one row per record" in row
    assert "Table.rows" in row and "List.items" in row


def test_an_object_prop_is_described_as_an_object():
    """`Table.emptyAction` is {label, navigate?, workflow?} in Zod. Every
    branch of _prop_schema handled a scalar or an array and everything else
    fell through to DynamicString, so the catalog told A2UI it was text. A2UI
    wrote "New survey" — exactly what it was asked for — our own validator
    rejected it, and the application lost its list screen."""
    from services.a2ui_catalog import build_a2ui_catalog

    spec = (build_a2ui_catalog()["components"]["Table"]["allOf"][2]
            ["properties"]["emptyAction"])
    assert spec.get("type") == "object"
    assert "$ref" not in spec


def test_an_object_with_a_known_shape_carries_it():
    from services.a2ui_catalog import _prop_schema

    out = _prop_schema("emptyAction", {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
    })
    assert out["properties"] == {"label": {"type": "string"}}
    assert out["required"] == ["label"]
