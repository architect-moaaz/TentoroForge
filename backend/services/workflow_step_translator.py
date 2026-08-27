"""Faithful planner-step → runtime-graph translator (working-app reliability).

The planner emits fully-specified workflow steps: {id, type, config{actionType,
table, fields, prompt, condition}, next, branches}. The legacy translators only
read {name, node_type, action}, build flat chains, and re-guess config — so all
that intelligence is lost and every node degrades to a no-op `custom`. This module
consumes the planner's ACTUAL schema and emits an engine-faithful {nodes, edges}
graph: real branching (next/branches → then/else edges) and config mapped into the
exact keys each runtime handler reads. Pure, deterministic, no I/O.
"""
from __future__ import annotations

import logging
import re
from typing import Any

# Still pure and deterministic — no I/O, no state. The logger exists only so
# that a graph shape INFERRED from array order (rather than read from the
# planner's declared `next`/`branches`) is visible in the build output instead
# of being silently indistinguishable from an authored one.
logger = logging.getLogger(__name__)

# The keys planners use for a gateway's two outgoing branches. Reading only
# "true"/"false" made a yes/no gateway's branches unreachable (register RT-9),
# so every spelling seen in real planner output is listed here. Add to these
# sets rather than adding another lookup somewhere else.
_TRUE_BRANCH_KEYS = {"true", "yes", "then", "y", "pass", "approved", "success"}
_FALSE_BRANCH_KEYS = {"false", "no", "else", "n", "fail", "rejected", "failure"}


def _first_key(branches: dict, keys: set[str]) -> str | None:
    """The first branch target whose key is in `keys`, case-insensitively."""
    for k, v in branches.items():
        if str(k).strip().lower() in keys and str(v or ""):
            return str(v)
    return None


def is_rich_step_list(steps: Any) -> bool:
    """True when `steps` is the planner's rich dict shape (carries config/branches/
    a typed graph), i.e. NOT the legacy prose `{name, node_type, action}` / str shape."""
    if not isinstance(steps, list) or not steps:
        return False
    for s in steps:
        if not isinstance(s, dict):
            continue  # skip a stray non-dict; keep scanning for a rich signal
        if isinstance(s.get("config"), dict) or isinstance(s.get("branches"), dict):
            return True
        if s.get("type") and ("next" in s or s.get("type") in ("trigger", "end")):
            return True
    return False


def _normalize_expression(expr: str) -> str:
    """Rewrite a JS-style predicate into FEEL-lite: `==`/`===` → `=`, `!==` → `!=`,
    `&&` → ` and `, `||` → ` or `. Leaves `>=`, `<=`, `!=`, quotes intact."""
    if not expr:
        return ""
    out = expr
    out = out.replace("===", "=").replace("!==", "!=")
    out = re.sub(r"(?<![<>!=])==(?!=)", "=", out)   # == → = (not part of >= <= != already)
    out = out.replace("&&", " and ").replace("||", " or ")
    return re.sub(r"\s+", " ", out).strip()


def _as_ref_map(fields: Any) -> dict:
    """['a','b'] → {'a':'{{a}}','b':'{{b}}'} (a values map bound to process vars)."""
    out: dict = {}
    if isinstance(fields, list):
        for f in fields:
            name = f if isinstance(f, str) else (f.get("name") if isinstance(f, dict) else None)
            if name:
                out[str(name)] = f"{{{{{name}}}}}"
    return out


def _values_from_fields(fields: Any, label: str, table: str | None = None) -> dict:
    """Build a db_update/db_insert `values` map from a bare `fields` list WITHOUT
    minting a destructive self-referential `{{status}}` ref for a state column.

    A `{{status}}` for a status column that no trigger supplies resolves to NULL at
    runtime and WIPES the column (the "button does nothing" defect). When the step
    label carries the intended state ("Set Picked Up" → "Picked Up") we emit that
    literal instead. Everything else — timestamps and genuine form fields — keeps
    `{{col}}` (a create form's dispatch supplies them; an unbacked lifecycle *At is
    converted to CURRENT_TIMESTAMP downstream by the healing pass, which has the full
    provided-var context this pure function lacks). Shares its status classification
    with the healing pass so author and heal never drift."""
    try:
        from services.workflow_mutation_guard import derive_status_literal, is_status_col
    except Exception:  # noqa: BLE001 — fall back to the plain ref map if unavailable
        return _as_ref_map(fields)
    out: dict = {}
    if not isinstance(fields, list):
        return out
    for f in fields:
        name = f if isinstance(f, str) else (f.get("name") if isinstance(f, dict) else None)
        if not name:
            continue
        col = str(name)
        # `table` lets the guard reject a label that merely names the record
        # ("Update Order" -> "Order"), which would be written into the status
        # column as if it were a state (register T3-11).
        lit = derive_status_literal(label, table) if is_status_col(col) else None
        out[col] = lit if lit else f"{{{{{col}}}}}"
    return out


