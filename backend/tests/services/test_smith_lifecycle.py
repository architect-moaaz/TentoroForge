"""§94 and §107 — the application lifecycle, driven by turns.

§94 gives the states and says "the orchestration engine controls allowed state
transitions". §107 says *when* the interesting ones happen, and it is not on a
timer: step 8 is "user accepts or modifies the Blueprint" and step 10 is "user
authorizes build". Two user acts, so the machine advances on conversation.

The bug these tests exist to prevent is the one that was here: `command` was a
declared intent that nothing dispatched, so "build the app" produced a
confident reply and an untouched Blueprint. A command that does nothing is
worse than one that is missing, because it looks like it worked.
"""
import json

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.orchestrator import ALLOWED_TRANSITIONS, DAG, can_transition
from services.blueprint.service import BlueprintService
from services.smith.smith import (
    APPROVE_WALK,
    BUILD_WALK,
    DEFINE_WALK,
    GATES,
    TURN_TRANSITIONS,
    Smith,
    build_nodes,
    definition_nodes,
    design_summary,
    domain_nodes,
    domain_summary,
)
from services.smith.turn import COMMANDS, TurnRejected, parse_turn, validate_turn


def plan_json(**over) -> str:
    body = {"intent": "describe", "command": "", "summary": "s", "reply": "ok",
            "answers": [], "anchors": [], "proposals": [], "confidence": 0.9}
    body.update(over)
    return json.dumps(body)


def reqs(*descriptions: str) -> list[dict]:
    return [
        {"section": "requirements", "natural_key": f"req-{i}",
         "body": json.dumps({"description": d, "confidence": 0.9})}
        for i, d in enumerate(descriptions)
    ]


class Scripted:
    enforces_schema = True

    def __init__(self):
        self.queue: list[str] = []

    def __call__(self, *, system: str, user: str, schema=None) -> str:
        return self.queue.pop(0)


def quiet_executor(spec):
    return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.95)


def authoring_executor(spec):
    proposals = []
    if spec.node == "data_model":
        proposals = [ArtifactProposal("data.entities", "Role", {
            "name": "Role", "table": "role", "confidence": 0.9, "fields": []})]
    if spec.node == "page_contracts":
        proposals = [ArtifactProposal("pages", "/roles", {
            "name": "Roles", "route": "/roles", "purpose": "List open roles",
            "confidence": 0.9})]
    return AgentResult(task_id=spec.task_id, agent=spec.agent,
                       confidence=0.95, proposals=proposals)


@pytest.fixture()
def smith(tmp_path, monkeypatch):
    # `preview` compiles what it assembles, which is the point of that node and
    # not what these tests are about: they exercise §107's state machine, and
    # an `npm install` per test would make the file minutes long for a fact it
    # never asserts. The build itself is covered in test_assembly.
    monkeypatch.setattr(
        "services.blueprint.assembly.verify_build",
        lambda app_root, **kw: {"install": 0, "build": 0},
    )
    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="ATS", domain="ATS")
    return Smith(svc, model=Scripted(), executor=authoring_executor,
                 app_root=str(tmp_path / "app"))


def say(smith: Smith, plan: str, text: str = "..."):
    smith.model.queue = [plan]
    return smith.turn(text)


# --- §94: the table cannot drift -------------------------------------------

def test_every_declared_turn_transition_is_legal():
    """Declared rather than computed, so an illegal transition is impossible to
    express. This is what keeps the table honest against §94."""
    for (src, event), dst in TURN_TRANSITIONS.items():
        assert can_transition(src, dst), (src, event, dst)


def test_the_define_walk_is_a_legal_path():
    src = "CLARIFICATION"
    for dst in DEFINE_WALK:
        assert can_transition(src, dst), (src, dst)
        src = dst
    assert src == "BLUEPRINT_REVIEW", "defining parks at §107 step 8's gate"


def test_the_approve_walk_is_a_legal_path():
    src = "BLUEPRINT_REVIEW"
    for dst in APPROVE_WALK:
        assert can_transition(src, dst), (src, dst)
        src = dst
    assert src == "PLAN_REVIEW", "approval parks at §107 step 10's gate"


def test_the_two_walks_join_end_to_end():
    """§107 steps 6-10 as one path: the second walk starts where the first
    stopped, so there is no state a user can be left in between the gates."""
    assert DEFINE_WALK[-1] == "BLUEPRINT_REVIEW"
    assert can_transition(DEFINE_WALK[-1], APPROVE_WALK[0])


def test_every_gate_can_be_returned_to_from_its_own_back_edge():
    """§107 step 8 and step 10 are 'accepts *or modifies*'. A gate whose
    back-edge is one-way is a gate a correction cannot be made at twice."""
    for gate in GATES:
        back = TURN_TRANSITIONS[(gate, "change")]
        assert can_transition(gate, back), (gate, back)
        assert can_transition(back, gate), (back, gate)


