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
    # §28's first tier is everything with no upstream. `figma_intelligence`
    # joins it because §51 places design extraction upstream of requirement,
    # entity and page inference — it is evidence those work from.
    # `install` joins it because `npm install` needs nothing an agent writes
    # and used to be the last one to three minutes of every build.
    assert set(lv[0]) == {"requirements", "figma_intelligence", "install"}
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

    report = run(svc, executor, plan=["page_contracts", "page_details"], max_attempts=1)
    assert "page_contracts" in report.failed
    assert "page_details" in report.skipped
    assert "page_details" not in attempted


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

    report = run(svc, unsure, plan=["page_contracts", "page_details"])
    assert "page_contracts" in report.blocked
    assert "page_details" in report.skipped
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

    report = run(svc, fails, plan=["page_contracts", "page_details"],
                 max_attempts=1)
    # `skipped` stays node keys, so membership tests keep working.
    assert report.skipped == ["page_details"]
    assert report.skipped_because["page_details"] == "page_contracts"


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


def test_applies_happen_one_at_a_time_as_results_land(svc):
    """The split is the design: calls parallel, applies serial.

    `apply_agent_result` saves one shared document, so applies never overlap.
    They no longer wait their turn, though: the page that returns first
    applies first, so a rejection on page four is known — and its retry is
    out — while page one is still composing. Holding applies to the given
    order was what kept a fan-out at one to four calls in flight for the
    last half of its life.
    """
    import threading
    import time

    from services.blueprint import orchestrator

    _fanout_svc(svc, pages=4)
    applied: list[str] = []
    inflight, peak = 0, 0
    lock = threading.Lock()

    def executor(spec):
        # later subjects return first, so completion order is reversed
        time.sleep(0.05 * (4 - int(spec.subject[-1])))
        return _layout_result(spec)

    real_apply = orchestrator.apply_agent_result

    def tracking(service, result, **kw):
        nonlocal inflight, peak
        with lock:
            inflight += 1
            peak = max(peak, inflight)
        try:
            applied.append(result.proposals[0].body["page"])
            time.sleep(0.01)
            return real_apply(service, result, **kw)
        finally:
            with lock:
                inflight -= 1

    orchestrator.apply_agent_result = tracking
    try:
        run(svc, executor, plan=["page_layouts"], max_attempts=1)
    finally:
        orchestrator.apply_agent_result = real_apply

    assert peak == 1, "two applies overlapped"
    assert sorted(applied) == ["PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004"]
    assert applied[0] == "PAGE-004", "the first result to land waited for the slowest"


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


def test_independent_nodes_apply_as_they_land(svc):
    """The node-level half of the same rule the fan-out obeys.

    Four nodes writing four different sections have nothing to order between
    them: `design_system`'s result applying before `data_model`'s changes no
    id, because ids are numbered per section. So the node that returns first
    applies first — and its dependents start — while the slowest is still
    thinking. Holding the four to plan order was one wave's worth of waiting.
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
    assert applied == list(reversed(_WAVE))


def test_two_producers_of_one_section_apply_in_plan_order(svc):
    """The one place arrival order would show: `requirements` and
    `figma_intelligence` both write `requirements`, and a fresh document
    numbers REQ-001 for whichever proposal lands first. The later node in the
    plan waits for the earlier one to finish, so the numbering is the plan's
    and not the network's — and nothing else waits on anything."""
    import time

    from services.blueprint.ids import prose_key

    svc.doc["designSources"] = [{"id": "FIGMA-001", "type": "figma", "fileKey": "abc"}]
    applied: list[str] = []

    def executor(spec):
        if spec.node == "requirements":
            time.sleep(0.1)  # the earlier node is the slower one
        text = f"From {spec.node}"
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.95,
            proposals=[ArtifactProposal(
                section="requirements", natural_key=prose_key("REQ", text),
                body={"description": text})],
        )

    from services.blueprint import orchestrator

    real_apply = orchestrator.apply_agent_result

    def tracking(service, result, **kw):
        applied.append(result.agent)
        return real_apply(service, result, **kw)

    orchestrator.apply_agent_result = tracking
    try:
        report = run(svc, executor, plan=["requirements", "figma_intelligence"],
                     max_attempts=1)
    finally:
        orchestrator.apply_agent_result = real_apply

    assert report.ok, report.failed_because
    assert applied == ["requirement", "figma_intelligence"]
    assert svc.doc["requirements"][0]["description"] == "From requirements"


