"""plan_and_apply — one-shot multi-step feature builder for Smith.

Layman asks "add candidate messaging" and gets ONE clean flow: Smith
proposes a 3–5 step plan (add_entity → add_page (list) → add_page
(create) → add_workflow → wire_form_to_workflow), executes each step
in order, streams progress, and returns a single result Smith can
report. No LLM tool-thrashing across 5 turns; no "which page?"
enumerations; no half-applied features.

This module owns the PLANNING (LLM call) + EXECUTION (deterministic
seam dispatch). The Smith agent invokes it as a single tool.

Design shape:

  1. ``plan_feature_ask(ask, output_dir)`` — asks a small LLM to
     translate the natural-language ask into an ordered list of steps.
     Each step names an existing seam and its arguments.

  2. ``apply_plan(steps, output_dir)`` — walks the plan, calls each
     seam's actual handler, collects the results, and returns a
     structured summary the caller can pass back into the loop.

  3. ``plan_and_apply(ask, output_dir, ...)`` — glue that composes 1
     and 2. Bails safely on any step failure (returns partial results
     + the step that broke, so Smith can either retry or ask the user).

The catalog of steps is intentionally tight — only the composable
seams that already exist. Adding new step kinds is a one-line change
in ``_STEP_DISPATCH``.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Step catalog                                                                 #
# --------------------------------------------------------------------------- #
# Each supported step names an EXISTING deterministic seam. The dispatcher
# maps the plan's ``kind`` to the seam's callable. Keeping this list SHORT
# is a feature: if the LLM emits a kind we don't handle, we reject the plan
# outright rather than executing a half-mapped step.

_SUPPORTED_STEP_KINDS = frozenset({
    "add_entity",
    "add_page",
    "add_workflow",
    "wire_form_to_workflow",
    "edit_page",
})


class PlanValidationError(ValueError):
    """The LLM's plan doesn't match the schema we ask for. Raised by
    ``validate_plan`` and caught by ``plan_and_apply``."""


def validate_plan(plan: Any) -> list[dict]:
    """Coerce + validate a plan into a list of steps.

    Rules:
      • ``plan`` must be a list of dicts.
      • Each step must have ``kind`` in :data:`_SUPPORTED_STEP_KINDS`.
      • Each step must have ``args`` (dict) — the shape the seam expects.
      • Total step count is capped at 8 to prevent LLM runaway.

    Returns the normalized list.
    """
    if not isinstance(plan, list):
        raise PlanValidationError("plan must be a JSON array")
    if not plan:
        raise PlanValidationError("plan is empty — no steps to apply")
    if len(plan) > 8:
        raise PlanValidationError(
            f"plan has {len(plan)} steps — too many (max 8). Split the "
            "ask into a smaller feature."
        )
    out: list[dict] = []
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            raise PlanValidationError(f"step {i}: expected object, got {type(step).__name__}")
        kind = step.get("kind")
        if kind not in _SUPPORTED_STEP_KINDS:
            raise PlanValidationError(
                f"step {i}: unsupported kind {kind!r}. "
                f"Allowed: {sorted(_SUPPORTED_STEP_KINDS)}"
            )
        args = step.get("args")
        if not isinstance(args, dict):
            raise PlanValidationError(f"step {i}: 'args' must be an object")
        # Passthrough — the seam validates its own arg shape.
        out.append({"kind": kind, "args": args, "label": step.get("label")})
    return out


# --------------------------------------------------------------------------- #
# LLM planning                                                                 #
# --------------------------------------------------------------------------- #

_PLANNING_SYSTEM_PROMPT = (
    "You are a build planner for Tentoro Forge. The user described a "
    "feature to add to a generated app. Your job is to translate their "
    "ask into an ORDERED list of concrete build steps, each naming an "
    "existing deterministic seam.\n\n"
    "Output JSON ONLY — a top-level array. No markdown, no prose, no "
    "explanations.\n\n"
    "Available step kinds (do NOT invent others):\n"
    "  • add_entity      — args: {name, fields[]}. Fields are\n"
    "                       {name, type, notNull?}.\n"
    "  • add_page        — args: {archetype, entity, route}. archetype\n"
    "                       ∈ list|detail|create|edit|dashboard|calendar|kanban.\n"
    "  • add_workflow    — args: {op, entity, name?}. op ∈ create|update|delete.\n"
    "  • wire_form_to_workflow — args: {page_route, workflow_name, field_map?}.\n"
    "  • edit_page       — args: {target_path, intent}. Use SPARINGLY —\n"
    "                       only for a specific tweak to an EXISTING page.\n\n"
    "Rules:\n"
    "  • Order matters: entities MUST come before pages that use them;\n"
    "    workflows MUST come before wire_form_to_workflow.\n"
    "  • Total steps ≤ 8. If the ask is bigger, pick the minimum that\n"
    "    delivers the feature end-to-end.\n"
    "  • Each step SHOULD have a ``label`` (one short line) that we\n"
    "    stream back to the user as progress: {\"label\": \"Add Message entity\"}.\n"
    "  • If the ask is really just ONE existing seam (e.g. 'add a\n"
    "    /pipeline dashboard'), emit a single step. Don't over-plan.\n"
)


def _build_planning_user_prompt(ask: str, output_dir: str) -> str:
    """Bundle the ask + a compact app context. The planner LLM needs to
    know which entities/pages already exist so it doesn't propose
    duplicates."""
    parts = [f"## ASK\n{ask}\n"]
    # Try to include a compact app-map so the planner sees the entity
    # landscape. Best-effort — a missing map still yields a usable plan.
    try:
        from services.app_map import build_app_map, render_app_map_skeleton
        m = build_app_map(output_dir)
        skel = render_app_map_skeleton(m)
        if skel:
            parts.append("## APP CONTEXT\n" + skel + "\n")
    except Exception:  # noqa: BLE001
        pass
    parts.append(
        "## OUTPUT\nEmit a JSON array of steps as described in the system "
        "prompt. Nothing else."
    )
    return "\n".join(parts)


PlanQueryFn = Callable[[str, str], str]
"""Boundary shape for the planning LLM call. system_prompt + user_prompt
→ raw text (JSON array)."""


def _default_plan_query(system_prompt: str, user_prompt: str) -> str:  # pragma: no cover
    """Real LLM boundary — same shape the fix agent uses. Kept import-
    guarded so unit tests don't need the SDK installed."""
    from agents.fix_chat_agent import _default_query as _fix_default
    return _fix_default(system_prompt, [{"role": "user", "content": user_prompt}])


