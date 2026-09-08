"""A build that passed reaches `ready` even if its SSE request died.

The status->ready flip lived only in the /generate/blueprint request handler,
so a long run the user navigated away from left the app BUILT but stuck in
`draft`, with Publish disabled. `reconcile_ready_status` derives `ready` from
the build artifact (`runtime.build.status == "passed"`) on read instead.
"""
import asyncio
import json

from models.project import Project, ProjectStatus
from services.project_service import _build_passed, reconcile_ready_status


def _bp(tmp_path, status):
    d = tmp_path / ".forge" / "blueprint"
    d.mkdir(parents=True)
    (d / "current.json").write_text(
        json.dumps({"runtime": {"build": {"status": status}}}), "utf-8")
    return str(tmp_path)


def test_build_passed_reads_the_artifact(tmp_path):
    assert _build_passed(_bp(tmp_path / "a", "passed")) is True
    assert _build_passed(_bp(tmp_path / "b", "failed")) is False
    assert _build_passed(str(tmp_path / "missing")) is False
    assert _build_passed(None) is False


class _FakeDB:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True

    async def refresh(self, _obj):
        pass


def _run(project, db):
    return asyncio.run(reconcile_ready_status(project, db))


def test_a_draft_project_whose_build_passed_becomes_ready(tmp_path):
    p = Project(status=ProjectStatus.draft, output_dir=_bp(tmp_path / "a", "passed"))
    db = _FakeDB()
    assert _run(p, db).status == ProjectStatus.ready
    assert db.committed


def test_a_draft_without_a_passing_build_stays_draft(tmp_path):
    p = Project(status=ProjectStatus.draft, output_dir=_bp(tmp_path / "b", "failed"))
    db = _FakeDB()
    assert _run(p, db).status == ProjectStatus.draft
    assert not db.committed


def test_generating_and_ready_are_left_alone(tmp_path):
    # A run in flight (`generating`) must not be flipped mid-build; a terminal
    # state owns itself. Idempotent for `ready`.
    for st in (ProjectStatus.generating, ProjectStatus.ready):
        p = Project(status=st, output_dir=_bp(tmp_path / str(st), "passed"))
        db = _FakeDB()
        assert _run(p, db).status == st
        assert not db.committed
