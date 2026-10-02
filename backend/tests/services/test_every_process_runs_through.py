"""Every process is run once, start to finish, before the build says it is done.

A process that fails, stops part-way or never finishes goes to Smith with the
run's own account, unattended, to fix the cause and run it again; what still
fails is said by name (F&B, fxa532bj, 2026-10-01/02).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import process_trials as pt
from services.smith import trials

FLOWS = [
    {"id": "FLOW-001", "name": "Create Category", "trigger": {"kind": "manual"},
     "inputs": [{"name": "name", "kind": "field", "type": "string", "required": True}]},
    {"id": "FLOW-005", "name": "Mark Order Fulfilled", "trigger": {"kind": "manual"},
     "inputs": [{"name": "order", "kind": "record", "entity": "ENTITY-003", "required": True}]},
    {"id": "FLOW-009", "name": "Nightly digest", "trigger": {"kind": "schedule"}},
    {"id": "FLOW-010", "name": "Old", "trigger": {"kind": "manual"}, "status": "DEPRECATED"},
]
DOC = {"workflows": FLOWS, "roles": [{"id": "ROLE-001", "name": "Admin"}],
       "data": {"entities": [{"id": "ENTITY-003", "name": "Order", "table": "orders", "labelField": "customerName",
                              "fields": [{"name": "customerName", "type": "string", "examples": ["Rina"]}]}]},
       "pages": []}

OK = "Create Category (FLOW-001) run as Admin: HTTP 200\nanswer: {}\nsteps:\n  0. Create [db] completed\nwritten:\n  categories +1"
REFUSED = "Mark Order Fulfilled (FLOW-005) run as Admin: HTTP 422\nanswer: {\"error\": \"no status field\"}"


class _Svc:
    def __init__(self, out: Path, doc: dict):
        self.out, self.doc = out, json.loads(json.dumps(doc))
        self.save()

    @property
    def path(self) -> Path:
        return self.out / ".forge" / "blueprint" / "current.json"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.doc))


class _Bench:
    def __init__(self, _out):
        self.closed = False

    def app(self):
        return SimpleNamespace(base="http://x")

    def close(self):
        self.closed = True


def _client(seen):
    def call(*, system, user, schema):
        seen.append(json.loads(user))
        return json.dumps({"runs": [{"workflow": "FLOW-001", "as": "Admin", "input": {"name": "Soups"}},
                                    {"workflow": "FLOW-005", "as": "Admin", "input": {"order": "o-1"}}]})
    return call


def _setup(tmp_path, monkeypatch, outcomes):
    from services.blueprint import service
    monkeypatch.setattr(service.BlueprintService, "load", classmethod(
        lambda cls, output_dir: SimpleNamespace(doc=json.loads(
            (Path(output_dir) / ".forge/blueprint/current.json").read_text()))))
    monkeypatch.setattr(pt, "_records", lambda app, doc: {"Order": [{"id": "o-1", "label": "Rina"}]})
    runs = []

    def run(name, args, *, bench, doc):
        runs.append(args)
        return outcomes[args["workflow"]].pop(0)
    monkeypatch.setattr(trials, "run", run)
    return runs


def test_only_live_processes_a_person_starts_are_run():
    assert [w["id"] for w in pt.manual_workflows(DOC)] == ["FLOW-001", "FLOW-005"]


def test_a_run_that_never_finished_counts_as_failed():
    assert pt.run_failed("`try_workflow` failed: TimeoutError: timed out")
    assert pt.run_failed(REFUSED)
    assert not pt.run_failed(OK)


def test_the_inputs_are_written_from_what_the_process_declares_and_real_ids(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-001": [OK], "FLOW-005": [OK]})
    seen = []
    svc = _Svc(tmp_path, DOC)
    out = pt.prove_processes(svc, str(tmp_path), client=_client(seen), bench_factory=_Bench,
                             run_turn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no repair needed")))
    brief = seen[0]
    assert [p["workflow"] for p in brief["processes"]] == ["FLOW-001", "FLOW-005"]
    assert brief["records"]["Order"][0]["id"] == "o-1"
    assert brief["processes"][1]["inputs"][0]["entity"] == "Order"
    assert runs[1] == {"workflow": "FLOW-005", "input": {"order": "o-1"}, "as": "Admin"}
    assert out["passed"] == ["Create Category", "Mark Order Fulfilled"] and not out["left"]


def test_a_failing_process_goes_to_smith_and_is_run_again(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK], "FLOW-005": [REFUSED, OK]})
    asks = []

    def smith(project_id, output_dir, message, *, max_steps, unattended):
        asks.append((message, unattended))
        return {"answer": "Added a status field and the step that sets it."}

    svc = _Svc(tmp_path, DOC)
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Bench, run_turn=smith)
    assert len(asks) == 1 and asks[0][1] is True
    assert "Mark Order Fulfilled" in asks[0][0] and "no status field" in asks[0][0] and '"order": "o-1"' in asks[0][0]
    assert out["fixed"] == ["Mark Order Fulfilled"] and not out["left"]


def test_what_still_fails_is_recorded_and_said(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK], "FLOW-005": [REFUSED, REFUSED, REFUSED]})
    svc = _Svc(tmp_path, DOC)
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Bench,
                             run_turn=lambda *a, **k: {"answer": "tried"})
    assert [t["name"] for t in out["left"]] == ["Mark Order Fulfilled"]
    issues = json.loads(svc.path.read_text())["runtime"]["issues"]
    assert issues == [{"kind": "process", "workflow": "FLOW-005", "name": "Mark Order Fulfilled",
                       "detail": issues[0]["detail"]}] and "HTTP 422" in issues[0]["detail"]
    from routers.blueprint_generate import _failing_processes_line
    assert "Mark Order Fulfilled" in _failing_processes_line(json.loads(svc.path.read_text()))
    assert next((tmp_path / ".forge/runs").glob("*-process-trials.jsonl"))


def test_an_app_that_cannot_start_records_every_process(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {})

    class _Down(_Bench):
        def app(self):
            raise trials.TrialUnavailable("next dev would not start")

    svc = _Svc(tmp_path, DOC)
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Down,
                             run_turn=lambda *a, **k: {})
    assert len(out["left"]) == 2 and "would not start" in out["left"][0]["reason"]


# --- a reply Smith can read --------------------------------------------------

def test_a_reply_with_a_sentence_and_braces_after_the_object_is_read():
    from services.smith.understand_ask import _parse
    raw = ('Looking at the definition.\n\n```json\n{"tool": "read_section", "args": {"name": "workflows"}, '
           '"why": "see how {{$input.id}} resolves"}\n```\nThen I will {fix} it.')
    assert _parse(raw)["tool"] == "read_section"
    two = '```json\n{"tool": "a", "args": {}}\n```\nthen\n```json\n{"tool": "b", "args": {}}\n```'
    assert _parse(two)["tool"] == "a"


# --- what Smith can read -----------------------------------------------------

def test_a_list_item_is_read_by_its_id_or_name_and_a_cut_says_what_it_holds():
    from services.smith import reads
    flows = [{"id": f"FLOW-{i:03d}", "name": f"Flow {i}", "steps": [{"n": j} for j in range(40)]}
             for i in range(1, 8)]
    doc = {"workflows": flows, "pages": [{"id": "PAGE-007", "route": "/admin/orders", "name": "Orders"}]}
    whole = reads.read_section(doc, "workflows")
    assert "it holds: FLOW-001 (Flow 1)" in whole and "FLOW-007 (Flow 7)" in whole
    assert '"id": "FLOW-007"' in reads.read_section(doc, "workflows.FLOW-007")
    assert '"id": "FLOW-003"' in reads.read_section(doc, "workflows.flow 3")
    assert '"name": "Orders"' in reads.read_section(doc, "pages./admin/orders")
    import pytest
    with pytest.raises(reads.ReadRefused) as no:
        reads.read_section(doc, "workflows.FLOW-099")
    assert "FLOW-001 (Flow 1)" in str(no.value)


def test_a_rewrite_that_names_no_file_still_lets_smith_look_again():
    from services.smith.loop import Observation
    from services.smith4.turn import _changed_after
    tried = Observation(tool="open_page", args={"route": "/admin/orders"}, status="read", said="browser error: …")
    rewrote = Observation(tool="write_page_code", args={"route": "/admin/orders"}, status="resolved",
                          said="Rewrote /admin/orders (version 61)")
    read = Observation(tool="read_section", args={"name": "pages"}, status="read", said="…")
    assert _changed_after([tried, rewrote], 0)
    assert not _changed_after([tried, read], 0)
