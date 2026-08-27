# Faithful Workflow Step Translator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the planner's rich per-step workflow schema (`{id, type, config, next, branches}`) faithfully into the runtime engine's node/edge graph, so generated domain workflows are as intelligent as the planner designed them — AI nodes with real prompts, `db_insert`/`db_update` with real tables/fields, and `exclusive_gateway` branching — instead of collapsing to no-op `custom` "Step" nodes.

**Architecture:** The planner already emits fully-specified steps; the loss is entirely in translation. Two translators (`_build_workflow_graph` in `routers/generate.py`, and `_generate_from_step_names` in `services/workflow_generator.py`) both expect a legacy prose shape (`{name, node_type, action}`), read only those keys, build flat linear chains, and re-guess config — dropping `config.actionType/table/fields/prompt/condition` and `branches` entirely. We add ONE pure, deterministic module, `services/workflow_step_translator.py`, that consumes the planner's actual emitted schema and produces an engine-faithful `{nodes, edges}` definition (real branching via `next`/`branches`, config mapped into the exact keys each runtime handler reads). We route rich-shape workflows through it from both writers (`_sync_workflows_from_plan` — the first writer, which currently poisons the files — and `generate_workflow_definitions`), and fix the skip-guard so a non-executable stub is never treated as "done". Legacy prose steps keep the existing path unchanged.

**Tech Stack:** Python 3 (backend, no new deps). Tests run from `backend/` with `/usr/local/bin/python3 -m pytest`. Runtime engine target is `backend/templates/runtime/workflows/` (TypeScript — read-only reference, not modified here).

---

## Runtime contract (verified against `backend/templates/runtime/workflows/`)

The translator MUST emit exactly what the engine reads. Confirmed field names:

- **Node shape:** `{"id", "type", "position":{"x","y"}, "data":{"label", "nodeType", "config":{...}, "status":"idle"}}`. `type` and `data.nodeType` are the same runtime node type.
- **Runtime `NodeType`** (types.ts): `trigger, action, condition, decision, parallel_gateway, exclusive_gateway, fork, join, user_task, approval, wait, end, end_event, ai_generate, ai_classify, ai_extract, ai_decide`. So `exclusive_gateway` is native — keep it.
- **Runtime `ActionType`** (types.ts): `db_query, db_insert, db_update, db_delete, http_call, send_email, send_notification, set_variable, transform, custom` — plus AI action handlers `ai_generate/ai_classify/ai_extract/ai_decide` and `generate_document` registered in `ai.ts`/`index.ts`.
- **Gateway/condition** (engine.ts `handleCondition`, lines 400–433): reads `config.expression` (FEEL-lite), NOT `config.condition`. On truthy → follows edges with `data.edgeType` in `{then, default}` or no `edgeType`; on falsy → edges with `data.edgeType == "else"`. FEEL-lite equality is a single `=` (evaluator line 164), not `==`; boolean ops are `and`/`or`.
- **Edge shape:** `{"id", "source", "target", "data":{"edgeType": "default"|"then"|"else", "label"?}}`. An `else` edge also needs `"sourceHandle": "else"` (mirrors `_build_workflow_graph.add_edge`).
- **Action handler config keys** (index.ts / ai.ts):
  - `db_insert`: `table` (SQL name), `values` (obj col→value, `{{var}}` supported). Owner-FK auto-fill is handled downstream in `_finalizeInsert`.
  - `db_update`: `table`, `values`, `where`.
  - `db_delete`: `table`, `where`. `db_query`: `table`, `where`.
  - `send_notification`: `title|subject`, `message|body`, `to|userId`, `toRole|assigneeRole`.
  - `send_email`: `to|email`, `subject|title`, `body|message|html`.
  - `ai_generate`/`ai_classify`: `aiPrompt`, `aiInput`.
  - `ai_extract`: `aiPrompt`, `aiExtractFields` (string[] or {name,type}[]), `aiInput` (default `{{input}}`).
  - `ai_decide`: `aiPrompt`, `aiOptions` (string[]), `aiContext`/`aiInput`.
  - `generate_document`: `template|content|html|body|spec|data|title`.
  - `custom`/`transform`: `expression|code`, `assignTo`. `set_variable`: `variableName|name|var`.

The executability contract (`services/workflow_executability.py` `is_executable_workflow`) is the acceptance oracle for "not a no-op". A translated workflow MUST pass it.

