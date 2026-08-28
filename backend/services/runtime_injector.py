"""Runtime Injector Service.

Copies the embedded runtime (workflows, rules, FEEL-lite) into generated
Next.js apps so they can actually execute the workflows and rules that
users designed in the editors.

The runtime files live at backend/templates/runtime/ and get copied to
{output_dir}/src/lib/ for each generated project.

Also generates:
- src/app/api/workflows/[id]/execute/route.ts (server-side workflow execution)
- src/app/api/workflows/event/[event]/route.ts (event-based workflow trigger)
- src/components/WorkflowTriggerButton.tsx (UI helper for triggering from buttons)
- rules/index.json (rules exported from DB to filesystem for runtime loading)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

# Self-contained shadcn Tailwind config: maps the :root CSS variables (defined in
# globals.css) to Tailwind color/radius tokens so `@apply border-border`,
# `bg-background`, `text-primary`, etc. compile. No external token import, so it is
# safe to write into any generated app.
#
# The `/*__TYPOGRAPHY_BLOCK__*/` marker is replaced with a fontSize + fontFamily
# block by ``_build_tailwind_config`` (derived from the app's design-spec type
# scale when present). Without a fontSize block the Heading component's named
# classes (`text-page-title` … `text-caption`) silently no-op and headings render
# at browser defaults.
_SHADCN_TAILWIND_CONFIG_TEMPLATE = '''import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./node_modules/@tentoroforge/library/**/*.{js,jsx,ts,tsx}",
    "./node_modules/@tentoroforge/renderer/**/*.{js,jsx,ts,tsx}",
    "./node_modules/@tentoroforge/engine/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
/*__TYPOGRAPHY_BLOCK__*/
    },
  },
  plugins: [],
};

export default config;
'''

# Baseline named type scale — [font-size, { lineHeight, letterSpacing?, fontWeight? }].
# Ported from apps/render-scaffold/tailwind.config.ts. Keys are EXACTLY the ones the
# Heading component references (`text-page-title` … `text-micro`). The design-spec's
# type scale overrides the sizes (and title fontWeight) at write time.
_BASELINE_FONT_SIZES: list[tuple[str, str, dict[str, str]]] = [
    ("page-title",    "1.875rem",  {"lineHeight": "2.25rem",  "letterSpacing": "-0.02em", "fontWeight": "700"}),
    ("section-title", "1.25rem",   {"lineHeight": "1.75rem",  "letterSpacing": "-0.01em", "fontWeight": "600"}),
    ("card-title",    "1rem",      {"lineHeight": "1.5rem",                                "fontWeight": "600"}),
    ("body",          "0.875rem",  {"lineHeight": "1.375rem"}),
    ("caption",       "0.75rem",   {"lineHeight": "1.125rem"}),
    ("micro",         "0.6875rem", {"lineHeight": "1rem",     "letterSpacing": "0.03em",  "fontWeight": "500"}),
]

# design-spec scale key → tailwind fontSize key. `micro` has no spec source (keeps default).
_SPEC_SCALE_MAP = {
    "h1": "page-title",
    "h2": "section-title",
    "h3": "card-title",
    "body": "body",
    "caption": "caption",
}
_TITLE_KEYS = {"page-title", "section-title", "card-title"}


def _extract_css_size(value: Any) -> str | None:
    """Pull a css length (rem/px/em) out of a spec scale value.

    Spec values may be clean (``"2.5rem"``) or descriptive
    (``"text-3xl (30px) — page titles"``); returns the first length token or
    None when none is present.
    """
    if not isinstance(value, str):
        return None
    m = re.search(r"\d*\.?\d+\s*(?:rem|px|em)", value)
    return m.group(0).replace(" ", "") if m else None


def _extract_weight(value: Any) -> str | None:
    """Pull a 3-digit font weight out of a spec value (``"700 (bold)"`` → ``"700"``)."""
    if value is None:
        return None
    m = re.search(r"[1-9]00", str(value))
    return m.group(0) if m else None


def _resolve_font_sizes(spec: dict | None) -> list[tuple[str, str, dict[str, str]]]:
    """Baseline type scale overridden by the design-spec typography scale/weights."""
    sizes = [(k, s, dict(opts)) for k, s, opts in _BASELINE_FONT_SIZES]
    if not isinstance(spec, dict):
        return sizes
    typo = spec.get("typography") or {}
    scale = typo.get("scale") or {}
    heading_weight = _extract_weight(typo.get("headingWeight"))
    by_key = {k: i for i, (k, _, _) in enumerate(sizes)}
    for spec_key, tw_key in _SPEC_SCALE_MAP.items():
        size = _extract_css_size(scale.get(spec_key)) if isinstance(scale, dict) else None
        if size and tw_key in by_key:
            k, _old, opts = sizes[by_key[tw_key]]
            sizes[by_key[tw_key]] = (k, size, opts)
    if heading_weight:
        for tw_key in _TITLE_KEYS:
            if tw_key in by_key:
                sizes[by_key[tw_key]][2]["fontWeight"] = heading_weight
    return sizes


def _render_typography_ts(spec: dict | None) -> str:
    """Render the fontSize + fontFamily TS block for `theme.extend`."""
    lines = ["      fontSize: {"]
    for key, size, opts in _resolve_font_sizes(spec):
        opts_ts = ", ".join(f'{k}: "{v}"' for k, v in opts.items())
        lines.append(f'        "{key}": ["{size}", {{ {opts_ts} }}],')
    lines.append("      },")
    lines.append("      fontFamily: {")
    lines.append('        heading: ["var(--font-heading)", "system-ui", "sans-serif"],')
    lines.append('        body: ["var(--font-body)", "system-ui", "sans-serif"],')
    lines.append('        sans: ["var(--font-body)", "system-ui", "sans-serif"],')
    lines.append("      },")
    return "\n".join(lines)


def _build_tailwind_config(output_dir: "Path | None" = None) -> str:
    """Render the self-contained shadcn tailwind config, injecting the type scale.

    When ``output_dir`` has a ``src/contracts/design-spec.json``, its typography
    scale drives the fontSize values; otherwise the baseline scale is used.
    """
    spec: dict | None = None
    if output_dir is not None:
        try:
            spec_path = Path(output_dir) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            spec = None
    return _SHADCN_TAILWIND_CONFIG_TEMPLATE.replace(
        "/*__TYPOGRAPHY_BLOCK__*/", _render_typography_ts(spec)
    )


# Fully-rendered baseline config (spec-independent) — kept for importers/tests
# that need a ready-to-write string.
_SHADCN_TAILWIND_CONFIG = _build_tailwind_config()

from typing import Any

logger = logging.getLogger(__name__)

# Path to the runtime template
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "runtime"


def _remove_except(target: Path, root: Path, preserve: tuple[str, ...]) -> None:
    """Clear ``target`` but keep anything under a preserved path.

    Ownership of a shared directory has to be decided in one place. Handing the
    preserved list in — rather than teaching this module which paths are
    generated — keeps that decision with the caller that projects them.
    """
    for child in sorted(target.rglob("*"), key=lambda p: -len(p.parts)):
        rel = str(child.relative_to(root))
        if any(rel == p or rel.startswith(p + "/") for p in preserve):
            continue
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif not any(child.iterdir()):
            child.rmdir()


def inject_runtime(output_dir: str, app_name: str | None = None, domain: str | None = None, project_id: str | None = None, preserve: tuple[str, ...] = ()) -> dict[str, Any]:
    """Copy runtime files into a generated app's src/lib/ directory.

    Args:
        output_dir: Project output directory (e.g., output/abc123)
        app_name: Human app name used to replace the __APP_NAME__ placeholder
            baked into the foundation templates (sidebar brand, <title>, etc.).
        project_id: UUID of THIS project row — seeded into .env.local as
            FORGE_PROJECT_ID so the runtime error reporter can POST back
            to /api/projects/<id>/runtime-exceptions. Without it the
            reporter silently no-ops (see error_reporter.ts:61) and the
            self-healing loop can never fire.

    Returns:
        Dict with copied files and any errors.
    """
    output_path = Path(output_dir)
    if not output_path.exists():
        return {"copied": [], "errors": [f"Output dir does not exist: {output_dir}"]}

    src_lib = output_path / "src" / "lib"
    src_lib.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    errors: list[str] = []

    # Copy each runtime subdirectory
    # "events" = the durable event bus + cron scheduler (R1/R2/R3):
    # workflows/index.ts imports ../events/emit-node and engine resumes
    # ride through events/bus.ts, so it MUST ship with the workflows dir.
    for subdir in ["feel-lite", "workflows", "rules", "events"]:
        src = _TEMPLATE_DIR / subdir
        dst = src_lib / subdir

        if not src.exists():
            errors.append(f"Template missing: {src}")
            continue

        try:
            # `preserve` names paths a projection owns. This used to rmtree the
            # whole directory, which installed the workflow engine correctly and
            # deleted the 13 workflow definitions written moments earlier —
            # `src/lib/workflows/definitions` is in PROJECTED_PATHS, but that
            # list only governs copy_scaffold, and this is a second copier with
            # its own idea of ownership. Two copiers, one directory, and the
            # generated half lost every run.
            if dst.exists():
                _remove_except(dst, output_path, preserve)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            # Track files
            for f in dst.rglob("*.ts"):
                copied.append(str(f.relative_to(output_path)))
        except Exception as e:
            errors.append(f"Failed to copy {subdir}: {e}")

    # Copy runtime-loader.ts
    loader_src = _TEMPLATE_DIR / "runtime-loader.ts"
    loader_dst = src_lib / "runtime-loader.ts"
    if loader_src.exists():
        try:
            shutil.copy2(loader_src, loader_dst)
            copied.append(str(loader_dst.relative_to(output_path)))
        except Exception as e:
            errors.append(f"Failed to copy runtime-loader: {e}")

    # Copy Data Engine
    data_engine_src = _TEMPLATE_DIR / "data-engine.ts"
    data_engine_dst = src_lib / "data-engine.ts"
    if data_engine_src.exists():
        try:
            shutil.copy2(data_engine_src, data_engine_dst)
            copied.append("src/lib/data-engine.ts")
        except Exception as e:
            errors.append(f"Failed to copy data-engine: {e}")

    # Slice-4 sensitive-column encrypt-at-rest helper. Copied into every
    # generated app so the data-engine can import it even when no sensitive
    # column is currently declared (the manifest is always emitted; the
    # runtime only calls into this module when a column is actually
    # sensitive — no crypto work happens for CRUD on plain columns).
    sensitive_src = _TEMPLATE_DIR / "sensitive-crypto.ts"
    sensitive_dst = src_lib / "sensitive-crypto.ts"
    if sensitive_src.exists():
        try:
            shutil.copy2(sensitive_src, sensitive_dst)
            copied.append("src/lib/sensitive-crypto.ts")
        except Exception as e:
            errors.append(f"Failed to copy sensitive-crypto: {e}")

    # Copy the file-storage module (pluggable disk/S3 backend for uploads)
    storage_src = _TEMPLATE_DIR / "storage.ts"
    storage_dst = src_lib / "storage.ts"
    if storage_src.exists():
        try:
            shutil.copy2(storage_src, storage_dst)
            copied.append("src/lib/storage.ts")
        except Exception as e:
            errors.append(f"Failed to copy storage: {e}")

    # Runtime error reporter — POSTs caught exceptions to Forge's ingest
    # endpoint so the self-healing loop can pick them up. The workflow
    # runtime imports this via `@/lib/error_reporter`, so it MUST be copied
    # into every generated app or the build fails at compile time.
    reporter_src = _TEMPLATE_DIR / "error_reporter.ts"
    reporter_dst = src_lib / "error_reporter.ts"
    if reporter_src.exists():
        try:
            shutil.copy2(reporter_src, reporter_dst)
            copied.append("src/lib/error_reporter.ts")
        except Exception as e:
            errors.append(f"Failed to copy error_reporter: {e}")

    # Global error boundary (Next.js App Router) — catches uncaught render
    # errors that escape every child boundary, reports them via the reporter
    # above, and shows a minimal recovery UI. Path is fixed by Next.js —
    # src/app/global-error.tsx or nothing.
    global_err_src = _TEMPLATE_DIR / "global-error.tsx"
    global_err_dst = output_path / "src" / "app" / "global-error.tsx"
    if global_err_src.exists():
        try:
            global_err_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(global_err_src, global_err_dst)
            copied.append("src/app/global-error.tsx")
        except Exception as e:
            errors.append(f"Failed to copy global-error: {e}")

    # Idempotent providers.tsx patch — ensures existing generated apps
    # (created before the reporter auto-bootstrap landed) get the side-
    # effect import that installs window handlers. New foundations already
    # carry it via app-foundation/src/app/providers.tsx.
    providers_dst = output_path / "src" / "app" / "providers.tsx"
    if providers_dst.exists():
        try:
            _ensure_providers_imports_reporter(providers_dst)
        except Exception as e:
            errors.append(f"Failed to patch providers.tsx reporter import: {e}")

    # Deterministic DB seed (admin login + demo data). Authoritative — every app
    # needs a login account or it's unusable; this guarantees one regardless of any
    # LLM seed step. start.sh runs it. See backend/templates/runtime/seed.ts.
    seed_src = _TEMPLATE_DIR / "seed.ts"
    seed_dst = output_path / "src" / "db" / "seed.ts"
    if seed_src.exists():
        try:
            seed_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(seed_src, seed_dst)
            copied.append("src/db/seed.ts")
        except Exception as e:
            errors.append(f"Failed to copy seed: {e}")

    # Copy /api/health/db endpoint — deploy-time smoke probe.
    # After Vercel reports READY, the deploy provider hits this to catch the
    # "green build, empty database" class of failure. See vercel_provider.py.
    health_src = _TEMPLATE_DIR / "api-health" / "route.ts"
    health_dst = output_path / "src" / "app" / "api" / "health" / "db" / "route.ts"
    if health_src.exists():
        try:
            health_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(health_src, health_dst)
            copied.append("src/app/api/health/db/route.ts")
        except Exception as e:
            errors.append(f"Failed to copy health/db route: {e}")

    # Copy Event Registry
    event_reg_src = _TEMPLATE_DIR / "event-registry.ts"
    event_reg_dst = src_lib / "event-registry.ts"
    if event_reg_src.exists():
        try:
            shutil.copy2(event_reg_src, event_reg_dst)
            copied.append("src/lib/event-registry.ts")
        except Exception as e:
            errors.append(f"Failed to copy event-registry: {e}")

    # Copy Data Engine helpers subdirectory (aggregations, saved-views, etc.)
    data_engine_helpers_src = _TEMPLATE_DIR / "data-engine"
    data_engine_helpers_dst = src_lib / "data-engine"
    if data_engine_helpers_src.exists():
        try:
            if data_engine_helpers_dst.exists():
                shutil.rmtree(data_engine_helpers_dst)
            shutil.copytree(data_engine_helpers_src, data_engine_helpers_dst)
            for f in data_engine_helpers_dst.rglob("*.ts"):
                copied.append(str(f.relative_to(output_path)))
        except Exception as e:
            errors.append(f"Failed to copy data-engine helpers: {e}")

    # Generate catch-all Data API route
    try:
        # Emit the registry's alias set FIRST — both the API route and the SSR
        # data-init import it so every entity registers under every known form.
        _generate_entity_aliases_module(output_path)
        if (output_path / "src" / "lib" / "entity-aliases.ts").exists():
            copied.append("src/lib/entity-aliases.ts")
        # Emit the FK-role authority the runtime reads to decide auto-fill vs.
        # domain Select — a domain FK (target != users) is never user-filled.
        try:
            from services.fk_semantics import emit_fk_roles_module
            wrote = emit_fk_roles_module(str(output_path))
            fk_roles_path = output_path / "src" / "lib" / "fk-roles.ts"
            if wrote is None and not fk_roles_path.exists():
                # No registry for this app — write a STUB so the runtime's static
                # `import { FK_ROLES } from "./fk-roles"` always resolves. With an
                # empty FK_ROLES every table is unknown, so the runtime falls back
                # to the legacy name-based auto-fill (registry-less apps unchanged).
                fk_roles_path.parent.mkdir(parents=True, exist_ok=True)
                fk_roles_path.write_text(
                    "// FK-role authority STUB — no registry was available for this app.\n"
                    "// FK_ROLES is empty, so every table is unknown and the runtime\n"
                    "// falls back to its legacy name-based owner-FK auto-fill.\n"
                    "export const FK_ROLES: Record<string, Record<string, string>> = {};\n\n"
                    "export function fkRole(table: string, col: string): string {\n"
                    '  return FK_ROLES[table]?.[col] || "plain";\n'
                    "}\n\n"
                    "export function isAutoFillFk(table: string, col: string): boolean {\n"
                    '  const r = fkRole(table, col); return r === "actor" || r === "tenancy";\n'
                    "}\n\n"
                    "export function isDomainFk(table: string, col: string): boolean {\n"
                    '  return fkRole(table, col) === "domain";\n'
                    "}\n",
                    encoding="utf-8",
                )
            if fk_roles_path.exists():
                copied.append("src/lib/fk-roles.ts")
        except Exception as e:  # noqa: BLE001 — never block runtime injection
            errors.append(f"Failed to emit fk-roles.ts: {e}")
        _generate_data_api_route(output_path)
        copied.append("src/app/api/data/[...path]/route.ts")
        _generate_data_init_module(output_path)
        copied.append("src/lib/data-init.ts")
    except Exception as e:
        errors.append(f"Failed to generate data API route: {e}")

    # Generate the workflow execution API route
    try:
        _generate_workflow_api_route(output_path)
        copied.append("src/app/api/workflows/[id]/execute/route.ts")
        copied.append("src/app/api/workflows/event/[event]/route.ts")
    except Exception as e:
        errors.append(f"Failed to generate workflow API routes: {e}")

    # Generate the WorkflowTriggerButton component
    try:
        _generate_workflow_trigger_button(output_path)
        copied.append("src/components/WorkflowTriggerButton.tsx")
    except Exception as e:
        errors.append(f"Failed to generate WorkflowTriggerButton: {e}")

    # Generate workflow list + detail API routes
    try:
        _generate_workflow_list_route(output_path)
        copied.append("src/app/api/workflows/route.ts")
        copied.append("src/app/api/workflows/[id]/route.ts")
    except Exception as e:
        errors.append(f"Failed to generate workflow list route: {e}")

    # Generate task inbox API route
    try:
        _generate_task_inbox_route(output_path)
        copied.append("src/app/api/tasks/route.ts")
    except Exception as e:
        errors.append(f"Failed to generate task inbox route: {e}")

    # Seed-status diagnostic — GET /api/_debug/seed-status compares
    # seed-plan.json expected rows against SELECT count(*). Makes silent
    # seed failures observable without direct DB access. Read-only, safe
    # to leave enabled in production.
    try:
        _generate_seed_status_route(output_path)
        copied.append("src/app/api/_debug/seed-status/route.ts")
    except Exception as e:
        errors.append(f"Failed to generate seed-status route: {e}")

    # Slice E T2: task inbox page + detail page + single-task GET route.
    # Ships /tasks, /tasks/[id], /api/tasks/[id] as static templates —
    # they read the workflow_tasks table from T1 and dispatch back
    # through the existing /api/workflows/[id]/execute resume path.
    try:
        copied.extend(_inject_task_inbox_pages(output_path))
    except Exception as e:
        errors.append(f"Failed to inject task inbox pages: {e}")

    # Inject file-storage: forge_files schema table + upload/download API routes.
    try:
        copied.extend(_inject_file_storage(output_path))
    except Exception as e:
        errors.append(f"Failed to inject file storage: {e}")

    # Rewrite any LLM-hallucinated workflow routes (non-existent getWorkflowEngine)
    # to the real stateless API so `next build` doesn't break.
    try:
        copied.extend(_fix_hallucinated_workflow_routes(output_path))
    except Exception as e:
        errors.append(f"Failed to fix hallucinated workflow routes: {e}")

    # Export rules from DB to filesystem so the runtime can load them
    try:
        _export_rules_to_filesystem(output_path, project_id=project_id)
        copied.append("rules/index.json")
    except Exception as e:
        errors.append(f"Failed to export rules: {e}")

    # Guarantee the dashboard shell has a MOBILE menu. The custom chrome rails
    # are `hidden md:flex` — below 768px they vanish with no nav — and the
    # template-floor copy is `if not exists`, so a regenerated (reused) output
    # dir keeps its old, mobile-less layout. This guard wires the mobile nav in
    # on EVERY generation (all pipelines run inject_runtime), fresh or reused.
    try:
        from services.shell_nav_guard import ensure_mobile_nav
        r = ensure_mobile_nav(output_path)
        if r.get("layout_patched") or r.get("mobilenav_copied"):
            copied.append("mobile-nav")
    except Exception as e:
        errors.append(f"Failed to ensure mobile nav: {e}")

    # Generate startup script (start.sh)
    try:
        _generate_startup_script(output_path)
        copied.append("start.sh")
    except Exception as e:
        errors.append(f"Failed to generate start.sh: {e}")

    # Generate .env.local if missing (infrastructure setup, not a code fix)
    try:
        _ensure_env_file(output_path, project_id=project_id)
        copied.append(".env.local")
    except Exception as e:
        errors.append(f"Failed to generate .env.local: {e}")

    # Substitute the __APP_NAME__ placeholder baked into the foundation templates
    # (sidebar brand, page <title>) with the real app name — otherwise the literal
    # "__APP_NAME__" shows in the running app's chrome.
    try:
        n = _substitute_app_name(output_path, app_name, domain)
        if n:
            copied.append(f"__APP_NAME__×{n}")
    except Exception as e:
        errors.append(f"Failed to substitute __APP_NAME__: {e}")

    # Substitute the __AUTH_IMAGE_URL__ placeholder (login/signup brand panel) with an
    # industry-relevant Unsplash image — preferring the design-spec's loginBackground,
    # else the domain default.
    try:
        m = _substitute_auth_image(output_path, domain)
        if m:
            copied.append(f"__AUTH_IMAGE_URL__×{m}")
    except Exception as e:
        errors.append(f"Failed to substitute __AUTH_IMAGE_URL__: {e}")

    # Substitute the login brand-panel copy (__AUTH_HEADLINE__ / __AUTH_SUBHEAD__)
    # with app-specific text so the sign-in page reads for THIS app, not generic
    # "Everything your team needs" corporate filler.
    try:
        c = _substitute_auth_copy(output_path, app_name, domain)
        if c:
            copied.append(f"__AUTH_COPY__×{c}")
    except Exception as e:
        errors.append(f"Failed to substitute auth copy: {e}")

    # Emit the library's --color-* design tokens into globals.css (else charts render black)
    try:
        if _emit_library_color_vars(output_path):
            copied.append("globals.css(--color-*)")
    except Exception as e:
        errors.append(f"Failed to emit --color-* tokens: {e}")

    logger.info(
        "Runtime injection: %d files copied, %d errors",
        len(copied),
        len(errors),
    )

    # Persist an injection manifest so downstream passes (notably
    # api_route_prune) have a single source of truth for which paths were
    # written here, instead of duplicating a hand-maintained allowlist.
    # This prevents the class of bug where a new infra route
    # (files/upload, notifications, documents/pdf, export/…) is silently
    # deleted because someone forgot to add it to _RESERVED.
    try:
        _write_injection_manifest(output_path, copied)
    except Exception:  # noqa: BLE001 — the manifest is a safety net; never fail injection over it
        logger.exception("Runtime injection: failed to write manifest")

    return {"copied": copied, "errors": errors}


_INJECTION_MANIFEST_REL = "contracts/runtime-injection-manifest.json"


def _write_injection_manifest(output_path: "Path", copied: list[str]) -> None:
    """Write the list of paths this injection wrote to
    contracts/runtime-injection-manifest.json. Later passes (prune, guards)
    read it as an allowlist — single source of truth, no hand-maintained
    duplicates.

    Shape (pinned so consumers can rely on it):
        {"paths": ["src/app/api/files/upload/route.ts", …],
         "version": 1}
    """
    manifest_path = output_path / _INJECTION_MANIFEST_REL
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Sort for deterministic diffs; dedupe defensively.
    entries = sorted(set(str(p) for p in copied if isinstance(p, str) and p))
    payload = {"version": 1, "paths": entries}
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _plan_has_commerce_flag(output_path: Path) -> bool:
    """True when the persisted plan.json marks any entity commerce:true.

    Used to gate the forge_cart runtime primitive so non-commerce apps
    (price-comparison, catalog browser) don't get spurious cart tables +
    /api/cart routes. Missing/malformed plan → False (safer default is
    to skip; a real commerce app will surface a clear "cart not wired"
    error and the fix is one commerce_flag update, whereas the reverse
    ships bloat we saw on nni3wjf6).
    """
    try:
        plan_path = output_path / "contracts" / "plan.json"
        if not plan_path.exists():
            plan_path = output_path / "plan.json"
        if not plan_path.exists():
            return False
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        entities = plan.get("entities")
        if isinstance(entities, dict):
            for spec in entities.values():
                if isinstance(spec, dict) and spec.get("commerce") is True:
                    return True
        elif isinstance(entities, list):
            for spec in entities:
                if isinstance(spec, dict) and spec.get("commerce") is True:
                    return True
    except Exception:
        return False
    return False


def _inject_file_storage(output_path: Path) -> list[str]:
    """Emit the forge_files metadata table + upload/download API routes so a
    generated app can receive, store and serve uploaded files (CVs, documents)."""
    written: list[str] = []

    # 1. forge_files schema table (drizzle-kit migrates it; data API auto-discovers it)
    schema_src = _TEMPLATE_DIR / "db" / "forge-files.schema.ts"
    schema_dir = output_path / "src" / "db" / "schema"
    if schema_src.exists() and schema_dir.exists():
        shutil.copy2(schema_src, schema_dir / "_forge_files.ts")
        written.append("src/db/schema/_forge_files.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_files" not in txt:
                barrel.write_text(
                    txt.rstrip() + '\nexport { forgeFiles } from "./_forge_files";\n',
                    encoding="utf-8",
                )

    # 2. upload route (multipart → storage)
    up_src = _TEMPLATE_DIR / "api-files" / "upload-route.ts"
    if up_src.exists():
        up_dst = output_path / "src" / "app" / "api" / "files" / "upload" / "route.ts"
        up_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(up_src, up_dst)
        written.append("src/app/api/files/upload/route.ts")

    # 3. download route (streams bytes by id)
    dn_src = _TEMPLATE_DIR / "api-files" / "download-route.ts"
    if dn_src.exists():
        dn_dst = output_path / "src" / "app" / "api" / "files" / "[id]" / "route.ts"
        dn_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dn_src, dn_dst)
        written.append("src/app/api/files/[id]/route.ts")

    # 3b. preview route (query-string based, accepts either UUID or absolute
    # URL) — same-origin proxy that iframe/object PDF embeds can always use
    # without mixed-content or CORS issues, and without needing schema
    # authors to conditionally build UUID-in-path vs URL-in-path URLs.
    pv_src = _TEMPLATE_DIR / "api-files" / "preview-route.ts"
    if pv_src.exists():
        pv_dst = output_path / "src" / "app" / "api" / "files" / "preview" / "route.ts"
        pv_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pv_src, pv_dst)
        written.append("src/app/api/files/preview/route.ts")

    # 4. notifications: forge_notifications table + /api/notifications route so the
    #    real send_notification / send_email workflow handlers have somewhere to land.
    ntf_schema = _TEMPLATE_DIR / "db" / "forge-notifications.schema.ts"
    if ntf_schema.exists() and schema_dir.exists():
        shutil.copy2(ntf_schema, schema_dir / "_forge_notifications.ts")
        written.append("src/db/schema/_forge_notifications.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_notifications" not in txt:
                barrel.write_text(
                    txt.rstrip() + '\nexport { forgeNotifications } from "./_forge_notifications";\n',
                    encoding="utf-8",
                )
    ntf_route = _TEMPLATE_DIR / "api-notifications" / "route.ts"
    if ntf_route.exists():
        ntf_dst = output_path / "src" / "app" / "api" / "notifications" / "route.ts"
        ntf_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ntf_route, ntf_dst)
        written.append("src/app/api/notifications/route.ts")

    # 5. scheduled triggers: forge_schedules table + /api/cron/tick route so
    #    schedule-typed workflows (preventive maintenance, reminders, SLA sweeps)
    #    fire when an external timer pings the endpoint.
    sch_schema = _TEMPLATE_DIR / "db" / "forge-schedules.schema.ts"
    if sch_schema.exists() and schema_dir.exists():
        shutil.copy2(sch_schema, schema_dir / "_forge_schedules.ts")
        written.append("src/db/schema/_forge_schedules.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_schedules" not in txt:
                barrel.write_text(
                    txt.rstrip() + '\nexport { forgeSchedules } from "./_forge_schedules";\n',
                    encoding="utf-8",
                )
    cron_route = _TEMPLATE_DIR / "api-cron" / "route.ts"
    if cron_route.exists():
        cron_dst = output_path / "src" / "app" / "api" / "cron" / "tick" / "route.ts"
        cron_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cron_route, cron_dst)
        written.append("src/app/api/cron/tick/route.ts")

    # R3 live UI: the SSE tail of the forge_events bus. LiveRefresh
    # (app-foundation src/lib/LiveRefresh.tsx, mounted by schema-page for
    # every page with dataSources) subscribes here and re-runs the server
    # component when one of its entities changes — push freshness instead
    # of navigation-only/polling.
    stream_route = _TEMPLATE_DIR / "api-events-stream" / "route.ts"
    if stream_route.exists():
        stream_dst = output_path / "src" / "app" / "api" / "events" / "stream" / "route.ts"
        stream_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stream_route, stream_dst)
        written.append("src/app/api/events/stream/route.ts")

    # 5a'. forge_events table: the durable event bus (R1). emitEvent
    #      (runtime/events/bus.ts) inserts one row per domain event; the
    #      data-engine write paths + emit_event workflow nodes both write
    #      here, and processPendingEvents dispatches event-triggered
    #      workflows / resumes wait_for_event pauses from it. Without the
    #      schema shipped, drizzle-kit never creates the table and every
    #      emit silently no-ops (by design — emission is non-fatal).
    ev_schema = _TEMPLATE_DIR / "db" / "forge-events.schema.ts"
    if ev_schema.exists() and schema_dir.exists():
        shutil.copy2(ev_schema, schema_dir / "_forge_events.ts")
        written.append("src/db/schema/_forge_events.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_events" not in txt:
                barrel.write_text(
                    txt.rstrip() + '\nexport { forgeEvents } from "./_forge_events";\n',
                    encoding="utf-8",
                )

    # 5b. workflow_tasks table: pending human tasks emitted by user_task
    #     nodes. persistPendingTask (runtime/workflows/index.ts:186) writes
    #     to this table on every paused workflow — without the schema
    #     shipped, drizzle-kit never generates a migration for it and the
    #     INSERT silently no-ops.
    wt_schema = _TEMPLATE_DIR / "db" / "workflow-tasks.schema.ts"
    if wt_schema.exists() and schema_dir.exists():
        shutil.copy2(wt_schema, schema_dir / "_forge_workflow_tasks.ts")
        written.append("src/db/schema/_forge_workflow_tasks.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_workflow_tasks" not in txt:
                barrel.write_text(
                    txt.rstrip() + '\nexport { forgeWorkflowTasks } from "./_forge_workflow_tasks";\n',
                    encoding="utf-8",
                )

    # 5b''. GET /api/workflow-runs — reads workflow_execution_log rows.
    wr_route = _TEMPLATE_DIR / "api-workflow-runs" / "route.ts"
    if wr_route.exists():
        wr_dst = output_path / "src" / "app" / "api" / "workflow-runs" / "route.ts"
        wr_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wr_route, wr_dst)
        written.append("src/app/api/workflow-runs/route.ts")

    # 5b'. workflow_execution_log table: one row per node execution.
    #      Powers the Properties-panel History tab in the platform editor.
    #      Contract: docs/superpowers/specs/2026-07-22-workflow-node-contracts.md § NC-4.
    wel_schema = _TEMPLATE_DIR / "db" / "workflow-execution-log.schema.ts"
    if wel_schema.exists() and schema_dir.exists():
        shutil.copy2(wel_schema, schema_dir / "_forge_workflow_execution_log.ts")
        written.append("src/db/schema/_forge_workflow_execution_log.ts")
        barrel = schema_dir / "index.ts"
        if barrel.exists():
            txt = barrel.read_text(encoding="utf-8")
            if "_forge_workflow_execution_log" not in txt:
                barrel.write_text(
                    txt.rstrip()
                    + '\nexport { forgeWorkflowExecutionLog } from "./_forge_workflow_execution_log";\n',
                    encoding="utf-8",
                )

    # 5d. forge_cart table + /api/cart + /api/cart/checkout: shopping-cart
    #     runtime primitive. Same shape as forge_files / forge_notifications —
    #     universal cart mechanic (per-user upsert-by-itemRef, subtotal, clear-
    #     on-checkout) exposed as a runtime service so generated storefront
    #     apps don't need to model Cart/CartItem/Order themselves. Checkout
    #     fires the `cart.checkout` workflow event; the app's own workflow
    #     (if defined) persists Orders, sends receipts, kicks off payment.
    #
    #     COMMERCE GATE (P1-G4): the cart primitive is only useful in apps
    #     that actually sell things. Non-commerce apps (price-comparison,
    #     catalog browser, review site) got the table + routes anyway,
    #     which showed up as unexplained `forge_cart` in psql. Gate on
    #     the plan's commerce flag — set by services/commerce_flag.py from
    #     explicit vocab (buy/sell/cart/checkout/order/…).
    _commerce_wanted = _plan_has_commerce_flag(output_path)
    if _commerce_wanted:
        cart_schema = _TEMPLATE_DIR / "db" / "forge-cart.schema.ts"
        if cart_schema.exists() and schema_dir.exists():
            shutil.copy2(cart_schema, schema_dir / "_forge_cart.ts")
            written.append("src/db/schema/_forge_cart.ts")
            barrel = schema_dir / "index.ts"
            if barrel.exists():
                txt = barrel.read_text(encoding="utf-8")
                if "_forge_cart" not in txt:
                    barrel.write_text(
                        txt.rstrip() + '\nexport { forgeCart } from "./_forge_cart";\n',
                        encoding="utf-8",
                    )
        cart_route = _TEMPLATE_DIR / "api-cart" / "route.ts"
        if cart_route.exists():
            cart_dst = output_path / "src" / "app" / "api" / "cart" / "route.ts"
            cart_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cart_route, cart_dst)
            written.append("src/app/api/cart/route.ts")
        cart_co_route = _TEMPLATE_DIR / "api-cart" / "checkout-route.ts"
        if cart_co_route.exists():
            cart_co_dst = output_path / "src" / "app" / "api" / "cart" / "checkout" / "route.ts"
            cart_co_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cart_co_route, cart_co_dst)
            written.append("src/app/api/cart/checkout/route.ts")

    # 5c. integrations resolver: thin env-only wrapper handlers call via
    #     getSecret(provider, key). Credentials themselves ARRIVE in
    #     .env.local — either at generation time or via the platform's
    #     "sync integrations" endpoint. No per-app DB, no admin UI in the
    #     generated app.
    #     Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
    int_lib_dir = _TEMPLATE_DIR / "integrations"
    if int_lib_dir.is_dir():
        int_lib_dst = output_path / "src" / "lib" / "integrations"
        int_lib_dst.mkdir(parents=True, exist_ok=True)
        for name in ("resolver.ts", "mcpClientPool.ts"):
            src = int_lib_dir / name
            if src.exists():
                shutil.copy2(src, int_lib_dst / name)
                written.append(f"src/lib/integrations/{name}")

    # 6. document + data export: pdf.ts helper + /api/documents/pdf (PDF render)
    #    + /api/export/[entity] (CSV). Powers invoices, certificates, reports.
    pdf_src = _TEMPLATE_DIR / "pdf.ts"
    if pdf_src.exists():
        pdf_dst = output_path / "src" / "lib" / "pdf.ts"
        pdf_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_src, pdf_dst)
        written.append("src/lib/pdf.ts")
    doc_route = _TEMPLATE_DIR / "api-documents" / "route.ts"
    if doc_route.exists():
        doc_dst = output_path / "src" / "app" / "api" / "documents" / "pdf" / "route.ts"
        doc_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(doc_route, doc_dst)
        written.append("src/app/api/documents/pdf/route.ts")
    exp_route = _TEMPLATE_DIR / "api-export" / "route.ts"
    if exp_route.exists():
        exp_dst = output_path / "src" / "app" / "api" / "export" / "[entity]" / "route.ts"
        exp_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exp_route, exp_dst)
        written.append("src/app/api/export/[entity]/route.ts")

    # Auto-pinger: instrumentation.ts (self-hosted/dev interval) + vercel.json cron
    # (serverless). Only written when absent so we never clobber a user's config.
    instr_src = _TEMPLATE_DIR / "instrumentation.ts"
    instr_dst = output_path / "src" / "instrumentation.ts"
    if instr_src.exists() and not instr_dst.exists():
        instr_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(instr_src, instr_dst)
        written.append("src/instrumentation.ts")
    vercel_src = _TEMPLATE_DIR / "vercel.json"
    vercel_dst = output_path / "vercel.json"
    if vercel_src.exists() and not vercel_dst.exists():
        shutil.copy2(vercel_src, vercel_dst)
        written.append("vercel.json")

    # Ensure the npm deps the injected files import are declared, else the app
    # fails to build ("Module not found: pdf-lib"). These files are copied in
    # unconditionally above, so their deps must be too — co-located here rather
    # than in a separate fixer that may not run.
    #   pdf.ts            -> pdf-lib                    (PDF generation)
    #   ai.ts             -> @anthropic-ai/sdk          (real AI workflow nodes; dynamic import)
    #   mcpClientPool.ts  -> @modelcontextprotocol/sdk  (agent mcp tool nodes)
    _ensure_package_deps(output_path, {
        "pdf-lib": "^1.17.1",
        "@anthropic-ai/sdk": "^0.32.0",
        "@modelcontextprotocol/sdk": "^1.30.0",
    })

    return written


def _ensure_package_deps(output_path: Path, deps: dict[str, str]) -> None:
    """Merge `deps` into the app's package.json dependencies (only adding keys
    that are absent, never downgrading an existing pin). No-op if the file is
    missing or unparseable."""
    pkg_json = output_path / "package.json"
    if not pkg_json.exists():
        return
    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        current = pkg.get("dependencies", {})
        added = [k for k in deps if k not in current]
        if not added:
            return
        for k in added:
            current[k] = deps[k]
        pkg["dependencies"] = current
        pkg_json.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        logger.info("Ensured package.json deps: %s", ", ".join(added))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not ensure package.json deps: %s", e)


def _generate_data_api_route(output_path: Path) -> None:
    """Create src/app/api/data/[...path]/route.ts — catch-all for all entity CRUD.

    Discovers schema files from src/db/schema/ and generates direct imports
    to avoid barrel circular dependency issues.
    """
    api_dir = output_path / "src" / "app" / "api" / "data" / "[...path]"
    api_dir.mkdir(parents=True, exist_ok=True)

    template_src = Path(__file__).parent.parent / "templates" / "data-api-route.ts"
    if not template_src.exists():
        logger.warning("data-api-route.ts template not found at %s", template_src)
        return

    content = template_src.read_text()

    # Discover schema files and replace barrel import with direct imports
    schema_dir = output_path / "src" / "db" / "schema"
    if schema_dir.exists():
        schema_files = [
            f.stem for f in schema_dir.glob("*.ts")
            if f.stem not in ("index", "relations") and not f.stem.startswith("_")
        ]
        if schema_files:
            # Build direct imports
            imports = "\n".join(
                f'    import("@/db/schema/{name}"),'
                for name in sorted(schema_files)
            )
            # Replace the barrel import block with direct imports
            old_block = """  // Dynamic import of all schema tables
  const schema = await import("@/db/schema");

  for (const [name, value] of Object.entries(schema)) {
    if (name.endsWith("Relations") || typeof value !== "object" || !value) continue;
    if (typeof value === "function") continue;
    // Drizzle tables have Symbol keys — detect them
    const symbols = Object.getOwnPropertySymbols(value);
    const keys = Object.keys(value as any);
    if (symbols.length === 0 && keys.length === 0) continue;
    // Must have at least one column-like property
    if (keys.length > 0) {
      const firstVal = (value as any)[keys[0]];
      if (!firstVal || typeof firstVal !== "object") continue;
    }
    registerEntity(name, value as any, { slug: name });
  }"""
            new_block = f"""  // Import schema files directly (auto-discovered, avoids barrel circular deps)
  const modules = await Promise.allSettled([
{imports}
  ]);

  for (const result of modules) {{
    if (result.status !== "fulfilled") continue;
    for (const [name, value] of Object.entries(result.value)) {{
      if (name.endsWith("Relations") || typeof value !== "object" || !value) continue;
      if (typeof value === "function") continue;
      registerEntity(name, value as any, {{ slug: name }});
    }}
  }}"""
            content = content.replace(old_block, new_block)

    # Register under the registry's alias set (authority-driven) when available, so
    # the API route resolves entities by every known form — matches the SSR path.
    if _build_entity_alias_map(output_path):
        content = content.replace(
            '} from "@/lib/data-engine";',
            '} from "@/lib/data-engine";\nimport { aliasesFor } from "@/lib/entity-aliases";',
            1,
        )
        content = content.replace(
            "registerEntity(name, value as any, { slug: name });",
            "registerEntity(name, value as any, { slug: name, aliases: aliasesFor(name) });",
        )

    (api_dir / "route.ts").write_text(content)


def _canon_key(s: str) -> str:
    """Separator-stripped, lowercased identity key — the same collapse the runtime
    ``registerEntity``/``getEntity`` use so snake/camel/Pascal/kebab all agree."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _build_entity_alias_map(output_path: Path) -> dict[str, list[str]]:
    """Read the canonical resource registry and return ``canon_key -> [alias, ...]``.

    Every entity carries four agreeing forms in the registry (``name`` Pascal,
    ``table`` snake, ``slug`` kebab, ``camel``). We index each entity's alias list
    under the canonical key of EVERY one of its forms, so a lookup by the JS export
    identifier (whatever casing the schema happened to use) always hits. This is the
    authority declaring which strings are the same entity — it closes the irregular
    -plural gap the runtime's heuristic pluraliser cannot bridge (Person↔people).

    **DV-BIND-2:** Also merges the route stem of every page whose ``entity`` matches
    a registry entry — the planner sometimes picks a shorter route than the entity
    name (``RecruitmentDrive`` → ``/drives``), and the data API endpoint uses the
    URL path segment as the slug (``/api/data/drives/{id}``). Without the route stem
    in the alias map, ``aliasesFor("drives")`` returns ``[]`` and the client-side
    fetch returns 404. Harvested from ``src/contracts/nav-flow.json``."""
    registry = None
    for rel in ("contracts/resource-registry.json", "registry.json"):
        p = output_path / rel
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("entities"), dict):
            registry = data
            break
    if not registry:
        return {}

    alias_map: dict[str, list[str]] = {}
    # Reverse index: canon(entity form) → the aliases list, so route-stem
    # augmentation below can find the right entity to attach to.
    entity_lists: dict[str, list[str]] = {}
    for key, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        forms = [
            key,
            ent.get("name"),
            ent.get("table"),
            ent.get("slug"),
            ent.get("camel"),
            ent.get("id"),
        ]
        aliases: list[str] = []
        for f in forms:
            if f and isinstance(f, str) and f not in aliases:
                aliases.append(f)
        if not aliases:
            continue
        for f in aliases:
            ck = _canon_key(f)
            if ck:
                alias_map.setdefault(ck, aliases)
                entity_lists.setdefault(ck, aliases)

    # DV-BIND-2: harvest route stems from the schema files themselves. Each
    # detail/list schema declares its ``dataSources[].entity`` — pair that with
    # the schema's file location (which mirrors the route) to know which
    # short-hand route stems point at each registered entity. Handles the
    # RecruitmentDrive → /drives class where the planner picked a route stem
    # ("drives") that isn't any of the entity's registered names, causing
    # /api/data/drives/<id> to 404.
    schemas_dir = output_path / "src" / "schemas"
    if schemas_dir.exists():
        for sp in schemas_dir.rglob("*.json"):
            # Skip config/registry files at the schemas root.
            if sp.name in ("registry.json", "shell.json", "nav-flow.json"):
                continue
            try:
                doc = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sources = doc.get("dataSources") if isinstance(doc, dict) else None
            if not isinstance(sources, list) or not sources:
                continue
            # First dataSource's entity is the page's focal entity.
            focal = next(
                (s.get("entity") for s in sources
                 if isinstance(s, dict) and isinstance(s.get("entity"), str)),
                None,
            )
            if not focal:
                continue
            ent_ck = _canon_key(focal)
            aliases = entity_lists.get(ent_ck)
            if not aliases:
                continue
            # Route stem = the file's top-level directory or basename.
            # ``src/schemas/drives.json`` → "drives"
            # ``src/schemas/drives/[id].json`` → "drives"
            rel = sp.relative_to(schemas_dir)
            stem = rel.parts[0] if len(rel.parts) > 1 else rel.stem
            if not stem or stem.startswith("[") or stem in ("login", "signup", "register"):
                continue
            stem_ck = _canon_key(stem)
            if not stem_ck or stem_ck in alias_map:
                continue
            if stem not in aliases:
                aliases.append(stem)
            alias_map[stem_ck] = aliases

    return alias_map


