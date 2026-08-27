"""The model is the one component that will do something unexpected.

Everything else in this package is deterministic and can be reasoned about.
The executor is where an LLM's output enters a system that then writes an
application's definition — so the tests that matter are the ones proving the
enforcement below it holds when the model misbehaves: proposes outside its
boundary, invents IDs, reports false confidence, returns malformed JSON.

None of these tests make a network call. The model callable is injected, which
is the point: orchestration and enforcement stay testable no matter what the
model does.
"""
import json

import pytest

from services.blueprint.agent_contract import (
    CapabilityViolation,
    apply_agent_result,
)
from services.blueprint.executors import (
    DEFAULT_MODEL,
    NODE_TASKS,
    PROPOSAL_SCHEMA,
    MalformedEnvelope,
    build_prompt,
    context_for,
    make_executor,
    parse_envelope,
)
from services.blueprint.orchestrator import DAG, TaskSpec, run
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    s = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Candidate",
                                   "table": "candidates", "status": "VERIFIED"}]}
    s.doc["designSystem"] = {"visualPersonality": "calm"}
    s.doc["workflows"] = []
    return s


def envelope(**over) -> str:
    base = {
        "proposals": [{
            "section": "pages",
            "natural_key": "PAGE:/candidates",
            "body": json.dumps({"name": "Candidates", "route": "/candidates",
                                "purpose": "Manage candidates."}),
        }],
        "confidence": 0.9,
        "assumptions": [],
        "issues": [],
        "change_requests": [],
    }
    base.update(over)
    return json.dumps(base)


def fake_model(reply: str):
    def _model(*, system: str, user: str, schema: dict) -> str:
        return reply
    return _model


# --- the output contract (§29) ---------------------------------------------

def test_proposal_schema_is_structured_outputs_safe():
    """Structured outputs reject `pattern` and numeric constraints and require
    additionalProperties:false everywhere. The Blueprint contract violates all
    three — this envelope must not."""
    banned = {"pattern", "minimum", "maximum", "minLength", "maxLength",
              "multipleOf", "minItems", "maxItems", "exclusiveMinimum"}
    objects = []

    def walk(node):
        if isinstance(node, dict):
            assert not (banned & set(node)), f"unsupported keyword in {node}"
            if node.get("type") == "object":
                objects.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(PROPOSAL_SCHEMA)
    assert objects, "schema declares no objects"
    for o in objects:
        assert o.get("additionalProperties") is False


def test_bodies_travel_as_strings_because_free_form_objects_cannot_be_constrained():
    body = PROPOSAL_SCHEMA["properties"]["proposals"]["items"]["properties"]["body"]
    assert body["type"] == "string"


def test_uses_the_current_default_model():
    assert DEFAULT_MODEL == "claude-opus-5"


# --- §101: capability-scoped context ---------------------------------------

def test_an_agent_sees_only_what_it_may_read(svc):
    ctx = context_for(svc.doc, "data_model")
    assert "data" in ctx, "it must see what it writes"
    assert "application" in ctx


def test_context_always_carries_application_identity(svc):
    for agent in ("page_design", "data_model", "testing"):
        assert "application" in context_for(svc.doc, agent)


def test_context_is_a_copy_not_the_live_document(svc):
    ctx = context_for(svc.doc, "data_model")
    ctx["application"] = {"tampered": True}
    assert svc.doc["application"]["name"] == "Recruitment"


# --- prompts ---------------------------------------------------------------

def test_prompt_states_the_agents_boundary(svc):
    system, _ = build_prompt(svc.doc, "page_contracts")
    assert "pages" in system
    assert "change_request" in system
    assert "businessRules" not in system.split("You may write ONLY")[1].split("If the")[0]


def test_prompt_forbids_inventing_ids(svc):
    system, _ = build_prompt(svc.doc, "data_model")
    assert "Do not invent IDs" in system


def test_prompt_explains_why_natural_key_matters(svc):
    system, _ = build_prompt(svc.doc, "apis")
    assert "natural_key" in system and "duplicated" in system


def test_every_dag_node_can_build_a_prompt(svc):
    for node in DAG:
        system, user = build_prompt(svc.doc, node)
        assert system and user


def test_named_tasks_cover_the_artifact_producing_nodes():
    for node in NODE_TASKS:
        assert node in DAG, node


# --- parsing ---------------------------------------------------------------

