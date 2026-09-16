"""The business processes are a Blueprint section, and Smith can change them.

"Email the admin after a registration" had nowhere to go: no chat verb touched
`workflows`, and the tool of that name wrote files a Blueprint-built app does
not have. A change takes the build's own path — declare, author steps, project,
and compose the screen it starts from."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import workflow_change as wc


def _wf(name, op, *, inputs, values=None, launched=()):
    step_cfg = {"actionType": op, "table": "nurses"}
    if values is not None:
        step_cfg["values"] = values
    if op != "db_insert":
        step_cfg["where"] = {"id": "{{record.id}}"}
    return {"name": name, "purpose": f"{name}.", "trigger": {"kind": "manual"}, "launchedFrom": list(launched),
            "inputs": inputs,
            "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["do"]},
                      {"key": "do", "name": name, "type": "action", "entity": "ENTITY-001", "config": step_cfg, "next": ["done"]},
                      {"key": "done", "name": "End", "type": "end", "next": []}]}


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"},
                                              {"name": "location", "type": "string"}]}]}
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Register nurses.", "status": "APPROVED",
                              "evidence": [{"message": "register nurses", "type": "conversation"}]}]
    form = s.upsert("pages", {"name": "Nurse Registration", "route": "/nurse-registration", "pattern": "form",
                              "purpose": "Register.", "actions": ["submit"], "data": {"primaryEntity": "ENTITY-001"}},
                    natural_key=page_key("/nurse-registration"))
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list",
                             "purpose": "All nurses.", "actions": ["view_record", "edit_record", "delete"],
                             "data": {"primaryEntity": "ENTITY-001"}}, natural_key=page_key("/master-data"))
    create = s.upsert("workflows", _wf("Register Nurse", "db_insert", launched=[form["id"]],
                                       inputs=[{"name": "fullName", "kind": "field", "type": "string", "required": True}],
                                       values={"fullName": "{{fullName}}"}), natural_key="Register Nurse")
    delete = s.upsert("workflows", _wf("Delete Nurse", "db_delete", launched=[lst["id"]],
                                       inputs=[{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True}]),
                      natural_key="Delete Nurse")
    s.upsert("pageLayouts", {"page": lst["id"], "composedBy": "a2ui",
                             "dataSources": [{"name": "nurses", "entity": "Nurse", "op": "list"}],
                             "root": {"type": "Stack", "props": {}, "children": [
                                 {"type": "Button", "props": {"label": "Add Nurse", "navigate": "/nurse-registration"}, "children": []},
                                 {"type": "Table", "props": {"data": "{{nurses}}", "columns": [{"key": "fullName", "label": "Name"}],
                                                             "rowActions": [{"label": "Delete", "variant": "danger", "workflow": delete["id"]}]},
                                  "children": []}]}},
             natural_key=lst["id"])
    s.save()
    s._t = SimpleNamespace(form=form, lst=lst, create=create, delete=delete)
    return s


def _agent(seen, *, declare_names=("Reset Nurse Location",), steps_for=None):
    """A stub for the two workflow nodes: `workflows` declares the names given
    (no steps), `workflow_steps` authors the steps of the subject."""
    def run(spec):
        seen.append(spec)
        if spec.node == "workflows":
            props = [ArtifactProposal("workflows", n, {k: v for k, v in _wf(n, "db_update",
                                      inputs=[{"name": "record", "kind": "record", "entity": "ENTITY-001", "required": True},
                                              {"name": "location", "kind": "field", "type": "string", "required": True}],
                                      values={"location": "{{location}}"}).items() if k != "steps"})
                     for n in declare_names]
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9, proposals=props)
        row = steps_for(spec.subject)
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal("workflows", row["name"], row)])
    return run


def _steps_of(svc):
    def steps_for(subject):
        row = dict(next(w for w in svc.doc["workflows"] if w["id"] == subject))
        row.pop("id", None)
        row["steps"] = _wf(row["name"], "db_update",
                           inputs=row["inputs"], values={"location": "{{location}}"})["steps"]
        return row
    return steps_for


def test_a_new_workflow_is_declared_authored_and_offered_on_its_screen(svc, monkeypatch):
    seen, composed = [], []
    monkeypatch.setattr("services.smith.compose.compose_route",
                        lambda s, route, **kw: composed.append((route, kw.get("request"))) or SimpleNamespace(applied=True))
    out = wc.add_workflow(svc, "let a nurse's location be corrected from the master data list",
                          route="/master-data", executor=_agent(seen, steps_for=_steps_of(svc)))
    assert [s.node for s in seen] == ["workflows", "workflow_steps"]
    brief = seen[0].brief
    assert "let a nurse's location be corrected" in brief and "Register Nurse" in brief and "Delete Nurse" in brief
    assert f'launchedFrom: ["{svc._t.lst["id"]}"]' in brief
    assert seen[1].subject == out["workflow"] and "just declared" in seen[1].brief
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    wf = next(w for w in fresh.doc["workflows"] if w["id"] == out["workflow"])
    assert wf["name"] == "Reset Nurse Location" and len(wf["steps"]) == 3
    assert wf["launchedFrom"] == [svc._t.lst["id"]] and out["requirement"] in wf["requirements"]
    req = next(r for r in fresh.doc["requirements"] if r["id"] == out["requirement"])
    assert req["owner"] == "workflows" and req["evidence"][0]["type"] == "conversation"
    assert [w["name"] for w in fresh.doc["workflows"] if w["name"] in ("Register Nurse", "Delete Nurse")] == ["Register Nurse", "Delete Nurse"]
    assert next(w for w in fresh.doc["workflows"] if w["name"] == "Delete Nurse")["steps"]      # untouched
    assert "THE TRIGGER COMES FROM THE WORDS" not in brief          # a screen was named: manual, there
    assert composed == [("/master-data", f"add a control that runs the Reset Nurse Location workflow ({out['workflow']})")]
    # the stub composer placed no control, and the reply says so instead of claiming one
    assert out["composed"] == "/master-data" and out["offered"] is False
    assert "placed no control for it" in wc.summary_of("add_workflow", out)


def test_the_reply_claims_a_control_only_when_the_screen_has_one(svc, monkeypatch):
    seen = []
    def compose(s, route, **kw):
        wf_id = kw["request"].split("(")[-1].rstrip(")")
        layout = next(l for l in s.doc["pageLayouts"] if l["page"] == svc._t.lst["id"] and l.get("status") != "SUPERSEDED")
        layout["root"]["children"].append({"type": "Button", "props": {"label": "Reset location", "workflow": wf_id}, "children": []})
        s.save()
        return SimpleNamespace(applied=True)
    monkeypatch.setattr("services.smith.compose.compose_route", compose)
    out = wc.add_workflow(svc, "correct a location", executor=_agent(seen, steps_for=_steps_of(svc)))
    assert "THE TRIGGER COMES FROM THE WORDS" in seen[0].brief and "db_change" in seen[0].brief
    assert out["offered"] is True and "so it offers it" in wc.summary_of("add_workflow", out)


def test_an_agent_that_only_re_declares_existing_workflows_is_asked_again(svc, monkeypatch):
    seen = []
    monkeypatch.setattr("services.smith.compose.compose_route", lambda *a, **k: SimpleNamespace(applied=True))
    calls = {"n": 0}
    def agent(spec):
        if spec.node == "workflows":
            calls["n"] += 1
            names = ("Delete Nurse",) if calls["n"] == 1 else ("Reset Nurse Location",)
            return _agent(seen, declare_names=names, steps_for=_steps_of(svc))(spec)
        return _agent(seen, steps_for=_steps_of(svc))(spec)
    out = wc.add_workflow(svc, "correct a location", executor=agent)
    assert [s.attempt for s in seen if s.node == "workflows"] == [1, 2]
    assert "already exists" in seen[1].feedback
    assert out["name"] == "Reset Nurse Location"
    # nobody named a screen: the entity's list page was picked and composed
    assert out["composed"] == "/master-data"


def test_a_change_re_authors_the_steps_and_records_the_decision(svc):
    seen = []
    def steps_for(subject):
        row = dict(next(w for w in svc.doc["workflows"] if w["id"] == subject))
        row.pop("id", None)
        row["steps"] = _wf(row["name"], "db_delete", inputs=row["inputs"])["steps"]
        row["steps"][1]["name"] = "Delete the record and note who did it"
        return row
    out = wc.edit_workflow(svc, "delete nurse", "keep a note of who deleted the record",
                           executor=_agent(seen, steps_for=steps_for))
    assert [s.node for s in seen] == ["workflow_steps"] and seen[0].subject == svc._t.delete["id"]
    assert "keep a note of who deleted" in seen[0].brief and "Delete Nurse" in seen[0].brief
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    wf = next(w for w in fresh.doc["workflows"] if w["id"] == svc._t.delete["id"])
    assert wf["name"] == "Delete Nurse" and wf["steps"][1]["name"] == "Delete the record and note who did it"
    dec = next(d for d in fresh.doc["decisions"] if d["id"] == out["decision"])
    assert dec["decision"] == "keep a note of who deleted the record"
    assert "Changed Delete Nurse" in wc.summary_of("edit_workflow", out)


def test_a_retired_workflow_leaves_no_control_and_no_declared_verb_behind(svc):
    out = wc.remove_workflow(svc, "remove the delete nurse workflow")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    wf = next(w for w in fresh.doc["workflows"] if w["id"] == svc._t.delete["id"])
    assert wf["status"] == "DEPRECATED" and wf["launchedFrom"] == []
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == svc._t.lst["id"] and l.get("status") != "SUPERSEDED")
    table = next(n for n in layout["root"]["children"] if n["type"] == "Table")
    assert "rowActions" not in table["props"]
    assert next(p for p in fresh.doc["pages"] if p["id"] == svc._t.lst["id"])["actions"] == ["view_record", "edit_record"]
    assert out["pages"] == ["/master-data"] and "no longer declares delete" in " ".join(out["notes"])
    assert wc.find_workflow(fresh.doc, "delete nurse") is None                    # retired means gone to the reader


def test_an_unknown_workflow_is_named_with_the_choices(svc):
    with pytest.raises(wc.WorkflowChangeError, match="Register Nurse"):
        wc.remove_workflow(svc, "the email one")
    with pytest.raises(wc.WorkflowChangeError, match="what should be different"):
        wc.edit_workflow(svc, "Delete Nurse", "", executor=lambda s: None)


def test_the_verbs_and_the_tools_share_the_seam(monkeypatch, tmp_path):
    import services.smith_tools as smith_tools
    from services.smith.understand_ask import _PROMPT
    from services.smith.verbs import REQUIRED_BY_VERB
    for v in ("add_workflow", "edit_workflow", "remove_workflow"):
        assert v in REQUIRED_BY_VERB and f'"{v}"' in _PROMPT and f"{v} needs:" in _PROMPT
    assert REQUIRED_BY_VERB["edit_workflow"] == {"workflow", "change"}
    calls = []
    monkeypatch.setattr("services.smith.workflow_change.run",
                        lambda output_dir, verb, **kw: calls.append((verb, kw)) or {"applied": True, "edited_paths": [], "diff_summary": "ok"})
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text("{}")
    assert smith_tools.READONLY_HANDLERS["add_workflow"](str(tmp_path), {"request": "email the admin"})["applied"]
    assert smith_tools.READONLY_HANDLERS["remove_workflow"](str(tmp_path), {"workflow": "Delete Nurse"})["applied"]
    assert [c[0] for c in calls] == ["add_workflow", "remove_workflow"]
    assert calls[0][1]["workflow"] == "email the admin" and calls[1][1]["workflow"] == "Delete Nurse"
    from services.smith_session import SmithSession
    session = SmithSession(project_id="p1", output_dir=str(tmp_path), guards_fn=lambda _d: [],
                           understand_ask_fn=lambda m, c, history=None: {"verb": "edit_workflow", "workflow": "Delete Nurse", "change": "ask for a reason"},
                           iteration_move_fn=lambda *a, **k: None)
    assert session.run_iteration(user_message="the delete should ask for a reason").status == "resolved"
    assert calls[-1][0] == "edit_workflow" and calls[-1][1]["change"] == "ask for a reason"


def test_steps_the_engine_would_refuse_are_fed_back_not_crashed(svc):
    """The contract refuses a step reading a value nothing declares; that is
    a rejection the retry is told, not an exception the turn dies on."""
    seen = []
    def steps_for(subject):
        row = _steps_of(svc)(subject)                       # reads {{location}}, which Delete Nurse never declared
        if len([s for s in seen if s.node == "workflow_steps"]) >= 2:
            row["steps"] = _wf(row["name"], "db_delete", inputs=row["inputs"])["steps"]
        return row
    out = wc.edit_workflow(svc, "Delete Nurse", "make it faster", executor=_agent(seen, steps_for=steps_for))
    assert [s.attempt for s in seen] == [1, 2] and "names nothing the engine holds" in seen[1].feedback
    assert out["applied"]


def test_a_declared_duplicate_of_an_existing_workflow_becomes_a_change_to_it(svc, monkeypatch):
    """"When a nurse is registered, notify the admin": the agent declared a
    second manual workflow taking the registration form's fields and the
    composer put a second form on the registration page. Same inputs, same
    screen — it IS Register Nurse; the ask is a change to it."""
    seen, composed = [], []
    monkeypatch.setattr("services.smith.compose.compose_route", lambda *a, **k: composed.append(a[1]) or SimpleNamespace(applied=True))
    def agent(spec):
        seen.append(spec)
        if spec.node == "workflows":
            body = _wf("Notify Admin of Registration", "db_insert", launched=[svc._t.form["id"]],
                       inputs=[{"name": "fullName", "kind": "field", "type": "string", "required": True}],
                       values={"fullName": "{{fullName}}"})
            body.pop("steps")
            return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                               proposals=[ArtifactProposal("workflows", body["name"], body)])
        row = dict(next(w for w in svc.doc["workflows"] if w["id"] == spec.subject)); row.pop("id", None)
        row["steps"] = _wf(row["name"], "db_insert", inputs=row["inputs"], values={"fullName": "{{fullName}}"})["steps"]
        row["steps"][1]["name"] = "Register and notify the admin"
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal("workflows", row["name"], row)])
    out = wc.add_workflow(svc, "when a nurse is registered, send a notification to the admin", executor=agent)
    assert [(s.node, s.subject) for s in seen] == [("workflows", ""), ("workflow_steps", svc._t.create["id"])]
    assert out["extended"] == "Register Nurse" and out["workflow"] == svc._t.create["id"]
    assert "send a notification to the admin" in seen[1].brief
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert [w["name"] for w in fresh.doc["workflows"]] == ["Register Nurse", "Delete Nurse"]      # no sibling declared
    reg = next(w for w in fresh.doc["workflows"] if w["id"] == svc._t.create["id"])
    assert reg["steps"][1]["name"] == "Register and notify the admin" and out["requirement"] in reg["requirements"]
    assert composed == []
    assert "changed it instead of adding a second workflow" in wc.summary_of("add_workflow", out)


def test_retiring_a_workflow_takes_its_form_off_the_screen_too(svc):
    svc.upsert("pageLayouts", {"page": svc._t.form["id"], "composedBy": "a2ui", "dataSources": [],
                               "root": {"type": "Stack", "props": {}, "children": [
                                   {"type": "Form", "props": {"workflow": svc._t.create["id"], "submitLabel": "Register",
                                                              "fields": [{"name": "fullName", "kind": "text", "label": "Name"}]}, "children": []},
                                   {"type": "Button", "props": {"label": "Back", "navigate": "/master-data"}, "children": []}]}},
               natural_key=svc._t.form["id"])
    svc.save()
    out = wc.remove_workflow(svc, "Register Nurse")
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    layout = next(l for l in fresh.doc["pageLayouts"] if l["page"] == svc._t.form["id"] and l.get("status") != "SUPERSEDED")
    assert [n["type"] for n in layout["root"]["children"]] == ["Button"]
    assert out["forms_left"] == 1 and "came off too" in wc.summary_of("remove_workflow", out)
