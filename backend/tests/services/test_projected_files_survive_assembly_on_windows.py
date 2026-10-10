"""Projected files survive assembly on Windows.

`PROJECTED_PATHS` is written with forward slashes. Two comparisons against it used `str(path)`,
which on Windows is `src\\middleware.ts`, so neither ever matched:

* `copy_scaffold` overwrote the projected `src/middleware.ts` with the scaffold's hard-coded gate —
  every page then bounced to /login while a valid session sat in the browser;
* `_remove_except` (the runtime injection's "clear this directory but keep what is projected")
  preserved nothing, so `src/lib/workflows/definitions` — the workflows the build had just written —
  was deleted, and an application whose ratings and comments are written by workflows shipped with none.

Run against the real filesystem on whatever platform the suite runs on; the pure check uses
`PureWindowsPath` so the Windows spelling is exercised on POSIX too.
"""
from __future__ import annotations

from pathlib import PureWindowsPath

from services.blueprint.assembly import (
    PROJECTED_PATHS,
    RETIRED_SCAFFOLD_FILES,
    SCAFFOLD_DEFAULTS,
    SCAFFOLD_OWNED,
    _template_dirs,
    copy_scaffold,
)
from services.runtime_injector import _remove_except


def test_the_posix_spelling_of_a_windows_path_matches_the_list():
    rel = PureWindowsPath("src") / "middleware.ts"
    assert str(rel) == "src\\middleware.ts", "the shape that broke the comparison"
    assert not any(str(rel).startswith(p) for p in PROJECTED_PATHS)
    assert any(rel.as_posix().startswith(p) for p in PROJECTED_PATHS), "and its posix form is protected"


def test_the_scaffold_does_not_overwrite_a_projected_middleware(tmp_path):
    app = tmp_path / "app"
    (app / "src").mkdir(parents=True)
    projected = "// the projected gate: cookies: sessionCookies()\n"
    (app / "src" / "middleware.ts").write_text(projected, encoding="utf-8")

    copy_scaffold(app, project_short_id="t")

    assert (app / "src" / "middleware.ts").read_text(encoding="utf-8") == projected
    assert (app / "src" / "auth.ts").is_file(), "the scaffold still lands everything it owns"


def test_the_scaffold_leaves_every_projected_file_it_also_ships(tmp_path):
    """Whatever the scaffold ships under a projected path, a projected file already there wins."""
    app = tmp_path / "app"
    shipped = set()
    for layer in _template_dirs():
        for src in layer.rglob("*"):
            if src.is_file():
                rel = src.relative_to(layer)
                rel = rel.with_suffix("") if rel.suffix == ".tmpl" else rel
                key = rel.as_posix()
                # A RETIRED file is removed on purpose on every platform (the scaffold's
                # landing page cannot sit beside the catch-all); that is not clobbering.
                if (any(key.startswith(p) for p in PROJECTED_PATHS)
                        and key not in SCAFFOLD_OWNED and key not in SCAFFOLD_DEFAULTS
                        and key not in RETIRED_SCAFFOLD_FILES):
                    shipped.add(key)
    assert "src/middleware.ts" in shipped, "the guard is looking at the right set"

    for key in shipped:
        dst = app / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("PROJECTED", encoding="utf-8")

    copy_scaffold(app, project_short_id="t")

    clobbered = sorted(k for k in shipped if (app / k).read_text(encoding="utf-8") != "PROJECTED")
    assert clobbered == [], f"the scaffold overwrote projected files: {clobbered}"


def test_a_projected_default_is_still_filled_when_the_projection_did_not_run(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    copy_scaffold(app, project_short_id="t")
    assert (app / "src" / "lib" / "account.ts").is_file(), "SCAFFOLD_DEFAULTS still fill a hole"


def test_runtime_injection_keeps_the_workflow_definitions_it_was_told_to_keep(tmp_path):
    root = tmp_path / "app"
    wf = root / "src" / "lib" / "workflows"
    (wf / "definitions").mkdir(parents=True)
    (wf / "definitions" / "post-comment.json").write_text("{}", encoding="utf-8")
    (wf / "definitions" / "nested").mkdir()
    (wf / "definitions" / "nested" / "x.json").write_text("{}", encoding="utf-8")
    (wf / "engine.ts").write_text("old engine", encoding="utf-8")
    (wf / "stale.ts").write_text("gone", encoding="utf-8")

    _remove_except(wf, root, ("src/lib/workflows/definitions",))

    assert (wf / "definitions" / "post-comment.json").is_file()
    assert (wf / "definitions" / "nested" / "x.json").is_file()
    assert not (wf / "engine.ts").exists() and not (wf / "stale.ts").exists(), "everything else is cleared"


def test_copy_scaffold_reports_posix_paths(tmp_path):
    written = copy_scaffold(tmp_path / "app", project_short_id="t")
    assert written and not any("\\" in w for w in written)
