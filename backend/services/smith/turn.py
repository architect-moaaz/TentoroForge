"""The model seam — one user turn becomes one structured plan (PRD §7, §16, §116).

Everything else in this package is deterministic. This is the file where
interpretation happens, and it is kept small on purpose: the model decides
*what the user meant*, and deterministic code decides everything that follows
from it.

Three calls, and only three:

``interpret``  user text + resolved context  →  :class:`TurnPlan`
``phrase``     a selected batch of artifacts →  questions in English (§16)
``explain``    an artifact and its trace     →  prose (§7.27); writes nothing

§16's batch is *selected* by ``clarification.select`` before this file is
involved. The model is handed five artifacts and asked to word them. Which five
is arithmetic over confidence, graph in-degree and §23 completeness, and giving
that to a model would make it unreproducible without making it better.

Constrain, don't correct
------------------------
The output is schema-constrained in transport and validated again here against
the real Blueprint. A plan that names an artifact which does not exist is
**rejected and re-asked once, with the failure named** — not patched up.

The distinction matters more than it looks. A repair pass that maps a
hallucinated ``PAGE-099`` onto the nearest real page is guessing at intent, and
it guesses silently, and it is right often enough that nobody removes it. Then
it is load-bearing. That is how a repair chain starts, and this rebuild exists
because one grew to 151 steps.

Nothing has been written when a plan is rejected, so re-asking is free. The one
thing that must never happen is a plan being *fixed* into something the model
did not say.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from services.blueprint.agent_contract import (
    ASK_USER,
    ArtifactProposal,
    capability_for,
)
from services.blueprint.executors import ModelReply
from services.blueprint.ids import is_valid_id
from services.smith.clarification import Question
from services.smith.context import Context

#: What a turn can be. Narrow on purpose — an intent set that grows a category
#: per phrasing stops being a decision and becomes a synonym table.
INTENTS: tuple[str, ...] = (
    "describe",   # states or extends what the application should be
    "answer",     # answers questions Smith asked
    "change",     # modifies an application that already exists
    "ask",        # asks about the application; changes nothing
    "command",    # build, preview, export, deploy
)


#: What a `command` turn can ask for. §107's golden path has exactly two user
#: authorisations in it — step 8 "user accepts the Blueprint" and step 10 "user
#: authorizes build" — and those are `approve` and `build`. The rest are the
#: lifecycle verbs §83/§86 name.
COMMANDS: tuple[str, ...] = (
    "define",    # §107 steps 6-7 — author the Blueprint from the requirements
    "approve",   # §25 — accept the definition, produce the §26 plan
    "build",     # §107 step 10 — authorise the run
    "preview",   # §66 — the running application
    "export",    # §83 — standalone source
    "deploy",    # §86-89
    "status",    # what Smith knows right now
)


class TurnRejected(ValueError):
    """The plan did not survive validation and must be re-asked, not repaired."""


TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "command", "summary", "answers", "anchors",
                 "proposals", "reply", "confidence"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": list(INTENTS),
            "description": (
                "describe = states what the app should be; answer = answers "
                "questions you asked; change = modifies an existing app; "
                "ask = wants to know something, changes nothing; "
                "command = build/preview/export/deploy."
            ),
        },
        "command": {
            "type": "string",
            "enum": ["", *COMMANDS],
            "description": (
                "Only for intent=command; empty string otherwise. "
                "define = draft the Blueprint from the requirements agreed "
                "so far; approve = the user accepts that definition so the "
                "build plan can be produced; build = the user authorises the "
                "run; "
                "preview/export/deploy/status are the lifecycle verbs. Pick "
                "the one the user asked for — do not infer `build` from "
                "enthusiasm."
            ),
        },
        "summary": {
            "type": "string",
            "description": (
                "Your reading of what the user wants, in one sentence. This is "
                "recorded as smithInterpretation in the Blueprint's change "
                "history, so write it for someone reading it in a year."
            ),
        },
        "answers": {
            "type": "array",
            "description": "Only for intent=answer. One entry per question answered.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["artifact", "decision", "reason", "delegated"],
                "properties": {
                    "artifact": {
                        "type": "string",
                        "description": "The artifact id the question was about. Must be one you were asked about.",
                    },
                    "decision": {
                        "type": "string",
                        "description": "What the user decided, stated as a decision rather than as a quote.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why, in the user's terms. Empty if they did not say.",
                    },
                    "delegated": {
                        "type": "boolean",
                        "description": (
                            "True when the user handed the decision back — 'you "
                            "decide', 'whatever is normal'. Recorded differently: "
                            "delegation grants autonomy, it does not create certainty."
                        ),
                    },
                },
            },
        },
        "anchors": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Existing artifact ids this request is about. Use only ids "
                "present in the Blueprint you were given. If you cannot find "
                "the artifact, leave this empty and say so in `reply` — never "
                "guess an id."
            ),
        },
        "proposals": {
            "type": "array",
            "description": (
                "Blueprint changes this request requires. Same contract as any "
                "agent: no ids, a stable natural_key, body as a JSON string."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "natural_key", "body"],
                "properties": {
                    "section": {"type": "string"},
                    "natural_key": {
                        "type": "string",
                        "description": (
                            "Stable identity — entity name, page route. Reused on "
                            "re-runs, so nothing run-specific in it."
                        ),
                    },
                    "body": {
                        "type": "string",
                        "description": "The artifact object, encoded as a JSON string.",
                    },
                },
            },
        },
        "reply": {
            "type": "string",
            "description": "What to say to the user. Plain prose, no markdown headings.",
        },
        "confidence": {
            "type": "number",
            "description": (
                "0..1 in your reading of the request. Below 0.40 nothing is "
                "applied and the user is asked instead, which is the correct "
                "outcome when you are guessing."
            ),
        },
    },
}


@dataclass
class TurnPlan:
    """One interpreted turn, after validation."""

    intent: str
    command: str = ""
    summary: str = ""
    reply: str = ""
    answers: list[dict] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    proposals: list[ArtifactProposal] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def actionable(self) -> bool:
        """§17 — below the clarification line nothing is applied."""
        return self.confidence >= ASK_USER

    @property
    def mutates(self) -> bool:
        return bool(self.proposals or self.answers)


SYSTEM = """You are Smith, the persistent architect of one application.

