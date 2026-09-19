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


def test_assembly_invalidates_the_build_cache_but_not_the_served_app(tmp_path):
    """Re-assembling rewrites the sources Next compiled from, so the compiler
    cache under `.next/cache` and the verification build's output go stale
    and are cleared. The rest of `.next` is what a running dev server serves
    from — removing it whole answered every request with "Internal Server
    Error" (`routes-manifest.json` missing) after each rebuild."""
    app = tmp_path / "app"
    stale = app / ".next" / "cache"
    stale.mkdir(parents=True)
    (stale / "old.js").write_text("stale")
    (app / ".next" / "routes-manifest.json").write_text("{}")
    verify = app / assembly.VERIFY_DIST_DIR
    verify.mkdir()
    (verify / "old.js").write_text("stale")

    assembly.assemble({"application": {"name": "T"}}, app, project_short_id="t")
    assert not stale.exists()
    assert not verify.exists()
    assert (app / ".next" / "routes-manifest.json").exists()


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
               projection.project_searchable_columns,
               projection.project_embedding_columns):
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
    # No dispatch manifest in an empty tree: the dry run reports zero checked.
    assert assembly.verify_build(tmp_path) == {"install": 0, "build": 0, "dispatches": 0}


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


def test_assembly_refuses_placeholders_that_survived_into_jsx(tmp_path):
    """`{{app_name}}` in JSX text is an object literal, not inert text — it
    compiles, passes both gates, and throws ReferenceError at prerender. The
    guard that recognises it reported for a year; the assembly now REFUSES
    over it, naming the file and the token, and still writes the report first
    so "found nothing" and "never ran" stay distinguishable.
    """
    app = tmp_path / "app"
    doc = {"application": {"name": "T"}}

    clean = assembly.assemble(doc, app, project_short_id="t")
    assert clean["residualPlaceholders"] == []
    assert (app / "contracts" / "placeholder-report.json").is_file()

    planted = app / "src" / "app" / "planted.tsx"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(
        "export default function P() {\n"
        "  return <div style={{ height }}>Return to {{app_name}}</div>;\n"
        "}\n",
        encoding="utf-8",
    )

    try:
        assembly.assemble(doc, app, project_short_id="t")
    except assembly.BuildFailed as e:
        assert "src/app/planted.tsx:{{app_name}}" in str(e)
    else:
        raise AssertionError("a shipped placeholder must refuse the assembly")
    report = json.loads((app / "contracts" / "placeholder-report.json").read_text())
    assert [h["token"] for h in report["findings"]] == ["app_name"]
    assert report["findings"][0]["file"] == "src/app/planted.tsx"

def test_assembly_substitutes_the_interface_language(tmp_path):
    """§11 — an Arabic Blueprint has to reach <html lang/dir>. layout.tsx is a
    plain .tsx, so the .tmpl copy step never reads it and the placeholder
    would ship literally."""
    app = tmp_path / "app"
    assembly.assemble({"application": {"name": "T"},
                       "product": {"locale": "ar"}}, app, project_short_id="t")
    layout = (app / "src" / "app" / "layout.tsx").read_text()
    assert '<html lang="ar" dir="rtl"' in layout
    assert "__APP_" not in layout

    other = tmp_path / "other"
    assembly.assemble({"application": {"name": "T"}}, other, project_short_id="t")
    assert '<html lang="en" dir="ltr"' in (
        other / "src" / "app" / "layout.tsx").read_text()


def test_the_install_and_the_build_can_run_apart(tmp_path, monkeypatch):
    """`install` runs at second zero of a build and `preview` compiles at the
    end of it; each issues only its own command."""
    import subprocess

    from services.blueprint import assembly

    seen: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert assembly.install_dependencies(tmp_path) == 0
    assert [c[:2] for c in seen] == [["npm", "install"]]
    seen.clear()
    assembly.verify_build(tmp_path, install=False)
    assert [c[:3] for c in seen] == [["npm", "run", "build"]]


def test_the_scaffold_is_filled_the_moment_it_is_laid_down(tmp_path):
    """The install node copies the scaffold at second zero; only the preview
    node's assemble used to fill its placeholders. A run that failed between
    the two (a refused page) left the app introducing itself as __APP_NAME__
    on its sign-in page and throwing `app_name is not defined` from its 404
    page. Laying the scaffold down now fills it in the same step."""
    app = tmp_path / "app"
    assembly.copy_scaffold(app, project_short_id="t1")
    doc = {"application": {"id": "t1", "name": "Recruitment Tracker", "domain": "hr"},
           "pages": [{"route": "/login"}, {"route": "/overview"}]}
    touched = assembly.interpolate_scaffold(app, doc)
    assert "__APP_NAME__" in touched and "src/app/not-found.tsx" in touched

    left = {}
    for f in (app / "src").rglob("*.tsx"):
        text = f.read_text("utf-8")
        hits = [t for t in ("__APP_NAME__", "{{app_name}}", "{{home_route}}",
                            "__AUTH_HEADLINE__", "__AUTH_SUBHEAD__") if t in text]
        if hits:
            left[str(f.relative_to(app))] = hits
    assert left == {}, left
    assert 'Return to Recruitment Tracker' in (app / "src/app/not-found.tsx").read_text()
    assert assembly.interpolate_scaffold(app, doc) == []      # idempotent


