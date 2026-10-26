"""The agent step: a workflow hands one step to an assistant and carries on.

A step of type ``agent_step`` is for a judgement that needs LOOKUPS across records (a triage that reads a pet's history,
its prescriptions, its vaccinations and the vets' schedules before it answers). The assistant is one of the app's own
(``agentId``), or described by a short brief (``agentBrief``) from which the build makes a workflow-only assistant. It
hands back a structured result (``outputFields``) plus the same three things every time: how sure it is, whether a
person should look, and a sentence. How much it may do alone is a dial on the step (``autonomy``).

This module is the build side of that, in three parts, all deterministic:

* THE GATE (:func:`agent_step_problems`): what a step must be before the Blueprint takes it, as plain sentences the
  author can answer: the assistant exists (or the brief can be built), what later steps read is something the step
  returns, a comparison fits the type it compares, the assistant changes nothing the step did not name, the dial and the
  limits are inside their ranges, and the assistant cannot start the workflow it belongs to.
* THE STAGE (:func:`build_workflow_assistants`): after the steps are written, makes the workflow-only assistant for each
  step that has a brief and no assistant, saves it in the project's ``agent-definitions/`` (where the install picks it
  up with the app) and writes its id back into the step.
* THE FILES (:func:`load_assistants`, :func:`save_assistant`): what the project's assistants are and what they can do,
  read from the same definitions the app is built from.

Nothing here calls a model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

AGENT_STEP = "agent_step"
AGENT_DEFS_DIR = "agent-definitions"  # the project's assistants, beside the app (see agent_runtime_install)

OUTPUT_TYPES = ("string", "number", "boolean", "array", "object", "enum")
AUTONOMY = ("suggest", "limited", "full")
ON_FAILURE = ("human", "skip", "fail")
_NAME_RX = re.compile(r"^[a-z][A-Za-z0-9_]*$")

#: What a step stores whatever it was asked for (the contract's output envelope), and each field's type.
#: The pseudo-tool an assistant step answers through (runtime: `return_result`): no assistant tool may take the name.
RESULT_TOOL = "return_result"
#: The role the runtime runs an assistant step as; it is granted read access, by name, to what a step reads.
WORKFLOW_ROLE = "workflow"

ENVELOPE: dict[str, str] = {"ok": "boolean", "needsHuman": "boolean", "confidence": "number", "summary": "string",
                            "result": "object", "proposals": "array", "actions": "array", "usage": "object",
                            "error": "string", "reason": "string"}
#: Added to every answer by the runtime, so an output field may not take their names.
STANDARD_RESULT_FIELDS = ("confidence", "needsHuman", "summary")

#: Limit -> (lowest, highest, what the runtime uses when it is not written).
LIMITS: dict[str, tuple[int, int, int]] = {
    "maxActions": (1, 10, 3), "maxTurns": (1, 12, 6), "timeoutSec": (5, 300, 60), "maxTokens": (1000, 100000, 30000)}
DEFAULT_MIN_CONFIDENCE = 0.85

#: Workflow actions that move money. An assistant is never let to run these on its own.
_MONEY_ACTIONS = frozenset({"take_payment", "refund_payment", "create_checkout", "connect_account"})
_DELETE_ACTIONS = frozenset({"db_delete"})

_REF_RX = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_EXPRESSION_KEYS = ("expression", "condition", "when")


def _fold(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def agent_steps_of(workflow: dict) -> list[dict]:
    return [s for s in (workflow.get("steps") or []) if isinstance(s, dict) and s.get("type") == AGENT_STEP]


def _cfg(step: dict) -> dict:
    return step.get("config") if isinstance(step.get("config"), dict) else {}


def _strings(value: Any) -> Iterator[tuple[str, str]]:
    """``(key, text)`` for every string inside a config, keyed by the nearest dict key above it."""
    def walk(node: Any, key: str) -> Iterator[tuple[str, str]]:
        if isinstance(node, str):
            yield key, node
        elif isinstance(node, dict):
            for k, v in node.items():
                yield from walk(v, str(k))
        elif isinstance(node, list):
            for v in node:
                yield from walk(v, key)
    yield from walk(value, "")


# ---------------------------------------------------------------------------
# the project's assistants, as the gate needs to know them
# ---------------------------------------------------------------------------

@dataclass
class ToolFact:
    """One tool of an assistant, reduced to what the gate asks: its name, whether it changes data, and what it runs."""
    name: str
    writes: bool = False
    deletes: bool = False
    workflow: str = ""        # the workflow it starts (slug, id or name as the definition spells it)
    description: str = ""
    entity: str = ""          # the table a data tool reads or writes
    operation: str = ""       # list / get / create / update / delete, for a data tool


@dataclass
class Assistant:
    id: str
    name: str = ""
    workflow_only: bool = False
    tools: list[ToolFact] = field(default_factory=list)
    made_for: dict = field(default_factory=dict)

    @property
    def write_tools(self) -> list[ToolFact]:
        return [t for t in self.tools if t.writes]


def _tool_facts(graph: dict) -> list[ToolFact]:
    from services.agent_runtime_config import changes_data, tool_name

    out: list[ToolFact] = []
    taken: set[str] = set()
    for n in graph.get("nodes") or []:
        d = (n or {}).get("data") or {}
        if d.get("nodeType") != "tool" and (n or {}).get("type") != "tool":
            continue
        cfg = d.get("config") or {}
        name = tool_name(cfg.get("tool_name") or d.get("label"), taken, f"tool_{len(taken) + 1}")
        ttype = str(cfg.get("tool_type") or "function").lower()
        if ttype == "data_engine":
            op = str(cfg.get("operation") or "list").lower()
            spec = {"kind": "data", "operation": op}
        elif ttype == "workflow":
            spec = {"kind": "workflow"}
        elif ttype in ("api_call", "external"):
            spec = {"kind": "api", "method": str(cfg.get("method") or "GET").upper()}
        else:
            spec = {"kind": "function"}
        writes = changes_data(spec)
        out.append(ToolFact(name=name, writes=writes,
                            deletes=spec.get("operation") == "delete" or spec.get("method") == "DELETE",
                            workflow=str(cfg.get("workflow_id") or "") if ttype == "workflow" else "",
                            description=str(cfg.get("description") or ""),
                            entity=str(cfg.get("entity") or "") if ttype == "data_engine" else "",
                            operation=spec.get("operation", "")))
    return out


def assistant_of(graph: dict, stem: str = "") -> Assistant:
    from services.agent_runtime_config import safe_id

    cfg = graph.get("config") if isinstance(graph.get("config"), dict) else {}
    return Assistant(id=safe_id(graph.get("id") or stem), name=str(graph.get("name") or stem),
                     workflow_only=cfg.get("workflow_only") is True, tools=_tool_facts(graph),
                     made_for=cfg.get("made_for") if isinstance(cfg.get("made_for"), dict) else {})


def definitions_dir(output_dir: Any) -> Path:
    return Path(output_dir) / AGENT_DEFS_DIR


def load_assistants(output_dir: Any) -> dict[str, Assistant]:
    """``{id: Assistant}`` for every definition in the project's ``agent-definitions/``; ``{}`` when there are none."""
    out: dict[str, Assistant] = {}
    if not output_dir:
        return out
    d = definitions_dir(output_dir)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            graph = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(graph, dict):
            a = assistant_of(graph, f.stem)
            out[a.id] = a
    return out