def _resolve_mutation_values(cfg: dict, fields: Any, label: str,
                             table: str | None = None) -> dict:
    """Resolve a db_update/db_insert `values` map with a strict source priority:

    1. an EXPLICIT authored literal `values` map (A2 — the planner/author supplied
       the concrete target state, e.g. `{"status":"Approved","approvedAt":"CURRENT_TIMESTAMP"}`)
       → written VERBATIM. This is the judgment only the author has; nothing overrides it
       (mixed literal + genuine `{{formField}}` entries are kept as-authored).
    2. else label-derivation from `fields` (the #6 fallback: a status literal recovered
       from the step label; timestamps/plain fields keep `{{col}}`).
    3. else the authored self-ref/form-field map is kept for the mutation guard net.

    So an explicit literal beats label-derivation, and label-derivation beats a pure
    self-ref — author > derive > self-ref."""
    authored = cfg.get("values")
    if isinstance(authored, dict) and authored:
        try:
            from services.workflow_mutation_guard import has_explicit_literal
        except Exception:  # noqa: BLE001 — fall back to verbatim if unavailable
            return authored
        if has_explicit_literal(authored):
            # (1) author's concrete intent wins PER COLUMN — but a column
            # declared in `fields` with no authored value is still a real
            # input (a trigger-form field like originalFilename). Dropping
            # it ships an insert that ignores the form data (atb0m97x
            # upload: values={status,uploadedAt} while the user's
            # originalFilename/filePath vanished → validation reject).
            # Merge: authored literals verbatim + `{{col}}` refs for the
            # remaining declared fields (status-wipe guard still applies
            # inside _values_from_fields).
            derived = _values_from_fields(fields, label, table)
            merged = {**{k: v for k, v in derived.items() if k not in authored},
                      **authored}
            return merged
        derived = _values_from_fields(fields, label, table)
        return derived or authored             # (2) label-derive over (3) self-refs
    return _values_from_fields(fields, label, table)  # (2) no authored values at all