def test_parses_a_well_formed_envelope():
    result = parse_envelope(envelope(), task_id="T-1", agent="page_design")
    assert result.agent == "page_design"
    assert result.confidence == 0.9
    assert result.proposals[0].body["route"] == "/candidates"


def test_model_supplied_ids_are_stripped():
    """§12/§116 — identity is the deterministic layer's to assign. A model that
    invents ENTITY-004 must not be able to claim an ID."""
    raw = envelope(proposals=[{
        "section": "pages", "natural_key": "PAGE:/x",
        "body": json.dumps({"id": "PAGE-999", "name": "X", "route": "/x",
                            "purpose": "y"}),
    }])
    result = parse_envelope(raw, task_id="T-1", agent="page_design")
    assert "id" not in result.proposals[0].body


def test_malformed_json_is_refused():
    with pytest.raises(MalformedEnvelope):
        parse_envelope("not json", task_id="T-1", agent="page_design")


def test_a_body_that_is_not_an_object_is_refused():
    raw = envelope(proposals=[{"section": "pages", "natural_key": "k",
                               "body": json.dumps(["a", "list"])}])
    with pytest.raises(MalformedEnvelope):
        parse_envelope(raw, task_id="T-1", agent="page_design")


def test_change_requests_survive_parsing():
    raw = envelope(change_requests=[{"section": "businessRules",
                                     "reason": "needs an approval rule"}])
    result = parse_envelope(raw, task_id="T-1", agent="page_design")
    assert result.change_requests[0].section == "businessRules"


# --- the executor end to end (no network) -----------------------------------

def test_executor_produces_a_result_the_orchestrator_can_run(svc):
    ex = make_executor(svc, fake_model(envelope()))
    report = run(svc, ex, plan=["page_contracts"])
    assert report.ok
    assert report.artifacts == ["PAGE-001"]
    assert svc.find("PAGE-001")[1]["route"] == "/candidates"


def test_malformed_output_is_retried_with_the_error(svc):
    seen: list[str] = []
    replies = iter(["{ broken", envelope()])

    def flaky(*, system, user, schema):
        seen.append(user)
        return next(replies)

    ex = make_executor(svc, flaky, repair_attempts=1)
    result = ex(TaskSpec(task_id="T-1", node="page_contracts", agent="page_design"))
    assert result.proposals
    assert "was rejected" in seen[1], "the repair prompt must carry the reason"


def test_persistently_malformed_output_fails_loudly(svc):
    ex = make_executor(svc, fake_model("{ broken"), repair_attempts=1)
    with pytest.raises(MalformedEnvelope):
        ex(TaskSpec(task_id="T-1", node="page_contracts", agent="page_design"))


# --- the enforcement below it still holds ----------------------------------

def test_a_model_writing_outside_its_boundary_is_refused(svc):
    """The whole point: the prompt asks for compliance, the contract enforces it."""
    rogue = envelope(proposals=[{
        "section": "businessRules", "natural_key": "RULE:x",
        "body": json.dumps({"name": "Rule", "statement": "Managers approve."}),
    }])
    ex = make_executor(svc, fake_model(rogue))
    with pytest.raises(CapabilityViolation):
        run(svc, ex, plan=["page_contracts"])
    assert svc.doc.get("businessRules", []) == []


def test_a_model_reporting_low_confidence_writes_nothing(svc):
    ex = make_executor(svc, fake_model(envelope(confidence=0.1)))
    report = run(svc, ex, plan=["page_contracts"])
    assert "page_contracts" in report.blocked
    assert svc.doc.get("pages", []) == []


def test_a_proposal_the_contract_rejects_does_not_reach_the_blueprint(svc):
    from services.blueprint.service import BlueprintInvalid

    bad = envelope(proposals=[{
        "section": "pages", "natural_key": "PAGE:/x",
        "body": json.dumps({"name": "X"}),  # no route, no purpose
    }])
    ex = make_executor(svc, fake_model(bad))
    with pytest.raises(BlueprintInvalid):
        apply_agent_result(svc, ex(TaskSpec("T-1", "page_contracts", "page_design")))


def test_rerunning_the_same_result_does_not_duplicate(svc):
    ex = make_executor(svc, fake_model(envelope()))
    run(svc, ex, plan=["page_contracts"])
    run(svc, ex, plan=["page_contracts"])
    assert len(svc.doc["pages"]) == 1


