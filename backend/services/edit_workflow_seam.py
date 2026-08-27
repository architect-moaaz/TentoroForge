"""Structured editor for existing workflow JSON files.

The `add_workflow` seam authors a workflow from scratch; there's been
no matching *edit* seam, so Smith has to reach for `edit_file` when he
needs to tweak an existing workflow — a substring hammer on a JSON
tree, exactly the drift-prone operation this project keeps burning
on.

`edit_workflow` operates on a **structured changes payload**, never
free-form string edits. Every allowed mutation has a named entry
point that validates its own shape and re-serializes the file. The
seam also runs the deterministic plan validator on the modified
workflow before writing, so a change that breaks connectivity or
input coverage is rejected instead of silently shipped.

Supported changes (see :class:`WorkflowChangeSet`)::

    {"add_trigger_input":    {"name": ..., "type": ..., "required": ...}}
    {"remove_trigger_input": "<name>"}
    {"set_step_config":      {"step_id": ..., "path": ["where", "id"], "value": ...}}
    {"add_step":             {"id": ..., "type": ..., "config": {...},
                              "after": "<step_id>"}}
    {"remove_step":          "<step_id>"}
    {"rewire":               {"step_id": ..., "next": "<step_id>"}}
    {"rename":               "<new_id>"}

Multiple changes can be applied in one call; they run in the order
listed. If any step fails validation, NO changes are persisted — the
file is left untouched.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass
class EditResult:
    success: bool
    workflow_id: str
    path: str | None = None
    applied: list[str] = field(default_factory=list)
    error: str | None = None
    violations: list[dict[str, Any]] = field(default_factory=list)
    #: Fingerprint of the file AFTER this edit — hand it back as
    #: ``expected_version`` on the next edit to detect a concurrent write.
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "workflow_id": self.workflow_id,
            "path": self.path,
            "applied": self.applied,
            "error": self.error,
            "violations": self.violations,
            "version": self.version,
        }


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

def _rel_path(output_dir: str, path: str | None) -> str | None:
    """``path`` expressed relative to the project root, forward-slashed.

    The seam used to return the ABSOLUTE path while every consumer speaks
    the project-relative dialect: `smith_edit_tools._safe_path` rejects an
    absolute path outright, and `smith_agent` folds this value into
    `edited_paths` and is then REQUIRED to verify each one. So the
    mandatory verify step could not consume the edit tool's own output
    (register S24-7). `edit_file` — the sibling tool — has always returned
    the relative path; this makes the two agree.
    """
    if not path:
        return path
    try:
        return os.path.relpath(path, output_dir).replace("\\", "/")
    except ValueError:
        # Different drive on Windows — no relative form exists. Returning the
        # absolute path is still better than raising inside a result builder.
        return str(path).replace("\\", "/")


def edit_workflow(
    output_dir: str,
    workflow_id: str,
    changes: dict[str, Any],
    expected_version: str | None = None,
) -> EditResult:
    """Apply ``changes`` to the named workflow in ``output_dir``.

    ``expected_version`` is the sha256 fingerprint the caller last read
    (:attr:`EditResult.version`, or ``smith_concurrency.file_fingerprint``).
    When supplied, the write is refused if the file moved on disk since
    then — the same collision ``routers/workflows.py`` answers with a 409.
    The seam used to take no version and perform no staleness check at all
    (register S23-1/S23-2), so a save the editor would REFUSE, Smith
    performed silently — on the one path that writes with no human
    watching. Omitting it still checks the narrow race between this call's
    own read and its own write.

    Returns :class:`EditResult`. On any validation failure the file
    stays as it was — the seam only persists on green."""
    if not isinstance(changes, dict) or not changes:
        return EditResult(success=False, workflow_id=workflow_id,
                          error=(
                              "changes must be a non-empty dict of "
                              "{operation: args}. Operations: set_step_config "
                              "{step_id, path, value} (e.g. {\"set_step_config\": "
                              "{\"step_id\": \"notify_new\", \"path\": [\"message\"], "
                              "\"value\": \"New product found: ...\"}}), add_step, "
                              "remove_step, rewire, rename, add_trigger_input, "
                              "remove_trigger_input. Read the workflow JSON first "
                              "to find the step id."
                          ))

    path = _resolve_workflow_path(output_dir, workflow_id)
    if not path or not os.path.exists(path):
        return EditResult(success=False, workflow_id=workflow_id,
                          error=f"workflow not found: {workflow_id!r}")

    from services.smith_concurrency import (
        ConcurrentModificationError,
        check_unchanged,
        file_fingerprint,
        save_file_if_unchanged,
    )
    try:
        read_version = check_unchanged(path, expected_fingerprint=expected_version)
    except ConcurrentModificationError as exc:
        return EditResult(success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path),
                          error=str(exc), version=file_fingerprint(path))

    try:
        original = json.load(open(path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return EditResult(success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path),
                          error=f"failed to read workflow JSON: {exc!r}")

    # Work on a deep copy so a mid-changes failure leaves the caller
    # able to compare against `original` for diagnostics.
    import copy
    modified = copy.deepcopy(original)

    applied: list[str] = []
    for op_name, op_args in changes.items():
        handler = _HANDLERS.get(op_name)
        if handler is None:
            return EditResult(
                success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path), applied=applied,
                error=f"unknown change operation: {op_name!r}",
            )
        try:
            handler(modified, op_args)
            applied.append(op_name)
        except _EditError as exc:
            return EditResult(
                success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path), applied=applied,
                error=f"{op_name}: {exc}",
            )

    # Post-condition: connectivity + input coverage check.
    #
    # Only ERROR-severity violations block (register S19-5). The gate was a
    # bare `if violations:` and `_validate_workflow` returns WARNINGS too — and
    # a perfectly ordinary product-generated workflow raises
    # workflow_inputs_missing / workflow_missing_source as warnings. So ANY
    # warning refused EVERY edit, which is why the seam's own test suite sits
    # at 8 failed / 5 passed on committed code. It also means any future
    # validator rule that emits a warning silently disables the whole seam.
    violations = _validate_workflow(modified)
    blocking = [v for v in violations
                if str(v.get("severity", "error")).lower() == "error"]
    if blocking:
        return EditResult(
            success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path), applied=applied,
            error="modified workflow failed structural validation",
            violations=blocking,
        )
    if violations:
        logger.info(
            "edit_workflow_seam: %s applied with %d warning-level violation(s): %s",
            workflow_id, len(violations),
            ", ".join(str(v.get("rule")) for v in violations),
        )

    # A rename is a FILE move; the id follows the filename, never diverges.
    rename_to = modified.pop("__rename_to", None)
    if isinstance(rename_to, str) and rename_to:
        new_path = os.path.join(os.path.dirname(path), f"{rename_to}.json")
        if os.path.abspath(new_path) != os.path.abspath(path) and os.path.exists(new_path):
            return EditResult(
                success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path), applied=applied,
                error=(f"rename target workflows/{rename_to}.json already exists — "
                       f"nothing was written"),
            )
        # The document's id is set to the NEW STEM so the two always agree —
        # `canonical_workflow` would overwrite anything else on the next read.
        modified["id"] = rename_to

    # Persist through the optimistic lock — the file-level twin of the
    # blueprint's `save_if_unchanged`. Validation above can take long enough
    # for a real race, so the check happens at the WRITE, not just at the read.
    try:
        save_file_if_unchanged(
            path,
            lambda: _atomic_write_json(path, modified),
            expected_fingerprint=read_version,
        )
    except ConcurrentModificationError as exc:
        return EditResult(success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path),
                          applied=applied, error=str(exc),
                          version=file_fingerprint(path))
    except Exception as exc:  # noqa: BLE001
        return EditResult(success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path),
                          applied=applied, error=f"write failed: {exc!r}")

    # A rename must move the FILE too (register S19-2).
    #
    # `_op_rename` set `wf["id"]` and nothing else, so the id and the filename
    # diverged — and `routers/workflows.py:canonical_workflow` force-overwrites
    # `id` from the filename stem on every read. So the rename silently REVERTED
    # the moment anyone loaded the workflow, and the seam had already reported
    # success. The filename is the canonical id everywhere in this system (the
    # engine loads `workflows/{id}.json`), so renaming means moving the file.
    # ONLY when a `rename` op was actually applied.
    #
    # Keying on "id differs from stem" is wrong: product workflows legitimately
    # carry an internal id that differs from their filename (build_crud_workflow
    # writes id="update-order" into UpdateOrder.json), which is precisely why
    # `canonical_workflow` exists. Renaming on that mismatch moved every file
    # the seam touched — an unrelated set_step_config edit would silently
    # relocate the workflow.
    current_stem = os.path.splitext(os.path.basename(path))[0]
    if isinstance(rename_to, str) and rename_to and rename_to != current_stem:
        new_path = os.path.join(os.path.dirname(path), f"{rename_to}.json")
        new_id = rename_to
        try:
            os.replace(path, new_path)
            logger.info("edit_workflow: renamed %s.json -> %s.json", current_stem, new_id)
            path = new_path
            workflow_id = new_id
        except OSError as exc:
            return EditResult(
                success=False, workflow_id=workflow_id, path=_rel_path(output_dir, path), applied=applied,
                error=(f"content saved but rename failed ({exc!r}); id and filename "
                       f"now diverge and readers will revert the id"),
            )

    logger.info(
        "edit_workflow: %s applied to %s (%d op(s))",
        workflow_id, os.path.relpath(path, output_dir), len(applied),
    )
    return EditResult(success=True, workflow_id=workflow_id, path=_rel_path(output_dir, path),
                      applied=applied, version=file_fingerprint(path))


# --------------------------------------------------------------------------- #
# Change handlers
# --------------------------------------------------------------------------- #

class _EditError(Exception):
    pass


def _trigger_node(wf: dict[str, Any]) -> dict[str, Any]:
    for step in _iter_steps(wf):
        if step.get("type") == "trigger":
            return step
    raise _EditError("workflow has no trigger node")


def _steps_container(wf: dict[str, Any]) -> tuple[dict[str, Any], str, list]:
    """The dict that OWNS the step list, its key, and the list ITSELF.

    Register S19-1. Every op read `wf["nodes"]` / `wf["steps"]` at the TOP
    level, but every workflow this product generates nests them under
    `definition` (crud_workflow_generator, workflow_step_translator). On a real
    file the seam therefore saw an EMPTY list and 6 of the 7 edit ops failed
    with a misleading "step not found" / "workflow has no trigger node" — while
    the file plainly had both. This is the seam advertised to Smith as the safe
    structured editor, so its headline failure mode was refusing to edit
    anything real and blaming the workflow.

    Returning the owner and key (not a copy) is the other half: `_iter_steps`
    used to return a FILTERED COPY, so an op that appended to it mutated a
    temporary list and the edit silently went nowhere.

    `definition` is checked first because that is the product shape; the
    top-level fallback keeps the planner/legacy shape working.
    """
    defn = wf.get("definition")
    if isinstance(defn, dict):
        for key in ("nodes", "steps"):
            if isinstance(defn.get(key), list):
                return defn, key, defn[key]
    for key in ("nodes", "steps"):
        if isinstance(wf.get(key), list):
            return wf, key, wf[key]
    # Nothing yet — create it where the workflow's own shape says it belongs.
    if isinstance(defn, dict):
        defn.setdefault("nodes", [])
        return defn, "nodes", defn["nodes"]
    wf.setdefault("nodes", [])
    return wf, "nodes", wf["nodes"]


def _iter_steps(wf: dict[str, Any]) -> list[dict[str, Any]]:
    """The step dicts, read through the single shape accessor."""
    return [n for n in _steps_container(wf)[2] if isinstance(n, dict)]


def _arg_step_id(args: Any, what: str = "step id") -> str:
    """The step id from an op's arguments, in any of the shapes callers use.

    The ops disagreed about their own argument contract: `remove_step` required
    a BARE STRING, `rewire` read `step_id`, and `set_step_config` read
    `step_id` — while callers (Smith, and the QA fixtures modelled on real
    usage) pass `{"id": ...}`. A seam whose entire purpose is being the SAFE
    structured editor cannot have a different argument shape per op; the
    mismatch simply produced "step None not found" (register S19-1's family).
    Accept all three spellings, once, here.
    """
    if isinstance(args, str) and args:
        return args
    if isinstance(args, dict):
        for key in ("id", "step_id", "node_id"):
            v = args.get(key)
            if isinstance(v, str) and v:
                return v
    raise _EditError(f"expected {what} as a string or {{'id': ...}}")


def _edges_container(wf: dict[str, Any]) -> tuple[dict[str, Any], list] | None:
    """The dict owning `edges` and the list itself, for a runtime-shaped
    workflow. None when the workflow uses `next` pointers instead."""
    defn = wf.get("definition")
    if isinstance(defn, dict) and isinstance(defn.get("edges"), list):
        return defn, defn["edges"]
    if isinstance(wf.get("edges"), list):
        return wf, wf["edges"]
    return None


def _step_config(step: dict[str, Any]) -> dict[str, Any]:
    """Return the mutable config dict, tolerating both `data.config`
    (renderer shape) and top-level `config` (planner shape)."""
    if isinstance(step.get("data"), dict):
        cfg = step["data"].setdefault("config", {})
        if isinstance(cfg, dict):
            return cfg
    cfg = step.setdefault("config", {})
    if not isinstance(cfg, dict):
        cfg = {}
        step["config"] = cfg
    return cfg


# --- add_trigger_input ------------------------------------------------------

def _op_add_trigger_input(wf: dict[str, Any], args: Any) -> None:
    if not isinstance(args, dict):
        raise _EditError("expected {name, type, required?}")
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _EditError("input name is required")
    trigger = _trigger_node(wf)
    cfg = _step_config(trigger)
    inputs = cfg.setdefault("inputs", [])
    if not isinstance(inputs, list):
        raise _EditError("trigger config.inputs must be a list")
    for existing in inputs:
        if isinstance(existing, dict) and existing.get("name") == name:
            # Idempotent — already present.
            return
    inputs.append({
        "name": name,
        "type": args.get("type", "string"),
        "required": bool(args.get("required", False)),
    })


# --- remove_trigger_input ---------------------------------------------------

def _op_remove_trigger_input(wf: dict[str, Any], args: Any) -> None:
    if not isinstance(args, str):
        raise _EditError("expected string input name")
    trigger = _trigger_node(wf)
    cfg = _step_config(trigger)
    inputs = cfg.get("inputs")
    if not isinstance(inputs, list):
        return  # nothing to do
    cfg["inputs"] = [i for i in inputs
                     if not (isinstance(i, dict) and i.get("name") == args)]


# --- set_step_config --------------------------------------------------------

def _op_set_step_config(wf: dict[str, Any], args: Any) -> None:
    if not isinstance(args, dict):
        raise _EditError("expected {step_id, path, value}")
    step_id = args.get("step_id")
    path = args.get("path")
    value = args.get("value")
    if not isinstance(step_id, str) or not step_id:
        raise _EditError("step_id required")
    if not isinstance(path, list) or not all(isinstance(p, str) for p in path):
        raise _EditError("path must be a list of string keys")
    target = None
    for step in _iter_steps(wf):
        if step.get("id") == step_id:
            target = step
            break
    if target is None:
        raise _EditError(f"step {step_id!r} not found")
    cfg = _step_config(target)
    _set_deep(cfg, path, value)


_MAX_SET_DEPTH = 12


def _set_deep(container: dict[str, Any], path: list[str], value: Any) -> None:
    """Set `value` at `path`, refusing to destroy what is already there.

    Register S19-4. This replaced ANY non-dict intermediate with `{}` — no type
    guard, no depth limit. So setting `values.status` on a config whose
    `values` was a string silently DELETED that string, and a hostile or
    mistaken path could walk arbitrarily deep. Overwriting data the caller did
    not name is never part of "set this key": refuse and say so.
    """
    if not path:
        raise _EditError("empty config path")
    if len(path) > _MAX_SET_DEPTH:
        raise _EditError(
            f"config path is {len(path)} levels deep (limit {_MAX_SET_DEPTH}): "
            f"{'.'.join(path)}"
        )
    cur = container
    for i, key in enumerate(path[:-1]):
        nxt = cur.get(key)
        if nxt is None:
            nxt = {}
            cur[key] = nxt
        elif not isinstance(nxt, dict):
            raise _EditError(
                f"cannot set {'.'.join(path)}: {'.'.join(path[:i + 1])} is a "
                f"{type(nxt).__name__}, not an object — overwriting it would "
                f"destroy the value already there"
            )
        cur = nxt
    cur[path[-1]] = value


# --- add_step ---------------------------------------------------------------

def _op_add_step(wf: dict[str, Any], args: Any) -> None:
    if not isinstance(args, dict):
        raise _EditError("expected {id, type, config, after}")
    new_id = args.get("id")
    if not isinstance(new_id, str) or not new_id:
        raise _EditError("id required")
    after = args.get("after")
    if not isinstance(after, str) or not after:
        raise _EditError("after (predecessor step_id) required")
    steps = _iter_steps(wf)
    if any(s.get("id") == new_id for s in steps):
        raise _EditError(f"step {new_id!r} already exists")
    predecessor = next((s for s in steps if s.get("id") == after), None)
    if predecessor is None:
        raise _EditError(f"predecessor step {after!r} not found")

    new_step = {
        "id": new_id,
        "type": args.get("type", "action"),
        "data": {"config": args.get("config", {})} if "data" in predecessor
                else {},
    }
    if "data" not in new_step:
        new_step["config"] = args.get("config", {})
    # Insert AFTER the predecessor in the REAL nodes list + rewire next.
    # Third site that re-derived the shape at the top level (register S19-1);
    # on a product workflow this appended to a list nobody reads.
    owner, key, nodes = _steps_container(wf)
    idx = next(i for i, s in enumerate(nodes) if s is predecessor)
    prev_next = predecessor.get("next")
    predecessor["next"] = new_id
    new_step["next"] = prev_next
    nodes.insert(idx + 1, new_step)
    wf[key] = nodes


# --- remove_step ------------------------------------------------------------

def _op_remove_step(wf: dict[str, Any], args: Any) -> None:
    args = _arg_step_id(args)
    # Same accessor as every other op — this re-derived the shape at the top
    # level and so operated on the wrong (usually absent) list.
    owner, key, nodes = _steps_container(wf)
    victim = None
    victim_idx = None
    for i, s in enumerate(nodes):
        if isinstance(s, dict) and s.get("id") == args:
            victim = s
            victim_idx = i
            break
    if victim is None:
        raise _EditError(f"step {args!r} not found")
    if victim.get("type") == "trigger":
        raise _EditError("cannot remove trigger step")
    # Rewire predecessors, in WHICHEVER connectivity model this workflow uses.
    #
    # This only ever rewired `next` pointers. A runtime-shaped workflow
    # expresses connectivity as `definition.edges`, so removing a node left its
    # edges dangling and the graph broken — the node vanished but the path
    # through it did not.
    successor = victim.get("next")
    for s in nodes:
        if isinstance(s, dict) and s.get("next") == args:
            s["next"] = successor
    del nodes[victim_idx]

    edges_pair = _edges_container(wf)
    if edges_pair is not None:
        _owner, edges = edges_pair
        incoming = [e for e in edges if isinstance(e, dict) and e.get("target") == args]
        outgoing = [e for e in edges if isinstance(e, dict) and e.get("source") == args]
        # Bridge each predecessor to each successor so the path survives.
        bridged = []
        for inc in incoming:
            for out in outgoing:
                src, tgt = inc.get("source"), out.get("target")
                if src and tgt and src != tgt:
                    bridged.append({"id": f"e_{src}_{tgt}", "source": src, "target": tgt})
        edges[:] = [e for e in edges
                    if not (isinstance(e, dict)
                            and (e.get("source") == args or e.get("target") == args))]
        seen = {(e.get("source"), e.get("target")) for e in edges if isinstance(e, dict)}
        for b in bridged:
            if (b["source"], b["target"]) not in seen:
                edges.append(b)
                seen.add((b["source"], b["target"]))


# --- rewire -----------------------------------------------------------------

def _op_rewire(wf: dict[str, Any], args: Any) -> None:
    if not isinstance(args, dict):
        raise _EditError("expected {step_id, next?, branches?}")
    step_id = _arg_step_id(args)
    step = next((s for s in _iter_steps(wf) if s.get("id") == step_id), None)
    if step is None:
        raise _EditError(f"step {step_id!r} not found")
    if "next" in args:
        target = args["next"]
        step["next"] = target
        # A runtime-shaped workflow is wired by EDGES; setting `next` on the
        # node changes nothing the engine reads. Replace this node's outgoing
        # edges with the requested one.
        edges_pair = _edges_container(wf)
        if edges_pair is not None and isinstance(target, str) and target:
            _owner, edges = edges_pair
            known = {n.get("id") for n in _iter_steps(wf)}
            if target not in known:
                raise _EditError(f"rewire target {target!r} is not a step in this workflow")
            edges[:] = [e for e in edges
                        if not (isinstance(e, dict) and e.get("source") == step_id)]
            edges.append({"id": f"e_{step_id}_{target}",
                          "source": step_id, "target": target})
    if "branches" in args:
        step["branches"] = args["branches"]


# --- rename -----------------------------------------------------------------

def _op_rename(wf: dict[str, Any], args: Any) -> None:
    """Request a rename. Records the target; does NOT write a divergent id.

    Setting `wf["id"]` here was the whole defect (register S19-2). The FILENAME
    is the canonical id everywhere in this system — the engine loads
    `workflows/{id}.json`, and `routers/workflows.py:canonical_workflow`
    force-overwrites `data["id"]` from the stem on every read. So writing a new
    id into the document produced a file whose id disagreed with its name, and
    the next reader silently reverted it. The rename is a FILE operation; the
    caller performs it after the write and sets the id to match the new stem.
    """
    if not isinstance(args, str) or not args:
        raise _EditError("expected non-empty new id")
    wf["__rename_to"] = args


_HANDLERS = {
    "add_trigger_input":    _op_add_trigger_input,
    "remove_trigger_input": _op_remove_trigger_input,
    "set_step_config":      _op_set_step_config,
    "add_step":             _op_add_step,
    "remove_step":          _op_remove_step,
    "rewire":               _op_rewire,
    "rename":               _op_rename,
}


# --------------------------------------------------------------------------- #
# Post-condition validation
# --------------------------------------------------------------------------- #

def _validate_workflow(wf: dict[str, Any]) -> list[dict[str, Any]]:
    """Structural checks — mirror the V2 plan validator's workflow-connectivity
    + input-coverage rules. Returns a list of violations (empty on green)."""
    # Validate with the validator that MATCHES THE SHAPE (register S19-3).
    #
    # There are two graph representations in this product and they express
    # connectivity differently:
    #
    #   planner shape — top-level `steps`, each carrying a `next` pointer
    #   runtime shape — `definition.nodes` + `definition.edges`, NO `next`
    #
    # `plan_validator` only understands the first. Feeding it a runtime
    # workflow made it report `node_missing_next` as an ERROR for every node —
    # a graph that is perfectly well connected by edges — so every edit to a
    # real workflow was refused as "structurally invalid". Projecting the steps
    # up (the first attempt at this fix) moved the failure without curing it,
    # because the rules themselves read `next`.
    #
    # A runtime workflow is therefore validated by the graph gate, which is the
    # authority for nodes+edges; only a genuinely planner-shaped workflow goes
    # to plan_validator.
    defn = wf.get("definition")
    is_runtime_shape = (
        isinstance(defn, dict)
        and isinstance(defn.get("nodes"), list)
        and isinstance(defn.get("edges"), list)
    )

    if is_runtime_shape:
        from services.workflow_graph_gate import validate_and_repair
        # Non-destructive: report, never rewrite the author's graph here.
        _, report = validate_and_repair(wf, drop_unreachable=False)
        out: list[dict[str, Any]] = []
        for msg in report.get("errors") or []:
            out.append({"rule": "workflow_graph", "severity": "error", "message": msg})
        for msg in report.get("warnings") or []:
            out.append({"rule": "workflow_graph", "severity": "warning", "message": msg})
        return out

    from services.plan_validator import validate_plan
    plan_shape = {"workflows": [wf]}
    # Only workflow-related rules matter here — filter the results.
    all_v = validate_plan(plan_shape)
    return [v for v in all_v
            if v.get("rule", "").startswith("workflow")
            or v.get("rule", "").startswith("node_")
            or v.get("rule", "").startswith("gateway_")]


# --------------------------------------------------------------------------- #
# Path resolution + atomic write
# --------------------------------------------------------------------------- #

def normalize_workflow_key(name: str) -> str:
    """The key every workflow-name lookup in the system compares on.

    Exported so the RESOLVER and the collision guards agree by construction.
    `add_workflow` used an exact-basename check while every resolver was
    case/separator-insensitive, so `create_candidate.json` could be created
    beside `CreateCandidate.json` and the resolver could then not tell them
    apart (register S20-2).
    """
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _resolve_workflow_path(output_dir: str, workflow_id: str) -> str | None:
    wf_dir = os.path.join(output_dir, "workflows")
    if not os.path.isdir(wf_dir):
        return None
    # Exact-name first — an exact match is never ambiguous.
    exact = os.path.join(wf_dir, f"{workflow_id}.json")
    if os.path.exists(exact):
        return exact

    # Fuzzy fallback: case- and separator-insensitive. An AMBIGUOUS match now
    # refuses instead of returning whichever file `listdir` happened to yield
    # first (register S20-1).
    #
    # `create-candidate.json`, `Create_Candidate.json` and `CreateCandidate.json`
    # all normalise to the same key, so on a directory containing two of them
    # Smith's edit silently landed in a DIFFERENT workflow than the one named —
    # and the seam reported success. Editing the wrong file is far worse than
    # not finding one, so when the name does not identify a single workflow we
    # decline and let the caller disambiguate with an exact id.
    wanted = normalize_workflow_key(workflow_id)
    matches = [
        os.path.join(wf_dir, fn)
        for fn in sorted(os.listdir(wf_dir))
        if fn.lower().endswith(".json") and normalize_workflow_key(fn[:-5]) == wanted
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.error(
            "edit_workflow_seam: %r matches %d workflow files (%s) — refusing to "
            "guess which one to edit. Use the exact filename stem.",
            workflow_id, len(matches),
            ", ".join(os.path.basename(m) for m in matches),
        )
    return None


def _atomic_write_json(path: str, data: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
