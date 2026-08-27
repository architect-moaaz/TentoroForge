"""End-to-end tests for PB-3 (persona-pills frame) + PB-4 (nav-flow persona metadata).

These tests exercise the full flow the pipeline does at runtime:

  plan + design_brief → ProductBrief → nav_flow_from_plan(brief)
                                           ↓
                                     nav-flow.json (with personas)
                                           ↓
                                    build_shell_deterministic
                                           ↓
                                     shell.json (persona-pills frame)

Each test pins one contract slice so a regression reads as a legible
single-cause failure. The yoga booking scenario is the canonical case.
"""
from __future__ import annotations

import pytest

from services.nav_flow_from_plan import nav_flow_from_plan
from services.product_brief import (
    Brand,
    Job,
    Persona,
    ProductBrief,
    VoiceNotes,
    _archetype_from_plan,
    derive_from_plan,
)
from services.shell_templates import (
    FRAMES,
    build_shell_deterministic,
    select_frame,
)


# ── shared fixtures ─────────────────────────────────────────────────


def _yoga_plan() -> dict:
    """A realistic booking-platform plan with 3 actors + a few pages."""
    return {
        "archetype": "booking-platform",
        "actors": [
            {"name": "Member", "role": "member",
             "responsibilities": [
                 "Browse the class schedule",
                 "Book classes with their preferred instructor",
                 "Manage bookings and membership",
                 "Leave post-class reviews",
             ]},
            {"name": "Instructor", "role": "instructor",
             "responsibilities": [
                 "Set weekly availability",
                 "View upcoming classes",
                 "Track student attendance",
             ]},
            {"name": "Studio Admin", "role": "studio_admin",
             "responsibilities": [
                 "Manage instructors, sessions, rooms, plans",
                 "View analytics on bookings and revenue",
             ]},
        ],
        "journeys": [
            {"name": "Schedule", "primary_actor": "member",
             "steps": [{"page": "/schedule"}]},
            {"name": "My Bookings", "primary_actor": "member",
             "steps": [{"page": "/bookings"}]},
            {"name": "Set Availability", "primary_actor": "instructor",
             "steps": [{"page": "/availability"}]},
        ],
        "pages": [
            {"id": "schedule", "route": "/schedule", "name": "Schedule", "type": "list"},
            {"id": "bookings", "route": "/bookings", "name": "My Bookings", "type": "list"},
            {"id": "availability", "route": "/availability", "name": "Availability", "type": "list"},
            {"id": "instructors", "route": "/instructors", "name": "Instructors", "type": "list"},
            {"id": "rooms", "route": "/rooms", "name": "Rooms", "type": "list"},
            {"id": "plans", "route": "/plans", "name": "Plans", "type": "list"},
        ],
    }


def _minimal_tokens() -> dict:
    """Design tokens the frame builder needs to render. Kept small on
    purpose — the frame doesn't care about the palette, only that the
    keys exist."""
    # Not needed directly by the tests below — build_shell_deterministic
    # goes through extract_tokens which fills every required key.
    return {}


# ── PB-4: nav-flow persona metadata ─────────────────────────────────


