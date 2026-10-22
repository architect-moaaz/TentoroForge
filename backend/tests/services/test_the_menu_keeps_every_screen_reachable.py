"""PlantPal (2026-10-22): the menu listed "Account Settings" from the first draft; a repair step judged that screen out of the
brief's scope, wrote Login over its entry and left the screen in the plan. The phone then had no way to reach it, no account tab
(the platform's own stood aside for the screen) and no way to sign out, and the menu listed Login and Sign Up beside the
application's own screens."""
import copy

from services.blueprint.menu_binding import bind_menu
from services.blueprint.native_projection import drawn_pages, has_account_tab, tab_pages

PAGES = [
    {"id": "PAGE-001", "name": "My Plants", "route": "/plants", "pattern": "entity_list", "access": "authenticated", "menuEntry": "My Plants"},
    {"id": "PAGE-002", "name": "Plant", "route": "/plants/[id]", "pattern": "record_workspace", "access": "authenticated"},
    {"id": "PAGE-003", "name": "Today", "route": "/today", "pattern": "entity_list", "access": "authenticated", "menuEntry": "Today"},
    {"id": "PAGE-004", "name": "Account Settings", "route": "/account", "pattern": "settings", "access": "authenticated",
     "menuEntry": "Account Settings"},
    {"id": "PAGE-005", "name": "Login", "route": "/login", "pattern": "auth", "access": "public"},
    {"id": "PAGE-006", "name": "Sign Up", "route": "/signup", "pattern": "auth", "access": "public"},
]
TREE = [
    {"label": "My Plants", "page": "PAGE-001", "roles": ["ROLE-001"], "tab": True},
    {"label": "Today", "page": "PAGE-003", "roles": ["ROLE-001"], "tab": True},
    {"label": "Login", "page": "PAGE-005", "roles": [], "tab": False},
    {"label": "Sign Up", "page": "PAGE-006", "roles": [], "tab": False},
]


def _doc(**over):
    doc = {"application": {"name": "PlantPal"}, "mobile": {"native": {"enabled": True}},
           "roles": [{"id": "ROLE-001", "name": "Plant Owner"}],
           "security": {"authentication": "email_password"},
           "navigation": {"tree": copy.deepcopy(TREE)}, "pages": copy.deepcopy(PAGES)}
    doc.update(over)
    return doc


def _labels(doc):
    return [n["label"] for n in doc["navigation"]["tree"]]


def test_a_screen_whose_menu_entry_was_taken_out_gets_it_back():
    doc = _doc()
    assert "Account Settings" in bind_menu(doc)
    node = next(n for n in doc["navigation"]["tree"] if n["label"] == "Account Settings")
    assert node["page"] == "PAGE-004" and node["roles"] == ["ROLE-001"], "for the same people as the screens beside it"
    assert bind_menu(doc) == [], "and only once"
    assert _labels(doc).count("Account Settings") == 1


def test_no_entry_is_made_up_for_a_record_screen_a_sign_in_page_or_a_nested_path():
    doc = _doc()
    doc["pages"][1]["menuEntry"] = "Plant"                 # a parameter in its route: not a destination
    doc["pages"][4]["menuEntry"] = "Login"                 # a sign-in page
    doc["pages"][3]["menuEntry"] = "Settings > Account"    # a parent nobody designed
    bind_menu(doc)
    assert "Plant" not in _labels(doc) and "Settings" not in _labels(doc) and "Account" not in _labels(doc)


def test_sign_in_and_sign_up_are_not_menu_entries_of_an_application_that_is_signed_in_to():
    doc = _doc()
    bind_menu(doc)
    assert _labels(doc) == ["My Plants", "Today", "Account Settings"]


def test_an_application_with_public_screens_keeps_its_sign_in_link():
    doc = _doc()
    doc["pages"][0]["access"] = "public"
    bind_menu(doc)
    assert "Login" in _labels(doc) and "Sign Up" in _labels(doc)


def test_the_phones_bar_ends_with_the_plans_own_account_page_and_the_platform_adds_no_second_one():
    doc = _doc()
    assert "/account" not in [p["route"] for p in tab_pages(doc)], "before the entry is back the page has no way in (the bug)"
    bind_menu(doc)
    assert [p["route"] for p in tab_pages(doc)] == ["/plants", "/today", "/account"]
    assert has_account_tab(doc) is False, "the page is the account tab; the platform's own stands aside, as before"
    assert "/account" in [p["route"] for p in drawn_pages(doc)]


def test_an_application_with_nothing_to_sign_in_to_has_no_account_tab():
    doc = _doc(roles=[], security={"authentication": "email_password", "rbac": False, "protectedRoutes": []})
    doc["pages"] = [dict(p, access="public") for p in PAGES[:4]]
    doc["data"] = {"entities": [{"name": "Plant"}]}
    assert has_account_tab(doc) is False
