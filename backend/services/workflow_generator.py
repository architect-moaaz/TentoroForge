"""Workflow Definition Generator — creates executable workflow JSON from plan.

Takes plan workflows (which have names, descriptions, and step lists) and
generates complete workflow definitions with:
  - Nodes (trigger, action, condition, approval, user_task, end)
  - Edges (connecting nodes in sequence with conditions)
  - Form bindings (which entity fields each user_task/approval needs)
  - Action configs (db_query, http_call, etc.)

The generated definitions are executed by the workflow engine at runtime.
The UI reads node types to render appropriate forms/buttons:
  - approval node → Approve/Reject buttons
  - user_task node → Form with bound fields
  - condition node → automatic evaluation
  - action node → automatic execution
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from services.workflow_executability import is_executable_workflow
from services.workflow_step_translator import is_rich_step_list, translate_workflow

logger = logging.getLogger(__name__)


def generate_workflow_definitions(
    output_dir: str,
    plan: dict,
    registry: dict | None = None,
) -> int:
    """Generate complete workflow JSON files from plan specifications.

    Reads plan.workflows, generates node/edge graphs, writes to workflows/*.json.
    Returns count of workflows generated.

    ``registry`` is the canonical resource registry (built from the SAME plan the
    schema builder used). It is the primary authority for db_insert/db_update table
    names so the workflow and schema can never drift; built here when not supplied.
    """
    workflows = plan.get("workflows", [])
    if not workflows:
        return 0

    root = Path(output_dir)
    wf_dir = root / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)

    if registry is None:
        try:
            from services.resource_registry import build_canonical_registry
            registry = build_canonical_registry(plan)
        except Exception as _re_err:  # never block generation on registry build
            logger.warning("resource registry unavailable for workflows: %s", _re_err)
            registry = None

    models = {m.get("name", ""): m for m in plan.get("data_models", [])}
    table_names = _load_table_names(output_dir)
    generated = 0

    archetype = (plan.get("archetype") or plan.get("app_archetype") or "").strip()
    try:
        from services.archetype_workflows import find_emitter as _find_archetype_emitter
    except Exception:  # pragma: no cover — archetype module optional
        _find_archetype_emitter = None  # type: ignore[assignment]

    for wf in workflows:
        wf_name = wf.get("name", "")
        if not wf_name:
            continue

        # An archetype may own a deterministic emitter for one of its named
        # workflows. Wins over the planner's step list and every LLM path —
        # the runtime primitives these workflows depend on (mcp_tool_call,
        # ai_identify_product, vision presets) cannot be reliably authored
        # step-for-step by the planner and needs domain-specific wiring.
        archetype_definition: dict | None = None
        if _find_archetype_emitter is not None:
            emitter = _find_archetype_emitter(archetype, wf_name)
            if emitter is not None:
                try:
                    archetype_definition = emitter(wf, plan, table_names, registry)
                    if archetype_definition is not None:
                        logger.info(
                            "workflow %s: using archetype-owned emitter for '%s'",
                            archetype, wf_name,
                        )
                except Exception as _ae:
                    logger.warning(
                        "archetype emitter for %s/%s failed (%s) — falling back",
                        archetype, wf_name, _ae,
                    )
                    archetype_definition = None

        steps = wf.get("steps", [])
        if archetype_definition is not None:
            definition = archetype_definition
        # Prefer the faithful translator for the planner's rich step shape so
        # AI prompts, db_insert/update tables+fields, and gateway branching are
        # honored verbatim. `definition` is the FULL workflow dict in every branch
        # (id/name/description/definition) — matching the helpers' return shape.
        elif is_rich_step_list(steps):
            translated = translate_workflow(wf, models, table_names)
            if translated is not None:
                definition = _ensure_trigger_node(translated, wf, models)
            elif steps:
                definition = _generate_from_step_dicts(wf, steps, models, table_names=table_names, registry=registry)
            else:
                definition = _generate_from_name(wf, models, table_names=table_names, registry=registry)
        elif isinstance(steps, list) and len(steps) > 0 and isinstance(steps[0], str):
            # Steps are just names — generate nodes from them
            definition = _generate_from_step_names(wf, steps, models, table_names=table_names, registry=registry)
        elif isinstance(steps, list) and len(steps) > 0 and isinstance(steps[0], dict):
            # Steps have detail — use them
            definition = _generate_from_step_dicts(wf, steps, models, table_names=table_names, registry=registry)
        else:
            # No steps — generate based on workflow name/description
            definition = _generate_from_name(wf, models, table_names=table_names, registry=registry)

        # Find the existing same-name file, if any. Overwrite it UNLESS it is
        # already executable — a non-empty-but-no-op stub (the early sync's old
        # output) must be replaced, but a good executable definition is kept.
        existing_files = list(wf_dir.glob("*.json"))
        target_file = None
        skip_write = False
        for ef in existing_files:
            try:
                existing = json.loads(ef.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if existing.get("name") == wf_name:
                target_file = ef
                if is_executable_workflow(existing):
                    skip_write = True  # keep the good one, don't clobber it
                break

        if skip_write:
            continue

        if target_file is None:
            target_file = wf_dir / f"{uuid.uuid4().hex[:8]}.json"

        # Wire ai_extract → db_insert so extracted fields actually persist.
        try:
            _wire_document_persist(definition, wf, models, table_names, registry=registry)
        except Exception as _pe:
            logger.warning("persist-wiring skipped for %s: %s", wf_name, _pe)

        # R1/R2: carry the plan's declared event/schedule trigger into the
        # emitted JSON as the top-level contract the runtime event bus +
        # cron scheduler read. Additive — absent for manual workflows.
        try:
            _contract = derive_trigger_contract(wf)
            if _contract:
                definition["trigger"] = _contract
        except Exception as _tc_err:  # noqa: BLE001 — never block generation
            logger.warning("trigger-contract skipped for %s: %s", wf_name, _tc_err)

        target_file.write_text(json.dumps(definition, indent=2), encoding="utf-8")
        generated += 1
        logger.info("Generated workflow definition: %s (%d nodes)", wf_name, len(definition["definition"]["nodes"]))

    return generated


def _ensure_trigger_node(full_wf: dict, wf: dict, models: dict) -> dict:
    """Guarantee the translated definition is engine-loadable: the runtime
    engine refuses any workflow whose ``definition.nodes`` has no trigger
    node ("No trigger node found"). The rich-step translator emits the
    plan's action graph verbatim, which has no trigger — historically a
    later heal patched one in, but an emitted file must never depend on a
    downstream repair to be executable. Prepend a trigger wired to the
    first node when missing."""
    defn = full_wf.get("definition") or {}
    nodes = defn.get("nodes") or []
    has_trigger = any(
        n.get("type") == "trigger"
        or (n.get("data") or {}).get("nodeType") == "trigger"
        for n in nodes if isinstance(n, dict)
    )
    if has_trigger or not nodes:
        return full_wf
    trigger_cfg = defn.get("trigger") or _infer_trigger(wf, models)
    trigger_node = {
        "id": "trigger",
        "type": "trigger",
        "position": {"x": 250, "y": -120},
        "data": {
            "label": f"Trigger: {trigger_cfg.get('type', 'api_event')}",
            "nodeType": "trigger",
            "config": trigger_cfg,
        },
    }
    first_id = nodes[0].get("id")
    defn["nodes"] = [trigger_node] + nodes
    edges = defn.get("edges") or []
    defn["edges"] = [{"id": f"e_trigger_{first_id}",
                      "source": "trigger", "target": first_id}] + edges
    full_wf["definition"] = defn
    return full_wf


def _generate_from_step_names(
    wf: dict, step_names: list[str], models: dict,
    step_meta: list[dict] | None = None,
    table_names: set[str] | None = None,
    registry: dict | None = None,
) -> dict:
    """Generate workflow definition from a list of step name strings. When
    `step_meta` is given (the planner's step dicts), the declared `node_type` is
    trusted over the keyword classifier. `table_names` (real Drizzle tables) lets
    create/update steps build executable db_insert/db_update configs."""
    nodes = []
    edges = []

    # Trigger node — schedule for periodic workflows, else api_event.
    trigger_id = "trigger"
    trigger_cfg = _infer_trigger(wf, models)
    if trigger_cfg.get("type") == "schedule":
        trigger_label = f"Schedule: {trigger_cfg.get('every', 'daily')}"
    else:
        trigger_label = f"Trigger: {trigger_cfg.get('event')}"
    nodes.append({
        "id": trigger_id,
        "type": "trigger",
        "position": {"x": 250, "y": 0},
        "data": {
            "label": trigger_label,
            "nodeType": "trigger",
            "config": trigger_cfg,
        },
    })

    prev_id = trigger_id
    for i, step_name in enumerate(step_names):
        node_id = f"step_{i}"
        meta = step_meta[i] if step_meta and i < len(step_meta) else None
        # Trust the planner's declared node_type when present/valid; else classify.
        node_type, forced_action = _resolve_step_node_type(meta, step_name)
        config = _build_step_config(step_name, node_type, wf, models, table_names,
                                    registry=registry, meta=meta)
        if forced_action and node_type == "action":
            config["actionType"] = forced_action

        nodes.append({
            "id": node_id,
            "type": node_type,
            "position": {"x": 250, "y": (i + 1) * 120},
            "data": {
                "label": _humanize(step_name),
                "nodeType": node_type,
                "config": config,
            },
        })

        edges.append({
            "id": f"e_{prev_id}_{node_id}",
            "source": prev_id,
            "target": node_id,
        })
        prev_id = node_id

    # End node
    end_id = "end"
    nodes.append({
        "id": end_id,
        "type": "end",
        "position": {"x": 250, "y": (len(step_names) + 1) * 120},
        "data": {"label": "Complete", "nodeType": "end"},
    })
    edges.append({"id": f"e_{prev_id}_{end_id}", "source": prev_id, "target": end_id})

    from services.workflow_process_variables import (
        derive_process_variables,
        strip_source,
    )
    process_vars = strip_source(derive_process_variables(wf, nodes))
    return {
        "id": _slugify(wf.get("name", "")),
        "name": wf.get("name", ""),
        "description": wf.get("description", ""),
        "processVariables": process_vars,
        "definition": {
            "trigger": trigger_cfg,
            "nodes": nodes,
            "edges": edges,
        },
    }


def _generate_from_step_dicts(
    wf: dict, steps: list[dict], models: dict,
    table_names: set[str] | None = None,
    registry: dict | None = None,
) -> dict:
    """Generate from steps that already have detail dicts — the planner's declared
    node_type per step is honored (keyword classifier is only the fallback)."""
    return _generate_from_step_names(
        wf,
        [s.get("name", s.get("label", s.get("id", f"step_{i}"))) for i, s in enumerate(steps)],
        models,
        step_meta=steps,
        table_names=table_names,
        registry=registry,
    )


def _generate_from_name(
    wf: dict, models: dict, table_names: set[str] | None = None,
    registry: dict | None = None,
) -> dict:
    """Generate a basic workflow from just the name and description."""
    name = wf.get("name", "")
    desc = wf.get("description", "")

    # Generate reasonable steps based on workflow name
    steps = _infer_steps_from_name(name, desc)
    return _generate_from_step_names(wf, steps, models, table_names=table_names, registry=registry)


# actionTypes the planner may name directly (→ an `action` node with that actionType).
_ACTION_TYPES = {"db_query", "db_insert", "db_update", "db_delete", "http_call",
                 "send_email", "send_notification", "set_variable", "transform",
                 "custom", "generate_document", "ocr_document",
                 # R3 event-bus nodes (emit / wait-for durable forge_events).
                 "emit_event", "wait_for_event"}
# Planner-level node types → the runtime node type they map to.
_PLANNER_NODE_ALIASES = {"assignment": "user_task", "task_pool": "user_task", "escalation": "action"}


def _runtime_node_types() -> set[str]:
    try:
        from services.workflow_node_contracts import node_contracts
        return set(node_contracts()["node_types"])
    except Exception:
        return {"trigger", "action", "condition", "decision", "wait", "approval",
                "user_task", "end", "ai_generate", "ai_classify", "ai_extract", "ai_decide"}


def _resolve_step_node_type(meta: dict | None, step_name: str) -> tuple[str, str | None]:
    """Prefer the planner's declared node_type (validated); fall back to the keyword
    classifier. Returns (runtime_node_type, forced_actionType|None)."""
    nt = ""
    if isinstance(meta, dict):
        nt = str(meta.get("node_type") or meta.get("type") or "").strip().lower()
    if not nt:
        return _classify_step(step_name), None
    if nt in _PLANNER_NODE_ALIASES:
        return _PLANNER_NODE_ALIASES[nt], None
    if nt in _ACTION_TYPES:
        return "action", nt
    if nt in _runtime_node_types():
        return nt, None
    return _classify_step(step_name), None  # unknown → keyword fallback


# Whole labels that mean "this is the terminator", matched exactly so a step
# like "Complete Onboarding" is still real work.
_TERMINAL_LABELS = frozenset({
    "end", "end process", "end workflow", "finish", "done", "stop", "complete",
    "completed", "terminate", "exit",
})

# Words that make a label a COMPARISON, i.e. a gateway condition rather than a
# thing to do: "If Over Limit", "Amount Exceeds Threshold", "At Least 3".
_COMPARISON_WORDS = (
    " over ", " under ", " above ", " below ", " exceeds", " greater",
    " less than", " more than", " at least", " at most", " equals",
    " threshold", " limit",
)


def _classify_step(step_name: str) -> str:
    """Classify a step name into a workflow node type (fallback when the planner
    did not declare a node_type)."""
    lower = step_name.lower()

    # Intelligent-system steps map to the engine's AI nodes (which call the LLM).
    # Checked FIRST so e.g. "generate reply" / "summarize" don't fall through to
    # the generic action rule. Each AI node has a distinct job:
    norm = lower.replace("_", " ")
    if any(kw in norm for kw in ("generate reply", "generate response", "ai reply",
                                 "ai response", "ai generate", "assistant reply", "llm reply",
                                 "summariz", "summaris", "draft reply", "compose reply",
                                 "generate summary", "generate description", "generate content")):
        return "ai_generate"
    if any(kw in norm for kw in ("classify", "categoriz", "categoris", "sentiment",
                                 "triage", "auto tag", "auto label", "detect intent")):
        return "ai_classify"
    # OCR — checked BEFORE ai_extract so "extract text from scan" / "OCR document"
    # bind to the PaddleOCR sidecar rather than the general LLM extractor.
    if any(kw in norm for kw in ("ocr document", "ocr file", "ocr pdf", "ocr scan",
                                 "run ocr", "extract text from scan",
                                 "extract text from document", "extract text from pdf",
                                 "scan document", "scan pdf", "digitize")):
        return "ocr_document"
    if "extract" in norm:
        return "ai_extract"
    if any(kw in norm for kw in ("ai decide", "auto route", "smart route", "recommend action")):
        return "ai_decide"

    # STEMS, not full verbs (register WG-1).
    #
    # These were verb-only, so the NOUN phrasings planners emit just as often
    # missed entirely: "Manager Approval" does not contain "approve",
    # "Document Verification" does not contain "verify", "Risk Assessment" does
    # not contain "assess"e. Those steps fell through to the generic action
    # rule and became plain actions — an approval gate silently stopped being a
    # human step, so nothing paused and nobody was asked to approve.
    # Separator-insensitive text for the remaining checks. "sign-off",
    # "sign_off" and "signoff" are the same word to a human but three
    # different strings here — the list carried two of the three, so the
    # hyphenated spelling people actually write fell through.
    flat = re.sub(r"[-_]+", " ", lower).strip()
    squashed = re.sub(r"[^a-z0-9]+", "", lower)

    # TERMINAL steps. There was NO branch for these at all, so a step named
    # "End" became an `action` — the graph gained a no-op node where its
    # terminator should be. Matched on the WHOLE label so "Complete
    # Onboarding" and "Finish Review" stay real work.
    if flat in _TERMINAL_LABELS or squashed in ("end", "endprocess", "endworkflow"):
        return "end"

    if any(kw in flat for kw in ["approv", "authoriz", "authoris", "review",
                                 "sign off", "signoff"]):
        return "approval"

    # CONDITIONAL GRAMMAR, not just decision verbs.
    #
    # The list was all verbs ("check", "validate"), so a step phrased as the
    # condition ITSELF — "If Over Limit", "When Amount Exceeds 500",
    # "Is Eligible?" — matched nothing and became an action. That is a gateway
    # silently demoted to a no-op, so the branch it was meant to guard ran
    # unconditionally.
    if (flat.startswith(("if ", "when ", "unless ", "whether "))
            or flat.endswith("?")
            or any(kw in f" {flat} " for kw in _COMPARISON_WORDS)):
        return "condition"

    if any(kw in flat for kw in ["check", "validat", "verif", "assess", "evaluat",
                                 "eligibility", "condition", "decision", "criteria"]):
        return "condition"

    # "Assign <role>" (assign technician / crew / inspector …) is a human task
    # with a pool → a user_task the assignment strategy can load-balance.
    if "assign" in lower and _detect_pool_role(step_name):
        return "user_task"

    if any(kw in lower for kw in ["collect", "enter", "input", "fill", "upload", "signature", "select"]):
        return "user_task"

    if any(kw in lower for kw in ["wait", "delay", "timeout", "hold"]):
        return "wait"

    if any(kw in lower for kw in ["send", "notify", "email", "alert", "reminder", "outreach"]):
        return "action"

    if any(kw in lower for kw in ["create", "generate", "update", "insert", "schedule", "assign", "process", "calculate", "record"]):
        return "action"

    if any(kw in lower for kw in ["escalat", "flag", "reject"]):
        return "action"

    return "action"


# Keywords that mark a workflow as document/file intake (drives ai_extract to read
# the uploaded file as a PDF/image rather than a text field).
_DOC_KEYWORDS = ("cv", "resume", "résumé", "document", "scan", "parse", "upload",
                 "attachment", "ocr", "pdf", "aggregate")
_SYS_COLS = {"id", "createdat", "updatedat", "deletedat",
             "created_at", "updated_at", "deleted_at"}


def _infer_target_entity(wf: dict, models: dict) -> str | None:
    """The model whose name appears in the workflow name/description (longest match)."""
    hay = f"{wf.get('name','')} {wf.get('description','')}".lower()
    best: str | None = None
    for mn in models:
        if mn and mn.lower() in hay and (best is None or len(mn) > len(best)):
            best = mn
    return best


def _extract_field_names(model: dict | None) -> list[str]:
    """Editable column names of a model (drops PK / system / FK columns), for
    schema-guided extraction so the AI returns keys that map to real DB columns."""
    if not isinstance(model, dict):
        return []
    out: list[str] = []
    for f in (model.get("fields") or []):
        if not isinstance(f, dict):
            continue
        name = f.get("name", "")
        low = name.lower()
        if not name or f.get("primaryKey") or low in _SYS_COLS:
            continue
        if low.endswith("id") and low != "id":  # foreign key — set by the app, not extracted
            continue
        out.append(name)
    return out[:15]


def _mark_progress(config: dict, step_name: str) -> None:
    """Fill `config` with a real, side-effect-free set_variable marker — used when a
    step can't be resolved to an executable op, so the workflow still flows without
    a dead custom/no-op node."""
    config["actionType"] = "set_variable"
    config["variableName"] = f"{_slugify(step_name)}_done"
    config["variableValue"] = True


def _authored_literal_values(meta: dict | None) -> dict | None:
    """A2: when the planner/business-logic author put an explicit CONCRETE literal
    `values` map on this step (the target state a button sets — `{"status":"Approved"}`),
    return it VERBATIM so it wins over label-derivation and self-refs. Returns None
    when no concrete literal was authored (fall back to the label-derived value)."""
    if not isinstance(meta, dict):
        return None
    cfg = meta.get("config")
    values = cfg.get("values") if isinstance(cfg, dict) else None
    if values is None:
        values = meta.get("values")  # tolerate a top-level `values` on a bare step dict
    try:
        from services.workflow_mutation_guard import has_explicit_literal
    except Exception:  # noqa: BLE001
        return None
    return values if has_explicit_literal(values) else None


def _build_step_config(
    step_name: str, node_type: str, wf: dict, models: dict,
    table_names: set[str] | None = None,
    registry: dict | None = None,
    meta: dict | None = None,
) -> dict:
    """Build the config object for a workflow step. When `table_names` (the app's
    real Drizzle tables) is given, create/update steps become EXECUTABLE db_insert/
    db_update against the real table + columns instead of a dead db_query stub.

    `meta` (the planner's raw step dict) lets an EXPLICIT authored literal `values`
    map (A2) be written verbatim, ahead of label-derivation."""
    table_names = table_names or set()
    lower = step_name.lower()
    config: dict[str, Any] = {}

    if node_type == "approval":
        # Load-balance approvals across a named review pool when one is implied
        # (e.g. "inspector", "advisor"); else route to admin.
        pool = _detect_pool_role(step_name)
        if pool:
            config["assignment"] = {"strategy": "load_balanced", "value": pool}
            config["assigneeRole"] = pool
        else:
            config["assigneeRole"] = "admin"
        # Infer which entity is being approved. The runtime reads
        # `formBinding` (engine.ts:418), not `formId` — the old key was a
        # dead field. See workflow-audit P1-10.
        for model_name in models:
            if model_name.lower() in wf.get("name", "").lower():
                config["formBinding"] = f"{model_name}ApprovalForm"
                config["entityType"] = model_name
                break
        config["dueIn"] = 1440  # 24 hours

    elif node_type == "condition":
        # A vacuous `expression = "true"` on the legacy path used to make
        # a condition into a hidden no-op — the run always took the then
        # branch AND generation only emits ONE outgoing edge (see the
        # linear edge builder), so falsy would silently end the workflow
        # mid-graph. Pair a defensible non-null check with a stable
        # trigger→variable form so at least the gate is meaningful; the
        # runtime side also now surfaces eval errors and missing else
        # edges instead of swallowing them. See workflow-audit P1-11.
        if "eligib" in lower or "valid" in lower:
            config["expression"] = "input.status != null"
        elif "check" in lower:
            config["expression"] = "input != null"
        else:
            config["expression"] = "input != null"

    elif node_type == "user_task":
        # Load-balance across a named pool (technician / crew / driver …) so the
        # task goes to whoever has the fewest open items; else a generic user task.
        pool = _detect_pool_role(step_name)
        if pool:
            config["assignment"] = {"strategy": "load_balanced", "value": pool}
            config["assigneeRole"] = pool
        else:
            config["assigneeRole"] = "user"
        config["dueIn"] = 480  # 8 hours

    elif node_type == "action":
        _authored_at = str(((meta or {}).get("config") or {}).get("actionType") or "").strip() \
            if isinstance(meta, dict) else ""
        _authored_vals = _authored_literal_values(meta)
        if _authored_at in ("db_update", "db_insert") and _authored_vals:
            # A2: the author explicitly declared a state-transition mutation with a
            # CONCRETE literal `values` map. Honor it verbatim regardless of what the
            # step-name keyword classifier would otherwise infer (the name may be
            # "Restore Availability", not "Update …").
            target = _infer_target_entity(wf, models)
            table = (isinstance(meta.get("config"), dict) and meta["config"].get("table")) \
                or (_resolve_table(target, table_names, registry=registry) if target else "")
            if table:
                config["actionType"] = _authored_at
                config["table"] = table
                config["values"] = _authored_vals
                if _authored_at == "db_update":
                    where = isinstance(meta.get("config"), dict) and meta["config"].get("where")
                    config["where"] = where or {"id": "{{id}}"}
                return config
        if _is_document_step(step_name):
            # Produce a PDF (invoice / certificate / report / sanction letter) via
            # the generate_document handler → stored in forge_files, returns a url.
            config["actionType"] = "generate_document"
            config["title"] = _humanize(step_name)
            config["record"] = "{{input}}"
        elif "send" in lower or "email" in lower or "notify" in lower:
            # Executable notification: a recipient role + a body (never prose-only,
            # which the executability guard would flag as a no-op).
            title = _humanize(step_name)
            role = _detect_pool_role(step_name) or "admin"
            if "email" in lower:
                config["actionType"] = "send_email"
                config["recipientRole"] = role
                config["subject"] = title
                config["body"] = f"{title}."
            else:
                config["actionType"] = "send_notification"
                config["recipientRole"] = role
                config["title"] = title
                config["message"] = f"{title}."
        elif "create" in lower or "insert" in lower or "add" in lower or "register" in lower:
            # Real db_insert into the target entity's table, its editable columns
            # bound to workflow vars (owner FKs are auto-filled by the engine).
            authored = _authored_literal_values(meta)
            target = _infer_target_entity(wf, models)
            table = _resolve_table(target, table_names, registry=registry) if target else ""
            cols = _extract_field_names(models.get(target)) if target else []
            if table and (authored or cols):
                config["actionType"] = "db_insert"
                config["table"] = table
                # Explicit authored literals win verbatim; else bind each column to its var.
                config["values"] = authored or {c: "{{" + c + "}}" for c in cols}
            else:
                _mark_progress(config, step_name)
        elif "update" in lower or "set " in lower or "mark" in lower or "change" in lower:
            authored = _authored_literal_values(meta)
            target = _infer_target_entity(wf, models)
            table = _resolve_table(target, table_names, registry=registry) if target else ""
            cols = _extract_field_names(models.get(target)) if target else []
            if table and authored:
                # A2: the author supplied the concrete target state — write it verbatim.
                config["actionType"] = "db_update"
                config["table"] = table
                config["where"] = {"id": "{{id}}"}
                config["values"] = authored
            elif table:
                config["actionType"] = "db_update"
                config["table"] = table
                config["where"] = {"id": "{{id}}"}
                set_col = next(
                    (c for c in cols if "status" in c.lower() or "stage" in c.lower()),
                    cols[0] if cols else None,
                )
                # A self-referential {{status}} for a state column that no trigger
                # supplies resolves to NULL and WIPES the column (the "button does
                # nothing" defect). When the step name encodes the target state
                # ("Mark applicant as Hired" → "Hired"), emit that literal instead.
                if set_col:
                    lit = None
                    try:
                        from services.workflow_mutation_guard import (
                            derive_status_literal, is_status_col,
                        )
                        if is_status_col(set_col):
                            lit = derive_status_literal(step_name)
                    except Exception:  # noqa: BLE001
                        lit = None
                    config["values"] = {set_col: lit if lit else "{{" + set_col + "}}"}
                else:
                    config["values"] = {}
            else:
                _mark_progress(config, step_name)
        elif "schedule" in lower:
            _mark_progress(config, step_name)
        else:
            # A generic action step → a real, side-effect-free progress marker
            # (keeps the workflow flowing without emitting a dead custom/no-op node).
            _mark_progress(config, step_name)

    elif node_type == "ai_generate":
        # The engine's ai_generate handler calls the LLM with (aiPrompt + aiInput)
        # and returns { generated_text, output }. Feed the user's incoming message
        # as context; downstream steps save `output` back as an assistant message.
        config["aiPrompt"] = ("You are a helpful assistant. Reply conversationally "
                              "to the user's latest message.")
        config["aiTone"] = "helpful"
        config["aiInput"] = "{{input.content}}"

    elif node_type == "ai_classify":
        # LLM classification → { label, confidence }. Labels are left for the
        # author to fill in the workflow editor (domain-specific categories).
        config["aiInput"] = "{{input.content}}"
        config["aiLabels"] = []
        config["aiPrompt"] = f"Classify the input for: {_humanize(step_name)}."
        config["aiThreshold"] = 0.7

    elif node_type == "ai_extract":
        # LLM extraction → structured fields from unstructured input. Schema-guided:
        # extract into the target entity's real columns so the result maps to the DB.
        text = f"{lower} {wf.get('name','')} {wf.get('description','')}".lower()
        is_doc = any(k in text for k in _DOC_KEYWORDS)
        target = _infer_target_entity(wf, models)
        fields = _extract_field_names(models.get(target)) if target else []
        config["aiInput"] = "{{input.content}}"
        config["aiExtractFields"] = fields  # empty → runtime default (name/email/phone)
        if is_doc:
            # Document intake: read the uploaded file (its id arrives in the trigger
            # input) as a PDF/image and extract from it.
            config["aiFileRef"] = "{{input.fileId}}"
            config["aiPrompt"] = (
                "Extract the applicant's details from the attached document"
                + (f" to populate a {target} record." if target else ".")
            )
        else:
            config["aiPrompt"] = f"Extract the relevant fields for: {_humanize(step_name)}."

    elif node_type == "ai_decide":
        # LLM decision → picks one of aiOptions given context + rules.
        config["aiContext"] = "{{input.content}}"
        config["aiOptions"] = ["approve", "reject"]
        config["aiRules"] = ""
        config["aiPrompt"] = f"Decide: {_humanize(step_name)}."

    elif node_type == "action" and config.get("actionType") == "ocr_document":
        # PaddleOCR sidecar. Trigger emits `input` = the uploaded file
        # (id or descriptor). Language + pages default to sidecar
        # behaviour when omitted (auto-detect + all pages).
        config.setdefault("ocrFileRef", "{{input}}")

    elif node_type == "wait":
        config["duration"] = 3600000  # 1 hour

    return config


# Workflow-name/description cues that mark a PERIODIC workflow → a schedule
# trigger fired by /api/cron/tick, mapped to a cadence.
_SCHEDULE_HOURLY = ("sla", "overdue", "breach", "monitor", "sweep", "escalat", "poll", "backlog")
_SCHEDULE_DAILY = ("reminder", "follow up", "follow-up", "followup", "preventive",
                   "maintenance schedul", "renewal", "renew", "deadline", "rest period",
                   "duty hour", "recurring", "periodic", "nightly", "expir", "expiring",
                   "license valid", "document check", "daily", "scheduled")
_SCHEDULE_WEEKLY = ("weekly", "week ")


def _infer_trigger(wf: dict, models: dict) -> dict:
    """Full trigger config for the workflow — a `schedule` trigger for periodic
    work (preventive maintenance, reminders, SLA/expiry sweeps), else `api_event`."""
    trig = wf.get("trigger")
    if isinstance(trig, dict) and trig.get("type") == "schedule":
        cfg = {"type": "schedule"}
        cfg.update({k: v for k, v in trig.items() if k != "type"})
        cfg.setdefault("every", "daily")
        return cfg
    text = f"{wf.get('name','')} {wf.get('description','')}".lower()
    for cadence, kws in (("hourly", _SCHEDULE_HOURLY), ("weekly", _SCHEDULE_WEEKLY), ("daily", _SCHEDULE_DAILY)):
        if any(k in text for k in kws):
            return {"type": "schedule", "every": cadence}
    return {"type": "api_event", "event": _infer_trigger_event(wf, models)}


# ── R1/R2: top-level trigger contract ────────────────────────────────────
# The runtime event bus (runtime/events/bus.ts) and cron scheduler
# (runtime/events/scheduler.ts) read a TOP-LEVEL `trigger` key on the
# workflow JSON:
#   {"kind": "event",    "event": "order.created"}
#   {"kind": "schedule", "cron":  "0 9 * * 1"}
# derive_trigger_contract maps the plan's declared trigger shapes onto that
# contract; anything ambiguous (free prose, "button", "manual") maps to
# None and the key is simply absent — those workflows stay UI-dispatched.

# 5 whitespace-separated cron fields, standard charset per field.
_CRON_FIELD = r"[\d*,/-]+"
_CRON_RE = re.compile(rf"^\s*{_CRON_FIELD}(?:\s+{_CRON_FIELD}){{4}}\s*$")
# Dot-namespaced event name ("order.created", "invoice.paid").
_EVENT_NAME_RE = re.compile(r"^[a-z0-9_-]+\.[a-z0-9_.-]+$", re.IGNORECASE)

# Cadence shorthand → deterministic cron. 09:00 UTC for human-scale
# cadences (matches the vercel.json */15 sweep granularity comfortably).
_CADENCE_CRON = {
    "hourly": "0 * * * *",
    "daily": "0 9 * * *",
    "nightly": "0 0 * * *",
    "weekly": "0 9 * * 1",
    "monthly": "0 9 1 * *",
}