def plan_feature_ask(
    ask: str,
    output_dir: str,
    *,
    query_fn: Optional[PlanQueryFn] = None,
) -> list[dict]:
    """Ask an LLM to translate the user's feature ask into an ordered
    step list. Returns the validated plan or raises
    :class:`PlanValidationError`.

    Tests inject ``query_fn`` to bypass the LLM.
    """
    import json
    fn = query_fn or _default_plan_query
    raw = fn(_PLANNING_SYSTEM_PROMPT, _build_planning_user_prompt(ask, output_dir))
    if not isinstance(raw, str) or not raw.strip():
        raise PlanValidationError("planner returned empty output")
    # Tolerate stray markdown fences — the fix agent's prompt does the
    # same trimming and it's the single most common LLM output smell.
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0]
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanValidationError(f"planner output was not valid JSON: {e}")
    return validate_plan(plan)


# --------------------------------------------------------------------------- #
# Dispatch — plan step → real seam                                             #
# --------------------------------------------------------------------------- #
# Each entry maps a plan step kind to a callable ``(output_dir, args) → result``.
# The seams already exist in smith_tools; we import them lazily so unit tests
# for planning don't need the whole app_actions router graph.


def _dispatch_step(kind: str, output_dir: str, args: dict) -> dict:
    """Route one plan step to its seam handler."""
    from services.smith_tools import (
        _smith_add_page,
        _smith_add_workflow,
        _smith_add_entity,
        _smith_wire_form_to_workflow,
        _smith_edit_page,
    )
    handlers: dict[str, Callable[[str, dict], dict]] = {
        "add_entity": _smith_add_entity,
        "add_page": _smith_add_page,
        "add_workflow": _smith_add_workflow,
        "wire_form_to_workflow": _smith_wire_form_to_workflow,
        "edit_page": _smith_edit_page,
    }
    fn = handlers.get(kind)
    if fn is None:
        return {"success": False, "error": f"no handler for step kind {kind!r}"}
    return fn(output_dir, args)


