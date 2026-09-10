"""Nav routes must point at pages that actually exist (registry keys)."""
import json

from services.nav_route_reconcile_guard import reconcile_nav_routes


def _write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _nav(root, pages, **extra):
    obj = {"version": "1.0", "pages": pages, **extra}
    _write(root, "src/contracts/nav-flow.json", obj)


def _read_nav(root):
    return json.loads((root / "src/contracts/nav-flow.json").read_text(encoding="utf-8"))


def test_repoints_drifted_route_to_schemafile(tmp_path):
    # The real repro: route says /dashboard but schemaFile is analytics.json (=> /analytics).
    _write(tmp_path, "src/schemas/analytics.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "analytics", "route": "/dashboard", "schemaFile": "src/schemas/analytics.json", "shell": True},
    ])
    res = reconcile_nav_routes(str(tmp_path))
    assert res["remapped"] == 1
    assert _read_nav(tmp_path)["pages"][0]["route"] == "/analytics"


def test_pluralised_slug_repointed(tmp_path):
    # /watchlist-items → /watchlist (the generated file).
    _write(tmp_path, "src/schemas/watchlist.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "watchlist", "route": "/watchlist-items", "schemaFile": "src/schemas/watchlist.json", "shell": True},
    ])
    reconcile_nav_routes(str(tmp_path))
    assert _read_nav(tmp_path)["pages"][0]["route"] == "/watchlist"


def test_two_pages_collapsed_to_dashboard_both_fixed(tmp_path):
    _write(tmp_path, "src/schemas/analytics.json", {"root": {}})
    _write(tmp_path, "src/schemas/portfolio.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "analytics", "route": "/dashboard", "schemaFile": "src/schemas/analytics.json", "shell": True},
        {"id": "portfolio", "route": "/dashboard", "schemaFile": "src/schemas/portfolio.json", "shell": True},
    ])
    res = reconcile_nav_routes(str(tmp_path))
    assert res["remapped"] == 2
    routes = [p["route"] for p in _read_nav(tmp_path)["pages"]]
    assert routes == ["/analytics", "/portfolio"]


def test_leaves_correct_route_untouched(tmp_path):
    _write(tmp_path, "src/schemas/holdings.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "holdings", "route": "/holdings", "schemaFile": "src/schemas/holdings.json", "shell": True},
    ])
    res = reconcile_nav_routes(str(tmp_path))
    assert res["remapped"] == 0


def test_skips_page_whose_schemafile_missing(tmp_path):
    # No file on disk → don't trust the derived route, leave it alone.
    _nav(tmp_path, [
        {"id": "ghost", "route": "/dashboard", "schemaFile": "src/schemas/ghost.json", "shell": True},
    ])
    res = reconcile_nav_routes(str(tmp_path))
    assert res["remapped"] == 0
    assert _read_nav(tmp_path)["pages"][0]["route"] == "/dashboard"


def test_repoints_post_login_redirect(tmp_path):
    _write(tmp_path, "src/schemas/analytics.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "analytics", "route": "/dashboard", "schemaFile": "src/schemas/analytics.json", "shell": True},
    ], initialPage="analytics", post_login_redirect="/dashboard")
    reconcile_nav_routes(str(tmp_path))
    assert _read_nav(tmp_path)["post_login_redirect"] == "/analytics"


def test_fixes_root_page_redirect(tmp_path):
    _write(tmp_path, "src/schemas/analytics.json", {"root": {}})
    page = tmp_path / "src/app/page.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text('import { redirect } from "next/navigation";\n'
                    'export default function RootPage() { redirect("/dashboard"); }\n', encoding="utf-8")
    _nav(tmp_path, [
        {"id": "analytics", "route": "/dashboard", "schemaFile": "src/schemas/analytics.json", "shell": True},
    ], initialPage="analytics")
    res = reconcile_nav_routes(str(tmp_path))
    assert res["root_fixed"] is True
    assert 'redirect("/analytics")' in page.read_text(encoding="utf-8")