def definition_hash(graph: dict) -> str:
    """What an assistant IS, apart from the bookkeeping about where it came from. A changed hash means a person has
    edited it since the build made it."""
    body = {k: graph.get(k) for k in ("id", "name", "description", "nodes", "edges")}
    cfg = dict(graph.get("config") or {})
    cfg.pop("made_for", None)
    body["config"] = cfg
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def brief_hash(brief: Any) -> str:
    from services.agent_suggest import clean_brief
    return hashlib.sha256(json.dumps(clean_brief(brief), sort_keys=True).encode("utf-8")).hexdigest()[:16]


def read_definition(output_dir: Any, agent_id: str) -> dict | None:
    f = definitions_dir(output_dir) / f"{agent_id}.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_assistant(output_dir: Any, graph: dict, *, workflow_id: str = "", step_key: str = "",
                   brief: Any = None) -> Path:
    """Write the assistant into the project's ``agent-definitions/`` with the note of where it came from and a hash of
    what was written, so a later build can tell an untouched assistant from one a person has edited."""
    graph = copy.deepcopy(graph)
    cfg = graph.setdefault("config", {})
    cfg.pop("made_for", None)
    cfg["made_for"] = {"workflowId": workflow_id, "stepKey": step_key,
                       "briefHash": brief_hash(brief) if brief is not None else "",
                       "builtHash": definition_hash(graph)}
    d = definitions_dir(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{graph['id']}.json"
    path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return path


def untouched(graph: dict) -> bool:
    """True when this definition is one the build made and nobody has edited since."""
    made = (graph.get("config") or {}).get("made_for")
    return isinstance(made, dict) and bool(made.get("builtHash")) and made["builtHash"] == definition_hash(graph)


# ---------------------------------------------------------------------------
# a step, resolved: who the assistant is and what it can do
# ---------------------------------------------------------------------------

@dataclass
class Effective:
    """The assistant a step would run: from its definition, or drawn from its brief."""
    source: str                                   # "definition" | "brief"
    tools: list[ToolFact]
    problems: list[str] = field(default_factory=list)
    #: The workflows the brief allows it to propose (their real tool names), for `source == "brief"`.
    sanctioned: set[str] = field(default_factory=set)


def _workflow_key(w: dict) -> str:
    return str(w.get("id") or "") or "name:" + _fold(w.get("name"))


def overlay_workflows(doc: dict, bodies: list[dict]) -> list[dict]:
    """The document's workflows with the ones being proposed standing in for the ones they replace."""
    rows = [w for w in _live(doc.get("workflows"))]
    out: list[dict] = []
    used: set[int] = set()
    for w in rows:
        hit = next((i for i, b in enumerate(bodies)
                    if (b.get("id") and b.get("id") == w.get("id")) or _fold(b.get("name")) == _fold(w.get("name"))), None)
        if hit is None:
            out.append(w)
        else:
            used.add(hit)
            out.append({**w, **bodies[hit]})
    out += [b for i, b in enumerate(bodies) if i not in used]
    return out


def _effective(step: dict, doc: dict, workflow: dict, workflows: list[dict],
               assistants: dict[str, Assistant] | None) -> Effective | None:
    """The assistant a step would run, or None when that cannot be told (no definitions to look in, no brief)."""
    from services.agent_suggest import resolve_brief_tools

    cfg = _cfg(step)
    agent_id = str(cfg.get("agentId") or "").strip()
    brief = cfg.get("agentBrief")
    if agent_id and assistants is not None and agent_id in assistants:
        a = assistants[agent_id]
        sanctioned: set[str] = set()
        if isinstance(brief, dict):
            sanctioned = {t["name"] for t in resolve_brief_tools({**doc, "workflows": workflows}, brief, host=workflow).writes}
        return Effective("definition", a.tools, sanctioned=sanctioned)
    if isinstance(brief, dict):
        # no assistant yet, or its file is gone: the brief is what the stage will build it from
        r = resolve_brief_tools({**doc, "workflows": workflows}, brief, host=workflow)
        tools = [ToolFact(t["name"]) for t in r.reads] + [
            ToolFact(t["name"], writes=True, workflow=str(t["workflow"].get("id") or t["workflow"].get("name") or ""))
            for t in r.writes]
        return Effective("brief", tools, problems=list(r.problems), sanctioned={t["name"] for t in r.writes})
    return None


def _workflow_ref(workflows: list[dict], ref: str) -> dict | None:
    from services.agent_suggest import workflow_for_tool
    return workflow_for_tool(workflows, ref)


def _actions_of(workflow: dict | None) -> set[str]:
    out: set[str] = set()
    for s in (workflow or {}).get("steps") or []:
        c = _cfg(s) if isinstance(s, dict) else {}
        if c.get("actionType"):
            out.add(str(c["actionType"]))
        for inner in c.get("steps") or []:
            if isinstance(inner, dict) and _cfg(inner).get("actionType"):
                out.add(str(_cfg(inner)["actionType"]))
    return out


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _output_problems(fields: Any) -> tuple[list[str], dict[str, dict]]:
    """``(problems, {name: field})`` for a step's `outputFields`."""
    problems: list[str] = []
    seen: dict[str, dict] = {}
    if not isinstance(fields, list) or not fields:
        return (["`outputFields` lists what the assistant hands back — at least one, each {name, type, description}: "
                 "the values a later step will use (e.g. urgency, a suggested vet)"], seen)
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            problems.append(f"outputFields[{i}] is {{name, type, description}}")
            continue
        name = f.get("name")
        if not isinstance(name, str) or not _NAME_RX.match(name):
            problems.append(f"outputFields[{i}].name {name!r} starts with a lower-case letter and holds letters, digits and "
                            "underscores only (urgency, suggestedVet)")
            continue
        if name in STANDARD_RESULT_FIELDS:
            problems.append(f"outputFields: {name!r} is returned by every assistant step already ("
                            f"{', '.join(STANDARD_RESULT_FIELDS)}), so a field cannot take that name — read it as "
                            f"{{{{<step>.{name}}}}} or choose another name")
            continue
        if name in seen:
            problems.append(f"outputFields: {name!r} is listed twice")
            continue
        kind = f.get("type")
        if kind not in OUTPUT_TYPES:
            problems.append(f"outputFields.{name}.type {kind!r} is one of {', '.join(OUTPUT_TYPES)}")
        elif kind == "enum":
            vals = f.get("values")
            if not isinstance(vals, list) or not vals or any(not isinstance(v, str) or not v for v in vals):
                problems.append(f"outputFields.{name} is an enum, so it lists its `values` (text, at least one)")
        elif f.get("values") is not None:
            problems.append(f"outputFields.{name}: `values` belongs to a field of type enum")
        if not isinstance(f.get("description"), str) or not f["description"].strip():
            problems.append(f"outputFields.{name} needs a `description`: one sentence the assistant reads to know what to put")
        if "required" in f and not isinstance(f["required"], bool):
            problems.append(f"outputFields.{name}.required is true or false")
        seen[name] = f
    return problems, seen


def _limit_problems(cfg: dict) -> list[str]:
    out: list[str] = []
    mc = cfg.get("minConfidence")
    if "minConfidence" in cfg and not (_is_number(mc) and 0 <= mc <= 1):
        out.append(f"`minConfidence` is a number from 0 to 1 (the share of certainty the assistant must report before it "
                   f"may act alone; {DEFAULT_MIN_CONFIDENCE} when left out), not {mc!r}")
    for key, (lo, hi, default) in LIMITS.items():
        if key in cfg:
            v = cfg[key]
            if not (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi):
                out.append(f"`{key}` is a whole number from {lo} to {hi} ({default} when left out), not {v!r}")
    return out


def _refs(text: str) -> Iterator[tuple[str, bool]]:
    """``(path, in_braces)`` for each name a string reads: inside `{{ }}`, a path."""
    for m in _REF_RX.finditer(text):
        for side in m.group(1).split("??"):
            yield side.strip().split("|")[0].strip(), True


_LITERAL = r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?|true|false|null)"""


def _literal(token: str) -> tuple[str, Any]:
    t = token.strip()
    if t in ("true", "false"):
        return "boolean", t == "true"
    if t == "null":
        return "null", None
    if t[:1] in "\"'":
        return "string", t[1:-1]
    return "number", float(t)


def _downstream_problems(workflow: dict, step: dict, fields: dict[str, dict]) -> list[str]:
    """Everything a later step reads from this one, held to what this one hands back."""
    key = str(step.get("key") or "")
    if not key:
        return []
    out: list[str] = []
    seen: set[str] = set()
    returned = ", ".join(fields) or "nothing yet"
    for other in workflow.get("steps") or []:
        if not isinstance(other, dict) or other is step:
            continue
        where = str(other.get("key") or "?")
        for k, text in _strings(_cfg(other)):
            # a template names a value; an expression field names it bare
            paths = [p for p, _ in _refs(text)]
            bare = k in _EXPRESSION_KEYS
            if bare:
                paths += re.findall(rf"(?<![\w.]){re.escape(key)}(?:\.[A-Za-z_]\w*|\[\d+\])+", text)
            for path in paths:
                parts = [p for p in re.split(r"\.|\[\d+\]", path) if p]
                if not parts or parts[0] != key or len(parts) < 2:
                    continue
                tag = f"{where}:{path}"
                if tag in seen:
                    continue
                seen.add(tag)
                seg = parts[1]
                if seg not in ENVELOPE:
                    hint = (f" — what it returns is under `result`: {{{{{key}.result.{seg}}}}}" if seg in fields else
                            f" — an assistant step hands back {', '.join(ENVELOPE)}; its own fields are under `result` "
                            f"({returned})")
                    out.append(f"step {where!r} reads {{{{{path}}}}}, which the step {key!r} does not return{hint}")
                elif seg == "result" and len(parts) >= 3 and parts[2] not in fields:
                    out.append(f"step {where!r} reads {{{{{path}}}}}, but {key!r} returns only {returned} under `result` — "
                               f"add {parts[2]!r} to its outputFields or read one of those")
    # comparisons in a condition: `triage.result.urgency = "emergency"` must be a value urgency can have
    for other in workflow.get("steps") or []:
        if not isinstance(other, dict) or other is step:
            continue
        where = str(other.get("key") or "?")
        for k, text in _strings(_cfg(other)):
            if k not in _EXPRESSION_KEYS:
                continue
            for path, kind, values in _typed_paths(key, fields):
                for m in re.finditer(rf"(?<![\w.]){re.escape(path)}\s*(=|!=|<=|>=|<|>)\s*{_LITERAL}", text):
                    out += _comparison_problem(where, path, kind, values, m.group(1), m.group(2))
                for m in re.finditer(rf"(?<![\w.]){re.escape(path)}\s+in\s*\[([^\]]*)\]", text):
                    for lit in re.findall(_LITERAL, m.group(1)):
                        out += _comparison_problem(where, path, kind, values, "=", lit)
    return list(dict.fromkeys(out))


def _typed_paths(key: str, fields: dict[str, dict]) -> Iterator[tuple[str, str, list[str]]]:
    for name, f in fields.items():
        yield f"{key}.result.{name}", str(f.get("type") or "string"), [str(v) for v in f.get("values") or []]
    for name, kind in ENVELOPE.items():
        if kind in ("boolean", "number", "string") and name != "result":
            yield f"{key}.{name}", kind, []


def _comparison_problem(where: str, path: str, kind: str, values: list[str], op: str, token: str) -> list[str]:
    lit_kind, lit = _literal(token)
    ref = f"{{{{{path}}}}}"
    if lit_kind == "null":
        return []
    if kind == "enum":
        if op not in ("=", "!="):
            return [f"step {where!r} compares {path} with {op} — it is one of a fixed set of words ({', '.join(values)}); use = or !="]
        if lit_kind != "string" or str(lit) not in values:
            return [f"step {where!r} compares {path} with {token}, which is not one of its values ({', '.join(values)}) — "
                    f"the branch could never be taken"]
    elif kind == "number":
        if lit_kind != "number":
            return [f"step {where!r} compares the number {path} with {token}, which is not a number — write it without quotes "
                    f"(e.g. {path} >= 0.8)"]
    elif kind == "boolean":
        if lit_kind != "boolean" or op not in ("=", "!="):
            return [f"step {where!r} compares the yes/no value {path} with {token} — compare it with true or false using ="]
    elif kind == "string":
        if op not in ("=", "!="):
            return [f"step {where!r} compares the text {path} with {op} — text can only be compared with = or !="]
        if lit_kind != "string":
            return [f"step {where!r} compares the text {path} with {token}, which is not text — put it in quotes"]
    elif kind in ("array", "object"):
        return [f"step {where!r} compares {ref}, a list or record, with {token} — test something about it instead "
                f"(count({path}) > 0, or a field of it)"]
    return []


def _reachable(origin: dict, workflows: list[dict], edges: dict[str, set[str]]) -> list[str] | None:
    """A path of workflow names from `origin` back to itself through assistants' workflow tools, or None."""
    start = _workflow_key(origin)
    names = {_workflow_key(w): str(w.get("name") or w.get("id")) for w in workflows}
    stack = [(start, [names.get(start, start)])]
    seen: set[str] = set()
    while stack:
        node, path = stack.pop()
        for nxt in sorted(edges.get(node, ())):
            if nxt == start:
                return path + [names.get(start, start)]
            if nxt not in seen:
                seen.add(nxt)
                stack.append((nxt, path + [names.get(nxt, nxt)]))
    return None


