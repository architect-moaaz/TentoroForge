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
            "input": {"type": "object", "description": "Input name -> value, exactly as the process declares its inputs."},
        }}}},
}

INPUTS_SYSTEM = (
    "You write one realistic run for each process of a built application: the input a real "
    "person would give it, as the role that would run it. Use the field examples and allowed "
    "values you are shown; a record input or a reference to another record takes one of the "
    "real ids listed. Fill every required input with a value the process should accept; fill "
    "optional ones when a real person would. Leave out file and image inputs. Do not try to make "
    "a process refuse: the run proves it works."
)


def manual_workflows(doc: dict) -> list[dict]:
    """The live processes a person starts."""
    return [w for w in doc.get("workflows") or []
            if isinstance(w, dict) and w.get("id")
            and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")
            and str((w.get("trigger") or {}).get("kind") or "manual") == "manual"]


def _records(app: Any, doc: dict) -> dict[str, list[dict]]:
    """Up to five real rows per entity from the copy: id and label."""
    from services.blueprint.page_review import _query

    out: dict[str, list[dict]] = {}
    for e in ((doc.get("data") or {}).get("entities") or []):
        table, label = str(e.get("table") or ""), str(e.get("labelField") or "id")
        if not table or not table.replace("_", "").isalnum():
            continue
        col = "".join("_" + c.lower() if c.isupper() else c for c in label)
        try:
            rows = _query(app, f'select id::text, "{col}"::text from "{table}" limit 5')
        except Exception:  # noqa: BLE001 — a table the copy lacks has no rows to offer
            try:
                rows = [(r[0], "") for r in _query(app, f'select id::text from "{table}" limit 5')]
            except Exception:  # noqa: BLE001
                continue
        out[str(e.get("name"))] = [{"id": r[0], "label": r[1] if len(r) > 1 else ""} for r in rows or []]
    return out


def _brief(doc: dict, flows: list[dict], records: dict[str, list[dict]]) -> str:
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
        shown.append({"workflow": w.get("id"), "name": w.get("name"), "purpose": w.get("description") or "",
                      "inputs": inputs, "runBy": roles.get(str(w.get("id"))) or []})
    fields = {str(e.get("name")): [{k: f.get(k) for k in ("name", "type", "enumValues", "examples", "required")
                                   if f.get(k) not in (None, [], "")}
                                  for f in e.get("fields") or [] if isinstance(f, dict)]
              for e in entities.values()}
    rules = [{"name": r.get("name"), "statement": r.get("statement")}
             for r in doc.get("businessRules") or [] if isinstance(r, dict)]
    return json.dumps({"processes": shown, "entities": fields, "records": records, "rules": rules},
                      default=str)[:60000]


def compose_inputs(doc: dict, flows: list[dict], records: dict[str, list[dict]],
                   client: Any) -> dict[str, dict]:
    """{FLOW-id: {"as": role, "input": {...}}} — one call for every process."""
    text = client(system=INPUTS_SYSTEM, user=_brief(doc, flows, records), schema=INPUTS_SCHEMA)
    try:
        body = json.loads(text)
        body = body.get("result", body) if isinstance(body, dict) else body
    except (TypeError, ValueError):
        logger.warning("[process-trials] inputs reply was not JSON")
        return {}
    out: dict[str, dict] = {}
    for run in (body or {}).get("runs") or []:
        if isinstance(run, dict) and run.get("workflow"):
            out[str(run["workflow"])] = {"as": str(run.get("as") or ""),
                                         "input": run.get("input") if isinstance(run.get("input"), dict) else {}}
    return out


def run_failed(said: str) -> bool:
    """A trial that shows the process not working — and one that could not
    finish at all (the trial's own timeout or a crash), which `trials.failed`
    reads as a missing header rather than a failure."""
    from services.smith import trials
    return trials.failed(said) or said.startswith("`try_workflow` failed")


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


def prove_processes(svc: Any, output_dir: str, *,
                    emit: Callable[[str, dict], None] | None = None,
                    client: Any = None,
                    run_turn: Callable[..., dict] | None = None,
                    bench_factory: Callable[[str], Any] | None = None,
                    rounds: int = ROUNDS, record: bool = True) -> dict:
    """Run every process; repair what fails; returns {passed, fixed, left}."""
    from services.blueprint.page_repair import _ledger
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
    left: list[dict] = []
    pending = [str(w["id"]) for w in flows]
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
                plan = compose_inputs(svc.doc, [by_id[p] for p in pending], _records(app, svc.doc), client)
                for pid in pending:
                    run = plan.get(pid) or {"as": "", "input": {}}
                    said = trials.run("try_workflow", {"workflow": pid, "input": run["input"], "as": run["as"]},
                                      bench=bench, doc=svc.doc)
                    if run_failed(said):
                        failing.append((by_id[pid], run, said))
                    else:
                        (fixed if round_ > 1 else passed).append(str(by_id[pid].get("name") or pid))
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
                try:
                    run_turn("", output_dir, fault_ask(flow, run, said), max_steps=STEPS, unattended=True)
                except Exception as exc:  # noqa: BLE001 — one repair never ends the build
                    logger.warning("[process-trials] %s: %s", flow.get("id"), exc)
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