def test_gated_root_redirect_lands_on_shell_not_login(tmp_path):
    # Regression: root redirecting to /login loops an authenticated user back to
    # the login page. It must land on the post-login shell page instead.
    _write(tmp_path, "src/schemas/dashboard.json", {"root": {}})
    page = tmp_path / "src/app/page.tsx"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text('import { redirect } from "next/navigation";\n'
                    'export default function RootPage() { redirect("/login"); }\n', encoding="utf-8")
    _nav(tmp_path, [
        {"id": "login", "route": "/login", "schemaFile": "src/schemas/login.json", "shell": False},
        {"id": "dashboard", "route": "/dashboard", "schemaFile": "src/schemas/dashboard.json", "shell": True},
    ], initialPage="login", authGated=True, post_login_redirect="/dashboard")
    res = reconcile_nav_routes(str(tmp_path))
    assert res["landing"] == "/dashboard"
    assert 'redirect("/dashboard")' in page.read_text(encoding="utf-8")
    assert 'redirect("/login")' not in page.read_text(encoding="utf-8")


def test_idempotent(tmp_path):
    _write(tmp_path, "src/schemas/analytics.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "analytics", "route": "/dashboard", "schemaFile": "src/schemas/analytics.json", "shell": True},
    ])
    assert reconcile_nav_routes(str(tmp_path))["remapped"] == 1
    assert reconcile_nav_routes(str(tmp_path))["remapped"] == 0


def test_no_nav_flow_file_is_noop(tmp_path):
    assert reconcile_nav_routes(str(tmp_path)) == {"remapped": 0, "pages": 0, "landing": None}


# --- route-group landing materialization ----------------------------------
# When landing points at ``/dashboard`` and the app only has
# ``src/app/(dashboard)/page.tsx`` (a route GROUP, not a real segment),
# the redirect target is a phantom — the group root serves ``/``, not
# ``/dashboard``. Post-guard should MOVE the group's page.tsx down into
# a real ``dashboard/`` folder so the redirect target becomes live.

def test_group_landing_materialized_into_real_folder(tmp_path):
    # Nav declares /dashboard as landing.
    _write(tmp_path, "src/schemas/dashboard.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "dashboard", "route": "/dashboard", "schemaFile": "src/schemas/dashboard.json", "shell": True},
    ], initialFor={"__default__": "/dashboard"})
    # Group-root page.tsx exists but no real /dashboard folder.
    (tmp_path / "src/app/(dashboard)").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/page.tsx").write_text("export default function P(){return null}", encoding="utf-8")
    # Root redirect target that the guard will keep pointing at /dashboard.
    (tmp_path / "src/app/page.tsx").write_text('import {redirect} from "next/navigation"; export default function R(){redirect("/dashboard")}', encoding="utf-8")

    reconcile_nav_routes(str(tmp_path))

    assert not (tmp_path / "src/app/(dashboard)/page.tsx").exists()
    assert (tmp_path / "src/app/(dashboard)/dashboard/page.tsx").exists()


def test_group_root_page_purged_when_real_folder_already_exists(tmp_path):
    # A real /dashboard folder is present, so the group-root (dashboard)/page.tsx
    # is redundant — the real dashboard/page.tsx serves /dashboard. The group-
    # root page is a Next.js #58272 landmine (missing clientReferenceManifest at
    # build), so purge it while leaving the real /dashboard folder alone.
    _write(tmp_path, "src/schemas/dashboard.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "dashboard", "route": "/dashboard", "schemaFile": "src/schemas/dashboard.json", "shell": True},
    ], initialFor={"__default__": "/dashboard"})
    (tmp_path / "src/app/(dashboard)").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/page.tsx").write_text("export default function P(){return null}", encoding="utf-8")
    (tmp_path / "src/app/dashboard").mkdir(parents=True)
    (tmp_path / "src/app/dashboard/page.tsx").write_text("export default function D(){return null}", encoding="utf-8")
    (tmp_path / "src/app/page.tsx").write_text('import {redirect} from "next/navigation"; export default function R(){redirect("/dashboard")}', encoding="utf-8")

    reconcile_nav_routes(str(tmp_path))

    assert not (tmp_path / "src/app/(dashboard)/page.tsx").exists()  # PURGED (#58272 landmine)
    assert (tmp_path / "src/app/dashboard/page.tsx").exists()  # real dashboard route untouched