def _edges(doc: dict, workflows: list[dict], assistants: dict[str, Assistant] | None) -> dict[str, set[str]]:
    """Workflow -> the workflows an assistant of one of its steps could start."""
    edges: dict[str, set[str]] = {}
    for w in workflows:
        for s in agent_steps_of(w):
            eff = _effective(s, doc, w, workflows, assistants)
            if eff is None:
                continue
            for t in eff.tools:
                if t.workflow:
                    target = _workflow_ref(workflows, t.workflow)
                    if target is not None:
                        edges.setdefault(_workflow_key(w), set()).add(_workflow_key(target))
    return edges


def step_problems(doc: dict, workflow: dict, step: dict, workflows: list[dict],
                  assistants: dict[str, Assistant] | None, edges: dict[str, set[str]] | None = None,
                  warnings: list[str] | None = None) -> list[str]:
    """Everything wrong with one agent step, each a plain sentence. ``assistants`` is None when the project's
    definitions are not to hand (a document-only check): then only what the document itself can say is checked.
    ``warnings``, when given, collects what is worth saying and never a reason to refuse."""
    from services.agent_suggest import brief_shape_problems

    cfg = _cfg(step)
    out: list[str] = []
    agent_id = str(cfg.get("agentId") or "").strip()
    brief = cfg.get("agentBrief")

    # who the assistant is
    if "agentId" in cfg and not isinstance(cfg["agentId"], str):
        out.append("`agentId` is the id of one of the app's assistants (text)")
    if not agent_id and brief is None:
        out.append("an assistant step needs an assistant: write `agentId` (one of the app's assistants) or `agentBrief` "
                   "({purpose, reads, mayChange?, instructions?}) and the build makes one for this step")
    if brief is not None:
        out += [f"the brief is not usable: {p}" for p in brief_shape_problems(brief)]
    eff = None
    if not out:
        eff = _effective(step, doc, workflow, workflows, assistants)
        if eff is not None and eff.problems:
            out += [f"the assistant cannot be built: {p[:1].upper() + p[1:]}" for p in eff.problems]
        elif eff is None and agent_id and assistants is not None:
            have = ", ".join(sorted(assistants)) or "none yet"
            out.append(f"it uses the assistant {agent_id!r}, which this app does not have (its assistants: {have}) — "
                       "name one of them, or write `agentBrief` and the build makes one")

    # the step hands its answer back through a tool of its own, so the assistant may not have one by that name
    if eff is not None and any(t.name == RESULT_TOOL for t in eff.tools):
        out.append(f"the assistant has a tool called {RESULT_TOOL!r}, which is the name the step gives its answer back "
                   "through — rename that tool, or give the step an assistant without it")

    # what it is asked, what it hands back
    if not isinstance(cfg.get("task"), str) or not cfg["task"].strip():
        out.append("`task` says what to do this time, in words, and may name values like {{pet.name}} — it is the message "
                   "the assistant receives")
    inp = cfg.get("input")
    if inp is not None and (not isinstance(inp, dict) or any(not isinstance(v, str) or "{{" not in v for v in inp.values())):
        out.append("`input` maps a name to a value from the workflow, written as a {{reference}} "
                   "(e.g. {\"pet\": \"{{pet.id}}\"})")
    problems, fields = _output_problems(cfg.get("outputFields"))
    out += problems

    # the dial, the limits, what to do when it fails
    autonomy = cfg.get("autonomy", "suggest")
    if autonomy not in AUTONOMY:
        out.append(f"`autonomy` is one of {', '.join(AUTONOMY)} (suggest when left out: the assistant only proposes), "
                   f"not {autonomy!r}")
        autonomy = "suggest"
    out += _limit_problems(cfg)
    if cfg.get("onFailure") not in ON_FAILURE:
        out.append(f"`onFailure` says what happens when the assistant cannot answer: {', '.join(ON_FAILURE)} — "
                   "`human` sends it to a person (right for anything risky)")
    allowed = cfg.get("allowedWriteTools")
    if allowed is not None and (not isinstance(allowed, list) or any(not isinstance(a, str) or not a.strip() for a in allowed)):
        out.append("`allowedWriteTools` is a list of tool names (text)")
        allowed = None
    allowed = [str(a).strip() for a in (allowed or [])]
    if autonomy in ("limited", "full") and not allowed:
        out.append(f"autonomy {autonomy!r} lets the assistant act on its own, so `allowedWriteTools` names the only tools "
                   f"it may run; with none to name, use autonomy \"suggest\"")

    # what the assistant can change, against what the step allows
    if eff is not None:
        writes = {t.name: t for t in eff.tools if t.writes}
        have = {_fold(n): n for n in writes}
        for a in allowed:
            real = have.get(_fold(a))
            if real is None:
                out.append(f"`allowedWriteTools` names {a!r}, but the assistant has no tool of that name that changes data "
                           f"(it has: {', '.join(writes) or 'none'})")
                continue
            if autonomy in ("limited", "full"):
                t = writes[real]
                target = _workflow_ref(workflows, t.workflow) if t.workflow else None
                acts = _actions_of(target)
                if t.deletes or acts & _DELETE_ACTIONS:
                    out.append(f"{a!r} deletes records, and an assistant is never allowed to do that on its own — leave it "
                               "out of `allowedWriteTools` so it stays a proposal a person approves")
                elif acts & _MONEY_ACTIONS:
                    out.append(f"{a!r} moves money, and an assistant is never allowed to do that on its own — leave it out "
                               "of `allowedWriteTools` so it stays a proposal a person approves")
        # nothing the step did not name: an assistant made from a brief changes only what the brief says;
        # one that already exists may carry other changes only if the step names them
        sanctioned = {_fold(n) for n in eff.sanctioned} | {_fold(a) for a in allowed}
        strays = [n for n in writes if _fold(n) not in sanctioned]
        if strays:
            mine = assistants.get(agent_id) if assistants and agent_id else None
            if eff.source == "definition" and mine is not None and not (mine.workflow_only and mine.id.startswith("wf_")):
                # One of the app's own chat assistants: at run time a change it was not allowed to make can only ever
                # become a proposal, so this is worth saying and never a reason to refuse.
                if warnings is not None:
                    warnings.append(f"the assistant {agent_id!r} can also change data with {', '.join(strays)}; this step "
                                    "does not allow them, so at run time they can only become proposals")
            elif eff.source == "definition":
                # An assistant the build made for a step is read-only plus exactly what the step names.
                out.append(f"the assistant made for this step can change data with {', '.join(strays)}, which the step does "
                           "not name — list what it may do in `agentBrief.mayChange` (it proposes them) or in "
                           "`allowedWriteTools`, or take the extra tools out of the assistant")

    # an assistant that can start the workflow it belongs to
    if eff is not None:
        edges = edges if edges is not None else _edges(doc, workflows, assistants)
        path = _reachable(workflow, workflows, edges)
        if path:
            out.append("the assistant could end up starting this workflow again (" + " -> ".join(path) + "): remove the "
                       "workflow it may run from the brief, or give the step an assistant that cannot run it")

    out += _downstream_problems(workflow, step, fields)
    return out


