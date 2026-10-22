"""Business rules and workflows, linked.

A record's rules are checked by the app on every save of that record — and a
workflow saves records with its `db_insert` / `db_update` / `db_upsert`
steps, which run the record's rules over the row being written (with the row
as it was, on an update: ``templates/runtime/workflows/index.ts``). So the
link between a rule and a workflow is not something a person has to draw:

* **links** — every workflow step that saves a rule's record, on the kind of
  save the rule is for (a rule "when an expense is created" is not checked by
  a workflow that only changes one). Worked out from the Blueprint each time it
  is read, so it can never fall behind a change to either side.

* **copies** — the build used to write a rule a second time into a workflow:
  a yes/no step with the rule's condition and a stop with the rule's message
  (``check_amount: amount > 0`` beside the rule "amount must be more than
  zero"). The copy is not the rule: change the rule and the workflow still
  checks the old one. A copy is found by asking the app's own engine about
  many sample saves: when the step and the rule agree on every one of them,
  the step is the rule, and it is taken out (``fold``) — the save step after
  it checks the rule itself, as it is now. A step that names the same fields
  but no longer agrees (the rule was edited after the build) is reported, so
  the person can choose the rule.

Nothing here evaluates a rule in Python: the questions go to the rule lab,
the engine every app ships (`services/blueprint/rule_lab.py`).
"""
from __future__ import annotations

import itertools
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_RETIRED = {"DEPRECATED", "REMOVED", "SUPERSEDED", "RETIRED"}
#: Write steps and the save each one is, for a rule's `on`.
_WRITES = {"db_insert": ("create",), "db_update": ("update",), "db_upsert": ("create", "update")}
#: An action that makes a save fail when it applies.
_STOPPING = {"show_error", "set_required"}
#: The most sample saves one copy is judged on.
_MAX_CASES = 600


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") not in _RETIRED]


def _entities(doc: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}


def _camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _actions(rule: dict) -> list[dict]:
    return [a for a in list(rule.get("then") or []) + list(rule.get("otherwise") or []) if isinstance(a, dict)]


def _stops(a: dict) -> bool:
    """An action that makes a save fail when it applies: a message, or a field
    it requires (`required: false` lifts a requirement instead)."""
    return a.get("type") == "show_error" or (a.get("type") == "set_required" and a.get("required") is not False)


def can_stop(rule: dict) -> bool:
    """Does this rule ever stop a save (a message, or a field it requires)?"""
    return rule.get("kind") == "condition_action" and any(_stops(a) for a in _actions(rule))


def rule_events(rule: dict) -> tuple[str, ...]:
    """The saves a rule acts on: its `on` when it says; otherwise what it can
    act on — a rule about the record as it was ("a rejected expense cannot
    become approved") only on a change, a rule that only fills in a value
    left empty only on a new record (an existing record already has it)."""
    on = rule.get("on")
    if isinstance(on, str):
        on = [on]
    if isinstance(on, list) and on:
        evs = tuple(e for e in ("create", "update") if any(str(x).startswith(e[:6]) for x in on))
        if evs:
            return evs
    if rule.get("kind") == "condition_action":
        if any(r.startswith("previous.") for r in _refs(_when(rule))):
            return ("update",)
        acts = _actions(rule)
        if acts and all(a.get("type") == "set_default" for a in acts):
            return ("create",)
    return ("create", "update")


def reads(rule: dict) -> set[str]:
    """The record's fields a rule looks at or acts on."""
    out = set(_rule_fields(rule))
    for a in _actions(rule):
        if a.get("field"):
            out.add(str(a["field"]))
    if rule.get("kind") == "decision_table":
        table = rule.get("table") or rule.get("decisionTable") or {}
        for col in list(table.get("inputs") or []) + list(table.get("outputs") or []):
            if isinstance(col, dict):
                name = col.get("field") or col.get("name") or col.get("expression")
                if name:
                    out.add(str(name).split(".")[-1])
    return out


