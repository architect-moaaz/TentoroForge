"""Move dispatcher — Migration Step 2.

Given an ``understanding`` dict, pick which seam to invoke and hand
it the args. The dispatcher is pure routing; the seams themselves
already exist in the codebase and are exercised by their own tests.

The dispatch table (``seams``) is injected so tests use stubs.
Production wiring happens in the chat handler (Step 3), which
supplies real callables that wrap the existing add_page_seam /
edit_workflow_seam / _apply_page_schema_patch functions.
"""
from __future__ import annotations

from typing import Any, Callable

from services.smith_session import IterationMove


# --------------------------------------------------------------------------- #
# The exhaustive seam registry
# --------------------------------------------------------------------------- #

SEAM_KEYS: tuple[str, ...] = (
    "edit_page",
    "add_page",
    "edit_workflow",
    "add_workflow",
    "add_entity",
    "edit_file",
    "replan",
)


# Heuristic: asks that describe a WHOLE CAPABILITY (auth, payments, roles,
# search, etc.) are too big for direct-seam edits — they need a fresh plan
# pass. Match generously; false positives are OK (the replan seam itself
# will refuse when it can't produce a coherent plan).
_REPLAN_HINTS: tuple[str, ...] = (
    "add auth", "authentication", "authoriz",
    "add payment", "stripe", "checkout",
    "add search", "full-text search", "index",
    "add roles", "rbac", "permission",
    "add notification", "email digest",
    "rewrite", "redesign the",
)

SeamFn = Callable[[dict, str], IterationMove | None]


# --------------------------------------------------------------------------- #
# Intent inference — understanding → seam name
# --------------------------------------------------------------------------- #

def infer_move_kind(understanding: dict[str, Any]) -> str | None:
    """Pick the seam kind that matches this ``understanding``.

    Heuristics, ordered by specificity — the first match wins:

      1. Explicit ``wants_new_page`` flag ⇒ add_page.
      2. ``target_file`` starts with ``workflows/`` ⇒ edit_workflow.
      3. ``target_file`` matches an env/config file ⇒ edit_file.
      4. ``target_file`` looks like a schema path ⇒ edit_page.
      5. Nothing to go on ⇒ None (session bubbles up to ask_user).
    """
    if not isinstance(understanding, dict):
        return None

    # Explicit replan flag wins over every file-based signal — a
    # "add authentication" ask that happens to also carry a target_file
    # must still be routed to the planner, not to an in-place edit.
    if understanding.get("wants_replan") is True:
        return "replan"

    if understanding.get("wants_new_page") is True:
        return "add_page"

    if understanding.get("wants_new_entity") is True:
        return "add_entity"

    if understanding.get("wants_new_workflow") is True:
        return "add_workflow"

    target = str(understanding.get("target_file") or "").strip()
    if not target:
        # No file target — last chance to catch a big-capability ask by
        # inspecting the desired behavior text. Keeps false positives
        # low (only fires when there's no file to edit).
        haystack = " ".join(
            str(understanding.get(k) or "")
            for k in ("desired_behavior", "element_label", "screen")
        ).lower()
        if any(hint in haystack for hint in _REPLAN_HINTS):
            return "replan"
        return None

    normalized = target.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("workflows/") or normalized.endswith(".workflow.json"):
        return "edit_workflow"
    if normalized in {".env", ".env.local", ".env.production"} \
            or normalized.startswith(".env."):
        return "edit_file"
    if normalized.startswith("src/schemas/") and normalized.endswith(".json"):
        return "edit_page"

    # Fallback: an obvious file path that isn't schema/workflow/env
    # gets edit_file, but only if the caller supplies it. Otherwise
    # unknown so the session asks.
    if "/" in normalized and "." in normalized.rsplit("/", 1)[-1]:
        return "edit_file"

    return None


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def dispatch_move(
    understanding: dict[str, Any],
    output_dir: str,
    seams: dict[str, SeamFn],
) -> IterationMove | None:
    """Route ``understanding`` to a seam. Returns None when no seam
    matches or the matched seam isn't registered (both surface as
    "I don't know how to do that" via the session)."""
    kind = infer_move_kind(understanding)
    if kind is None:
        return None
    seam = seams.get(kind)
    if seam is None:
        return None
    return seam(understanding, output_dir)