def agent_step_problems(bodies: list[dict], doc: dict | None,
                        assistants: "dict[str, Assistant] | Callable[[], dict[str, Assistant]] | None" = None,
                        warnings: list[str] | None = None) -> list[str]:
    """The gate for the workflows being proposed: ``"<workflow>/<step>: <sentence>"`` for each thing wrong with an agent
    step in them. Cheap when no workflow has one."""
    steps = [(b, s) for b in bodies if isinstance(b, dict) for s in agent_steps_of(b)]
    if not steps:
        return []
    doc = doc or {}
    known = assistants() if callable(assistants) else assistants
    workflows = overlay_workflows(doc, bodies)
    edges = _edges(doc, workflows, known)
    out: list[str] = []
    for body, s in steps:
        name = body.get("name") or body.get("id")
        workflow = next((w for w in workflows if (body.get("id") and w.get("id") == body.get("id"))
                         or _fold(w.get("name")) == _fold(body.get("name"))), body)
        said: list[str] = []
        out += [f"{name}/{s.get('key')}: {p}" for p in step_problems(doc, workflow, s, workflows, known, edges, said)]
        if warnings is not None:
            warnings += [f"{name}/{s.get('key')}: {w}" for w in said]
    return out


def agent_step_findings(doc: dict) -> list[dict]:
    """The same checks over a whole document, as findings, for the verification report. No project folder is to hand
    here, so a step naming an existing assistant is not checked for it (the build's stage does that)."""
    bodies = [w for w in _live(doc.get("workflows")) if agent_steps_of(w)]
    out: list[dict] = []
    for p in agent_step_problems(bodies, doc, None):
        wf_name, _, rest = p.partition("/")
        wf = next((w for w in bodies if str(w.get("name") or w.get("id")) == wf_name), {})
        out.append({"rule": "agent-step", "page": str(wf.get("id") or wf_name), "detail": p})
    return out