You are not a chat assistant bolted to a code generator. You hold the \
application's definition — its requirements, data, pages, workflows and rules \
— and you change it by conversation. The definition is the product; the code \
is generated from it. Nothing you say changes the application. What changes it \
is the structured plan you return, which a deterministic service then commits.

What you may write:
{writes}

Anything outside that list is refused, and the refusal costs the whole turn. \
Endpoints, file paths, pattern templates and infrastructure are derived by \
platform code from what you write — do not propose them.

How to answer:

- Identify artifacts by the ids in the Blueprint slice you were given. If the \
thing the user means is not in the slice, say so in `reply` and leave \
`anchors` empty. Never invent an id; a plan naming an artifact that does not \
exist is thrown away whole.
- Do not put ids in `proposals`. Identity is assigned to you.
- natural_key is an artifact's stable identity across runs — an entity's name, \
a page's route. The same artifact must produce the same key next time or it \
will be duplicated instead of updated.
- `confidence` is read, not decoration. Below 0.40 nothing is applied and the \
user is asked instead. That is the right outcome when you are guessing.
- When the user answers a question you asked, record it in `answers` against \
the artifact it settles. If they handed the decision back to you, set \
`delegated` — it is recorded differently, and pretending they chose would put \
words in their mouth.

{decisions}

{task}"""

DECISIONS_ADDENDUM = """Decisions the user has already made. §20: you must \
respect these unless the user deliberately changes one. If this request \
contradicts one, say so in `reply` rather than quietly overriding it.