def _generate_entity_aliases_module(output_path: Path) -> None:
    """Emit src/lib/entity-aliases.ts — the registry's alias set, so both
    registration sites (SSR data-init + the data API route) register each entity
    under EVERY name the authority knows, instead of heuristically guessing."""
    alias_map = _build_entity_alias_map(output_path)
    if not alias_map:
        return
    entries = ",\n".join(
        f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in sorted(alias_map.items())
    )
    content = (
        "// Registry-declared entity aliases. Generated from resource-registry.json so\n"
        "// the data engine registers each entity under every known form (Pascal name,\n"
        "// snake table, kebab slug, camel accessor) — authority, not a heuristic guess.\n"
        "const ENTITY_ALIASES: Record<string, string[]> = {\n"
        f"{entries}\n"
        "};\n\n"
        "function canonKey(s: string): string {\n"
        '  return (s || "").replace(/[^a-z0-9]/gi, "").toLowerCase();\n'
        "}\n\n"
        "/** Every registry-declared form of the entity a schema export identifies. */\n"
        "export function aliasesFor(name: string): string[] {\n"
        "  return ENTITY_ALIASES[canonKey(name)] || [];\n"
        "}\n"
    )
    lib_dir = output_path / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "entity-aliases.ts").write_text(content, encoding="utf-8")
    logger.info("Wrote src/lib/entity-aliases.ts (%d entities)", len(set(map(id, alias_map.values()))))


