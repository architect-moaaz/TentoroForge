"""§69, §71, §72, §114 — prompt-to-change.

§72's requirement is negative: *"avoid rebuilding the entire application for
every user request."* So the tests that matter are the ones that would pass
just as well if impact analysis returned everything — and don't.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult,
    ArtifactProposal,
    CapabilityViolation,
)
from services.blueprint.ids import workflow_key
from services.blueprint.orchestrator import DAG, TaskSpec
from services.blueprint.service import BlueprintService
from services.smith.change import analyse, apply_change, resolve_preview
from services.smith.smith import bootstrap


@pytest.fixture()
def svc(ats, tmp_path) -> BlueprintService:
    s = BlueprintService(output_dir=tmp_path)
    s.doc = ats
    s.root.mkdir(parents=True, exist_ok=True)
    s.save()
    bootstrap(s)
    return s


# --- §69: "this" ------------------------------------------------------------

def test_preview_context_fills_in_every_field_section_69_lists(ats):
    ctx = resolve_preview(ats, page="PAGE-009", component="CMP-033")
    assert ctx.page == "PAGE-009"
    assert ctx.component == "CMP-033"
    assert ctx.component_type
    assert ctx.entity.startswith("ENTITY-")
    assert ctx.requirements


def test_the_user_never_has_to_describe_what_they_clicked(ats):
    ctx = resolve_preview(ats, page="PAGE-009", component="CMP-033")
    assert "CMP-033" in ctx.describe() and "PAGE-009" in ctx.describe()


def test_the_entity_is_context_not_a_thing_being_changed(ats):
    """§69 supplies the associated entity so Smith *understands* the selection.
    Seeding impact analysis with it says the opposite — "make this table
    compact" becomes a change to the Candidate entity, which reaches every page,
    workflow and rule in the application."""
    ctx = resolve_preview(ats, page="PAGE-009", component="CMP-033")
    assert ctx.entity in ctx.anchors
    assert ctx.entity not in ctx.subject


def test_an_unknown_selection_does_not_become_a_confident_wrong_answer(ats):
    ctx = resolve_preview(ats, page="PAGE-999", component="CMP-999")
    assert ctx.empty and "no preview selection" in ctx.describe()


# --- §71: NEW vs MODIFIED ---------------------------------------------------

def test_impact_separates_new_from_modified(svc):
    """§71's report has two columns. Nothing computed the first one."""
    report = analyse(
        svc, "managers approve offers",
        anchors=["ENTITY-008"],
        proposals=[ArtifactProposal(
            "workflows", "Manager Offer Approval",
            {"name": "Manager Offer Approval", "purpose": "A hiring manager "
             "approves an offer before it is sent.",
             "trigger": {"kind": "api_event", "detail": "offer.prepared"},
             "confidence": 0.9},
        )],
    )
    # The key is restated in the registry's own scheme — a model says
    # "Manager Offer Approval", the registry keys workflows as FLOW:<name>.
    assert [section for section, _key in report.new] == ["workflows"]
    assert report.new[0][1] == workflow_key("Manager Offer Approval")
    assert "ENTITY-008" in report.modified
    # §71's report is what a user approves a change from, so it names the
    # artifact rather than the digest its identity is built from.
    assert "Manager Offer Approval" in report.render()


def test_new_versus_modified_is_decided_by_the_id_registry_not_by_asking(svc):
    """A natural key that is already bound names an artifact that exists."""
    existing = svc.doc["pages"][0]
    # Keyed on the route deliberately: §12 says a page renamed from
    # "Candidates" to "Talent Pool" at /candidates is the same page. The model
    # supplies the route in the body and the canonical key is derived from it.
    report = analyse(
        svc, "rename it",
        proposals=[ArtifactProposal(
            "pages", "whatever the model called it",
            {"name": "Renamed", "route": existing["route"]},
        )],
    )
    assert not report.new
    assert existing["id"] in report.modified


def test_impact_analysis_writes_nothing(svc):
    """§114 step 4 shows the change to the user before step 5 applies it. An
    analysis with side effects could not be shown and then declined."""
    before = svc.snapshot()
    analyse(svc, "anything", anchors=["ENTITY-008"],
            proposals=[ArtifactProposal("workflows", "Brand New", {"name": "Brand New"})])
    assert svc.snapshot() == before


def test_an_additive_change_still_selects_a_plan(svc):
    """A change that only adds has no impacted artifacts, so a plan seeded from
    impact alone is empty and the change silently does nothing."""
    report = analyse(
        svc, "add approval",
        proposals=[ArtifactProposal(
            "data.entities", "OfferApproval",
            {"name": "OfferApproval", "table": "offer_approval",
             "description": "One manager approval of one offer.",
             "confidence": 0.9, "fields": []},
        )],
    )
    assert report.new and report.plan
    assert "data_model" in report.plan