{decisions}"""

INTERPRET_TASK = """The user has said something. Work out what they mean and \
return the plan that carries it out."""

#: What the turn is *for*, given where the application is (§94, §107).
#:
#: Without this a cold start silently does nothing: on an empty Blueprint there
#: is no artifact to anchor to and nothing below §17's ask-the-user line, so
#: Smith has nothing to ask about and nothing to change. §107 step 4 is
#: "Smith analyses the input" and step 6 is "Smith generates the Application
#: Definition" — which means extracting requirements is the first real act, and
#: requirements are Smith's own to write (§115: they *are* the approved user
#: intent).
STATE_TASKS: dict[str, str] = {
    "DISCOVERY": (
        "This application has no definition yet — §107 step 3, the user is "
        "describing what they want built.\n\n"
        "Extract requirements from what they say: one per distinct capability, "
        "each a sentence a non-technical stakeholder would recognise as a "
        "promise the software makes. Propose them into `requirements`, and set "
        "each one's confidence honestly — what the user stated outright is not "
        "the same as what you inferred from the domain, and the difference is "
        "what decides which questions get asked next.\n\n"
        "Do not propose pages, entities or workflows yet. Specialist agents "
        "author those from the requirements once the definition is accepted; "
        "designing them now would be guessing ahead of the clarification."
    ),
    "CLARIFICATION": (
        "The definition is being clarified (§107 step 5). If the user is "
        "answering questions you asked, record each answer against the "
        "artifact it settles. If they are adding new intent, extract it as "
        "requirements."
    ),
}


def _writes_for(agent: str = "smith") -> str:
    return "\n".join(f"  - {s}" for s in sorted(capability_for(agent).writes))


SHAPE_ADDENDUM = """

## The shape of what you write

Each artifact `body` must match the contract for its section exactly. Extra
properties are rejected outright — the Blueprint's schema is closed, and a body
carrying a field it invented is thrown away whole rather than trimmed to fit.
Omit `id`; identity is assigned for you.

