"""A boundary that is documented but not enforced is not a boundary.

§30 says the Page Design Agent "cannot modify business rules". The old platform
said that too, in prose, and then shipped `submit_authority_guards` and
`workflow_mutation_guard` to clean up after agents that did. The difference
between a rule and a comment is whether something raises.

So the tests that matter here are the refusals. Each one corresponds to a class
of post-generation repair pass that becomes unnecessary once the write is
impossible rather than merely discouraged.
"""
import json
from pathlib import Path

import pytest

from services.blueprint.agent_contract import (
    AGENT_REGISTRY,
    ASK_USER,
    WRITABLE_SECTIONS,
    AgentResult,
    ArtifactProposal,
    CapabilityViolation,
    ChangeRequest,
    ContractViolation,
    UnknownAgent,
    apply_agent_result,
    capability_for,
)
from services.blueprint.ids import entity_key, page_key, prose_key
from services.blueprint.service import CONTRACT_PATH, BlueprintService


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="app_1", name="Recruitment", domain="ATS"
    )


def page_result(**kw) -> AgentResult:
    base = dict(
        task_id="TASK-332",
        agent="page_design",
        proposals=[
            ArtifactProposal(
                section="pages",
                natural_key=page_key("/candidates"),
                body={
                    "name": "Candidates",
                    "route": "/candidates",
                    "purpose": "Manage candidates progressing through recruitment.",
                },
            )
        ],
        requirements_satisfied=["REQ-031"],
        confidence=0.94,
    )
    base.update(kw)
    return AgentResult(**base)


# --- §27: the roster --------------------------------------------------------

#: §27 "Initial agents", in order.
SECTION_27_AGENTS = (
    "requirement", "domain_intelligence", "product_analysis",
    "solution_architecture", "page_design", "data_model", "api", "backend",
    "frontend", "workflow", "business_rules", "integration", "security",
    "testing", "accessibility", "build", "verification", "deployment",
)


def test_all_eighteen_section_27_agents_are_registered():
    assert len(SECTION_27_AGENTS) == 18
    for expected in SECTION_27_AGENTS:
        assert expected in AGENT_REGISTRY, expected


def test_figma_intelligence_is_registered_from_section_101():
    """§27's roster omits it, but §101 grants it tools by name — so it is a
    real agent the DAG can schedule, and it needs a declared boundary like any
    other. Registering it is deliberate, not an off-by-one."""
    extra = set(AGENT_REGISTRY) - set(SECTION_27_AGENTS)
    # Beyond §27's eighteen: figma_intelligence (§101), two the rebuild added —
    # a2ui_pages (§34) and memory (§20/§23, a derivation service that owns
    # sections rather than an agent that is ever prompted) — and smith itself.
    #
    # Smith is not a specialist; §6 makes it the architect the specialists
    # answer to. It is in the registry anyway so that its writes go through the
    # same check_capability as theirs. A coordinator exempt from the boundary
    # check is how §28's "uncontrolled swarm" gets in wearing a badge.
    assert extra == {"figma_intelligence", "a2ui_pages", "memory", "smith"}
    cap = capability_for("figma_intelligence")
    assert "mcp:figma" in cap.tools
    # §48 — Figma is design evidence, not confirmed requirements; it may not
    # author pages off its own bat.
    assert not cap.can_write("pages")


def test_unregistered_agents_are_refused():
    with pytest.raises(UnknownAgent):
        capability_for("rogue_agent")


def test_every_declared_write_target_is_a_real_blueprint_section():
    """A capability naming a section the schema doesn't have would grant a
    permission over nothing, and the mistake would never surface."""
    schema = json.loads(CONTRACT_PATH.read_text("utf-8"))
    for cap in AGENT_REGISTRY.values():
        for section in cap.writes:
            assert section in WRITABLE_SECTIONS, (cap.agent, section)
            top = section.split(".")[0]
            assert top in schema["properties"], (cap.agent, section)


# --- §30: the boundary, verbatim from the PRD's own example ----------------

def test_page_design_agent_can_compose_pages(svc):
    out = apply_agent_result(svc, page_result())
    assert out.applied
    assert out.artifacts == ["PAGE-001"]
    assert svc.find("PAGE-001")[1]["route"] == "/candidates"


def test_page_design_agent_cannot_modify_business_rules(svc):
    bad = page_result(
        proposals=[
            ArtifactProposal(
                section="businessRules",
                natural_key=prose_key("RULE", "Only managers may approve."),
                body={"name": "Approval", "statement": "Only managers may approve."},
            )
        ]
    )
    with pytest.raises(CapabilityViolation) as exc:
        apply_agent_result(svc, bad)
    assert "businessRules" in str(exc.value)
    assert "ChangeRequest" in str(exc.value)