_DB_OP_ALIASES = {
    "create": "created", "created": "created", "insert": "created",
    "update": "updated", "updated": "updated", "change": "updated",
    "delete": "deleted", "deleted": "deleted", "remove": "deleted",
}


def _cadence_to_cron(text: str) -> str | None:
    """Map an interval shorthand ("daily", "6h", "every 15 minutes") to cron."""
    s = str(text or "").strip().lower()
    if not s:
        return None
    for key, cron in _CADENCE_CRON.items():
        if key in s:
            return cron
    m = re.search(r"(\d+)\s*(minutes?|mins?|m\b|hours?|hrs?|h\b|days?|d\b)", s)
    if m:
        n = max(1, int(m.group(1)))
        unit = m.group(2)[0]
        if unit == "m" and n < 60:
            return f"*/{n} * * * *"
        if unit == "h" and n < 24:
            return f"0 */{n} * * *"
        if unit == "d":
            return "0 9 * * *" if n == 1 else f"0 9 */{min(n, 28)} * *"
    return None


def derive_trigger_contract(wf: dict) -> dict | None:
    """Plan workflow → top-level runtime trigger contract, or None.

    Accepted plan shapes (the planner emits `trigger` as a dict or string):
      {"type"|"kind": "schedule", "cron": "0 9 * * 1"}         → schedule
      {"type": "schedule", "every": "daily"|"6h"|…}            → schedule (mapped)
      {"kind"|"type": "event"|"api_event"|"db_change",
       "event": "order.created"}                               → event
      {"type": "db_change", "entity": "Order", "on": "update"} → event
      "0 9 * * 1"                                              → schedule
      "order.created"                                          → event
    Everything else (manual, button, free prose) → None.
    """
    trig = wf.get("trigger") if isinstance(wf, dict) else None

    if isinstance(trig, dict):
        kind = str(trig.get("kind") or trig.get("type") or "").strip().lower()

        cron = trig.get("cron")
        if isinstance(cron, str) and _CRON_RE.match(cron):
            return {"kind": "schedule", "cron": cron.strip()}
        if kind == "schedule":
            cadence = (trig.get("every") or trig.get("schedule")
                       or trig.get("cadence") or trig.get("interval") or "daily")
            mapped = _cadence_to_cron(str(cadence))
            return {"kind": "schedule", "cron": mapped} if mapped else None

        if kind in ("event", "api_event", "db_change", "data_event", ""):
            event = trig.get("event")
            if isinstance(event, str) and _EVENT_NAME_RE.match(event.strip()):
                return {"kind": "event", "event": event.strip().lower()}
            # db_change with entity (+ optional on/operation) — build the
            # data-engine event name. The slug is the entity name lowercased
            # verbatim (no pluralisation guess); dot-named events remain the
            # explicit, unambiguous spelling.
            entity = trig.get("entity")
            if kind == "db_change" and isinstance(entity, str) and entity.strip():
                op_raw = str(trig.get("on") or trig.get("operation") or "created").lower()
                op = _DB_OP_ALIASES.get(op_raw)
                if op:
                    slug = re.sub(r"[^a-z0-9_-]", "", entity.strip().lower())
                    if slug:
                        return {"kind": "event", "event": f"{slug}.{op}"}
        return None

    if isinstance(trig, str):
        s = trig.strip()
        if _CRON_RE.match(s):
            return {"kind": "schedule", "cron": s}
        if _EVENT_NAME_RE.match(s):
            return {"kind": "event", "event": s.lower()}

    return None


