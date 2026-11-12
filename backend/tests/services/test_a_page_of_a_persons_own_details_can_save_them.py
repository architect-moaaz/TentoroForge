"""A page that shows a person's own record has a workflow that saves it.

Found building a ride-hailing app: the onboarding wizard and the profile page showed the driver's own phone, licence and
bank details, and no workflow saved any of it. Forge now refuses that before the app is built, the way it refuses a
button that does nothing, and the workflow-writing agent is told the pattern."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import self_service
from services.blueprint.functional_completeness import functional_findings

BACKEND = Path(__file__).resolve().parents[2]


def doc(workflows=None, pages=None):
    fields = [{"name": n, "type": t} for n, t in [
        ("id", "uuid"), ("name", "string"), ("email", "string"), ("phone", "string"), ("profilePhoto", "image"),
        ("drivingLicenseNumber", "string"), ("bankAccountNumber", "string"), ("verificationStatus", "enum"),
        ("rating", "number"), ("totalRides", "number"), ("currentLocation", "location"), ("createdAt", "timestamp"),
    ]]
    return {
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Driver", "table": "drivers", "account": True, "fields": fields},
            {"id": "ENTITY-002", "name": "Ride", "table": "rides", "fields": [{"name": "id", "type": "uuid"}, {"name": "fare", "type": "number"}]},
        ]},
        "security": {"ownershipRules": [{"entity": "Driver", "column": "id", "kind": "scope", "scope": "user"}]},
        "pages": pages if pages is not None else [
            {"id": "PAGE-002", "name": "Driver Onboarding", "route": "/onboarding", "pattern": "wizard", "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-003", "name": "Verification Status", "route": "/profile/verification", "data": {"primaryEntity": "ENTITY-001"}},
            {"id": "PAGE-004", "name": "Rides", "route": "/rides", "data": {"primaryEntity": "ENTITY-002"}},
        ],
        "workflows": workflows or [],
    }


def step(table, values):
    return {"key": "s", "config": {"actionType": "db_update", "table": table, "values": {v: "x" for v in values}}}


SUBMIT = {"id": "FLOW-1", "name": "Submit onboarding", "launchedFrom": ["PAGE-002"], "steps": [step("drivers", ["verificationStatus"])]}
SAVE = {"id": "FLOW-2", "name": "Save my details", "launchedFrom": ["PAGE-002"], "steps": [step("drivers", ["phone", "drivingLicenseNumber", "bankAccountNumber"])]}
ADMIN = {"id": "FLOW-3", "name": "Approve driver", "launchedFrom": [], "steps": [step("drivers", ["verificationStatus", "rating"])]}


def pages_flagged(d):
    return [f["page"] for f in self_service.findings(d)]


def test_a_wizard_that_shows_the_persons_own_record_with_no_way_to_save_it_is_refused():
    found = self_service.findings(doc([SUBMIT]))
    assert [f["page"] for f in found] == ["PAGE-002"]
    assert found[0]["rule"] == "own-details-cannot-be-saved"
    text = found[0]["detail"]
    assert "Save my driver" in text and "$user.id" in text and "phone" in text and "bankAccountNumber" in text


def test_a_workflow_launched_from_the_page_that_writes_what_they_may_change_clears_it():
    assert pages_flagged(doc([SUBMIT, SAVE])) == []


def test_a_workflow_that_only_moves_a_status_is_not_a_way_to_save_the_details():
    assert pages_flagged(doc([SUBMIT])) == ["PAGE-002"]


def test_what_the_person_may_not_change_is_never_asked_for():
    fields = self_service.editable_fields(doc([ADMIN]), doc()["data"]["entities"][0])
    assert fields == ["name", "phone", "profilePhoto", "drivingLicenseNumber", "bankAccountNumber"]
    for never in ("id", "email", "verificationStatus", "rating", "totalRides", "currentLocation", "createdAt"):
        assert never not in fields


def test_a_page_that_only_shows_a_standing_is_not_a_form():
    assert "PAGE-003" not in pages_flagged(doc([SUBMIT]))


def test_a_page_about_something_else_is_left_alone():
    assert "PAGE-004" not in pages_flagged(doc([SUBMIT]))


def test_an_app_with_no_record_owned_by_the_person_has_nothing_to_check():
    d = doc([SUBMIT])
    d["data"]["entities"][0]["account"] = False
    d["security"]["ownershipRules"] = []
    assert self_service.findings(d) == []


def test_the_refusal_reaches_the_completeness_findings():
    rules = [f["rule"] for f in functional_findings(doc([SUBMIT]))]
    assert "own-details-cannot-be-saved" in rules
    assert "own-details-cannot-be-saved" not in [f["rule"] for f in functional_findings(doc([SUBMIT, SAVE]))]


def test_the_workflow_agent_is_told_the_pattern_before_it_writes():
    text = (BACKEND / "services" / "blueprint" / "executors.py").read_text(encoding="utf-8")
    assert "A PERSON'S OWN DETAILS NEED A WORKFLOW TO BE SAVED" in text
    assert "Save my <thing>" in text and "keep a field left empty as it" in text
