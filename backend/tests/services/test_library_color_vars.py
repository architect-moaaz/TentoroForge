"""The library components read var(--color-primary-500) etc. for chart series/axes and
status colors. The design agent only emits shadcn --primary vars, so without the --color-*
scale the charts render BLACK. runtime_injector emits the scale from the design palette."""
import json
from pathlib import Path
from services.runtime_injector import _emit_library_color_vars, _color_scale


def test_color_scale_shape():
    sc = _color_scale("#2A9D8F")
    assert sc["500"] == "#2A9D8F"
    assert sc["100"] != sc["500"] and sc["800"] != sc["500"]  # tints differ


def _app(tmp_path, primary="#2A9D8F"):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "globals.css").write_text(":root { --primary: 0 0% 0%; }\n", encoding="utf-8")
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "design-spec.json").write_text(
        json.dumps({"colorPalette": {"primary": primary, "accent": "#E9C46A", "border": "#D8ECEA"}}), encoding="utf-8")
    return tmp_path


def test_emits_color_vars_from_palette(tmp_path):
    assert _emit_library_color_vars(_app(tmp_path)) is True
    css = (tmp_path / "src" / "app" / "globals.css").read_text(encoding="utf-8")
    assert "--color-primary-500: #2A9D8F;" in css
    assert "--color-accent-500: #E9C46A;" in css
    assert "--color-text-tertiary:" in css and "--color-border-default:" in css


def test_idempotent(tmp_path):
    app = _app(tmp_path)
    _emit_library_color_vars(app)
    assert _emit_library_color_vars(app) is False  # already present


def test_falls_back_without_design_spec(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "globals.css").write_text(":root {}\n", encoding="utf-8")
    assert _emit_library_color_vars(tmp_path) is True  # uses defaults
    assert "--color-primary-500:" in (tmp_path / "src" / "app" / "globals.css").read_text(encoding="utf-8")