def test_prepare_app_root_fills_the_scaffold_when_given_the_blueprint(tmp_path, monkeypatch):
    monkeypatch.setattr(assembly, "vendor_engines", lambda out: [])
    app = tmp_path / "app"
    doc = {"application": {"id": "t2", "name": "Ledger", "domain": "finance"},
           "pages": [{"route": "/login"}, {"route": "/accounts"}]}
    assembly.prepare_app_root(app, project_short_id="t2", doc=doc)
    assert "__APP_NAME__" not in (app / "src/app/login/page.tsx").read_text()
    assert "{{app_name}}" not in (app / "src/app/not-found.tsx").read_text()


# --- the shipped-file contract and the dispatch dry run --------------------

def test_the_token_contract_is_read_off_the_templates():
    tokens = assembly.scaffold_tokens()
    assert {"__APP_NAME__", "{{app_name}}", "{{home_route}}", "__AUTH_HEADLINE__"} <= tokens
    assert all(t.startswith("__") or t.startswith("{{") for t in tokens)


def test_a_shipped_placeholder_refuses_the_assembly_by_file_and_token(tmp_path):
    app = tmp_path / "app"
    (app / "src" / "app").mkdir(parents=True)
    (app / "src" / "app" / "page.tsx").write_text("<h1>__APP_NAME__</h1>")
    (app / "src" / "app" / "not-found.tsx").write_text("Return to {{app_name}}")
    assert assembly.unfilled_scaffold_tokens(app) == [
        "src/app/not-found.tsx:{{app_name}}", "src/app/page.tsx:__APP_NAME__"]
    try:
        assembly.refuse_unfilled_scaffold(app)
    except assembly.BuildFailed as e:
        assert "src/app/page.tsx:__APP_NAME__" in str(e)
    else:
        raise AssertionError("shipped placeholders must refuse")
    (app / "src" / "app" / "page.tsx").write_text("<h1>Ledger</h1>")
    (app / "src" / "app" / "not-found.tsx").write_text("Return to Ledger")
    assembly.refuse_unfilled_scaffold(app)                       # clean: silent


def test_prepare_app_root_refuses_a_scaffold_it_could_not_fill(tmp_path, monkeypatch):
    monkeypatch.setattr(assembly, "vendor_engines", lambda out: [])
    monkeypatch.setattr(assembly, "interpolate_scaffold", lambda out, doc: [])   # nothing filled
    try:
        assembly.prepare_app_root(tmp_path / "app", project_short_id="t3",
                                  doc={"application": {"id": "t3", "name": "X"}, "pages": []})
    except assembly.BuildFailed as e:
        assert "__APP_NAME__" in str(e)
    else:
        raise AssertionError("an unfilled scaffold must refuse at install")


def test_the_dry_run_is_skipped_without_a_manifest(tmp_path):
    assert assembly.verify_dispatches(tmp_path) == 0


def test_a_wire_that_would_refuse_fails_the_build_naming_the_control(tmp_path, monkeypatch):
    import subprocess
    app = tmp_path / "app"
    (app / "src/lib/workflows").mkdir(parents=True); (app / "src/contracts").mkdir(parents=True)
    (app / assembly.DISPATCH_VERIFIER).write_text("// verifier")
    (app / assembly.DISPATCH_MANIFEST).write_text("{}")
    (app / ".env.local").write_text('DATABASE_URL="postgres://u:p@localhost:5/x"\n')
    seen = {}

    class P:
        returncode = 1
        stderr = ""
        stdout = "noise\n" + json.dumps({"ok": False, "checked": 1, "failed": 1, "results": [
            {"route": "/records/[id]", "control": "Button", "label": "Delete Record", "workflow": "FLOW-D",
             "ok": False, "problems": [{"node": "do", "actionType": "db_delete",
                                        "problem": "WHERE id is empty — trigger form is missing an input"}]}]})

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
        return P()
    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        assembly.verify_dispatches(app)
    except assembly.BuildFailed as e:
        msg = str(e)
        assert "would refuse at first click" in msg
        assert "/records/[id]: Button 'Delete Record' runs FLOW-D" in msg
        assert "WHERE id is empty" in msg
    else:
        raise AssertionError("a refusing wire must fail the build")
    assert seen["cmd"] == ["npx", "tsx", assembly.DISPATCH_VERIFIER]
    assert seen["env"]["DATABASE_URL"] == "postgres://u:p@localhost:5/x"   # the app's own


def test_a_clean_dry_run_reports_what_it_checked(tmp_path, monkeypatch):
    import subprocess
    app = tmp_path / "app"
    (app / "src/lib/workflows").mkdir(parents=True); (app / "src/contracts").mkdir(parents=True)
    (app / assembly.DISPATCH_VERIFIER).write_text("// verifier")
    (app / assembly.DISPATCH_MANIFEST).write_text("{}")

    class P:
        returncode = 0; stderr = ""
        stdout = json.dumps({"ok": True, "checked": 3, "failed": 0, "results": []})
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: P())
    assert assembly.verify_dispatches(app) == 3
