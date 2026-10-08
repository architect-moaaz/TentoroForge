"""§32/§115 — the page set is asked for feature by feature, user first."""

from services.blueprint.executors import build_prompt
from services.blueprint.page_planner import page_slot_prompt, page_slots

DOC = {
    "application": {"description": "Track bikes dropped off for repair."},
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Bike", "requirements": ["REQ-001"]},
        {"id": "ENTITY-002", "name": "JobPart", "requirements": []},
    ]},
    "pages": [],
}


def test_a_record_is_asked_where_it_goes_not_given_pages():
    """Screens are the pages; a record is placed as a section of one."""
    features = {f["feature"]: f for f in page_slots(DOC)}
    assert set(features) == {"home", "ENTITY-001", "ENTITY-002"}
    assert [p["slot"] for p in features["ENTITY-001"]["pages"]] == ["ENTITY-001.place"]
    assert "a section of one of the screens above" in features["ENTITY-001"]["pages"][0]["prompt"]


def test_completeness_is_asked_for_over_coverage():
    text = page_slot_prompt(DOC)
    assert "serves its person fully beats three that each serve them partly" in text
    assert "a job a person cannot finish" in text


def test_the_users_own_words_travel_with_the_question():
    """§115 — what they asked for outranks what the shape suggests."""
    text = page_slot_prompt(DOC)
    assert "Track bikes dropped off for repair." in text
    assert "not declinable" in text


def test_requirements_travel_with_each_feature():
    features = {f["feature"]: f for f in page_slots(DOC)}
    assert features["ENTITY-001"]["requirements"] == ["REQ-001"]
    assert features["ENTITY-002"]["requirements"] == []


def test_nothing_is_marked_required_by_a_derived_signal():
    """Every entity carries requirements, so it would mark everything.

    A live run had 21 of 21 entities 'required' on that signal, and 37 of 39
    requirements citing application.description. A flag that is always true is
    not precedence, it is noise — the judgement belongs to the model, with the
    evidence in front of it.
    """
    assert all("required" not in f for f in page_slots(DOC))


def test_there_is_no_slot_for_a_filtered_list():
    slots = [p["slot"] for f in page_slots(DOC) for p in f["pages"]]
    assert all("filter" not in s for s in slots)
    assert page_slot_prompt(DOC).count("views") == 1


def test_the_prompt_carries_features_and_the_blueprint():
    _, user = build_prompt(DOC, "page_contracts")
    assert "people first, then the records" in user
    assert "ENTITY-001.place" in user
    assert "a line item lives on its order" in user


# --- §32: a relation is a fact, not an inference ----------------------------

REL_DOC = {
    "application": {"description": "Track bikes dropped off for repair."},
    "data": {"entities": [
        {"id": "E1", "name": "Job", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True}]},
        {"id": "E2", "name": "PartUsage", "fields": [
            {"name": "jobId", "type": "uuid", "required": True, "references": "E1"}]},
        {"id": "E3", "name": "Draft", "fields": [
            {"name": "jobId", "type": "uuid", "required": False, "references": "E1"}]},
    ]},
    "pages": [],
}


def test_a_required_reference_marks_the_feature_as_reached_through_it():
    by = {f["feature"]: f for f in page_slots(REL_DOC) if f.get("entity")}
    assert by["E2"]["reachedThrough"] == ["Job"]


def test_a_top_level_entity_is_reached_through_nothing():
    by = {f["feature"]: f for f in page_slots(REL_DOC) if f.get("entity")}
    assert by["E1"]["reachedThrough"] == []


def test_an_optional_reference_does_not_make_a_feature_a_child():
    """A nullable FK is an association, not a containment: a draft that may
    belong to a job is still something you go to."""
    by = {f["feature"]: f for f in page_slots(REL_DOC) if f.get("entity")}
    assert by["E3"]["reachedThrough"] == []


def test_the_prompt_tells_the_agent_what_reached_through_means():
    text = page_slot_prompt(REL_DOC)
    assert "reachedThrough" in text
    assert "a section of that one's panel" in text


def test_relations_are_named_not_ided():
    """`reachedThrough: ['Job']` reads; `['E1']` needs a lookup the model
    has to do itself."""
    by = {f["feature"]: f for f in page_slots(REL_DOC) if f.get("entity")}
    assert by["E2"]["reachedThrough"] == ["Job"]


# --- Mozato (forge-v3, 2026-10-06): 106 pages, 21 of them a create form ------
# beside a list of the same record, 46 for the back office, and no page where a
# customer could open a restaurant. Adding moved onto the list, and the people
# the product is for are asked about before the tables are.

PERSONAS = {**DOC, "product": {"personas": [
    {"name": "Customer", "description": "Drops a bike off and collects it",
     "goals": ["Know when the bike is ready"]},
    {"name": "Mechanic", "goals": ["Work through today's repairs"]},
]}}


def test_a_screen_holds_its_records_as_sections():
    """Mozato planned 106 routes for jobs a React screen does in one."""
    from services.blueprint.page_planner import SECTION_PLACEMENTS, SECTION_SHOWS
    text = page_slot_prompt(DOC)
    for word in ("`sections`", "`placement`", "`opensFrom`", "`param`", "`addsHere: true`", "`actions`"):
        assert word in text, word
    assert all(v in text for v in SECTION_SHOWS + SECTION_PLACEMENTS)
    assert "a record opened from a list is a panel with a `param`, not a route" in text
    assert "orders arrive and nothing accepts them is not finished" in text
    assert "A PAGE FOR ADDING is the exception" in text


def test_the_people_are_asked_about_before_the_tables():
    slots = page_slots(PERSONAS)
    order = [f["feature"] for f in slots]
    assert order[:3] == ["home", "journey:Customer", "journey:Mechanic"]
    customer = slots[1]
    assert customer["goals"] == ["Know when the bike is ready"] and customer["entity"] is None
    assert "see a record differently" in customer["pages"][0]["prompt"]
    assert "screens a Customer works in" in customer["pages"][0]["prompt"]
    assert "PEOPLE FIRST" in page_slot_prompt(PERSONAS)


def test_no_personas_no_journeys():
    assert not [f for f in page_slots(DOC) if f["feature"].startswith("journey:")]


def test_the_page_set_may_say_where_records_are_added():
    """Declared by the page-set call, kept through the contract author."""
    from services.blueprint.executors import _DECLARED_PAGE_FIELDS, _PINNED_PAGE_FIELDS, NODE_TASKS
    for field in ("addsHere", "sections"):
        assert field in _DECLARED_PAGE_FIELDS and field in _PINNED_PAGE_FIELDS, field
        assert field in NODE_TASKS["page_contracts"], field