## Planner input schema (verified — see `backend/tests/fixtures/ewn5ue3r_plan_workflows.json`)

Each `plan.workflows[i]` = `{name, description, trigger, steps:[...]}`. Each step:
- `{id, type, config, next}` for linear steps, where `type ∈ {trigger, action, end, ...}` and `config` carries `actionType` + action params (`table`, `fields:[col,...]`, `prompt`, `template`).
- `{id, type:"exclusive_gateway", config:{condition}, branches:{true:<id>, false:<id>}}` for a branch — NO `next`.
- Trigger step: `{id:"trigger", type:"trigger", config:{triggerType}, next:<firstStepId>}`.
- An explicit `{id:"end", type:"end"}` terminal is usually present.

Note the two `template` meanings: for `send_notification`, `config.template` is the **message text** → map to `message`; for `generate_document`, `config.template` is the **template id** → keep as `template`. The translator dispatches on `actionType`.

## File Structure

- **Create** `backend/services/workflow_step_translator.py` — pure translation, no I/O. Public: `is_rich_step_list(steps) -> bool`, `translate_workflow(wf, models=None, table_names=None) -> dict | None`.
- **Create** `backend/tests/test_workflow_step_translator.py` — unit tests for every helper + the two real fixtures.
- **Fixture (already written)** `backend/tests/fixtures/ewn5ue3r_plan_workflows.json` — the 6 real domain workflows' plan-step arrays.
- **Modify** `backend/routers/generate.py` — `_sync_workflows_from_plan` (~line 4510): route rich workflows through the translator; keep `_build_workflow_graph` as the prose fallback.
- **Modify** `backend/services/workflow_generator.py` — `generate_workflow_definitions` (~line 29): route rich workflows through the translator; fix the "skip if has nodes" guard to "skip only if already executable".
- **Create** `backend/tests/test_workflow_faithful_e2e.py` — regression over all 6 fixtures + graph-gate idempotency.

---

### Task 1: Module skeleton + `is_rich_step_list` + expression normalizer

**Files:**
- Create: `backend/services/workflow_step_translator.py`
- Test: `backend/tests/test_workflow_step_translator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflow_step_translator.py
from services.workflow_step_translator import is_rich_step_list, _normalize_expression


def test_is_rich_step_list_detects_planner_shape():
    rich = [{"id": "trigger", "type": "trigger", "next": "a"},
            {"id": "a", "type": "action", "config": {"actionType": "db_insert", "table": "x"}}]
    assert is_rich_step_list(rich) is True


def test_is_rich_step_list_rejects_prose_and_empty():
    assert is_rich_step_list(["Create record", "Send email"]) is False
    assert is_rich_step_list([{"name": "Create record", "node_type": "action"}]) is False
    assert is_rich_step_list([]) is False
    assert is_rich_step_list(None) is False


def test_is_rich_step_list_detects_branches_only():
    assert is_rich_step_list([{"id": "g", "type": "exclusive_gateway",
                               "branches": {"true": "a", "false": "b"}}]) is True


def test_normalize_expression_feel_lite():
    assert _normalize_expression("recommendation == 'Hire'") == "recommendation = 'Hire'"
    assert _normalize_expression("a === b") == "a = b"
    assert _normalize_expression("a !== b") == "a != b"
    assert _normalize_expression("a && b || c") == "a and b or c"
    assert _normalize_expression("score >= 80") == "score >= 80"  # untouched
    assert _normalize_expression("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -q`
Expected: FAIL — `ModuleNotFoundError: services.workflow_step_translator`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/workflow_step_translator.py
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

import re
from typing import Any


def is_rich_step_list(steps: Any) -> bool:
    """True when `steps` is the planner's rich dict shape (carries config/branches/
    a typed graph), i.e. NOT the legacy prose `{name, node_type, action}` / str shape."""
    if not isinstance(steps, list) or not steps:
        return False
    for s in steps:
        if not isinstance(s, dict):
            return False
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_step_translator.py backend/tests/test_workflow_step_translator.py backend/tests/fixtures/ewn5ue3r_plan_workflows.json
git commit -m "feat(workflows): rich-step detection + FEEL-lite expr normalizer (translator slice 1)"
```

---

### Task 2: `_translate_config` — per-actionType config fidelity

**Files:**
- Modify: `backend/services/workflow_step_translator.py`
- Test: `backend/tests/test_workflow_step_translator.py`

- [ ] **Step 1: Write the failing test**

```python
from services.workflow_step_translator import _translate_config