def test_yielding_only_runs_forward_in_the_plan():
    from services.blueprint.orchestrator import _yields_to

    order = ["requirements", "figma_intelligence", "application_model"]
    # the earlier producer of `requirements` is still running: wait
    assert _yields_to("figma_intelligence", order, {"requirements"}, set())
    # it finished: go
    assert not _yields_to("figma_intelligence", order, {"requirements"},
                          {"requirements"})
    # a node never waits on one behind it, so this cannot deadlock
    assert not _yields_to("requirements", order, {"figma_intelligence"}, set())
    # a node writing a different section has nothing to wait for
    assert not _yields_to("application_model", order,
                          {"requirements", "figma_intelligence"}, set())


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


def test_an_optional_node_failure_does_not_sink_the_run(svc):
    """`testing` is verification, not the running app — and the last node to
    spend the API. A failure there (a low credit balance) must NOT hold a built
    app in draft: it is shipped without, recorded in `degraded`, and the run
    stays ok so the app can still reach ready."""
    def executor(spec: TaskSpec) -> AgentResult:
        if spec.node == "testing":
            raise RuntimeError("credit balance too low")
        return page_agent_result(spec)

    report = run(svc, executor, plan=["testing"], max_attempts=1)
    assert report.ok, f"failed={report.failed} blocked={report.blocked}"
    assert "testing" in report.degraded and "testing" not in report.failed
    assert "credit balance too low" in report.degraded["testing"]


def test_a_fanout_resume_reruns_only_the_uncomposed_subjects():
    """Resume is continue, not redo, at the subject grain: a page that already
    has a composed `pageLayouts` row is not re-run, so a resume of a run that
    dropped pages recomposes exactly the ones that failed — not all of them,
    which on `page_layouts` (the dominant cost) would triple the bill."""
    from services.blueprint.orchestrator import DAG, subjects_for, pending_subjects
    doc = {
        "pages": [{"id": f"PAGE-{i}", "route": f"/p{i}"} for i in range(1, 5)],
        # two of the four already composed
        "pageLayouts": [{"page": "PAGE-1", "root": {}}, {"page": "PAGE-3", "root": {}}],
    }
    node = DAG["page_layouts"]
    assert sorted(subjects_for(node, doc)) == ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]
    assert sorted(pending_subjects(node, doc)) == ["PAGE-2", "PAGE-4"]
    # A fresh document (nothing composed) still runs every subject.
    assert sorted(pending_subjects(node, {"pages": doc["pages"], "pageLayouts": []})) == \
        ["PAGE-1", "PAGE-2", "PAGE-3", "PAGE-4"]


# ---------------------------------------------------------------------------
# Event-driven: a node starts when ITS dependencies are done, not its level's
# ---------------------------------------------------------------------------


def test_a_node_starts_the_moment_its_own_dependency_is_done(svc):
    """`database` depends on `data_model` and on nothing else at that level.
    The wave loop made it wait for `design_system` too, because they shared a
    topological level. Here `design_system` is the long pole and `database`
    must not be behind it."""
    import threading
    import time

    started: dict[str, float] = {}
    returned: dict[str, float] = {}
    lock = threading.Lock()

    def executor(spec):
        with lock:
            started[spec.node] = time.monotonic()
        if spec.node == "design_system":
            time.sleep(0.3)
        elif spec.node == "database":
            return AgentResult(
                task_id=spec.task_id, agent=spec.agent, confidence=0.95,
                proposals=[ArtifactProposal(
                    section="database", natural_key="database",
                    body={"engine": "postgres", "provider": "neon"})])
        with lock:
            returned[spec.node] = time.monotonic()
        return _wave_result(spec)

    report = run(svc, executor, plan=["data_model", "design_system", "database"],
                 max_attempts=1)
    assert report.ok, report.failed_because
    assert started["database"] < returned["design_system"], (
        "database waited for a node it does not depend on")


