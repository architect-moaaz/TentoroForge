from services.nav_flow_from_plan import (
    _humanize_route,
    _label_for_persona_screen,
    nav_flow_from_plan,
)


def test_basic_plan_with_mixed_types():
    plan = {"pages": [
        {"id": "login", "route": "/login", "name": "Login", "type": "auth"},
        {"id": "dashboard", "route": "/dashboard", "name": "Dashboard", "type": "dashboard"},
        {"id": "settings", "route": "/settings", "name": "Settings", "type": "form"},
    ]}
    nf = nav_flow_from_plan(plan)
    assert nf["auth_routes"] == ["/login"]
    assert nf["post_login_redirect"] == "/dashboard"
    assert nf["post_logout_redirect"] == "/login"
    assert nf["pages"][0]["shell"] is False  # login
    assert nf["pages"][1]["shell"] is True   # dashboard
    assert nf["pages"][2]["shell"] is True   # settings
    assert nf["initialPage"] == "login"


def test_all_auth_pages():
    plan = {"pages": [
        {"id": "login", "route": "/login", "name": "Login", "type": "auth"},
        {"id": "signup", "route": "/signup", "name": "Sign up", "type": "auth"},
    ]}
    nf = nav_flow_from_plan(plan)
    assert nf["auth_routes"] == ["/login", "/signup"]
    assert "post_login_redirect" not in nf
    assert nf["post_logout_redirect"] == "/login"


def test_no_auth_pages():
    plan = {"pages": [
        {"id": "dashboard", "route": "/", "name": "Dashboard", "type": "dashboard"},
    ]}
    nf = nav_flow_from_plan(plan)
    assert nf["auth_routes"] == []
    assert nf["post_login_redirect"] == "/"
    assert "post_logout_redirect" not in nf


def test_empty_plan():
    nf = nav_flow_from_plan({})
    assert nf["pages"] == []
    assert nf["auth_routes"] == []


def test_missing_type_treated_as_shell():
    """Pages without a type default to shell:true (safer than treating as auth)."""
    plan = {"pages": [{"id": "p1", "route": "/p1", "name": "P1"}]}
    nf = nav_flow_from_plan(plan)
    assert nf["pages"][0]["shell"] is True


def test_colon_param_route_normalised_to_bracket():
    """`/users/:id` should become `/users/[id]` in the emitted route, and
    the schema file should match where page_schema_agent actually writes
    (via slugify_route) — `src/schemas/users/[id].json`."""
    plan = {"pages": [
        {"id": "users-:id", "route": "/users/:id", "name": "User Detail", "type": "detail"},
    ]}
    nf = nav_flow_from_plan(plan)
    page = nf["pages"][0]
    assert page["route"] == "/users/[id]"
    assert page["schemaFile"] == "src/schemas/users/[id].json"
    # Sanitised id — no colons leaking to filenames
    assert ":" not in page["id"]
    assert page["id"] == "users-detail"


def test_bracket_param_route_passthrough():
    """Routes already in Next.js bracket convention should remain unchanged."""
    plan = {"pages": [
        {"id": "users", "route": "/users/[id]", "name": "User Detail", "type": "detail"},
    ]}
    nf = nav_flow_from_plan(plan)
    page = nf["pages"][0]
    assert page["route"] == "/users/[id]"
    assert page["schemaFile"] == "src/schemas/users/[id].json"


def test_root_route_maps_to_home_schema():
    plan = {"pages": [{"id": "home", "route": "/", "name": "Home", "type": "dashboard"}]}
    nf = nav_flow_from_plan(plan)
    assert nf["pages"][0]["schemaFile"] == "src/schemas/home.json"


def test_nested_route_keeps_folder_structure():
    plan = {"pages": [
        {"id": "requests-new", "route": "/requests/new", "name": "New Request", "type": "form"},
    ]}
    nf = nav_flow_from_plan(plan)
    assert nf["pages"][0]["schemaFile"] == "src/schemas/requests/new.json"


def test_initial_for_map_per_role():
    """Every role mentioned in visibleTo gets a landing route — the first
    shell page (in nav-flow order) that role can see. Roles missing from
    an explicit page still land on a page marked public (visibleTo=None)."""
    plan = {"pages": [
        {"id": "signup",     "route": "/signup",     "name": "Sign up",  "type": "auth"},
        {"id": "cv-upload",  "route": "/profile/cv-upload", "name": "CV",
         "type": "form", "visibleTo": ["candidate"]},
        {"id": "dashboard",  "route": "/dashboard",  "name": "Dashboard",
         "type": "dashboard", "visibleTo": ["admin", "recruiter"]},
        {"id": "roles",      "route": "/roles",      "name": "Roles",
         "type": "list"},  # public (no visibleTo)
    ]}
    nf = nav_flow_from_plan(plan)
    assert nf["initialFor"]["candidate"] == "/profile/cv-upload"
    assert nf["initialFor"]["admin"] == "/dashboard"
    assert nf["initialFor"]["recruiter"] == "/dashboard"


