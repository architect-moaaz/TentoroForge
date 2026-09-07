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
        spec_path.write_text(json.dumps(content), encoding="utf-8")
    else:
        spec_path.write_text(content, encoding="utf-8")
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

    written = json.loads(tokens_file.read_text(encoding="utf-8"))
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
