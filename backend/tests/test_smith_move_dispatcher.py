"""Move dispatcher — Migration Step 2.

Given an `understanding` dict (the output of `understand_ask`), picks
the right seam to actually make the change. The dispatcher itself is
pure routing; the seams it dispatches to are already tested in their
own modules.

Contract:
  * `dispatch_move(understanding, output_dir, seams)` → IterationMove
  * seams is an injectable table: {seam_name: callable}. Production
    supplies real seams (add_page_seam, edit_page, edit_workflow_seam,
    add_workflow_seam, add_entity_seam, edit_file); tests supply stubs.
  * Refuses to invent a move it doesn't have — returns None so the
    session bubbles up "I don't know how to do that" to the user.
"""
from __future__ import annotations

import pytest

from services.smith_move_dispatcher import (
    dispatch_move,
    infer_move_kind,
    SEAM_KEYS,
)
from services.smith_session import IterationMove


# --------------------------------------------------------------------------- #
# infer_move_kind — text → seam name
# --------------------------------------------------------------------------- #

def test_infer_move_kind_field_change_maps_to_edit_page():
    u = {
        "screen": "Add Candidate",
        "element_label": "Upload CV",
        "current_behavior": "Select",
        "desired_behavior": "FileUpload",
        "target_file": "src/schemas/candidates/new.json",
    }
    assert infer_move_kind(u) == "edit_page"


def test_infer_move_kind_new_page_maps_to_add_page():
    u = {
        "screen": "no such page yet",
        "current_behavior": "missing",
        "desired_behavior": "new page for Candidate list",
        "target_file": "",           # signal: doesn't exist yet
        "wants_new_page": True,       # optional field the understand may add
    }
    assert infer_move_kind(u) == "add_page"


def test_infer_move_kind_workflow_change_maps_to_edit_workflow():
    u = {
        "screen": "Approve Candidate action",
        "current_behavior": "workflow crashes on submit",
        "desired_behavior": "requires notes on rejection",
        "target_file": "workflows/ApproveCandidate.json",
    }
    assert infer_move_kind(u) == "edit_workflow"


def test_infer_move_kind_env_change_maps_to_edit_file():
    u = {
        "current_behavior": "S3 bucket not set",
        "desired_behavior": "set S3_BUCKET=my-bucket",
        "target_file": ".env.local",
    }
    assert infer_move_kind(u) == "edit_file"


def test_infer_move_kind_unknown_returns_none():
    u = {
        "current_behavior": "?",
        "desired_behavior": "make it faster",
        "target_file": "",
    }
    assert infer_move_kind(u) is None


# --------------------------------------------------------------------------- #
# dispatch_move — invokes the right seam
# --------------------------------------------------------------------------- #

def test_dispatch_move_calls_the_right_seam_by_target_file(tmp_path):
    calls: list[tuple[str, dict, str]] = []

    def _edit_page(understanding, output_dir):
        calls.append(("edit_page", understanding, output_dir))
        return IterationMove(
            move_name="edit_page(candidates/new.json)",
            touched_paths=[understanding["target_file"]],
        )

    move = dispatch_move(
        understanding={
            "screen": "Add Candidate",
            "element_label": "Upload CV",
            "current_behavior": "Select",
            "desired_behavior": "FileUpload",
            "target_file": "src/schemas/candidates/new.json",
        },
        output_dir=str(tmp_path),
        seams={"edit_page": _edit_page},
    )
    assert move is not None
    assert move.move_name.startswith("edit_page")
    assert calls[0][0] == "edit_page"


def test_dispatch_move_returns_none_when_seam_is_missing(tmp_path):
    """A move kind we can infer but have no seam for → None. Session
    surfaces "I know what to do but can't do it here" to the user."""
    move = dispatch_move(
        understanding={
            "screen": "x", "element_label": "y",
            "current_behavior": "workflow issue",
            "desired_behavior": "fix",
            "target_file": "workflows/X.json",
        },
        output_dir=str(tmp_path),
        seams={},  # no edit_workflow seam
    )
    assert move is None


def test_dispatch_move_returns_none_for_unknown_intent(tmp_path):
    move = dispatch_move(
        understanding={"current_behavior": "?", "desired_behavior": "?", "target_file": ""},
        output_dir=str(tmp_path),
        seams={"edit_page": lambda u, o: IterationMove("x", [])},
    )
    assert move is None


def test_seam_keys_is_the_exhaustive_registry():
    """Regression guard: if we introduce a new seam name it must be
    listed here so callers can enumerate what's plausibly available."""
    assert set(SEAM_KEYS) == {
        "edit_page", "add_page",
        "edit_workflow", "add_workflow", "add_entity",
        "edit_file",
        "replan",
    }


# --------------------------------------------------------------------------- #
# Phase D — replan intent
# --------------------------------------------------------------------------- #

def test_infer_move_kind_wants_replan_flag_wins():
    """When understand_ask sets `wants_replan: true`, no other signal
    matters — the seam is replan."""
    u = {
        "desired_behavior": "add authentication with roles + login page",
        "target_file": "src/schemas/whatever.json",  # would otherwise route to edit_page
        "wants_replan": True,
    }
    assert infer_move_kind(u) == "replan"


def test_infer_move_kind_replan_hint_in_desired_behavior():
    """Fallback: without an explicit flag, hint keywords in
    desired_behavior trigger a replan."""
    u = {
        "desired_behavior": "add authentication so recruiters must log in",
        "target_file": "",  # no file → wouldn't route anywhere else
    }
    assert infer_move_kind(u) == "replan"


def test_infer_move_kind_small_ask_does_not_trigger_replan():
    """A local field-change ask stays edit_page even if the text
    happens to contain a soft word."""
    u = {
        "element_label": "Upload CV",
        "desired_behavior": "make it a FileUpload",
        "target_file": "src/schemas/candidates/new.json",
    }
    assert infer_move_kind(u) == "edit_page"


def test_dispatch_move_routes_to_replan_seam(tmp_path):
    calls: list[dict] = []

    def _replan(u, out):
        calls.append(u)
        return IterationMove(
            move_name="replan(2 entities added)", touched_paths=["plan.json"],
        )

    move = dispatch_move(
        understanding={
            "desired_behavior": "add authentication",
            "target_file": "",
            "wants_replan": True,
        },
        output_dir=str(tmp_path),
        seams={"replan": _replan},
    )
    assert move is not None
    assert move.move_name.startswith("replan")
    assert calls
