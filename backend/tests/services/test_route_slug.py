import pytest
from services.route_slug import slugify_route, route_from_slug

@pytest.mark.parametrize("route,expected", [
    ("/",                  "home"),
    ("/notes",             "notes"),
    ("/notes/new",         "notes/new"),
    ("/notes/[id]",        "notes/[id]"),
    ("/notes/[id]/edit",   "notes/[id]/edit"),
    ("/settings/profile",  "settings/profile"),
    ("//double//slash/",   "double/slash"),
    ("",                   "home"),
    ("/users-list",        "users-list"),
])
def test_slugify_route(route, expected):
    assert slugify_route(route) == expected

def test_slugify_route_rejects_unsafe():
    with pytest.raises(ValueError):
        slugify_route("/notes/../etc/passwd")
    with pytest.raises(ValueError):
        slugify_route("/notes; rm -rf /")

@pytest.mark.parametrize("slug,expected", [
    ("home",               "/"),
    ("notes",              "/notes"),
    ("notes/new",          "/notes/new"),
    ("notes/[id]/edit",    "/notes/[id]/edit"),
])
def test_route_from_slug_roundtrip(slug, expected):
    assert route_from_slug(slug) == expected
    assert slugify_route(route_from_slug(slug)) == slug
