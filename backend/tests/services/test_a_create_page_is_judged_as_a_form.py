"""A create screen is a form, whatever the pattern enum was able to call it.

The Blueprint's eighteen-value `pattern` enum offers `wizard`, `configuration`
and `settings` for the form family and nothing for the commonest screen in a
CRUD app. So `page_contracts` labelled `/contacts/new` and `/contacts/[id]/edit`
`record_workspace` — the least-bad value available to it — and everything
downstream behaved correctly on a false premise:

  * the family became `record`,
  * so the composer was handed the record job, "This screen shows ONE record in
    detail", for a page that exists to collect one,
  * so it composed a detail surface and never bound `FLOW-001 Create Contact`,
    which names that very page in its own `launchedFrom`,
  * so the record floor refused it: `record_no_action`.

Every page_layouts failure in two separate builds was a `/new` or form page —
15 of 38 on one, 2 of 5 on the other.

Two properties are held here. The route settles the family, and a `Form` is its
own submit: it renders the button from `submitLabel` and posts to `workflow`,
the same reason `_FIELD_TYPES` already counts it without child inputs.
"""
import pytest

from services.page_kind_anatomy import (
    _submits, page_family, page_kind_findings, route_family,
)

FORM_ROUTES = ["/contacts/new", "/contacts/[id]/edit", "/admin/users/new",
               "/cases/new", "/policy/[id]/edit"]
NON_FORM_ROUTES = ["/contacts", "/contacts/[id]", "/dashboard", "/sign-in",
                   "/newsletters"]


@pytest.mark.parametrize("route", FORM_ROUTES)
def test_a_create_or_edit_route_is_a_form(route):
    assert route_family(route) == "form"


@pytest.mark.parametrize("route", NON_FORM_ROUTES)
def test_other_routes_keep_their_declared_family(route):
    """`/newsletters` ends in the letters of "new" and is not a create page."""
    assert route_family(route) is None


def test_the_route_outranks_a_record_pattern():
    """The exact condition that refused /contacts/new on every build."""
    assert page_family("record_workspace") == "record"
    assert route_family("/contacts/new") == "form"


def test_a_form_is_its_own_submit():
    """A2UI composed {Container, Stack, Text, Link, Card, Form} for
    /contacts/new. There is no Button, and none is wanted — a second submit
    beside the Form's own would be the defect."""
    tree = {"type": "Container", "children": [
        {"type": "Form", "props": {"workflow": "FLOW-001",
                                   "submitLabel": "Save contact"}},
    ]}
    assert _submits(tree) is True


def test_a_form_with_no_action_still_fails():
    """The floor must not be widened into uselessness: a Form that submits
    nowhere is the original defect and stays caught."""
    tree = {"type": "Container", "children": [
        {"type": "Form", "props": {"fields": []}},
    ]}
    assert _submits(tree) is False


def test_a_create_page_holding_only_a_bound_form_clears_the_floor():
    """End to end through the public predicate, at the shape A2UI produces."""
    doc = {"root": {"type": "Container", "children": [
        {"type": "Form", "props": {"workflow": "FLOW-001",
                                   "submitLabel": "Save contact",
                                   "fields": [{"kind": "text", "name": "firstName",
                                               "label": "First name"}]}},
    ]}}
    findings = page_kind_findings("record_workspace", "/contacts/new", doc)
    assert findings == [], [f["rule"] for f in findings]
