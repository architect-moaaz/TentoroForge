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


def test_a_camel_case_param_is_an_ordinary_route():
    """`[scanId]` is plain Next.js. Refusing it failed HippieKit's build at
    `frontend` after 43 minutes of generation — four of its 27 routes used
    camelCase params — and took integration and assemble down with it."""
    from services.route_slug import slugify_route

    assert slugify_route("/scan/result/[scanId]") == "scan/result/[scanId]"
    assert slugify_route("/categories/[categoryId]/products") == "categories/[categoryId]/products"
    assert slugify_route("/Reports") == "Reports"


def test_what_the_rule_is_for_is_still_refused():
    """Capitals were never the danger; these are."""
    import pytest

    from services.route_slug import slugify_route

    for route in ("/notes/../etc", "/a/./b", "/notes/..", "/a b", "/a;rm -rf", "/a%2e%2e",
                  "/a\\\\b", "/a$b", "/a`b`", "/a'b"):
        with pytest.raises(ValueError):
            slugify_route(route)