def test_page_design_agent_cannot_modify_the_database_schema(svc):
    bad = page_result(
        proposals=[
            ArtifactProposal(
                section="data.entities",
                natural_key=entity_key("Candidate"),
                body={"name": "Candidate", "table": "candidates"},
            )
        ]
    )
    with pytest.raises(CapabilityViolation):
        apply_agent_result(svc, bad)


def test_page_design_agent_cannot_change_security_or_permissions(svc):
    for section in ("security", "permissions", "roles"):
        bad = page_result(
            proposals=[ArtifactProposal(section=section, natural_key=f"k:{section}", body={})]
        )
        with pytest.raises(CapabilityViolation):
            apply_agent_result(svc, bad)


def test_a_refused_write_leaves_the_blueprint_untouched(svc):
    bad = page_result(
        proposals=[
            ArtifactProposal(section="businessRules", natural_key="k", body={"name": "x"})
        ]
    )
    with pytest.raises(CapabilityViolation):
        apply_agent_result(svc, bad)
    assert svc.doc.get("businessRules", []) == []
    assert svc.doc["version"] == 1


def test_cross_domain_need_travels_as_a_change_request(svc):
    """§30 — the agent asks Smith rather than reaching across the boundary."""
    out = apply_agent_result(
        svc,
        page_result(
            change_requests=[
                ChangeRequest(
                    section="businessRules",
                    reason="the candidate list needs an 'approved' stage to filter on",
                    proposed={"statement": "A candidate reaching Offer must be approved."},
                )
            ]
        ),
    )
    assert out.applied, "its own domain still gets written"
    assert len(out.change_requests) == 1
    assert out.change_requests[0].section == "businessRules"
    # the requested change is NOT applied by this agent
    assert svc.doc.get("businessRules", []) == []


def test_the_agent_that_only_reports_cannot_author(svc):
    """Verification observes; §76 has it record divergence, not edit content."""
    assert capability_for("verification").writes == frozenset()
    with pytest.raises(CapabilityViolation):
        apply_agent_result(
            svc,
            AgentResult(
                task_id="T-1", agent="verification",
                proposals=[ArtifactProposal("pages", page_key("/x"), {"name": "X"})],
            ),
        )


# --- §29: the output contract ----------------------------------------------

def test_malformed_results_are_refused(svc):
    with pytest.raises(ContractViolation):
        apply_agent_result(svc, page_result(status="finished-ish"))
    with pytest.raises(ContractViolation):
        apply_agent_result(svc, page_result(confidence=1.4))
    with pytest.raises(ContractViolation):
        apply_agent_result(svc, page_result(task_id=""))


def test_proposals_require_a_natural_key(svc):
    bad = page_result(
        proposals=[ArtifactProposal(section="pages", natural_key="", body={"name": "X"})]
    )
    with pytest.raises(ContractViolation) as exc:
        apply_agent_result(svc, bad)
    assert "duplicate" in str(exc.value)


def test_blocked_and_failed_results_write_nothing(svc):
    for status in ("blocked", "failed"):
        out = apply_agent_result(svc, page_result(status=status))
        assert not out.applied
        assert svc.doc.get("pages", []) == []


# --- §17: confidence is enforced, not advisory ------------------------------

def test_low_confidence_is_refused_rather_than_applied(svc):
    out = apply_agent_result(svc, page_result(confidence=0.25))
    assert not out.applied
    assert out.needs_clarification
    assert f"{ASK_USER:.2f}" in out.reason
    assert svc.doc.get("pages", []) == []


def test_middle_band_proceeds_but_records_the_assumption(svc):
    out = apply_agent_result(
        svc,
        page_result(confidence=0.75, assumptions=["Assumed recruiters may bulk-reject."]),
    )
    assert out.applied
    assert out.recorded_assumptions == ["Assumed recruiters may bulk-reject."]


def test_high_confidence_records_no_assumption(svc):
    out = apply_agent_result(svc, page_result(confidence=0.97, assumptions=["ignored"]))
    assert out.applied
    assert out.recorded_assumptions == []


# --- §103: tasks must be retryable ------------------------------------------

def test_reapplying_the_same_result_is_idempotent(svc):
    first = apply_agent_result(svc, page_result())
    second = apply_agent_result(svc, page_result())
    assert first.artifacts == second.artifacts == ["PAGE-001"]
    assert len(svc.doc["pages"]) == 1


def test_retry_after_a_reload_does_not_renumber(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="n", domain="d")
    apply_agent_result(svc, page_result())
    reloaded = BlueprintService.load(output_dir=tmp_path)
    out = apply_agent_result(reloaded, page_result())
    assert out.artifacts == ["PAGE-001"]
    assert len(reloaded.doc["pages"]) == 1


# --- §91/§92: committing through the Blueprint ------------------------------