def test_the_build_walk_is_a_legal_path():
    src = "PLAN_REVIEW"
    for dst, _gate in BUILD_WALK:
        assert can_transition(src, dst), (src, dst)
        src = dst
    assert src == "PREVIEW", "§107 step 21 — the preview runtime starts"


def test_the_build_walk_gates_on_nodes_that_run_in_that_phase():
    """Gating on `database` or `data_model` would never fire: those author the
    definition and have already run. The walk would stop at IMPLEMENTATION
    however well the build went."""
    for _dst, gate in BUILD_WALK:
        if gate:
            assert gate in build_nodes(), gate


def test_the_three_phases_partition_the_dag():
    """Domain, definition and build. Every node runs in exactly one of them —
    a node in two phases is a node paid for twice, and a node in none never
    runs at all."""
    phases = [set(domain_nodes()), set(definition_nodes()), set(build_nodes())]
    assert set().union(*phases) == set(DAG)
    for i, a in enumerate(phases):
        for b in phases[i + 1:]:
            assert not a & b, (a & b)


def test_the_domain_phase_authors_what_everything_else_reads():
    """The split is only worth making if the cheap half is the half the rest
    of the DAG depends on."""
    assert set(domain_nodes()) == {"requirements", "application_model"}
    downstream = set(definition_nodes())
    assert all(
        DAG[k].depends_on <= set(domain_nodes()) | downstream | set(build_nodes())
        for k in downstream
    )


def test_verification_belongs_to_the_build_not_the_definition():
    """§107 puts it at step 20. A report against a definition nobody has built
    has nothing to check."""
    assert "verification" in build_nodes()
    assert "verification" not in definition_nodes()


# --- the command contract ---------------------------------------------------

def test_a_command_turn_must_say_which_command(ats):
    with pytest.raises(TurnRejected, match="expected one of"):
        validate_turn(parse_turn(plan_json(intent="command")), ats)


def test_an_unknown_command_is_refused(ats):
    with pytest.raises(TurnRejected):
        validate_turn(parse_turn(plan_json(intent="command", command="destroy")), ats)


def test_a_command_on_a_non_command_turn_is_refused(ats):
    with pytest.raises(TurnRejected, match="only carried by"):
        validate_turn(parse_turn(plan_json(intent="change", command="build")), ats)


def test_every_command_does_something_or_says_why_not(smith):
    """The whole point. None of them may silently no-op."""
    for command in COMMANDS:
        turn = say(smith, plan_json(intent="command", command=command))
        assert turn.command == command
        assert turn.command_result, f"{command} produced no result at all"


# --- §107: the cold start ---------------------------------------------------

def test_an_empty_application_can_be_described_into_existence(smith):
    """Smith could only ever *evolve* an application. Every other path computes
    an incremental plan (§72), and on an empty Blueprint there is nothing to be
    incremental about — so a describe turn was a silent no-op."""
    assert smith.state == "DISCOVERY"
    turn = say(smith, plan_json(intent="describe", proposals=reqs(
        "A recruiter can post an open role.",
        "A recruiter can move a candidate through interview stages.")))
    assert turn.state_after == "CLARIFICATION"
    assert len(smith.doc["requirements"]) == 2


def test_a_describe_that_writes_nothing_does_not_move_the_machine(smith):
    """State is a claim about the application, not about the conversation."""
    turn = say(smith, plan_json(intent="describe"))
    assert turn.state_after == "DISCOVERY" and not turn.moved


def test_defining_stops_at_the_domain_and_asks(smith):
    """§107 step 6 then step 8's gate. The dozen nodes that read `product` do
    not run until somebody has agreed `product` is right."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    turn = say(smith, plan_json(intent="command", command="define"))

    assert turn.state_after == "BLUEPRINT_REVIEW"
    assert smith.doc["requirements"]
    assert not smith.doc.get("pages")
    assert not (smith.doc.get("data") or {}).get("entities")


def test_the_plan_gate_is_never_shown_a_blank_document(smith):
    """The failure the old single gate existed to prevent, still prevented.
    Run the authoring after the build authorisation and §26's plan reports 18
    pages as 0, and authorising a build means authorising nothing."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))

    turn = say(smith, plan_json(intent="command", command="approve"))
    assert turn.state_after == "PLAN_REVIEW"
    assert turn.plan_summary["pages"] > 0
    assert turn.plan_summary["entities"] > 0
    assert smith.doc["pages"] and smith.doc["data"]["entities"]


