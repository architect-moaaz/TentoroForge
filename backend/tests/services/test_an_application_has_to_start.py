"""Compiling is not starting, and the gate has to know the difference.

MEASURED. A generated app with two files resolving to "/" — the scaffold's
landing page inside a route group, and the optional catch-all — built clean:
`next build`, exit 0, full route listing. `next dev` refused:

    You cannot define a route with the same specificity as a optional
    catch-all route ("/" and "/[[...slug]]")

Every node had completed, the projection was correct, and the first person to
learn the application was broken was the person running it. So the build gate
was never going to catch this, and no stricter version of a BUILD check will:
the fault does not exist at build time.

SHAPE-AGNOSTIC, WHICH IS THE OTHER HALF. A gate saying "the root must
redirect" or "something must serve /" would refuse a single-page tool for
correctly being its own landing page. What every application owes is the same
regardless of shape: it starts, and its way in is served. The way in comes
from the Blueprint.
"""
import pytest

from services.blueprint.projection import _entry_route


def test_the_way_in_is_read_from_the_blueprint_not_assumed():
    """A calculator IS the root; a master-data app forwards to its entry."""
    calculator = {"pages": [{"id": "P1", "route": "/", "pattern": "tool",
                             "entry": True}]}
    assert _entry_route(calculator) == ""

    master_data = {"pages": [{"id": "P1", "route": "/add-data", "entry": True},
                             {"id": "P2", "route": "/master-data"}]}
    assert _entry_route(master_data) == "/add-data"


def test_a_single_page_app_is_never_sent_somewhere_else():
    """The case the redirect would break. An app whose only page is the root
    has nowhere to forward to, and must not try."""
    for pattern in ("tool", "dashboard", "form"):
        doc = {"pages": [{"id": "P1", "route": "/", "pattern": pattern}]}
        assert _entry_route(doc) == "", pattern


def test_the_entry_flag_outranks_navigation_order():
    doc = {"pages": [{"id": "P1", "route": "/a"},
                     {"id": "P2", "route": "/b", "entry": True}],
           "navigation": {"tree": [{"page": "P1"}, {"page": "P2"}]}}
    assert _entry_route(doc) == "/b"


def test_navigation_answers_when_nothing_is_flagged():
    doc = {"pages": [{"id": "P1", "route": "/a"}, {"id": "P2", "route": "/b"}],
           "navigation": {"tree": [{"page": "P2"}, {"page": "P1"}]}}
    assert _entry_route(doc) == "/b"


def test_a_retired_page_is_not_the_way_in():
    doc = {"pages": [{"id": "P1", "route": "/gone", "entry": True,
                      "status": "DEPRECATED"},
                     {"id": "P2", "route": "/here"}]}
    assert _entry_route(doc) == "/here"


def test_an_app_with_no_pages_asks_for_nothing():
    assert _entry_route({}) == ""
    assert _entry_route({"pages": []}) == ""


def test_the_boot_check_reports_the_servers_own_words():
    """A failure has to name the cause, not the symptom. The route collision
    is reported in Next's wording, because that is what a person searches."""
    from services.blueprint.assembly import _last_error

    output = (
        " ✓ Starting...\n"
        "[Error: You cannot define a route with the same specificity as a "
        "optional catch-all route (\"/\" and \"/[[...slug]]\").]\n"
    )
    said = _last_error(output)
    assert "same specificity" in said
    assert "Starting" not in said


def test_a_silent_death_still_says_something():
    from services.blueprint.assembly import _last_error

    assert _last_error("") == "no output"
    assert _last_error("just a line\n") == "just a line"


def test_any_answer_counts_as_started():
    """A 500 from an unreachable database and a 307 to a sign-in both mean the
    server routed. This gate checks booting, not behaviour — and must not need
    a database to run."""
    import inspect

    from services.blueprint.assembly import verify_boot

    src = inspect.getsource(verify_boot)
    assert "HTTPError" in src, "a 4xx/5xx must count as served"
    assert "status = exc.code" in src
