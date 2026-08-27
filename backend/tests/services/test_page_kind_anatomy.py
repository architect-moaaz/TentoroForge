"""Substance floors for collection, record and form pages.

Why these exist
---------------
The A2UI composer is safe to leave switched on because of one property: it
writes nothing unless the page it produced clears a floor. That property is
only as wide as the floors, and until now the only floor was the dashboard's.
Widening the composer past the landing route without widening the floors would
trade the safety for the scope silently.

Every rule below is calibrated against the 78 output apps carrying a plan —
the plan is what declares a page's kind, and guessing from route shape instead
sweeps /login and /profile into "collections" (which is exactly the mistake
that produced a meaningless 29% before the numbers were checked):

    collection  n=477    3 no list surface    76 no action at all
    form        n= 73    4 no field/Form       2 no submit
    record      n= 36    1 no body             8 no action

84% of judged pages come back clean, which is the shape a floor should have:
it fires on a real minority, not on everything.
"""

import pytest

from services.page_kind_anatomy import page_family, page_kind_findings


def page(*types, route="/x"):
    kids = [{"type": t, "props": {}} for t in types]
    return {"schemaVersion": "2", "id": "p", "route": route,
            "root": {"type": "Stack", "props": {}, "children": kids}}


def rules(kind, doc, route="/x"):
    return [f["rule"] for f in page_kind_findings(kind, route, doc)]


# ────────────────────────────────────────────────────── kind → family mapping

def test_the_planner_vocabulary_collapses_to_three_shapes():
    """The planner names kinds with more words than there are shapes. Letting
    the rules multiply with the vocabulary is how they drift apart."""
    assert page_family("list") == page_family("collection") == "collection"
    assert page_family("create") == page_family("edit") == page_family("form") == "form"
    assert page_family("detail") == page_family("record") == "record"


def test_kinds_with_no_shape_opinion_are_left_alone():
    """Silence here means "not my rule", never "checked and fine". An auth
    page has no list and should not be told so."""
    assert page_family("auth") is None
    assert page_kind_findings("auth", "/login", page("Heading")) == []
    assert page_kind_findings("static", "/about", page("Text")) == []


# ─────────────────────────────────────────────────────────────── collection

def test_a_collection_with_no_list_surface_is_a_title_over_nothing():
    assert "collection_no_list_surface" in rules("list", page("Heading", "Text"))


def test_any_many_records_surface_satisfies_the_slot():
    """Matched by JOB, not by one blessed name — a Kanban is a list with an
    opinion about layout. Pinning the rule to Table teaches authors to satisfy
    the letter of it."""
    for t in ("Table", "Kanban", "Calendar", "List", "DataGrid", "Timeline"):
        assert "collection_no_list_surface" not in rules("list", page(t, "Button")), t


def test_a_collection_nobody_can_click_is_a_dead_end():
    """76 shipped list pages have no action of any kind: no create, no row
    action, nothing. The reader arrives and leaves."""
    assert "collection_no_action" in rules("list", page("Table"))
    assert "collection_no_action" not in rules("list", page("Table", "Button"))


# ─────────────────────────────────────────────────────────────────── record

def test_a_record_page_with_no_body_is_a_heading_over_whitespace():
    assert "record_no_body" in rules("detail", page("Heading"))
    assert "record_no_body" not in rules("detail", page("DescriptionList", "Button"))


def test_a_record_the_reader_cannot_act_on_is_flagged():
    """A third of shipped detail pages: you can see the record and do nothing
    with it — no edit, no delete, not even a way back."""
    assert "record_no_action" in rules("detail", page("DescriptionList"))


# ───────────────────────────────────────────────────────────────────── form

def test_a_form_with_no_field_collects_nothing():
    assert "form_no_fields" in rules("create", page("Heading", "Button"))


def test_the_form_node_counts_on_its_own():
    """`Form` carries its fields as a prop rather than as child nodes, so
    requiring a separate Input would fail every well-formed form."""
    assert "form_no_fields" not in rules("create", page("Form", "Button"))


def test_a_form_with_no_submit_cannot_deliver_what_it_collected():
    assert "form_no_submit" in rules("create", page("Input", "Select"))


# ───────────────────────────────────────────────────── false-positive guards

def test_a_redirect_page_is_a_routing_artifact_not_a_screen():
    """The route reconciler collapses duplicate routes into these, so
    `/staffs` legitimately holds one Redirect and nothing else. Eleven of the
    fourteen "collection has no table" hits were this — a gate that reports
    them teaches people to distrust it."""
    assert page_kind_findings("list", "/staffs", page("Redirect")) == []


def test_an_unreadable_page_never_passes_by_default():
    """Scoring what cannot be read as flawless is how ten legacy-shaped
    dashboards came back clean in an earlier survey."""
    out = rules("list", {"route": "/x", "root": None})
    assert out == ["collection_unreadable"]


def test_a_healthy_page_of_each_kind_is_silent():
    assert rules("list", page("Table", "Button")) == []
    assert rules("detail", page("DescriptionList", "Button")) == []
    assert rules("create", page("Form", "Button")) == []


def test_the_legacy_flat_page_shape_is_read_not_rejected():
    """Ten of 125 dashboards store the page AS the root node with no `root`
    key. `page_root` handles both; this pins that the kind floors inherit it."""
    flat = {"type": "Stack", "props": {},
            "children": [{"type": "Table", "props": {}},
                         {"type": "Button", "props": {"label": "New"}}]}
    assert rules("list", flat) == []