```json
{shapes}
```"""

#: Sections worth showing the shape of, given where the application is. A cold
#: start only ever writes requirements, and inlining nineteen section schemas
#: to say so costs ~4,900 tokens to no purpose.
STATE_SHAPES: dict[str, tuple[str, ...]] = {
    "DISCOVERY": ("requirements",),
    "CLARIFICATION": ("requirements",),
}


def shapes_for(agent: str, state: str) -> dict[str, Any]:
    """The contract slice describing what this turn may produce.

    Smith was told *which* sections it owns and never what an artifact in them
    looks like. The first live cold start is what surfaced it: asked for
    requirements, the model returned `title`, `statement`, `actor`, `priority`,
    `source` and `notes` — a perfectly reasonable requirement shape, and not
    this contract's. All five were rejected.

    That is the same defect already found and fixed on the agent path, where
    `writable_shapes` inlines the contract slice into the prompt. Smith simply
    never got the same treatment.
    """
    from services.blueprint.executors import writable_shapes

    shapes = writable_shapes(agent)
    wanted = STATE_SHAPES.get(state)
    if wanted:
        shapes = {k: v for k, v in shapes.items() if k in wanted}
    return shapes


def body_errors(section: str, body: dict, agent: str = "smith") -> list[str]:
    """Contract errors for one proposal body, before anything is written.

    Checked here so a bad shape is *re-asked* rather than raised. Without it the
    failure surfaced from ``BlueprintService.validate`` deep inside
    ``apply_change``, which is past the point where a retry is possible: the
    turn died with a traceback instead of Smith saying "that did not fit, let me
    try again".
    """
    import json as _json
    import warnings

    from services.blueprint.service import CONTRACT_PATH

    shape = shapes_for(agent, "").get(section)
    if not shape:
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from jsonschema import Draft7Validator, RefResolver

        contract = _json.loads(CONTRACT_PATH.read_text("utf-8"))
        validator = Draft7Validator(shape, resolver=RefResolver.from_schema(contract))
        return [e.message for e in validator.iter_errors(body)]


def build_interpret_prompt(
    context: Context, *, agent: str = "smith", inline_schema: bool = False,
    state: str = "",
) -> tuple[str, str]:
    """(system, user) for one interpretation call.

    ``state`` is §94's application state. It changes what the turn is for: in
    DISCOVERY the job is to extract requirements from a description, and
    everywhere else it is to interpret a request against a definition that
    already exists.
    """
    decisions = context.decisions[:40]
    decisions_block = (
        DECISIONS_ADDENDUM.format(
            decisions="\n".join(
                f"  - {d.get('id')}: {d.get('decision')}"
                + (f"  (because {d['reason']})" if d.get("reason") else "")
                for d in decisions
            )
        )
        if decisions else ""
    )
    system = SYSTEM.format(
        writes=_writes_for(agent), decisions=decisions_block,
        task=STATE_TASKS.get(state, INTERPRET_TASK),
    )
    shapes = shapes_for(agent, state)
    if shapes:
        system += SHAPE_ADDENDUM.format(
            shapes=json.dumps(shapes, indent=2)[:12000]
        )
    if inline_schema:
        system += (
            "\n\nReturn JSON matching this schema exactly:\n"
            + json.dumps(TURN_SCHEMA, indent=2)
        )

    parts = ["The application, sliced to what looks relevant to this request:",
             "```json", json.dumps(context.blueprint, indent=2, sort_keys=True), "```"]
    if context.truncated:
        parts.append(
            "This slice is capped and does not contain every artifact that "
            "matched. If what you need is missing, say so rather than assuming "
            "it does not exist."
        )
    if not context.grounded:
        parts.append(
            "Nothing in the application matched this request's wording. Treat "
            "that as a signal to ask what they mean, not to guess."
        )
    if context.conversation:
        parts += ["", "The conversation so far:"]
        parts += [f"  [{m['id']}] {m['role']}: {m['text']}" for m in context.conversation]
    parts += ["", "The user says:", context.request]
    return system, "\n".join(parts)


def parse_turn(raw: str) -> TurnPlan:
    """Parse the envelope. Structural failures only — semantics come next."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TurnRejected(f"reply was not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TurnRejected("reply was not a JSON object")

    intent = data.get("intent")
    if intent not in INTENTS:
        raise TurnRejected(
            f"{intent!r} is not one of {', '.join(INTENTS)}"
        )

    proposals: list[ArtifactProposal] = []
    for i, p in enumerate(data.get("proposals") or []):
        body_raw = p.get("body")
        try:
            body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
        except json.JSONDecodeError as exc:
            raise TurnRejected(f"proposal {i} body was not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise TurnRejected(f"proposal {i} body was not an object")
        body.pop("id", None)  # identity is not the model's to assign (§12)
        proposals.append(ArtifactProposal(
            section=p.get("section", ""),
            natural_key=p.get("natural_key", ""),
            body=body,
        ))

    return TurnPlan(
        intent=intent,
        command=str(data.get("command") or ""),
        summary=str(data.get("summary") or ""),
        reply=str(data.get("reply") or ""),
        answers=[dict(a) for a in (data.get("answers") or [])],
        anchors=[str(a) for a in (data.get("anchors") or [])],
        proposals=proposals,
        confidence=float(data.get("confidence") or 0.0),
    )


def validate_turn(
    plan: TurnPlan,
    doc: dict,
    *,
    asked: Sequence[Question] = (),
    agent: str = "smith",
) -> None:
    """Check the plan against the actual Blueprint. Raises; never edits.

    Every failure here is a case where a repair would be easy and wrong.
    Dropping an unknown anchor would silently change what the turn is about;
    clamping an out-of-range confidence would overrule the model's own report
    of how sure it is; re-homing a proposal into a section Smith may write
    would move a decision from the model to a fallback nobody reviewed.
    """
    from services.blueprint.orchestrator import graph_pool

    known = {art["id"] for _s, art in graph_pool(doc) if art.get("id")}
    problems: list[str] = []

    unknown = [a for a in plan.anchors if a not in known]
    if unknown:
        problems.append(
            f"anchors name artifacts that do not exist: {', '.join(sorted(unknown))}"
        )

    malformed = [a for a in plan.anchors if not is_valid_id(a)]
    if malformed:
        problems.append(f"anchors are not artifact ids: {', '.join(sorted(malformed))}")

    # An answer must settle something that was actually asked. Without this a
    # turn could record a "user decision" about an artifact the user was never
    # shown, which is the one thing §20's `source: user` must never mean.
    askable = {q.artifact for q in asked}
    for answer in plan.answers:
        artifact = answer.get("artifact")
        if artifact not in known:
            problems.append(f"answer names an artifact that does not exist: {artifact!r}")
        elif asked and artifact not in askable:
            problems.append(
                f"answer settles {artifact}, which was not among the questions "
                f"asked ({', '.join(sorted(askable))})"
            )
        if not (answer.get("decision") or "").strip():
            problems.append(f"answer for {artifact} records no decision")

    cap = capability_for(agent)
    for p in plan.proposals:
        if not cap.can_write(p.section):
            problems.append(
                f"proposal writes {p.section!r}, outside Smith's boundary "
                f"({', '.join(sorted(cap.writes))})"
            )
            continue
        if not p.natural_key:
            problems.append(f"proposal for {p.section!r} has no natural_key")
        for message in body_errors(p.section, p.body, agent):
            problems.append(f"{p.section} body for {p.natural_key!r}: {message}")

    if not 0.0 <= plan.confidence <= 1.0:
        problems.append(f"confidence {plan.confidence} is outside 0..1")

    # A command turn that does not say which command is the failure mode this
    # field exists to close: `intent: command` used to be parsed and then
    # silently dispatched to nothing, so "build it" got a confident reply and
    # no build. Refuse rather than guess which verb was meant.
    if plan.intent == "command" and plan.command not in COMMANDS:
        problems.append(
            f"intent is 'command' but command is {plan.command!r}; "
            f"expected one of {', '.join(COMMANDS)}"
        )
    if plan.intent != "command" and plan.command:
        problems.append(
            f"command {plan.command!r} was set on a {plan.intent!r} turn; "
            "commands are only carried by intent='command'"
        )

    if problems:
        raise TurnRejected("; ".join(problems))


def interpret(
    client: Any,
    context: Context,
    doc: dict,
    *,
    asked: Sequence[Question] = (),
    agent: str = "smith",
    state: str = "",
    retries: int = 1,
) -> TurnPlan:
    """One interpretation call, re-asked once if the plan does not validate.

    The retry appends the rejection to the prompt and asks again. It does not
    adjust the reply. Compare ``make_executor``, which does the same thing for
    agent envelopes: repair *before* anything is committed is the system
    working, because a rejected plan never became an artifact.
    """
    system, user = build_interpret_prompt(
        context, agent=agent,
        inline_schema=not getattr(client, "enforces_schema", True),
        state=state,
    )
    last: Exception | None = None

    for attempt in range(retries + 1):
        prompt = user
        if attempt and last:
            prompt = (
                f"{user}\n\nYour previous reply was rejected: {last}\n"
                "Return a corrected plan. Do not explain the mistake, and do "
                "not invent ids to satisfy the check."
            )
        raw = client(system=system, user=prompt, schema=TURN_SCHEMA)
        text = raw.text if isinstance(raw, ModelReply) else raw
        try:
            plan = parse_turn(text)
            validate_turn(plan, doc, asked=asked, agent=agent)
            return plan
        except TurnRejected as exc:
            last = exc

    raise TurnRejected(f"plan rejected after {retries + 1} attempts: {last}")


# ---------------------------------------------------------------------------
# §16 — wording the batch
# ---------------------------------------------------------------------------

QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["preamble", "questions"],
    "properties": {
        "preamble": {
            "type": "string",
            "description": (
                "One sentence saying what you now understand, before asking. "
                "§16's example opens 'I understand the gate-entry process.'"
            ),
        },
        "questions": {
            "type": "array",
            "description": "Exactly one question per artifact you were given, in the same order.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["artifact", "question"],
                "properties": {
                    "artifact": {"type": "string"},
                    "question": {
                        "type": "string",
                        "description": (
                            "A single closed question a non-technical user can "
                            "answer. No ids, no section names, no jargon."
                        ),
                    },
                },
            },
        },
    },
}

