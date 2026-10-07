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
        return json.dumps({"runs": [{"workflow": "FLOW-001", "as": "Admin", "input": [{"name": "name", "value": '"Soups"'}]},
                                    {"workflow": "FLOW-005", "as": "Admin", "input": [{"name": "order", "value": '"o-1"'}]}]})
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
    makes, acts = seen                      # what makes records first, then what acts on them
    assert [p["workflow"] for p in makes["processes"]] == ["FLOW-001"]
    assert [p["workflow"] for p in acts["processes"]] == ["FLOW-005"]
    assert acts["records"]["Order"][0]["id"] == "o-1"
    assert acts["processes"][0]["inputs"][0]["entity"] == "Order"
    assert runs[1] == {"workflow": "FLOW-005", "input": {"order": "o-1"}, "as": "Admin"}
    assert out["passed"] == ["Create Category", "Mark Order Fulfilled"] and not out["left"]


def test_a_failing_process_goes_to_smith_and_is_run_again(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [REFUSED, OK]})
    asks = []

    def smith(project_id, output_dir, message, *, max_steps, unattended):
        asks.append((message, unattended))
        return {"answer": "Added a status field and the step that sets it.",
                "edited_paths": [".forge/blueprint/current.json", "app/src/db/schema/order.ts"]}

    svc = _Svc(tmp_path, DOC)
    out = pt.prove_processes(svc, str(tmp_path), client=_client([]), bench_factory=_Bench, run_turn=smith)
    assert len(asks) == 1 and asks[0][1] is True
    assert "Mark Order Fulfilled" in asks[0][0] and "no status field" in asks[0][0] and '"order": "o-1"' in asks[0][0]
    assert out["fixed"] == ["Mark Order Fulfilled"] and not out["left"]


def test_what_still_fails_is_recorded_and_said(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [REFUSED, REFUSED, REFUSED]})
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


def test_every_object_in_the_inputs_schema_is_closed():
    """The API refuses a structured-output schema with an open object (the
    first live run lost the whole stage to it)."""
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(pt.INPUTS_SCHEMA)


def test_values_come_back_typed_and_a_failed_call_still_runs_every_process():
    assert pt._pairs([{"name": "price", "value": "12.5"}, {"name": "items", "value": '[{"q": 2}]'},
                      {"name": "note", "value": "not json"}]) == {"price": 12.5, "items": [{"q": 2}], "note": "not json"}

    def broken(**_k):
        raise RuntimeError("400 schema")
    assert pt.compose_inputs(DOC, FLOWS[:2], {}, broken) == {}


def test_a_real_clients_reply_object_is_read():
    from services.blueprint.executors import ModelReply
    reply = ModelReply(text=json.dumps({"runs": [{"workflow": "FLOW-001", "as": "", "input": [{"name": "name", "value": '"Soups"'}]}]}))
    assert pt.compose_inputs(DOC, FLOWS[:1], {}, lambda **_k: reply) == {"FLOW-001": {"as": "", "input": {"name": "Soups"}}}


def test_the_second_run_is_chosen_knowing_why_the_first_was_refused(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [REFUSED, OK]})
    seen = []
    svc = _Svc(tmp_path, DOC)
    pt.prove_processes(svc, str(tmp_path), client=_client(seen), bench_factory=_Bench,
                       run_turn=lambda *a, **k: {"answer": "The process is right; that order is already fulfilled."})
    second = {p["workflow"]: p for p in seen[-1]["processes"]}
    assert "no status field" in second["FLOW-005"]["lastRun"] and "already fulfilled" in second["FLOW-005"]["lastRun"]
    assert "lastRun" not in {p["workflow"]: p for p in seen[1]["processes"]}["FLOW-005"]