def _generate_data_init_module(output_path: Path) -> None:
    """Emit src/lib/data-init.ts — a shared, idempotent entity-registry initialiser
    the SSR data path (data-engine-bridge) calls. Entities are otherwise only
    registered on the first API request, so server-side renders hit 'Unknown entity'
    and no data loads. Concurrency-safe via a single in-flight promise."""
    schema_dir = output_path / "src" / "db" / "schema"
    if not schema_dir.exists():
        return
    names = sorted(
        f.stem for f in schema_dir.glob("*.ts")
        if f.stem not in ("index", "relations") and not f.stem.startswith("_")
    )
    if not names:
        return
    imports = "\n".join(f'      import("@/db/schema/{n}"),' for n in names)
    # Register under the registry's alias set when it's available, so the SSR path
    # resolves every entity by every known form (authority-driven, not guessed).
    has_aliases = bool(_build_entity_alias_map(output_path))
    alias_import = 'import { aliasesFor } from "./entity-aliases";\n' if has_aliases else ""
    register_call = (
        "        registerEntity(name, value as any, { slug: name, aliases: aliasesFor(name) });\n"
        if has_aliases
        else "        registerEntity(name, value as any, { slug: name });\n"
    )
    content = (
        "// Shared data-engine initialiser. The SSR render path (data-engine-bridge)\n"
        "// does not pass through the API route where entities are registered, so it\n"
        "// must populate the registry itself. Idempotent + concurrency-safe.\n"
        'import { isInitialized, markInitialized, registerEntity } from "./data-engine";\n'
        f"{alias_import}\n"
        "let _initPromise: Promise<void> | null = null;\n\n"
        "export function ensureDataEngineInitialized(): Promise<void> {\n"
        "  if (isInitialized()) return Promise.resolve();\n"
        "  if (_initPromise) return _initPromise;\n"
        "  _initPromise = (async () => {\n"
        "    const modules = await Promise.allSettled([\n"
        f"{imports}\n"
        "    ]);\n"
        "    for (const result of modules) {\n"
        '      if (result.status !== "fulfilled") continue;\n'
        "      for (const [name, value] of Object.entries(result.value)) {\n"
        '        if (name.endsWith("Relations") || typeof value !== "object" || !value) continue;\n'
        '        if (typeof value === "function") continue;\n'
        f"{register_call}"
        "      }\n"
        "    }\n"
        "    try {\n"
        '      const { initializeEventRegistry } = await import("@/lib/event-registry");\n'
        "      await initializeEventRegistry();\n"
        "    } catch {\n"
        "      // workflows optional — data engine works standalone\n"
        "    }\n"
        "    markInitialized();\n"
        "  })();\n"
        "  return _initPromise;\n"
        "}\n"
    )
    (output_path / "src" / "lib" / "data-init.ts").write_text(content, encoding="utf-8")
    logger.info("Wrote src/lib/data-init.ts (SSR entity-registry initialiser)")


