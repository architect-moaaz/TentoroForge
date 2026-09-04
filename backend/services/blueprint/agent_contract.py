"""Agent output contract and capability boundaries (PRD §29, §30, §101).

Why this is the load-bearing brick
----------------------------------
The old platform accumulated ~150 post-generation repair passes because agents
wrote whatever they liked and something downstream had to fix it. §30 inverts
that: each agent declares what it *cannot* do, and when it needs a change
outside its domain it "must return a change request to Smith" rather than
making the change and hoping.

That only works if the boundary is enforced somewhere. This module is that
somewhere. An agent does not write files or mutate the Blueprint directly — it
returns an :class:`AgentResult`, and :func:`apply_agent_result` commits it
through :class:`BlueprintService`, refusing anything outside the agent's
declared ``writes``.

So ``sensitive_column_guard`` does not become a better pass. It stops being a
pass at all: the Page Design Agent cannot write ``data.entities``, so it cannot
expose a sensitive column in the first place.

Relationship to §29
-------------------
§29's example result reports ``artifacts`` as IDs the agent already produced.
Under §120 an agent cannot have produced them yet — nothing may mutate the
application without passing through the Blueprint. So the contract here is a
superset: agents send :class:`ArtifactProposal` bodies, and ``artifacts`` is
populated with allocated IDs *after* a successful apply. Every other §29 field
is carried verbatim.

Confidence (§17) is enforced, not advisory: a result below the clarification
threshold is refused rather than applied with a warning.
"""
from __future__ import annotations

import copy

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService

#: §17 decision policy. Mirrors AUTONOMY_BANDS in packages/schema/src/blueprint/ids.ts.
AUTO_DECIDE = 0.90
RECORD_ASSUMPTION = 0.70
ASK_USER = 0.40

#: Every writable Blueprint location. "data.entities" is addressed explicitly
#: because entities are nested under the ``data`` section.
WRITABLE_SECTIONS: frozenset[str] = frozenset(
    set(ARTIFACT_SECTIONS)
    | {"data.entities", "data.relationships", "data.constraints",
       "navigation", "designSystem", "security",
       "runtime", "database", "deployment", "product", "codeMap",
       "pageLayouts", "completeness"}
)


class CapabilityViolation(PermissionError):
    """An agent attempted a write outside its §30 boundary."""


class UnknownAgent(KeyError):
    pass


class ContractViolation(ValueError):
    """The result does not satisfy the §29 output contract."""


# ---------------------------------------------------------------------------
# §30 / §101 — capabilities
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentCapability:
    """What one agent may do.

    ``writes`` is the enforced boundary. ``tools`` is declared here for §101 but
    enforced by the MCP Gateway (§98) — this module governs Blueprint writes,
    not tool access, and should not pretend otherwise.
    """

    agent: str
    writes: frozenset[str]
    reads: frozenset[str] = frozenset({"*"})
    tools: frozenset[str] = frozenset()
    may_set_status: bool = True

    def can_write(self, section: str) -> bool:
        return section in self.writes

    def can_read(self, section: str) -> bool:
        return "*" in self.reads or section in self.reads


