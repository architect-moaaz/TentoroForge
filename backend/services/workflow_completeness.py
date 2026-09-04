"""Workflow validity floor (working-app reliability).

Workflows are generated two ways (planner sync + deterministic CRUD), both in the
engine-correct `definition: {trigger, nodes, edges}` shape. But if the business-logic
agent wedges mid-write it can leave a workflow file truncated/empty/partial, and the
engine's loadWorkflows() -> `workflow.definition.nodes.find(...)` will crash at runtime
on a malformed one. This pass guarantees the floor: every workflows/*.json is a valid,
loadable definition, and every plan workflow has a file. Malformed/missing ones are
repaired/created to a minimal valid skeleton (trigger -> end) — so the running app never
crashes loading a workflow. It does NOT touch valid workflows (keeps their real logic).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.workflow_nodes import workflow_node

logger = logging.getLogger(__name__)


def _node(node_id: str, ntype: str, row: int, config: dict, label: str) -> dict:
    return workflow_node(node_id, ntype, row, config, label)


def minimal_workflow(wf_id: str, name: str | None = None) -> dict:
    """A minimal but engine-valid workflow: manual trigger -> end (does nothing)."""
    name = name or wf_id
    return {
        "id": wf_id,
        "name": name,
        "description": f"{name} workflow.",
        "processVariables": [],
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [
                _node("trigger", "trigger", 0, {"type": "manual"}, "Start"),
                _node("end", "end", 1, {}, "End"),
            ],
            "edges": [{"id": "e_trigger_end", "source": "trigger", "target": "end"}],
        },
    }


def is_valid_workflow(d: object) -> bool:
    """Is this a workflow the engine can LOAD without crashing?

    Register T3-13 — the previous one-line docstring said "load + execute", and
    callers relied on the "execute" half. This is a LOADABILITY floor only. It
    checks that `definition` is an object, that `nodes` is a non-empty list in
    which every node has an id and a type, that `edges` is a list, that
    `trigger` is an object, and that a trigger node exists.

    It deliberately does NOT check that:
      * edges reference nodes that exist (the engine tolerates a dangling edge —
        it simply finds no target and stops that path),
      * a terminal node is reachable,
      * any action node is executable or its table/columns exist.

    For "will it actually DO something", use
    :func:`services.workflow_executability.is_executable_workflow`; for graph
    repair use :func:`services.workflow_graph_gate.validate_and_repair`.
    """
    if not isinstance(d, dict):
        return False
    defn = d.get("definition")
    if not isinstance(defn, dict):
        return False
    nodes, edges, trig = defn.get("nodes"), defn.get("edges"), defn.get("trigger")
    if not isinstance(nodes, list) or not nodes:
        return False
    if not isinstance(edges, list):
        return False
    if not isinstance(trig, dict):
        return False
    if not all(isinstance(n, dict) and n.get("id") and n.get("type") for n in nodes):
        return False
    if not any(n.get("type") == "trigger" for n in nodes):
        return False
    return True


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def salvage_workflow(d: object) -> tuple[dict, list[str]] | None:
    """Repair a structurally-invalid workflow IN PLACE, keeping everything usable.

    Returns ``(repaired, losses)`` or ``None`` when there is nothing to salvage.

    ``is_valid_workflow`` rejects the whole file if a SINGLE node is missing an
    ``id`` or ``type``. The caller used to respond by overwriting it with
    :func:`minimal_workflow` — a two-node stub — so one malformed node silently
    destroyed every other node and edge the planner or the LLM had authored.
    The workflow then passed every downstream gate, because a stub is perfectly
    valid; it just does nothing.

    Repairing costs one bad node instead of all of them, and every loss is
    returned so the caller can report it rather than record a clean "repair".
    """
    if not isinstance(d, dict):
        return None
    defn = d.get("definition")
    if not isinstance(defn, dict):
        return None
    nodes = defn.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None

    losses: list[str] = []
    good = []
    for i, n in enumerate(nodes):
        if isinstance(n, dict) and n.get("id") and n.get("type"):
            good.append(n)
        else:
            losses.append(f"node[{i}] dropped (missing id/type): {str(n)[:80]}")
    if not good:
        return None

    keep = {g["id"] for g in good}
    edges = defn.get("edges")
    if not isinstance(edges, list):
        losses.append("edges was not a list — reset to []")
        edges = []
    kept_edges = []
    for e in edges:
        if isinstance(e, dict) and e.get("source") in keep and e.get("target") in keep:
            kept_edges.append(e)
        elif isinstance(e, dict):
            losses.append(f"edge {e.get('source')}→{e.get('target')} dropped (endpoint removed)")

    if not any(n.get("type") == "trigger" for n in good):
        good.insert(0, _node("trigger", "trigger", 0, {"type": "manual"}, "Start"))
        losses.append("no trigger node — a manual trigger was inserted")

    trig = defn.get("trigger")
    if not isinstance(trig, dict):
        trig = {"type": "manual"}
        losses.append("definition.trigger was missing — defaulted to manual")

    repaired = dict(d)
    repaired["definition"] = {**defn, "nodes": good, "edges": kept_edges, "trigger": trig}
    return repaired, losses


def ensure_workflow_validity(output_dir: str | Path, plan: dict | None) -> dict:
    """Repair malformed workflow files + create files for any plan workflow missing one.

    Returns {"repaired": [filenames], "created": [filenames]}.
    """
    wf_dir = Path(output_dir) / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    repaired: list[str] = []
    created: list[str] = []
    present_names: set[str] = set()

    # 1) repair existing malformed/unparseable workflow files (keep valid ones intact)
    for f in sorted(wf_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            d = None
        if d is not None and is_valid_workflow(d):
            present_names.add(_norm(d.get("name")))
            continue
        wid = (d.get("id") if isinstance(d, dict) else None) or f.stem
        wname = (d.get("name") if isinstance(d, dict) else None) or f.stem

        # Salvage before replacing. Overwriting with a stub is a total loss of
        # everything the file contained, and the stub then passes every
        # downstream gate — so a workflow gutted here shipped green.
        salvaged = salvage_workflow(d)
        if salvaged is not None:
            fixed, losses = salvaged
            logger.error(
                "workflow_completeness: %s was structurally invalid and has been "
                "REPAIRED IN PLACE. %d node(s) kept. Losses: %s",
                f.name, len(fixed["definition"]["nodes"]), "; ".join(losses) or "none",
            )
        else:
            fixed = minimal_workflow(wid, wname)
            logger.error(
                "workflow_completeness: %s had NOTHING salvageable (unparseable or "
                "no usable nodes) and was replaced with an empty stub. This "
                "workflow now does nothing — it will pass every downstream gate "
                "and silently perform no work at runtime.",
                f.name,
            )
        if isinstance(d, dict) and d.get("description"):
            fixed["description"] = d["description"]
        f.write_text(json.dumps(fixed, indent=2))
        present_names.add(_norm(wname))
        repaired.append(f.name)

    # 2) ensure every plan workflow has a file
    for wf in (plan or {}).get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        nm = wf.get("name")
        if not nm or _norm(nm) in present_names:
            continue
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", nm).strip("-") or "workflow"
        path = wf_dir / f"{slug}.json"
        if path.exists():
            continue
        mw = minimal_workflow(slug, nm)
        if wf.get("description"):
            mw["description"] = wf["description"]
        # Carry any planner-declared process variables into the stub so the
        # editor picker isn't empty even for a wf we couldn't fully translate.
        try:
            from services.workflow_process_variables import (
                derive_process_variables,
                strip_source,
            )
            pv = strip_source(derive_process_variables(wf, mw["definition"]["nodes"]))
            if pv:
                mw["processVariables"] = pv
        except Exception:
            pass
        path.write_text(json.dumps(mw, indent=2))
        present_names.add(_norm(nm))
        created.append(path.name)

    return {"repaired": repaired, "created": created}
