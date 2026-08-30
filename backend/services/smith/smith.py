"""Smith — the persistent application architect (PRD §6, §8, §114, §118).

§118 states the relationship the whole product is built around::

    Smith  ↕  Living Blueprint  ↕  Knowledge Graph  ↕  Implementation  ↕  App

and then says what Smith is not: *"Smith is not merely a chat assistant
attached to a code generator. Smith is the persistent AI architect of the
application."*

Persistent is the operative word, and it is a claim about storage rather than
about tone. A batch pipeline holds its state in the call stack: you assemble a
plan, run the DAG, and when the process exits the application's understanding
of itself exits with it. Smith holds nothing in the call stack. Every layer it
thinks with is on disk before the turn ends:

    Layer 1  Conversation   .forge/smith/conversation.jsonl
    Layer 2  Blueprint      .forge/blueprint/current.json  (+ versions/)
    Layer 3  Decisions      the Blueprint's `decisions` section
    Layer 4  Code           the Blueprint's `codeMap` section

So a Smith constructed tomorrow in a new process is the same Smith. That is the
whole of what "persistent" buys, and it is enough: §114's twelve-step
prompt-to-change works on an application nobody has looked at in a month
because none of the twelve steps needs anything that was in memory.

What a turn is
--------------
One user message in, one :class:`Turn` out. The model is consulted once to say
what the message *meant*; everything the platform then does about it —
selecting questions, analysing impact, allocating ids, committing versions,
choosing which DAG nodes re-run — is deterministic (§116).

Smith's writes go through :func:`agent_contract.apply_agent_result` against a
capability declared in ``AGENT_REGISTRY``, exactly like every specialist
agent's. A coordinator exempt from the boundary check is §28's uncontrolled
swarm with a nicer name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from services.blueprint import references
from services.blueprint.ids import IdAllocator, InvalidArtifactId, natural_key_for
from services.blueprint.orchestrator import (
    ALLOWED_TRANSITIONS,
    IllegalTransition,
    RunReport,
    DAG,
    build_plan_summary,
    can_transition,
    graph_pool,
    levels,
    transition,
)
from services.blueprint.orchestrator import run as run_dag
from services.blueprint.service import BlueprintService
from services.smith import clarification, decisions as decision_log
from services.smith.change import ChangeResult, PreviewContext, apply_change, resolve_preview
from services.smith.code_intel import Trace, coverage, trace
from services.smith.context import Context, resolve
from services.smith.conversation import Conversation, Message
from services.smith.turn import (
    QuestionBatch,
    TurnPlan,
    TurnRejected,
    explain as explain_call,
    interpret,
    phrase,
)


#: §94 as a turn-level table: (state, event) -> the state that turn moves to.
#:
#: §94 says "the orchestration engine controls allowed state transitions", and
#: §25 plus §107 steps 8 and 10 say *when* the interesting ones happen — the
#: user accepts the definition, and the user authorises the build. So the
#: machine advances on turns, not on a timer, and this is the whole of what a
#: turn is allowed to do to it.
#:
#: Declared rather than computed so that an illegal transition is impossible to
#: express, not merely caught. ``test_every_declared_transition_is_legal``
#: checks every entry against ``ALLOWED_TRANSITIONS``, so this table cannot
#: drift from §94.
TURN_TRANSITIONS: dict[tuple[str, str], str] = {
    # §107 steps 3-5: the user describes, Smith starts clarifying.
    ("DISCOVERY", "describe"): "CLARIFICATION",
    # §107 step 8 and step 10 are both "accepts *or modifies*", and §94 gives
    # each gate a back-edge for the second half of that. Without these two
    # entries the back-edges are legal and unreachable: a user correcting the
    # domain description at the gate has no event that moves the machine, so
    # the correction lands in the Blueprint while the state still claims the
    # description is awaiting acceptance.
    ("BLUEPRINT_REVIEW", "change"): "DEFINITION",
    ("PLAN_REVIEW", "change"): "PLANNING",
    # A change request against an application that has been previewed is §114
    # maintenance, which §94 routes through ITERATION.
    ("PREVIEW", "change"): "ITERATION",
    ("READY", "change"): "ITERATION",
    ("MAINTENANCE", "change"): "ITERATION",
}

#: §107 steps 6-7 into step 8's gate. Authoring the domain description parks at
#: BLUEPRINT_REVIEW, which is the first of the two things §107 asks a user to
#: accept. Starts at DEFINITION so it is reachable from CLARIFICATION, where a
#: user who is happy with the answers actually is.
DEFINE_WALK: tuple[str, ...] = ("DEFINITION", "BLUEPRINT_REVIEW")

#: §25/§107 steps 8-9. Accepting the domain description is one user act that
#: buys the rest of the definition and the §26 plan, and parks at the build
#: authorisation gate; it is not four separate asks.
APPROVE_WALK: tuple[str, ...] = ("PLANNING", "PLAN_REVIEW")

#: The two review gates — the states where the application is waiting on a
#: person rather than on a node. §94 gives each a back-edge to the state that
#: authored it (BLUEPRINT_REVIEW → DEFINITION, PLAN_REVIEW → PLANNING), which
#: is how "modify" is expressed; :meth:`Smith.turn` uses this set to return to
#: the gate afterwards, because a user who corrected something is still
#: standing at the gate they corrected it from.
GATES: frozenset[str] = frozenset({"BLUEPRINT_REVIEW", "PLAN_REVIEW"})


#: §107 step 6 — the nodes that author what the application *is*, as opposed to
#: what it will be made of. Between them they write ``requirements`` and
#: ``product``: the objectives, the personas, the domain's own vocabulary, the
#: capabilities. Named rather than derived, because "is this a domain claim"
#: is a judgement about meaning and not a property of the graph.
DOMAIN_NODES: tuple[str, ...] = ("requirements", "application_model")


def domain_nodes() -> list[str]:
    """The domain description — two model calls, and everything inherits them.

    This is the cheap half of the definition and the half most worth being
    wrong about early: every other node reads ``requirements`` or ``product``,
    so a misread of the problem in its first sentence is a misread the whole
    fan-out then elaborates faithfully.
    """
    order = [k for lvl in levels() for k in lvl]
    return [k for k in order if k in DOMAIN_NODES]


def definition_nodes() -> list[str]:
    """What the user buys by accepting the domain description — §107 step 9.

    The split matters and is easy to get backwards in either direction. §107
    step 8 is "user accepts or modifies the Blueprint" and step 10 is "user
    authorizes build", so there are two gates, and each has to have something
    real behind it:

    * Run *everything* before the first gate and the user is asked to accept a
      reading of their problem only after a dozen model calls have elaborated
      it — and a user who corrects the first sentence pays for the fan-out
      twice.
    * Run everything after the *second* gate instead and §26's plan reports 18
      pages as 0, and authorising a build means authorising a blank document.

    So the entities, pages, workflows and rules are authored *between* the
    gates: after the domain description is accepted, before the plan is shown.
    Nothing is ever approved blank, and nothing is elaborated from a premise
    nobody confirmed.

    Agent and derivation nodes define, projections implement. Verification is
    excluded because §107 puts it at step 20, after the build — a report
    against a definition nobody has built yet has nothing to check.
    """
    order = [k for lvl in levels() for k in lvl]
    return [
        k for k in order
        if DAG[k].kind in ("agent", "service")
        and k != "verification"
        and k not in DOMAIN_NODES
    ]


def domain_summary(doc: dict) -> dict[str, Any]:
    """§107 step 8's gate, made reviewable — what Smith understood.

    The plan gate can be a row of numbers because a plan is a quantity: 18
    pages either is or is not what you expected. A domain description is not.
    "4 personas" is nothing a user can accept or correct; the personas' names,
    the vocabulary Smith adopted and the objectives it inferred are the whole
    of what there is to disagree with, so they are what the gate shows.

    ``assumed`` is the part that earns the gate. §17 already scores every
    artifact Smith is unsure of, and :func:`clarification.candidates` is that
    scoring — reused here rather than re-derived, so there is one ask-the-user
    line in the platform and not two that drift. A user reading this sees the
    difference between what they said and what Smith supplied on their behalf,
    which is the single most useful thing a review can tell them.
    """
    product = doc.get("product") or {}
    live = [r for r in (doc.get("requirements") or [])
            if r.get("status") != "DEPRECATED"]
    open_now = {q.artifact: q for q in clarification.candidates(doc)}

    return {
        "application": (doc.get("application") or {}).get("name", ""),
        "objectives": list(product.get("objectives") or []),
        "personas": [
            {"name": p.get("name", ""), "description": p.get("description", "")}
            for p in (product.get("personas") or []) if isinstance(p, dict)
        ],
        "terminology": dict(product.get("terminology") or {}),
        "capabilities": [
            c.get("name", "") for c in (product.get("capabilities") or [])
            if isinstance(c, dict)
        ],
        "requirements": [
            {
                "id": r.get("id", ""),
                "description": r.get("description", ""),
                "confidence": r.get("confidence"),
                # §17 — an artifact Smith flagged as its own assumption rather
                # than something the user said.
                "assumption": r.get("assumption", ""),
            }
            for r in live
        ],
        "assumed": [
            r.get("id", "") for r in live
            if r.get("id") in open_now or r.get("assumption")
        ],
    }


def design_summary(doc: dict, references: Sequence[Path] = ()) -> dict[str, Any]:
    """§26's plan gate, for the half of it that is not a count.

    §107 step 9 shows the user what will be built, and the colour scheme
    belongs among it — it is the one decision at this gate a person can judge
    at a glance, and the first thing they will notice is wrong. Eight counts
    and no colour is a plan review that hides the most visible thing in the
    plan.

    Kept out of :func:`build_plan_summary` rather than folded into it. That
    function returns a map of section to count and several callers read it as
    exactly that; a palette is not a count, and widening the return type to
    carry one would make every caller handle a value that is not what the
    function is for.

    ``references`` is reported as what was *shown*, not as what was used. The
    agent saw them; whether the palette came off them is a claim only
    ``visualPersonality`` can make, and it is asked to.
    """
    ds = doc.get("designSystem") or {}
    return {
        "personality": ds.get("visualPersonality", ""),
        "colors": dict(ds.get("colors") or {}),
        "typography": dict(ds.get("typography") or {}),
        "density": ds.get("informationDensity", ""),
        "navigation": ds.get("navigationApproach", ""),
        "referencesShown": [p.name for p in references],
    }


def build_nodes() -> list[str]:
    """Nodes that turn an accepted definition into a running app (§107 12-21)."""
    order = [k for lvl in levels() for k in lvl]
    return [k for k in order if DAG[k].kind == "projection" or k == "verification"]

#: §107 steps 10-21, and the order §94 puts them in. Walked as far as the run
#: actually got — see :meth:`Smith.build`.
#: Each state is gated on a node from :func:`build_nodes` — the ones that
#: actually run in this phase. Gating on `database` or `data_model` would never
#: fire: those author the definition and have already run by now, so the walk
#: would stop at IMPLEMENTATION however well the build went.
BUILD_WALK: tuple[tuple[str, str], ...] = (
    ("IMPLEMENTATION", ""),                       # entered before anything runs
    ("DATABASE_PROVISIONING", "backend"),         # §56-62: schema, migrations, seed
    ("BUILD", "integration"),                     # the join projection
    ("VERIFICATION", "verification"),             # §107 step 20
    ("PREVIEW", "preview"),                       # §107 step 21
)


def bootstrap(svc: BlueprintService) -> int:
    """Bind the document's existing ids into the ID allocator.

    Needed whenever a Blueprint arrives without the ``ids.json`` that was
    written alongside it — loading a fixture into a fresh directory, restoring
    from an export, importing an application.

    Without it the allocator starts from zero and hands out ``DEC-001`` for a
    brand-new decision while ``DEC-001`` already means something else in the
    document. ``upsert`` refuses that outright (``IdentityCollision``), so the
    application is not corrupted — but it also cannot be changed until the
    registry is taught what the document already knows, which is this.

    Keys come from :func:`natural_key_for`, the same scheme ``upsert``'s
    callers use. Binding under anything else would register the id without
    making it *findable*: the next proposal for an artifact already in the
    document would miss its binding and be allocated a second id.

    Re-binding is idempotent, and ``IdAllocator.bind`` advances each counter
    past the highest id it has seen, so nothing already in the document can be
    minted again. Keys the scheme no longer produces are then pruned, so a
    document written before the scheme changed ends up with exactly one key per
    artifact. Returns the number of registry entries added or dropped — zero on
    a second run over the same document.
    """
    changed = 0
    with IdAllocator.session(output_dir=svc.output_dir) as alloc:
        #: artifact id -> the key it ended up registered under, for the prune.
        registered: dict[str, str] = {}

        def register(artifact_id: str, *candidates: str | None) -> bool:
            """Bind ``artifact_id`` under the first candidate key that is free.

            The last candidate is always the id itself, and that matters more
            than it looks: when two artifacts share a natural key one of them
            cannot be bound under it, and dropping it would leave the counter
            short of the highest id in use — so the next allocation would mint
            straight over an existing artifact. Registered under its own id it
            is at least safe, and the ambiguity is left for verification to
            surface rather than resolved by guessing (§116).
            """
            for key in candidates:
                if not key:
                    continue
                if alloc.lookup(key) == artifact_id:
                    registered[artifact_id] = key
                    return False  # already registered
                try:
                    alloc.bind(key, artifact_id)
                except InvalidArtifactId:
                    continue  # taken by a different artifact, or a malformed id
                registered[artifact_id] = key
                return True
            return False

        # Widgets are keyed on the route of the page they sit on, and carry
        # only that page's id.
        page_routes = {
            page["id"]: page.get("route") or ""
            for page in (svc.doc.get("pages") or [])
            if page.get("id")
        }

        for section, art in graph_pool(svc.doc):
            artifact_id = art.get("id")
            if not artifact_id:
                continue  # codeMap entries are keyed by the artifact they map
            changed += register(
                artifact_id,
                natural_key_for(section, art, page_routes=page_routes),
                artifact_id,
            )

        # Decisions are keyed on the *artifact they decide*, not on their own
        # prose — that is the natural key `decision_memory` upserts them under,
        # and the only link back, since the contract gives a decision no field
        # naming its subject.
        #
        # Recovering that link matters. Bound under its own id instead, a
        # derived decision is invisible to `_existing_for`, so the user
        # answering a question about that artifact creates a *second* decision
        # rather than superseding the first — and `user_decided` never protects
        # it from the next re-derivation.
        #
        # The mapping is recoverable because the derivation is deterministic:
        # `assumptions` regenerates each decision's exact text alongside the
        # artifact it came from. Matching on that text is safe in the only
        # direction that matters — a match means the derivation would produce
        # this decision for this artifact.
        from services.blueprint.decision_memory import assumptions

        derived = {a["decision"]: a["_artifact"] for a in assumptions(svc.doc)}
        for decision in svc.doc.get("decisions") or []:
            decision_id = decision.get("id")
            if not decision_id:
                continue
            changed += register(
                decision_id,
                derived.get(decision.get("decision", "")),
                decision_id,
            )

        # A scheme that has changed since the document was written leaves each
        # artifact registered twice: under the key it was written with, and
        # under the key everything now looks it up by. The stale one is not
        # merely unused — `key_for` can return it, so `upsert` reads an
        # artifact handed an explicit id as belonging to a key its caller never
        # named, and refuses a change that is perfectly well formed.
        #
        # Only keys for an artifact that is *in the document* and already
        # reachable under its current key are dropped, so this removes a
        # duplicate route to an artifact and never an artifact's identity. A
        # binding for an id the document no longer carries is left alone: it
        # costs nothing, and §22 revival should get its own id back.
        for key, artifact_id in list(alloc.bindings.items()):
            if registered.get(artifact_id, key) != key:
                alloc.unbind(key)
                changed += 1
    return changed


@dataclass
class Turn:
    """Everything one exchange produced, for a caller to render or assert on."""

    user: Message
    plan: TurnPlan | None = None
    reply: str = ""
    #: §16's batch, when Smith asked rather than acted.
    questions: QuestionBatch | None = None
    #: §20 decisions this turn recorded.
    recorded: list[decision_log.RecordedDecision] = field(default_factory=list)
    #: §71/§72, when the turn changed the application.
    change: ChangeResult | None = None
    #: §18, when the turn was a question about the application.
    trace: Trace | None = None
    context: Context | None = None
    smith: Message | None = None
    rejected: str = ""
    #: §94 state before and after this turn. Equal when the turn did not move
    #: the machine, which is most turns.
    state_before: str = ""
    state_after: str = ""
    #: §26's countable plan, when the turn produced one.
    plan_summary: dict[str, int] | None = None
    #: §107 step 8's gate — what Smith understood, when the turn authored it.
    domain_summary: dict[str, Any] | None = None
    #: §26's plan gate, for the half of the plan that is not a count.
    design_summary: dict[str, Any] | None = None
    #: What a command turn did. ``refused`` carries the reason when a command
    #: is recognised but deliberately not executed.
    command: str = ""
    command_result: dict[str, Any] = field(default_factory=dict)
    #: §72/§107 — the DAG run a build produced.
    run: RunReport | None = None

    @property
    def ok(self) -> bool:
        return not self.rejected

    @property
    def intent(self) -> str:
        return self.plan.intent if self.plan else "unknown"

    @property
    def moved(self) -> bool:
        return bool(self.state_after) and self.state_after != self.state_before


class Smith:
    """The architect. Construct it against an application; it remembers."""

    def __init__(
        self,
        blueprint: BlueprintService,
        *,
        model: Any = None,
        executor: Callable[[Any], Any] | None = None,
        app_root: str | None = None,
        question_limit: int = clarification.DEFAULT_BATCH,
    ):
        self.blueprint = blueprint
        self.conversation = Conversation(blueprint.output_dir)
        self.model = model
        self.executor = executor
        self.app_root = app_root
        self.question_limit = question_limit

    # -- construction -------------------------------------------------------

    @classmethod
    def load(cls, output_dir: str | Path, **kw: Any) -> "Smith":
        svc = BlueprintService.load(output_dir=output_dir)
        bootstrap(svc)
        return cls(svc, **kw)

    @classmethod
    def adopt(cls, doc: dict, output_dir: str | Path, **kw: Any) -> "Smith":
        """Take custody of an existing Blueprint document at a new location.

        Bootstraps the allocator from the document, which is the whole point:
        adopting without it renumbers the application.
        """
        svc = BlueprintService(output_dir=str(output_dir))
        svc.doc = doc
        svc.root.mkdir(parents=True, exist_ok=True)
        svc.save()
        bootstrap(svc)
        return cls(svc, **kw)

    # -- the four layers ----------------------------------------------------

    @property
    def doc(self) -> dict:
        return self.blueprint.doc

    def context_for(self, request: str, *, anchors: Sequence[str] = (), **kw: Any) -> Context:
        """§8's Context Resolver, over all four layers."""
        return resolve(
            self.doc, request, anchors=list(anchors),
            conversation=self.conversation, **kw,
        )

    def open_questions(self, limit: int | None = None) -> list[clarification.Question]:
        """§16 — the most material things nobody has decided."""
        return clarification.select(
            self.doc, conversation=self.conversation,
            limit=self.question_limit if limit is None else limit,
        )

    def status(self) -> dict[str, Any]:
        """What Smith knows about the application right now."""
        return {
            "application": self.doc.get("application", {}).get("name", ""),
            "version": self.doc.get("version", 1),
            "state": self.doc.get("state", "DISCOVERY"),
            "messages": len(self.conversation),
            "completeness": self.doc.get("completeness", {}),
            "clarification": clarification.summary(self.doc),
            "decisions": {
                "total": len(self.doc.get("decisions") or []),
                "byUser": len(decision_log.by_user(self.doc)),
            },
            # Counts only. `coverage` returns every unmapped id, which is the
            # right API and the wrong status line — on the ATS fixture it is
            # 305 entries, and a status nobody can read is a status nobody
            # checks.
            "code": {k: v for k, v in coverage(self.doc).items() if k != "unmapped"},
        }

    def trace(self, requirement_id: str) -> Trace:
        """§18 — has this requirement been implemented?"""
        return trace(self.doc, requirement_id)

    # -- asking (§16) -------------------------------------------------------

    def ask(self, limit: int | None = None) -> QuestionBatch:
        """Select the batch and word it, recording what was asked.

        The recording is the point: ``clarification.already_asked`` reads it
        back off the transcript, so Smith does not open every turn with the
        same five questions. There is no queue — the transcript *is* the record
        of what was asked, and confidence is the record of what was answered.
        """
        batch = self.open_questions(limit)
        if not batch:
            return QuestionBatch()
        if self.model is None:
            raise RuntimeError("Smith needs a model to word questions (§16)")
        worded = phrase(self.model, batch)
        self.conversation.append(
            "smith", worded.render(), refs=tuple(worded.artifacts),
            context={"kind": "clarification"},
        )
        return worded

    # -- one turn -----------------------------------------------------------

    def turn(
        self,
        text: str,
        *,
        preview: PreviewContext | dict | None = None,
        run_agents: bool = True,
    ) -> Turn:
        """One exchange. §114's twelve steps, for the ones that apply.

        The user's message is written to the transcript *before* anything is
        interpreted, so a turn that fails still leaves a record of what was
        asked for. A transcript that only contains successful turns is a
        transcript that cannot explain how the application got this way.
        """
        if isinstance(preview, dict):
            preview = resolve_preview(self.doc, **preview)

        anchors = list(preview.anchors) if preview else []
        user_msg = self.conversation.append(
            "user", text, refs=tuple(anchors),
            context={"preview": preview.describe()} if preview else {},
        )

        asked = self._last_asked()
        context = self.context_for(text, anchors=anchors)
        turn = Turn(user=user_msg, context=context,
                    state_before=self.state, state_after=self.state)

        if self.model is None:
            raise RuntimeError("Smith needs a model to interpret a turn")

        try:
            plan = interpret(
                self.model, context, self.doc, asked=asked, state=self.state,
            )
        except TurnRejected as exc:
            # Not repaired into something usable. The turn failed, the user is
            # told, and the Blueprint is untouched.
            turn.rejected = str(exc)
            turn.reply = (
                "I could not turn that into a change I am confident about, so I "
                "have not altered anything. Could you say it another way?"
            )
            turn.smith = self.conversation.append("smith", turn.reply)
            return turn

        turn.plan = plan
        turn.reply = plan.reply

        if not plan.actionable:
            # §17: below the clarification line, do not implement the affected
            # behaviour. Applying anyway "with a warning" is how a guess becomes
            # a fact nobody remembers agreeing to.
            turn.reply = plan.reply or (
                "I am not confident enough about what you mean to change the "
                "application on it. Can you tell me more?"
            )
            turn.smith = self.conversation.append("smith", turn.reply)
            return turn

        if plan.intent == "command":
            self._run_command(plan, turn)

        if plan.answers:
            turn.recorded = self._record_answers(plan, user_msg)

        if plan.proposals or (plan.intent == "change" and plan.anchors):
            turn.change = apply_change(
                self.blueprint,
                text,
                proposals=plan.proposals,
                anchors=self._impact_seeds(plan, preview),
                interpretation=plan.summary,
                executor=self.executor,
                app_root=self.app_root,
                run_agents=run_agents and self.executor is not None,
                regenerate=self.defined,
            )

        if plan.intent == "ask" and plan.anchors:
            first = plan.anchors[0]
            if first.startswith("REQ-"):
                turn.trace = self.trace(first)

        # §94, last: the machine moves on what the turn *did*, so a describe
        # that wrote no requirements does not claim the definition has started.
        if plan.intent != "command":
            event = plan.intent
            if event == "describe" and not (turn.change and turn.change.applied):
                event = ""
            elif event == "change" and not (turn.change and turn.change.applied):
                event = ""
            if event:
                # A modification made *at* a gate goes back through the state
                # that authored the thing being modified — §94's back-edge —
                # and then returns, because the user is still standing at the
                # gate. Walking back rather than staying put is what makes the
                # round trip visible in the transcript: the Blueprint records
                # that the definition was reopened, not merely edited in place.
                gate = self.state if self.state in GATES else ""
                self._advance(event)
                if gate:
                    self._walk((gate,))
        # §107 step 5-6: once nothing is left below the ask-the-user line, the
        # definition is no longer being clarified.
        if self.state == "CLARIFICATION" and turn.recorded:
            if not [q for q in clarification.candidates(self.doc) if q.blocking]:
                self._walk(("DEFINITION",))
        turn.state_after = self.state

        turn.smith = self.conversation.append(
            "smith", turn.reply, refs=tuple(plan.anchors),
            context={"intent": plan.intent},
        )
        return turn

    def explain(self, question: str, *, anchors: Sequence[str] = ()) -> str:
        """§7.27 — explain the application. Read-only."""
        if self.model is None:
            raise RuntimeError("Smith needs a model to explain")
        context = self.context_for(question, anchors=anchors)
        answer = explain_call(self.model, context, ", ".join(anchors) or "the application")
        self.conversation.append("user", question, refs=tuple(anchors))
        self.conversation.append("smith", answer, refs=tuple(anchors))
        return answer

    # -- §94: the state machine ---------------------------------------------

    @property
    def state(self) -> str:
        return self.doc.get("state", "DISCOVERY")

    @property
    def defined(self) -> bool:
        """Whether there is an application for §72 to regenerate.

        Derived from the document rather than read off ``state``. The obvious
        implementation — "is the state DISCOVERY or CLARIFICATION" — trusts a
        label, and the ATS fixture is the counterexample sitting in the repo: a
        complete application with eighteen pages and eight entities whose state
        is still DISCOVERY, because until the lifecycle was wired nothing ever
        transitioned it. Gating regeneration on that label stops a real
        application from ever rebuilding.

        Pages or entities, because those are what the projections need. A
        Blueprint holding only requirements has been described, not defined.
        """
        return bool(
            self.doc.get("pages")
            or (self.doc.get("data") or {}).get("entities")
        )

    def _advance(self, event: str) -> str:
        """Apply the one transition this (state, event) pair permits, if any.

        Looked up rather than decided. A turn cannot move the machine anywhere
        ``TURN_TRANSITIONS`` does not declare, so ``IllegalTransition`` is
        unreachable from here by construction — §94 puts the orchestration
        engine in charge of transitions, and this is Smith asking it rather
        than overruling it.
        """
        dst = TURN_TRANSITIONS.get((self.state, event))
        return transition(self.blueprint, dst) if dst else self.state

    def _walk(self, states: Iterable[str]) -> str:
        """Move through a sequence, stopping at the first step §94 refuses.

        Stopping rather than skipping ahead: a state the machine would not
        enter is a fact about the application, and jumping over it would make
        `state` describe a path that was not taken.
        """
        for dst in states:
            try:
                transition(self.blueprint, dst)
            except IllegalTransition:
                break
        return self.state

    # -- §107 steps 8-21 -----------------------------------------------------

    def _author(self, plan: list[str], user_request: str) -> RunReport:
        """Run a slice of the DAG, or say why there is nobody to run it."""
        if self.executor is None:
            raise RuntimeError(
                "Smith needs an executor to author a definition; agents are "
                "injected so orchestration stays testable without a model (§116)"
            )
        return run_dag(
            self.blueprint, self.executor, plan=plan, commit=False,
            user_request=user_request, app_root=self.app_root,
        )

    def define(self) -> RunReport:
        """§107 step 6 — author what the application *is*, and then stop.

        Stopping is the point. The domain description is two model calls and
        the rest of the definition is a dozen, and every one of the dozen
        reads what these two wrote. Elaborating a misread problem is not a
        cheaper mistake for having been thorough about it — it is a more
        expensive one, because the user who corrects the first sentence then
        pays for the fan-out a second time.

        Explicit rather than automatic. §107 has this follow clarification
        with no user act between, but running it as a side effect of someone
        answering a question would spend their money without asking. The
        deviation is the trigger, not the order.

        Parks at BLUEPRINT_REVIEW — §107 step 8's gate.
        """
        report = self._author(domain_nodes(), "define")
        self._walk(DEFINE_WALK)
        return report

    def approve(self) -> RunReport:
        """§25 / §107 steps 8-9 — accept the domain description, get the plan.

        One user act. §25 says approval "applies at meaningful product
        boundaries", not per property, so accepting authors the entities,
        pages, workflows and rules in one go and parks at PLAN_REVIEW — which
        is exactly §107 step 10's gate, waiting for the build authorisation.

        Refuses anywhere but the gate it belongs to. Approving from
        CLARIFICATION used to walk the machine to PLAN_REVIEW over a document
        with nothing in it: legal by §94, and an acceptance of nothing.
        """
        if self.state != "BLUEPRINT_REVIEW":
            raise IllegalTransition(
                f"the application is in {self.state}; the domain description "
                "is accepted from BLUEPRINT_REVIEW (§107 step 8)"
            )
        report = self._author(definition_nodes(), "approve")
        self._walk(APPROVE_WALK)
        return report

    def build(self, *, app_root: str | None = None) -> RunReport:
        """§107 steps 10-21 — run the whole DAG, not a sub-plan.

        This is what `Smith.turn` alone could never do. Every other path here
        computes an *incremental* plan (§72), and on an application that does
        not exist yet there is nothing to be incremental about: no artifact to
        anchor to, no impacted section, so an empty plan and a silent no-op.

        The state walk follows what actually completed rather than what was
        attempted. §94's sequence is a claim about the application, and
        asserting VERIFICATION because a run was requested — rather than
        because verification ran — would make the state a wish.
        """
        transition(self.blueprint, "IMPLEMENTATION")  # §107 step 10's gate
        if self.executor is None:
            raise RuntimeError(
                "Smith needs an executor to build; agents are injected so the "
                "orchestration stays testable without a model (§116)"
            )

        report = run_dag(
            self.blueprint, self.executor, plan=build_nodes(), commit=False,
            user_request="build", app_root=app_root or self.app_root,
        )

        done = set(report.completed)
        reached: list[str] = []
        for dst, gate in BUILD_WALK:
            if gate and gate not in done:
                break
            if dst != "IMPLEMENTATION":
                reached.append(dst)
        self._walk(reached)
        return report

    def export(self, package_root: str | Path) -> Path:
        """§83 — put the Blueprint beside the generated source.

        Honest about its limit: this writes ``blueprint.json`` into the package
        so the project can be re-imported (§4.6). The standalone source itself
        is what the projections and assembly wrote to ``app_root``; this does
        not archive or package it.
        """
        path = self.blueprint.export_to(package_root)
        self._walk(("EXPORT_DEPLOY",))
        return path

    # -- internals ----------------------------------------------------------

    def _run_command(self, plan: TurnPlan, turn: "Turn") -> None:
        """Dispatch a `command` turn (§107 steps 8, 10; §66, §83, §86).

        Every command either does something or says why it did not. The one
        thing none of them may do is nothing at all, which is what `command`
        used to mean: the intent was parsed, no branch handled it, and "build
        the app" got a confident reply and an untouched Blueprint.
        """
        turn.command = plan.command

        if plan.command == "status":
            turn.command_result = self.status()
            return

        if plan.command == "define":
            if self.executor is None:
                turn.command_result = {
                    "refused": "no executor is configured, so there is nothing "
                               "to delegate the authoring to",
                }
                return
            report = self.define()
            turn.run = report
            # Not `build_plan_summary`: at this gate the pages and workflows it
            # counts have deliberately not been authored yet, and a plan of
            # eight zeros reads as a failed run rather than as a gate.
            turn.domain_summary = domain_summary(self.doc)
            turn.command_result = {
                "completed": len(report.completed), "failed": len(report.failed),
                "blocked": len(report.blocked), "state": self.state,
            }
            return

        if plan.command == "approve":
            # Refuse with the reason rather than raise — same contract as
            # `build` below: the state machine saying no is an answer to give
            # the user, not a crash.
            if self.state != "BLUEPRINT_REVIEW":
                turn.command_result = {
                    "refused": (
                        f"the application is in {self.state}; the domain "
                        "description is accepted from BLUEPRINT_REVIEW (§107 "
                        "step 8). Draft it first."
                    ),
                }
                return
            if self.executor is None:
                turn.command_result = {
                    "refused": "no executor is configured, so there is nothing "
                               "to delegate the authoring to",
                }
                return
            turn.run = self.approve()
            turn.plan_summary = build_plan_summary(self.doc)
            turn.design_summary = design_summary(
                self.doc, references.paths(self.blueprint.output_dir))
            turn.command_result = {
                "approved": True, "state": self.state,
                "completed": len(turn.run.completed),
                "failed": len(turn.run.failed),
                "blocked": len(turn.run.blocked),
            }
            return

        if plan.command == "build":
            if self.executor is None:
                turn.command_result = {
                    "refused": "no executor is configured, so there is nothing "
                               "to delegate the build to",
                }
                return
            # §107 step 10 authorises the build *from* the plan-review gate.
            # Refuse with the reason rather than raise: the state machine
            # saying no is an answer to give the user, not a crash.
            if not can_transition(self.state, "IMPLEMENTATION"):
                turn.command_result = {
                    "refused": (
                        f"the application is in {self.state}; a build is "
                        "authorised from PLAN_REVIEW (§107 step 10). Draft the "
                        "definition and accept it first."
                    ),
                }
                return
            turn.run = self.build()
            turn.command_result = {
                "completed": len(turn.run.completed),
                "skipped": len(turn.run.skipped),
                "failed": len(turn.run.failed),
                "blocked": len(turn.run.blocked),
                "state": self.state,
            }
            return

        if plan.command == "preview":
            runtime = self.doc.get("runtime") or {}
            turn.command_result = (
                {"runtime": runtime, "state": self.state} if runtime else
                {"refused": "no preview runtime has been generated yet; "
                            "build the application first (§107 step 21)"}
            )
            return

        if plan.command == "export":
            if not self.app_root:
                turn.command_result = {
                    "refused": "export needs an app_root — the standalone "
                               "source the projections wrote (§83)",
                }
                return
            turn.command_result = {"exported": str(self.export(self.app_root))}
            return

        if plan.command == "deploy":
            # §86-89 exist as services, and this deliberately does not call
            # them. Deploying publishes an application to the internet under
            # the user's account: it is outward-facing, hard to reverse, and
            # needs credentials. A chat turn saying "ship it" is not the place
            # to decide that, so the command is recognised and refused with a
            # reason rather than either executed or silently ignored.
            turn.command_result = {
                "refused": "deployment is not driven from a conversational "
                           "turn: it publishes the application and needs "
                           "explicit authorisation and credentials (§86-89)",
            }
            return

    def _last_asked(self) -> list[clarification.Question]:
        """The batch Smith most recently asked, so answers can be bound to it."""
        asked = clarification.already_asked(self.conversation, turns=1)
        if not asked:
            return []
        return [q for q in clarification.candidates(self.doc) if q.artifact in asked]

    def _record_answers(
        self, plan: TurnPlan, message: Message,
    ) -> list[decision_log.RecordedDecision]:
        out: list[decision_log.RecordedDecision] = []
        for answer in plan.answers:
            out.append(decision_log.record(
                self.blueprint,
                artifact_id=answer["artifact"],
                decision=answer.get("decision", ""),
                reason=answer.get("reason", ""),
                message_id=message.id,
                delegated=bool(answer.get("delegated")),
            ))
        return out

    def _impact_seeds(
        self, plan: TurnPlan, preview: PreviewContext | None,
    ) -> list[str]:
        """What impact analysis starts from — what the turn *writes*.

        Deliberately not ``plan.anchors``. Anchors are the artifacts the
        request is *about*: everything Smith looked at to understand it. Seeding
        impact analysis with them says every one of them changed.

        Measured, on a real turn answering four clarification questions: the
        plan anchored nine artifacts across entities, rules, permissions and
        components, impact analysis reported 185 affected, and the incremental
        plan selected 21 of 21 nodes — a full rebuild, which is precisely what
        §72 exists to prevent.

        Answering a question is the clearest case. It settles an artifact's
        confidence and records a decision (§20); neither is something the
        generated application reads, so neither propagates. What propagates is
        a *proposal*, and ``change.analyse`` already derives those from the
        natural keys. A preview selection counts too, because the user pointed
        at a specific thing and asked for it to be different.
        """
        if preview and not preview.empty:
            return list(preview.subject)
        return []
