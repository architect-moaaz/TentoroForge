"""Fields, requirements, product, APIs and integrations after the build."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import definition_change as dc, field_change as fc, section_change as sc


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses", "labelField": "fullName",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                              {"name": "fullName", "type": "string", "required": True},
                                              {"name": "location", "type": "string"},
                                              {"name": "yearsOfExperience", "type": "integer"}]},
                                  {"id": "ENTITY-002", "name": "Ward", "table": "wards",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "headNurseId", "type": "uuid", "references": "ENTITY-001"}]}],
                     "relationships": [{"from": "ENTITY-002", "to": "ENTITY-001", "kind": "one_to_many", "fromField": "headNurseId", "toField": "id"}]}
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Register nurses with their years of experience.", "status": "APPROVED",
                              "evidence": [{"message": "register", "type": "conversation"}]}]
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list", "purpose": "All.",
                             "actions": ["view_record"], "data": {"primaryEntity": "ENTITY-001"}, "requirements": ["REQ-001"]},
                   natural_key=page_key("/master-data"))
    wf = s.upsert("workflows", {"name": "Register Nurse", "purpose": "Register.", "trigger": {"kind": "manual"}, "launchedFrom": [],
                                "requirements": ["REQ-001"],
                                "inputs": [{"name": "fullName", "kind": "field", "type": "string", "required": True},
                                           {"name": "yearsOfExperience", "kind": "field", "type": "integer", "required": False}],
                                "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["do"]},
                                          {"key": "do", "name": "Insert", "type": "action", "entity": "ENTITY-001",
                                           "config": {"actionType": "db_insert", "table": "nurses",
                                                      "values": {"fullName": "{{fullName}}", "yearsOfExperience": "{{yearsOfExperience}}"}}, "next": ["done"]},
                                          {"key": "done", "name": "End", "type": "end", "next": []}]}, natural_key="Register Nurse")
    rule = s.upsert("businessRules", {"name": "Years Non-Negative", "statement": "Years cannot be negative.", "kind": "condition_action",
                                      "entity": "ENTITY-001", "when": "yearsOfExperience < 0", "appliesTo": ["ENTITY-001"],
                                      "then": [{"type": "show_error", "field": "yearsOfExperience", "message": "No."}]}, natural_key="Years Non-Negative")
    s.upsert("pageLayouts", {"page": lst["id"], "composedBy": "a2ui", "dataSources": [{"name": "nurses", "entity": "Nurse", "op": "list"}],
                             "root": {"type": "Stack", "props": {}, "children": [
                                 {"type": "Heading", "props": {"content": "{{nurses.count}} nurses"}, "children": []},
                                 {"type": "Table", "props": {"data": "{{nurses}}", "columns": [{"key": "fullName", "label": "Name"}, {"key": "yearsOfExperience", "label": "Years"}]}, "children": []},
                                 {"type": "Form", "props": {"workflow": wf["id"], "fields": [{"name": "fullName", "kind": "text", "label": "Name"},
                                                                                            {"name": "yearsOfExperience", "kind": "number", "label": "Years"}]}, "children": []},
                                 {"type": "Text", "props": {"content": "Most experienced: {{nurses.0.yearsOfExperience}} years"}, "children": []}]}},
             natural_key=lst["id"])
    s.upsert("apis", {"method": "GET", "path": "/api/data/nurses", "purpose": "List nurses.", "entity": "ENTITY-001"}, natural_key="GET /api/data/nurses")
    wf["steps"].insert(1, {"key": "check", "name": "Check", "type": "condition", "config": {"expression": "yearsOfExperience > 60"}, "next": ["do", "done"]})
    s.doc["widgets"] = [{"id": "WIDGET-001", "label": "Experience", "kind": "text", "page": lst["id"],
                         "dataSource": {"entity": "ENTITY-001", "fields": ["yearsOfExperience"], "op": "list"}}]
    s.doc["product"] = {"objectives": ["Track nurses"], "personas": [], "terminology": {}, "capabilities": [], "locale": "en"}
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/master-data"}, "tree": [{"label": "Master Data", "page": lst["id"]}]}
    s.save()
    s._t = SimpleNamespace(lst=lst, wf=wf, rule=rule)
    return s


# --- fields --------------------------------------------------------------------

def test_a_field_is_renamed_everywhere_the_blueprint_names_it(svc):
    out = fc.rename_field(svc, "nurse", "yearsOfExperience", "experienceYears")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    ent = fresh.doc["data"]["entities"][0]
    assert [f["name"] for f in ent["fields"]] == ["id", "fullName", "location", "experienceYears"]
    wf = next(w for w in fresh.doc["workflows"] if w["id"] == svc._t.wf["id"])
    assert wf["inputs"][1]["name"] == "experienceYears"
    assert wf["steps"][1]["config"]["expression"] == "experienceYears > 60"                         # a bare FEEL name
    assert wf["steps"][2]["config"]["values"] == {"fullName": "{{fullName}}", "experienceYears": "{{experienceYears}}"}
    assert fresh.doc["widgets"][0]["dataSource"]["fields"] == ["experienceYears"]
    rule = next(r for r in fresh.doc["businessRules"] if r["id"] == svc._t.rule["id"])
    assert rule["when"] == "experienceYears < 0" and rule["then"][0]["field"] == "experienceYears"
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == svc._t.lst["id"] and l.get("status") != "SUPERSEDED")
    kids = layout["root"]["children"]
    assert kids[1]["props"]["columns"][1]["key"] == "experienceYears" and kids[2]["props"]["fields"][1]["name"] == "experienceYears"
    assert kids[3]["props"]["content"] == "Most experienced: {{nurses.0.experienceYears}} years"
    assert len(out["hits"]) >= 8 and fresh.doc["changeHistory"][-1]["userRequest"].startswith("rename Nurse.yearsOfExperience")
    assert "drop and re-add" in fc.summary_of("rename_field", out)


def test_a_field_is_removed_with_its_uses_and_what_still_reads_it_is_named(svc):
    out = fc.remove_field(svc, "Nurse", "yearsOfExperience")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert [f["name"] for f in fresh.doc["data"]["entities"][0]["fields"]] == ["id", "fullName", "location"]
    wf = next(w for w in fresh.doc["workflows"] if w["id"] == svc._t.wf["id"])
    assert [i["name"] for i in wf["inputs"]] == ["fullName"] and wf["steps"][2]["config"]["values"] == {"fullName": "{{fullName}}"}
    assert any("check expression still names yearsOfExperience" in x for x in out["left"])
    assert fresh.doc["widgets"][0]["dataSource"]["fields"] == []
    assert next(r for r in fresh.doc["businessRules"] if r["id"] == svc._t.rule["id"])["status"] == "DEPRECATED"
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == svc._t.lst["id"] and l.get("status") != "SUPERSEDED")
    kids = layout["root"]["children"]
    assert [c["key"] for c in kids[1]["props"]["columns"]] == ["fullName"] and [f["name"] for f in kids[2]["props"]["fields"]] == ["fullName"]
    assert kids[3]["props"]["content"].endswith("{{nurses.0.yearsOfExperience}} years")            # left, and named
    assert any("Text.content still reads" in x for x in out["left"])
    assert "Still reading it" in fc.summary_of("remove_field", out)


def test_managed_and_unknown_fields_are_refused(svc):
    with pytest.raises(sc.SectionChangeError, match="managed column"):
        fc.remove_field(svc, "Nurse", "id")
    with pytest.raises(sc.SectionChangeError, match="has no field 'salary'"):
        fc.rename_field(svc, "Nurse", "salary", "pay")
    with pytest.raises(sc.SectionChangeError, match="already has a field named"):
        fc.rename_field(svc, "Nurse", "location", "fullName")
    with pytest.raises(sc.SectionChangeError, match="not a field name"):
        fc.rename_field(svc, "Nurse", "location", "home town")


def test_a_relationship_field_renames_with_the_field(svc):
    fc.rename_field(svc, "Ward", "headNurseId", "chargeNurseId")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert fresh.doc["data"]["relationships"][0]["fromField"] == "chargeNurseId"


# --- requirements ----------------------------------------------------------------

def test_a_restated_requirement_flows_to_what_cites_it(svc, monkeypatch):
    composed, edited = [], []
    monkeypatch.setattr("services.smith.compose.compose_route", lambda s, route, **kw: composed.append((route, kw["request"])) or SimpleNamespace(applied=True))
    monkeypatch.setattr("services.smith.workflow_change.edit_workflow", lambda s, wid, change, **kw: edited.append((wid, change)) or {"applied": True})
    out = dc.edit_requirement(svc, "REQ-001", "Register nurses with their years of experience and their ward.")
    assert composed == [("/master-data", "REQ-001 now says: Register nurses with their years of experience and their ward.")]
    assert edited == [(svc._t.wf["id"], "REQ-001 now says: Register nurses with their years of experience and their ward.")]
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    req = fresh.doc["requirements"][0]
    assert req["description"].endswith("their ward.") and req["evidence"][-1]["type"] == "conversation"
    assert out["reauthored"] == ["/master-data", "Register Nurse"] and "Re-authored against it" in dc.summary_of("edit_requirement", out)


def test_requirements_are_added_and_retired_honestly(svc):
    out = dc.add_requirement(svc, "a nurse can mark herself unavailable")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert any(r["description"] == "a nurse can mark herself unavailable" and r["status"] == "APPROVED" for r in fresh.doc["requirements"])
    assert "Nothing implements it yet" in dc.summary_of("add_requirement", out)
    out = dc.remove_requirement(svc, "REQ-001")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert fresh.doc["requirements"][0]["status"] == "DEPRECATED"
    assert "REQ-001" not in next(p for p in fresh.doc["pages"] if p["id"] == svc._t.lst["id"])["requirements"]
    assert sorted(out["uncited"]) == sorted([svc._t.lst["id"], svc._t.wf["id"]])


# --- product ---------------------------------------------------------------------

def test_the_product_is_revised_and_the_shell_re_projected(svc, tmp_path):
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app" / "src" / "app" / "(dashboard)").mkdir(parents=True)
    client = lambda *, system, user, schema: json.dumps({"name": "Nurse Roster", "description": "Roster of nurses.",
                                                        "objectives": ["Track nurses", "Plan wards"],
                                                        "personas": [{"name": "Their own details", "goals": []}],   # rewritten but not declared
                                                        "changed": ["name", "description", "objectives"], "note": ""})
    out = dc.edit_product(svc, "call the app Nurse Roster and add the objective of planning wards", app_root=str(tmp_path / "app"), client=client)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert fresh.doc["application"]["name"] == "Nurse Roster" and fresh.doc["product"]["objectives"] == ["Track nurses", "Plan wards"]
    assert sorted(out["changed"]) == ["description", "name", "objectives"] and fresh.doc["product"]["personas"] == []
    assert json.loads((tmp_path / "app" / "src" / "schemas" / "shell.json").read_text())["children"][0]["props"]["appName"] == "Nurse Roster"
    with pytest.raises(sc.SectionChangeError, match="exactly as it is"):
        dc.edit_product(svc, "nothing", client=lambda **k: json.dumps({"name": "Nurse Roster", "description": "Roster of nurses.", "objectives": ["Track nurses", "Plan wards"], "changed": []}))


# --- apis and integrations -------------------------------------------------------

def test_an_endpoint_is_declared_for_its_entity_and_said_to_be_served_or_not(svc):
    def agent(spec):
        assert spec.node == "apis" and "GET /api/data/nurses" in spec.brief
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=[
            ArtifactProposal("apis", "GET /api/data/nurses", {"method": "GET", "path": "/api/data/nurses", "purpose": "again"}),
            ArtifactProposal("apis", "GET /api/data/wards", {"method": "GET", "path": "/api/data/wards", "purpose": "List wards.", "entity": "ENTITY-002"})])
    out = dc.add_api(svc, "an endpoint that lists wards", executor=agent)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert [a["path"] for a in fresh.doc["apis"]] == ["/api/data/nurses", "/api/data/wards"] and out["served"] is True
    assert "The data engine serves it" in dc.summary_of("add_api", out)
    out = dc.remove_api(svc, "GET /api/data/wards")
    assert next(a for a in BlueprintService.load(output_dir=str(svc.output_dir)).doc["apis"] if a["path"] == "/api/data/wards")["status"] == "DEPRECATED"


def test_an_integration_is_declared_with_secret_names_only(svc):
    agent = lambda spec: AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=[
        ArtifactProposal("integrations", "SendGrid", {"name": "SendGrid", "kind": "email", "provider": "sendgrid", "secretRefs": ["SENDGRID_API_KEY"]})])
    out = dc.add_integration(svc, "send email through SendGrid", executor=agent)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert fresh.doc["integrations"][0]["secretRefs"] == ["SENDGRID_API_KEY"] and out["secrets"] == ["SENDGRID_API_KEY"]
    assert "names only" in dc.summary_of("add_integration", out)
    dc.remove_integration(svc, "sendgrid")
    assert BlueprintService.load(output_dir=str(svc.output_dir)).doc["integrations"][0]["status"] == "DEPRECATED"


# --- the verbs and the tools -----------------------------------------------------

def test_every_new_verb_is_offered_dispatched_and_tooled(monkeypatch, tmp_path):
    import services.smith_tools as smith_tools
    from services.smith.understand_ask import _PROMPT
    from services.smith.verbs import REQUIRED_BY_VERB
    for v in ("rename_field", "remove_field", "add_requirement", "edit_requirement", "remove_requirement", "edit_product",
              "add_api", "remove_api", "add_integration", "remove_integration"):
        assert v in REQUIRED_BY_VERB and f'"{v}"' in _PROMPT, v
    calls = []
    monkeypatch.setattr("services.smith.field_change.run", lambda d, verb, **k: calls.append((verb, k)) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    monkeypatch.setattr("services.smith.definition_change.run", lambda d, verb, **k: calls.append((verb, k)) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text("{}")
    H = smith_tools.READONLY_HANDLERS
    assert H["edit_field"](str(tmp_path), {"entity": "Nurse", "field_name": "location", "new_name": "town"})["applied"]
    assert H["remove_field"](str(tmp_path), {"entity": "Nurse", "field_name": "location"})["applied"]
    assert H["edit_product"](str(tmp_path), {"change": "call it Roster"})["applied"]
    assert H["add_integration"](str(tmp_path), {})["applied"] is False
    assert [c[0] for c in calls] == ["rename_field", "remove_field", "edit_product"]
    assert calls[0][1]["new_value"] == "town" and calls[2][1]["text"] == "call it Roster"
    from services.smith_session import SmithSession
    session = SmithSession(project_id="p1", output_dir=str(tmp_path), guards_fn=lambda _d: [],
                           understand_ask_fn=lambda m, c, history=None: {"verb": "rename_field", "entity": "Nurse", "field": {"name": "location"}, "new_value": "town"},
                           iteration_move_fn=lambda *a, **k: None)
    assert session.run_iteration(user_message="rename location to town").status == "resolved"
    assert calls[-1][0] == "rename_field" and calls[-1][1]["field"] == "location"
