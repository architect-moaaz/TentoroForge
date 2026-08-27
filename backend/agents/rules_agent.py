"""Rules Agent — converts the planner's prose access-control rules into
structured ProjectRule records the runtime engine can execute.

Input:
  plan.access_control.rules: list[str]  — free-form English from the planner
  plan.entities (or registry entities)  — entity definitions with fields
  plan.workflows                        — for state-transition rules

Output:
  list[dict] — structured rules matching ProjectRule shape:
    { name, rule_type, model_name, field_name?, config, is_active }

The dicts are written to `registry.rules` so runtime_injector exports them
to `rules/index.json` at runtime injection time. When `project_id` is
provided, the rules are also persisted to the `project_rules` table so the
editor UI's RulesPanel sees them. Existing rows for the project are wiped
first so re-runs idempotently replace the prior set.

Follows the same conventions as other agents:
  - async, uses claude_agent_sdk.query
  - signature: run_rules_agent(output_dir, plan, domain_context=None, project_id=None)
  - pops CLAUDECODE to prevent recursion
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query

logger = logging.getLogger(__name__)

VALID_TYPES = {
    "validation", "access", "business", "computed",
    "state_machine", "trigger",
}


async def run_rules_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Generate structured rules from the plan. Returns the list of rules
    written to registry. Does NOT yield SSE events — the caller handles that.

    When `project_id` is provided, also writes the rules to the project_rules
    DB table (replacing any existing rows for that project).
    """
    os.environ.pop("CLAUDECODE", None)

    prose = _collect_prose_rules(plan)
    # The new planner emits entities under `data_models`; older / schema-mode
    # plans use `entities`. Honour both so the agent works against either.
    entities = _normalize_entities(plan.get("data_models") or plan.get("entities") or {})
    if not prose and not entities:
        logger.info("[rules-agent] No rule prose and no entities — skipping")
        return []

    workflows = plan.get("workflows", [])

    prompt = _build_prompt(prose, entities, workflows, domain_context)
    raw = await _call_llm(prompt)
    rules = _extract_rules(raw)
    valid = _validate_rules(rules, entities)

    # Persist into the registry so runtime_injector picks them up.
    registry_path = Path(output_dir) / "registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
        except Exception:
            registry = {}
        rules_section = registry.get("rules") or {}
        # Registry stores rules as { name: rule_dict }. Coexist with anything
        # already there (defensive — usually empty).
        if isinstance(rules_section, list):
            existing = {r.get("name", f"rule-{i}"): r for i, r in enumerate(rules_section)}
        else:
            existing = dict(rules_section)
        for r in valid:
            existing[r["name"]] = r
        registry["rules"] = list(existing.values())  # injector expects a list
        registry_path.write_text(json.dumps(registry, indent=2))

    if project_id is not None and valid:
        await _sync_rules_to_db(project_id, valid)

    return valid