def test_a_rejected_subject_is_retried_while_its_siblings_are_still_running(svc):
    """The retry round used to open only when every first attempt in the
    wave had returned. A page refused in two seconds waited for the slowest
    page of the run before it was asked again."""
    import threading
    import time

    _fanout_svc(svc, pages=3)
    events: list[tuple[str, str, int, float]] = []
    lock = threading.Lock()

    def executor(spec):
        with lock:
            events.append(("start", spec.subject, spec.attempt, time.monotonic()))
        if spec.subject == "PAGE-003":
            time.sleep(0.3)  # the slow sibling
        elif spec.subject == "PAGE-001" and spec.attempt == 1:
            raise RuntimeError("refused at once")
        with lock:
            events.append(("end", spec.subject, spec.attempt, time.monotonic()))
        return _layout_result(spec)

    report = run(svc, executor, plan=["page_layouts"], max_attempts=2)
    assert report.ok, report.failed_because
    retry_started = next(t for k, s, a, t in events
                         if k == "start" and s == "PAGE-001" and a == 2)
    slow_returned = next(t for k, s, a, t in events
                         if k == "end" and s == "PAGE-003")
    assert retry_started < slow_returned, "the retry waited for the slowest sibling"


def test_a_dependent_starts_before_an_unrelated_fanout_finishes(svc):
    """The whole point, end to end: `page_layouts` is wide and slow, and
    `security` needs only `data_model`. `security` must run while pages are
    still composing rather than after the last one lands."""
    import threading
    import time

    _fanout_svc(svc, pages=4)
    started: dict[str, float] = {}
    finished: dict[str, float] = {}
    lock = threading.Lock()

    def executor(spec):
        with lock:
            started.setdefault(spec.node, time.monotonic())
        if spec.node == "page_layouts":
            time.sleep(0.25)
            out = _layout_result(spec)
        elif spec.node == "security":
            out = AgentResult(
                task_id=spec.task_id, agent=spec.agent, confidence=0.95,
                proposals=[ArtifactProposal(
                    section="roles", natural_key="Admin",
                    body={"name": "Admin", "description": "x"})])
        else:
            out = _wave_result(spec)
        with lock:
            finished[spec.node] = time.monotonic()
        return out

    # page_layouts' own dependencies are not in this plan, so it is ready at
    # once; security is ready as soon as data_model applies.
    report = run(svc, executor, plan=["page_layouts", "data_model", "security"],
                 max_attempts=1)
    assert report.ok, report.failed_because
    assert started["security"] < finished["page_layouts"], (
        "security waited for a fan-out it does not depend on")


def test_the_scheduler_holds_the_document_lock_while_applying(svc):
    """One writer. Executor threads read the document under `svc.lock` to
    build their prompts; the scheduler applies under it. An apply outside the
    lock would race a prompt being built from the same dict."""
    from services.blueprint import orchestrator

    _fanout_svc(svc, pages=2)
    owned: list[bool] = []
    real_apply = orchestrator.apply_agent_result

    def tracking(service, result, **kw):
        owned.append(service.lock._is_owned())
        return real_apply(service, result, **kw)

    orchestrator.apply_agent_result = tracking
    try:
        run(svc, _layout_result, plan=["page_layouts"], max_attempts=1)
    finally:
        orchestrator.apply_agent_result = real_apply
    assert owned and all(owned)


# ---------------------------------------------------------------------------
# Workflows are declared once and authored one at a time
# ---------------------------------------------------------------------------