def mend(bodies: list[dict], doc: dict | None) -> list[str]:
    """What has one right answer: a tool named the way a person says it ("Book Appointment") is the tool's real name
    (`book_appointment`), so the runtime, which compares names exactly, finds it."""
    from services.agent_suggest import workflow_for_tool, _assistant_workflows, _snake

    said: list[str] = []
    doc = doc or {}
    workflows = overlay_workflows(doc, bodies)
    flows = _assistant_workflows({"workflows": workflows})

    def real(name: str) -> str:
        w = workflow_for_tool(flows, name)
        return _snake(str(w.get("name"))) if w is not None else name

    for body in bodies:
        for s in agent_steps_of(body):
            cfg = _cfg(s)
            where = f"{body.get('name') or body.get('id')}/{s.get('key')}"
            if isinstance(cfg.get("allowedWriteTools"), list):
                fixed = [real(a) if isinstance(a, str) else a for a in cfg["allowedWriteTools"]]
                if fixed != cfg["allowedWriteTools"]:
                    cfg["allowedWriteTools"] = fixed
                    said.append(f"{where}: allowedWriteTools names the tools by their real names")
            brief = cfg.get("agentBrief")
            if isinstance(brief, dict) and isinstance(brief.get("mayChange"), list):
                for m in brief["mayChange"]:
                    if isinstance(m, dict) and isinstance(m.get("tool"), str) and real(m["tool"]) != m["tool"]:
                        m["tool"] = real(m["tool"])
                        said.append(f"{where}: mayChange names the tool by its real name")
    return said


