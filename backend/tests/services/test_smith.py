"""Smith end to end — §6, §8, §114, §118.

§118: *"Smith is not merely a chat assistant attached to a code generator.
Smith is the persistent AI architect of the application."*

Persistent is a claim about storage, not tone, and it is the one worth testing:
a Smith built tomorrow in a new process, against the same directory, is the
same Smith. Nothing that matters lives in the call stack.
"""
import json

import pytest

from services.blueprint.agent_contract import AgentResult
from services.blueprint.ids import (
    IdAllocator,
    InvalidArtifactId,
    _norm,
    entity_key,
    natural_key_for,
)
from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService
from services.smith import decisions as decision_log
from services.smith.clarification import candidates
from services.smith.smith import Smith, bootstrap


def plan_json(**over) -> str:
    body = {"intent": "change", "summary": "s", "reply": "Done.",
            "answers": [], "anchors": [], "proposals": [], "confidence": 0.9}
    body.update(over)
    return json.dumps(body)


class FakeModel:
    enforces_schema = True

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, *, system: str, user: str, schema=None) -> str:
        self.calls.append((system, user))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@pytest.fixture()
def smith(ats, tmp_path):
    return Smith.adopt(ats, tmp_path, model=FakeModel(plan_json()))


# --- §118: persistence ------------------------------------------------------

def test_a_reconstructed_smith_is_the_same_smith(ats, tmp_path):
    first = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json()))
    first.turn("make the data table compact")

    # A new process, the same application.
    second = Smith.load(tmp_path, model=FakeModel(plan_json()))
    assert len(second.conversation) == 2
    assert second.status()["version"] == first.status()["version"]


def test_every_layer_is_on_disk_before_the_turn_ends(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json()))
    smith.turn("hello")
    assert (tmp_path / ".forge" / "smith" / "conversation.jsonl").exists()
    assert (tmp_path / ".forge" / "blueprint" / "current.json").exists()
    assert (tmp_path / ".forge" / "ids.json").exists()


def test_adopting_a_blueprint_does_not_renumber_it(ats, tmp_path):
    """Without bootstrapping the allocator, a fixture loaded into a fresh
    directory starts minting from DEC-001 over ids that already mean something
    else, and upsert merges the two without complaint."""
    smith = Smith.adopt(ats, tmp_path)
    assert [d["id"] for d in smith.doc["decisions"]] == \
           [d["id"] for d in json.loads(json.dumps(ats))["decisions"]]

    rec = decision_log.record(
        smith.blueprint, artifact_id="REQ-016", decision="Settled.",
        message_id="MSG-001",
    )
    assert rec.id not in {d["id"] for d in ats["decisions"] if d["id"] != rec.id}
    assert len(smith.doc["decisions"]) == len(ats["decisions"])


def test_adoption_recovers_which_artifact_each_decision_decides(ats, tmp_path):
    """A decision's natural key is the artifact it decides — the only link
    back, since the contract gives a decision no field naming its subject.
    Bound under its own id instead, a derived decision is invisible when the
    user later answers a question about that artifact: they get a *second*
    decision rather than a supersession, and the re-derivation guard never
    protects it."""
    from services.blueprint.decision_memory import assumptions

    smith = Smith.adopt(ats, tmp_path)
    derived = assumptions(smith.doc)
    assert derived, "fixture should carry derived assumptions"
    target = derived[0]["_artifact"]
    existing = {d["id"] for d in smith.doc["decisions"]}

    rec = decision_log.record(
        smith.blueprint, artifact_id=target, decision="The user overrode this.",
        message_id="MSG-001",
    )
    assert rec.id in existing, "should supersede in place, not mint a new DEC"
    written = next(d for d in smith.doc["decisions"] if d["id"] == rec.id)
    assert written["source"] == "user" and written.get("supersedes")


def test_bootstrap_is_idempotent(ats, tmp_path):
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)
    assert bootstrap(svc) == 0


def test_adoption_makes_the_document_findable_not_just_safe(ats, tmp_path):
    """Registering the ids stops the allocator minting over them, but that is
    only half of it. Bound under a key nobody looks up, an artifact already in
    the document is invisible to the next proposal about it — which then gets a
    second id, and the application holds the same entity twice."""
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)

    existing = svc.doc["data"]["entities"][0]
    before = len(svc.doc["data"]["entities"])
    written = svc.upsert(
        "data.entities",
        {"name": existing["name"], "table": existing["table"],
         "labelField": "fullName"},
        natural_key=entity_key(existing["name"]),
    )
    assert written["id"] == existing["id"]
    assert len(svc.doc["data"]["entities"]) == before
    assert svc.doc["data"]["entities"][0]["labelField"] == "fullName"


