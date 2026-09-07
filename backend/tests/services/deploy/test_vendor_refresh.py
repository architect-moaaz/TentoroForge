"""Tests for the deploy-time vendor + package.json normaliser."""

import json
from pathlib import Path

import pytest

from services.deploy.vendor_refresh import (
    VendorRefreshError,
    _rewrite_deps_for_vendor,
    _verify_vendor_tree,
    refresh_vendor_and_deps,
)


# ---------- _rewrite_deps_for_vendor (pure function) ----------


def test_monorepo_paths_get_rewritten_to_vendor():
    """The exact failure mode from UAT — monorepo-relative paths that
    only resolve on the dev machine, not on Vercel."""
    deps = {
        "@tentoroforge/schema": "file:../../packages/schema",
        "@tentoroforge/renderer": "file:../../packages/renderer",
        "@tentoroforge/library": "file:../../packages/library",
        "next": "^15.1.0",
    }
    out, changes = _rewrite_deps_for_vendor(deps)
    assert out["@tentoroforge/schema"] == "file:./vendor/@tentoroforge/schema"
    assert out["@tentoroforge/renderer"] == "file:./vendor/@tentoroforge/renderer"
    assert out["@tentoroforge/library"] == "file:./vendor/@tentoroforge/library"
    # engine wasn't in the input — should be added since every real app needs it
    assert out["@tentoroforge/engine"] == "file:./vendor/@tentoroforge/engine"
    # non-Forge deps untouched
    assert out["next"] == "^15.1.0"
    # rewrite log contains schema/renderer/library entries (was rewritten) +
    # engine + patches (were missing)
    rewritten_keys = {r[0] for r in changes["rewritten"]}
    assert "@tentoroforge/schema" in rewritten_keys
    assert "@tentoroforge/engine" in rewritten_keys
    assert "@forge/patches" in rewritten_keys


def test_editor_is_dropped():
    """@tentoroforge/editor is dev-only and must not ship."""
    deps = {
        "@tentoroforge/editor": "file:../../packages/editor",
        "next": "^15.1.0",
    }
    out, changes = _rewrite_deps_for_vendor(deps)
    assert "@tentoroforge/editor" not in out
    assert "@tentoroforge/editor" in changes["dropped"]


def test_non_vendored_forge_deps_dropped():
    """@tentoroforge/feel-lite is not vendored (shipped as loose files under
    src/lib/)."""
    deps = {
        "@tentoroforge/feel-lite": "file:../../packages/feel-lite",
        "@tentoroforge/some-experimental": "*",
    }
    out, changes = _rewrite_deps_for_vendor(deps)
    assert "@tentoroforge/feel-lite" not in out
    assert "@tentoroforge/some-experimental" not in out
    assert set(changes["dropped"]) >= {"@tentoroforge/feel-lite", "@tentoroforge/some-experimental"}


def test_correctly_specified_deps_left_unchanged():
    """If package.json already uses file:./vendor/... it's a no-op."""
    deps = {
        "@tentoroforge/engine":   "file:./vendor/@tentoroforge/engine",
        "@tentoroforge/library":  "file:./vendor/@tentoroforge/library",
        "@tentoroforge/renderer": "file:./vendor/@tentoroforge/renderer",
        "@tentoroforge/schema":   "file:./vendor/@tentoroforge/schema",
        "@forge/patches":         "file:./vendor/@forge/patches",
        "react": "^19.0.0",
    }
    out, changes = _rewrite_deps_for_vendor(deps)
    assert out == deps  # unchanged
    assert changes["rewritten"] == []  # nothing rewritten


def test_forge_patches_backfilled_when_missing():
    deps = {"react": "^19.0.0"}
    out, _ = _rewrite_deps_for_vendor(deps)
    assert out["@forge/patches"] == "file:./vendor/@forge/patches"


def test_workspace_star_shape_still_normalised():
    """Old dev shape `workspace:*` or `*` also gets pinned to vendor."""
    deps = {"@tentoroforge/schema": "workspace:*"}
    out, _ = _rewrite_deps_for_vendor(deps)
    assert out["@tentoroforge/schema"] == "file:./vendor/@tentoroforge/schema"


# ---------- _verify_vendor_tree ----------


def _make_vendored(root: Path, ns: str, pkg: str, *, with_dist: bool = True) -> None:
    p = root / ns / pkg
    p.mkdir(parents=True, exist_ok=True)
    (p / "package.json").write_text('{"name":"' + f"{ns}/{pkg}" + '","main":"dist/index.js"}', encoding="utf-8")
    if with_dist:
        (p / "dist").mkdir(exist_ok=True)
        (p / "dist" / "index.js").write_text("module.exports = {};\n", encoding="utf-8")