class TestNavFlowPersonas:
    def test_no_brief_no_personas_key(self):
        nf = nav_flow_from_plan(_yoga_plan())
        assert "personas" not in nf

    def test_brief_with_personas_attaches_metadata(self):
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nf = nav_flow_from_plan(plan, product_brief=brief)
        assert "personas" in nf
        # Every actor with resolvable jobs should surface as a persona.
        persona_ids = {p["id"] for p in nf["personas"]}
        assert "member" in persona_ids
        assert "instructor" in persona_ids

    def test_persona_jobs_resolve_to_real_routes(self):
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nf = nav_flow_from_plan(plan, product_brief=brief)
        member = next(p for p in nf["personas"] if p["id"] == "member")
        # Every job's route must exist in the pages array (no dead links).
        page_routes = {p["route"] for p in nf["pages"]}
        for job in member["jobs"]:
            assert job["route"] in page_routes, (
                f"member job {job['id']!r} routes to {job['route']} "
                "which isn't in nav-flow pages"
            )

    def test_persona_with_no_resolvable_jobs_is_dropped(self):
        # A persona whose jobs don't resolve to any page in pages_out
        # must NOT appear in nav-flow.personas — otherwise it'd render
        # as a pill with no destination.
        brief = ProductBrief(
            personas=[
                Persona(id="ghost", name="Ghost", role="ghost",
                        jobs=[Job(id="fly", label="Fly",
                                  primary_entities=["nonexistent"])]),
                Persona(id="member", name="Member", role="member",
                        jobs=[Job(id="browse", label="Browse",
                                  primary_entities=["schedule"])]),
            ],
        )
        nf = nav_flow_from_plan(_yoga_plan(), product_brief=brief)
        ids = {p["id"] for p in nf.get("personas", [])}
        assert "ghost" not in ids
        assert "member" in ids

    def test_dead_job_dropped_but_persona_kept_if_other_jobs_resolve(self):
        # A persona with one bad job + one good job keeps the good job.
        brief = ProductBrief(
            personas=[
                Persona(id="member", name="Member", role="member",
                        jobs=[
                            Job(id="fly", label="Fly",
                                primary_entities=["nonexistent"]),
                            Job(id="browse", label="Browse",
                                primary_entities=["schedule"]),
                        ]),
            ],
        )
        nf = nav_flow_from_plan(_yoga_plan(), product_brief=brief)
        member = nf["personas"][0]
        job_ids = {j["id"] for j in member["jobs"]}
        assert "browse" in job_ids
        assert "fly" not in job_ids

    def test_title_fallback_when_no_primary_entities(self):
        # Job with no primary_entities but a label matching a page title
        # resolves via title match.
        brief = ProductBrief(
            personas=[
                Persona(id="member", name="Member", role="member",
                        jobs=[Job(id="my-bookings", label="My Bookings",
                                  primary_entities=[])]),
            ],
        )
        nf = nav_flow_from_plan(_yoga_plan(), product_brief=brief)
        member = nf["personas"][0]
        assert member["jobs"][0]["route"] == "/bookings"

    def test_auth_pages_never_targeted_by_persona_jobs(self):
        # An auth route (/login) must never be a persona-job destination.
        plan_with_auth = _yoga_plan()
        plan_with_auth["pages"].insert(0,
            {"id": "login", "route": "/login", "name": "Sign In", "type": "auth"})
        brief = ProductBrief(
            personas=[
                Persona(id="member", name="Member", role="member",
                        jobs=[Job(id="sign", label="Sign In",
                                  primary_entities=["login"])]),
            ],
        )
        nf = nav_flow_from_plan(plan_with_auth, product_brief=brief)
        # No persona should have jobs targeting /login.
        for p in nf.get("personas", []):
            for j in p["jobs"]:
                assert j["route"] != "/login"

    def test_empty_pages_returns_no_personas_metadata(self):
        # Plan with actors but no shell pages → no personas attached
        # (nothing to route to).
        empty_plan = {"actors": [{"name": "Member", "role": "member",
                                   "responsibilities": ["browse"]}],
                      "pages": []}
        brief = derive_from_plan(empty_plan)
        nf = nav_flow_from_plan(empty_plan, product_brief=brief)
        assert nf.get("personas") is None


# ── PB-3: shell frame picker ────────────────────────────────────────


