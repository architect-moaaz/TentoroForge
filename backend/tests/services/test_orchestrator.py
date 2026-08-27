"""A swarm is what you get when nobody owns the order.

§28's rule — "agents shall not operate in an uncontrolled swarm" — is really
two claims: dependencies are declared, and work that isn't ready doesn't run.
The second is the one that bites. An agent handed missing inputs does not fail;
it invents. That is how you end up with a page bound to an entity that was
never modelled, and then a guard to detect it.

So these tests care most about restraint: unmet dependencies skip rather than
attempt, illegal state transitions raise, and an incremental change re-runs the
sub-DAG rather than everything.
"""
import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import entity_key, page_key
from services.blueprint.orchestrator import (
    ALLOWED_TRANSITIONS,
    DAG,
    STATES,
    CyclicDag,
    DagNode,
    IllegalTransition,
    TaskSpec,
    build_plan_summary,
    can_transition,
    descendants,
    impacted_artifacts,
    incremental_plan,
    levels,
    run,
    transition,
)
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )


# --- §28: the graph ---------------------------------------------------------

def test_dag_is_acyclic_and_layered():
    lv = levels()
    assert lv[0] == ["requirements"], "requirements come first (§28)"
    flat = [k for level in lv for k in level]
    assert sorted(flat) == sorted(DAG)


def test_every_dependency_names_a_real_node():
    for node in DAG.values():
        for dep in node.depends_on:
            assert dep in DAG, (node.key, dep)


def test_data_and_experience_branches_are_concurrent():
    """§28 forks after the application model; §28 also says independent work
    may execute concurrently, which is only true if they share a level."""
    lv = levels()
    level_of = {k: i for i, level in enumerate(lv) for k in level}
    assert level_of["data_model"] == level_of["ux_architecture"]


def test_integration_waits_for_both_branches():
    lv = levels()
    level_of = {k: i for i, level in enumerate(lv) for k in level}
    assert level_of["integration"] > level_of["backend"]
    assert level_of["integration"] > level_of["frontend"]
    assert level_of["verification"] > level_of["testing"]


def test_a_cycle_raises_instead_of_hanging():
    broken = {
        "a": DagNode("a", "api", frozenset({"b"})),
        "b": DagNode("b", "api", frozenset({"a"})),
    }
    with pytest.raises(CyclicDag):
        levels(broken)


def test_every_node_uses_a_registered_agent():
    from services.blueprint.agent_contract import capability_for
    for node in DAG.values():
        capability_for(node.agent)


def test_nodes_only_claim_to_produce_what_their_agent_may_write():
    """A node producing a section its agent cannot write would fail at apply
    time, deep inside a run, instead of here."""
    from services.blueprint.agent_contract import capability_for
    for node in DAG.values():
        cap = capability_for(node.agent)
        for section in node.produces:
            assert cap.can_write(section), (node.key, node.agent, section)


def test_descendants_walks_transitively():
    assert "verification" in descendants("data_model")
    assert "backend" in descendants("apis")
    assert descendants("preview") == set()


# --- §94: the state machine -------------------------------------------------

def test_states_match_section_94():
    assert len(STATES) == 15
    assert STATES[0] == "DISCOVERY" and STATES[-1] == "MAINTENANCE"


def test_legal_transition_advances(svc):
    assert svc.doc["state"] == "DISCOVERY"
    transition(svc, "CLARIFICATION")
    assert svc.doc["state"] == "CLARIFICATION"


def test_illegal_transition_is_refused(svc):
    with pytest.raises(IllegalTransition) as exc:
        transition(svc, "EXPORT_DEPLOY")
    assert "DISCOVERY" in str(exc.value)
    assert svc.doc["state"] == "DISCOVERY", "a refused transition must not move state"


def test_unknown_state_is_refused(svc):
    with pytest.raises(IllegalTransition):
        transition(svc, "VIBES")


def test_verification_can_loop_back_to_implementation():
    """§73 — verify, and on failure repair and verify again."""
    assert can_transition("VERIFICATION", "IMPLEMENTATION")
    assert can_transition("BUILD", "IMPLEMENTATION")


def test_maintenance_reopens_for_modification():
    """§114 — prompt-to-change keeps working after the app has shipped."""
    assert can_transition("MAINTENANCE", "ITERATION")
    assert can_transition("ITERATION", "IMPLEMENTATION")