def test_approving_before_there_is_anything_to_approve_is_refused(smith):
    """Approving from CLARIFICATION used to walk the machine to PLAN_REVIEW
    over an empty document: legal by §94, and an acceptance of nothing."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    turn = say(smith, plan_json(intent="command", command="approve"))

    assert "refused" in turn.command_result
    assert "BLUEPRINT_REVIEW" in turn.command_result["refused"]
    assert not turn.moved


def test_the_domain_gate_shows_what_smith_understood_not_a_count(smith):
    """"4 personas" is nothing a user can accept or correct."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    turn = say(smith, plan_json(intent="command", command="define"))

    assert turn.plan_summary is None, "counts are the *other* gate"
    summary = turn.domain_summary
    assert summary is not None
    assert [r["description"] for r in summary["requirements"]]
    # §17 — what Smith supplied on the user's behalf, separated from what they
    # said. This is the part of the gate worth reading.
    assert set(summary["assumed"]) <= {r["id"] for r in summary["requirements"]}


def test_a_modification_at_a_gate_returns_to_that_gate(smith):
    """§107 step 8 is 'accepts *or modifies*'. A user who corrects the domain
    description is still standing at the gate they corrected it from."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    assert smith.state == "BLUEPRINT_REVIEW"

    turn = say(smith, plan_json(intent="change", proposals=reqs("Close a role.")))
    assert turn.change and turn.change.applied
    assert turn.state_after == "BLUEPRINT_REVIEW"
    assert len(smith.doc["requirements"]) > 1


def test_the_plan_gate_shows_the_colour_scheme(smith):
    """§107 step 9 shows what will be built, and the palette is the one
    decision here a person judges at a glance — eight counts and no colour is
    a plan review that hides the most visible thing in the plan."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    turn = say(smith, plan_json(intent="command", command="approve"))

    assert turn.plan_summary is not None, "the counts are still there"
    assert turn.design_summary is not None
    assert set(turn.design_summary) >= {
        "personality", "colors", "density", "referencesShown"}


def test_the_counts_stay_a_map_of_counts(smith):
    """`build_plan_summary` has callers that read it as exactly that; a
    palette is not a count, and widening it would make every caller handle a
    value the function is not for."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    turn = say(smith, plan_json(intent="command", command="approve"))

    assert all(isinstance(v, int) for v in turn.plan_summary.values())


def test_references_are_reported_as_shown_not_as_used(smith):
    """The agent saw them. Whether the palette came off them is a claim only
    `visualPersonality` can make, and it is asked to make it."""
    summary = design_summary(
        {"designSystem": {"colors": {"primary": "#0f766e"}}}, ())
    assert summary["referencesShown"] == []
    assert "used" not in summary


def test_a_modification_at_the_plan_gate_returns_to_the_plan_gate(smith):
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    say(smith, plan_json(intent="command", command="approve"))
    assert smith.state == "PLAN_REVIEW"

    turn = say(smith, plan_json(intent="change", proposals=reqs("Close a role.")))
    assert turn.change and turn.change.applied
    assert turn.state_after == "PLAN_REVIEW"


def test_the_plan_counts_derived_endpoints_nobody_authored(smith):
    """§116 inside the golden path — apis come from api_derivation."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    turn = say(smith, plan_json(intent="command", command="approve"))
    assert turn.plan_summary["apis"] > 0


def test_a_build_before_approval_is_refused_with_a_reason(smith):
    """§107 step 10 authorises the build from the plan-review gate. The state
    machine saying no is an answer to give the user, not a crash."""
    turn = say(smith, plan_json(intent="command", command="build"))
    assert "refused" in turn.command_result
    assert "PLAN_REVIEW" in turn.command_result["refused"]
    assert not turn.moved


def test_the_full_golden_path(smith):
    """§107 steps 3 through 21."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    say(smith, plan_json(intent="command", command="approve"))
    turn = say(smith, plan_json(intent="command", command="build"))
    assert turn.state_after == "PREVIEW"
    assert turn.run and not turn.run.failed


def test_a_build_runs_the_whole_dag_not_a_sub_plan(smith):
    ran: list[str] = []

    def watcher(spec):
        ran.append(spec.node)
        return authoring_executor(spec)

    smith.executor = watcher
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    assert set(ran) == set(domain_nodes()), "the domain gate runs the cheap half"

    say(smith, plan_json(intent="command", command="approve"))
    assert set(ran) >= {"requirements", "data_model", "page_contracts", "testing"}


def test_the_state_walk_follows_what_completed_not_what_was_asked(smith, tmp_path):
    """§94's sequence is a claim about the application. Asserting VERIFICATION
    because a run was requested would make the state a wish."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    say(smith, plan_json(intent="command", command="approve"))

    smith.app_root = None  # projections cannot run, so the build stalls
    turn = say(smith, plan_json(intent="command", command="build"))
    assert turn.state_after in ("IMPLEMENTATION", "DATABASE_PROVISIONING")
    assert turn.state_after != "PREVIEW"