def _generate_workflow_api_route(output_path: Path) -> None:
    """Create src/app/api/workflows/[id]/execute/route.ts."""
    api_dir = output_path / "src" / "app" / "api" / "workflows" / "[id]" / "execute"
    api_dir.mkdir(parents=True, exist_ok=True)

    route_content = '''/**
 * Workflow Execution API Route
 *
 * POST /api/workflows/[id]/execute
 *
 * Body: { input: object, user?: { id, role, email }, taskId?: string }
 * Returns: WorkflowExecutionResult
 *
 * When a workflow pauses at an approval/user_task node, it creates a task
 * record in the workflow_tasks table. To resume, call this endpoint with
 * the taskId and the user's response data in input.
 *
 * Auto-generated by Tentoro Forge runtime injector.
 */

// Scan-style workflows chain AI vision + web search + N retailer scrapes and
// routinely outrun the 60s vercel.json default — the platform kills the
// function mid-run and the client never hears back. 300s is the Pro cap.
export const maxDuration = 300;

import { NextResponse } from "next/server";
import { triggerWorkflow } from "@/lib/workflows";
import { initializeRuntime } from "@/lib/runtime-loader";
import { db } from "@/db";
import { sql } from "drizzle-orm";
import { auth } from "@/auth";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  await initializeRuntime();

  try {
    const { id } = await params;
    const body = await request.json();
    const input = body.input || {};
    // Acting user from the SERVER session (never trust a client-sent user). The
    // workflow runtime defaults owner FKs (ownerId/landlordId/userId/…) from
    // ctx.user.id; without this an authed create hits a NOT NULL FK error.
    const session = await auth();
    const su = session?.user as { id?: string; role?: string; email?: string | null } | undefined;
    const user = su?.id ? { id: su.id, role: su.role, email: su.email ?? undefined } : body.user;
    let taskId = body.taskId;

    // ─── RESUME PATH ──────────────────────────────────────────────────────
    // Any dispatch that carries a taskId (Tasks-inbox completion) OR an
    // entity+__decision (row-level Approve/Reject button) is a resume, not a
    // fresh trigger. Every resume MUST seed the per-node completion markers
    // BEFORE calling triggerWorkflow — the engine walks from the trigger
    // node, and without the marker it re-executes every db_insert / email
    // / http_call upstream of the paused approval, then pauses again
    // (creating a duplicate task row while marking the original completed
    // in the block below). The pre-fix gate was `!taskId` — so the branch
    // that seeded markers was skipped exactly when the Tasks UI sent a
    // taskId, which is the common case. See workflow-audit P0-1.
    let resumeTaskRow: { id: string; node_id: string; process_variables: any } | null = null;
    try {
      if (taskId) {
        const res: any = await db.execute(sql`
          SELECT id, node_id, process_variables
          FROM workflow_tasks
          WHERE id = ${String(taskId)}::uuid
          LIMIT 1
        `);
        resumeTaskRow = (res.rows ?? res)?.[0] ?? null;
      } else if ((input as any).__decision) {
        const entityId = (input as any).entityId ?? (input as any).id ?? null;
        if (entityId) {
          const res: any = await db.execute(sql`
            SELECT id, node_id, process_variables
            FROM workflow_tasks
            WHERE entity_id = ${String(entityId)} AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
          `);
          resumeTaskRow = (res.rows ?? res)?.[0] ?? null;
          if (resumeTaskRow) taskId = resumeTaskRow.id;
        }
      }
    } catch (dbErr) {
      console.warn("[workflow] Could not resolve resume task:", dbErr);
    }

    if (resumeTaskRow) {
      const pv =
        typeof resumeTaskRow.process_variables === "string"
          ? JSON.parse(resumeTaskRow.process_variables || "{}")
          : resumeTaskRow.process_variables || {};
      // Merge order: stored process_variables first, fresh input overrides.
      // Then set completion markers so the engine's short-circuit fires on
      // every already-run node — including the paused approval itself.
      const markers: Record<string, unknown> = {
        [`__step_${resumeTaskRow.node_id}_completed`]: true,
        [`__step_${resumeTaskRow.node_id}_completedBy`]: user?.id ?? null,
      };
      if ((input as any).__decision !== undefined) {
        markers[`__step_${resumeTaskRow.node_id}_decision`] = (input as any).__decision;
        // The user_task/approval node reads `_output` as its returned value;
        // seed the decision here so downstream conditions can gate on it via
        // outputMappings without an entity re-query.
        markers[`__step_${resumeTaskRow.node_id}_output`] = { decision: (input as any).__decision };
      }
      Object.assign(input, { ...pv, ...input, ...markers });
    }

    // Detached mode (?detach=1): kick off the workflow and return
    // immediately so the caller (a "Queue for processing" style button)
    // navigates instantly instead of blocking for the whole pipeline.
    // Long-running steps (OCR + AI vision + external API calls) run in
    // the background; errors surface later on the record's detail page
    // (status=failed + errorMessage), not on the initial POST. Never
    // detach resumes (taskId present) — those need the completion write
    // that follows this call.
    const url = new URL(request.url);
    const detach = url.searchParams.get("detach") === "1" && !taskId;
    if (detach) {
      void triggerWorkflow(id, input, user).catch((err: unknown) => {
        console.error("[workflow] detached run failed:", err);
      });
      return NextResponse.json(
        { status: "queued", workflowId: id, mode: "detached" },
        { status: 202 },
      );
    }

    // triggerWorkflow persists a pending task itself if the workflow pauses.
    const result = await triggerWorkflow(id, input, user);

    // If resuming a completed task: update the task record
    if (taskId) {
      try {
        await db.execute(sql`
          UPDATE workflow_tasks
          SET status = 'completed',
              completed_by = ${user?.id || null},
              completed_at = NOW(),
              decision = ${input.__decision || null},
              response_data = ${JSON.stringify(input)}
          WHERE id = ${taskId}::uuid
        `);
      } catch (dbErr) {
        console.warn("[workflow] Could not update task:", dbErr);
      }
    }

    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
'''
    (api_dir / "route.ts").write_text(route_content, encoding="utf-8")

    # Also create the event-based trigger route
    event_dir = output_path / "src" / "app" / "api" / "workflows" / "event" / "[event]"
    event_dir.mkdir(parents=True, exist_ok=True)

    event_content = '''/**
 * Workflow Event Trigger Route
 *
 * POST /api/workflows/event/[event]
 *
 * Triggers all workflows whose trigger.type === "api_event" and
 * trigger.event matches the [event] path parameter.
 *
 * Auto-generated by Tentoro Forge runtime injector.
 */

import { NextResponse } from "next/server";
import { triggerWorkflowEvent } from "@/lib/workflows";
import { initializeRuntime } from "@/lib/runtime-loader";
import { auth } from "@/auth";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ event: string }> },
) {
  await initializeRuntime();

  try {
    const { event } = await params;
    const body = await request.json().catch(() => ({}));
    const input = body.input || body || {};
    // Acting user from the SERVER session (workflow runtime defaults owner FKs
    // from ctx.user.id — see the [id]/execute route).
    const session = await auth();
    const su = session?.user as { id?: string; role?: string; email?: string | null } | undefined;
    const user = su?.id ? { id: su.id, role: su.role, email: su.email ?? undefined } : body.user;

    const results = await triggerWorkflowEvent(event, input, user);

    return NextResponse.json({ event, results });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
'''
    (event_dir / "route.ts").write_text(event_content, encoding="utf-8")