PHRASE_TASK = """These are the decisions that most need the user's input right \
now. They were selected by the platform, not by you — do not add, drop or \
reorder them.

Write one question for each, in the user's language. A question should be \
answerable in a sentence by someone who knows the business and not the \
software: no artifact ids, no section names, no talk of confidence.

{questions}"""


@dataclass
class QuestionBatch:
    """§16's grouped ask, wording joined back to the artifacts it settles."""

    preamble: str = ""
    #: ``(artifact_id, question)`` in the order they were selected.
    items: list[tuple[str, str]] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def render(self) -> str:
        lines = [self.preamble] if self.preamble else []
        lines += [f"  {i}. {text}" for i, (_a, text) in enumerate(self.items, 1)]
        return "\n".join(lines)

    @property
    def artifacts(self) -> list[str]:
        return [a for a, _q in self.items]


def phrase(client: Any, batch: Sequence[Question], *, agent: str = "smith") -> QuestionBatch:
    """Turn a selected batch into questions a person can answer (§16).

    Rejects a reply that answers about artifacts other than the ones selected.
    The selection is the deterministic part and it is not the model's to
    revise — a model that quietly swapped a question would be overruling the
    materiality ranking with an impression, which is §116 backwards.
    """
    if not batch:
        return QuestionBatch()

    described = "\n".join(
        f"  - {q.artifact} ({q.section}): {q.label}\n"
        f"      why it matters: {q.why}"
        for q in batch
    )
    system = SYSTEM.format(
        writes=_writes_for(agent), decisions="",
        task=PHRASE_TASK.format(questions=described),
    )
    if not getattr(client, "enforces_schema", True):
        system += ("\n\nReturn JSON matching this schema exactly:\n"
                   + json.dumps(QUESTION_SCHEMA, indent=2))

    raw = client(system=system, user="Write the questions.", schema=QUESTION_SCHEMA)
    text = raw.text if isinstance(raw, ModelReply) else raw
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TurnRejected(f"question batch was not JSON: {exc}") from exc

    wanted = [q.artifact for q in batch]
    items: list[tuple[str, str]] = []
    for entry in data.get("questions") or []:
        artifact, question = entry.get("artifact"), (entry.get("question") or "").strip()
        if artifact in wanted and question:
            items.append((artifact, question))

    covered = {a for a, _ in items}
    missing = [a for a in wanted if a not in covered]
    if missing:
        raise TurnRejected(
            f"no question written for {', '.join(missing)}; the batch is chosen "
            "by materiality and is not the model's to edit"
        )

    order = {a: i for i, a in enumerate(wanted)}
    items.sort(key=lambda it: order[it[0]])
    return QuestionBatch(
        preamble=str(data.get("preamble") or ""), items=items, questions=list(batch),
    )


