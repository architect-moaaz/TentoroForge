"""Business rules: one record of them, in the Living Blueprint.

Before this, a rule lived in one of two places that never met. Generation and
Smith wrote the Blueprint's ``businessRules``; the Business Rules tab wrote the
``project_rules`` table. The tab showed none of the Blueprint's rules, Smith saw
none of the tab's, and on a Blueprint-built app the tab's rules never reached
the running app (found on a task board Kimi built, 2026-10-14: five rules in the
definition, "No business rules yet" in the tab).

Now the Blueprint is the only record. The tab reads and writes it here —
deterministically, through the checks the build runs on a rule, versioned in
``changeHistory`` so Smith reads who changed what — and every write is projected
into the running app at once (``project_business_rules``). Smith reads the same
section on every turn, and a rule it adds appears in the tab when the tab next
reads. A rule says where it came from (``origin``) and whether it is on
(``enabled``).

Nothing here calls a model: saving a rule costs nothing and cannot be
reinterpreted.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX only; where it is missing (Windows) writers in ONE process are serialised by a per-app thread lock
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

#: The Windows fallback (no fcntl): one lock PER APP, not one for the whole process, so a write to one app's rules does
#: not block a write to another's — and two writers of the SAME app are still serialised. This serialises only within a
#: process; without fcntl there is no cross-process lock, so run one worker on Windows (it is a development platform here).
_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _process_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = _PROCESS_LOCKS[key] = threading.Lock()
        return lock

logger = logging.getLogger(__name__)

#: Kinds of rule the tab can make and edit. `prerequisite` rules are shown and
#: can be switched off or removed; they are written by the build and by Smith.
EDITABLE_KINDS = ("statement", "condition_action", "decision_table")
KINDS = EDITABLE_KINDS + ("prerequisite",)
ORIGINS = ("brief", "smith", "editor", "generated")
SCOPES = ("entity", "form", "server")
ACTION_TYPES = (
    "set_field", "set_default", "clear_field", "show_error", "set_visibility",
    "set_required", "set_readonly", "set_options", "recommendation",
    "trigger_workflow", "send_notification",
)
#: Actions that refuse a save or change data — what makes a rule run on every
#: save, not only on the form (the engine's `effectiveScope` says the same).
DATA_ACTIONS = frozenset({"show_error", "set_field", "set_default", "clear_field",
                          "set_required", "trigger_workflow", "send_notification"})
_RETIRED = ("DEPRECATED", "SUPERSEDED", "REJECTED")
_ACTION_KEYS = ("type", "field", "valueMode", "value", "message", "visible", "required",
                "readonly", "options", "workflow")
#: Words of the condition language that are not field names.
_FEEL_WORDS = frozenset({
    "and", "or", "not", "in", "null", "true", "false", "between", "instance", "of",
    "if", "then", "else", "for", "return", "some", "every", "satisfies", "function",
    "user", "previous", "today", "now", "date", "time", "duration",
})


class RuleError(ValueError):
    """A rule that cannot be saved as it stands — the message says why, in
    words the person can act on. ``status`` is the HTTP answer."""

    def __init__(self, message: str, *, status: int = 400, problems: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.problems = problems or [message]


# ---------------------------------------------------------------------------
# Where the definition is, and one writer at a time
# ---------------------------------------------------------------------------

def has_definition(output_dir: str | Path) -> bool:
    return (Path(output_dir) / ".forge" / "blueprint" / "current.json").is_file()


@contextlib.contextmanager
def write_lock(output_dir: str | Path, *, timeout: float | None = None) -> Iterator[None]:
    """ONE WRITER OF THE RULES AT A TIME, across workers and threads.

    The tab and Smith each load the document, change it and save it; two of
    those interleaved lose one change. An advisory lock on a file beside the
    Blueprint serialises them. Smith's rule changes hold it for their whole
    turn (an agent call); the tab waits at most `timeout` seconds and is then
    told Smith is changing the rules, rather than hanging the request."""
    import time
    path = Path(output_dir) / ".forge" / "blueprint" / ".rules.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        lock = _process_lock(path)
        if not lock.acquire(timeout=-1 if timeout is None else timeout):
            raise RuleError("Smith is changing this app's rules right now. Try again in a moment.", status=423)
        try:
            yield
        finally:
            lock.release()
        return
    with open(path, "a+") as fh:
        if timeout is None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuleError("Smith is changing this app's rules right now. Try again in a moment.",
                                        status=423) from None
                    time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

#: How long a tab write waits for Smith to finish changing the rules.
TAB_LOCK_WAIT = 20.0


#: The runs after a build that check the app it handed over (`fix_to_green`).
_CHECK_RUNS = ("-checks", "-app-check", "-process-trials")


def busy(output_dir: str | Path) -> str | None:
    """What is changing this app right now, or None.

    Each of these loaded the definition when it began and saves the whole of
    it when it ends, so a rule saved in between would be lost without a word:
    "building" (a build), "checking" (the checks after a build — they record
    each result and send what is red to Smith, unattended), "smith" (a Smith
    turn). A run whose ledger has gone quiet is not running (`ledger_snapshot`
    — a laptop switched off mid-build does not lock the tab for good)."""
    try:
        from services import run_registry
        snap = run_registry.ledger_snapshot(output_dir, turns=False)
        if snap and snap.get("active"):
            run_id = str(snap.get("runId") or "")
            return "checking" if snap.get("phase") == "checking" or run_id.endswith(_CHECK_RUNS) else "building"
        snap = run_registry.ledger_snapshot(output_dir, turns=True)
        if snap and snap.get("active"):
            return "smith"
    except Exception:  # noqa: BLE001 — not knowing is not "busy"
        return None
    return None


#: What the tab says while it cannot save, in the person's words.
BUSY_SAID = {
    "building": "Forge is building this app right now. Rules can be changed as soon as the build finishes — "
                "the build would otherwise overwrite your change.",
    "checking": "Forge is checking the app it just built and fixing what it finds. Rules can be changed as soon "
                "as that finishes — it would otherwise overwrite your change.",
    "smith": "Smith is working on this app right now. Your change can be saved as soon as Smith finishes — "
             "Smith would otherwise overwrite it.",
}


def building(output_dir: str | Path) -> bool:
    """A build, or the checks after it, is writing this definition now."""
    return busy(output_dir) in ("building", "checking")


def _refuse_if_building(output_dir: str | Path) -> None:
    """Checked again once the write lock is held. A build and the checks after
    it rewrite the whole definition WITHOUT taking this lock, so one that began
    in the gap between `_guard_writable` and the lock would otherwise clobber a
    tab write that holds the lock. (A Smith turn cannot be here: it holds the
    same lock, so we would not have acquired it.)"""
    why = busy(output_dir)
    if why in ("building", "checking"):
        raise RuleError(BUSY_SAID[why], status=423)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") not in _RETIRED]


#: The fields the platform maintains on a rule, not the person editing it in
#: the tab: a sync, a catch-up or an adoption rewrites `origin`, `appliesTo`,
#: `syncNote` and `status` while the person's own wording is untouched. They
#: are left out of the revision so that routine churn does not make a tab edit
#: of an otherwise-unchanged rule collide with itself (a spurious 409). A rule
#: retired out from under the tab is caught separately, by `_find` (404).
_REVISION_IGNORES = frozenset({"origin", "appliesTo", "syncNote", "status"})


def revision(rule: dict) -> str:
    """What the rule looks like now, as a short hash — the tab sends it back
    with an edit, and an edit of a rule that has changed since is refused. Only
    the person-editable content is hashed; the platform-maintained fields
    (`_REVISION_IGNORES`) are left out."""
    body = {k: v for k, v in rule.items() if k not in _REVISION_IGNORES}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _entities(doc: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}


def _field_type(f: dict) -> str:
    t = str(f.get("type") or "string").lower()
    if f.get("enumValues") or t == "enum":
        return "enum"
    if t in ("int", "integer", "number", "decimal", "float", "double", "money", "currency", "bigint", "numeric"):
        return "number"
    if t in ("bool", "boolean"):
        return "boolean"
    if t in ("date", "datetime", "timestamp", "time"):
        return "date"
    return "string"


def _enum_values(f: dict) -> list:
    """An enum field's choices, whichever way the definition spells them."""
    vals = f.get("enumValues") or f.get("values") or f.get("options") or []
    return [v.get("value") if isinstance(v, dict) else v for v in vals if v not in (None, "")]