def test_every_state_is_reachable_from_discovery():
    seen, frontier = {"DISCOVERY"}, ["DISCOVERY"]
    while frontier:
        for nxt in ALLOWED_TRANSITIONS.get(frontier.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    assert seen == set(STATES), f"unreachable: {set(STATES) - seen}"


# --- §71: impact analysis ---------------------------------------------------

def sample_doc() -> dict:
    return {
        "schemaVersion": "1", "version": 1, "state": "IMPLEMENTATION",
        "application": {"id": "a", "name": "R", "domain": "ATS"},
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Candidate", "table": "candidates"},
            {"id": "ENTITY-002", "name": "Office", "table": "offices"},
        ]},
        "apis": [
            {"id": "API-001", "method": "POST", "path": "/api/candidates",
             "entity": "ENTITY-001"},
            {"id": "API-002", "method": "GET", "path": "/api/offices",
             "entity": "ENTITY-002"},
        ],
        "pages": [{"id": "PAGE-001", "name": "Candidates", "route": "/candidates",
                   "purpose": "x", "data": {"primaryEntity": "ENTITY-001"}}],
        "workflows": [{"id": "FLOW-001", "name": "hire", "trigger": {"kind": "manual"},
                       "steps": [{"key": "s", "name": "save", "type": "action",
                                  "entity": "ENTITY-001"}]}],
        "tests": [{"id": "TEST-001", "name": "t", "kind": "api",
                   "verifies": ["PAGE-001"]}],
    }


def test_impact_reaches_everything_downstream_of_an_entity():
    hit = impacted_artifacts(sample_doc(), ["ENTITY-001"])
    assert {"ENTITY-001", "API-001", "PAGE-001", "FLOW-001", "TEST-001"} <= hit


def test_impact_does_not_over_reach():
    """§72 exists to avoid rebuilding everything; an impact set that includes
    the whole application makes it pointless."""
    hit = impacted_artifacts(sample_doc(), ["ENTITY-001"])
    assert "ENTITY-002" not in hit
    assert "API-002" not in hit


def test_impact_of_nothing_is_nothing():
    assert impacted_artifacts(sample_doc(), []) == set()


# --- §72: incremental plans -------------------------------------------------

def test_incremental_plan_is_a_subset_not_the_whole_dag():
    plan = incremental_plan(sample_doc(), ["ENTITY-001"])
    assert set(plan) < set(DAG), "an incremental change re-ran everything"
    assert "requirements" not in plan


def test_incremental_plan_keeps_dependency_order():
    plan = incremental_plan(sample_doc(), ["ENTITY-001"])
    order = [k for lvl in levels() for k in lvl]
    assert plan == [k for k in order if k in plan]


def test_incremental_plan_always_reverifies():
    """Skipping verification would leave the §75 matrix asserting a state that
    no longer holds."""
    plan = incremental_plan(sample_doc(), ["ENTITY-001"])
    assert "verification" in plan


# --- execution --------------------------------------------------------------

def page_agent_result(spec: TaskSpec) -> AgentResult:
    return AgentResult(
        task_id=spec.task_id, agent=spec.agent, confidence=0.95,
        proposals=[ArtifactProposal(
            section="pages", natural_key=page_key("/candidates"),
            body={"name": "Candidates", "route": "/candidates", "purpose": "x"},
        )],
    )


def test_run_executes_a_plan_in_order(svc):
    seen: list[str] = []

    def executor(spec: TaskSpec) -> AgentResult:
        seen.append(spec.node)
        return page_agent_result(spec)

    report = run(svc, executor, plan=["page_contracts"])
    assert report.ok
    assert seen == ["page_contracts"]
    assert report.artifacts == ["PAGE-001"]


def test_a_node_with_unmet_dependencies_is_skipped_not_attempted(svc):
    """The restraint that matters: an agent given missing inputs invents."""
    attempted: list[str] = []

    def executor(spec: TaskSpec) -> AgentResult:
        attempted.append(spec.node)
        if spec.node == "page_contracts":
            raise RuntimeError("page agent is down")
        return page_agent_result(spec)

    report = run(svc, executor, plan=["page_contracts", "page_designs"], max_attempts=1)
    assert "page_contracts" in report.failed
    assert "page_designs" in report.skipped
    assert "page_designs" not in attempted


def test_failed_tasks_are_retried(svc):
    calls: list[int] = []

    def flaky(spec: TaskSpec) -> AgentResult:
        calls.append(spec.attempt)
        if spec.attempt == 1:
            raise RuntimeError("transient")
        return page_agent_result(spec)

    report = run(svc, flaky, plan=["page_contracts"], max_attempts=2)
    assert report.ok
    assert calls == [1, 2]


def test_retry_does_not_duplicate_artifacts(svc):
    """§103 retryability is only safe because results are idempotent."""
    def always_ok(spec: TaskSpec) -> AgentResult:
        return page_agent_result(spec)

    run(svc, always_ok, plan=["page_contracts"])
    run(svc, always_ok, plan=["page_contracts"])
    assert len(svc.doc["pages"]) == 1


def test_low_confidence_blocks_the_node_and_its_dependents(svc):
    def unsure(spec: TaskSpec) -> AgentResult:
        r = page_agent_result(spec)
        r.confidence = 0.2
        return r

    report = run(svc, unsure, plan=["page_contracts", "page_designs"])
    assert "page_contracts" in report.blocked
    assert "page_designs" in report.skipped
    assert svc.doc.get("pages", []) == []


def test_capability_violations_surface_rather_than_being_swallowed(svc):
    from services.blueprint.agent_contract import CapabilityViolation

    def overreaching(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id, agent="page_design",
            proposals=[ArtifactProposal("businessRules", "k", {"name": "x"})],
        )

    with pytest.raises(CapabilityViolation):
        run(svc, overreaching, plan=["page_contracts"])