# Person/role pools that warrant load-balanced assignment (vs a single admin).
_POOL_ROLES = ("technician", "crew", "pilot", "engineer", "inspector", "advisor",
               "agent", "driver", "doctor", "nurse", "officer", "reviewer",
               "approver", "housekeeper", "cashier", "picker", "packer", "surveyor")


def _detect_pool_role(step_name: str) -> str | None:
    low = step_name.lower()
    for r in _POOL_ROLES:
        if r in low:
            return r.capitalize()
    return None


# A step that OUTPUTS a document → the generate_document action (renders a PDF,
# stores it, returns a url). A strong output verb + a document noun; "create" is
# deliberately excluded so record-creation steps still map to db_insert.
_DOC_VERBS = ("generate", "issue", "produce", "print", "export", "prepare", "download")
_DOC_NOUNS = ("invoice", "certificate", "receipt", "report", "statement", "sanction",
              "document", "letter", "contract", "voucher", "payslip", "quotation", "pdf")


def _is_document_step(step_name: str) -> bool:
    low = step_name.lower()
    return any(v in low for v in _DOC_VERBS) and any(n in low for n in _DOC_NOUNS)


import re as _re

# _to_table (camelCase plural) / _to_slug (kebab plural) are the SAME naming
# helpers the deterministic schema builder uses to name its pgTable(...) tables,
# so resolving through them yields exactly what the schema declared. Imported
# here (not at module top) purely for locality; there is no circular import —
# contract_generator does not import this module.
from services.contract_generator import _to_table, _to_slug


