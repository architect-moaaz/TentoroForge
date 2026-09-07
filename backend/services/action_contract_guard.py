"""Post-generation action-contract reconciler/validator (Slice 3 of the
resource-binding contract).

The planner authors, per page, an explicit *action intent*: each workflow-backed
button/form carries `{label, workflow, kind}` and (Slice 3) optionally
`input_map: {formField -> entityColumn}` + `requires_record: bool`. But the
planner runs BEFORE the workflows and schemas exist, so its intent is unvalidated
guesswork. This guard runs AFTER workflows + schemas are generated (like the other
workflow guards) and RECONCILES every UI action against reality:

  * Confirm the referenced workflow exists (canonical match). A phantom ref is
    the trigger/button guards' job to heal — here it is merely REPORTED
    (`resolved: false`).
  * Validate/derive the `input_map`. Each form field feeding the action should
    map to one of the workflow's real INPUT columns (the union of every
    `db_insert`/`db_update` `values` key). A DECLARED input_map entry whose target
    column does not exist is DROPPED (and recorded). Any form field left unmapped
    is DERIVED by name-matching (case/separator-insensitive) to a real input
    column.
  * Set `requires_record` from the workflow's trigger + steps: an event-driven
    trigger (db_change/api_event/schedule), or a workflow that updates/deletes an
    existing row (db_update/db_delete, or a `{{id}}` reference) → the action needs
    a record context to run.

The reconciled map is written to `<output_dir>/contracts/action-contract.json`
as a durable artifact the validator/renderer can trust. Deterministic,
idempotent (a re-run over the same inputs produces byte-identical output), loudly
logged, and NEVER raises — a guard failure degrades to an empty result.

Reuses the registry readers + node-walking helpers from `binding_validator`
(Slice 1) so canonicalization never drifts.
"""
from __future__ import annotations

import json
import re
import logging
import os
import pathlib

from services.binding_validator import (
    _SlugResolver,
    _canon,
    _collect_db_writes,
    _extract_trigger_type,
    _form_field_nodes,
    _is_event_only,
    _iter_nodes_ctx,
    _node_type,
    _node_workflow_ref,
    _props,
    _read_schema_tables,
    _BUTTON_TYPES,
)

logger = logging.getLogger(__name__)


def _read_workflows_full(output_dir: str) -> dict[str, dict]:
    """canon(id|name|stem) -> {id, name, trigger, input_columns, requires_record, table}.

    Like binding_validator._read_workflows but additionally computes
    `requires_record` from the trigger type + the workflow's step actions.
    """
    wdir = os.path.join(output_dir, "workflows")
    idx: dict[str, dict] = {}
    if not os.path.isdir(wdir):
        return idx
    for fn in sorted(os.listdir(wdir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(wdir, fn), encoding="utf-8") as fh:
                wf = json.load(fh)
        except Exception:  # noqa: BLE001 — a bad file must not break the guard
            continue
        if not isinstance(wf, dict):
            continue
        cols, table = _collect_db_writes(wf)
        trigger = _extract_trigger_type(wf)
        where_vars, tables = _collect_where_vars(wf)
        rec = {
            "id": wf.get("id") or wf.get("name") or fn[:-5],
            "name": wf.get("name") or wf.get("id") or fn[:-5],
            "trigger": trigger,
            "input_columns": cols,
            "requires_record": _is_event_only(trigger) or _workflow_touches_record(wf),
            "table": table,
            "where_vars": where_vars,
            "tables": tables,
        }
        for key in (wf.get("id"), wf.get("name"), fn[:-5]):
            if key and isinstance(key, str):
                idx.setdefault(_canon(key), rec)
    return idx


_WHERE_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}")


def _collect_where_vars(wf: dict) -> tuple[set[str], set[str]]:
    """(vars bound in any node's `where` clause, tables the wf touches)."""
    where_vars: set[str] = set()
    tables: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            cfg = obj.get("config") if isinstance(obj.get("config"), dict) else obj
            if isinstance(cfg.get("table"), str):
                tables.add(cfg["table"])
            where = cfg.get("where")
            if isinstance(where, dict):
                for v in where.values():
                    if isinstance(v, str):
                        m = _WHERE_BINDING_RE.fullmatch(v.strip())
                        if m:
                            where_vars.add(m.group(1))
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(wf)
    return where_vars, tables