def test_narrowing_reads_actually_restricts_context(svc):
    """The registry grants every agent `reads = {"*"}` today, so scoping is a
    no-op in practice. This proves the mechanism is real and will bite the
    moment a capability declares a narrower set — otherwise the §101 claim
    would be decoration."""
    from dataclasses import replace

    from services.blueprint import agent_contract

    cap = agent_contract.AGENT_REGISTRY["data_model"]
    narrowed = replace(cap, reads=frozenset({"data"}))
    original = agent_contract.AGENT_REGISTRY["data_model"]
    agent_contract.AGENT_REGISTRY["data_model"] = narrowed
    try:
        ctx = context_for(svc.doc, "data_model")
        assert "data" in ctx, "must still see what it writes"
        assert "application" in ctx, "identity is always carried"
        assert "designSystem" not in ctx, "a narrowed read must exclude"
    finally:
        agent_contract.AGENT_REGISTRY["data_model"] = original


def test_narrowed_agents_actually_get_a_narrowed_context(svc):
    """§101 context scoping is live, not decorative.

    This used to assert the opposite — that every agent read ``*`` — which made
    the scoping machinery a no-op the test then certified as correct. The first
    agent to declare narrow reads is ``a2ui_patterns``: it authors structure
    from page contracts and the design language, so handing it entities,
    endpoints and workflows costs tokens for context it cannot use.
    """
    from services.blueprint.agent_contract import AGENT_REGISTRY

    narrowed = {name: cap for name, cap in AGENT_REGISTRY.items()
                if "*" not in cap.reads}
    assert narrowed, "at least one agent should declare what it needs"

    for name, cap in narrowed.items():
        ctx = context_for(svc.doc, name)
        assert "application" in ctx, f"{name}: identity is always carried"
        for section in ctx:
            # `context_for` also hands back whatever the agent writes — it
            # cannot update a section it cannot see.
            declared = {s.split(".")[0] for s in cap.reads | cap.writes}
            assert (section in declared
                    or section in {"application", "product", "schemaVersion",
                                   "version", "state"}), (
                f"{name} was handed {section!r}, which it never declared")


# --- mixed providers: Kimi for one agent, Claude for another ----------------

def kimi() -> "OpenAICompatibleModel":
    from services.blueprint.executors import OpenAICompatibleModel
    return OpenAICompatibleModel(
        model="kimi-k2-0711-preview",
        base_url="https://api.moonshot.ai/v1",
        api_key_env="MOONSHOT_API_KEY",
    )


def test_router_sends_each_node_to_its_assigned_model():
    from services.blueprint.executors import AnthropicModel, ModelRouter

    router = ModelRouter(default=AnthropicModel(), by_node={"testing": kimi()})
    assert router.for_task("testing", "testing").model == "kimi-k2-0711-preview"
    assert router.for_task("data_model", "data_model").model == "claude-opus-5"


def test_router_can_route_by_agent_as_well_as_node():
    from services.blueprint.executors import AnthropicModel, ModelRouter

    router = ModelRouter(default=AnthropicModel(), by_agent={"business_rules": kimi()})
    assert router.for_task("business_rules", "business_rules").model.startswith("kimi")


def test_node_assignment_beats_agent_assignment():
    from services.blueprint.executors import AnthropicModel, ModelRouter

    k = kimi()
    router = ModelRouter(default=AnthropicModel(), by_node={"testing": k},
                         by_agent={"testing": AnthropicModel()})
    assert router.for_task("testing", "testing") is k


def test_assignments_report_what_runs_where():
    from services.blueprint.executors import AnthropicModel, ModelRouter

    router = ModelRouter(default=AnthropicModel(), by_node={"testing": kimi()})
    a = router.assignments()
    assert a["testing"] == "kimi-k2-0711-preview"
    assert a["data_model"] == "claude-opus-5"
    assert set(a) == set(DAG), "every node must have a declared model"


def test_a_transport_that_cannot_enforce_the_schema_gets_it_in_the_prompt(svc):
    """Kimi's JSON mode guarantees valid JSON, not our envelope. The constraint
    has to be stated somewhere, so it moves into the system prompt."""
    enforced, _ = build_prompt(svc.doc, "testing", inline_schema=False)
    stated, _ = build_prompt(svc.doc, "testing", inline_schema=True)
    marker = "Your reply must be a single JSON object"
    assert marker in stated and "natural_key" in stated
    assert marker not in enforced, "Claude's transport enforces it; don't pay the tokens"
    assert len(stated) > len(enforced)


