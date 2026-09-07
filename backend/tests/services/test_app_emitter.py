"""Tests for the standalone-app emitter."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from services.app_emitter import emit_standalone_app


_EXPECTED_FILES = [
    "package.json",
    "next.config.js",
    "tsconfig.json",
    "tailwind.config.ts",
    "postcss.config.js",
    ".gitignore",
    "src/app/layout.tsx",
    "src/app/[...slug]/page.tsx",
    "src/app/not-found.tsx",
]
# NOTE: src/app/page.tsx (the root redirect) is GENERATED, not a static template,
# and is intentionally OMITTED when there is no safe non-root landing (an empty
# app resolves to "/", which the (dashboard) route group already serves — a
# page.tsx redirecting to "/" would self-loop). Its content is covered by
# test_root_page_* below + test_root_redirect.py.


def test_emit_writes_all_template_files():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="proj-1")
        for rel in _EXPECTED_FILES:
            assert (Path(td) / rel).exists(), f"missing {rel}"


def test_root_page_redirects_to_safe_static_landing():
    """page.tsx must redirect to a real STATIC route (/dashboard), never a
    dynamic route like /invite/[token] (the shipped 404 bug)."""
    with tempfile.TemporaryDirectory() as td:
        contracts = Path(td) / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({
            "initialPage": "login",
            "pages": [
                {"id": "login", "route": "/login", "shell": True},
                {"id": "invite", "route": "/invite/[token]", "shell": True},
                {"id": "dashboard", "route": "/dashboard", "shell": True},
            ],
        }), encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        page = (Path(td) / "src" / "app" / "page.tsx").read_text(encoding="utf-8")
        assert 'DEFAULT_INITIAL = "/dashboard"' in page
        # the landing assignment is never a dynamic route
        assert 'DEFAULT_INITIAL = "/invite/[token]"' not in page
        assert '"[' not in page.split("DEFAULT_INITIAL")[1].split(";")[0]


def test_root_page_omitted_when_landing_is_root():
    """No safe non-root landing → page.tsx is unlinked so the (dashboard) group
    serves "/" (no self-loop)."""
    with tempfile.TemporaryDirectory() as td:
        contracts = Path(td) / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({
            "initialPage": "login",
            "pages": [{"id": "login", "route": "/login", "shell": True}],
        }), encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        assert not (Path(td) / "src" / "app" / "page.tsx").exists()


def test_emit_interpolates_project_short_id():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="my-app-xyz")
        pkg = json.loads((Path(td) / "package.json").read_text(encoding="utf-8"))
        assert pkg["name"] == "my-app-xyz"


def test_top_level_package_json_uses_file_paths():
    """The top-level package.json points at vendor/@tentoroforge/<pkg> via file:."""
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        top = json.loads((Path(td) / "package.json").read_text(encoding="utf-8"))
        deps = top.get("dependencies") or {}
        assert deps["@tentoroforge/engine"] == "file:./vendor/@tentoroforge/engine"
        assert deps["@tentoroforge/library"] == "file:./vendor/@tentoroforge/library"
        assert deps["@tentoroforge/renderer"] == "file:./vendor/@tentoroforge/renderer"
        assert deps["@tentoroforge/schema"] == "file:./vendor/@tentoroforge/schema"


def test_emit_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        first = (Path(td) / "package.json").read_text(encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        second = (Path(td) / "package.json").read_text(encoding="utf-8")
        assert first == second


def test_emit_preserves_existing_schemas():
    with tempfile.TemporaryDirectory() as td:
        schemas = Path(td) / "src" / "schemas"
        schemas.mkdir(parents=True)
        (schemas / "home.json").write_text('{"x":1}', encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        assert (schemas / "home.json").read_text(encoding="utf-8") == '{"x":1}'


def test_emit_preserves_existing_globals_css():
    # A realistic generated globals.css already carries @tailwind directives —
    # that's what the design agent emits and what ensure_tailwind_directives
    # backfills when absent. The invariant this test guards is "emit doesn't
    # clobber the user's globals.css", not "emit never touches it at all"
    # (the tailwind-backfill is a legitimate no-op safety net for LLM output
    # variance — see theme_tokens.ensure_tailwind_directives).
    original = (
        "@tailwind base;\n"
        "@tailwind components;\n"
        "@tailwind utilities;\n"
        "\n/* project css */\n"
    )
    with tempfile.TemporaryDirectory() as td:
        appdir = Path(td) / "src" / "app"
        appdir.mkdir(parents=True)
        (appdir / "globals.css").write_text(original, encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        assert (appdir / "globals.css").read_text(encoding="utf-8") == original


def test_emit_preserves_design_spec_json():
    with tempfile.TemporaryDirectory() as td:
        contracts = Path(td) / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "design-spec.json").write_text('{"register":"linear"}', encoding="utf-8")
        emit_standalone_app(output_dir=td, project_short_id="x")
        assert (contracts / "design-spec.json").read_text(encoding="utf-8") == '{"register":"linear"}'


def test_emit_vendors_engine_packages():
    """Engine + library + renderer + schema package.json + dist appear under vendor/."""
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        for pkg in ("engine", "library", "renderer", "schema"):
            vendor_pkg = Path(td) / "vendor" / "@tentoroforge" / pkg
            assert (vendor_pkg / "package.json").exists(), f"{pkg} package.json missing"
            assert (vendor_pkg / "dist").exists(), f"{pkg} dist missing"


def test_vendored_package_json_uses_file_paths_for_workspace_deps():
    """Inside vendor/<pkg>/package.json, @tentoroforge/* deps become file:../<other>."""
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        engine_pkg = json.loads(
            (Path(td) / "vendor" / "@tentoroforge" / "engine" / "package.json").read_text(encoding="utf-8")
        )
        deps = engine_pkg.get("dependencies") or {}
        for k, v in deps.items():
            if k.startswith("@tentoroforge/"):
                assert v.startswith("file:../"), f"{k} = {v} (expected file:../)"


def test_vendored_package_json_drops_unresolvable_private_deps():
    """No vendored package.json keeps a dep that npm-install can't resolve.

    Rules:
      - ``@tentoroforge/<vendored>`` → sibling ``file:../<name>`` (kept)
      - ``@tentoroforge/<other>``    → dropped (unpublished)
      - ``@forge/<vendored>``        → sibling ``file:../../@forge/<name>`` (kept)
      - ``@forge/<other>``           → dropped (unpublished)
    """
    _vendored_tt = ("engine", "library", "renderer", "schema")
    _vendored_forge = ("patches",)
    with tempfile.TemporaryDirectory() as td:
        emit_standalone_app(output_dir=td, project_short_id="x")
        for pkg in _vendored_tt:
            content = json.loads(
                (Path(td) / "vendor" / "@tentoroforge" / pkg / "package.json").read_text(encoding="utf-8")
            )
            deps = content.get("dependencies") or {}
            for k, v in deps.items():
                if k.startswith("@forge/"):
                    suffix = k.split("/", 1)[1]
                    assert suffix in _vendored_forge, (
                        f"{pkg}: leaked private @forge dep {k}"
                    )
                    assert v == f"file:../../@forge/{suffix}", (
                        f"{pkg}: {k} not rewritten to sibling path"
                    )
                elif k.startswith("@tentoroforge/"):
                    suffix = k.split("/", 1)[1]
                    assert suffix in _vendored_tt, (
                        f"{pkg}: non-vendored @tentoroforge dep {k}"
                    )
                    assert v == f"file:../{suffix}", (
                        f"{pkg}: {k} not rewritten to sibling path"
                    )
