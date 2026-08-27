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
        svc, executor, "patterns", DAG["patterns"], "",
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
    assert "patterns" in plan


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
    """A component change still has to reach composition and the projections."""
    plan = incremental_plan(ats, ["CMP-033"])
    for required in ("patterns", "frontend", "integration", "verification", "preview"):
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

    report = run(svc, fails, plan=["page_contracts", "page_designs"],
                 max_attempts=1)
    # `skipped` stays node keys, so membership tests keep working.
    assert report.skipped == ["page_designs"]
    assert report.skipped_because["page_designs"] == "page_contracts"


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