def test_the_executor_picks_the_prompt_form_from_the_clients_capability(svc):
    from services.blueprint.executors import ModelRouter

    seen: dict[str, str] = {}

    def spy(name, enforces):
        class Spy:
            enforces_schema = enforces
            model = name
            def __call__(self, *, system, user, schema):
                seen[name] = system
                return envelope()
        return Spy()

    router = ModelRouter(
        default=spy("claude", True), by_node={"testing": spy("kimi", False)}
    )
    ex = make_executor(svc, router)
    ex(TaskSpec("T-1", "page_contracts", "page_design"))
    ex(TaskSpec("T-2", "testing", "testing"))

    marker = "Your reply must be a single JSON object"
    assert marker not in seen["claude"], "schema-enforcing transport: no inline envelope"
    assert marker in seen["kimi"], "json-mode transport: envelope must be inlined"


def test_enforcement_is_identical_regardless_of_provider(svc):
    """The whole point of the seam: a cheaper model gets no extra latitude."""
    from services.blueprint.executors import ModelRouter

    class Rogue:
        enforces_schema = False
        model = "kimi-k2-0711-preview"
        def __call__(self, *, system, user, schema):
            return envelope(proposals=[{
                "section": "businessRules", "natural_key": "RULE:x",
                "body": json.dumps({"name": "R", "statement": "Managers approve."}),
            }])

    ex = make_executor(svc, ModelRouter(default=Rogue()))
    with pytest.raises(CapabilityViolation):
        ex_result = ex(TaskSpec("T-1", "page_contracts", "page_design"))
        apply_agent_result(svc, ex_result)


def test_a_single_client_still_works_without_a_router(svc):
    ex = make_executor(svc, fake_model(envelope()))
    assert ex(TaskSpec("T-1", "page_contracts", "page_design")).proposals


# --- provider registry ------------------------------------------------------

def test_every_provider_entry_is_usable():
    from services.blueprint.executors import PROVIDERS, provider

    for name, spec in PROVIDERS.items():
        assert spec.base_url.startswith("http"), name
        client = provider(name, "some-model")
        assert client.base_url == spec.base_url
        assert client.enforces_schema is spec.enforces_schema


def test_self_hosted_providers_need_no_api_key():
    from services.blueprint.executors import PROVIDERS

    for name in ("ollama", "vllm", "lmstudio"):
        assert PROVIDERS[name].api_key_env is None, name


def test_only_verified_providers_claim_to_enforce_schema():
    """enforces_schema=True skips prompt-inlining, so a wrong True silently
    removes the constraint. Default must be conservative."""
    from services.blueprint.executors import PROVIDERS

    claiming = {n for n, s in PROVIDERS.items() if s.enforces_schema}
    assert claiming == {"openai"}, f"unverified providers claiming enforcement: {claiming}"


def test_unknown_provider_is_refused():
    from services.blueprint.executors import UnknownProvider, provider

    with pytest.raises(UnknownProvider) as exc:
        provider("not-a-provider", "m")
    assert "moonshot" in str(exc.value), "the error should list what is available"


def test_overrides_win_over_registry_defaults():
    from services.blueprint.executors import provider

    c = provider("moonshot", "kimi-k2-0711-preview", enforces_schema=True,
                 max_tokens=4096)
    assert c.enforces_schema is True and c.max_tokens == 4096


# --- native Gemini ----------------------------------------------------------

def test_gemini_schema_strips_only_what_gemini_rejects():
    """Gemini spells it `additional_properties`, so the JSON Schema key is
    unrecognised — but everything else must survive or the schema stops
    constraining anything."""
    from services.blueprint.executors import PROPOSAL_SCHEMA, _gemini_schema

    out = _gemini_schema(PROPOSAL_SCHEMA)
    dumped = json.dumps(out)
    assert "additionalProperties" not in dumped
    for kept in ("proposals", "natural_key", "confidence", "change_requests",
                 "description", "required", "type"):
        assert kept in dumped, kept


def test_gemini_enforces_schema_so_it_gets_no_inlined_copy():
    from services.blueprint.executors import GeminiModel

    assert GeminiModel().enforces_schema is True


def test_gemini_can_target_vertex():
    from services.blueprint.executors import GeminiModel

    g = GeminiModel(vertexai=True, project="p", location="us-central1")
    assert g.vertexai and g.project == "p"


# --- three providers, one pipeline -----------------------------------------