def _load_table_names(output_dir: str) -> set[str]:
    """Authoritative SQL table names from the generated Drizzle schema files.

    The schema names tables via ``_to_table`` (camelCase plural, e.g.
    ``knowledgeArticles``), so the capture class must allow uppercase — a
    ``[a-z0-9_]+`` class would truncate/miss every multi-word camel table."""
    names: set[str] = set()
    schema_dir = Path(output_dir) / "src" / "db" / "schema"
    if schema_dir.exists():
        for f in schema_dir.glob("*.ts"):
            try:
                names.update(_re.findall(r"pgTable\(\s*[\"']([A-Za-z0-9_]+)[\"']", f.read_text(encoding="utf-8")))
            except OSError:
                continue
    return names


def _canon(s: str) -> str:
    """Case/separator-insensitive key for matching a derived name to a real one."""
    return s.lower().replace("_", "").replace("-", "")


def _registry_table_for(token: str, registry: dict | None) -> str | None:
    """The canonical table for ``token`` per the resource registry, or None.

    The registry (built from the SAME plan as the schema builder) owns every
    entity's ``table`` — hint-honoring and NOT independently re-pluralized. Match
    ``token`` case/separator- and plural-tolerantly against each entity's name,
    id, table, slug, camel/singular forms AND the pluralized derivations of its
    name, so both the singular entity name (``Equipment``) and an already-plural
    token (``equipments``) resolve to the one registered ``table``."""
    entities = (registry or {}).get("entities") or {}
    if not token or not entities:
        return None
    ct = _canon(token)
    for name, rec in entities.items():
        if not isinstance(rec, dict):
            continue
        candidates = {
            name, rec.get("id"), rec.get("table"), rec.get("slug"),
            rec.get("camel"), rec.get("singular"),
            _to_table(name), _to_slug(name),
        }
        if ct in {_canon(c) for c in candidates if c}:
            return rec.get("table") or None
    return None


