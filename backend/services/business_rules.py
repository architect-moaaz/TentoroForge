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


def view(rule: dict, doc: dict, copies: list[dict] | None = None) -> dict:
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
        "usages": usages(doc, rule, copies),
    }


def read(output_dir: str | Path) -> dict:
    """Every live rule of the application, and what the tab needs to edit one."""
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.load(output_dir=str(output_dir))
    doc = svc.doc
    why = busy(output_dir)
    from services import rule_links
    judged = rule_links.review_all(doc) if rule_links.has_candidates(doc) else []
    copies = rule_links.stale(doc, judged)
    rules = [view(r, doc, copies) for r in _live(doc.get("businessRules"))]
    names = {str(r.get("id")): r.get("name") for r in _live(doc.get("businessRules"))}
    # Workflow checks that say exactly what a rule says: offered, never done on
    # a read — the person presses "Use the rules" (PR #29 review).
    repeats = [{"rule": c["rule"], "ruleName": names.get(c["rule"]), "workflow": c["workflow"], "name": c["name"],
                "step": c["step"], "stepName": c.get("stepName")} for c in judged if c.get("same") is True]
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
        "repeats": repeats,
        "catalogue": catalogue(doc),
    }


# ---------------------------------------------------------------------------
# Checking a rule as the build would
# ---------------------------------------------------------------------------

_INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
MESSAGE_MAX = 1000


def _clean_action(a: Any) -> dict:
    """An action as the contract stores it: its own keys only (the editor's
    `id` is the editor's), and nothing empty."""
    if not isinstance(a, dict):
        raise RuleError("Each action must be an object.")
    out = {k: a[k] for k in _ACTION_KEYS if k in a and a[k] not in (None, "")}
    if out.get("type") not in ACTION_TYPES:
        raise RuleError(f"“{a.get('type')}” is not something a rule can do.")
    for k in ("field", "workflow", "valueMode"):
        if k in out and not isinstance(out[k], str):
            raise RuleError(f"An action's {k} is a name, not {type(out[k]).__name__}.")
    if "valueMode" in out and out["valueMode"] not in ("literal", "field", "formula"):
        raise RuleError("A value is written as it is, copied from a field, or worked out by a formula.")
    if "message" in out:
        if not isinstance(out["message"], str):
            raise RuleError("An action's message must be text.")
        out["message"] = str(out["message"]).strip()
        if len(out["message"]) > MESSAGE_MAX:
            raise RuleError(f"A message is at most {MESSAGE_MAX} characters.")
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


#: Fields every record has and no rule may write.
_SYSTEM_FIELDS = frozenset({"id", "createdAt", "updatedAt", "created_at", "updated_at"})
_NUM = r"-?\d+(?:\.\d+)?"


#: An action as the editor names it (frontend/src/types/business-rules.ts ACTION_META).
_ACTION_SAID = {
    "set_field": "Fill in a value", "set_default": "Fill in if left empty", "clear_field": "Empty a field",
    "show_error": "Stop and show a message", "set_visibility": "Show or hide a field",
    "set_required": "Make a field required", "set_readonly": "Lock or unlock a field",
    "set_options": "Limit the choices", "recommendation": "Suggest a value",
    "trigger_workflow": "Start a workflow", "send_notification": "Send a notification",
}


def _human(field: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", field).lower()


def _condition_problems(when: str, ent: dict | None) -> list[str]:
    """What the engine would read wrongly in a condition that parses: one that
    is not a yes/no, a value no record can have, a comparison of different
    kinds of thing, a pattern that can hang the app."""
    out: list[str] = []
    when = (when or "").strip()
    if not when or when in ("true", "false"):
        return out
    fields = {str(f.get("name")): f for f in (ent or {}).get("fields") or [] if isinstance(f, dict)}
    kinds = {n: _field_type(f) for n, f in fields.items()}
    bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', when)
    # A yes/no: a comparison, and/or/not, a function, or a yes/no field.
    if not re.search(r"[=<>!(]|\b(and|or|not|in|between)\b", bare):
        if not (bare in kinds and kinds[bare] == "boolean"):
            out.append(f"The condition “{when[:80]}” is not a yes-or-no question — compare something, "
                       "like amount > 5000 or status = \"open\".")
            return out
    # Every comparison, whichever way round it is written: A op B.
    for left, op, right in _comparisons(when):
        lk, rk = _operand_kind(left, kinds), _operand_kind(right, kinds)
        if lk[0] == "literal" and rk[0] == "field":
            left, right, lk, rk = right, left, rk, lk          # "archived" = status reads as status = "archived"
            op = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(op, op)
        if lk[0] != "field":
            continue
        name, k = lk[1], lk[2]
        said = _comparison_problem(name, k, op, right, rk, fields)
        if said:
            out.append(said)
    for m in re.finditer(r'(?<![\w])((?:previous\.)?[A-Za-z_]\w*)\s+in\s*\[([^\]]*)\]', when):
        name = m.group(1).removeprefix("previous.")
        if kinds.get(name) == "enum":
            choices = [str(v) for v in _enum_values(fields[name])]
            for val in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(2)):
                if val not in choices:
                    out.append(f"“{val}” is not one of {_human(name)}’s choices ({', '.join(choices)}).")
    # Patterns: written in the rule, valid in the app's engine, never one that can take forever.
    for m in re.finditer(r'\bmatches\s*\(\s*[^,()]+,\s*("(?:[^"\\]|\\.)*"|[^)]*)\s*\)', when):
        arg = m.group(1).strip()
        lit = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', arg)
        if not lit:
            out.append("A pattern is written in the rule, in quotes — not taken from a field, where anyone "
                       "saving a record could put a pattern that freezes the app.")
            continue
        said = _pattern_problem(lit.group(1).encode().decode("unicode_escape", errors="ignore"))
        if said:
            out.append(said)
    return out


