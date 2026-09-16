"""Access, rules and entities are Blueprint sections, and Smith can change
them — through one shared shape: re-run the owning node with a brief, hold
the reply to the contract, commit through the Blueprint, re-project."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import access_change as ac, entity_change as ec, rule_change as rc, section_change as sc


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                              {"name": "fullName", "type": "string", "required": True},
                                              {"name": "yearsOfExperience", "type": "integer"}]}],
                     "relationships": []}
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Register nurses.", "status": "APPROVED",
                              "evidence": [{"message": "register nurses", "type": "conversation"}]}]
    role = s.upsert("roles", {"name": "User", "description": "Anyone.", "permissions": []}, natural_key="User")
    perm = s.upsert("permissions", {"name": "Delete Nurse Record", "action": "delete", "subject": "ENTITY-001"},
                    natural_key="delete:ENTITY-001:Delete Nurse Record")
    role["permissions"] = [perm["id"]]
    s.doc["security"] = {"authentication": "email_password", "rbac": True, "ownershipRules": []}
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list", "purpose": "All.",
                             "actions": ["view_record"], "data": {"primaryEntity": "ENTITY-001"}, "users": [role["id"]],
                             "access": "authenticated"}, natural_key=page_key("/master-data"))
    rule = s.upsert("businessRules", {"name": "Years Non-Negative", "statement": "Years cannot be negative.",
                                      "kind": "condition_action", "entity": "ENTITY-001", "when": "yearsOfExperience < 0",
                                      "then": [{"type": "show_error", "field": "yearsOfExperience", "message": "No."}],
                                      "appliesTo": ["ENTITY-001"]}, natural_key="Years Non-Negative")
    s.upsert("workflows", {"name": "Delete Nurse", "purpose": "Delete.", "trigger": {"kind": "manual"}, "launchedFrom": [lst["id"]],
                           "inputs": [{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True}],
                           "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["do"]},
                                     {"key": "do", "name": "Delete", "type": "action", "entity": "ENTITY-001",
                                      "config": {"actionType": "db_delete", "table": "nurses", "where": {"id": "{{record.id}}"}}, "next": ["done"]},
                                     {"key": "done", "name": "End", "type": "end", "next": []}]}, natural_key="Delete Nurse")
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/master-data"},
                           "tree": [{"label": "Master Data", "page": lst["id"]}]}
    s.save()
    s._t = SimpleNamespace(role=role, perm=perm, lst=lst, rule=rule)
    return s


def _result(spec, proposals):
    return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=proposals)


# --- rules ---------------------------------------------------------------------

def test_a_rule_is_added_from_the_ask_and_existing_rules_are_left_alone(svc):
    seen = []
    def agent(spec):
        seen.append(spec)
        cap = {"name": "Years Realistic Cap", "statement": "Years of experience cannot exceed 60.", "kind": "condition_action",
               "entity": "ENTITY-001", "when": "yearsOfExperience > 60", "appliesTo": ["ENTITY-001"],
               "then": [{"type": "show_error", "field": "yearsOfExperience", "message": "Too many."}]}
        old = {"name": "Years Non-Negative", "statement": "REWRITTEN", "kind": "statement", "appliesTo": []}
        return _result(spec, [ArtifactProposal("businessRules", "Years Non-Negative", old),
                              ArtifactProposal("businessRules", "Years Realistic Cap", cap)])
    out = rc.add_rule(svc, "years of experience cannot exceed 60", executor=agent)
    assert seen[0].node == "business_rules" and "Years Non-Negative" in seen[0].brief and "NOT to be returned" in seen[0].brief
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    rules = {r["name"]: r for r in fresh.doc["businessRules"]}
    assert rules["Years Non-Negative"]["statement"] == "Years cannot be negative."          # the re-stated one was dropped
    assert rules["Years Realistic Cap"]["when"] == "yearsOfExperience > 60" and out["requirement"] in rules["Years Realistic Cap"]["requirements"]
    assert "fires on the form when `yearsOfExperience > 60`" in rc.summary_of("add_rule", out)


def test_a_rule_edit_updates_that_rule_under_its_id_and_records_the_decision(svc):
    def agent(spec):
        return _result(spec, [ArtifactProposal("businessRules", "years non negative (revised)",
                                               {"name": "Years non negative", "statement": "Years must be zero or more.",
                                                "kind": "condition_action", "entity": "ENTITY-001", "when": "yearsOfExperience < 0",
                                                "then": [{"type": "show_error", "field": "yearsOfExperience", "message": "Zero or more."}],
                                                "appliesTo": ["ENTITY-001"]})])
    out = rc.edit_rule(svc, "years non-negative", "say zero or more", executor=agent)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    # a rule's registry key is a hash of its statement: the re-stated rule is a
    # new artifact, the old one is retired, and only one rule is live
    live = [r for r in fresh.doc["businessRules"] if r.get("status") != "DEPRECATED"]
    assert len(live) == 1 and live[0]["name"] == "Years Non-Negative"                          # the name carries over
    assert live[0]["statement"] == "Years must be zero or more." and live[0]["id"] == out["rule"]
    assert out["superseded"] == svc._t.rule["id"]
    assert next(r for r in fresh.doc["businessRules"] if r["id"] == svc._t.rule["id"])["status"] == "DEPRECATED"
    assert next(d for d in fresh.doc["decisions"] if d["id"] == out["decision"])["decision"] == "say zero or more"
    assert "supersedes RULE-001" in rc.summary_of("edit_rule", out)


def test_a_rule_is_retired_not_deleted(svc, tmp_path):
    (tmp_path / "app").mkdir()
    out = rc.remove_rule(svc, "Years Non-Negative", app_root=str(tmp_path / "app"))
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert fresh.doc["businessRules"][0]["status"] == "DEPRECATED"
    assert json.loads((tmp_path / "app" / "rules" / "blueprint-rules.json").read_text()) in ([], {}, {"rules": []}) or \
        "Years" not in (tmp_path / "app" / "rules" / "blueprint-rules.json").read_text()
    with pytest.raises(sc.SectionChangeError, match=r"The rules are: \(none\)"):      # a retired rule is not offered
        rc.remove_rule(svc, "the speciality rule")


# --- access --------------------------------------------------------------------

def test_access_is_re_decided_and_the_screens_follow(svc):
    seen = []
    def agent(spec):
        seen.append(spec)
        admin = {"name": "Admin", "description": "Runs the roster.", "permissions": [svc._t.perm["id"]]}
        user = {"name": "User", "description": "Anyone.", "permissions": []}
        return _result(spec, [ArtifactProposal("roles", "Admin", admin), ArtifactProposal("roles", "User", user),
                              ArtifactProposal("security", "security", {"rbac": True})])
    calls = []
    def client(*, system, user, schema):
        calls.append(user)
        pages = json.loads(user.split("The pages as they stand:\n")[1].split("\n\nReturn")[0])
        return json.dumps({"pages": [{"page": pages[0]["id"], "access": "authenticated", "roles": ["Admin"]}], "note": ""})
    out = ac.change_access(svc, "only admins can delete a nurse, and make master data admin-only",
                           executor=agent, client=client)
    assert seen[0].node == "security" and "status: \"DEPRECATED\"" in seen[0].brief.replace("`", "")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    roles = {r["name"]: r for r in fresh.doc["roles"]}
    assert roles["Admin"]["permissions"] == [svc._t.perm["id"]] and roles["User"]["permissions"] == []
    assert roles["User"]["id"] == svc._t.role["id"]                                              # kept under its name
    page = next(p for p in fresh.doc["pages"] if p["id"] == svc._t.lst["id"])
    assert page["users"] == [roles["Admin"]["id"]] and page["access"] == "authenticated"
    assert out["roles_after"] == ["User", "Admin"] and out["pages_changed"] == ["/master-data"]
    assert "Admin" in calls[0] and "/master-data → authenticated for Admin" in ac.summary_of(out, "x")


def test_a_screen_access_that_names_an_unknown_role_is_refused_then_retried(svc):
    agent = lambda spec: _result(spec, [ArtifactProposal("roles", "User", {"name": "User", "permissions": []})])
    replies = [{"pages": [{"page": svc._t.lst["id"], "access": "public", "roles": ["Ghost"]}]},
               {"pages": [{"page": svc._t.lst["id"], "access": "public", "roles": []}]}]
    seen = []
    def client(*, system, user, schema):
        seen.append(user)
        return json.dumps(replies[min(len(seen) - 1, 1)])
    out = ac.change_access(svc, "let anyone see master data without signing in", executor=agent, client=client)
    assert "'Ghost' is not a role" in seen[1]
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    page = next(p for p in fresh.doc["pages"] if p["id"] == svc._t.lst["id"])
    assert page["access"] == "public" and page["users"] == [] and out["pages_changed"] == ["/master-data"]


# --- entities ------------------------------------------------------------------

def test_an_entity_is_declared_then_authored_then_projected(svc, tmp_path):
    seen = []
    def agent(spec):
        seen.append(spec)
        if spec.node == "data_model":
            return _result(spec, [
                ArtifactProposal("data.entities", "Nurse", {"name": "Nurse", "table": "nurses", "description": "re-stated", "fields": []}),
                ArtifactProposal("data.entities", "Ward", {"name": "Ward", "table": "wards", "description": "A hospital ward.",
                                                            "fields": [{"name": "sneaky", "type": "string"}]}),
                ArtifactProposal("data.relationships", "Ward->Nurse", {"from": "Ward", "to": "Nurse", "kind": "one_to_many", "toField": "wardId"}),
            ])
        return _result(spec, [ArtifactProposal("data.entities", "ward", {
            "name": "Ward", "table": "wards", "description": "A hospital ward.", "labelField": "name",
            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "name", "type": "string", "required": True},
                       {"name": "capacity", "type": "integer"}]})])
    (tmp_path / "app").mkdir()
    out = ec.add_entity(svc, "add a Ward entity with a name and a capacity", app_root=str(tmp_path / "app"), executor=agent)
    assert [s.node for s in seen] == ["data_model", "entity_fields"] and seen[1].subject == out["entity"]
    assert "Nurse (ENTITY-001)" in seen[0].brief and "NOT to be returned" in seen[0].brief
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    ents = {e["name"]: e for e in fresh.doc["data"]["entities"]}
    assert ents["Nurse"].get("description") != "re-stated" and len(ents) == 2               # existing untouched, one new
    assert [f["name"] for f in ents["Ward"]["fields"]] == ["id", "name", "capacity"]          # the declaration's sneaky field never landed
    assert out["requirement"] in ents["Ward"]["requirements"]
    assert (tmp_path / "app" / "src" / "db" / "schema" / "ward.ts").exists()
    assert "migration on the next install" in ec.summary_of("add_entity", out)


def test_retiring_an_entity_takes_its_screens_workflows_and_menu_entry_with_it(svc, tmp_path):
    (tmp_path / "app").mkdir()
    svc.doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Ward", "table": "wards",
                                        "fields": [{"name": "id", "type": "uuid"}, {"name": "nurseId", "type": "uuid", "references": "ENTITY-001"}]})
    svc.doc["data"]["relationships"] = [{"from": "ENTITY-002", "to": "ENTITY-001", "kind": "one_to_many"}]
    svc.save()
    out = ec.remove_entity(svc, "nurse", app_root=None)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert next(e for e in fresh.doc["data"]["entities"] if e["id"] == "ENTITY-001")["status"] == "DEPRECATED"
    assert next(p for p in fresh.doc["pages"] if p["id"] == svc._t.lst["id"])["status"] == "DEPRECATED"
    assert next(w for w in fresh.doc["workflows"] if w["name"] == "Delete Nurse")["status"] == "DEPRECATED"
    assert fresh.doc["navigation"]["tree"] == [] and fresh.doc["navigation"]["initialRoute"] == {}
    assert fresh.doc["data"]["relationships"] == []
    assert out["pages"] == ["/master-data"] and out["workflows"] == ["Delete Nurse"] and out["pointing"] == ["Ward.nurseId"]
    text = ec.summary_of("remove_entity", out)
    assert "Still pointing at it" in text and "Ward.nurseId" in text


# --- the verbs and the tools ---------------------------------------------------

def test_every_new_verb_is_offered_dispatched_and_tooled(monkeypatch, tmp_path):
    import services.smith_tools as smith_tools
    from services.smith.understand_ask import _PROMPT
    from services.smith.verbs import REQUIRED_BY_VERB
    for v in ("edit_access", "add_rule", "edit_rule", "remove_rule", "add_entity", "remove_entity"):
        assert v in REQUIRED_BY_VERB and f'"{v}"' in _PROMPT, v
    calls = []
    monkeypatch.setattr("services.smith.access_change.run", lambda d, change, **k: calls.append(("access", change)) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    monkeypatch.setattr("services.smith.rule_change.run", lambda d, verb, **k: calls.append((verb, k.get("rule"))) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    monkeypatch.setattr("services.smith.entity_change.run", lambda d, verb, **k: calls.append((verb, k.get("entity"))) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text("{}")
    H = smith_tools.READONLY_HANDLERS
    assert H["add_role"](str(tmp_path), {"role_name": "Ward Manager"})["applied"]
    assert H["restrict_page_to_role"](str(tmp_path), {"page_route": "/master-data", "role_name": "Admin"})["applied"]
    assert H["create_business_rule"](str(tmp_path), {"name": "cap", "rule_type": "validation"})["applied"]
    assert H["add_entity"](str(tmp_path), {"name": "Ward", "fields": [{"name": "name", "type": "text"}]})["applied"]
    assert H["remove_entity"](str(tmp_path), {"entity": "Ward"})["applied"]
    assert H["add_rule"](str(tmp_path), {})["applied"] is False
    assert [c[0] for c in calls] == ["access", "access", "add_rule", "add_entity", "remove_entity"]
    assert calls[0][1] == "add a role named Ward Manager" and calls[3][1] == "Ward with name (text)"
    from services.smith_session import SmithSession
    session = SmithSession(project_id="p1", output_dir=str(tmp_path), guards_fn=lambda _d: [],
                           understand_ask_fn=lambda m, c, history=None: {"verb": "edit_rule", "rule": "cap", "change": "raise it"},
                           iteration_move_fn=lambda *a, **k: None)
    assert session.run_iteration(user_message="raise the cap").status == "resolved"
    assert calls[-1] == ("edit_rule", "cap")


def test_several_new_rules_are_refused_until_exactly_one_comes_back(svc):
    """Asked for a cap on years of experience, the agent returned the rules it
    thought the app lacked and the first — a specialities check — was taken."""
    seen = []
    def agent(spec):
        seen.append(spec)
        cap = {"name": "Years Realistic Cap", "statement": "Years cannot exceed 60.", "kind": "condition_action",
               "entity": "ENTITY-001", "when": "yearsOfExperience > 60", "appliesTo": ["ENTITY-001"],
               "then": [{"type": "show_error", "field": "yearsOfExperience", "message": "Too many."}]}
        spec_ = {"name": "Specialities Required", "statement": "A speciality is required.", "kind": "statement", "appliesTo": []}
        props = [ArtifactProposal("businessRules", "Specialities Required", spec_), ArtifactProposal("businessRules", "Years Realistic Cap", cap)]
        return _result(spec, props if len(seen) == 1 else props[1:])
    out = rc.add_rule(svc, "years of experience cannot exceed 60", executor=agent)
    assert [s.attempt for s in seen] == [1, 2] and "exactly ONE new rule" in seen[1].feedback
    assert out["name"] == "Years Realistic Cap"
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert sorted(r["name"] for r in fresh.doc["businessRules"]) == ["Years Non-Negative", "Years Realistic Cap"]


def test_an_ask_an_existing_rule_already_enforces_is_answered_not_duplicated(svc):
    agent = lambda spec: _result(spec, [ArtifactProposal("businessRules", "Years Non-Negative",
                                                          {"name": "Years Non-Negative", "statement": "Years cannot be negative (already).",
                                                           "kind": "statement", "appliesTo": []})])
    with pytest.raises(sc.SectionChangeError, match="already enforced by the rule Years Non-Negative"):
        rc.add_rule(svc, "years cannot be negative", executor=agent)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert [r["statement"] for r in fresh.doc["businessRules"]] == ["Years cannot be negative."]      # untouched
