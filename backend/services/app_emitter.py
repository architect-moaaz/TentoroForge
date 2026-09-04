"""Emit a standalone Next.js app skeleton into a project's output directory.

Runs AFTER the schema agents have written src/schemas/*.json and the
design agent has written src/contracts/design-spec.json. We add the
templated runtime files (package.json, next.config.js, layout.tsx,
[...slug]/page.tsx, etc.) so the project becomes a working Next.js app.

Idempotent — re-emitting overwrites our templated files but never
touches LLM-generated content under src/schemas/ or src/contracts/ or
src/app/globals.css.
"""
from __future__ import annotations
import json as _json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "standalone-app"
_TMPL_SUFFIX = ".tmpl"

# Engine-stack packages to vendor into each exported app under
# vendor/@tentoroforge/<pkg>/. Order matters for predictability but not
# for correctness.
_VENDOR_PACKAGES = ("engine", "library", "renderer", "schema")

# Private "@forge/*" packages that never shipped to npm but are still
# imported by the compiled engine-stack (renderer/dist calls
# `syntheticNodeId` from @forge/patches). Vendored under
# vendor/@forge/<pkg>/ and referenced from package.json + next.config.js
# so `next build` can resolve them without a registry.
_VENDOR_FORGE_PACKAGES = ("patches",)


# Text files worth reading back to substitute placeholders into. Anything
# else in the template is copied byte for byte.
_TEXT_SUFFIXES = {".tsx", ".ts", ".jsx", ".js", ".json", ".css", ".mdx"}


def _interpolate(text: str, *, project_short_id: str,
                 locale: str = "en", direction: str = "ltr") -> str:
    return (text.replace("<<project_short_id>>", project_short_id)
                .replace("__APP_LOCALE__", locale)
                .replace("__APP_DIR__", direction))


def _ensure_package_built(pkg_dir: Path) -> None:
    """Rebuild a package's dist/ if it is missing or older than its source.

    dist/ is gitignored and the generator only COPIES it — so without this, a source
    fix that wasn't manually rebuilt would silently ship stale code in every new app.
    Cheap staleness check (newest src mtime vs newest dist mtime); only rebuilds when
    needed, and falls back to the existing dist if the build fails (never blocks a gen).
    """
    import subprocess

    src_dir = pkg_dir / "src"
    dist_dir = pkg_dir / "dist"
    if not src_dir.exists():
        return

    def _newest(root: Path, exts: set[str]) -> float:
        newest = 0.0
        if not root.exists():
            return newest
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in exts:
                try:
                    newest = max(newest, p.stat().st_mtime)
                except OSError:
                    pass
        return newest

    src_mtime = _newest(src_dir, {".ts", ".tsx"})
    dist_mtime = _newest(dist_dir, {".js", ".d.ts"})
    if dist_dir.exists() and dist_mtime >= src_mtime:
        return  # dist is fresh

    try:
        subprocess.run(
            ["npm", "run", "build"], cwd=str(pkg_dir),
            check=True, capture_output=True, timeout=300,
        )
        logger.info("[vendor] rebuilt %s/dist (was %s)", pkg_dir.name,
                    "missing" if not dist_dir.exists() else "stale")
    except Exception as e:  # keep generating with whatever dist exists
        logger.warning("[vendor] could not rebuild %s (%s) — vendoring existing dist", pkg_dir.name, e)


def _rewrite_vendored_deps(deps: dict) -> dict:
    """Rewrite a vendored package.json's dependencies to something npm can
    resolve inside the output tree.

    - ``@tentoroforge/<vendored>``  → ``file:../<vendored>`` (sibling in
      vendor/@tentoroforge/)
    - ``@tentoroforge/<other>``     → dropped (non-vendored siblings like
      @tentoroforge/feel-lite ship as loose files under src/lib/ and are
      resolved via a next.config.js webpack alias, not as npm packages)
    - ``@forge/<vendored>``         → ``file:../../@forge/<vendored>``
      (crosses namespace directories under vendor/)
    - ``@forge/<other>``            → dropped (same rationale)
    - ``workspace:*`` / ``"*"``     → ``"*"`` (npm resolves from registry)
    """
    for k, v in list(deps.items()):
        if k.startswith("@forge/"):
            suffix = k.split("/", 1)[1]
            if suffix in _VENDOR_FORGE_PACKAGES:
                deps[k] = f"file:../../@forge/{suffix}"
            else:
                del deps[k]
        elif k.startswith("@tentoroforge/"):
            suffix = k.split("/", 1)[1]
            if suffix in _VENDOR_PACKAGES:
                deps[k] = f"file:../{suffix}"
            else:
                del deps[k]
        elif isinstance(v, str) and (
            v.startswith("workspace:") or v == "*"
        ):
            deps[k] = "*"
    return deps


