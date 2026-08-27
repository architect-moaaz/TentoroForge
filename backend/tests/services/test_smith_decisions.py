"""§20 — decisions the user made, and what answering one does to the Blueprint.

§20 ends with the sentence these tests exist to protect: *"Future agents must
respect accepted decisions unless deliberately changed."* A re-derivation is
not a deliberate change, so the interesting cases are the ones where something
would quietly replace a user's answer with a default.
"""
import pytest

from services.blueprint.agent_contract import AUTO_DECIDE, RECORD_ASSUMPTION
from services.blueprint.decision_memory import apply_decision_memory, user_decided
from services.blueprint.service import BlueprintService
from services.smith import decisions as D
from services.smith.clarification import candidates
from services.smith.smith import bootstrap


@pytest.fixture()
def svc(ats, tmp_path) -> BlueprintService:
    s = BlueprintService(output_dir=tmp_path)
    s.doc = ats
    s.root.mkdir(parents=True, exist_ok=True)
    s.save()
    bootstrap(s)
    return s


def test_a_user_answer_is_recorded_as_source_user(svc):
    rec = D.record(
        svc, artifact_id="REQ-016",
        decision="Recruiters land on the pipeline board after sign-in.",
        reason="They work the board daily.", message_id="MSG-004",
    )
    assert rec.source == "user"
    written = next(d for d in svc.doc["decisions"] if d["id"] == rec.id)
    assert written["approvedBy"] == "user" and written["binding"] is True


def test_answering_settles_the_artifact(svc):
    """§17's bands are an authority grant, not a mood. An answered artifact is
    one the platform may now act on."""
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    assert svc.find("REQ-016")[1]["confidence"] == D.ANSWERED_CONFIDENCE


def test_answering_closes_the_question_without_any_bookkeeping(svc):
    assert "REQ-016" in {q.artifact for q in candidates(svc.doc)}
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    assert "REQ-016" not in {q.artifact for q in candidates(svc.doc)}


def test_delegation_grants_autonomy_without_claiming_certainty(svc):
    """"You decide" is not "I decided". It lands on §17's AUTO_DECIDE floor,
    which is exactly the band where Smith may choose alone."""
    rec = D.record(
        svc, artifact_id="REQ-016", decision="Smith chooses the landing page.",
        message_id="MSG-002", delegated=True,
    )
    assert rec.source == "smith_recommendation"
    assert svc.find("REQ-016")[1]["confidence"] == AUTO_DECIDE
    assert AUTO_DECIDE < D.ANSWERED_CONFIDENCE


def test_delegation_still_counts_as_approval(svc):
    """The user was asked and answered. That binds them in a way a domain
    default never does."""
    rec = D.record(svc, artifact_id="REQ-016", decision="You choose.",
                   message_id="MSG-002", delegated=True)
    assert next(d for d in svc.doc["decisions"] if d["id"] == rec.id)["approvedBy"] == "user"


def test_the_answer_cites_the_message_that_settled_it(svc):
    """§14 — every requirement retains its origin."""
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-052")
    evidence = svc.find("REQ-016")[1]["evidence"]
    assert {"type": "conversation", "message": "MSG-052", "source": "user"} in evidence


def test_recording_twice_supersedes_rather_than_overwrites(svc):
    """§92 — the history should read as a change of mind, not as if the first
    decision was never made."""
    first = D.record(svc, artifact_id="REQ-016", decision="Board.", message_id="MSG-001")
    second = D.record(svc, artifact_id="REQ-016", decision="Overview.", message_id="MSG-009")
    written = next(d for d in svc.doc["decisions"] if d["id"] == second.id)
    assert written["supersedes"] == first.id


def test_a_decision_must_name_a_real_artifact(svc):
    """A decision floating free of what it decides cannot be honoured,
    superseded, or found again."""
    with pytest.raises(D.NotADecision):
        D.record(svc, artifact_id="PAGE-999", decision="Something.")


def test_an_empty_decision_is_refused(svc):
    with pytest.raises(D.NotADecision):
        D.record(svc, artifact_id="REQ-016", decision="   ")


# --- the invariant §20 turns on ---------------------------------------------

def test_re_derivation_never_downgrades_a_user_decision(svc):
    """Both records key on the same artifact. Without the guard the next run
    replaces `source: user` with `source: domain_default`, and the Blueprint
    quietly forgets anyone was asked."""
    target = next(
        a["id"] for a in svc.doc["pages"]
        if RECORD_ASSUMPTION <= (a.get("confidence") or 0) < AUTO_DECIDE
    )
    rec = D.record(svc, artifact_id=target, decision="The user chose this.",
                   message_id="MSG-001")
    # Put it back in the assumption band so the derivation would reach it.
    svc.find(target)[1]["confidence"] = 0.75
    apply_decision_memory(svc)
    assert next(d for d in svc.doc["decisions"] if d["id"] == rec.id)["source"] == "user"


def test_user_decided_finds_the_artifact_behind_a_decision(svc):
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    assert "REQ-016" in user_decided(svc)


def test_apply_decision_memory_reports_what_it_preserved(svc):
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    assert apply_decision_memory(svc)["preserved"] >= 1


def test_derived_decisions_still_get_written_for_everything_else(svc):
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    assert apply_decision_memory(svc)["recorded"] > 0


def test_by_user_lists_only_accepted_decisions(svc):
    assert D.by_user(svc.doc) == []
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    listed = D.by_user(svc.doc)
    assert len(listed) == 1 and listed[0]["source"] == "user"


def test_the_blueprint_still_validates_after_a_decision(svc):
    D.record(svc, artifact_id="REQ-016", decision="Settled.", message_id="MSG-001")
    svc.validate()
