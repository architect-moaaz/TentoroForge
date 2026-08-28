"""§32 — the page set is asked for slot by slot, not as a free list."""

from services.blueprint.executors import build_prompt
from services.blueprint.page_planner import page_slots

DOC = {
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Job"},
        {"id": "ENTITY-002", "name": "Customer"},
    ]},
    "pages": [],
}


def test_every_entity_gets_a_list_detail_and_create_slot():
    slots = page_slots(DOC)
    for entity in ("ENTITY-001", "ENTITY-002"):
        got = {s["slot"] for s in slots if s["entity"] == entity}
        assert got == {f"{entity}.list", f"{entity}.detail", f"{entity}.create"}


def test_there_is_no_slot_for_a_filtered_list():
    """The whole point: 'overdue jobs' has nowhere to go but `views`."""
    slots = page_slots(DOC)
    assert all("filter" not in s["slot"] for s in slots)
    assert sum(1 for s in slots if s["entity"] == "ENTITY-001") == 3


def test_an_app_with_no_entities_still_gets_a_home_slot():
    assert [s["slot"] for s in page_slots({"data": {"entities": []}})] == ["home"]


def test_slots_carry_the_pattern_the_page_should_use():
    by = {s["slot"]: s["pattern"] for s in page_slots(DOC)}
    assert by["ENTITY-001.list"] == "entity_list"
    assert by["ENTITY-001.detail"] == "record_workspace"
    assert by["ENTITY-001.create"] == "form"


def test_the_prompt_asks_slot_by_slot_and_allows_declining():
    _, user = build_prompt(DOC, "page_contracts")
    assert "slot by slot" in user
    assert "decline" in user.lower()
    assert "ENTITY-001.list" in user
    assert "views" in user


def test_declining_is_explained_so_lookups_do_not_get_pages():
    _, user = build_prompt(DOC, "page_contracts")
    assert "join table" in user
