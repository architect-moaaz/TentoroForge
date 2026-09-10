"""The route-registry generator must also emit src/schemas/load.ts — registry.ts
imports loadSchema from './load', and without that file the /[entity] route fails
to compile ('Module not found: ./load')."""
import json
from pathlib import Path

from services.schema_pipeline import _regenerate_route_registry


def _app(tmp_path: Path) -> Path:
    sd = tmp_path / "src" / "schemas"
    sd.mkdir(parents=True)
    (sd / "home.json").write_text(json.dumps({"id": "home", "route": "/"}), encoding="utf-8")
    (sd / "tasks.json").write_text(json.dumps({"id": "tasks", "route": "/tasks"}), encoding="utf-8")
    return tmp_path


def test_emits_load_ts_next_to_registry(tmp_path):
    _regenerate_route_registry(str(_app(tmp_path)))
    sd = tmp_path / "src" / "schemas"
    assert (sd / "registry.ts").exists()
    load = sd / "load.ts"
    assert load.exists(), "registry.ts imports ./load — load.ts must be emitted"
    txt = load.read_text(encoding="utf-8")
    assert "export function loadSchema" in txt
    # registry's import resolves to this file
    assert 'from "./load"' in (sd / "registry.ts").read_text(encoding="utf-8")


def test_does_not_clobber_existing_load(tmp_path):
    app = _app(tmp_path)
    (app / "src" / "schemas" / "load.ts").write_text("// custom\nexport function loadSchema(){}\n", encoding="utf-8")
    _regenerate_route_registry(str(app))
    assert "// custom" in (app / "src" / "schemas" / "load.ts").read_text(encoding="utf-8")


def test_load_ts_is_lenient_not_throwing(tmp_path):
    # Generated schemas use binding strings ("{{x}}") in typed fields, so strict
    # validation must NOT 500 the page — warn + render raw instead of throwing.
    from services.schema_pipeline import _SCHEMA_LOAD_TS
    assert "console.warn" in _SCHEMA_LOAD_TS
    assert "throw new Error(`invalid schema" not in _SCHEMA_LOAD_TS
    assert "return data;" in _SCHEMA_LOAD_TS  # falls through to raw schema
