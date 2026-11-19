"""Each role that has the phone app gets its own bar, and lands on its own first tab.

Zomato's phone app gave EVERYONE the customer's bar (Restaurants, My orders, Profile) and put the delivery
partner's screens behind More, so a driver signing in landed on restaurants and could not find the map
(2026-11-16). The bar now declares every role's tabs and shows the signed-in person's.
"""
import json

from services.blueprint import native_projection as n
from services.blueprint.native_projection import _kept_link


def _page(pid, route, name, who, pattern="entity_list"):
    p = {"id": pid, "route": route, "name": name, "pattern": pattern, "access": "role_restricted" if who else "authenticated"}
    if who:
        p["users"] = who
    return p


def _doc(native_roles=("Customer", "Delivery Partner")):
    return {
        "application": {"name": "Zomato"},
        "roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Delivery Partner"}, {"id": "ROLE-003", "name": "Admin"}],
        "mobile": {"native": {"enabled": True}, "nativeRoles": list(native_roles)},
        "navigation": {"mobile": "tabs", "tree": [
            {"label": "Restaurants", "page": "PAGE-001", "tab": True},
            {"label": "My orders", "page": "PAGE-005", "tab": True},
            {"label": "Help", "page": "PAGE-008", "tab": True},
            {"label": "Delivery", "page": "PAGE-009", "tab": True},
            {"label": "Earnings", "page": "PAGE-012", "tab": True},
            {"label": "Overview", "page": "PAGE-022"},
        ]},
        "pages": [
            _page("PAGE-001", "/restaurants", "Restaurants near me", ["ROLE-001"]),
            _page("PAGE-005", "/orders", "My orders", ["ROLE-001"]),
            _page("PAGE-008", "/support", "Help and support", []),
            _page("PAGE-009", "/driver", "Delivery home", ["ROLE-002"]),
            _page("PAGE-012", "/driver/earnings", "Driver earnings", ["ROLE-002"]),
            _page("PAGE-022", "/admin", "Admin overview", ["ROLE-003"]),
        ],
    }


def _names(rows):
    return [p["name"] for p in rows]


def test_two_phone_roles_each_get_their_own_bar():
    layouts = n.role_layouts(_doc())
    assert set(layouts) == {"Customer", "Delivery Partner"}
    customer_bar, _ = layouts["Customer"]
    driver_bar, _ = layouts["Delivery Partner"]
    assert _names(customer_bar)[:2] == ["Restaurants near me", "My orders"]
    assert "Delivery home" not in _names(customer_bar) and "Driver earnings" not in _names(customer_bar)
    assert _names(driver_bar)[:2] == ["Delivery home", "Driver earnings"]
    assert "Restaurants near me" not in _names(driver_bar) and "My orders" not in _names(driver_bar)


def test_a_page_for_everyone_comes_after_the_roles_own_pages():
    driver_bar, _ = n.role_layouts(_doc())["Delivery Partner"]
    assert _names(driver_bar).index("Help and support") > _names(driver_bar).index("Driver earnings")


def test_a_page_of_a_role_without_the_phone_app_is_in_nobodys_bar():
    for bar, more in n.role_layouts(_doc()).values():
        assert "Admin overview" not in _names(bar + more)


def test_the_generated_navigation_says_where_each_role_lands():
    module = n.navigation_module(_doc())
    assert '"Customer": "/restaurants"' in module
    assert '"Delivery Partner": "/driver"' in module
    assert "ROLE_TABS" in module and "ROLE_MORE" in module and "ROLE_HOME" in module


def test_every_roles_tab_has_a_route_file_in_the_tab_folder():
    routes = {p["route"] for p in n.tab_pages(_doc())}
    assert {"/restaurants", "/driver", "/driver/earnings"} <= routes


def test_one_phone_role_keeps_the_one_bar_it_always_had():
    doc = _doc(native_roles=("Customer",))
    assert n.role_layouts(doc) == {}
    module = n.navigation_module(doc)
    assert "export const ROLE_TABS: Readonly<Record<string, readonly string[]>> = {};" in module


def test_a_maps_key_put_in_app_json_survives_projecting_again(tmp_path):
    app_json = tmp_path / "app.json"
    app_json.write_text(json.dumps({"expo": {"android": {"config": {"googleMaps": {"apiKey": "kept-key"}}}}}), encoding="utf-8")
    written = json.dumps({"expo": {"name": "Zomato", "android": {"config": {"googleMaps": {"apiKey": ""}}}}})
    out = json.loads(_kept_link(app_json, written))
    assert out["expo"]["android"]["config"]["googleMaps"]["apiKey"] == "kept-key"


def test_a_key_the_platform_writes_is_not_replaced_by_an_old_one(tmp_path):
    app_json = tmp_path / "app.json"
    app_json.write_text(json.dumps({"expo": {"android": {"config": {"googleMaps": {"apiKey": "old"}}}}}), encoding="utf-8")
    written = json.dumps({"expo": {"android": {"config": {"googleMaps": {"apiKey": "new"}}}}})
    assert json.loads(_kept_link(app_json, written))["expo"]["android"]["config"]["googleMaps"]["apiKey"] == "new"
