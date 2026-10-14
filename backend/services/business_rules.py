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
import fcntl
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

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


def building(output_dir: str | Path) -> bool:
    """A build is writing this definition right now. Its document was loaded
    before the change and is saved after it, so a rule saved now would be
    overwritten when the build commits — refused instead, with the reason."""
    try:
        from services import run_registry
        snap = run_registry.ledger_snapshot(output_dir, turns=False)
    except Exception:  # noqa: BLE001 — not knowing is not "building"
        return False
    return bool(snap and snap.get("active"))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") not in _RETIRED]


def revision(rule: dict) -> str:
    """What the rule looks like now, as a short hash — the tab sends it back
    with an edit, and an edit of a rule that has changed since is refused."""
    return hashlib.sha256(json.dumps(rule, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


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


def catalogue(doc: dict) -> dict:
    """What a rule can name: the records with their fields (type, choices),
    the workflows it can start, the requirements it can cite."""
    entities = []
    for e in _live((doc.get("data") or {}).get("entities")):
        entities.append({
            "id": e.get("id"), "name": e.get("name"), "table": e.get("table"),
            "fields": [{"name": f.get("name"), "type": _field_type(f),
                        "enumValues": [str(v) for v in f.get("enumValues") or []],
                        "required": bool(f.get("required"))}
                       for f in e.get("fields") or [] if isinstance(f, dict) and f.get("name")],
        })
    return {
        "entities": entities,
        "workflows": [{"id": w.get("id"), "name": w.get("name")} for w in _live(doc.get("workflows"))],
        "requirements": [{"id": r.get("id"), "description": r.get("description")}
                         for r in _live(doc.get("requirements"))],
    }


def where_it_runs(rule: dict) -> str:
    """In the person's terms: `everywhere` (every save and live on the form),
    `form` (how the form looks only), `save` (every save, not the form),
    `before` (checked before the workflows it gates), `nowhere` (written
    down — nothing enforces it — or switched off)."""
    if rule.get("enabled") is False:
        return "nowhere"
    kind = rule.get("kind") or "statement"
    if kind == "prerequisite":
        return "before"
    if kind == "decision_table":
        return "everywhere" if rule.get("entity") and (rule.get("table") or {}).get("rules") else "nowhere"
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
        "requirements": [{"id": r, "description": reqs.get(str(r))} for r in rule.get("requirements") or []],
    }


def read(output_dir: str | Path) -> dict:
    """Every live rule of the application, and what the tab needs to edit one."""
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.load(output_dir=str(output_dir))
    doc = svc.doc
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
        "building": building(output_dir),
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
        if not rule.get("then"):
            problems.append("Add at least one thing the rule does when its condition holds.")
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
        if ent is not None:
            for col in list(table.get("inputs") or []) + list(table.get("outputs") or []):
                name = str(col.get("variableBinding") or col.get("name") or "")
                if name and name not in fields:
                    problems.append(f"The column “{name}” is not a field of {ent.get('name')}.")
            width_in, width_out = len(table.get("inputs") or []), len(table.get("outputs") or [])
            for i, row in enumerate(table.get("rules") or [], 1):
                if len(row.get("inputEntries") or []) != width_in or len(row.get("outputEntries") or []) != width_out:
                    problems.append(f"Row {i} does not have a cell for every column.")
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
    for key in ("then", "otherwise"):
        if key in payload:
            rule[key] = [_clean_action(a) for a in payload.get(key) or []]
    if "table" in payload:
        t = payload.get("table") or {}
        rule["table"] = {
            "hitPolicy": str(t.get("hitPolicy") or "F"),
            "inputs": [{k: c[k] for k in ("id", "name", "label", "type", "variableBinding") if k in c and c[k] not in (None, "")}
                       for c in t.get("inputs") or [] if isinstance(c, dict)],
            "outputs": [{k: c[k] for k in ("id", "name", "label", "type", "variableBinding") if k in c and c[k] not in (None, "")}
                        for c in t.get("outputs") or [] if isinstance(c, dict)],
            "rules": [{"inputEntries": [str(x) for x in r.get("inputEntries") or []],
                       "outputEntries": [str(x) for x in r.get("outputEntries") or []],
                       **({"annotation": str(r["annotation"])} if r.get("annotation") else {})}
                      for r in t.get("rules") or [] if isinstance(r, dict)],
        }
        for col in rule["table"]["inputs"] + rule["table"]["outputs"]:
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
    if building(output_dir):
        raise RuleError("Forge is building this app right now. Rules can be changed as soon as the build "
                        "finishes — the build would otherwise overwrite your change.", status=423)


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
        svc = BlueprintService.load(output_dir=str(output_dir))
        rule = normalise(payload, svc.doc)
        rule["origin"] = "editor"
        rule.setdefault("enabled", True)
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
        svc = BlueprintService.load(output_dir=str(output_dir))
        current = _find(svc.doc, rule_id)
        if expected and revision(current) != expected:
            raise RuleError("This rule was changed since you opened it (by Smith or someone else). "
                            "Reload it to see the change, then edit again.", status=409)
        if current.get("kind") == "prerequisite":
            allowed = {k: payload[k] for k in ("enabled", "name", "message", "statement") if k in payload}
            payload = allowed
        rule = normalise(payload, svc.doc, existing=current)
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
    return {"ok": not problems, "problems": problems, "runs": where_it_runs(rule),
            "statement": rule.get("statement")}


# ---------------------------------------------------------------------------
# What the person asked for is never lost
# ---------------------------------------------------------------------------

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
    cited = {str(x) for r in _live(doc.get("businessRules")) for x in r.get("requirements") or []}
    added: list[str] = []
    if any(str(r.get("id")) not in cited for r in stated):
        _ensure_registry(svc)
    for req in stated:
        rid = str(req.get("id"))
        if rid in cited:
            continue
        text = " ".join(str(req.get("description") or "").split())
        if not text:
            continue
        name = text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "…"
        stored = svc.upsert("businessRules", {
            "name": name, "statement": text, "kind": "statement", "origin": "brief", "enabled": True,
            "requirements": [rid], "status": "PROPOSED",
            "syncNote": "you asked for this; the build did not make it enforceable — open it to enforce it",
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