def _step_table(step: dict, ent_by_id: dict[str, dict]) -> str:
    cfg = step.get("config") or {}
    table = str(cfg.get("table") or "").lower()
    if table:
        return table
    ent = ent_by_id.get(str(step.get("entity") or "")) or {}
    return str(ent.get("table") or "").lower()


def _entity_of_table(table: str, ents: dict[str, dict]) -> dict | None:
    for e in ents.values():
        names = {str(e.get("table") or "").lower(), _snake(str(e.get("name") or "")),
                 _snake(str(e.get("name") or "")) + "s"}
        if table and table in names:
            return e
    return None


def save_steps(flow: dict, ent: dict, ents: dict[str, dict]) -> list[dict]:
    """The steps of a workflow that save this record, with the saves they are."""
    out = []
    table = str(ent.get("table") or "").lower()
    for st in flow.get("steps") or []:
        if not isinstance(st, dict):
            continue
        events = _WRITES.get(str((st.get("config") or {}).get("actionType") or ""))
        if not events:
            continue
        t = _step_table(st, ents)
        if (t and table and t == table) or (not t and str(st.get("entity") or "") == str(ent.get("id"))):
            values = (st.get("config") or {}).get("values")
            out.append({"step": st.get("key"), "stepName": st.get("name") or st.get("key"), "events": events,
                        "writes": sorted(values) if isinstance(values, dict) else None})
    return out


def links(doc: dict, rule: dict) -> list[dict]:
    """Every workflow step that checks this rule because it saves the rule's
    record on a save the rule is for. Off rules and written-only rules are
    checked nowhere."""
    if rule.get("enabled") is False or rule.get("kind") not in ("condition_action", "decision_table"):
        return []
    ents = _entities(doc)
    ent = ents.get(str(rule.get("entity") or ""))
    if not ent:
        return []
    want = rule_events(rule)
    fields = reads(rule)
    out = []
    for w in _live(doc.get("workflows")):
        for s in save_steps(w, ent, ents):
            evs = [e for e in s["events"] if e in want]
            if evs:
                # Does this save change what the rule looks at? A new record
                # always does; a change does when it writes one of its fields
                # (or writes fields we cannot name). Otherwise the rule is
                # still checked there — over the record as it is.
                touches = evs[0] == "create" or s["writes"] is None or bool(fields & set(s["writes"]))
                out.append({"workflow": str(w.get("id")), "name": str(w.get("name") or w.get("id")),
                            "step": s["step"], "stepName": s["stepName"], "event": evs[0],
                            "touches": touches})
    return out


def workflow_links(doc: dict) -> dict[str, dict[str, list[dict]]]:
    """For the workflow screens: ``{workflow id: {step key: [{rule, name}]}}``
    — the rules each save step checks."""
    out: dict[str, dict[str, list[dict]]] = {}
    for rule in _live(doc.get("businessRules")):
        for ln in links(doc, rule):
            out.setdefault(ln["workflow"], {}).setdefault(str(ln["step"]), []).append(
                {"rule": str(rule.get("id")), "name": str(rule.get("name") or rule.get("id"))})
    return out


# ---------------------------------------------------------------------------
# Copies of a rule inside a workflow
# ---------------------------------------------------------------------------

_IDENT = re.compile(r"(?<![\w.\"'])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)(?![\w(])")
_KEYWORDS = {"and", "or", "not", "in", "null", "true", "false", "between", "instance", "of", "if", "then",
             "else", "some", "every", "satisfies", "for", "return", "date", "time", "now", "today", "user"}
_TEMPLATE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")