def _resolve_table(entity: str, table_names, registry: dict | None = None) -> str:
    """Resolve an entity name to the SQL table name the schema ACTUALLY declares.

    The Drizzle schema now names its tables from the canonical resource registry
    (``schema_builder`` reads ``registry.entities[name].table``). A workflow's
    ``config.table`` must point at that exact name or the runtime throws
    ``[workflow:X] unknown table`` — the live drift being a hinted entity the
    schema wrote as ``equipment`` while this generator pluralized to ``equipments``.
    So the registry is the PRIMARY authority; the schema-file scan is the fallback:

    1. If ``registry`` knows the entity (by name / id / table / slug, plural-tolerant),
       return that entity's registry ``table`` VERBATIM — both generators agree.
    2. Else canonically match the entity — itself, its ``_to_table`` and ``_to_slug``
       forms — against the real ``table_names`` and return the matching entry.
    3. Else fall back to ``_to_table(entity)`` (camelCase — the schema's own
       convention), never the old snake_case form.
    """
    reg_table = _registry_table_for(entity, registry)
    if reg_table:
        return reg_table
    names = list(table_names or [])
    derived = (entity, _to_table(entity), _to_slug(entity))
    canon_derived = {_canon(d) for d in derived if d}
    for t in names:
        if _canon(t) in canon_derived:
            return t
    return _to_table(entity)


