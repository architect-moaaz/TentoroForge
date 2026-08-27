"""Deploy-time normalisation of an app's vendored-package tree + package.json.

Problem this solves
-------------------
The generated app's ``package.json`` and ``vendor/`` directory are written
during code generation. Between then and deploy, two things can go wrong:

1. The ``vendor/@tentoroforge/*`` dirs are missing or empty (an old
   emitter ran, or the workspace's package dists weren't built at
   generation time).
2. The ``package.json`` was authored — by an old template or by an LLM
   agent that copied the ``app-foundation/package.json`` verbatim —
   with monorepo-relative paths like ``file:../../packages/schema``.
   Those paths work on the dev machine but not on Vercel, where only
   the app dir is uploaded. Result: ``Module not found:
   @tentoroforge/engine`` at ``next build`` time.

Fix: on every publish, refresh the vendor tree from the workspace
packages and rewrite the project's ``package.json`` deps so every
``@tentoroforge/*`` / ``@forge/*`` entry points at ``file:./vendor/...``.

The transform is idempotent and additive — it preserves every non-Forge
dep the app author added and only touches the Forge-owned entries. If a
workspace package has no built ``dist/``, we ERROR loudly instead of
silently shipping a broken vendored package.

Called from :mod:`services.deploy.vercel_provider.publish` just before
``build_snapshot``, alongside the existing ``_refresh_platform_files``
step for ``vercel.json``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from services.app_emitter import (
    _VENDOR_FORGE_PACKAGES,
    _VENDOR_PACKAGES,
    _vendor_engine_packages,
)


logger = logging.getLogger(__name__)


# Platform-authoritative config files. The template's copy is the
# source of truth; whatever landed in the project's output_dir at
# generation time (may be older, may have been overwritten by an LLM)
# is overwritten at deploy time. Same pattern as vercel_provider's
# _PLATFORM_REFRESH_FILES for vercel.json — this exists for files that
# are tightly coupled to the vendor tree layout and therefore belong in
# the vendor_refresh scope.
#
# next.config.js: contains the `@tentoroforge/feel-lite` +
# `@forge/patches` webpack aliases required for the vendored renderer's
# compiled dist to resolve. Without these the Vercel build errors with
# "Module not found: @tentoroforge/feel-lite" even after a clean vendor
# refresh.
_TEMPLATE_STANDALONE_DIR = (
    Path(__file__).resolve().parents[2] / "templates" / "standalone-app"
)
# Files copied verbatim from the standalone-app template on every deploy.
# next.config.js: contains the feel-lite / @forge/patches webpack aliases.
# scripts/fix-rsc-manifest.js: post-build hook that backfills missing
# Next.js RSC page manifests for route-group index pages (works around
# vercel/next.js#58272). Chained into the build script below via
# _normalise_scripts.
_STANDALONE_REFRESH_FILES = (
    "next.config.js",
    "scripts/fix-rsc-manifest.js",
)

# The exact build command every deployed app must run so that the
# post-build RSC-manifest fix executes after next build. Older generated
# apps have `"build": "next build"` from an older template; overwrite it
# so the fix script runs on Vercel. Any other build command is left alone
# (an app author may have chained additional steps).
_EXPECTED_BUILD_SCRIPT = "next build && node scripts/fix-rsc-manifest.js"


# Vendored @tentoroforge/editor is dev-only and pulls in heavy editor UI
# code that generated apps must never ship. Remove it from deps.
_STRIP_DEPS = {"@tentoroforge/editor"}


class VendorRefreshError(RuntimeError):
    """Raised when the vendor tree can't be made deploy-ready.

    Callers should treat this as a hard-stop for the publish — a
    deployment with missing vendored dists will fail at Vercel build
    time anyway, and failing before the snapshot upload saves ~15s of
    wasted work + a more informative error message than "Module not
    found: @tentoroforge/engine".
    """


def _rewrite_deps_for_vendor(deps: dict) -> tuple[dict, dict]:
    """Return ``(rewritten_deps, changes)`` — a copy of ``deps`` with every
    ``@tentoroforge/*`` and ``@forge/*`` entry pointing at
    ``file:./vendor/...``, plus a dict describing what changed for
    logging.

    - Vendored packages get ``file:./vendor/{@ns}/{pkg}`` (the deploy
      ships the vendor tree so this resolves at ``npm install`` on
      Vercel).
    - Non-vendored ``@tentoroforge/*`` / ``@forge/*`` entries (e.g.
      ``feel-lite``, ``editor``) are dropped — they're either shipped
      as loose files under ``src/lib/`` or dev-only.
    - Every other dep is left alone.

    Pure function; no I/O.
    """
    out: dict = {}
    changes: dict = {"rewritten": [], "dropped": [], "unchanged_forge": []}

    for name, spec in deps.items():
        if name in _STRIP_DEPS:
            changes["dropped"].append(name)
            continue

        if name.startswith("@tentoroforge/"):
            suffix = name.split("/", 1)[1]
            if suffix in _VENDOR_PACKAGES:
                expected = f"file:./vendor/@tentoroforge/{suffix}"
                if spec != expected:
                    changes["rewritten"].append((name, spec, expected))
                out[name] = expected
            else:
                changes["dropped"].append(name)
            continue

        if name.startswith("@forge/"):
            suffix = name.split("/", 1)[1]
            if suffix in _VENDOR_FORGE_PACKAGES:
                expected = f"file:./vendor/@forge/{suffix}"
                if spec != expected:
                    changes["rewritten"].append((name, spec, expected))
                out[name] = expected
            else:
                changes["dropped"].append(name)
            continue

        out[name] = spec

    # Ensure every REQUIRED vendored package appears in deps — an old
    # template may have omitted @tentoroforge/engine even though the
    # generated app imports it. Adding a missing dep here is safe
    # because we've verified the vendor tree above in the caller.
    for req in _VENDOR_PACKAGES:
        key = f"@tentoroforge/{req}"
        expected = f"file:./vendor/@tentoroforge/{req}"
        if key not in out:
            changes["rewritten"].append((key, "(missing)", expected))
            out[key] = expected
    for req in _VENDOR_FORGE_PACKAGES:
        key = f"@forge/{req}"
        expected = f"file:./vendor/@forge/{req}"
        if key not in out:
            changes["rewritten"].append((key, "(missing)", expected))
            out[key] = expected

    return out, changes


def _verify_vendor_tree(vendor_root: Path) -> list[str]:
    """Return a list of missing/broken vendored package paths.

    A package is considered broken if either:
    - the vendor dir doesn't exist, or
    - it has no ``dist/`` (webpack would fail to resolve the ``main``).

    ``package.json`` alone isn't enough — it's a manifest pointing at
    files that must actually exist.
    """
    missing: list[str] = []
    for pkg in _VENDOR_PACKAGES:
        p = vendor_root / "@tentoroforge" / pkg
        if not p.is_dir():
            missing.append(f"vendor/@tentoroforge/{pkg} (dir missing)")
        elif not (p / "dist").is_dir():
            missing.append(f"vendor/@tentoroforge/{pkg}/dist (no built output)")
    for pkg in _VENDOR_FORGE_PACKAGES:
        p = vendor_root / "@forge" / pkg
        if not p.is_dir():
            missing.append(f"vendor/@forge/{pkg} (dir missing)")
        elif not (p / "dist").is_dir():
            missing.append(f"vendor/@forge/{pkg}/dist (no built output)")
    return missing


_MANIFEST_FIX_SUFFIX = "node scripts/fix-rsc-manifest.js"


def _normalise_scripts(pkg: dict) -> bool:
    """Ensure the ``build`` script chains the RSC-manifest fix after
    ``next build``.

    Handles three shapes:
    1. Vanilla template ``next build`` → rewrite to full chained form.
    2. Custom prelude ending in ``next build`` (e.g.
       ``npx drizzle-kit push && npx tsx src/db/seed.ts && next build``,
       which is what the generated apps ship — migrate + seed + build):
       append the manifest-fix step to the chain, preserving the prelude.
    3. Anything else (fix already appended, or build doesn't end in
       ``next build``): leave alone. This preserves author customisations
       and is idempotent.

    Returns True if a change was made.
    """
    scripts = pkg.get("scripts")
    if not isinstance(scripts, dict):
        return False
    current = scripts.get("build")
    if not isinstance(current, str):
        return False
    stripped = current.rstrip()
    if _MANIFEST_FIX_SUFFIX in stripped:
        return False  # already chained; idempotent
    # Case 1: vanilla vanilla — rewrite whole thing.
    if stripped == "next build":
        scripts["build"] = _EXPECTED_BUILD_SCRIPT
        return True
    # Case 2: custom prelude ending in `next build` (with or without
    # trailing flags). Append the fix step to keep migrate/seed work.
    if stripped.endswith("next build") or stripped.endswith("&& next build"):
        scripts["build"] = stripped + " && " + _MANIFEST_FIX_SUFFIX
        return True
    return False


def _interpolate_placeholders(pkg: dict, project_slug: str | None) -> bool:
    """Replace legacy template placeholders (``__APP_SLUG__``) in ``name``.

    Returns True if a change was made. This catches package.json files
    that were copied from a template but never had their placeholders
    filled — npm doesn't crash on ``__APP_SLUG__`` as a name but it's a
    clear signal of a broken emission that we should heal at deploy time.
    """
    if not project_slug:
        return False
    name = pkg.get("name") or ""
    if "__APP_SLUG__" in name:
        pkg["name"] = name.replace("__APP_SLUG__", project_slug)
        return True
    return False


def refresh_vendor_and_deps(
    output_dir: Path | str,
    *,
    project_slug: str | None = None,
) -> None:
    """Re-vendor the Forge packages and normalise the app's package.json
    deps to point at the vendor tree.

    Raises :class:`VendorRefreshError` if a required vendored package
    has no built ``dist/`` — publishing a broken vendor tree just moves
    the failure downstream to Vercel with a worse error message.
    """
    root = Path(output_dir)
    if not root.is_dir():
        raise VendorRefreshError(f"output_dir does not exist: {root}")

    # 1. Re-vendor — overwrites vendor/@tentoroforge/* and vendor/@forge/*
    #    with the current workspace packages' package.json + dist.
    #    Silently no-ops for any workspace package that doesn't exist on
    #    disk (e.g. dev-only checkouts).
    _vendor_engine_packages(root)

    # 1b. Refresh platform-authoritative config from the standalone-app
    #    template. Overwrites whatever's in the project because the
    #    template's copy contains structural aliases (feel-lite, patches)
    #    that must match the vendored layout — an app that shipped an
    #    older next.config.js will lack these and error at Vercel build
    #    with "Module not found: @tentoroforge/feel-lite".
    #    Also strips any conflicting next.config.ts (Next.js picks
    #    ambiguously when both exist).
    for name in _STANDALONE_REFRESH_FILES:
        src = _TEMPLATE_STANDALONE_DIR / name
        if not src.is_file():
            continue
        dst = root / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        # If we just wrote next.config.js, delete a stale next.config.ts
        # that would otherwise be picked ambiguously.
        if name == "next.config.js":
            stale = root / "next.config.ts"
            if stale.exists():
                stale.unlink()

    # 2. Verify — every required vendored package must have a dist/.
    #    Fail loudly if not; a Vercel deploy of a broken vendor tree
    #    burns ~40s and returns a confusing error.
    missing = _verify_vendor_tree(root / "vendor")
    if missing:
        raise VendorRefreshError(
            "vendor tree is incomplete after refresh — the workspace "
            "packages likely need a build (`npm run build` in packages/*). "
            "Missing: " + ", ".join(missing)
        )

    # 3. Normalise package.json deps + interpolate placeholders.
    pkg_path = root / "package.json"
    if not pkg_path.is_file():
        raise VendorRefreshError(f"package.json missing: {pkg_path}")
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))

    original_deps = dict(pkg.get("dependencies") or {})
    rewritten, changes = _rewrite_deps_for_vendor(original_deps)
    name_changed = _interpolate_placeholders(pkg, project_slug)
    scripts_changed = _normalise_scripts(pkg)

    if rewritten != original_deps or name_changed or scripts_changed:
        pkg["dependencies"] = rewritten
        pkg_path.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        for old_name, old_spec, new_spec in changes["rewritten"]:
            logger.info(
                "[vendor-refresh] rewrote %s: %s → %s",
                old_name, old_spec, new_spec,
            )
        for name in changes["dropped"]:
            logger.info("[vendor-refresh] dropped %s (non-vendored)", name)
        if name_changed:
            logger.info("[vendor-refresh] interpolated __APP_SLUG__ → %s", project_slug)
        if scripts_changed:
            logger.info(
                "[vendor-refresh] normalised build script → %s",
                pkg["scripts"]["build"],
            )


__all__ = [
    "VendorRefreshError",
    "refresh_vendor_and_deps",
    "_rewrite_deps_for_vendor",
    "_verify_vendor_tree",
]
