"""Smith — the persistent application architect (PRD §6–§8, §16, §20, §69, §114, §118).

The conversational layer over ``services.blueprint``. Two packages rather than
one because §118 names two things: *Smith ↕ Living Blueprint*. The Blueprint
package holds custody of what the application is; this one holds the architect
that changes it by conversation.

Only :mod:`services.smith.turn` calls a model. Everything else — which
questions to ask, what a change affects, which DAG nodes re-run, what
implements a requirement — is derived (§116).
"""
from services.smith.conversation import (  # noqa: F401
    ROLES,
    Conversation,
    MalformedTranscript,
    Message,
)
from services.smith.code_intel import (  # noqa: F401,E402
    CHAIN,
    CodeLocation,
    Trace,
    coverage,
    dependencies,
    implements,
    neighbourhood,
    serves,
    trace,
    where,
)
from services.smith.context import (  # noqa: F401,E402
    DEFAULT_BUDGET,
    Context,
    Scored,
    resolve,
    score_artifacts,
)
from services.smith.clarification import (  # noqa: F401,E402
    DEFAULT_BATCH,
    QUESTION_SECTIONS,
    Question,
    already_asked,
    candidates,
    in_degree,
    select,
    summary,
)
from services.smith.decisions import (  # noqa: F401,E402
    ANSWERED_CONFIDENCE,
    DELEGATED_CONFIDENCE,
    SOURCES,
    NotADecision,
    RecordedDecision,
    by_user,
    record,
)
from services.smith.change import (  # noqa: F401,E402
    IMPACT_DEPTH,
    ChangeResult,
    ImpactReport,
    PreviewContext,
    analyse,
    apply_change,
    resolve_preview,
)
from services.smith.turn import (  # noqa: F401,E402
    INTENTS,
    EXPLAIN_SCHEMA,
    QUESTION_SCHEMA,
    TURN_SCHEMA,
    QuestionBatch,
    TurnPlan,
    TurnRejected,
    interpret,
    parse_turn,
    phrase,
    validate_turn,
)
from services.smith.smith import Smith, Turn, bootstrap  # noqa: F401,E402
