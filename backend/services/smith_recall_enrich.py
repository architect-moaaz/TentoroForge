"""Enriched recall block for Smith's orchestrator.

Baseline recall (:func:`services.app_recall.assemble_recall`) tells
Smith what the app HAS — entities, pages, workflows. That's necessary
but not sufficient. The reason Smith reaches for `edit_file` on a
field-type change instead of the `page_schema_patch` seam is that
his context doesn't remind him:

* Which components exist in the library + their prop contracts
  (so he knows FileUpload takes ``accept/maxSize``, not ``options``).
* Which data-engine endpoints exist and what they take/return
  (so he knows a FileUpload posts to ``/api/files/upload`` and gets
  back a fileAttachment id).
* Which workflow node types exist and their config shape (so he
  knows ``db_update`` takes ``{table, where, values}``, not
  free-form).
* Which specialist seams he has + what each seam accepts (so he
  chooses the specialist over `edit_file`).

This module composes those four catalogs into a compact block that
appends to the base recall. Every source is derived deterministically
from files/registries that already exist — no static duplication.
"""
from __future__ import annotations

import json
import os
from typing import Any


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

def enriched_recall_block(output_dir: str) -> str:
    """Compose base recall + component catalog + data-engine surface +
    workflow-node catalog + specialist-seams catalog into a single
    string, ready for injection into Smith's system-turn context.

    Silent on partial failure — a missing library dist or workflow
    generator module just shortens the block, never crashes."""
    from services.app_recall import assemble_recall

    parts: list[str] = []
    try:
        parts.append(assemble_recall(output_dir).to_prompt_block())
    except Exception as exc:  # noqa: BLE001
        parts.append(f"(base recall unavailable: {exc!r})")

    parts.append(_component_catalog(output_dir))
    parts.append(_data_engine_surface())
    parts.append(_workflow_node_catalog())
    parts.append(_specialist_seams_catalog())

    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Component catalog — from the library's dist/starter.json
# --------------------------------------------------------------------------- #

