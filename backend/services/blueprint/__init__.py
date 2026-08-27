"""Blueprint Service (PRD §97) — deterministic custody of the Living Blueprint.

Nothing in this package calls an LLM. Per §116 the model interprets and
proposes; this layer owns identity, versions and state transitions.
"""
from services.blueprint.ids import (  # noqa: F401
    ID_PREFIXES,
    IdAllocator,
    InvalidArtifactId,
    UnknownPrefix,
    api_key,
    component_key,
    entity_key,
    is_valid_id,
    integration_key,
    module_key,
    natural_key_for,
    page_key,
    parse_id,
    permission_key,
    prose_key,
    role_key,
    widget_key,
    workflow_key,
)
from services.blueprint.service import (  # noqa: F401,E402
    BlueprintInvalid,
    BlueprintService,
    IdentityCollision,
    empty_blueprint,
)
from services.blueprint.agent_contract import (  # noqa: F401,E402
    AGENT_REGISTRY,
    AgentCapability,
    AgentResult,
    ArtifactProposal,
    CapabilityViolation,
    ChangeRequest,
    apply_agent_result,
    capability_for,
)
from services.blueprint.verification import (  # noqa: F401,E402
    CHECKS,
    EDGES,
    Finding,
    VerificationReport,
    apply_findings,
    requirement_verdict,
    verify,
)
from services.blueprint.orchestrator import (  # noqa: F401,E402
    ALLOWED_TRANSITIONS,
    DAG,
    STATES,
    DagNode,
    IllegalTransition,
    RunReport,
    TaskSpec,
    build_plan_summary,
    impacted_artifacts,
    incremental_plan,
    levels,
    run,
    transition,
)
from services.blueprint.migration_ledger import (  # noqa: F401,E402
    DISPOSITIONS,
    LEDGER,
    by_disposition,
    new_edges_required,
    summary as ledger_summary,
)
from services.blueprint.scoreboard import (  # noqa: F401,E402
    METRICS,
    Score,
    ScoreRegression,
    assert_no_regression,
    bless,
    compare,
    load_baseline,
    render_table,
    score,
    score_fleet,
)
from services.blueprint.executors import (  # noqa: F401,E402
    DEFAULT_MODEL,
    PROVIDERS,
    GeminiModel,
    ModelReply,
    RunUsage,
    Usage,
    ModelRouter,
    OpenAICompatibleModel,
    ProviderSpec,
    UnknownProvider,
    provider,
    PROPOSAL_SCHEMA,
    AnthropicModel,
    MalformedEnvelope,
    ModelRefused,
    build_prompt,
    context_for,
    make_executor,
    parse_envelope,
)
