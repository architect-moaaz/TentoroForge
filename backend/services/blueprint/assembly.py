"""Assemble a runnable app around what the projections already wrote.

The projections put the *application* on disk — schema modules, page schemas,
workflow definitions, the route graph, tokens, seed rows. None of that runs on
its own. Assembly adds the parts that are the same in every generated app: the
Next.js scaffold, and the engine packages vendored so ``npm install`` resolves
without a registry.

This deliberately reuses ``app_emitter``'s copy and vendoring and deliberately
does **not** reuse its repair cascade. That cascade — thirteen steps — exists
because the old chain's LLM output needed fixing before it would run:

    reconcile_db_schema_barrel     stale singular shadow schema files
    reconcile_user_fk_types        FK columns that could not hold a session id
    complete_light_theme           undefined --border falling back to currentColor
    ensure_nav_flow                a route graph reconstructed from the schemas
    normalize_component_aliases    "hallucinated component types"
    ensure_crud_pages              an "Add X" button that 404s
    reconcile_singleton_pages      pages navigated to but never emitted
    fix_schema_versions            schemaVersion the renderer did not accept
    _regenerate_route_registry     a registry rebuilt by scanning disk

Every one of those is a defect the Blueprint path cannot produce. The data
projection writes a single authoritative barrel; foreign keys come from declared
relationships with the entity's real key type; tokens come from ``designSystem``;
nav-flow is projected from ``navigation`` rather than inferred; components are
validated against the real registry before anything is written; pages come from
page contracts. Running the repairs anyway would not be harmless — the alias
step rewrites ``TableSortable`` to ``Table``, and ``TableSortable`` is a
registered component the planner emits on purpose.

What is kept is what is boilerplate rather than repair: the scaffold itself, the
vendored engines, a drizzle config in the format drizzle-kit actually accepts,
and a per-app auth secret.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

#: Repairs from ``app_emitter`` that the Blueprint path makes unnecessary, and
#: the projection that makes each one so. Stated rather than merely omitted, so
#: dropping one is an argument someone can check.
SUPERSEDED_REPAIRS: dict[str, str] = {
    "reconcile_db_schema_barrel": "project_data_layer writes one barrel",
    "reconcile_user_fk_types": "FKs derive from declared relationships",
    "complete_light_theme": "project_design_tokens writes tokens.css",
    "ensure_nav_flow": "project_nav_flow writes it from navigation",
    "normalize_component_aliases": "templates validate against the real registry",
    "ensure_crud_pages": "pages come from page contracts; a gap is a Blueprint defect",
    "reconcile_singleton_pages": "same — synthesising a page hides the gap",
    "fix_schema_versions": "the planner emits the version the engine declares",
    "_regenerate_route_registry": "the frontend projection emits registry.ts",
}

#: Written by the projections; assembly must never overwrite them.
PROJECTED_PATHS: tuple[str, ...] = (
    "src/schemas", "src/contracts", "src/db/schema", "src/db/seed.json",
    "src/lib/workflows/definitions", "src/app/tokens.css",
    # The scaffold ships a middleware that gates everything; the projection
    # writes one from what each page declares. Assembly runs after projection,
    # so leaving this off the list silently restored the hardcoded gate and an
    # app with public pages had them quietly closed again.
    "src/middleware.ts",
    # `/` is owned by the scaffold's `(dashboard)/page.tsx`, inside the group
    # that carries the shell. `project_root_route` overwrites that file with a
    # redirect when no page claims `/`, and deletes any `src/app/page.tsx` an
    # older build left beside it — a root page outside the group resolves to
    # `/` too and renders without the sidebar.
    "src/app/(dashboard)/page.tsx",
    "src/lib/sensitive-columns.ts", "src/lib/searchable-columns.ts",
    "src/lib/append-only-entities.ts",
)

#: Files inside a projected directory that the *scaffold* still owns.
#:
#: `src/db/schema` holds two kinds of table. The projection writes one file per
#: business entity, and the scaffold ships the platform's own — the user table
#: auth.ts and the signup route import. Marking the directory projection-owned
#: is right for the first kind and deletes the second: the build failed on
#: `Can't resolve '@/db/schema/user'` because nothing ever wrote it and
#: assembly was told to keep its hands off the directory that would have.
#:
#: Directory-level ownership cannot express "these 28 files are generated and
#: this one is not", so the exception is stated by name.
SCAFFOLD_OWNED: tuple[str, ...] = (
    "src/db/schema/user.ts",
)

#: Scaffold files that are a DEFAULT for something a projection writes: copied
#: only when the projection did not write one.
#:
#: A third category, and it needs to be. `PROJECTED_PATHS` says "never touch",
#: which leaves nothing when the projection is skipped; `SCAFFOLD_OWNED` says
#: "always copy", and since assembly runs AFTER projection that would overwrite
#: the application's own palette with the neutral one every time.
#:
#: `globals.css` imports `./tokens.css` unconditionally, so a scaffold without
#: it does not build — and one page failing to plan was enough to skip the
#: projection and produce `Module not found: Can't resolve './tokens.css'` for
#: the whole application. The ordering fix stopped that particular trigger.
#: This stops the class: a template that imports a file it does not contain is
#: broken on its own terms, and a crash, a timeout, a partial run or an export
#: taken mid-build all reach the same place.
#:
#: The floor is a plain-looking application, not an unbuildable one.
SCAFFOLD_DEFAULTS: tuple[str, ...] = (
    "src/app/tokens.css",
)

DRIZZLE_CONFIG = '''import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./src/db/schema",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: { url: process.env.DATABASE_URL! },
});
'''


#: Directories that are build output or dependencies, never scaffold.
_SKIP_DIRS = frozenset({"node_modules", ".next", "dist", ".git", "drizzle"})


def _template_dirs() -> list[Path]:
    """The scaffold layers, base first.

    The scaffold is two templates, not one. ``app-foundation`` is the base —
    the runtime the generated app is built on: ``src/lib/schema-page.tsx``
    (which the catch-all route imports), the data-engine bridge, the library
    registry, the UI components, the API routes. ``standalone-app`` is a
    seventeen-file overlay that adapts it into a standalone Next app.

    ``app_emitter`` copies only the overlay, which is why the catch-all route
    could not resolve ``@/lib/schema-page``: the file it imports lives in the
    layer underneath. Layering base-then-overlay is what actually produces a
    compiling app.
    """
    from services.app_emitter import _TEMPLATE_DIR

    return [_TEMPLATE_DIR.parent / "app-foundation", _TEMPLATE_DIR]


#: Scaffold files a template used to ship and no longer does; deleted from an
#: application on every assembly so the old copy cannot shadow the new shape.
RETIRED_SCAFFOLD_FILES: tuple[str, ...] = ("src/app/page.tsx",)


def copy_scaffold(app_root: str | Path, *, project_short_id: str) -> list[str]:
    """Copy the scaffold layers in order, interpolating ``.tmpl`` files.

    Never touches anything under :data:`PROJECTED_PATHS` — those are the
    application, and the scaffold is only the shell it runs in. Later layers
    overwrite earlier ones, which is the point: the overlay wins.
    """
    from services.app_emitter import _interpolate, _TMPL_SUFFIX

    out = Path(app_root)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for layer in _template_dirs():
        if not layer.is_dir():
            continue
        for src in layer.rglob("*"):
            if src.is_dir() or any(part in _SKIP_DIRS for part in src.parts):
                continue
            rel = src.relative_to(layer)
            dst_rel = rel.with_suffix("") if rel.suffix == _TMPL_SUFFIX else rel
            if (any(str(dst_rel).startswith(p) for p in PROJECTED_PATHS)
                    and str(dst_rel) not in SCAFFOLD_OWNED
                    and str(dst_rel) not in SCAFFOLD_DEFAULTS):
                continue
            dst = out / dst_rel
            # A default only fills a hole. The projection ran first and its
            # output is the application's; this is what stands in when it did
            # not run at all.
            if str(dst_rel) in SCAFFOLD_DEFAULTS and dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if rel.suffix == _TMPL_SUFFIX:
                dst.write_text(_interpolate(src.read_text(),
                                            project_short_id=project_short_id))
            else:
                shutil.copyfile(src, dst)
            written.append(str(dst_rel))
    # WHAT THE SCAFFOLD NO LONGER SHIPS IS REMOVED. Copying only adds, so a
    # file a template retired stayed in every application built before: the
    # root page that redirected to a hard-coded /home sat beside the group's
    # index at "/", two pages at one path, until deleted here.
    for rel in RETIRED_SCAFFOLD_FILES:
        if rel in written:
            continue
        stale = out / rel
        if stale.is_file():
            stale.unlink()
    return written


#: Scaffold files carrying `{{…}}` placeholders. These are plain `.tsx`, not
#: `.tmpl`, so the copy step never touched them — and an unsubstituted
#: `{{app_name}}` is not inert text, it is a JSX expression that throws
#: `ReferenceError: app_name is not defined` the moment the page renders. The
#: error pages were the worst place for it: the app crashed while trying to
#: tell the user something had crashed.
EDGE_PAGES: tuple[str, ...] = (
    "src/app/not-found.tsx",
    "src/app/error.tsx",
    "src/app/forbidden.tsx",
    "src/app/loading.tsx",
    "src/app/maintenance.tsx",
    "src/components/EdgePageFrame.tsx",
)

#: Scaffold files carrying placeholders that are NOT `{{…}}`. `layout.tsx`
#: holds `__APP_LOCALE__` / `__APP_DIR__` — §11's interface language reaching
#: the document. Same failure as EDGE_PAGES and the same cause: a plain `.tsx`
#: the `.tmpl` copy step never reads. It is listed separately only because the
#: token spelling differs; the substitution pass below is one pass, not two.
PLACEHOLDER_PAGES: tuple[str, ...] = EDGE_PAGES + ("src/app/layout.tsx",)


def _landing_route(doc: dict) -> str:
    """Where "back to the app" should point.

    The declared landing page if navigation names one, else the first page that
    is not an auth route — never a guess like "/dashboard" that may not exist.
    """
    nav = doc.get("navigation") or {}
    for key in ("landing", "home", "root"):
        route = nav.get(key)
        if isinstance(route, str) and route.startswith("/"):
            return route
    pages = [p for p in (doc.get("pages") or []) if p.get("status") != "DEPRECATED"]
    for page in pages:
        route = page.get("route") or ""
        if route and route != "/" and not any(
            k in route for k in ("sign-in", "signin", "login", "sign-up", "register")
        ):
            return route
    return "/"


def interpolate_edge_pages(app_root: str | Path, doc: dict) -> list[str]:
    """Substitute the scaffold's placeholders from the Blueprint.

    Runs on THIS path — the Blueprint pipeline assembles through
    `copy_scaffold`, never through `app_emitter.emit_standalone_app`, and
    `inject_runtime`'s callers are all in the legacy router. Anything a
    scaffold `.tsx` leaves unsubstituted ships literally.
    """
    from services.runtime_injector import _RTL_LANGUAGES  # one RTL list

    application = doc.get("application") or {}
    app_name = application.get("name") or "the app"
    initial = next((c for c in app_name if c.isalnum()), "A").upper()

    tag = str((doc.get("product") or {}).get("locale") or "").strip() or "en"
    base = tag.replace("_", "-").split("-")[0].lower()

    values = {
        "{{app_name}}": app_name,
        "{{app_initial}}": initial,
        "{{home_route}}": _landing_route(doc),
        "__APP_LOCALE__": tag,
        "__APP_DIR__": "rtl" if base in _RTL_LANGUAGES else "ltr",
    }

    out = Path(app_root)
    touched: list[str] = []
    for rel in PLACEHOLDER_PAGES:
        path = out / rel
        if not path.is_file():
            continue
        text = original = path.read_text("utf-8")
        for token, value in values.items():
            text = text.replace(token, value)
        if text != original:
            path.write_text(text, "utf-8")
            touched.append(rel)
    return touched


def inject_runtime_layer(app_root: str | Path, doc: dict) -> dict[str, Any]:
    """Install the embedded runtime — workflows, rules, FEEL-lite, data engine.

    A third scaffold layer, and the one that makes the app *execute* rather
    than merely render: ``templates/runtime/`` copies into ``src/lib/`` and
    brings the workflow executor, the rules engine and the API routes that
    drive them. Without it the catch-all route cannot even resolve
    ``@/lib/error_reporter`` and every page 500s.

    This is installation, not repair — it ships fixed files the generated app
    imports — so unlike the repair cascade it belongs on the Blueprint path.
    """
    from services.runtime_injector import inject_runtime

    application = doc.get("application") or {}
    return inject_runtime(
        str(app_root),
        # The projections own these; the injector must install the engine
        # around them rather than over them.
        preserve=PROJECTED_PATHS,
        app_name=application.get("name"),
        domain=application.get("domain"),
        project_id=application.get("id"),
    )


#: Packages the vendored engine dist imports that are NOT npm packages — they
#: ship as loose TypeScript under ``src/lib/`` and are resolved by a webpack
#: alias in ``next.config.js``. ``_rewrite_vendored_deps`` drops them from the
#: dependency graph on purpose, and nothing then copied them, so every render
#: died on ``Can't resolve '@tentoroforge/feel-lite'``. Source -> destination,
#: relative to the workspace root and the app root respectively.
LOOSE_LIBS: dict[str, str] = {
    "frontend/src/lib/feel-lite": "src/lib/feel-lite",
}


def copy_loose_libs(app_root: str | Path) -> list[str]:
    """Copy the aliased non-npm libraries the engine dist imports."""
    workspace = Path(__file__).resolve().parents[3]
    out = Path(app_root)
    copied: list[str] = []
    for src_rel, dst_rel in LOOSE_LIBS.items():
        src = workspace / src_rel
        if not src.is_dir():
            continue
        dst = out / dst_rel
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied.append(dst_rel)
    return copied


def vendor_engines(app_root: str | Path) -> list[str]:
    """Vendor the engine stack: rebuild stale dist, copy package.json + dist."""
    from services.app_emitter import _vendor_engine_packages

    out = Path(app_root)
    _vendor_engine_packages(out)
    copy_loose_libs(out)
    vendor = out / "vendor"
    return sorted(str(p.relative_to(out)) for p in vendor.glob("*/*")) \
        if vendor.exists() else []


def database_name(project_short_id: str) -> str:
    """The database this project owns, and no other project's.

    ONE NAME FOR EVERY APPLICATION IS THE BUG THIS REPLACES. A constant
    `postgres://…/app` was written into every generated `.env.local`, so every
    application that read that file — `npm run dev`, drizzle-kit, the verify
    compose file, a deploy — opened the SAME database. A real run found a
    Figma-specification app reading an expense tracker's `users` table: the
    column its schema expected did not exist, `authorize()` threw, and the
    login page reported "Invalid email or password". A wrong database wearing
    a wrong-password mask.

    `run.sh` already derived a per-project name and said why it refused to
    trust the file::

        # Deliberately not read back from .env.local: assembly writes `/app`
        # there for every application, which is the value that put two apps in
        # one database.

    That is a workaround living in one of the several things that start an
    app, and it only protects the one. The name belongs where the file is
    written, so every reader of the file gets it. THE STRING MUST MATCH WHAT
    THE SCRIPT COMPUTES — `app_` plus the sanitised directory name — or the
    two paths would disagree and a script-started app would migrate one
    database while `npm run dev` read another.

    Postgres takes neither a leading digit nor a dash, which is what the
    prefix and the substitution are for; a short_id is already eight lowercase
    alphanumerics, so this only bites the uuid-named directories that predate
    short_id paths.
    """
    ident = re.sub(r"[^a-z0-9]", "_", str(project_short_id or "forge").lower())
    return f"app_{ident}"


def default_database_url(project_short_id: str) -> str:
    """The connection string for that database, on the conventional dev port.

    The port is a starting point, not a promise: `run.sh` picks a free one and
    rewrites both env files, because every generated app otherwise hardcodes
    5432 and collides with the second app to start.
    """
    return (f"postgres://postgres:postgres@localhost:5432/"
            f"{database_name(project_short_id)}")


def assemble(doc: dict, app_root: str | Path, *,
             project_short_id: str = "forge",
             database_url: str | None = None) -> dict[str, Any]:
    """Scaffold + vendored engines + the config the toolchain needs."""
    # Derived rather than defaulted: the project's identity is already a
    # parameter of this call, and a module-level constant is how every
    # application came to share one database.
    database_url = database_url or default_database_url(project_short_id)

    out = Path(app_root)
    scaffold = copy_scaffold(out, project_short_id=project_short_id)
    edge = interpolate_edge_pages(out, doc)
    runtime = inject_runtime_layer(out, doc)
    vendored = vendor_engines(out)
    loose = copy_loose_libs(out)

    (out / "drizzle.config.ts").write_text(DRIZZLE_CONFIG, "utf-8")

    # Next caches compiled output under `.next`, and a running dev server keeps
    # serving it. Re-assembling rewrites scaffold sources underneath that cache,
    # so a fixed file can keep failing exactly as it did before the fix — the
    # placeholder substitution landed on disk and the browser still showed
    # `ReferenceError: app_name is not defined`. Assembly changes the sources it
    # compiles from, so it invalidates the cache it invalidated.
    # BUT NOT THE DIRECTORY A RUNNING DEV SERVER IS SERVING FROM. Removing
    # `.next` whole while `next dev` was up took its manifests away, and the
    # served app answered "Internal Server Error" (`routes-manifest.json`
    # not found) after every rebuild until someone restarted it. The dev
    # server recompiles changed sources by itself; what goes stale is the
    # persistent compiler cache under `.next/cache` and the verification
    # build's own output, and those are what assembly clears.
    for stale in (out / ".next" / "cache", out / VERIFY_DIST_DIR):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)

    # A per-app secret, generated rather than templated — a shared one across
    # every generated app is a real vulnerability, not a nit.
    #
    # Written to `.env` as well as `.env.example`, because auth reads the real
    # file: without it NextAuth answers every route with a 307 to
    # `/api/auth/error?error=Configuration`, which looks like a routing bug and
    # is actually a missing secret. `.env` is only created if absent, so a
    # re-assembly never rotates a secret out from under a running app.
    # THE COMMENT ABOVE WAS THE INTENT; THE CODE ROTATED THE SECRET ANYWAY.
    # Both files were rewritten with fresh secrets on every assembly, so every
    # rebuild signed the user out with `JWT_SESSION_ERROR: decryption
    # operation failed` — a session issued under the old secret. An app keeps
    # its secrets across rebuilds; only an app that has none is given some.
    kept = existing_secrets(out)
    env_body = (
        f"DATABASE_URL={database_url}\n"
        f"AUTH_SECRET={kept.get('AUTH_SECRET') or secrets.token_urlsafe(32)}\n"
        f"NEXTAUTH_SECRET={kept.get('NEXTAUTH_SECRET') or secrets.token_urlsafe(32)}\n"
        # No NEXTAUTH_URL: pinning it to :3000 sent every post-login redirect
        # to a port the app is not served on. NextAuth infers the origin from
        # the request, which is correct for any port a preview lands on.
        f"AUTH_TRUST_HOST=true\n"
    )
    (out / ".env.example").write_text(env_body, "utf-8")

    # Next.js gives `.env.local` precedence over `.env`, and the scaffold ships
    # one pointing at a shared development database. Copied verbatim, every
    # generated app would quietly write into the same tables as every other —
    # and the symptom is baffling: the schema is projected correctly, psql
    # confirms the columns exist, and the app still insists they do not,
    # because it is talking to a different database entirely.
    #
    # So the app's own connection is written to the file that actually wins.
    for name in (".env", ".env.local"):
        (out / name).write_text(env_body, "utf-8")

    # Last, after every writer above. A `{{token}}` surviving into a .tsx is a
    # JSX expression, so it compiles, passes both gates, and dies at prerender
    # — the guard reads the finished app and says so. It repairs nothing: a
    # finding here means a substitution pass did not run, and the pass is what
    # needs fixing.
    #
    # It existed already, validated over 8,612 emitted files, and its only
    # caller was the legacy router — so the pipeline that builds today was the
    # one flying blind. The report is written even when clean, so "no findings"
    # and "never ran" stay distinguishable.
    from services.residual_placeholder_guard import (
        apply_residual_placeholder_guard,
    )

    placeholders = apply_residual_placeholder_guard(out)

    return {
        "scaffold": len(scaffold),
        "vendored": vendored,
        "looseLibs": loose,
        "edgePages": edge,
        "runtimeFiles": len(runtime.get("copied") or []),
        "runtimeErrors": runtime.get("errors") or [],
        "supersededRepairs": sorted(SUPERSEDED_REPAIRS),
        "residualPlaceholders": placeholders.get("findings") or [],
    }


_SECRET_KEYS = ("AUTH_SECRET", "NEXTAUTH_SECRET")


def existing_secrets(app_root: str | Path) -> dict[str, str]:
    """The auth secrets an assembled app already runs with, if any.

    Read from `.env.local` first because Next gives it precedence, then
    `.env`. A secret is the app's identity to every session it has issued;
    a rebuild that changes it logs everyone out.
    """
    root = Path(app_root)
    found: dict[str, str] = {}
    for name in (".env.local", ".env"):
        f = root / name
        if not f.exists():
            continue
        for line in f.read_text("utf-8").splitlines():
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key in _SECRET_KEYS and value and key not in found:
                found[key] = value
    return found


# ---------------------------------------------------------------------------
# runtime / deployment / dependencies — facts about the assembled app
# ---------------------------------------------------------------------------

def describe_runtime(app_root: str | Path) -> dict[str, Any]:
    """§86 — what the assembled app actually runs on.

    Read off the scaffold rather than declared by an agent: the framework and
    node version are properties of the thing on disk, and an agent asked to
    state them would be guessing at a file it cannot see.
    """
    pkg_path = Path(app_root) / "package.json"
    pkg = json.loads(pkg_path.read_text("utf-8")) if pkg_path.exists() else {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    return {
        "framework": "nextjs" if "next" in deps else "node",
        "language": "typescript" if "typescript" in deps else "javascript",
        "packageManager": "npm",
        "nodeVersion": (pkg.get("engines") or {}).get("node") or ">=20",
    }


def describe_deployment(doc: dict, *, preview_url: str | None = None) -> dict[str, Any]:
    """§86–89 — where it goes, and how far along it is.

    ``preview`` and ``production`` are *states*, not URLs: §94's machine tracks
    whether a preview is stopped, starting, running or failed. Assembly only
    establishes that the app can be served — it does not claim a running
    preview, and it never claims a production deployment that has not happened.
    """
    deployment: dict[str, Any] = {
        "provider": "vercel",
        "preview": {"status": "running" if preview_url else "stopped"},
        "production": {"status": "none"},
    }
    if preview_url:
        deployment["preview"]["url"] = preview_url
    return deployment


def describe_dependencies(app_root: str | Path) -> list[str]:
    """Runtime dependencies of the assembled app, vendored ones included.

    Recorded so §83 export and §100 review have a real list rather than a
    remembered one.
    """
    pkg_path = Path(app_root) / "package.json"
    if not pkg_path.exists():
        return []
    pkg = json.loads(pkg_path.read_text("utf-8"))
    return sorted((pkg.get("dependencies") or {}).keys())


def apply_assembly(svc: Any, app_root: str | Path, *,
                   project_short_id: str = "forge",
                   preview_url: str | None = None) -> dict[str, Any]:
    """Assemble, then record what was assembled in the Blueprint."""
    result = assemble(svc.doc, app_root, project_short_id=project_short_id)
    svc.doc["runtime"] = describe_runtime(app_root)
    svc.doc["deployment"] = describe_deployment(svc.doc, preview_url=preview_url)
    svc.doc["dependencies"] = describe_dependencies(app_root)
    svc.save()
    result["runtime"] = svc.doc["runtime"]
    result["deployment"] = svc.doc["deployment"]
    result["dependencies"] = len(svc.doc["dependencies"])
    return result


class BuildFailed(RuntimeError):
    """The assembled application does not compile."""


def page_funnel(doc: dict, app_root: str | Path) -> dict[str, Any]:
    """Planned pages against pages the application actually serves.

    A RUN THAT PLANS N PAGES AND SHIPS FEWER REPORTS SUCCESS. `page_layouts`
    completes with per-subject failures, every projection downstream faithfully
    projects what survived, `next build` compiles it, and the missing routes are
    discovered by a person clicking on them. Measured on two real builds:
    53 planned -> 27 composed, and 38 planned -> 23 composed. Both "succeeded".

    The projection is lossless — everything is lost at composition — so the
    honest place to state the shortfall is against the registry the app is
    actually served from, not against the Blueprint that intended it.

    Returns the counts and the missing routes rather than raising: whether a
    shortfall should end a run is the caller's decision, and `_project_preview`
    records it either way. Reporting it is the part that was missing.
    """
    root = Path(app_root)
    planned = {
        str(p.get("route")) for p in (doc.get("pages") or [])
        if isinstance(p, dict) and p.get("route")
    }
    registry = root / "src" / "schemas" / "registry.ts"
    served: set[str] = set()
    if registry.exists():
        # The generated registry maps route -> loader, one `"<route>": () =>`
        # per line. Read rather than re-derived, so this cannot agree with the
        # Blueprint by construction and disagree with the app.
        served = set(re.findall(r'"([^"]+)":\s*\(\)\s*=>', registry.read_text("utf-8")))

    missing = sorted(planned - served)
    return {
        "planned": len(planned),
        "served": len(served & planned),
        "missing": missing,
        "status": "complete" if not missing else "short",
    }


def verify_build(app_root: str | Path, *, timeout: int = 900) -> dict[str, Any]:
    """Install and build the assembled app; raise if it does not compile.

    The `preview` node assembled a tree and reported success without ever
    compiling it, so "an application was generated" meant "files were written".
    Two build-breaking faults survived every run that way: the scaffold's own
    user table was deleted by the projection guard, and the data engine's
    catch-all imported a module no projection wrote. Both would have surfaced
    the first time anything ran `next build`.

    Slow — install and build are minutes, not seconds — and that is the cost of
    the claim. A generated app that has not been compiled has not been checked.
    """
    import os
    import subprocess

    root = Path(app_root)
    steps = (("install", ["npm", "install", "--no-audit", "--no-fund"]),
             ("build", ["npm", "run", "build"]))
    # THE CHECK MUST NOT BREAK THE THING IT CHECKS. `next build` and `next dev`
    # both own `.next`; a verification build in the directory of a running
    # dev server rewrote its manifests under it, and the served app answered
    # 500 (`routes-manifest.json` not found) while the build itself failed on
    # the dev server's half-written chunks — three times on one project. The
    # generated Next config reads its `distDir` from this variable, so the
    # verification compiles beside the served app and never into it.
    env = {**os.environ, "NEXT_DIST_DIR": VERIFY_DIST_DIR}
    out: dict[str, Any] = {}
    for name, cmd in steps:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              timeout=timeout, env=env)
        out[name] = proc.returncode
        if proc.returncode != 0:
            raise BuildFailed(
                f"npm {name} failed ({proc.returncode}):\n"
                + build_message(proc.stdout, proc.stderr)
            )
    return out


#: Where a verification build writes, beside — never inside — the served app.
VERIFY_DIST_DIR = ".next-verify"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ERROR_LINE = re.compile(
    r"Failed to compile|Module not found|Type error|error TS\d+|"
    r"\bError:|SyntaxError|ReferenceError|Build error occurred", re.I)
_NOISE = ("inferred your workspace root", "multiple lockfiles",
          "outputFileTracingRoot", "npm error", "npm ERR!", "npm notice")


def build_message(stdout: str | None, stderr: str | None) -> str:
    """The compiler's own message, from wherever it was written.

    Next writes its errors to stdout and its warnings to stderr, and the
    scaffold's monorepo placement earns a lockfile warning on every build. The
    first version kept `stderr or stdout`, so whenever a warning existed the
    error was discarded, and the run log's 400-character reason was the
    warning about lockfiles — for a build that failed for another reason
    entirely. Both streams are read; the warning is dropped; the message
    starts at the first line that names an error, so the reason's first
    characters are the ones that matter.
    """
    lines = [_ANSI.sub("", l).rstrip()
             for l in ((stdout or "") + "\n" + (stderr or "")).splitlines()]
    lines = [l for l in lines if l.strip() and not any(n in l for n in _NOISE)]
    start = next((i for i, l in enumerate(lines) if _ERROR_LINE.search(l)), None)
    kept = lines[start:start + 25] if start is not None else lines[-25:]
    return "\n".join(kept)
