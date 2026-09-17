"""The platform's own rewrite of a composed page may never introduce a fault.

MEASURED ON UAT AND ON A LOCAL MASTER-DATA BUILD. One line in the step that
translates every composed page filled `value` from `label` on any `items`
list it met. Menus require that value; breadcrumbs and mobile navigation
forbid it. The contract then refused the page and told the composer to
remove a key it had never written:

    PAGE-001: root.children[1].props.items.0: Additional properties are not
    allowed ('value' was unexpected)

The composer removed nothing, because there was nothing to remove. The
translation added the key back. No answer could pass, so every affected page
spent every attempt: on LabConnect 121 such refusals behind 101 layout
retries, and 8 pages that never composed.

Three layers, one per test group below:

  1. The component's contract decides whether an item needs a value.
  2. A rewrite that makes a tree worse is reverted and logged as the
     platform's defect, so the composer is only held to what it wrote.
  3. Every component with an item list is swept, so a component added later
     is covered without anyone remembering to add a case.
"""
import copy
import logging

import pytest

import services.a2ui_to_forge as translation
from services.a2ui_to_forge import _Binder, _item_requires, _translate_option_sources
from services.blueprint.page_planner import load_catalog, validate_props

REG = {"entities": {}}
CATALOG = load_catalog()


def _page(*children):
    return {"type": "Stack", "id": "r", "props": {}, "children": list(children)}


def _node(kind, items):
    return {"type": kind, "id": kind.lower(), "props": {"items": items}, "children": []}


def _translate(root):
    _translate_option_sources(root, _Binder(REG, {}), REG)
    return root


def _errors(root):
    return validate_props({"root": root}, CATALOG)


# ------------------------------------------------ layer 1: the contract decides

def test_a_breadcrumb_entry_is_left_as_the_composer_wrote_it():
    root = _translate(_page(_node("Breadcrumb", [{"label": "Home", "href": "/"}])))
    assert root["children"][0]["props"]["items"] == [{"label": "Home", "href": "/"}]
    assert not [e for e in _errors(root) if "value" in e]


def test_a_mobile_nav_entry_is_left_as_the_composer_wrote_it():
    item = {"label": "Add Data", "href": "/add-data"}
    root = _translate(_page(_node("MobileNav", [dict(item)])))
    assert root["children"][0]["props"]["items"] == [item]


def test_a_menu_entry_still_gets_the_value_it_requires():
    root = _translate(_page(_node("DropdownMenu", [{"label": "Edit"}])))
    assert root["children"][0]["props"]["items"] == [{"label": "Edit", "value": "Edit"}]


def test_the_rule_reads_the_catalogue_not_the_shape():
    assert _item_requires("DropdownMenu", "value")
    assert not _item_requires("Breadcrumb", "value")
    assert not _item_requires("MobileNav", "value")
    # Tabs has no `items` list in its contract at all.
    assert not _item_requires("Tabs", "value")
    assert not _item_requires("NoSuchComponent", "value")


# ------------------------------------ layer 2: a rewrite may not make it worse

@pytest.fixture()
def the_old_rule(monkeypatch):
    """Reinstate the shape-driven fill, so the guard is tested on its own."""
    monkeypatch.setattr(translation, "_item_requires", lambda kind, key: True)


def test_a_rewrite_that_breaks_a_component_is_reverted(the_old_rule, caplog):
    root = _page(_node("Breadcrumb", [{"label": "Home", "href": "/"}]))
    with caplog.at_level(logging.ERROR):
        _translate(root)
    assert root["children"][0]["props"]["items"] == [{"label": "Home", "href": "/"}]
    assert not _errors(root)
    assert "PLATFORM DEFECT" in caplog.text
    assert "not blamed" in caplog.text


def test_only_the_broken_component_is_reverted(the_old_rule):
    """The menu's fill-in was right and is kept; the breadcrumb's was wrong."""
    root = _translate(_page(_node("Breadcrumb", [{"label": "Home", "href": "/"}]),
                            _node("DropdownMenu", [{"label": "Edit"}])))
    assert "value" not in root["children"][0]["props"]["items"][0]
    assert root["children"][1]["props"]["items"][0]["value"] == "Edit"


def test_a_fault_the_composer_wrote_is_still_the_composers():
    """The guard compares against the tree as written. A fault already there
    is left for the validator to report in the composer's own terms."""
    written = _page(_node("Breadcrumb", [{"label": "Home", "value": "x"}]))
    before = _errors(copy.deepcopy(written))
    assert before, "the fixture must start invalid"
    root = _translate(written)
    assert _errors(root) == before
    assert root["children"][0]["props"]["items"][0]["value"] == "x"


def test_the_revert_is_recorded_in_the_translation_ledger(the_old_rule):
    binder = _Binder(REG, {})
    binder.losses = translation.Losses()
    root = _page(_node("Breadcrumb", [{"label": "Home", "href": "/"}]))
    _translate_option_sources(root, binder, REG)
    kinds = [e["kind"] for e in binder.losses.entries]
    assert "translation_reverted" in kinds


# --------------------------------- layer 3: every component with an item list

def _item_list_components():
    out = []
    for name, entry in sorted(CATALOG.items()):
        props = ((entry or {}).get("props") or {}).get("properties") or {}
        if isinstance(props.get("items"), dict) and props["items"].get("type") == "array":
            out.append(name)
    return out


def test_the_sweep_finds_the_components_that_caused_this():
    names = _item_list_components()
    assert {"Breadcrumb", "MobileNav", "DropdownMenu"} <= set(names)


@pytest.mark.parametrize("kind", _item_list_components())
def test_translating_a_label_only_item_introduces_no_fault(kind):
    """For every component with an item list: whatever faults the page had as
    written, translation adds none. A component added to the library later is
    covered here without a new case."""
    root = _page(_node(kind, [{"label": "Something"}]))
    before = set(_errors(copy.deepcopy(root)))
    _translate(root)
    introduced = [e for e in _errors(root) if e not in before]
    assert not introduced, introduced


def _option_list_components():
    out = []
    for name, entry in sorted(CATALOG.items()):
        props = ((entry or {}).get("props") or {}).get("properties") or {}
        if isinstance(props.get("options"), dict):
            out.append(name)
    return out


def test_the_sweep_covers_the_second_defect_the_guard_found():
    """The guard's first run caught `placeholder` written onto a Select,
    whose contract has none — the same shape-not-contract mistake."""
    assert "Select" in _option_list_components()


@pytest.mark.parametrize("kind", _option_list_components())
def test_translating_a_captioned_option_list_introduces_no_fault(kind):
    """An empty-valued first option is how a composer writes a caption. For
    every component with an option list, taking it out adds no fault."""
    root = _page({"type": kind, "id": "o", "children": [], "props": {
        "name": "x", "label": "X",
        "options": [{"label": "Choose…", "value": ""}, {"label": "A", "value": "a"}]}})
    before = set(_errors(copy.deepcopy(root)))
    _translate(root)
    introduced = [e for e in _errors(root) if e not in before]
    assert not introduced, introduced