def test_run_can_commit_and_version(svc):
    report = run(
        svc, page_agent_result, plan=["page_contracts"],
        commit=True, user_request="Add candidates list.",
    )
    assert report.ok
    assert svc.doc["version"] == 2
    assert svc.doc["changeHistory"][-1]["userRequest"] == "Add candidates list."


# --- §26: the plan the user approves ---------------------------------------

def test_build_plan_summary_counts_what_section_26_shows():
    summary = build_plan_summary(sample_doc())
    assert summary["entities"] == 2
    assert summary["apis"] == 2
    assert summary["pages"] == 1
    assert summary["workflows"] == 1


# --- node kinds: not everything in the DAG is a model call ------------------

def test_verification_is_deterministic_not_an_agent_call():
    """It IS the §75 matrix. Routing it through a model is a category error —
    and its agent writes nothing, so any proposal it made would be refused,
    killing the run."""
    from services.blueprint.orchestrator import SERVICE_HANDLERS

    assert DAG["verification"].kind == "service"
    assert "verification" in SERVICE_HANDLERS


def test_verification_node_flags_findings_without_a_model(svc):
    """No executor is consulted — the handler runs the matrix directly."""
    svc.upsert("apis", {"method": "DELETE", "path": "/api/x"},
               natural_key="API:DELETE /api/x")

    def never_called(spec):
        raise AssertionError("a service node must not call an agent")

    report = run(svc, never_called, plan=["verification"])
    assert report.completed == ["verification"]
    assert svc.find("API-001")[1]["status"] == "OUT_OF_SYNC"


def test_projection_nodes_are_deterministic_not_model_calls():
    """The generated app is a scaffold plus vendored engines that read
    Blueprint-derived files at runtime — so these nodes emit data, not code.
    Nothing here is a design decision, and a model asked to fill codeMap would
    invent paths that pass validation against files nobody wrote."""
    from services.blueprint.orchestrator import PROJECTIONS

    for key in ("backend", "frontend", "integration", "preview"):
        assert DAG[key].kind == "projection", key
        assert key in PROJECTIONS, f"{key} must declare what it projects"


def test_every_projection_names_its_consuming_engine():
    from services.blueprint.orchestrator import PROJECTIONS

    for key, (writes, engine) in PROJECTIONS.items():
        assert writes and engine, key


def test_a_run_over_projection_nodes_reports_blocked_not_failed(svc):
    def never_called(spec):
        raise AssertionError("a projection node must not call an agent")

    report = run(svc, never_called, plan=["backend", "preview"])
    assert set(report.blocked) == {"backend", "preview"}
    assert report.failed == []


def test_every_node_declares_a_known_kind():
    from services.blueprint.orchestrator import NODE_KINDS

    for node in DAG.values():
        assert node.kind in NODE_KINDS, (node.key, node.kind)


def test_a_projection_with_a_handler_runs_deterministically(svc, tmp_path):
    """`backend` projects entities into Drizzle modules — no model involved."""
    from services.blueprint.ids import entity_key

    svc.upsert("data.entities",
               {"name": "Candidate", "table": "candidates",
                "fields": [{"name": "fullName", "type": "string"}]},
               natural_key=entity_key("Candidate"))

    def never_called(spec):
        raise AssertionError("a projection must not call an agent")

    report = run(svc, never_called, plan=["backend"], app_root=str(tmp_path))
    assert report.completed == ["backend"]
    assert (tmp_path / "src/db/schema/candidate.ts").exists()


def test_a_projection_without_an_app_root_stays_blocked(svc):
    def never_called(spec):
        raise AssertionError("a projection must not call an agent")

    report = run(svc, never_called, plan=["backend"])
    assert report.blocked == ["backend"]


def test_every_projection_and_service_node_has_a_handler():
    """A node with no handler stays blocked forever, which is the honest state
    while a projection is unported — and a silent dead end once it is not.

    This used to assert the opposite, that `frontend` and `preview` were still
    blocked. Every node is ported now, so the invariant worth holding is that
    none of them is a dead end.
    """
    from services.blueprint.orchestrator import PROJECTION_HANDLERS, SERVICE_HANDLERS

    handled = {**PROJECTION_HANDLERS, **SERVICE_HANDLERS}
    missing = [k for k, n in DAG.items()
               if n.kind in ("projection", "service") and k not in handled]
    assert not missing, f"no handler for: {missing}"


def test_ported_projections_run_without_an_agent(svc, tmp_path):
    """A projection is deterministic code, so it must never call a model."""
    from services.blueprint.orchestrator import PROJECTION_HANDLERS

    def never_called(spec):
        raise AssertionError("a projection must not call an agent")

    assert {"backend", "frontend"} <= set(PROJECTION_HANDLERS)
    report = run(svc, never_called, plan=["frontend"], app_root=str(tmp_path))
    assert report.completed == ["frontend"]
    assert report.failed == [] and report.blocked == []
