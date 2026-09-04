"""§73-§76 against what was actually drawn.

The §75 matrix reads every edge off the Blueprint and says so — `UNVERIFIED_HERE`
states plainly that nothing there exercises what was rendered. So a page can
satisfy all fourteen edges and still come back as a grey wall of defaults. These
tests are about the pass that looks, and about the one thing it must never do.
"""
from dataclasses import dataclass, field

import pytest

from services.blueprint.service import BlueprintService
from services.blueprint.verification import SECTION_OWNER
from services.blueprint.visual_verification import (
    EDGE,
    SECTION,
    Shot,
    apply_visual_findings,
    findings_for,
    repair_brief,
    shots_for,
    verify_rendered,
)


# --- stand-ins for vision_evaluator's pydantic models ----------------------

@dataclass
class FakeIssue:
    severity: str
    axis: str
    issue: str
    suggestion: str = ""
    patchOp: dict | None = None


@dataclass
class FakeCritique:
    pass_: bool
    topIssues: list = field(default_factory=list)


@pytest.fixture
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="ATS", domain="ATS")
    s.doc["pages"] = [
        {"id": "PAGE-001", "name": "Candidates", "route": "/candidates",
         "purpose": "List candidates."},
        {"id": "PAGE-002", "name": "Roles", "route": "/roles",
         "purpose": "List roles."},
    ]
    s.save()
    return s


def shot(page_id="PAGE-001", route="/candidates") -> Shot:
    return Shot(page_id=page_id, route=route, png=b"\x89PNG", a11y_tree="tree")


# --- the line this module exists to hold -----------------------------------

def test_a_proposed_patch_is_not_carried_over():
    """`Issue.patchOp` is the legacy pipeline in miniature: look, compute a
    patch, apply it, look again. §76 says flag, and a divergence the platform
    quietly fixes is one nobody ever designs away."""
    critique = FakeCritique(pass_=False, topIssues=[FakeIssue(
        severity="high", axis="visualPolish", issue="Cramped header",
        suggestion="More vertical rhythm",
        patchOp={"op": "replace", "path": "/root/props/padding", "value": "24"},
    )])

    findings = findings_for(shot(), critique)

    assert len(findings) == 1
    assert "24" not in findings[0].detail
    assert "padding" not in findings[0].detail
    assert not hasattr(findings[0], "patchOp")


def test_a_finding_is_addressed_to_whoever_composes_the_page():
    """§74 — the responsible agent receives a repair task. A page that looks
    wrong is composed wrong."""
    findings = findings_for(shot(), FakeCritique(
        pass_=False, topIssues=[FakeIssue("high", "domainFeel", "Reads generic")]))

    assert findings[0].section == SECTION
    assert findings[0].responsible_agent == "a2ui_pages"
    assert SECTION_OWNER[SECTION] == "a2ui_pages"


def test_the_issue_keeps_its_severity_and_its_suggestion():
    findings = findings_for(shot(), FakeCritique(
        pass_=False,
        topIssues=[FakeIssue("high", "brandReflection", "No brand colour",
                             "Use the primary from the design system")]))
    detail = findings[0].detail

    assert "high" in detail and "brandReflection" in detail
    assert "No brand colour" in detail
    assert "Use the primary" in detail


# --- whose verdict decides --------------------------------------------------

def test_the_model_decides_whether_a_page_passed_not_a_threshold_here():
    """A cutoff — high fails, medium does not — accumulates exceptions until
    nobody can say what the platform considers acceptable."""
    critic = lambda s: FakeCritique(  # noqa: E731
        pass_=True, topIssues=[FakeIssue("high", "visualPolish", "Noted")])

    report, verdicts = verify_rendered([shot()], critic)

    assert verdicts == {"PAGE-001": True}
    assert len(report.findings) == 1, "issues are reported whatever the verdict"


def test_a_page_that_passed_is_not_flagged_for_having_notes(svc):
    """OUT_OF_SYNC must mean 'this disagrees with the Blueprint', not
    'somebody had an opinion'."""
    critic = lambda s: FakeCritique(  # noqa: E731
        pass_=True, topIssues=[FakeIssue("low", "informationDensity", "A bit airy")])
    report, verdicts = verify_rendered([shot()], critic)

    assert apply_visual_findings(svc, report, verdicts) == []
    assert svc.find("PAGE-001")[1].get("status") != "OUT_OF_SYNC"