def test_commit_versions_and_attributes_the_change(svc):
    out = apply_agent_result(
        svc, page_result(tests_generated=["TEST-331"]),
        commit=True, user_request="Add a candidates list.",
    )
    assert out.applied
    assert svc.doc["version"] == 2
    record = svc.doc["changeHistory"][-1]
    assert record["userRequest"] == "Add a candidates list."
    assert record["affectedArtifacts"] == ["PAGE-001"]
    assert record["tests"] == ["TEST-331"]


def test_committed_result_still_satisfies_the_schema(svc):
    apply_agent_result(svc, page_result(), commit=True, user_request="x")
    svc.validate()


# --- in-batch cross references ---------------------------------------------

def test_a_batch_can_reference_artifacts_it_is_creating(svc):
    """An agent proposing entities and the relationships between them cannot
    cite an id that does not exist yet, and may not invent one. It cites the
    name or natural key; resolution happens here."""
    from services.blueprint.ids import entity_key

    result = AgentResult(
        task_id="T-1", agent="data_model", confidence=0.9,
        proposals=[
            ArtifactProposal("data.entities", entity_key("Candidate"),
                             {"name": "Candidate", "table": "candidates"}),
            ArtifactProposal("data.entities", entity_key("Application"),
                             {"name": "Application", "table": "applications"}),
            ArtifactProposal("data.relationships", "app->cand",
                             {"from": "Application", "to": "Candidate",
                              "kind": "one_to_many"}),
            ArtifactProposal("data.constraints", "cand unique email",
                             {"entity": "Candidate", "kind": "unique",
                              "expression": "email"}),
        ],
    )
    out = apply_agent_result(svc, result)
    assert out.applied

    rel = svc.doc["data"]["relationships"][0]
    assert rel["from"] == "ENTITY-002" and rel["to"] == "ENTITY-001"
    assert svc.doc["data"]["constraints"][0]["entity"] == "ENTITY-001"
    svc.validate()


def test_only_reference_typed_fields_are_rewritten(svc):
    """A description mentioning an entity by name must survive untouched."""
    from services.blueprint.ids import entity_key

    result = AgentResult(
        task_id="T-1", agent="data_model", confidence=0.9,
        proposals=[
            ArtifactProposal("data.entities", entity_key("Candidate"),
                             {"name": "Candidate", "table": "candidates",
                              "description": "A Candidate the agency represents."}),
        ],
    )
    apply_agent_result(svc, result)
    assert svc.find("ENTITY-001")[1]["description"] == "A Candidate the agency represents."


def test_an_unresolvable_reference_fails_loudly(svc):
    """Left as-is rather than silently dropped, so the contract rejects it."""
    from services.blueprint.service import BlueprintInvalid

    result = AgentResult(
        task_id="T-1", agent="data_model", confidence=0.9,
        proposals=[ArtifactProposal("data.relationships", "x",
                                    {"from": "Nonexistent", "to": "AlsoMissing",
                                     "kind": "one_to_many"})],
    )
    with pytest.raises(BlueprintInvalid) as exc:
        apply_agent_result(svc, result)
    assert "Nonexistent" in str(exc.value)


def test_reference_fields_are_derived_not_hardcoded():
    """Found by their §12 pattern behind zodToJsonSchema's $ref folding — a
    naive walk finds almost none of them."""
    from services.blueprint.service import reference_fields

    refs = reference_fields()
    assert "entity" in refs["apis"]
    assert refs["data.relationships"] == {"from", "to"}
    assert "users" in refs["pages"], "arrays of ids count too"
    assert "primaryEntity" in refs["pages"], "nested references count too"
    assert "page" in refs["navigation"], "navigation.tree[].page is four levels down"


def test_nested_references_resolve(svc):
    """A live page_contracts run wrote navigation.tree[].page as routes. The
    resolver only rewrote top-level fields, so eight nested references reached
    the validator untouched."""
    from services.blueprint.ids import page_key

    result = AgentResult(
        task_id="T-1", agent="page_design", confidence=0.9,
        proposals=[
            ArtifactProposal("pages", page_key("/candidates"),
                             {"name": "Candidates", "route": "/candidates",
                              "purpose": "List candidates."}),
            ArtifactProposal("pages", page_key("/overview"),
                             {"name": "Overview", "route": "/overview",
                              "purpose": "Dashboard."}),
            ArtifactProposal("navigation", "nav",
                             {"style": "sidebar", "tree": [
                                 {"label": "Home", "page": "/overview"},
                                 {"label": "Recruiting", "children": [
                                     {"label": "Candidates", "page": "/candidates"}]},
                             ]}),
        ],
    )
    out = apply_agent_result(svc, result)
    assert out.applied

    tree = svc.doc["navigation"]["tree"]
    assert tree[0]["page"] == "PAGE-002"
    assert tree[1]["children"][0]["page"] == "PAGE-001", "four levels down"
    svc.validate()