async def _sync_rules_to_db(project_id: uuid.UUID, rules: list[dict]) -> None:
    """Replace project_rules rows for this project with the agent's output.

    Wipe-and-rewrite (vs upsert) keeps semantics simple: the agent is the
    source of truth for AI-generated rules, and re-running it should converge
    to its current output. Failures are logged but don't crash the pipeline —
    the filesystem export still works.
    """
    try:
        from sqlalchemy import delete
        from database import async_session
        from models.rules import ProjectRule

        async with async_session() as session:
            # Preserve rules authored by hand in the Business Rules editor
            # (config.source == "manual"). The agent is the source of truth only
            # for AI-generated rules; wiping manual rules on every regeneration
            # would silently destroy the user's editor work. IS DISTINCT FROM
            # also deletes legacy AI rules whose config has no "source" key.
            await session.execute(
                delete(ProjectRule).where(
                    ProjectRule.project_id == project_id,
                    ProjectRule.config["source"].astext.is_distinct_from("manual"),
                )
            )
            for r in rules:
                session.add(ProjectRule(
                    project_id=project_id,
                    name=r["name"],
                    rule_type=r["rule_type"],
                    model_name=r.get("model_name"),
                    field_name=r.get("field_name"),
                    config=r.get("config") or {},
                    is_active=bool(r.get("is_active", True)),
                ))
            await session.commit()
        logger.info("[rules-agent] DB sync: wrote %d rules for project %s", len(rules), project_id)
    except Exception:
        logger.exception("[rules-agent] DB sync failed for project %s", project_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _collect_prose_rules(plan: dict) -> list[str]:
    ac = plan.get("access_control") or {}
    prose: list[str] = []
    for raw in ac.get("rules", []) or []:
        if isinstance(raw, str) and raw.strip():
            prose.append(raw.strip())
    # Some planners stash field rules under access_control.field_access too.
    for fa in ac.get("field_access", []) or []:
        if isinstance(fa, str):
            prose.append(fa)
        elif isinstance(fa, dict):
            prose.append(json.dumps(fa))
    return prose


def _normalize_entities(raw: Any) -> dict[str, dict]:
    """The plan stores entities as either dict[name → defn] or list[defn]."""
    if isinstance(raw, dict):
        return {name: (defn if isinstance(defn, dict) else {}) for name, defn in raw.items()}
    if isinstance(raw, list):
        out: dict[str, dict] = {}
        for e in raw:
            if isinstance(e, dict) and "name" in e:
                out[e["name"]] = e
        return out
    return {}


def _entity_fields(entity_defn: dict) -> list[str]:
    """Pull the field name list from whatever shape the planner used."""
    fields = entity_defn.get("fields")
    if isinstance(fields, dict):
        return list(fields.keys())
    if isinstance(fields, list):
        return [f.get("name") for f in fields if isinstance(f, dict) and f.get("name")]
    schema = entity_defn.get("schema")
    if isinstance(schema, dict):
        return list(schema.keys())
    return []


def _build_prompt(
    prose: list[str],
    entities: dict[str, dict],
    workflows: list[Any],
    domain_context: dict | None,
) -> str:
    entity_summary_lines: list[str] = []
    for name, defn in entities.items():
        fields = _entity_fields(defn)
        entity_summary_lines.append(f"- {name}: fields = {', '.join(fields) if fields else '(none)'}")
    entity_summary = "\n".join(entity_summary_lines) or "(no entities)"

    workflow_summary = ""
    if workflows:
        wf_names = []
        for w in workflows:
            if isinstance(w, dict):
                wf_names.append(w.get("name") or w.get("id") or "(unnamed)")
            else:
                wf_names.append(str(w))
        workflow_summary = f"\nWorkflows: {', '.join(wf_names)}\n"

    domain_line = ""
    if domain_context:
        domain_line = f"\nDomain context: {json.dumps(domain_context)}\n"

    prose_block = "\n".join(f"- {p}" for p in prose) if prose else "(none — infer reasonable defaults from entities)"

    return f"""Convert the following business intent into structured ProjectRule records.

ENTITIES IN THIS APP:
{entity_summary}
{workflow_summary}{domain_line}

BUSINESS RULES (free-form, may overlap or be vague):
{prose_block}

Emit a JSON object with a single key `rules`, whose value is a list of
ProjectRule dicts. Each rule has:
  - name: short kebab-case identifier (e.g. "leave-request-positive-days")
  - rule_type: one of {sorted(VALID_TYPES)}
  - model_name: an entity name from the list above (or null for cross-entity rules)
  - field_name: a field name belonging to that model (or null)
  - config: a dict whose shape depends on rule_type:
      validation → {{ "expression": "<feel-lite>", "errorMessage": "<text>" }}
                   or {{ "min": <num>, "max": <num>, "errorMessage": "<text>" }}
                   or {{ "required": true, "errorMessage": "<text>" }}
      access     → {{ "roles": ["Admin","Manager"], "can_view": true, "can_edit": true }}
                   or {{ "condition": "<feel-lite>" }}
      business   → {{ "expression": "<feel-lite>", "trigger": "on_create"|"on_update"|"on_read" }}
      computed   → {{ "expression": "<feel-lite>" }}
      state_machine → {{ "states": [...], "transitions": [{{"from":..., "to":..., "requires":"role"}}] }}
      trigger    → {{ "event": "on_create"|"on_update", "action": "<workflow-name>" }}
  - is_active: true

Rules MUST reference real entities and fields from the list above — never invent
them. Prefer concrete validation rules and access rules over vague business prose.
If prose says "Manager: full access" turn it into one access rule per entity.
If prose mentions a workflow trigger, emit a trigger rule pointing at the workflow.

Output ONLY the JSON object, no prose, no markdown fences.
"""


async def _call_llm(prompt: str) -> str:
    options = ClaudeAgentOptions(
        system_prompt="You convert business intent into structured rule definitions. Output ONLY valid JSON.",
        allowed_tools=[],
        permission_mode="default",
        max_turns=1,
        model="claude-sonnet-4-6",
    )
    parts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
    return "".join(parts)


def _extract_rules(text: str) -> list[dict]:
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    start = text.find("{")
    if start == -1:
        return []
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        return []
    try:
        obj = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []
    rules = obj.get("rules")
    return rules if isinstance(rules, list) else []


# Field-name patterns that identify workflow-populated (AI-output) columns.
# A validation rule that requires such a field to be non-empty at form submit
# always fails — the value is written LATER by an AI node in the workflow the
# form is triggering, not authored by the user. The rule blocks the submit
# before the workflow ever runs, and the user sees "must be recorded" for
# something they can't type in.
#
# Detected class: confidence/score fields on scan/vision results (visual-
# product-search), extracted-* fields on document intake, and any field
# starting with "identified" or "extracted" (populated by ai_extract /
# ai_identify_product downstream of the trigger).
_AI_OUTPUT_FIELD_RE = re.compile(
    r"(?:^|_)(?:"
    r"confidence(?:_?score)?"
    r"|identified_?[a-z0-9_]*"
    r"|extracted_?[a-z0-9_]*"
    r"|ai_?output_?[a-z0-9_]*"
    r"|predicted_?[a-z0-9_]*"
    r"|classified_?[a-z0-9_]*"
    r")(?:$|_)",
    re.IGNORECASE,
)


def _is_ai_output_field(field_name: str | None) -> bool:
    """True when `field_name` names a column populated by a downstream AI
    step, not by a user-facing form input."""
    if not field_name or not isinstance(field_name, str):
        return False
    return bool(_AI_OUTPUT_FIELD_RE.search(field_name))


def _validate_rules(rules: list[dict], entities: dict[str, dict]) -> list[dict]:
    valid: list[dict] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        name = r.get("name")
        rule_type = r.get("rule_type")
        if not name or rule_type not in VALID_TYPES:
            logger.info("[rules-agent] dropping rule without name/valid type: %r", r)
            continue
        model_name = r.get("model_name")
        if model_name and model_name not in entities:
            logger.info("[rules-agent] dropping rule referencing unknown entity %r: %r", model_name, name)
            continue
        field_name = r.get("field_name")
        if field_name and model_name:
            entity_fields = _entity_fields(entities.get(model_name, {}))
            if entity_fields and field_name not in entity_fields:
                logger.info("[rules-agent] dropping rule referencing unknown field %s.%s",
                            model_name, field_name)
                continue
        config = r.get("config") or {}
        if not isinstance(config, dict):
            continue
        # Drop required-not-empty validation rules targeting AI-output fields
        # (see _AI_OUTPUT_FIELD_RE). Keep the rule structure otherwise; only
        # the "required: true" path is the trap. When the LLM used `min`/
        # `expression` on an AI-output field the semantics may still be
        # meaningful (bounds check downstream of the AI write), so we don't
        # drop those.
        if rule_type == "validation" and _is_ai_output_field(field_name) and config.get("required") is True:
            logger.info(
                "[rules-agent] dropping required-validation rule %r on AI-output field %s.%s "
                "(would block form submit before the AI node writes the value)",
                name, model_name, field_name,
            )
            continue
        valid.append({
            "name": str(name),
            "rule_type": rule_type,
            "model_name": model_name,
            "field_name": field_name,
            "config": config,
            "is_active": True,
        })
    return valid