def _step_success(result: dict) -> bool:
    """Any of the seam success signals: applied/success/edited True.
    Kept liberal so a mix of seam return shapes all count."""
    return (
        result.get("applied") is True
        or result.get("success") is True
        or result.get("edited") is True
    )


#: Directories the plan seams write into. Snapshotted before a plan runs so
#: a mid-plan failure can be unwound. Kept to the seam-owned trees — the
#: whole project would include node_modules and .next.
_SNAPSHOT_DIRS = ("workflows", "contracts", "src/schemas", "src/db", "src/app")

#: Above this many files the pre-image copy stops being a cheap safety net.
#: We then run WITHOUT rollback and say so in the result rather than
#: pretending the plan is unwindable.
_MAX_SNAPSHOT_FILES = 5000


def _take_snapshot(output_dir: str) -> tuple[Optional[str], Optional[str]]:
    """Copy the seam-owned trees to a temp dir. Returns ``(dir, reason)``:
    the snapshot path, or ``None`` plus why it was skipped."""
    root = Path(output_dir)
    present = [d for d in _SNAPSHOT_DIRS if (root / d).is_dir()]
    if not present:
        return None, "no seam-owned directories exist yet"
    n = sum(1 for d in present for _ in (root / d).rglob("*") if _.is_file())
    if n > _MAX_SNAPSHOT_FILES:
        return None, f"{n} files exceeds the {_MAX_SNAPSHOT_FILES}-file snapshot budget"
    snap = tempfile.mkdtemp(prefix="forge-plan-snap-")
    try:
        for d in present:
            shutil.copytree(root / d, Path(snap) / d, dirs_exist_ok=True)
    except OSError as exc:
        shutil.rmtree(snap, ignore_errors=True)
        return None, f"snapshot copy failed: {exc}"
    return snap, None


def _restore_snapshot(output_dir: str, snap: str) -> list[str]:
    """Restore the snapshotted trees over the live ones. Returns the list of
    directories restored. Raises OSError if a restore fails — a rollback that
    half-works must not be reported as a rollback."""
    root = Path(output_dir)
    restored: list[str] = []
    for d in _SNAPSHOT_DIRS:
        src = Path(snap) / d
        if not src.is_dir():
            continue
        dst = root / d
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        restored.append(d)
    return restored