def test_verify_returns_empty_when_all_present(tmp_path):
    for pkg in ("engine", "library", "renderer", "schema"):
        _make_vendored(tmp_path, "@tentoroforge", pkg)
    _make_vendored(tmp_path, "@forge", "patches")
    assert _verify_vendor_tree(tmp_path) == []


def test_verify_flags_missing_dir(tmp_path):
    _make_vendored(tmp_path, "@tentoroforge", "engine")
    # library / renderer / schema / patches all missing
    missing = _verify_vendor_tree(tmp_path)
    assert any("library" in m for m in missing)
    assert any("renderer" in m for m in missing)
    assert any("schema" in m for m in missing)
    assert any("patches" in m for m in missing)
    assert not any("engine" in m for m in missing)


def test_verify_flags_missing_dist(tmp_path):
    _make_vendored(tmp_path, "@tentoroforge", "engine", with_dist=False)
    for pkg in ("library", "renderer", "schema"):
        _make_vendored(tmp_path, "@tentoroforge", pkg)
    _make_vendored(tmp_path, "@forge", "patches")
    missing = _verify_vendor_tree(tmp_path)
    assert len(missing) == 1
    assert "engine" in missing[0]
    assert "dist" in missing[0]


# ---------- refresh_vendor_and_deps (full flow) ----------


@pytest.fixture
def broken_project(tmp_path, monkeypatch):
    """A project dir whose package.json looks like the failing UAT app +
    has an empty vendor tree. Mirrors the exact 4v35xahc failure mode."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "__APP_SLUG__",
        "dependencies": {
            "@tentoroforge/schema":   "file:../../packages/schema",
            "@tentoroforge/renderer": "file:../../packages/renderer",
            "@tentoroforge/library":  "file:../../packages/library",
            "@tentoroforge/editor":   "file:../../packages/editor",
            "next": "^15.1.0",
        },
    }), encoding="utf-8")

    # Stub _vendor_engine_packages so we don't actually shell out to build
    # the workspace packages during the test. Populate the vendor tree
    # inline instead.
    def fake_vendor(root: Path) -> None:
        vroot = root / "vendor"
        for pkg in ("engine", "library", "renderer", "schema"):
            _make_vendored(vroot, "@tentoroforge", pkg)
        _make_vendored(vroot, "@forge", "patches")
    monkeypatch.setattr(
        "services.deploy.vendor_refresh._vendor_engine_packages", fake_vendor,
    )
    return tmp_path


def test_refresh_fixes_broken_project(broken_project):
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    pkg = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    # deps rewritten to vendor paths
    assert pkg["dependencies"]["@tentoroforge/schema"] == "file:./vendor/@tentoroforge/schema"
    assert pkg["dependencies"]["@tentoroforge/renderer"] == "file:./vendor/@tentoroforge/renderer"
    assert pkg["dependencies"]["@tentoroforge/library"] == "file:./vendor/@tentoroforge/library"
    # engine backfilled
    assert pkg["dependencies"]["@tentoroforge/engine"] == "file:./vendor/@tentoroforge/engine"
    # editor dropped
    assert "@tentoroforge/editor" not in pkg["dependencies"]
    # non-Forge deps kept
    assert pkg["dependencies"]["next"] == "^15.1.0"
    # __APP_SLUG__ interpolated
    assert pkg["name"] == "test-app"


def test_refresh_raises_when_dist_missing(tmp_path, monkeypatch):
    """Loud failure when the workspace packages haven't been built."""
    (tmp_path / "package.json").write_text('{"name":"x","dependencies":{}}', encoding="utf-8")

    def bad_vendor(root: Path) -> None:
        # Populate dirs but no dist
        vroot = root / "vendor"
        for pkg in ("engine", "library", "renderer", "schema"):
            _make_vendored(vroot, "@tentoroforge", pkg, with_dist=False)
    monkeypatch.setattr(
        "services.deploy.vendor_refresh._vendor_engine_packages", bad_vendor,
    )

    with pytest.raises(VendorRefreshError, match="vendor tree is incomplete"):
        refresh_vendor_and_deps(tmp_path)


def test_refresh_raises_when_output_dir_missing(tmp_path):
    with pytest.raises(VendorRefreshError, match="output_dir does not exist"):
        refresh_vendor_and_deps(tmp_path / "nonexistent")


def test_refresh_raises_when_package_json_missing(tmp_path, monkeypatch):
    def fake_vendor(root: Path) -> None:
        vroot = root / "vendor"
        for pkg in ("engine", "library", "renderer", "schema"):
            _make_vendored(vroot, "@tentoroforge", pkg)
        _make_vendored(vroot, "@forge", "patches")
    monkeypatch.setattr(
        "services.deploy.vendor_refresh._vendor_engine_packages", fake_vendor,
    )
    with pytest.raises(VendorRefreshError, match="package.json missing"):
        refresh_vendor_and_deps(tmp_path)


