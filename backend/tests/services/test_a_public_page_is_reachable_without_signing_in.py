"""A page declared public gets a door that is not inside the gate.

THE MIDDLEWARE OPENED THE DOOR AND THE LAYOUT CLOSED IT. `project_middleware`
builds its matcher from what each page declares, so a page with
`access: "public"` was correctly excluded from the gate. But Next resolves a
one-segment URL against `src/app/(dashboard)/[entity]/page.tsx`, and that
group's layout begins `if (!session) redirect("/login")` — it has no notion of
a public route. So the visitor the page was written for got a sign-in screen,
and `entity_access`'s `"*"` readers and `launch_roles`'s `"*"` launchers, both
already projected for exactly that visitor, were unreachable.

A static segment outranks a dynamic one in Next's matcher, so a file at
`src/app/nurse-registration/page.tsx` is what the request resolves to — and it
sits outside the group, and therefore outside the gate.
"""
import json
from pathlib import Path

import pytest

from services.blueprint.projection import (project_middleware,
                                           project_public_routes)
from services.blueprint.service import BlueprintService

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def _page(pid, route, access="public", **over):
    return {"id": pid, "name": route.strip("/") or "Home", "route": route,
            "purpose": "a page", "access": access, **over}


@pytest.fixture
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="APP-1",
                                name="Bright Care", domain="care")
    s.doc["designSystem"] = {"colors": {"primary": "#0a7"}}
    s.doc["pages"] = [
        _page("PAGE-001", "/nurse-registration"),
        _page("PAGE-002", "/nurse-registration/[id]"),
        _page("PAGE-003", "/master-data", access="authenticated"),
    ]
    s.save()
    return s


# --------------------------------------------------------------------------- #
# the defect this exists for
# --------------------------------------------------------------------------- #

