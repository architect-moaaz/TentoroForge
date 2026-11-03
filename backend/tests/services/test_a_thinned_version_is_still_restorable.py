"""Keeping every version whole filled a host; keeping fewer must lose nothing.

A snapshot used to be the entire document, change history included — and the
history is the larger half of a grown Blueprint, the same list copied into
every snapshot, so the versions directory grew with the square of the number
of changes. One application held 119 snapshots in 8.2 GB and the UAT disk hit
92% (2026-11-03).

Thinning snapshots is only acceptable if it takes nothing away, so these tests
are about what survives it: a version whose file is gone must still come back,
byte for byte, replayed from the diffs the history already records — and must
still be offered to a person as restorable.
"""
import json

import pytest

from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="app_1", name="Recruitment", domain="ATS"
    )


def _change(svc: BlueprintService, n: int) -> tuple[int, dict]:
    """One recorded change; the version it lands on and the document at it.

    `commit` bumps, so a service created at v1 stands at v2 after the first
    change — and the snapshot it wrote is of v1, the state it superseded.
    """
    before = svc.snapshot()
    svc.doc.setdefault("product", {})["objectives"] = [f"objective {i}" for i in range(n)]
    svc.commit(user_request=f"set {n} objectives", before=before)
    return int(svc.doc["version"]), svc.snapshot()


def _bodies(docs: dict[int, dict]) -> dict[int, dict]:
    return {v: {k: x for k, x in d.items() if k != "changeHistory"} for v, d in docs.items()}


# --- what a snapshot holds -------------------------------------------------

def test_a_snapshot_does_not_carry_the_change_history(svc):
    _change(svc, 1)
    stored = json.loads(svc.version_path(1).read_text("utf-8"))
    assert "changeHistory" not in stored, (
        "the history is the same list in every snapshot and no reader wants "
        "the copy — storing it is what made the directory grow quadratically")


def test_the_document_read_back_does_carry_the_history(svc):
    _change(svc, 1)
    _change(svc, 2)
    doc = svc.document_at(1)
    assert doc["version"] == 1
    assert doc["changeHistory"] == svc.doc["changeHistory"], (
        "a restore keeps the whole trail, including the change it reverses")


def test_the_definition_can_be_read_without_the_history(svc):
    _change(svc, 1)
    assert "changeHistory" not in svc.document_at(1, with_history=False)


# --- thinning --------------------------------------------------------------

def test_nothing_is_thinned_while_the_recent_window_covers_everything(svc):
    for n in range(1, BlueprintService.KEEP_RECENT + 1):
        _change(svc, n)
    assert svc.versions() == list(range(1, BlueprintService.KEEP_RECENT + 1))


def test_older_snapshots_are_thinned_and_the_floor_and_bases_stay(svc):
    total = BlueprintService.BASE_EVERY * 2 + 5
    for n in range(1, total + 1):
        _change(svc, n)

    kept = svc.versions()
    assert len(kept) < total, "the whole point is that fewer files are kept"
    assert kept[0] == 1, "the oldest snapshot is the replay floor and is never dropped"
    for v in range(total - BlueprintService.KEEP_RECENT + 1, total + 1):
        assert v in kept, f"v{v} is inside the recent window"
    for base in (BlueprintService.BASE_EVERY, BlueprintService.BASE_EVERY * 2):
        assert base in kept, f"v{base} is a base and bounds the replay"


# --- what thinning must not take away --------------------------------------

def test_a_thinned_version_is_rebuilt_exactly(svc):
    total = BlueprintService.BASE_EVERY * 2 + 5
    seen = {}
    for n in range(1, total + 1):
        version, doc = _change(svc, n)
        seen[version] = doc
    bodies = _bodies(seen)

    gone = [v for v in bodies if not svc.version_path(v).is_file()]
    assert gone, "this test is pointless unless something was thinned"

    for v in gone:
        assert svc.document_at(v, with_history=False) == bodies[v], (
            f"v{v} came back different from how it stood")


def test_a_kept_version_and_a_thinned_one_read_the_same_way(svc):
    for n in range(1, BlueprintService.BASE_EVERY * 2 + 6):
        _change(svc, n)
    kept = [v for v in svc.recoverable_versions() if svc.version_path(v).is_file()]
    gone = [v for v in svc.recoverable_versions() if not svc.version_path(v).is_file()]
    for v in (kept[-1], gone[0]):
        assert svc.document_at(v)["version"] == v


def test_every_recorded_version_is_still_offered_as_recoverable(svc):
    total = BlueprintService.BASE_EVERY * 2 + 5
    for n in range(1, total + 1):
        _change(svc, n)
    # Every version the history records, from the floor to where it stands.
    assert svc.recoverable_versions() == list(range(1, total + 2)), (
        "a thinned version must not disappear from what a person can go back to")


def test_a_version_the_history_cannot_reach_is_refused_not_guessed(svc):
    _change(svc, 1)
    with pytest.raises(FileNotFoundError):
        svc.document_at(99)