def _generate_workflow_list_route(output_path: Path) -> None:
    """Create GET /api/workflows (list) and GET /api/workflows/[id] (detail)."""
    # List route
    list_dir = output_path / "src" / "app" / "api" / "workflows"
    list_dir.mkdir(parents=True, exist_ok=True)

    list_route = list_dir / "route.ts"
    if not list_route.exists():
        list_route.write_text('''/**
 * Workflow List API — serves workflow definitions from workflows/*.json.
 * GET /api/workflows → all workflows
 */
import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET() {
  try {
    const wfDir = path.join(process.cwd(), "workflows");
    const files = await fs.readdir(wfDir).catch(() => [] as string[]);
    const workflows = [];

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const content = await fs.readFile(path.join(wfDir, file), "utf-8");
        const wf = JSON.parse(content);
        workflows.push({
          id: wf.id,
          name: wf.name,
          description: wf.description,
          trigger: wf.definition?.trigger,
          nodeCount: wf.definition?.nodes?.length ?? 0,
          processVariableCount: wf.processVariables?.length ?? 0,
        });
      } catch { /* skip invalid files */ }
    }

    return NextResponse.json(workflows);
  } catch (error) {
    return NextResponse.json([], { status: 200 });
  }
}
''', encoding="utf-8")

    # Detail route
    detail_dir = list_dir / "[id]"
    detail_dir.mkdir(parents=True, exist_ok=True)

    detail_route = detail_dir / "route.ts"
    if not detail_route.exists():
        detail_route.write_text('''/**
 * Workflow Detail API — serves a single workflow definition.
 * GET /api/workflows/[id] → full workflow JSON with nodes, edges, processVariables
 */
import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const wfDir = path.join(process.cwd(), "workflows");
    const files = await fs.readdir(wfDir).catch(() => [] as string[]);

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const content = await fs.readFile(path.join(wfDir, file), "utf-8");
        const wf = JSON.parse(content);
        if (wf.id === id || file.replace(".json", "") === id) {
          return NextResponse.json(wf);
        }
      } catch { /* skip */ }
    }

    return NextResponse.json(
      { error: "Workflow not found" },
      { status: 404 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: String(error) },
      { status: 500 },
    );
  }
}
''', encoding="utf-8")


def _generate_seed_status_route(output_path: Path) -> None:
    """Emit src/app/api/_debug/seed-status/route.ts.

    Copies the template verbatim, then patches the two placeholders
    (`__SCHEMA_IMPORTS__` and `__SCHEMA_MODULES__`) with one entry per
    discovered `src/db/schema/*.ts` file — same discovery pattern as
    `_generate_data_api_route`. The route reads `seed-plan.json` at
    request time (no build-time bake-in) and reports
    expected-vs-actual row counts per table.
    """
    api_dir = output_path / "src" / "app" / "api" / "_debug" / "seed-status"
    api_dir.mkdir(parents=True, exist_ok=True)

    template_src = Path(__file__).parent.parent / "templates" / "seed-status-route.ts"
    if not template_src.exists():
        logger.warning("seed-status-route.ts template not found at %s", template_src)
        return

    content = template_src.read_text(encoding="utf-8")

    schema_dir = output_path / "src" / "db" / "schema"
    imports_block = ""
    modules_block = "const SCHEMA_MODULES: Array<Record<string, unknown>> = [];\n"
    if schema_dir.exists():
        schema_files = sorted(
            f.stem for f in schema_dir.glob("*.ts")
            if f.stem not in ("index", "relations") and not f.stem.startswith("_")
        )
        if schema_files:
            imports_block = "\n".join(
                f'import * as _seedschema_{i} from "@/db/schema/{name}";'
                for i, name in enumerate(schema_files)
            )
            modules_block = (
                "const SCHEMA_MODULES: Array<Record<string, unknown>> = ["
                + ", ".join(f"_seedschema_{i}" for i in range(len(schema_files)))
                + "];\n"
            )

    content = content.replace("// __SCHEMA_IMPORTS__", imports_block)
    content = content.replace("// __SCHEMA_MODULES__", modules_block)

    (api_dir / "route.ts").write_text(content, encoding="utf-8")


def _generate_task_inbox_route(output_path: Path) -> None:
    """Create GET /api/tasks — returns tasks for the logged-in user."""
    tasks_dir = output_path / "src" / "app" / "api" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    route_file = tasks_dir / "route.ts"
    if not route_file.exists():
        route_file.write_text('''/**
 * Task Inbox API — returns workflow tasks for the current user.
 *
 * GET /api/tasks?status=pending — filter by status
 *
 * Returns tasks where:
 * - assigneeId matches the logged-in user, OR
 * - assigneeRole matches the user's role, OR
 * - status is "pending" (for admin view)
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { db } from "@/db";
import { sql } from "drizzle-orm";

export async function GET(request: Request) {
  try {
    const session = await auth();
    if (!session?.user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status") || "pending";
    const userId = (session.user as any).id || "";
    const userRole = (session.user as any).role || "";

    // Query tasks assigned to this user by ID, role, or unassigned
    const tasks = await db.execute(sql`
      SELECT * FROM workflow_tasks
      WHERE status = ${status}
        AND (
          assignee_id = ${userId}::text
          OR assignee_role = ${userRole}
          OR (assignee_id IS NULL AND assignee_role IS NULL)
        )
      ORDER BY created_at DESC
      LIMIT 50
    `);

    return NextResponse.json(tasks.rows || []);
  } catch (error) {
    // Table may not exist — return empty
    return NextResponse.json([]);
  }
}
''', encoding="utf-8")


def _plan_has_task_entity(output_path: Path) -> bool:
    """True when the app's plan declares a DOMAIN entity named Task/Tasks —
    that entity's list page owns the /tasks route, so the workflow inbox
    must park at /inbox instead."""
    import json as _json
    plan_fp = output_path / "src" / "contracts" / "plan.json"
    try:
        plan = _json.loads(plan_fp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    ents = plan.get("entities") or {}
    names: list[str] = []
    if isinstance(ents, dict):
        for k, v in ents.items():
            names.append(str(k))
            if isinstance(v, dict) and v.get("table"):
                names.append(str(v["table"]))
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict):
                names.extend(str(e.get(x) or "") for x in ("name", "table"))
    return any(n.lower() in ("task", "tasks") for n in names)


def _inject_task_inbox_pages(output_path: Path) -> list[str]:
    """Slice E T2: copy the task-inbox page + detail page + single-task
    GET route into a generated app.

    Pairs with the /api/tasks list route (already emitted by
    _generate_task_inbox_route above) and the workflow_tasks Drizzle
    schema (T1). The detail page submits back through the existing
    /api/workflows/[id]/execute resume path — no new engine hook.

    Idempotent: only writes each target if it does not already exist,
    so hand edits inside a generated app survive re-runs.
    """
    written: list[str] = []

    # Route-collision guard: when the app's DOMAIN has a Task entity
    # (project-management-ish plans), its list page owns /tasks — parking
    # the workflow-approval inbox there shadows the entity route with a
    # near-always-empty "your inbox is clear" page rendered OUTSIDE the
    # (dashboard) shell (no chrome). Seen live on cwx1stzz. In that case
    # the inbox relocates to /inbox; internal links are rewritten to match.
    slug = "inbox" if _plan_has_task_entity(output_path) else "tasks"

    inbox_src = _TEMPLATE_DIR.parent / "app-foundation" / "src" / "app" / "tasks" / "page.tsx"
    inbox_dst = output_path / "src" / "app" / slug / "page.tsx"
    if inbox_src.exists() and not inbox_dst.exists():
        inbox_dst.parent.mkdir(parents=True, exist_ok=True)
        inbox_dst.write_text(
            inbox_src.read_text(encoding="utf-8").replace("/tasks/", f"/{slug}/"),
            encoding="utf-8",
        )
        written.append(f"src/app/{slug}/page.tsx")

    detail_src = _TEMPLATE_DIR.parent / "app-foundation" / "src" / "app" / "tasks" / "[id]" / "page.tsx"
    detail_dst = output_path / "src" / "app" / slug / "[id]" / "page.tsx"
    if detail_src.exists() and not detail_dst.exists():
        detail_dst.parent.mkdir(parents=True, exist_ok=True)
        detail_dst.write_text(
            detail_src.read_text(encoding="utf-8").replace("/tasks/", f"/{slug}/"),
            encoding="utf-8",
        )
        written.append(f"src/app/{slug}/[id]/page.tsx")

    api_src = _TEMPLATE_DIR.parent / "api-tasks" / "id-route.ts"
    api_dst = output_path / "src" / "app" / "api" / "tasks" / "[id]" / "route.ts"
    if api_src.exists() and not api_dst.exists():
        api_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(api_src, api_dst)
        written.append("src/app/api/tasks/[id]/route.ts")

    return written