def test_what_makes_records_runs_before_what_acts_on_them(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-001": [OK], "FLOW-005": [OK]})
    reads = []
    monkeypatch.setattr(pt, "_records", lambda app, doc: reads.append(len(runs)) or {})
    seen = []
    doc = json.loads(json.dumps(DOC))
    doc["workflows"] = [doc["workflows"][1], doc["workflows"][0]]       # the record-taking one listed first
    pt.prove_processes(_Svc(tmp_path, doc), str(tmp_path), client=_client(seen), bench_factory=_Bench,
                       run_turn=lambda *a, **k: {})
    assert [r["workflow"] for r in runs] == ["FLOW-001", "FLOW-005"]
    assert reads == [0, 1], "the records are read again after the create ran"
    assert [p["workflow"] for p in seen[0]["processes"]] == ["FLOW-001"]


def test_records_are_read_from_the_columns_the_table_has(monkeypatch):
    from services.blueprint import page_review
    asked = []

    def query(app, sql):
        asked.append(sql)
        if "information_schema" in sql:
            return [["id"], ["customer_name"], ["created_at"]] if "'orders'" in sql else [["id"]]
        return [["o-2", "Rina"], ["o-1", "Ahmad"]]
    monkeypatch.setattr(page_review, "_query", query)
    doc = {"data": {"entities": [
        {"name": "Order", "table": "orders", "labelField": "customerName"},
        {"name": "Tag", "table": "tags", "labelField": "title"}]}}
    got = pt._records(object(), doc)
    assert got["Order"][0] == {"id": "o-2", "label": "Rina"}
    reads = [q for q in asked if "information_schema" not in q]
    assert 'select id::text, "customer_name"::text from "orders" order by created_at desc nulls last limit 10' in reads
    assert """select id::text, '' from "tags" limit 10""" in reads


def test_creates_then_changes_then_deletes():
    def flow(fid, ops, takes):
        return {"id": fid, "steps": [{"config": {"actionType": o}} for o in ops],
                "inputs": [{"name": "r", "kind": "record"}] if takes else []}
    flows = [flow("DEL", ["db_query", "db_delete"], True), flow("EDIT", ["db_update"], True),
             flow("ADD", ["db_insert"], True), flow("ORDER", ["db_insert", "db_update"], False)]
    assert pt._phases(flows) == [["ADD", "ORDER"], ["EDIT"], ["DEL"]]


def test_a_later_round_runs_the_proven_creates_again_first_unjudged(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-001": [OK, REFUSED], "FLOW-005": [REFUSED, OK]})
    out = pt.prove_processes(_Svc(tmp_path, DOC), str(tmp_path), client=_client([]), bench_factory=_Bench,
                             run_turn=lambda *a, **k: {"answer": "", "edited_paths": ["app/x.ts"]})
    assert [r["workflow"] for r in runs] == ["FLOW-001", "FLOW-005", "FLOW-001", "FLOW-005"]
    assert out["passed"] == ["Create Category"] and out["fixed"] == ["Mark Order Fulfilled"] and not out["left"]


def test_a_process_the_writer_left_out_is_asked_for_on_its_own(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-001": [OK], "FLOW-005": [OK]})
    calls = []

    def writer(*, system, user, schema):
        listed = [p["workflow"] for p in json.loads(user)["processes"]]
        calls.append(listed)
        if listed == ["FLOW-005"]:
            return json.dumps({"runs": [{"workflow": "FLOW-005", "as": "", "input": [{"name": "order", "value": '"o-1"'}]}]})
        return json.dumps({"runs": [{"workflow": "FLOW-001", "as": "", "input": []}]})   # FLOW-005 left out

    doc = json.loads(json.dumps(DOC))
    doc["workflows"][0]["inputs"] = [{"name": "order", "kind": "record", "entity": "ENTITY-003"}]   # both in one phase
    doc["workflows"][0]["steps"] = doc["workflows"][1]["steps"] = [{"config": {"actionType": "db_update"}}]
    pt.prove_processes(_Svc(tmp_path, doc), str(tmp_path), client=writer, bench_factory=_Bench,
                       run_turn=lambda *a, **k: {})
    assert calls == [["FLOW-001", "FLOW-005"], ["FLOW-005"]]
    assert {r["workflow"]: r["input"] for r in runs}["FLOW-005"] == {"order": "o-1"}


# --- wz7a99ir (2026-10-04): a test file for a file input; "fixed" only when something changed ---

IMAGE_FLOW = {"id": "FLOW-002", "name": "Create Category", "trigger": {"kind": "manual"},
              "inputs": [{"name": "name", "kind": "field", "type": "string", "required": True},
                         {"name": "image", "kind": "field", "type": "image", "required": True}]}


def test_a_file_or_image_input_gets_a_stored_test_file(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-002": [OK]})
    stored = []
    monkeypatch.setattr(trials, "stored_file", lambda bench, doc, kind, as_: stored.append((kind, as_)) or "file-1")

    def client(*, system, user, schema):
        return json.dumps({"runs": [{"workflow": "FLOW-002", "as": "Admin",
                                     "input": [{"name": "name", "value": '"Vegan Specials"'}]}]})
    doc = {**DOC, "workflows": [IMAGE_FLOW]}
    out = pt.prove_processes(_Svc(tmp_path, doc), str(tmp_path), client=client, bench_factory=_Bench,
                             run_turn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no repair needed")))
    assert runs[0]["input"] == {"name": "Vegan Specials", "image": "file-1"}
    assert stored == [("image", "Admin")] and out["passed"] == ["Create Category"]


def test_a_given_file_is_kept_and_other_inputs_are_left_alone():
    run = {"as": "Admin", "input": {"image": "mine", "name": "x"}}
    pt.attach_files(None, {}, IMAGE_FLOW, run)
    assert run["input"] == {"image": "mine", "name": "x"}


def test_a_rerun_with_a_better_input_is_passed_not_fixed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [REFUSED, OK]})
    out = pt.prove_processes(_Svc(tmp_path, DOC), str(tmp_path), client=_client([]), bench_factory=_Bench,
                             run_turn=lambda *a, **k: {"answer": "The process is right; ran it with an open order.",
                                                       "edited_paths": []})
    assert out["passed"] == ["Create Category", "Mark Order Fulfilled"] and out["fixed"] == []


def test_rows_made_by_this_run_are_marked_new():
    records = {"FoodItem": [{"id": "f-9", "label": "Beef Wellington"}, {"id": "f-1", "label": "Samosa"}]}
    assert pt._mark_new(records, {"f-1"}) == {"FoodItem": [{"id": "f-9", "label": "Beef Wellington", "new": True},
                                                           {"id": "f-1", "label": "Samosa"}]}
    assert "marked `new`" in pt.INPUTS_SYSTEM and "the run attaches a test file" in pt.INPUTS_SYSTEM


def test_a_change_with_no_file_after_a_failing_try_ends_the_turn_cleanly():
    """ihf6pjga, 2026-10-05 18:52: a workflow refused the admin (403), Smith
    rewrote the permissions — a change with no file — read the rows, and said
    `done`. The check before `done` counted the rewrite as a change, then asked
    for the latest change WITH a file, found none, and the turn died on
    `max()` of nothing: "Something went wrong on my side (ValueError)"."""
    from services.smith.loop import Observation
    from services.smith4.turn import UNPROVEN, _before_done

    tried = Observation(tool="try_workflow", args={"workflow": "Create Product"}, status="read",
                        said="Create Product: HTTP 403 — This action is not available to your role")
    rewrote = Observation(tool="write_section", args={"section": "permissions"}, status="resolved",
                          said="permissions rewritten")
    read = Observation(tool="read_rows", args={"entity": "Product"}, status="read", said="0 rows")

    said = _before_done([tried, rewrote, read], landed=[])
    assert said.startswith(UNPROVEN), "the change is a guess until the refused action is tried again"

    again = Observation(tool="try_workflow", args={"workflow": "Create Product"}, status="read",
                        said="Create Product: HTTP 200 — created")
    assert _before_done([tried, rewrote, read, again], landed=[]) == ""


# --- a refusal is the app's own rule more often than a fault (ToroCommerce, 2026-10-07) ---

TURNED_DOWN = ('Mark Order Fulfilled (FLOW-005) run as Admin: HTTP 422\nanswer: {"status": "failed", '
               '"refused": true, "error": "That order is already fulfilled."}')


def _judging_client(seen, verdict):
    runs = _client(seen)

    def call(*, system, user, schema):
        if schema is pt.JUDGE_SCHEMA:
            seen.append(("judge", json.loads(user)))
            return json.dumps({"verdicts": [{"workflow": "FLOW-005", "refusal": verdict, "why": "x"}]})
        return runs(system=system, user=user, schema=schema)
    return call


def test_a_rightly_refused_run_is_tried_again_with_a_new_input_not_sent_to_smith(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [TURNED_DOWN, OK]})
    seen, asks = [], []
    out = pt.prove_processes(_Svc(tmp_path, DOC), str(tmp_path), client=_judging_client(seen, "right"),
                             bench_factory=_Bench, run_turn=lambda *a, **k: asks.append(a) or {})
    assert asks == [], "no Smith turn for the app keeping its own rule"
    assert out["passed"] == ["Create Category", "Mark Order Fulfilled"] and not out["left"]
    judged = [s for s in seen if isinstance(s, tuple)]
    assert judged and judged[0][1]["runs"][0]["refused"] == "That order is already fulfilled."
    replanned = [s for s in seen if isinstance(s, dict) and any(p.get("lastRun") for p in s["processes"])]
    assert "rightly refused" in replanned[0]["processes"][0]["lastRun"], "the new input is chosen knowing why"
    assert [r["workflow"] for r in runs].count("FLOW-005") == 2


def test_a_wrong_refusal_is_a_fault_and_goes_to_smith(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [TURNED_DOWN, OK]})
    asks = []
    out = pt.prove_processes(_Svc(tmp_path, DOC), str(tmp_path), client=_judging_client([], "wrong"),
                             bench_factory=_Bench,
                             run_turn=lambda pid, od, message, **k: asks.append(message) or {"edited_paths": ["x"]})
    assert len(asks) == 1 and "already fulfilled" in asks[0]
    assert out["fixed"] == ["Mark Order Fulfilled"]


def test_refused_again_with_an_input_meant_to_pass_goes_to_smith_saying_so(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [TURNED_DOWN, TURNED_DOWN, OK]})
    asks = []
    pt.prove_processes(_Svc(tmp_path, DOC), str(tmp_path), client=_judging_client([], "right"),
                       bench_factory=_Bench,
                       run_turn=lambda pid, od, message, **k: asks.append(message) or {"edited_paths": ["x"]})
    assert len(asks) == 1 and "Refused twice" in asks[0] and "the data or a rule is what is wrong" in asks[0]


def test_a_process_is_run_as_the_people_it_is_for():
    doc = {**DOC, "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
           "pages": [{"id": "PAGE-002", "route": "/cart", "users": ["ROLE-002"]}],
           "workflows": [{**FLOWS[0], "launchedFrom": ["PAGE-002"]}]}
    brief = json.loads(pt._brief(doc, doc["workflows"], {}))
    assert [s["route"] for s in brief["processes"][0]["startedFrom"]] == ["/cart"]
    assert "never as a stand-in for a customer" in pt.INPUTS_SYSTEM
