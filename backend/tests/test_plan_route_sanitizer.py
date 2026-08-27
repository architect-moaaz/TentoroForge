"""Plan-level route hygiene: unique + normalised routes before schema-gen."""
from agents.planner import _sanitize_page_routes


def test_normalises_colon_params():
    plan = {"pages": [{"name": "Order", "route": "/orders/:id"}]}
    _sanitize_page_routes(plan)
    assert plan["pages"][0]["route"] == "/orders/[id]"


def test_dedupes_collapsed_routes_using_page_identity():
    # The real failure mode: two distinct pages the planner gave the same route.
    plan = {"pages": [
        {"name": "Analytics", "entity": None, "route": "/dashboard"},
        {"name": "Portfolio", "entity": "Portfolio", "route": "/dashboard"},
    ]}
    _sanitize_page_routes(plan)
    routes = [p["route"] for p in plan["pages"]]
    assert routes[0] == "/dashboard"          # first keeps it
    assert routes[1] == "/portfolio"          # second disambiguated from its entity
    assert len(set(routes)) == 2              # unique


def test_second_collision_falls_back_to_numeric_suffix():
    plan = {"pages": [
        {"name": "A", "route": "/x"},
        {"name": "Report", "route": "/x"},
        {"name": "Report", "route": "/x"},   # same identity → needs -2
    ]}
    _sanitize_page_routes(plan)
    routes = [p["route"] for p in plan["pages"]]
    assert routes == ["/x", "/report", "/report-2"]


def test_missing_route_derived_from_identity():
    plan = {"pages": [{"name": "Settings Page", "route": ""}]}
    _sanitize_page_routes(plan)
    assert plan["pages"][0]["route"] == "/settings-page"


def test_unsafe_route_replaced_with_identity_slug():
    plan = {"pages": [{"name": "Reports", "route": "/../etc/passwd"}]}
    _sanitize_page_routes(plan)
    assert plan["pages"][0]["route"] == "/reports"


def test_leaves_distinct_valid_routes_untouched():
    plan = {"pages": [
        {"name": "Analytics", "route": "/analytics"},
        {"name": "Portfolio", "route": "/portfolio"},
        {"name": "Watchlist", "route": "/watchlist"},
    ]}
    _sanitize_page_routes(plan)
    assert [p["route"] for p in plan["pages"]] == ["/analytics", "/portfolio", "/watchlist"]


def test_idempotent():
    plan = {"pages": [
        {"name": "Analytics", "route": "/dashboard"},
        {"name": "Portfolio", "entity": "Portfolio", "route": "/dashboard"},
    ]}
    _sanitize_page_routes(plan)
    once = [p["route"] for p in plan["pages"]]
    _sanitize_page_routes(plan)
    assert [p["route"] for p in plan["pages"]] == once


def test_no_pages_is_noop():
    assert _sanitize_page_routes({}) == {}
    assert _sanitize_page_routes({"pages": "nope"}) == {"pages": "nope"}
