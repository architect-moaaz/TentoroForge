"""What must happen is said by the architect and tried as the person (2026-10-08).

TCommerce's definition said shoppers only see active products, that a shopper
can add to the cart, that the admin starts on the admin console; the app did
none of it, and every check passed, because every check asked whether the app
was broken and none knew what right was. The acceptance criteria were prose
only a review screen read.

Now the testing agent writes `expectations` — statements of who does what,
from what, and what must follow — and one runner tries every one in the
running application. These tests hold the parts that need no browser: the
contract, what a statement may name, who writes which part, and how the
runner judges what it saw. The fixture is a clinic on purpose: nothing here
may know what any application is for.
"""
from __future__ import annotations

import copy

import pytest

from services.expects import resolve
from services.expects import statements as st

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Patient"}, {"id": "ROLE-002", "name": "Admin"}],
    "navigation": {"initialRoute": {"Patient": "/visits", "Admin": "/admin"}},
    "requirements": [
        {"id": "REQ-001", "area": "Booking", "description": "A patient books a visit.",
         "acceptanceCriteria": ["A patient can book an open slot."]},
        {"id": "REQ-002", "area": "Booking", "description": "A patient sees their visits.",
         "acceptanceCriteria": ["A patient sees their own visits."]},
        {"id": "REQ-003", "area": "Clinic", "description": "The admin closes a slot.",
         "acceptanceCriteria": ["A closed slot cannot be booked."]},
        {"id": "REQ-004", "description": "Change the menu to a sidebar."},
    ],
    "businessRules": [{"id": "RULE-001", "name": "One booking a slot", "requirements": ["REQ-001"],
                       "statement": "A slot is booked at most once."}],
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Slot", "table": "slots", "labelField": "label",
         "fields": [{"name": "label", "type": "string"}, {"name": "isOpen", "type": "boolean"}]},
        {"id": "ENTITY-002", "name": "Visit", "table": "visits",
         "fields": [{"name": "slotId", "type": "uuid"}, {"name": "note", "type": "string"}]},
    ]},
    "pages": [
        {"id": "PAGE-001", "name": "Slots", "route": "/slots", "access": "public"},
        {"id": "PAGE-002", "name": "Slot", "route": "/slots/[id]", "access": "public"},
        {"id": "PAGE-003", "name": "Visits", "route": "/visits", "users": ["ROLE-001"]},
        {"id": "PAGE-004", "name": "Admin", "route": "/admin", "users": ["ROLE-002"]},
        {"id": "PAGE-005", "name": "Sign in", "route": "/login", "pattern": "auth", "access": "public"},
    ],
    "workflows": [{"id": "FLOW-001", "name": "Book", "launchedFrom": ["PAGE-002"]}],
}

BOOKS = {
    "id": "EXP-001", "kind": "action", "says": "A patient books an open slot and sees it in their visits.",
    "requirements": ["REQ-001"], "rules": ["RULE-001"],
    "given": [{"ref": "ten", "entity": "ENTITY-001", "values": {"label": "Tuesday 10:00", "isOpen": True}}],
    "steps": [{"as": "ROLE-001", "act": "open", "page": "PAGE-002", "record": "ten"},
              {"as": "ROLE-001", "act": "do", "what": "book this slot"}],
    "then": [{"check": "told", "told": "success"},
             {"check": "sees", "page": "PAGE-003", "record": "ten"},
             {"check": "stored", "entity": "ENTITY-002", "values": {"slotId": "@ten"}}],
}
ARRIVES = {
    "id": "EXP-002", "kind": "arrival", "says": "A patient who signs in lands on their visits.",
    "steps": [{"as": "ROLE-001", "act": "sign_in"}], "then": [{"check": "on", "page": "PAGE-003"}],
}


def _doc(*exps):
    doc = copy.deepcopy(DOC)
    doc["expectations"] = [copy.deepcopy(e) for e in exps]
    return doc


# --------------------------------------------------------------------------- #
# The contract
# --------------------------------------------------------------------------- #

