"""The observer closes §73's loop at the node.

What these tests hold it to, in order of how much it would cost to get wrong:

* it never authors — the same boundary check that stops every other agent
  stops it, and a repair is the OWNING agent's re-authoring with the findings
  as feedback;
* a node the observer fails is repaired before anything downstream runs;
* an edge is judged only once both of its sides exist, so the requirements
  author is never told nothing implements a requirement before a page exists;
* the critic's verdict is a closed shape with nowhere to put a fix, an
  unavailable critic is recorded rather than replaced with a guess, and a
  ``fail`` with no findings is an opinion;
* what cannot be brought round is flagged OUT_OF_SYNC and named in the
  report, never patched.
"""
import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult,
    ArtifactProposal,
    CapabilityViolation,
    apply_agent_result,
    capability_for,
)
from services.blueprint.ids import page_key, role_key
from services.blueprint.observer import (
    CRITIC_EDGE,
    VERDICT_SCHEMA,
    Observation,
    OBSERVER_MODEL_ENV,
    Observer,
    RepairTask,
    anthropic_observer,
    critic_prompt,
    observation_context,
    owned_sections,
    ready_edges,
)
from services.blueprint.orchestrator import DAG, TaskSpec, run
from services.blueprint.run_ledger import read, runs
from services.blueprint.service import BlueprintService
from services.blueprint.verification import (
    CHECKS,
    EDGE_SECTIONS,
    EDGES,
    SECTION_OWNER,
    Finding,
)


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )
    # A role, so Page↔Permission has a settled side to be judged against.
    s.upsert("roles", {"name": "Admin"}, natural_key=role_key("Admin"))
    s.save()
    return s


def page(spec: TaskSpec, *, users: list[str] | None = None,
         route: str = "/candidates") -> AgentResult:
    body = {"name": "Candidates", "route": route, "purpose": "list candidates"}
    if users is not None:
        body["users"] = users
    return AgentResult(
        task_id=spec.task_id, agent=spec.agent, confidence=0.95,
        proposals=[ArtifactProposal(
            section="pages", natural_key=page_key(route), body=body,
        )],
    )


class Ghost:
    """An author that addresses its page to a role that does not exist until
    it is told about it — the defect the observer must catch and the brief
    must fix."""

    def __init__(self, *, fix_after: int = 1) -> None:
        self.calls: list[TaskSpec] = []
        self.fix_after = fix_after

    def __call__(self, spec: TaskSpec) -> AgentResult:
        self.calls.append(spec)
        if spec.node != "page_contracts":
            raise AssertionError(f"unexpected node {spec.node}")
        repairs = sum(1 for c in self.calls if "observer" in c.task_id)
        if repairs >= self.fix_after:
            return page(spec, users=["ROLE-001"])
        return page(spec, users=["ROLE-999"])


# --- the boundary -----------------------------------------------------------

def test_the_observer_is_registered_flag_only():
    cap = capability_for("observer")
    assert not cap.writes
    assert cap.may_set_status


def test_the_observer_cannot_author_even_if_it_tries(svc):
    """The check that stops it is the same one that stops every agent."""
    result = AgentResult(
        task_id="TASK-observer", agent="observer",
        proposals=[ArtifactProposal(
            section="pages", natural_key=page_key("/x"),
            body={"name": "X", "route": "/x", "purpose": "p"},
        )],
    )
    with pytest.raises(CapabilityViolation):
        apply_agent_result(svc, result)


def test_the_verdict_shape_has_nowhere_to_put_a_fix():
    props = VERDICT_SCHEMA["properties"]["findings"]["items"]["properties"]
    assert set(props) == {"section", "artifact", "requirement", "detail"}
    assert VERDICT_SCHEMA["properties"]["findings"]["items"]["additionalProperties"] is False
    # Structured-output safe: the contract's own schema is rejected for these.
    assert "pattern" not in json.dumps(VERDICT_SCHEMA)


# --- readiness --------------------------------------------------------------

def test_every_edge_declares_what_it_relates():
    assert set(EDGE_SECTIONS) == set(CHECKS) == set(EDGES)
    writable = set(SECTION_OWNER) | {"codeMap"}
    for edge, sections in EDGE_SECTIONS.items():
        assert sections, edge
        for s in sections:
            assert s in writable, (edge, s)


def test_an_edge_waits_for_a_pending_side(svc):
    ready = ready_edges(svc.doc, pending={"apis"}, planned={"pages", "apis"})
    assert "Page↔API" not in ready
    assert "Page↔Permission" in ready  # roles present, nothing pending on it


