"""Assembly's job is to add only what every generated app shares — and to
leave behind the repairs that existed for a pipeline that produced defects."""
from __future__ import annotations

import json

import pytest

from services.blueprint import assembly


def test_the_scaffold_is_layered_base_then_overlay():
    """`app-foundation` is the runtime; `standalone-app` adapts it.

    Copying only the overlay is what left the catch-all route importing
    `@/lib/schema-page` from a layer that was never copied — the app installed
    cleanly and then 500'd on every route.
    """
    layers = assembly._template_dirs()
    assert [p.name for p in layers] == ["app-foundation", "standalone-app"]
    assert (layers[0] / "src" / "lib" / "schema-page.tsx").is_file()


def test_assembly_never_overwrites_what_the_projections_wrote(tmp_path):
    app = tmp_path / "app"
    (app / "src" / "schemas").mkdir(parents=True)
    marker = app / "src" / "schemas" / "roles.json"
    marker.write_text('{"id":"PAGE-001"}')

    assembly.copy_scaffold(app, project_short_id="t")
    assert marker.read_text() == '{"id":"PAGE-001"}', (
        "the scaffold is the shell; the projections are the application")


def test_the_aliased_loose_libraries_are_copied(tmp_path):
    """`feel-lite` is dropped from the dependency graph on purpose and resolved
    by a webpack alias — so something has to put it on disk, and nothing did."""
    app = tmp_path / "app"
    copied = assembly.copy_loose_libs(app)
    assert copied == ["src/lib/feel-lite"]
    assert (app / "src" / "lib" / "feel-lite" / "index.ts").is_file()


def test_superseded_repairs_are_named_not_silently_dropped():
    """Skipping a repair is an argument someone should be able to check."""
    assert "normalize_component_aliases" in assembly.SUPERSEDED_REPAIRS
    assert "_regenerate_route_registry" in assembly.SUPERSEDED_REPAIRS
    for repair, why in assembly.SUPERSEDED_REPAIRS.items():
        assert why and len(why) > 15, repair


def test_the_alias_repair_would_corrupt_valid_output():
    """`normalize_component_aliases` renames TableSortable -> Table. The planner
    emits TableSortable from the real registry, so running that repair on the
    Blueprint path is not a no-op — it is damage."""
    from services.blueprint.page_planner import load_catalog

    assert "TableSortable" in load_catalog()


def test_deployment_records_state_not_a_guessed_url():
    """§94 tracks whether a preview is running. Assembly must not claim a
    production deployment that has not happened."""
    d = assembly.describe_deployment({"application": {"id": "app"}})
    assert d["preview"]["status"] == "stopped"
    assert d["production"] == {"status": "none"}
    assert "url" not in d["preview"]

    live = assembly.describe_deployment({}, preview_url="http://localhost:3000")
    assert live["preview"] == {"status": "running", "url": "http://localhost:3000"}


