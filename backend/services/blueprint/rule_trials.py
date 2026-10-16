"""Every rule refuses its refused case.

Process trials prove the accepting path: each process run once with an
input it should take. A rule is only proven the other way — "the stock cap
makes the refusal unreachable" was found by a tester, not the build (Ecom
L1, 2026-10-11). So for every rule that gates a process (a prerequisite's
`gates`, a rule applied to a workflow), one input is written that breaks
the rule — the rule's own statement and message, and the domain reference's
`refusedCase` when it names the rule — and the process is run with it as
the person it is for. Green only when the application refuses with its own
message (`process_trials.refused`); a run that is accepted, or that breaks
instead of refusing, is red. A rule gating no process cannot be tried this
way and is `untried`.

One low-effort model call for all the rules; one process run each.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

RULE_INPUTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["runs"],
    "properties": {"runs": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["rule", "workflow", "as", "input"],
        "properties": {
            "rule": {"type": "string", "description": "The rule id (RULE-…)."},
            "workflow": {"type": "string", "description": "The process id (FLOW-…) the rule gates."},
            "as": {"type": "string", "description": "The role that runs it, by name; \"signed out\" for a visitor."},
            "input": {"type": "array", "description": "One entry per input given, named as the process declares it.",
                      "items": {"type": "object", "additionalProperties": False, "required": ["name", "value"],
                                "properties": {"name": {"type": "string"},
                                               "value": {"type": "string", "description": "The value as JSON."}}}},
        }}}},
}

RULE_INPUTS_SYSTEM = (
    "For EVERY rule listed, write one run of the process it gates that the rule must REFUSE: the input a "
    "person would give that breaks exactly that rule and nothing else — more than is in stock, a date in "
    "the past, an amount over the limit, a record in the wrong state, a person who has not done what the "
    "rule requires. Every other input is valid and realistic, taken from the field examples and the real "
    "record ids listed. Run it as the person the rule applies to (one of the process's `runBy`); a rule "
    "about a customer is broken by a customer. When a `refusedCase` is given, use it. Never skip a rule."
)


def gated(doc: dict) -> list[tuple[dict, dict]]:
    """`(rule, workflow)` for every live rule that gates a live manual process."""
    from services.blueprint.process_trials import manual_workflows
    flows = {str(w.get("id")): w for w in manual_workflows(doc)}
    out: list[tuple[dict, dict]] = []
    for r in doc.get("businessRules") or []:
        if not isinstance(r, dict) or not r.get("id") \
                or str(r.get("status") or "").upper() in ("DEPRECATED", "REMOVED"):
            continue
        ids = [str(g) for g in r.get("gates") or []] + [str(a) for a in r.get("appliesTo") or []
                                                        if str(a).startswith("FLOW-")]
        for fid in dict.fromkeys(ids):
            if fid in flows:
                out.append((r, flows[fid]))
                break                                        # one process per rule is the trial
    return out


def ungated(doc: dict) -> list[dict]:
    """Live rules no process trial can reach."""
    tried = {str(r.get("id")) for r, _f in gated(doc)}
    return [r for r in doc.get("businessRules") or []
            if isinstance(r, dict) and r.get("id") and str(r["id"]) not in tried
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _refused_case(doc: dict, rule: dict) -> str:
    want = str(rule.get("name") or "").strip().lower()
    for ref in ((doc.get("domainReference") or {}).get("rules") or []):
        if isinstance(ref, dict) and str(ref.get("name") or "").strip().lower() == want and ref.get("refusedCase"):
            return str(ref["refusedCase"])
    return ""


def compose_breaking_inputs(doc: dict, pairs: list[tuple[dict, dict]], records: dict[str, list[dict]],
                            client: Any) -> dict[str, dict]:
    """`{RULE-id: {"workflow", "as", "input"}}` — one call for all rules."""
    from services.blueprint.process_trials import _brief, _pairs
    shown = [{"rule": r.get("id"), "name": r.get("name"), "statement": r.get("statement"),
              "message": r.get("message") or "", "workflow": f.get("id"),
              **({"refusedCase": _refused_case(doc, r)} if _refused_case(doc, r) else {})}
             for r, f in pairs]
    flows = list({str(f.get("id")): f for _r, f in pairs}.values())
    user = json.dumps({"rules": shown}, default=str) + "\n\nThe processes and records:\n" + _brief(doc, flows, records)
    try:
        reply = client(system=RULE_INPUTS_SYSTEM, user=user[:60000], schema=RULE_INPUTS_SCHEMA)
        body = json.loads(getattr(reply, "text", reply))
        body = body.get("result", body) if isinstance(body, dict) else body
    except Exception:  # noqa: BLE001
        logger.warning("[rule-trials] no breaking inputs were written", exc_info=True)
        return {}
    out: dict[str, dict] = {}
    for run in (body or {}).get("runs") or []:
        if isinstance(run, dict) and run.get("rule"):
            out[str(run["rule"])] = {"workflow": str(run.get("workflow") or ""), "as": str(run.get("as") or ""),
                                     "input": _pairs(run.get("input"))}
    return out


def refuse_rules(doc: dict, bench: Any, client: Any, *, only: set[str] | None = None,
                 records: dict[str, list[dict]] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` over the live rules."""
    from services.blueprint.process_trials import _records, _why, refused, run_failed
    from services.smith import trials

    pairs = [(r, f) for r, f in gated(doc) if only is None or str(r.get("id")) in only]
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    # A RULE NO PROCESS CARRIES IS NOTHING A TRIAL CAN JUDGE. It used to be
    # counted as "untried", so a calculator with seven rules and no process
    # read "0 of 7 hold, 7 I couldn't try — my own check failed" (Mark 8,
    # 2026-10-16). It is skipped, with the reason, outside the total.
    skipped: list[dict] = [item(str(r["id"]), str(r.get("name") or r["id"]),
                                "gates no process a trial can run", str(r["id"]))
                           for r in ungated(doc) if only is None or str(r.get("id")) in only]
    if not pairs:
        return {"total": 0, "green": green, "red": red, "untried": untried, "skipped": skipped}
    try:
        app = bench.app()
        if records is None:
            records = _records(app, doc)
    except trials.TrialUnavailable as exc:
        untried += [item(str(r["id"]), str(r.get("name") or r["id"]),
                         f"the app could not be started to try it: {exc}", str(r["id"])) for r, _f in pairs]
        return {"total": len(untried), "green": green, "red": red, "untried": untried, "skipped": skipped}
    plans = compose_breaking_inputs(doc, pairs, records, client)
    for rule, flow in pairs:
        rid, label = str(rule["id"]), str(rule.get("name") or rule["id"])
        it = lambda why: item(rid, label, why, rid)  # noqa: E731
        if cancelled():
            untried.append(it("stopped by the person"))
            continue
        plan = plans.get(rid)
        if not plan:
            untried.append(it("no input that breaks it could be written"))
            continue
        said = trials.run("try_workflow", {"workflow": plan.get("workflow") or str(flow.get("id")),
                                           "input": plan.get("input") or {}, "as": plan.get("as") or ""},
                          bench=bench, doc=doc)
        if refused(said):
            green.append(it(f"{flow.get('name')} refuses it: {_why(said)[:160]}"))
        elif run_failed(said):
            red.append(it(f"{flow.get('name')} breaks instead of refusing ({_why(said)[:160]})"))
        else:
            red.append(it(f"{flow.get('name')} accepts what the rule says to refuse "
                          f"({json.dumps(plan.get('input') or {}, default=str)[:160]})"))
    return {"total": len(pairs), "green": green, "red": red, "untried": untried, "skipped": skipped}


__all__ = ["RULE_INPUTS_SCHEMA", "RULE_INPUTS_SYSTEM", "compose_breaking_inputs", "gated", "refuse_rules", "ungated"]