def _fold_name(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _is_record_id_var(var: str, entity: str, tables: set[str]) -> bool:
    """True when ``var`` names THE record's id (vs an actor/relation FK).

    ``id`` / ``recordId`` always; ``<stem>Id`` when the stem matches the
    page entity or any workflow table (singular or plural). ``documentId``
    on a Document page ⇒ True; ``uploadedById`` ⇒ False.
    """
    f = _fold_name(var)
    if f in ("id", "recordid"):
        return True
    if not f.endswith("id"):
        return False
    stem = f[:-2]
    stems = {_fold_name(entity)}
    if entity.endswith("s"):
        stems.add(_fold_name(entity[:-1]))
    for t in tables:
        stems.add(_fold_name(t))
        if t.endswith("s"):
            stems.add(_fold_name(t[:-1]))
    stems.discard("")
    return stem in stems


def backfill_record_button_args(output_dir: str) -> dict:
    """Complete bare workflow-launcher buttons with the record id they need.

    The planner declares a workflow's NEED (``where: {id: "{{documentId}}"}``)
    but the button node is authored by writers that never read it — so a
    detail-page "Reprocess" button ships with no ``args`` and the engine
    throws "WHERE id is empty" on click. This pass closes the loop
    deterministically: for every page with a ``get``-op dataSource, each
    Button dispatching a workflow gets ``args[var] = "{{<source>.id}}"``
    for every record-id-shaped var the workflow's where-clauses bind.
    Existing args are never overwritten. Idempotent; never raises.
    """
    report: dict = {"patched": [], "summary": {"buttons_patched": 0}}
    try:
        workflows = _read_workflows_full(output_dir)
        sdir = os.path.join(output_dir, "src", "schemas")
        if not os.path.isdir(sdir) or not workflows:
            return report
        import glob
        for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
            try:
                with open(fp, encoding="utf-8") as fh:
                    page = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(page, dict):
                continue
            srcs = page.get("dataSources")
            get_src = next(
                (s for s in (srcs or []) if isinstance(s, dict)
                 and s.get("op") == "get" and isinstance(s.get("name"), str)),
                None,
            )
            if get_src is None:
                continue
            src_name = get_src["name"]
            entity = get_src.get("entity") if isinstance(get_src.get("entity"), str) else ""

            dirty = {"v": False}

            def patch(node):
                if isinstance(node, dict):
                    if _node_type(node) in _BUTTON_TYPES:
                        wf_ref = _node_workflow_ref(node)
                        wf = workflows.get(_canon(wf_ref)) if wf_ref else None
                        if wf:
                            for var in sorted(wf.get("where_vars") or ()):
                                if not _is_record_id_var(var, entity, wf.get("tables") or set()):
                                    continue
                                props = node.setdefault("props", {})
                                args = props.get("args")
                                if not isinstance(args, dict):
                                    args = {}
                                    props["args"] = args
                                if var not in args:
                                    args[var] = f"{{{{{src_name}.id}}}}"
                                    dirty["v"] = True
                                    report["summary"]["buttons_patched"] += 1
                                    report["patched"].append({
                                        "file": pathlib.PurePath(
                                            os.path.relpath(fp, sdir)).as_posix(),
                                        "label": _action_label(node),
                                        "workflow": wf_ref,
                                        "arg": var,
                                    })
                    for v in node.values():
                        patch(v)
                elif isinstance(node, list):
                    for v in node:
                        patch(v)

            patch(page.get("root"))
            if dirty["v"]:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(page, fh, indent=2)
                    fh.write("\n")
    except Exception:  # noqa: BLE001 — the backfill must never crash the pipeline
        logger.exception("backfill_record_button_args: internal error (degrading to no-op)")
    return report


def _workflow_touches_record(wf: dict) -> bool:
    """True when the workflow operates on an EXISTING row (needs a record).

    A workflow that updates/deletes a row, or references `{{id}}` anywhere, can
    only run with a record in hand. A pure create (db_insert only, manual
    trigger) does not.
    """
    hit = {"v": False}

    def walk(obj):
        if hit["v"]:
            return
        if isinstance(obj, dict):
            cfg = obj.get("config") if isinstance(obj.get("config"), dict) else obj
            atype = str(cfg.get("actionType", "")).strip().lower()
            if atype in ("db_update", "db_delete"):
                hit["v"] = True
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(wf)
    if hit["v"]:
        return True
    # A literal `{{id}}` binding anywhere means the action is scoped to a record.
    try:
        return "{{id}}" in json.dumps(wf)
    except (TypeError, ValueError):
        return False


def _declared_input_map(node: dict) -> dict:
    """Any input_map the page node already carries (node-level / props / action).

    Forward-compatible with a page agent (Slice 2) that emits the planner's
    input_map onto the Form/Button node. Tolerates `input_map` / `inputMap`.
    """
    for holder in (node, node.get("props"), node.get("action"), node.get("onClick")):
        if not isinstance(holder, dict):
            continue
        for key in ("input_map", "inputMap"):
            m = holder.get(key)
            if isinstance(m, dict) and m:
                return {str(k): str(v) for k, v in m.items()
                        if isinstance(k, str) and isinstance(v, (str, int, float))}
    return {}


def _reconcile_input_map(
    declared: dict, form_fields: list[str], input_columns: set[str]
) -> tuple[dict, list, list]:
    """Return (input_map, dropped, unmapped_fields).

    * A declared entry whose target column IS a real input column is KEPT
      (canonicalized to the real column casing); one that is NOT is DROPPED.
    * Every remaining form field is DERIVED to the real input column whose name
      matches (case/separator-insensitive), when unambiguous and not already used.
    * `unmapped_fields` are form fields with no matching input column (advisory).
    """
    col_by_canon: dict[str, str] = {}
    for c in sorted(input_columns):  # sorted → deterministic on canon collisions
        col_by_canon.setdefault(_canon(c), c)

    result: dict[str, str] = {}
    dropped: list = []
    used_cols: set[str] = set()

    for fld, col in (declared or {}).items():
        real = col if col in input_columns else col_by_canon.get(_canon(col))
        if real:
            result[fld] = real
            used_cols.add(real)
        else:
            dropped.append({"field": fld, "column": col})

    unmapped: list = []
    for fname in form_fields:
        if fname in result:
            continue
        real = fname if fname in input_columns else col_by_canon.get(_canon(fname))
        if real and real not in used_cols:
            result[fname] = real
            used_cols.add(real)
        elif real is None:
            unmapped.append(fname)

    # Deterministic key order.
    return {k: result[k] for k in sorted(result)}, dropped, unmapped


def _action_label(node: dict) -> str:
    """Best-effort human label for the action (submit label / button text)."""
    p = _props(node)
    for key in ("submitLabel", "label", "text", "title", "content"):
        v = p.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = node.get("label")
    return v.strip() if isinstance(v, str) and v.strip() else ""


def reconcile_action_contract(output_dir: str) -> dict:
    """Reconcile every page action (button/form → workflow) against reality.

    Writes `<output_dir>/contracts/action-contract.json` and returns
    {"actions": [...], "files_scanned": int, "resolved": int, "unresolved": int,
    "dropped_inputs": int}. Idempotent, never raises.
    """
    result = {"actions": [], "files_scanned": 0, "resolved": 0,
              "unresolved": 0, "dropped_inputs": 0}
    try:
        tables = _read_schema_tables(output_dir)
        resolver = _SlugResolver(tables)  # noqa: F841 — reserved for future column typing
        workflows = _read_workflows_full(output_dir)

        sdir = os.path.join(output_dir, "src", "schemas")
        actions: list[dict] = []
        if os.path.isdir(sdir):
            import glob
            for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
                if os.path.basename(fp) in ("nav-flow.json",):
                    continue
                # POSIX separators: this becomes the `file` key of
                # contracts/action-contract.json, which `app_map.py:302`
                # looks up as a dict key against a `.as_posix()`-derived
                # path. `os.path.relpath` returns OS separators, so on
                # Windows the lookup missed for every nested page and the
                # app map reported no form dispatching a workflow.
                rel = pathlib.PurePath(os.path.relpath(fp, sdir)).as_posix()
                try:
                    with open(fp, encoding="utf-8") as fh:
                        page = json.load(fh)
                except (OSError, ValueError) as e:
                    logger.warning("action_contract_guard: could not parse %s: %s", rel, e)
                    continue
                if not isinstance(page, dict):
                    continue
                actions.extend(_reconcile_page(rel, page, workflows))

        # Stable ordering so the artifact is byte-identical on a re-run.
        actions.sort(key=lambda a: (a["file"], a["workflow_ref"], a["kind"], a["label"]))
        result["actions"] = actions
        result["resolved"] = sum(1 for a in actions if a["resolved"])
        result["unresolved"] = sum(1 for a in actions if not a["resolved"])
        result["dropped_inputs"] = sum(len(a["dropped_inputs"]) for a in actions)
        result["files_scanned"] = len({a["file"] for a in actions})

        _write_contract(output_dir, actions)

        # Decision ledger (REL-S1) — every action's workflow pick gets a
        # row. Resolved (exact match) → high; unresolved with fuzzy
        # candidates → low (surfaces as chip so user can pick correct
        # workflow); unresolved with no candidates → low with empty
        # alternatives (still surfaces so user knows the wf ref is dead).
        _record_action_decisions(output_dir, actions, workflows)
    except Exception as e:  # noqa: BLE001 — the guard must never crash the pipeline
        logger.exception("action_contract_guard: internal error (degrading to no-op)")
        result["error"] = str(e)
    return result


def _record_action_decisions(
    output_dir: str, actions: list[dict], workflows: dict,
) -> None:
    """Write ledger rows for every reconciled action. Resolved picks ship
    silent (high band, audit only); unresolved ones surface as chips
    with fuzzy suggestions from the workflow catalog.

    Fail-open: any ledger error must not crash the guard.
    """
    try:
        from services import decision_ledger as _dl
    except Exception:  # noqa: BLE001
        return

    workflow_names = list(workflows.keys())
    for a in actions:
        wf_ref = a.get("workflow_ref")
        if not wf_ref:
            continue
        resolved = bool(a.get("resolved"))
        if resolved:
            confidence: float | str = _dl.BAND_HIGH
            alternatives: list = []
            reason = f"exact match: workflow {wf_ref!r} found"
            target = a.get("workflow_id") or wf_ref
        else:
            # Fuzzy hints — the workflow ref didn't match any known name;
            # surface the closest candidates so the user can pick or the
            # planner can heal.
            alt_candidates = _fuzzy_workflow_alternatives(wf_ref, workflow_names)
            confidence = _dl.BAND_LOW
            alternatives = [
                _dl.make_alternative(
                    target=cand_name,
                    score=score,
                    reason=f"edit-distance match to {wf_ref!r}",
                )
                for cand_name, score in alt_candidates
            ]
            reason = (
                f"workflow {wf_ref!r} not found; "
                + (f"closest: {alt_candidates[0][0]!r}" if alt_candidates
                   else "no similar workflows in catalog")
            )
            target = f"unresolved:{wf_ref}"

        # Scope: page:route + kind. Identity: the action label (button
        # text or form name). Same identity on different pages is a
        # different decision, so scope carries the file rel.
        try:
            _dl.record_pick(
                output_dir,
                kind=_dl.KIND_BUTTON_TARGET if a.get("kind") == "button"
                else _dl.KIND_FORM_SUBMIT,
                scope=f"file:{a.get('file', '')}",
                identity=str(a.get("label") or a.get("workflow_ref") or "unnamed"),
                target_picked=str(target),
                confidence=confidence,
                source_emitter="action_contract_guard",
                alternatives=alternatives,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[action-contract-guard] ledger row failed: %s", exc)


def _fuzzy_workflow_alternatives(
    ref: str, workflow_names: list[str], top_k: int = 3,
) -> list[tuple[str, float]]:
    """Return up-to-top_k (name, score) tuples for workflows whose name
    is edit-distance close to ``ref``. Scores > 0.6 only — anything
    lower is noise and would flood the chip UI with false alternatives.
    """
    from difflib import SequenceMatcher
    if not ref or not workflow_names:
        return []
    scored: list[tuple[str, float]] = []
    ref_lower = ref.lower()
    for name in workflow_names:
        ratio = SequenceMatcher(None, name.lower(), ref_lower).ratio()
        if ratio > 0.6:
            scored.append((name, round(ratio, 2)))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:top_k]


def _reconcile_page(rel: str, page: dict, workflows: dict) -> list[dict]:
    """Reconcile every workflow-backed action node on one page schema."""
    out: list[dict] = []
    root = page.get("root") if isinstance(page.get("root"), dict) else page
    record_ctx = "[" in rel
    for node, node_ctx in _iter_nodes_ctx(root, record_ctx):
        wf_ref = _node_workflow_ref(node)
        if wf_ref is None:
            continue
        ntype = _node_type(node)
        is_button = ntype in _BUTTON_TYPES
        is_form = ntype == "form"
        if not (is_button or is_form):
            continue  # only forms + buttons dispatch actions we reconcile

        wf = workflows.get(_canon(wf_ref))
        resolved = wf is not None
        kind = "form_submit" if is_form else "button"

        form_fields: list[str] = []
        if is_form:
            for fnode in _form_field_nodes(node):
                fname = _props(fnode).get("name")
                if isinstance(fname, str) and fname and fname not in form_fields:
                    form_fields.append(fname)

        input_columns = wf["input_columns"] if resolved else set()
        input_map, dropped, unmapped = _reconcile_input_map(
            _declared_input_map(node), form_fields, input_columns
        )

        # requires_record: prefer the reconciled workflow's computed value; fall
        # back to any node-declared bool (Slice 2 forward-compat) when unresolved.
        if resolved:
            requires_record = bool(wf["requires_record"])
        else:
            requires_record = _declared_requires_record(node)

        entry = {
            "file": rel,
            "kind": kind,
            "label": _action_label(node),
            "workflow_ref": wf_ref,
            "workflow_id": wf["id"] if resolved else None,
            "resolved": resolved,
            "record_context": bool(node_ctx),
            "requires_record": requires_record,
            "input_map": input_map,
            "dropped_inputs": dropped,
            "unmapped_fields": unmapped,
        }
        out.append(entry)
        if not resolved:
            logger.warning(
                "action_contract_guard: UNRESOLVED workflow ref %r on %s in %s "
                "(trigger/button guards own the heal)", wf_ref, kind, rel,
            )
        elif dropped:
            logger.warning(
                "action_contract_guard: dropped %d bogus input_map column(s) for %r in %s: %s",
                len(dropped), wf_ref, rel,
                ", ".join(f"{d['field']}->{d['column']}" for d in dropped),
            )
    return out


def _declared_requires_record(node: dict) -> bool:
    for holder in (node, node.get("props"), node.get("action"), node.get("onClick")):
        if isinstance(holder, dict) and isinstance(holder.get("requires_record"), bool):
            return holder["requires_record"]
    return False


def _write_contract(output_dir: str, actions: list[dict]) -> None:
    try:
        cdir = os.path.join(output_dir, "contracts")
        os.makedirs(cdir, exist_ok=True)
        payload = {"version": 1, "actions": actions}
        with open(os.path.join(cdir, "action-contract.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
    except OSError as e:  # noqa: BLE001
        logger.warning("action_contract_guard: could not write action-contract.json: %s", e)