_OPERAND = (r'(?:"(?:[^"\\]|\\.)*"|' + _NUM + r'|(?:date|time|date and time|today|now|duration)\s*\([^)]*\)'
            r'|(?:previous\.|user\.)?[A-Za-z_]\w*)')
_COMPARISON = re.compile(r'(?<![\w."])(' + _OPERAND + r')\s*(<=|>=|!=|=|<|>)\s*(' + _OPERAND + r')')


def _comparisons(when: str) -> list[tuple[str, str, str]]:
    return [(m.group(1), m.group(2), m.group(3)) for m in _COMPARISON.finditer(when)]


def _operand_kind(tok: str, kinds: dict[str, str]) -> tuple:
    """("field", name, kind) | ("literal", kind) | ("other",)."""
    tok = tok.strip()
    if tok.startswith('"'):
        inner = tok[1:-1]
        return ("literal", "date-text" if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?", inner) else "text", inner)
    if re.fullmatch(_NUM, tok):
        return ("literal", "number", tok)
    if tok in ("true", "false"):
        return ("literal", "boolean", tok)
    if tok == "null":
        return ("literal", "null", tok)
    if re.match(r"(date|today|now|date and time)\s*\(", tok):
        return ("literal", "date", tok)
    if tok.startswith("user."):
        return ("other",)
    name = tok.removeprefix("previous.")
    if name in kinds:
        return ("field", name, kinds[name])
    return ("other",)


def _comparison_problem(name: str, k: str, op: str, right: str, rk: tuple, fields: dict) -> str | None:
    """`name op right`, where `name` is a field of kind `k`."""
    what = _human(name).capitalize()
    if rk[0] == "literal" and rk[1] == "null":
        return None
    ordered = op in ("<", ">", "<=", ">=")
    if ordered and k in ("string", "enum", "boolean"):
        return (f"{what} is {'text' if k != 'boolean' else 'a yes/no'} — it cannot be more or less than "
                "something. Compare it with = or !=.")
    other = rk[1] if rk[0] == "literal" else rk[2] if rk[0] == "field" else None
    if other is None:
        return None
    same = {"number": {"number"}, "date": {"date", "date-text"}, "boolean": {"boolean"},
            "string": {"text", "string", "enum", "date-text"}, "enum": {"text", "string", "enum"}}
    if other not in same.get(k, {other}):
        shown = right if rk[0] == "literal" else _human(rk[1])
        kind_word = {"number": "a number", "date": "a date", "boolean": "yes/no (true or false)",
                     "string": "text", "enum": "one of a list"}[k]
        return f"{what} is {kind_word}; it is compared with {shown[:40]}, which is not."
    if k == "enum" and rk[0] == "literal" and op in ("=", "!="):
        choices = [str(v) for v in _enum_values(fields[name])]
        if rk[2] not in choices:
            return f"“{rk[2]}” is not one of {_human(name)}’s choices ({', '.join(choices)})."
    return None


def _pattern_problem(pattern: str) -> str | None:
    """A pattern the app's engine (JavaScript) runs safely, or why not."""
    if len(pattern) > 500:
        return "A pattern is at most 500 characters."
    if re.search(r"\(\?P[<=]", pattern):
        return f"The pattern “{pattern[:60]}” uses a form the app's engine does not read — named groups are (?<name>…)."
    if re.search(r"\(\?[aiLmsux-]+[:)]|\(\?#", pattern):
        return (f"The pattern “{pattern[:60]}” sets its options inside it, which the app's engine does not read. "
                "To match any case, list both: [Ss]enior.")
    try:
        re.compile(pattern.replace("(?<", "(?P<").replace("(?P<=", "(?<=").replace("(?P<!", "(?<!"))
    except re.error as exc:
        return f"The pattern “{pattern[:60]}” is not a valid pattern: {exc}."
    for body, quantified in _groups(pattern):
        if quantified and _ambiguous(body):
            return (f"The pattern “{pattern[:60]}” repeats a group that can match the same text in more than one "
                    "way, which can freeze the app on some text. Repeat a single class instead — (a|aa)+ is a+, "
                    "(a+)+ is a+ — or start each repeat with its own character, like (-[a-z]+)*.")
    return None


def _groups(p: str) -> list[tuple[str, bool]]:
    """Each group's body, and whether the group is repeated (*, +, {n,} or {n,m} with m > 1)."""
    out, stack, i, in_class = [], [], 0, False
    while i < len(p):
        c = p[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            stack.append(i)
        elif c == ")" and stack:
            start = stack.pop()
            body = re.sub(r"^\(\?(?::|<?[=!]|<[A-Za-z_]\w*>)", "(", p[start:i + 1])[1:-1]
            rest = p[i + 1:]
            q = re.match(r"[*+]|\{(\d+)(,(\d*))?\}", rest)
            repeated = bool(q) and (q.group(0) in "*+" or (q.group(2) is not None and (q.group(3) in ("", None)
                                    or int(q.group(3)) > 1)) or (q.group(1) and int(q.group(1)) > 1 and not q.group(2)))
            out.append((body, repeated))
        i += 1
    return out


def _top_level_split(body: str) -> list[str]:
    parts, depth, cur, i, in_class = [], 0, "", 0, False
    while i < len(body):
        c = body[i]
        if c == "\\":
            cur += body[i:i + 2]
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            parts.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    return parts + [cur]


#: The characters a set is judged over: printable ASCII, whitespace, a few beyond.
_ALPHABET = frozenset([chr(c) for c in range(32, 127)] + ["\t", "\n", "é", "ß", "٣", "\u00a0"])
_ALL = _ALPHABET


def _shorthand(code: str) -> frozenset:
    base = {"w": {c for c in _ALPHABET if c.isalnum() or c == "_"}, "d": {c for c in _ALPHABET if c.isdigit()},
            "s": {c for c in _ALPHABET if c.isspace()}}[code.lower()]
    return frozenset(_ALPHABET - base) if code.isupper() else frozenset(base)


def _class_set(inner: str) -> frozenset:
    neg = inner.startswith("^")
    inner = inner[1:] if neg else inner
    out, i = set(), 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            out |= _shorthand(nxt) if nxt in "wWdDsS" else {nxt}
            i += 2
            continue
        if i + 2 < len(inner) and inner[i + 1] == "-":
            lo, hi = c, inner[i + 2]
            out |= {x for x in _ALPHABET if lo <= x <= hi}
            i += 3
            continue
        out.add(c)
        i += 1
    return frozenset(_ALPHABET - out) if neg else frozenset(out)


def _units(seq: str) -> list[tuple[frozenset, bool]] | None:
    """A sequence as (the characters a unit can match, whether it repeats or is optional).
    None when the sequence has alternatives or groups beyond what is judged here."""
    units, i = [], 0
    while i < len(seq):
        c = seq[i]
        if c in "^$":
            i += 1
            continue
        if c == "\\":
            nxt = seq[i + 1:i + 2]
            if nxt in ("b", "B"):
                i += 2
                continue
            chars, i = (_shorthand(nxt) if nxt in "wWdDsS" else frozenset({nxt})), i + 2
        elif c == "[":
            j = i + 1
            while j < len(seq) and (seq[j] != "]" or j == i + 1):
                j += 2 if seq[j] == "\\" else 1
            chars, i = _class_set(seq[i + 1:j]), j + 1
        elif c == ".":
            chars, i = _ALL, i + 1
        elif c == "(":
            depth, j = 1, i + 1
            while j < len(seq) and depth:
                if seq[j] == "\\":
                    j += 2
                    continue
                depth += {"(": 1, ")": -1}.get(seq[j], 0)
                j += 1
            inner = re.sub(r"^\?(?::|<?[=!]|<[A-Za-z_]\w*>)", "", seq[i + 1:j - 1])
            if seq[i + 1:i + 3] in ("?=", "?!") or seq[i + 1:i + 4] in ("?<=", "?<!"):
                i = j                                        # a lookaround matches no characters
                continue
            sub = _units(inner) if len(_top_level_split(inner)) == 1 else None
            chars = frozenset().union(*(u[0] for u in sub)) if sub else _ALL
            inner_varies = sub is None or any(v for _, v in sub)  # ((a+))+ repeats a repeat
            i = j
        elif c in "|":
            return None
        else:
            chars, i = frozenset({c}), i + 1
        if c != "(":
            inner_varies = False
        q = re.match(r"[*+?]\??|\{\d+(,\d*)?\}\??", seq[i:])
        varies = bool(q) and not re.fullmatch(r"\{(\d+)\}\??", q.group(0))
        if q:
            i += len(q.group(0))
        units.append((chars, varies or inner_varies))
    return units


def _ambiguous(body: str) -> bool:
    """Can one repeat of `body` match a stretch the next repeat could also take?"""
    alternatives = _top_level_split(body)
    if len(alternatives) > 1:
        # Safe when each alternative is a fixed length and they start apart: (ab|cd)*, (\w|-)+.
        parsed = [_units(a) for a in alternatives]
        if any(u is None or not u or any(v for _, v in u) for u in parsed):
            return True
        firsts = [u[0][0] for u in parsed]
        return any(firsts[x] & firsts[y] for x in range(len(firsts)) for y in range(x + 1, len(firsts)))
    units = _units(body)
    if units is None:
        return True
    if not any(v for _, v in units):
        return False                                         # a fixed stretch, every time
    # A first (or last) unit that is fixed and that nothing else in the repeat can
    # match keeps the repeats apart: ([A-Z][a-z]*)+, (-[a-z]+)*, ([a-z0-9]+\.)+.
    for edge, rest in ((units[0], units[1:]), (units[-1], units[:-1])):
        chars, varies = edge
        if not varies and rest and not any(chars & other for other, _ in rest):
            return False
    return True


def _write_problem(t: str, field: str, a: dict, by_name: dict) -> str | None:
    """What a set/default/clear action would write, against the field it writes."""
    where = f"“{t.replace('_', ' ')}”"
    f = by_name.get(field)
    mode = str(a.get("valueMode") or "literal")
    if t == "clear_field" or mode == "literal":
        return _value_problem(field, f, a.get("value") if t != "clear_field" else None, where)
    said = _value_problem(field, f, None, where)            # identity fields, whatever the value
    if said or f is None:
        return said
    value = str(a.get("value") or "").strip()
    if not value:
        return f"{where}: say which {'field' if mode == 'field' else 'formula'} the value comes from."
    if mode == "field":
        src = by_name.get(value.removeprefix("previous."))
        if src is None:
            return f"{where}: {value[:40]} is not a field of this record."
        k_to, k_from = _field_type(f), _field_type(src)
        if k_to != k_from and not (k_to == "string" and k_from in ("enum", "number")):
            return f"{where}: {_human(field)} cannot take {_human(value)}’s value — they are different kinds of thing."
        return None
    from services.blueprint.feel_check import check_expressions
    bad = check_expressions([("v", value)]).get("v")
    if bad:
        return f"{where}: the formula “{value[:60]}” cannot be read: {bad}."
    # A formula that is one value or one field is checked like one.
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"|' + _NUM + r"|true|false", value):
        return _value_problem(field, f, value, where)
    if value in by_name:
        return _write_problem(t, field, {**a, "valueMode": "field"}, by_name)
    return None


def _value_problem(field: str, f: dict | None, value: Any, where: str) -> str | None:
    """A literal value a rule writes into a field, against that field's kind."""
    if field in _SYSTEM_FIELDS or (f or {}).get("primaryKey"):
        return f"{where}: {_human(field)} is the record's own identity — a rule cannot set it."
    if f is None or value in (None, ""):
        return None
    v = str(value).strip()
    if v.startswith('"') and v.endswith('"') and len(v) >= 2:
        v = v[1:-1]
    k = _field_type(f)
    if k == "number" and not re.fullmatch(_NUM, v):
        return f"{where}: {_human(field)} is a number, and “{v[:40]}” is not."
    if k == "boolean" and v.lower() not in ("true", "false"):
        return f"{where}: {_human(field)} is yes/no (true or false), not “{v[:40]}”."
    if k == "enum":
        choices = [str(c) for c in _enum_values(f)]
        if v not in choices:
            return f"{where}: “{v[:40]}” is not one of {_human(field)}’s choices ({', '.join(choices)})."
    if k == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?", v) and not v.startswith(("today", "now")):
        return f"{where}: {_human(field)} is a date (like 2026-10-21), not “{v[:40]}”."
    return None


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
    # Two rules setting one field: on a save where both act, one value is lost.
    mine = _sets(rule)
    if mine and rule.get("entity"):
        for other in _live(doc.get("businessRules")):
            if (str(other.get("id")) == str(rule.get("id")) or other.get("enabled") is False
                    or str(other.get("entity") or "") != str(rule["entity"])):
                continue
            both = sorted(mine & _sets(other))
            if both:
                fields = ", ".join(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", f).lower() for f in both)
                out.append(f"{other.get('id')} “{other.get('name')}” also sets {fields}: on a save where both act, "
                           "only one value is kept. Merge them, or give them conditions that never hold together.")
    return out


def _sets(rule: dict) -> set[str]:
    """The fields a rule writes: a table's outputs, or the values its actions set."""
    if (rule.get("kind") or "") == "decision_table":
        return {str(c.get("name")) for c in (rule.get("table") or {}).get("outputs") or [] if c.get("name")}
    return {str(a.get("field")) for a in list(rule.get("then") or []) + list(rule.get("otherwise") or [])
            if isinstance(a, dict) and a.get("field")
            and a.get("type") in ("set_field", "set_default", "clear_field")}


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
        problems.append("Write what the rule is, in one sentence.")
    ents = _entities(doc)
    ent = ents.get(str(rule.get("entity") or ""))
    fields = {str(f.get("name")) for f in (ent or {}).get("fields") or []}
    # Every record has these, whether or not the definition lists them.
    readable = fields | {"id", "createdAt", "updatedAt", "created_at", "updated_at"}
    flows = {str(w.get("id")) for w in _live(doc.get("workflows"))}
    if kind in ("condition_action", "decision_table") and ent is None:
        problems.append("Choose what this rule is about (for example, Expense).")
    if kind == "condition_action":
        if not str(rule.get("when") or "").strip():
            problems.append("Add the “If” part: when should the rule apply?")
        acts = list(rule.get("then") or []) + list(rule.get("otherwise") or [])
        # "When the amount is at most 5000 or there is a note: fine; otherwise
        # refuse" acts only in its otherwise — a rule, as long as it does
        # something on one side.
        if not acts:
            problems.append("Add what the rule does: under “Then”, press “Add an action”.")
        # Read by the engine's own parser now, beside whatever else is wrong —
        # not only once the rest is right.
        when = str(rule.get("when") or "").strip()
        if when and when != "true":
            from services.blueprint.feel_check import check_expressions
            bad = check_expressions([("when", when)]).get("when")
            if bad:
                problems.append(f"The condition “{when[:160]}” cannot be read: {bad}. Conditions are written like "
                                "amount > 5000 and category = \"travel\" (= not ==, and/or/not).")
            else:
                problems += _condition_problems(when, ent)
        if ent is not None:
            unknown = sorted(n for n in _condition_fields(str(rule.get("when") or "")) if n not in readable)
            if unknown:
                problems.append(f"The condition reads {', '.join(unknown)}, which {ent.get('name')} does not have "
                                f"(fields: {', '.join(sorted(fields))}).")
        by_name = {str(f.get("name")): f for f in (ent or {}).get("fields") or [] if isinstance(f, dict)}
        for a in acts:
            t = a.get("type")
            if t in ("set_field", "set_default", "clear_field", "set_visibility", "set_required",
                     "set_readonly", "set_options", "recommendation") and not a.get("field"):
                problems.append(f"“{_ACTION_SAID.get(t, t.replace('_', ' '))}” needs a field — choose which one.")
            if t in ("set_field", "set_default", "clear_field") and a.get("field"):
                said = _write_problem(t, str(a["field"]), a, by_name)
                if said:
                    problems.append(said)
            if t == "show_error" and not str(a.get("message") or "").strip():
                problems.append("“Stop and show a message” needs the message the person will see.")
            if t == "send_notification" and not str(a.get("message") or "").strip():
                problems.append("“Send a notification” needs the message to send.")
            if t == "trigger_workflow":
                if not a.get("workflow"):
                    problems.append("Choose which workflow the rule starts.")
                elif flows and str(a["workflow"]) not in flows:
                    problems.append(f"{a['workflow']} is not a workflow of this application.")
            if t == "set_options" and not a.get("options"):
                problems.append("“Limit the choices” needs the choices to offer.")
    if kind == "decision_table":
        table = rule.get("table") or {}
        if not table.get("inputs") or not table.get("outputs"):
            problems.append("A table rule needs at least one column to check and one column to fill in.")
        if not table.get("rules"):
            problems.append("A table rule needs at least one row.")
        policy = str(table.get("hitPolicy") or "F").upper()
        if policy == "R" or (policy == "C" and not table.get("aggregation")):
            problems.append("A table that sets a record's fields needs one value per field: use First, Unique, "
                            "Priority or Any — or Collect with a sum, count, minimum or maximum. Rule order and "
                            "plain Collect give a list, which only a workflow step can use.")
        agg = str(table.get("aggregation") or "").upper()
        if policy == "C" and agg and ent is not None:
            # A total is a number (smallest/largest may be a date): adding up or
            # counting categories would write a number into a list of words.
            by_field = {str(f.get("name")): f for f in ent.get("fields") or [] if isinstance(f, dict)}
            for col in table.get("outputs") or []:
                f = by_field.get(str(col.get("variableBinding") or col.get("name") or ""))
                kind = _field_type(f) if f else str(col.get("type") or "")
                fits = kind == "number" or (agg in ("MIN", "MAX") and kind == "date")
                if f is not None and not fits:
                    word = {"SUM": "adding up", "COUNT": "counting", "MIN": "taking the smallest",
                            "MAX": "taking the largest"}[agg]
                    problems.append(f"{_human(str(f.get('name'))).capitalize()} is "
                                    f"{'one of a list' if kind == 'enum' else kind}, so {word} the matches "
                                    "cannot fill it. Collect totals fill number fields; use First or Priority here.")
        outs = [str(c.get("variableBinding") or c.get("name") or "") for c in table.get("outputs") or []]
        if len(set(outs)) != len(outs):
            problems.append("Each “fill in” column must be a different field.")
        ins = [str(c.get("variableBinding") or c.get("name") or "") for c in table.get("inputs") or []]
        if len(set(ins)) != len(ins):
            problems.append("Each field to check is one column — put all its conditions in one cell.")
        by_name = {str(f.get("name")): f for f in (ent or {}).get("fields") or [] if isinstance(f, dict)}
        for ci, name in enumerate(outs):
            if name in _SYSTEM_FIELDS or (by_name.get(name) or {}).get("primaryKey"):
                problems.append(f"{_human(name).capitalize()} is the record's own identity — a table cannot set it.")
                continue
            f = by_name.get(name)
            if f is None or _field_type(f) not in ("number", "boolean", "date"):
                continue
            for ri, row in enumerate(table.get("rules") or [], 1):
                entries = row.get("outputEntries") or []
                cell = str(entries[ci]).strip() if ci < len(entries) else ""
                # A field's name or a formula is worked out when the row is used.
                if cell in ("", "-", "null") or cell in by_name or re.search(r"[()+*/]|\s[-+]\s", cell):
                    continue
                said = _value_problem(name, f, cell, f"Row {ri}")
                if said:
                    problems.append(said)
        for ci, name in enumerate(ins):
            f = by_name.get(name)
            if f is not None and _field_type(f) in ("number", "date"):
                for ri, row in enumerate(table.get("rules") or [], 1):
                    entries = row.get("inputEntries") or []
                    cell = str(entries[ci]).strip() if ci < len(entries) else ""
                    other = re.match(r"^(?:<=|>=|<|>|=|!=)\s*([A-Za-z_]\w*)$", cell)
                    if other and other.group(1) in by_name and _field_type(by_name[other.group(1)]) != _field_type(f):
                        problems.append(f"Row {ri}, {_human(name)}: it is compared with {_human(other.group(1))}, "
                                        "which is a different kind of thing.")
                continue
            if f is None or _field_type(f) not in ("string", "enum", "boolean"):
                continue
            for ri, row in enumerate(table.get("rules") or [], 1):
                entries = row.get("inputEntries") or []
                cell = str(entries[ci]).strip() if ci < len(entries) else ""
                if re.match(r"^(<=|>=|<|>)", cell):
                    problems.append(f"Row {ri}, {_human(name)}: it is text, so it cannot be more or less than "
                                    "something — list the values it may be.")
        if ent is not None:
            for col in list(table.get("inputs") or []) + list(table.get("outputs") or []):
                name = str(col.get("variableBinding") or col.get("name") or "")
                if name and name not in fields:
                    problems.append(f"The column “{name}” is not a field of {ent.get('name')}.")
            width_in, width_out = len(table.get("inputs") or []), len(table.get("outputs") or [])
            for i, row in enumerate(table.get("rules") or [], 1):
                if len(row.get("inputEntries") or []) != width_in or len(row.get("outputEntries") or []) != width_out:
                    problems.append(f"Row {i} is missing a cell — fill in every column.")
    if kind == "decision_table" and not problems:
        # The cells, overlaps and typos — read by the app's own engine.
        problems += [f["message"] for f in table_findings(rule) if f.get("severity") == "error"]
    problems = list(dict.fromkeys(problems))      # the same fault twice (then and otherwise) is said once
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
        # The sentence is the rule's identity too (its id is keyed on it): two
        # tables setting the same field are told apart by what they read and
        # by their name, or the second would be refused as the first.
        t = rule.get("table") or {}
        outs = ", ".join(str(c.get("name")) for c in t.get("outputs") or [])
        ins = ", ".join(str(c.get("name")) for c in t.get("inputs") or [])
        named = f" (“{rule['name']}”)" if rule.get("name") else ""
        return f"{ent}: {outs or 'values'} decided from {ins or 'nothing'} by a table{named}."
    effects = []
    for a in rule.get("then") or []:
        t, f = a.get("type"), _human(str(a.get("field") or ""))
        if t == "show_error":
            effects.append(f"it is not saved and the person sees “{a.get('message')}”")
        elif t == "set_field":
            effects.append(f"{f} is set to {a.get('value')}")
        elif t == "set_default":
            effects.append(f"{f} is filled in with {a.get('value')} if it is empty")
        elif t == "clear_field":
            effects.append(f"{f} is emptied")
        elif t == "set_required":
            msg = f" (“{a.get('message')}”)" if a.get("message") else ""
            effects.append(f"{f} must be filled in{msg}" if a.get("required") is not False else f"{f} is optional")
        elif t == "set_visibility":
            effects.append(f"{f} is {'shown' if a.get('visible', True) else 'hidden'}")
        elif t == "set_readonly":
            effects.append(f"{f} is locked")
        elif t == "trigger_workflow":
            effects.append(f"the workflow {a.get('workflow')} starts")
        elif t == "send_notification":
            effects.append(f"a notification is sent: “{a.get('message')}”")
        else:
            effects.append(f"{str(t).replace('_', ' ')} {f or ''}".strip())
    return f"{ent}: when {_when_said(str(rule.get('when') or ''))}, {', and '.join(effects) or 'nothing happens'}."


_SAID_OPS = [(r"\s*>=\s*", " is at least "), (r"\s*<=\s*", " is at most "), (r"\s*!=\s*", " is not "),
             (r"\s*>\s*", " is more than "), (r"\s*<\s*", " is less than "), (r"\s*=\s*", " is ")]


def _when_said(when: str) -> str:
    """A simple condition in words ("category is meals and amount is more than
    500"); anything with brackets or functions is left as it is written."""
    if not when or re.search(r"[()\[\]]", when):
        return when
    parts = re.split(r"(\s+and\s+|\s+or\s+)", when)
    out = []
    for p in parts:
        if re.fullmatch(r"\s+(and|or)\s+", p):
            out.append(f" {p.strip()} ")
            continue
        p = re.sub(r"\bprevious\.(\w+)", lambda m: f"the old {_human(m.group(1))}", p.strip())
        p = re.sub(r"\s*(=|!=)\s*null\b", lambda m: " is empty" if m.group(1) == "=" else " is filled in", p)
        for pat, said in _SAID_OPS:
            if re.search(pat, p):
                p = re.sub(pat, said, p, count=1)
                break
        p = re.sub(r'"([^"]*)"', r"\1", p)
        out.append(re.sub(r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b", lambda m: _human(m.group(0)), p))
    return "".join(out)


def normalise(payload: dict, doc: dict, *, existing: dict | None = None) -> dict:
    """The rule a payload describes, in the contract's shape. Unknown keys are
    dropped; what the tab does not send is kept from `existing`."""
    if not isinstance(payload, dict):
        raise RuleError("A rule must be an object.")
    base = dict(existing or {})
    # A rule written by the build may carry no `kind`: it is what it holds.
    stored_kind = base.get("kind") or (None if existing is None else
                                       "decision_table" if base.get("table") else
                                       "condition_action" if base.get("when") or base.get("then") else "statement")
    kind = str(payload.get("kind") or stored_kind or "condition_action")
    if kind not in KINDS:
        raise RuleError(f"“{kind}” is not a kind of rule.")
    if kind == "prerequisite" and (existing is None or existing.get("kind") != "prerequisite"):
        raise RuleError("A prerequisite is set up by Smith (it gates workflows); ask Smith in the chat.")
    rule: dict[str, Any] = {k: v for k, v in base.items()}
    rule["kind"] = kind
    for key in ("name", "statement", "entity", "when", "message"):
        if key in payload:
            val = payload[key]
            if val is not None and not isinstance(val, (str, int, float)):
                raise RuleError(f"The rule's {key} must be text.")
            # Control and invisible characters are not part of a name a person reads.
            text = _INVISIBLE.sub("", str(val)).strip() if val is not None else ""
            if not text:
                rule.pop(key, None)
            else:
                rule[key] = text
    if "scope" in payload:
        if payload["scope"] not in SCOPES:
            raise RuleError("Where a rule runs is one of: everywhere, form only, on save only.")
        rule["scope"] = payload["scope"]
    if "salience" in payload:
        try:
            rule["salience"] = int(payload.get("salience") or 0)
        except (TypeError, ValueError, OverflowError):
            raise RuleError("Priority must be a whole number.") from None
        if abs(rule["salience"]) > 1_000_000:
            raise RuleError("Priority is a whole number between -1000000 and 1000000.")
    if payload.get("enabled") is not None:              # null says nothing: kept as it is
        rule["enabled"] = bool(payload["enabled"])
    if "on" in payload:
        raw_on = payload.get("on") or []
        if not isinstance(raw_on, list) or any(str(x) not in ("create", "update") for x in raw_on):
            raise RuleError("A rule fires when a record is created, changed, or both.")
        on = [str(x) for x in raw_on]
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
    # A SENTENCE THAT NO LONGER SAYS WHAT THE RULE DOES. The rule's If or
    # Then was changed and its sentence left as it was ("above 5000" on a
    # rule now about 7000): Smith and people read the sentence, so it is
    # written again from the rule — unless the person wrote a new one.
    if (existing is not None and kind in ("condition_action", "decision_table") and stored_kind == kind
            and rule.get("statement") and rule.get("statement") == existing.get("statement")
            and any(rule.get(k) != existing.get(k) for k in ("when", "then", "otherwise", "table", "entity"))):
        rule.pop("statement", None)
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


def _fold_own_copies(svc: Any, rule_id: str) -> list[str]:
    """Before a rule changes, is switched off or is removed: a workflow step
    that says exactly what the rule says now is the rule's copy — it goes, so
    the workflow follows the rule from now on (otherwise the old copy would
    go on stopping saves the rule no longer stops). The workflows changed."""
    from services import rule_links
    try:
        done = rule_links.fold_copies(svc.doc, rule_ids={str(rule_id)})
    except Exception:  # noqa: BLE001 — the rule still changes; the copy stays as it was
        logger.exception("[rules] could not hand %s's workflow copies to the rule", rule_id)
        return []
    return sorted({d["workflow"] for d in done})


def link_copies(output_dir: str | Path) -> list[dict]:
    """Every workflow step proven to say exactly what a rule says is handed
    to the rule (see `services/rule_links`), when the person asks ("Use the
    rules" on the tab, or Smith) — an app built before the build did this
    keeps one rule, not a rule and its copy. Never on a read: opening the tab
    changes nothing (PR #29 review). Raises when Smith or a build is working
    on the app; nothing to do costs no write."""
    from services import rule_links
    from services.blueprint.projection import project_workflows
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    svc = BlueprintService.load(output_dir=str(output_dir))
    if not rule_links.has_candidates(svc.doc):
        return []
    if not any(c.get("same") is True for c in rule_links.review_all(svc.doc)):
        return []
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        before = svc.snapshot()
        done = rule_links.fold_copies(svc.doc)
        if not done:
            return []
        svc.validate()
        flows = sorted({d["workflow"] for d in done})
        said = "; ".join(f"{d['name']}: “{d['step']}” is now the rule {d['rule']}" for d in done)
        _commit(svc, before, "Business Rules: workflow checks that repeated a rule now follow the rule",
                said, sorted({d["rule"] for d in done}) + flows)
        app = Path(svc.output_dir) / "app"
        if app.is_dir():
            project_workflows(svc.doc, str(app))
        logger.info("[rules] %s: %s", Path(output_dir).name, said)
        return done


def follow_rule(output_dir: str | Path, rule_id: str, *, workflow: str, step: str, actor: str = "") -> dict:
    """The person's choice: a workflow's own check on the rule's fields is
    taken out, and the rule — checked when the workflow saves — decides."""
    from services import rule_links
    from services.blueprint.projection import project_workflows
    from services.blueprint.service import BlueprintService
    _guard_writable(output_dir)
    with write_lock(output_dir, timeout=TAB_LOCK_WAIT):
        _refuse_if_building(output_dir)
        svc = BlueprintService.load(output_dir=str(output_dir))
        rule = _find(svc.doc, rule_id)
        mine = rule_links.stale(svc.doc, rule_links.review_all(svc.doc))
        cand = next((c for c in mine if c["rule"] == str(rule_id)
                     and c["workflow"] == str(workflow) and c["step"] == str(step)), None)
        flow = next((w for w in _live(svc.doc.get("workflows")) if str(w.get("id")) == str(workflow)), None)
        if cand is None or flow is None:
            raise RuleError("That workflow no longer has its own check here. Reload the list.", status=404)
        before = svc.snapshot()
        if not rule_links.fold(flow, cand):
            raise RuleError("That check could not be taken out. Reload the list.", status=409)
        svc.validate()
        version = _commit(svc, before, f"Business Rules tab: let “{rule.get('name')}” decide in {flow.get('name')}"
                          + (f" (by {actor})" if actor else ""),
                          f"Took out {flow.get('name')}'s own check “{step}”; {rule_id} decides when it saves",
                          [str(rule_id), str(workflow)])
        app = Path(svc.output_dir) / "app"
        if app.is_dir():
            project_workflows(svc.doc, str(app))
        return {"rule": view(rule, svc.doc), "version": version}


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
        # onto that record. A new rule is what was sent: nothing of the
        # removed one survives (its `on`, `when`, scope, why it was removed).
        for k in [k for k in stored if k not in rule and k != "id"]:
            stored.pop(k)
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
        folded = _fold_own_copies(svc, rule_id)
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
                          f"Edited {rule_id} in the Business Rules tab", [str(rule_id), *folded])
        files = _project(svc, prerequisites=rule.get("kind") == "prerequisite" or bool(folded))
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
        folded = _fold_own_copies(svc, rule_id)
        for r in svc.doc.get("businessRules") or []:
            if isinstance(r, dict) and str(r.get("id")) == str(rule_id):
                r["status"] = "DEPRECATED"
                r["syncNote"] = "removed in the Business Rules tab"
                retire_asks(svc.doc, r, f"its rule {rule_id} was removed in the Business Rules tab")
        # A step running a rule that is gone never passes (it takes the
        # refusal path), so the rule leaves every workflow it was a step of —
        # whoever put it there, under whatever key.
        flows = []
        for flow in _live(svc.doc.get("workflows")):
            keys = [s.get("key") for s in flow.get("steps") or [] if isinstance(s, dict)
                    and s.get("type") == "decision" and str((s.get("config") or {}).get("rule") or "") == str(rule_id)]
            if [k for k in keys if _detach_in(flow, k)]:
                flows.append(str(flow.get("id")))
        flows = sorted(set(flows) | set(folded))
        if flows:
            svc.validate()
        version = _commit(svc, before, f"Business Rules tab: remove “{current.get('name')}”"
                          + (f" (by {actor})" if actor else ""),
                          f"Removed {rule_id} in the Business Rules tab", [str(rule_id), *flows])
        files = _project(svc, prerequisites=current.get("kind") == "prerequisite" or bool(flows))
        logger.info("[rules] %s: removed %s in the tab", Path(output_dir).name, rule_id)
        return {"removed": rule_id, "version": version, "files": files, "workflows": flows}


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
    "RuleError", "adopt", "building", "catalogue", "check", "create", "follow_rule", "has_definition",
    "keep_stated_rules", "link_copies",
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
    # A pattern that could hang the engine is not run, even here.
    unsafe = [p for p in problems if "pattern" in p]
    if unsafe:
        return {"ok": False, "problems": problems, "advice": []}
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
    """RULE-008 -> rule_008."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(rule_id).lower()).strip("_")
    return slug if slug.startswith("rule_") else f"rule_{slug}"


def usages(doc: dict, rule: dict, copies: list[dict] | None = None) -> dict:
    """Where a rule acts in the workflows:
    ``links`` — every workflow step that saves its record on a save the rule
    is for: the rule is checked there, by the app, always (services/rule_links);
    ``steps`` — extra steps that run it earlier in a workflow; ``starts`` —
    the workflows it starts; ``copies`` — a workflow's own yes/no step on the
    same fields that does not say what the rule says (left from a build, the
    rule edited since), which the person can hand over to the rule;
    ``saves`` — the workflows of `links`, kept for older screens."""
    from services import rule_links
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
    linked = rule_links.links(doc, rule)
    by_flow: dict[str, dict] = {}
    for ln in linked:
        by_flow.setdefault(ln["workflow"], {"workflow": ln["workflow"], "name": ln["name"]})
    own = [{k: c.get(k) for k in ("workflow", "name", "step", "stepName", "expression", "differs", "same",
                                         "unproven")}
           for c in copies or [] if c.get("rule") == str(rule.get("id")) and c.get("same") is not True]
    return {"steps": steps, "starts": started, "links": linked, "copies": own,
            "saves": list(by_flow.values()) if linked or not saves else saves}


def _flow_concerns(flow: dict, ent: dict) -> bool:
    """Does the workflow work with this record at all — name it, its table, or
    carry it as a variable (`expense.amount`)?"""
    # Names, not text: a page path that mentions /roles/ is not a Role.
    text = json.dumps(flow).lower()
    name = str(ent.get("name") or "")
    camel, snake = name[:1].lower() + name[1:], re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    whole = [f'"{str(ent.get("id") or "").lower()}"', f'"{str(ent.get("table") or "").lower()}"',
             f'"{camel.lower()}"', f'"{snake}"']
    if any(w != '""' and w in text for w in whole):
        return True
    return bool(re.search(r"(?<![\w/.])(?:" + re.escape(camel.lower()) + "|" + re.escape(snake) + r")\.\w", text))


def _a(noun: str) -> str:
    return f"{'an' if noun[:1].lower() in 'aeiou' else 'a'} {noun}"


def _refusal_message(rule: dict) -> str:
    for side in ("then", "otherwise"):
        for a in rule.get(side) or []:
            if (isinstance(a, dict) and a.get("type") in ("show_error", "set_required")
                    and a.get("required") is not False and str(a.get("message") or "").strip()):
                return str(a["message"]).strip()
    return str(rule.get("message") or "").strip() or f"Stopped by the rule “{rule.get('name') or rule.get('id')}”."


def attach(output_dir: str | Path, rule_id: str, *, workflow: str, after: str | None,
           on_refusal: str = "stop", actor: str = "", path: str = "then") -> dict:
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
    if path not in ("then", "else"):
        raise RuleError("After a yes/no step, say whether the check goes on its yes or its no path.")
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
        from services import rule_links
        if rule.get("kind") == "condition_action" and not rule_links.can_stop(rule):
            ent_name = (_entities(svc.doc).get(str(rule.get("entity") or "")) or {}).get("name") or "record"
            raise RuleError(f"This rule only fills in or changes values. It already does that every time a "
                            f"workflow saves {_a(ent_name)}, so it does not need its own step.")
        flow = next((w for w in _live(svc.doc.get("workflows")) if str(w.get("id")) == str(workflow)), None)
        if flow is None:
            raise RuleError(f"{workflow} is not a workflow of this application.", status=404)
        ent = _entities(svc.doc).get(str(rule.get("entity") or "")) or {}
        if ent and not _flow_concerns(flow, ent):
            raise RuleError(f"{flow.get('name')} does not work with a {ent.get('name')}, so this rule has nothing "
                            f"to read there. Choose a workflow that creates, changes or loads a {ent.get('name')}.")
        before = svc.snapshot()
        key = _step_key(rule_id)
        _detach_in(flow, key)
        steps = flow.setdefault("steps", [])
        by_key = {s.get("key"): s for s in steps if isinstance(s, dict)}
        if after is not None and after not in by_key:
            raise RuleError(f"The workflow has no step “{after}”.", status=404)
        if after is not None and by_key[after].get("type") in ("end", "end_event"):
            raise RuleError("A step cannot come after the end of the workflow — choose a step before it.")
        gate = rule_links.can_stop(rule)
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
            # After a yes/no step, on the path chosen: its yes (first) or no (second) way out.
            prev = by_key[after]
            pnext = list(prev.get("next") or [])
            idx = 1 if path == "else" else 0
            if idx == 1 and len(pnext) < 2:
                raise RuleError(f"“{prev.get('name') or after}” has no “no” path to put the check on.")
            follow = pnext[idx] if len(pnext) > idx else None
            if pnext:
                pnext[idx] = key
            else:
                pnext = [key]
            prev["next"] = pnext
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
