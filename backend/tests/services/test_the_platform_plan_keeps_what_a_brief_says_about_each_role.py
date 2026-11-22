"""A brief written in headings ("CUSTOMER (mobile app): ...") that says each role's platform outright. Found by giving Forge a
Zomato-like brief: the plan listed the driver twice (as "Driver" and "Delivery partner"), called the restaurant a "Merchant", sent
the admin to the phone because a paragraph called LIVE UPDATES came after the admin's section, lost the delivery partner's own
lines because its heading was longer than 60 characters (so they were read as the customer's), and ignored "(web dashboard)"."""
from __future__ import annotations

from services.blueprint import platform_plan

ZOMATO = """A food delivery platform: customers order from restaurants, restaurants cook, delivery partners (drivers) carry the food, and an admin runs it.

CUSTOMER (mobile app, Android and iOS):
- Registers, saves addresses, searches restaurants and orders.
- Follows the order live on a map once a driver is assigned.

DELIVERY PARTNER (mobile app, Android and iOS, built around the map):
- Goes online and offline. While online their live GPS position is shared.
- Gets a delivery request as a popup with a countdown. Accepts or rejects.
- Navigates to the restaurant, then to the customer, and completes the delivery with the customer's code.

RESTAURANT (web app for a desktop or tablet in the kitchen):
- Incoming orders appear in real time. Accepts or rejects, marks preparing, marks ready for pickup.
- Manages the menu and sees earnings and reports.

ADMIN (web dashboard):
- Overview of customers, restaurants, drivers and orders.
- Approves restaurants and drivers. Sees a live map of online drivers.

DISPATCH. When an order is ready the nearest drivers are alerted and the first to accept gets it.

LIVE UPDATES. When a customer places an order the restaurant sees it at once and the admin sees it in live order monitoring.
"""


def roles():
    return {r.role: r for r in platform_plan.analyse(ZOMATO).roles}


def test_a_driver_and_a_delivery_partner_are_one_role():
    got = roles()
    assert "Delivery partner" in got and "Driver" not in got


def test_the_restaurant_keeps_its_own_name():
    assert "Restaurant" in roles() and "Merchant" not in roles()


def test_a_platform_the_brief_states_is_kept():
    got = roles()
    assert got["Customer"].platform == "mobile"
    assert got["Delivery partner"].platform == "mobile"
    assert got["Restaurant"].platform == "web"
    assert got["Admin"].platform == "web"


def test_a_role_built_around_the_map_is_map_first_and_no_other_is():
    got = roles()
    assert got["Delivery partner"].experience == "map_first"
    assert all(r.experience == "screens" for name, r in got.items() if name != "Delivery partner")


def test_a_paragraph_with_its_own_title_does_not_belong_to_the_role_before_it():
    # LIVE UPDATES / DISPATCH come after the admin's section and are about everyone: they must not be credited to the admin
    admin = roles()["Admin"]
    assert "live updates" not in admin.phone


def test_a_long_heading_still_owns_its_lines():
    # the delivery partner's heading is longer than 60 characters; its lines were read as the customer's
    partner = roles()["Delivery partner"]
    assert any("navigat" in hit for hit in partner.phone)


def test_the_plan_for_such_a_brief_is_still_shown_and_names_the_restaurant():
    plan = platform_plan.analyse(ZOMATO)
    assert plan.needed and plan.surface == "web_native"
    text = platform_plan.question(plan)
    assert "Restaurant: Website" in text and "Delivery partner: Phone app. The phone app is built around the map" in text


def test_a_brief_that_states_nothing_is_still_inferred_as_before():
    plan = platform_plan.analyse("Customers book a ride. Drivers go online, accept rides and share live GPS location. Admins view reports and a dashboard.")
    by = {r.role: r for r in plan.roles}
    assert by["Driver"].platform == "mobile" and by["Driver"].experience == "map_first" and by["Admin"].platform == "web"