def catalogue(doc: dict) -> dict:
    """What a rule can name: the records with their fields (type, choices),
    the workflows it can start, the requirements it can cite."""
    entities = []
    for e in _live((doc.get("data") or {}).get("entities")):
        entities.append({
            "id": e.get("id"), "name": e.get("name"), "table": e.get("table"),
            "fields": [{"name": f.get("name"), "type": _field_type(f),
                        "enumValues": [str(v) for v in _enum_values(f)],
                        "required": bool(f.get("required"))}
                       for f in e.get("fields") or [] if isinstance(f, dict) and f.get("name")],
        })
    return {
        "entities": entities,
        # With their steps, so a rule can be placed after one of them.
        "workflows": [{"id": w.get("id"), "name": w.get("name"),
                       "steps": [{"key": st.get("key"), "name": st.get("name") or st.get("key"),
                                  "type": st.get("type")}
                                 for st in w.get("steps") or [] if isinstance(st, dict) and st.get("key")]}
                      for w in _live(doc.get("workflows"))],
        "requirements": [{"id": r.get("id"), "description": r.get("description")}
                         for r in _live(doc.get("requirements"))],
    }


def where_it_runs(rule: dict) -> str:
    """In the person's terms: `everywhere` (every save and live on the form),
    `form` (how the form looks only), `save` (every save, not the form),
    `before` (checked before the workflows it gates), `nowhere` (written
    down — nothing enforces it — or switched off).

    This is the LABEL for what the running app actually does, so the
    condition→action decision here (``scope == "server"`` → save; any
    `DATA_ACTIONS` effect → everywhere; otherwise form) must mirror
    `effectiveScope` in ``templates/runtime/rules/engine.ts``, which is where
    the app enforces it. Change the two together, or the tab will say a rule
    runs somewhere it does not."""
    if rule.get("enabled") is False:
        return "nowhere"
    kind = rule.get("kind") or "statement"
    if kind == "prerequisite":
        return "before"
    if kind == "decision_table":
        # A table sets fields when the record is saved; the form does not
        # evaluate tables, so it never ran "live on the form" as it was labelled.
        return "save" if rule.get("entity") and (rule.get("table") or {}).get("rules") else "nowhere"
    if kind != "condition_action" or not rule.get("entity"):
        return "nowhere"
    acts = list(rule.get("then") or []) + list(rule.get("otherwise") or [])
    if rule.get("scope") == "server":
        return "save"
    if any(str((a or {}).get("type")) in DATA_ACTIONS for a in acts):
        return "everywhere"
    return "form" if acts else "nowhere"


def view(rule: dict, doc: dict) -> dict:
    """A rule as the tab shows it: the rule itself, plus what a person needs
    to read it — the record's name, where it runs, what it gates and cites."""
    ents = _entities(doc)
    flows = {str(w.get("id")): w.get("name") for w in _live(doc.get("workflows"))}
    reqs = {str(r.get("id")): r.get("description") for r in _live(doc.get("requirements"))}
    ent = ents.get(str(rule.get("entity") or ""))
    runs = where_it_runs(rule)
    return {
        "rule": rule,
        "revision": revision(rule),
        "kind": rule.get("kind") or "statement",
        "origin": rule.get("origin") or "generated",
        "enabled": rule.get("enabled") is not False,
        "enforced": runs not in ("nowhere",),
        "runs": runs,
        "entityName": (ent or {}).get("name"),
        "gates": [{"id": g, "name": flows.get(str(g))} for g in rule.get("gates") or []],
        # What it answers now: an ask withdrawn since is not listed as one.
        "requirements": [{"id": r, "description": reqs[str(r)]} for r in rule.get("requirements") or []
                         if str(r) in reqs],
        # Where else it acts: as a workflow step, the workflows it starts, and
        # the workflows that save its record (its checks run there too).
        "usages": usages(doc, rule),
    }


def read(output_dir: str | Path) -> dict:
    """Every live rule of the application, and what the tab needs to edit one."""
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.load(output_dir=str(output_dir))
    doc = svc.doc
    why = busy(output_dir)
    rules = [view(r, doc) for r in _live(doc.get("businessRules"))]
    # STRAIGHT FROM THE REQUEST. A rule the person stated is a requirement
    # (`owner: businessRules`) from the moment the requirements are written;
    # the rule that enforces it is written by the build. Until then it is
    # listed as asked for, so the tab shows it the moment it was said.
    cited = {str(x) for v in rules for x in v["rule"].get("requirements") or []}
    planned = [{"id": r.get("id"), "description": r.get("description")}
               for r in _live(doc.get("requirements"))
               if str(r.get("owner") or "") == "businessRules" and str(r.get("id")) not in cited]
    return {
        "mode": "blueprint",
        "version": int(doc.get("version") or 1),
        # Read-only now, and why: the panel says which.
        "building": why is not None,
        "busy": why,
        "rules": rules,
        "planned": planned,
        "catalogue": catalogue(doc),
    }


# ---------------------------------------------------------------------------
# Checking a rule as the build would
# ---------------------------------------------------------------------------

def _clean_action(a: Any) -> dict:
    """An action as the contract stores it: its own keys only (the editor's
    `id` is the editor's), and nothing empty."""
    if not isinstance(a, dict):
        raise RuleError("Each action must be an object.")
    out = {k: a[k] for k in _ACTION_KEYS if k in a and a[k] not in (None, "")}
    if out.get("type") not in ACTION_TYPES:
        raise RuleError(f"“{a.get('type')}” is not something a rule can do.")
    if "value" in out and not isinstance(out["value"], str):
        out["value"] = json.dumps(out["value"]) if isinstance(out["value"], (dict, list)) else str(out["value"])
    if out.get("options"):
        out["options"] = [{"value": str(o.get("value", "")), "label": str(o.get("label", o.get("value", "")))}
                          for o in out["options"] if isinstance(o, dict)]
    return out


