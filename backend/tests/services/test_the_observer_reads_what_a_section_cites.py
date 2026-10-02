"""The observer is shown every requirement a section cites, wherever it cites it.

forge-v3, project 9naxfb3d (2026-09-22): `application_model` spent nine minutes
on one node. After a legitimate repair added a "Medical Safety Disclaimer"
capability citing REQ-029, the critic reported that "both the
requirementsCited and requirements arrays in the output are empty, so this
requirement ID does not exist anywhere in the artifact" — and sent the author
round twice more for it, then flagged it. The requirement existed; the
observer's slice read `requirements` at a row's top level only, and `product`
is one object whose capabilities each cite their own.
"""
from services.blueprint.observer import observation_context

DOC = {
    "application": {"name": "KV", "domain": "health", "description": "Kids vaccination"},
    "requirements": [
        {"id": "REQ-001", "description": "Parents see a child's schedule"},
        {"id": "REQ-029", "description": "No medical diagnosis or treatment advice"},
        {"id": "REQ-030", "description": "A doctor marks a dose given", "owner": "workflows"},
    ],
    "product": {
        "locale": "en", "objectives": [], "personas": [], "terminology": [],
        "capabilities": [
            {"name": "Schedule", "requirements": ["REQ-001"]},
            {"name": "Medical Safety Disclaimer", "requirements": ["REQ-029"]},
            {"name": "Dose recording", "requirements": ["REQ-030"]},
        ],
    },
}


def test_a_capabilitys_requirement_is_cited_and_shown():
    ctx = observation_context(DOC, agent="product_analysis")
    assert "REQ-029" in ctx["requirementsCited"] and "REQ-001" in ctx["requirementsCited"]
    assert {r["id"] for r in ctx["requirements"]} >= {"REQ-001", "REQ-029"}


def test_a_requirement_another_section_owns_is_still_not_graded_here():
    ctx = observation_context(DOC, agent="product_analysis")
    assert "REQ-030" not in ctx["requirementsCited"]


def test_only_requirement_ids_count_as_citations():
    doc = {**DOC, "product": {**DOC["product"], "capabilities": [
        {"name": "x", "requirements": ["REQ-001", "not an id", 7]}]}}
    ctx = observation_context(doc, agent="product_analysis")
    assert ctx["requirementsCited"] == ["REQ-001"]