def _generate_workflow_trigger_button(output_path: Path) -> None:
    """Create src/components/WorkflowTriggerButton.tsx."""
    components_dir = output_path / "src" / "components"
    components_dir.mkdir(parents=True, exist_ok=True)

    component_content = '''"use client";

/**
 * WorkflowTriggerButton — reusable button that triggers a workflow.
 *
 * Usage:
 * ```tsx
 * <WorkflowTriggerButton
 *   workflowId="SurveyPublished"
 *   input={{ surveyId: survey.id }}
 *   label="Publish Survey"
 *   onSuccess={(result) => router.refresh()}
 * />
 * ```
 *
 * Auto-generated by Tentoro Forge runtime injector.
 */

import { useState } from "react";

interface WorkflowTriggerButtonProps {
  workflowId: string;
  input?: Record<string, unknown>;
  label: string;
  className?: string;
  onSuccess?: (result: any) => void;
  onError?: (error: string) => void;
}

export function WorkflowTriggerButton({
  workflowId,
  input = {},
  label,
  className,
  onSuccess,
  onError,
}: WorkflowTriggerButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleClick = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/workflows/${workflowId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input }),
      });
      const result = await res.json();

      if (!res.ok || result.error) {
        const msg = result.error || "Workflow failed";
        setError(msg);
        onError?.(msg);
      } else {
        onSuccess?.(result);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      onError?.(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className={
          className ||
          "inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium disabled:opacity-50"
        }
      >
        {loading ? "Running..." : label}
      </button>
      {error && (
        <p className="text-sm text-destructive mt-1">{error}</p>
      )}
    </>
  );
}
'''
    (components_dir / "WorkflowTriggerButton.tsx").write_text(
        component_content, encoding="utf-8"
    )


def _fix_hallucinated_workflow_routes(output_path: Path) -> list[str]:
    """Rewrite LLM-hallucinated workflow routes that call a non-existent
    stateful engine API.

    Agents sometimes emit `src/app/api/workflows/trigger/route.ts` importing
    ``getWorkflowEngine`` from ``@/lib/workflows/engine`` and calling
    ``engine.startWorkflow(...)`` / ``engine['instances']`` — none of which
    exist. The real runtime is stateless and function-based
    (``triggerWorkflow`` / ``triggerWorkflowEvent``). Such a route fails to
    compile and breaks ``next build`` for the whole app.

    This rewrites any workflow route that references ``getWorkflowEngine`` to a
    correct thin wrapper over the real API. Returns the list of fixed files.
    """
    fixed: list[str] = []
    workflows_api = output_path / "src" / "app" / "api" / "workflows"
    if not workflows_api.exists():
        return fixed

    canonical_trigger = '''/**
 * Workflow Trigger API — POST to start a workflow by id/name or fire an event.
 *
 * Rewritten by the runtime injector: the original used a non-existent stateful
 * engine API. The real runtime is stateless and function-based.
 *
 * Body: { workflowId?: string, eventName?: string, payload?: object }
 */
import { NextResponse } from "next/server";
import { triggerWorkflow, triggerWorkflowEvent } from "@/lib/workflows";
import { initializeRuntime } from "@/lib/runtime-loader";

export async function POST(request: Request) {
  await initializeRuntime();
  try {
    const body = await request.json();
    const { workflowId, eventName, payload } = body ?? {};

    if (!workflowId && !eventName) {
      return NextResponse.json(
        { error: "Either workflowId or eventName is required" },
        { status: 400 },
      );
    }

    if (workflowId) {
      const result = await triggerWorkflow(workflowId, payload || {}, body?.user);
      return NextResponse.json({ success: result.status !== "failed", result });
    }

    const results = await triggerWorkflowEvent(eventName, payload || {}, body?.user);
    return NextResponse.json({ success: true, results });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
'''

    for route_file in workflows_api.rglob("route.ts"):
        try:
            content = route_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if "getWorkflowEngine" not in content:
            continue
        # Only the manual trigger route gets the canonical body; any other
        # route that references the phantom engine is at least made to import
        # the real API so the build doesn't break on the missing symbol.
        if route_file.parent.name == "trigger":
            route_file.write_text(canonical_trigger, encoding="utf-8")
        else:
            patched = content.replace(
                'from "@/lib/workflows/engine"',
                'from "@/lib/workflows"',
            ).replace("getWorkflowEngine,", "").replace("getWorkflowEngine", "triggerWorkflow")
            route_file.write_text(patched, encoding="utf-8")
        fixed.append(str(route_file.relative_to(output_path)))
        logger.info("Fixed hallucinated workflow route: %s", route_file.name)

    return fixed


def _generate_startup_script(output_path: Path) -> None:
    """Create start.sh — single command to start everything."""
    script = '''#!/usr/bin/env bash
# Generated App Startup Script — Usage: ./start.sh
# Boots Postgres (Docker) on a FREE port, migrates, seeds, then runs Next.js.
# Self-contained: picks a non-conflicting DB port at runtime and exports
# DATABASE_URL so every CLI step (drizzle-kit, tsx seed, next) sees the same DB.

set -e

# printf '%b' interprets the \\033 colour escapes portably (plain `echo` on macOS
# prints them literally).
say() { printf '%b\\n' "$1"; }
GREEN="\\033[0;32m"; YELLOW="\\033[0;33m"; RED="\\033[0;31m"; NC="\\033[0m"

# --seed-only: boot Postgres + migrate + seed, then STOP (no dev server). Used by
# the chat "Seed demo data" action to populate the DB and surface the admin login.
SEED_ONLY=0
[ "$1" = "--seed-only" ] && SEED_ONLY=1

say "${GREEN}🚀 Starting generated app...${NC}"

# Derive the DB name from .env.local's DATABASE_URL (segment after the last '/'),
# so it matches the database docker-compose creates. Default: app.
# Every generated app used DB_NAME="app" and no COMPOSE_PROJECT_NAME, so the
# second app to run reused the FIRST one's container and database. Picking a
# free PORT isolates nothing when the container is shared: drizzle-kit found
# another app's tables and asked, interactively, whether `articles` was a
# rename of `bikes` — hanging the seed, and one keystroke away from renaming
# another application's table.
#
# Derived from the project directory (output/<project-id>/app), so it needs no
# substitution plumbing. Postgres will not take a leading digit or a dash.
DB_NAME="app_$(basename "$(dirname "$PWD")" | tr -c 'a-zA-Z0-9' '_')"
# Deliberately not read back from .env.local: assembly writes `/app` there for
# every application, which is the value that put two apps in one database.

# Pick a free host port for Postgres — every generated app otherwise hardcodes
# 5432 and collides the moment a second app is already running.
is_free() {
  if command -v lsof >/dev/null 2>&1; then ! lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else ! nc -z localhost "$1" >/dev/null 2>&1; fi
}
DB_PORT="${DB_PORT:-5432}"
if ! is_free "$DB_PORT"; then
  for p in $(seq 5432 5600); do
    if is_free "$p"; then DB_PORT="$p"; break; fi
  done
fi
export DB_PORT
# Names the compose project, and so the container: without it Docker derives
# it from the directory, which is `app` for every generated application.
export COMPOSE_PROJECT_NAME="$DB_NAME"
export PROJECT_DB_NAME="$DB_NAME"
export DATABASE_URL="postgresql://postgres:postgres@localhost:${DB_PORT}/${DB_NAME}"
say "${YELLOW}🔌 Database port: ${DB_PORT} (DATABASE_URL exported)${NC}"

# Write .env (read by docker compose for ${DB_PORT}, and by drizzle-kit which
# auto-loads .env) and sync .env.local's DATABASE_URL (read by next dev) so all
# tools agree on the same port — drizzle-kit/seed do NOT auto-load .env.local.
{ printf 'DB_PORT=%s\\n' "$DB_PORT"; printf 'DATABASE_URL=%s\\n' "$DATABASE_URL"; } > .env
if [ -f .env.local ]; then
  _tmp=$(mktemp); grep -vE '^DATABASE_URL=' .env.local > "$_tmp" 2>/dev/null || true
  printf 'DATABASE_URL=%s\\n' "$DATABASE_URL" >> "$_tmp"; mv "$_tmp" .env.local
fi

# 1. Start PostgreSQL (errors are shown, NOT swallowed).
if [ -f docker-compose.yml ]; then
  say "${YELLOW}📦 Starting PostgreSQL on :${DB_PORT}...${NC}"
  docker compose up -d || docker-compose up -d
  say "${YELLOW}⏳ Waiting for database...${NC}"
  for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
      say "${GREEN}✅ Database is ready${NC}"; break
    fi
    if [ "$i" -eq 30 ]; then say "${RED}❌ Database failed to start — run: docker compose logs${NC}"; exit 1; fi
    sleep 1
  done
else
  say "${YELLOW}ℹ️  No docker-compose.yml — using external DATABASE_URL${NC}"
fi

# 2. Install dependencies
#    --legacy-peer-deps: next-auth@4.24.15 declared a peerOptional bump of
#    nodemailer to ^7 while we pin ^6 (the version our SMTP handler is
#    tested against). Peer-optional means it only matters if you actually
#    use the Email provider — the flag lets npm ignore the noise. Mirrors
#    what vercel.json already does for production deploys.
if [ ! -d node_modules ]; then
  say "${YELLOW}📥 Installing dependencies...${NC}"
  npm install --legacy-peer-deps
  say "${GREEN}✅ Dependencies installed${NC}"
fi

# 3. Migrations (DATABASE_URL exported above → drizzle-kit sees it). --force keeps
#    drizzle-kit push non-interactive; a failed migration is FATAL (no tables = unusable).
if [ -f drizzle.config.ts ]; then
  say "${YELLOW}🔄 Running database migrations...${NC}"
  if npx drizzle-kit push --force; then
    say "${GREEN}✅ Migrations applied${NC}"
  else
    say "${RED}❌ Migration failed — the app needs its tables. Check DATABASE_URL + drizzle.config.ts schema path.${NC}"
    exit 1
  fi
fi

# 4. Seed (non-fatal; errors surfaced).
if [ -f src/db/seed.ts ]; then
  say "${YELLOW}🌱 Seeding database...${NC}"
  if npx tsx src/db/seed.ts; then
    say "${GREEN}✅ Database seeded${NC}"
  else
    say "${YELLOW}⚠️  Seeding failed (continuing) — login/seed data may be missing.${NC}"
  fi
fi

# --seed-only stops here: DB is up + seeded, admin login is ready.
if [ "$SEED_ONLY" = "1" ]; then
  say ""
  say "${GREEN}✅ Seed complete. Admin login:${NC}"
  say "${GREEN}   email:    ${SEED_ADMIN_EMAIL:-admin@example.com}${NC}"
  say "${GREEN}   password: ${SEED_ADMIN_PASSWORD:-admin1234}${NC}"
  say "SEEDED_OK"
  exit 0
fi

# 5. Start dev server
say ""
say "${GREEN}🌐 Starting Next.js dev server...${NC}"
say "${GREEN}   App:      http://localhost:3000${NC}"
say "${GREEN}   Database: localhost:${DB_PORT}${NC}"
say ""
npx next dev
'''
    script_path = output_path / "start.sh"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)  # Make executable