def test_the_contract_holds_statements():
    import json
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json").read_text())
    item = schema["properties"]["expectations"]["items"]
    assert item["properties"]["id"]["pattern"].startswith("^EXP-")
    assert set(item["required"]) >= {"id", "says", "kind", "steps", "then"}
    check = item["properties"]["then"]["items"]["properties"]["check"]["enum"]
    assert set(check) == set(st.CHECKS)
    act = item["properties"]["steps"]["items"]["properties"]["act"]["enum"]
    assert set(act) == set(st.ACTS), "the checker and the contract know the same verbs"


# --------------------------------------------------------------------------- #
# What a statement may name
# --------------------------------------------------------------------------- #

def test_a_statement_that_names_what_the_app_has_is_accepted():
    assert st.statement_findings(_doc(), BOOKS) == []
    assert st.statement_findings(_doc(), ARRIVES) == []


@pytest.mark.parametrize("mend,needle", [
    (lambda e: e["steps"][0].update(page="PAGE-404"), "names the screen PAGE-404"),
    (lambda e: e["given"][0]["values"].update(colour="red"), "sets colour, which Slot does not have"),
    (lambda e: e["steps"][1].update(what=""), "say `what` the person does"),
    (lambda e: e["steps"][0].update(**{"as": "ROLE-404"}), "neither a role id nor 'guest'"),
    (lambda e: e["then"][0].pop("told"), "without saying which"),
    (lambda e: e["then"][1].update(record="nine"), "not among the given records"),
    (lambda e: e["then"].append({"check": "gets", "page": "PAGE-004"}), "without saying what"),
    (lambda e: e["then"].append({"check": "on"}), "without a `page`"),
    (lambda e: e["steps"].append({"as": "guest", "act": "sign_in"}), "done as the role they sign in as"),
    (lambda e: e.update(requirements=["REQ-404"]), "REQ-404, which is not a requirement"),
])
def test_a_statement_that_cannot_be_tried_is_refused_naming_why(mend, needle):
    e = copy.deepcopy(BOOKS)
    mend(e)
    found = st.statement_findings(_doc(), e)
    assert any(needle in f for f in found), found


def test_an_email_is_not_a_record_reference():
    e = copy.deepcopy(BOOKS)
    e["given"][0]["values"]["label"] = "jane@example.com"
    assert st.statement_findings(_doc(), e) == [], "an @ inside a value is an email, not a record"
    e["given"][0]["values"]["label"] = "@nobody"
    assert any("@nobody" in f for f in st.statement_findings(_doc(), e))


def test_a_record_looked_for_on_a_screen_needs_a_name():
    e = copy.deepcopy(BOOKS)
    e["given"][0]["values"] = {"isOpen": True}
    assert any("has a name or title to be found by" in f for f in st.statement_findings(_doc(), e))


# --------------------------------------------------------------------------- #
# Who writes which part
# --------------------------------------------------------------------------- #

def test_the_people_and_the_requirements_are_written_in_parts(monkeypatch):
    monkeypatch.setattr(st, "REQUIREMENTS_PER_SUBJECT", 2)
    parts = st.expect_subjects(_doc())
    assert list(parts) == [st.PEOPLE, "REQ-001", "REQ-003"], "an area's requirements stay together"
    assert parts["REQ-001"] == {"requirements": ["REQ-001", "REQ-002"], "rules": ["RULE-001"], "processes": []}
    assert parts["REQ-003"]["processes"] == ["FLOW-001"], "a process serving no part's requirement goes to the last"
    assert "REQ-004" in parts["REQ-003"]["requirements"], "a requirement without criteria is tried by its words"


def test_a_group_with_many_processes_hands_the_rest_to_further_calls(monkeypatch):
    """Ecom L1 (2026-10-11): 62 processes in one call, cut off at the output
    cap twice."""
    monkeypatch.setattr(st, "PROCESSES_PER_SUBJECT", 3)
    doc = _doc()
    doc["workflows"] = [{"id": f"FLOW-00{i}", "name": f"P{i}", "status": "ACTIVE", "trigger": {"kind": "manual"},
                         "launchedFrom": ["PAGE-001"], "requirements": ["REQ-003"]} for i in range(1, 8)]
    parts = st.expect_subjects(doc)
    assert [len(p["processes"]) for p in parts.values()] == [0, 3, 3, 1]
    assert list(parts)[2:] == ["FLOW-004", "FLOW-007"]
    assert parts["FLOW-004"] == {"requirements": [], "rules": [], "processes": ["FLOW-004", "FLOW-005", "FLOW-006"]}
    assert st.subject_ask(doc, "FLOW-004").count("FLOW-00") == 3