def _stale_two_part_registry(ats, tmp_path):
    """A registry as the pre-`name` permission scheme left it."""
    with IdAllocator.session(output_dir=tmp_path) as alloc:
        for perm in ats["permissions"]:
            key = f"PERM:{_norm(perm.get('subject', ''))}:{_norm(perm['action'])}"
            try:
                alloc.bind(key, perm["id"])
            except InvalidArtifactId:
                alloc.bind(perm["id"], perm["id"])


def test_adoption_drops_keys_the_scheme_no_longer_produces(ats, tmp_path):
    """A document written before the key scheme changed is registered twice:
    under the key it was written with and the key everything now looks it up
    by. The stale one is not merely unused — `key_for` can return it, so an
    upsert handed an explicit id reads the artifact as belonging to a key its
    caller never named, and refuses a change that is perfectly well formed."""
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    _stale_two_part_registry(ats, tmp_path)

    bootstrap(svc)
    bindings = IdAllocator.load(output_dir=tmp_path).bindings
    assert not [k for k in bindings if k.startswith("PERM:") and k.count(":") == 2]
    for perm in ats["permissions"]:
        assert sum(1 for v in bindings.values() if v == perm["id"]) == 1, perm["id"]

    perm = next(p for p in ats["permissions"] if p["id"] == "PERM-004")
    body = {k: v for k, v in perm.items() if k != "id"}
    written = svc.upsert("permissions", dict(body, id="PERM-004"),
                         natural_key=natural_key_for("permissions", perm))
    assert written["id"] == "PERM-004"
    assert len(svc.doc["permissions"]) == len(ats["permissions"])


def test_adoption_keeps_the_key_of_an_artifact_that_left_the_document(ats, tmp_path):
    """Pruning drops a duplicate route to an artifact, never an identity. An
    id the document no longer carries costs nothing to keep, and §22 revival
    should come back under its own id rather than a fresh one."""
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)

    gone = svc.doc["data"]["entities"].pop()
    svc.save()
    assert bootstrap(svc) == 0
    alloc = IdAllocator.load(output_dir=tmp_path)
    assert alloc.lookup(entity_key(gone["name"])) == gone["id"]


def test_adoption_registers_every_id_even_when_two_artifacts_share_a_key(ats, tmp_path):
    """The ats fixture carries three identical /overview widgets, so one
    natural key covers three ids. Dropping the two it cannot bind would leave
    the counter below the highest WIDGET in use, and the next allocation would
    mint straight over one of them."""
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)

    counters = IdAllocator.load(output_dir=tmp_path).counters
    for section, prefix in ARTIFACT_SECTIONS.items():
        highest = [int(a["id"].rsplit("-", 1)[1]) for a in (ats.get(section) or [])]
        if highest:
            assert counters.get(prefix, 0) >= max(highest), section


# --- §8: knowing the application --------------------------------------------

def test_smith_can_report_what_it_knows(smith):
    status = smith.status()
    assert status["application"] == "Recruitment Tracker"
    assert status["clarification"]["open"] > 0
    assert status["code"]["artifacts"] > 300


def test_smith_can_answer_whether_a_requirement_is_implemented(smith):
    """§18 — Smith should be able to answer this."""
    trace = smith.trace("REQ-017")
    assert trace.verdict in ("PASSED", "FAILED")
    assert trace.render().startswith("REQ: REQ-017")


# --- §16: asking ------------------------------------------------------------

def test_asking_records_what_was_asked(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path)
    batch = smith.open_questions()
    smith.model = FakeModel(json.dumps({
        "preamble": "I understand the pipeline.",
        "questions": [{"artifact": q.artifact, "question": "Q?"} for q in batch],
    }))
    worded = smith.ask()
    assert worded.items
    assert set(smith.conversation.messages()[-1].refs) == set(worded.artifacts)


def test_smith_does_not_open_every_turn_with_the_same_questions(ats, tmp_path):
    def replier(batch):
        return json.dumps({"preamble": "p", "questions": [
            {"artifact": q.artifact, "question": "Q?"} for q in batch]})

    smith = Smith.adopt(ats, tmp_path)
    first = smith.open_questions()
    smith.model = FakeModel(replier(first))
    smith.ask()
    assert not ({q.artifact for q in first} & {q.artifact for q in smith.open_questions()})


