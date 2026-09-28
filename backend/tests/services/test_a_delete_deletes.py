"""Test 5 (z0024gyq), 2026-09-28: "give me the provision to add and delete
the person".

Every kept Delete waited 300ms and filtered the row out of React state; the
row came back on reload. One rewrite took the button away and was reported
as "Rewrote /register (version 27)". When Smith finally added a DeleteWorker
workflow, the layout composer tried to redraw the React page, was refused
twice, and Smith said "nothing has been changed" with the workflow in place.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.blueprint import ui_engineer
from services.blueprint.ui_engineer import (
    NeedsWorkflow, _control_labels, _dropped_controls, _simulated_writes, compose_page)

GOOD_LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'

FAKE_DELETE = '''"use client";
export default function View({ workers: initial }: Props) {
  const [workers, setWorkers] = useState(initial);
  const handleDelete = async (id: string) => {
    setDeletingId(id);
    await new Promise((resolve) => setTimeout(resolve, 300));
    setWorkers((prev) => prev.filter((x) => x.id !== id));
    setDeletingId(null);
  };
  return <Button variant="danger" onClick={() => handleDelete(w.id)} disabled={deletingId === w.id}>
    {deletingId === w.id ? "Deleting…" : "Delete / हटाएं"}
  </Button>;
}
'''
REAL_DELETE = '''"use client";
export default function View({ workers: initial }: Props) {
  const [workers, setWorkers] = useState(initial);
  const { run } = useWorkflow(workflows.deleteWorker);
  const handleDelete = async (id: string) => {
    const out = await run({ worker: id });
    if (out.ok) setWorkers((prev) => prev.filter((x) => x.id !== id));
  };
  return <Button variant="danger" onClick={() => handleDelete(w.id)}>Delete / हटाएं</Button>;
}
'''


def _doc():
    return {
        "application": {"id": "t", "name": "Workers", "description": "Register workers."},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Worker", "fields": [
            {"name": "name", "type": "string", "required": True}]}]},
        "pages": [{"id": "PAGE-001", "name": "Register", "route": "/register", "purpose": "Register workers.",
                   "data": {"primaryEntity": "ENTITY-001"}}],
        "workflows": [],
        "composition": {"vision": "Plain.", "conventions": []},
    }


class _Client:
    max_tokens = 64000

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, *, system, user, schema):
        self.calls.append((user, schema))
        return json.dumps(self.replies.pop(0))


# ── No faked writes ─────────────────────────────────────────────────────────

def test_a_delete_that_only_edits_the_screen_is_refused():
    assert _simulated_writes(FAKE_DELETE)
    assert "needs" in _simulated_writes(FAKE_DELETE)[0]


def test_a_delete_that_runs_a_workflow_is_not():
    assert _simulated_writes(REAL_DELETE) == []


def test_a_search_filter_is_not_a_write():
    view = ('const shown = useMemo(() => rows.filter((r) => r.name.includes(q)), [rows, q]);\n'
            'function toggle(id: string) { setOpen((o) => (o === id ? null : id)); }')
    assert _simulated_writes(view) == []


def test_the_writer_is_told_a_change_is_never_simulated():
    assert "A CHANGE NO WORKFLOW MAKES IS NEVER SIMULATED" in ui_engineer.system_prompt(_doc())
    assert "needs" in ui_engineer.PAGE_EDIT_SCHEMA["required"]


def test_a_change_that_needs_a_workflow_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "", "edits": [], "load": "", "view": "", "needs": ["delete a Worker"]}])
    with pytest.raises(NeedsWorkflow) as e:
        compose_page(_doc(), _doc()["pages"][0], tmp_path, client, brief="make delete remove the worker",
                     current={"load": GOOD_LOAD, "view": REAL_DELETE.replace("workflows.deleteWorker", "x")})
    assert e.value.needs == ["delete a Worker"]
    assert len(client.calls) == 1, "nothing is compiled around a missing workflow"


def test_a_faked_delete_goes_back_to_the_writer(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "", "load": GOOD_LOAD, "view": FAKE_DELETE},
                      {"rationale": "", "load": GOOD_LOAD, "view": REAL_DELETE}])
    # A repair round, so no plan is asked first: every reply here is code.
    body, _ = compose_page(_doc(), _doc()["pages"][0], tmp_path, client, feedback="write it")
    assert "useWorkflow" in body["view"]
    assert "without running a workflow" in client.calls[-1][0]


# ── Nothing asked for disappears quietly ───────────────────────────────────

def test_the_labels_of_a_button_are_read_through_its_handler():
    assert _control_labels(FAKE_DELETE) == ["Deleting…", "Delete / हटाएं"]


def test_a_rewrite_that_drops_the_delete_is_sent_back():
    after = '"use client";\nexport default function View() { return <div />; }'
    assert _dropped_controls(FAKE_DELETE, after, "its not deleting from the table") \
        == ["Deleting…", "Delete / हटाएं"]


def test_an_ask_to_remove_or_rename_it_is_honoured():
    after = '"use client";\nexport default function View() { return <div />; }'
    assert _dropped_controls(FAKE_DELETE, after, "remove the delete button") == []
    renamed = REAL_DELETE.replace("Delete / हटाएं", "Remove")
    assert _dropped_controls(REAL_DELETE, renamed, "rename Delete to Remove") == []


def test_a_changed_page_that_drops_a_control_is_not_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    dropped = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
    client = _Client([{"rationale": "", "edits": [], "load": GOOD_LOAD, "view": dropped, "needs": []}]
                     * ui_engineer.COMPILE_ROUNDS)
    with pytest.raises(ui_engineer.CompileError) as e:
        compose_page(_doc(), _doc()["pages"][0], tmp_path, client, brief="its not deleting from the table",
                     current={"load": GOOD_LOAD, "view": REAL_DELETE})
    assert "took away" in str(e.value) and "Delete / हटाएं" in str(e.value)


def test_a_rewrite_says_what_it_changed(monkeypatch, tmp_path):
    from services.smith import compose, writes
    out_dir = tmp_path
    doc = {"pages": [{"id": "PAGE-001", "route": "/register"}],
           "pageCode": [{"page": "PAGE-001", "view": "x", "load": "y"}]}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: SimpleNamespace(doc=doc)))
    monkeypatch.setattr(compose, "recode_page", lambda *a, **k: {
        "applied": True, "committed": ["pageCode"], "version": 28, "missing": [],
        "rationale": "Delete now runs DeleteWorker, so the worker is removed from the records."})
    said = writes.write_page_code(str(out_dir), "/register", "make delete real")["said"]
    assert said == ("Rewrote **/register** (version 28): Delete now runs DeleteWorker, so the "
                    "worker is removed from the records.")


# ── Workflow first ──────────────────────────────────────────────────────────

def test_a_page_that_needs_a_workflow_tells_smith_to_add_it(monkeypatch, tmp_path):
    from services.smith import compose, writes
    doc = {"pages": [{"id": "PAGE-001", "route": "/register"}],
           "pageCode": [{"page": "PAGE-001", "view": "x", "load": "y"}]}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: SimpleNamespace(doc=doc)))

    def needs(*a, **k):
        raise compose.NeedsWorkflowError("/register", ["delete a Worker"])
    monkeypatch.setattr(compose, "recode_page", needs)
    out = writes.write_page_code(str(tmp_path), "/register", "make delete real")
    assert not out["applied"]
    assert out["finding"].startswith("/register was not changed: the change needs records to delete a Worker")
    assert "`add_workflow`" in out["finding"]


def test_the_loop_is_told_a_change_to_records_is_a_workflow_first():
    from services.smith import loop, writes
    assert "A CHANGE TO RECORDS IS A WORKFLOW, AND IT COMES FIRST" in loop._PROMPT
    assert "`add_workflow` first" in writes.WRITES[0][1]


# ── A code page is changed as code, and a refused screen is not "nothing" ──

def test_composing_a_coded_page_rewrites_its_code(monkeypatch):
    from services.smith import compose
    doc = {"pages": [{"id": "PAGE-001", "route": "/register"}],
           "pageCode": [{"page": "PAGE-001", "view": "x", "load": "y"}]}
    svc = SimpleNamespace(doc=doc, output_dir="/tmp/app-x")
    seen = {}

    def recode(svc_, route, *, app_root, request, reasoning=None):
        seen.update(route=route, app_root=app_root, request=request)
        return {"applied": True, "committed": ["pageCode"], "version": 9, "missing": []}
    monkeypatch.setattr(compose, "recode_page", recode)
    monkeypatch.setattr(compose, "_ensure_page", lambda svc_, route, request: doc["pages"][0])
    out = compose.compose_route(svc, "/register", request="add a control that runs DeleteWorker")
    assert out.coded and out.committed == ["pageCode"]
    assert seen == {"route": "/register", "app_root": "/tmp/app-x/app",
                    "request": "add a control that runs DeleteWorker"}


def test_a_workflow_whose_screen_is_refused_is_still_reported_added():
    from services.smith.workflow_change import summary_of
    s = summary_of("add_workflow", {"name": "DeleteWorker", "workflow": "FLOW-002", "steps": 3,
                                    "trigger": "manual", "requirement": "REQ-009", "composed": None,
                                    "offered": False, "page_refused": "/register was not changed: X",
                                    "start_route": "/register"})
    assert s.startswith("Added the workflow DeleteWorker (FLOW-002)")
    assert "The workflow is in the app, but /register could not be changed to offer it" in s


def test_the_loop_sees_a_refused_screen_as_something_to_do(monkeypatch, tmp_path):
    from services.smith import workflow_change
    from services.smith4.verbs import Ctx, workflow
    monkeypatch.setattr(workflow_change, "run", lambda *a, **k: {
        "applied": True, "edited_paths": ["x"], "diff_summary": "Added the workflow DeleteWorker.",
        "name": "DeleteWorker", "workflow": "FLOW-002", "page_refused": "refused", "start_route": "/register"})
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="m", ask="m")
    out = workflow(ctx, {"verb": "add_workflow", "workflow": "DeleteWorker"})
    assert out.status == "resolved"
    assert "does not offer it yet" in out.finding and "`write_page_code`" in out.finding


def test_a_coded_page_offers_a_workflow_its_code_runs():
    from services.smith.workflow_change import _offers
    doc = {"workflows": [{"id": "FLOW-002", "name": "DeleteWorker"}],
           "pageCode": [{"page": "PAGE-001", "view": REAL_DELETE, "load": ""}]}
    assert _offers(doc, "PAGE-001", "FLOW-002")
    doc["pageCode"][0]["view"] = FAKE_DELETE
    assert not _offers(doc, "PAGE-001", "FLOW-002")
