"""The catalog must describe the components we actually have.

Four of five composer defects fixed on 2026-08-29 were one fault: the catalog
told A2UI something untrue about a prop, A2UI complied, and our own validator
rejected what our own catalog had asked for.

  Chart.data          declared, never required — charts shipped with no data
  Button.action       four ways to act, none required — a prop was invented
  Table.emptyAction   an object described as a string — a page was lost
  Stack / Row         no description at all — "Column" invented on most pages

Each had tests on both sides. `component-contracts.json` is generated from the
Zod components and has tests; `build_a2ui_catalog` has tests. Nothing tested
that the second faithfully describes the first, so twelve thousand tests passed
while the two disagreed.

This is that test. It compares every prop the catalog emits against the
contract it was built from — not against a list maintained here, which would be
a third copy of the same fact and a third thing to drift.
"""

import pytest

from services.a2ui_catalog import build_a2ui_catalog, load_contracts, props_for

_DYNAMIC = "DynamicString"


@pytest.fixture(scope="module")
def catalog():
    return build_a2ui_catalog()["components"]


@pytest.fixture(scope="module")
def contracts():
    return load_contracts()


def _body(catalog, name):
    return catalog[name]["allOf"][2]


def _emitted(catalog, name):
    return _body(catalog, name).get("properties") or {}


def _is_dynamic_string(schema: dict) -> bool:
    if _DYNAMIC in str(schema.get("$ref") or ""):
        return True
    return any(_DYNAMIC in str(alt.get("$ref") or "")
               for alt in schema.get("anyOf") or [])


def test_the_catalog_is_not_empty(catalog, contracts):
    """A guard on the guard: an empty catalog would pass every check below."""
    assert len(catalog) > 50
    assert len(contracts) > 50


def test_no_structured_prop_is_described_as_text(catalog, contracts):
    """The exact shape of the emptyAction defect.

    A prop the contract declares as an object, an array, a boolean or a number
    must not reach A2UI as a string. `Table.emptyAction` is
    {label, navigate?, workflow?} and was described as DynamicString, so A2UI
    wrote "New survey" and the surveys list page did not ship.
    """
    wrong: list[str] = []
    for name in catalog:
        emitted = _emitted(catalog, name)
        for prop, spec in props_for(name, contracts).items():
            declared = str(spec.get("type") or "").lower()
            if declared not in ("object", "array", "boolean", "number",
                                "integer"):
                continue
            schema = emitted.get(prop)
            if schema and _is_dynamic_string(schema):
                wrong.append(f"{name}.{prop}: contract says {declared},"
                             f" catalog says string")
    assert not wrong, "\n".join(wrong)


def test_declared_types_survive_into_the_catalog(catalog, contracts):
    """Structural types match, rather than merely not being strings."""
    expected = {"object": "object", "array": "array",
                "boolean": "boolean", "number": "number", "integer": "number"}
    wrong: list[str] = []
    for name in catalog:
        emitted = _emitted(catalog, name)
        for prop, spec in props_for(name, contracts).items():
            declared = str(spec.get("type") or "").lower()
            want = expected.get(declared)
            # An enum is emitted as members-or-binding, which is deliberate:
            # a status colour that follows the row is the ordinary case.
            if not want or spec.get("enum"):
                continue
            got = emitted.get(prop)
            # A binding prop is described rather than typed on purpose: the
            # renderer resolves `rows` from a dataSource, so a type would
            # forbid the binding. Scoped by shape as well as name, so
            # `Textarea.rows` (an integer) is not mistaken for data.
            if got is not None and set(got) == {"description"}:
                continue
            if got is not None and got.get("type") != want:
                wrong.append(f"{name}.{prop}: {declared} -> {got.get('type')}")
    assert not wrong, "\n".join(wrong)


def test_enum_members_come_through_intact(catalog, contracts):
    """Members are the contract's, not a list restated here — and a binding
    stays allowed beside them, which is what let a Badge follow its row."""
    wrong: list[str] = []
    for name in catalog:
        emitted = _emitted(catalog, name)
        for prop, spec in props_for(name, contracts).items():
            members = spec.get("enum")
            if not isinstance(members, list) or not members:
                continue
            schema = emitted.get(prop)
            if schema is None:
                continue
            alts = schema.get("anyOf") or []
            found = next((a.get("enum") for a in alts if a.get("enum")), None)
            if found is None:
                wrong.append(f"{name}.{prop}: enum lost")
            elif sorted(map(str, found)) != sorted(map(str, members)):
                wrong.append(f"{name}.{prop}: members differ")
            elif not _is_dynamic_string(schema):
                wrong.append(f"{name}.{prop}: enum cannot be bound")
    assert not wrong, "\n".join(wrong)


def test_a_required_prop_is_required_in_the_catalog(catalog, contracts):
    """The Chart.series defect: required-ness that never reached the composer
    produced a chart with rows and no encoding, valid to A2UI and blank to us.
    """
    wrong: list[str] = []
    for name in catalog:
        required = set(_body(catalog, name).get("required") or ())
        for prop, spec in props_for(name, contracts).items():
            if not spec.get("optional") and prop not in required:
                wrong.append(f"{name}.{prop} is required and not declared so")
    assert not wrong, "\n".join(wrong)


def test_every_contract_prop_reaches_the_catalog(catalog, contracts):
    """A prop dropped in translation cannot be used, and nothing says why."""
    missing: list[str] = []
    for name in catalog:
        emitted = _emitted(catalog, name)
        for prop in props_for(name, contracts):
            if prop not in emitted:
                missing.append(f"{name}.{prop}")
    assert not missing, "\n".join(missing)


def test_a_one_of_list_names_every_way_the_component_can_act():
    """The first Button list held four of the six action props the catalog
    offers, so `{label: "Edit", opensDialog: "editDialog"}` — correct, and what
    a page whose create form is a modal needs — was refused for declaring an
    action that was not on the list. The constraint was right; the enumeration
    was hand-written, and a hand-written enumeration of a generated set drifts.
    """
    from services.a2ui_catalog import _COMPOSE_ONE_OF, build_a2ui_catalog

    comps = build_a2ui_catalog()["components"]
    for name, choices in _COMPOSE_ONE_OF.items():
        body = comps[name]["allOf"][2]
        declared = {a["required"][0] for a in body.get("anyOf") or []}
        assert declared == set(choices), f"{name}: anyOf lost a choice"
        # Every choice must be a prop the component actually has, or the
        # composer is offered an alternative it cannot satisfy.
        missing = declared - set(body["properties"])
        assert not missing, f"{name}: offers {sorted(missing)}, which do not exist"