#: §101 — what each agent may read *beyond* what it writes.
#:
#: ``context_for`` already carries identity (application, product, version,
#: state) to everyone and adds each agent's own writable sections, because an
#: agent that cannot see what it wrote cannot update it idempotently. So these
#: are only the sections an agent genuinely *references*.
#:
#: Two reasons this is worth the care. The obvious one is cost: handing the
#: whole Blueprint to the pattern author was ~80k tokens a call for context it
#: could not act on, and scoping it cut that to ~20k. The better one is §30 —
#: an agent that cannot see a section cannot invent references into it, which
#: removes a class of defect instead of detecting it downstream.
#:
#: An agent absent from this table reads everything. That is correct for the
#: two that legitimately need the whole document — ``verification`` walks every
#: edge and ``memory`` derives from every section — and harmless for the
#: projections, which are deterministic code and never receive a prompt.
_READS: dict[str, set[str]] = {
    # Discovery: intent in, requirements out. Nothing designed yet exists.
    "requirement": set(),
    "domain_intelligence": {"requirements"},
    "product_analysis": {"requirements"},

    # Structure: modules and navigation over the pages that exist.
    "solution_architecture": {"requirements", "pages"},

    # Data: grounded in requirements, not in anybody's UI.
    "data_model": {"requirements"},

    # Design language: the product and what the UI already uses.
    "accessibility": {"requirements", "pages"},
    "figma_intelligence": {"requirements", "pages"},

    # §30 verbatim — page design may compose pages and select patterns, and may
    # NOT touch business rules, database schema, security rules or role
    # permissions. It still needs to *see* roles and entities to address a page
    # to a role and bind it to an entity; it cannot write either.
    # `designSources` is here so a page can say WHICH FRAME it is. The contract
    # already carries `pages[].figmaFrame` and `page_design` could already write
    # it — but the frames live in `designSources`, which this agent could not
    # see, so it was being asked to name a node id it had never been shown. The
    # field existed, the author had the pen, and the paper was missing.
    #
    # Read-only, and it stays that way: the extraction is evidence (§48), and an
    # agent that could edit what the design says could make the design agree
    # with the app it just invented.
    "page_design": {"requirements", "modules", "data", "designSystem",
                    "roles", "permissions", "designSources"},

    # Behaviour: what the business does, over the data it does it to.
    "workflow": {"requirements", "data", "pages", "businessRules", "roles"},
    "business_rules": {"requirements", "data", "workflows"},

    # §100 — permissions guard entities, pages and workflow execution.
    "security": {"requirements", "data", "pages", "workflows"},

    "integration": {"requirements"},

    # Endpoints are derived, not authored, but the derivation reads all of this.
    "api": {"requirements", "data", "database", "workflows", "pages",
            "widgets", "permissions"},

    # Tests are written against everything that claims to do something.
    "testing": {"requirements", "data", "pages", "apis", "workflows",
                "businessRules"},
}


def _cap(agent: str, writes: Iterable[str], tools: Iterable[str] = (), **kw) -> AgentCapability:
    kw.setdefault("reads", frozenset(_READS.get(agent, {"*"})))
    return AgentCapability(
        agent=agent, writes=frozenset(writes), tools=frozenset(tools), **kw
    )