def test_runtime_is_read_off_the_app_not_declared(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text(json.dumps({
        "dependencies": {"next": "15.0.0", "typescript": "5.0.0"},
        "engines": {"node": ">=22"},
    }))
    assert assembly.describe_runtime(app) == {
        "framework": "nextjs", "language": "typescript",
        "packageManager": "npm", "nodeVersion": ">=22",
    }


def test_edge_page_placeholders_are_substituted(tmp_path):
    """`{{app_name}}` in a .tsx is a JSX expression, not inert text — it throws
    `ReferenceError: app_name is not defined` on render. The error pages were
    the worst place for it: the app crashed while reporting a crash."""
    app = tmp_path / "app"
    (app / "src" / "app").mkdir(parents=True)
    page = app / "src" / "app" / "error.tsx"
    page.write_text('<Link href="{{home_route}}">{{app_name}}</Link>')

    touched = assembly.interpolate_edge_pages(app, {
        "application": {"name": "Recruitment Tracker"},
        "pages": [{"route": "/sign-in"}, {"route": "/overview"}],
    })
    assert touched == ["src/app/error.tsx"]
    assert page.read_text() == '<Link href="/overview">Recruitment Tracker</Link>'


def test_the_landing_route_skips_auth_pages():
    """"Back to the app" must not point at the login screen."""
    doc = {"pages": [{"route": "/login"}, {"route": "/sign-up"}, {"route": "/roles"}]}
    assert assembly._landing_route(doc) == "/roles"
    assert assembly._landing_route({"navigation": {"landing": "/home"}}) == "/home"


def test_assembly_invalidates_the_build_cache(tmp_path):
    """Re-assembling rewrites the sources Next compiled from, so leaving
    `.next` in place means a fixed file keeps failing exactly as before."""
    app = tmp_path / "app"
    stale = app / ".next" / "cache"
    stale.mkdir(parents=True)
    (stale / "old.js").write_text("stale")

    assembly.assemble({"application": {"name": "T"}}, app, project_short_id="t")
    assert not (app / ".next").exists()


def test_everything_a_projection_writes_is_protected_from_the_scaffold(tmp_path):
    """Assembly runs after projection, so any projected path missing from
    PROJECTED_PATHS gets silently overwritten by the scaffold's own copy.

    That is how the generated middleware was replaced by the hardcoded
    gate-everything one: the file was correct on disk, then assembly restored
    the scaffold's, and an app with public pages had them quietly closed.
    """
    from services.blueprint import projection

    written: set[str] = set()
    doc = {
        "pages": [{"id": "PAGE-001", "route": "/", "name": "Home",
                   "access": "public", "pattern": "entity_list"}],
        "data": {"entities": [], "relationships": []},
        "widgets": [], "workflows": [], "navigation": {}, "patternTemplates": [],
    }
    app = tmp_path / "app"
    for fn in (projection.project_nav_flow, projection.project_design_tokens,
               projection.project_middleware, projection.project_seed,
               projection.project_sensitive_columns,
               projection.project_searchable_columns):
        written.update(fn(doc, app).get("files") or [])

    unprotected = [f for f in written
                   if not any(f.startswith(p) for p in assembly.PROJECTED_PATHS)]
    assert not unprotected, f"scaffold would overwrite: {unprotected}"


# ---------------------------------------------------------------------------
# The build is what makes an assembled tree an application
# ---------------------------------------------------------------------------


def test_a_failing_build_raises_with_the_compiler_message(tmp_path, monkeypatch):
    """The reason must name the module, not just say the node failed."""
    import subprocess

    from services.blueprint import assembly

    def fake_run(cmd, **kw):
        rc = 0 if "install" in cmd else 1
        return subprocess.CompletedProcess(
            cmd, rc, stdout="", stderr="Module not found: Can't resolve '@/db/schema/user'")

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        assembly.verify_build(tmp_path)
        raise AssertionError("expected BuildFailed")
    except assembly.BuildFailed as exc:
        assert "@/db/schema/user" in str(exc)
        assert "npm build failed" in str(exc)


def test_a_failing_install_stops_before_the_build(tmp_path, monkeypatch):
    import subprocess

    from services.blueprint import assembly

    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ENOENT")

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        assembly.verify_build(tmp_path)
    except assembly.BuildFailed:
        pass
    assert len(seen) == 1, "build ran after install failed"


def test_a_passing_build_reports_both_exit_codes(tmp_path, monkeypatch):
    import subprocess

    from services.blueprint import assembly

    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    assert assembly.verify_build(tmp_path) == {"install": 0, "build": 0}


def test_the_runtime_injector_installs_around_projected_files_not_over_them():
    """Two copiers share `src/lib/workflows`, and only one read PROJECTED_PATHS.

    copy_scaffold skipped the directory correctly; inject_runtime rmtree'd it to
    install the engine and took the 13 projected workflow definitions with it.
    Ownership has to be decided once, so the preserved list is handed in.
    """
    import inspect

    from services.blueprint.assembly import PROJECTED_PATHS, inject_runtime_layer

    src = inspect.getsource(inject_runtime_layer)
    assert "preserve=PROJECTED_PATHS" in src
    assert "src/lib/workflows/definitions" in PROJECTED_PATHS


def test_remove_except_keeps_preserved_paths_and_clears_the_rest(tmp_path):
    from services.runtime_injector import _remove_except

    (tmp_path / "src/lib/workflows/definitions").mkdir(parents=True)
    (tmp_path / "src/lib/workflows/definitions/a.json").write_text("{}")
    (tmp_path / "src/lib/workflows/engine.ts").write_text("//")

    _remove_except(tmp_path / "src/lib/workflows", tmp_path,
                   ("src/lib/workflows/definitions",))

    assert (tmp_path / "src/lib/workflows/definitions/a.json").exists()
    assert not (tmp_path / "src/lib/workflows/engine.ts").exists()