# ---------------------------------------------------------------------------
# the stage: make the assistants the steps need
# ---------------------------------------------------------------------------

@dataclass
class StageReport:
    built: list[str] = field(default_factory=list)       # ids written or rewritten
    kept: list[str] = field(default_factory=list)        # ids left exactly as they were
    problems: list[str] = field(default_factory=list)    # steps whose assistant could not be made, in words
    updated_workflows: list[str] = field(default_factory=list)
    grants: list[str] = field(default_factory=list)       # read access written to / taken from the ownership rules


def _same_target(graph: dict | None, workflow: dict, step_key: str) -> bool:
    made = ((graph or {}).get("config") or {}).get("made_for") or {}
    return isinstance(made, dict) and str(made.get("workflowId")) == str(workflow.get("id")) \
        and str(made.get("stepKey")) == step_key


def build_workflow_assistants(svc: Any, *, commit: bool = True) -> StageReport:
    """The workflow assistants the document's steps need, made and saved; ids written back into the steps.

    For each ``agent_step`` that has a brief:

    * no assistant yet, or its file gone: draw one from the brief and save it;
    * its file is there, the build made it, nobody has edited it, and the brief has changed since: draw it again;
    * its file is there and a person has edited it, or it is one of the app's own assistants: keep it exactly as it is.

    So a rebuild never duplicates an assistant, never resets one a builder has since changed, and gives every step
    the same assistant it had before. A step that already names an assistant keeps naming it."""
    from services.agent_suggest import BriefError, agent_for_brief, assistant_id_for
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result

    report = StageReport()
    output_dir = getattr(svc, "output_dir", None)
    if not output_dir:
        return report
    changed: dict[str, dict] = {}                       # workflow id -> the workflow body to write back
    for wf in _live(svc.doc.get("workflows")):
        if not wf.get("id"):
            continue
        for step in agent_steps_of(wf):
            cfg = _cfg(step)
            brief = cfg.get("agentBrief")
            key = str(step.get("key") or "")
            where = f"{wf.get('name') or wf.get('id')}/{key}"
            agent_id = str(cfg.get("agentId") or "").strip()
            if not isinstance(brief, dict):
                continue                                 # nothing to build from: the gate answers for a missing assistant
            aid = agent_id or assistant_id_for(wf, key)
            existing = read_definition(output_dir, aid)
            if existing is not None:
                regenerate = (untouched(existing) and _same_target(existing, wf, key)
                              and ((existing.get("config") or {}).get("made_for") or {}).get("briefHash") != brief_hash(brief))
                if not regenerate:
                    report.kept.append(aid)
                    if not agent_id:
                        changed.setdefault(str(wf["id"]), copy.deepcopy(wf))
                        _set_agent_id(changed[str(wf["id"])], key, aid)
                    continue
            try:
                made = agent_for_brief(svc.doc, brief, wf, step, agent_id=aid)
            except BriefError as exc:
                report.problems.append(f"{where}: {exc}")
                logger.warning("[workflow_agents] %s: %s", where, exc)
                continue
            save_assistant(output_dir, made["agent"], workflow_id=str(wf.get("id")), step_key=key, brief=brief)
            report.built.append(aid)
            if not agent_id:
                changed.setdefault(str(wf["id"]), copy.deepcopy(wf))
                _set_agent_id(changed[str(wf["id"])], key, aid)

    for wid, body in changed.items():
        key = _natural_key(svc, wid, body)
        result = AgentResult(task_id=f"TASK-workflow_agents-{wid}", agent="workflow", confidence=1.0,
                             proposals=[ArtifactProposal(section="workflows", natural_key=key, body=body)])
        try:
            apply_agent_result(svc, result, commit=commit)
        except Exception as exc:  # noqa: BLE001 — one workflow never costs the others its assistant
            report.problems.append(f"{body.get('name') or wid}: the assistant was made but could not be attached: {exc}")
            logger.warning("[workflow_agents] %s: %s", wid, exc)
        else:
            report.updated_workflows.append(wid)
    # What the assistants read must be readable by the role they run as; a step that is gone takes its grant with it.
    try:
        report.grants = sync_read_grants(svc, load_assistants(output_dir), commit=commit)
    except Exception as exc:  # noqa: BLE001 — the assistants stand; the grant is reported
        report.problems.append(f"read access for the assistants could not be recorded: {exc}")
        logger.warning("[workflow_agents] read grants: %s", exc)
    return report


