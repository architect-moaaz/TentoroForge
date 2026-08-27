"""Persona jobs must be derived from THIS app's routes, not a fixed vocabulary.

Live failure on the Palestinian Legislative Council build (49w6y3nd): all
four personas — member, committee_chair, secretary_general, public — shipped
the *identical* job list (Dashboard, Sessions, Members, Committees), so the
persona switcher rendered the same nav for every role. The user reported it
as "Roles shows same pages for all the roles".

Cause: `_jobs_from_pages` mapped role → route-prefix from a hardcoded list
grown in the yoga-studio domain (admin / manager / studio_admin /
instructor / teacher / coach / trainer). Any role outside that list fell to
the `None` branch, which means "give them every member-facing page" — so
every unrecognised role got the same everything-list.

Two further defects in the same function:

* `admin` matched the `/admin/` prefix, but the app's route is `/admins`
  (plural, no trailing slash) → zero jobs → the persona was dropped
  entirely, silently.
* Jobs took the LAST path segment, so `/bills/new` produced a nav item
  labelled "New" bound to a non-existent `new` entity.

And the rule that matters most: when roles genuinely cannot be told apart
from the routes, emitting identical persona job-lists is WORSE than
emitting none — it renders a role switcher that changes nothing.
"""
from __future__ import annotations

from services.product_brief import _jobs_from_pages

# The real Legislative Council route set (trimmed to the shape that matters).
_PLC_PAGES = [
    {"route": "/dashboard"}, {"route": "/sessions"}, {"route": "/sessions/new"},
    {"route": "/sessions/[id]"}, {"route": "/sessions/[id]/votes"},
    {"route": "/bills"}, {"route": "/bills/new"}, {"route": "/bills/[id]"},
    {"route": "/members"}, {"route": "/members/new"},
    {"route": "/committees"}, {"route": "/blocs"}, {"route": "/documents"},
    {"route": "/audit"}, {"route": "/public"}, {"route": "/login"},
]

# A role-scoped app: routes carry the role in the first segment.
_SCOPED_PAGES = [
    {"route": "/dashboard"},
    {"route": "/organiser/events"}, {"route": "/organiser/events/new"},
    {"route": "/attendee/tickets"}, {"route": "/attendee/profile"},
]


def _labels(jobs) -> list[str]:
    return [j.label for j in jobs]


def _entities(jobs) -> list[str]:
    return [e for j in jobs for e in (j.primary_entities or [])]


class TestVerbLeavesAreNotJobs:
    """`/bills/new` is a create form, not a section of the app."""

    def test_new_is_never_a_job_label(self):
        jobs = _jobs_from_pages("member", _PLC_PAGES)
        assert "New" not in _labels(jobs)

    def test_new_is_never_an_entity(self):
        assert "new" not in _entities(_jobs_from_pages("member", _PLC_PAGES))

    def test_nested_route_binds_to_its_SECTION_not_its_leaf(self):
        """`/bills/new` belongs to `bills`; the leaf slug is the verb."""
        jobs = _jobs_from_pages("member", [{"route": "/bills/new"}])
        assert _entities(jobs) == ["bills"]

    def test_edit_is_also_a_verb(self):
        assert "edit" not in _entities(
            _jobs_from_pages("member", [{"route": "/bills/edit"}]))


class TestRoleScopingIsDerivedNotHardcoded:
    """Role→prefix must come from the app's own routes."""

    def test_unknown_roles_get_their_own_scoped_routes(self):
        """`organiser` is in no hardcoded list, but the routes name it."""
        jobs = _jobs_from_pages("organiser", _SCOPED_PAGES)
        assert "events" in _entities(jobs)
        assert "tickets" not in _entities(jobs), "attendee's routes must not leak"

    def test_a_second_unknown_role_gets_a_DIFFERENT_set(self):
        organiser = set(_entities(_jobs_from_pages("organiser", _SCOPED_PAGES)))
        attendee = set(_entities(_jobs_from_pages("attendee", _SCOPED_PAGES)))
        assert organiser != attendee, "scoped roles must not share one nav"
        assert "tickets" in attendee

    def test_scoped_role_excludes_other_roles_routes(self):
        ents = _entities(_jobs_from_pages("attendee", _SCOPED_PAGES))
        assert "events" not in ents


class TestUndifferentiableRolesDoNotFakeIt:
    """The Legislative Council case: no route names any role."""

    def test_all_plc_roles_produce_the_same_set(self):
        """Precondition — the routes genuinely cannot separate these roles."""
        sets = [
            tuple(_entities(_jobs_from_pages(r, _PLC_PAGES)))
            for r in ("member", "committee_chair", "secretary_general", "public")
        ]
        assert len(set(sets)) == 1, "routes carry no role scoping here"

    def test_no_role_gets_a_junk_job(self):
        """Whatever we emit, it must be real sections — never verbs."""
        for r in ("member", "committee_chair", "secretary_general", "public"):
            ents = _entities(_jobs_from_pages(r, _PLC_PAGES))
            assert "new" not in ents and "edit" not in ents

    def test_auth_routes_never_appear(self):
        assert "login" not in _entities(_jobs_from_pages("member", _PLC_PAGES))

    def test_dynamic_segments_never_appear(self):
        ents = _entities(_jobs_from_pages("member", _PLC_PAGES))
        assert not any("[" in e for e in ents)


class TestPluralAdminRouteIsFound:
    """`admin` matched `/admin/` but the app ships `/admins` → 0 jobs → the
    persona vanished from nav with no warning."""

    def test_admins_plural_still_yields_jobs(self):
        jobs = _jobs_from_pages("admin", [{"route": "/admins"},
                                          {"route": "/admins/new"},
                                          {"route": "/dashboard"}])
        assert jobs, "an admin persona with real routes must not come back empty"
        assert "admins" in _entities(jobs)


class TestDegenerate:
    def test_no_pages(self):
        assert _jobs_from_pages("member", []) == []

    def test_non_list_input(self):
        assert _jobs_from_pages("member", None) == []

    def test_job_cap_holds(self):
        many = [{"route": f"/sec{n}"} for n in range(20)]
        assert len(_jobs_from_pages("member", many)) <= 5