def test_a_run_can_mix_anthropic_gemini_and_an_openai_compatible_provider(svc):
    from services.blueprint.executors import (
        AnthropicModel, GeminiModel, ModelRouter, provider,
    )

    router = ModelRouter(
        default=AnthropicModel(),
        by_node={
            "testing": provider("moonshot", "kimi-k2-0711-preview"),
            "business_rules": GeminiModel(),
        },
    )
    a = router.assignments()
    assert a["data_model"] == "claude-opus-5"
    assert a["testing"] == "kimi-k2-0711-preview"
    assert a["business_rules"] == "gemini-2.5-pro"
    assert len(set(a.values())) >= 3


def test_prompt_form_follows_each_providers_capability(svc):
    """Claude and Gemini enforce the schema; Kimi does not — so only Kimi's
    prompt should carry the inlined copy."""
    from services.blueprint.executors import (
        AnthropicModel, GeminiModel, provider,
    )

    for client, should_inline in (
        (AnthropicModel(), False),
        (GeminiModel(), False),
        (provider("moonshot", "kimi-k2-0711-preview"), True),
    ):
        system, _ = build_prompt(
            svc.doc, "testing",
            inline_schema=not client.enforces_schema,
        )
        marker = "Your reply must be a single JSON object"
        assert (marker in system) is should_inline, client


# --- writable shapes: found by the first live run ---------------------------

def test_agents_are_told_the_shape_of_what_they_may_write(svc):
    """The first live run guessed `engine: "postgresql"` where the contract
    says the literal "postgres", and the Blueprint refused it. An agent that
    knows which sections it owns but not what an artifact looks like will
    guess — so hand it the contract slice."""
    from services.blueprint.executors import writable_shapes

    shapes = writable_shapes("data_model")
    assert set(shapes) == {"data.entities", "data.relationships",
                           "data.constraints", "database"}
    assert shapes["database"]["properties"]["engine"]["const"] == "postgres"

    system, _ = build_prompt(svc.doc, "data_model")
    assert "Artifacts you write must match these shapes" in system
    assert '"postgres"' in system


def test_shapes_describe_one_artifact_not_the_array_wrapper():
    from services.blueprint.executors import writable_shapes

    shapes = writable_shapes("page_design")
    assert shapes["pages"]["type"] == "object", "must unwrap `items`"
    assert "route" in shapes["pages"]["properties"]


def test_an_agent_with_no_writable_sections_gets_no_shape_block(svc):
    from services.blueprint.executors import writable_shapes

    assert writable_shapes("verification") == {}
    system, _ = build_prompt(svc.doc, "verification")
    assert "Artifacts you write must match" not in system


def test_singleton_sections_are_writable(svc):
    """`database`, `security`, `designSystem` and friends are objects, not
    ID-bearing artifact lists — nine of nineteen agents write one, and upsert
    raised KeyError on all of them until the live run surfaced it."""
    from services.blueprint.service import SINGLETON_SECTIONS

    result = svc.upsert("database", {"engine": "postgres", "provider": "neon"},
                        natural_key="primary")
    assert result["provider"] == "neon"
    assert "id" not in result and "status" not in result
    svc.validate()

    svc.upsert("database", {"seeded": True}, natural_key="primary")
    assert svc.doc["database"] == {"engine": "postgres", "provider": "neon",
                                   "seeded": True}, "merge, not replace"
    assert "database" in SINGLETON_SECTIONS


def test_codemap_is_keyed_by_artifact_not_by_id(svc):
    svc.upsert("codeMap", {"artifact": "PAGE-001", "frontend": ["p.tsx"]},
               natural_key="PAGE-001")
    svc.upsert("codeMap", {"artifact": "PAGE-001", "api": ["r.ts"]},
               natural_key="PAGE-001")
    assert len(svc.doc["codeMap"]) == 1
    assert svc.doc["codeMap"][0]["frontend"] == ["p.tsx"]


def test_every_writable_section_has_a_working_write_path():
    """The gap the live run found, closed as an invariant: if a capability can
    write a section, upsert must know how."""
    from services.blueprint.agent_contract import WRITABLE_SECTIONS
    from services.blueprint.service import (
        ARTIFACT_SECTIONS, KEYED_LIST_SECTIONS, SINGLETON_SECTIONS,
    )

    handled = set(ARTIFACT_SECTIONS) | set(SINGLETON_SECTIONS) | set(KEYED_LIST_SECTIONS)
    handled.add("data.entities")
    assert WRITABLE_SECTIONS <= handled, f"no write path for: {WRITABLE_SECTIONS - handled}"


