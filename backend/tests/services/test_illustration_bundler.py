import json
from pathlib import Path
from services.illustration_bundler import bundle_illustrations_for_schema


def test_bundles_chosen_slug_into_public_illustrations(tmp_path, monkeypatch):
    # Stub cache dir with a fake SVG
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "running-athlete__6b7280.svg").write_bytes(b"<svg/>")
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)

    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "auth",
        "route": "/login", "layout": "main",
        "root": {
            "type": "Hero",
            "id": "hero",
            "props": {
                "headline": "Welcome",
                "illustration": {"slug": "running-athlete", "alt": "Running"}
            }
        }
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")

    bundled = output_dir / "public" / "illustrations" / "running-athlete.svg"
    assert bundled.exists()
    assert bundled.read_bytes() == b"<svg/>"


def test_no_op_when_schema_has_no_illustrations(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)

    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "list", "route": "/", "layout": "main",
        "root": {"type": "Stack", "id": "r", "children": []}
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")
    # No illustrations dir created when nothing to bundle
    assert not (output_dir / "public" / "illustrations").exists()


def test_missing_cache_entry_skipped_silently(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr("services.illustration_bundler._CACHE_DIR", cache)
    output_dir = tmp_path / "proj"
    schema = {
        "schemaVersion": "2", "id": "auth", "route": "/login", "layout": "main",
        "root": {
            "type": "Hero", "id": "hero",
            "props": {"illustration": {"slug": "never-fetched", "alt": ""}}
        }
    }
    bundle_illustrations_for_schema(str(output_dir), schema, accent_color="6b7280")
    # Doesn't crash; no file produced
    assert not (output_dir / "public" / "illustrations" / "never-fetched.svg").exists()