# --- §20: answering ---------------------------------------------------------

def test_an_answer_becomes_a_user_decision(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path)
    target = smith.open_questions()[0]
    smith.model = FakeModel(json.dumps({
        "preamble": "p", "questions": [{"artifact": target.artifact, "question": "Q?"}],
    }))
    smith.ask(limit=1)

    smith.model = FakeModel(plan_json(intent="answer", answers=[{
        "artifact": target.artifact, "decision": "Yes, always.",
        "reason": "It is how the team works.", "delegated": False,
    }]))
    turn = smith.turn("yes, always")
    assert turn.ok and turn.recorded
    assert turn.recorded[0].source == "user"
    assert target.artifact not in {q.artifact for q in candidates(smith.doc)}


def test_the_decision_cites_the_message_that_settled_it(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path)
    target = smith.open_questions()[0]
    smith.model = FakeModel(json.dumps({
        "preamble": "p", "questions": [{"artifact": target.artifact, "question": "Q?"}],
    }))
    smith.ask(limit=1)
    smith.model = FakeModel(plan_json(intent="answer", answers=[{
        "artifact": target.artifact, "decision": "Yes.", "reason": "", "delegated": False,
    }]))
    turn = smith.turn("yes")
    assert turn.recorded[0].message == turn.user.id


# --- §69 / §114: prompt-to-change -------------------------------------------

def test_a_preview_selection_makes_this_resolvable(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json(anchors=["CMP-033"])))
    turn = smith.turn(
        "make this more compact", preview={"page": "PAGE-009", "component": "CMP-033"},
    )
    assert turn.ok and turn.change is not None
    assert "CMP-033" in turn.change.impact.modified


def test_a_change_re_runs_only_part_of_the_dag(ats, tmp_path):
    from services.blueprint.orchestrator import DAG

    ran: list[str] = []

    def executor(spec):
        ran.append(spec.node)
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=1.0)

    smith = Smith.adopt(
        ats, tmp_path, model=FakeModel(plan_json(anchors=["CMP-033"])),
        executor=executor,
    )
    smith.turn("make this compact", preview={"page": "PAGE-009", "component": "CMP-033"})
    assert ran and len(set(ran)) < len(DAG)


def test_a_turn_that_writes_nothing_does_not_version_the_blueprint(ats, tmp_path):
    """§91 versions an *accepted change*. A version with an empty diff is
    history nobody can read, and it makes §93 rollback offer a version
    identical to the one before it. Regenerating from an unchanged Blueprint
    is still a legitimate turn — §115 is satisfied because the definition did
    not move."""
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json(anchors=["CMP-033"])))
    before = smith.doc["version"]
    turn = smith.turn("compact", preview={"page": "PAGE-009", "component": "CMP-033"})
    assert turn.change and turn.change.impact.plan
    assert smith.doc["version"] == before


def test_a_change_that_writes_something_versions_the_blueprint(ats, tmp_path):
    plan = plan_json(anchors=["ENTITY-008"], proposals=[{
        "section": "workflows", "natural_key": "Manager Offer Approval",
        "body": json.dumps({
            "name": "Manager Offer Approval",
            "purpose": "A hiring manager approves an offer before it is sent.",
            "trigger": {"kind": "api_event", "detail": "offer.prepared"},
            "confidence": 0.9,
        }),
    }])
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan))
    before = smith.doc["version"]
    turn = smith.turn("managers approve offers before they are sent")
    assert turn.change and turn.change.applied
    assert smith.doc["version"] == before + 1
    assert smith.doc["changeHistory"][-1]["blueprintDiff"]


def test_answering_a_question_does_not_trigger_a_rebuild(ats, tmp_path):
    """§72. Answering settles confidence and records a decision; the generated
    application reads neither, so neither propagates.

    Seeding impact analysis with the plan's anchors instead — every artifact
    Smith looked at to understand the answer — reported 185 affected artifacts
    and selected all 21 DAG nodes on a real turn. That is a full rebuild
    triggered by someone saying "yes".
    """
    smith = Smith.adopt(ats, tmp_path)
    target = smith.open_questions()[0]
    smith.model = FakeModel(json.dumps({
        "preamble": "p", "questions": [{"artifact": target.artifact, "question": "Q?"}],
    }))
    smith.ask(limit=1)

    smith.model = FakeModel(plan_json(
        intent="answer",
        # The model legitimately anchors everything it consulted.
        anchors=["ENTITY-008", "PAGE-016", "CMP-031", "REQ-016"],
        answers=[{"artifact": target.artifact, "decision": "Yes.",
                  "reason": "", "delegated": False}],
    ))
    turn = smith.turn("yes")
    assert turn.ok and turn.recorded
    assert turn.change is None or not turn.change.impact.plan, (
        "answering changed nothing the application reads; nothing should rebuild"
    )


