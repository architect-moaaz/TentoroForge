"""Login/signup pages are hand-written Tailwind; they render UNSTYLED (distorted)
if globals.css is missing the `@tailwind base/components/utilities` directives. The
design LLM is instructed to write them but sometimes omits them (variance), which
disables the entire utility layer. This deterministic guard guarantees they exist.
"""
from pathlib import Path

from services.theme_tokens import ensure_tailwind_directives


def _write(tmp_path: Path, css: str) -> Path:
    p = tmp_path / "src" / "app" / "globals.css"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(css)
    return p


def test_inserts_directives_when_missing(tmp_path):
    css = "@import url('https://fonts.googleapis.com/x');\n\n:root { --primary: 173 79% 26%; }\n"
    p = _write(tmp_path, css)
    info = ensure_tailwind_directives(tmp_path)
    out = p.read_text()
    assert out.count("@tailwind base;") == 1
    assert "@tailwind components;" in out and "@tailwind utilities;" in out
    assert info["inserted"] is True
    # directives must come AFTER the @import (CSS requires @import first) and
    # BEFORE :root.
    assert out.index("@import") < out.index("@tailwind base;") < out.index(":root")


def test_noop_when_already_present(tmp_path):
    css = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n:root { --primary: 1 2% 3%; }\n"
    p = _write(tmp_path, css)
    info = ensure_tailwind_directives(tmp_path)
    assert info["inserted"] is False
    assert p.read_text().count("@tailwind base;") == 1  # not duplicated


def test_handles_no_import_line(tmp_path):
    css = ":root { --primary: 1 2% 3%; }\n"
    p = _write(tmp_path, css)
    ensure_tailwind_directives(tmp_path)
    out = p.read_text()
    assert out.startswith("@tailwind base;")
    assert out.index("@tailwind base;") < out.index(":root")


def test_missing_globals_is_safe(tmp_path):
    info = ensure_tailwind_directives(tmp_path)
    assert info["inserted"] is False