def _set_agent_id(workflow_body: dict, step_key: str, agent_id: str) -> None:
    for s in agent_steps_of(workflow_body):
        if str(s.get("key") or "") == step_key:
            s.setdefault("config", {})["agentId"] = agent_id


def _natural_key(svc: Any, workflow_id: str, body: dict) -> str:
    """The key the allocator bound this workflow to, so the write is an update of it and never a second workflow."""
    try:
        from services.blueprint.ids import IdAllocator
        key = IdAllocator.load(output_dir=svc.output_dir).key_for(workflow_id)
        if key:
            return str(key)
    except Exception:  # noqa: BLE001 — a missing registry is not a reason to stop
        pass
    return str(body.get("name") or workflow_id)


# ---------------------------------------------------------------------------
# what the assistant may read, in the Blueprint where a person can see it
# ---------------------------------------------------------------------------

def _entity_folds(entity: dict) -> set[str]:
    from services.agent_suggest import _folds
    return _folds(entity.get("name")) | _folds(entity.get("table"))


def entities_read_by_steps(doc: dict, assistants: dict[str, Assistant] | None = None) -> list[dict]:
    """The records the document's assistant steps read: each step's brief `reads`, or, for a step that names an
    assistant and no brief, the records that assistant's own read tools open. Each once."""
    from services.agent_suggest import resolve_brief_tools

    entities = [e for e in _live((doc.get("data") or {}).get("entities")) if e.get("id")]
    found: dict[str, dict] = {}
    for w in _live(doc.get("workflows")):
        for step in agent_steps_of(w):
            cfg = _cfg(step)
            if isinstance(cfg.get("agentBrief"), dict):
                labels = {t["entity"] for t in resolve_brief_tools(doc, cfg["agentBrief"], host=w).reads}
                hits = [e for e in entities if str(e.get("name")) in labels]
            elif assistants and str(cfg.get("agentId") or "") in assistants:
                tables = {t.entity.lower() for t in assistants[str(cfg["agentId"])].tools
                          if t.entity and t.operation in ("list", "get")}
                hits = [e for e in entities if str(e.get("table") or "").lower() in tables]
            else:
                hits = []
            for e in hits:
                found[str(e["id"])] = e
    return list(found.values())


