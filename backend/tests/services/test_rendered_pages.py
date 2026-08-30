"""Which pages get photographed, and what is said about the ones that don't.

The failure this guards against is the expensive kind of green: a capture that
quietly visited eleven of a Blueprint's eighteen pages, came back clean, and
was read as the application being fine.
"""
import pytest

from services.rendered_pages import (
    Capture,
    Target,
    capture_rendered,
    landed,
    plan_routes,
    _render_tree,
)


def doc(*pages) -> dict:
    return {"pages": list(pages)}


def page(pid="PAGE-001", route="/candidates", **over) -> dict:
    return {"id": pid, "name": "Candidates", "route": route, **over}


# --- which routes ----------------------------------------------------------

def test_routes_come_from_the_blueprint_not_the_filesystem():
    """Walking `src/app` finds what was generated. The question is whether what
    the Blueprint promised is what a user sees."""
    targets, skipped = plan_routes(doc(page(), page("PAGE-002", "/roles")))

    assert [t.route for t in targets] == ["/candidates", "/roles"]
    assert skipped == {}


def test_a_modal_has_no_route_of_its_own_to_visit():
    """§34 — drawer and modal open over their caller. Visiting one as a URL
    renders a 404, and a critique of a 404 is worse than no critique."""
    targets, skipped = plan_routes(doc(
        page(), page("PAGE-002", "/candidates/new", presentation="modal")))

    assert [t.route for t in targets] == ["/candidates"]
    assert "does not own a route" in skipped["/candidates/new"]


def test_a_drawer_is_skipped_for_the_same_reason():
    _targets, skipped = plan_routes(doc(page(presentation="drawer")))
    assert "/candidates" in skipped


def test_a_detail_route_needs_a_record_that_does_not_exist_here():
    """Substituting an id would be inventing data, and the 404 would be scored
    as a design failure belonging to the fixture."""
    _targets, skipped = plan_routes(doc(page(route="/candidates/[id]")))
    assert "inventing data" in skipped["/candidates/[id]"]


def test_a_deprecated_page_is_history_not_an_obligation():
    _targets, skipped = plan_routes(doc(page(status="DEPRECATED")))
    assert "deprecated" in skipped["/candidates"]


def test_a_page_with_no_route_is_reported_against_its_id():
    _targets, skipped = plan_routes(doc(page(route="")))
    assert skipped["PAGE-001"] == "the page declares no route"


def test_access_is_carried_so_a_redirect_can_be_explained():
    targets, _ = plan_routes(doc(page(access="role_restricted")))
    assert targets[0].access == "role_restricted"


def test_nothing_is_dropped_without_a_reason():
    """Every page is either a target or has a stated reason. A page that is
    neither is a page nobody knows was not looked at."""
    pages = [
        page("PAGE-001", "/candidates"),
        page("PAGE-002", "/candidates/[id]"),
        page("PAGE-003", "/new", presentation="modal"),
        page("PAGE-004", "/old", status="DEPRECATED"),
        page("PAGE-005", ""),
    ]
    targets, skipped = plan_routes(doc(*pages))

    accounted = {t.route for t in targets} | set(skipped)
    for p in pages:
        assert (p["route"] or p["id"]) in accounted, p["id"]


# --- landing where you asked ------------------------------------------------

def test_a_page_that_stayed_put_is_usable():
    assert landed("/candidates", "http://localhost:3000/candidates") == ""


def test_a_trailing_slash_is_the_same_page():
    assert landed("/candidates", "http://localhost:3000/candidates/") == ""


def test_a_query_string_the_app_added_is_still_that_page():
    assert landed("/candidates", "http://localhost:3000/candidates?view=all") == ""


def test_a_sign_in_redirect_is_reported_rather_than_photographed():
    """Every protected page would otherwise come back looking identical and
    scoring identically, which reads as a consistent design language."""
    why = landed("/candidates", "http://localhost:3000/login?next=/candidates")
    assert "redirected to /login" in why
    assert "login screen would be scored as this page" in why


def test_no_url_at_all_is_not_treated_as_success():
    assert landed("/candidates", "") != ""


# --- degrading honestly -----------------------------------------------------

def test_a_capture_that_could_not_run_says_so_against_every_route(tmp_path, monkeypatch):
    """Coming back empty would look like agreement."""
    import builtins

    real_import = builtins.__import__

    def no_playwright(name, *a, **kw):
        if name.startswith("playwright"):
            raise ImportError("no playwright here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_playwright)

    cap = capture_rendered(doc(page(), page("PAGE-002", "/roles")), tmp_path)

    assert cap.rendered == []
    assert set(cap.skipped) == {"/candidates", "/roles"}
    assert all("playwright" in why for why in cap.skipped.values())


def test_nothing_to_visit_is_not_an_error(tmp_path):
    cap = capture_rendered(doc(page(route="/candidates/[id]")), tmp_path)
    assert cap.rendered == []
    assert "/candidates/[id]" in cap.skipped


def test_the_summary_always_states_what_was_left_out():
    cap = Capture(rendered=[("/a", b"png", "")], skipped={"/b": "why"})
    assert cap.summary() == {"captured": 1, "skipped": {"/b": "why"}}


# --- the accessibility tree -------------------------------------------------

def test_the_tree_carries_role_and_name_for_what_a_picture_cannot_show():
    """A heading that is only bold, a button that is a div."""
    tree = _render_tree({
        "role": "WebArea", "name": "Candidates",
        "children": [
            {"role": "heading", "name": "Open roles"},
            {"role": "button", "name": "Add candidate"},
        ],
    })
    assert "WebArea: Candidates" in tree
    assert "  heading: Open roles" in tree
    assert "  button: Add candidate" in tree


def test_an_empty_snapshot_is_empty_text():
    assert _render_tree(None) == ""


# --- the seam with visual verification --------------------------------------

def test_what_is_captured_is_what_shots_for_consumes():
    """The two modules meet here and nowhere else."""
    from services.blueprint.visual_verification import shots_for

    cap = Capture(rendered=[("/candidates", b"png", "tree")])
    shots = shots_for({"pages": [page()]}, cap.rendered)

    assert [s.page_id for s in shots] == ["PAGE-001"]
    assert shots[0].png == b"png" and shots[0].a11y_tree == "tree"


def test_smith_carries_the_skipped_routes_out_to_the_caller(tmp_path):
    """A review of eleven of eighteen pages reporting "no findings" would be
    the most expensive kind of green."""
    from services.blueprint.service import BlueprintService
    from services.smith.smith import Smith

    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="ATS", domain="ATS")
    svc.doc["pages"] = [page("PAGE-001", "/candidates/[id]")]
    svc.save()

    smith = Smith(svc, app_root=str(tmp_path / "app"))
    out = smith.review_preview(critic=lambda s: None)

    assert out["checked"] == 0
    assert "/candidates/[id]" in out["skipped"]


def test_a_review_with_nowhere_to_look_is_refused_with_a_reason(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.smith.smith import Smith

    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="ATS", domain="ATS")
    smith = Smith(svc)

    assert "refused" in smith.review_preview(critic=lambda s: None)