def test_impact_does_not_return_the_whole_application(svc):
    """The point of §72. Unbounded closure returns ~80% of the artifacts from
    any starting point, which is the same answer for every request."""
    total = len(svc.doc["pages"]) + len(svc.doc["workflows"]) + len(svc.doc["businessRules"])
    report = analyse(svc, "compact", anchors=["CMP-033", "PAGE-009"])
    assert len(report.modified) < total


def test_a_change_re_runs_a_subset_of_the_dag(svc):
    report = analyse(svc, "compact", anchors=["CMP-033", "PAGE-009"])
    assert 0 < len(report.plan) < len(DAG)


def test_verification_always_re_runs(svc):
    """A change that skipped re-verification leaves the §75 matrix asserting a
    state that no longer holds."""
    assert "verification" in analyse(svc, "compact", anchors=["PAGE-009"]).plan


def test_direct_impact_is_distinguished_from_downstream(svc):
    report = analyse(svc, "compact", anchors=["CMP-033"])
    assert set(report.direct) <= set(report.modified)
    assert len(report.direct) < len(report.modified)


def test_a_request_that_changes_nothing_says_so(svc):
    report = analyse(svc, "what does this app do?")
    assert report.empty and not report.plan


# --- §13 / §114: order ------------------------------------------------------

def test_the_blueprint_is_updated_before_any_agent_runs(svc):
    """§13 — "the Blueprint must be updated first"."""
    seen: list[int] = []

    def executor(spec: TaskSpec) -> AgentResult:
        seen.append(svc.doc["version"])
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=1.0)

    before = svc.doc["version"]
    # An entity, so `database` (an agent node that does not itself produce
    # data.entities) is still in the plan and reachable. Proposing a workflow
    # would drop the `workflows` node — correctly — and the only agent left
    # sits downstream of a blocked projection, so nothing would run and the
    # ordering would be unobservable.
    result = apply_change(
        svc, "record offer approvals",
        proposals=[ArtifactProposal(
            "data.entities", "OfferApproval",
            {"name": "OfferApproval", "table": "offer_approval",
             "description": "One manager approval of one offer.",
             "confidence": 0.9, "fields": []},
        )],
        executor=executor,
    )
    assert result.applied and result.version == before + 1
    assert seen and all(v == before + 1 for v in seen)


def test_a_change_creates_a_version_and_records_the_request(svc):
    apply_change(
        svc, "managers approve offers before they are sent",
        proposals=[ArtifactProposal("workflows", "Manager Offer Approval",
                                    {"name": "Manager Offer Approval",
                                     "purpose": "Approve before send.",
                                     "trigger": {"kind": "api_event",
                                                 "detail": "offer.prepared"},
                                     "confidence": 0.9})],
        interpretation="Adds an approval step ahead of send.",
        run_agents=False,
    )
    record = svc.doc["changeHistory"][-1]
    assert record["userRequest"] == "managers approve offers before they are sent"
    assert record["smithInterpretation"] == "Adds an approval step ahead of send."
    assert record["blueprintDiff"]


def test_smith_writes_are_checked_against_its_declared_boundary(svc):
    """§30/§120 — Smith goes through the same gate as every agent. A
    coordinator exempt from the boundary check is §28's swarm with a badge."""
    with pytest.raises(CapabilityViolation):
        apply_change(
            svc, "invent an endpoint",
            proposals=[ArtifactProposal("apis", "GET /invented", {"path": "/invented"})],
            run_agents=False,
        )


def test_a_refused_change_leaves_no_version_behind(svc):
    before = svc.doc["version"]
    with pytest.raises(CapabilityViolation):
        apply_change(svc, "x",
                     proposals=[ArtifactProposal("codeMap", "k", {"artifact": "PAGE-001"})],
                     run_agents=False)
    assert svc.doc["version"] == before


def test_a_change_can_be_analysed_without_being_run(svc):
    """§114 step 4 — propose the change if necessary, before doing it."""
    result = apply_change(
        svc, "add approval",
        proposals=[ArtifactProposal("workflows", "Manager Offer Approval",
                                    {"name": "Manager Offer Approval",
                                     "purpose": "Approve before send.",
                                     "trigger": {"kind": "api_event",
                                                 "detail": "offer.prepared"},
                                     "confidence": 0.9})],
        run_agents=False,
    )
    assert result.applied and result.run is None and result.impact.plan


def test_the_blueprint_still_validates_after_a_change(svc):
    apply_change(
        svc, "add approval",
        proposals=[ArtifactProposal("workflows", "Manager Offer Approval",
                                    {"name": "Manager Offer Approval",
                                     "purpose": "Approve before send.",
                                     "trigger": {"kind": "api_event",
                                                 "detail": "offer.prepared"},
                                     "confidence": 0.9})],
        run_agents=False,
    )
    svc.validate()