def test_the_gate_this_routes_around_is_still_there():
    """If the dashboard layout ever learns what a public route is, this
    projector's whole reason changes — so the reason is a check, not a
    comment."""
    layout = (TEMPLATES / "app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert 'if (!session) redirect("/login");' in layout
    assert "public" not in layout.split("export default async function")[1][:800], (
        "the layout has grown some notion of a public route — re-read "
        "project_public_routes before trusting it")


def test_the_middleware_and_the_route_file_say_the_same_thing(svc, tmp_path):
    """Two projections, one statement. The matcher lets the request in; the
    route file is what it lands on."""
    app_root = tmp_path / "app"
    project_middleware(svc.doc, app_root)
    out = project_public_routes(svc.doc, app_root)

    middleware = (app_root / "src/middleware.ts").read_text()
    assert "nurse-registration" in middleware
    assert "src/app/nurse-registration/page.tsx" in out["files"]


# --------------------------------------------------------------------------- #
# what it writes
# --------------------------------------------------------------------------- #

def test_a_public_page_gets_a_door_outside_the_group(svc, tmp_path):
    app_root = tmp_path / "app"
    out = project_public_routes(svc.doc, app_root)

    assert out["files"] == ["src/app/nurse-registration/[id]/page.tsx",
                            "src/app/nurse-registration/page.tsx"]
    for rel in out["files"]:
        assert "(dashboard)" not in rel, "a public page inside the gated group"
        assert (app_root / rel).is_file()


def test_an_authenticated_page_keeps_the_route_it_had(svc, tmp_path):
    """Only public pages get a file. Everything else still resolves to
    `(dashboard)/[entity]`, which is where its rail and its gate are."""
    app_root = tmp_path / "app"
    project_public_routes(svc.doc, app_root)
    assert not (app_root / "src/app/master-data").exists()


def test_the_root_is_left_alone(svc, tmp_path):
    """The optional catch-all already serves "/" from outside the group, so a
    public root page was the one case that always worked. Writing
    `src/app/page.tsx` would shadow the catch-all — which is why every build
    deletes that file (`RETIRED_SCAFFOLD_FILES`)."""
    svc.doc["pages"].append(_page("PAGE-004", "/"))
    app_root = tmp_path / "app"
    out = project_public_routes(svc.doc, app_root)
    assert not (app_root / "src/app/page.tsx").exists()
    assert all("app/page.tsx" not in f for f in out["files"])


def test_a_detail_route_threads_its_id_the_way_the_catch_all_does(svc, tmp_path):
    """`data-engine-bridge` turns a detail page into `engine.findById` off the
    `id` search param, and `resolveCrumbHrefs` needs the concrete path. Both
    come through the internal Request, exactly as `[entity]/[id]` builds it."""
    app_root = tmp_path / "app"
    project_public_routes(svc.doc, app_root)
    body = (app_root / "src/app/nurse-registration/[id]/page.tsx").read_text()
    assert "params: Promise<{ id: string }>" in body
    assert "const path = `/nurse-registration/${encodeURIComponent(p.id)}`" in body
    assert "internal:?id=${encodeURIComponent(p.id)}&path=" in body
    assert 'renderSchemaPage("/nurse-registration/[id]"' in body


def test_the_page_renders_with_no_rail_and_somewhere_for_a_mark(svc, tmp_path):
    """`nav-flow` already says `shell: false` about a public page; nothing in
    the standalone app had ever honoured it. `PublicPageFrame` is what a page
    with no rail signs its name in — and it draws nothing at all unless the
    owner gave a logo."""
    app_root = tmp_path / "app"
    project_public_routes(svc.doc, app_root)
    body = (app_root / "src/app/nurse-registration/page.tsx").read_text()
    assert "PublicPageFrame" in body and "SideNav" not in body

    frame = (TEMPLATES / "app-foundation/src/components/PublicPageFrame.tsx").read_text()
    assert "if (!BRAND_LOGO) return <>{children}</>;" in frame


# --------------------------------------------------------------------------- #
# what it refuses
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("route", ["/login", "/signup", "/api/things", "/403"])
def test_a_route_the_scaffold_owns_is_refused_not_overwritten(svc, tmp_path, route):
    """Writing these would replace the sign-in screen with a form, or shadow
    the API the application talks to."""
    before = (TEMPLATES / "app-foundation/src/app/login/page.tsx").read_text()
    svc.doc["pages"] = [_page("PAGE-009", route)]
    app_root = tmp_path / "app"
    out = project_public_routes(svc.doc, app_root)
    assert out["files"] == [] and out["refused"] == [route]
    assert (TEMPLATES / "app-foundation/src/app/login/page.tsx").read_text() == before


@pytest.mark.parametrize("route", ["/../../etc", "/a/../b", "/a b/c", "/[id", "/."])
def test_a_route_that_is_not_a_directory_name_is_refused(svc, tmp_path, route):
    """`route` comes out of a JSON document and becomes a DIRECTORY NAME.

    The first version of the segment pattern was `[A-Za-z0-9._-]+`, which
    matches `..` — so `/a/../b` wrote its file one directory above the tree it
    was handed. The comment said the pattern refused traversal and the pattern
    did not, which is why this is a test and not a comment.
    """
    svc.doc["pages"] = [_page("PAGE-009", route)]
    app_root = tmp_path / "app"
    out = project_public_routes(svc.doc, app_root)
    assert out["files"] == [] and out["refused"] == [route]
    # Nothing anywhere, not merely nothing where we looked: a traversal writes
    # OUTSIDE the tree, so asserting the tree is empty would miss it.
    assert not list(tmp_path.rglob("page.tsx"))


# --------------------------------------------------------------------------- #
# what it takes back
# --------------------------------------------------------------------------- #

def test_a_page_that_stops_being_public_loses_its_door(svc, tmp_path):
    """The dangerous direction. A route file left behind keeps a page
    reachable without a session long after the document stopped saying so."""
    app_root = tmp_path / "app"
    project_public_routes(svc.doc, app_root)
    assert (app_root / "src/app/nurse-registration/page.tsx").is_file()

    for page in svc.doc["pages"]:
        page["access"] = "authenticated"
    out = project_public_routes(svc.doc, app_root)

    assert out["files"] == []
    assert out["removed"] == ["src/app/nurse-registration/[id]/page.tsx",
                              "src/app/nurse-registration/page.tsx"]
    # …and the empty directories with it, so Next stops walking them.
    assert not (app_root / "src/app/nurse-registration").exists()


def test_it_only_removes_the_files_it_wrote(svc, tmp_path):
    """The sweep walks every `page.tsx` under `src/app`. Without the marker it
    would delete the scaffold's sign-in screen the first time it ran."""
    app_root = tmp_path / "app"
    scaffold = app_root / "src/app/login/page.tsx"
    scaffold.parent.mkdir(parents=True, exist_ok=True)
    scaffold.write_text("export default function LoginPage() { return null; }\n")

    svc.doc["pages"] = [_page("PAGE-001", "/nurse-registration", access="authenticated")]
    out = project_public_routes(svc.doc, app_root)

    assert out["removed"] == [] and scaffold.is_file()


def test_re_running_it_changes_nothing(svc, tmp_path):
    app_root = tmp_path / "app"
    first = project_public_routes(svc.doc, app_root)
    bodies = {f: (app_root / f).read_text() for f in first["files"]}
    second = project_public_routes(svc.doc, app_root)
    assert second["files"] == first["files"] and second["removed"] == []
    assert {f: (app_root / f).read_text() for f in second["files"]} == bodies
