"""When ``derive_shell_groups`` runs on a nav-flow whose pages carry
``visibleTo`` (from :mod:`services.page_visibility_derivation`), each
emitted top-level group should carry the AGGREGATED ``roles`` array
so the runtime shell can filter the sidebar per current user."""
from __future__ import annotations

from services.shell_menu_sync import derive_shell_groups


def test_group_carries_roles_from_scoped_pages():
    """A top route whose pages are all scoped to one role gets that
    role on the emitted menu group."""
    nav = {"pages": [
        {"route": "/candidate/apply",       "shell": True, "visibleTo": ["candidate"]},
        {"route": "/candidate/[id]",        "shell": True, "visibleTo": ["candidate"]},
        {"route": "/candidate",             "shell": True, "visibleTo": ["candidate"]},
        {"route": "/recruiter/candidates",  "shell": True, "visibleTo": ["recruiter"]},
        {"route": "/recruiter",             "shell": True, "visibleTo": ["recruiter"]},
    ]}
    groups = derive_shell_groups(nav)
    by_route = {g["route"]: g for g in groups}
    assert by_route["/candidate"]["roles"] == ["candidate"]
    assert by_route["/recruiter"]["roles"] == ["recruiter"]


def test_public_page_makes_the_whole_group_public():
    """If ANY page under a top route is public (visibleTo=None), the
    whole group must be public — otherwise a user hitting the top-route
    landing page would see the menu item disappear when they arrive."""
    nav = {"pages": [
        {"route": "/dashboard",       "shell": True, "visibleTo": None},
        {"route": "/dashboard/deep",  "shell": True, "visibleTo": ["admin"]},
    ]}
    groups = derive_shell_groups(nav)
    dashboard = next(g for g in groups if g["route"] == "/dashboard")
    assert "roles" not in dashboard, (
        "public page under top → group must NOT be role-scoped"
    )


def test_group_with_no_visible_to_stays_public():
    """Backwards-compat: nav-flow pages without any visibleTo produce
    groups without a roles field — unchanged from pre-slice behavior."""
    nav = {"pages": [
        {"route": "/dashboard", "shell": True},
        {"route": "/settings",  "shell": True},
    ]}
    groups = derive_shell_groups(nav)
    for g in groups:
        assert "roles" not in g


def test_multiple_roles_union_across_pages():
    """A top route touched by multiple roles across its pages carries
    the UNION of them."""
    nav = {"pages": [
        {"route": "/reports/candidates", "shell": True, "visibleTo": ["recruiter"]},
        {"route": "/reports/hiring",     "shell": True, "visibleTo": ["admin"]},
        {"route": "/reports",            "shell": True, "visibleTo": ["recruiter", "admin"]},
    ]}
    groups = derive_shell_groups(nav)
    reports = next(g for g in groups if g["route"] == "/reports")
    assert set(reports["roles"]) == {"recruiter", "admin"}
