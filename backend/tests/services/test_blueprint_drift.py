"""Tests for services.blueprint_drift — detect out-of-band edits."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint_drift import (
    check_drift,
    format_drift_warning,
    _canonical,
    _parse_header,
    _sections_by_title,
)
from services.blueprint_writer import write_blueprint


def _write(root: Path, rel: str, content: dict | str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_text(json.dumps(content, indent=2), encoding="utf-8")


class TestMissingDir:
    def test_missing_dir_reports_stale(self, tmp_path):
        r = check_drift(tmp_path / "does-not-exist")
        assert r["stale"] is True
        assert r["missing"] is True
        assert "does not exist" in r["diff_summary"]

    def test_missing_blueprint_reports_stale(self, tmp_path):
        r = check_drift(tmp_path)
        assert r["stale"] is True
        assert r["missing"] is True


class TestFreshBuild:
    def test_after_write_drift_is_clean(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {
            "name": "MyApp",
            "entities": {"Tenant": {"fields": []}},
        })
        write_blueprint(tmp_path, source="generation", summary="build")
        r = check_drift(tmp_path)
        assert r["stale"] is False
        assert r["freshly_built_matches"] is True
        assert r["diff_summary"] == "blueprint is up-to-date"
        # Header timestamp/source captured for the UI.
        assert r["on_disk_source"] == "generation"
        assert r["on_disk_ts"] is not None


class TestActualDrift:
    def test_edit_after_write_shows_stale(self, tmp_path):
        # Build an initial blueprint against one plan.
        _write(tmp_path, "contracts/plan.json", {
            "name": "MyApp",
            "entities": {"Tenant": {"fields": []}},
        })
        write_blueprint(tmp_path, source="generation")

        # Simulate an out-of-band edit — add an entity without going
        # through any writer seam. The blueprint on disk still shows
        # only Tenant.
        _write(tmp_path, "contracts/plan.json", {
            "name": "MyApp",
            "entities": {
                "Tenant": {"fields": []},
                "Owner": {"fields": []},  # NEW — nothing rebuilt the blueprint
            },
        })

        r = check_drift(tmp_path)
        assert r["stale"] is True
        assert r["freshly_built_matches"] is False
        assert "stale" in r["diff_summary"]
        # Data Model section must be flagged as changed.
        assert any("Data Model" in s for s in r["changed_sections"])

    def test_stale_still_reports_last_source(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {"name": "A"})
        write_blueprint(tmp_path, source="smith")
        _write(tmp_path, "contracts/plan.json", {"name": "A", "description": "changed"})
        r = check_drift(tmp_path)
        assert r["on_disk_source"] == "smith"


class TestHeaderNormalization:
    def test_timestamp_diff_alone_is_not_drift(self, tmp_path):
        # Two builds ~1s apart with same content should not drift.
        _write(tmp_path, "contracts/plan.json", {"name": "App"})
        write_blueprint(tmp_path, source="generation")
        text_1 = (tmp_path / "BLUEPRINT.md").read_text()

        # Hand-edit the header to a different timestamp / different source.
        text_2 = text_1.replace(
            "Written by: generation",
            "Written by: someone_else",
        )
        (tmp_path / "BLUEPRINT.md").write_text(text_2, encoding="utf-8")

        r = check_drift(tmp_path)
        assert r["stale"] is False, (
            "changing only the header line should not count as drift"
        )


class TestCanonicalizer:
    def test_canonical_strips_last_built(self):
        text = "# App\n\n_Last built: 2026-01-01 · X · Y_\n\n## Body\nfoo"
        out = _canonical(text)
        assert "Last built" not in out
        assert "## Body" in out


class TestHeaderParse:
    def test_parse_header_extracts_ts_and_source(self):
        line = (
            "_Last built: 2026-08-09 12:34:56 UTC · Blueprint version 1 · "
            "Written by: editor · Log: 3 entries_"
        )
        ts, src = _parse_header(line)
        assert ts.startswith("2026-08-09")
        assert src == "editor"

    def test_parse_header_absent(self):
        ts, src = _parse_header("nothing here")
        assert ts is None
        assert src is None


class TestSectionsByTitle:
    def test_sections_split(self):
        text = "## A\nbody a\n## B\nbody b"
        m = _sections_by_title(text)
        assert m["A"] == "body a"
        assert m["B"] == "body b"


class TestFormatDriftWarning:
    def test_empty_when_clean(self):
        assert format_drift_warning({"stale": False}) == ""

    def test_stale_produces_line(self):
        w = format_drift_warning({
            "stale": True,
            "on_disk_ts": "2026-01-01",
            "changed_sections": ["Data Model", "Pages"],
        })
        assert "blueprint drift" in w
        assert "Data Model" in w


# ---------------------------------------------------------------------------
# Endpoint test
# ---------------------------------------------------------------------------

class _FakeProject:
    def __init__(self, output_dir: str | None):
        self.output_dir = output_dir


class _FakeUser:
    id = "u-1"
    email = "test@example.com"


@pytest.fixture()
def _patched_auth(monkeypatch):
    async def _fake_get_project(project_id, user, db):
        return _fake_get_project.project
    _fake_get_project.project = _FakeProject(output_dir=None)
    monkeypatch.setattr(
        "services.project_service.get_project_with_auth", _fake_get_project,
    )
    monkeypatch.setattr(
        "routers.projects.get_project_with_auth", _fake_get_project,
    )
    return _fake_get_project


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_returns_drift_report(self, tmp_path, _patched_auth):
        from routers.projects import blueprint_drift as endpoint
        import uuid as _uuid

        _write(tmp_path, "contracts/plan.json", {"name": "App"})
        write_blueprint(tmp_path, source="generation")

        _patched_auth.project = _FakeProject(output_dir=str(tmp_path))
        r = await endpoint(
            project_id=_uuid.uuid4(),
            user=_FakeUser(),
            db=None,
        )
        assert "stale" in r
        assert r["stale"] is False

    @pytest.mark.asyncio
    async def test_endpoint_400_without_output_dir(self, tmp_path, _patched_auth):
        from routers.projects import blueprint_drift as endpoint
        from fastapi import HTTPException
        import uuid as _uuid

        _patched_auth.project = _FakeProject(output_dir=None)
        with pytest.raises(HTTPException) as exc:
            await endpoint(
                project_id=_uuid.uuid4(),
                user=_FakeUser(),
                db=None,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_endpoint_404_when_dir_missing(self, tmp_path, _patched_auth):
        from routers.projects import blueprint_drift as endpoint
        from fastapi import HTTPException
        import uuid as _uuid

        _patched_auth.project = _FakeProject(
            output_dir=str(tmp_path / "nope"),
        )
        with pytest.raises(HTTPException) as exc:
            await endpoint(
                project_id=_uuid.uuid4(),
                user=_FakeUser(),
                db=None,
            )
        assert exc.value.status_code == 404