def _fix_common_agent_mistakes(output_path: Path) -> None:
    """Fix common mistakes agents make despite clear prompts.

    Agents sometimes use the wrong package or import pattern.
    This catches and fixes the most frequent issues.
    """
    fixes_applied = 0

    # Fix 1: src/db/index.ts — agents often use `pg` instead of `postgres`
    db_index = output_path / "src" / "db" / "index.ts"
    if db_index.exists():
        content = db_index.read_text(encoding="utf-8")
        if 'from "pg"' in content or "from 'pg'" in content or "drizzle-orm/node-postgres" in content:
            db_index.write_text(
                'import { drizzle } from "drizzle-orm/postgres-js";\n'
                'import postgres from "postgres";\n'
                'import * as schema from "./schema";\n'
                "\n"
                "const connectionString = process.env.DATABASE_URL!;\n"
                "\n"
                "export const client = postgres(connectionString, { prepare: false });\n"
                "export const db = drizzle(client, { schema });\n",
                encoding="utf-8",
            )
            fixes_applied += 1
            logger.info("Fixed src/db/index.ts: pg → postgres")

    # Fix 2: Check package.json has `postgres` not `pg`
    pkg_json = output_path / "package.json"
    if pkg_json.exists():
        import json as _json
        try:
            pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = pkg.get("dependencies", {})
            changed = False

            # Remove pg, add postgres if missing
            if "pg" in deps:
                del deps["pg"]
                changed = True
            if "@types/pg" in pkg.get("devDependencies", {}):
                del pkg["devDependencies"]["@types/pg"]
                changed = True
            if "postgres" not in deps:
                deps["postgres"] = "^3.4.0"
                changed = True

            # Ensure autoprefixer is present
            if "autoprefixer" not in deps and "autoprefixer" not in pkg.get("devDependencies", {}):
                deps["autoprefixer"] = "^10.4.0"
                changed = True

            # Ensure clsx + tailwind-merge present (for cn utility)
            if "clsx" not in deps:
                deps["clsx"] = "^2.1.0"
                changed = True
            if "tailwind-merge" not in deps:
                deps["tailwind-merge"] = "^2.0.0"
                changed = True

            # Anthropic SDK — real AI workflow nodes (ai_generate/classify/extract/decide).
            # Dynamically imported at runtime; app falls back to mock output if the key
            # is unset, but the package must be installed for real inference.
            if "@anthropic-ai/sdk" not in deps:
                deps["@anthropic-ai/sdk"] = "^0.32.0"
                changed = True

            # pdf-lib — pure-JS PDF generation (invoices, certificates, reports)
            # for the generate_document workflow action + /api/documents/pdf route.
            if "pdf-lib" not in deps:
                deps["pdf-lib"] = "^1.17.1"
                changed = True

            if changed:
                pkg["dependencies"] = deps
                pkg_json.write_text(_json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
                fixes_applied += 1
                logger.info("Fixed package.json: corrected dependencies")
        except Exception as e:
            logger.warning("Could not fix package.json: %s", e)

    # Fix 3: Ensure src/lib/utils.ts exists (cn utility)
    utils_file = output_path / "src" / "lib" / "utils.ts"
    if not utils_file.exists():
        utils_file.parent.mkdir(parents=True, exist_ok=True)
        utils_file.write_text(
            'import { type ClassValue, clsx } from "clsx";\n'
            'import { twMerge } from "tailwind-merge";\n'
            "\n"
            "export function cn(...inputs: ClassValue[]) {\n"
            "  return twMerge(clsx(inputs));\n"
            "}\n",
            encoding="utf-8",
        )
        fixes_applied += 1
        logger.info("Created src/lib/utils.ts (cn utility)")

    if fixes_applied > 0:
        logger.info("Fixed %d common agent mistakes", fixes_applied)


def _fix_tailwind_config(output_path: Path) -> None:
    """Fix Tailwind v3/v4 incompatibility in generated apps.

    The schema agent sometimes generates mixed v3+v4 configs.
    This normalizes everything to Tailwind v3 (stable).
    """
    # Fix globals.css: v4→v3 + @apply incompatibilities
    globals_css = output_path / "src" / "app" / "globals.css"
    if globals_css.exists():
        content = globals_css.read_text(encoding="utf-8")
        changed = False

        if '@import "tailwindcss"' in content:
            content = content.replace(
                '@import "tailwindcss";',
                "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
            )
            changed = True

        # Fix @apply border-border (Tailwind v3 doesn't have this utility)
        if "@apply border-border" in content:
            content = content.replace(
                "@apply border-border;",
                "border-color: hsl(var(--border));",
            )
            changed = True

        # Fix @apply bg-background text-foreground
        if "@apply bg-background text-foreground" in content:
            content = content.replace(
                "@apply bg-background text-foreground;",
                "background-color: hsl(var(--background));\n    color: hsl(var(--foreground));",
            )
            changed = True

        if changed:
            globals_css.write_text(content, encoding="utf-8")
            logger.info("Fixed globals.css: v4→v3, @apply→plain CSS")

    # Fix postcss.config.mjs: use tailwindcss + autoprefixer
    postcss = output_path / "postcss.config.mjs"
    if postcss.exists():
        content = postcss.read_text(encoding="utf-8")
        if "@tailwindcss/postcss" in content:
            postcss.write_text(
                '/** @type {import("postcss-load-config").Config} */\n'
                "const config = {\n"
                "  plugins: {\n"
                "    tailwindcss: {},\n"
                "    autoprefixer: {},\n"
                "  },\n"
                "};\n\n"
                "export default config;\n",
                encoding="utf-8",
            )
            logger.info("Fixed postcss.config.mjs: replaced v4 plugin with v3")

    # Ensure tailwind.config.ts maps the shadcn CSS-variable tokens (border,
    # background, primary, …) that globals.css and the components use via
    # @apply / className. A config with an empty `theme.extend: {}` has no
    # `border-border` class, so `@apply border-border` in globals.css fails to
    # compile and EVERY page 500s. Write a self-contained config when the file is
    # missing OR when it lacks the border token (repairs empty/template configs).
    tw_config = output_path / "tailwind.config.ts"
    needs_config = True
    if tw_config.exists():
        try:
            existing = tw_config.read_text(encoding="utf-8")
            # Rewrite when the shadcn token mapping is absent OR the content globs
            # don't scan the renderer dist — without that glob, Tailwind never
            # compiles the gap-*/utility classes the renderer's Stack/Grid emit, so
            # page spacing silently collapses.
            needs_config = (
                "hsl(var(--border))" not in existing
                or "@tentoroforge/renderer" not in existing
                # Missing the named type scale → Heading classes no-op; upgrade it.
                or "page-title" not in existing
            )
        except Exception:
            needs_config = True
    if needs_config:
        tw_config.write_text(_build_tailwind_config(output_path), encoding="utf-8")
        logger.info("Wrote shadcn tailwind.config.ts (CSS-var tokens + type scale + renderer/engine globs)")


def _humanize_app_name(raw: str | None) -> str:
    """Turn a module name / slug into a presentable app name.
    'task_manager' -> 'Task Manager'; falls back to 'App'."""
    s = (raw or "").strip()
    if not s:
        return "App"
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)  # split camelCase
    return " ".join(w.capitalize() for w in s.split()) or "App"


def _resolve_app_name(output_path: Path, app_name: str | None, domain: str | None = None) -> str:
    """The app's PRODUCT name, never its vertical.

    Most plans carry no real product name — appName/module_name is just the
    domain slug ("legaltech", "fitness"), so every generated app introduced
    itself by its industry: the loudest same-generator tell in the audit. A
    distinct user-supplied name always wins; otherwise use the design DNA's
    seeded brand name (e.g. LexFlow, TempoLab, CuraPath).
    """
    name = _humanize_app_name(app_name)
    dom = _humanize_app_name(domain) if domain else ""
    generic = name == "App" or (dom and name.lower() == dom.lower()) or (
        app_name or "").strip().lower() == (domain or "").strip().lower()
    if not generic:
        return name
    try:
        dna = json.loads((output_path / "src" / "contracts" / "design-dna.json")
                         .read_text(encoding="utf-8"))
        brand = ((dna.get("brand") or {}).get("name") or "").strip()
        if brand:
            return brand
    except Exception:  # noqa: BLE001 — brand naming must never fail generation
        pass
    return name


def _substitute_app_name(output_path: Path, app_name: str | None,
                         domain: str | None = None) -> int:
    """Replace the literal __APP_NAME__ placeholder across the generated app's text
    files with the real app name. Returns the number of files changed."""
    name = _resolve_app_name(output_path, app_name, domain)
    # Resolve a page-meta description too — the app-foundation layout ships
    # `description: "__APP_DESCRIPTION__"`, which was NEVER substituted (only
    # __APP_NAME__ was), so every app shipped the literal placeholder in its
    # <meta name="description">. Prefer a design-spec tagline, else a clean
    # default built from the app name.
    description = _resolve_app_description(output_path, name, domain)
    changed = 0
    src = output_path / "src"
    if not src.exists():
        return 0
    for f in src.rglob("*"):
        if f.suffix not in (".tsx", ".ts", ".jsx", ".js", ".json", ".css", ".mdx"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "__APP_NAME__" in text or "__APP_DESCRIPTION__" in text:
            new_text = text.replace("__APP_NAME__", name).replace("__APP_DESCRIPTION__", description)
            if new_text != text:
                f.write_text(new_text, encoding="utf-8")
                changed += 1
    return changed


def _resolve_app_description(output_path: Path, name: str, domain: str | None) -> str:
    """A human page-meta description for the generated app. Prefers a design-spec
    tagline/description; falls back to a clean default from the app name/domain."""
    try:
        ds = json.loads((output_path / "src" / "contracts" / "design-spec.json").read_text())
        for key in ("tagline", "description", "subtitle"):
            v = ds.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:160]
    except Exception:
        pass
    if domain:
        return f"{name} — a {domain} application"
    return f"{name} — built with TentoroForge"


def _resolve_login_image(output_path: Path, domain: str | None) -> str:
    """Industry-relevant login image: prefer the design-spec's loginBackground (set by
    the design agent), else the per-domain default."""
    try:
        ds = json.loads((output_path / "src" / "contracts" / "design-spec.json").read_text())
        url = (ds.get("imagery") or {}).get("loginBackground")
        if isinstance(url, str) and url.startswith("http"):
            return url
    except Exception:
        pass
    from services.industry_design import get_login_background
    return get_login_background(domain)


def _substitute_auth_copy(output_path: Path, app_name: str | None,
                          domain: str | None = None) -> int:
    """Fill the auth pages' copy placeholders per app.

    Brand-panel copy: __AUTH_HEADLINE__ / __AUTH_SUBHEAD__.
    Form copy: __AUTH_FORM_TITLE__ / __AUTH_FORM_SUB__ — from the design DNA's
    per-archetype authCopy, so no two apps greet users with the identical
    "Welcome back / Sign in to X" (a byte-identical subtree in the audit).
    """
    name = _resolve_app_name(output_path, app_name, domain)
    if name and name != "App":
        headline, subhead = f"Welcome to {name}", f"Sign in to continue to {name}."
    else:
        headline, subhead = "Welcome back", "Sign in to continue."

    form_title, form_sub = "Welcome back", f"Sign in to {name}" if name != "App" else "Sign in to continue"
    try:
        dna = json.loads((output_path / "src" / "contracts" / "design-dna.json")
                         .read_text(encoding="utf-8"))
        ac = dna.get("authCopy") or {}
        if ac.get("title"):
            form_title = str(ac["title"]).replace("{app}", name)
        if ac.get("sub"):
            form_sub = str(ac["sub"]).replace("{app}", name)
    except Exception:  # noqa: BLE001
        pass

    changed = 0
    for rel in ("src/app/login/page.tsx", "src/app/signup/page.tsx"):
        f = output_path / rel
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        original = text
        text = (text.replace("__AUTH_HEADLINE__", headline)
                    .replace("__AUTH_SUBHEAD__", subhead)
                    .replace("__AUTH_FORM_TITLE__", form_title)
                    .replace("__AUTH_FORM_SUB__", form_sub))
        if text != original:
            f.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def _substitute_auth_image(output_path: Path, domain: str | None) -> int:
    """Fill the auth pages' generation-time placeholders.

    Two substitutions:
      * ``__AUTH_LAYOUT__`` — the auth COMPOSITION chosen by this project's
        design DNA (split-editorial / centered-minimal / brand-wash /
        side-panel / top-anchored / split-reversed). This is what stops every
        generated app from opening on an identical sign-in screen.
      * ``__AUTH_IMAGE_URL__`` — legacy stock-photo placeholder, still filled
        for older templates that reference it (the current template paints its
        brand panel from the app's own palette instead).
    """
    changed = 0

    # The DNA's auth layout (written by the pipeline at design time).
    layout = "split-editorial"
    try:
        dna_path = output_path / "src" / "contracts" / "design-dna.json"
        if dna_path.exists():
            dna = json.loads(dna_path.read_text(encoding="utf-8"))
            cand = ((dna.get("layout") or {}).get("auth") or "").strip()
            if cand:
                layout = cand
    except Exception:  # noqa: BLE001 — never fail generation on design metadata
        pass

    url = None
    for rel in ("src/app/login/page.tsx", "src/app/signup/page.tsx"):
        f = output_path / rel
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        original = text
        if "__AUTH_LAYOUT__" in text:
            text = text.replace("__AUTH_LAYOUT__", layout)
        if "__AUTH_IMAGE_URL__" in text:
            if url is None:
                url = _resolve_login_image(output_path, domain)
            text = text.replace("__AUTH_IMAGE_URL__", url)
        if text != original:
            f.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def _mix_hex(hex_color: str, target: tuple[int, int, int], ratio: float) -> str:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return hex_color or "#000000"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    tr, tg, tb = target
    nr, ng, nb = (round(r + (tr - r) * ratio), round(g + (tg - g) * ratio), round(b + (tb - b) * ratio))
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _color_scale(hex_color: str, dark: bool = False) -> dict[str, str]:
    """A 100/200/500/800 scale from a base hex.

    Light mode: 100/200 are light tints (mixed toward white), 800 a dark shade.
    Dark mode the ramp INVERTS: 100/200 become deep tints that sit on a
    near-black canvas (Badge/Alert washes), 800 a bright shade for text/lines.
    Without this, dark apps rendered light-mode chips — white Badge washes and
    pale Chart fills floating on a charcoal page.
    """
    if dark:
        return {
            "100": _mix_hex(hex_color, (10, 12, 14), 0.78),
            "200": _mix_hex(hex_color, (10, 12, 14), 0.60),
            "500": hex_color,
            "800": _mix_hex(hex_color, (255, 255, 255), 0.45),
        }
    return {
        "100": _mix_hex(hex_color, (255, 255, 255), 0.85),
        "200": _mix_hex(hex_color, (255, 255, 255), 0.70),
        "500": hex_color,
        "800": _mix_hex(hex_color, (0, 0, 0), 0.45),
    }