def test_a_part_is_held_to_what_it_was_asked_to_cover(monkeypatch):
    monkeypatch.setattr(st, "REQUIREMENTS_PER_SUBJECT", 2)
    doc = _doc()
    assert any("REQ-002" in f for f in st.coverage_findings(doc, [BOOKS], "REQ-001"))
    assert st.coverage_findings(doc, [BOOKS], "REQ-003") == [
        "REQ-003 (The admin closes a slot.) is a requirement no statement tries",
        "REQ-004 (Change the menu to a sidebar.) is a requirement no statement tries",
        "FLOW-001 (Book) is a process no statement starts — give a `do` step its id in `workflow`"]
    starts = copy.deepcopy(BOOKS)
    starts["steps"][1]["workflow"] = "FLOW-001"
    assert not any("FLOW-001" in f for f in st.coverage_findings(doc, [starts], "REQ-003")), \
        "a step that names the process it starts covers it"
    people = st.coverage_findings(doc, [ARRIVES], st.PEOPLE)
    assert len(people) == 1 and "ROLE-002 (Admin) starts on /admin" in people[0], \
        "every person who has a landing page is signed in to see that they land there"


def test_a_call_is_refused_for_its_own_part_and_a_lone_statement_for_its_shape():
    from services.blueprint.agent_contract import (AgentResult, ArtifactProposal, InvalidExpectation,
                                                   check_expectations)
    result = AgentResult(task_id="t", agent="testing",
                         proposals=[ArtifactProposal("expectations", BOOKS["says"], copy.deepcopy(BOOKS))])
    result.subject = "REQ-001"  # type: ignore[attr-defined]
    with pytest.raises(InvalidExpectation, match="REQ-002"):
        check_expectations(result, _doc())
    lone = AgentResult(task_id="t", agent="testing",
                       proposals=[ArtifactProposal("expectations", BOOKS["says"], copy.deepcopy(BOOKS))])
    check_expectations(lone, _doc(BOOKS))   # a statement added later is held to its shape alone


def test_the_build_writes_them_and_the_testing_agent_owns_them(monkeypatch):
    monkeypatch.setattr(st, "REQUIREMENTS_PER_SUBJECT", 2)
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG, subjects_for
    node = DAG["expectations"]
    assert node.agent == "testing" and node.produces == frozenset({"expectations"}) and node.optional
    assert {"page_details", "workflows", "security", "business_rules"} <= set(node.depends_on)
    assert not any("expectations" in DAG[k].depends_on for k in ("page_code",)), \
        "nothing waits on the statements while the pages are written"
    assert subjects_for(node, _doc()) == [st.PEOPLE, "REQ-001", "REQ-003"]
    assert "expectations" in AGENT_REGISTRY["testing"].writes


def test_the_writers_task_knows_no_application():
    import re
    words = st.EXPECT_PROMPT.lower()
    for domain in ("shop", "shopper", "cart", "product", "orders", "checkout", "patient", "clinic", "invoice",
                   "basket", "bag", "stock"):
        assert not re.search(rf"\b{domain}\b", words), \
            f"the writer's task names {domain!r}; it must hold for every application"


# --------------------------------------------------------------------------- #
# How the runner judges what it saw
# --------------------------------------------------------------------------- #

class _App:
    base = "http://127.0.0.1:1"
    clone = None