#: The 18 agents of §27.
#:
#: Four of these have their tool grants spelled out in §101 (page_design,
#: figma_intelligence, database/data_model, deployment) and the Page Design
#: Agent has its full can/cannot list in §30 — those are transcribed. The rest
#: are derived from each agent's name in §27 under §30's principle that an
#: agent owns exactly one domain and requests changes outside it. They are a
#: starting point to argue with, not scripture.
AGENT_REGISTRY: dict[str, AgentCapability] = {
    "requirement": _cap("requirement", {"requirements", "product"}),
    "domain_intelligence": _cap("domain_intelligence", {"product"}),
    "product_analysis": _cap("product_analysis", {"product", "requirements"}),
    "solution_architecture": _cap("solution_architecture", {"modules", "navigation"}),
    # §30, verbatim: may compose pages, select patterns, define UI interactions,
    # use A2UI MCP, update UI-related Blueprint information. May NOT touch
    # business rules, database schema, security rules or role permissions.
    "page_design": _cap(
        "page_design",
        {"pages", "widgets", "navigation"},
        tools={"blueprint:read", "page_contract:read", "design_system:read",
               "mcp:a2ui"},
    ),
    # §20 + §23. Derived by deterministic code rather than authored, but it
    # still needs a declared owner: §74 routes a repair task to whoever may
    # write the section, and a section nobody owns is one no finding can ever
    # be closed against.
    "memory": _cap(
        "memory",
        {"decisions", "completeness"},
        reads={"*"},
        tools={"blueprint:read"},
    ),
    # §34 — A2UI as the composition authority, one page at a time. It composes
    # against the real component catalog, so what it authors is renderable by
    # construction rather than by a repair pass.
    "a2ui_pages": _cap(
        "a2ui_pages",
        {"pageLayouts"},
        reads={"requirements", "pages", "data", "widgets", "roles",
               "permissions", "designSystem", "navigation",
               "modules", "workflows", "apis"},
        tools={"blueprint:read", "page_contract:read", "design_system:read",
               "component_catalog:read", "mcp:a2ui"},
    ),
    "data_model": _cap(
        "data_model",
        {"data.entities", "data.relationships", "data.constraints", "database"},
        tools={"blueprint:data", "schema:write", "migration:write"},
    ),
    "api": _cap("api", {"apis"}),
    "backend": _cap("backend", {"apis", "codeMap"}),
    "frontend": _cap("frontend", {"components", "codeMap"}),
    "workflow": _cap("workflow", {"workflows"}),
    "business_rules": _cap("business_rules", {"businessRules"}),
    "integration": _cap("integration", {"integrations"}),
    "security": _cap("security", {"security", "roles", "permissions"}),
    "testing": _cap("testing", {"tests"}),
    "accessibility": _cap("accessibility", {"designSystem"}),
    "build": _cap("build", {"runtime"}),
    # Verification reports divergence; it never edits an artifact's content.
    "verification": _cap("verification", set(), may_set_status=True),
    "deployment": _cap(
        "deployment", {"deployment"},
        tools={"build:approved", "deploy:config", "vercel"},
    ),
    # Smith itself (§6–§8). Not one of §27's eighteen — those are the
    # specialists Smith delegates to — but registered here on purpose, so that
    # Smith's writes are checked by the same `check_capability` as everyone
    # else's rather than trusted because of who is asking.
    #
    # The surface is the *product definition*: what the application is. That is
    # deliberately wide, because a conversation that can only file requirements
    # cannot answer "make the candidate table compact" without a full DAG
    # round-trip.
    #
    # Four things are excluded, and not because they are risky — because a
    # direct write to them cannot be correct:
    #
    #   apis             derived from entities + workflows + widgets by
    #                    api_derivation; anything authored here is overwritten
    #                    on the next derivation, so writing it is a lie.
    #   pageLayouts      validated against the real component catalog, which is
    #                    injected into the a2ui_pages prompt and not into
    #                    Smith's. Authoring blind would fail
    #                    check_page_layout anyway.
    #   codeMap          projection output. A model asked for file paths
    #                    produces plausible ones, and Blueprint↔Implementation
    #                    then goes green against files nobody wrote.
    #   runtime,         infrastructure and derivation (§23, §56–§62). Owned by
    #   database,        deterministic services; a conversational override
    #   deployment,      would be §116 inverted.
    #   completeness
    "smith": _cap(
        "smith",
        {"requirements", "decisions", "product", "modules", "navigation",
         "pages", "components", "widgets", "data.entities",
         "data.relationships", "data.constraints", "workflows",
         "businessRules", "integrations", "roles", "permissions", "security",
         "designSystem"},
        tools={"blueprint:read", "blueprint:write"},
    ),
    # §31/§34 — the Figma Intelligence Agent contributes evidence, not design
    # decisions; it may not author pages.
    "figma_intelligence": _cap(
        "figma_intelligence",
        {"requirements", "designSystem"},
        tools={"mcp:figma", "design:extract", "blueprint:evidence"},
    ),
}


# ---------------------------------------------------------------------------
# §29 — the structured result
# ---------------------------------------------------------------------------

@dataclass
class ArtifactProposal:
    """One artifact an agent proposes to add or update."""

    section: str
    natural_key: str
    body: dict[str, Any]


@dataclass
class ChangeRequest:
    """§30 — what an agent returns instead of reaching outside its domain."""

    section: str
    reason: str
    proposed: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """The §29 structured output contract."""

    task_id: str
    agent: str
    status: str = "completed"  # completed | blocked | failed
    proposals: list[ArtifactProposal] = field(default_factory=list)
    requirements_satisfied: list[str] = field(default_factory=list)
    tests_generated: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    change_requests: list[ChangeRequest] = field(default_factory=list)
    confidence: float = 1.0
    #: Populated by apply_agent_result — the IDs actually allocated.
    artifacts: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.status not in ("completed", "blocked", "failed"):
            raise ContractViolation(f"{self.status!r} is not a valid agent status")
        if not 0.0 <= self.confidence <= 1.0:
            raise ContractViolation("confidence must be within 0..1")
        if not self.task_id:
            raise ContractViolation("task_id is required — §103 requires retryable tasks")
        for p in self.proposals:
            if p.section not in WRITABLE_SECTIONS:
                raise ContractViolation(f"{p.section!r} is not a writable Blueprint section")
            if not p.natural_key:
                raise ContractViolation(
                    "every proposal needs a natural_key, or re-running the agent "
                    "would duplicate its artifacts instead of updating them"
                )