def test_an_edge_never_judges_against_a_side_nothing_will_write(svc):
    """codeMap is empty and no projection is in the plan: Requirement↔Code
    would say every requirement is unimplemented. It is not ready."""
    ready = ready_edges(svc.doc, pending=set(), planned={"requirements"})
    assert "Requirement↔Code" not in ready
    assert "Requirement↔Test" not in ready


def test_a_planned_side_that_has_completed_is_settled(svc):
    ready = ready_edges(svc.doc, pending=set(), planned={"pages", "apis"})
    assert "Page↔API" in ready


# --- deterministic judgement -------------------------------------------------

def test_findings_are_filed_to_the_node_that_owns_them(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-404"]}, natural_key=page_key("/c"))
    obs = Observer().observe(
        "page_contracts", agent="page_design", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert not obs.ok
    assert [f.edge for f in obs.findings[""]] == ["Page↔Permission"]
    assert "ROLE-404" in obs.brief("")


def test_another_agents_finding_is_deferred_not_repaired_here(svc):
    """Observing `security` after the page above: the finding is on `pages`,
    which security does not own. Re-authoring roles would not fix the page,
    and re-authoring the page would re-order the DAG."""
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-404"]}, natural_key=page_key("/c"))
    obs = Observer().observe(
        "security", agent="security", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages", "roles"},
    )
    assert obs.ok
    assert [f.edge for f in obs.deferred] == ["Page↔Permission"]


def test_a_fanout_finding_is_filed_to_its_subject(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-404"]}, natural_key=page_key("/c"))
    svc.upsert("pages", {"name": "D", "route": "/d", "purpose": "p"},
               natural_key=page_key("/d"))
    ids = [p["id"] for p in svc.doc["pages"]]
    obs = Observer().observe(
        "page_contracts", agent="page_design", subjects=ids, doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert set(obs.findings) == {ids[0]}
    assert [t.subject for t in Observer().repairs(obs)] == [ids[0]]


# --- the loop, through the orchestrator -------------------------------------

def test_a_failed_node_is_sent_back_to_its_author_with_the_findings(svc):
    author = Ghost()
    report = run(svc, author, plan=["page_contracts"],
                 observer_agent=Observer())
    assert report.ok
    assert report.repaired == ["page_contracts"]
    assert report.unrepaired == {}
    # Two calls: the original and one repair, told exactly what was wrong.
    assert [c.attempt for c in author.calls] == [1, 1]
    assert "observer" in author.calls[1].task_id
    assert "ROLE-999" in author.calls[1].feedback
    assert "Page↔Permission" in author.calls[1].feedback
    # The document holds the repaired page, and only one of it.
    assert [p["users"] for p in svc.doc["pages"]] == [["ROLE-001"]]
    assert svc.doc["pages"][0]["status"] != "OUT_OF_SYNC"


def test_the_repair_lands_before_any_dependent_runs(svc):
    """§28: a dependent that consumed the defect is the swarm. A node under
    observation is finished but not done, so `workflows` — which depends on
    `page_contracts` — does not start until the repair has landed."""
    order: list[str] = []

    class Both(Ghost):
        def __call__(self, spec: TaskSpec) -> AgentResult:
            order.append(spec.task_id)
            if spec.node == "workflows":
                # Sees the repaired page or it does not run at all.
                assert svc.doc["pages"][0]["users"] == ["ROLE-001"]
                return AgentResult(task_id=spec.task_id, agent=spec.agent,
                                   confidence=0.95)
            return Ghost.__call__(self, spec)

    assert "page_contracts" in DAG["workflows"].depends_on
    report = run(svc, Both(), plan=["page_contracts", "workflows"],
                 observer_agent=Observer())
    assert "page_contracts" in report.completed
    assert "workflows" in report.completed
    repair = next(i for i, t in enumerate(order) if "observer" in t)
    dependent = next(i for i, t in enumerate(order) if "workflows" in t)
    assert repair < dependent


def test_what_cannot_be_brought_round_is_flagged_not_patched(svc):
    author = Ghost(fix_after=99)
    report = run(svc, author, plan=["page_contracts"],
                 observer_agent=Observer(rounds=2))
    # The run is not failed: nothing was lost, a divergence was named (§76).
    assert report.ok
    assert "page_contracts" in report.completed
    assert report.repaired == []
    assert "Page↔Permission" in report.unrepaired["page_contracts"]
    assert svc.doc["pages"][0]["status"] == "OUT_OF_SYNC"
    assert "ROLE-999" in svc.doc["pages"][0]["syncNote"]
    # Original + exactly `rounds` repairs, no more.
    assert len(author.calls) == 3
    # The second brief carries what the first repair still missed — it is a
    # fresh judgement of the re-authored page, not the first brief replayed.
    assert "ROLE-999" in author.calls[2].feedback


def test_a_refused_repair_goes_round_told_why(svc):
    seen: list[str] = []

    def author(spec: TaskSpec) -> AgentResult:
        seen.append(spec.feedback)
        if "observer1" in spec.task_id:
            raise RuntimeError("model down")
        if "observer2" in spec.task_id:
            return page(spec, users=["ROLE-001"])
        return page(spec, users=["ROLE-999"])

    report = run(svc, author, plan=["page_contracts"],
                 observer_agent=Observer(rounds=2))
    assert report.repaired == ["page_contracts"]
    assert "model down" in seen[2]
    assert "ROLE-999" in seen[2]


def test_a_passing_node_is_recorded_and_left_alone(svc):
    calls: list[TaskSpec] = []

    def author(spec: TaskSpec) -> AgentResult:
        calls.append(spec)
        return page(spec, users=["ROLE-001"])

    report = run(svc, author, plan=["page_contracts"], observer_agent=Observer())
    assert len(calls) == 1
    assert report.observed["page_contracts"]["ok"] is True
    assert report.repaired == [] and report.unrepaired == {}


def test_without_an_observer_the_run_is_exactly_what_it_was(svc):
    author = Ghost(fix_after=99)
    report = run(svc, author, plan=["page_contracts"])
    assert len(author.calls) == 1
    assert report.observed == {} and report.repaired == []
    assert svc.doc["pages"][0]["status"] != "OUT_OF_SYNC"


def test_the_observer_judges_while_the_graph_carries_on(svc):
    """A node that finishes is judged on a worker while its neighbour's call
    is still out: the observation of `page_contracts` starts before
    `integrations` has even returned its first attempt."""
    import time

    marks: dict[str, float] = {}

    class Watching(Observer):
        def observe(self, key, **kw):
            marks[f"observe:{key}"] = time.monotonic()
            return super().observe(key, **kw)

    def author(spec: TaskSpec) -> AgentResult:
        if spec.node == "page_contracts":
            return page(spec, users=["ROLE-001"])
        time.sleep(0.3)  # integrations is slow; nothing waits for it
        marks["returned:integrations"] = time.monotonic()
        return AgentResult(task_id=spec.task_id, agent=spec.agent,
                           confidence=0.95)

    # Independent nodes: both depend only on nodes outside this plan.
    report = run(svc, author, plan=["page_contracts", "integrations"],
                 observer_agent=Watching())
    assert report.ok
    assert marks["observe:page_contracts"] < marks["returned:integrations"]


# --- the critic -------------------------------------------------------------

class Critic:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list[dict] = []
        self.enforces_schema = True

    def __call__(self, *, system: str, user: str, schema: dict) -> str:
        self.calls.append({"system": system, "user": json.loads(user), "schema": schema})
        if isinstance(self.reply, Exception):
            raise self.reply
        return json.dumps(self.reply)


def test_the_critics_finding_is_routed_like_any_other(svc):
    critic = Critic({"verdict": "fail", "findings": [{
        "section": "pages", "artifact": "", "requirement": "REQ-001",
        "detail": "no page lets an admin deactivate a tag",
    }]})
    author_calls: list[TaskSpec] = []

    def author(spec: TaskSpec) -> AgentResult:
        author_calls.append(spec)
        return page(spec, users=["ROLE-001"])

    # The critic passes the repair (second consultation) so the loop closes.
    def two_faced(*, system, user, schema):
        if len(critic.calls) >= 1:
            critic.calls.append({})
            return json.dumps({"verdict": "pass", "findings": []})
        return critic(system=system, user=user, schema=schema)

    report = run(svc, author, plan=["page_contracts"],
                 observer_agent=Observer(critic=two_faced))
    assert report.repaired == ["page_contracts"]
    assert CRITIC_EDGE in author_calls[1].feedback
    assert "REQ-001" in author_calls[1].feedback
    assert critic.calls[0]["schema"] is VERDICT_SCHEMA
    assert critic.calls[0]["user"]["agent"] == "page_design"


def test_the_critic_sees_the_slice_not_the_document(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p"},
               natural_key=page_key("/c"))
    svc.upsert("requirements", {"description": "Admins list candidates"},
               natural_key="REQ:list")
    ctx = observation_context(svc.doc, agent="page_design", user_request="an ATS")
    assert ctx["userRequest"] == "an ATS"
    assert set(ctx["output"]) == {"pages"}
    assert ctx["requirements"][0]["description"] == "Admins list candidates"
    assert "roles" not in ctx["output"]
    assert set(ctx["sectionsYouMayName"]) == set(owned_sections("page_design"))
    system, user = critic_prompt(ctx)
    assert "cannot edit" in system


def test_an_unavailable_critic_is_recorded_not_replaced(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-001"]}, natural_key=page_key("/c"))
    obs = Observer(critic=Critic(RuntimeError("no key"))).observe(
        "page_contracts", agent="page_design", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert obs.ok
    assert obs.critic.startswith("unavailable: RuntimeError")


def test_a_fail_with_no_findings_is_an_opinion(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-001"]}, natural_key=page_key("/c"))
    obs = Observer(critic=Critic({"verdict": "fail", "findings": []})).observe(
        "page_contracts", agent="page_design", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert obs.ok
    assert obs.critic == "pass"


def test_a_critic_naming_another_agents_section_is_deferred(svc):
    svc.upsert("pages", {"name": "C", "route": "/c", "purpose": "p",
                         "users": ["ROLE-001"]}, natural_key=page_key("/c"))
    critic = Critic({"verdict": "fail", "findings": [{
        "section": "roles", "artifact": "", "requirement": "",
        "detail": "there should be a recruiter role",
    }]})
    obs = Observer(critic=critic).observe(
        "page_contracts", agent="page_design", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert obs.ok
    assert [f.section for f in obs.deferred] == ["roles"]


def test_a_node_that_wrote_nothing_is_not_critiqued(svc):
    critic = Critic({"verdict": "pass", "findings": []})
    Observer(critic=critic).observe(
        "page_contracts", agent="page_design", subjects=[""], doc=svc.doc,
        pending=set(), planned={"pages"},
    )
    assert critic.calls == []


# --- the account ------------------------------------------------------------

def test_the_ledger_carries_the_observers_verdicts_and_repairs(svc):
    run(svc, Ghost(fix_after=99), plan=["page_contracts"],
        observer_agent=Observer(rounds=1))
    lines = read(svc.output_dir, runs(svc.output_dir)[0])
    events = [l["event"] for l in lines]
    assert events.count("observer:verdict") == 2  # original, then the repair
    assert "observer:repair" in events
    assert "observer:unrepaired" in events
    end = next(l for l in lines if l["event"] == "run:end")
    assert "page_contracts" in end["unrepaired"]


def test_the_brief_is_a_repair_task_addressed_to_the_author():
    obs = Observation(node="page_contracts", agent="page_design", subjects=[""])
    obs.findings[""] = [Finding("Page↔Permission", section="pages",
                                artifact_id="PAGE-001", detail="unknown role")]
    [task] = Observer().repairs(obs)
    assert task == RepairTask(node="page_contracts", agent="page_design",
                              subject="", feedback=obs.brief(""))
    assert "PAGE-001: unknown role" in task.feedback
    assert DAG[task.node].agent == task.agent


# --- which model judges -----------------------------------------------------

def test_the_critic_can_be_pointed_at_a_cheaper_model(monkeypatch):
    """Judging is reading, not authoring, so it is the one call a build can
    run on a cheaper model while measuring. The override wins over the
    router the agents use, and never changes what the agents run on."""
    from services.blueprint.executors import AnthropicModel, tiered_router

    monkeypatch.delenv(OBSERVER_MODEL_ENV, raising=False)
    router = tiered_router()
    same = anthropic_observer(router)
    assert same.critic is router.for_task("observer", "observer")

    explicit = anthropic_observer(router, model_id="claude-sonnet-5")
    assert isinstance(explicit.critic, AnthropicModel)
    assert explicit.critic.model == "claude-sonnet-5"
    assert explicit.critic.effort == "medium"
    assert router.default.model == "claude-sonnet-5"  # AGENT_MODEL, untouched

    monkeypatch.setenv(OBSERVER_MODEL_ENV, "claude-sonnet-5")
    from_env = anthropic_observer(router)
    assert from_env.critic.model == "claude-sonnet-5"


# --- a repair is the whole answer -------------------------------------------

def test_a_repair_that_renames_retires_what_it_replaced(svc):
    """Measured live: a repair that re-authored the modules under new names
    appended them, leaving three 'Notes' modules. What the subject authored
    before and did not re-propose is retired, so the document holds the
    repair's answer and nothing beside it."""
    calls: list[TaskSpec] = []

    def author(spec: TaskSpec) -> AgentResult:
        calls.append(spec)
        if "observer" in spec.task_id:
            # The repair re-authors the page under a new route and forgets
            # to carry the old one across.
            return page(spec, users=["ROLE-001"], route="/candidates-v2")
        return page(spec, users=["ROLE-999"])

    report = run(svc, author, plan=["page_contracts"], observer_agent=Observer())
    assert report.repaired == ["page_contracts"]
    by_route = {p["route"]: p for p in svc.doc["pages"]}
    assert by_route["/candidates"]["status"] == "DEPRECATED"
    assert "superseded by the observer's repair" in by_route["/candidates"]["syncNote"]
    assert by_route["/candidates-v2"]["status"] != "DEPRECATED"
    live = [p for p in svc.doc["pages"] if p["status"] != "DEPRECATED"]
    assert len(live) == 1
    assert "REPLACES what you wrote before" in calls[1].feedback


def test_a_repair_under_the_same_key_updates_in_place_and_retires_nothing(svc):
    author = Ghost()
    run(svc, author, plan=["page_contracts"], observer_agent=Observer())
    assert [p["status"] for p in svc.doc["pages"]] == ["PROPOSED"]
    assert [p["users"] for p in svc.doc["pages"]] == [["ROLE-001"]]


def test_retiring_a_keyed_row_removes_it_and_leaves_its_neighbours(svc):
    from services.blueprint.orchestrator import _retire

    svc.doc.setdefault("data", {})["constraints"] = [
        {"entity": "ENTITY-001", "kind": "index", "expression": "member_id"},
        {"entity": "ENTITY-001", "kind": "index", "expression": "memberId"},
    ]
    _retire(svc, {("keyed", "data.constraints",
                   ("ENTITY-001", "index", "member_id"))}, note="x")
    assert [c["expression"] for c in svc.doc["data"]["constraints"]] == ["memberId"]


def test_proposed_identities_cover_ids_and_keyed_rows():
    from services.blueprint.agent_contract import AgentApplication
    from services.blueprint.orchestrator import _proposed_identities

    result = AgentResult(task_id="t", agent="data_model", proposals=[
        ArtifactProposal(section="data.entities", natural_key="ENTITY:note",
                         body={"name": "Note"}),
        ArtifactProposal(section="data.constraints", natural_key="c",
                         body={"entity": "ENTITY-001", "kind": "index",
                               "expression": "memberId"}),
        ArtifactProposal(section="database", natural_key="database",
                         body={"engine": "postgres"}),
    ])
    application = AgentApplication(applied=True, result=result, artifacts=["ENTITY-001"])
    assert _proposed_identities(result, application) == {
        ("id", "data.entities", "ENTITY-001"),
        ("keyed", "data.constraints", ("ENTITY-001", "index", "memberId")),
    }


def test_the_critic_is_not_shown_retired_rows(svc):
    svc.upsert("pages", {"name": "Old", "route": "/old", "purpose": "p"},
               natural_key=page_key("/old"))
    svc.upsert("pages", {"name": "New", "route": "/new", "purpose": "p"},
               natural_key=page_key("/new"))
    old = next(p for p in svc.doc["pages"] if p["route"] == "/old")
    svc.set_status(old["id"], "DEPRECATED", note="retired")
    ctx = observation_context(svc.doc, agent="page_design")
    assert [p["route"] for p in ctx["output"]["pages"]] == ["/new"]


def test_flagging_never_revives_a_retired_artifact(svc):
    from services.blueprint.observer import flag_unrepaired

    svc.upsert("pages", {"name": "Old", "route": "/old", "purpose": "p"},
               natural_key=page_key("/old"))
    old = next(p for p in svc.doc["pages"] if p["route"] == "/old")
    svc.set_status(old["id"], "DEPRECATED", note="retired")
    obs = Observation(node="page_contracts", agent="page_design", subjects=[""])
    obs.findings[""] = [Finding(CRITIC_EDGE, section="pages",
                                artifact_id=old["id"], detail="leftover")]
    assert flag_unrepaired(svc, obs, "") == []
    assert svc.doc["pages"][0]["status"] == "DEPRECATED"