def _trial():
    from services.expects.runner import Trial
    return Trial(_App(), _doc(BOOKS), browser=None, recipes=None, logins=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("calls,said,want", [
    ([{"method": "POST", "path": "/api/workflows/FLOW-001/execute", "status": 200, "body": "{}"}], {}, "success"),
    ([{"method": "POST", "path": "/api/workflows/FLOW-001/execute", "status": 422, "body": "{}"}], {}, "refusal"),
    ([{"method": "POST", "path": "/api/x", "status": 200, "body": '{"refused": true}'}], {}, "refusal"),
    ([{"method": "POST", "path": "/api/x", "status": 500, "body": "boom"}], {}, "error"),
    ([], {"invalid": ["email: Please fill in this field."]}, "refusal"),
    ([], {"messages": ["Only 2 left in stock"]}, "refusal"),
    ([{"method": "GET", "path": "/api/data/slots", "status": 200}], {}, "nothing"),
    ([], {"held_back": ["Increase quantity"]}, "refusal"),
])
def test_what_the_application_answered_is_read_from_what_it_sent_back(calls, said, want):
    got, _ = _trial().told({"calls": calls, **said})
    assert got == want


@pytest.mark.parametrize("nav,check,want", [
    ({"status": 200, "url": "http://127.0.0.1:1/login?callbackUrl=%2Fadmin", "text": "Sign in"},
     {"page": "PAGE-004"}, "sign_in_asked"),
    ({"status": 404, "url": "http://127.0.0.1:1/slots/x", "text": ""}, {"address": "/slots/x"}, "not_found"),
    ({"status": 200, "url": "http://127.0.0.1:1/slots/x", "text": "This page could not be found."},
     {"address": "/slots/x"}, "not_found"),
    ({"status": 200, "url": "http://127.0.0.1:1/admin", "text": "This action is not available to your role"},
     {"page": "PAGE-004"}, "not_allowed"),
    ({"status": 200, "url": "http://127.0.0.1:1/admin", "text": "Dashboard"}, {"page": "PAGE-004"}, "shown"),
    ({"status": 200, "url": "http://127.0.0.1:1/visits", "text": "Your visits"}, {"page": "PAGE-004"},
     "sent to /visits"),
])
def test_what_opening_a_screen_gave_is_read_from_where_it_landed(nav, check, want):
    t = _trial()
    where = check.get("address") or "/admin"
    assert t._gets(nav, where, check) == want


def test_a_record_that_opens_in_a_panel_is_opened_there():
    t = _trial()
    t.pages["PAGE-001"]["sections"] = [{"key": "list", "placement": "main", "entity": "ENTITY-001"},
                                       {"key": "slot", "placement": "panel", "param": "slot", "entity": "ENTITY-001"}]
    t.given["ten"] = {"id": "abc", "entity": "ENTITY-001", "values": {"label": "Tuesday 10:00"}, "row": {}}
    assert t.address("PAGE-001", "ten") == "/slots?slot=abc"
    assert t.address("PAGE-001") == "/slots"


def test_a_screen_with_a_record_is_opened_on_that_record():
    t = _trial()
    t.given["ten"] = {"id": "abc", "entity": "ENTITY-001", "values": {"label": "Tuesday 10:00"}, "row": {}}
    assert t.address("PAGE-002", "ten") == "/slots/abc"
    assert t.address(address="/slots/@ten/edit") == "/slots/abc/edit"
    assert t.label("ten") == "Tuesday 10:00", "found on a screen by its label field"


def test_a_remembered_control_is_found_again_by_what_a_person_knows_it_by():
    controls = [{"idx": 0, "role": "button", "name": "Book", "within": "Monday 09:00"},
                {"idx": 1, "role": "button", "name": "Book", "within": "Tuesday 10:00"},
                {"idx": 2, "role": "textbox", "name": "Note", "field": "note"}]
    assert resolve.find({"role": "button", "name": "Book", "within": "Tuesday 10:00"}, controls) == 1
    assert resolve.find({"role": "textbox", "name": "Note", "field": "note", "placeholder": "gone"}, controls) == 2
    assert resolve.find({"role": "button", "name": "Cancel"}, controls) is None


def test_a_record_that_points_at_another_names_a_given_one():
    e = copy.deepcopy(BOOKS)
    e["given"].append({"ref": "v", "entity": "ENTITY-002", "values": {"slotId": "slot-1", "note": "x"}})
    assert any("slotId to 'slot-1'" in f for f in st.statement_findings(_doc(), e)), \
        "a made-up id is refused; the record it points at is given and named @ref"
    e["given"][-1]["values"]["slotId"] = "@ten"
    assert st.statement_findings(_doc(), e) == []


def test_a_given_record_is_completed_with_what_the_statement_left_out():
    from services.expects.runner import complete
    entity = {"fields": [
        {"name": "id", "type": "uuid"},
        {"name": "name", "type": "string", "required": True},
        {"name": "slug", "type": "string", "required": True, "unique": True},
        {"name": "status", "type": "enum", "required": True, "values": ["open", "closed"]},
        {"name": "price", "type": "decimal", "required": True},
        {"name": "active", "type": "boolean", "required": True},
        {"name": "ownerId", "type": "uuid", "required": True},
        {"name": "createdAt", "type": "datetime", "required": True},
        {"name": "note", "type": "string"}]}
    got = complete(entity, {"name": "Tuesday 10:00"}, "exp007")
    assert got["name"] == "Tuesday 10:00", "what the statement says is kept"
    assert got["slug"] == "tuesday-10-00-exp007", "made unique to the statement"
    assert got["status"] == "open" and got["price"] == 1 and got["active"] is True
    assert "ownerId" not in got, "a record it points at is the statement's to give, or the app's to stamp"
    assert "createdAt" not in got and "note" not in got and "id" not in got


def test_a_person_who_signs_in_is_that_person_from_the_start():
    e = copy.deepcopy(ARRIVES)
    e["steps"] = [{"as": "guest", "act": "open", "page": "PAGE-003"}, {"as": "ROLE-001", "act": "sign_in"}]
    assert any("another browser" in f for f in st.statement_findings(_doc(), e))
    e["steps"][0]["as"] = "ROLE-001"
    assert st.statement_findings(_doc(), e) == [], "signed out until step 2, then signed in, in one browser"


def test_the_checks_see_each_person_as_they_end():
    e = copy.deepcopy(ARRIVES)
    e["steps"] = [{"as": "ROLE-001", "act": "sign_in"}, {"as": "ROLE-001", "act": "sign_out"},
                  {"as": "ROLE-002", "act": "sign_in"}]
    e["then"] = [{"check": "gets", "as": "ROLE-001", "page": "PAGE-004", "gets": "not_allowed"}]
    assert any("judged signed out" in f for f in st.statement_findings(_doc(), e))


def test_whose_a_record_is_comes_from_who_makes_it():
    doc = _doc()
    doc["security"] = {"ownershipRules": [{"entity": "Visit", "column": "patientId", "kind": "scope",
                                           "scope": "user", "guestColumn": "guestToken"}]}
    doc["data"]["entities"][1]["fields"] += [{"name": "patientId", "type": "uuid", "required": True},
                                             {"name": "guestToken", "type": "string"}]
    e = copy.deepcopy(BOOKS)
    e["given"].append({"ref": "v", "entity": "ENTITY-002", "as": "ROLE-001", "values": {"slotId": "@ten"}})
    assert st.statement_findings(doc, e) == [], "the owner is stamped by the app, not given"
    e["given"][-1]["values"]["guestToken"] = "abc"
    assert any("fills that from whoever makes it" in f for f in st.statement_findings(doc, e))


def test_a_given_record_may_point_at_one_listed_after_it():
    e = copy.deepcopy(BOOKS)
    e["given"] = [{"ref": "visit", "entity": "ENTITY-002", "values": {"slotId": "@ten", "note": "x"}},
                  {"ref": "ten", "entity": "ENTITY-001", "values": {"label": "Tuesday 10:00"}}]
    assert st.statement_findings(_doc(), e) == [], "the runner makes them in the order they point"
    assert [g["ref"] for g in st.given_order(e["given"])] == ["ten", "visit"]
    e["given"][1]["values"]["label"] = "@visit"
    assert any("loop" in f for f in st.statement_findings(_doc(), e))


def test_who_is_turned_away_is_read_from_the_access_rule_not_the_audience():
    doc = _doc()
    doc["pages"][2]["access"] = "authenticated"          # /visits: made for patients, open to anyone signed in
    e = copy.deepcopy(ARRIVES)
    e["steps"] = [{"as": "ROLE-002", "act": "sign_in"}]
    e["then"] = [{"check": "gets", "as": "ROLE-002", "page": "PAGE-003", "gets": "not_allowed"}]
    assert any("its access says they may open it" in f for f in st.statement_findings(doc, e))
    doc["pages"][2]["access"] = "role_restricted"
    assert st.statement_findings(doc, e) == [], "restricted to patients, the admin is rightly turned away"
    assert st.may_open(doc, doc["pages"][2]) == ["Patient"]


def test_only_someone_signed_out_is_asked_to_sign_in():
    e = copy.deepcopy(ARRIVES)
    e["then"] = [{"check": "gets", "as": "ROLE-001", "page": "PAGE-003", "gets": "sign_in_asked"}]
    assert any("check that as `guest`" in f for f in st.statement_findings(_doc(), e))
    e["then"][0]["as"] = "guest"
    assert st.statement_findings(_doc(), e) == []



def test_text_looked_for_on_a_screen_comes_from_a_record_or_the_requirements():
    e = copy.deepcopy(BOOKS)
    e["then"] = [{"check": "sees", "page": "PAGE-003", "text": "Your slot is confirmed, enjoy!"}]
    assert any("no requirement, rule, process or screen says" in f for f in st.statement_findings(_doc(), e))
    for fine in ("Tuesday 10:00", "book an open slot", "19.99"):
        e["then"][0]["text"] = fine
        assert st.statement_findings(_doc(), e) == [], fine


def test_a_record_with_no_name_is_found_by_what_it_points_at():
    t = _trial()
    t.given["shirt"] = {"id": "p1", "entity": "ENTITY-001", "values": {"name": "Linen Shirt"}, "row": {}}
    t.given["size"] = {"id": "v1", "entity": "ENTITY-001", "values": {"productId": "p1", "size": "M"}, "row": {}}
    t.given["line"] = {"id": "c1", "entity": "ENTITY-002", "values": {"variantId": "v1", "quantity": 2}, "row": {}}
    assert t.label("line") == "Linen Shirt", "a cart line is shown by its product's name"
    e = copy.deepcopy(BOOKS)
    e["given"] = [{"ref": "ten", "entity": "ENTITY-001", "values": {"label": "Tuesday 10:00"}},
                  {"ref": "visit", "entity": "ENTITY-002", "values": {"slotId": "@ten"}}]
    e["then"] = [{"check": "sees", "page": "PAGE-003", "record": "visit"}]
    assert st.statement_findings(_doc(), e) == [], "found by the slot it points at, no name field needed"


def test_a_record_that_belongs_to_someone_is_made_as_them():
    doc = _doc()
    doc["security"] = {"ownershipRules": [{"entity": "Visit", "column": "patientId", "kind": "scope", "scope": "user"}]}
    doc["data"]["entities"][1]["fields"].append({"name": "patientId", "type": "uuid", "required": True})
    e = copy.deepcopy(BOOKS)
    e["given"].append({"ref": "v", "entity": "ENTITY-002", "values": {"slotId": "@ten"}})
    assert any("belongs to someone" in f for f in st.statement_findings(doc, e)), "made by the admin, it is nobody's"
    e["given"][-1]["as"] = "ROLE-001"
    assert not any("belongs to someone" in f for f in st.statement_findings(doc, e))


def test_a_guests_steps_before_a_roles_sign_in_are_mended_into_that_persons():
    """Ecom L1 (2026-10-11): every arrival statement was written "a guest
    opens the page, then the role signs in", refused, and mended by an edit
    turn; the mend is deterministic, so the seam does it."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, check_expectations
    body = {"says": "A patient sent to sign in from Visits is brought back.", "kind": "arrival",
            "requirements": ["REQ-002"],
            "steps": [{"as": "guest", "act": "open", "page": "PAGE-003"},
                      {"as": "ROLE-001", "act": "sign_in"}],
            "then": [{"check": "on", "as": "ROLE-001", "page": "PAGE-003"}]}
    assert any("another browser" in f for f in st.statement_findings(DOC, copy.deepcopy(body)))
    result = AgentResult(task_id="T", agent="testing", proposals=[
        ArtifactProposal(section="expectations", natural_key="arrive", body=body)])
    check_expectations(result, DOC)
    assert body["steps"][0]["as"] == "ROLE-001"
    assert st.statement_findings(DOC, body) == []