@dataclass
class AgentApplication:
    """Outcome of committing an :class:`AgentResult` through the Blueprint."""

    applied: bool
    result: AgentResult
    artifacts: list[str] = field(default_factory=list)
    change_requests: list[ChangeRequest] = field(default_factory=list)
    needs_clarification: bool = False
    recorded_assumptions: list[str] = field(default_factory=list)
    reason: str = ""


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

def capability_for(agent: str) -> AgentCapability:
    try:
        return AGENT_REGISTRY[agent]
    except KeyError as exc:
        raise UnknownAgent(
            f"{agent!r} is not a registered agent; §28 forbids an uncontrolled swarm"
        ) from exc


def check_capability(result: AgentResult) -> None:
    """Raise if the result writes outside the agent's §30 boundary.

    Deliberately raises rather than dropping the offending proposal. A silently
    discarded write is how you get an application that looks generated but
    isn't — the same failure class the repair chain existed to paper over.
    """
    cap = capability_for(result.agent)
    for p in result.proposals:
        if not cap.can_write(p.section):
            raise CapabilityViolation(
                f"agent {result.agent!r} may not write {p.section!r} "
                f"(§30). It writes: {', '.join(sorted(cap.writes)) or '<nothing>'}. "
                f"Return a ChangeRequest to Smith instead."
            )


class InvalidPatternTemplate(ValueError):
    """A2UI proposed a template the component registry cannot render."""


def _blamed(exc: Exception, svc: Any) -> Exception:
    """The same failure, saying whose fault it is.

    THE WHOLE DOCUMENT IS VALIDATED ON EVERY COMMIT, so a Blueprint that is
    already invalid refuses every write — and the error names the section that
    is broken, which is rarely the section being written. It reads exactly like
    a rejected proposal.

    Measured: a 50-page application carried `runtime.placeholders`, an empty
    list left by a since-removed producer. Every write to that project had
    failed ever since, and a composition that was demonstrably valid — it
    passed `check_pattern_templates` — was reported refused. Two rounds of
    investigation went into the composition before anyone validated the
    untouched document, which fails in one line.

    Nothing is repaired here and nothing is loosened. The document is still
    invalid and the write still refused; the message stops pointing at the
    wrong thing.
    """
    from services.blueprint.service import BlueprintInvalid

    if not isinstance(exc, BlueprintInvalid):
        return exc
    try:
        svc.validate()          # the restored document, as it was before
    except BlueprintInvalid as prior:
        # `BlueprintInvalid` takes the error LIST, not a message — its own
        # __init__ builds the prose. Handing it a string makes each character
        # an error, which is a 310-error report of one sentence.
        return BlueprintInvalid([
            "this Blueprint was ALREADY invalid before the change, so every "
            "write to it fails. Nothing about the proposed change caused it.",
            *list(getattr(prior, "errors", None) or [str(prior)]),
        ])
    except Exception:  # noqa: BLE001 — never mask the original failure
        return exc
    return exc