def test_refresh_is_idempotent(broken_project):
    """Running twice must not toggle state or reintroduce dropped deps."""
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    first = (broken_project / "package.json").read_text(encoding="utf-8")
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    second = (broken_project / "package.json").read_text(encoding="utf-8")
    assert first == second


def test_refresh_overwrites_stale_next_config_with_feel_lite_alias(broken_project):
    """The Vercel build errored with "Module not found: @tentoroforge/feel-lite"
    because the app's next.config.js lacked the alias. Refresh must overwrite
    it with the template version (which includes the alias)."""
    # Simulate a broken next.config from the failed UAT app.
    (broken_project / "next.config.js").write_text(
        "module.exports = { reactStrictMode: true };\n"
    )
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    text = (broken_project / "next.config.js").read_text(encoding="utf-8")
    assert "@tentoroforge/feel-lite" in text
    assert "./src/lib/feel-lite" in text
    assert "@forge/patches" in text


def test_refresh_deletes_stale_next_config_ts(broken_project):
    """If both next.config.js and next.config.ts exist, Next.js picks
    ambiguously. Kill the .ts so the .js we ship wins."""
    (broken_project / "next.config.ts").write_text(
        "export default { reactStrictMode: true };\n"
    )
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    assert not (broken_project / "next.config.ts").exists()
    assert (broken_project / "next.config.js").exists()


def test_refresh_copies_fix_rsc_manifest_script(broken_project):
    """The RSC-manifest fix script must land at scripts/fix-rsc-manifest.js
    so `next build && node scripts/fix-rsc-manifest.js` can find it on
    Vercel. Works around vercel/next.js#58272 (missing
    page_client-reference-manifest.js for route-group index pages)."""
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    script = broken_project / "scripts" / "fix-rsc-manifest.js"
    assert script.is_file()
    body = script.read_text(encoding="utf-8")
    assert "page_client-reference-manifest.js" in body
    assert ".next/server/app" in body or ".next\", \"server\", \"app\"" in body


def test_refresh_normalises_build_script_to_chain_manifest_fix(broken_project):
    """Old apps have `\"build\": \"next build\"`. Refresh must chain
    the manifest-fix script so it actually runs on Vercel."""
    # Broken-project fixture writes a package.json with default scripts;
    # ensure the vanilla "next build" is present so we're actually
    # testing the rewrite.
    pkg = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    pkg["scripts"] = {"build": "next build", "dev": "next dev"}
    (broken_project / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    out = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    assert out["scripts"]["build"] == "next build && node scripts/fix-rsc-manifest.js"
    # Unrelated scripts untouched.
    assert out["scripts"]["dev"] == "next dev"


def test_refresh_appends_fix_to_custom_build_chain(broken_project):
    """The generated apps ship a custom build chain
    (migrate + seed + next build). The RSC-manifest fix must be
    appended to the chain, not skipped — otherwise Vercel still errors
    with ENOENT on page_client-reference-manifest.js."""
    pkg = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    pkg["scripts"] = {
        "build": (
            "npx drizzle-kit push --config=drizzle.config.ts --force --verbose"
            " && npx tsx src/db/seed.ts && next build"
        )
    }
    (broken_project / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    out = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    assert out["scripts"]["build"] == (
        "npx drizzle-kit push --config=drizzle.config.ts --force --verbose"
        " && npx tsx src/db/seed.ts && next build"
        " && node scripts/fix-rsc-manifest.js"
    )


def test_refresh_leaves_unrelated_custom_build_alone(broken_project):
    """A build that doesn't end in `next build` (e.g. author replaced
    it with a custom bundler) is left untouched — the fix only makes
    sense chained after next build."""
    pkg = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    pkg["scripts"] = {"build": "npm run bundle && npm run static"}
    (broken_project / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    out = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    assert out["scripts"]["build"] == "npm run bundle && npm run static"


def test_refresh_leaves_already_chained_build_alone(broken_project):
    """Idempotent: if the build already chains the manifest fix, don't
    double-append."""
    pkg = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    pkg["scripts"] = {"build": "next build && node scripts/fix-rsc-manifest.js"}
    (broken_project / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    out = json.loads((broken_project / "package.json").read_text(encoding="utf-8"))
    assert out["scripts"]["build"] == "next build && node scripts/fix-rsc-manifest.js"


def test_refreshed_next_config_ignores_ts_and_eslint_errors(broken_project):
    """Generated apps have LLM-authored TS/ESLint quirks that shouldn't
    block the Vercel build. Regression guard for the api/tasks/route.ts
    `.rows` failure on UAT."""
    refresh_vendor_and_deps(broken_project, project_slug="test-app")
    text = (broken_project / "next.config.js").read_text(encoding="utf-8")
    assert "ignoreBuildErrors: true" in text
    assert "ignoreDuringBuilds: true" in text