def _component_catalog(output_dir: str) -> str:
    """Read the component library's `starter.json` — the same source
    the renderer resolves component types against — and render a
    compact `Component: props` catalog.

    Search order:
    1. `<output_dir>/node_modules/@tentoroforge/*/dist/starter.json`
    2. Monorepo fallback: `<repo>/packages/registry/dist/starter.json`
    """
    starter = _find_starter_json(output_dir)
    if not starter:
        return "COMPONENT CATALOG: (starter.json not found; component contracts unavailable)"

    try:
        data = json.load(open(starter, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"COMPONENT CATALOG: (failed to parse {starter}: {exc!r})"

    if not isinstance(data, dict):
        return "COMPONENT CATALOG: (unexpected starter.json shape)"

    lines = ["COMPONENT CATALOG — every renderable type + its props (source of truth):"]
    for name in sorted(data.keys()):
        entry = data[name]
        props = entry.get("props") if isinstance(entry, dict) else None
        if not isinstance(props, dict):
            lines.append(f"  {name}: (no props declared)")
            continue
        prop_names = sorted(props.keys())
        # Compact one-liner per component.
        prop_str = ", ".join(prop_names) if prop_names else "(no props)"
        if len(prop_str) > 140:
            prop_str = prop_str[:137] + "…"
        lines.append(f"  {name}: {prop_str}")
    return "\n".join(lines)


def _find_starter_json(output_dir: str) -> str | None:
    """Locate the component library's starter.json — first in the app's
    node_modules, then fall back to the monorepo's packages dir."""
    # 1. App-local install (production shape).
    node_modules = os.path.join(output_dir, "node_modules")
    if os.path.isdir(node_modules):
        for root, _dirs, files in os.walk(node_modules):
            if "starter.json" in files and "dist" in root:
                return os.path.join(root, "starter.json")
    # 2. Monorepo fallback (dev shape).
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(here, "packages", "registry", "dist", "starter.json")
        if os.path.exists(candidate):
            return candidate
        here = os.path.dirname(here)
    return None


# --------------------------------------------------------------------------- #
# Data-engine surface — what /api/... accepts and returns
# --------------------------------------------------------------------------- #

def _data_engine_surface() -> str:
    """The endpoints every generated app ships with. Static text —
    the data-engine template is fixed at gen-time and every app
    exposes the same set."""
    return "\n".join([
        "DATA ENGINE API — endpoints every generated app exposes:",
        "  GET    /api/data/[entity]              → list all rows of entity",
        "  GET    /api/data/[entity]/[id]         → single row by id",
        "  POST   /api/data/[entity]              → create; body = row (id auto)",
        "  PATCH  /api/data/[entity]/[id]         → partial update",
        "  DELETE /api/data/[entity]/[id]         → delete row",
        "  POST   /api/files/upload               → multipart file upload;",
        "                                             returns { id, url, size }",
        "  GET    /api/files/[id]                 → download file by id",
        "  POST   /api/workflows/[id]/execute     → trigger workflow with input body",
        "  GET    /api/notifications              → list; PATCH /:id → mark-read",
        "  GET/POST /api/cron/tick                → scheduled-workflow fire hook",
        "",
        "FIELD TYPE → API PATTERN:",
        "  FileUpload node → POSTs multipart to /api/files/upload, sets the",
        "    returned id on the form field (FK to fileAttachments).",
        "  Select w/ optionsFrom → reads GET /api/data/[source-entity] on mount.",
        "  Form submit → POST /api/data/[entity] with the values map.",
    ])


# --------------------------------------------------------------------------- #
# Workflow-node catalog — what steps exist and what config each takes
# --------------------------------------------------------------------------- #

def _workflow_node_catalog() -> str:
    """The action-type set the runtime workflow engine recognizes.
    Sourced from the runtime template's `registerDefaultActions()` —
    but kept static here to avoid parsing TypeScript. Update when
    the runtime action list grows."""
    return "\n".join([
        "WORKFLOW NODE CATALOG — action types the runtime engine understands:",
        "  trigger        config: { triggerType: 'manual'|'db_change'|'schedule',",
        "                            inputs: [{name, type, required?}] }",
        "  db_insert      config: { table, values: {col: '{{binding}}'} }",
        "  db_update      config: { table, where: {col: '{{binding}}'},",
        "                            values: {col: '{{binding}}'} }",
        "  db_delete      config: { table, where: {col: '{{binding}}'} }",
        "  db_query       config: { table, where?: {col: '{{binding}}'} }",
        "                          → outputs: rows",
        "  ai_generate    config: { prompt, output? }         → outputs: text",
        "  ai_classify    config: { prompt, options: [str] }  → outputs: choice",
        "  ai_extract     config: { source, schema: {...} }   → outputs: extracted",
        "  ai_decide      config: { prompt, options }         → outputs: branch",
        "  send_notification config: { user, message, kind? }",
        "  send_email     config: { to, subject, body }",
        "  task           config: { title, form: {fields}, assignee }",
        "                        → creates a task row, waits for form submit",
        "  set_variable   config: { variableName, variableValue }",
        "  transform      config: { transformExpression }     → outputs: value",
        "  end            (no config — terminates workflow)",
        "",
        "CONNECTIVITY: every node has `next: <step_id>` OR (gateway) `branches:",
        "  {label: <step_id>}`. Exactly one trigger + one end per workflow.",
    ])


# --------------------------------------------------------------------------- #
# Specialist seams catalog — what Smith can call BEFORE reaching for edit_file
# --------------------------------------------------------------------------- #

def _specialist_seams_catalog() -> str:
    return "\n".join([
        "SPECIALIST SEAMS — prefer these over `edit_file` for their artifact class:",
        "",
        "  page_schema_patch(page, target_name, change)",
        "    Owner of: src/schemas/**/*.json field/section edits.",
        "    Use when: change a Form field's type/props, swap a component,",
        "               add or remove a display node, retitle a section.",
        "    Knows: the component library's prop contracts; drops stale props",
        "               (e.g. Select→FileUpload strips options+optionsFrom, adds",
        "               accept+maxSize).",
        "",
        "  edit_workflow(workflow_id, changes)",
        "    Owner of: workflows/*.json step / trigger-input / connectivity edits.",
        "    Supported change ops:",
        "      add_trigger_input | remove_trigger_input | set_step_config",
        "      add_step | remove_step | rewire | rename",
        "    Runs V2 workflow validation before write — refuses on connectivity",
        "    breaks or dangling next targets.",
        "",
        "  add_page(entity, kind, route)",
        "    Owner of: creating a whole new page + wiring nav + detail routes.",
        "    kind ∈ list | detail | form | dashboard | kanban | calendar.",
        "",
        "  add_workflow(name, spec)",
        "    Owner of: authoring a brand-new workflow with trigger + steps.",
        "",
        "  add_entity(name, fields)",
        "    Owner of: new entity + Drizzle schema + migration + registry +",
        "    starter list/form pages.",
        "",
        "  add_component(name, from_library)",
        "    Owner of: adding a library component to the app's registry so",
        "    pages can reference it.",
        "",
        "  env_upsert(key, value)",
        "    Owner of: .env.local writes. Preserves existing user-set values;",
        "    only fills in blanks. Use for FORGE_UPLOAD_DIR, storage keys, etc.",
        "",
        "  regenerate_seed(entity?)",
        "    Owner of: contracts/seed-plan.json + seed row synthesis.",
        "",
        "  edit_file(path, edits)  — LAST RESORT",
        "    Use only when no seam owns the target (e.g. src/lib/**/*.ts",
        "    runtime code — the self-heal path). Never use for src/schemas/**",
        "    or workflows/** — a seam owns those.",
        "",
        "ROUTING RULE: On any modification ask,",
        "  1. call impact_analysis(target) FIRST — get the blast radius.",
        "  2. For each impacted artifact, pick the seam that OWNS it.",
        "  3. Only fall through to edit_file when no seam covers the file.",
        "  4. After edits, run_guards() until GREEN before answering.",
    ])