def test_group_landing_noop_when_landing_is_root(tmp_path):
    # Landing = "/" already triggers the "delete root page.tsx" path in
    # _fix_root_redirect; the materialize helper must NOT fire and clobber
    # the group root page.tsx.
    _write(tmp_path, "src/schemas/home.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "home", "route": "/", "schemaFile": "src/schemas/home.json", "shell": True},
    ], initialFor={"__default__": "/"})
    (tmp_path / "src/app/(dashboard)").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/page.tsx").write_text("export default function P(){return null}", encoding="utf-8")
    (tmp_path / "src/app/page.tsx").write_text('import {redirect} from "next/navigation"; export default function R(){redirect("/")}', encoding="utf-8")

    reconcile_nav_routes(str(tmp_path))

    # root page.tsx removed (self-loop fix), group page.tsx left alone —
    # it's the only thing serving / when landing == "/".
    assert not (tmp_path / "src/app/page.tsx").exists()
    assert (tmp_path / "src/app/(dashboard)/page.tsx").exists()


def test_group_root_page_purged_when_landing_is_unrelated_segment(tmp_path):
    # The 1h3jo42a scenario: landing is /services (a real segment inside the
    # (dashboard) group). The group-root (dashboard)/page.tsx isn't wired to
    # anything — the root redirect goes to /services — but its presence
    # triggers Next.js #58272 at build time. Guard must purge it.
    _write(tmp_path, "src/schemas/services.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "services", "route": "/services", "schemaFile": "src/schemas/services.json", "shell": True},
    ], initialFor={"__default__": "/services"})
    (tmp_path / "src/app/(dashboard)").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/page.tsx").write_text(
        'import {renderSchemaPage} from "@/lib/schema-page"; '
        'export default async function P(){return renderSchemaPage("/")}'
    )
    (tmp_path / "src/app/(dashboard)/services").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/services/page.tsx").write_text("export default function S(){return null}", encoding="utf-8")
    (tmp_path / "src/app/page.tsx").write_text(
        'import {redirect} from "next/navigation"; '
        'export default function R(){redirect("/services")}'
    )

    res = reconcile_nav_routes(str(tmp_path))

    assert not (tmp_path / "src/app/(dashboard)/page.tsx").exists()  # PURGED
    assert (tmp_path / "src/app/(dashboard)/services/page.tsx").exists()  # real page kept
    assert (tmp_path / "src/app/page.tsx").exists()  # root redirect kept
    assert res["purged_group_root_pages"] == ["src/app/(dashboard)/page.tsx"]


def test_materialized_landing_rewrites_render_schema_page_arg(tmp_path):
    """When _materialize_route_group_landing moves (dashboard)/page.tsx down
    to (dashboard)/dashboard/page.tsx, it must also rewrite the file's
    `renderSchemaPage("/")` argument to the new landing route so the schema
    lookup hits the registry key the schema pipeline actually emitted
    (`/dashboard`, not `/`). The live repro was qzdvdmje: file moved but
    argument stayed `"/"` → schema-page fell through to notFound() → 404.
    """
    # Nav-flow declares /dashboard as landing.
    _write(tmp_path, "src/schemas/dashboard.json", {"root": {}})
    _nav(tmp_path, [
        {"id": "dashboard", "route": "/dashboard", "schemaFile": "src/schemas/dashboard.json", "shell": True},
    ], entryPoint="dashboard")
    # Template-shape group root that hardcodes "/" (as the app-foundation template does).
    (tmp_path / "src/app/(dashboard)").mkdir(parents=True)
    (tmp_path / "src/app/(dashboard)/page.tsx").write_text(
        'import { renderSchemaPage } from "@/lib/schema-page";\n'
        'export default async function DashboardHome() {\n'
        '  return renderSchemaPage("/");\n'
        '}\n'
    )
    # Root redirects to landing (so the root/redirect fixer has something to work on).
    (tmp_path / "src/app/page.tsx").write_text(
        'import {redirect} from "next/navigation"; '
        'export default function R(){redirect("/dashboard")}'
    )

    reconcile_nav_routes(str(tmp_path))

    # File was moved DOWN into the real URL segment...
    assert not (tmp_path / "src/app/(dashboard)/page.tsx").exists()
    moved = tmp_path / "src/app/(dashboard)/dashboard/page.tsx"
    assert moved.exists()
    # ...and its renderSchemaPage argument was rewritten to the landing route.
    body = moved.read_text(encoding="utf-8")
    assert 'renderSchemaPage("/dashboard")' in body
    assert 'renderSchemaPage("/")' not in body
