"""Three refusals LabConnect's re-run earned that its pages could not answer.

Each is a check whose words and whose code disagreed, measured on the
2026-09-17 run of `d1bl1nes`: 8 composer attempts on /packages/[id], 6 on
/labs, and a retry loop on /labs that gave up without ever being told what it
had written wrong.
"""
import pytest

from services.page_demands import findings
from services.blueprint.functional_completeness import _acts_on_another_thing
from services.blueprint.page_planner import load_catalog, validate_props


# ------------------------------- a row action is an action; a filter is not

def _collection(*children):
    return {"root": {"type": "Container", "children": list(children)}}


TABLE = {"type": "Table", "props": {"data": "{{rows}}"}}


@pytest.mark.parametrize("child, acted_on", [
    ({"type": "FilterBar", "props": {"chips": []}}, False),
    ({"type": "Table", "props": {"data": "{{r}}", "rowActions": [{"label": "View"}]}}, True),
    ({"type": "Table", "props": {"data": "{{r}}", "onRowClick": "/labs/{{id}}"}}, True),
    ({"type": "Link", "props": {"href": "/labs/1"}}, True),
    # A card grid is how most designs list records; `Card.navigate` exists so
    # one can open what it shows, through the same seam a Link uses.
    ({"type": "Card", "props": {"title": "City Labs", "navigate": "/labs/1"}}, True),
    ({"type": "Card", "props": {"title": "City Labs"}}, False),
    ({"type": "Button", "props": {"label": "New"}}, True),
    ({"type": "Text", "props": {"value": "nothing"}}, False),
])
def test_what_counts_as_acting_on_a_listed_record(child, acted_on):
    rules = [f["rule"] for f in findings("collection", "/labs", _collection(TABLE, child))]
    assert ("collection_no_action" in rules) is not acted_on


def test_the_refusal_no_longer_promises_that_filtering_counts():
    """The composer read 'no filter control', added one, and was refused
    again — six times."""
    [finding] = [f for f in findings("collection", "/labs", _collection(TABLE))
                 if f["rule"] == "collection_no_action"]
    assert "Filtering" in finding["detail"], "say what does not count"
    assert "Filtering the list is not acting" in finding["detail"]


# ------------------------------ an association action is not a create action

@pytest.mark.parametrize("label, entity, other", [
    ("add_test_to_package", "TestPackage", True),
    ("remove_test_from_package", "TestPackage", True),
    ("add_lab_staff", "Lab", True),
    ("add_package", "TestPackage", False),
    ("create_package", "TestPackage", False),
    ("add", "TestPackage", False),
    ("add_test", "Test", False),
    ("edit_package", "TestPackage", False),
])
def test_an_action_naming_another_thing_is_not_this_pages_create(label, entity, other):
    assert _acts_on_another_thing(label, entity) is other


# ------------------------------- a prop error names the component it is about

def test_a_prop_error_says_which_component_and_what_it_takes():
    page = {"root": {"type": "Breadcrumb",
                     "props": {"items": [{"label": "Labs", "value": "/labs"}]}}}
    [error] = validate_props(page, load_catalog())
    assert "Breadcrumb" in error, "the path alone does not name the component"
    assert "'value' was unexpected" in error
    assert "accepts: label (required), href" in error