def test_a_proposal_still_drives_regeneration(ats, tmp_path):
    """The complement: what propagates is what was written."""
    plan = plan_json(anchors=["ENTITY-008", "PAGE-016", "CMP-031"], proposals=[{
        "section": "workflows", "natural_key": "Manager Offer Approval",
        "body": json.dumps({
            "name": "Manager Offer Approval",
            "purpose": "A hiring manager approves an offer before it is sent.",
            "trigger": {"kind": "api_event", "detail": "offer.prepared"},
            "confidence": 0.9,
        }),
    }])
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan))
    turn = smith.turn("managers approve offers")
    assert turn.change and turn.change.applied
    plan = turn.change.impact.plan
    assert plan, "a written artifact must reach the implementation"
    # Downstream consumes the new workflow...
    assert "verification" in plan and "testing" in plan
    # ...but the workflow agent does not re-author what Smith just wrote from
    # the user's own words (§20).
    assert "workflows" not in plan


# --- refusal ----------------------------------------------------------------

def test_a_rejected_plan_leaves_the_blueprint_untouched(ats, tmp_path):
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json(anchors=["PAGE-099"])))
    before = smith.doc["version"]
    turn = smith.turn("do something to page ninety-nine")
    assert not turn.ok
    assert smith.doc["version"] == before


def test_a_low_confidence_turn_changes_nothing(ats, tmp_path):
    """§17 — below the clarification line, do not implement the behaviour.
    Applying anyway "with a warning" is how a guess becomes a fact nobody
    remembers agreeing to."""
    smith = Smith.adopt(
        ats, tmp_path,
        model=FakeModel(plan_json(confidence=0.2, anchors=["PAGE-009"])),
    )
    before = smith.doc["version"]
    turn = smith.turn("do the thing")
    assert turn.ok and turn.change is None
    assert smith.doc["version"] == before


def test_a_failed_turn_is_still_in_the_transcript(ats, tmp_path):
    """A transcript containing only successful turns cannot explain how the
    application got this way."""
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(plan_json(anchors=["PAGE-099"])))
    smith.turn("do something impossible")
    assert [m.text for m in smith.conversation.messages()][0] == "do something impossible"
    assert len(smith.conversation) == 2


# --- §116 -------------------------------------------------------------------

def test_one_turn_consults_the_model_once(ats, tmp_path):
    """Everything after interpretation — impact, ids, versions, which nodes
    re-run — is derived."""
    model = FakeModel(plan_json(anchors=["CMP-033"]))
    smith = Smith.adopt(ats, tmp_path, model=model)
    smith.turn("compact", preview={"page": "PAGE-009", "component": "CMP-033"})
    assert len(model.calls) == 1


def test_only_the_turn_module_calls_a_model():
    """§116 in one assertion: the rest of the package is deterministic."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "services" / "smith"
    callers = [
        p.name for p in root.glob("*.py")
        if "client(" in p.read_text("utf-8")
    ]
    assert callers == ["turn.py"]


def test_a_change_the_blueprint_refuses_is_a_rejected_turn_not_a_crash(ats, tmp_path):
    """Plan validation is re-asked once; if the model still proposes a workflow
    the Blueprint refuses, the turn reports the refusal and writes nothing."""
    bad = plan_json(anchors=["ENTITY-008"], proposals=[{
        "section": "workflows", "natural_key": "Manager Offer Approval",
        "body": json.dumps({
            "name": "Manager Offer Approval",
            "trigger": {"kind": "api_event", "detail": "offer.prepared"},
            "steps": [{"key": "review", "name": "Review", "type": "approval", "config": {}}],
        }),
    }])
    smith = Smith.adopt(ats, tmp_path, model=FakeModel(bad))
    before = smith.doc["version"]
    turn = smith.turn("managers approve offers before they are sent")
    assert turn.change is None
    assert "assignType" in turn.rejected
    assert "not altered anything" in turn.reply
    assert smith.doc["version"] == before