def test_db_insert_fields_become_values():
    cfg = _translate_config({"actionType": "db_insert", "table": "applicants",
                             "fields": ["firstName", "email"]})
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "applicants"
    assert cfg["values"] == {"firstName": "{{firstName}}", "email": "{{email}}"}


def test_db_update_gets_where_id_and_values():
    cfg = _translate_config({"actionType": "db_update", "table": "applications",
                             "fields": ["stage", "status"]})
    assert cfg["table"] == "applications"
    assert cfg["where"] == {"id": "{{id}}"}
    assert cfg["values"] == {"stage": "{{stage}}", "status": "{{status}}"}


def test_ai_extract_prompt_and_fields_map():
    cfg = _translate_config({"actionType": "ai_extract",
                             "prompt": "Extract name and email", "fields": ["name", "email"]})
    assert cfg["aiPrompt"] == "Extract name and email"
    assert cfg["aiExtractFields"] == ["name", "email"]
    assert cfg["aiInput"] == "{{input}}"  # exec-contract group 2 satisfied


def test_ai_decide_prompt_maps_to_aiprompt():
    cfg = _translate_config({"actionType": "ai_decide", "prompt": "Score 0-100"})
    assert cfg["aiPrompt"] == "Score 0-100"


def test_send_notification_template_becomes_message_with_recipient():
    # planner gives no recipient — translator must still make it executable
    cfg = _translate_config({"actionType": "send_notification",
                             "template": "Applicant {{firstName}} scored {{aiScore}}"})
    assert cfg["actionType"] == "send_notification"
    assert cfg["message"] == "Applicant {{firstName}} scored {{aiScore}}"
    assert cfg["channel"] == "in_app"        # satisfies executability contract
    assert cfg["toRole"] == "admin"


def test_send_email_gets_recipient_role_and_body():
    cfg = _translate_config({"actionType": "send_email", "template": "Hello {{name}}"})
    assert cfg["body"] == "Hello {{name}}"
    assert cfg["recipientRole"] == "admin"


def test_generate_document_keeps_template_id():
    cfg = _translate_config({"actionType": "generate_document",
                             "template": "assessment_summary_report", "fields": ["a", "b"]})
    assert cfg["template"] == "assessment_summary_report"
    assert cfg["actionType"] == "generate_document"


def test_unknown_actiontype_passthrough_stays_present():
    # transform carries an expression → executable, must not be dropped
    cfg = _translate_config({"actionType": "transform", "expression": "a + b"})
    assert cfg["actionType"] == "transform"
    assert cfg["expression"] == "a + b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k translate_config -q`
Expected: FAIL — `_translate_config` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `workflow_step_translator.py`:

```python
def _as_ref_map(fields: Any) -> dict:
    """['a','b'] → {'a':'{{a}}','b':'{{b}}'} (a values map bound to process vars)."""
    out: dict = {}
    if isinstance(fields, list):
        for f in fields:
            name = f if isinstance(f, str) else (f.get("name") if isinstance(f, dict) else None)
            if name:
                out[str(name)] = f"{{{{{name}}}}}"
    return out


def _translate_config(cfg: dict) -> dict:
    """Map one planner step config into the exact keys the runtime handler reads.
    Faithful: carries the planner's table/fields/prompt/template verbatim; never
    re-guesses. Unknown keys pass through so nothing is silently dropped."""
    at = str(cfg.get("actionType") or "").strip()
    out: dict = {k: v for k, v in cfg.items() if k not in ("fields",)}
    out["actionType"] = at
    fields = cfg.get("fields")

    if at == "db_insert":
        out["values"] = cfg.get("values") or _as_ref_map(fields)
    elif at == "db_update":
        out["where"] = cfg.get("where") or {"id": "{{id}}"}
        out["values"] = cfg.get("values") or _as_ref_map(fields)
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
        # executability group 1 needs to/recipient/recipientRole
        out["recipientRole"] = cfg.get("recipientRole") or cfg.get("toRole") or "admin"
    elif at == "generate_document":
        # template here is the template id — keep it; carry fields as `data`
        if isinstance(fields, list) and fields:
            out.setdefault("data", _as_ref_map(fields))
    # custom/transform/set_variable and any other: pass-through (already copied above)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k translate_config -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_step_translator.py backend/tests/test_workflow_step_translator.py
git commit -m "feat(workflows): faithful per-actionType config mapping (translator slice 2)"
```

