"""§95 enforced — the state machine refuses unauthorised work.

A gate nobody consults is a UI step. This is the place that consults it: the
§94 transitions §95 puts a gate on.
"""
import pytest

from services.blueprint import approval
from services.blueprint.orchestrator import (
    GATED_TRANSITIONS,
    IllegalTransition,
    transition,
)
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )


def walk(svc, *states):
    for state in states:
        transition(svc, state)
    return svc


@pytest.fixture()
def at_plan_review(svc):
    return walk(svc, "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW",
                "PLANNING", "PLAN_REVIEW")


# --- the fingerprint -------------------------------------------------------

def test_one_definition_of_the_digest(ats):
    """Two implementations of "is this approved" that could disagree would be
    worse than none."""
    from services.smith import definition as definition_mod

    assert definition_mod.digest(definition_mod.derive(ats)) == \
        approval.product_digest(ats)


def test_digest_is_auditable(ats):
    """An opaque hash nobody can explain is barely better than no hash."""
    material = approval.identity_material(ats)
    assert material["name"] == ats["application"]["name"]
    assert len(material["pages"]) == len(ats["pages"])
    assert all(":" in entry for entry in material["pages"])


def test_digest_moves_with_the_product_surface_not_with_prose(ats):
    before = approval.product_digest(ats)
    ats["pages"][0]["purpose"] = "reworded, same page"
    assert approval.product_digest(ats) == before
    ats["pages"][0]["name"] = "Renamed"
    assert approval.product_digest(ats) != before


# --- reading the record ----------------------------------------------------

def test_state_is_open_then_approved_then_stale(at_plan_review):
    svc = at_plan_review
    assert approval.state_of(svc.doc, "plan") == "open"
    approval.record(svc, "plan")
    assert approval.state_of(svc.doc, "plan") == "approved"
    svc.doc.setdefault("roles", []).append({"id": "ROLE-900", "name": "Auditor"})
    assert approval.state_of(svc.doc, "plan") == "stale"


def test_record_fingerprints_the_document_it_is_approving(at_plan_review):
    svc = at_plan_review
    entry = approval.record(svc, "plan", message_id="MSG-004", note="looks right")
    assert entry["digest"] == approval.product_digest(svc.doc)
    assert entry["message"] == "MSG-004"
    svc.validate()


def test_require_distinguishes_why_it_refused(at_plan_review):
    svc = at_plan_review
    with pytest.raises(approval.NotApproved, match="has not been accepted"):
        approval.require(svc.doc, "plan")

    approval.record(svc, "plan", "changes_requested", note="drop the billing module")
    with pytest.raises(approval.NotApproved, match="drop the billing module"):
        approval.require(svc.doc, "plan")

    approval.record(svc, "plan")
    svc.doc.setdefault("pages", []).append(
        {"id": "PAGE-900", "name": "Billing", "route": "/b", "purpose": "p"}
    )
    with pytest.raises(approval.NotApproved, match="changed since"):
        approval.require(svc.doc, "plan")


def test_require_names_the_work_it_stopped(at_plan_review):
    with pytest.raises(approval.NotApproved,
                       match="cannot proceed with building the thing"):
        approval.require(at_plan_review.doc, "plan", doing="building the thing")


def test_a_discussion_is_not_an_acceptance(at_plan_review):
    """§25 offers discussion as a first-class answer — asking about the plan
    must read as neither consent nor rejection."""
    svc = at_plan_review
    approval.record(svc, "plan", "discussed", note="what is a module here?")
    assert approval.state_of(svc.doc, "plan") == "open"


def test_answers_accumulate_rather_than_overwrite(at_plan_review):
    """The history of how consent was reached is the audit trail (§103)."""
    svc = at_plan_review
    approval.record(svc, "plan", "discussed")
    approval.record(svc, "plan", "changes_requested", note="add an auditor role")
    approval.record(svc, "plan")
    assert [a["outcome"] for a in svc.doc["approvals"]] == [
        "discussed", "changes_requested", "accepted"
    ]
    assert approval.state_of(svc.doc, "plan") == "approved"


# --- the gated transitions (§94 × §95) -------------------------------------

