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
from typing import Any, Callable, Sequence

from services.blueprint.ids import IdAllocator, InvalidArtifactId, natural_key_for
from services.blueprint.orchestrator import graph_pool
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

    @property
    def ok(self) -> bool:
        return not self.rejected

    @property
    def intent(self) -> str:
        return self.plan.intent if self.plan else "unknown"


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
        turn = Turn(user=user_msg, context=context)

        if self.model is None:
            raise RuntimeError("Smith needs a model to interpret a turn")

        try:
            plan = interpret(self.model, context, self.doc, asked=asked)
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
            )

        if plan.intent == "ask" and plan.anchors:
            first = plan.anchors[0]
            if first.startswith("REQ-"):
                turn.trace = self.trace(first)

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

    # -- internals ----------------------------------------------------------

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