class TestFramePicker:
    def test_persona_pills_registered_in_frames(self):
        assert "persona-pills" in FRAMES

    def test_picker_prefers_persona_pills_with_2_to_4_personas(self):
        nav_flow_2 = {"pages": [], "personas": [
            {"id": "a", "name": "A", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "b", "name": "B", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
        ]}
        nav_flow_3 = {"pages": [], "personas": [
            {"id": "a", "name": "A", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "b", "name": "B", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "c", "name": "C", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
        ]}
        nav_flow_4 = {"pages": [], "personas": [
            {"id": "a", "name": "A", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "b", "name": "B", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "c", "name": "C", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
            {"id": "d", "name": "D", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
        ]}
        for nf in (nav_flow_2, nav_flow_3, nav_flow_4):
            assert select_frame(plan={}, nav_flow=nf) == "persona-pills"

    def test_picker_skips_persona_pills_for_single_persona(self):
        # One persona → nothing to switch between. Falls through to the
        # normal IA heuristic.
        nf = {"pages": [], "personas": [
            {"id": "a", "name": "A", "jobs": [{"id": "j", "label": "J", "route": "/"}]},
        ]}
        assert select_frame(plan={}, nav_flow=nf) != "persona-pills"

    def test_picker_skips_persona_pills_for_5_plus_personas(self):
        # 5+ personas → pills overflow the top strip. Fall through.
        nf = {"pages": [], "personas": [
            {"id": f"p{i}", "name": f"P{i}",
             "jobs": [{"id": "j", "label": "J", "route": "/"}]}
            for i in range(5)
        ]}
        assert select_frame(plan={}, nav_flow=nf) != "persona-pills"

    def test_picker_no_personas_key_no_pills(self):
        assert select_frame(plan={}, nav_flow={"pages": []}) != "persona-pills"


# ── PB-3: full build_shell_deterministic integration ────────────────


class TestBuildShellPersonaPills:
    def test_full_flow_yoga_plan_yields_persona_pills(self):
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nav_flow = nav_flow_from_plan(plan, product_brief=brief)

        shell = build_shell_deterministic(plan, nav_flow)
        assert shell["frame"] == "persona-pills"

    def test_shell_children_render_pills_for_every_persona(self):
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nav_flow = nav_flow_from_plan(plan, product_brief=brief)
        shell = build_shell_deterministic(plan, nav_flow)

        # Walk the tree, collect every Button with a persona label.
        found_labels: set[str] = set()
        expected_labels = {p["name"] for p in nav_flow["personas"]}

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "Button":
                    label = (node.get("props") or {}).get("label")
                    if label in expected_labels:
                        found_labels.add(label)
                for child in (node.get("children") or []):
                    walk(child)
            elif isinstance(node, list):
                for c in node:
                    walk(c)

        walk(shell)
        assert found_labels == expected_labels

    def test_shell_no_sidebar_when_persona_pills(self):
        # Persona-pills should NOT render a SideNav / sidebar container.
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nav_flow = nav_flow_from_plan(plan, product_brief=brief)
        shell = build_shell_deterministic(plan, nav_flow)

        def has_type(node, t: str) -> bool:
            if isinstance(node, dict):
                if node.get("type") == t:
                    return True
                for c in (node.get("children") or []):
                    if has_type(c, t):
                        return True
            elif isinstance(node, list):
                return any(has_type(c, t) for c in node)
            return False

        assert not has_type(shell, "SideNav"), (
            "persona-pills shell should not include SideNav — that's the "
            "chrome we're specifically getting rid of"
        )
        # It also shouldn't have a data-shell-region=sidebar container.
        def has_sidebar_region(node) -> bool:
            if isinstance(node, dict):
                p = node.get("props") or {}
                if p.get("data-shell-region") == "sidebar":
                    return True
                for c in (node.get("children") or []):
                    if has_sidebar_region(c):
                        return True
            elif isinstance(node, list):
                return any(has_sidebar_region(c) for c in node)
            return False
        assert not has_sidebar_region(shell)

    def test_shell_includes_page_outlet(self):
        # A shell without a PageOutlet is useless — pages never render.
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        nav_flow = nav_flow_from_plan(plan, product_brief=brief)
        shell = build_shell_deterministic(plan, nav_flow)

        def has_outlet(node) -> bool:
            if isinstance(node, dict):
                if node.get("type") == "PageOutlet":
                    return True
                for c in (node.get("children") or []):
                    if has_outlet(c):
                        return True
            elif isinstance(node, list):
                return any(has_outlet(c) for c in node)
            return False
        assert has_outlet(shell)

    def test_fallback_to_topbar_when_personas_empty(self):
        # Defensive: if nav_flow.personas somehow arrives as [] (should
        # be None by contract), the frame picker will have chosen
        # something else. But if a caller manually passes frame=
        # "persona-pills" with empty personas, we should still emit a
        # renderable shell rather than crash.
        nav_flow = {"pages": [], "personas": []}
        # Empty personas → picker doesn't pick pills → different frame.
        picked = select_frame(plan={}, nav_flow=nav_flow)
        assert picked != "persona-pills"

    def test_backward_compat_plan_without_brief_still_gets_sidebar(self):
        # Plan with 3 actors but NO product brief → nav_flow has no
        # personas key → old sidebar frame wins (existing behaviour).
        plan = _yoga_plan()
        nav_flow = nav_flow_from_plan(plan)  # no brief
        assert "personas" not in nav_flow
        shell = build_shell_deterministic(plan, nav_flow)
        # Multi-actor + 6 pages → old rules pick sidebar.
        assert shell["frame"] in ("sidebar", "topbar", "rail")
        assert shell["frame"] != "persona-pills"


class TestPersonaScreens:
    """Slice B (2026-08-13) — personas gain a `screens` key resolved from
    the archetype vocabulary's primary_screens_per_persona list. Consumed
    by layout.tsx to render the second-tier sub-nav pill row."""

    def test_member_persona_gets_screens_from_booking_platform_vocab(self):
        plan = _yoga_plan()
        # Attach archetype to the brief.
        brief = derive_from_plan(plan)
        brief.archetype = "booking-platform"
        nf = nav_flow_from_plan(plan, product_brief=brief)
        member = next(p for p in nf["personas"] if p["id"] == "member")
        assert "screens" in member and member["screens"], (
            "member persona should carry a resolved screens list"
        )
        routes = {s["route"] for s in member["screens"]}
        # The yoga plan has /schedule and /bookings — both should resolve.
        assert "/schedule" in routes
        assert "/bookings" in routes
        # Every screen entry must have label, route, icon keys.
        for s in member["screens"]:
            assert set(s.keys()) >= {"label", "route", "icon"}

    def test_no_archetype_means_no_screens_key(self):
        plan = _yoga_plan()
        brief = derive_from_plan(plan)
        brief.archetype = ""  # no archetype set
        nf = nav_flow_from_plan(plan, product_brief=brief)
        # Every persona survives (jobs still resolve), but `screens`
        # never gets populated (or is empty).
        for p in nf.get("personas", []):
            assert not p.get("screens"), (
                f"persona {p['id']} got screens without an archetype set"
            )

    def test_unknown_role_gets_no_screens(self):
        """Role not in the vocabulary's per-persona map → no screens."""
        plan = _yoga_plan()
        brief = ProductBrief(
            archetype="booking-platform",
            personas=[
                Persona(id="janitor", name="Janitor", role="janitor",
                        jobs=[Job(id="clean", label="Clean",
                                  primary_entities=["schedule"])]),
            ],
        )
        nf = nav_flow_from_plan(plan, product_brief=brief)
        p = next(x for x in nf["personas"] if x["id"] == "janitor")
        assert not p.get("screens")

    def test_instructor_and_admin_resolve_against_real_yoga_plan(self):
        """Regression pin (2026-08-13): the actual generated yoga plan
        emits pages under ``/instructor/*`` and ``/admin/*`` prefixes.
        The vocabulary's ``sessions``/``availability``/``dashboard``/
        ``instructors``/``rooms``/``plans`` screen slugs must resolve
        against those prefixed routes — otherwise Instructor/Admin
        personas render an empty sub-nav row."""
        real_plan = {
            "archetype": "booking-platform",
            "actors": [
                {"name": "Member", "role": "member", "responsibilities": ["Book"]},
                {"name": "Instructor", "role": "instructor",
                 "responsibilities": ["Teach"]},
                {"name": "Studio Admin", "role": "studio_admin",
                 "responsibilities": ["Run the studio"]},
            ],
            "journeys": [
                {"name": "Schedule", "primary_actor": "member",
                 "steps": [{"page": "/schedule"}]},
                {"name": "Sessions", "primary_actor": "instructor",
                 "steps": [{"page": "/instructor/sessions"}]},
                {"name": "Dashboard", "primary_actor": "studio_admin",
                 "steps": [{"page": "/admin/dashboard"}]},
            ],
            "pages": [
                {"id": "schedule",              "route": "/schedule",              "name": "Schedule",     "type": "list"},
                {"id": "member-bookings",       "route": "/member/bookings",       "name": "My Bookings",  "type": "list"},
                {"id": "member-membership",     "route": "/member/membership",     "name": "Membership",   "type": "list"},
                {"id": "instructor-sessions",   "route": "/instructor/sessions",   "name": "Sessions",     "type": "list"},
                {"id": "instructor-availability","route": "/instructor/availability","name": "Availability","type": "list"},
                {"id": "admin-dashboard",       "route": "/admin/dashboard",       "name": "Dashboard",    "type": "list"},
                {"id": "admin-instructors",     "route": "/admin/instructors",     "name": "Instructors",  "type": "list"},
                {"id": "admin-rooms",           "route": "/admin/rooms",           "name": "Rooms",        "type": "list"},
                {"id": "admin-membership-plans","route": "/admin/membership-plans","name": "Plans",        "type": "list"},
            ],
        }
        brief = derive_from_plan(real_plan)
        brief.archetype = "booking-platform"
        nf = nav_flow_from_plan(real_plan, product_brief=brief)
        personas = {p["id"]: p for p in nf["personas"]}

        # Member survives with schedule + bookings + membership.
        assert "member" in personas
        member_routes = {s["route"] for s in personas["member"].get("screens", [])}
        assert "/schedule" in member_routes
        assert "/member/bookings" in member_routes
        assert "/member/membership" in member_routes

        # Instructor MUST have at least sessions and availability
        # (previously resolved to zero screens → persona dropped).
        assert "instructor" in personas, (
            "Instructor persona was dropped — vocab slugs failed to resolve"
        )
        instr_routes = {s["route"] for s in personas["instructor"].get("screens", [])}
        assert "/instructor/sessions" in instr_routes
        assert "/instructor/availability" in instr_routes

        # Studio admin resolves dashboard + rooms + plans + instructors.
        # Persona ids are hyphenated; role stays underscored.
        assert "studio-admin" in personas
        assert personas["studio-admin"]["role"] == "studio_admin"
        admin_routes = {s["route"] for s in personas["studio-admin"].get("screens", [])}
        assert "/admin/dashboard" in admin_routes
        assert "/admin/rooms" in admin_routes
        assert "/admin/instructors" in admin_routes


class TestArchetypeAutoDetect:
    """Slice 1c (2026-08-13) — a plan description that mentions banking
    keywords should auto-detect the ``banking-platform`` archetype, and
    the existing booking-platform detection must keep working."""

    def test_banking_description_detects_banking_platform(self):
        plan = {
            "description": "credit union member account portal with kyc onboarding",
        }
        assert _archetype_from_plan(plan) == "banking-platform"

    def test_banking_entities_detect_banking_platform(self):
        plan = {
            "entities": {
                "Account": {},
                "Transaction": {},
                "Loan": {},
            },
        }
        assert _archetype_from_plan(plan) == "banking-platform"

    def test_yoga_plan_still_detects_booking_platform(self):
        # Regression guard — adding banking-platform must not steal the
        # yoga case.
        plan = _yoga_plan()
        assert _archetype_from_plan(plan) == "booking-platform"

    def test_explicit_archetype_wins_over_keywords(self):
        # If the planner already emitted an archetype, that wins — no
        # keyword scan needed.
        plan = {"archetype": "banking-platform", "description": "yoga booking"}
        assert _archetype_from_plan(plan) == "banking-platform"

    # ── New archetype detection (2026-08-13 Slice) ────────────────

    def test_healthcare_description_detects_healthcare_platform(self):
        plan = {"description": "medical clinic patient prescription and vitals tracker"}
        assert _archetype_from_plan(plan) == "healthcare-platform"

    def test_field_service_description_detects_field_service_platform(self):
        plan = {"description": "HVAC technician dispatch and work order scheduling"}
        assert _archetype_from_plan(plan) == "field-service-platform"

    def test_learning_description_detects_learning_platform(self):
        plan = {"description": "LMS with courses cohort and quizzes for learners"}
        assert _archetype_from_plan(plan) == "learning-platform"

    def test_marketplace_description_detects_marketplace_platform(self):
        plan = {"description": "Two-sided marketplace of sellers and listings for buyers"}
        assert _archetype_from_plan(plan) == "marketplace-platform"

    def test_content_description_detects_content_platform(self):
        plan = {"description": "Editorial CMS for a blog with articles and posts"}
        assert _archetype_from_plan(plan) == "content-platform"

    def test_crm_description_detects_crm_platform(self):
        plan = {"description": "Sales CRM with deals pipeline and contacts for account executives"}
        assert _archetype_from_plan(plan) == "crm-platform"

    def test_inventory_description_detects_inventory_platform(self):
        plan = {"description": "Warehouse WMS with stock levels SKU and purchase order receiving"}
        assert _archetype_from_plan(plan) == "inventory-platform"

    def test_project_description_detects_project_platform(self):
        plan = {"description": "Project management tool with tasks milestones and timesheet tracking"}
        assert _archetype_from_plan(plan) == "project-platform"

    # ── 2026-08-13 Slice (5 more vocabs) ──────────────────────────

    def test_payment_processing_description_detects_payment_platform(self):
        plan = {"description": "Stripe-style payment gateway for merchants with chargebacks and payouts"}
        assert _archetype_from_plan(plan) == "payment-processing-platform"

    def test_subscription_billing_description_detects_subscription_platform(self):
        plan = {"description": "SaaS subscription billing platform with dunning and recurring invoices"}
        assert _archetype_from_plan(plan) == "subscription-billing-platform"

    def test_analytics_dashboard_description_detects_analytics_platform(self):
        plan = {"description": "Business intelligence dashboard platform with saved queries and datasets for analysts"}
        assert _archetype_from_plan(plan) == "analytics-dashboard-platform"

    def test_messaging_description_detects_messaging_platform(self):
        plan = {"description": "Slack-style team messaging platform with channels and threads"}
        assert _archetype_from_plan(plan) == "messaging-platform"

    def test_dev_tools_description_detects_dev_tools_platform(self):
        plan = {"description": "CI/CD platform with deployments monitoring incidents alerts and oncall rotations"}
        assert _archetype_from_plan(plan) == "dev-tools-platform"
