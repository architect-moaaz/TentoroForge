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


def test_a_feature_is_one_entity_and_all_of_its_pages():
    """The unit of decision is the feature, so half-built cannot be chosen."""
    features = {f["feature"]: f for f in page_slots(DOC)}
    assert set(features) == {"home", "ENTITY-001", "ENTITY-002"}
    assert {p["slot"] for p in features["ENTITY-001"]["pages"]} == {
        "ENTITY-001.list", "ENTITY-001.detail", "ENTITY-001.create"}


def test_completeness_is_asked_for_over_coverage():
    text = page_slot_prompt(DOC)
    assert "fill it completely or decline it completely" in text
    assert "few features a user can complete over many they cannot" in text


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
    assert "feature by feature" in user
    assert "ENTITY-001.list" in user
    assert "join table" in user


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
    assert "declining" in text


def test_relations_are_named_not_ided():
    """`reachedThrough: ['Job']` reads; `['E1']` needs a lookup the model
    has to do itself."""
    by = {f["feature"]: f for f in page_slots(REL_DOC) if f.get("entity")}
    assert by["E2"]["reachedThrough"] == ["Job"]