def _vendor_one_package(src: Path, dst: Path) -> None:
    """Rebuild dist if stale, then copy package.json + dist/ into `dst`,
    rewriting the copied package.json's dependency graph so npm-install
    inside the generated app resolves every internal reference.
    """
    _ensure_package_built(src)  # rebuild dist if a source fix wasn't compiled
    dst.mkdir(parents=True, exist_ok=True)

    src_pkg = src / "package.json"
    if src_pkg.exists():
        content = _json.loads(src_pkg.read_text())
        content["dependencies"] = _rewrite_vendored_deps(
            content.get("dependencies") or {}
        )
        (dst / "package.json").write_text(
            _json.dumps(content, indent=2) + "\n"
        )

    src_dist = src / "dist"
    if src_dist.exists():
        dst_dist = dst / "dist"
        if dst_dist.exists():
            shutil.rmtree(dst_dist)
        shutil.copytree(src_dist, dst_dist)


def _vendor_engine_packages(output_dir: Path) -> None:
    """Copy every engine-stack package's package.json + dist/ into
    output_dir/vendor/{@tentoroforge,@forge}/<pkg>/ so the generated app's
    ``file:./vendor/...`` deps resolve at npm-install time without
    needing a registry.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    for pkg in _VENDOR_PACKAGES:
        src = workspace_root / "packages" / pkg
        if src.exists():
            _vendor_one_package(src, output_dir / "vendor" / "@tentoroforge" / pkg)
    for pkg in _VENDOR_FORGE_PACKAGES:
        src = workspace_root / "packages" / pkg
        if src.exists():
            _vendor_one_package(src, output_dir / "vendor" / "@forge" / pkg)


_AUTH_ROUTES = frozenset({"/login", "/signup"})
_AUTH_PREFIXES = ("/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register")


def _is_safe_landing(route: object, page: object = None) -> bool:
    """True only for a concrete, navigable, post-login CONTENT route.

    Rejects every route shape that would 404 or self-loop the app's landing:
      * dynamic/param routes (a "[" segment) — 404 with no id bound. This is
        the exact bug that shipped: DEFAULT_INITIAL = "/invite/[token]" from
        picking the first non-auth page with no dynamic-route guard.
      * the root "/" — src/app/page.tsx redirecting to "/" self-loops against
        the (dashboard) route group that already serves "/".
      * auth entry routes (/login, /signup, …) — bounce an authed user back.
      * create/edit form routes (…/new, …/edit) — no record context.
      * non-shell pages (shell:false) — orphaned, outside the app frame.
    """
    if not isinstance(route, str) or not route.startswith("/"):
        return False
    if route == "/" or "[" in route:
        return False
    if route in _AUTH_ROUTES or any(
        route == p or route.startswith(p + "/") for p in _AUTH_PREFIXES
    ):
        return False
    if route.endswith("/new") or route.endswith("/edit"):
        return False
    if isinstance(page, dict) and page.get("shell") is False:
        return False
    return True


def derive_root_redirect(nav: dict) -> tuple[dict[str, str], str]:
    """Compute (INITIAL_FOR per-role map, DEFAULT_INITIAL) for a generated app's
    root redirect (src/app/page.tsx) from its nav-flow. Every returned route is
    guaranteed `_is_safe_landing` — never a dynamic/auth/form route, so the
    /invite/[token] 404 class of bug cannot recur.

    Default landing — first SAFE, EXISTING candidate wins:
      1. an explicit /dashboard page (the conventional home)
      2. nav-flow's post_login_redirect (the plan's stated intent)
      3. the initialPage's own route
      4. the first static shell CONTENT page in nav order
    Final fallback "/" (the caller unlinks page.tsx in that case).
    """
    pages = nav.get("pages") or []
    by_id = {p.get("id"): p for p in pages if isinstance(p, dict)}
    by_route = {p.get("route"): p for p in pages if isinstance(p, dict)}

    initial_for: dict[str, str] = {}
    raw_map = nav.get("initialFor") or {}
    if isinstance(raw_map, dict):
        for role, route in raw_map.items():
            if isinstance(role, str) and _is_safe_landing(route, by_route.get(route)):
                initial_for[role.strip()] = route

    _ip = by_id.get(nav.get("initialPage")) or {}
    candidates = [
        "/dashboard",
        nav.get("post_login_redirect"),
        _ip.get("route"),
        next((p.get("route") for p in pages if _is_safe_landing(p.get("route"), p)), None),
    ]
    default_initial = next(
        (c for c in candidates
         if isinstance(c, str) and c in by_route and _is_safe_landing(c, by_route[c])),
        "/",
    )
    return initial_for, default_initial


def emit_standalone_app(*, output_dir: str | Path, project_short_id: str) -> None:
    """Copy the template into output_dir, interpolating .tmpl files.

    Preserves any existing src/schemas/, src/contracts/, src/app/globals.css.
    Files NOT in the template are left alone.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # §11 — the interface language reaches the document here. This emitter is
    # the one the Blueprint pipeline runs; `inject_runtime`, which resolves the
    # same pair for the legacy router, is never called on this path. Imported
    # rather than reimplemented: one RTL list, not two.
    from services.runtime_injector import _resolve_locale

    locale, direction = _resolve_locale(out)

    for src in _TEMPLATE_DIR.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(_TEMPLATE_DIR)
        is_template = rel.suffix == _TMPL_SUFFIX
        dst_rel = rel.with_suffix("") if is_template else rel
        dst = out / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if is_template:
            content = src.read_text()
            content = _interpolate(
                content,
                project_short_id=project_short_id,
                locale=locale,
                direction=direction,
            )
            dst.write_text(content)
            continue

        # A plain .tsx carrying a placeholder — layout.tsx's <html lang/dir> is
        # the reason this branch exists. Only files that actually hold one are
        # read back; everything else is still a byte copy.
        if dst_rel.suffix in _TEXT_SUFFIXES:
            try:
                text = src.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                text = None
            if text is not None and ("__APP_LOCALE__" in text
                                     or "__APP_DIR__" in text):
                dst.write_text(
                    _interpolate(text, project_short_id=project_short_id,
                                 locale=locale, direction=direction),
                    encoding="utf-8",
                )
                continue
        shutil.copyfile(src, dst)

    # Consolidate the DB schema into a single authoritative barrel so
    # `@/db/schema` can't resolve to a stale singular shadow file (which breaks
    # workflow db_insert / CRUD routes with "unknown table").
    try:
        from services.schema_barrel import reconcile_db_schema_barrel
        reconcile_db_schema_barrel(out)
    except Exception as e:  # never block app emit on reconciliation
        logger.warning("[schema-barrel] reconcile skipped: %s", e)

    # Make user-referencing FK columns (landlordId/ownerId/userId/…) match the
    # users-table PK type, so a session user.id can actually populate them.
    try:
        from services.user_fk_types import reconcile_user_fk_types
        reconcile_user_fk_types(out)
    except Exception as e:
        logger.warning("[user-fk-types] reconcile skipped: %s", e)

    # Complete the light-theme :root so undefined --border/--foreground don't fall
    # back to currentColor (harsh near-black borders on every surface).
    try:
        from services.theme_tokens import complete_light_theme, ensure_tailwind_directives
        complete_light_theme(out)
        # Guarantee the @tailwind directives exist — without them every
        # hand-written Tailwind page (login/signup) renders unstyled.
        ensure_tailwind_directives(out)
    except Exception as e:
        logger.warning("[theme-tokens] complete skipped: %s", e)

    # Deterministically emit drizzle.config.ts in the drizzle-kit >=0.20 format.
    # The schema agent sometimes writes the legacy `driver: "pg"` shape, which
    # drizzle-kit 0.30 rejects ("Please specify 'dialect'") — so migration fails,
    # no tables get created, and every CRUD op then errors. Boilerplate, not LLM work.
    try:
        (out / "drizzle.config.ts").write_text(
            'import { defineConfig } from "drizzle-kit";\n\n'
            'export default defineConfig({\n'
            '  schema: "./src/db/schema",\n'
            '  out: "./drizzle",\n'
            '  dialect: "postgresql",\n'
            '  dbCredentials: { url: process.env.DATABASE_URL! },\n'
            '});\n',
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("[drizzle-config] emit skipped: %s", e)

    # Single authoritative next.config.js. The agent sometimes ALSO emits a
    # next.config.ts; with both present Next picks ambiguously and may drop
    # transpilePackages, leaking the vendored packages' browser code (which uses
    # `self`) into the server/middleware bundle -> "self is not defined" 500 on
    # every authenticated route. Write one config and remove conflicting variants.
    try:
        (out / "next.config.js").write_text(
            "/** @type {import('next').NextConfig} */\n"
            "module.exports = {\n"
            "  reactStrictMode: true,\n"
            '  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", '
            '"@tentoroforge/renderer", "@tentoroforge/schema"],\n'
            '  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],\n'
            "  outputFileTracingIncludes: {\n"
            '    "/**/*": ['
            '"./src/schemas/**/*.json", "./src/contracts/**/*.json", "./registry.json"'
            "],\n"
            "  },\n"
            "  typescript: { ignoreBuildErrors: true },\n"
            '  images: { domains: ["localhost"] },\n'
            "};\n",
            encoding="utf-8",
        )
        for _alt in ("next.config.ts", "next.config.mjs"):
            _p = out / _alt
            if _p.exists():
                _p.unlink()
    except Exception as e:
        logger.warning("[next-config] emit skipped: %s", e)

    # Point the root "/" redirect at the app's ACTUAL initial page (from nav-flow),
    # not a hardcoded "/home" — apps without a dashboard (e.g. a single-entity list
    # app) have no /home, so "/" -> "/home" 404s.
    try:
        initial = "/home"
        nav_path = out / "src" / "contracts" / "nav-flow.json"
        # Safety-net: guarantee nav-flow.json exists. The plan-driven emitter
        # runs earlier in the pipeline, but if it produced nothing (missing/empty
        # plan) the editor's Canvas would show "No nav-flow." Synthesize it from
        # the page schemas so every emitted app is editable and the redirect
        # below has real pages to target. No-op when it already exists.
        if not nav_path.exists():
            try:
                from services.nav_flow_from_schemas import ensure_nav_flow
                ensure_nav_flow(out)
            except Exception as _nf_ex:  # noqa: BLE001
                logger.warning("[nav-flow] synth fallback skipped: %s", _nf_ex)
        # Per-actor landing map. nav-flow's `initialFor` (written by
        # nav_flow_from_plan) already picks the first shell page each role
        # can see; we inline it into the generated page.tsx so the runtime
        # decides which route to serve based on session.user.role. If the
        # map is absent (older nav-flow / no visibleTo hints) we still fall
        # back to the single-route redirect below.
        initial_for: dict[str, str] = {}
        # "/" is the safe universal fallback: it is always served by the
        # (dashboard) route group. ("/home" was a bug — home lives at "/".)
        default_initial = "/"
        if nav_path.exists():
            nav = _json.loads(nav_path.read_text())
            initial_for, default_initial = derive_root_redirect(nav)

        # Emit the session-aware root redirect. The map is inlined at
        # generation time so we don't need `import json from "..."` at
        # runtime — simpler + one less thing that can break.
        map_entries = ",\n".join(
            f'  {_json.dumps(role)}: {_json.dumps(route)}'
            for role, route in sorted(initial_for.items())
        )
        map_body = "{\n" + map_entries + "\n}" if map_entries else "{}"
        _page_tsx = out / "src" / "app" / "page.tsx"
        if default_initial == "/" and not initial_for:
            # "/" is already served by the (dashboard) route group; a root
            # redirect to "/" would self-loop. With no per-role targets either,
            # emit NO page.tsx so the (dashboard) group serves "/" directly.
            if _page_tsx.exists():
                _page_tsx.unlink()
        else:
            _page_tsx.write_text(
                'import { redirect } from "next/navigation";\n'
                'import { auth } from "@/auth";\n\n'
                '// Session-aware root redirect. Middleware guarantees the caller\n'
                '// is authenticated (unauth requests bounce to /login), so we pick\n'
                "// the actor's landing route from a per-role map derived from\n"
                '// nav-flow.initialFor at generation time. Roles not in the map\n'
                '// (or a request with no session) fall back to DEFAULT_INITIAL.\n'
                '// The landing route is guaranteed non-dynamic / non-auth / non-form\n'
                '// at generation time, so this redirect can never 404.\n'
                f'const INITIAL_FOR: Record<string, string> = {map_body};\n'
                f'const DEFAULT_INITIAL = {_json.dumps(default_initial)};\n\n'
                'export default async function RootPage() {\n'
                '  const session = await auth();\n'
                '  const role = (session?.user as { role?: string } | undefined)?.role;\n'
                '  const route = (role && INITIAL_FOR[role]) || DEFAULT_INITIAL;\n'
                '  redirect(route);\n'
                '}\n',
                encoding="utf-8",
            )
    except Exception as e:
        logger.warning("[root-redirect] skipped: %s", e)

    # Rename hallucinated component types (TableSortable -> Table, …) to registered ones.
    try:
        from services.component_alias import normalize_component_aliases
        normalize_component_aliases(out)
    except Exception as e:
        logger.warning("[component-alias] skipped: %s", e)

    # Completeness: every user-facing entity with a Create workflow must have a
    # create page (the page agent often skips them for secondary entities, leaving
    # an "Add X" button that 404s).
    try:
        from services.crud_page_coverage import ensure_crud_pages
        _cpc = ensure_crud_pages(out)
        if _cpc.get("created"):
            logger.info("[crud-pages] synthesized %d missing create page(s): %s",
                        len(_cpc["created"]), ", ".join(_cpc["created"]))
    except Exception as e:
        logger.warning("[crud-pages] coverage skipped: %s", e)

    # Singleton-shape reconciler: pages the LLM navigated to but never
    # emitted, for the "current user's X" class (/profile, /profile/edit,
    # /account, ...). Runs AFTER ensure_crud_pages so we only rescue what
    # the CRUD-shape coverage didn't. Kills Bug 4 (blank /profile/edit).
    try:
        from services.singleton_page_reconciler import reconcile_singleton_pages
        _spr = reconcile_singleton_pages(out)
        if _spr.get("created"):
            logger.info("[singleton-pages] synthesized %d missing singleton page(s): %s",
                        len(_spr["created"]), ", ".join(_spr["created"]))
    except Exception as e:
        logger.warning("[singleton-pages] reconciler skipped: %s", e)

    # Route-content mismatch DETECTOR (Bug 3 telemetry). Doesn't repair —
    # deleting off-domain schemas without a strong replacement is worse
    # than leaving them. Logs every mismatch so the next iteration of the
    # page_schema_agent prompt has real signal about what to constrain.
    try:
        from services.route_content_guard import check_route_content
        _rcg = check_route_content(out)
        if _rcg.get("mismatches"):
            logger.warning(
                "[route-content] %d route(s) have off-domain content: %s",
                len(_rcg["mismatches"]),
                ", ".join(
                    f"{m['route']} (got {m['observed_entity']}, expected {m['expected_entity']})"
                    for m in _rcg["mismatches"]
                ),
            )
    except Exception as e:
        logger.warning("[route-content] guard skipped: %s", e)

    # Coerce invalid schemaVersion (e.g. "2.0") to "2" so pages validate + normalize
    # (an invalid version makes the renderer fall back to render-as-is, mis-rendering).
    try:
        from services.schema_version_fix import fix_schema_versions
        fix_schema_versions(out)
    except Exception as e:
        logger.warning("[schema-version] fix skipped: %s", e)

    # Re-generate the route registry AFTER synthesizing create/detail pages, so the
    # new src/schemas/<t>/[id].json + new.json are routable (else /projects/[id] 404s).
    try:
        from services.schema_pipeline import _regenerate_route_registry
        _regenerate_route_registry(str(out))
    except Exception as e:
        logger.warning("[route-registry] regen skipped: %s", e)

    # Give each app a unique NEXTAUTH_SECRET so sessions don't leak across apps on a
    # shared origin (stale token -> wrong user id -> owner-scoped queries/inserts break).
    try:
        from services.auth_secret import ensure_unique_auth_secret
        ensure_unique_auth_secret(out)
    except Exception as e:
        logger.warning("[auth-secret] skipped: %s", e)

    # Make credentials login case-insensitive (browsers auto-capitalize the email
    # field -> CredentialsSignin against a seeded lowercase admin).
    try:
        from services.auth_email_ci import make_email_login_case_insensitive
        make_email_login_case_insensitive(out)
    except Exception as e:
        logger.warning("[auth-ci] skipped: %s", e)

    # Make form/create pages render live (empty previewData={} otherwise flips the
    # Engine into preview mode -> inert dispatch -> form submits silently no-op).
    try:
        from services.schema_page_live import make_form_pages_live
        make_form_pages_live(out)
    except Exception as e:
        logger.warning("[schema-page-live] skipped: %s", e)

    # Vendor the engine stack so the tarball is self-contained.
    _vendor_engine_packages(out)