def _wire_document_persist(definition: dict, wf: dict, models: dict, table_names: set[str],
                           registry: dict | None = None) -> None:
    """When a workflow has an ai_extract step, ensure a real db_insert persists the
    extracted fields onto the target entity — closing the 'extracts but never saves'
    gap. Extracted fields become process vars (see ai.ts), bound here as
    values:{column: '{{column}}'}. Idempotent; the graph gate repairs any splice."""
    defn = definition.get("definition") or {}
    nodes = defn.get("nodes") or []

    def _is_extract(n: dict) -> bool:
        # ai_extract may be a dedicated node (type == "ai_extract") OR — on the
        # faithful/translated path — an action node whose config.actionType is
        # ai_extract. Match both so persist-wiring sees either shape.
        if n.get("type") == "ai_extract":
            return True
        return ((n.get("data") or {}).get("config") or {}).get("actionType") == "ai_extract"

    ext = next((n for n in nodes if _is_extract(n)), None)
    if not ext:
        return
    raw_fields = (ext.get("data") or {}).get("config", {}).get("aiExtractFields") or []
    fields = [f if isinstance(f, str) else (f.get("name", "") if isinstance(f, dict) else "") for f in raw_fields]
    fields = [f for f in fields if f]
    target = _infer_target_entity(wf, models)
    if not fields or not target:
        return
    table = _resolve_table(target, table_names, registry=registry)
    values = {f: f"{{{{{f}}}}}" for f in fields}

    ext_idx = nodes.index(ext)
    downstream = nodes[ext_idx + 1:]
    # An existing create/save action step downstream → make it the real db_insert.
    persist = next(
        (n for n in downstream if n.get("type") == "action"
         and any(k in (n.get("data") or {}).get("label", "").lower()
                 for k in ("create", "save", "insert", "persist", "record", "store", "add", "register"))),
        None,
    ) or next((n for n in downstream if n.get("type") == "action"), None)
    if persist is not None:
        cfg = persist.setdefault("data", {}).setdefault("config", {})
        cfg["actionType"] = "db_insert"
        cfg["table"] = table
        cfg["values"] = values
        return
    # No persist step → splice a db_insert right after the extract.
    edges = defn.setdefault("edges", [])
    ids = {n.get("id") for n in nodes}
    new_id = f"persist_{target.lower()}"
    while new_id in ids:
        new_id += "_x"
    y = (ext.get("position") or {}).get("y", 0) + 120
    nodes.append({
        "id": new_id, "type": "action", "position": {"x": 250, "y": y},
        "data": {"label": f"Save {_humanize(target)}", "nodeType": "action",
                 "config": {"actionType": "db_insert", "table": table, "values": values}},
    })
    out_edge = next((e for e in edges if e.get("source") == ext["id"]), None)
    if out_edge:
        succ = out_edge["target"]
        out_edge["target"] = new_id
        edges.append({"id": f"e_{new_id}_{succ}", "source": new_id, "target": succ})
    else:
        edges.append({"id": f"e_{ext['id']}_{new_id}", "source": ext["id"], "target": new_id})


