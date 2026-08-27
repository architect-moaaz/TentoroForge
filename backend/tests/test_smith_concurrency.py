"""Concurrency: multiple Smiths + editor writes on the same project.

Spec §10.6 & §6.5-6.6.

Two seams here:
  * ``Blueprint.save_if_unchanged(expected_fingerprint)`` — optimistic
    locking. A caller that loaded the blueprint at fingerprint X can
    only save if the on-disk fingerprint is still X.
  * ``EditorMirror.record_edit(...)`` — the editor's save handler
    calls this after writing a schema/workflow file, so Smith's next
    turn sees the change in the blueprint change_log with
    source='editor'.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.smith_concurrency import (
    ConcurrentModificationError,
    EditorMirror,
    save_if_unchanged,
)


def _fresh_bp(tmp_path: Path) -> Blueprint:
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="v1", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()
    return Blueprint.load(project_id="p1", output_dir=str(tmp_path))


# --------------------------------------------------------------------------- #
# save_if_unchanged
# --------------------------------------------------------------------------- #

def test_save_if_unchanged_succeeds_when_fingerprint_matches(tmp_path):
    bp = _fresh_bp(tmp_path)
    fp = bp.fingerprint()
    bp.add_entity(name="X", table="xs", purpose="", key_fields=[],
                  why_shaped_this_way="")
    # No one else touched the file; fingerprint check passes.
    save_if_unchanged(bp, expected_fingerprint=fp)

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert [e["name"] for e in reloaded.entities] == ["X"]


def test_save_if_unchanged_refuses_when_other_writer_won(tmp_path):
    """Two Smiths read at the same fingerprint. One writes first
    (changing the on-disk fingerprint). The second's save must fail
    loudly rather than clobber."""
    bp_a = _fresh_bp(tmp_path)
    fp = bp_a.fingerprint()

    # Simulate the OTHER writer landing first.
    bp_b = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp_b.add_entity(name="OtherWriter", table="ow", purpose="",
                    key_fields=[], why_shaped_this_way="")
    bp_b.save()

    # A's staged change now stales — save_if_unchanged should refuse.
    bp_a.add_entity(name="A", table="a", purpose="", key_fields=[],
                    why_shaped_this_way="")
    with pytest.raises(ConcurrentModificationError):
        save_if_unchanged(bp_a, expected_fingerprint=fp)

    # OtherWriter's entry is intact — no clobber.
    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert any(e["name"] == "OtherWriter" for e in reloaded.entities)


# --------------------------------------------------------------------------- #
# EditorMirror
# --------------------------------------------------------------------------- #

def test_editor_mirror_records_change_log_entry_with_editor_source(tmp_path):
    _fresh_bp(tmp_path)
    mirror = EditorMirror(project_id="p1", output_dir=str(tmp_path))
    mirror.record_edit(
        artifact_path="src/schemas/candidates/new.json",
        summary="renamed field firstName → givenName",
        why="user renamed field in the visual editor",
    )

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    last = bp.change_log[-1]
    assert last["source"] == "editor"
    assert "renamed" in last["diff_summary"]
    assert "editor" in last["smith_move"]  # "editor: …" prefix by convention
    assert "src/schemas/candidates/new.json" in last["smith_move"]


def test_editor_mirror_supports_concurrent_smith_writes(tmp_path):
    """Even when Smith is mid-turn, an editor save must land — it's
    the user driving. The mirror retries once on a stale
    fingerprint, then bails loudly. Here we test that the retry
    branch works when the on-disk state has moved on."""
    _fresh_bp(tmp_path)
    # Simulate a Smith write happening between mirror's load and save.
    bp_pre = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    # Sneak in a change from another writer BEFORE the mirror commits.
    bp_smith = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp_smith.add_entity(name="SmithMidTurn", table="smt", purpose="",
                        key_fields=[], why_shaped_this_way="")
    bp_smith.save()

    # Mirror still lands its edit (reloads on the retry).
    mirror = EditorMirror(project_id="p1", output_dir=str(tmp_path))
    mirror.record_edit(
        artifact_path="workflows/CreateCandidate.json",
        summary="+1 field on trigger inputs",
        why="editor added a required input",
    )

    reloaded = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    # Both landed.
    assert any(e["name"] == "SmithMidTurn" for e in reloaded.entities)
    editor_entries = [e for e in reloaded.change_log if e.get("source") == "editor"]
    assert len(editor_entries) == 1
    assert "trigger inputs" in editor_entries[0]["diff_summary"]
