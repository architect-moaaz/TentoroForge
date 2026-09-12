"""Smith's review loop: bound, converge, degrade — the control flow is the
contract. The critique and the re-compose are injected, so these pin the loop
itself, not the vision model or the build."""

from services.smith.review_loop import run_review_loop, ReviewOutcome

DOC = {"pages": [{"id": "PAGE-001", "route": "/master-data"},
                 {"id": "PAGE-002", "route": "/add-data"}]}


def _finding(route, kind="sparse", sev="warn", note="mostly empty"):
    return {"route": route, "kind": kind, "severity": sev, "note": note}


def test_converges_when_a_re_compose_fixes_the_page():
    # Round 1 flags /master-data; after the rebuild the critic is clean.
    reports = iter([{"findings": [_finding("/master-data")]}, {"findings": []}])
    recomposed = []
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: next(reports),
        recompose_and_rebuild=lambda briefs: recomposed.append(sorted(briefs)),
    )
    assert out.converged
    assert out.rounds == 1
    assert out.recomposed == ["PAGE-001"]
    assert recomposed == [["PAGE-001"]]      # re-composed exactly the flagged page
    assert out.remaining == {}


def test_first_look_already_clean_does_no_rounds():
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": []},
        recompose_and_rebuild=lambda briefs: (_ for _ in ()).throw(
            AssertionError("must not re-compose a clean app")),
    )
    assert out.converged and out.rounds == 0 and out.recomposed == []


def test_caps_and_reports_what_remains():
    # The critic never clears the page — the loop must stop at the cap, not spin.
    calls = {"n": 0}
    def critique():
        calls["n"] += 1
        return {"findings": [_finding("/master-data", note=f"still sparse {calls['n']}")]}
    out = run_review_loop(
        read_doc=lambda: DOC, critique=critique,
        recompose_and_rebuild=lambda briefs: None, max_rounds=2,
    )
    assert out.rounds == 2
    assert calls["n"] == 3                    # initial + one per rebuild
    assert not out.converged
    assert set(out.remaining) == {"PAGE-001"}


def test_no_screenshots_degrades_to_a_clean_no_op():
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: None,                # app could not be rendered
        recompose_and_rebuild=lambda briefs: (_ for _ in ()).throw(
            AssertionError("must not re-compose when review is unavailable")),
    )
    assert out.skipped and out.rounds == 0 and not out.converged


def test_narration_names_the_pages_and_round():
    said = []
    reports = iter([{"findings": [_finding("/master-data")]}, {"findings": []}])
    run_review_loop(
        read_doc=lambda: DOC, critique=lambda: next(reports),
        recompose_and_rebuild=lambda briefs: None,
        emit=lambda ev, data: said.append((ev, data.get("text", ""))),
    )
    assert said and said[0][0] == "message"
    assert "/master-data" in said[0][1] and "round 1 of 2" in said[0][1]


def test_info_only_findings_are_not_worth_a_round():
    # info severity is advisory; the loop should see nothing to fix.
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": [_finding("/master-data", sev="info")]},
        recompose_and_rebuild=lambda briefs: (_ for _ in ()).throw(
            AssertionError("advisory notes must not trigger a re-compose")),
    )
    assert out.converged and out.rounds == 0
