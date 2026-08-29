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
import time

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.ids import entity_key, page_key
from services.blueprint.orchestrator import (
    completed_nodes,
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
    sections_of,
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

    report = run(svc, executor, plan=["page_contracts", "page_layouts"], max_attempts=1)
    assert "page_contracts" in report.failed
    assert "page_layouts" in report.skipped
    assert "page_layouts" not in attempted


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

    report = run(svc, unsure, plan=["page_contracts", "page_layouts"])
    assert "page_contracts" in report.blocked
    assert "page_layouts" in report.skipped
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


def test_a_rejected_proposal_is_re_asked_with_the_reason(svc):
    """Rejecting without saying why makes the retry reproduce the mistake.

    Two pages failed twice each on the same bad enum value because the second
    attempt received a byte-identical prompt.
    """
    from services.blueprint.agent_contract import InvalidPatternTemplate
    from services.blueprint.orchestrator import DAG, RunReport, _run_agent_subject

    seen: list[str] = []

    def executor(spec):
        seen.append(spec.feedback)
        raise InvalidPatternTemplate("root.props.variant: 'ghost' is not allowed")

    report = RunReport()
    _run_agent_subject(
        svc, executor, "page_layouts", DAG["page_layouts"], "",
        max_attempts=2, commit=False, user_request="", report=report,
    )
    assert len(seen) == 2, "the subject must actually be retried"
    assert seen[0] == "", "the first attempt has nothing to react to"
    assert "ghost" in seen[1], "the retry must be told what was rejected"


def test_the_reason_reaches_the_prompt(svc):
    from services.blueprint.executors import build_prompt

    _, plain = build_prompt(svc.doc, "page_layouts", subject="PAGE-001")
    _, retry = build_prompt(svc.doc, "page_layouts", subject="PAGE-001",
                            feedback="root.props.variant: 'ghost' is not allowed")
    assert "ghost" in retry and "ghost" not in plain

# --- §72: the frame is not rebuilt for every change -------------------------

def test_foundational_nodes_are_classified_by_what_they_produce():
    """§72 enumerates what an incremental change affects: requirements, pages,
    components, entities, APIs, workflows, rules, tests, source files,
    migrations. It conspicuously omits the application's frame — what it is,
    what it looks like, how it is organised, what it talks to."""
    from services.blueprint.orchestrator import is_foundational

    frame = {k for k, n in DAG.items() if is_foundational(n)}
    assert frame == {"application_model", "design_system", "integrations",
                     "ux_architecture"}


def test_service_and_projection_nodes_are_never_foundational():
    """They are deterministic and cheap, and a projection that does not run
    leaves the application unbuilt."""
    from services.blueprint.orchestrator import is_foundational

    for node in DAG.values():
        if node.kind in ("service", "projection"):
            assert not is_foundational(node), node.key


def test_a_rule_change_does_not_re_author_the_design_language(ats):
    """The DAG is a chain — requirements -> application_model -> {design_system,
    integrations, ux_architecture} -> everything — so `descendants` alone made
    every plan the whole DAG. Measured on this fixture: 19 of 22 nodes for a
    change that added two rules and a field."""
    plan = incremental_plan(ats, ["RULE-004"], also_sections={"businessRules"})
    assert "design_system" not in plan
    assert "integrations" not in plan
    assert "application_model" not in plan
    assert len(plan) < len(DAG)


def test_containment_does_not_seed_the_frame(ats):
    """Impact reaches a MODULE because that module *contains* the page that
    changed. Seeding `ux_architecture` off that has it re-author the module and
    navigation structure because a table was made more compact."""
    plan = incremental_plan(ats, ["CMP-033", "PAGE-009"])
    assert "modules" in sections_of(ats, impacted_artifacts(ats, ["CMP-033", "PAGE-009"]))
    assert "ux_architecture" not in plan


def test_writing_the_frame_does_seed_it(ats):
    """The safety valve. When the frame genuinely moves — a new module — Smith
    writes that section and the node is seeded directly."""
    plan = incremental_plan(ats, [], also_sections={"modules"})
    assert "ux_architecture" in plan


def test_each_frame_section_can_still_reach_its_node(ats):
    """Every foundational node must remain reachable by writing what it owns,
    or the frame could never be changed at all."""
    from services.blueprint.orchestrator import is_foundational

    for key, node in DAG.items():
        if not is_foundational(node):
            continue
        for section in node.produces:
            assert key in incremental_plan(ats, [], also_sections={section}), (key, section)


def test_dropping_a_frame_node_does_not_hide_what_sits_behind_it(ats):
    """`patterns` depends on `design_system`. Filtering after the closure
    rather than during it keeps every other node reachable *through* the ones
    that are dropped."""
    plan = incremental_plan(ats, ["PAGE-009"])
    assert "design_system" not in plan
    assert "page_layouts" in plan


def test_the_plan_still_reaches_the_implementation(ats):
    """Narrowing must not cut the projections off — a change that never
    regenerates anything is not a change."""
    plan = incremental_plan(ats, ["RULE-004"], also_sections={"businessRules"})
    for required in ("integration", "testing", "verification", "preview"):
        assert required in plan


# --- §20: an agent must not re-author what Smith just wrote -----------------

def test_a_section_this_change_wrote_is_not_re_authored(ats):
    """§20 — "future agents must respect accepted decisions unless deliberately
    changed", and a regeneration is not a deliberate change. Re-running
    `business_rules` over a rule Smith wrote from the user's own words has the
    agent write over it."""
    plan = incremental_plan(
        ats, ["RULE-004"],
        also_sections={"businessRules"}, already_written={"businessRules"},
    )
    assert "business_rules" not in plan


def test_downstream_of_a_written_section_still_runs(ats):
    """The complement: what Smith wrote still has to reach the implementation."""
    plan = incremental_plan(
        ats, ["RULE-004"],
        also_sections={"businessRules"}, already_written={"businessRules"},
    )
    assert "integration" in plan and "verification" in plan

# --- §72: the plan follows dataflow, not the impact closure -----------------

def test_a_presentational_change_does_not_re_author_the_rule_catalogue(ats):
    """`business_rules` depends only on `data_model`, so a component is not one
    of its inputs. It was being seeded because the *impact closure* from
    CMP-033 reaches a RULE — via a page that contains the component — and
    `sections_of` then reported `businessRules` as touched.

    Impact answers "what might be affected", which is what §71 reports to the
    user. That is a different claim from "this section's owner must re-author
    its catalogue"."""
    assert "businessRules" in sections_of(
        ats, impacted_artifacts(ats, ["CMP-033", "PAGE-009"], depth=2)
    ), "the closure really does reach rules — that is the trap"
    assert "businessRules" not in sections_of(ats, {"CMP-033", "PAGE-009"})

    plan = incremental_plan(ats, ["CMP-033", "PAGE-009"])
    assert "business_rules" not in plan


def test_an_entity_change_does_re_author_the_rules(ats):
    """The complement, and the reason the edge exists: rules are authored from
    the data model, so an entity change is genuinely one of their inputs."""
    assert "business_rules" in incremental_plan(ats, ["ENTITY-003"])


def test_a_plan_is_seeded_by_what_changed_not_by_what_it_touches(ats):
    """The closure reaches six sections from one component; directly it is two.
    A plan seeded from the closure re-runs nodes that cannot see the change."""
    direct = incremental_plan(ats, ["CMP-033"])
    from services.blueprint.orchestrator import sections_of as _sections

    assert _sections(ats, {"CMP-033"}) == {"components"}
    assert "business_rules" not in direct
    assert "database" not in direct
    assert "security" not in direct


def test_narrowing_did_not_cut_off_what_reads_the_change(ats):
    """A page change still has to reach composition and the projections.

    Anchored on a component before: `components` was authored by `page_designs`
    and read by the composer. Nothing authors it now — the frontend projection
    derives it from the trees A2UI composed — so a component id is no longer a
    change anything upstream can respond to.
    """
    plan = incremental_plan(ats, ["PAGE-009"])
    for required in ("page_layouts", "frontend", "integration", "verification", "preview"):
        assert required in plan, required


def test_a_skipped_node_records_which_dependency_stopped_it(svc):
    """A plan that quietly drops nodes reads exactly like one that ran them.

    During an incremental change the `apis` node was skipped for an unmet
    dependency, so the Blueprint kept the 51 endpoints it already had while the
    data model had gained two entities — and nothing in the output said the
    derivation never ran. Counting skips is not enough; the reason is the part
    that makes it actionable.
    """
    def fails(spec):
        raise RuntimeError("no")

    report = run(svc, fails, plan=["page_contracts", "page_layouts"],
                 max_attempts=1)
    # `skipped` stays node keys, so membership tests keep working.
    assert report.skipped == ["page_layouts"]
    assert report.skipped_because["page_layouts"] == "page_contracts"


def test_a_node_that_ran_is_not_recorded_as_skipped(svc):
    report = run(svc, lambda spec: None, plan=[])
    assert report.skipped == [] and report.skipped_because == {}


def _layout_result(spec: TaskSpec) -> AgentResult:
    """One authored page tree, keyed to the subject the node fanned out to."""
    return AgentResult(
        task_id=spec.task_id, agent=spec.agent, confidence=0.95,
        proposals=[ArtifactProposal(
            section="pageLayouts", natural_key=spec.subject,
            body={"page": spec.subject,
                  "root": {"type": "Stack", "props": {}, "children": []}},
        )],
    )


def _fanout_svc(svc, pages=3):
    svc.doc["pages"] = [
        {"id": f"PAGE-{i:03d}", "route": f"/p{i}", "name": f"P{i}",
         "purpose": f"Page {i}."}
        for i in range(1, pages + 1)
    ]
    return svc


def test_one_failed_subject_does_not_take_the_whole_node(svc):
    """One page of twenty-four failed on a live run and `page_layouts` failed
    with it, skipping frontend, integration, testing, memory, verification and
    preview. One bad page cost the entire application.

    The hole was the thing to close, not the node: the failure is named, and a
    page with no authored tree still falls back to its pattern.
    """
    _fanout_svc(svc)
    seen: list[str] = []

    def executor(spec):
        seen.append(spec.subject)
        if spec.subject == "PAGE-002":
            raise RuntimeError("this one is broken")
        return _layout_result(spec)

    report = run(svc, executor, plan=["page_layouts"], max_attempts=1)
    # every subject was attempted, not abandoned at the first failure
    assert seen == ["PAGE-001", "PAGE-002", "PAGE-003"]
    assert "page_layouts" in report.completed
    assert any("PAGE-002" in f for f in report.failed)


def test_a_node_that_authored_nothing_at_all_has_genuinely_failed(svc):
    """Partial results are usable; no result is not."""
    _fanout_svc(svc)

    def executor(spec):
        raise RuntimeError("all broken")

    report = run(svc, executor, plan=["page_layouts"], max_attempts=1)
    assert "page_layouts" not in report.completed
    assert len(report.failed) == 3


def test_a_partial_node_still_unblocks_what_depends_on_it(svc):
    """The point of the change: downstream work proceeds on partial input."""
    _fanout_svc(svc)

    def executor(spec):
        if spec.subject == "PAGE-002":
            raise RuntimeError("broken")
        return _layout_result(spec)

    report = run(svc, executor, plan=["page_layouts", "frontend"],
                 max_attempts=1, app_root="/tmp/forge-partial-test")
    assert "frontend" not in report.skipped, (
        "a partial page_layouts must not skip the projection behind it")


def test_a_failed_node_records_why(svc):
    """`failed: ["data_model"]` and nothing else made a rate limit and a
    malformed envelope indistinguishable. Four nodes failed consecutively on
    one live run and the report could not say whether the cause was transport
    or content — the reason was being computed for the retry's feedback and
    then discarded."""
    def boom(spec):
        raise TimeoutError("upstream timed out")

    report = run(svc, boom, plan=["requirements"], max_attempts=1)
    assert report.failed == ["requirements"]
    assert "TimeoutError" in report.failed_because["requirements"]
    assert "upstream timed out" in report.failed_because["requirements"]


def test_a_rejected_proposal_records_the_contract_error(svc):
    """A rejection is a different kind of failure from a transport fault, and
    the report has to be able to tell them apart."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal

    def bad_shape(spec):
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.95,
            proposals=[ArtifactProposal(
                section="pages", natural_key="p",
                body={"name": "No route or purpose"},
            )],
        )

    report = run(svc, bad_shape, plan=["page_contracts"], max_attempts=1)
    assert report.failed == ["page_contracts"]
    why = report.failed_because["page_contracts"]
    assert "BlueprintInvalid" in why or "required" in why


def test_the_reason_is_one_readable_line(svc):
    def boom(spec):
        raise RuntimeError("line one\nline two\n" + "x" * 900)

    report = run(svc, boom, plan=["requirements"], max_attempts=1)
    why = report.failed_because["requirements"]
    assert "\n" not in why and len(why) <= 400


def test_the_fanout_runs_subjects_concurrently(svc):
    """§28: "independent work may execute concurrently." Pages are genuinely
    independent — each call gets one page's brief and reads nothing another
    page wrote — and serially they were the dominant cost of a run."""
    import threading
    import time

    from services.blueprint.orchestrator import FANOUT_CONCURRENCY

    _fanout_svc(svc, pages=6)
    inflight, peak = 0, 0
    lock = threading.Lock()

    def executor(spec):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        time.sleep(0.05)
        with lock:
            inflight -= 1
        return _layout_result(spec)

    run(svc, executor, plan=["page_layouts"], max_attempts=1)
    assert peak > 1, "subjects ran one at a time"
    assert peak <= FANOUT_CONCURRENCY


def test_applies_happen_in_the_given_order_whatever_order_calls_return(svc):
    """The split is the design: calls parallel, applies serial and ordered.

    `apply_agent_result` allocates ids and saves one shared document, so
    concurrent applies would race — and id allocation is order-dependent, so a
    re-projection meant to be byte-identical would stop being one.
    """
    import time

    _fanout_svc(svc, pages=4)
    applied: list[str] = []

    def executor(spec):
        # later subjects return first, so completion order is reversed
        time.sleep(0.05 * (4 - int(spec.subject[-1])))
        return _layout_result(spec)

    original = svc.upsert

    def tracking(section, body, **kw):
        if section == "pageLayouts":
            applied.append(body["page"])
        return original(section, body, **kw)

    svc.upsert = tracking
    run(svc, executor, plan=["page_layouts"], max_attempts=1)
    svc.upsert = original
    assert applied == ["PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004"]


def test_a_retry_still_carries_its_own_feedback(svc):
    """Concurrency must not lose §102's feedback: a retry that is not told what
    went wrong is just the same request again."""
    _fanout_svc(svc, pages=3)
    seen: dict[str, list[str]] = {}

    def executor(spec):
        seen.setdefault(spec.subject, []).append(spec.feedback)
        if spec.subject == "PAGE-002" and spec.attempt == 1:
            raise RuntimeError("bad page tree")
        return _layout_result(spec)

    report = run(svc, executor, plan=["page_layouts"], max_attempts=2)
    assert seen["PAGE-002"][0] == ""
    assert "bad page tree" in seen["PAGE-002"][1]
    assert report.failed == []
    # subjects that succeeded first time are not called again
    assert len(seen["PAGE-001"]) == 1


# ---------------------------------------------------------------------------
# Resume skips what is already authored
# ---------------------------------------------------------------------------


def test_completed_nodes_reports_sections_with_content():
    """A node whose produced sections are populated has already run."""
    doc = {"requirements": [{"id": "REQ-001"}], "product": {"objectives": ["x"]}}
    done = completed_nodes(doc)
    assert "requirements" in done
    assert "application_model" in done
    # `data_model` produces data.entities, which this document does not have.
    assert "data_model" not in done


def test_completed_nodes_resolves_dotted_paths():
    """`data.entities` is nested, not a top-level key."""
    assert "data_model" not in completed_nodes({"data": {}})
    assert "data_model" in completed_nodes({"data": {"entities": [{"id": "E1"}]}})


def test_completed_nodes_treats_empty_sections_as_unrun():
    """An empty list is what an un-run node leaves behind, not an answer."""
    assert "requirements" not in completed_nodes({"requirements": []})


def test_completed_nodes_never_skips_projections():
    """Projections cost no tokens and are how a fixed projection reaches disk.

    `backend` produces codeMap; a populated codeMap must not stop it re-running,
    or a repaired projection would preserve the output it was meant to replace.
    """
    doc = {"codeMap": [{"artifact": "PAGE-001"}], "runtime": {"port": 3000}}
    done = completed_nodes(doc)
    assert "backend" not in done
    assert "frontend" not in done
    assert "preview" not in done


def test_completed_nodes_empty_for_a_fresh_document():
    assert completed_nodes({}) == set()
# --- §28: independent *nodes*, not just independent subjects ----------------

#: Four nodes with no dependency between them — §28's own example of work that
#: "may execute concurrently", and the level the DAG spends longest in.
_WAVE = ["data_model", "design_system", "integrations", "ux_architecture"]

#: One valid proposal per node of that wave, so the ordering claim below is
#: about applies that really happened rather than about rejected ones.
_WAVE_PROPOSAL = {
    "data_model": ("data.entities", "Candidate",
                   {"name": "Candidate", "table": "candidates",
                    "fields": [{"name": "id", "type": "uuid"}]}),
    "design_system": ("designSystem", "designSystem",
                      {"visualPersonality": "calm",
                       "informationDensity": "comfortable"}),
    "integrations": ("integrations", "Slack", {"name": "Slack", "kind": "webhook"}),
    "ux_architecture": ("modules", "Hiring", {"name": "Hiring", "description": "x"}),
}


def _wave_result(spec: TaskSpec) -> AgentResult:
    section, natural_key, body = _WAVE_PROPOSAL[spec.node]
    return AgentResult(
        task_id=spec.task_id, agent=spec.agent, confidence=0.95,
        proposals=[ArtifactProposal(section=section, natural_key=natural_key,
                                    body=body)],
    )


def test_a_wave_of_independent_nodes_runs_concurrently(svc):
    """The graph already declared these four independent and we ran them one
    after another. Fifteen agent nodes at a level apiece is most of the wall
    time of a run, and none of it was work that had to wait."""
    import threading
    import time

    from services.blueprint.orchestrator import WAVE_CONCURRENCY

    inflight, peak = 0, 0
    lock = threading.Lock()

    def executor(spec):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        time.sleep(0.05)
        with lock:
            inflight -= 1
        return _wave_result(spec)

    report = run(svc, executor, plan=_WAVE, max_attempts=1)
    assert report.ok
    assert sorted(report.completed) == sorted(_WAVE)
    assert peak > 1, "independent nodes ran one at a time"
    assert peak <= WAVE_CONCURRENCY


def test_a_wave_applies_node_by_node_whatever_order_calls_return(svc):
    """The node-level half of the same rule the fan-out obeys.

    Four nodes calling at once means four nodes applying into one shared
    document, and ``apply_agent_result`` allocates stable ids (§12) in the order
    it is called. If applies interleaved by whichever call returned first, a
    re-projection meant to be byte-identical would stop being one — and
    ``project_frontend`` is idempotent by design.

    A lock would not fix this. It would make the applies safe against
    corruption and leave the order nondeterministic, which is the half that
    matters.
    """
    import time

    applied: list[str] = []

    def executor(spec):
        # last node returns first, so completion order is exactly reversed
        time.sleep(0.05 * (len(_WAVE) - 1 - _WAVE.index(spec.node)))
        return _wave_result(spec)

    from services.blueprint import orchestrator

    real_apply = orchestrator.apply_agent_result

    def tracking(service, result, **kw):
        applied.append(result.task_id.split("-")[1])
        return real_apply(service, result, **kw)

    orchestrator.apply_agent_result = tracking
    try:
        report = run(svc, executor, plan=_WAVE, max_attempts=1)
    finally:
        orchestrator.apply_agent_result = real_apply

    assert report.ok
    assert applied == _WAVE


def test_a_node_retried_inside_a_wave_still_carries_its_feedback(svc):
    """§102 survives the widening, at node level as well as subject level: a
    retry that is not told what went wrong is just the same request again."""
    seen: dict[str, list[str]] = {}

    def executor(spec):
        seen.setdefault(spec.node, []).append(spec.feedback)
        if spec.node == "integrations" and spec.attempt == 1:
            raise RuntimeError("provider list was empty")
        return _wave_result(spec)

    report = run(svc, executor, plan=_WAVE, max_attempts=2)
    assert report.ok
    assert seen["integrations"][0] == ""
    assert "provider list was empty" in seen["integrations"][1]
    # nodes that succeeded first time are not called again
    assert len(seen["data_model"]) == 1


def test_a_failed_node_does_not_stop_its_neighbours_in_the_wave(svc):
    """Independence cuts both ways: a node that fails takes its own dependents
    with it and nothing else."""
    def executor(spec):
        if spec.node == "data_model":
            raise RuntimeError("entity agent is down")
        return _wave_result(spec)

    report = run(svc, executor, plan=_WAVE, max_attempts=1)
    assert report.failed == ["data_model"]
    assert sorted(report.completed) == ["design_system", "integrations",
                                        "ux_architecture"]


def test_a_wave_never_starts_a_node_whose_dependency_failed(svc):
    """§28's restraint is unchanged by the widening: a dependent of a failed
    node is skipped, not attempted on missing inputs."""
    attempted: list[str] = []

    def executor(spec):
        attempted.append(spec.node)
        if spec.node == "data_model":
            raise RuntimeError("entity agent is down")
        return _wave_result(spec)

    report = run(svc, executor, plan=_WAVE + ["database"], max_attempts=1)
    assert "database" in report.skipped
    assert report.skipped_because["database"] == "data_model"
    assert "database" not in attempted


def test_one_node_cannot_spend_the_whole_wave_budget(svc):
    """A wave of fanning-out nodes multiplies, and the multiplication is what
    finds the provider's rate limit rather than the machine's.

    Two caps, and they answer different questions: how wide one node may go,
    and how wide the run may go. `page_layouts` here has more subjects than
    either budget, so it would take every slot if only the wave cap existed.
    """
    import threading

    from services.blueprint.orchestrator import (
        FANOUT_CONCURRENCY, WAVE_CONCURRENCY,
    )

    _fanout_svc(svc, pages=24)
    lock = threading.Lock()
    inflight: dict[str, int] = {}
    total = peak_total = 0
    peak_node: dict[str, int] = {}

    def executor(spec):
        nonlocal total, peak_total
        with lock:
            total += 1
            peak_total = max(peak_total, total)
            inflight[spec.node] = inflight.get(spec.node, 0) + 1
            peak_node[spec.node] = max(peak_node.get(spec.node, 0),
                                       inflight[spec.node])
        time.sleep(0.02)
        with lock:
            total -= 1
            inflight[spec.node] -= 1
        if spec.node == "page_layouts":
            return _layout_result(spec)
        return _wave_result(spec)

    # `page_layouts` depends on `patterns`, which is not in this plan — so all
    # three nodes are ready at once and share one wave.
    plan = ["page_layouts", "data_model", "integrations"]
    report = run(svc, executor, plan=plan, max_attempts=1)

    assert report.ok
    assert sorted(report.completed) == sorted(plan)
    assert peak_total <= WAVE_CONCURRENCY, "the wave budget was exceeded"
    assert peak_node["page_layouts"] <= FANOUT_CONCURRENCY, (
        "one node took more than its own width out of the shared budget")