def test_nested_non_reference_text_is_left_alone(svc):
    from services.blueprint.ids import page_key

    result = AgentResult(
        task_id="T-1", agent="page_design", confidence=0.9,
        proposals=[ArtifactProposal("pages", page_key("/candidates"), {
            "name": "Candidates", "route": "/candidates",
            "purpose": "List candidates.",
            "primaryTasks": ["search /candidates", "open Candidates"],
        })],
    )
    apply_agent_result(svc, result)
    page = svc.find("PAGE-001")[1]
    assert page["primaryTasks"] == ["search /candidates", "open Candidates"]
    assert page["route"] == "/candidates", "route is not a reference"


# ---------------------------------------------------------------------------
# §34 — A2UI composes page trees, and they must render
# ---------------------------------------------------------------------------

def _template_result(root: dict, pattern: str = "entity_list") -> AgentResult:
    return AgentResult(
        task_id="t", agent="a2ui_pages", status="completed",
        proposals=[ArtifactProposal(
            section="pageLayouts", natural_key="PAGE-001",
            body={"page": "PAGE-001", "pattern": pattern, "root": root})],
    )


def test_template_naming_an_unregistered_component_is_refused():
    """The alternative is accepting it and repairing at render time, which is
    how the component library ended up with preprocessors for null columns."""
    from services.blueprint.agent_contract import (
        InvalidPatternTemplate, check_pattern_templates,
    )

    with pytest.raises(InvalidPatternTemplate, match="not a registered component"):
        check_pattern_templates(_template_result({"type": "MagicGrid", "children": []}))


def test_template_breaking_a_positional_child_contract_is_refused():
    from services.blueprint.agent_contract import (
        InvalidPatternTemplate, check_pattern_templates,
    )

    lopsided = {"type": "SplitView", "children": [{"type": "Card", "children": []}]}
    with pytest.raises(InvalidPatternTemplate, match="exactly 2 children"):
        check_pattern_templates(_template_result(lopsided, "master_detail"))


def test_a_valid_template_passes_the_gate():
    from services.blueprint.agent_contract import check_pattern_templates

    check_pattern_templates(_template_result({
        "type": "Stack", "children": [
            {"type": "Heading", "props": {"content": "$entity.plural"},
             "children": []}]}))


def test_the_gate_ignores_agents_that_do_not_write_templates():
    from services.blueprint.agent_contract import check_pattern_templates

    check_pattern_templates(AgentResult(
        task_id="t", agent="data_model", status="completed",
        proposals=[ArtifactProposal(section="data.entities", natural_key="x",
                                    body={"name": "X"})]))


def test_a2ui_is_scoped_but_can_see_the_intent_it_designs_for():
    """This asserted the opposite — that A2UI could not see `data` — which
    certified a real gap as correct: it was designing pages without ever
    seeing the requirements behind them or the entities its forms are made of.
    Scoped still, but scoped to the job rather than below it."""
    cap = AGENT_REGISTRY["a2ui_pages"]
    assert "*" not in cap.reads
    assert {"requirements", "pages", "data"} <= cap.reads


# ---------------------------------------------------------------------------
# A rejected proposal must leave the Blueprint exactly as it was
# ---------------------------------------------------------------------------


def _bad_widget() -> AgentResult:
    """A widget whose `unit` is what is counted, not a unit — the enum says no."""
    return page_result(proposals=[
        ArtifactProposal(
            section="widgets",
            natural_key=prose_key("open-jobs"),
            body={"name": "Open jobs", "title": "Open jobs", "unit": "jobs",
                  "dataSource": {"entity": "ENTITY-001"}},
        )
    ])


def test_a_rejected_proposal_leaves_no_trace(tmp_path):
    """Upsert mutates before validate raises. Without a rollback the next node
    validates against someone else's bad artifact and fails for it: a fresh run
    lost fourteen nodes when `security`, which writes no widgets, failed on the
    widget `page_contracts` had just been rejected for."""
    import copy as _copy

    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="A", domain="D")
    before = _copy.deepcopy(svc.doc)

    with pytest.raises(Exception):
        apply_agent_result(svc, _bad_widget())

    assert svc.doc.get("widgets") in (None, []), "the rejected widget survived"
    assert svc.doc == before, "the document changed despite the rejection"


def test_the_document_object_is_restored_in_place(tmp_path):
    """The orchestrator holds this dict; rebinding would strand it."""
    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="A", domain="D")
    held = svc.doc

    with pytest.raises(Exception):
        apply_agent_result(svc, _bad_widget())

    assert svc.doc is held, "callers were left holding the poisoned copy"
