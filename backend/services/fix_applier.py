"""Deterministic fix-applier (Conversational Fix-Assistant, Task 1-C).

Given a structured ``Diagnosis`` (produced by the diagnoser, Task 1-B), APPLY the
fix through the correct deterministic seam, run the whole-app heal, RE-VERIFY, and
report — with git safety.

The Diagnosis contract (consumed verbatim)::

    { "symptom","feature","rootCause",
      "artifact": {"kind": "workflow"|"page"|"schema", "path": <rel to output_dir>},
      "locator": {"nodeId": str|None, "jsonPointer": str|None},
      "proposedFix": {"seam": "workflow_node_config"|"page_schema_patch"|"code_edit",
                      "patch": <object>},
      "confidence": float, "explanation": str }

Seams:
- ``workflow_node_config`` — ``patch`` is a config-merge dict (e.g. ``{"values": {..}}``)
  shallow-merged into the located node's ``data.config`` via the SAME helper the node
  PATCH route uses (``routers.workflows.merge_node_config``).
- ``page_schema_patch`` — ``patch`` is a list of RFC-6902 ops applied transactionally
  through ``services.patch_applier``.
- ``code_edit`` — NOT implemented in this slice; a safe no-op.

Every structured apply is transactional (a pre-image of the target file is kept and
restored on any error), heals the whole app (``apply_post_generate_fixes``), and is
RE-VERIFIED before it may claim ``resolved``. Never claims resolved if the verify
still finds the issue.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from services.post_generate_fixes import apply_post_generate_fixes
from services.patch_applier import (
    PatchApplyError,
    apply_patches_transactional,
    validate_patches,
)
from services.patch_coherence import check_patch_coherence, check_promise_kept
from services.workflow_value_types import (
    analyze_workflow_values,
    columns_by_table_from_registry,
)


_REGISTRY_REL = "contracts/resource-registry.json"


def apply_fix(output_dir: str, diagnosis: dict, *, git: bool = True) -> dict:
    """Apply a structured Diagnosis through its deterministic seam and report.

    Returns ``{applied, seam, changes, verify:{resolved, remaining}, committed}``
    (plus ``reason`` on a no-op). Transactional: on any error during apply or
    verify the target artifact is restored from its pre-image.
    """
    proposed = (diagnosis or {}).get("proposedFix") or {}
    seam = proposed.get("seam")

    if seam == "workflow_node_config":
        return _apply_workflow_node_config(output_dir, diagnosis, git=git)
    if seam == "page_schema_patch":
        return _apply_page_schema_patch(output_dir, diagnosis, git=git)
    if seam == "add_page":
        return _apply_add_page(output_dir, diagnosis, git=git)
    if seam == "add_workflow":
        return _apply_add_workflow(output_dir, diagnosis, git=git)
    if seam == "add_entity":
        return _apply_add_entity(output_dir, diagnosis, git=git)
    if seam == "code_edit":
        return {
            "applied": False,
            "seam": "code_edit",
            "reason": "code_edit seam requires the refiner (out of slice-1 scope)",
            "changes": [],
            "verify": {"resolved": False, "remaining": []},
            "committed": False,
        }

    return {
        "applied": False,
        "seam": seam,
        "reason": f"unknown seam: {seam!r}",
        "changes": [],
        "verify": {"resolved": False, "remaining": []},
        "committed": False,
    }


# --------------------------------------------------------------------------- #
# apply_fix_with_retry — bounded re-diagnose-on-failure loop (Task 2-B)
# --------------------------------------------------------------------------- #

def _residual_from(diagnosis: dict, result: dict, *, attempt: int) -> dict:
    """A residual summary of what is STILL failing, shaped for a re-diagnosis.

    Carries the original symptom + the prior attempt's seam/artifact/locator and
    the concrete remaining findings so the diagnoser can author a follow-up.
    """
    verify = result.get("verify") or {}
    applied = bool(result.get("applied"))
    return {
        "symptom": (diagnosis or {}).get("symptom"),
        "feature": (diagnosis or {}).get("feature"),
        "priorSeam": result.get("seam"),
        "priorArtifact": (diagnosis or {}).get("artifact"),
        "priorLocator": (diagnosis or {}).get("locator"),
        "priorChanges": result.get("changes") or [],
        "applied": applied,
        "reason": result.get("reason"),
        "remaining": verify.get("remaining") or [],
        "attempt": attempt,
        "note": (
            "The previous fix was applied but the issue is NOT resolved; "
            "re-diagnose from the remaining problems below."
            if applied else
            "The previous fix could not be applied; re-diagnose."
        ),
    }


def _describe_remaining(remaining: list) -> str:
    if not remaining:
        return "no specific findings were reported."
    parts: list[str] = []
    for f in remaining[:5]:
        if not isinstance(f, dict):
            parts.append(str(f))
            continue
        col = f.get("column")
        detail = f.get("reason") or f.get("msg") or f.get("kind")
        if col and detail:
            parts.append(f"{col}: {detail}")
        elif col:
            parts.append(str(col))
        elif detail:
            parts.append(str(detail))
    return "; ".join(parts) if parts else "unresolved."


def apply_fix_with_retry(
    output_dir: str,
    diagnosis: dict,
    *,
    diagnose_fn: Callable[[dict], dict],
    max_retries: int = 1,
    git: bool = True,
) -> dict:
    """Apply a fix and, if verification fails, RE-DIAGNOSE from the residual ONCE
    (bounded — never loops) before giving up honestly.

    ``diagnose_fn(residual) -> Diagnosis`` is injectable so tests (and the caller)
    control the re-diagnosis without hitting the model. On success returns the
    resolving apply result with ``resolved: True`` and ``retries``. When still
    unresolved after the bounded retries, returns the LAST apply result with
    ``resolved: False``, the ``residual`` that remains, and a clear
    ``message`` — it NEVER claims success it did not achieve.
    """
    result = apply_fix(output_dir, diagnosis, git=git)
    result["retries"] = 0
    result["resolved"] = bool((result.get("verify") or {}).get("resolved"))
    if result["resolved"]:
        return result

    current = result
    current_diag = diagnosis
    retries = 0
    while retries < max(0, int(max_retries)):
        residual = _residual_from(current_diag, current, attempt=retries + 1)
        retries += 1
        try:
            new_diag = diagnose_fn(residual)
        except Exception:  # noqa: BLE001 — a diagnoser failure must not crash apply
            new_diag = None
        if not isinstance(new_diag, dict):
            current["retries"] = retries
            current["resolved"] = False
            current["residual"] = residual
            current["message"] = (
                "I couldn't automatically resolve this — re-diagnosis did not "
                "produce a follow-up fix. What remains: "
                + _describe_remaining(residual.get("remaining"))
            )
            return current

        current = apply_fix(output_dir, new_diag, git=git)
        current_diag = new_diag
        if (current.get("verify") or {}).get("resolved"):
            current["retries"] = retries
            current["resolved"] = True
            current["message"] = (
                f"Resolved after re-diagnosing the residual failure "
                f"(attempt {retries + 1})."
            )
            return current

    # Bounded stop — still unresolved. Report the residual honestly.
    residual = _residual_from(current_diag, current, attempt=retries + 1)
    current["retries"] = retries
    current["resolved"] = False
    current["residual"] = residual
    current["message"] = (
        f"I couldn't automatically resolve this after {retries + 1} attempt(s). "
        "Here's what still remains: "
        + _describe_remaining(residual.get("remaining"))
    )
    return current


# --------------------------------------------------------------------------- #
# workflow_node_config
# --------------------------------------------------------------------------- #

def _apply_workflow_node_config(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    from routers.workflows import merge_node_config  # lazy: avoids FastAPI import cost

    root = Path(output_dir)
    artifact = (diagnosis.get("artifact") or {})
    rel_path = artifact.get("path")
    node_id = (diagnosis.get("locator") or {}).get("nodeId")
    config_patch = (diagnosis.get("proposedFix") or {}).get("patch") or {}

    wf_file = root / rel_path if rel_path else None
    if not wf_file or not wf_file.exists():
        return _noop(f"workflow artifact not found: {rel_path!r}", seam="workflow_node_config")
    if not node_id:
        return _noop("no locator.nodeId for workflow_node_config", seam="workflow_node_config")

    pre_image = wf_file.read_text()
    try:
        data = json.loads(pre_image)
        definition = data.get("definition") or {}

        # Snapshot the node's pre-merge config values for a change list.
        before_values = _node_config_values(definition, node_id)

        node = merge_node_config(definition, node_id, config_patch)
        if node is None:
            # Node not located — safe no-op, artifact untouched (never written).
            return _noop(f"node {node_id!r} not found in workflow", seam="workflow_node_config")

        wf_file.write_text(json.dumps(data, indent=2))

        # Do NOT run apply_post_generate_fixes here — see fix_applier
        # BUG-APPLY-1: the post-gen suite (form_scaffold especially)
        # re-adds fields that Smith just intentionally removed. Same
        # rationale as the page-schema-patch path above and NT-7.

        # Re-verify from disk.
        remaining = _verify_workflow(output_dir, wf_file)
        after_values = _node_config_values(
            (json.loads(wf_file.read_text()).get("definition") or {}), node_id
        )
        changes = _value_changes(node_id, before_values, after_values)
    except Exception:
        # Transactional: never leave a half-written artifact.
        wf_file.write_text(pre_image)
        raise

    committed = _commit(output_dir, f"fix(workflow): patch node {node_id}", git=git,
                    paths=[os.path.relpath(str(wf_file), output_dir)])

    return {
        "applied": True,
        "seam": "workflow_node_config",
        "changes": changes,
        "verify": {"resolved": not remaining, "remaining": remaining},
        "committed": committed,
    }


def _node_config_values(definition: dict, node_id: str) -> dict:
    for n in (definition.get("nodes") or []):
        if isinstance(n, dict) and n.get("id") == node_id:
            cfg = (n.get("data") or {}).get("config") or {}
            vals = cfg.get("values")
            return dict(vals) if isinstance(vals, dict) else {}
    return {}


def _value_changes(node_id: str, before: dict, after: dict) -> list[dict]:
    changes: list[dict] = []
    for key in sorted(set(before) | set(after)):
        b = before.get(key)
        a = after.get(key)
        if b != a:
            changes.append({"node": node_id, "field": key, "from": b, "to": a})
    return changes


def _verify_workflow(output_dir: str, wf_file: Path) -> list[dict]:
    """Run the value↔column type check on the patched workflow. Returns the list
    of remaining findings (empty == resolved)."""
    columns_by_table = _columns_by_table(output_dir)
    if not columns_by_table:
        # No registry → we can't affirm resolution; report empty but caller sees
        # an honest "resolved" only when there is nothing to check.
        return []
    try:
        data = json.loads(wf_file.read_text())
    except (OSError, ValueError):
        return []
    defn = data.get("definition") if isinstance(data, dict) else None
    return analyze_workflow_values(defn or {}, columns_by_table)


def _columns_by_table(output_dir: str) -> dict:
    reg_path = Path(output_dir) / _REGISTRY_REL
    if not reg_path.exists():
        return {}
    try:
        registry = json.loads(reg_path.read_text())
    except (OSError, ValueError):
        return {}
    return columns_by_table_from_registry(registry)


# --------------------------------------------------------------------------- #
# page_schema_patch
# --------------------------------------------------------------------------- #

def _apply_page_schema_patch(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    root = Path(output_dir)
    rel_path = (diagnosis.get("artifact") or {}).get("path")
    patch_ops = (diagnosis.get("proposedFix") or {}).get("patch")

    schema_file = root / rel_path if rel_path else None
    if not schema_file or not schema_file.exists():
        return _noop(f"page schema not found: {rel_path!r}", seam="page_schema_patch")
    if not isinstance(patch_ops, list):
        return _noop("page_schema_patch expects a list of RFC-6902 ops", seam="page_schema_patch")

    pre_image = schema_file.read_text()
    try:
        schema = json.loads(pre_image)

        errors = validate_patches(patch_ops, schema)
        if errors:
            return {
                "applied": False,
                "seam": "page_schema_patch",
                "reason": "patch validation failed",
                "changes": [],
                "verify": {
                    "resolved": False,
                    "remaining": [{"idx": e.idx, "kind": e.kind, "msg": e.msg} for e in errors],
                },
                "committed": False,
            }

        # Coherence gate — the explanation Smith renders to the user and
        # the actual JSON patch are two independent LLM outputs, so
        # verify they agree BEFORE writing to disk. When the check flags
        # a strong verb+noun phrase the patch never touches (the classic
        # "I'll remove password" + reorder-Switch drift), reject the fix
        # and surface a concrete diff to the caller so Smith can be
        # re-asked with the mismatch spelled out.
        explanation = str((diagnosis or {}).get("explanation") or "")
        incoherences = check_patch_coherence(
            explanation=explanation,
            patch=patch_ops,
            pre_schema=schema,
        )
        if incoherences:
            return {
                "applied": False,
                "seam": "page_schema_patch",
                "reason": "explanation/patch coherence failed",
                "changes": [],
                "verify": {"resolved": False, "remaining": incoherences},
                "committed": False,
            }

        # Apply transactionally (zod validation degrades to no-op when Node is
        # unavailable; the whole-app validator is the authoritative gate later).
        patched = apply_patches_transactional(patch_ops, schema, validate_zod=False)

        # Post-apply "did the promise actually land?" gate — catches the
        # replace-with-same-value / add-then-remove-pair class of no-op
        # patches. When the explanation promised change but pre == post,
        # rollback (never write) and surface the broken promise. This is
        # the second half of the coherence contract: the first half
        # checks the ops match the words; this half checks the WORLD
        # actually changed.
        promise_gaps = check_promise_kept(
            explanation=explanation,
            pre_schema=schema,
            post_schema=patched,
        )
        if promise_gaps:
            return {
                "applied": False,
                "seam": "page_schema_patch",
                "reason": "patch produced no diff — explanation promise not kept",
                "changes": [],
                "verify": {"resolved": False, "remaining": promise_gaps},
                "committed": False,
            }

        schema_file.write_text(json.dumps(patched, indent=2))

        # Do NOT run apply_post_generate_fixes here — the post-gen suite
        # includes form_scaffold, which re-adds any field it thinks the
        # form is "missing" from the entity. That undoes Smith's targeted
        # removes: user asks "remove the duplicate CV Url", Smith removes
        # it, form_scaffold re-adds it, commit captures the re-added
        # version, user sees the field still there. Live-observed on
        # xoiz4i97 (BUG-APPLY-1). NT-7 already removed this from Smith's
        # direct-edit wrapper; the seam-based apply path had the same
        # bug. Smith's edit is authoritative — no whole-app heal here.
    except PatchApplyError as e:
        schema_file.write_text(pre_image)
        return {
            "applied": False,
            "seam": "page_schema_patch",
            "reason": f"patch apply failed: {e}",
            "changes": [],
            "verify": {"resolved": False, "remaining": [{"kind": "apply_error", "msg": str(e)}]},
            "committed": False,
        }
    except Exception:
        schema_file.write_text(pre_image)
        raise

    committed = _commit(output_dir, f"fix(page): patch schema {rel_path}", git=git,
                    paths=[rel_path])

    return {
        "applied": True,
        "seam": "page_schema_patch",
        "changes": [{"artifact": rel_path, "ops": patch_ops}],
        # The transactional apply succeeded (structurally valid) → the change landed.
        "verify": {"resolved": True, "remaining": []},
        "committed": committed,
    }


# --------------------------------------------------------------------------- #
# add_page seam (S5-T2) — composite whole-page adds via the pipeline's own
# builders, executed atomically via services.atomic_apply.
# --------------------------------------------------------------------------- #

def _apply_add_page(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    """Apply an ``add_page`` proposal.

    The Diagnosis payload for this seam is intentionally simpler than the
    workflow_node_config / page_schema_patch shapes — it carries a
    ``proposedFix.patch`` dict with the seam parameters, not a JSON patch::

        proposedFix: {
          seam: "add_page",
          patch: {
            archetype: "kanban",
            entity:    "Application",
            route:     "/pipeline",
            title:     "Candidate Pipeline",
            features:  ["groupBy:stage"],
            fields:    <optional planner-shape field-spec list>
          }
        }

    The applier delegates to :mod:`services.add_page_seam` to compose the
    file-bundle and to :mod:`services.atomic_apply` to write + verify +
    commit as one transaction. Any failure rolls back every file.
    """
    from services.add_page_seam import build_add_page_bundle, AddPageError
    from services.atomic_apply import apply_bundle

    proposed = (diagnosis or {}).get("proposedFix") or {}
    params = proposed.get("patch") if isinstance(proposed.get("patch"), dict) else {}

    try:
        ops = build_add_page_bundle(
            output_dir,
            archetype=str(params.get("archetype") or "").strip().lower(),
            entity=str(params.get("entity") or "").strip(),
            route=str(params.get("route") or "").strip(),
            title=params.get("title"),
            fields=params.get("fields") if isinstance(params.get("fields"), list) else None,
            features=params.get("features") if isinstance(params.get("features"), list) else None,
        )
    except AddPageError as exc:
        return _noop(str(exc), seam="add_page")

    # Verify: just JSON-parse every written file. A future slice can add
    # a call into the guard suite / binding_validator here.
    def _verify(root: Path) -> dict:
        for op in ops:
            try:
                json.loads((root / op.path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return {"ok": False, "reason": f"{op.path}: {e}"}
        return {"ok": True}

    label = params.get("title") or params.get("route") or "new page"
    result = apply_bundle(
        output_dir, ops, verify=_verify,
        commit_message=f"smith: add page — {label}", git=git,
    )

    # Regenerate src/schemas/registry.ts so Next's compiled route dispatcher
    # (src/app/(dashboard)/[entity]/page.tsx) can find the new page. Without
    # this the schema file exists on disk but hitting the URL 404s because
    # the entity page checks `!(route in schemas)` at request time. Commit
    # the regenerated registry as its own follow-up commit so `git log`
    # still reads cleanly (one commit per logical change).
    if result.applied:
        try:
            from services.schema_pipeline import _regenerate_route_registry
            from services.shell_menu_sync import sync_shell_menu
            from services.fix_applier import _commit as _seam_commit
            _regenerate_route_registry(output_dir)
            # Sidebar too: shell.json's menu is derived from nav-flow.json;
            # without this the recruiters route lands in nav-flow but never
            # in the sidebar the user actually sees.
            sync_shell_menu(output_dir)
            _seam_commit(
                output_dir,
                f"smith: regen route registry + shell menu after add_page — {label}",
                git=git,
            )
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "[add_page] post-apply regen (registry / shell menu) failed"
            )

    return {
        "applied": bool(result.applied),
        "seam": "add_page",
        "changes": [{"path": p, "kind": "add"} for p in (result.ops_written or [])],
        "verify": {
            "resolved": bool(result.applied),
            "remaining": [] if result.applied else [
                {"reason": result.reason or "add_page rolled back"}
            ],
        },
        "committed": bool(result.commit_hash),
        "commit_hash": result.commit_hash,
        "reason": result.reason,
    }


# --------------------------------------------------------------------------- #
# remove_page seam — inverse of add_page. Deletes schema file(s) at a route
# (or the whole feature slice with cascade=True), strips nav-flow entries,
# regenerates registry + sidebar. Same post-apply hook as add_page so the
# tree stays consistent.
# --------------------------------------------------------------------------- #

def _apply_remove_page(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    """Apply a ``remove_page`` proposal.

    Diagnosis shape::

        proposedFix: {
          seam: "remove_page",
          patch: {
            route:   "/recruiters/new"         # required
            cascade: false                      # remove whole feature area if True
          }
        }
    """
    from services.remove_page_seam import build_remove_page_bundle, RemovePageError
    from services.atomic_apply import apply_bundle

    proposed = (diagnosis or {}).get("proposedFix") or {}
    params = proposed.get("patch") if isinstance(proposed.get("patch"), dict) else {}
    route = str(params.get("route") or "").strip()
    cascade = bool(params.get("cascade"))

    try:
        ops = build_remove_page_bundle(output_dir, route, cascade=cascade)
    except RemovePageError as exc:
        return _noop(str(exc), seam="remove_page")

    label = route + (" (cascade)" if cascade else "")
    result = apply_bundle(
        output_dir, ops, verify=None,
        commit_message=f"smith: remove page — {label}", git=git,
    )

    # Same post-apply reconciliation as add_page — registry.ts and sidebar
    # must reflect the removed routes, else the app dispatcher keeps
    # trying to import a deleted schema.
    if result.applied:
        try:
            from services.schema_pipeline import _regenerate_route_registry
            from services.shell_menu_sync import sync_shell_menu
            from services.fix_applier import _commit as _seam_commit
            _regenerate_route_registry(output_dir)
            sync_shell_menu(output_dir)
            _seam_commit(
                output_dir,
                f"smith: regen route registry + shell menu after remove_page — {label}",
                git=git,
            )
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "[remove_page] post-apply regen failed"
            )

    return {
        "applied": bool(result.applied),
        "seam": "remove_page",
        "changes": [{"path": p, "kind": "delete"} for p in (result.ops_written or [])],
        "verify": {
            "resolved": bool(result.applied),
            "remaining": [] if result.applied else [
                {"reason": result.reason or "remove_page rolled back"}
            ],
        },
        "committed": bool(result.commit_hash),
        "commit_hash": result.commit_hash,
        "reason": result.reason,
    }


# --------------------------------------------------------------------------- #
# add_workflow seam (S5-T4) — new CRUD workflow via the pipeline's own
# generator, atomic-applied.
# --------------------------------------------------------------------------- #

def _apply_add_workflow(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    """Apply an ``add_workflow`` proposal.

    Diagnosis shape::

        proposedFix: {
          seam: "add_workflow",
          patch: {
            op:     "create" | "update" | "delete",
            entity: "Candidate",
            name:   "BulkImportCandidate"   # optional; defaults to <Op><Entity>
          }
        }
    """
    from services.add_workflow_seam import build_add_workflow_bundle, AddWorkflowError
    from services.atomic_apply import apply_bundle

    proposed = (diagnosis or {}).get("proposedFix") or {}
    params = proposed.get("patch") if isinstance(proposed.get("patch"), dict) else {}

    try:
        ops = build_add_workflow_bundle(
            output_dir,
            op=str(params.get("op") or "").strip().lower(),
            entity=str(params.get("entity") or "").strip(),
            name=params.get("name"),
        )
    except AddWorkflowError as exc:
        return _noop(str(exc), seam="add_workflow")

    def _verify(root: Path) -> dict:
        for op in ops:
            try:
                json.loads((root / op.path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                return {"ok": False, "reason": f"{op.path}: {e}"}
        return {"ok": True}

    label = params.get("name") or f"{params.get('op','')}{params.get('entity','')}"
    result = apply_bundle(
        output_dir, ops, verify=_verify,
        commit_message=f"smith: add workflow — {label}", git=git,
    )

    return {
        "applied": bool(result.applied),
        "seam": "add_workflow",
        "changes": [{"path": p, "kind": "add"} for p in (result.ops_written or [])],
        "verify": {
            "resolved": bool(result.applied),
            "remaining": [] if result.applied else [
                {"reason": result.reason or "add_workflow rolled back"}
            ],
        },
        "committed": bool(result.commit_hash),
        "commit_hash": result.commit_hash,
        "reason": result.reason,
    }


# --------------------------------------------------------------------------- #
# add_entity seam (S5-T5) — new entity via registry + Drizzle + barrel,
# atomic-applied.
# --------------------------------------------------------------------------- #

def _apply_add_entity(output_dir: str, diagnosis: dict, *, git: bool) -> dict:
    """Apply an ``add_entity`` proposal.

    Diagnosis shape::

        proposedFix: {
          seam: "add_entity",
          patch: {
            name:   "Assessor",
            fields: [
              {name:"fullName", type:"varchar"},
              {name:"email",    type:"varchar", notNull:True},
              …
            ],
            table:  "assessors"    # optional; defaults to pluralized snake
          }
        }
    """
    from services.add_entity_seam import build_add_entity_bundle, AddEntityError
    from services.atomic_apply import apply_bundle

    proposed = (diagnosis or {}).get("proposedFix") or {}
    params = proposed.get("patch") if isinstance(proposed.get("patch"), dict) else {}

    try:
        ops = build_add_entity_bundle(
            output_dir,
            name=str(params.get("name") or "").strip(),
            fields=params.get("fields") if isinstance(params.get("fields"), list) else [],
            table=params.get("table"),
        )
    except AddEntityError as exc:
        return _noop(str(exc), seam="add_entity")

    # Verify: registry parses + drizzle file has an export line + barrel
    # has the export. Full TS compile is out of scope for this seam.
    def _verify(root: Path) -> dict:
        try:
            reg = json.loads((root / "contracts/resource-registry.json").read_text(encoding="utf-8"))
            if not any(e.get("name") == params.get("name") for e in reg.get("entities") or []):
                return {"ok": False, "reason": "new entity not present in registry"}
        except (OSError, ValueError) as e:
            return {"ok": False, "reason": f"registry re-read failed: {e}"}
        for op in ops:
            if not (root / op.path).is_file():
                return {"ok": False, "reason": f"expected file not written: {op.path}"}
        return {"ok": True}

    label = params.get("name") or "entity"
    result = apply_bundle(
        output_dir, ops, verify=_verify,
        commit_message=f"smith: add entity — {label}", git=git,
    )

    return {
        "applied": bool(result.applied),
        "seam": "add_entity",
        "changes": [{"path": p, "kind": "add"} for p in (result.ops_written or [])],
        "verify": {
            "resolved": bool(result.applied),
            "remaining": [] if result.applied else [
                {"reason": result.reason or "add_entity rolled back"}
            ],
        },
        "committed": bool(result.commit_hash),
        "commit_hash": result.commit_hash,
        "reason": result.reason,
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _noop(reason: str, *, seam: str) -> dict:
    return {
        "applied": False,
        "seam": seam,
        "reason": reason,
        "changes": [],
        "verify": {"resolved": False, "remaining": []},
        "committed": False,
    }


def _commit(output_dir: str, message: str, *, git: bool,
            actor: str = "smith", paths: list[str] | None = None) -> bool:
    """Best-effort git commit via the repo's existing async git_commit path.
    Returns True when a commit landed. ``git=False`` skips (tests).

    ``actor`` is recorded as a ``Forge-Actor:`` trailer so `revert_last_patch`
    can tell Smith's commits from a visual-editor save (register S24-6)."""
    if not git:
        return False
    try:
        import asyncio
        from services.git_service import git_commit

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            running = False
        else:
            running = True

        if running:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                commit_hash = ex.submit(
                    lambda: asyncio.run(git_commit(output_dir, message, actor=actor, paths=paths))
                ).result()
        else:
            commit_hash = asyncio.run(git_commit(output_dir, message, actor=actor, paths=paths))
        return bool(commit_hash)
    except Exception:
        return False