def test_shapes_do_not_ask_for_an_id_the_prompt_forbids():
    """The first live run reported this contradiction itself: the shape said
    `id` was required, the instructions said omit it. Identity is assigned."""
    from services.blueprint.executors import writable_shapes

    for agent in ("data_model", "page_design", "api", "workflow"):
        for section, shape in writable_shapes(agent).items():
            if "properties" in shape:
                assert "id" not in shape["properties"], (agent, section)
                assert "id" not in shape.get("required", []), (agent, section)


def test_applying_a_singleton_section_does_not_expect_an_id(svc):
    """`apply_agent_result` collected `art["id"]` unconditionally — which
    KeyErrors on every singleton section."""
    from services.blueprint.agent_contract import (
        AgentResult, ArtifactProposal, apply_agent_result,
    )

    result = AgentResult(
        task_id="T-1", agent="data_model", confidence=0.9,
        proposals=[ArtifactProposal("database",
                                    "primary",
                                    {"engine": "postgres", "provider": "neon"})],
    )
    out = apply_agent_result(svc, result)
    assert out.applied
    assert out.artifacts == [], "a singleton contributes no artifact id"
    assert svc.doc["database"]["provider"] == "neon"


# --- usage and cost ---------------------------------------------------------

def test_current_opus_is_not_priced_as_claude_3_opus():
    """The substring table charged every Opus $15/$75 — Claude 3 Opus pricing.
    Current Opus is $5/$25, so every Opus call was overstated threefold."""
    from services.build_usage import _price_for

    for m in ("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"):
        assert _price_for(m) == (5.0, 25.0), m
    assert _price_for("claude-3-opus-20240229") == (15.0, 75.0), "legacy row preserved"


def test_non_anthropic_models_are_flagged_unpriced():
    """estimate_cost_usd still returns a number for them — a placeholder. The
    flag is what stops a fabricated figure being read as a measurement."""
    from services.build_usage import is_priced

    assert is_priced("claude-opus-5")
    assert not is_priced("kimi-k2-0711-preview")
    assert not is_priced("gemini-2.5-pro")


def test_cost_accounts_for_cache_tokens():
    from services.build_usage import estimate_cost_usd

    plain = estimate_cost_usd("claude-opus-5", {"input_tokens": 10000})
    cached = estimate_cost_usd("claude-opus-5", {"cache_read_input_tokens": 10000})
    assert cached == pytest.approx(plain * 0.1, rel=1e-3), "reads bill at ~0.1x"


def test_run_usage_separates_priced_from_unpriced():
    from services.blueprint.executors import RunUsage, Usage

    r = RunUsage()
    r.record(node="data_model", agent="data_model",
             usage=Usage("claude-opus-5", 20000, 4000), elapsed_s=88.3)
    r.record(node="testing", agent="testing",
             usage=Usage("kimi-k2-0711-preview", 9000, 1200), elapsed_s=12.4)

    assert r.total_tokens == 34200, "tokens are counted for every model"
    assert r.unpriced == ["kimi-k2-0711-preview"]
    assert r.total_cost_usd == pytest.approx(0.2, rel=1e-2), "priced spend only"
    assert "excludes unpriced" in r.render()


def test_executor_records_usage_when_the_client_reports_it(svc):
    from services.blueprint.executors import ModelReply, RunUsage, Usage

    def reporting(*, system, user, schema):
        return ModelReply(text=envelope(),
                          usage=Usage("claude-opus-5", 1200, 340, 100, 50))

    usage = RunUsage()
    ex = make_executor(svc, reporting, usage=usage)
    ex(TaskSpec("T-1", "page_contracts", "page_design"))

    assert len(usage.entries) == 1
    e = usage.entries[0]
    assert e["node"] == "page_contracts" and e["model"] == "claude-opus-5"
    assert e["input_tokens"] == 1200 and e["cache_read_tokens"] == 100
    assert e["cost_usd"] > 0 and e["elapsed_s"] >= 0


def test_a_client_returning_a_bare_string_still_works(svc):
    """Test fakes stay one-liners; only real clients report usage."""
    usage_ledger = __import__(
        "services.blueprint.executors", fromlist=["RunUsage"]
    ).RunUsage()
    ex = make_executor(svc, fake_model(envelope()), usage=usage_ledger)
    assert ex(TaskSpec("T-1", "page_contracts", "page_design")).proposals
    assert usage_ledger.entries == [], "nothing to record without a reported usage"