# ---------------------------------------------------------------------------
# §7.27 / §8 — explaining the application back
# ---------------------------------------------------------------------------

EXPLAIN_TASK = """Explain this part of the application to the user in plain \
prose. You are given the artifact, everything that traces to it, and the files \
that implement it — all of it factual, all of it from the application's own \
definition.

Explain what it does and how it connects. Do not speculate beyond what you \
were given, and do not describe the Blueprint as a document: the user cares \
about their application, not about how it is stored."""


EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {
        "answer": {
            "type": "string",
            "description": "The explanation, in plain prose.",
        },
    },
}


def explain(client: Any, context: Context, subject: str, *, agent: str = "smith") -> str:
    """Answer a question about the application. Writes nothing (§7.27).

    Schema-constrained like the others, even though the payload is one string.
    ``AnthropicModel`` builds ``output_config.format`` unconditionally, so a
    client called with ``schema=None`` fails at the transport rather than
    returning prose — and an unconstrained reply would arrive wrapped in
    whatever preamble the model felt like adding.
    """
    system = SYSTEM.format(writes="  (nothing — this is a read-only answer)",
                           decisions="", task=EXPLAIN_TASK)
    user = "\n".join([
        f"Subject: {subject}",
        "",
        "```json",
        json.dumps(context.blueprint, indent=2, sort_keys=True),
        "```",
        "",
        "Implementation:",
        json.dumps(context.code, indent=2, sort_keys=True) or "(not yet generated)",
        "",
        f"The user asks: {context.request}",
    ])
    raw = client(system=system, user=user, schema=EXPLAIN_SCHEMA)
    text = raw.text if isinstance(raw, ModelReply) else str(raw)
    try:
        return str(json.loads(text).get("answer") or text)
    except (json.JSONDecodeError, AttributeError):
        return text