def _declared_workflows(svc, n=3):
    svc.doc["pages"] = [{"id": "PAGE-001", "route": "/cases/new", "name": "New",
                         "purpose": "x"}]
    for i in range(1, n + 1):
        svc.upsert("workflows", {"name": f"Flow {i}", "trigger": {"kind": "manual"},
                                 "launchedFrom": ["PAGE-001"]},
                   natural_key=f"Flow {i}")
    return svc


def test_pages_compose_against_declared_workflows_not_their_steps():
    """A button names a workflow by id and supplies its inputs; it never reads
    a step. So `page_layouts` waits for the declaration and runs beside the
    step authoring, which was the longest node of a build and sat ahead of
    every page."""
    assert "workflows" in DAG["page_layouts"].depends_on
    assert "workflow_steps" not in DAG["page_layouts"].depends_on
    # what derives from steps waits for them
    assert "workflow_steps" in DAG["apis"].depends_on
    assert "workflow_steps" in DAG["integration"].depends_on
    assert DAG["workflow_steps"].fanout == "workflows"
    assert DAG["workflow_steps"].depends_on == frozenset({"workflows"})
    at = {k: i for i, level in enumerate(levels()) for k in level}
    assert at["page_layouts"] == at["workflow_steps"]


def test_workflow_steps_fan_out_over_the_declared_workflows(svc):
    from services.blueprint.orchestrator import pending_subjects, subjects_for

    _declared_workflows(svc, 3)
    ids = [w["id"] for w in svc.doc["workflows"]]
    assert subjects_for(DAG["workflow_steps"], svc.doc) == ids
    assert pending_subjects(DAG["workflow_steps"], svc.doc) == ids


def test_resuming_the_step_authoring_reruns_only_the_stepless(svc):
    """`workflows` and `workflow_steps` both write one section, so "the
    section has content" would call the author done the moment the declarer
    ran. What the author owes is a step graph per workflow, and that is what
    resume checks."""
    from services.blueprint.orchestrator import pending_subjects

    _declared_workflows(svc, 3)
    ids = [w["id"] for w in svc.doc["workflows"]]
    svc.doc["workflows"][1]["steps"] = [{"key": "end", "name": "End", "type": "end"}]
    assert pending_subjects(DAG["workflow_steps"], svc.doc) == [ids[0], ids[2]]
    assert "workflows" in completed_nodes(svc.doc)
    assert "workflow_steps" not in completed_nodes(svc.doc)
    for w in svc.doc["workflows"]:
        w["steps"] = [{"key": "end", "name": "End", "type": "end"}]
    assert "workflow_steps" in completed_nodes(svc.doc)


def test_each_workflow_is_authored_by_its_own_call(svc):
    _declared_workflows(svc, 3)
    seen: list[str] = []

    def executor(spec):
        seen.append(spec.subject)
        row = next(w for w in svc.doc["workflows"] if w["id"] == spec.subject)
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.95,
            proposals=[ArtifactProposal(
                section="workflows", natural_key=row["name"],
                body={"name": row["name"], "trigger": row["trigger"],
                      "steps": [{"key": "end", "name": "End", "type": "end"}]})])

    report = run(svc, executor, plan=["workflow_steps"], max_attempts=1)
    assert report.ok, report.failed_because
    assert sorted(seen) == sorted(w["id"] for w in svc.doc["workflows"])
    assert all(w["steps"] for w in svc.doc["workflows"])
    assert len(svc.doc["workflows"]) == 3, "authoring created a second row"


# ---------------------------------------------------------------------------
# The tail: install at second zero, build right after the join
# ---------------------------------------------------------------------------


def test_install_depends_on_nothing_and_the_build_waits_for_it():
    """`npm install` reads the scaffold's package.json and the vendored
    engines — the same for every application — so it can start with the
    first agent and be done before there is anything to compile."""
    assert DAG["install"].depends_on == frozenset()
    assert DAG["install"].kind == "projection"
    assert "install" in DAG["preview"].depends_on
    assert "integration" in DAG["preview"].depends_on
    assert "verification" not in DAG["preview"].depends_on, (
        "the compile waited for a report it does not read")
    assert "install" in levels()[0]