def test_initial_for_falls_back_to_public_page():
    """A role whose only pages are auth-type still lands on a public shell page."""
    plan = {"pages": [
        {"id": "signup",   "route": "/signup",   "name": "Sign up",   "type": "auth"},
        {"id": "roles",    "route": "/roles",    "name": "Roles",     "type": "list"},
        {"id": "admin-x",  "route": "/admin/x",  "name": "Admin X",   "type": "form",
         "visibleTo": ["ghost-role"]},
    ]}
    nf = nav_flow_from_plan(plan)
    # ghost-role could see /admin/x, but /roles comes first in nav-flow order
    # and is public (visibleTo=None → visible to everyone), so it wins.
    assert nf["initialFor"] == {"ghost-role": "/roles"}


# ── Persona sub-nav label humanization ──────────────────────────────────────
# The persona sub-nav row (Member / Instructor / Admin persona pills) used
# to render raw page class-name IDs like "MemberSchedulePage" as its pill
# labels. These tests pin the humanizer that fixes it.

def test_humanize_route_yoga_app_examples():
    assert _humanize_route("/schedule") == "Schedule"
    assert _humanize_route("/member/bookings") == "Bookings"
    assert _humanize_route("/instructor/sessions") == "Sessions"
    assert _humanize_route("/admin/dashboard") == "Dashboard"


def test_humanize_route_skips_dynamic_segments():
    """Next.js [id] and :param dynamic segments are not meaningful labels —
    walk backwards past them to the first real noun."""
    assert _humanize_route("/instructor/sessions/[id]/roster") == "Roster"
    assert _humanize_route("/users/:id/profile") == "Profile"
    assert _humanize_route("/orders/[orderId]") == "Orders"


def test_humanize_route_kebab_and_snake_case():
    assert _humanize_route("/team-members") == "Team Members"
    assert _humanize_route("/my_bookings") == "My Bookings"


def test_humanize_route_acronyms():
    assert _humanize_route("/kpis/api-usage") == "API Usage"
    assert _humanize_route("/settings/url-config") == "URL Config"


def test_humanize_route_root_and_empty():
    assert _humanize_route("/") == "Home"
    assert _humanize_route("") == "Home"


def test_label_for_persona_screen_prefers_human_title():
    """A genuinely authored title wins over the route-derived label."""
    page = {"title": "My Schedule", "route": "/schedule"}
    assert _label_for_persona_screen(page, "schedule") == "My Schedule"


def test_label_for_persona_screen_rejects_raw_classname_title():
    """A title matching ^[A-Z][a-zA-Z0-9]*Page$ is the plan's page-class
    ID, not a user-facing label. Fall through to the route humanizer."""
    page = {"title": "MemberSchedulePage", "route": "/schedule"}
    assert _label_for_persona_screen(page, "schedule") == "Schedule"


def test_label_for_persona_screen_yoga_app_defaults():
    """Live-observed regression: the yoga demo shipped pills labeled
    'MemberBookingsPage' etc. Now they read as their route-derived nouns."""
    cases = [
        ({"title": "MemberSchedulePage",   "route": "/schedule"},           "Schedule"),
        ({"title": "MemberBookingsPage",   "route": "/member/bookings"},    "Bookings"),
        ({"title": "MemberMembershipPage", "route": "/member/membership"},  "Membership"),
        ({"title": "MemberReviewsPage",    "route": "/member/reviews"},     "Reviews"),
        ({"title": "AdminDashboardPage",   "route": "/admin/dashboard"},    "Dashboard"),
        ({"title": "InstructorAvailabilityPage",
          "route": "/instructor/availability"},                             "Availability"),
    ]
    for page, expected in cases:
        assert _label_for_persona_screen(page, "any") == expected, page


def test_label_for_persona_screen_falls_back_to_slug():
    """When route yields nothing meaningful, fall back to a humanized slug."""
    page = {"title": None, "route": "/"}
    assert _label_for_persona_screen(page, "my-bookings") == "My Bookings"


def test_no_visible_to_hints_yields_no_initial_for():
    """When the plan uses no visibleTo hints, initialFor is omitted."""
    plan = {"pages": [
        {"id": "dashboard", "route": "/dashboard", "name": "Dashboard", "type": "dashboard"},
    ]}
    nf = nav_flow_from_plan(plan)
    assert "initialFor" not in nf
