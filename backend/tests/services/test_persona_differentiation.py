"""A persona switcher that shows every role the same nav is worse than none.

On the Legislative Council build every persona resolved to the same four
jobs, so the pills rendered — member / committee-chair / secretary-general /
public — and clicking between them changed nothing. The user reported it as
"Roles shows same pages for all the roles".

Fixing the job derivation (see test_product_brief_persona_jobs) makes roles
differ whenever the ROUTES carry role scoping. When they don't — and for
this domain they don't — no amount of derivation can invent the difference,
because the plan never said which pages each role may see.

At that point the honest output is a single menu. Rendering a switcher
implies a per-role view the app does not have, and it hides the real gap:
the planner emitted actors with no page access.
"""
from __future__ import annotations

from services.nav_flow_from_plan import _drop_undifferentiated_personas


def _persona(pid: str, routes: list[str]) -> dict:
    return {
        "id": pid, "name": pid.title(), "role": pid,
        "jobs": [{"id": r.strip("/"), "label": r.strip("/").title(), "route": r}
                 for r in routes],
    }


class TestIdenticalPersonasAreDropped:
    def test_the_live_plc_shape_is_rejected(self):
        same = ["/dashboard", "/sessions", "/members", "/committees"]
        personas = [_persona(p, same) for p in
                    ("member", "committee-chair", "secretary-general", "public")]
        assert _drop_undifferentiated_personas(personas) is None

    def test_two_identical_personas_are_enough_to_reject(self):
        personas = [_persona("a", ["/x"]), _persona("b", ["/x"])]
        assert _drop_undifferentiated_personas(personas) is None

    def test_order_does_not_rescue_them(self):
        """Same routes in a different order is still the same nav."""
        personas = [_persona("a", ["/x", "/y"]), _persona("b", ["/y", "/x"])]
        assert _drop_undifferentiated_personas(personas) is None


class TestGenuinelyDifferentPersonasSurvive:
    def test_distinct_route_sets_are_kept(self):
        personas = [_persona("organiser", ["/organiser/events"]),
                    _persona("attendee", ["/attendee/tickets"])]
        assert _drop_undifferentiated_personas(personas) == personas

    def test_overlapping_but_not_identical_is_kept(self):
        """Shared /dashboard is normal; the rest differs, so the switcher
        does real work."""
        personas = [_persona("organiser", ["/dashboard", "/organiser/events"]),
                    _persona("attendee", ["/dashboard", "/attendee/tickets"])]
        assert _drop_undifferentiated_personas(personas) is not None

    def test_a_single_persona_is_kept(self):
        """One persona is not a switcher — nothing to be identical to."""
        personas = [_persona("member", ["/dashboard"])]
        assert _drop_undifferentiated_personas(personas) == personas


class TestScreensParticipate:
    """`screens` overrides `jobs` in the layout, so it must be compared too."""

    def test_identical_screens_are_rejected(self):
        a = _persona("a", ["/x"]); a["screens"] = [{"label": "S", "route": "/s"}]
        b = _persona("b", ["/y"]); b["screens"] = [{"label": "S", "route": "/s"}]
        assert _drop_undifferentiated_personas([a, b]) is None

    def test_different_screens_survive_identical_jobs(self):
        a = _persona("a", ["/x"]); a["screens"] = [{"label": "A", "route": "/a"}]
        b = _persona("b", ["/x"]); b["screens"] = [{"label": "B", "route": "/b"}]
        assert _drop_undifferentiated_personas([a, b]) is not None


class TestDegenerate:
    def test_empty(self):
        assert _drop_undifferentiated_personas([]) is None

    def test_none(self):
        assert _drop_undifferentiated_personas(None) is None