def test_a_failing_ledger_write_never_breaks_a_run(svc, monkeypatch):
    from services.blueprint.executors import ModelReply, RunUsage, Usage

    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("services.build_usage.record_usage", boom)
    usage = RunUsage()
    usage.record(node="n", agent="a", usage=Usage("claude-opus-5", 10, 5), elapsed_s=1.0)
    assert len(usage.entries) == 1, "the run-scoped entry survives a ledger failure"


def test_every_real_client_reports_usage():
    """A silent no-op edit left AnthropicModel returning bare text while the
    other two reported usage — so the first measured run cost $0.00. Assert
    the contract instead of trusting the edit."""
    import inspect

    from services.blueprint.executors import (
        AnthropicModel, GeminiModel, OpenAICompatibleModel,
    )

    for client in (AnthropicModel, OpenAICompatibleModel, GeminiModel):
        src = inspect.getsource(client.__call__)
        assert "ModelReply(" in src, f"{client.__name__} does not report usage"
        assert "Usage(" in src, f"{client.__name__} reports no token counts"


def test_relationships_and_constraints_are_now_writable(svc):
    """They were reachable by no agent, so the live run produced 0 of them
    three times running and the FK integrity checks had nothing to check."""
    from services.blueprint.agent_contract import capability_for

    cap = capability_for("data_model")
    assert cap.can_write("data.relationships")
    assert cap.can_write("data.constraints")

    svc.upsert("data.relationships",
               {"from": "ENTITY-001", "to": "ENTITY-002", "kind": "one_to_many",
                "fromField": "candidateId"},
               natural_key="ENTITY-001->ENTITY-002")
    assert len(svc.doc["data"]["relationships"]) == 1
    svc.validate()


def test_a_relationship_is_its_own_identity_not_a_duplicate(svc):
    """Keyed on (from, to, kind) — re-proposing the same edge updates it."""
    for field_name in ("candidateId", "candidate_id"):
        svc.upsert("data.relationships",
                   {"from": "ENTITY-001", "to": "ENTITY-002",
                    "kind": "one_to_many", "fromField": field_name},
                   natural_key="whatever")
    rels = svc.doc["data"]["relationships"]
    assert len(rels) == 1, "same edge proposed twice must not duplicate"
    assert rels[0]["fromField"] == "candidate_id"


def test_a_different_kind_is_a_different_relationship(svc):
    for kind in ("one_to_many", "many_to_many"):
        svc.upsert("data.relationships",
                   {"from": "ENTITY-001", "to": "ENTITY-002", "kind": kind},
                   natural_key="k")
    assert len(svc.doc["data"]["relationships"]) == 2


# --- effort-aware token headroom (found by the effort sweep) ----------------

def test_high_effort_gets_more_token_headroom():
    """Thinking counts against max_tokens. A sweep at xhigh with the 16k
    default came back with exactly 16,000 output tokens and a Blueprint that
    failed validation — the ceiling, not a coincidence."""
    from services.blueprint.executors import DEFAULT_MAX_TOKENS, AnthropicModel

    for effort in ("low", "medium", "high"):
        assert AnthropicModel(effort=effort).max_tokens == DEFAULT_MAX_TOKENS
    for effort in ("xhigh", "max"):
        assert AnthropicModel(effort=effort).max_tokens == 64000
    assert DEFAULT_MAX_TOKENS >= 32000, (
        "16k truncated page_contracts and came within 500 tokens of truncating "
        "data_model at high effort")


def test_an_explicit_max_tokens_is_never_overridden():
    from services.blueprint.executors import AnthropicModel

    assert AnthropicModel(effort="xhigh", max_tokens=8000).max_tokens == 8000


def test_large_max_tokens_uses_streaming():
    """The SDK refuses a non-streaming request it estimates could run past ~10
    minutes, which any large max_tokens does — it raises ValueError before the
    call is made."""
    import inspect

    from services.blueprint.executors import AnthropicModel

    src = inspect.getsource(AnthropicModel.__call__)
    assert "messages.stream" in src and "get_final_message" in src