def test_a_version_below_the_floor_is_refused(svc):
    _change(svc, 1)
    _change(svc, 2)
    svc.version_path(1).unlink()
    with pytest.raises(FileNotFoundError):
        svc.document_at(1)


# --- an application versioned before this ----------------------------------

def test_compaction_strips_the_history_from_snapshots_already_written(svc):
    # Write the old way: whole document, history and all.
    for n in range(1, BlueprintService.BASE_EVERY + 6):
        _change(svc, n)
    for v in svc.versions():
        svc.version_path(v).write_text(
            json.dumps({**svc.doc, "version": v}, indent=2, sort_keys=True), "utf-8")
    fat = sum(svc.version_path(v).stat().st_size for v in svc.versions())

    out = svc.compact_versions()

    assert out["bytes_after"] < fat
    for v in svc.versions():
        assert "changeHistory" not in json.loads(svc.version_path(v).read_text("utf-8"))


def test_an_old_fat_snapshot_still_reads(svc):
    _change(svc, 1)
    _change(svc, 2)
    svc.version_path(1).write_text(
        json.dumps({**svc.doc, "version": 1}, indent=2, sort_keys=True), "utf-8")
    assert svc.document_at(1)["version"] == 1


# --- the history must say what was true when it was written ----------------
#
# Found by the replay above returning a document with the LATEST values under
# an early version. `jsonpatch.make_patch` does not copy: the op it records
# points at the object it found in the document, so until the diff was
# detached, a later in-place change rewrote a diff already saved — and every
# §92 audit trail on a long-lived service was telling the wrong story.

def test_a_recorded_change_is_not_rewritten_by_a_later_one(svc):
    before = svc.snapshot()
    svc.doc.setdefault("product", {})["objectives"] = ["first"]
    svc.commit(user_request="one objective", before=before)
    as_recorded = json.loads(json.dumps(svc.doc["changeHistory"][0]["blueprintDiff"]))

    before = svc.snapshot()
    svc.doc["product"]["objectives"].append("second")  # mutated in place
    svc.commit(user_request="two objectives", before=before)

    assert svc.doc["changeHistory"][0]["blueprintDiff"] == as_recorded
    on_disk = json.loads(svc.current_path.read_text("utf-8"))
    assert on_disk["changeHistory"][0]["blueprintDiff"] == as_recorded, (
        "the saved history was overwritten with values from a later change")


def test_rebuilding_a_version_does_not_disturb_the_history(svc):
    for n in range(1, BlueprintService.BASE_EVERY + 6):
        _change(svc, n)
    unchanged = json.loads(json.dumps(svc.doc["changeHistory"]))

    for v in svc.recoverable_versions():
        if not svc.version_path(v).is_file() and v != int(svc.doc["version"]):
            svc.document_at(v)

    assert svc.doc["changeHistory"] == unchanged, (
        "a replay read the records; it must not have written to them")


# --- a file is only deleted when a replay has earned it --------------------
#
# Measured on the UAT host before this guard existed: of 669 adjacent versions
# across the live applications, 511 did NOT replay — every one versioned
# before the diffs were detached above. Thinning on the policy alone would
# have deleted history nothing could bring back.

def test_a_snapshot_the_history_cannot_rebuild_is_kept(svc):
    for n in range(1, BlueprintService.BASE_EVERY + 6):
        _change(svc, n)
    thinned = [v for v in svc.recoverable_versions() if not svc.version_path(v).is_file()]
    assert thinned, "nothing was thinned, so the guard is untested"

    # Corrupt one diff the way the aliasing bug did — values from a later change.
    victim = thinned[len(thinned) // 2]
    for rec in svc.doc["changeHistory"]:
        if int(rec.get("version") or 0) == victim:
            rec["blueprintDiff"] = [
                {"op": "add", "path": "/product/objectives/0", "value": "from the future"}]
    svc.save()

    # A later change prunes again; the unrebuildable version must survive it.
    before = svc.snapshot()
    svc.doc["product"]["objectives"] = ["something else"]
    svc.commit(user_request="one more", before=before)

    rebuilt_wrong = []
    for v in svc.versions():
        try:
            if svc._replay_to(v) != svc._stored_snapshot(v):
                rebuilt_wrong.append(v)
        except FileNotFoundError:
            continue
    assert all(svc.version_path(v).is_file() for v in rebuilt_wrong), (
        "a snapshot whose replay disagrees with it was deleted anyway")


def test_a_diff_that_touches_the_history_does_not_break_a_replay(svc):
    # `revert` rewrites changeHistory before committing, so its diff carries
    # ops against a list a stripped snapshot does not have.
    for n in range(1, 4):
        _change(svc, n)
    target = int(svc.doc["version"])
    before = svc.snapshot()
    svc.doc["product"]["objectives"] = ["after an undo"]
    svc.doc["changeHistory"] = list(before.get("changeHistory") or [])
    svc.commit(user_request="undo: something", before=before)

    assert svc.document_at(target)["version"] == target
