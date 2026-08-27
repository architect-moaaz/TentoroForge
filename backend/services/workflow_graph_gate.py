"""Deterministic workflow executability gate + auto-repair.

Statically "simulates" each generated workflow — walks the graph from the
trigger, tracking reachability and variable availability — and repairs the
issues that make a workflow silently fail at runtime: dangling edges,
unreachable nodes, no reachable terminal, dead-end nodes, planner-only node
types the engine can't run, unknown actionTypes with no handler, and human
tasks with no assignee. All fixes are deterministic and idempotent (re-running
the gate on repaired output is a no-op).

This is the drift-free version of a simulate-and-repair loop: instead of
executing the TS engine, it verifies the graph WOULD execute coherently and
fixes it against the authoritative node contract (workflow_node_contracts).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable

from services.workflow_node_contracts import node_contracts, real_actions
from services.workflow_variable_contract import analyze_workflow

logger = logging.getLogger(__name__)

_TERMINAL = {"end", "end_event"}
# Planner-level node types → the runtime node type the engine actually executes.
_NODE_TYPE_ALIASES = {"assignment": "user_task", "task_pool": "user_task", "escalation": "action"}
# Variable roots that are always available at runtime (not produced by a node).
_AMBIENT_ROOTS = {"input", "trigger", "user", "now", "scheduledat", "env"}


def _defn(wf: dict) -> dict:
    return wf.get("definition") if isinstance(wf.get("definition"), dict) else {}


def _graph_order(nodes: list, edges: list) -> dict[str, int]:
    """Distance from the trigger for every node — the real execution order.

    A BFS from the trigger, so "later" means "further downstream", not "further
    down the JSON array". Nodes unreachable from the trigger (and graphs with no
    trigger at all) fall back to array position, which is the only ordering
    available for them and matches the previous behaviour."""
    ids = [n["id"] for n in nodes if isinstance(n, dict) and n.get("id")]
    order: dict[str, int] = {nid: i for i, nid in enumerate(ids)}

    adj: dict[str, list[str]] = {}
    for e in edges or []:
        if isinstance(e, dict) and e.get("source") and e.get("target"):
            adj.setdefault(e["source"], []).append(e["target"])

    trig = next((n["id"] for n in nodes
                 if isinstance(n, dict) and n.get("type") == "trigger"), None)
    if trig is None:
        return order

    depth = 0
    seen = {trig}
    frontier = [trig]
    while frontier:
        for nid in frontier:
            order[nid] = depth
        nxt = []
        for nid in frontier:
            for tgt in adj.get(nid, []):
                if tgt not in seen:
                    seen.add(tgt)
                    nxt.append(tgt)
        frontier = nxt
        depth += 1

    # Anything unreachable sorts after everything reachable, so a reference
    # into it is still reported.
    for nid in ids:
        if nid not in seen:
            order[nid] = depth + order.get(nid, 0)
    return order


def _iter_strings(v: object) -> Iterable[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _iter_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _iter_strings(x)


def validate_and_repair(
    wf: dict,
    contract: dict | None = None,
    *,
    drop_unreachable: bool = False,
) -> tuple[dict, dict]:
    """Return (repaired_wf, report).
    report = {fixed, warnings, errors, unproduced_vars}.

    ``drop_unreachable`` — whether a node unreachable from the trigger is
    DELETED. **Defaults to False: keep the node and report it.**

    The default used to be True, and both register rows about this behaviour
    (T3-4 and A16-1) describe deletion as the defect: "deletes unreachable
    nodes instead of connecting them or reporting them". Adding a node and not
    yet wiring it is the normal MIDDLE of an edit — drop it on the canvas, then
    connect it — so deleting it removes a node the author just created from
    their own saved graph while they are still working. An unreachable node is
    also harmless at runtime: the walk simply never reaches it.

    `run_workflow_gate` passes True explicitly, so the GENERATION pipeline
    still prunes a graph it considers final. Any other caller gets the safe
    behaviour by default."""
    contract = contract or node_contracts()
    valid_node_types = set(contract["node_types"]) | {"trigger"}
    real = real_actions()
    known_actions = set(contract["actions"])
    report: dict = {"fixed": [], "warnings": [], "errors": [], "unproduced_vars": []}

    defn = _defn(wf)
    _raw_nodes = defn.get("nodes") or []
    nodes = [n for n in _raw_nodes if isinstance(n, dict) and n.get("id")]
    # A node with no id DISAPPEARED here without a word (register T3-12).
    # It is authored work being deleted; say so, the way the unreachable-node
    # deletion below does.
    _idless = len(_raw_nodes) - len(nodes)
    if _idless:
        report["errors"].append(
            f"{_idless} node(s) had no usable id and were DROPPED — authored "
            f"steps that will never run. A node without an id cannot be "
            f"referenced by an edge, so the graph silently does less than authored."
        )
    edges = [e for e in (defn.get("edges") or []) if isinstance(e, dict)]
    if not nodes:
        report["errors"].append("workflow has no nodes")
        return wf, report

    ids = {n["id"] for n in nodes}

    # 1. Drop edges whose endpoints don't exist.
    kept = []
    for e in edges:
        if e.get("source") in ids and e.get("target") in ids:
            kept.append(e)
        else:
            report["fixed"].append(f"dropped dangling edge {e.get('source')}→{e.get('target')}")
    edges = kept

    # 2. Normalize node types + coerce unknown actionTypes + default assignees.
    for n in nodes:
        t = n.get("type")
        if t in _NODE_TYPE_ALIASES:
            n["type"] = _NODE_TYPE_ALIASES[t]
            n.setdefault("data", {})["nodeType"] = n["type"]
            report["fixed"].append(f"normalized node type {t}→{n['type']} ({n['id']})")
            t = n["type"]
        elif t not in valid_node_types:
            report["warnings"].append(f"unknown node type '{t}' on {n['id']}")
        if t == "action":
            cfg = n.setdefault("data", {}).setdefault("config", {})
            at = cfg.get("actionType")
            if at and at not in known_actions:
                cfg["actionType"] = "set_variable"
                cfg["variableName"] = f"{n['id']}_done"
                cfg["variableValue"] = True
                # Recorded as BOTH a fix and an error — same treatment as the
                # unreachable-node deletion below.
                #
                # The coercion is a genuine repair: it keeps the graph
                # structurally valid. But the node no longer DOES anything, so
                # an unknown action becomes a certified no-op. Filing it ONLY
                # under `fixed` told every downstream gate the workflow was
                # healthy, so a workflow that had lost its only real action
                # shipped green and the button did nothing. Turning work into a
                # no-op is a loss to report as well as a repair to record.
                report["fixed"].append(
                    f"coerced unknown actionType '{at}'→set_variable ({n['id']})"
                )
                report["errors"].append(
                    f"unknown actionType '{at}' on {n['id']} — coerced to a "
                    f"no-op set_variable so the graph stays valid, but this node "
                    f"no longer performs any action"
                )
            elif at and at not in real:
                report["warnings"].append(f"action '{at}' on {n['id']} is not a real handler")
        if t in ("approval", "user_task"):
            cfg = n.setdefault("data", {}).setdefault("config", {})
            if not (cfg.get("assignee") or cfg.get("assigneeRole") or cfg.get("assignment")):
                cfg["assigneeRole"] = "admin"
                report["fixed"].append(f"defaulted assignee on {n['id']}")

    by_id = {n["id"]: n for n in nodes}
    out_adj: dict[str, list[str]] = {}
    for e in edges:
        out_adj.setdefault(e["source"], []).append(e["target"])

    # 3. Reachability from the trigger — drop nodes that can never run.
    trig = next((n for n in nodes if n.get("type") == "trigger"), None)
    if trig is None:
        report["errors"].append("no trigger node")
    reachable: set[str] = set()
    if trig:
        stack = [trig["id"]]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(out_adj.get(cur, []))
        unreachable = [nid for nid in by_id if nid not in reachable]
        if unreachable and not drop_unreachable:
            # Interactive path — report, never destroy (register A16-1).
            report["warnings"].append(
                f"{len(unreachable)} node(s) are not yet reachable from the "
                f"trigger: {unreachable}. They are KEPT — connect them to make "
                f"them run."
            )
            unreachable = []
        if unreachable:
            nodes = [n for n in nodes if n["id"] in reachable]
            edges = [e for e in edges if e["source"] in reachable and e["target"] in reachable]
            by_id = {n["id"]: n for n in nodes}
            out_adj = {}
            for e in edges:
                out_adj.setdefault(e["source"], []).append(e["target"])
            # Deletion is recorded as an ERROR as well as a fix. The nodes are
            # authored work that the graph will never run; removing them makes
            # the graph valid but does not make the workflow correct. Filing it
            # only under `fixed` meant the pipeline certified a workflow it had
            # just emptied — the "silent certification" chain.
            report["fixed"].append(f"dropped {len(unreachable)} unreachable node(s): {unreachable}")
            report["errors"].append(
                f"{len(unreachable)} node(s) unreachable from the trigger were "
                f"DELETED: {unreachable} — authored steps that will never run. "
                f"The graph is now valid but the workflow does less than authored."
            )

    # 4. Ensure a terminal exists, then connect every dead-end to it.
    end_id = next((nid for nid, n in by_id.items() if n.get("type") in _TERMINAL), None)
    if end_id is None:
        end_id = "end"
        while end_id in by_id:
            end_id += "_x"
        end_node = {"id": end_id, "type": "end",
                    "position": {"x": 250, "y": 9999},
                    "data": {"label": "Complete", "nodeType": "end"}}
        nodes.append(end_node)
        by_id[end_id] = end_node
        report["fixed"].append("added missing terminal (end) node")
    for nid, n in list(by_id.items()):
        if n.get("type") in _TERMINAL or nid == end_id:
            continue
        if not out_adj.get(nid):
            edges.append({"id": f"e_{nid}_{end_id}", "source": nid, "target": end_id})
            out_adj.setdefault(nid, []).append(end_id)
            report["fixed"].append(f"connected dead-end {nid}→{end_id}")

    # 5. Dataflow warning: {{node.*}} refs to a later/self node (unresolvable at run).
    #
    # Order is GRAPH order (distance from the trigger), not array position.
    #
    # `enumerate(nodes)` made the JSON array's ordering the definition of
    # "later", so a node that appears late in the file but runs early in the
    # graph was reported as an unresolvable forward reference, while a genuine
    # forward reference whose target happened to sit earlier in the array was
    # missed entirely. Nothing guarantees the array is in execution order — the
    # editor writes nodes in creation order. Same array-order-as-truth defect
    # as RT-10 (register T3-10).
    order = _graph_order(nodes, edges)
    for n in nodes:
        cfg = (n.get("data") or {}).get("config") or {}
        for s in _iter_strings(cfg):
            for m in re.findall(r"\{\{\s*([\w.]+)\s*\}\}", s):
                head = m.split(".")[0]
                if head.lower() in _AMBIENT_ROOTS:
                    continue
                if head in order and order[head] >= order.get(n["id"], 10 ** 9):
                    report["warnings"].append(f"{n['id']} references {{{{{m}}}}} from a later/self node")

    defn["nodes"] = nodes
    defn["edges"] = edges
    wf["definition"] = defn

    # 6. Variable provenance: flag any gateway/condition that branches on a
    # variable no upstream node produces (a dead branch — every record routes to
    # the else path). Runs on the FINAL repaired graph. Conservative: no registry
    # is threaded here, so a trigger-entity column is NOT auto-counted as a
    # producer (see workflow_variable_contract.producers) — that keeps this
    # detector alive for the exact dead-branch class it targets (e.g. f4pw5y5k's
    # `overallRecommendation` gateway). Flag-only; never mutates the workflow.
    for finding in analyze_workflow(wf):
        report["unproduced_vars"].append(finding)
        report["warnings"].append(
            f"gateway {finding['node']} branches on '{finding['variable']}' "
            f"which no upstream node produces — dead branch "
            f"(expression: {finding['expression']})"
        )
    return wf, report


def run_workflow_gate(output_dir: str | Path, plan: dict | None = None) -> dict:
    """Gate + repair every workflow JSON in the project. Writes repaired files
    back in place. Returns a summary {checked, repaired, warnings, reports}."""
    wf_dir = Path(output_dir) / "workflows"
    if not wf_dir.exists():
        return {"checked": 0, "repaired": 0, "warnings": 0, "reports": {}}
    contract = node_contracts()

    # SOURCE-side value↔column TYPE map, built once from the canonical registry.
    # Lets us catch/repair db_insert/db_update values whose KIND is wrong for the
    # target column (e.g. CURRENT_TIMESTAMP into a uuid FK, a leaked node label
    # into an enum/status column). No registry → the pass is a no-op.
    columns_by_table: dict = {}
    try:
        from services.workflow_value_types import (
            columns_by_table_from_registry,
            repair_workflow_dict,
        )
        from services.fk_semantics import _load_registry

        _reg = _load_registry(str(output_dir))
        if _reg:
            columns_by_table = columns_by_table_from_registry(_reg)
    except Exception:
        columns_by_table = {}

    checked = repaired = warn_count = error_count = 0
    reports: dict = {}
    unproduced_findings: list[dict] = []
    value_type_changes: list[dict] = []
    error_findings: list[dict] = []
    unreadable: list[str] = []
    for f in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A workflow this gate cannot READ is a workflow it has not
            # checked. Skipping it silently meant an unparseable file was
            # indistinguishable from a clean pass in the gate's own totals.
            logger.error(
                "workflow_graph_gate: could not read %s (%s) — its graph is "
                "UNCHECKED and may be invalid at runtime", f.name, exc,
            )
            unreadable.append(f.name)
            error_count += 1
            continue
        checked += 1
        # Generation opts IN to pruning: the graph is final here, so an
        # unreachable node is dead weight rather than work in progress.
        wf2, rep = validate_and_repair(wf, contract, drop_unreachable=True)

        # Value↔column type repair (source pass). Flag/repair; never crash.
        vt_changes: list[dict] = []
        if columns_by_table:
            try:
                wf2, vt_changes = repair_workflow_dict(wf2, columns_by_table)
            except Exception:
                vt_changes = []
        if vt_changes:
            rep.setdefault("value_type_fixes", []).extend(vt_changes)
            for c in vt_changes:
                value_type_changes.append({"workflow": f.name, **c})

        reports[f.stem] = rep
        warn_count += len(rep["warnings"])
        # Hard errors used to stay buried inside `reports[<stem>]["errors"]`,
        # which no caller read — post_generate_fixes logs only the counters
        # this function returns. So a workflow the gate KNEW was broken (no
        # trigger, no nodes, an action coerced to a no-op, steps deleted as
        # unreachable) was reported to the pipeline as a clean run. Surface
        # them, and log each one at ERROR as it is found.
        for _err in rep.get("errors", []):
            error_count += 1
            error_findings.append({"workflow": f.name, "error": _err})
            logger.error("workflow_graph_gate: %s — %s", f.name, _err)
        for finding in rep.get("unproduced_vars", []):
            unproduced_findings.append({"workflow": f.name, **finding})
        if rep["fixed"] or vt_changes:
            f.write_text(json.dumps(wf2, indent=2), encoding="utf-8")
            repaired += 1
    return {
        "checked": checked,
        "repaired": repaired,
        "warnings": warn_count,
        # `errors` / `blocking` are what a caller must branch on. Without
        # them the gate could only ever report success.
        "errors": error_count,
        "error_findings": error_findings,
        "unreadable": unreadable,
        "blocking": bool(error_count),
        "reports": reports,
        "unproduced_vars": len(unproduced_findings),
        "unproduced_var_findings": unproduced_findings,
        "value_type_fixes": len(value_type_changes),
        "value_type_fix_changes": value_type_changes,
    }