def _condition_fields(feel: str) -> set[str]:
    """The field names a condition reads (not functions, words or `user.` /
    `previous.` paths' own segments). Text inside quotes is not read."""
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', feel or "")
    # The functions whose names are two words: `string length(title)` reads
    # `title`, not a field called `string`.
    text = re.sub(r"\b(?:string\s+length|starts\s+with|ends\s+with)\s*\(", "fn(", text)
    names: set[str] = set()
    for m in re.finditer(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*(\()?", text):
        head, path, call = m.group(1), m.group(2), m.group(3)
        if call or head in _FEEL_WORDS and not path:
            continue
        if head in ("user",):
            continue
        if head == "previous":
            if path:
                names.add(path.lstrip(".").split(".")[0])
            continue
        if head in _FEEL_WORDS:
            continue
        names.add(head)
    return names


def table_findings(rule: dict) -> list[dict]:
    """What the app's engine finds in a decision table (``rule_lab``):
    cells it cannot read, rows that overlap under Unique, rows a First table
    can never use, values that are not the column's. Memoised on the table,
    so a check and its advice read it once."""
    table = (rule or {}).get("table") or {}
    key = json.dumps(table, sort_keys=True)
    if _TABLE_FINDINGS.get("key") != key:
        from services.blueprint import rule_lab
        _TABLE_FINDINGS.update(key=key, findings=rule_lab.analyze_table(table))
    return list(_TABLE_FINDINGS.get("findings") or [])


_TABLE_FINDINGS: dict = {}


def advice(doc: dict, rule: dict) -> list[str]:
    """What is worth saying about a rule that is not a reason to refuse it."""
    out: list[str] = []
    if (rule.get("kind") or "") == "decision_table":
        out += [f["message"] for f in table_findings(rule) if f.get("severity") == "warning"]
    on = rule.get("on") or []
    if on == ["create"] and "previous." in str(rule.get("when") or ""):
        out.append("It fires only when a record is created, when there is no previous value — "
                   "a condition on “previous” never holds then.")
    return out


def check(doc: dict, rule: dict) -> list[str]:
    """What is wrong with `rule` against this definition — empty when it
    would be accepted. The build's own checks (`authoring_findings`: the
    entity exists, every action's field is on it, the condition parses in the
    engine's language; `prerequisite_findings`), plus what only an editor can
    get wrong: a condition naming a field the record does not have, a decision
    table whose columns are not the record's fields, a workflow that does not
    exist."""
    problems: list[str] = []
    kind = rule.get("kind") or "statement"
    if not str(rule.get("name") or "").strip():
        problems.append("Give the rule a name.")
    if not str(rule.get("statement") or "").strip():
        problems.append("Say what the rule is, in a sentence.")
    ents = _entities(doc)
    ent = ents.get(str(rule.get("entity") or ""))
    fields = {str(f.get("name")) for f in (ent or {}).get("fields") or []}
    # Every record has these, whether or not the definition lists them.
    readable = fields | {"id", "createdAt", "updatedAt", "created_at", "updated_at"}
    flows = {str(w.get("id")) for w in _live(doc.get("workflows"))}
    if kind in ("condition_action", "decision_table") and ent is None:
        problems.append("Choose the record this rule applies to.")
    if kind == "condition_action":
        if not str(rule.get("when") or "").strip():
            problems.append("Say when the rule applies (its condition).")
        acts = list(rule.get("then") or []) + list(rule.get("otherwise") or [])
        # "When the amount is at most 5000 or there is a note: fine; otherwise
        # refuse" acts only in its otherwise — a rule, as long as it does
        # something on one side.
        if not acts:
            problems.append("Add at least one thing the rule does — when its condition holds, or otherwise.")
        if ent is not None:
            unknown = sorted(n for n in _condition_fields(str(rule.get("when") or "")) if n not in readable)
            if unknown:
                problems.append(f"The condition reads {', '.join(unknown)}, which {ent.get('name')} does not have "
                                f"(fields: {', '.join(sorted(fields))}).")
        for a in acts:
            t = a.get("type")
            if t in ("set_field", "set_default", "clear_field", "set_visibility", "set_required",
                     "set_readonly", "set_options", "recommendation") and not a.get("field"):
                problems.append(f"“{t.replace('_', ' ')}” needs a field.")
            if t == "show_error" and not str(a.get("message") or "").strip():
                problems.append("A refusal needs the message the person is shown.")
            if t == "send_notification" and not str(a.get("message") or "").strip():
                problems.append("A notification needs its message.")
            if t == "trigger_workflow":
                if not a.get("workflow"):
                    problems.append("Choose the workflow the rule starts.")
                elif flows and str(a["workflow"]) not in flows:
                    problems.append(f"{a['workflow']} is not a workflow of this application.")
            if t == "set_options" and not a.get("options"):
                problems.append("“set options” needs the options the field offers.")
    if kind == "decision_table":
        table = rule.get("table") or {}
        if not table.get("inputs") or not table.get("outputs"):
            problems.append("A decision table needs at least one input and one output column.")
        if not table.get("rules"):
            problems.append("A decision table needs at least one row.")
        policy = str(table.get("hitPolicy") or "F").upper()
        if policy == "R" or (policy == "C" and not table.get("aggregation")):
            problems.append("A table that sets a record's fields needs one value per field: use First, Unique, "
                            "Priority or Any — or Collect with a sum, count, minimum or maximum. Rule order and "
                            "plain Collect give a list, which only a workflow step can use.")
        outs = [str(c.get("variableBinding") or c.get("name") or "") for c in table.get("outputs") or []]
        if len(set(outs)) != len(outs):
            problems.append("Each output column sets a different field.")
        if ent is not None:
            for col in list(table.get("inputs") or []) + list(table.get("outputs") or []):
                name = str(col.get("variableBinding") or col.get("name") or "")
                if name and name not in fields:
                    problems.append(f"The column “{name}” is not a field of {ent.get('name')}.")
            width_in, width_out = len(table.get("inputs") or []), len(table.get("outputs") or [])
            for i, row in enumerate(table.get("rules") or [], 1):
                if len(row.get("inputEntries") or []) != width_in or len(row.get("outputEntries") or []) != width_out:
                    problems.append(f"Row {i} does not have a cell for every column.")
    if kind == "decision_table" and not problems:
        # The cells, overlaps and typos — read by the app's own engine.
        problems += [f["message"] for f in table_findings(rule) if f.get("severity") == "error"]
    if problems:
        return problems
    # The build's own checks, exactly as an agent's rule meets them.
    try:
        from services.blueprint.agent_contract import prerequisite_findings
        from services.blueprint.functional_completeness import authoring_findings
        findings = authoring_findings({"businessRules": [rule], "workflows": [], "data": doc.get("data") or {}})
        problems += [str(f.get("detail") or f) for f in findings]
        problems += prerequisite_findings(rule, doc)
    except Exception as exc:  # noqa: BLE001 — a checker that broke is said, not hidden
        logger.exception("[rules] checking a rule failed")
        problems.append(f"The rule could not be checked: {type(exc).__name__}: {exc}")
    return problems


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _describe(rule: dict, doc: dict) -> str:
    """A sentence for a rule made without one — what it says when it is read
    back, by a person or by Smith."""
    ent = (_entities(doc).get(str(rule.get("entity") or "")) or {}).get("name") or "the record"
    if rule.get("kind") == "decision_table":
        outs = ", ".join(str(c.get("name")) for c in (rule.get("table") or {}).get("outputs") or [])
        return f"{ent}: {outs or 'values'} decided by a table of conditions."
    effects = []
    for a in rule.get("then") or []:
        t, f = a.get("type"), a.get("field")
        if t == "show_error":
            effects.append(f"refuse with “{a.get('message')}”")
        elif t == "set_field":
            effects.append(f"set {f} to {a.get('value')}")
        elif t == "set_default":
            effects.append(f"default {f} to {a.get('value')}")
        elif t == "clear_field":
            effects.append(f"clear {f}")
        elif t == "set_required":
            effects.append(f"require {f}")
        elif t == "set_visibility":
            effects.append(f"{'show' if a.get('visible', True) else 'hide'} {f}")
        elif t == "set_readonly":
            effects.append(f"lock {f}")
        elif t == "trigger_workflow":
            effects.append(f"start {a.get('workflow')}")
        elif t == "send_notification":
            effects.append(f"notify “{a.get('message')}”")
        else:
            effects.append(f"{str(t).replace('_', ' ')} {f or ''}".strip())
    return f"{ent}: when {rule.get('when')}, {', '.join(effects) or 'nothing'}."


def normalise(payload: dict, doc: dict, *, existing: dict | None = None) -> dict:
    """The rule a payload describes, in the contract's shape. Unknown keys are
    dropped; what the tab does not send is kept from `existing`."""
    if not isinstance(payload, dict):
        raise RuleError("A rule must be an object.")
    base = dict(existing or {})
    kind = str(payload.get("kind") or base.get("kind") or "condition_action")
    if kind not in KINDS:
        raise RuleError(f"“{kind}” is not a kind of rule.")
    if kind == "prerequisite" and (existing is None or existing.get("kind") != "prerequisite"):
        raise RuleError("A prerequisite is set up by Smith (it gates workflows); ask Smith in the chat.")
    rule: dict[str, Any] = {k: v for k, v in base.items()}
    rule["kind"] = kind
    for key in ("name", "statement", "entity", "when", "message"):
        if key in payload:
            val = payload[key]
            if val is None or (isinstance(val, str) and not val.strip()):
                rule.pop(key, None)
            else:
                rule[key] = str(val).strip()
    if "scope" in payload:
        if payload["scope"] not in SCOPES:
            raise RuleError("Where a rule runs is one of: everywhere, form only, on save only.")
        rule["scope"] = payload["scope"]
    if "salience" in payload:
        try:
            rule["salience"] = int(payload.get("salience") or 0)
        except (TypeError, ValueError):
            raise RuleError("Priority must be a whole number.") from None
    if "enabled" in payload:
        rule["enabled"] = bool(payload["enabled"])
    if "on" in payload:
        on = [str(x) for x in (payload.get("on") or []) if str(x) in ("create", "update")]
        on = [x for x in ("create", "update") if x in on]   # in order, once each
        if on and on != ["create", "update"]:
            rule["on"] = on
        else:
            rule.pop("on", None)                            # both is the default
    for key in ("then", "otherwise"):
        if key in payload:
            rule[key] = [_clean_action(a) for a in payload.get(key) or []]
    if "table" in payload:
        t = payload.get("table") or {}
        policy = str(t.get("hitPolicy") or "F").upper()
        if policy not in ("U", "F", "A", "P", "C", "R"):
            raise RuleError(f"“{t.get('hitPolicy')}” is not a hit policy.")
        cols = ("id", "name", "label", "type", "variableBinding")

        def column(c: dict) -> dict:
            out = {k: c[k] for k in cols if k in c and c[k] not in (None, "")}
            # An output column keeps the field it writes (it was dropped, so
            # an output named apart from its field wrote nowhere).
            if not out.get("variableBinding") and out.get("name"):
                out["variableBinding"] = out["name"]
            vals = [str(v).strip() for v in c.get("values") or [] if str(v).strip()]
            if vals:
                out["values"] = list(dict.fromkeys(vals))
            return out
        rule["table"] = {
            "hitPolicy": policy,
            **({"aggregation": str(t["aggregation"]).upper()}
               if policy == "C" and str(t.get("aggregation") or "").upper() in ("SUM", "COUNT", "MIN", "MAX") else {}),
            "inputs": [column(c) for c in t.get("inputs") or [] if isinstance(c, dict)],
            "outputs": [column(c) for c in t.get("outputs") or [] if isinstance(c, dict)],
            "rules": [{"inputEntries": [str(x) for x in r.get("inputEntries") or []],
                       "outputEntries": [str(x) for x in r.get("outputEntries") or []],
                       **({"annotation": str(r["annotation"])} if r.get("annotation") else {})}
                      for r in t.get("rules") or [] if isinstance(r, dict)],
        }
        # A column's type and values follow its field: an enum's values are
        # what Priority ranks by and what a typo is caught against.
        ent = _entities(doc).get(str(payload.get("entity") or base.get("entity") or ""))
        fields = {str(f.get("name")): f for f in (ent or {}).get("fields") or [] if isinstance(f, dict)}
        for col in rule["table"]["inputs"] + rule["table"]["outputs"]:
            f = fields.get(str(col.get("variableBinding") or col.get("name") or ""))
            if f is not None:
                col["type"] = _field_type(f) if _field_type(f) in ("string", "number", "boolean", "date") else "string"
                enum_vals = [str(v) for v in _enum_values(f)]
                if enum_vals and not col.get("values"):
                    col["values"] = enum_vals
            col["type"] = col.get("type") if col.get("type") in ("string", "number", "boolean", "date", "any") else "any"
    if "requirements" in payload:
        known = {str(r.get("id")) for r in _live(doc.get("requirements"))}
        rule["requirements"] = [str(r) for r in payload.get("requirements") or [] if str(r) in known]
    # What the kind does not use is not kept: a statement made enforceable
    # becomes a condition→action rule; a rule turned back into prose drops
    # its effects rather than carrying ones nothing runs.
    if kind == "statement":
        for k in ("when", "then", "otherwise", "table", "scope", "salience"):
            rule.pop(k, None)
    elif kind == "condition_action":
        rule.pop("table", None)
        rule.setdefault("then", [])
        rule.setdefault("otherwise", [])
        rule.setdefault("scope", "entity")
    elif kind == "decision_table":
        for k in ("when", "then", "otherwise"):
            rule.pop(k, None)
    if not rule.get("statement") and kind != "statement":
        rule["statement"] = _describe(rule, doc)
    # What the rule touches, for impact analysis and the Rules↔Process edges.
    applies = [str(x) for x in base.get("appliesTo") or []]
    if rule.get("entity") and rule["entity"] not in applies:
        applies.insert(0, str(rule["entity"]))
    for a in list(rule.get("then") or []) + list(rule.get("otherwise") or []):
        if a.get("workflow") and a["workflow"] not in applies:
            applies.append(str(a["workflow"]))
    if applies:
        rule["appliesTo"] = applies
    return rule


def _ensure_registry(svc: Any) -> None:
    """The id registry knows every id the document already uses before a rule
    is added. An app whose `ids.json` is missing or behind its document (an
    import, a restore, an older build) otherwise hands a new rule an id the
    document already gives another — refused as an IdentityCollision, and the
    person could add no rule at all. Idempotent: an app in step is untouched."""
    try:
        from services.smith.smith import bootstrap
        bootstrap(svc)
    except Exception:  # noqa: BLE001 — the upsert then says what is wrong
        logger.exception("[rules] could not bring the id registry in step")


def _project(svc: Any, *, prerequisites: bool = False) -> list[str]:
    """Write the rules into the running app — at once, no rebuild. A change to
    a prerequisite rewrites the workflows it gates too."""
    from services.blueprint.projection import project_business_rules, project_workflows
    app = Path(svc.output_dir) / "app"
    if not app.is_dir():
        return []
    # AN APP BUILT BEFORE THE ENGINE COULD RE-READ ITS RULES KEEPS THEM UNTIL
    # IT RESTARTS. The engine is the platform's; a Smith turn starts by
    # bringing the app up to the current platform (`catch_up`: the engine,
    # the frame and every projection, once per platform version), and a
    # change made here does the same — otherwise a rule saved in the tab
    # would wait for the next conversation to apply. Copying the engine alone
    # is not enough: the current engine reads files only a projection writes.
    if (app / "package.json").is_file():
        try:
            from services.smith.sync_app import catch_up
            catch_up(svc.output_dir)
        except Exception:  # noqa: BLE001 — the rules are still written; the next turn catches up
            logger.exception("[rules] the app could not be brought up to the current platform")
    files = list(project_business_rules(svc.doc, app).get("files") or [])
    if prerequisites:
        try:
            project_workflows(svc.doc, str(app))
            files.append("src/lib/workflows/definitions/")
        except Exception:  # noqa: BLE001 — the rules are written; the guards follow on the next sync
            logger.exception("[rules] re-writing the gated workflows failed")
    return files


def _commit(svc: Any, before: dict, request: str, said: str, affected: list[str]) -> int:
    record = svc.commit(user_request=request, smith_interpretation=said, before=before, affected=affected)
    return int(record["version"])


def _guard_writable(output_dir: str | Path) -> None:
    if not has_definition(output_dir):
        raise RuleError("This app has no definition yet — describe it to Smith first.", status=404)
    why = busy(output_dir)
    if why == "smith":
        # A turn is often short: waited for, as the rules lock is.
        deadline = time.monotonic() + TAB_LOCK_WAIT
        while why == "smith" and time.monotonic() < deadline:
            time.sleep(0.5)
            why = busy(output_dir)
    if why:
        raise RuleError(BUSY_SAID[why], status=423)


def _find(doc: dict, rule_id: str) -> dict:
    for r in _live(doc.get("businessRules")):
        if str(r.get("id")) == str(rule_id):
            return r
    raise RuleError("That rule no longer exists — it may have been removed in the chat. Reload the list.",
                    status=404)


def create(output_dir: str | Path, payload: dict, *, actor: str = "") -> dict:
    """A rule made in the Business Rules tab."""
    from services.blueprint.ids import prose_key
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        rule = normalise(payload, svc.doc)
        rule["origin"] = "editor"
        rule.setdefault("enabled", True)
        rule.setdefault("requirements", [])
        rule["status"] = "PROPOSED"
        problems = check(svc.doc, rule)
        if problems:
            raise RuleError(problems[0], problems=problems)
        same = [r for r in _live(svc.doc.get("businessRules"))
                if str(r.get("statement") or "").strip().lower() == rule["statement"].strip().lower()]
        if same:
            raise RuleError(f"{same[0].get('id')} already says that: “{same[0].get('name')}”.", status=409)
        before = svc.snapshot()
        _ensure_registry(svc)
        stored = svc.upsert("businessRules", rule, natural_key=prose_key("RULE", rule["statement"]))
        # The same wording as a rule removed before is the same id, merged
        # onto that record — not onto why it was removed.
        stored.pop("syncNote", None)
        version = _commit(svc, before, f"Business Rules tab: add “{rule['name']}”"
                          + (f" (by {actor})" if actor else ""),
                          f"Added {stored['id']} in the Business Rules tab", [str(stored["id"])])
        files = _project(svc)
        logger.info("[rules] %s: added %s in the tab", Path(output_dir).name, stored["id"])
        return {"rule": view(stored, svc.doc), "version": version, "files": files}


def update(output_dir: str | Path, rule_id: str, payload: dict, *, expected: str | None,
           actor: str = "") -> dict:
    """An edit made in the Business Rules tab. Refused when the rule has changed
    since the person opened it (Smith or another tab changed it)."""
    from services.blueprint.ids import IdAllocator, prose_key
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        current = _find(svc.doc, rule_id)
        if expected and revision(current) != expected:
            raise RuleError("This rule was changed since you opened it (by Smith or someone else). "
                            "Reload it to see the change, then edit again.", status=409)
        if current.get("kind") == "prerequisite":
            allowed = {k: payload[k] for k in ("enabled", "name", "message", "statement") if k in payload}
            payload = allowed
        rule = normalise(payload, svc.doc, existing=current)
        if rule.get("syncNote") == KEPT_NOTE and rule.get("kind") != "statement":
            rule.pop("syncNote")              # enforceable now: no longer "not enforced yet"
        problems = check(svc.doc, rule)
        if problems:
            raise RuleError(problems[0], problems=problems)
        if rule == current:
            return {"rule": view(current, svc.doc), "version": int(svc.doc.get("version") or 1),
                    "files": [], "unchanged": True}
        before = svc.snapshot()
        rows = svc.doc.get("businessRules") or []
        for i, r in enumerate(rows):
            if isinstance(r, dict) and str(r.get("id")) == str(rule_id):
                rows[i] = rule
        # THE SAME RULE, REWORDED. A rule's id follows its wording; an edit in
        # the tab is the same rule, so its id is carried to the new wording
        # rather than a second rule being minted the next time it is written.
        if str(current.get("statement") or "") != str(rule.get("statement") or ""):
            try:
                with IdAllocator.session(output_dir=svc.output_dir) as alloc:
                    old_key = prose_key("RULE", str(current.get("statement") or ""))
                    new_key = prose_key("RULE", str(rule.get("statement") or ""))
                    if alloc.lookup(old_key) == str(rule_id) and not alloc.lookup(new_key):
                        alloc.rebind(old_key=old_key, new_key=new_key)
            except Exception:  # noqa: BLE001 — the rule is still saved under its id
                logger.warning("[rules] could not carry %s's id to its new wording", rule_id)
        version = _commit(svc, before, f"Business Rules tab: edit “{rule.get('name')}”"
                          + (f" (by {actor})" if actor else ""),
                          f"Edited {rule_id} in the Business Rules tab", [str(rule_id)])
        files = _project(svc, prerequisites=rule.get("kind") == "prerequisite")
        logger.info("[rules] %s: edited %s in the tab", Path(output_dir).name, rule_id)
        return {"rule": view(rule, svc.doc), "version": version, "files": files}


def set_enabled(output_dir: str | Path, rule_id: str, enabled: bool, *, expected: str | None,
                actor: str = "") -> dict:
    return update(output_dir, rule_id, {"enabled": bool(enabled)}, expected=expected, actor=actor)


def remove(output_dir: str | Path, rule_id: str, *, expected: str | None, actor: str = "") -> dict:
    """A rule removed in the tab is retired (DEPRECATED, kept in history) and
    taken out of the running app at once."""
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        current = _find(svc.doc, rule_id)
        if expected and revision(current) != expected:
            raise RuleError("This rule was changed since you opened it. Reload, then remove it again.",
                            status=409)
        before = svc.snapshot()
        for r in svc.doc.get("businessRules") or []:
            if isinstance(r, dict) and str(r.get("id")) == str(rule_id):
                r["status"] = "DEPRECATED"
                r["syncNote"] = "removed in the Business Rules tab"
                retire_asks(svc.doc, r, f"its rule {rule_id} was removed in the Business Rules tab")
        version = _commit(svc, before, f"Business Rules tab: remove “{current.get('name')}”"
                          + (f" (by {actor})" if actor else ""),
                          f"Removed {rule_id} in the Business Rules tab", [str(rule_id)])
        files = _project(svc, prerequisites=current.get("kind") == "prerequisite")
        logger.info("[rules] %s: removed %s in the tab", Path(output_dir).name, rule_id)
        return {"removed": rule_id, "version": version, "files": files}


def try_rule(output_dir: str | Path, payload: dict, *, rule_id: str | None = None) -> dict:
    """Check a rule without saving it — the editor's live feedback."""
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.load(output_dir=str(output_dir))
    existing = _find(svc.doc, rule_id) if rule_id else None
    try:
        rule = normalise(payload, svc.doc, existing=existing)
    except RuleError as exc:
        return {"ok": False, "problems": exc.problems}
    problems = check(svc.doc, rule)
    findings = table_findings(rule) if rule.get("kind") == "decision_table" else []
    return {"ok": not problems, "problems": problems, "runs": where_it_runs(rule),
            "statement": rule.get("statement"), "advice": advice(svc.doc, rule),
            # Per row and column, so the table can mark the cell itself.
            "findings": findings}


# ---------------------------------------------------------------------------
# What the person asked for is never lost
# ---------------------------------------------------------------------------

#: How a written-down rule kept from the request says so (`keep_stated_rules`).
KEPT_NOTE = "you asked for this; the build did not make it enforceable — open it to enforce it"


def retire_asks(doc: dict, rule: dict, why: str) -> list[str]:
    """The asks a removed rule answered, withdrawn with it: each requirement
    it cites that states a rule (`owner: businessRules`) and that no other
    live rule answers. Returns their ids. Writes the document in place.

    Without this a rule the person removed came back: its ask was still a
    stated rule nothing cited, so the next build — or the next Smith turn's
    catch-up — kept it as a written-down rule "you asked for" (Task Board,
    2026-10-14). A requirement that is not a rule (a page, a record) is never
    touched: other parts of the app answer it."""
    cites = {str(x) for x in rule.get("requirements") or []}
    if not cites:
        return []
    others = {str(x) for r in _live(doc.get("businessRules"))
              if str(r.get("id")) != str(rule.get("id")) for x in r.get("requirements") or []}
    out: list[str] = []
    for req in doc.get("requirements") or []:
        if (isinstance(req, dict) and str(req.get("id")) in cites and str(req.get("id")) not in others
                and str(req.get("owner") or "") == "businessRules" and req.get("status") not in _RETIRED):
            req["status"] = "DEPRECATED"
            req["syncNote"] = why
            out.append(str(req.get("id")))
    return out


def keep_stated_rules(svc: Any) -> dict:
    """After the build writes the rules: every rule the person stated is in
    the list, and every rule says where it came from.

    A rule stated in the request is kept as its own requirement, tagged
    ``owner: "businessRules"`` (the requirements brief). The rules agent is
    told to turn each into an enforced rule citing it; one it did not cover is
    added here, deterministically, as a written-down rule from the person's
    request — shown in the Business Rules tab under "not enforced yet" with a
    way to enforce it, never silently dropped. A rule without an `origin` is
    marked `brief` when it cites such a requirement and `generated` otherwise.
    Writes the document in place; the caller saves."""
    from services.blueprint.ids import prose_key
    doc = svc.doc
    stated = [r for r in _live(doc.get("requirements")) if str(r.get("owner") or "") == "businessRules"]
    stated_ids = {str(r.get("id")) for r in stated}
    tagged = 0
    for rule in doc.get("businessRules") or []:
        if not isinstance(rule, dict) or rule.get("origin"):
            continue
        rule["origin"] = "brief" if stated_ids & {str(x) for x in rule.get("requirements") or []} else "generated"
        tagged += 1
    # A RULE KEPT FROM THE REQUEST STEPS ASIDE once another rule enforces the
    # same ask — the tab would otherwise list it twice, once "not enforced".
    live = _live(doc.get("businessRules"))
    for kept in live:
        if kept.get("kind") != "statement" or kept.get("syncNote") != KEPT_NOTE:
            continue
        asks = {str(x) for x in kept.get("requirements") or []}
        by = next((r for r in live if r is not kept and r.get("kind") != "statement"
                   and asks & {str(x) for x in r.get("requirements") or []}), None)
        if asks and by is not None:
            kept["status"] = "DEPRECATED"
            kept["syncNote"] = f"enforced by {by.get('id')}"
    cited = {str(x) for r in _live(doc.get("businessRules")) for x in r.get("requirements") or []}
    added: list[str] = []
    if any(str(r.get("id")) not in cited for r in stated):
        _ensure_registry(svc)
    # One rule per thing said: the same sentence recorded twice is one ask.
    uncovered: dict[str, list[str]] = {}
    for req in stated:
        rid = str(req.get("id"))
        text = " ".join(str(req.get("description") or "").split())
        if rid not in cited and text:
            uncovered.setdefault(text, []).append(rid)
    for text, rids in uncovered.items():
        name = text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "…"
        stored = svc.upsert("businessRules", {
            "name": name, "statement": text, "kind": "statement", "origin": "brief", "enabled": True,
            "requirements": rids, "status": "PROPOSED",
            "syncNote": KEPT_NOTE,
        }, natural_key=prose_key("RULE", text))
        added.append(str(stored.get("id")))
    if added:
        logger.warning("[rules] %s: %d stated rule(s) the build did not cover were kept as written-down rules: %s",
                       Path(str(svc.output_dir)).name, len(added), ", ".join(added))
    return {"added": added, "tagged": tagged}


# ---------------------------------------------------------------------------
# Rules made in the tab before it wrote the Blueprint
# ---------------------------------------------------------------------------

def adopt(output_dir: str | Path, rows: list[dict]) -> list[str]:
    """Bring rules the tab saved to the old table into the Blueprint, once.

    `rows` are ``project_rules`` rows of this project (dicts). The tab's
    condition→action rules and decision tables are matched to their record by
    name (table or entity spelling) and written as `origin: editor`; a row
    that names no record of this app is left where it is. Returns the ids of
    the rows adopted, for the caller to remove from the table."""
    from services.blueprint.ids import prose_key
    from services.blueprint.service import BlueprintService
    candidates = [r for r in rows if r.get("rule_type") in ("condition_action", "decision_table")]
    if not candidates or not has_definition(output_dir):
        return []
    adopted: list[str] = []
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        svc = BlueprintService.load(output_dir=str(output_dir))
        ents = list(_entities(svc.doc).values())

        def key(s: str) -> str:
            c = re.sub(r"[^a-z0-9]", "", s.lower())
            return c[:-3] + "y" if c.endswith("ies") else c[:-1] if c.endswith("s") and not c.endswith("ss") else c

        before = svc.snapshot()
        _ensure_registry(svc)
        for row in candidates:
            model = str(row.get("model_name") or "")
            cfg = row.get("config") or {}
            ent = next((e for e in ents if model and key(model) in (key(str(e.get("name") or "")),
                                                                     key(str(e.get("table") or ""))) ), None)
            if ent is None and row.get("rule_type") == "decision_table" and len(ents) == 1:
                ent = ents[0]
            if ent is None:
                continue
            payload: dict[str, Any] = {"name": row.get("name"), "entity": ent.get("id"),
                                       "enabled": row.get("is_active") is not False}
            if row.get("rule_type") == "decision_table":
                payload.update(kind="decision_table", table=cfg.get("table") or {})
            else:
                payload.update(kind="condition_action", when=cfg.get("whenFeel") or "true",
                               then=cfg.get("then") or [], otherwise=cfg.get("otherwise") or [],
                               scope=cfg.get("scope") or "entity", salience=cfg.get("salience") or 0)
            try:
                rule = normalise(payload, svc.doc)
            except RuleError:
                continue
            rule.update(origin="editor", status="PROPOSED",
                        syncNote="moved here from the old Business Rules table")
            if check(svc.doc, rule):
                rule["enabled"] = False
                rule["syncNote"] = ("moved here from the old Business Rules table; switched off until fixed: "
                                    + "; ".join(check(svc.doc, rule))[:400])
            if any(str(r.get("statement") or "").strip().lower() == rule["statement"].strip().lower()
                   for r in _live(svc.doc.get("businessRules"))):
                adopted.append(str(row.get("id")))   # already here: the row is a duplicate
                continue
            svc.upsert("businessRules", rule, natural_key=prose_key("RULE", rule["statement"]))
            adopted.append(str(row.get("id")))
        if adopted and svc.doc != before:
            _commit(svc, before, "Business Rules tab: rules saved before the tab wrote the definition",
                    f"Adopted {len(adopted)} rule(s) from the old Business Rules table", [])
            _project(svc)
    return adopted


__all__ = [
    "RuleError", "adopt", "building", "catalogue", "check", "create", "has_definition", "keep_stated_rules",
    "normalise", "read", "remove", "revision", "set_enabled", "try_rule", "update", "view",
    "where_it_runs", "write_lock",
]


# ---------------------------------------------------------------------------
# Test it — the app's own engine, on a sample record
# ---------------------------------------------------------------------------

DRAFT_ID = "RULE-DRAFT"


def test_rule(output_dir: str | Path, payload: dict | None, *, rule_id: str | None = None,
              entity: str | None = None, record: dict | None = None, previous: dict | None = None,
              event: str = "create", user: dict | None = None) -> dict:
    """What the app would do with this save: the draft rule (or, with no
    payload, the rules as they are) among every other rule of its record, run
    by the app's own engine (`rule_lab`). Nothing is saved.

    ``{ok, problems, advice, refused, errors, patches, formHints, record,
    sideEffects, trace, focus}`` — `focus` is the draft's own line: did it
    fire on this event, did its condition hold, which rows matched."""
    from services.blueprint import rule_lab
    from services.blueprint.projection import business_rule_rows
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.load(output_dir=str(output_dir))
    doc = json.loads(json.dumps(svc.doc))
    problems: list[str] = []
    draft = None
    if payload is not None:
        existing = _find(doc, rule_id) if rule_id else None
        try:
            draft = normalise(payload, doc, existing=existing)
        except RuleError as exc:
            return {"ok": False, "problems": exc.problems or [str(exc)], "advice": []}
        problems = check(doc, draft)
        draft = {**draft, "id": rule_id or DRAFT_ID, "enabled": True, "status": "PROPOSED"}
        rows = [r for r in doc.get("businessRules") or []
                if not (isinstance(r, dict) and str(r.get("id")) == str(draft["id"]))]
        doc["businessRules"] = rows + [draft]
    if draft is not None and draft.get("kind") == "statement":
        return {"ok": False, "problems": ["A written rule is not checked by the app, so there is nothing to test — "
                                          "make it enforceable first."], "advice": []}
    ent_id = str((draft or {}).get("entity") or entity or "")
    ent = _entities(doc).get(ent_id)
    if ent is None:
        return {"ok": False, "problems": problems or ["Choose the record to test it on."], "advice": []}
    rows = [r for r in business_rule_rows(doc) if str(r.get("model_name")) == str(ent.get("name"))]
    try:
        result = rule_lab.simulate(model=str(ent.get("name")), rules=rows, record=dict(record or {}),
                                   event="update" if event == "update" else "create",
                                   previous=dict(previous or {}) if event == "update" else None,
                                   user=user, focus=str(draft["id"]) if draft else None)
    except rule_lab.LabUnavailable as exc:
        return {"ok": False, "problems": problems, "advice": [],
                "unavailable": f"The test could not run here: {exc}."}
    return {"ok": not problems, "problems": problems,
            "advice": advice(doc, draft) if draft else [], **result}


# ---------------------------------------------------------------------------
# Rules in workflows
# ---------------------------------------------------------------------------

#: How a rule's step in a workflow is keyed: one step per rule per workflow.
def _step_key(rule_id: str) -> str:
    return "rule_" + re.sub(r"[^a-z0-9]+", "_", str(rule_id).lower()).strip("_")


def usages(doc: dict, rule: dict) -> dict:
    """Where a rule acts beyond the record's own saves:
    ``steps`` — workflow steps that run it; ``starts`` — the workflows it
    starts; ``saves`` — the workflows that save its record, where the record's
    rules are checked on every write anyway."""
    rid = str(rule.get("id") or "")
    ent = _entities(doc).get(str(rule.get("entity") or "")) or {}
    table = str(ent.get("table") or "").lower()
    starts = {str(a.get("workflow")) for a in list(rule.get("then") or []) + list(rule.get("otherwise") or [])
              if isinstance(a, dict) and a.get("type") == "trigger_workflow" and a.get("workflow")}
    steps, saves, started = [], [], []
    for w in _live(doc.get("workflows")):
        wid, wname = str(w.get("id")), str(w.get("name") or w.get("id"))
        if wid in starts:
            started.append({"workflow": wid, "name": wname})
        saved = False
        for st in w.get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") or {}
            if st.get("type") == "decision" and str(cfg.get("rule") or "") == rid:
                steps.append({"workflow": wid, "name": wname, "step": st.get("key"),
                              "stepName": st.get("name") or st.get("key"),
                              "stops": any(str(n).endswith("_refused") for n in (st.get("next") or [])[1:2])})
            # A write of this record: a db_insert/db_update of its table, or an
            # action step naming the record with no other action type (how the
            # build writes "create the role").
            writes = cfg.get("actionType") in ("db_insert", "db_update", "db_upsert") or (
                st.get("type") == "action" and not cfg.get("actionType"))
            names_it = (str(st.get("entity") or "") == str(rule.get("entity") or "")
                        or (table and str(cfg.get("table") or "").lower() == table))
            if writes and names_it:
                saved = True
        if saved and rule.get("entity"):
            saves.append({"workflow": wid, "name": wname})
    return {"steps": steps, "starts": started, "saves": saves}


def _refusal_message(rule: dict) -> str:
    for side in ("then", "otherwise"):
        for a in rule.get(side) or []:
            if isinstance(a, dict) and a.get("type") == "show_error" and str(a.get("message") or "").strip():
                return str(a["message"]).strip()
    return str(rule.get("message") or "").strip() or f"Stopped by the rule “{rule.get('name') or rule.get('id')}”."


def attach(output_dir: str | Path, rule_id: str, *, workflow: str, after: str | None,
           on_refusal: str = "stop", actor: str = "") -> dict:
    """Run a rule as a step of a workflow, after the step `after` (None: at
    the start). A rule that can refuse becomes a gate: with ``on_refusal ==
    "stop"`` its else-path ends the workflow, refused, with the rule's own
    message; ``"continue"`` carries on either way (its values still reach the
    steps after). A decision table's outputs are written for the steps after.
    A rule already in that workflow is moved, not added twice."""
    from services.blueprint.projection import project_workflows
    from services.blueprint.service import BlueprintService
    if on_refusal not in ("stop", "continue"):
        raise RuleError("Say whether a refusal stops the workflow or it carries on.")
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        rule = _find(svc.doc, rule_id)
        if rule.get("kind") not in ("condition_action", "decision_table"):
            raise RuleError("Only a rule the app checks — a when/then rule or a decision table — can be a step "
                            "of a workflow. Make this one enforceable first.")
        if rule.get("enabled") is False:
            raise RuleError("This rule is switched off; switch it on to use it in a workflow.")
        flow = next((w for w in _live(svc.doc.get("workflows")) if str(w.get("id")) == str(workflow)), None)
        if flow is None:
            raise RuleError(f"{workflow} is not a workflow of this application.", status=404)
        before = svc.snapshot()
        key = _step_key(rule_id)
        _detach_in(flow, key)
        steps = flow.setdefault("steps", [])
        by_key = {s.get("key"): s for s in steps if isinstance(s, dict)}
        if after is not None and after not in by_key:
            raise RuleError(f"The workflow has no step “{after}”.", status=404)
        if after is not None and by_key[after].get("type") in ("end", "end_event"):
            raise RuleError("A step cannot come after the end of the workflow — choose a step before it.")
        gate = rule.get("kind") == "condition_action" and any(
            isinstance(a, dict) and a.get("type") == "show_error"
            for a in list(rule.get("then") or []) + list(rule.get("otherwise") or []))
        step = {"key": key, "name": f"Check: {rule.get('name') or rule_id}", "type": "decision",
                "config": {"rule": str(rule_id)}, "next": []}
        if rule.get("entity"):
            step["entity"] = rule["entity"]
        if after is None:
            # After the trigger step when the workflow has one, else first.
            at = next((i + 1 for i, s in enumerate(steps) if isinstance(s, dict) and s.get("type") == "trigger"), 0)
            first = steps[at]["key"] if at < len(steps) else None
            if at > 0:
                trig = steps[at - 1]
                tnext = list(trig.get("next") or [])
                if tnext:
                    first = tnext[0]
                    trig["next"] = [key] + tnext[1:]
                else:
                    trig["next"] = [key]
            follow = first
            steps.insert(at, step)
        else:
            prev = by_key[after]
            pnext = list(prev.get("next") or [])
            follow = pnext[0] if pnext else None
            prev["next"] = [key] + pnext[1:]
            steps.insert(steps.index(prev) + 1, step)
        if follow is None:
            # The step handed to the workflow's end; make that end explicit.
            end_key = f"{key}_done"
            steps.append({"key": end_key, "name": "Done", "type": "end", "config": {"refused": False}, "next": []})
            follow = end_key
        step["next"] = [follow]
        if gate and on_refusal == "stop":
            refused = f"{key}_refused"
            steps.append({"key": refused, "name": f"Refused: {rule.get('name') or rule_id}", "type": "end",
                          "config": {"refused": True, "message": _refusal_message(rule)}, "next": []})
            step["next"] = [follow, refused]
        try:
            svc.validate()
        except Exception as exc:  # noqa: BLE001 — refused whole, nothing saved
            raise RuleError(f"The workflow would not be valid with this step: {exc}") from exc
        version = _commit(svc, before, f"Business Rules tab: run “{rule.get('name')}” in {flow.get('name')}"
                          + (f" (by {actor})" if actor else ""),
                          f"Added {rule_id} as a step of {workflow}", [str(rule_id), str(workflow)])
        files = _project(svc)
        app = Path(svc.output_dir) / "app"
        if app.is_dir():
            project_workflows(svc.doc, str(app))
            files.append("src/lib/workflows/definitions/")
        return {"rule": view(rule, svc.doc), "version": version, "files": files}


def _detach_in(flow: dict, key: str) -> bool:
    """Take a rule's step out of a workflow: whatever led to it now leads to
    what came after it on its then-path, and the ends it added go with it."""
    steps = flow.get("steps") or []
    step = next((s for s in steps if isinstance(s, dict) and s.get("key") == key), None)
    if step is None:
        return False
    own = {f"{key}_refused", f"{key}_done"}
    follow = (step.get("next") or [None])[0]
    if follow in own:
        follow = None          # it led to its own end: those before it now end there
    for s in steps:
        if s is step or not isinstance(s, dict) or key not in (s.get("next") or []):
            continue
        s["next"] = [follow if n == key else n for n in s["next"] if n != key or follow]
    flow["steps"] = [s for s in steps if s is not step and not (isinstance(s, dict) and s.get("key") in own)]
    return True


def detach(output_dir: str | Path, rule_id: str, *, workflow: str, actor: str = "") -> dict:
    """Stop running a rule as a step of a workflow."""
    from services.blueprint.projection import project_workflows
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        rule = _find(svc.doc, rule_id)
        flow = next((w for w in _live(svc.doc.get("workflows")) if str(w.get("id")) == str(workflow)), None)
        if flow is None:
            raise RuleError(f"{workflow} is not a workflow of this application.", status=404)
        before = svc.snapshot()
        if not _detach_in(flow, _step_key(rule_id)):
            raise RuleError("This rule is not a step of that workflow.", status=404)
        svc.validate()
        version = _commit(svc, before, f"Business Rules tab: stop running “{rule.get('name')}” in {flow.get('name')}"
                          + (f" (by {actor})" if actor else ""),
                          f"Removed {rule_id}'s step from {workflow}", [str(rule_id), str(workflow)])
        files = _project(svc)
        app = Path(svc.output_dir) / "app"
        if app.is_dir():
            project_workflows(svc.doc, str(app))
            files.append("src/lib/workflows/definitions/")
        return {"rule": view(rule, svc.doc), "version": version, "files": files}