def check_pattern_templates(result: AgentResult,
                            doc: dict | None = None) -> None:
    """Reject templates that do not compose against the real catalog.

    The alternative — accepting them and repairing later — is what produced the
    component library's preprocessors: `columns` folded from null, `header`
    aliased to `label`, unknown props stripped. Each of those absorbs a model
    mistake at render time and hides it. A template that names a component that
    does not exist, or breaks a container's positional contract, is rejected
    here so the agent is asked again rather than the schema loosened.
    """
    proposals = [p for p in result.proposals if p.section == "pageLayouts"]
    if not proposals:
        return

    from services.blueprint.page_planner import (
        load_catalog, validate_props, validate_template,
    )

    catalog = load_catalog()
    problems: list[str] = []
    for proposal in proposals:
        # Structure *and* props. Checking only structure let a bad prop value
        # through the gate and commit, so it surfaced at projection instead —
        # long after the retry that could have fixed it. `variant: "ghost"` on
        # a Table rowAction passed apply and failed the build.
        errors = validate_template(proposal.body, catalog)
        errors += validate_props({"root": proposal.body.get("root")}, catalog)
        if errors:
            pattern = proposal.body.get("pattern") or proposal.body.get("page", "?")
            problems.extend(f"{pattern}: {e}" for e in errors)
    # WOULD IT DO ANYTHING. The checks above ask whether the tree renders; this
    # asks whether it works. A Button with a label and no action renders
    # perfectly and does nothing, an action naming a workflow that does not
    # exist answers "Workflow not found" on click, and a binding with no source
    # renders its own template text — all valid trees, all shipped, all found
    # by somebody using the application.
    #
    # Raised here rather than reported later because this is the one place the
    # composer can still be told. §73 exists to close the loop and the
    # orchestrator already re-asks a node when its output is refused; a control
    # with no action is a page composed wrongly, not a page to repair.
    #
    # Needs the doc for the workflow list, and is skipped without one — a
    # caller that cannot say which workflows exist would otherwise reject every
    # real binding as invented.
    if doc is not None:
        from services.blueprint.functional_completeness import (
            functional_findings,
        )

        pages = {p.get("id"): p for p in (doc.get("pages") or [])}
        for proposal in proposals:
            page_id = proposal.body.get("page")
            findings = functional_findings({
                "pages": [pages.get(page_id) or {"id": page_id, "route": page_id}],
                "workflows": doc.get("workflows") or [],
                "pageLayouts": [proposal.body],
            })
            problems.extend(f["detail"] for f in findings)

    if problems:
        raise InvalidPatternTemplate("; ".join(problems[:6]))