def test_unfillable_fields_are_withheld_from_agents():
    """`decisions` is a DEC- reference list and *no agent writes the decisions
    section*, so those ids never exist. Every agent shown the field wrote its
    rationale into it as prose instead — 99 validation errors on one live
    `apis` node, and the same failure on an earlier xhigh run."""
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.executors import WITHHELD_FIELDS, writable_shapes

    # `memory` owns the section now, but it is a derivation service — nothing
    # ever prompts it — so the field is still unfillable by anything that gets
    # a prompt. If a *prompted* agent gains it, stop withholding.
    prompted = [a for a, c in AGENT_REGISTRY.items()
                if "decisions" in c.writes and a != "memory"]
    assert not prompted, (
        "if a prompted agent can now author decisions, stop withholding the field")

    for agent in ("api", "data_model", "page_design", "workflow", "testing"):
        for section, shape in writable_shapes(agent).items():
            if "properties" not in shape:
                continue
            for field in WITHHELD_FIELDS:
                assert field not in shape["properties"], (agent, section, field)


def test_requirements_stay_offered_because_agents_can_fill_them(svc):
    """REQ ids do exist in the Blueprint an agent is handed — withholding that
    field would break traceability (§18)."""
    from services.blueprint.executors import writable_shapes

    assert "requirements" in writable_shapes("api")["apis"]["properties"]


def test_the_prompt_redirects_rationale_to_assumptions(svc):
    system, _ = build_prompt(svc.doc, "apis")
    assert "reasoning in `assumptions`" in system


# ---------------------------------------------------------------------------
# §101 context scoping
# ---------------------------------------------------------------------------

#: Sections a node's dependency produces that the consuming agent deliberately
#: does NOT read, and why. A dependency is often an ordering constraint rather
#: than a data one, so an unexplained gap is a bug and an explained one is a
#: design decision.
_DELIBERATE_BLIND_SPOTS: dict[tuple[str, str], str] = {
    ("patterns", "components"):
        "A2UI composes from the 165-component catalog, not from Blueprint "
        "components; it depends on page_designs for ordering, not for data.",
}


def test_every_agent_can_see_what_its_upstream_produces():
    """A scoped agent that cannot see its own inputs is worse than an unscoped
    one: it does not fail, it invents.

    Checked against the capability rather than against a document, so a section
    that merely happens to be empty in a fixture does not read as a gap.
    """
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG

    missing = []
    for key, node in DAG.items():
        if node.kind != "agent":
            continue
        cap = AGENT_REGISTRY[node.agent]
        if "*" in cap.reads:
            continue
        visible = {s.split(".")[0] for s in cap.reads | cap.writes}
        visible |= {"application", "product", "schemaVersion", "version", "state"}
        for dep in node.depends_on:
            for produced in DAG[dep].produces:
                top = produced.split(".")[0]
                if top in visible or (key, top) in _DELIBERATE_BLIND_SPOTS:
                    continue
                missing.append(f"{key} ({node.agent}) cannot see {produced} from {dep}")
    assert not missing, "\n".join(missing)


def test_blind_spots_are_documented_not_just_listed():
    for (node, section), why in _DELIBERATE_BLIND_SPOTS.items():
        assert len(why) > 40, f"{node}/{section} needs a real reason"


def test_scoping_actually_reduces_what_an_agent_is_handed(svc):
    """The point of §101 is that an agent cannot reach past its job — so a
    scoped agent must be handed strictly less than an unscoped one."""
    from dataclasses import replace

    from services.blueprint import agent_contract
    from services.blueprint.agent_contract import AGENT_REGISTRY

    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "W"}]
    svc.doc["tests"] = [{"id": "TEST-001", "name": "T"}]

    scoped = set(context_for(svc.doc, "requirement"))
    original = AGENT_REGISTRY["requirement"]
    AGENT_REGISTRY["requirement"] = replace(original, reads=frozenset({"*"}))
    try:
        wide = set(context_for(svc.doc, "requirement"))
    finally:
        AGENT_REGISTRY["requirement"] = original

    assert scoped < wide, "scoping handed over the same sections"
    assert "workflows" not in scoped, (
        "the requirements agent has no business seeing workflows")


def test_the_two_agents_that_need_everything_still_get_it():
    """`verification` walks every edge and `memory` derives from every section.
    Scoping either of them would break what they exist to do."""
    from services.blueprint.agent_contract import AGENT_REGISTRY

    for agent in ("verification", "memory"):
        assert "*" in AGENT_REGISTRY[agent].reads, agent