def _translate_config(cfg: dict, label: str = "") -> dict:
    """Map one planner step config into the exact keys the runtime handler reads.
    Faithful: carries the planner's table/fields/prompt/template verbatim; never
    re-guesses. Unknown keys pass through so nothing is silently dropped.

    `label` (the humanized step id, e.g. "Set Picked Up") lets db_update/db_insert
    values recover a status literal instead of a destructive self-referential ref."""
    at = str(cfg.get("actionType") or "").strip()
    out: dict = {k: v for k, v in cfg.items() if k not in ("fields",)}
    out["actionType"] = at
    fields = cfg.get("fields")

    if at == "db_insert":
        out["values"] = _resolve_mutation_values(cfg, fields, label, cfg.get("table"))
    elif at == "db_update":
        out["where"] = cfg.get("where") or {"id": "{{id}}"}
        out["values"] = _resolve_mutation_values(cfg, fields, label, cfg.get("table"))
    elif at in ("db_delete", "db_query"):
        out["where"] = cfg.get("where") or {"id": "{{id}}"} if at == "db_delete" else cfg.get("where", {})
    elif at == "ai_extract":
        if cfg.get("prompt"):
            out["aiPrompt"] = cfg["prompt"]
        out["aiExtractFields"] = cfg.get("aiExtractFields") or (fields if isinstance(fields, list) else [])
        out.setdefault("aiInput", cfg.get("input") or "{{input}}")  # exec-contract group 2
    elif at == "ai_decide":
        if cfg.get("prompt"):
            out["aiPrompt"] = cfg["prompt"]
        if isinstance(cfg.get("options"), list):
            out["aiOptions"] = cfg["options"]
    elif at in ("ai_generate", "ai_classify"):
        if cfg.get("prompt"):
            out["aiPrompt"] = cfg["prompt"]
        out.setdefault("aiInput", cfg.get("input") or "{{input}}")
    elif at == "send_notification":
        # runtime reads message/toRole; executability requires one of
        # recipient/to/userId/channel/recipientRole → default channel keeps it valid
        # AND the handler always persists in-app, so it's honest.
        out["message"] = cfg.get("message") or cfg.get("body") or cfg.get("template") or ""
        out.pop("template", None)  # for notifications, template WAS the message
        out["toRole"] = cfg.get("recipientRole") or cfg.get("toRole") or "admin"
        out.setdefault("channel", "in_app")
    elif at == "send_email":
        out["body"] = cfg.get("body") or cfg.get("message") or cfg.get("template") or ""
        out.pop("template", None)
        # Preserve an explicit recipient the planner supplied (either a
        # literal `to@example.com` or a `{{some.email}}` binding). The old
        # translator dropped this even when the planner set it, forcing
        # every send_email node to fall through to the role→email lookup
        # or the in-app fallback. Keep `recipientRole` too — the runtime
        # uses it as a fallback when `to` doesn't resolve.
        for k in ("to", "email", "recipient"):
            if cfg.get(k):
                out["to"] = cfg[k]
                break
        # executability group 1 needs to/recipient/recipientRole
        out["recipientRole"] = cfg.get("recipientRole") or cfg.get("toRole") or "admin"
    elif at == "generate_document":
        # template here is the template id — keep it; carry fields as `data`
        if isinstance(fields, list) and fields:
            out.setdefault("data", _as_ref_map(fields))
    elif at == "ocr_document":
        # Accept planner aliases: file / fileRef / document → canonical ocrFileRef.
        # Default to {{input}} so a workflow triggered by a document upload
        # (trigger emits `input` = the uploaded file) OCRs it without config.
        for k in ("ocrFileRef", "fileRef", "file", "document"):
            if cfg.get(k):
                out["ocrFileRef"] = cfg[k]
                break
        out.setdefault("ocrFileRef", "{{input}}")
        # Pages: normalise scalar → single-item list, keep list as-is.
        pages_raw = cfg.get("ocrPages") or cfg.get("pages")
        if pages_raw is not None:
            out["ocrPages"] = pages_raw if isinstance(pages_raw, list) else [pages_raw]
        # Language: keep whatever the planner set (ISO 639-1 or PaddleOCR code).
        for k in ("ocrLanguage", "language", "lang"):
            if cfg.get(k):
                out["ocrLanguage"] = cfg[k]
                break
    # custom/transform/set_variable and any other: pass-through (already copied above)
    return out


# planner-level node types → runtime node types (mirror workflow_generator aliases)
# NOTE: `escalation` used to be aliased to "action", which destroyed its
# semantics — the engine has a dedicated `escalation` case (engine.ts:442)
# that reads slaHours/escalateTo and drives escalation.ts. Aliasing turned
# it into an actionType="" bare action → "No handler" skip. Keep it as its
# own node type instead. See workflow-audit P1-10.
_NODE_ALIASES = {"assignment": "user_task", "task_pool": "user_task",
                 "decision_table": "decision"}
# a step whose `type` is a bare actionType (no wrapping "action") → an action node.
# NOTE: the ai_* types are deliberately NOT here — the editor's canonical AI node is a
# TOP-LEVEL node type (`type:"ai_generate"`), and the runtime NodeType union lists them
# as node types too. So a step typed `ai_generate` must fall through to the node-type
# branch in _resolve_node_type and resolve to ("ai_generate", None), not ("action", …).
# The legacy `action`+config.actionType:"ai_generate" shape is still honored via the
# config.actionType fallback (back-compat).
_ACTIONTYPES = {"db_query", "db_insert", "db_update", "db_delete", "http_call",
                "send_email", "send_notification", "set_variable", "transform", "custom",
                "generate_document", "ocr_document",
                # R3 event-bus nodes — emit a durable forge_events row /
                # pause until a matching event arrives.
                "emit_event", "wait_for_event"}