def sync_read_grants(svc: Any, assistants: dict[str, Assistant] | None = None, *, commit: bool = True) -> list[str]:
    """Give the role the runtime runs an assistant step as (`workflow`) READ access to the records its assistants read,
    and to nothing else, in `security.ownershipRules`, where it can be reviewed.

    That role has no id, so a record a person's own rule scopes (a vet sees only their own row) would return it no
    rows. `readRoles` on that rule names it: exempt on a read, never on a write, and only on the rules of the records
    the steps read. Deterministic and idempotent: run again it changes nothing; when a step goes (or stops reading a
    record) the grant is taken back. `attribution` rules filter nothing and an `everyone` rule needs none, so neither
    is touched. Returns a line for each rule changed."""
    sec = svc.doc.get("security")
    rules = [r for r in ((sec or {}).get("ownershipRules") or []) if isinstance(r, dict)]
    if not rules:
        return []
    wanted: set[str] = set()
    for e in entities_read_by_steps(svc.doc, assistants):
        wanted |= _entity_folds(e)
    from services.agent_suggest import _folds

    said: list[str] = []
    before = svc.snapshot() if commit else None
    snapshot = copy.deepcopy(svc.doc)
    for rule in rules:
        roles = [str(r) for r in rule.get("readRoles") or []]
        grant = (str(rule.get("kind") or "scope") != "attribution" and str(rule.get("reads") or "") != "everyone"
                 and WORKFLOW_ROLE not in (rule.get("unscopedRoles") or [])
                 and bool(_folds(rule.get("entity")) & wanted))
        if grant and WORKFLOW_ROLE not in roles:
            roles.append(WORKFLOW_ROLE)
            said.append(f"{rule.get('entity')}: the `{WORKFLOW_ROLE}` role may read it (an assistant step reads it)")
        elif not grant and WORKFLOW_ROLE in roles:
            roles.remove(WORKFLOW_ROLE)
            said.append(f"{rule.get('entity')}: the `{WORKFLOW_ROLE}` role no longer reads it (no assistant step does)")
        else:
            continue
        if roles:
            rule["readRoles"] = roles
        else:
            rule.pop("readRoles", None)
    if not said:
        return []
    try:
        svc.validate()
    except Exception:
        svc.doc.clear()
        svc.doc.update(snapshot)
        raise
    if commit:
        svc.commit(user_request="workflow_agents: read access for assistant steps",
                   smith_interpretation="; ".join(said), before=before, affected=[], tests=[])
    else:
        svc.save()
    return said


# ---------------------------------------------------------------------------
# who uses an assistant
# ---------------------------------------------------------------------------

def used_by(output_dir: Any, doc: dict | None, agent_id: str) -> list[dict]:
    """``[{workflowId, workflowName, stepId}]``: the workflows whose agent steps run this assistant.

    The workflows the app was built with are its definitions (`app/src/lib/workflows/definitions/*.json`, which the
    editor changes too), so those are read first; a project that has none yet is answered from the Blueprint."""
    out: list[dict] = []
    defs = Path(output_dir) / "app" / "src" / "lib" / "workflows" / "definitions" if output_dir else None
    if defs is not None and defs.is_dir():
        for f in sorted(defs.glob("*.json")):
            try:
                text = f.read_text(encoding="utf-8")
                if agent_id not in text:
                    continue
                data = json.loads(text)
            except (OSError, ValueError):
                continue
            for n in ((data.get("definition") or {}).get("nodes") or []) if isinstance(data, dict) else []:
                d = (n or {}).get("data") or {}
                if (n.get("type") == AGENT_STEP or d.get("nodeType") == AGENT_STEP) \
                        and str((d.get("config") or {}).get("agentId") or "") == agent_id:
                    out.append({"workflowId": f.stem, "workflowName": str(data.get("name") or f.stem),
                                "stepId": str(n.get("id") or "")})
        return out
    for w in _live((doc or {}).get("workflows")):
        for s in agent_steps_of(w):
            if str(_cfg(s).get("agentId") or "") == agent_id:
                out.append({"workflowId": str(w.get("id") or ""), "workflowName": str(w.get("name") or w.get("id") or ""),
                            "stepId": str(s.get("key") or "")})
    return out