def apply_plan(
    plan: list[dict], output_dir: str,
    *,
    on_progress: Optional[Callable[[dict], None]] = None,
    rollback: bool = True,
) -> dict:
    """Execute each step in order, unwinding on the first failure.

    ``rollback=True`` (the default) snapshots the seam-owned directories
    before the first step and restores them if any step fails. Without it
    a 5-step plan failing at step 4 left 3 steps applied on disk with no
    way back (register S24-5) — the sub-seams run with ``git=False``, so
    there is not even a commit boundary to revert to.

    Returns::

        {
          "status": "ok" | "partial",
          "steps": [{kind, label, ok, result, elapsed_ms}, …],
          "edited_paths": [str, …],   # unique union across steps
          "failed_at": <index>|None,  # index of the failing step, or None
          "rolled_back": bool,        # were the applied steps unwound?
          "rollback_note": str|None,  # why not, when False
        }
    """
    steps_out: list[dict] = []
    edited_paths: list[str] = []
    failed_at: Optional[int] = None

    snapshot: Optional[str] = None
    rollback_note: Optional[str] = None
    if rollback:
        snapshot, rollback_note = _take_snapshot(output_dir)
        if snapshot is None:
            logger.warning(
                "plan_and_apply: running WITHOUT rollback for %s — %s",
                output_dir, rollback_note,
            )

    for i, step in enumerate(plan):
        kind = step["kind"]
        label = step.get("label") or f"{kind} step"
        args = step["args"]
        t0 = time.monotonic()
        if on_progress:
            try:
                on_progress({"index": i, "total": len(plan), "label": label, "stage": "start"})
            except Exception:  # noqa: BLE001 — progress errors are non-fatal
                logger.exception("plan_and_apply: on_progress crashed")
        try:
            result = _dispatch_step(kind, output_dir, args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("plan_and_apply: step %d (%s) crashed", i, kind)
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        ok = _step_success(result)
        # Fold any paths the seam touched.
        for k in ("edited_paths", "files_touched", "written"):
            v = result.get(k) if isinstance(result, dict) else None
            if isinstance(v, list):
                for p in v:
                    if isinstance(p, str) and p and p not in edited_paths:
                        edited_paths.append(p)
                    elif isinstance(p, dict):
                        pp = p.get("path")
                        if isinstance(pp, str) and pp and pp not in edited_paths:
                            edited_paths.append(pp)
        steps_out.append({
            "index": i, "kind": kind, "label": label, "ok": ok,
            "result": result, "elapsed_ms": elapsed_ms,
        })
        if on_progress:
            try:
                on_progress({
                    "index": i, "total": len(plan), "label": label,
                    "stage": "done" if ok else "failed",
                    "elapsed_ms": elapsed_ms,
                })
            except Exception:  # noqa: BLE001
                logger.exception("plan_and_apply: on_progress crashed")
        if not ok:
            failed_at = i
            break

    rolled_back = False
    if failed_at is not None and snapshot:
        try:
            restored = _restore_snapshot(output_dir, snapshot)
            rolled_back = True
            logger.warning(
                "plan_and_apply: step %d (%s) failed — rolled back %d applied "
                "step(s); restored %s",
                failed_at, steps_out[failed_at]["kind"], failed_at,
                ", ".join(restored) or "nothing",
            )
        except OSError as exc:
            # A half-restored tree is worse than an un-restored one, and
            # reporting a rollback that did not happen is worse still.
            rollback_note = (
                f"ROLLBACK FAILED after step {failed_at}: {exc}. The plan is "
                f"half-applied on disk and the pre-image is at {snapshot} — "
                f"do not delete it until the tree is reconciled."
            )
            logger.exception("plan_and_apply: rollback failed for %s", output_dir)
            snapshot = None  # keep it on disk for recovery

    if snapshot:
        shutil.rmtree(snapshot, ignore_errors=True)

    return {
        "status": "ok" if failed_at is None else "partial",
        "steps": steps_out,
        "edited_paths": [] if rolled_back else edited_paths,
        "failed_at": failed_at,
        "rolled_back": rolled_back,
        "rollback_note": rollback_note,
    }


# --------------------------------------------------------------------------- #
# Entry point — plan + apply as one call                                       #
# --------------------------------------------------------------------------- #

def plan_and_apply(
    ask: str, output_dir: str,
    *,
    query_fn: Optional[PlanQueryFn] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
) -> dict:
    """One call: plan → validate → execute → summarize.

    Returns the same shape as :func:`apply_plan` plus a ``plan`` key
    with the LLM's proposed step list — so Smith can echo it back to
    the user (Rule 2 of KISS: 'always show a 1-line plan before
    multi-step work')."""
    try:
        plan = plan_feature_ask(ask, output_dir, query_fn=query_fn)
    except PlanValidationError as e:
        return {
            "status": "plan_error",
            "error": str(e),
            "steps": [],
            "edited_paths": [],
            "plan": None,
        }
    exec_result = apply_plan(plan, output_dir, on_progress=on_progress)
    exec_result["plan"] = plan
    return exec_result