# AI node types that are valid BOTH as a top-level node type and as an action actionType.
_AI_TYPES = {"ai_generate", "ai_classify", "ai_extract", "ai_decide"}
_GATEWAYS = {"exclusive_gateway", "condition", "decision"}


def _humanize_id(sid: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\s]+", str(sid or "step")) if w) or "Step"


def _nonempty(v: Any) -> bool:
    """Mirror of workflow_executability._present: None / empty str|list|dict is absent."""
    if v is None:
        return False
    if isinstance(v, (dict, list, str)) and len(v) == 0:
        return False
    return True


def _snake_ident(sid: str) -> str:
    """A safe snake_case identifier derived from a step id (for a default var name)."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(sid or "")).strip("_").lower()
    return s or "value"


def _ensure_executable_action(config: dict, step_id: str, label: str) -> dict:
    """Deterministically backfill the executability-CRITICAL key when the planner
    (LLM non-determinism) omitted it, so EVERY action node this translator emits
    passes workflow_executability.action_node_executable — matching that module's
    `_REQUIRED` contract.

    Faithful & idempotent: a key is filled ONLY when none of its accepted aliases is
    already present, so a planner-provided variableName/prompt/expression is never
    overwritten. Only covers the cases `_translate_config` doesn't already guarantee
    (variable/compute/decide); db_* / send_* / generate_document / ai_extract are left
    untouched and NO db table is ever fabricated."""
    at = str(config.get("actionType") or "").strip()

    def _has(*keys: str) -> bool:
        return any(_nonempty(config.get(k)) for k in keys)

    if at == "set_variable":
        # _REQUIRED: one of variableName / name / var. The value key MUST
        # be `variableValue` — the runtime reads `variableValue` OR
        # `expression`, not `value`. Writing `value` (the old bug) made
        # backfilled progress markers set their variable to undefined.
        # See workflow-audit P1-10 (set_variable drift).
        if not _has("variableName", "name", "var"):
            config["variableName"] = _snake_ident(step_id)
            config.setdefault("variableValue", True)
    elif at in ("custom", "transform"):
        expr_keys = ("expression", "code", "handler") if at == "custom" \
            else ("expression", "mapping", "code", "template")
        if not _has(*expr_keys):
            # A bare custom/transform is a runtime no-op — convert it into an
            # executable progress marker rather than leaving a dead node.
            config["actionType"] = "set_variable"
            config["variableName"] = f"{_snake_ident(step_id)}_done"
            config["variableValue"] = True
    elif at == "ai_decide":
        # _REQUIRED: one of aiPrompt/prompt/aiContext/context/instruction/aiOptions/options
        if not _has("aiPrompt", "prompt", "aiContext", "context", "instruction",
                    "aiOptions", "options"):
            config["aiPrompt"] = f"Decide the outcome for: {label}."
    elif at in ("ai_generate", "ai_classify"):
        # _translate_config already defaults aiInput (so these pass); belt-and-suspenders
        # for the degenerate case where even that is somehow absent.
        if not _has("aiPrompt", "prompt", "instruction", "aiInput", "input",
                    "aiContext", "context"):
            config["aiPrompt"] = f"Process: {label}."
    return config


def _resolve_node_type(step: dict) -> tuple[str, str | None]:
    """Return (runtime_node_type, forced_actionType|None) for a planner step."""
    t = str(step.get("type") or "").strip().lower()
    if t in _NODE_ALIASES:
        return _NODE_ALIASES[t], None
    if t in _ACTIONTYPES:
        return "action", t
    if t in ("trigger", "action", "user_task", "approval", "wait", "end", "end_event",
             "exclusive_gateway", "condition", "decision", "parallel_gateway", "fork", "join",
             "escalation",
             "ai_generate", "ai_classify", "ai_extract", "ai_decide"):
        return t, None
    # fall back: infer from the config's actionType if present. A legacy
    # config.actionType of an AI type still resolves as an action node (the runtime
    # handles both the action form and the top-level ai_* node form).
    at = str((step.get("config") or {}).get("actionType") or "").strip()
    if at in _ACTIONTYPES or at in _AI_TYPES:
        return "action", at
    return "action", "custom"


def _translate_node(step: dict, idx: int) -> dict:
    ntype, forced = _resolve_node_type(step)
    cfg_in = dict(step.get("config") or {})
    if forced and not cfg_in.get("actionType"):
        cfg_in["actionType"] = forced

    if ntype in _GATEWAYS:
        expr = _normalize_expression(str(cfg_in.get("expression") or cfg_in.get("condition") or ""))
        config = {"nodeType": ntype, "expression": expr}
        # For DECISION nodes: preserve the decisionTable + outputMapping
        # config the planner supplied. The old translator built the config
        # from scratch (nodeType + expression only), silently dropping
        # decisionTable — so every planner-emitted decision reached the
        # runtime as `{skipped:true, reason:"no decision table"}`. See
        # workflow-audit P1-10.
        if ntype == "decision":
            for k in ("decisionTable", "outputMapping"):
                if cfg_in.get(k):
                    config[k] = cfg_in[k]
        label = _humanize_id(step.get("id"))
    elif ntype == "escalation":
        # Preserve slaHours/escalateTo/action verbatim so escalation.ts
        # receives the SLA policy the planner declared. Runtime keys read
        # in engine.ts:449-461.
        label = _humanize_id(step.get("id"))
        config = {"nodeType": "escalation"}
        for k in ("slaHours", "escalateTo", "action", "escalationAction",
                  "reminderIntervalHours"):
            if cfg_in.get(k) is not None:
                config[k] = cfg_in[k]
    elif ntype == "action":
        label = _humanize_id(step.get("id"))
        config = _translate_config(cfg_in, label)
        # Backfill executability-critical keys the planner may have omitted, so this
        # action node is guaranteed to pass action_node_executable.
        _ensure_executable_action(config, str(step.get("id") or f"step_{idx}"), label)
        config["nodeType"] = "action"
    elif ntype in ("end", "end_event"):
        config = {"nodeType": ntype}
        label = "Complete"
    elif ntype == "trigger":
        config = {"nodeType": "trigger", **cfg_in}
        label = _humanize_id(step.get("id"))
    elif ntype in _AI_TYPES:
        # Top-level AI node (canonical editor shape). Build the SAME AI config the
        # legacy `action`+actionType path builds (aiPrompt/aiInput/aiExtractFields/
        # aiOptions) by routing through _translate_config with the ai type as the
        # actionType — so both paths produce identical AI config. Then backfill any
        # executability-critical key, matching the action path.
        label = _humanize_id(step.get("id"))
        cfg_in.setdefault("actionType", ntype)
        config = _translate_config(cfg_in, label)
        _ensure_executable_action(config, str(step.get("id") or f"step_{idx}"), label)
        config["nodeType"] = ntype
    else:  # user_task / approval / wait passthrough
        label = _humanize_id(step.get("id"))
        config = _translate_config(cfg_in, label) if cfg_in.get("actionType") else {**cfg_in, "nodeType": ntype}
        config["nodeType"] = ntype

    return {
        "id": str(step.get("id") or f"step_{idx}"),
        "type": ntype,
        "position": {"x": 250, "y": idx * 120},
        "data": {"label": label, "nodeType": ntype, "config": config, "status": "idle"},
    }


def _find_end_id(steps: list) -> str | None:
    for s in steps:
        if str(s.get("type") or "").lower() in ("end", "end_event"):
            return str(s.get("id"))
    return None


def _translate_edges(steps: list) -> list:
    ids = {str(s.get("id")) for s in steps if isinstance(s, dict)}
    end_id = _find_end_id(steps)
    edges: list = []

    def add(src: str, tgt: str, etype: str = "default", label: str | None = None) -> None:
        if not tgt or tgt not in ids:
            return
        e: dict = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt,
                   "data": {"edgeType": etype}}
        if label:
            e["data"]["label"] = label
        if etype == "else":
            e["sourceHandle"] = "else"
        edges.append(e)

    for s in steps:
        sid = str(s.get("id"))
        stype = str(s.get("type") or "").lower()
        if stype in ("end", "end_event"):
            continue
        branches = s.get("branches")
        if isinstance(branches, dict) and branches:
            def _branch_target(raw: str) -> str:
                # missing / dangling branch target -> route to end so the
                # gateway always has both outgoing edges (never stalls at runtime)
                t = str(raw or "")
                return t if t in ids else (end_id or "")

            # Accept every spelling the planner actually emits.
            #
            # Only "true"/"false" were read, but planners emit "yes"/"no" at
            # least as often (and "then"/"else"). An unrecognised key produced
            # an empty target, which fell through to `end` — for BOTH edges.
            # So a gateway whose branches were spelled yes/no had its two real
            # branch bodies silently made unreachable: `approve` and `reject`
            # could never run, and nothing reported it.
            true_target = _first_key(branches, _TRUE_BRANCH_KEYS)
            false_target = _first_key(branches, _FALSE_BRANCH_KEYS)

            if true_target is None and false_target is None:
                # Nothing recognisable. Fall back to declaration ORDER rather
                # than dumping both edges on `end`, and say so — a gateway with
                # two unreachable branches is worse than a guessed one.
                ordered = [str(v) for v in branches.values() if str(v or "") in ids]
                true_target = ordered[0] if len(ordered) > 0 else None
                false_target = ordered[1] if len(ordered) > 1 else None
                logger.error(
                    "workflow_step_translator: gateway %r declares branch keys %s, "
                    "none of which is a recognised true/false key %s. Falling back "
                    "to declaration order (then=%r, else=%r). Both branches would "
                    "otherwise have been routed to `end` and become unreachable.",
                    sid, sorted(branches.keys()),
                    sorted(_TRUE_BRANCH_KEYS | _FALSE_BRANCH_KEYS),
                    true_target, false_target,
                )

            add(sid, _branch_target(true_target or ""), "then", "Yes")
            add(sid, _branch_target(false_target or ""), "else", "No")
            continue
        nxt = s.get("next")
        if nxt:
            add(sid, str(nxt))
            continue

        # A TRIGGER with no `next` is not a dead end — it is a workflow that
        # never starts.
        #
        # Treating it like any other dead-end wired trigger→end directly, which
        # made every other node unreachable. The graph gate then deleted them
        # all as unreachable, and the executability gate certified the empty
        # result because "zero action nodes" counted as executable. One missing
        # `next` on one step therefore produced a workflow that passed all
        # three gates and did nothing — this is the head of that chain.
        #
        # Connect it to the first real step instead, which is what the step
        # ORDER already implies, and say so.
        if stype == "trigger":
            first = next(
                (str(x.get("id")) for x in steps
                 if isinstance(x, dict)
                 and str(x.get("id")) not in (sid, end_id)
                 and str(x.get("type") or "").lower() not in ("trigger", "end", "end_event")
                 and str(x.get("id")) in ids),
                None,
            )
            if first:
                add(sid, first)
                logger.warning(
                    "workflow_step_translator: trigger %r declares no `next`; "
                    "connected it to the first step %r from array order. Without "
                    "this the whole graph is unreachable from the trigger.",
                    sid, first,
                )
                continue

        if end_id and sid != end_id:
            add(sid, end_id)  # dead-end → terminate at end
    return edges


def _has_connectivity(steps: list) -> bool:
    """True when any rich step carries explicit connectivity — a truthy `next` or a
    dict `branches`. False means the planner emitted the "array-order" variant (rich
    {id,type,config} in sequence, no next/branches), which the sequential fallback
    handles."""
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("next"):
            return True
        if isinstance(s.get("branches"), dict) and s.get("branches"):
            return True
    return False


def _translate_edges_sequential(steps: list) -> list:
    """Array-order fallback edge builder. When rich steps LACK connectivity, chain
    them in array order (trigger → step0 → step1 → … → end) and give each gateway a
    heuristic branch: then → the next step in order, else → end. Every gateway ends
    up with BOTH a then and an else edge; the graph is connected from the trigger and
    reaches end. Node config mapping is untouched — this only shapes edges."""
    ids = {str(s.get("id")) for s in steps if isinstance(s, dict)}
    end_id = _find_end_id(steps)
    edges: list = []

    def add(src: str, tgt: str, etype: str = "default", label: str | None = None) -> None:
        if not tgt or tgt not in ids:
            return
        e: dict = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt,
                   "data": {"edgeType": etype}}
        if label:
            e["data"]["label"] = label
        if etype == "else":
            e["sourceHandle"] = "else"
        edges.append(e)

    # trigger = first step typed "trigger", else the very first step
    trigger_id = None
    for s in steps:
        if str(s.get("type") or "").lower() == "trigger":
            trigger_id = str(s.get("id"))
            break
    if trigger_id is None and steps:
        trigger_id = str(steps[0].get("id"))

    # main = ordered steps excluding the trigger and the end (preserve array order)
    main = [s for s in steps
            if str(s.get("id")) not in (trigger_id, end_id)
            and str(s.get("type") or "").lower() not in ("end", "end_event")]

    prev = trigger_id
    i = 0
    while i < len(main):
        s = main[i]
        sid = str(s.get("id"))
        ntype = _resolve_node_type(s)[0]
        if ntype in _GATEWAYS:
            add(prev, sid, "default")
            next_step = main[i + 1] if i + 1 < len(main) else None
            next_ntype = _resolve_node_type(next_step)[0] if next_step else ""
            # If the next step is ITSELF a gateway, DON'T claim it as the
            # then-target and DON'T `i += 2` past it — it needs its own
            # then/else edges emitted on the next iteration. Pre-fix, two
            # adjacent gateways silently lost the second one's branches
            # (graph_gate then wired it straight to end). See workflow-audit
            # P1-8. Empty else-edge is still a heuristic loss (planner-level
            # branches under FORGE_PLANNER_V2 is the real cure).
            if next_step and next_ntype not in _GATEWAYS:
                # The guarded step is the THEN branch, and only that step.
                #
                # This used to send `else` straight to end and then keep
                # chaining every remaining step off the THEN target, so the
                # two branches were sequential rather than exclusive: the
                # true path inherited the entire rest of the workflow and the
                # false path did nothing at all. In real planner output that
                # shortlisted an applicant, emailed them, then rejected them
                # and emailed them again in a single run.
                #
                # There is no declared structure to recover here — this
                # builder only runs when the planner emitted no `next` and no
                # `branches`, so array order is genuinely all we have. But a
                # gateway whose branches are not mutually exclusive is not a
                # gateway. Read the array the only way that keeps the
                # exclusivity its own node type promises: "if the condition
                # holds, run the guarded step and finish; otherwise carry on
                # with the rest of the chain."
                then_target = str(next_step.get("id"))
                after = main[i + 2] if i + 2 < len(main) else None
                else_target = str(after.get("id")) if after else (end_id or "")

                add(sid, then_target, "then", "Yes")
                add(sid, else_target, "else", "No")
                # Terminate the then-branch so it cannot fall through into
                # the false path's body.
                add(then_target, end_id or "", "default")

                logger.warning(
                    "workflow_step_translator: gateway %r has no declared branches; "
                    "inferred then=%r / else=%r from array order. Planner-level "
                    "`branches` is the real cure — see FORGE_PLANNER_V2.",
                    sid, then_target, else_target,
                )

                # The edge into `after` is already emitted (as the else edge),
                # so the next iteration must not emit another one.
                prev = None
                i += 2   # consume the gateway AND its guarded then-step
            else:
                # No next step, or next is another gateway → route both
                # then and else at what we have. Then→next step (which
                # will get its own edges on the next iteration); else→end.
                fallback_then = str(next_step.get("id")) if next_step else (end_id or "")
                add(sid, fallback_then, "then", "Yes")
                add(sid, end_id or "", "else", "No")
                prev = sid
                i += 1
        else:
            # prev is None when the incoming edge was already emitted (the
            # else edge out of a gateway). Emitting another would duplicate it.
            if prev:
                add(prev, sid, "default")
            prev = sid
            i += 1

    # terminate the chain at end, unless prev already emits an edge (avoid a dup)
    if prev and prev != end_id and not any(e["source"] == prev for e in edges):
        add(prev, end_id or "", "default")
    return edges


_TRIGGER_TYPES = {"manual", "api_event", "schedule", "webhook", "db_change"}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "workflow").lower()).strip("-")
    return s or "workflow"


def _trigger_type(wf: dict, steps: list) -> str:
    raw = str(wf.get("trigger") or "").lower()
    if any(w in raw for w in ("schedule", "cron", "daily", "hourly", "weekly")):
        return "schedule"
    if any(w in raw for w in ("webhook", "http")):
        return "webhook"
    if raw in _TRIGGER_TYPES:
        return raw
    return "api_event"


def translate_workflow(wf: dict, models: dict | None = None,
                       table_names: set | None = None,
                       plan: dict | None = None) -> dict | None:
    """Translate a rich planner workflow → engine-faithful definition. Returns None
    when the steps aren't the rich shape (caller falls back to the legacy path).

    `models`/`table_names` are accepted for signature parity with the deterministic
    generator; the planner already supplies real table names in config, so they are
    only a last-resort hint and currently unused here.

    ``plan`` is optional — when supplied, IRF-M4-T3 kicks in: the workflow's
    ``owning_route`` (or ``ownerRoute`` / ``owning_page``) drives a per-route
    ``resolve_shape`` lookup, and ``workflows.executionMode`` from the effective
    shape is emitted as ``definition.trigger.submitMode``. Downstream form
    dispatchers + the runtime engine both read that key to honor the app's
    substrate contract (fire-and-forget vs await-with-progress vs streaming).
    Missing plan → historic behavior preserved byte-for-byte."""
    steps = wf.get("steps")
    if not is_rich_step_list(steps):
        return None

    # A stray non-dict step must not crash node/edge building — drop it.
    steps = [s for s in steps if isinstance(s, dict)]
    nodes = [_translate_node(s, i) for i, s in enumerate(steps)]
    # Guarantee a terminal end node exists (planner usually includes one).
    if not any(n["type"] in ("end", "end_event") for n in nodes):
        nodes.append({"id": "end", "type": "end", "position": {"x": 250, "y": len(nodes) * 120},
                      "data": {"label": "Complete", "nodeType": "end", "config": {"nodeType": "end"},
                               "status": "idle"}})
        steps = list(steps) + [{"id": "end", "type": "end"}]

    if _has_connectivity(steps):
        edges = _translate_edges(steps)              # explicit connectivity (unchanged)
    else:
        edges = _translate_edges_sequential(steps)   # array-order fallback
    ttype = _trigger_type(wf, steps)
    from services.workflow_process_variables import (
        derive_process_variables,
        strip_source,
    )
    process_vars = strip_source(derive_process_variables(wf, nodes))

    # IRF-M4-T3: emit workflows.executionMode from the OWNING route's effective
    # shape as trigger.submitMode. The runtime dispatcher + generated form
    # submit UX both key off this. Empty when no plan / no owning_route /
    # no app_shape — historic behavior preserved.
    trigger_block: dict = {"type": ttype}
    owning_route = wf.get("owning_route") or wf.get("ownerRoute") or wf.get("owning_page")
    if isinstance(plan, dict) and isinstance(owning_route, str) and owning_route.strip():
        from services.shape_profile_derived import resolve_shape as _resolve
        shape = _resolve(plan, owning_route.strip())
        mode = ((shape.get("workflows") or {}).get("executionMode")
                if isinstance(shape, dict) else None)
        if mode in ("fire-and-forget", "await-with-progress",
                    "streaming", "background-with-notification"):
            trigger_block["submitMode"] = mode

    return {
        "id": _slug(wf.get("name", "")),
        "name": wf.get("name", ""),
        "description": wf.get("description", ""),
        # Top-level `processVariables` — same key the runtime engine +
        # editor look at. Planner-authored entries win; `set_variable`
        # nodes and promoted output-mappings back-fill anything the planner
        # omitted so the picker isn't empty for LLM-authored workflows.
        "processVariables": process_vars,
        "definition": {
            "trigger": trigger_block,
            # Preserve the raw planner steps (for the editor/preview) so both
            # writers — _sync_workflows_from_plan and generate_workflow_definitions
            # — emit a consistent definition shape.
            "steps": wf.get("steps", []),
            "nodes": nodes,
            "edges": edges,
        },
    }
