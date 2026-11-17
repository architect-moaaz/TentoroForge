"""A phone screen is written only for a page someone with the phone app uses.

Zomato put the customer and the delivery partner on phones and the restaurant and the administrator on the
web. `native_page_subjects` still asked for a phone screen of EVERY page (36), the writers answered twenty-odd
screens for the restaurant's and the administrator's pages, and nothing ever showed them (2026-11-16).
"""
from services.blueprint.orchestrator import native_page_subjects


def _doc(native_roles):
    roles = [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Delivery Partner"},
             {"id": "ROLE-003", "name": "Restaurant Manager"}, {"id": "ROLE-004", "name": "Admin"}]

    def page(pid, route, who):
        return {"id": pid, "route": route, "name": route, "pattern": "entity_list", "access": "role_restricted", "users": who}

    return {
        "roles": roles,
        "mobile": {"native": {"enabled": True}, "nativeRoles": native_roles},
        "pages": [page("PAGE-001", "/restaurants", ["ROLE-001"]), page("PAGE-009", "/driver", ["ROLE-002"]),
                  page("PAGE-015", "/restaurant", ["ROLE-003"]), page("PAGE-022", "/admin", ["ROLE-004"])],
    }


def test_only_the_pages_of_roles_with_the_phone_app_are_asked_for():
    assert native_page_subjects(_doc(["Customer", "Delivery Partner"])) == ["PAGE-001", "PAGE-009"]


def test_with_no_plan_every_page_is_asked_for_as_before():
    assert native_page_subjects(_doc(None)) == ["PAGE-001", "PAGE-009", "PAGE-015", "PAGE-022"]


def test_an_app_that_is_not_native_asks_for_none():
    doc = _doc(["Customer"])
    doc["mobile"]["native"]["enabled"] = False
    assert native_page_subjects(doc) == []