def _strip_strings(expr: str) -> str:
    return re.sub(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", '""', expr)


def _refs(expr: str) -> set[str]:
    return {m for m in _IDENT.findall(_strip_strings(expr or "")) if m.split(".")[0] not in _KEYWORDS}


def _literals(expr: str) -> tuple[list[float], list[str]]:
    nums = [float(n) for n in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", _strip_strings(expr or ""))]
    strs = re.findall(r"\"((?:[^\"\\]|\\.)*)\"", expr or "")
    return nums, strs


def _when(rule: dict) -> str:
    return str(rule.get("when") or "true")


def _rule_fields(rule: dict) -> set[str]:
    out = set()
    for r in _refs(_when(rule)):
        out.add(r.split(".", 1)[1] if r.startswith("previous.") else r.split(".")[0])
    for a in _actions(rule):
        if _stops(a) and a.get("type") == "set_required" and a.get("field"):
            out.add(str(a["field"]))
    return out


def _end_refused(step: dict | None) -> bool:
    return bool(step) and step.get("type") in ("end", "end_event") and (step.get("config") or {}).get("refused") is True


def _first_save_after(flow: dict, start: str, ent: dict, ents: dict) -> dict | None:
    """The first step that saves the record on the way on from `start`,
    through other yes/no checks (their way on is the side that does not stop)."""
    by_key = {s.get("key"): s for s in flow.get("steps") or [] if isinstance(s, dict)}
    saves = {s["step"]: s for s in save_steps(flow, ent, ents)}
    seen, key = set(), start
    while key and key not in seen:
        seen.add(key)
        if key in saves:
            return {**saves[key], "config": (by_key[key].get("config") or {})}
        st = by_key.get(key)
        if not st:
            return None
        nxt = [n for n in (st.get("next") or []) if n]
        on = [n for n in nxt if not _end_refused(by_key.get(n))]
        key = on[0] if on else None
    return None


def candidates(doc: dict, rule: dict) -> list[dict]:
    """The workflow steps that look like a copy of this rule: a yes/no step on
    the rule's fields, one side of it stopping the workflow with a message,
    the other side going on to save the rule's record."""
    if not can_stop(rule) or rule.get("enabled") is False:
        return []
    ents = _entities(doc)
    ent = ents.get(str(rule.get("entity") or ""))
    if not ent:
        return []
    fields = _rule_fields(rule)
    camel, snake = _camel(str(ent.get("name") or "")), _snake(str(ent.get("name") or ""))
    out = []
    for w in _live(doc.get("workflows")):
        by_key = {s.get("key"): s for s in w.get("steps") or [] if isinstance(s, dict)}
        for st in w.get("steps") or []:
            if not isinstance(st, dict) or st.get("type") not in ("condition", "exclusive_gateway"):
                continue
            nxt = list(st.get("next") or [])
            if len(nxt) != 2:
                continue
            stops = [i for i, n in enumerate(nxt) if _end_refused(by_key.get(n))]
            if len(stops) != 1:
                continue
            expr = str((st.get("config") or {}).get("expression") or "")
            names = {r.split(".", 1)[1] if r.split(".")[0] in (camel, snake) else r.split(".")[0] for r in _refs(expr)}
            if not names or not (names & fields):
                continue
            go_on = nxt[1 - stops[0]]
            save = _first_save_after(w, go_on, ent, ents)
            if not save:
                continue
            evs = [e for e in save["events"] if e in rule_events(rule)]
            if not evs:
                continue
            out.append({"workflow": str(w.get("id")), "name": str(w.get("name") or w.get("id")),
                        "step": st.get("key"), "stepName": st.get("name") or st.get("key"),
                        "stop": nxt[stops[0]], "goOn": go_on, "goOnIsYes": stops[0] == 1,
                        "expression": expr, "save": save, "event": evs[0]})
    return out


def _values_for(field: dict | None, nums: list[float], strs: list[str]) -> list[Any]:
    """Sample values for a field: its choices, or numbers around every number
    the two conditions name, or texts they name — and blank, unless the field
    is required (a required field left blank is never saved, whatever the
    rules say, so a check and a rule may differ there and still be one)."""
    from services.business_rules import _enum_values, _field_type
    vals = _sample_values(field, nums, strs)
    if field and field.get("required") is True:
        vals = [v for v in vals if v is not None and v != ""] or vals
    return vals


def _sample_values(field: dict | None, nums: list[float], strs: list[str]) -> list[Any]:
    from services.business_rules import _enum_values, _field_type
    t = _field_type(field) if field else ""
    if t == "enum":
        return list(dict.fromkeys(_enum_values(field) + strs + ["zz-other", None]))
    if t == "number" or (not field and nums and not strs):
        base = {0.0, -1.0, 1.0, 100000.0}
        for n in nums:
            base |= {n - 1, n, n + 1, n - 0.5, n + 0.5}
        return sorted(base) + [None]
    if t == "boolean":
        return [True, False, None]
    return list(dict.fromkeys(strs + ["", "some text", None]))


def _cases(dims: list[tuple[str, list[Any]]]) -> list[dict]:
    sizes = [len(v) for _, v in dims]
    total = 1
    for s in sizes:
        total *= s
    if total <= _MAX_CASES:
        combos = itertools.product(*[v for _, v in dims])
    else:
        # Every value of every field, each beside every value of each other
        # field (pairs), plus a fixed sweep: enough to tell two simple
        # conditions apart, small enough to run in one go.
        combos_set = []
        for i, (_, vi) in enumerate(dims):
            for j in range(i + 1, len(dims)):
                for a in vi:
                    for b in dims[j][1]:
                        row = [d[1][0] for d in dims]
                        row[i], row[j] = a, b
                        combos_set.append(tuple(row))
        combos = combos_set[:_MAX_CASES]
    return [dict(zip([k for k, _ in dims], c)) for c in combos]


_LITERAL = re.compile(r"""^(?:"([^"]*)"|'([^']*)'|(-?\d+(?:\.\d+)?)|(true|false|null))$""")


def _fill(value: Any, vars_: dict) -> Any:
    """A save step's value as the app fills it: `{{path}}`, and `{{a ?? b}}`
    — the first side that holds something (empty text counts as nothing),
    each side a path or a literal (workflows/engine.ts interpolateValue)."""
    if not isinstance(value, str) or "{{" not in value:
        return value
    m = re.match(r"^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$", value)
    if not m:
        return value

    def read(path: str) -> Any:
        cur: Any = vars_
        for part in path.strip().split("."):
            if cur is None:
                return None
            if part == "id" and isinstance(cur, (str, int, float)):
                return cur
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    def term(t: str) -> Any:
        lit = _LITERAL.match(t.strip())
        if not lit:
            return read(t)
        if lit.group(1) is not None:
            return lit.group(1)
        if lit.group(2) is not None:
            return lit.group(2)
        if lit.group(3) is not None:
            return float(lit.group(3))
        return {"true": True, "false": False}.get(lit.group(4))

    expr = m.group(1)
    if "??" not in expr:
        return read(expr)
    for side in expr.split("??"):
        v = term(side)
        if v not in (None, ""):
            return v
    return None


_JUDGED: dict[str, dict] = {}
_JUDGED_MAX = 2000


def _plan(doc: dict, rule: dict, c: dict) -> tuple[list[dict], list[dict], list[dict]] | None:
    """The sample saves one candidate is judged on: ``(cases, conditions, saves)``."""
    from services.blueprint.projection import business_rule_rows
    ents = _entities(doc)
    ent = ents.get(str(rule.get("entity") or "")) or {}
    fields = {str(f.get("name")): f for f in ent.get("fields") or [] if isinstance(f, dict)}
    camel = _camel(str(ent.get("name") or ""))
    rows = [r for r in business_rule_rows({**doc, "businessRules": [rule]})
            if str(r.get("id")) == str(rule.get("id"))]
    if not rows:
        return None
    expr, save = c["expression"], c["save"]
    values = dict((save.get("config") or {}).get("values") or {})
    nums, strs = _literals(expr + " " + _when(rule))
    # The fields that vary: what the step reads (as itself or on the loaded
    # record) and what the rule reads (on the record being saved, and on the
    # record as it was).
    flat, prev = set(), set()
    for r in _refs(expr):
        head, _, tail = r.partition(".")
        (prev if head == camel and tail else flat).add(tail if head == camel and tail else head)
    for r in _refs(_when(rule)):
        if r.startswith("previous."):
            prev.add(r.split(".", 1)[1])
        else:
            flat.add(r.split(".")[0])
    for a in _actions(rule):
        if _stops(a) and a.get("type") == "set_required" and a.get("field"):
            flat.add(str(a["field"]))
    # A field the save writes from a variable is that variable; one it writes
    # as a fixed value is fixed; one it does not write is the record's own (on
    # an update) or missing (on a create).
    for v in values.values():
        m = re.match(r"^\s*\{\{\s*([A-Za-z_]\w*)", v) if isinstance(v, str) else None
        if m:
            flat.add(m.group(1))
    if c["event"] == "update":
        prev |= {f for f in flat if f not in values}
    dims = [(f"in:{f}", _values_for(fields.get(f), nums, strs)) for f in sorted(flat)]
    dims += [(f"was:{f}", _values_for(fields.get(f), nums, strs)) for f in sorted(prev)]
    cases = _cases(dims)
    conditions, saves = [], []
    for case in cases:
        inputs = {k[3:]: v for k, v in case.items() if k.startswith("in:")}
        was = {"id": "rec-1", **{k[4:]: v for k, v in case.items() if k.startswith("was:")}}
        vars_ = {**inputs, camel: was}
        conditions.append({"expression": expr, "vars": vars_})
        written = {k: _fill(v, vars_) for k, v in values.items()}
        if c["event"] == "update":
            record, previous = {**was, **written}, was
        else:
            record, previous = written, None
        saves.append({"model": str(ent.get("name")), "rules": rows, "record": record,
                      "event": c["event"], "previous": previous})
    return cases, conditions, saves


def _key(rule: dict, c: dict) -> str:
    return json.dumps([rule.get("when"), rule.get("then"), rule.get("otherwise"), rule.get("entity"),
                       c["expression"], c["goOnIsYes"], c["event"], c["save"].get("config", {}).get("values")],
                      sort_keys=True, default=str)


def judge_all(doc: dict, pairs: list[tuple[dict, dict]]) -> list[dict]:
    """Each (rule, candidate) judged, with ``same``: does the workflow's step
    say "go on" exactly when the rule lets the save through, on every sample
    save? One run of the app's engine for all of them; ``same`` is None when
    it cannot run. Answers are remembered: the same rule and step are the
    same question."""
    from services.blueprint import rule_lab
    out: list[dict | None] = [None] * len(pairs)
    todo, conditions, saves = [], [], []
    for i, (rule, c) in enumerate(pairs):
        k = _key(rule, c)
        if k in _JUDGED:
            out[i] = {**c, **_JUDGED[k], "rule": str(rule.get("id"))}
            continue
        plan = _plan(doc, rule, c)
        if plan is None:
            out[i] = {**c, "same": None, "rule": str(rule.get("id"))}
            continue
        cases, cs, ss = plan
        todo.append((i, k, cases, len(conditions), len(cs)))
        conditions += cs
        saves += ss
    if todo:
        try:
            ans = rule_lab.run({"op": "batch", "conditions": conditions, "saves": saves}, timeout=90)
        except rule_lab.LabUnavailable as exc:
            logger.warning("[rule-links] could not compare workflow checks with rules: %s", exc)
            ans = None
        for i, k, cases, at, n in todo:
            rule, c = pairs[i]
            if ans is None:
                out[i] = {**c, "same": None, "rule": str(rule.get("id"))}
                continue
            cv = (ans.get("conditions") or [])[at:at + n]
            sv = (ans.get("saves") or [])[at:at + n]
            same, differs = len(cv) == n == len(sv), None
            for case, a, b in zip(cases, cv, sv):
                if "error" in a or "error" in b:
                    same, differs = False, case
                    break
                goes_on = a["value"] if c["goOnIsYes"] else not a["value"]
                if goes_on == bool(b["refused"]):
                    same, differs = False, case
                    break
            verdict = {"same": same, "cases": n,
                       **({"differs": {kk.split(":", 1)[1] + (" (before)" if kk.startswith("was:") else ""): v
                                       for kk, v in differs.items()}} if differs else {})}
            if len(_JUDGED) > _JUDGED_MAX:
                _JUDGED.clear()
            _JUDGED[k] = verdict
            out[i] = {**c, **verdict, "rule": str(rule.get("id"))}
    return [o for o in out if o is not None]


def judge(doc: dict, rule: dict, cands: list[dict]) -> list[dict]:
    """The candidates of one rule, judged (see `judge_all`)."""
    return judge_all(doc, [(rule, c) for c in cands])


def fold(flow: dict, cand: dict) -> bool:
    """Take a copy out of a workflow: what led to it now leads where its
    yes-path went, and its stop goes too when nothing else leads there."""
    steps = flow.get("steps") or []
    key, stop = cand["step"], cand["stop"]
    step = next((s for s in steps if isinstance(s, dict) and s.get("key") == key), None)
    if step is None:
        return False
    # Where it goes on NOW: an earlier fold may have changed what it leads to.
    nxt = list(step.get("next") or [])
    if len(nxt) != 2 or stop not in nxt:
        return False
    go_on = nxt[1 - nxt.index(stop)]
    led = False
    for s in steps:
        if isinstance(s, dict) and s is not step and key in (s.get("next") or []):
            s["next"] = [go_on if n == key else n for n in s["next"]]
            led = True
    first_real = next((s for s in steps if isinstance(s, dict) and s.get("type") not in ("start", "trigger")), None)
    remaining = [s for s in steps if s is not step]
    if not led and first_real is step:
        # It was where the workflow began: what came after it begins it now.
        nxt = next((s for s in remaining if isinstance(s, dict) and s.get("key") == go_on), None)
        if nxt is not None:
            remaining.remove(nxt)
            at = next((i for i, s in enumerate(remaining)
                       if isinstance(s, dict) and s.get("type") not in ("start", "trigger")), len(remaining))
            remaining.insert(at, nxt)
    still = any(isinstance(s, dict) and stop in (s.get("next") or []) for s in remaining)
    if not still:
        remaining = [s for s in remaining if not (isinstance(s, dict) and s.get("key") == stop)]
    flow["steps"] = remaining
    return True


def review(doc: dict, rule: dict) -> list[dict]:
    """The copies of this rule in workflows, judged."""
    return judge(doc, rule, candidates(doc, rule))


def review_all(doc: dict, rule_ids: set[str] | None = None) -> list[dict]:
    """Every rule's candidate copies, judged in one go."""
    pairs = [(r, c) for r in _live(doc.get("businessRules"))
             if rule_ids is None or str(r.get("id")) in rule_ids
             for c in candidates(doc, r)]
    return judge_all(doc, pairs) if pairs else []


def has_candidates(doc: dict) -> bool:
    """Cheap: is there anything that might be a copy? (No engine run.)"""
    return any(candidates(doc, r) for r in _live(doc.get("businessRules")))


def fold_copies(doc: dict, *, rule_ids: set[str] | None = None, only_same: bool = True,
                judged: list[dict] | None = None) -> list[dict]:
    """Take every proven copy of a rule out of its workflow (in place). The
    list of what was taken out, for the change record."""
    names = {str(r.get("id")): r.get("name") for r in _live(doc.get("businessRules"))}
    done: list[dict] = []
    for c in (judged if judged is not None else review_all(doc, rule_ids)):
        if only_same and c.get("same") is not True:
            continue
        if rule_ids is not None and c["rule"] not in rule_ids:
            continue
        flow = next((w for w in _live(doc.get("workflows")) if str(w.get("id")) == c["workflow"]), None)
        if flow is not None and fold(flow, c):
            done.append({"rule": c["rule"], "ruleName": names.get(c["rule"]),
                         "workflow": c["workflow"], "name": c["name"], "step": c["step"]})
    return done


__all__ = ["can_stop", "candidates", "fold", "fold_copies", "has_candidates", "judge", "judge_all", "links",
           "reads", "review", "review_all", "rule_events", "save_steps", "workflow_links"]