def test_a_failed_page_is_flagged_with_what_was_wrong(svc):
    critic = lambda s: FakeCritique(  # noqa: E731
        pass_=False, topIssues=[FakeIssue("high", "domainFeel", "Reads generic")])
    report, verdicts = verify_rendered([shot()], critic)

    assert apply_visual_findings(svc, report, verdicts) == ["PAGE-001"]
    page = svc.find("PAGE-001")[1]
    assert page["status"] == "OUT_OF_SYNC"
    assert "Reads generic" in (page.get("syncNote") or "")


def test_nothing_is_written_but_the_status(svc):
    """The verification capability writes no section and may set status. A
    critique that edits the page it judges is a second author with no §30
    boundary."""
    before = {p["id"]: dict(p) for p in svc.doc["pages"]}
    critic = lambda s: FakeCritique(  # noqa: E731
        pass_=False, topIssues=[FakeIssue("high", "visualPolish", "Cramped")])
    report, verdicts = verify_rendered([shot()], critic)
    apply_visual_findings(svc, report, verdicts)

    after = {p["id"]: dict(p) for p in svc.doc["pages"]}
    for pid, page in after.items():
        changed = {k for k in set(page) | set(before[pid])
                   if page.get(k) != before[pid].get(k)}
        assert changed <= {"status", "syncNote"}, (pid, changed)


# --- tolerance --------------------------------------------------------------

def test_one_unreachable_render_does_not_cost_the_others_their_critique():
    """On a thirty-page application, twenty-nine pages must still be reviewed."""
    def critic(s: Shot):
        if s.page_id == "PAGE-001":
            raise RuntimeError("render timed out")
        return FakeCritique(pass_=True)

    report, verdicts = verify_rendered(
        [shot(), shot("PAGE-002", "/roles")], critic)

    assert verdicts == {"PAGE-002": True}
    assert [f.artifact_id for f in report.findings] == ["PAGE-001"]
    assert "render timed out" in report.findings[0].detail


def test_a_page_that_could_not_be_critiqued_is_itself_a_divergence(svc):
    """The Blueprint says there is a page and nothing could be rendered."""
    def critic(s: Shot):
        raise RuntimeError("boom")

    report, verdicts = verify_rendered([shot()], critic)
    assert apply_visual_findings(svc, report, verdicts) == ["PAGE-001"]


# --- the repair task --------------------------------------------------------

def test_the_next_attempt_is_told_what_was_wrong_with_the_last(svc):
    """§103 — a retry told nothing re-runs an identical prompt and reproduces
    the identical page."""
    critic = lambda s: FakeCritique(  # noqa: E731
        pass_=False, topIssues=[FakeIssue("high", "domainFeel", "Reads generic",
                                          "Lean on the domain vocabulary")])
    report, _ = verify_rendered([shot()], critic)

    brief = repair_brief(report, "PAGE-001")
    assert "Reads generic" in brief and "Lean on the domain" in brief
    # It describes the page, it does not dictate the edit.
    assert "decide yourself" in brief


def test_a_page_with_nothing_against_it_gets_no_brief():
    report, _ = verify_rendered([shot()], lambda s: FakeCritique(pass_=True))
    assert repair_brief(report, "PAGE-001") == ""


# --- binding renders to artifacts ------------------------------------------

def test_a_render_is_bound_to_the_page_its_route_names(svc):
    shots = shots_for(svc.doc, [("/roles", b"png", "tree")])
    assert [s.page_id for s in shots] == ["PAGE-002"]


def test_a_render_of_a_route_no_page_claims_is_dropped(svc):
    """A critique against an id nobody can flag is spend with nowhere to land."""
    assert shots_for(svc.doc, [("/nowhere", b"png", "")]) == []


def test_every_section_a_finding_can_name_has_an_owner():
    """§74 routes a repair task to whoever may write the section, so a section
    with no owner is a finding nobody can be asked to fix. `pageLayouts` was
    exactly that: reachable through the Page↔Layout edge and unowned, so every
    one of those repair tasks was addressed to "unassigned"."""
    import ast
    import inspect

    from services.blueprint import verification

    src = inspect.getsource(verification)
    named = {
        kw.value.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "Finding"
        for kw in node.keywords
        if kw.arg == "section" and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str)
    }
    assert named, "the matrix names sections on its findings"
    assert named <= set(SECTION_OWNER), sorted(named - set(SECTION_OWNER))


def test_the_edge_is_named_but_not_folded_into_the_matrix():
    """Everything in `verification.EDGES` is checked by a pure function of the
    document; `verify()` would call this one the same way and have no
    screenshot to give it."""
    from services.blueprint.verification import EDGES

    assert EDGE not in EDGES