---

### Task 3: `_translate_node` — planner step → runtime node

**Files:**
- Modify: `backend/services/workflow_step_translator.py`
- Test: `backend/tests/test_workflow_step_translator.py`

- [ ] **Step 1: Write the failing test**

```python
from services.workflow_step_translator import _translate_node, _humanize_id


def test_translate_action_node():
    n = _translate_node({"id": "extract_cv", "type": "action",
                         "config": {"actionType": "ai_extract", "prompt": "Extract"}}, idx=1)
    assert n["type"] == "action"
    assert n["data"]["nodeType"] == "action"
    assert n["data"]["config"]["actionType"] == "ai_extract"
    assert n["data"]["config"]["aiPrompt"] == "Extract"
    assert n["data"]["label"] == "Extract Cv"
    assert n["id"] == "extract_cv"


def test_translate_gateway_node_uses_expression():
    n = _translate_node({"id": "check_recommendation", "type": "exclusive_gateway",
                         "config": {"condition": "recommendation == 'Hire'"}}, idx=2)
    assert n["type"] == "exclusive_gateway"
    assert n["data"]["config"]["expression"] == "recommendation = 'Hire'"


def test_translate_end_node():
    n = _translate_node({"id": "end", "type": "end"}, idx=9)
    assert n["type"] == "end"
    assert n["data"]["label"] == "Complete"


def test_humanize_id():
    assert _humanize_id("extract_cv") == "Extract Cv"
    assert _humanize_id("notify_recruiter_hire") == "Notify Recruiter Hire"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k "translate_node or humanize" -q`
Expected: FAIL — names not defined.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
# planner-level node types → runtime node types (mirror workflow_generator aliases)
_NODE_ALIASES = {"assignment": "user_task", "task_pool": "user_task", "escalation": "action",
                 "decision_table": "decision"}
# a step whose `type` is a bare actionType (no wrapping "action") → an action node
_ACTIONTYPES = {"db_query", "db_insert", "db_update", "db_delete", "http_call",
                "send_email", "send_notification", "set_variable", "transform", "custom",
                "generate_document", "ai_generate", "ai_classify", "ai_extract", "ai_decide"}
_GATEWAYS = {"exclusive_gateway", "condition", "decision"}


