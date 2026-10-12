"""After Smith changes a built app, the pages the change reaches are used again.

Smith tries what it changed; a change also reaches pages it never touched — a
list of the record type whose fields moved, a page that starts the process
that changed. Those are opened as the people they are for, what broke is
repaired once, and the check the Publish dialog reads stays current.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import app_check as ac

DOC = {
    "version": 7,
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Parent"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Child", "table": "children", "fields": []},
                          {"id": "ENTITY-002", "name": "Doctor", "table": "doctors", "fields": []}]},
    "workflows": [{"id": "FLOW-004", "name": "Create Child", "trigger": {"kind": "manual"}}],
    "pages": [
        {"id": "PAGE-005", "name": "My Children", "route": "/children", "users": ["ROLE-002"],
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-006", "name": "Child", "route": "/children/[id]", "users": ["ROLE-002"],
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-007", "name": "Add Child", "route": "/children/new", "users": ["ROLE-002"],
         "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-008", "name": "Doctors", "route": "/doctors", "data": {"primaryEntity": "ENTITY-002"}},
    ],
    "pageCode": [{"page": "PAGE-007", "view": "<WorkflowForm workflow={workflows.createChild} />", "load": ""},
                 {"page": "PAGE-008", "view": "<Table />", "load": ""}],
}


def test_a_pages_own_files_reach_that_page_only():
    got = ac.affected_pages(DOC, ["app/src/app/(dashboard)/children/view.tsx"])
    assert got == {"PAGE-005"}


def test_a_record_types_schema_reaches_every_page_showing_it():
    assert ac.affected_pages(DOC, ["app/src/db/schema/child.ts"]) == {"PAGE-005", "PAGE-006", "PAGE-007"}
    assert ac.affected_pages(DOC, ["app/src/db/schema/children.ts"]) == {"PAGE-005", "PAGE-006", "PAGE-007"}


def test_a_process_reaches_the_pages_that_start_it():
    assert ac.affected_pages(DOC, ["app/src/lib/workflows/definitions/create-child.json"]) == {"PAGE-007"}


def test_the_shared_frame_reaches_every_page():
    assert len(ac.affected_pages(DOC, ["app/src/app/(dashboard)/layout.tsx"])) == 4


def test_a_definition_alone_reaches_nothing_to_open():
    assert ac.affected_pages(DOC, [".forge/blueprint/current.json"]) == set()


class _Svc:
    def __init__(self, doc):
        self.doc, self.saved = json.loads(json.dumps(doc)), 0

    def save(self):
        self.saved += 1


class _App:
    def __init__(self, _root):
        pass

    def __enter__(self):
        return SimpleNamespace(base="http://x")

    def __exit__(self, *a):
        pass


def _pages_saying(findings_by_round):
    rounds = iter(findings_by_round)

    def check_pages(app, doc, todo, out_dir, *, server_said):
        found = next(rounds)
        return {v["page"]: {"name": v["name"], "route": v["route"],
                            "findings": [(v["as"], found[v["route"]])] if v["route"] in found else []}
                for v in todo}
    return check_pages


def test_a_change_check_repairs_once_and_keeps_what_the_build_said_of_the_rest(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    doc = json.loads(json.dumps(DOC))
    doc["runtime"] = {"check": {"pages": 4, "working": 3, "fixed": ["/doctors"], "failing": ["/doctors"], "version": 6},
                      "issues": [{"kind": "page_check", "page": "PAGE-008", "route": "/doctors", "name": "Doctors",
                                  "detail": "as Admin: it answers HTTP 500"}]}
    svc = _Svc(doc)
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: svc))
    monkeypatch.setattr(ac, "check_pages", _pages_saying([{"/children": "it shows dates in 2001"}, {}]))
    turns = []
    out = ac.check_change(str(tmp_path), ["app/src/db/schema/child.ts"], app_factory=_App,
                          run_turn=lambda pid, od, ask, **k: turns.append(ask) or {"edited_paths": ["app/src/x.ts"]})
    assert len(turns) == 1 and "as Parent: it shows dates in 2001" in turns[0]
    assert out["checked"] == ["/children", "/children/[id]", "/children/new"]
    assert out["fixed"] == ["/children"] and out["touched"] == ["app/src/x.ts"]
    assert "they work (fixed on the way: /children)" in out["said"]
    check = svc.doc["runtime"]["check"]
    assert check["failing"] == ["/doctors"] and check["working"] == 3 and check["version"] == 7   # the rest kept


def test_what_a_change_broke_and_could_not_fix_is_said(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    doc = json.loads(json.dumps(DOC))
    doc["runtime"] = {"check": {"pages": 4, "working": 4, "fixed": [], "failing": [], "version": 6}, "issues": []}
    svc = _Svc(doc)
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: svc))
    broken = {"/children/new": "button \"Add child\" runs a workflow that fails"}
    monkeypatch.setattr(ac, "check_pages", _pages_saying([broken, broken]))
    out = ac.check_change(str(tmp_path), ["app/src/lib/workflows/definitions/create-child.json"], app_factory=_App,
                          run_turn=lambda *a, **k: {})
    assert "Still not working: /children/new — as Parent: button \"Add child\" runs a workflow that fails" in out["said"]
    assert svc.doc["runtime"]["check"]["failing"] == ["/children/new"]
    assert svc.doc["runtime"]["issues"][0]["route"] == "/children/new"


def test_a_change_to_an_app_never_checked_records_only_its_failures(monkeypatch, tmp_path):
    monkeypatch.setattr("services.blueprint.account_model.admin_role", lambda doc: "Admin")
    svc = _Svc(DOC)
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: svc))
    monkeypatch.setattr(ac, "check_pages", _pages_saying([{"/doctors": "it answers HTTP 500"}] * 2))
    ac.check_change(str(tmp_path), ["app/src/db/schema/doctor.ts"], app_factory=_App, run_turn=lambda *a, **k: {})
    runtime = svc.doc["runtime"]
    assert "check" not in runtime                      # no count it did not see
    assert runtime["issues"][0]["route"] == "/doctors"


def test_a_smith_turn_that_changed_the_app_reports_its_check(monkeypatch, tmp_path):
    handle_mod = importlib.import_module("services.smith4.handle")
    from services.smith4.outcome import Outcome
    monkeypatch.setattr(handle_mod, "_handle", lambda **k: Outcome(status="resolved", said="Added a phone field.",
                                                                  touched=["app/src/db/schema/child.ts"]))
    seen = []
    # The statements a change reaches are tried after a chat turn (the page
    # check and its repair turn were retired, 2026-10-09).
    monkeypatch.setattr("services.expects.build.check_change",
                        lambda output_dir, touched: seen.append(list(touched)) or {
                            "said": "I then opened the 3 pages this change reaches … they work.",
                            "touched": ["app/src/fix.ts"], "failing": [], "fixed": [], "tried": []})
    out = handle_mod.handle(project_id="p1", output_dir=str(tmp_path), message="add a phone to child")
    assert seen == [["app/src/db/schema/child.ts"]]
    assert out.said == "Added a phone field.\n\nI then opened the 3 pages this change reaches … they work."
    assert out.touched == ["app/src/db/schema/child.ts", "app/src/fix.ts"]

    seen.clear()
    handle_mod.handle(project_id="p1", output_dir=str(tmp_path), message="fix it", unattended=True)
    assert seen == []                                   # a turn inside a check is not checked again

    # the chat testers use (`smith_chat_v2`) and the platform's both come through `handle`
    root = Path(__file__).resolve().parents[2]
    assert "from services.smith4 import handle as smith4_handle" in (root / "services/smith_chat_v2.py").read_text()
    assert "out = handle(" in (root / "services/smith4/platform.py").read_text()


def test_a_tree_with_nothing_built_is_not_checked(tmp_path):
    assert ac.check_change(str(tmp_path), ["app/src/db/schema/child.ts"]) is None


def test_publish_says_when_the_app_changed_after_its_check(monkeypatch, tmp_path):
    doc = {"version": 9, "runtime": {"check": {"pages": 2, "working": 2, "failing": [], "version": 7}}}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: SimpleNamespace(doc=doc)))
    assert ac.publish_note(str(tmp_path))["stale"] is True
    doc["runtime"]["check"]["version"] = 9
    assert ac.publish_note(str(tmp_path))["stale"] is False


def test_the_version_a_check_reflects_is_in_the_contract():
    import jsonschema
    contract = json.loads((Path(__file__).resolve().parents[2] / "contracts/blueprint.schema.json").read_text())
    jsonschema.validate({"check": {"pages": 1, "working": 1, "version": 3}}, contract["properties"]["runtime"])