# --- deployment -------------------------------------------------------------

def test_deployment_is_recognised_and_refused_never_executed(smith):
    """It publishes the application under the user's account: outward-facing,
    hard to reverse, and needing credentials. A chat turn saying "ship it" is
    not where that gets decided."""
    turn = say(smith, plan_json(intent="command", command="deploy"))
    assert "refused" in turn.command_result
    assert not turn.moved


def test_preview_is_refused_before_anything_is_built(smith):
    turn = say(smith, plan_json(intent="command", command="preview"))
    assert "refused" in turn.command_result


# --- §114 still works -------------------------------------------------------

def test_a_change_after_preview_enters_iteration(ats, tmp_path):
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.doc["state"] = "PREVIEW"
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    from services.smith.smith import bootstrap

    bootstrap(svc)
    smith = Smith(svc, model=Scripted())
    turn = say(smith, plan_json(intent="change", anchors=["ENTITY-008"], proposals=[{
        "section": "workflows", "natural_key": "Manager Offer Approval",
        "body": json.dumps({
            "name": "Manager Offer Approval", "purpose": "Approve before send.",
            "trigger": {"kind": "api_event", "detail": "offer.prepared"},
            "confidence": 0.9}),
    }]))
    assert turn.state_after == "ITERATION"


def test_describing_an_app_does_not_regenerate_one_that_does_not_exist(smith):
    """§72's plan answers "what must be rebuilt", and before there is a
    definition the answer is nothing. A live cold start reported "re-running 17
    of 22 nodes" for a turn that had only written requirements."""
    turn = say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    assert turn.change and turn.change.applied
    assert turn.change.impact.plan == []
    assert smith.doc["requirements"], "the write still goes through the Blueprint"


def test_a_change_after_definition_does_regenerate(smith):
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    say(smith, plan_json(intent="command", command="approve"))
    turn = say(smith, plan_json(intent="change", proposals=reqs("Close a role.")))
    assert turn.change and turn.change.impact.plan


def test_a_change_at_the_domain_gate_has_nothing_to_regenerate_yet(smith):
    """§72 over a document with no pages or entities is an empty plan, and
    that is the correct answer rather than a missed one — this is exactly what
    the early gate buys: the correction lands before the fan-out, not after."""
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    say(smith, plan_json(intent="command", command="define"))
    turn = say(smith, plan_json(intent="change", proposals=reqs("Close a role.")))
    assert turn.change and turn.change.applied
    assert turn.change.impact.plan == []


def test_definedness_is_derived_not_read_off_the_state_label(ats, tmp_path):
    """The ATS fixture is the counterexample sitting in the repo: a complete
    application — eighteen pages, eight entities — whose state is still
    DISCOVERY, because until the lifecycle was wired nothing transitioned it.
    Gating regeneration on that label stops a real application rebuilding."""
    from services.smith.smith import bootstrap

    assert ats["state"] == "DISCOVERY"
    svc = BlueprintService(output_dir=tmp_path)
    svc.doc = ats
    svc.root.mkdir(parents=True, exist_ok=True)
    svc.save()
    bootstrap(svc)
    assert Smith(svc, model=Scripted()).defined


def test_an_application_with_only_requirements_is_not_yet_defined(smith):
    say(smith, plan_json(intent="describe", proposals=reqs("Post a role.")))
    assert smith.doc["requirements"] and not smith.defined


def test_smith_carries_an_app_root_so_projections_are_not_blocked(tmp_path):
    """A projection with nowhere to write blocks, and takes its dependents.

    An incremental change planned eighteen nodes and quietly ran a handful:
    `integration` had no app root, so it blocked, and `testing`, `memory` and
    `verification` were skipped behind it. The Blueprint kept the endpoints and
    tests it already had while the data model had gained two entities.
    """
    from services.blueprint.orchestrator import run
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=tmp_path / "bp", app_id="a",
                                  name="n", domain="d")

    def never(spec):
        raise AssertionError("a projection must not call a model")

    blocked = run(svc, never, plan=["backend", "frontend"])
    assert set(blocked.blocked) == {"backend", "frontend"}
    assert blocked.completed == []

    ran = run(svc, never, plan=["backend", "frontend"],
              app_root=str(tmp_path / "app"))
    assert ran.completed == ["backend", "frontend"]
    assert ran.blocked == []


def test_the_cli_defaults_the_app_root_beside_the_blueprint():
    """It has to default to something, or every conversational change
    regenerates the definition and not the application."""
    import inspect

    from services.smith import cli

    src = inspect.getsource(cli.main)
    assert "--app-root" in inspect.getsource(cli)
    assert 'args.output_dir / "app"' in src
