"""Tests for the _debug_schema debug router.

Covers:
  POST /api/_debug/recompile-tokens/{short_id}
    - Happy path: compiles a design-spec and writes tokens.custom.json
    - 404: missing design-spec
    - 400: invalid JSON in design-spec

Path resolution is monkeypatched via _resolve_output_dir so the tests
are fully self-contained inside pytest's tmp_path, with no dependency on
the real repo output/ directory.
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: redirect _resolve_output_dir to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with _resolve_output_dir redirected to a per-test temp dir.

    The monkeypatch replaces the helper in the router module so every call
    inside the request handler hits tmp_path/<short_id> instead of the real
    output/ directory.
    """
    import routers._debug_schema as dbg

    def _fake_resolve(short_id: str) -> Path:
        return tmp_path / short_id

    monkeypatch.setattr(dbg, "_resolve_output_dir", _fake_resolve)

    from main import app
    yield TestClient(app), tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_DESIGN_SPEC = {
    "colorPalette": {
        "primary": "#3B82F6",
        "secondary": "#10B981",
        "background": "#F9FAFB",
    },
    "spacing": {
        "base": 4,
        "scale": [0, 4, 8, 12, 16, 24, 32, 48, 64],
    },
    "borderRadius": {
        "sm": "2px",
        "md": "6px",
        "lg": "12px",
        "full": "9999px",
    },
    "typography": {
        "fontFamily": "Inter",
        "headingWeight": "700",
        "bodySize": "14px",
    },
}


def _write_design_spec(base: Path, short_id: str, content: str | dict) -> Path:
    """Write design-spec.json under base/<short_id>/src/contracts/ and return its path."""
    contracts_dir = base / short_id / "src" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    spec_path = contracts_dir / "design-spec.json"
    if isinstance(content, dict):
        spec_path.write_text(json.dumps(content))
    else:
        spec_path.write_text(content)
    return spec_path


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_recompile_tokens_happy_path(client):
    tc, tmp = client
    short_id = "proj-happy"
    _write_design_spec(tmp, short_id, MINIMAL_DESIGN_SPEC)

    r = tc.post(f"/api/_debug/recompile-tokens/{short_id}")
    assert r.status_code == 200, r.text

    body = r.json()

    # Top-level response shape
    assert body["short_id"] == short_id
    assert body["design_spec_path"].endswith("design-spec.json")
    assert body["tokens_path"].endswith("tokens.custom.json")

    # Summary shape: all keys must be present
    summary = body["summary"]
    assert "color_groups" in summary
    assert "spacing_keys" in summary
    assert "radius_keys" in summary
    assert "shadow_keys" in summary
    assert "has_typography" in summary
    assert "has_motion" in summary
    assert "has_status" in summary
    assert "has_layout" in summary
    assert "total_top_level_keys" in summary

    # The design-spec has colorPalette -> compile() produces a "color" key
    assert summary["color_groups"] > 0
    # spacing and radius sections present in spec
    assert summary["spacing_keys"] > 0
    assert summary["radius_keys"] > 0
    # typography present
    assert summary["has_typography"] is True
    # no shadows, motion, or status in minimal spec
    assert summary["shadow_keys"] == 0
    assert summary["has_motion"] is False
    assert summary["has_status"] is False

    # The file must have been written on disk
    tokens_file = tmp / short_id / "src" / "theme" / "tokens.custom.json"
    assert tokens_file.exists(), "tokens.custom.json was not created on disk"

    written = json.loads(tokens_file.read_text())
    # color, spacing, radius, typography sections expected
    assert "color" in written
    assert "spacing" in written
    assert "radius" in written
    assert "typography" in written


# ---------------------------------------------------------------------------
# 404 — missing design-spec
# ---------------------------------------------------------------------------

def test_recompile_tokens_missing_spec(client):
    tc, tmp = client
    short_id = "proj-missing"
    # Deliberately do NOT create the design-spec file.

    r = tc.post(f"/api/_debug/recompile-tokens/{short_id}")
    assert r.status_code == 404
    detail = r.json().get("detail", "")
    assert "design-spec" in detail.lower()


# ---------------------------------------------------------------------------
# 400 — invalid JSON in design-spec
# ---------------------------------------------------------------------------

