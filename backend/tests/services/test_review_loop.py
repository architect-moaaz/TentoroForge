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


# --- the Blueprint's own gaps come first; a refusal is reported, not respun ---

def test_a_settled_gap_forces_the_round_even_when_the_critic_is_clean():
    settled = {"n": 0}
    def settle(_only):
        settled["n"] += 1
        return {"PAGE-001": "Before re-composing, I fixed the Blueprint: bind Delete to FLOW-003"}
    recomposed = []
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": []},            # nothing visible is wrong
        recompose_and_rebuild=lambda briefs: recomposed.append(dict(briefs)),
        settle=settle,
    )
    assert settled["n"] == 1                          # once, on the first round
    assert out.rounds == 1 and out.converged
    assert recomposed == [{"PAGE-001": "Before re-composing, I fixed the Blueprint: bind Delete to FLOW-003"}]


def test_a_settled_note_rides_with_the_critics_brief_for_the_same_page():
    reports = iter([{"findings": [_finding("/master-data")]}, {"findings": []}])
    recomposed = []
    run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: next(reports),
        recompose_and_rebuild=lambda briefs: recomposed.append(dict(briefs)),
        settle=lambda _o: {"PAGE-001": "NOTE: bind Delete to FLOW-003"},
    )
    (briefs,) = recomposed
    assert set(briefs) == {"PAGE-001"}
    assert "mostly empty" in briefs["PAGE-001"]       # the visual finding
    assert briefs["PAGE-001"].endswith("NOTE: bind Delete to FLOW-003")


def test_a_gap_needs_no_screenshot_to_settle():
    recomposed = []
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: None,                        # the app could not be rendered
        recompose_and_rebuild=lambda briefs: recomposed.append(sorted(briefs)),
        settle=lambda _o: {"PAGE-001": "bind Delete to FLOW-003"},
    )
    assert recomposed == [["PAGE-001"]]
    assert out.rounds == 1
    assert out.skipped == "the rebuilt app could not be rendered to check it"
    assert not out.converged                          # unseen is not "looks good"


def test_a_refused_re_compose_is_reported_once_and_not_sent_round_again():
    # The critic keeps flagging /master-data; the composer refuses it.
    calls = {"n": 0}
    def critique():
        calls["n"] += 1
        return {"findings": [_finding("/master-data"), _finding("/add-data")]}
    recomposed = []
    def recompose(briefs):
        recomposed.append(sorted(briefs))
        return {"PAGE-001": "InvalidPatternTemplate: Table runs Update Record"} if "PAGE-001" in briefs else {}
    out = run_review_loop(read_doc=lambda: DOC, critique=critique,
                          recompose_and_rebuild=recompose, max_rounds=3)
    assert recomposed == [["PAGE-001", "PAGE-002"], ["PAGE-002"], ["PAGE-002"]]
    assert out.refused == {"PAGE-001": "InvalidPatternTemplate: Table runs Update Record"}
    assert set(out.remaining) == {"PAGE-002"}         # refused is not "remaining"
    assert not out.converged
    assert out.summary()["refused"] == ["PAGE-001"]


def test_once_everything_left_is_refused_the_loop_stops_early():
    recomposed = []
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": [_finding("/master-data")]},
        recompose_and_rebuild=lambda briefs: (recomposed.append(sorted(briefs)) or {"PAGE-001": "refused"}),
        max_rounds=2,
    )
    assert recomposed == [["PAGE-001"]]               # not a second round for the same refusal
    assert out.rounds == 1 and out.refused == {"PAGE-001": "refused"} and not out.converged


def test_a_page_the_observer_flagged_unrepaired_is_not_sent_round_again():
    """DC5, 22:51: round 2 re-composed /master-data over the Female-count
    filter the observer had just failed to get fixed — seven minutes to reach
    the verdict round 1 had already reached."""
    from services.smith.review_wiring import Rebuilt
    calls = {"n": 0}
    def critique():
        calls["n"] += 1
        return {"findings": [_finding("/master-data", note=f"still off {calls['n']}"),
                             _finding("/add-data", note="sparse")]}
    recomposed = []
    def recompose(briefs):
        recomposed.append(sorted(briefs))
        return Rebuilt(unrepaired={"PAGE-001": "REQ-012: the Female metric filters on Male"}
                       if "PAGE-001" in briefs else {})
    out = run_review_loop(read_doc=lambda: DOC, critique=critique,
                          recompose_and_rebuild=recompose, max_rounds=3)
    assert recomposed == [["PAGE-001", "PAGE-002"], ["PAGE-002"], ["PAGE-002"]]
    assert out.unrepaired == {"PAGE-001": "REQ-012: the Female metric filters on Male"}
    assert set(out.remaining) == {"PAGE-002"}         # unrepaired is not "remaining"
    assert not out.converged
    assert out.summary()["unrepaired"] == ["PAGE-001"]


def test_a_plain_dict_return_still_means_refused():
    from services.smith.review_wiring import Rebuilt
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": [_finding("/master-data")]},
        recompose_and_rebuild=lambda briefs: {"PAGE-001": "refused"}, max_rounds=2)
    assert out.refused == {"PAGE-001": "refused"} and out.unrepaired == {}
    out = run_review_loop(
        read_doc=lambda: DOC,
        critique=lambda: {"findings": [_finding("/master-data")]},
        recompose_and_rebuild=lambda briefs: Rebuilt(refused={"PAGE-001": "refused"}), max_rounds=2)
    assert out.refused == {"PAGE-001": "refused"} and out.rounds == 1
