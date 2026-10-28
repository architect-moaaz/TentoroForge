"""The Business Rules tab's API answers for the authorised project only, reads
and writes the Blueprint, and says why it refuses.

A project of the older pipeline (no Blueprint) answers `mode: legacy`, and its
tab keeps using /rules. Rules the tab saved to the old table are moved into the
definition the first time the tab reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"
ROLE = "ENTITY-002"
RULE = {"name": "Openings must be positive", "kind": "condition_action", "entity": ROLE,
        "when": "openingsCount < 1",
        "then": [{"id": "act_1", "type": "show_error", "message": "A role needs at least one opening."}]}


async def _project(client, org_id, *, defined=True) -> dict:
    from services.project_service import OUTPUT_BASE
    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Rules"})
    assert res.status_code == 201, res.text
    body = res.json()
    out = Path(OUTPUT_BASE) / body["short_id"]
    if defined:
        (out / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
        (out / ".forge" / "blueprint" / "current.json").write_text(FIXTURE.read_text())
        (out / "app").mkdir(exist_ok=True)
    return {**body, "out": out}


@pytest.mark.asyncio
async def test_list_create_edit_toggle_remove(auth_client, org_id):
    p = await _project(auth_client, org_id)
    base = f"/api/projects/{p['id']}/business-rules"

    listed = (await auth_client.get(base)).json()
    assert listed["mode"] == "blueprint" and listed["rules"] and listed["catalogue"]["entities"]

    res = await auth_client.post(base, json=RULE)
    assert res.status_code == 201, res.text
    made = res.json()["rule"]
    rid = made["rule"]["id"]
    assert made["origin"] == "editor" and made["runs"] == "everywhere"
    on_disk = json.loads((p["out"] / "app" / "rules" / "blueprint-rules.json").read_text())
    assert [r["id"] for r in on_disk] == [rid]

    checked = (await auth_client.post(f"{base}/check?rule_id={rid}", json={"when": "nosuch > 1"})).json()
    assert checked["ok"] is False and "nosuch" in checked["problems"][0]

    res = await auth_client.put(f"{base}/{rid}", json={"when": "openingsCount < 2", "revision": made["revision"]})
    assert res.status_code == 200, res.text
    edited = res.json()["rule"]
    stale = await auth_client.put(f"{base}/{rid}", json={"name": "x", "revision": made["revision"]})
    assert stale.status_code == 409
    assert "changed since you opened it" in stale.json()["detail"]["message"]

    res = await auth_client.patch(f"{base}/{rid}/enabled", json={"enabled": False, "revision": edited["revision"]})
    assert res.status_code == 200 and res.json()["rule"]["enabled"] is False

    off = res.json()["rule"]
    res = await auth_client.delete(f"{base}/{rid}?revision={off['revision']}")
    assert res.status_code == 200
    assert all(v["rule"]["id"] != rid for v in (await auth_client.get(base)).json()["rules"])


@pytest.mark.asyncio
async def test_a_refusal_carries_every_reason(auth_client, org_id):
    p = await _project(auth_client, org_id)
    res = await auth_client.post(f"/api/projects/{p['id']}/business-rules",
                                 json={**RULE, "name": "", "then": []})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["message"] and len(detail["problems"]) >= 2


@pytest.mark.asyncio
async def test_a_project_without_a_blueprint_keeps_the_old_tab(auth_client, org_id):
    p = await _project(auth_client, org_id, defined=False)
    res = await auth_client.get(f"/api/projects/{p['id']}/business-rules")
    assert res.status_code == 200 and res.json()["mode"] == "legacy"
    res = await auth_client.post(f"/api/projects/{p['id']}/business-rules", json=RULE)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_rules_saved_to_the_old_table_move_into_the_definition(auth_client, org_id):
    p = await _project(auth_client, org_id)
    res = await auth_client.post(f"/api/projects/{p['id']}/rules", json={
        "name": "Old tab rule", "rule_type": "condition_action", "model_name": "roles",
        "config": {"source": "manual", "whenFeel": "openingsCount > 50", "scope": "entity", "salience": 0,
                   "then": [{"id": "a", "type": "show_error", "message": "Too many openings."}],
                   "otherwise": []},
        "is_active": True})
    assert res.status_code in (200, 201), res.text
    listed = (await auth_client.get(f"/api/projects/{p['id']}/business-rules")).json()
    adopted = [v for v in listed["rules"] if v["rule"]["name"] == "Old tab rule"]
    assert len(adopted) == 1 and adopted[0]["origin"] == "editor" and adopted[0]["entityName"] == "Role"
    left = (await auth_client.get(f"/api/projects/{p['id']}/rules")).json()
    assert all(r["name"] != "Old tab rule" for r in left), "moved, not copied"
    again = (await auth_client.get(f"/api/projects/{p['id']}/business-rules")).json()
    assert len([v for v in again["rules"] if v["rule"]["name"] == "Old tab rule"]) == 1


@pytest.mark.asyncio
async def test_another_organisation_reaches_nothing(auth_client, org_id):
    p = await _project(auth_client, org_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as outsider:
        signup = await outsider.post("/api/auth/signup", json={
            "email": "rules-outsider@example.com", "name": "Out", "password": "Testpass123"})
        outsider.headers["Authorization"] = f"Bearer {signup.json()['access_token']}"
        base = f"/api/projects/{p['id']}/business-rules"
        assert (await outsider.get(base)).status_code in (403, 404)
        assert (await outsider.post(base, json=RULE)).status_code in (403, 404)
        assert (await outsider.put(f"{base}/RULE-001", json={"name": "x"})).status_code in (403, 404)
        assert (await outsider.delete(f"{base}/RULE-001")).status_code in (403, 404)
    doc = json.loads((p["out"] / ".forge" / "blueprint" / "current.json").read_text())
    assert all(r["name"] != "x" for r in doc["businessRules"])


def _with_a_copy(out: Path) -> None:
    """A rule and a workflow that repeats it word for word before it saves."""
    path = out / ".forge" / "blueprint" / "current.json"
    doc = json.loads(path.read_text())
    doc["businessRules"].append({
        "id": "RULE-900", "name": "Openings are positive", "kind": "condition_action", "entity": ROLE,
        "status": "PROPOSED", "statement": "A role has at least one opening.",
        "when": "openingsCount = null or openingsCount < 1",
        "then": [{"type": "show_error", "message": "A role needs at least one opening."}], "otherwise": []})
    doc["workflows"].append({
        "id": "FLOW-900", "name": "Quick role", "status": "PROPOSED", "purpose": "Adds a role in one go.",
        "trigger": dict(doc["workflows"][0]["trigger"]),
        "steps": [
            {"key": "check_openings", "name": "Has openings", "type": "condition",
             "config": {"expression": "openingsCount >= 1"}, "next": ["add_role", "no_openings"]},
            {"key": "no_openings", "name": "Stop", "type": "end",
             "config": {"refused": True, "message": "Enter the openings."}, "next": []},
            {"key": "add_role", "name": "Add the role", "type": "action", "entity": ROLE,
             "config": {"actionType": "db_insert", "table": "roles",
                        "values": {"title": "{{title}}", "openingsCount": "{{openingsCount}}"}},
             "next": []}]})
    path.write_text(json.dumps(doc))


@pytest.mark.asyncio
@pytest.mark.skipif(not __import__("shutil").which("node"), reason="the rule lab needs node")
async def test_opening_the_tab_changes_nothing_and_use_the_rules_is_recorded(auth_client, org_id):
    """PR #29 review: the tab's GET folded copies into the definition. Now a
    read only offers it ("repeats"); the person's POST does it, with history."""
    p = await _project(auth_client, org_id)
    _with_a_copy(p["out"])
    current = p["out"] / ".forge" / "blueprint" / "current.json"
    before = current.read_text()
    base = f"/api/projects/{p['id']}/business-rules"

    listed = (await auth_client.get(base)).json()
    assert [(r["workflow"], r["step"], r["rule"]) for r in listed["repeats"]] == [
        ("FLOW-900", "check_openings", "RULE-900")]
    assert "linked" not in listed and current.read_text() == before, "a read wrote the definition"

    res = await auth_client.post(f"{base}/use-rules-in-workflows")
    assert res.status_code == 200, res.text
    assert [(d["workflow"], d["step"]) for d in res.json()["linked"]] == [("FLOW-900", "check_openings")]
    doc = json.loads(current.read_text())
    flow = next(w for w in doc["workflows"] if w["id"] == "FLOW-900")
    assert [s["key"] for s in flow["steps"]] == ["add_role"]
    assert "repeated a business rule" in doc["changeHistory"][-1]["userRequest"] or \
        "now follow the rule" in doc["changeHistory"][-1]["userRequest"]
    assert (await auth_client.get(base)).json()["repeats"] == []
    again = await auth_client.post(f"{base}/use-rules-in-workflows")
    assert again.status_code == 200 and again.json()["linked"] == []


@pytest.mark.asyncio
async def test_use_the_rules_waits_for_a_build(auth_client, org_id, monkeypatch):
    from services import business_rules as rules
    p = await _project(auth_client, org_id)
    monkeypatch.setattr(rules, "busy", lambda out: "building")
    res = await auth_client.post(f"/api/projects/{p['id']}/business-rules/use-rules-in-workflows")
    assert res.status_code == 423