def _infer_trigger_event(wf: dict, models: dict) -> str:
    """Derive the trigger event from the workflow's plan data.

    Strategy (in order):
    1. If the plan workflow has an explicit trigger.event → use it
    2. If the workflow name contains an entity name from the plan → entity_created
    3. Fallback: derive from workflow name keywords (schedule, manual, etc.)

    This is domain-agnostic — works for healthcare, e-commerce, HR, etc.
    """
    # 1. Explicit trigger from plan
    trigger = wf.get("trigger", {})
    if isinstance(trigger, dict) and trigger.get("event"):
        return trigger["event"]
    if isinstance(trigger, str):
        return trigger

    name = wf.get("name", "")
    name_lower = name.lower()

    # 2. Match against plan entities
    # Convert WorkflowName to find entity: "OrderApprovalWorkflow" → find "Order" in models
    import re
    # Extract words from the workflow name
    words = re.sub(r'(?<!^)(?=[A-Z])', ' ', name).lower().split()
    # Remove generic workflow terms
    skip_words = {"workflow", "process", "processing", "management", "reminder",
                  "alert", "notification", "approval", "review", "the", "and", "for"}
    entity_words = [w for w in words if w not in skip_words]

    for model_name in models:
        model_lower = model_name.lower()
        # Check if any entity word matches the model
        if model_lower in entity_words or any(model_lower.startswith(w) or w.startswith(model_lower) for w in entity_words):
            entity_snake = re.sub(r'(?<!^)(?=[A-Z])', '_', model_name).lower()
            # Determine event type from workflow keywords
            if any(kw in name_lower for kw in ["update", "edit", "modify", "refill"]):
                return f"{entity_snake}_updated"
            if any(kw in name_lower for kw in ["delete", "remove", "cancel"]):
                return f"{entity_snake}_deleted"
            if any(kw in name_lower for kw in ["submit", "request"]):
                return f"{entity_snake}_submitted"
            return f"{entity_snake}_created"

    # 3. Keyword-based fallback (domain-agnostic)
    if any(kw in name_lower for kw in ["reminder", "schedule", "recurring", "daily", "weekly"]):
        return "schedule_trigger"
    if any(kw in name_lower for kw in ["manual", "adhoc"]):
        return "manual_trigger"

    # Last resort: derive from name
    entity = _extract_entity(name)
    return f"{entity}_created"