def test_testing_waits_for_what_it_reads_not_for_the_projections():
    from services.blueprint.agent_contract import capability_for

    reads = capability_for(DAG["testing"].agent).reads
    assert "codeMap" not in reads
    assert DAG["testing"].depends_on == frozenset({"apis", "workflow_steps", "business_rules"})


def test_a_deterministic_node_may_hand_back_a_future_and_is_done_when_it_lands(svc, tmp_path, monkeypatch):
    """A handler whose work is a process rather than a computation returns
    a future; the scheduler counts the node in flight — beside the agent
    calls, not blocking them — and records it when the process ends."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from services.blueprint import orchestrator

    order: list[str] = []
    lock = threading.Lock()

    def slow_install(service, app_root):
        pool = ThreadPoolExecutor(max_workers=1)

        def work():
            time.sleep(0.2)
            with lock:
                order.append("install-landed")
            return 0

        fut = pool.submit(work)
        pool.shutdown(wait=False)
        return fut

    def executor(spec):
        with lock:
            order.append(f"{spec.node}-called")
        return page_agent_result(spec)

    monkeypatch.setitem(orchestrator.PROJECTION_HANDLERS, "install", slow_install)
    report = run(svc, executor, plan=["install", "page_contracts"],
                 max_attempts=1, app_root=str(tmp_path / "app"))
    assert report.ok, report.failed_because
    assert sorted(report.completed) == ["install", "page_contracts"]
    assert order.index("page_contracts-called") < order.index("install-landed"), (
        "the agent call waited for the install to finish")


def test_a_failed_install_is_recorded_and_the_build_is_skipped(svc, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from services.blueprint import orchestrator

    def broken_install(service, app_root):
        pool = ThreadPoolExecutor(max_workers=1)

        def work():
            raise RuntimeError("npm ERR! ENOTFOUND registry.npmjs.org")

        fut = pool.submit(work)
        pool.shutdown(wait=False)
        return fut

    monkeypatch.setitem(orchestrator.PROJECTION_HANDLERS, "install", broken_install)
    report = run(svc, page_agent_result, plan=["install", "preview"],
                 max_attempts=1, app_root=str(tmp_path / "app"))
    assert report.failed == ["install"]
    assert "ENOTFOUND" in report.failed_because["install"]
    assert "preview" in report.skipped
    assert report.skipped_because["preview"] == "install"


def test_the_build_does_not_install_again_when_the_install_node_did(svc, tmp_path, monkeypatch):
    from services.blueprint import assembly, orchestrator

    app_root = tmp_path / "app"
    seen: list[dict] = []
    monkeypatch.setattr(assembly, "verify_build",
                        lambda root, **kw: seen.append(kw) or {"install": 0, "build": 0})
    monkeypatch.setattr(assembly, "apply_assembly", lambda *a, **k: {})
    monkeypatch.setattr(assembly, "page_funnel",
                        lambda doc, root: {"planned": 0, "served": 0, "missing": []})

    (app_root / "node_modules").mkdir(parents=True)
    orchestrator._project_preview(svc, str(app_root))
    assert seen[-1]["install"] is False

    import shutil
    shutil.rmtree(app_root / "node_modules")
    orchestrator._project_preview(svc, str(app_root))
    assert seen[-1]["install"] is True, "no node_modules: the build installs for itself"


# ---------------------------------------------------------------------------
# The page set is decided once and the contracts are written per feature
# ---------------------------------------------------------------------------


def _declared_pages(svc):
    from services.blueprint.ids import page_key

    svc.upsert("data.entities", {"name": "Case", "table": "cases",
                                 "fields": [{"name": "id", "type": "uuid"}]},
               natural_key="Case")
    svc.upsert("data.entities", {"name": "Note", "table": "notes",
                                 "fields": [{"name": "id", "type": "uuid"}]},
               natural_key="Note")
    case, note = (e["id"] for e in svc.doc["data"]["entities"])
    for route, name, entity in (("/cases", "Cases", case), ("/cases/[id]", "Case", case),
                                ("/notes", "Notes", note), ("/", "Home", None)):
        body = {"name": name, "route": route, "purpose": "x", "pattern": "entity_list"}
        if entity:
            body["data"] = {"primaryEntity": entity}
        svc.upsert("pages", body, natural_key=page_key(route))
    svc.validate()
    svc.save()
    return case, note


def test_workflows_are_declared_against_the_page_set_and_contracts_run_beside_them():
    """A workflow needs a page's id and route to say where it launches; a
    contract's tasks and states it never reads. The two longest declarations
    of a build used to run one after the other."""
    assert DAG["page_details"].depends_on == frozenset({"page_contracts"})
    assert DAG["page_details"].fanout == "page_features"
    assert "page_contracts" in DAG["workflows"].depends_on
    assert "page_details" not in DAG["workflows"].depends_on
    assert "page_details" in DAG["page_layouts"].depends_on
    assert "page_details" in DAG["apis"].depends_on
    at = {k: i for i, level in enumerate(levels()) for k in level}
    assert at["page_details"] == at["workflows"]
    assert at["page_layouts"] == at["workflow_steps"]


def test_a_feature_is_an_entitys_pages_and_an_orphan_page_is_its_own(svc):
    from services.blueprint.orchestrator import feature_pages, page_features

    case, note = _declared_pages(svc)
    home = next(p["id"] for p in svc.doc["pages"] if p["route"] == "/")
    assert page_features(svc.doc) == [case, note, home]
    assert [p["route"] for p in feature_pages(svc.doc, case)] == ["/cases", "/cases/[id]"]
    assert [p["route"] for p in feature_pages(svc.doc, home)] == ["/"]


def test_resuming_the_contracts_reruns_only_the_features_without_states(svc):
    """`page_contracts` and `page_details` both write `pages`, so "the section
    has content" would call the author done the moment the declaration ran.
    A contract declares its states up front; a declaration never does."""
    from services.blueprint.orchestrator import pending_subjects

    case, note = _declared_pages(svc)
    home = next(p["id"] for p in svc.doc["pages"] if p["route"] == "/")
    assert pending_subjects(DAG["page_details"], svc.doc) == [case, note, home]
    assert "page_contracts" in completed_nodes(svc.doc)
    assert "page_details" not in completed_nodes(svc.doc)
    for p in svc.doc["pages"]:
        if p["route"].startswith("/cases"):
            p["states"] = ["loading", "empty", "populated", "error"]
    assert pending_subjects(DAG["page_details"], svc.doc) == [note, home]
    for p in svc.doc["pages"]:
        p["states"] = ["loading", "populated"]
    assert "page_details" in completed_nodes(svc.doc)


def test_each_feature_is_written_by_its_own_call_onto_the_declared_pages(svc):
    """The executor's `pin_page_identity` resolves whatever key the author
    replied with to the declared one; here the executor is raw, so it
    answers under the declaration's own key."""
    from services.blueprint.ids import page_key
    from services.blueprint.orchestrator import feature_pages

    case, note = _declared_pages(svc)
    seen: list[str] = []

    def executor(spec):
        seen.append(spec.subject)
        return AgentResult(
            task_id=spec.task_id, agent=spec.agent, confidence=0.95,
            proposals=[ArtifactProposal(
                section="pages", natural_key=page_key(p["route"]),
                body={"name": p["name"], "route": p["route"], "purpose": "written",
                      "pattern": p["pattern"], "states": ["loading", "populated"]})
                for p in feature_pages(svc.doc, spec.subject)])

    report = run(svc, executor, plan=["page_details"], max_attempts=1)
    assert report.ok, report.failed_because
    assert len(seen) == 3 and len(svc.doc["pages"]) == 4, "authoring changed the page set"
    assert all(p["states"] and p["purpose"] == "written" for p in svc.doc["pages"])