def _emit_library_color_vars(output_path: Path) -> bool:
    """Emit the library's --color-* design-token CSS variables into globals.css from the
    design-spec palette. The library components (Chart series/axes, Badge, Alert, …) read
    var(--color-primary-500), var(--color-text-tertiary), etc. — the design agent only
    emits shadcn-style vars (--primary), so without these the charts render BLACK and
    status colours fall back. Idempotent."""
    css = output_path / "src" / "app" / "globals.css"
    if not css.exists():
        return False
    try:
        text = css.read_text(encoding="utf-8")
    except Exception:
        return False
    if "--color-primary-500" in text:
        return False
    pal: dict = {}
    try:
        ds = json.loads((output_path / "src" / "contracts" / "design-spec.json").read_text())
        pal = ds.get("colorPalette") or {}
    except Exception:
        pal = {}
    dflt = {"primary": "#5B4FCF", "secondary": "#64748B", "accent": "#F59E0B",
            "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
            "info": "#3B82F6",
            "border": "#E2E8F0", "textTertiary": "#94A3B8", "surface": "#FFFFFF"}
    # Dark-mode apps need the whole scale inverted (deep tints, bright shades)
    # and a dark surface — light chips on a charcoal canvas scream template.
    dark = False
    try:
        dna = json.loads((output_path / "src" / "contracts" / "design-dna.json").read_text())
        dark = dna.get("mode") == "dark"
        if dark:
            dflt["surface"] = (dna.get("color") or {}).get("surface") or "#15181c"
            dflt["border"] = (dna.get("color") or {}).get("border") or "#2a2f36"
            dflt["textTertiary"] = (dna.get("color") or {}).get("textTertiary") or "#8b94a1"
    except Exception:
        pass
    # The design agent sometimes annotates palette values with prose
    # (e.g. "#FFFFFF — card and panel background; white surfaces…"), which is
    # invalid as a CSS value and breaks the build. Extract just the color token.
    import re as _re
    def _color_only(v):
        if not isinstance(v, str):
            return v
        m = _re.search(r"#[0-9A-Fa-f]{3,8}\b|(?:rgb|hsl)a?\([^)]*\)", v)
        return m.group(0) if m else (v.strip().split() or [v])[0]
    g = lambda k: _color_only(pal.get(k) or dflt.get(k))
    lines = ["", "/* Library design tokens — the --color-* scale Chart/Badge/Alert read.",
             "   Mapped from the design-spec palette so components are themed, not black. */",
             ":root {"]
    for name in ("primary", "secondary", "accent", "error", "warning", "success", "info"):
        sc = _color_scale(g(name), dark=dark)
        for lvl in ("100", "200", "500", "800"):
            lines.append(f"  --color-{name}-{lvl}: {sc[lvl]};")
    lines += [f"  --color-text-tertiary: {g('textTertiary')};",
              f"  --color-border-default: {g('border')};",
              f"  --color-surface-1: {g('surface')};", "}", ""]
    css.write_text(text + "\n".join(lines), encoding="utf-8")
    return True


def _ensure_env_file(output_path: Path, project_id: str | None = None) -> None:
    """Create .env.local if it doesn't exist, with default values, and
    upsert the runtime-reporter keys (FORGE_URL, FORGE_PROJECT_ID) so
    the client-side error reporter always has somewhere to POST.

    Idempotent — existing user values for FORGE_URL / FORGE_PROJECT_ID
    are preserved, missing lines are appended, other keys are never
    touched. Runs on both first-generation (creates the file) and
    re-generation (appends only what's missing)."""
    import os
    env_file = output_path / ".env.local"

    forge_url = os.environ.get("FORGE_URL") or os.environ.get("FORGE_BACKEND_URL") or "http://localhost:6500"
    forge_project_id = project_id or ""

    if env_file.exists():
        # Re-generation path — upsert reporter keys, leave the rest alone.
        _upsert_env_keys(env_file, {
            "FORGE_URL": forge_url,
            "FORGE_PROJECT_ID": forge_project_id,
        })
        return

    # Use a concrete port: postgres-js can't expand shell vars at runtime.
    db_port = "5432"

    import base64
    import secrets
    auth_secret = secrets.token_hex(32)
    # Slice-4: an AES-256 key (32 raw bytes → base64) for encrypt-at-rest of
    # any `sensitive: true` column. Generated per project so the app works
    # out-of-box; the user rotates by pasting a fresh key on
    # /settings/integrations (writes SENSITIVE_ENCRYPTION_KEY via the
    # platform_integrations flow). See TODO(sensitive-rotation) in
    # src/lib/sensitive-crypto.ts — versioned rotation is a future slice.
    sensitive_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")

    env_content = f"""# Generated by Tentoro Forge — edit as needed
DATABASE_URL=postgresql://postgres:postgres@localhost:{db_port}/app
NEXTAUTH_SECRET={auth_secret}
NEXTAUTH_URL=http://localhost:3000

# Sensitive-column encryption (Slice-4). Base64 of a 32-byte AES-256 key.
# Rotate via /settings/integrations (a new key requires re-encrypting every
# existing sensitive row — out of scope for this slice; see the crypto
# module for the TODO). NEVER commit a real key to git.
SENSITIVE_ENCRYPTION_KEY={sensitive_key}

# Runtime error reporter — POSTs runtime crashes back to Forge so the
# self-healing loop can pick them up. Both must be set; blank = reporter
# silently no-ops (see src/lib/error_reporter.ts).
FORGE_URL={forge_url}
FORGE_PROJECT_ID={forge_project_id}

# AI workflow nodes (ai_generate/classify/extract/decide). Set your key to enable
# real inference; without it, AI nodes return deterministic mock output.
ANTHROPIC_API_KEY=
FORGE_AI_MODEL=claude-sonnet-4-6

# File uploads. Bytes go to disk here by default; set FORGE_S3_BUCKET (and install
# @aws-sdk/client-s3) to use S3 instead. Metadata always lives in the forge_files table.
FORGE_UPLOAD_DIR=./data/uploads
# FORGE_S3_BUCKET=
# FORGE_S3_REGION=us-east-1

# Workflow notifications persist to the forge_notifications table (see /api/notifications).
# send_email sends real email when RESEND_API_KEY is set; otherwise it persists an in-app
# notification instead. No key → alerts still work, just in-app.
# RESEND_API_KEY=
# FORGE_EMAIL_FROM=notifications@yourdomain.com

# Scheduled workflows (trigger.type "schedule") fire when GET/POST /api/cron/tick is hit.
# Drive it from Vercel Cron, a crontab curl, or an uptime pinger. Set CRON_SECRET to require
# a Bearer token / ?secret= on that endpoint.
# CRON_SECRET=
"""
    env_file.write_text(env_content, encoding="utf-8")
    logger.info("Created .env.local at %s", env_file)


def _ensure_providers_imports_reporter(providers_file: Path) -> None:
    """Guarantee providers.tsx imports `@/lib/error_reporter` for side
    effects — the reporter's module-level bootstrap installs
    window.onerror + unhandledrejection handlers, so a missing import
    means client-side crashes never reach Forge. Idempotent — no-op
    when the import is already present."""
    try:
        text = providers_file.read_text(encoding="utf-8")
    except Exception:
        return
    if 'from "@/lib/error_reporter"' in text or "from '@/lib/error_reporter'" in text:
        return  # already imported (typed import) — bootstrap runs
    if 'import "@/lib/error_reporter"' in text or "import '@/lib/error_reporter'" in text:
        return  # already side-effect imported
    # Insert the import after the "use client" pragma if present, else at top.
    lines = text.splitlines()
    insert_at = 0
    for i, ln in enumerate(lines[:5]):
        stripped = ln.strip()
        if stripped in ('"use client";', "'use client';"):
            insert_at = i + 1
            break
    marker = '// Auto-added by runtime_injector: side-effect import installs\n' \
             '// window.onerror + unhandledrejection reporting for self-heal.\n' \
             'import "@/lib/error_reporter";'
    lines.insert(insert_at, marker)
    providers_file.write_text("\n".join(lines) + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    logger.info("Patched providers.tsx to import error_reporter for browser bootstrap")


def _upsert_env_keys(env_file: Path, updates: dict[str, str]) -> None:
    """Append/replace ``KEY=value`` lines in a .env-style file. Only
    replaces a line if the existing value is empty; a user-set value
    (even if different) is preserved. Missing keys get appended."""
    try:
        text = env_file.read_text(encoding="utf-8")
    except Exception:
        text = ""
    lines = text.splitlines()
    have: dict[str, int] = {}
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        have[k.strip()] = i

    changed = False
    for k, v in updates.items():
        if k in have:
            existing_line = lines[have[k]]
            _, _, existing_val = existing_line.partition("=")
            if existing_val.strip() == "" and v:
                # Only fill in blanks — never clobber a user-set value.
                lines[have[k]] = f"{k}={v}"
                changed = True
        else:
            if not changed and lines and lines[-1] != "":
                lines.append("")  # tidy separator
            lines.append(f"{k}={v}")
            changed = True
    if changed:
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Upserted %d key(s) in %s", len(updates), env_file)


def _fetch_project_rules_sync(project_id: str) -> list[dict[str, Any]]:
    """Read a project's active rules straight from the project_rules table.

    Editor-authored rules (condition_action / decision_table, source='manual')
    are stored ONLY in the DB — never in registry.json — so without this they
    would never ship into the generated app. rules_agent syncs the AI rules to
    the same table BEFORE inject_runtime runs, so the DB is the complete source
    (AI + manual). Sync psycopg2 read because inject_runtime is synchronous;
    best-effort — any failure falls back to the registry.
    """
    import os

    import psycopg2  # type: ignore

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return []
    # asyncpg URL -> plain libpq URL for psycopg2
    url = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, rule_type, model_name, field_name, config, is_active "
            "FROM project_rules WHERE project_id = %s AND is_active = true",
            (project_id,),
        )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            cfg = row[5]
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            out.append({
                "id": str(row[0]),
                "name": row[1],
                "rule_type": row[2],
                "model_name": row[3],
                "field_name": row[4],
                "config": cfg or {},
                "is_active": bool(row[6]),
            })
        return out
    finally:
        conn.close()


# Rule types the runtime engine + editor understand. Kept in sync with
# routers.rules.VALID_RULE_TYPES; duplicated here so this sync helper has no
# import cycle with the router.
_SYNC_VALID_RULE_TYPES = {
    "validation", "access", "business", "computed", "state_machine", "trigger",
    "condition_action", "decision_table",
}


def create_project_rule_sync(project_id: str, rule: dict[str, Any]) -> dict[str, Any]:
    """Insert one ProjectRule into the platform DB synchronously (psycopg2).

    Used by the Smith `create_business_rule` tool, which runs in a sync worker
    thread and therefore can't await the async ORM. Returns
    ``{"ok": True, "id": <uuid>}`` on success or ``{"ok": False, "error": ...}``.
    Never raises — the caller surfaces the error to the user.
    """
    import os
    import uuid as _uuid

    name = str(rule.get("name") or "").strip()
    rule_type = str(rule.get("rule_type") or "").strip()
    if not name:
        return {"ok": False, "error": "rule name is required"}
    if rule_type not in _SYNC_VALID_RULE_TYPES:
        return {"ok": False, "error": f"invalid rule_type {rule_type!r}; must be one of {sorted(_SYNC_VALID_RULE_TYPES)}"}
    config = rule.get("config")
    if not isinstance(config, dict):
        return {"ok": False, "error": "config must be an object"}

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return {"ok": False, "error": "DATABASE_URL not set — cannot persist the rule"}
    url = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    try:
        import psycopg2  # type: ignore
        from psycopg2.extras import Json  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"psycopg2 unavailable: {e}"}

    rid = str(_uuid.uuid4())
    try:
        conn = psycopg2.connect(url)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"db connect failed: {e}"}
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO project_rules "
            "(id, project_id, name, rule_type, model_name, field_name, config, is_active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                rid, project_id, name, rule_type,
                rule.get("model_name"), rule.get("field_name"),
                Json(config), bool(rule.get("is_active", True)),
            ),
        )
        conn.commit()
        return {"ok": True, "id": rid}
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "error": f"insert failed: {e}"}
    finally:
        conn.close()


def _export_rules_to_filesystem(output_path: Path, project_id: str | None = None) -> None:
    """Export project rules to the app's /rules/index.json for the runtime loader.

    Prefers the project_rules DB (complete: AI + editor-authored 'manual' rules)
    when a project_id is available; falls back to registry.json otherwise. This
    is what makes Business Rules editor rules actually ship into the app.
    """
    rules_dir = output_path / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    # Registry rules are the fallback (and the only source for project-less runs).
    rules: list[dict[str, Any]] = []
    registry_path = output_path / "registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            rules = registry.get("rules", []) or []
        except Exception:
            pass

    # The DB is the complete, authoritative source when we know the project.
    if project_id:
        try:
            db_rules = _fetch_project_rules_sync(project_id)
            if db_rules:
                rules = db_rules
                logger.info(
                    "[rules] exported %d rule(s) from DB for project %s",
                    len(db_rules), project_id,
                )
        except Exception as exc:  # noqa: BLE001 — never break generation over rules
            logger.warning("[rules] DB rule export failed, using registry: %s", exc)

    payload = json.dumps(rules, indent=2)
    (rules_dir / "index.json").write_text(payload, encoding="utf-8")
    # ALSO write under src/ so the rules survive Next's serverless output-file
    # tracing on Vercel (the app-root rules/ dir is otherwise dropped from the
    # function bundle → rules silently disabled in production). loadRules reads
    # whichever of the two it finds first. next.config's outputFileTracingIncludes
    # names both dirs.
    try:
        src_rules_dir = output_path / "src" / "rules"
        src_rules_dir.mkdir(parents=True, exist_ok=True)
        (src_rules_dir / "index.json").write_text(payload, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — never break generation over rules
        logger.warning("[rules] src/rules mirror failed: %s", exc)
