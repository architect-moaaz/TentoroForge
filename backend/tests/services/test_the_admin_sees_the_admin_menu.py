"""wz7a99ir (local F&B build, 2026-10-04): "once admin logs in it should see
the admin menus as well". Three faults, each held here:

1. The built-in admin was given the sign-up role. The admin pages named no
   role and the customer pages named Customer, so the ranking made
   admin@example.com a Customer — and the menu, shown per role, hid every
   admin entry from the admin.
2. The "Admin" role's test login was admin@example.com — the seeded admin's
   own address — so it had no login and the table listed one account twice.
3. Asked to show the admin entries to admins only, the navigation tool said
   the menu "has no mechanism for per-role visibility" and tripped over a
   removed page's stale entry; Smith spent ~200 steps reconciling that.
"""
import json
import re
from pathlib import Path

from services.blueprint.account_model import admin_role, demo_email, demo_logins
from services.smith import navigation_change as nc

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def _doc():
    return {
        "security": {"signupRole": "ROLE-002"},
        "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
        "pages": [
            {"id": "PAGE-001", "route": "/admin/categories", "status": "DEPRECATED", "access": "authenticated"},
            {"id": "PAGE-004", "name": "Manage Menu Items", "route": "/admin/menu-items", "access": "authenticated"},
            {"id": "PAGE-007", "name": "Menu", "route": "/menu", "access": "public", "users": ["ROLE-002"]},
            {"id": "PAGE-011", "name": "Cart", "route": "/cart", "access": "public", "users": ["ROLE-002"]},
        ],
        "navigation": {"style": "hybrid", "tree": [
            {"label": "Menu", "page": "PAGE-007"}, {"label": "Cart & Order", "page": "PAGE-011"},
            {"label": "Admin Categories", "page": "PAGE-001"}, {"label": "Admin Menu Items", "page": "PAGE-004"}]},
    }


# --- 1. the sign-up role is never the administrator's -------------------------------------

def test_the_role_people_sign_up_into_is_never_the_admins():
    assert admin_role(_doc()) == "Admin"


def test_with_one_role_that_role_is_the_admins():
    doc = {"security": {"signupRole": "ROLE-001"}, "roles": [{"id": "ROLE-001", "name": "Staff"}], "pages": []}
    assert admin_role(doc) == "Staff"


def test_the_signup_role_named_by_name_is_excluded_too():
    doc = _doc()
    doc["security"]["signupRole"] = "Customer"
    assert admin_role(doc) == "Admin"


# --- 2. one account, one role, one row --------------------------------------------------------

def test_a_role_never_gets_the_seeded_admins_address():
    assert demo_email("Admin") == "admin.role@example.com"
    assert demo_email("Customer") == "customer@example.com"
    doc = _doc()
    doc["security"] = {}                                     # the guess can still go wrong…
    emails = [e for e, _ in demo_logins(doc)]
    assert len(emails) == len(set(emails)), "…but no address is listed twice"


def test_the_seed_derives_the_same_address():
    seed = (TEMPLATES / "runtime/seed.ts").read_text()
    body = re.search(r"function demoEmail\(role: string\): string \{(.*?)\n\}", seed, re.S).group(1)
    assert '=== "admin@example.com" ? `${local}.role@example.com`' in body


# --- 3. the navigation tool says who sees an entry, and drops removed pages ---------------------

def test_each_page_says_whom_its_menu_entry_is_shown_to():
    brief = {p["id"]: p["shownTo"] for p in nc.pages_brief(_doc())}
    assert brief == {"PAGE-004": "everyone", "PAGE-007": ["Customer"], "PAGE-011": ["Customer"]}


def test_the_revision_is_told_that_visibility_follows_the_page():
    system, user = nc._prompt(_doc(), "show the admin items only to admins")
    assert "Who sees an entry is not set in the menu" in system and "edit_access" in system
    assert '"shownTo"' in user


def test_a_removed_pages_entry_is_never_shown_to_the_revision():
    system, user = nc._prompt(_doc(), "rename Cart")
    shown = json.loads(user.split("The navigation as it stands:\n", 1)[1].split("\n\nReturn", 1)[0])
    assert [n["label"] for n in shown["tree"]] == ["Menu", "Cart & Order", "Admin Menu Items"]


def test_a_removed_page_is_named_as_removed():
    problems = nc.validate(_doc(), {"tree": [{"label": "Admin Categories", "page": "PAGE-001"}]})
    assert problems == ["'Admin Categories' opens PAGE-001, which was removed from this application — leave its entry out"]


def test_the_result_says_whom_each_entry_is_shown_to(tmp_path):
    class Svc:
        doc = _doc()
    revised = {"style": "hybrid", "tree": [{"label": "Admin Menu Items", "page": "PAGE-004"},
                                           {"label": "Menu", "page": "PAGE-007"}], "note": ""}
    labels = nc._labels(revised, nc.shown_to(Svc.doc))
    assert labels == ["Admin Menu Items", "Menu (Customer only)"]
