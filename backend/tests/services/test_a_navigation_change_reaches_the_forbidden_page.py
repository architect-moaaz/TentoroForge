"""A landing route changed after the build reaches the 403 page.

The 403, 404 and error pages send someone back to the application through a
`{{home_route}}` the build fills from the Blueprint when it lays the scaffold
down. The fill consumes the placeholder, and a change after the build never
re-copied the scaffold — so "open on Master Data" moved the rail, the route
graph and the root redirect, and the forbidden page still returned people to
the landing the app was built with. Every verb that re-projects the
navigation now re-lays and re-fills the edge pages through one helper."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint import assembly
from services.blueprint.ids import page_key
from services.blueprint.projection import landing_route, project_navigation, project_root_route
from services.blueprint.service import BlueprintService
from services.smith import navigation_change as nc


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"}]}]}
    form = s.upsert("pages", {"name": "Nurse Registration", "route": "/nurse-registration", "pattern": "form",
                              "purpose": "Register.", "actions": ["submit"], "data": {"primaryEntity": "ENTITY-001"}},
                    natural_key=page_key("/nurse-registration"))
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list",
                             "purpose": "All nurses.", "actions": ["view_record"], "data": {"primaryEntity": "ENTITY-001"}},
                   natural_key=page_key("/master-data"))
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/nurse-registration"},
                           "tree": [{"label": "Nurse Registration", "page": form["id"], "icon": "user-plus"},
                                    {"label": "Master Data", "page": lst["id"], "icon": "table"}]}
    s.save()
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app" / "src" / "app" / "(dashboard)").mkdir(parents=True)
    s._t = SimpleNamespace(form=form, lst=lst)
    return s


def _client(reply):
    def call(*, system, user, schema):
        return json.dumps(reply)
    return call


def _href(app, rel):
    text = (app / rel).read_text("utf-8")
    assert "{{" not in text, f"{rel} shipped a placeholder"
    return text


def test_a_changed_landing_route_reaches_the_forbidden_page(svc, tmp_path):
    app = tmp_path / "app"
    # THE BUILD: the scaffold laid down and filled from the Blueprint of the day.
    assembly.copy_scaffold(app, project_short_id="t")
    assembly.interpolate_edge_pages(app, svc.doc)
    assert 'const LANDING = "/nurse-registration";' in _href(app, "src/app/forbidden.tsx")
    # The fill consumed the placeholder: filling again finds nothing to fill.
    assert assembly.interpolate_edge_pages(app, svc.doc) == []

    # THE CHANGE, after the build.
    out = nc.change_navigation(svc, "open on Master Data", app_root=str(app),
                               client=_client({"tree": [{"label": "Nurse Registration", "page": svc._t.form["id"]},
                                                        {"label": "Master Data", "page": svc._t.lst["id"]}],
                                               "initialRoute": "/master-data", "note": ""}))
    assert out["landing"] == "/master-data"
    # The 403 page computes its link per role and falls back to the landing;
    # the 404 and error pages link to it outright.
    assert 'const LANDING = "/master-data";' in _href(app, "src/app/forbidden.tsx")
    for rel in ("src/app/error.tsx", "src/app/not-found.tsx"):
        assert 'href="/master-data"' in _href(app, rel), rel
    for rel in ("src/app/forbidden.tsx", "src/app/error.tsx", "src/app/not-found.tsx"):
        assert rel in out["edited_paths"]
    # …and the four doors agree: the rail, the route graph, the root, the 403.
    assert json.loads((app / "src/schemas/shell.json").read_text())["initialRoute"] == "/master-data"
    assert 'redirect("/master-data")' in (app / "src/app/(dashboard)/page.tsx").read_text()
    assert "Return to Med Registration" in _href(app, "src/app/forbidden.tsx")


def test_the_landing_is_read_from_the_key_the_blueprint_writes():
    """`navigation.initialRoute.default` is what the navigation agent writes and
    Smith's verb changes; the legacy keys still count, a dynamic route and "/"
    do not, and the fallback is the first page that is not an auth screen."""
    pages = [{"route": "/login"}, {"route": "/overview"}]
    assert landing_route({"navigation": {"initialRoute": {"default": "/master-data"}}, "pages": pages}) == "/master-data"
    assert landing_route({"navigation": {"initialRoute": {"default": "/nurses/[id]"}}, "pages": pages}) == "/overview"
    assert landing_route({"navigation": {"initialRoute": {"default": "/"}}, "pages": pages}) == "/overview"
    assert landing_route({"navigation": {"landing": "/home"}, "pages": pages}) == "/home"
    assert assembly._landing_route({"navigation": {"initialRoute": {"default": "/master-data"}}, "pages": pages}) == "/master-data"


def test_the_edge_pages_are_relaid_from_the_scaffold_before_the_fill(tmp_path):
    app = tmp_path / "app"
    doc = {"application": {"name": "Ledger"},
           "navigation": {"style": "sidebar", "initialRoute": {"default": "/books"},
                          "tree": [{"label": "Books", "page": "PAGE-001"}, {"label": "Entries", "page": "PAGE-002"}]},
           "pages": [{"id": "PAGE-001", "name": "Books", "route": "/books"},
                     {"id": "PAGE-002", "name": "Entries", "route": "/entries"}]}
    laid = assembly.relay_edge_pages(app, doc)
    assert "src/app/forbidden.tsx" in laid and "src/components/EdgePageFrame.tsx" in laid
    assert 'const LANDING = "/books";' in _href(app, "src/app/forbidden.tsx")
    assert 'href="/books"' in _href(app, "src/app/not-found.tsx")
    doc["navigation"]["initialRoute"]["default"] = "/entries"
    assembly.relay_edge_pages(app, doc)
    assert 'const LANDING = "/entries";' in _href(app, "src/app/forbidden.tsx")
    assert 'href="/entries"' in _href(app, "src/app/not-found.tsx")
    # One helper for every verb: the bundle writes all four doors.
    files = project_navigation(doc, app)["files"]
    assert {"src/schemas/shell.json", "src/contracts/nav-flow.json",
            "src/app/(dashboard)/page.tsx", "src/app/forbidden.tsx"} <= set(files)
    assert project_root_route(doc, app)["redirectsTo"] == "/entries"