def test_only_the_two_prd_edges_are_gated():
    """§95 is explicit that small engineering decisions must not keep
    interrupting the user, so everything else moves on engineering grounds."""
    assert GATED_TRANSITIONS == {
        ("PLAN_REVIEW", "IMPLEMENTATION"): "plan",
        ("READY", "EXPORT_DEPLOY"): "deployment",
    }


def test_implementation_is_unreachable_without_the_plan_gate(at_plan_review):
    with pytest.raises(approval.NotApproved, match="moving to IMPLEMENTATION"):
        transition(at_plan_review, "IMPLEMENTATION")
    assert at_plan_review.doc["state"] == "PLAN_REVIEW"


def test_recording_the_approval_is_what_opens_it(at_plan_review):
    svc = at_plan_review
    approval.record(svc, "plan")
    transition(svc, "IMPLEMENTATION")
    assert svc.doc["state"] == "IMPLEMENTATION"


def test_a_stale_approval_does_not_open_the_edge(at_plan_review):
    svc = at_plan_review
    approval.record(svc, "plan")
    svc.doc.setdefault("roles", []).append({"id": "ROLE-900", "name": "Auditor"})
    with pytest.raises(approval.NotApproved, match="changed since"):
        transition(svc, "IMPLEMENTATION")


def test_returning_from_iteration_is_deliberately_ungated(svc):
    """§70/§114 — a conversational change goes ITERATION → IMPLEMENTATION and
    back to PREVIEW. Gating that edge would put §95's Gate 3 in front of every
    "make this table more compact", which is exactly what §95 forbids."""
    walk(svc, "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW", "PLANNING",
         "PLAN_REVIEW")
    approval.record(svc, "plan")
    walk(svc, "IMPLEMENTATION", "DATABASE_PROVISIONING", "BUILD",
         "VERIFICATION", "PREVIEW", "ITERATION")
    svc.doc.setdefault("roles", []).append({"id": "ROLE-900", "name": "Auditor"})

    transition(svc, "IMPLEMENTATION")
    assert svc.doc["state"] == "IMPLEMENTATION"


def test_an_illegal_transition_still_fails_as_illegal_not_unapproved(svc):
    """The two refusals are different and must stay so."""
    with pytest.raises(IllegalTransition):
        transition(svc, "IMPLEMENTATION")


def test_deployment_is_gated_too(svc):
    walk(svc, "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW", "PLANNING",
         "PLAN_REVIEW")
    approval.record(svc, "plan")
    walk(svc, "IMPLEMENTATION", "DATABASE_PROVISIONING", "BUILD",
         "VERIFICATION", "PREVIEW", "READY")
    with pytest.raises(approval.NotApproved, match="'deployment'"):
        transition(svc, "EXPORT_DEPLOY")
    approval.record(svc, "deployment")
    transition(svc, "EXPORT_DEPLOY")
    assert svc.doc["state"] == "EXPORT_DEPLOY"


# --- through Smith's own lifecycle -----------------------------------------

def test_approve_puts_the_acceptance_on_the_record(ats, tmp_path):
    """`Smith.approve` walked the state machine and recorded nothing, so
    nothing downstream could tell whether the document had moved since."""
    from services.blueprint.agent_contract import AgentResult
    from services.smith import Smith

    def ok(spec):
        return AgentResult(task_id=spec.task_id, agent=spec.agent,
                           status="completed", confidence=0.9, proposals=[])

    smith = Smith.adopt(ats, tmp_path, executor=ok, app_root=str(tmp_path))
    for state in ("CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW"):
        transition(smith.blueprint, state)

    smith.approve()
    assert approval.state_of(smith.doc, "plan") == "approved"
    transition(smith.blueprint, "IMPLEMENTATION")
    assert smith.state == "IMPLEMENTATION"


def test_build_refuses_when_the_plan_was_never_accepted(ats, tmp_path):
    from services.smith import Smith

    smith = Smith.adopt(ats, tmp_path, executor=lambda s: None,
                        app_root=str(tmp_path))
    walk(smith.blueprint, "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW",
         "PLANNING", "PLAN_REVIEW")
    with pytest.raises(approval.NotApproved):
        smith.build()