def test_recompile_tokens_invalid_json(client):
    tc, tmp = client
    short_id = "proj-badjson"
    _write_design_spec(tmp, short_id, "this is not json {{{{")

    r = tc.post(f"/api/_debug/recompile-tokens/{short_id}")
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "json" in detail.lower()


# ---------------------------------------------------------------------------
# project-file write resolves into app/ the way the read does
#
# The Blueprint projects the generated app under <output>/app/src/...; the GET
# falls through into app/ when the root miss. The POST used to write at the
# root, so an editor save landed in a file nothing serves and the page came
# back on refresh (DC5 "delete the Save Changes section" bug).
# ---------------------------------------------------------------------------

def _mk(tmp: Path, short_id: str, rel: str, text: str) -> Path:
    p = tmp / short_id / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_write_lands_where_the_read_resolves(client):
    """An existing app/src file is overwritten in place; no root copy appears."""
    tc, tmp = client
    sid = "proj-app-existing"
    schema = _mk(tmp, sid, "app/src/schemas/add-data.json", '{"id":"PAGE-002","old":1}')

    # The read finds it via the app/ fallback …
    r = tc.get(f"/api/_debug/project-file/{sid}/src/schemas/add-data.json")
    assert r.status_code == 200
    assert r.json()["old"] == 1

    # … so the write must land on the same file.
    r = tc.post(
        f"/api/_debug/project-file/{sid}/src/schemas/add-data.json",
        json={"content": '{"id":"PAGE-002","new":2}'},
    )
    assert r.status_code == 200, r.text
    assert json.loads(schema.read_text()) == {"id": "PAGE-002", "new": 2}
    assert not (tmp / sid / "src").exists(), "a root-level src/ copy was created"

    # And the read now sees the edit — the refresh round-trip.
    r = tc.get(f"/api/_debug/project-file/{sid}/src/schemas/add-data.json")
    assert r.json() == {"id": "PAGE-002", "new": 2}


def test_a_new_src_file_goes_into_the_app_when_one_exists(client):
    """A brand-new src/… file is created inside app/ — the output root's own
    src is never the generated application."""
    tc, tmp = client
    sid = "proj-app-new"
    _mk(tmp, sid, "app/package.json", "{}")

    r = tc.post(
        f"/api/_debug/project-file/{sid}/src/schemas/brand-new.json",
        json={"content": '{"id":"PAGE-009"}'},
    )
    assert r.status_code == 200, r.text
    assert (tmp / sid / "app/src/schemas/brand-new.json").read_text() == '{"id":"PAGE-009"}'
    assert not (tmp / sid / "src").exists()


def test_a_root_level_file_stays_at_the_root(client):
    """Files that already live at the output root (and non-src paths when no
    app/ exists) keep writing where they are — the fallback is not a redirect."""
    tc, tmp = client
    sid = "proj-root"
    root_file = _mk(tmp, sid, "src/schemas/at-root.json", '{"v":1}')
    _mk(tmp, sid, "app/package.json", "{}")  # app exists, but the root file wins

    r = tc.post(
        f"/api/_debug/project-file/{sid}/src/schemas/at-root.json",
        json={"content": '{"v":2}'},
    )
    assert r.status_code == 200, r.text
    assert root_file.read_text() == '{"v":2}'
    assert not (tmp / sid / "app/src").exists()

    # No app/ at all → a new file is created at the root, as before.
    sid2 = "proj-no-app"
    (tmp / sid2).mkdir()
    r = tc.post(
        f"/api/_debug/project-file/{sid2}/notes.txt",
        json={"content": "hello"},
    )
    assert r.status_code == 200, r.text
    assert (tmp / sid2 / "notes.txt").read_text() == "hello"


def test_write_still_blocks_traversal(client):
    tc, tmp = client
    sid = "proj-trav"
    (tmp / sid).mkdir()
    # httpx collapses a literal `..` client-side; percent-encode it so the
    # segment reaches the router's path parameter intact.
    r = tc.post(
        f"/api/_debug/project-file/{sid}/%2E%2E/escape.txt",
        json={"content": "x"},
    )
    assert r.status_code == 403, r.text
    assert not (tmp / "escape.txt").exists()