def _extract_entity(name: str) -> str:
    """Extract entity name from workflow name as snake_case."""
    import re
    # Remove common suffixes
    for suffix in ["workflow", "process", "processing", "management", "reminder",
                   "alert", "notification", "approval", "review"]:
        name = name.lower().replace(suffix, "")
    name = name.strip().strip("_").strip("-")
    if not name:
        return "entity"
    # Convert camelCase to snake_case
    name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    return name.strip("_")


def _infer_steps_from_name(name: str, description: str) -> list[str]:
    """Generate workflow steps from name and description.

    Uses generic patterns based on workflow TYPE (approval, notification,
    processing, etc.) — not domain-specific keywords. Works for any domain.
    """
    lower = name.lower()
    entity = _extract_entity(name)

    # Assistant / chatbot pattern: a user message triggers an LLM reply that is
    # saved back as an assistant message. `generate_reply` → ai_generate node
    # (calls the model); `insert_reply` → db action that persists the response.
    if any(kw in lower for kw in ["assistant", "chatbot", "chat bot", "conversational",
                                  "ai reply", "ai response", "chat response", "chat reply"]):
        return ["generate_reply", "insert_reply"]

    # Classify workflow type from generic keywords
    if any(kw in lower for kw in ["approval", "authorize", "review"]):
        # Approval pattern: validate → assign → review → decide → notify
        return [
            f"validate_{entity}",
            "assign_reviewer",
            f"review_{entity}",
            "approve_or_reject",
            "notify_requester",
            "update_status",
        ]

    if any(kw in lower for kw in ["registration", "onboarding", "signup", "intake"]):
        # Onboarding pattern: collect → validate → create → confirm
        return [
            "collect_information",
            "validate_data",
            f"create_{entity}",
            "send_confirmation",
        ]

    if any(kw in lower for kw in ["reminder", "notification", "alert"]):
        # Notification pattern: check → send → wait → followup
        return [
            "check_eligibility",
            "send_notification",
            "wait_for_response",
            "send_followup",
            "update_status",
        ]

    if any(kw in lower for kw in ["processing", "pipeline", "flow"]):
        # Processing pattern: validate → process steps → complete → notify
        return [
            f"validate_{entity}",
            f"process_{entity}",
            "check_results",
            "update_status",
            "notify_stakeholders",
        ]

    if any(kw in lower for kw in ["fulfillment", "delivery", "shipment"]):
        # Fulfillment pattern: validate → prepare → dispatch → track → confirm
        return [
            f"validate_{entity}",
            "prepare_for_dispatch",
            "dispatch",
            "track_progress",
            "confirm_completion",
            "notify_stakeholders",
        ]

    if any(kw in lower for kw in ["escalation", "critical", "urgent", "emergency"]):
        # Escalation pattern: detect → alert → escalate → respond → document
        return [
            f"detect_{entity}",
            "immediate_alert",
            "escalation_check",
            "response_action",
            "documentation",
        ]

    if any(kw in lower for kw in ["payment", "billing", "invoice", "charge"]):
        # Financial pattern: validate → calculate → process → reconcile → notify
        return [
            f"validate_{entity}",
            "calculate_amount",
            "process_payment",
            "reconcile",
            "send_receipt",
        ]

    # If description has useful content, try to extract verbs
    if description and len(description) > 20:
        import re
        # Extract action verbs from description
        verbs = re.findall(
            r'\b(validate|verify|check|create|update|send|notify|assign|process|review|approve|generate|calculate|schedule)\b',
            description.lower(),
        )
        if len(verbs) >= 3:
            return [f"{v}_{entity}" for v in dict.fromkeys(verbs)]  # dedupe preserving order

    # Generic fallback
    return [
        f"validate_{entity}",
        f"process_{entity}",
        "notify_stakeholders",
        "update_status",
    ]


def _humanize(name: str) -> str:
    """Convert step_name or camelCase to Human Name."""
    import re
    # Insert spaces before uppercase in camelCase
    name = re.sub(r'(?<!^)(?=[A-Z])', ' ', name)
    return name.replace("_", " ").replace("-", " ").title()


def _slugify(name: str) -> str:
    """Convert WorkflowName to workflow-name."""
    import re
    slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
    return slug.replace("_", "-").replace(" ", "-")
