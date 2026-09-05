"""Workflow EXECUTABILITY contract (working-app reliability — Part B).

`workflow_completeness.is_valid_workflow` guarantees a workflow is *structurally*
loadable (trigger + nodes + edges). But the business-logic agent often emits domain
workflows whose action nodes are English PROSE in the `description` field with no
executable params:

    {"actionType": "send_notification",
     "description": "Skipped: Validate Warranty Eligibility condition not met"}

The engine loads these fine but they do no real work — `send_notification`/`custom`
just `console.log` the description. So the app has "lots of workflows" that aren't
"proper". This module adds the executability check: each action node must carry the
real params its `actionType` needs (db ops -> table/values/where; send_email -> to +
body; http -> url; etc.). Non-executable domain workflows are regenerated on the
Anthropic SDK against a strict contract, so they actually execute.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

from services.entity_names import EntityNameError, derive_names
from services.workflow_completeness import is_valid_workflow

logger = logging.getLogger(__name__)

# Per actionType: a tuple of requirement GROUPS. Each group is a set of alternative
# keys, at least one of which must be present and non-empty for the node to count as
# executable. An actionType absent from this map (custom / unknown / ai_* placeholder)
# is treated as NON-executable — those are storyboard no-ops at runtime.
def _required_from_catalog() -> dict[str, tuple[tuple[str, ...], ...]]:
    """What each action variant must carry to execute — read from the workflow
    node catalog, the same declaration the workflow agent authors against and
    the editor's palette offers. ``api_call`` is the legacy spelling of
    ``http_call`` and shares its contract."""
    from services.catalog import workflow_nodes

    cat = workflow_nodes()
    out = {
        key: tuple(tuple(g) for g in variant["config"].get("required") or ())
        for key, variant in cat.variants("action").items()
    }
    # Older workflows spell an AI node as `action` + `actionType: ai_*`; the
    # contract is the top-level AI node's.
    for ntype in cat.node_types:
        if ntype.startswith("ai_"):
            out[ntype] = tuple(tuple(g) for g in cat.required_groups(ntype))
    out["api_call"] = out["http_call"]
    return out


_REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = _required_from_catalog()


def _present(v: object) -> bool:
    if v is None:
        return False
    if isinstance(v, (dict, list, str)) and len(v) == 0:
        return False
    return True


def action_node_executable(node: object) -> bool:
    """True if `node` is not an action node, or is an action node carrying the real
    params its actionType requires. Prose-only action nodes return False."""
    if not isinstance(node, dict):
        return False
    if node.get("type") != "action":
        return True  # triggers/conditions/approvals/waits/end are not our concern
    cfg = (node.get("data") or {}).get("config") or {}
    groups = _REQUIRED.get(cfg.get("actionType"))
    if groups is None:
        return False  # custom/unknown/ai_* -> no-op storyboard
    return all(any(_present(cfg.get(k)) for k in grp) for grp in groups)


def mutation_values_resolvable(d: object) -> bool:
    """True unless some db_update/db_insert node's `values` SET clause resolves to
    ALL NULL — every entry an unresolvable `{{var}}` with no backing trigger input,
    upstream node output, or `id`. Such a clause silently NULLs the columns (the
    "Confirm Pickup does nothing" defect), so it is treated as non-executable."""
    if not isinstance(d, dict):
        return True
    try:
        from services.workflow_mutation_guard import collect_provided_vars, mutation_all_null
    except Exception:  # noqa: BLE001 — guard module optional; don't hard-fail the check
        return True
    provided = collect_provided_vars(d)
    definition = d.get("definition") if isinstance(d.get("definition"), dict) else {}
    nodes = definition.get("nodes") if isinstance(definition.get("nodes"), list) else []
    for n in nodes:
        if not isinstance(n, dict) or n.get("type") != "action":
            continue
        cfg = (n.get("data") or {}).get("config") or {}
        if mutation_all_null(cfg, provided):
            return False
    return True


def is_executable_workflow(d: object) -> bool:
    """True iff d is structurally valid AND every action node it contains is
    executable. A workflow with no action nodes (pure approval/condition flow) is
    considered executable — there is no side-effecting node to be a no-op.

    Also requires every mutation's SET clause to resolve to a real value — an
    all-NULL-resolving db_update/db_insert is flagged non-executable."""
    if not is_valid_workflow(d):
        return False
    nodes = d["definition"]["nodes"]  # type: ignore[index]
    actions = [n for n in nodes if isinstance(n, dict) and n.get("type") == "action"]
    if not actions:
        # No action nodes. A pure approval/condition flow is still legitimate —
        # a human task creates a real task row — but a workflow with NEITHER an
        # action NOR a human step does nothing at all.
        #
        # "Zero action nodes" used to return True unconditionally, so a workflow
        # gutted upstream (every node dropped as unreachable, or an unknown
        # actionType coerced to a no-op) was certified EXECUTABLE precisely
        # because it had been emptied. Absence of work is not proof of working.
        human = [n for n in nodes
                 if isinstance(n, dict)
                 and n.get("type") in ("approval", "user_task", "assignment", "task_pool")]
        return bool(human)
    if not all(action_node_executable(n) for n in actions):
        return False
    return mutation_values_resolvable(d)


def find_nonexecutable(output_dir: str | Path) -> list[tuple[str, dict]]:
    """Return [(filename, workflow_dict)] for structurally-valid workflows whose
    action nodes are prose-only (non-executable). Skips malformed files — those are
    the structural floor's job (workflow_completeness)."""
    wf_dir = Path(output_dir) / "workflows"
    out: list[tuple[str, dict]] = []
    for f in sorted(wf_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if is_valid_workflow(d) and not is_executable_workflow(d):
            out.append((f.name, d))
    return out


# A regenerator takes (workflow_dict, plan, domain_context) and returns a rebuilt,
# hopefully-executable workflow dict (or None on failure).
Regenerator = Callable[[dict, Optional[dict], Optional[dict]], Awaitable[Optional[dict]]]


async def ensure_workflow_executability(
    output_dir: str | Path,
    plan: dict | None = None,
    domain_context: dict | None = None,
    regenerate: Regenerator | None = None,
) -> dict:
    """Find non-executable domain workflows and regenerate them against the
    executability contract. `regenerate` defaults to the Anthropic-SDK regenerator
    (skipped when no ANTHROPIC_API_KEY). Returns a report dict.

    Only writes a regenerated workflow back if it is BOTH structurally valid AND
    executable — never replaces a real workflow with a worse one. CRUD workflows are
    already executable (real db params) so they are untouched."""
    nonexec = find_nonexecutable(output_dir)
    report = {
        "checked": _count_workflows(output_dir),
        "nonexecutable": [n for n, _ in nonexec],
        "repaired": [],
        "still_nonexecutable": [],
    }
    if not nonexec:
        return report

    if regenerate is None:
        regenerate = _sdk_regenerate_workflow if os.environ.get("ANTHROPIC_API_KEY") else None
    if regenerate is None:
        report["still_nonexecutable"] = [n for n, _ in nonexec]
        logger.warning(
            "[Workflows] %d non-executable workflow(s), no regenerator available: %s",
            len(nonexec), ", ".join(n for n, _ in nonexec))
        return report

    wf_dir = Path(output_dir) / "workflows"
    for fname, wf in nonexec:
        try:
            rebuilt = await regenerate(wf, plan, domain_context)
        except Exception as exc:  # noqa: BLE001 — one bad workflow must not abort the pass
            logger.warning("[Workflows] regeneration failed for %s: %s", fname, exc)
            rebuilt = None
        if rebuilt is not None and is_executable_workflow(rebuilt):
            # preserve identity so dispatch/binding keep working
            rebuilt["id"] = wf.get("id", rebuilt.get("id"))
            rebuilt["name"] = wf.get("name", rebuilt.get("name"))
            (wf_dir / fname).write_text(json.dumps(rebuilt, indent=2))
            report["repaired"].append(fname)
            logger.info("[Workflows] regenerated executable workflow %s", fname)
        else:
            report["still_nonexecutable"].append(fname)
            logger.warning("[Workflows] could not make %s executable — left as-is", fname)
    return report


def _count_workflows(output_dir: str | Path) -> int:
    return len(list((Path(output_dir) / "workflows").glob("*.json")))


def _contract_text() -> str:
    return (
        "Each action node's data.config MUST carry executable parameters, NOT prose:\n"
        "- db_insert: {actionType:'db_insert', table:'<sql_table>', values:{col: '<value or ${var}>'}}\n"
        "- db_update: {actionType:'db_update', table, where:{col:'${var}'}, values:{col:'...'}}\n"
        "- db_delete: {actionType:'db_delete', table, where:{col:'${var}'}}\n"
        "- db_query:  {actionType:'db_query', table, where:{...}}\n"
        "- send_email: {actionType:'send_email', to:'${var or literal}', subject:'...', body:'...'}\n"
        "- send_notification: {actionType:'send_notification', recipient:'${userId}', title:'...', message:'...'}\n"
        "- http_call: {actionType:'http_call', url:'https://...', method:'POST', body:{...}}\n"
        "Never emit an action node whose only config is a 'description' string. The "
        "'description' may accompany real params but can NEVER replace them."
    )


async def _sdk_regenerate_workflow(
    wf: dict, plan: dict | None, domain_context: dict | None
) -> dict | None:
    """Rebuild one workflow as an executable definition on the Anthropic SDK.

    The current (prose) workflow is handed to the model as the INTENT spec, plus the
    real entity/table list and the executability contract; the model returns a
    complete workflow JSON with executable action configs."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    tables = _table_hints(plan, domain_context)
    prompt = (
        "Rewrite this workflow so every action node is EXECUTABLE. Keep the same intent, "
        "trigger, branching and step order, but replace prose action configs with real "
        "executable params.\n\n"
        f"INTENT (current workflow, action configs are prose to be made real):\n{json.dumps(wf)[:6000]}\n\n"
        f"REAL DATABASE TABLES + columns you may target:\n{tables}\n\n"
        f"EXECUTABILITY CONTRACT:\n{_contract_text()}\n\n"
        "Return ONLY the complete workflow JSON object (id, name, description, "
        "processVariables, definition{trigger,nodes,edges}). No markdown, no commentary."
    )
    try:
        import asyncio
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

        client = llm_client.AsyncAnthropic(api_key=api_key)
        msg = await asyncio.wait_for(
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16000,
                system="You generate executable workflow JSON. Output ONLY a single JSON object.",
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=180,
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Workflows] SDK regenerate error: %s", exc)
        return None
    return _extract_json(text)


def _table_hints(plan: dict | None, domain_context: dict | None) -> str:
    ents = (plan or {}).get("entities")
    if isinstance(ents, dict) and ents:
        lines = []
        for name, info in ents.items():
            tbl = (info or {}).get("table") if isinstance(info, dict) else None
            fields = (info or {}).get("fields") if isinstance(info, dict) else None
            cols = ""
            if isinstance(fields, list):
                cols = ", ".join(f.get("name", "") for f in fields if isinstance(f, dict))
            elif isinstance(fields, dict):
                cols = ", ".join(fields.keys())
            # Never hand the LLM an ENTITY name as if it were a table.
            #
            # `tbl or name` fell back to the entity ("Category"), and the prompt
            # says "REAL DATABASE TABLES you may target" — so the model
            # faithfully emitted `table: "Category"`, which does not exist, and
            # the regenerated workflow failed at runtime with `unknown table`.
            # The naming authority already derives the real table name, so
            # there is no reason to guess (register T3-9).
            if not tbl:
                try:
                    tbl = derive_names(name).tableSnake
                except EntityNameError:
                    logger.warning(
                        "workflow_executability: entity %r has no table and no "
                        "derivable name — omitting it from the regeneration "
                        "prompt rather than offering a table that does not exist.",
                        name,
                    )
                    continue
            lines.append(f"- {tbl}: {cols}")
        return "\n".join(lines)
    return "(entity/table list unavailable — use snake_case plural table names)"


def _extract_json(text: str) -> dict | None:
    import re
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    start = text.find("{")
    if start == -1:
        return None
    # Brace-count OUTSIDE string literals only.
    #
    # Counting every brace meant a `}` inside a string value ended the object
    # early — e.g. a prompt or label containing "}" or a regex like "\\d{2}".
    # json.loads then got a truncated fragment and this returned None, so a
    # perfectly good LLM response was discarded as unparseable.
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None