def apply_agent_result(
    svc: BlueprintService,
    result: AgentResult,
    *,
    commit: bool = False,
    user_request: str = "",
) -> AgentApplication:
    """Commit an agent's output through the Blueprint (§115, §120).

    Refuses, in order:

    * a malformed result (§29),
    * a write outside the agent's declared domain (§30),
    * a result whose confidence sits below the clarification threshold (§17) —
      "do not implement the affected behavior without clarification" is a
      refusal, not a warning.

    Applying the same result twice is a no-op beyond the first, because every
    proposal carries a natural key and upsert is idempotent — which is what
    §103's "tasks must be retryable" requires in practice.
    """
    result.validate()
    check_capability(result)
    check_pattern_templates(result, svc.doc)

    # WHO DESIGNED THIS SCREEN, RECORDED WHERE EVERY LAYOUT PASSES.
    #
    # Two composers write pageLayouts — A2UI, and the LLM page author that runs
    # when A2UI declines or fails — and they emit the same shape. So a page
    # composed well and a page nobody could compose properly were
    # indistinguishable in the Blueprint, answerable only from run logs that
    # age out. The same argument removed the deterministic pattern stub: a
    # stubbed page and a designed one looking alike was judged unacceptable.
    #
    # `_compose_via_a2ui` stamps its own; anything arriving here unstamped came
    # from an agent, and this is the one place every layout passes through.
    for proposal in result.proposals:
        if proposal.section == "pageLayouts" and not proposal.body.get("composedBy"):
            proposal.body["composedBy"] = "agent"

    if result.status != "completed":
        return AgentApplication(
            applied=False, result=result, change_requests=list(result.change_requests),
            reason=f"agent reported status {result.status!r}",
        )

    if result.confidence < ASK_USER:
        # WHAT IT WANTS TO BE TOLD, NOT JUST THAT IT STOPPED. §17's band is
        # named ASK_USER, and the only thing recorded here was the arithmetic:
        # "confidence 0.10 is below the §17 clarification threshold of 0.40".
        # A build died on that line, thirteen nodes were skipped, and the user
        # was shown a number — while the agent's `change_requests` held the
        # actual questions, in its own words, and were dropped on the floor.
        #
        # Measured on a real EMR build: the agent asked whether paying a
        # supplier invoice should also post an expense transaction, since
        # REQ-019 and REQ-023/024 disagree and answering it either way changes
        # the schema. That is a question a person answers in one sentence, and
        # it never reached them.
        #
        # The questions travel in `reason` because that is what the ledger,
        # `RunReport.blocked_because` and the chat surface all read. They are
        # already on `change_requests` for a caller that wants them structured.
        asks = [
            str(getattr(cr, "reason", "") or "").strip()
            for cr in result.change_requests
        ]
        asks = [a for a in asks if a]
        if not asks:
            # Nothing to ask means nothing to answer, and the run stops on a
            # number the user cannot act on. Say that plainly rather than
            # implying a question exists.
            asks = [str(i) for i in (result.issues or [])][:2]
        detail = (" — needs: " + " | ".join(a[:400] for a in asks[:3])) if asks else (
            " — and raised no question, so there is nothing to answer"
        )
        return AgentApplication(
            applied=False, result=result, change_requests=list(result.change_requests),
            needs_clarification=True,
            reason=(
                f"confidence {result.confidence:.2f} is below the §17 clarification "
                f"threshold of {ASK_USER:.2f}{detail}"
            ),
        )

    before = svc.snapshot() if commit else None

    # Pass 1 — allocate every ID-bearing proposal's id up front, so proposals
    # in the same batch can reference each other. An agent proposing entities
    # and the relationships between them cannot cite an id that does not exist
    # yet, and inventing one is forbidden (§12/§116) — so it cites a natural
    # key or a name, and this is where that closes.
    from services.blueprint.service import (
        ARTIFACT_SECTIONS, resolve_batch_references,
    )
    from services.blueprint.ids import IdAllocator

    allocated: dict[str, str] = {}
    with IdAllocator.session(output_dir=svc.output_dir) as alloc:
        for p in result.proposals:
            prefix = (
                "ENTITY" if p.section == "data.entities"
                else ARTIFACT_SECTIONS.get(p.section)
            )
            if not prefix:
                continue
            artifact_id = p.body.get("id") or alloc.allocate(prefix, p.natural_key)
            allocated[p.natural_key] = artifact_id
            # Agents cite each other by the human name far more often than by
            # the natural key, so accept both.
            for alias in (p.body.get("name"), p.body.get("route"),
                          p.body.get("table")):
                if isinstance(alias, str) and alias:
                    allocated.setdefault(alias, artifact_id)

    resolve_batch_references(
        [(p.section, p.natural_key, p.body) for p in result.proposals], allocated
    )

    # Upsert mutates the shared document and `validate` raises after it, so a
    # rejected proposal used to stay in memory: the next node validated against
    # someone else's bad artifact and failed for it. A fresh run lost fourteen
    # nodes that way — `page_contracts` proposed a widget with `unit: "jobs"`,
    # was rightly rejected, and `security`, which writes no widgets at all,
    # failed on the same five errors moments later because it shared the
    # document. The forecast then counted 29 pages that were never saved.
    #
    # Level waves made this load-bearing rather than causing it: siblings in a
    # wave share one document, so a rejection reaches further than the node
    # that earned it. Rejecting has to leave the Blueprint exactly as it was.
    snapshot = copy.deepcopy(svc.doc)
    try:
        ids: list[str] = []
        for p in result.proposals:
            art = svc.upsert(p.section, p.body, natural_key=p.natural_key)
            # Singleton sections (database, security, …) carry no id — there is
            # nothing to reference, so there is nothing to collect.
            if art.get("id"):
                ids.append(art["id"])
        result.artifacts = ids

        # §17 middle band: proceed, but the assumption must be on the record.
        recorded: list[str] = []
        if result.confidence < AUTO_DECIDE and result.assumptions:
            recorded = list(result.assumptions)

        svc.validate()
    except Exception as exc:
        # Restored in place: callers and the orchestrator hold this dict, so
        # rebinding the attribute would leave them on the poisoned copy.
        svc.doc.clear()
        svc.doc.update(snapshot)
        raise _blamed(exc, svc) from exc

    if commit:
        svc.commit(
            user_request=user_request or f"{result.agent}:{result.task_id}",
            smith_interpretation="; ".join(recorded),
            before=before,
            affected=ids,
            tests=result.tests_generated,
        )
    else:
        svc.save()

    return AgentApplication(
        applied=True, result=result, artifacts=ids,
        change_requests=list(result.change_requests),
        recorded_assumptions=recorded,
    )