def _humanize_id(sid: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[_\s]+", str(sid or "step")) if w) or "Step"


def _resolve_node_type(step: dict) -> tuple[str, str | None]:
    """Return (runtime_node_type, forced_actionType|None) for a planner step."""
    t = str(step.get("type") or "").strip().lower()
    if t in _NODE_ALIASES:
        return _NODE_ALIASES[t], None
    if t in _ACTIONTYPES:
        return "action", t
    if t in ("trigger", "action", "user_task", "approval", "wait", "end", "end_event",
             "exclusive_gateway", "condition", "decision", "parallel_gateway", "fork", "join",
             "ai_generate", "ai_classify", "ai_extract", "ai_decide"):
        return t, None
    # fall back: infer from the config's actionType if present
    at = str((step.get("config") or {}).get("actionType") or "").strip()
    if at in _ACTIONTYPES:
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
        label = _humanize_id(step.get("id"))
    elif ntype == "action":
        config = _translate_config(cfg_in)
        config["nodeType"] = "action"
        label = _humanize_id(step.get("id"))
    elif ntype in ("end", "end_event"):
        config = {"nodeType": ntype}
        label = "Complete"
    elif ntype == "trigger":
        config = {"nodeType": "trigger", **cfg_in}
        label = _humanize_id(step.get("id"))
    else:  # user_task / approval / wait / ai_* passthrough
        config = _translate_config(cfg_in) if cfg_in.get("actionType") else {**cfg_in, "nodeType": ntype}
        config["nodeType"] = ntype
        label = _humanize_id(step.get("id"))

    return {
        "id": str(step.get("id") or f"step_{idx}"),
        "type": ntype,
        "position": {"x": 250, "y": idx * 120},
        "data": {"label": label, "nodeType": ntype, "config": config, "status": "idle"},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k "translate_node or humanize" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_step_translator.py backend/tests/test_workflow_step_translator.py
git commit -m "feat(workflows): planner step → runtime node mapping (translator slice 3)"
```

---

### Task 4: `_translate_edges` — `next` + `branches` → then/else edges, end wiring

**Files:**
- Modify: `backend/services/workflow_step_translator.py`
- Test: `backend/tests/test_workflow_step_translator.py`

- [ ] **Step 1: Write the failing test**

```python
from services.workflow_step_translator import _translate_edges


def test_linear_next_edges():
    steps = [{"id": "trigger", "type": "trigger", "next": "a"},
             {"id": "a", "type": "action", "next": "end"},
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    pairs = {(e["source"], e["target"]) for e in edges}
    assert ("trigger", "a") in pairs and ("a", "end") in pairs
    assert all(e["data"]["edgeType"] == "default" for e in edges)


def test_gateway_branches_become_then_else():
    steps = [{"id": "g", "type": "exclusive_gateway",
              "branches": {"true": "hire", "false": "review"}},
             {"id": "hire", "type": "action", "next": "end"},
             {"id": "review", "type": "action", "next": "end"},
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    then = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "then"]
    els = [e for e in edges if e["source"] == "g" and e["data"]["edgeType"] == "else"]
    assert then and then[0]["target"] == "hire"
    assert els and els[0]["target"] == "review"
    assert els[0]["sourceHandle"] == "else"


def test_terminal_step_without_next_connects_to_end():
    steps = [{"id": "trigger", "type": "trigger", "next": "a"},
             {"id": "a", "type": "action"},              # no next, no branches
             {"id": "end", "type": "end"}]
    edges = _translate_edges(steps)
    assert ("a", "end") in {(e["source"], e["target"]) for e in edges}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k translate_edges -q`
Expected: FAIL — `_translate_edges` not defined.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
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
            add(sid, str(branches.get("true", "")), "then", "Yes")
            add(sid, str(branches.get("false", "")), "else", "No")
            continue
        nxt = s.get("next")
        if nxt:
            add(sid, str(nxt))
        elif end_id and sid != end_id:
            add(sid, end_id)  # dead-end → terminate at end
    return edges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k translate_edges -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_step_translator.py backend/tests/test_workflow_step_translator.py
git commit -m "feat(workflows): faithful edge/branch translation (translator slice 4)"
```

---

### Task 5: `translate_workflow` orchestrator — real fixtures must be executable + branch

**Files:**
- Modify: `backend/services/workflow_step_translator.py`
- Test: `backend/tests/test_workflow_step_translator.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import os
from services.workflow_step_translator import translate_workflow, is_rich_step_list
from services.workflow_executability import is_executable_workflow

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ewn5ue3r_plan_workflows.json")


def _load(name):
    return json.load(open(_FIX))[name]


def test_translate_returns_none_for_prose():
    assert translate_workflow({"name": "X", "steps": ["do a", "do b"]}) is None


def test_cv_parsing_is_executable_with_ai_nodes():
    wf = translate_workflow(_load("CVParsingWorkflow"))
    assert wf is not None
    assert is_executable_workflow(wf)
    nodes = wf["definition"]["nodes"]
    ats = [((n.get("data") or {}).get("config") or {}).get("actionType")
           for n in nodes if n["type"] == "action"]
    assert "ai_extract" in ats and "ai_decide" in ats and "db_insert" in ats
    # the ai_extract prompt survived
    ext = next(n for n in nodes if ((n["data"]["config"]).get("actionType")) == "ai_extract")
    assert ext["data"]["config"]["aiPrompt"].startswith("Extract applicant")


def test_feedback_has_gateway_with_then_else():
    wf = translate_workflow(_load("FeedbackSubmissionWorkflow"))
    assert wf is not None
    assert is_executable_workflow(wf)
    nodes, edges = wf["definition"]["nodes"], wf["definition"]["edges"]
    gw = next(n for n in nodes if n["type"] == "exclusive_gateway")
    assert gw["data"]["config"]["expression"] == "recommendation = 'Hire'"
    outs = {e["data"]["edgeType"] for e in edges if e["source"] == gw["id"]}
    assert "then" in outs and "else" in outs


def test_translated_id_name_preserved():
    wf = translate_workflow(_load("CVParsingWorkflow"))
    assert wf["name"] == "CVParsingWorkflow"
    assert wf["id"]  # non-empty slug
    assert wf["definition"]["trigger"]["type"]  # a runtime trigger type
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -k "translate_returns_none or cv_parsing or feedback_has or id_name" -q`
Expected: FAIL — `translate_workflow` not defined.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
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
                       table_names: set | None = None) -> dict | None:
    """Translate a rich planner workflow → engine-faithful definition. Returns None
    when the steps aren't the rich shape (caller falls back to the legacy path).

    `models`/`table_names` are accepted for signature parity with the deterministic
    generator; the planner already supplies real table names in config, so they are
    only a last-resort hint and currently unused here."""
    steps = wf.get("steps")
    if not is_rich_step_list(steps):
        return None

    nodes = [_translate_node(s, i) for i, s in enumerate(steps)]
    # Guarantee a terminal end node exists (planner usually includes one).
    if not any(n["type"] in ("end", "end_event") for n in nodes):
        nodes.append({"id": "end", "type": "end", "position": {"x": 250, "y": len(nodes) * 120},
                      "data": {"label": "Complete", "nodeType": "end", "config": {"nodeType": "end"},
                               "status": "idle"}})
        steps = list(steps) + [{"id": "end", "type": "end"}]

    edges = _translate_edges(steps)
    ttype = _trigger_type(wf, steps)
    return {
        "id": _slug(wf.get("name", "")),
        "name": wf.get("name", ""),
        "description": wf.get("description", ""),
        "definition": {
            "trigger": {"type": ttype},
            "nodes": nodes,
            "edges": edges,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_step_translator.py -q`
Expected: PASS (all tests in file).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_step_translator.py backend/tests/test_workflow_step_translator.py
git commit -m "feat(workflows): translate_workflow orchestrator — real fixtures executable+branching (translator slice 5)"
```

---

### Task 6: Wire the translator into `_sync_workflows_from_plan` (the first writer)

**Files:**
- Modify: `backend/routers/generate.py:4510-4553` (`_sync_workflows_from_plan`)
- Test: `backend/tests/test_workflow_faithful_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflow_faithful_e2e.py
import json
import os
from routers.generate import _sync_workflows_from_plan
from services.workflow_executability import is_executable_workflow

_FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ewn5ue3r_plan_workflows.json")


def test_sync_writes_executable_domain_workflows(tmp_path):
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    files = list((tmp_path / "workflows").glob("*.json"))
    assert len(files) == 6
    execu = 0
    for f in files:
        d = json.loads(f.read_text())
        if is_executable_workflow(d):
            execu += 1
    assert execu == 6, f"only {execu}/6 domain workflows executable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_faithful_e2e.py -q`
Expected: FAIL — with the current `_build_workflow_graph`, the workflows are non-executable `custom` no-ops (`0/6` or similar).

- [ ] **Step 3: Write minimal implementation**

In `routers/generate.py`, inside `_sync_workflows_from_plan`, replace the per-workflow build block (the `for wf in workflows:` loop body that calls `_build_workflow_graph`) so rich steps go through the faithful translator and only prose steps use the legacy graph builder:

```python
    from services.workflow_step_translator import is_rich_step_list, translate_workflow

    for wf in workflows:
        name = wf.get("name", "Untitled")
        steps = wf.get("steps", [])

        translated = translate_workflow(wf) if is_rich_step_list(steps) else None
        if translated is not None:
            wf_id = translated["id"] or str(uuid.uuid4())[:8]
            wf_data = {
                "id": wf_id,
                "name": name,
                "description": wf.get("description", f"{name} workflow"),
                "definition": {
                    "trigger": translated["definition"]["trigger"],
                    "steps": steps,  # preserve raw steps for the editor/preview
                    "nodes": translated["definition"]["nodes"],
                    "edges": translated["definition"]["edges"],
                },
            }
        else:
            wf_id = str(uuid.uuid4())[:8]
            trigger_str = wf.get("trigger", "manual")
            nodes, edges = _build_workflow_graph(wf_id, name, trigger_str, steps)
            wf_data = {
                "id": wf_id,
                "name": name,
                "description": wf.get("description", f"{name} workflow"),
                "definition": {
                    "trigger": {"type": _map_trigger_type(trigger_str)},
                    "steps": steps,
                    "nodes": nodes,
                    "edges": edges,
                },
            }
        (wf_dir / f"{wf_id}.json").write_text(json.dumps(wf_data, indent=2))

    logger.info(f"[workflows] Synced {len(workflows)} workflows from plan to {wf_dir}")
```

(Delete the old loop body that unconditionally called `_build_workflow_graph`; keep the early `if any(wf_dir.glob("*.json")): return` guard and the `wf_dir.mkdir` above it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_faithful_e2e.py -q`
Expected: PASS — `6/6` executable.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/generate.py backend/tests/test_workflow_faithful_e2e.py
git commit -m "fix(workflows): sync rich plan workflows via faithful translator (not the lossy graph builder)"
```

---

### Task 7: Route `generate_workflow_definitions` through the translator + fix the skip-guard

**Files:**
- Modify: `backend/services/workflow_generator.py:29-90` (`generate_workflow_definitions`)
- Test: `backend/tests/test_workflow_deterministic_coverage.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_workflow_deterministic_coverage.py`:

```python
def test_generate_definitions_overwrites_noop_stub(tmp_path):
    """A pre-existing non-executable stub (as the early sync used to write) must be
    replaced by generate_workflow_definitions, not skipped for having nodes."""
    import json
    from services.workflow_generator import generate_workflow_definitions
    from services.workflow_executability import is_executable_workflow
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    # a no-op stub with non-empty nodes + the same name the plan will use
    (wf_dir / "stub.json").write_text(json.dumps({
        "id": "stub", "name": "Intake",
        "definition": {"trigger": {"type": "api_event"},
                       "nodes": [{"id": "trigger", "type": "trigger", "data": {"config": {}}},
                                 {"id": "s1", "type": "action",
                                  "data": {"config": {"actionType": "custom", "nodeType": "custom"}}}],
                       "edges": []}}))
    plan = {"workflows": [{
        "name": "Intake",
        "steps": [{"id": "trigger", "type": "trigger", "next": "ins"},
                  {"id": "ins", "type": "action", "next": "end",
                   "config": {"actionType": "db_insert", "table": "applicants",
                              "fields": ["email"]}},
                  {"id": "end", "type": "end"}]}]}
    generate_workflow_definitions(str(tmp_path), plan)
    # find the Intake file and assert it's now executable
    ok = False
    for f in wf_dir.glob("*.json"):
        d = json.loads(f.read_text())
        if d.get("name") == "Intake" and is_executable_workflow(d):
            ok = True
    assert ok, "generate_workflow_definitions left the no-op stub in place"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_deterministic_coverage.py -k overwrites_noop -q`
Expected: FAIL — the "skip if `len(existing_nodes) > 0`" guard preserves the stub.

- [ ] **Step 3: Write minimal implementation**

In `generate_workflow_definitions`, (a) prefer the faithful translator for rich steps, and (b) change the skip decision to test executability instead of node count.

At the top of the `for wf in workflows:` loop, before the `steps` shape dispatch, add:

```python
        from services.workflow_step_translator import is_rich_step_list, translate_workflow
        steps = wf.get("steps", [])
        if is_rich_step_list(steps):
            translated = translate_workflow(wf, models, table_names)
            if translated is not None:
                definition = translated["definition"]
            else:
                definition = _generate_from_step_dicts(wf, steps, models, table_names=table_names)["definition"] \
                    if steps else _generate_from_name(wf, models, table_names=table_names)["definition"]
        else:
            # ... existing str/dict/name dispatch, assigning `definition` ...
```

(Restructure so both branches set `definition` — the existing code already computes a `definition` dict from `_generate_from_step_names/_generate_from_step_dicts/_generate_from_name`; wrap it in the `else`. Extract `.get("definition")` when those helpers return the full workflow dict.)

Then replace the skip-guard:

```python
        from services.workflow_executability import is_executable_workflow
        existing_files = list(wf_dir.glob("*.json"))
        target_file = None
        for ef in existing_files:
            try:
                existing = json.loads(ef.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if existing.get("name") == wf_name:
                target_file = ef
                # Overwrite unless the existing file is ALREADY executable — a
                # non-empty-but-no-op stub (the early sync's old output) must be replaced.
                if is_executable_workflow(existing):
                    target_file = None  # keep the good one, skip writing
                break
```

Keep the subsequent `if target_file is None: target_file = wf_dir / f"{uuid.uuid4().hex[:8]}.json"` only when we intend to WRITE. Guard the write so an already-executable match is left untouched (introduce a `skip = existing is executable` flag rather than reusing `target_file = None` for two meanings if clearer — the implementer may refactor for readability as long as the test passes).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_deterministic_coverage.py -q`
Expected: PASS (existing 4 + new 1).

- [ ] **Step 5: Commit**

```bash
git add backend/services/workflow_generator.py backend/tests/test_workflow_deterministic_coverage.py
git commit -m "fix(workflows): generate_workflow_definitions honors rich steps + overwrites no-op stubs"
```

---

### Task 8: End-to-end regression — all 6 fixtures executable + branching + gate-idempotent

**Files:**
- Modify: `backend/tests/test_workflow_faithful_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
def test_all_six_domain_workflows_intelligent(tmp_path):
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    wf_dir = tmp_path / "workflows"
    by_name = {}
    for f in wf_dir.glob("*.json"):
        d = json.loads(f.read_text())
        by_name[d["name"]] = d

    # 1) every domain workflow is executable (no no-op custom chains)
    for name, d in by_name.items():
        assert is_executable_workflow(d), f"{name} not executable"

    # 2) CV parsing actually uses AI extraction + scoring
    cv = by_name["CVParsingWorkflow"]
    ats = [((n["data"].get("config") or {}).get("actionType"))
           for n in cv["definition"]["nodes"] if n["type"] == "action"]
    assert "ai_extract" in ats and "ai_decide" in ats

    # 3) feedback flow branches on the Hire predicate
    fb = by_name["FeedbackSubmissionWorkflow"]
    assert any(n["type"] == "exclusive_gateway" for n in fb["definition"]["nodes"])
    gw = next(n for n in fb["definition"]["nodes"] if n["type"] == "exclusive_gateway")
    outs = {e["data"]["edgeType"] for e in fb["definition"]["edges"] if e["source"] == gw["id"]}
    assert {"then", "else"} <= outs


def test_graph_gate_is_idempotent_on_translated(tmp_path):
    """The deterministic graph gate must find nothing to repair in faithfully
    translated workflows (proves the graph is well-formed: reachable, terminated)."""
    from services.workflow_graph_gate import run_workflow_gate
    plan = {"workflows": list(json.load(open(_FIX)).values())}
    _sync_workflows_from_plan(str(tmp_path), plan)
    report = run_workflow_gate(str(tmp_path), plan)
    total_fixes = sum(len(v.get("fixes", [])) for v in (report or {}).get("workflows", {}).values()) \
        if isinstance(report, dict) else 0
    assert total_fixes == 0, f"graph gate had to repair translated workflows: {report}"
```

Note: adapt the `run_workflow_gate` report-shape assertion to its real return (check `services/workflow_graph_gate.py`); the intent is "0 repairs".

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/test_workflow_faithful_e2e.py -q`
Expected: after Tasks 6–7, PASS. If `test_graph_gate_is_idempotent_on_translated` reports repairs, read the fixes and adjust `_translate_edges`/`_translate_node` until the graph is clean (typically: an unreachable node or a missing terminal — the translator should not produce these).

- [ ] **Step 3: Full workflow-suite regression**

Run: `cd backend && /usr/local/bin/python3 -m pytest tests/ -k workflow -q`
Expected: all workflow tests green (existing 181 + new). Fix any drift surfaced by `test_workflow_node_contracts.py` (e.g., a new actionType must have a handler).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_workflow_faithful_e2e.py
git commit -m "test(workflows): e2e proof — 6 domain workflows executable + branching + gate-clean"
```

---

## Out of scope (do NOT do here)

- The Figma pipeline (`_run_figma_relay_pipeline`) — it has no domain-workflow generator; unchanged.
- Changing the planner prompt or the runtime TS engine.
- The LLM executability fallback (`ensure_workflow_executability`) — it remains as the safety net for genuinely prose steps; this plan makes it a no-op for rich workflows because they now arrive executable.
- CRUD workflow generation (`crud_workflow_generator.py`) — already executable, untouched.

## Verification after the branch

Trigger one live generation (the recruitment prompt) and confirm the 6 domain workflows in `output/<slug>/workflows/*.json` are executable, CVParsing carries `ai_extract`+`ai_decide` with prompts, and Feedback has an `exclusive_gateway` with `then`/`else` edges. Compare against this run's broken baseline (`output/ewn5ue3r`).
