"""Every process is run once, start to finish, before the build says it is done.

F&B's edit screens shipped saying "Editing isn't wired up yet" and its order
queue had nothing to mark an order fulfilled (fxa532bj, 2026-10-01); the
build's checks were about whether a control would be accepted on its first
click, not whether the process behind it ran to its end and wrote what it
says. A process that stops part-way, writes nothing, or never finishes was
found by the person using the app.

After the pages are finished (`page_repair`), each process a person starts is
run on a copy of the application's database, as the role that starts it,
with a realistic input. The inputs are written by one small model call that
sees each process's declared inputs, the fields' examples and allowed values,
and real record ids from the copy — values made up in code would be refused
by a correct process and send a repair after a fault that is not there.

A run that fails — an error, a failed step, a refusal of good input, a server
error, or no answer within the trial's timeout — goes to Smith, unattended,
with the run's own account: what each step did and handed on, what was
written, what the server printed. Smith fixes the cause wherever it lives and
runs it again. What still fails after `ROUNDS` is recorded by name.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

ROUNDS = 2
STEPS = 12

INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["runs"],
    "properties": {"runs": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["workflow", "as", "input"],
        "properties": {
            "workflow": {"type": "string", "description": "The process id (FLOW-…)."},
            "as": {"type": "string", "description": "The role that runs it, by name; empty for the administrator."},
            # A list of pairs, each value as JSON: structured output takes no
            # object whose keys it does not know in advance.
            "input": {"type": "array", "description": "One entry per input given, named as the process declares it.",
                      "items": {"type": "object", "additionalProperties": False, "required": ["name", "value"],
                                "properties": {"name": {"type": "string"},
                                               "value": {"type": "string",
                                                         "description": "The value as JSON: \"Soups\", 12.5, true, [{\"menuItemId\": \"…\", \"quantity\": 2}]"}}}},
        }}}},
}

INPUTS_SYSTEM = (
    "You write one realistic run for EVERY process listed — never skip one — of a built application: the input a real "
    "person would give it, as the role that would run it. Use the field examples and allowed "
    "values you are shown; a record input or a reference to another record — including an id "
    "inside a list of items — takes one of the real ids listed, never a made-up one. A new "
    "record's name must not be one already listed among that record's rows. Fill every required input with a value the process should accept; fill "
    "optional ones when a real person would. Leave out file and image inputs: the run attaches a test file to "
    "each. A row marked `new` was made by this run moments ago — for a process that changes or deletes a "
    "record, take a `new` one of the right kind when there is one, as nothing depends on it yet. Do not try to make "
    "a process refuse: the run proves it works. When a process shows `lastRun`, its last input "
    "was refused or failed for the reason given there: choose one that the rule accepts — a name "
    "not already taken, a record nothing else depends on."
)


def manual_workflows(doc: dict) -> list[dict]:
    """The live processes a person starts."""
    return [w for w in doc.get("workflows") or []
            if isinstance(w, dict) and w.get("id")
            and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")
            and str((w.get("trigger") or {}).get("kind") or "manual") == "manual"]


def _records(app: Any, doc: dict) -> dict[str, list[dict]]:
    """Up to ten real rows per entity from the copy, newest first: id and label.

    The table's columns are asked for first: `_query` answers a failed
    statement with no rows, so a read that guessed a column and fell back on
    failure read every table as empty — and the inputs were written with
    names where ids belong (2026-10-02)."""
    from services.blueprint.page_review import _query

    out: dict[str, list[dict]] = {}
    for e in ((doc.get("data") or {}).get("entities") or []):
        table, label = str(e.get("table") or ""), str(e.get("labelField") or "id")
        if not table or not table.replace("_", "").isalnum():
            continue
        cols = {r[0] for r in _query(app, "select column_name from information_schema.columns "
                                          f"where table_schema = 'public' and table_name = '{table}'") if r}
        if "id" not in cols:
            continue
        col = "".join("_" + c.lower() if c.isupper() else c for c in label)
        shown = f'"{col}"::text' if col in cols else "''"
        # NEWEST FIRST: a row a create run made a moment ago has nothing
        # depending on it yet, so an edit or a delete can use it.
        order = "order by created_at desc nulls last " if "created_at" in cols else ""
        rows = _query(app, f'select id::text, {shown} from "{table}" {order}limit 10')
        out[str(e.get("name"))] = [{"id": r[0], "label": r[1] if len(r) > 1 else ""} for r in rows or [] if r]
    return out


def _brief(doc: dict, flows: list[dict], records: dict[str, list[dict]],
           before: dict[str, str] | None = None) -> str:
    from services.blueprint.projection import launch_roles

    entities = {str(e.get("id")): e for e in ((doc.get("data") or {}).get("entities") or [])}
    roles = launch_roles(doc)
    shown = []
    for w in flows:
        inputs = []
        for i in w.get("inputs") or []:
            row = {k: i.get(k) for k in ("name", "kind", "type", "required", "description") if i.get(k) is not None}
            if i.get("entity"):
                row["entity"] = str((entities.get(str(i["entity"])) or {}).get("name") or i["entity"])
            inputs.append(row)
        row = {"workflow": w.get("id"), "name": w.get("name"), "purpose": w.get("description") or "",
               "inputs": inputs, "runBy": roles.get(str(w.get("id"))) or []}
        # WHAT THE LAST RUN WAS TOLD. F&B's first round picked "Soups", which
        # the seed already had, a category that still held food items and a
        # dish already ordered — each refused, correctly, by the app's own
        # rule (2026-10-02). The second run is chosen knowing why.
        if (before or {}).get(str(w.get("id"))):
            row["lastRun"] = before[str(w.get("id"))]
        shown.append(row)
    fields = {str(e.get("name")): [{k: f.get(k) for k in ("name", "type", "enumValues", "examples", "required")
                                   if f.get(k) not in (None, [], "")}
                                  for f in e.get("fields") or [] if isinstance(f, dict)]
              for e in entities.values()}
    rules = [{"name": r.get("name"), "statement": r.get("statement")}
             for r in doc.get("businessRules") or [] if isinstance(r, dict)]
    return json.dumps({"processes": shown, "entities": fields, "records": records, "rules": rules},
                      default=str)[:60000]


def compose_inputs(doc: dict, flows: list[dict], records: dict[str, list[dict]],
                   client: Any, before: dict[str, str] | None = None) -> dict[str, dict]:
    """{FLOW-id: {"as": role, "input": {...}}} — one call for every process.
    A call that fails leaves every process to run with no input: a refusal
    then goes to Smith, who runs it with the right one — the stage is never
    skipped for want of sample values."""
    try:
        reply = client(system=INPUTS_SYSTEM, user=_brief(doc, flows, records, before), schema=INPUTS_SCHEMA)
        body = json.loads(getattr(reply, "text", reply))
        body = body.get("result", body) if isinstance(body, dict) else body
    except Exception:  # noqa: BLE001
        logger.warning("[process-trials] no inputs were written", exc_info=True)
        return {}
    out: dict[str, dict] = {}
    for run in (body or {}).get("runs") or []:
        if isinstance(run, dict) and run.get("workflow"):
            out[str(run["workflow"])] = {"as": str(run.get("as") or ""), "input": _pairs(run.get("input"))}
    return out


def _pairs(given: Any) -> dict:
    """[{name, value-as-JSON}] -> {name: value}; a bare object is taken as it is."""
    if isinstance(given, dict):
        return given
    out: dict = {}
    for pair in given or []:
        if not isinstance(pair, dict) or not pair.get("name"):
            continue
        raw = pair.get("value")
        try:
            out[str(pair["name"])] = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            out[str(pair["name"])] = raw
    return out


def _phases(flows: list[dict]) -> list[list[str]]:
    """Process ids in three phases: what inserts records (and removes none),
    what changes them, what deletes them."""
    from services.blueprint.functional_completeness import _workflow_db_ops

    makes, changes, removes = [], [], []
    for w in flows:
        ops = _workflow_db_ops(w)
        takes = any(isinstance(i, dict) and i.get("kind") == "record" for i in w.get("inputs") or [])
        if "db_delete" in ops:
            removes.append(str(w["id"]))
        elif "db_insert" in ops or not takes:
            makes.append(str(w["id"]))
        else:
            changes.append(str(w["id"]))
    return [g for g in (makes, changes, removes) if g]


#: Input types a person fills by choosing a file. `compose_inputs` leaves them
#: out; the run attaches a stored test file. Left empty, F&B's Create Category
#: and Add Food Item were refused "needs image" on every build, and a Smith
#: turn each was spent finding that the input, not the app, was short
#: (wz7a99ir, 2026-10-04).
FILE_INPUTS = frozenset({"image", "photo", "picture", "file", "document", "pdf", "attachment"})


def attach_files(bench: Any, doc: dict, flow: dict, run: dict) -> None:
    """Give each file or image input the run left empty a stored test file."""
    from services.smith import trials
    given = run.setdefault("input", {})
    for i in flow.get("inputs") or []:
        if not isinstance(i, dict) or not i.get("name") or given.get(i["name"]) not in (None, ""):
            continue
        kind = str(i.get("type") or i.get("kind") or "").lower()
        if kind not in FILE_INPUTS:
            continue
        stored = trials.stored_file(bench, doc, "file" if kind in ("file", "document", "pdf", "attachment")
                                    else "image", run.get("as") or "")
        if stored:
            given[i["name"]] = stored


def _mark_new(records: dict[str, list[dict]], before: set[str]) -> dict[str, list[dict]]:
    """Rows this run made since `before` was read, marked `new`."""
    return {k: [{**r, "new": True} if r.get("id") not in before else r for r in rows]
            for k, rows in records.items()}


def run_failed(said: str) -> bool:
    """A trial that shows the process not working — and one that could not
    finish at all (the trial's own timeout or a crash), which `trials.failed`
    reads as a missing header rather than a failure."""
    from services.smith import trials
    return trials.failed(said) or said.startswith("`try_workflow` failed")


def _why(said: str) -> str:
    """The run's own reason, in a line: the app's error, else its first line."""
    import re
    m = re.search(r'"error": "([^"]{1,300})"', said)
    return m.group(1) if m else said.split("\n", 1)[0][:200]


def fault_ask(flow: dict, run: dict, said: str) -> str:
    return (
        f"The build ran the process {flow.get('name')} ({flow.get('id')}) once, as "
        f"{run.get('as') or 'the administrator'}, with this input: {json.dumps(run.get('input') or {}, default=str)}. "
        f"It did not work. What the run showed:\n{said[:3000]}\n\n"
        "Find the cause and fix it where it lives — a step, how the flow runs, what one step hands "
        "the next, a field or record the data model lacks, a rule, who may run it — or, if the "
        "input was wrong for what the process rightly asks, run it with the right one. Then run it "
        "again and see it finish and write what it says. Nobody is waiting to answer questions: "
        "decide from the definition and act."
    )


def prove_processes(svc: Any, output_dir: str, *args: Any, **kwargs: Any) -> dict:
    """See `_prove_processes`; its model calls, and the Smith turns it starts, are the build's spend."""
    from services.build_usage import usage_scope
    with usage_scope(agent="process_trials", output_dir=str(output_dir), phase="build", kind="build"):
        return _prove_processes(svc, output_dir, *args, **kwargs)


def _prove_processes(svc: Any, output_dir: str, *,
                    emit: Callable[[str, dict], None] | None = None,
                    client: Any = None,
                    run_turn: Callable[..., dict] | None = None,
                    bench_factory: Callable[[str], Any] | None = None,
                    rounds: int = ROUNDS, record: bool = True) -> dict:
    """Run every process; repair what fails; returns {passed, fixed, left}."""
    from services.blueprint.page_repair import _ledger
    from services.blueprint.round_trips import read_back
    from services.smith import trials

    say = emit or (lambda _e, _d: None)
    if run_turn is None:
        from services.smith4.platform import smith_result as run_turn
    if bench_factory is None:
        bench_factory = trials.Bench
    if client is None:
        # Filling a declared shape from examples and ids: low effort. Not a
        # node of the graph, so not in the router's per-node table.
        from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
        client = AnthropicModel(model=DEFAULT_MODEL, effort="low")

    def reload() -> None:
        from services.blueprint.service import BlueprintService
        try:
            svc.doc = BlueprintService.load(output_dir=output_dir).doc
        except Exception:  # noqa: BLE001
            logger.warning("[process-trials] could not reload the Blueprint", exc_info=True)

    flows = manual_workflows(svc.doc)
    if not flows:
        return {"passed": [], "fixed": [], "left": []}
    passed: list[str] = []
    fixed: list[str] = []
    # FIXED MEANS SOMETHING CHANGED. A repair that only ran the process again
    # with a better input left the app as it was; counting that as "fixed"
    # told the owner three working processes had been broken (wz7a99ir).
    changed: set[str] = set()
    left: list[dict] = []
    pending = [str(w["id"]) for w in flows]
    lessons: dict[str, str] = {}
    proven: list[str] = []
    with _ledger(output_dir if record else None, len(pending), node="process_trials") as ledger:
        for round_ in range(1, rounds + 2):
            if not pending:
                break
            by_id = {str(w["id"]): w for w in manual_workflows(svc.doc)}
            pending = [p for p in pending if p in by_id]
            bench = bench_factory(output_dir)
            failing: list[tuple[dict, dict, str]] = []
            try:
                app = bench.app()
                # WHAT MAKES RECORDS RUNS FIRST, WHAT REMOVES THEM LAST. F&B's
                # seed put every dish in an order, so "Delete Food Item" was
                # refused — rightly — on every dish there was. A person tries a
                # delete on something they just added; so does this: creates,
                # then changes, then deletes, each phase given the records as
                # they now stand, newest first.
                # EACH ROUND IS A FRESH COPY: what round one created is gone. The
                # creates that already passed run again first, unjudged, so a
                # delete left for a later round has something new to delete.
                makes = (_phases([by_id[p] for p in by_id]) or [[]])[0]
                setup = [p for p in proven if p in makes and p not in pending]
                seeded: set[str] | None = None
                for group in _phases([by_id[p] for p in pending + setup]):
                    if not group:
                        continue
                    records = _records(app, svc.doc)
                    if seeded is None:
                        seeded = {r.get("id") for rows in records.values() for r in rows}
                    else:
                        records = _mark_new(records, seeded)
                    plan = compose_inputs(svc.doc, [by_id[p] for p in group], records, client, before=lessons)
                    # A PROCESS LEFT OUT IS ASKED FOR AGAIN, ON ITS OWN. Told its
                    # last run was rightly refused, the writer skipped F&B's
                    # Delete Food Item, which then ran with no input at all.
                    missing = [p for p in group if p not in plan]
                    if missing:
                        plan.update(compose_inputs(svc.doc, [by_id[p] for p in missing], records, client,
                                                   before=lessons))
                    for pid in group:
                        run = plan.get(pid) or {"as": "", "input": {}}
                        attach_files(bench, svc.doc, by_id[pid], run)
                        said = trials.run("try_workflow", {"workflow": pid, "input": run["input"], "as": run["as"]},
                                          bench=bench, doc=svc.doc)
                        if pid in setup:
                            continue
                        if not run_failed(said):
                            # RAN THROUGH IS HALF. The other half is what a
                            # person then sees: Add Child wrote every child
                            # and My Children showed none (`round_trips`).
                            unseen = read_back(bench, svc.doc, run["as"])
                            if unseen:
                                said += ("\n\nthen, looking for it as the person who ran it:\n"
                                         + "\n".join(f"  {u}" for u in unseen))
                        if run_failed(said) or "\nthen, looking for it as the person who ran it:" in said:
                            failing.append((by_id[pid], run, said))
                        else:
                            proven.append(pid)
                            (fixed if round_ > 1 and pid in changed else passed).append(str(by_id[pid].get("name") or pid))
                            ledger.node_subject("process_trials", pid, len(passed) + len(fixed), len(flows), True)
            except trials.TrialUnavailable as exc:
                logger.warning("[process-trials] the app could not be run: %s", exc)
                left = [{"workflow": p, "name": str(by_id[p].get("name") or p),
                         "reason": f"the app could not be started to run it: {exc}"} for p in pending]
                pending = []
                break
            finally:
                bench.close()
            if round_ > rounds:
                left = [{"workflow": str(f.get("id")), "name": str(f.get("name") or f.get("id")),
                         "reason": said.split("\n", 1)[0][:200] + " — " + said[-400:]} for f, _r, said in failing]
                break
            for flow, run, said in failing:
                ledger.repair("process_trials", str(flow.get("id")), round_, rounds, said[:600])
                say("message", {"text": f"{flow.get('name')} did not run through — fixing the cause and running it again."})
                found = ""
                try:
                    turn = run_turn("", output_dir, fault_ask(flow, run, said), max_steps=STEPS,
                                    unattended=True) or {}
                    found = str(turn.get("answer") or "")
                    if turn.get("edited_paths"):
                        changed.add(str(flow.get("id")))
                except Exception as exc:  # noqa: BLE001 — one repair never ends the build
                    logger.warning("[process-trials] %s: %s", flow.get("id"), exc)
                lessons[str(flow.get("id"))] = (f"input {json.dumps(run.get('input') or {}, default=str)[:400]} -> "
                                                f"{_why(said)}" + (f"; found: {found[:400]}" if found else ""))
                reload()
            pending = [str(f.get("id")) for f, _r, _s in failing]
        for item in left:
            ledger.unrepaired("process_trials", item["workflow"], item["reason"])

    runtime = dict(svc.doc.get("runtime") or {})
    issues = [i for i in runtime.get("issues") or [] if not (isinstance(i, dict) and i.get("kind") == "process")]
    issues += [{"kind": "process", "workflow": t["workflow"], "name": t["name"], "detail": t["reason"][:600]}
               for t in left]
    runtime["issues"] = issues
    svc.doc["runtime"] = runtime
    svc.save()
    return {"passed": passed, "fixed": fixed, "left": left}
