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
import logging
import re

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService

logger = logging.getLogger(__name__)

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
       "pageLayouts", "pageCode", "nativeCode", "composition", "completeness",
       "domainReference", "mobile"}
)


class CapabilityViolation(PermissionError):
    """An agent attempted a write outside its §30 boundary."""


class UnknownAgent(KeyError):
    pass


class AuthorRefusal(ValueError):
    """An agent's proposal refused by a check on what it wrote — an outcome the
    author is asked again about, never a crash. Every such check raises a
    subclass, so a caller catching this cannot miss a new one: the entity-field
    and page-content checks were added on 2026-09-19 and neither was in the
    orchestrator's retry list, which is how InvalidBusinessRule once took a
    whole build down.

    `settle`, when a check gives one, is the SAFE WAY THROUGH: what the build
    does instead of stopping when the author's attempts run out. Called with
    no arguments, it changes the refused reply so that what ships is still
    correct and secure, only less complete — a restricted page nobody was
    named for becomes the administrator's, a chart nobody could cite is kept
    uncited — marks its check as settled on the reply (`settle_check`), and
    returns what it settled for, in a line each, for the person and for Smith.
    A check offers one only when EVERY fault it is raising has one; a fault
    that would ship something wrong or open stays a refusal. Earlier attempts
    are refused as before: the author is asked first, and only the last
    attempt is settled (`orchestrator._apply_subject`). Four builds died on a
    refusal whose own message stated the safe answer (2026-10-20)."""

    def __init__(self, *args: Any, settle: "Callable[[], list[str]] | None" = None) -> None:
        super().__init__(*args)
        self.settle = settle


class SeveralRefusals(AuthorRefusal):
    """More than one check refused the same reply: all of them, together, so
    the author mends every fault in one attempt. Its safe way through is
    every check's own, taken in turn — offered only when each has one."""

    def __init__(self, refusals: list[AuthorRefusal]) -> None:
        settles = [getattr(r, "settle", None) for r in refusals]

        def settle() -> list[str]:
            said: list[str] = []
            for fn in settles:
                said += list(fn() or [])
            return said
        super().__init__("\n".join(f"{type(r).__name__}: {r}" for r in refusals),
                         settle=settle if all(callable(f) for f in settles) else None)
        self.refusals = refusals


def settle_check(result: "AgentResult", check: str) -> None:
    """Mark `check` as settled on this reply: its safe way through was taken,
    so the reply is applied without it."""
    done = set(getattr(result, "settled_checks", None) or ())
    done.add(check)
    try:
        result.settled_checks = done
    except AttributeError:  # pragma: no cover — a frozen result has no room for it
        pass


def _settled(result: "AgentResult", check: str) -> bool:
    return check in (getattr(result, "settled_checks", None) or ())


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
    "product_analysis": {"requirements", "domainReference"},

    # Structure: modules and navigation over the pages that exist.
    # `designSources` because a connected design DRAWS the navigation — its
    # sidebar is the same subtree on every screen — and the agent that authors
    # `navigation.tree` could not see it, so every Figma app got the generic
    # sidebar with the design's own rail rendered inside each page (§48).
    "solution_architecture": {"requirements", "pages", "designSources", "domainReference", "mobile"},

    # Data: grounded in requirements, not in anybody's UI — and in what a
    # practitioner expects such a product to keep (`domainReference`).
    "data_model": {"requirements", "domainReference"},

    # Design language: the product and what the UI already uses.
    "accessibility": {"requirements", "pages", "mobile"},
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
                    "roles", "permissions", "designSources",
                    # The app flows are the screens' and the processes'
                    # paths: who moves where, by which process (`flows`) —
                    # written once the roles are (`security`).
                    "workflows", "security", "domainReference"},

    # Behaviour: what the business does, over the data it does it to.
    "workflow": {"requirements", "data", "pages", "businessRules", "roles", "domainReference", "integrations"},
    "business_rules": {"requirements", "data", "workflows", "domainReference"},

    # The analytics each page carries, over the data the pages show and the
    # processes that move it — the states a workflow changes are what a
    # dashboard counts.
    "analytics": {"requirements", "product", "data", "pages", "roles",
                  "workflows", "security", "domainReference"},

    # §100 — permissions guard entities, pages and workflow execution.
    "security": {"requirements", "data", "pages", "workflows", "integrations", "domainReference"},

    "integration": {"requirements", "domainReference"},

    # Endpoints are derived, not authored, but the derivation reads all of this.
    "api": {"requirements", "data", "database", "workflows", "pages",
            "widgets", "permissions"},


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
    # The domain reference: what a practitioner expects of such a product,
    # written before the model and held to by every model node.
    "domain_intelligence": _cap("domain_intelligence", {"domainReference"}),
    "product_analysis": _cap("product_analysis", {"product", "requirements", "mobile"}),
    "solution_architecture": _cap("solution_architecture", {"modules", "navigation"}),
    # §30, verbatim: may compose pages, select patterns, define UI interactions,
    # use A2UI MCP, update UI-related Blueprint information. May NOT touch
    # business rules, database schema, security rules or role permissions.
    "page_design": _cap(
        "page_design",
        {"pages", "navigation", "flows"},
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
               "modules", "workflows", "apis", "composition"},
        tools={"blueprint:read", "page_contract:read", "design_system:read",
               "component_catalog:read", "mcp:a2ui"},
    ),
    # §34 — every page the build lays out, from the page's own contract
    # (`template_page`) or its drawn frame. Deterministic: no model, no tools.
    "page_template": _cap(
        "page_template",
        {"pageLayouts"},
        reads={"pages", "data", "workflows", "security", "designSources"},
        tools={"blueprint:read"},
    ),
    # §34 — the whole app's direction, once: `composition.vision` and its
    # conventions. No model output reaches a page without passing through them.
    "ui_director": _cap(
        "ui_director",
        {"composition"},
        tools={"blueprint:read", "design_system:read"},
    ),
    # §34 — each page written as React against the typed app SDK. Its tool is
    # the compiler: a page is type-checked before it is proposed.
    "ui_engineer": _cap(
        "ui_engineer",
        {"pageCode"},
        tools={"blueprint:read", "page_contract:read", "design_system:read",
               "sdk:read", "tsc:check"},
    ),
    # One native screen per page, written as React Native against the native SDK
    # and kit, beside `ui_engineer`'s web page. It writes `nativeCode` and
    # nothing else, and only for an application whose `mobile.native` is on.
    "native_engineer": _cap(
        "native_engineer",
        {"nativeCode"},
        tools={"blueprint:read", "page_contract:read", "design_system:read",
               "sdk:read", "tsc:check"},
    ),
    "data_model": _cap(
        "data_model",
        {"data.entities", "data.relationships", "data.constraints", "database"},
        tools={"blueprint:data", "schema:write", "migration:write"},
    ),
    "api": _cap("api", {"apis"}),
    # The KPIs, charts and breakdowns attached to each page, each a query of
    # measures by dimensions over declared columns. Split from page design so
    # the analytics are designed with every page and every entity in view —
    # a dashboard summarises what the other pages hold.
    "analytics": _cap("analytics", {"widgets"}, tools={"blueprint:read"}),
    "backend": _cap("backend", {"apis", "codeMap"}),
    "frontend": _cap("frontend", {"components", "codeMap"}),
    "workflow": _cap("workflow", {"workflows"}),
    "business_rules": _cap("business_rules", {"businessRules"}),
    "integration": _cap("integration", {"integrations"}),
    "security": _cap("security", {"security", "roles", "permissions"}),
    "accessibility": _cap("accessibility", {"designSystem"}),
    "build": _cap("build", {"runtime"}),
    # Verification reports divergence; it never edits an artifact's content.
    "verification": _cap("verification", set(), may_set_status=True),
    # The observer (§73's loop, closed at the node). Judges every agent
    # node's outcome as it lands and commands the repair — which the owning
    # agent authors. Like verification it may flag and write nothing: an
    # observer that patched a page directly would be a second author with no
    # §30 boundary.
    "observer": _cap("observer", set(), may_set_status=True),
    # §73 for the rendered page: looks at each coded page as it renders and
    # sends the ones that fall short back to the UI engineer, who rewrites
    # them. Writes nothing itself — the rewrite is the engineer's.
    "page_reviewer": _cap("page_reviewer", set(), may_set_status=True),
    # §27's test agent. Registered because §27 names it; no node runs it now —
    # the declarations it wrote were never written out or run (see the DAG).
    "testing": _cap("testing", {"tests"}),
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
    #   pageLayouts      laid out from each page's contract by `page_template`;
    #   composition      the catalog is not in Smith's prompt, so authoring
    #                    blind would fail check_pattern_templates anyway.
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
         "designSystem", "domainReference"},
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
    #: Checks whose safe way through was taken on this reply (`AuthorRefusal.settle`).
    settled_checks: set[str] = field(default_factory=set)

    def validate(self) -> None:
        if self.status not in ("completed", "blocked", "failed"):
            raise ContractViolation(f"{self.status!r} is not a valid agent status")
        if not 0.0 <= self.confidence <= 1.0:
            raise ContractViolation("confidence must be within 0..1")
        if not self.task_id:
            raise ContractViolation("task_id is required — §103 requires retryable tasks")
        for p in self.proposals:
            if p.section not in WRITABLE_SECTIONS:
                # SAY WHAT WOULD HAVE BEEN RIGHT. `product.capabilities` is
                # the shape this takes live (UAT, 2026-09-18): the agent
                # addressed a field INSIDE a section it may write, and the
                # refusal named neither the section that does exist nor the
                # ones that do. A retry told only that its answer was wrong
                # has nothing to change.
                parent = p.section.split(".")[0] if "." in p.section else ""
                hint = (f" — write {parent!r} and put {p.section.split('.', 1)[1]!r} "
                        f"inside its body" if parent in WRITABLE_SECTIONS else
                        f" — the writable sections are: "
                        f"{', '.join(sorted(WRITABLE_SECTIONS))}")
                raise ContractViolation(
                    f"{p.section!r} is not a writable Blueprint section{hint}")
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


class InvalidWorkflowStep(AuthorRefusal):
    """A proposed workflow uses a step the node catalog does not offer, or
    leaves a node's declared configuration empty."""


#: The comparisons a workflow `where` value may name — the engine's `_OPS`.
WHERE_COMPARISONS = frozenset({"ne", "neq", "not", "!=", "gt", ">", "gte", ">=", "lt", "<",
                               "lte", "<=", "in", "notIn", "nin"})


def check_workflow_steps(result: "AgentResult", doc: dict | None = None,
                         mcp_servers: list[dict] | None = None,
                         api_refs: list[dict] | None = None) -> None:
    """Reject workflows whose steps are not configured catalog nodes.

    The same argument as :func:`check_pattern_templates`: accepting a step
    whose config the engine cannot execute and repairing it later is how the
    old chain grew its regeneration passes. A step is a node from the catalog
    carrying what that node declares it needs; anything else is refused here,
    with the missing keys named, so the agent is asked again.
    """
    proposals = [p for p in result.proposals if p.section == "workflows"]
    if not proposals or _settled(result, "check_workflow_steps"):
        return

    from services.catalog import workflow_nodes

    catalog = workflow_nodes()
    problems: list[str] = []
    for proposal in proposals:
        name = proposal.body.get("name") or proposal.natural_key
        problems.extend(f"{name}/{e}" for e in catalog.workflow_errors(proposal.body))
    # A LOOP'S STEPS ARE STEPS: its shape, then each inner action against the
    # catalog like any other, then (below) every check on the laid-out body.
    from services.blueprint.functional_completeness import loop_step_errors, with_loop_bodies
    for proposal in proposals:
        problems.extend(loop_step_errors(proposal.body))
        name = proposal.body.get("name") or proposal.natural_key
        for st in proposal.body.get("steps") or []:
            cfg = (st or {}).get("config") or {} if isinstance(st, dict) else {}
            if cfg.get("actionType") != "for_each":
                continue
            for inner in cfg.get("steps") or []:
                if isinstance(inner, dict) and isinstance(inner.get("config"), dict):
                    problems.extend(f"{name}/{st.get('key')}/{inner.get('key')}: {e}" for e in
                                    catalog.step_errors({"type": "action", "config": inner["config"]}))
    # A TOOL STEP NAMES A SERVER THAT EXISTS, A TOOL IT HAS, AND ITS INPUTS.
    from services.blueprint.mcp_catalog import workflow_errors as mcp_errors
    for proposal in proposals:
        problems.extend(mcp_errors(with_loop_bodies(proposal.body), mcp_servers))
    # A CALL TO A DOCUMENTED SERVICE IS THE CALL ITS DOCUMENTATION DESCRIBES:
    # an endpoint it has, fields it takes and answers with, signed its way.
    from services.blueprint.api_reference import workflow_errors as api_errors
    for proposal in proposals:
        problems.extend(api_errors(with_loop_bodies(proposal.body), api_refs or []))
    # A LOOKUP THE ENGINE CAN READ. `where` maps a field to a value (equals)
    # or to ONE comparison: `{"id": {"ne": "{{customer.id}}"}}`. ToroCommerce
    # wrote `"id__neq"` and `{"ne": …}` with nothing to read either: the first
    # was no column, the second reached Postgres as "[object Object]".
    for proposal in proposals:
        name = proposal.body.get("name") or proposal.natural_key
        for st in with_loop_bodies(proposal.body).get("steps") or []:
            where = ((st or {}).get("config") or {}).get("where") if isinstance(st, dict) else None
            for field, value in (where.items() if isinstance(where, dict) else ()):
                bad = re.search(r"__(ne|neq|not|gt|gte|lt|lte|in|nin|notin|like)$", str(field), re.I)
                # Several comparisons on one field are ANDed — a range is
                # `{"gte": from, "lte": to}`.
                odd = isinstance(value, dict) and not (value and all(k in WHERE_COMPARISONS for k in value))
                if bad or odd:
                    problems.append(
                        f"{name}/{st.get('key')}: where {field!r} — write a comparison as "
                        f"{{\"<field>\": {{\"ne\": <value>}}}} (ne, gt, gte, lt, lte, in, notIn; several on one field "
                        "are ANDed, a range is {{\"gte\": from, \"lte\": to}}); a field alone with a value means equals")
    # WHAT AN END HANDS BACK IS DECLARED, SMALL, AND SOMEWHERE. `reply` is a
    # map of names to templates; `redirect` is a route of this application or
    # a template over a step's output — never free prose, never on a refused
    # end (a refusal is told, not followed).
    for proposal in proposals:
        name = proposal.body.get("name") or proposal.natural_key
        for st in with_loop_bodies(proposal.body).get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") if isinstance(st.get("config"), dict) else {}
            if "reply" not in cfg and "redirect" not in cfg:
                continue
            key = st.get("key") or st.get("id")
            if str(st.get("type") or "") not in ("end", "end_event"):
                problems.append(f"{name}/{key}: `reply` and `redirect` belong on an `end` step")
                continue
            if cfg.get("refused") is True:
                problems.append(f"{name}/{key}: a refused end tells the person why; it does not reply or redirect")
            if "reply" in cfg and not isinstance(cfg.get("reply"), dict):
                problems.append(f"{name}/{key}: `reply` maps names to values (`{{\"url\": \"{{{{checkout.url}}}}\"}}`)")
            red = cfg.get("redirect")
            if "redirect" in cfg and not (isinstance(red, str) and (red.startswith("/") or "{{" in red)):
                problems.append(f"{name}/{key}: `redirect` is a route of this application (`/orders/{{{{insert_order.id}}}}`) "
                                "or a template over a step's output (`{{{{checkout.url}}}}`)")
    # WOULD THE ENGINE RUN IT. A step whose condition the engine's parser
    # refuses, a function the engine lacks, a template naming what the engine
    # never holds — each is a workflow the author can fix now and nobody can
    # fix later. Checked here, at the author, never at the pages that bind it.
    from services.blueprint.functional_completeness import authoring_findings
    problems.extend(f["detail"] for f in authoring_findings(
        {"workflows": [p.body for p in proposals], "businessRules": [],
         "data": (doc or {}).get("data") or {}}))
    if problems:
        raise InvalidWorkflowStep(_all_of(problems),
                                  settle=_process_off(result, proposals, problems, "check_workflow_steps"))


def _process_off(result: "AgentResult", proposals: list, problems: list[str], check: str) -> "Callable[[], list[str]]":
    """The safe way through for a process the author could not get right:
    SHIPPED CLOSED. A fault in its steps makes it a process whose one step
    refuses with "not available yet" — its button says so, nothing is done
    wrongly; a fault in its trigger alone switches the automation off. A
    fault that names no process closes every process of the reply. The
    after-build fixing works on each (`settled.json`)."""
    def name_of(p) -> str:
        return str((p.body or {}).get("name") or p.natural_key)

    steps: dict[int, Any] = {}
    trigger: dict[int, Any] = {}
    for prob in problems:
        owner = next((p for p in proposals if prob.startswith(name_of(p) + "/")), None)
        if owner is not None:
            steps[id(owner)] = owner
            continue
        owner = next((p for p in proposals if prob.startswith(name_of(p) + ":")), None)
        if owner is not None:
            trigger[id(owner)] = owner
            continue
        owner = proposals[0] if len(proposals) == 1 else None
        for p in ([owner] if owner is not None else proposals):
            steps[id(p)] = p

    def settle() -> list[str]:
        said: list[str] = []
        for p in steps.values():
            name = name_of(p)
            p.body["steps"] = [{"key": "unavailable", "name": "Not available yet", "type": "end", "next": [],
                                "config": {"refused": True,
                                           "message": f"{name} is not available yet — it is being fixed."}}]
            said.append(f"{name} is built switched off: starting it says it is not available yet, until its "
                        "steps are fixed")
        for p in trigger.values():
            if id(p) in steps:
                continue
            trig = p.body.get("trigger") if isinstance(p.body.get("trigger"), dict) else None
            if trig is not None:
                trig["enabled"] = False
            said.append(f"{name_of(p)} does not start by itself yet: its trigger is off until it is fixed")
        settle_check(result, check)
        return said
    return settle


class InvalidTrigger(AuthorRefusal):
    """A workflow's trigger, wait or deadline is not one the clock can read."""


def check_workflow_triggers(result: "AgentResult", doc: dict | None = None) -> None:
    """A trigger the runtime will act on, a wait it can measure, a deadline
    it can hand on.

    A schedule used to be a sentence nothing parsed, a record change a
    condition nothing read, and `"1 hour"` a wait of zero: each was accepted
    at the author and silent in the app (2026-10-12). Refused here with
    what to write instead, so the agent is asked again."""
    proposals = [p for p in result.proposals if p.section == "workflows"]
    if not proposals or _settled(result, "check_workflow_triggers"):
        return
    from services.blueprint.cron_expr import is_valid_cron, parse_duration_ms
    from services.blueprint.functional_completeness import with_loop_bodies
    doc = doc or {}
    entities = {str(e.get("id")) for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)}
    roles = {str(r.get("id")) for r in doc.get("roles") or [] if isinstance(r, dict)}
    role_names = {str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict)}
    live_integrations = [i for i in doc.get("integrations") or []
                         if isinstance(i, dict) and str(i.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]
    integrations = {str(i.get("id")) for i in live_integrations}
    inbound_by_id = {str(i.get("id")): i.get("inbound") for i in live_integrations if isinstance(i.get("inbound"), dict)}
    declared_refs = {str(r) for i in live_integrations for r in i.get("secretRefs") or []}
    problems: list[str] = []
    for proposal in proposals:
        body = proposal.body
        name = body.get("name") or proposal.natural_key
        trig = body.get("trigger") if isinstance(body.get("trigger"), dict) else {}
        kind = str(trig.get("kind") or "manual")
        if kind == "schedule":
            cron = str(trig.get("cron") or trig.get("detail") or "").strip()
            if not is_valid_cron(cron):
                problems.append(f"{name}: a schedule says when as `trigger.cron`, five fields "
                                f"(`0 9 * * 1` is Mondays at 09:00); got {cron!r}")
            tz = str(trig.get("timezone") or "").strip()
            if tz:
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(tz)
                except Exception:  # noqa: BLE001
                    problems.append(f"{name}: `trigger.timezone` {tz!r} is not an IANA zone (`Asia/Dubai`)")
        elif kind == "db_change":
            if str(trig.get("entity") or "") not in entities:
                problems.append(f"{name}: a `db_change` trigger names the record type it watches as "
                                f"`trigger.entity` (an entity id); got {trig.get('entity')!r}")
            if str(trig.get("on") or "") not in ("created", "updated", "deleted"):
                problems.append(f"{name}: a `db_change` trigger says which change as `trigger.on`: "
                                f"created, updated or deleted; got {trig.get('on')!r}")
        elif kind == "api_event":
            if not str(trig.get("event") or trig.get("detail") or "").strip():
                problems.append(f"{name}: an `api_event` trigger names its event as `trigger.event`")
        elif kind == "webhook":
            row = inbound_by_id.get(str(trig.get("integration") or ""))
            if str(trig.get("integration") or "") not in integrations:
                problems.append(f"{name}: a `webhook` trigger names the integration that calls in as "
                                f"`trigger.integration` (one declared under `integrations`); got "
                                f"{trig.get('integration')!r}")
            elif row is None:
                problems.append(f"{name}: {trig.get('integration')} does not call in — it declares no `inbound`; "
                                "a webhook starts only from an integration with one")
            event = str(trig.get("event") or "").strip()
            if not event:
                problems.append(f"{name}: a `webhook` trigger names the event the integration sends as `trigger.event`")
            elif row is not None and event not in [str(e) for e in row.get("events") or []]:
                problems.append(f"{name}: {trig.get('integration')} sends {', '.join(str(e) for e in row.get('events') or []) or 'nothing listed'}; "
                                f"`trigger.event` {event!r} is not one of them")
        for st in with_loop_bodies(body).get("steps") or []:
            if not isinstance(st, dict):
                continue
            cfg = st.get("config") if isinstance(st.get("config"), dict) else {}
            key = st.get("key") or st.get("id")
            if str(st.get("type") or "") == "wait":
                until = str(cfg.get("until") or "")
                length = parse_duration_ms(cfg.get("for") if cfg.get("for") is not None
                                           else cfg.get("duration") if cfg.get("duration") is not None
                                           else cfg.get("durationMs"))
                if not (length > 0 or "{{" in until):
                    problems.append(f"{name}/{key}: a wait says how long as `config.for` (`2 days`, `PT90M`) "
                                    "or when as `config.until` (a template to a date)")
            if "dueIn" in cfg and not (isinstance(cfg.get("dueIn"), int) and not isinstance(cfg.get("dueIn"), bool)
                                       and cfg["dueIn"] > 0):
                problems.append(f"{name}/{key}: `config.dueIn` is a number of minutes")
            if "escalateTo" in cfg and str(cfg.get("escalateTo")) not in roles | role_names:
                problems.append(f"{name}/{key}: `config.escalateTo` names a declared role; got {cfg.get('escalateTo')!r}")
            if str(cfg.get("actionType") or "") == "create_checkout":
                ref = cfg.get("reference")
                if not (isinstance(ref, dict) and ref.get("entity") and ref.get("id") is not None):
                    problems.append(f"{name}/{key}: `create_checkout` names the record it pays for as "
                                    "`reference: {entity, id}`")
                if cfg.get("amount") is None and not cfg.get("lineItems"):
                    problems.append(f"{name}/{key}: `create_checkout` says what is paid: `amount` (major units) or `lineItems`")
                pays = [i for i in live_integrations if str(i.get("serves") or "") == "take_payment"]
                listeners = [w for w in (doc.get("workflows") or []) + [p.body for p in proposals]
                             if isinstance(w, dict) and str((w.get("trigger") or {}).get("kind") or "") == "webhook"
                             and str((w.get("trigger") or {}).get("event") or "") == "payment.succeeded"]
                if not pays:
                    problems.append(f"{name}/{key}: no integration `serves: take_payment`; declare the payment service first")
                elif not listeners:
                    problems.append(f"{name}/{key}: nothing listens for `payment.succeeded` from {pays[0].get('name')} — declare "
                                    "a workflow with a `webhook` trigger on it that records the outcome")
            auth = cfg.get("auth")
            if auth is not None:
                ref = str((auth or {}).get("secretRef") or "") if isinstance(auth, dict) else ""
                if not ref:
                    problems.append(f"{name}/{key}: `config.auth` names the secret as `secretRef` (a NAME an integration declares)")
                elif ref not in declared_refs:
                    problems.append(f"{name}/{key}: `auth.secretRef` {ref!r} is declared by no integration; declare it under "
                                    f"`integrations[].secretRefs` first" + (f" (declared: {', '.join(sorted(declared_refs))})" if declared_refs else ""))
    if problems:
        raise InvalidTrigger(_all_of(problems),
                             settle=_process_off(result, proposals, problems, "check_workflow_triggers"))


class InvalidIntegration(AuthorRefusal):
    """An integration the runtime could not carry, or a secret written where a name belongs."""


SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


def check_integrations(result: "AgentResult", doc: dict | None = None) -> None:
    """A declared integration the runtime can act on: `serves` only an
    action with an adapter (and then that adapter's provider and names),
    secret NAMES never values, and an `inbound` that says how a call is
    verified and by which of its names."""
    proposals = [p for p in result.proposals if p.section == "integrations"]
    if not proposals or _settled(result, "check_integrations"):
        return
    # SHIPPED CLOSED WHEN THE AUTHOR CANNOT FIX IT (`AuthorRefusal.settle`):
    # a value written where a name goes is removed and a name put in its
    # place for the person to fill in settings — the value is never kept; an
    # adapter that does not fit is unset, so the system is reached from the
    # steps that call it; an inbound call that cannot be verified is not
    # accepted at all.
    fixes: list = []
    from services.smith.connect_service import actions, providers_of
    from services.smith.secrets_scrub import carries_secret
    problems: list[str] = []
    for proposal in proposals:
        body = proposal.body or {}
        name = body.get("name") or proposal.natural_key
        refs = [str(r) for r in body.get("secretRefs") or []]
        bad_refs = [ref for ref in refs if not SECRET_NAME.match(ref) or carries_secret(ref)]
        for ref in bad_refs:
            problems.append(f"{name}: `secretRefs` holds NAMES, UPPER_SNAKE (`XERO_API_KEY`); got {ref[:40]!r}")
        if bad_refs:
            stem = re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_") or "SERVICE"
            def names_not_values(b=body, bad=frozenset(bad_refs), stem=stem):
                kept = [r for r in b.get("secretRefs") or [] if str(r) not in bad]
                b["secretRefs"] = kept + ([f"{stem}_API_KEY"] if f"{stem}_API_KEY" not in kept else [])
            fixes.append((names_not_values, f"{name}: what was written as its key was not kept; enter the key "
                                            f"in the app's settings as {stem}_API_KEY"))
        serves = str(body.get("serves") or "").strip()
        if serves:
            if serves not in actions():
                problems.append(f"{name}: `serves` names an action with an adapter ({', '.join(sorted(actions()))}) "
                                f"or is empty; got {serves!r}")
                fixes.append((lambda b=body: b.__setitem__("serves", ""),
                              f"{name} is reached from the steps that call it, not through a built-in adapter"))
            else:
                provider = str(body.get("provider") or "").strip().lower()
                known = providers_of(serves)
                from services.smith.connect_service import adapter_for
                flexible = bool(getattr(adapter_for(serves), "FLEXIBLE_NAMES", False))
                if provider not in known:
                    problems.append(f"{name}: `{serves}` is carried by {', '.join(sorted(known))}; got provider {provider!r}")
                    fixes.append((lambda b=body: b.__setitem__("serves", ""),
                                  f"{name} ({provider}) is reached from the steps that call it: the built-in "
                                  f"{serves} adapter is for {', '.join(sorted(known))}"))
                elif flexible:
                    # NAMES PER ENTRY (`SSO_<ID>_ISSUER/CLIENT_ID/CLIENT_SECRET`):
                    # any complete triple reaches a provider.
                    if not adapter_for(serves).complete_triples(refs):
                        problems.append(f"{name}: {provider} reads a triple of names — {', '.join(known[provider])} "
                                        "(or the same three under the entry's own id)")
                        fixes.append((lambda b=body, want=list(known[provider]): b.__setitem__(
                            "secretRefs", [*(b.get("secretRefs") or []), *[k for k in want if k not in (b.get("secretRefs") or [])]]),
                            f"{name}: its keys are {', '.join(known[provider])}"))
                else:
                    missing = [k for k in known[provider] if k not in refs]
                    if missing:
                        problems.append(f"{name}: {provider} reads {', '.join(known[provider])} — add {', '.join(missing)} to `secretRefs`")
                        fixes.append((lambda b=body, add=list(missing): b.__setitem__(
                            "secretRefs", [*(b.get("secretRefs") or []), *add]),
                            f"{name}: also needs {', '.join(missing)} in the app's settings"))
        inbound = body.get("inbound")
        if inbound is not None:
            closed = (lambda b=body: b.pop("inbound", None),
                      f"{name} cannot call the app yet: how its calls are verified was not settled")
            if not isinstance(inbound, dict):
                problems.append(f"{name}: `inbound` is an object: events, verify, signingSecretRef")
                fixes.append(closed)
            else:
                ref = str(inbound.get("signingSecretRef") or "")
                no_events = not [e for e in inbound.get("events") or [] if str(e).strip()]
                if ref not in refs:
                    problems.append(f"{name}: `inbound.signingSecretRef` names one of `secretRefs`; got {ref!r}")
                if no_events:
                    problems.append(f"{name}: `inbound.events` lists the events the system sends (`payment.succeeded`)")
                if no_events or not SECRET_NAME.match(ref) or carries_secret(ref):
                    if ref not in refs or no_events:
                        fixes.append(closed)
                elif ref not in refs:
                    fixes.append((lambda b=body, r=ref: b.__setitem__("secretRefs", [*(b.get("secretRefs") or []), r]),
                                  f"{name}: its calls are verified with {ref}, kept with its other keys"))
    if problems:
        def settle() -> list[str]:
            for fix, _said in fixes:
                fix()
            settle_check(result, "check_integrations")
            return list(dict.fromkeys(said for _fix, said in fixes))
        raise InvalidIntegration(_all_of(problems), settle=settle)


class InvalidEntityFields(AuthorRefusal):
    """An entity's fields cannot be stored as proposed."""


#: What a vector field may be taken of: a picture, or words.
EMBEDDABLE_TYPES = frozenset({"image", "string", "text"})


#: WHAT THE PLATFORM ALREADY DOES, stated once — the refusals below enforce
#: it, and the observer is shown the same words so it stops asking for the
#: opposite. Measured: over three weeks the critic demanded a password field
#: on the login entity again and again, which this module refuses outright —
#: a round nobody could win, twice in one HippieKit build.
CREDENTIAL_RULE = ("A person's password, or any credential, is held by the platform's login and "
                   "never stored as a field of an entity — not even the login entity.")
AUTH_RULE = ("Signing up, signing in and resetting a password are provided by the platform "
             "(its /login and /signup pages and its session); they are not written as entity "
             "fields, business rules or workflows.")
PLATFORM_RULES: tuple[str, ...] = (CREDENTIAL_RULE, AUTH_RULE)


def check_entity_fields(result: "AgentResult", doc: dict | None = None) -> None:
    """A `vector` field names the image or text field of the same entity it is
    taken of. 036farqu: Tool and ConditionEvidence came back with
    `embedding: {of: ""}`, the contract refused the whole document, and the
    retry was told only "'' should be non-empty" — ConditionEvidence ended with
    no columns at all. Refused here instead, naming the fields it could be."""
    problems: list[str] = []
    if _settled(result, "check_entity_fields"):
        return
    # THE SAFE WAY THROUGH, ONE PER FAULT (`AuthorRefusal.settle`). This node
    # is whole: one record's refusal fails every record, so each fault here
    # carries what the build does instead — a field that cannot work is taken
    # off, a flag that contradicts the data model is dropped, a label is one
    # of the record's own fields. None of them ships a record that is wrong.
    fixes: list = []
    for proposal in (p for p in result.proposals if p.section == "data.entities"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        fields = [f for f in body.get("fields") or [] if isinstance(f, dict)]
        sources = [str(f.get("name")) for f in fields
                   if str(f.get("type") or "").lower() in EMBEDDABLE_TYPES and f.get("name")]
        for f in fields:
            if str(f.get("type") or "").lower() != "vector":
                continue
            of = str(((f.get("embedding") or {}) if isinstance(f.get("embedding"), dict) else {}).get("of") or "").strip()
            if of and of in sources:
                continue
            said = (f"`embedding.of` is {of!r}, which is not an image or text field of this entity"
                    if of else "has no `embedding.of`")
            fix = (f"set `of` to one of: {', '.join(sources)}" if sources
                   else "this entity has no image or text field to embed — remove the vector field, "
                        "or add the image field it should be taken of")
            problems.append(f"{body.get('name') or proposal.natural_key}.{f.get('name')}: a vector field {said}; {fix}")
            where = f"{body.get('name') or proposal.natural_key}.{f.get('name')}"
            if len(sources) == 1:
                fixes.append((lambda f=f, src=sources[0]: f.__setitem__("embedding", {**(f.get("embedding") or {}), "of": src}),
                              f"{where} is taken of {sources[0]}, the record's only image or text field"))
            else:
                fixes.append((lambda b=body, f=f: b.__setitem__("fields", [x for x in b.get("fields") or [] if x is not f]),
                              f"{where} was left out: it named no field to be taken of"
                              + (f" (it could be one of {', '.join(sources)})" if sources else "")))
    # AN ENTITY'S LABEL IS ONE OF ITS OWN FIELDS. `labelField: "brandName"` on
    # an entity with no `brandName` is a contradiction a reader can see in the
    # proposal itself — checked here, at the author, in the same attempt,
    # rather than sent back by the observer a round later (HippieKit's
    # BrandSuggestion). Only once fields are being written: the entity set
    # names the label before any field exists.
    known = {str(e.get("name")): e for e in ((doc or {}).get("data") or {}).get("entities") or []
             if isinstance(e, dict)}
    for proposal in (p for p in result.proposals if p.section == "data.entities"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        names = [str(f.get("name")) for f in body.get("fields") or [] if isinstance(f, dict) and f.get("name")]
        if not names:
            continue
        ename = str(body.get("name") or proposal.natural_key)
        label = body.get("labelField") or (known.get(ename) or {}).get("labelField")
        if label and label not in names:
            problems.append(f"{ename}: `labelField` is {label!r}, which is not one of its fields "
                            f"({', '.join(names)}) — add that field, or set `labelField` to one of these")
            texty = [str(f.get("name")) for f in body.get("fields") or [] if isinstance(f, dict)
                     and str(f.get("type") or "").lower() in ("string", "text") and not f.get("primaryKey")]
            pick = (texty or names)[0]
            fixes.append((lambda b=body, pick=pick: b.__setitem__("labelField", pick),
                          f"{ename} is labelled by {pick} ({label} is not one of its fields)"))
    for said, field_ in _unique_many_side(result, doc):
        problems.append(said)
        fixes.append((lambda f=field_: f.pop("unique", None),
                      f"{said.split(':', 1)[0]} is not unique: many rows point at one record"))
    # THE ACCOUNT ENTITY: at most one, and signup must be able to create it —
    # a required reference to another record is a field no one can fill when
    # the account is made.
    live = [e for e in ((doc or {}).get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"]
    # ONE LOGIN ENTITY, DECIDED ONCE. Two entities both marked `account`
    # (a marketplace's Shopper and VendorAccount, 7ttp60zi 2026-10-11) were
    # each refused because the OTHER already had the flag; each author then
    # dropped its own flag "since the other holds it", and neither landed.
    # The first live account entity is the login; the refusal names it and
    # goes only to the others. Within one reply (the entity set), the first
    # proposal that claims it is the login and the later claimants are told.
    login = next((e for e in live if e.get("account")), None)
    claimed_here: list[str] = []
    for proposal in (p for p in result.proposals if p.section == "data.entities"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        name = body.get("name") or proposal.natural_key
        same = lambda e: e.get("name") == name or str(e.get("id")) == str(proposal.natural_key)
        # The flag is set with the entity set; the fields arrive per entity
        # later and need not repeat it.
        if not (body.get("account") or any(e.get("account") and same(e) for e in live)):
            continue
        if body.get("account"):
            already = any(e.get("account") and same(e) for e in live)
            # A flag the document already carries is not this author's to
            # move (`entity_fields` re-asserts it from the entity set), so a
            # refusal here could never be satisfied: the clash is decided by
            # `one_login` when the proposals land.
            if login is not None and not same(login) and not already:
                problems.append(f"{name}: `account: true` is already on {login.get('name')} — one entity is the "
                                f"person behind a login. Drop `account` here: a {name} is a login "
                                f"({login.get('name')}) with its own role, and this entity holds what that "
                                "person has beyond the login, referencing it by a field")
                fixes.append((lambda b=body: b.pop("account", None),
                              f"{name} is not the login record; {login.get('name')} is"))
            elif login is None and claimed_here and str(name) not in claimed_here:
                problems.append(f"{name}: `account: true` is already on {claimed_here[0]} in this reply — one "
                                f"entity is the person behind a login. Keep it on {claimed_here[0]} and drop it "
                                f"here; a {name} is a login with its own role plus this record of what they have")
                fixes.append((lambda b=body: b.pop("account", None),
                              f"{name} is not the login record; {claimed_here[0]} is"))
            elif login is None and str(name) not in claimed_here:
                claimed_here.append(str(name))
        from services.blueprint.projection import _is_credential_field
        for f in body.get("fields") or []:
            # THE LOGIN HOLDS THE PASSWORD. 0l133sp2's Member carried a required
            # `passwordHash`; signup creates the row without one, so every
            # signup would have been refused by the database.
            if isinstance(f, dict) and _is_credential_field(f.get("name")):
                problems.append(f"{name}.{f.get('name')}: remove this field. {CREDENTIAL_RULE}")
                fixes.append((lambda b=body, f=f: b.__setitem__("fields", [x for x in b.get("fields") or [] if x is not f]),
                              f"{name}.{f.get('name')} was removed: the login keeps the password, not the record"))
            if isinstance(f, dict) and f.get("references") and f.get("required"):
                problems.append(f"{name}.{f.get('name')}: the account entity's row is created at signup, when no "
                                "other record exists to point at — make this reference optional")
                fixes.append((lambda f=f: f.__setitem__("required", False),
                              f"{name}.{f.get('name')} is optional: the record is made at sign-up, before "
                              "there is anything for it to point at"))
    if problems:
        def settle() -> list[str]:
            for fix, _said in fixes:
                fix()
            settle_check(result, "check_entity_fields")
            return [said for _fix, said in fixes]
        raise InvalidEntityFields(_all_of(problems), settle=settle)


def _unique_many_side(result: "AgentResult", doc: dict | None) -> list[tuple[str, dict]]:
    """A reference on the MANY side of a one-to-many is never unique by itself.

    HippieKit (2026-09-22) marked `ProductIngredient.productId` and
    `RecentSearch.shopperId` unique while the data model said a product has
    many ingredients and a shopper many searches: each product could then
    carry one ingredient, each shopper keep one search. The observer caught
    both a round later. The two statements are in the Blueprint side by side —
    the relationship and the flag — so the contradiction is refused here, in
    the author's own attempt. One row per PAIR is a `unique` constraint over
    both columns, which this does not touch."""
    data = (doc or {}).get("data") or {}
    name_of = {str(e.get("id")): str(e.get("name")) for e in data.get("entities") or []
               if isinstance(e, dict)}
    many: dict[str, dict[str, str]] = {}      # entity name -> {fk field: the "one" entity}
    rels = list(data.get("relationships") or [])
    for proposal in (p for p in result.proposals if p.section == "data.relationships"):
        if isinstance(proposal.body, dict):
            rels.append(proposal.body)
    for r in rels:
        if not isinstance(r, dict) or r.get("kind") != "one_to_many" or r.get("status") == "DEPRECATED":
            continue
        fk = str(r.get("toField") or "")
        if not fk or fk == "id":
            continue
        one = name_of.get(str(r.get("from")), str(r.get("from")))
        many.setdefault(name_of.get(str(r.get("to")), str(r.get("to"))), {})[fk] = one
    out: list[tuple[str, dict]] = []
    for proposal in (p for p in result.proposals if p.section == "data.entities"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        ename = str(body.get("name") or name_of.get(str(proposal.natural_key), proposal.natural_key))
        for f in body.get("fields") or []:
            if not isinstance(f, dict) or not f.get("unique") or f.get("primaryKey"):
                continue
            one = many.get(ename, {}).get(str(f.get("name")))
            if one:
                out.append((f"{ename}.{f.get('name')}: marked `unique`, but the data model says one {one} "
                            f"has many {ename} rows — unique, each {one} could have only one. Remove "
                            f"`unique`; if one {ename} per pair is meant, add a `unique` constraint over "
                            f"both columns", f))
    return out


class InvalidAnalytics(AuthorRefusal):
    """A page that should carry charts was given none."""


#: The page patterns that carry analytics, and how many charts each must.
#: A dashboard IS analytics; a list over records with a status, a type, a
#: date or an amount carries the breakdown or the trend of what it lists.
CHARTS_REQUIRED: dict[str, int] = {"dashboard": 3, "analytics": 3, "entity_list": 1,
                                   "master_detail": 1, "approval_inbox": 1}
#: A dashboard's charts are of at least this many different marks: three
#: bars is one chart said three times.
DASHBOARD_MARKS = 2
#: A dashboard opens with how things stand: this many `metric` tiles at least.
DASHBOARD_METRICS = 3
_DATE_TYPES = {"date", "datetime", "timestamp"}
_NUMBER_TYPES = {"number", "integer", "int", "decimal", "float", "currency", "money"}


def plottable_fields(entity: dict) -> list[str]:
    """The fields of an entity a chart can be drawn over: an enum (a status,
    a type), a date (a trend), a number (a total, a distribution) or a
    foreign key (a breakdown by the record it points at)."""
    out = []
    for f in entity.get("fields") or []:
        if not isinstance(f, dict) or f.get("status") == "DEPRECATED":
            continue
        t = str(f.get("type") or "").lower()
        why = ("enum" if f.get("enumValues") or t == "enum"
               else "date" if t in _DATE_TYPES
               else "number" if t in _NUMBER_TYPES
               else "reference" if f.get("references") else "")
        if why:
            out.append(f"{f.get('name')} ({why})")
    return out


def customer_facing(doc: dict, page: dict) -> bool:
    """Whether a page is for the product's customers rather than its staff:
    public, or — in an application with more than one role — open only to the
    role people sign up as. Such a page shows the product, not numbers about
    it: F&B's customer menu carried a "Price range" chart because every list
    page had to (2026-10-02)."""
    from services.blueprint.account_model import signup_role
    if str(page.get("access") or "") == "public":
        return True
    roles = {str(r.get("id")): str(r.get("name") or "") for r in doc.get("roles") or []
             if isinstance(r, dict) and r.get("status") != "DEPRECATED"}
    customer = signup_role(doc)
    users = [roles.get(str(u), str(u)) for u in page.get("users") or []]
    return len(roles) > 1 and bool(customer) and bool(users) and all(u == customer for u in users)


class InvalidAppFlow(AuthorRefusal):
    """A flow names a screen, a section or a process that is not there."""


def check_flows(result: "AgentResult", doc: dict | None) -> None:
    """A PATH THROUGH SCREENS THAT EXIST. Each proposed flow is checked as the
    document would hold it: every step a live screen, a section that screen
    has, a process it starts — refused naming each, so the author mends the
    step rather than the page writer being told a hand-off to nowhere."""
    from services.blueprint.app_flows import flow_findings
    proposals = [p for p in result.proposals if p.section == "flows" and isinstance(p.body, dict)]
    if not proposals or not doc or _settled(result, "check_flows"):
        return

    def leave_out(why: str) -> "Callable[[], list[str]]":
        # JOURNEYS ARE GUIDANCE, not structure: the screens and processes they
        # walk through stand without them. Left out, and said.
        def settle() -> list[str]:
            result.proposals = [p for p in result.proposals if p.section != "flows"]
            settle_check(result, "check_flows")
            return [f"the journeys through the app were left out ({len(proposals)}) — {why}"]
        return settle
    # JOURNEYS THROUGH SCREENS THIS SAME REPLY PROPOSES are premature: the
    # screens have no ids yet, and journeys are the journeys step's, once
    # they do. Said as that, not as "not a screen" (60v142ju, 2026-10-12).
    saved = {str(pg.get("id")) for pg in doc.get("pages") or [] if isinstance(pg, dict)} | \
            {str(pg.get("route")) for pg in doc.get("pages") or [] if isinstance(pg, dict)}
    new_pages = [p for p in result.proposals if p.section == "pages" and isinstance(p.body, dict)
                 and str(p.body.get("route") or "") not in saved and str(p.body.get("id") or "") not in saved]
    if new_pages:
        raise InvalidAppFlow("Leave `flows` out of this reply: journeys are planned by their own step once the "
                             "screens you are proposing exist and have ids. Return the screens without them.",
                             settle=leave_out("they were written before their screens existed"))
    problems = flow_findings({**doc, "flows": [p.body for p in proposals]})
    if problems:
        raise InvalidAppFlow("These flows name what the application does not have — mend each step:\n- "
                             + "\n- ".join(problems[:30]),
                             settle=leave_out("they named screens or processes the app does not have: "
                                              + "; ".join(problems[:3])))


def check_analytics(result: "AgentResult", doc: dict | None) -> None:
    """CHARTS SHOW UP ON EVERY RELEVANT PAGE. The analytics agent was asked
    to decide page by page and decided "none" for a product's home
    dashboard and for every list of its catalogue (zo9k0ekd: 0 of 24
    widgets on `/`, `/categories`, `/products`). A dashboard with no chart
    is not a dashboard; a list of records with a status or a date and no
    breakdown or trend is a table with nothing to say about itself. Refused
    at the author, naming each page and the fields it could chart, so the
    reply is edited rather than shipped bare."""
    proposals = [p for p in result.proposals if p.section == "widgets"]
    if not proposals or not doc or _settled(result, "check_analytics"):
        return
    ents = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"}
    charts: dict[str, int] = {}
    metrics: dict[str, int] = {}
    marks: dict[str, set[str]] = {}
    over_time: set[str] = set()
    problems: list[str] = []
    known = {str(r.get("id")) for r in doc.get("requirements") or [] if isinstance(r, dict) and r.get("id")}
    # A CHANGE IS JUDGED ON WHAT IT CHANGES. Counted from this reply alone and
    # judged over every page, a rewrite of one screen's widgets read every
    # other page as chartless and was refused for them — TStyle's /trends,
    # / and /water-intake rewrites, one after another (forge-v3, 2026-10-09).
    # The first authoring (no widgets yet) is judged on the whole app, which
    # is what catches a dashboard decided to need none; a later change on the
    # pages it gives widgets to, counted with the widgets already there.
    existing = [w for w in doc.get("widgets") or []
                if isinstance(w, dict) and w.get("status") != "DEPRECATED"]
    changing = {str((p.body or {}).get("id") or "") for p in proposals if isinstance(p.body, dict)} - {""}
    # The pages it gives widgets to, and the pages the widgets it changes
    # leave — a chart moved or retired off a dashboard is a change to it.
    touched = {str((p.body or {}).get("page") or "") for p in proposals if isinstance(p.body, dict)} | \
              {str(w.get("page") or "") for w in existing if str(w.get("id") or "") in changing}
    counted = [w for w in existing if str(w.get("id") or "") not in changing] + \
              [p.body for p in proposals if isinstance(p.body, dict) and p.body.get("status") != "DEPRECATED"]
    for p in proposals:
        body = p.body if isinstance(p.body, dict) else {}
        # EVERYTHING ON IT IS ABOUT THIS APPLICATION. A widget that cites no
        # requirement is a number nobody asked for; one that cites a
        # requirement that does not exist is a number nobody can check.
        cited = [str(r) for r in body.get("requirements") or []]
        if known and not cited:
            problems.append(f"{body.get('id') or p.natural_key} ({body.get('label')}): names no requirement it answers; "
                            "cite the one it does, or leave it out")
        elif known and not any(c in known for c in cited):
            problems.append(f"{body.get('id') or p.natural_key} ({body.get('label')}): cites {', '.join(cited)}, "
                            "which this application does not have")
    for body in counted:
        pid = str(body.get("page") or "")
        if str(body.get("kind") or "") == "metric":
            metrics[pid] = metrics.get(pid, 0) + 1
        if str(body.get("kind") or "") == "chart":
            charts[pid] = charts.get(pid, 0) + 1
            mark = str((body.get("chart") or {}).get("mark") or "") if isinstance(body.get("chart"), dict) else ""
            if mark:
                marks.setdefault(pid, set()).add(mark)
            src = body.get("dataSource") if isinstance(body.get("dataSource"), dict) else {}
            if any(isinstance(d, dict) and d.get("bucket") for d in src.get("dimensions") or []):
                over_time.add(pid)
    for page in doc.get("pages") or []:
        if not isinstance(page, dict) or page.get("status") == "DEPRECATED":
            continue
        if existing and str(page.get("id")) not in touched:
            continue                      # a change, and not to this page
        need = CHARTS_REQUIRED.get(str(page.get("pattern") or ""), 0)
        if not need or customer_facing(doc, page):
            continue
        pid = str(page.get("id"))
        ent = ents.get(str((page.get("data") or {}).get("primaryEntity") or ""))
        fields = plottable_fields(ent) if ent else []
        if page.get("pattern") not in ("dashboard", "analytics") and not fields:
            continue                      # nothing to draw over: a list of free text
        have = charts.get(pid, 0)
        over = (f" over {ent.get('name')}: {', '.join(fields[:5])}" if ent and fields
                else " over the entities the page shows")
        if have < need:
            problems.append(f"{pid} {page.get('route')} ({page.get('pattern')}) has {have} chart{'s' if have != 1 else ''}; "
                            f"it needs at least {need} — a breakdown or a trend{over}")
            continue
        if page.get("pattern") in ("dashboard", "analytics"):
            # HOW THINGS STAND, THEN WHY. The first reply under the chart
            # rule kept the charts and dropped the KPI tiles on two of three
            # dashboards (nlwtcyz5): a dashboard opens with its numbers.
            if metrics.get(pid, 0) < DASHBOARD_METRICS:
                problems.append(f"{pid} {page.get('route')} (dashboard): has {metrics.get(pid, 0)} metric tile"
                                f"{'s' if metrics.get(pid, 0) != 1 else ''}; it opens with at least {DASHBOARD_METRICS} "
                                f"`kind: metric` widgets that say how things stand, each with `timeField` where its entity has a date")
            # RICH, NOT REPEATED: different marks, and the trend over time
            # when there is a date to trend over.
            if len(marks.get(pid, set())) < DASHBOARD_MARKS:
                problems.append(f"{pid} {page.get('route')} (dashboard): its {have} charts are all "
                                f"{'/'.join(sorted(marks.get(pid, set())) or ['unmarked'])}; a dashboard reads through at "
                                f"least {DASHBOARD_MARKS} different marks — a trend over time, a breakdown, a ranking")
            dated = any(f.endswith("(date)") for e in ents.values() for f in plottable_fields(e))
            if dated and pid not in over_time:
                problems.append(f"{pid} {page.get('route')} (dashboard): no chart over time, though the data has "
                                f"dates — add a line or area with a `bucket` by week or month")
    if problems:
        def settle() -> list[str]:
            # THE CHARTS THAT WERE WRITTEN SHIP AS THEY ARE. Every fault here is
            # one of richness — fewer charts than a page should have, a widget
            # whose citation cannot be checked — and none makes a chart wrong.
            # A citation that names nothing is taken off rather than kept.
            for p in proposals:
                if isinstance(p.body, dict) and known:
                    p.body["requirements"] = [r for r in p.body.get("requirements") or [] if str(r) in known]
            settle_check(result, "check_analytics")
            return [f"charts kept as written, short of the house standard: {f}" for f in problems[:8]]
        raise InvalidAnalytics(
            "Charts show up on every relevant page, dashboards are rich, and every widget is about this "
            "application. " + _all_of(problems)
            + " Add or amend `kind: chart` widgets for these pages (keep the metrics you have).", settle=settle)


class InvalidPageContent(AuthorRefusal):
    """A page's content plan names a source the data model does not have."""


def check_page_content(result: "AgentResult", doc: dict | None) -> None:
    """Every fact a page's content plan shows resolves — a field its entity
    has (or proposes in `newField`), a foreign key that points where it says,
    a count over a real relationship. Refused at the page's author, naming the
    fault, rather than discovered by the UI engineer as a page with nothing to
    show."""
    from services.blueprint.page_content import content_findings

    problems: list[str] = []
    for proposal in (p for p in result.proposals if p.section == "pages"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        if body.get("content"):
            problems.extend(content_findings(body, doc or {}))
    if problems:
        raise InvalidPageContent(_all_of(problems[:12]))


class InconsistentPageAccess(AuthorRefusal):
    """Pages of one module, for the same people, disagree on who may open them."""


def access_findings(pages: list[dict]) -> list[str]:
    """Pages of one module that name the same audience and disagree on whether
    that audience is a permission. F&B's back office was five pages for Admin
    in one module: three `role_restricted`, and "Edit Menu Item" and "Orders"
    `authenticated` — so a signed-up customer opened the order queue
    (fxa532bj, 2026-10-02). Either reading can be right; one module saying
    both of the same people is not a decision, it is a slip."""
    groups: dict[tuple[str, tuple[str, ...]], dict[str, list[str]]] = {}
    for page in pages:
        access = str(page.get("access") or "authenticated")
        users = tuple(sorted(str(u) for u in page.get("users") or []))
        module = str(page.get("module") or "")
        if not module or not users or access == "public":
            continue
        groups.setdefault((module, users), {}).setdefault(access, []).append(
            str(page.get("route") or page.get("id")))
    problems: list[str] = []
    for (module, users), by in groups.items():
        if len(by) > 1:
            said = "; ".join(f"{a}: {', '.join(sorted(r))}" for a, r in sorted(by.items()))
            problems.append(
                f"pages of {module} for {', '.join(users)} disagree on who may open them ({said}) — "
                "give them the same `access`: `role_restricted` if only those roles may open "
                "them, `authenticated` if anyone signed in may")
    return problems


def check_page_access(result: "AgentResult", doc: dict | None) -> None:
    """`access_findings` over the pages as they would stand, refused at the
    page's author when its own proposal is one of the pages that disagree —
    and only when it says who the page is for (`access`, `users`, `module`):
    an edit to a page's content is not the place a module's access is
    settled, and refusing it would hold that edit hostage to another page."""
    proposed = [p.body for p in result.proposals
                if p.section == "pages" and isinstance(p.body, dict)]
    if not proposed or _settled(result, "check_page_access"):
        return
    merged: dict[str, dict] = {}
    for page in (doc or {}).get("pages") or []:
        if isinstance(page, dict) and str(page.get("status") or "").upper() != "REMOVED":
            merged[str(page.get("id") or page.get("route"))] = page
    nameless: list[dict] = []
    touched: set[str] = set()
    for body in proposed:
        key = str(body.get("id") or "") or next(
            (k for k, v in merged.items() if v.get("route") == body.get("route")), str(body.get("route")))
        is_new = key not in merged
        merged[key] = {**merged.get(key, {}), **body}
        if is_new or {"access", "users", "module"} & set(body):
            touched.add(str(merged[key].get("route") or key))
    problems = [f for f in access_findings(list(merged.values()))
                if any(r in f for r in touched)]
    # A RESTRICTED PAGE NAMES WHO MAY OPEN IT. Nameless, the projection makes
    # it the administrator's (restricted means restricted) — so a vendor's
    # Product Catalogue and Product Editor declared `role_restricted` with no
    # `users` answered 403 to every vendor (7ttp60zi, 2026-10-11). Said to the
    # author, in the same attempt, rather than found by a person.
    for body in proposed:
        key = str(body.get("id") or "") or next(
            (k for k, v in merged.items() if v.get("route") == body.get("route")), str(body.get("route")))
        page = merged.get(key) or body
        if str(page.get("access") or "") == "role_restricted" and not page.get("users"):
            # THE SECTIONS MAY ALREADY SAY WHO. A screen whose parts each name
            # their roles is for the union of them; that is written onto the
            # page rather than asked for a second time.
            from_sections = sorted({str(r) for sec in (page.get("sections") or []) if isinstance(sec, dict)
                                    for r in (sec.get("roles") or []) if r})
            if from_sections:
                body["users"] = from_sections
                continue
            nameless.append(body)
            problems.append(f"{page.get('route') or page.get('name')}: `access: \"role_restricted\"` names no "
                            "role — put the roles that may open it in `users` (the people this screen is "
                            "for); a restricted page nobody is named for is the administrator's alone")
    if problems:
        raise InconsistentPageAccess(_all_of(problems), settle=_admin_only(result, doc, nameless, problems))


def _admin_of(doc: dict | None) -> tuple[str, str]:
    """The administrator role's name and id, or ("", "") when there is none."""
    from services.blueprint.account_model import admin_role
    admin = admin_role(doc or {})
    admin_id = next((str(r.get("id")) for r in (doc or {}).get("roles") or []
                     if isinstance(r, dict) and r.get("name") == admin and r.get("id")), "")
    return admin, admin_id


def _admin_only(result: "AgentResult", doc: dict | None, nameless: list[dict],
                problems: list[str]) -> "Callable[[], list[str]] | None":
    """The safe way through for restricted pages that name nobody: the
    administrator's, which is what the projection serves for them anyway —
    written down, so the page says so and Smith can say who else should open
    it. Only when nameless pages are ALL that is wrong: pages of one module
    that disagree on who may open them are not settled by a guess."""
    if not nameless or len(nameless) != len(problems):
        return None
    admin, admin_id = _admin_of(doc)
    if not admin_id:
        return None

    def settle() -> list[str]:
        for body in nameless:
            body["users"] = [admin_id]
        settle_check(result, "check_page_access")
        return [f"{b.get('route') or b.get('name')} opens for the administrator ({admin}) only — the page "
                "writer named no other role for it; say who else should open it" for b in nameless]
    return settle


class RoleWithoutADoor(AuthorRefusal):
    """A role has pages only it may open and none it arrives on."""


def check_role_doors(result: "AgentResult", doc: dict | None) -> None:
    """Every audience with pages of its own has a door: one of them marked
    `entry`. ToroCommerce's back office had four pages for Admin and the
    navigation named no landing; the administrator signed in to the shop
    front every time (forge-v3, 2026-10-07). Refused at the page author, and
    only for the roles whose pages this proposal says who they are for."""
    from services.blueprint.account_model import roles_without_a_door
    from services.blueprint.projection import restricted_roles

    proposed = [p.body for p in result.proposals
                if p.section == "pages" and isinstance(p.body, dict)]
    if not any({"access", "users", "entry"} & set(b) for b in proposed):
        return
    merged: dict[str, dict] = {}
    for page in (doc or {}).get("pages") or []:
        if isinstance(page, dict) and str(page.get("status") or "").upper() not in ("REMOVED", "DEPRECATED"):
            merged[str(page.get("id") or page.get("route"))] = page
    touched: list[dict] = []
    for body in proposed:
        key = str(body.get("id") or "") or next(
            (k for k, v in merged.items() if v.get("route") == body.get("route")), str(body.get("route")))
        merged[key] = {**merged.get(key, {}), **body}
        touched.append(merged[key])
    after = {**(doc or {}), "pages": list(merged.values())}
    theirs = {str(n) for page in touched for n in restricted_roles(after, page)}
    missing = [r for r in roles_without_a_door(after) if r in theirs]
    # A ROLE WITH PAGES AND NO DOOR IS GIVEN ONE. The author's own reply holds
    # the pages that role may open; the first concrete one — a dashboard before
    # a list before anything else — becomes where it lands, rather than the
    # whole build dying for a flag (FitTrackr qpqhdugb, 2026-10-16: five builds).
    # The author may still say otherwise with `entry: true` of its own.
    rank = {"dashboard": 0, "list": 1, "kanban": 1, "calendar": 1, "map": 1}
    still: list[str] = []
    for role in missing:
        mine = [b for b in proposed if role in {str(n) for n in restricted_roles(after, b)}
                and "[" not in str(b.get("route") or "")]
        mine.sort(key=lambda b: rank.get(str(b.get("pattern") or ""), 2))
        if mine:
            mine[0]["entry"] = True
        else:
            still.append(role)
    if still:
        raise RoleWithoutADoor(_all_of([
            f"{role} has pages only {role} may open and none marked as where {role} arrives — "
            f"give the page {role} opens first `entry: true` (a concrete route, no `[id]`)"
            for role in still]))


class InvalidNavigation(AuthorRefusal):
    """Two menu entries lead to the same address."""


def check_navigation(result: "AgentResult", doc: dict | None = None) -> None:
    """Every menu entry is its own address: a page, or a view of it. 0l133sp2's
    "My Listings" and "Discover" both named the tools page — both lit at once
    and the phone's tab bar drew two tabs keyed `/tools`. Refused here, naming
    both, so the architect points one at the view it meant (`view`)."""
    pages = {str(p.get("id")): p for p in ((doc or {}).get("pages") or []) if isinstance(p, dict)}
    problems: list[str] = []
    for proposal in (p for p in result.proposals if p.section == "navigation"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        seen: dict[tuple[str, str], str] = {}

        def walk(nodes: Any) -> None:
            for node in nodes or []:
                if not isinstance(node, dict):
                    continue
                page = str(node.get("page") or "")
                if page:
                    key = (page, str(node.get("view") or ""))
                    label = str(node.get("label") or page)
                    if key in seen:
                        route = str((pages.get(page) or {}).get("route") or page)
                        problems.append(f"navigation: \"{seen[key]}\" and \"{label}\" both lead to {route}"
                                        f"{'?view=' + key[1] if key[1] else ''} — point one at a view of the page "
                                        f"(`view`: a key of its `views`) or at another page, or drop one")
                    else:
                        seen[key] = label
                walk(node.get("children"))

        walk(body.get("tree"))
    if problems:
        raise InvalidNavigation(_all_of(problems))


class InvalidDesignModules(AuthorRefusal):
    """A module set that leaves one of the design's groups without a module."""


def check_design_modules(result: "AgentResult", doc: dict | None = None) -> None:
    """Every group the connected design is drawn in has its module.

    The groups are the designer's own (`designSources[].frames[].group`): a
    module per group is how a design of hundreds of screens is built a module
    at a time. Checked on an answer that proposes the module set (two or more
    modules) — a one-module edit is not asked about groups it never touched —
    and a `designGroup` naming no group is refused whatever the answer."""
    from services.blueprint.page_planner import design_groups

    proposed = [p.body for p in result.proposals
                if p.section == "modules" and isinstance(p.body, dict)]
    if not proposed:
        return
    groups = design_groups(doc or {})
    named = {str(b.get("designGroup") or "").strip() for b in proposed} - {""}
    problems = [f"modules: designGroup \"{g}\" is not one of the design's groups "
                f"({', '.join(groups) or 'it has none'}) — use a group's exact name or leave it out"
                for g in sorted(named - set(groups))]
    if len(proposed) >= 2 and groups:
        have = named | {str(m.get("designGroup") or "").strip()
                        for m in (doc or {}).get("modules") or [] if isinstance(m, dict)}
        missing = [g for g in groups if g not in have]
        if missing:
            problems.append("modules: the design is drawn in groups with no module: "
                            + ", ".join(f"\"{g}\"" for g in missing)
                            + " — give each its own module with `designGroup` set to that exact name")
    if problems:
        raise InvalidDesignModules(_all_of(problems))


class DrawnScreensShareARoute(AuthorRefusal):
    """Two drawn screens given one route."""


def check_drawn_routes(result: "AgentResult", doc: dict | None = None) -> None:
    """Two drawn screens never share a route.

    A page's identity is its route (`ids.page_key`), so a second screen
    declared at a route a first already holds is not a second page: it is an
    update of the first, and one drawn screen silently replaced another. A
    design of hundreds of screens is declared in parts side by side, none
    seeing the others' routes, which is where two alike choices meet; refused,
    naming the screen that holds it, so the author picks another. A frame this
    reply moves elsewhere no longer holds its old route."""
    from services.blueprint.ids import page_key

    bodies = [p.body for p in result.proposals
              if p.section == "pages" and isinstance(p.body, dict)
              and p.body.get("figmaFrame") and p.body.get("route")]
    if not bodies:
        return
    moving = {str(b["figmaFrame"]) for b in bodies}
    held: dict[str, tuple[str, str]] = {}
    for page in (doc or {}).get("pages") or []:
        if not isinstance(page, dict) or str(page.get("status") or "").upper() in ("REMOVED", "DEPRECATED"):
            continue
        frame = str(page.get("figmaFrame") or "")
        if frame and frame not in moving and page.get("route"):
            held[page_key(str(page["route"]))] = (frame, str(page.get("name") or ""))
    problems: list[str] = []
    for body in bodies:
        key, frame = page_key(str(body["route"])), str(body["figmaFrame"])
        other = held.get(key)
        if other and other[0] != frame:
            problems.append(f"pages: {body['route']} is already the page for the drawn screen "
                            f"“{other[1] or other[0]}” ({other[0]}) — give "
                            f"“{body.get('name') or frame}” ({frame}) a route of its own")
        else:
            held[key] = (frame, str(body.get("name") or ""))
    if problems:
        raise DrawnScreensShareARoute(_all_of(problems))


class InvalidOwnershipRule(AuthorRefusal):
    """An ownership rule the data engine could not apply as written."""


def _field_names(entity: dict) -> set[str]:
    names: set[str] = set()
    for f in entity.get("fields") or []:
        if isinstance(f, dict) and f.get("name"):
            names |= {str(f["name"]), re.sub(r"(?<!^)(?=[A-Z])", "_", str(f["name"])).lower()}
    return names


def ownership_findings(security: dict, doc: dict) -> list[str]:
    """Each enforceable ownership rule names an entity the data model has and
    a column that entity has; a rule owned `through` another record names an
    entity that exists and is itself scoped.

    Kids Vaccination Tracker's security agent scoped Appointment by a
    "denormalized parentId" the table never had; the data engine refused the
    rule at run time and every parent saw no appointments (forge-v3,
    2026-09-26). Refused here, at the author, with the way to say it."""
    entities = [e for e in ((doc.get("data") or {}).get("entities") or [])
                if isinstance(e, dict) and e.get("status") != "DEPRECATED"]
    def find(name: str) -> dict | None:
        key = re.sub(r"[^a-z0-9]", "", str(name).lower())
        for e in entities:
            for form in (e.get("name"), e.get("table"), e.get("id")):
                if form and re.sub(r"[^a-z0-9]", "", str(form).lower()) in (key, key + "s", key + "es"):
                    return e
        return None
    rules = [r for r in (security.get("ownershipRules") or []) if isinstance(r, dict)]
    def key_of(name: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str((find(str(name or "")) or {}).get("name") or "").lower())
    scoped = {key_of(r.get("entity")) for r in rules
              if r.get("kind", "scope") != "attribution" and not r.get("through")}
    # A CHAIN IS SCOPED WHEN IT ENDS AT A SCOPED RECORD. The engine walks
    # `through` up to three records deep (throughConditions), so an order
    # item is a vendor's through its vendor order, which is the vendor's
    # through their profile. Asked for the target to be scoped "itself",
    # the author of Ecom L1's marketplace was refused for exactly that
    # chain, and the edit that answered dropped the rules for Product,
    # ProductVariant, VendorOrder and OrderItem — every vendor then saw
    # every vendor's listings and orders (2026-10-11).
    through_of = {key_of(r.get("entity")): key_of(r.get("through"))
                  for r in rules if r.get("kind", "scope") != "attribution" and r.get("through")}
    def reaches_scope(start: str) -> bool:
        seen, at = set(), start
        for _ in range(3):
            if at in scoped:
                return True
            if at in seen or at not in through_of:
                return False
            seen.add(at)
            at = through_of[at]
        return at in scoped
    problems: list[str] = []
    # WHERE A WORKSPACE SCOPE'S ACTOR COMES FROM: a column of the login entity
    # (`actorColumn`), or the organisation the person acts in when the
    # application declares `security.tenancy`. A rule saying neither
    # compared every row to nothing and was accepted (2026-10-12).
    tenancy_on = isinstance(doc.get("security"), dict) and \
        str(((doc.get("security") or {}).get("tenancy") or {}).get("kind") or "none") == "organisation"
    login_cols: set[str] = set()
    for e in entities:
        if isinstance(e, dict) and e.get("account") is True:
            login_cols = {str(f.get("name")) for f in e.get("fields") or [] if isinstance(f, dict)}
    for r in rules:
        named, column = str(r.get("entity") or ""), str(r.get("column") or "")
        entity = find(named)
        if str(r.get("scope") or "user") == "workspace" and r.get("kind", "scope") != "attribution":
            actor = str(r.get("actorColumn") or "")
            if not actor and not tenancy_on:
                problems.append(f"{named}.{column}: a workspace scope says where the actor's workspace comes from — "
                                "`actorColumn` (a field of the login entity) — or the application declares "
                                "`security.tenancy` and the organisation is the person's active one")
            elif actor and login_cols and actor not in login_cols:
                problems.append(f"{named}.{column}: `actorColumn` {actor!r} is not a field of the login entity")
        if entity is None:
            problems.append(f"ownership rule for {named!r}: the data model has no such entity")
            continue
        if column not in _field_names(entity):
            problems.append(
                f"ownership rule for {entity.get('name')}: {column!r} is not a field of {entity.get('name')} "
                f"(its fields: {', '.join(sorted(str(f.get('name')) for f in entity.get('fields') or [] if isinstance(f, dict)))}). "
                f"Name the field that holds the owner; where a row belongs to someone through another "
                f"record it references, name that reference as `column` and the referenced entity as "
                f"`through`")
            continue
        guest = str(r.get("guestColumn") or "")
        if guest and guest not in _field_names(entity):
            problems.append(f"ownership rule for {entity.get('name')}: guestColumn {guest!r} is not a field of "
                            f"{entity.get('name')} — name the field that holds the visitor's guest token, or "
                            f"ask for one in the data model")
        if r.get("through"):
            target = find(str(r["through"]))
            if target is None:
                problems.append(f"ownership rule for {entity.get('name')}: `through` names "
                                f"{r['through']!r}, which the data model does not have")
            elif not reaches_scope(re.sub(r"[^a-z0-9]", "", str(target.get("name") or "").lower())):
                problems.append(f"ownership rule for {entity.get('name')}: it is owned through "
                                f"{target.get('name')}, which has no scope rule of its own — add "
                                f"a rule for {target.get('name')} naming the field that holds its owner "
                                f"(or the record it is owned through, up to three records deep), and keep "
                                f"this rule")
    return problems


def check_security(result: "AgentResult", doc: dict | None) -> None:
    """The security section's ownership rules are ones the engine can apply."""
    if _settled(result, "check_security"):
        return
    problems = [msg for p in result.proposals if p.section == "security" and isinstance(p.body, dict)
                for msg in ownership_findings(p.body, doc or {})]
    if problems:
        raise InvalidOwnershipRule(_all_of(problems), settle=_records_closed(result, doc or {}))


def _records_closed(result: "AgentResult", doc: dict) -> "Callable[[], list[str]] | None":
    """The safe way through for ownership rules the author could not get
    right: SHIPPED CLOSED. The rule is taken out, and the record type it
    governed is the administrator's alone — every other role loses its
    permissions on it — until the rule is fixed; a guest column that is not a
    field is dropped (visitors lose access, owners keep theirs). Never open:
    when a rule names a record type the data model does not have, or a role
    holding permissions on it is not in this reply to change, there is no
    closed version to ship, and the refusal stands."""
    sec = next((p for p in result.proposals if p.section == "security" and isinstance(p.body, dict)), None)
    if sec is None:
        return None
    role_props = [p for p in result.proposals if p.section == "roles" and isinstance(p.body, dict)]
    perm_props = [p.body for p in result.proposals if p.section == "permissions" and isinstance(p.body, dict)]
    roles = [p.body for p in role_props] + [r for r in doc.get("roles") or [] if isinstance(r, dict)
                                            and r.get("name") not in {b.get("name") for b in (p.body for p in role_props)}]
    admin, _ = _admin_of({**doc, "roles": roles})
    if not admin:
        return None
    entities = {str(e.get("name")): e for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)}
    rules = [r for r in sec.body.get("ownershipRules") or [] if isinstance(r, dict)]
    closing: list[tuple[dict, dict]] = []      # (rule, entity) to take out and close
    guests: list[dict] = []
    for rule in rules:
        found = ownership_findings({**sec.body, "ownershipRules": [rule] + [r for r in rules if r is not rule
                                                                           and r.get("entity") != rule.get("entity")]},
                                   doc)
        mine = [f for f in found if str(rule.get("entity")) in f or str(rule.get("column")) in f]
        if not mine:
            continue
        if any("the data model has no such entity" in f for f in mine):
            return None
        entity = next((e for name, e in entities.items()
                       if re.sub(r"[^a-z0-9]", "", name.lower()) in
                       {re.sub(r"[^a-z0-9]", "", str(rule.get("entity")).lower()) + x for x in ("", "s", "es")}
                       or str(e.get("id")) == str(rule.get("entity"))), None)
        if entity is None:
            return None
        if all("guestColumn" in f for f in mine):
            guests.append(rule)
        else:
            closing.append((rule, entity))
    if not closing and not guests:
        return None              # a fault no rule owns has no closed version
    perms = [*perm_props, *[q for q in doc.get("permissions") or [] if isinstance(q, dict)]]
    shut: dict[str, set[str]] = {}
    for _rule, entity in closing:
        ids = {str(q.get("id")) for q in perms
               if str(q.get("subject")) in (str(entity.get("id")), str(entity.get("name")))}
        shut[str(entity.get("name"))] = ids
        # Every non-administrator holding one of them must be in this reply,
        # or it would keep its access.
        for r in doc.get("roles") or []:
            if isinstance(r, dict) and r.get("name") != admin and ids & {str(x) for x in r.get("permissions") or []} \
                    and r.get("name") not in {p.body.get("name") for p in role_props}:
                return None

    def settle() -> list[str]:
        said: list[str] = []
        for rule in guests:
            rule.pop("guestColumn", None)
            said.append(f"visitors who are not signed in cannot keep {rule.get('entity')} records yet: "
                        "the column for their guest token was not settled")
        gone = {id(rule) for rule, _e in closing}
        sec.body["ownershipRules"] = [r for r in sec.body.get("ownershipRules") or [] if id(r) not in gone]
        for name, ids in shut.items():
            for p in role_props:
                if p.body.get("name") != admin:
                    p.body["permissions"] = [x for x in p.body.get("permissions") or [] if str(x) not in ids]
            said.append(f"{name} records are open to the administrator ({admin}) only: who owns each one was "
                        "not settled, so nobody else may reach them until it is")
        settle_check(result, "check_security")
        return said
    return settle


class InvalidTenancy(AuthorRefusal):
    """Organisations declared in a way the runtime could not serve."""


def check_tenancy(result: "AgentResult", doc: dict | None) -> None:
    """One tenant entity at most; a tenancy names it; every role is a member
    role or a platform role, never both; the admin role is a member role."""
    doc = doc or {}
    problems: list[str] = []
    if _settled(result, "check_tenancy"):
        return
    # THE SAFE WAY THROUGH, ONE PER FAULT, EACH STRICTER (`AuthorRefusal.settle`):
    # one organisation record, roles that exist, a role inside organisations
    # rather than across them. An organisation with no record to be has none:
    # `closable` turns false and the refusal stands.
    fixes: list = []
    closable = True
    entities = [p.body for p in result.proposals if p.section == "data.entities" and isinstance(p.body, dict)]
    tenants_here = [str(e.get("name")) for e in entities if e.get("tenant") is True]
    existing = [str(e.get("name")) for e in (doc.get("data") or {}).get("entities") or []
                if isinstance(e, dict) and e.get("tenant") is True and str(e.get("name")) not in tenants_here
                and str(e.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]
    if len(tenants_here) + len(existing) > 1:
        problems.append(f"only ONE entity is the organisation (`tenant: true`); got {', '.join(tenants_here + existing)}")
        keep = (existing or tenants_here)[0]
        def one_tenant(keep=keep):
            for e in entities:
                if e.get("tenant") is True and str(e.get("name")) != keep:
                    e.pop("tenant", None)
        fixes.append((one_tenant, f"{keep} is the organisation; the other record types are not"))
    roles = known_roles(result, doc)
    role_names: set[str] = set()
    for p in result.proposals:
        if p.section != "security" or not isinstance(p.body, dict) or not isinstance(p.body.get("tenancy"), dict):
            continue
        ten = p.body["tenancy"]
        if str(ten.get("kind") or "none") != "organisation":
            continue
        has_tenant = bool(tenants_here or existing or any(isinstance(e, dict) and e.get("tenant") is True
                                                           for e in (doc.get("data") or {}).get("entities") or []))
        if not has_tenant:
            problems.append("security.tenancy: `organisation` needs an entity marked `tenant: true` in the data model")
            closable = False
        members = [str(r) for r in ten.get("memberRoles") or []]
        platform = [str(r) for r in ten.get("platformRoles") or []]
        unknown = [r for r in members + platform if r not in roles | role_names]
        for r in unknown:
            problems.append(f"security.tenancy: {r!r} is not a declared role")
        if unknown:
            def known_only(t=ten, bad=frozenset(unknown)):
                t["memberRoles"] = [r for r in t.get("memberRoles") or [] if str(r) not in bad]
                t["platformRoles"] = [r for r in t.get("platformRoles") or [] if str(r) not in bad]
            fixes.append((known_only, f"roles that do not exist were taken out of the organisations: {', '.join(unknown)}"))
        both = sorted(set(members) & set(platform))
        if both:
            problems.append(f"security.tenancy: a role is a member role or a platform role, never both: {', '.join(both)}")
            fixes.append((lambda t=ten, b=frozenset(both): t.__setitem__(
                "platformRoles", [r for r in t.get("platformRoles") or [] if str(r) not in b]),
                f"{', '.join(both)} work inside one organisation, not across all of them"))
        if not members:
            problems.append("security.tenancy: name the `memberRoles` people hold inside an organisation")
            names = sorted({str(r.get("name")) for r in [*(p.body for p in result.proposals if p.section == "roles"
                                                            and isinstance(p.body, dict)),
                                                         *(doc.get("roles") or [])]
                            if isinstance(r, dict) and r.get("name")} - set(platform))
            if names:
                fixes.append((lambda t=ten, n=names: t.__setitem__("memberRoles", list(n)),
                              f"everyone but the platform's own staff works inside one organisation: {', '.join(names)}"))
            else:
                closable = False
        admin = ten.get("organisationAdminRole")
        if admin and str(admin) not in members:
            problems.append(f"security.tenancy: `organisationAdminRole` {admin!r} is not one of the member roles")
            fixes.append((lambda t=ten, a=str(admin): t.__setitem__(
                "memberRoles", [*(t.get("memberRoles") or []), a] if a not in (t.get("memberRoles") or []) else t["memberRoles"]),
                f"{admin} administers one organisation, as one of its members"))
    if problems:
        def settle() -> list[str]:
            for fix, _said in fixes:
                fix()
            settle_check(result, "check_tenancy")
            return [said for _fix, said in fixes]
        raise InvalidTenancy(_all_of(problems), settle=settle if closable and fixes else None)


class NoRequirements(AuthorRefusal):
    """A definition that states what the application is and none of what it must do."""


def check_requirements(result: "AgentResult", doc: dict | None) -> None:
    """The requirement agent, on an application that has no requirements
    yet, states at least one. Its reply once carried only the product
    summary; the step reported success and Smith told the person "0
    requirements" (6ysfw182, 2026-10-12). The observer does not watch this
    node, so the shape is held here and the author is asked again."""
    if result.agent != "requirement":
        return
    if any(str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")
           for r in (doc or {}).get("requirements") or [] if isinstance(r, dict)):
        return
    if any(p.section == "requirements" for p in result.proposals):
        return
    raise NoRequirements(
        "The reply states the product and no requirements. Every application has at least one thing it "
        "must do: return a `requirements` proposal for each one the person asked for, beside the `product` "
        "proposal.")


class InvalidMobile(AuthorRefusal):
    """A push channel in an application without push, or a store wrapper with no id."""


def check_mobile(result: "AgentResult", doc: dict | None) -> None:
    """A `send_notification` step may name `push` among its channels only
    where `mobile.push` is on; a store wrapper names its bundle id."""
    doc = doc or {}
    problems: list[str] = []
    mobile = doc.get("mobile") if isinstance(doc.get("mobile"), dict) else {}
    for p in result.proposals:
        if p.section == "mobile" and isinstance(p.body, dict):
            mobile = {**mobile, **p.body}
            store = p.body.get("store") if isinstance(p.body.get("store"), dict) else {}
            if store.get("enabled") is True and not store.get("bundleId"):
                problems.append("mobile.store: a store wrapper names its `bundleId` (com.example.app)")
    native = mobile.get("native") if isinstance(mobile.get("native"), dict) else {}
    if native.get("enabled") is True:
        store = mobile.get("store") if isinstance(mobile.get("store"), dict) else {}
        if not store.get("bundleId"):
            problems.append("mobile.native: a native app names its bundle id — set `mobile.store.bundleId` (com.example.app)")
        signin = ((doc.get("security") or {}).get("signIn") or {}) if isinstance(doc.get("security"), dict) else {}
        for p in result.proposals:
            if p.section == "security" and isinstance(p.body, dict) and isinstance(p.body.get("signIn"), dict):
                signin = {**signin, **p.body["signIn"]}
        if signin.get("password") is False:
            problems.append("mobile.native: the phone signs in with email and password, and `security.signIn.password` is off — "
                            "turn password sign-in on, or turn the native app off")
    push_on = mobile.get("push") is True
    for p in result.proposals:
        if p.section != "workflows" or not isinstance(p.body, dict):
            continue
        for step in p.body.get("steps") or []:
            if not isinstance(step, dict):
                continue
            cfg = step.get("config") if isinstance(step.get("config"), dict) else {}
            channels = cfg.get("channels")
            if isinstance(channels, list) and "push" in [str(c) for c in channels] and not push_on:
                problems.append(f"{p.body.get('name') or p.natural_key}: step {step.get('id') or step.get('name')!s} sends by `push`, "
                                "and the application does not send push (`mobile.push` is off) — drop the channel or turn push on")
    if problems:
        raise InvalidMobile(_all_of(problems))


class InvalidSignIn(AuthorRefusal):
    """A way in nobody could take, or a provider with no row to reach it by."""


_SSO_ID = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_DOMAIN = re.compile(r"^@?[a-z0-9-]+(\.[a-z0-9-]+)+$", re.I)


def check_sign_in(result: "AgentResult", doc: dict | None) -> None:
    """Password off needs another way in; every provider names an `auth`
    integration that exists (or is proposed) and carries its three names;
    a role map names declared roles; a just-in-time provider has a default
    role or a map; domains are domains."""
    doc = doc or {}
    problems: list[str] = []
    if _settled(result, "check_sign_in"):
        return
    # THE SAFE WAY THROUGH, ONE PER FAULT (`AuthorRefusal.settle`): never a
    # way in that should not be there — a provider whose names exist under
    # another id takes that id; one that cannot be reached is left out with
    # password sign-in kept on; a person made on first sign-in with no role
    # is invited instead.
    fixes: list = []
    roles = known_roles(result, doc)
    rows = {str(r.get("id")): r for r in doc.get("integrations") or [] if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")}
    proposed = {p.natural_key or str((p.body or {}).get("name") or ""): p.body for p in result.proposals
                if p.section == "integrations" and isinstance(p.body, dict)}
    from services.blueprint.projection import sso_secret_names
    for p in result.proposals:
        if p.section != "security" or not isinstance(p.body, dict) or not isinstance(p.body.get("signIn"), dict):
            continue
        si = p.body["signIn"]
        sso = [e for e in si.get("sso") or [] if isinstance(e, dict)]

        def drop(entry, si=si, why=""):
            def fix():
                si["sso"] = [x for x in si.get("sso") or [] if x is not entry]
                if not si.get("sso") and not si.get("magicLink"):
                    si["password"] = True
            return (fix, f"sign-in through {entry.get('name') or entry.get('id')} is not offered yet — {why}; "
                         "people sign in with email and password meanwhile")
        if si.get("password") is False and not si.get("magicLink") and not sso:
            problems.append("security.signIn: password off with no magic link and no identity provider — nobody could sign in")
            fixes.append((lambda si=si: si.__setitem__("password", True),
                          "people sign in with email and password: no other way in was settled"))
        seen: set[str] = set()
        for e in sso:
            eid = str(e.get("id") or "")
            if not _SSO_ID.match(eid):
                problems.append(f"security.signIn.sso: `id` is a short lower_snake name (entra, okta_saml); got {eid!r}")
                slug = (re.sub(r"[^a-z0-9_]+", "_", eid.lower()).strip("_") or "sso")[:24]
                slug = slug if slug[:1].isalpha() else f"sso_{slug}"[:24]
                fixes.append((lambda e=e, slug=slug: e.__setitem__("id", slug), f"a sign-in provider's id is {slug}"))
            if eid in seen:
                problems.append(f"security.signIn.sso: two entries share the id {eid!r}")
                fixes.append(drop(e, why="it repeated another provider's id"))
            seen.add(eid)
            ref = str(e.get("integration") or "")
            row = rows.get(ref) or next((b for k, b in proposed.items() if ref and (k == ref or str(b.get("id") or "") == ref)), None)
            if row is None:
                by_kind = [r for r in list(rows.values()) + list(proposed.values()) if str(r.get("kind") or "") == "auth"
                           and str(r.get("serves") or "") == "sign_in"]
                row = by_kind[0] if len(by_kind) == 1 and not ref else None
            if row is None:
                problems.append(f"security.signIn.sso[{eid}]: `integration` names an `auth` integration row (serves `sign_in`) "
                                "that holds the provider's secret NAMES; none found")
                fixes.append(drop(e, why="no integration holds its keys"))
            else:
                names = set(sso_secret_names(eid).values())
                refs = {str(r) for r in row.get("secretRefs") or []}
                missing = sorted(names - refs)
                if missing:
                    problems.append(f"security.signIn.sso[{eid}]: its integration row lists {', '.join(sorted(refs)) or 'no names'}; "
                                    f"add {', '.join(missing)} to its `secretRefs`")
                    # THE NAMES ARE THERE UNDER ANOTHER ID (`SSO_ENTRA_*` for an
                    # entry called `entra_criterion`): the entry takes that id, as
                    # the strongest model did by hand (f7kxusg6, 2026-10-20).
                    ids = [m.group(1).lower() for r in refs for m in [re.match(r"^SSO_([A-Z0-9_]+)_CLIENT_ID$", r)] if m]
                    match = next((c for c in ids if set(sso_secret_names(c).values()) <= refs and _SSO_ID.match(c)), None)
                    if match:
                        fixes.append((lambda e=e, c=match: e.__setitem__("id", c),
                                      f"the {e.get('name') or eid} sign-in uses the keys its integration holds ({match})"))
                    else:
                        fixes.append(drop(e, why=f"its keys ({', '.join(missing)}) are not declared"))
            bad_domains = [d for d in e.get("domains") or [] if not _DOMAIN.match(str(d))]
            for d in bad_domains:
                problems.append(f"security.signIn.sso[{eid}]: `domains` holds domains (acme.com); got {str(d)[:40]!r}")
            if bad_domains:
                fixes.append((lambda e=e, bad=list(bad_domains): e.__setitem__(
                    "domains", [d for d in e.get("domains") or [] if d not in bad]),
                    f"{', '.join(map(str, bad_domains))} are not domains and were left out"))
            rf = e.get("roleFrom") if isinstance(e.get("roleFrom"), dict) else None
            if rf:
                unknown = [g for g, role in (rf.get("map") or {}).items() if str(role) not in roles]
                for group in unknown:
                    problems.append(f"security.signIn.sso[{eid}]: roleFrom.map[{group!r}] names an unknown role "
                                    f"{(rf.get('map') or {}).get(group)!r}")
                if unknown:
                    fixes.append((lambda rf=rf, bad=list(unknown): rf.__setitem__(
                        "map", {g: r for g, r in (rf.get("map") or {}).items() if g not in bad}),
                        f"groups {', '.join(unknown)} map to no role yet"))
                if rf.get("default") and str(rf["default"]) not in roles:
                    problems.append(f"security.signIn.sso[{eid}]: roleFrom.default names an unknown role {rf['default']!r}")
                    fixes.append((lambda rf=rf: rf.pop("default", None), f"{eid}: no default role for people outside the mapped groups"))
            if str(e.get("provisioning") or "just_in_time") == "just_in_time" and not (rf and (rf.get("map") or rf.get("default"))) \
                    and not p.body.get("signupRole") and not (doc.get("security") or {}).get("signupRole"):
                problems.append(f"security.signIn.sso[{eid}]: a person made on first sign-in needs a role — set `roleFrom` "
                                "(a group map or a default) or `signupRole`")
                fixes.append((lambda e=e: e.__setitem__("provisioning", "invite_only"),
                              f"people signing in through {e.get('name') or eid} must be invited first: no role was settled for them"))
    if problems:
        def settle() -> list[str]:
            for fix, _said in fixes:
                fix()
            settle_check(result, "check_sign_in")
            return list(dict.fromkeys(said for _fix, said in fixes))
        raise InvalidSignIn(_all_of(problems), settle=settle if fixes else None)


class InvalidAudit(AuthorRefusal):
    """An audit policy nobody may read, or an audit screen for the wrong people."""


def known_roles(result: "AgentResult", doc: dict | None) -> set[str]:
    """Every role id and name the document has, AND every role this same
    reply declares: the security agent writes `roles` beside `security`, and
    a check reading only the document refused reviewers it was creating in
    that very reply (60v142ju, 2026-10-12)."""
    doc = doc or {}
    out = {str(r.get(k)) for r in doc.get("roles") or [] if isinstance(r, dict) for k in ("id", "name") if r.get(k)}
    for p in result.proposals:
        if p.section == "roles":
            out.add(str(p.natural_key))
            if isinstance(p.body, dict):
                out |= {str(p.body.get(k)) for k in ("id", "name") if p.body.get(k)}
    return out


def role_aliases(result: "AgentResult", doc: dict | None) -> dict[str, str]:
    """Every spelling of a role (its id, its name) → one key, the id where
    known. A page's `users` are role ids and the audit's `reviewers` may be
    names; compared as written they never matched (60v142ju: users
    ROLE-002/ROLE-003 refused against reviewers Supervisor/SystemAdmin)."""
    out: dict[str, str] = {}
    rows = [r for r in (doc or {}).get("roles") or [] if isinstance(r, dict)]
    rows += [p.body for p in result.proposals if p.section == "roles" and isinstance(p.body, dict)]
    for r in rows:
        key = str(r.get("id") or r.get("name") or "")
        for k in ("id", "name"):
            if r.get(k):
                out[str(r[k])] = key
    for p in result.proposals:
        if p.section == "roles":
            out.setdefault(str(p.natural_key), out.get(str((p.body or {}).get("name") or ""), str(p.natural_key)))
    return out


def _security_authored(result: "AgentResult", doc: dict) -> bool:
    """The access step has spoken: roles exist, or this reply declares them."""
    return bool(doc.get("roles")) or any(p.section in ("roles", "security") for p in result.proposals)


def _audit_pages(doc: dict) -> list[dict]:
    return [pg for pg in doc.get("pages") or [] if isinstance(pg, dict) and str(pg.get("pattern") or "") == "audit_trail"
            and str(pg.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def check_audit(result: "AgentResult", doc: dict | None) -> None:
    """A trail has reviewers who are roles; reasons are required on records
    that exist; an `audit_trail` page is for the reviewers, and only where a
    trail is declared.

    THE ORDER OF THE TWO WRITERS. Screens are planned before the access step
    decides roles and the trail, so a screen check made then refused every
    planned audit screen against a policy that did not exist yet (60v142ju).
    The page is judged once the access step has spoken; when it speaks after
    the page, the access step is held to the page: a trail screen already
    planned needs a trail."""
    doc = doc or {}
    roles = known_roles(result, doc)
    entities = {str(e.get("id")): str(e.get("name") or "") for e in (doc.get("data") or {}).get("entities") or []
                if isinstance(e, dict)}
    named = ", ".join(f"{k} ({v})" for k, v in sorted(entities.items())) or "none yet"
    problems: list[str] = []
    if _settled(result, "check_audit"):
        return
    # THE SAFE WAY THROUGH, ONE PER FAULT (`AuthorRefusal.settle`): every fault
    # here has one that leaves the trail at least as closed as asked — the
    # administrator reads a trail nobody was named for, a name that is not a
    # role is dropped, a screen is for the reviewers and nobody else.
    fixes: list = []
    # The administrator among the roles saved AND the roles this reply makes:
    # the access step writes both at once, and its new roles have names before
    # they have ids — a reviewer may be either.
    admin, admin_id = _admin_of({**doc, "roles": [*(doc.get("roles") or []),
                                                  *(p.body for p in result.proposals
                                                    if p.section == "roles" and isinstance(p.body, dict))]})
    admin_id = admin_id or admin or ""
    audit = ((doc.get("security") or {}).get("audit") or {}) if isinstance(doc.get("security"), dict) else {}
    for p in result.proposals:
        if p.section == "security" and isinstance(p.body, dict) and isinstance(p.body.get("audit"), dict):
            audit = p.body["audit"]
            level = str(audit.get("level") or "none")
            reviewers = [str(r) for r in audit.get("reviewers") or []]
            if level != "none" and not reviewers:
                problems.append("security.audit: a trail nobody may read is write-only — name the `reviewers` (roles)")
                fixes.append((lambda a=audit: a.__setitem__("reviewers", [admin_id]),
                              f"the audit trail is read by the administrator ({admin}) only — no reviewers were named"))
            unknown = [r for r in reviewers if r not in roles]
            for r in unknown:
                problems.append(f"security.audit.reviewers: {r!r} is not a declared role")
            if unknown:
                def drop_unknown(a=audit, bad=frozenset(unknown)):
                    a["reviewers"] = [r for r in a.get("reviewers") or [] if str(r) not in bad] or [admin_id]
                fixes.append((drop_unknown, f"audit reviewers that are not roles were dropped: {', '.join(unknown)}"))
            stray = [e for e in audit.get("reasonRequired") or [] if str(e) not in entities]
            for e in stray:
                problems.append(f"security.audit.reasonRequired names RECORD TYPES by entity id, not actions: "
                                f"{e!r} is none of {named}")
            if stray:
                # A RECORD TYPE NAMED BY ITS NAME IS THAT RECORD TYPE: its id goes
                # in (f7kxusg6 wrote `ApprovalDecision` for ENTITY-008). Only a
                # name that is no record type is dropped.
                by_name = {_norm_name(v): k for k, v in entities.items()}
                def mend_stray(a=audit, bad=frozenset(str(e) for e in stray), by_name=by_name):
                    mended = [str(e) if str(e) not in bad else by_name.get(_norm_name(e), "")
                              for e in a.get("reasonRequired") or []]
                    a["reasonRequired"] = [x for x in dict.fromkeys(mended) if x]
                named_here = [str(e) for e in stray if _norm_name(e) in by_name]
                lost = [str(e) for e in stray if _norm_name(e) not in by_name]
                fixes.append((mend_stray, "a reason is asked for on changes to " + ", ".join(named_here)
                              if not lost else "a reason is not asked for on changes to " + ", ".join(lost)
                              + " (not record types the app has)"))
            planned = _audit_pages(doc)
            if level == "none" and planned:
                problems.append(f"security.audit: the screens include an audit trail ({planned[0].get('name')}); "
                                "declare the trail (`level`, `reviewers`) it shows")
                def keep_trail(a=audit):
                    a["level"] = "writes"
                    a["reviewers"] = a.get("reviewers") or [admin_id]
                fixes.append((keep_trail, f"an audit trail of every change is kept for the planned "
                                          f"{planned[0].get('name')} screen"))
    level = str(audit.get("level") or "none")
    alias = role_aliases(result, doc)
    reviewers = {alias.get(str(r), str(r)) for r in audit.get("reviewers") or []}
    reviewer_names = sorted(str(r) for r in audit.get("reviewers") or [])
    if _security_authored(result, doc):
        for p in result.proposals:
            if p.section != "pages" or not isinstance(p.body, dict):
                continue
            if str(p.body.get("pattern") or "") != "audit_trail":
                continue
            name = p.body.get("name") or p.natural_key
            if level == "none":
                problems.append(f"{name}: an `audit_trail` page needs a trail — `security.audit.level` is none")
                fixes.append((lambda prop=p: result.proposals.remove(prop) if prop in result.proposals else None,
                              f"the {name} screen was left out: the app keeps no audit trail for it to show"))
                continue
            users = [alias.get(str(u), str(u)) for u in p.body.get("users") or []]
            if not users:
                # THE TRAIL'S SCREEN IS THE REVIEWERS', AND THE POLICY ALREADY SAYS WHO
                # THEY ARE. The page writer plans screens and does not author `users`
                # (roles sit on sections), so the page is given the reviewers rather
                # than refused for not naming them: refusing killed every build of an
                # app with a trail at this node, four times over (FitTrackr qpqhdugb,
                # 2026-10-16). Naming someone who is NOT a reviewer is still refused.
                if reviewers:
                    p.body["users"] = [alias.get(str(r), str(r)) for r in audit.get("reviewers") or []]
            elif any(u not in reviewers for u in users):
                problems.append(f"{name}: an `audit_trail` page is for the reviewers the audit policy names; "
                                f"`users` must be among {reviewer_names or ['(none declared)']}")
                fixes.append((lambda b=p.body: b.__setitem__(
                    "users", [alias.get(str(r), str(r)) for r in audit.get("reviewers") or []] or [admin_id]),
                    f"the {name} screen is for the audit reviewers only"))
    if problems:
        def settle() -> list[str]:
            for fix, _said in fixes:
                fix()
            settle_check(result, "check_audit")
            return [said for _fix, said in fixes]
        # Every fault above has its fix; without an administrator to fall back
        # to, a trail nobody may read has no safe answer, and stays refused.
        raise InvalidAudit(_all_of(problems), settle=settle if admin_id else None)


class InvalidBusinessRule(AuthorRefusal):
    """A rule the engine could not evaluate as written."""


def check_business_rules(result: "AgentResult", doc: dict | None) -> None:
    """A rule names an entity the data model has, fields that entity has, and
    a condition the engine's parser reads — refused at the author, with the
    fault named, never at the forms that later fire it."""
    proposals = [p for p in result.proposals if p.section == "businessRules"]
    if not proposals or _settled(result, "check_business_rules"):
        return
    from services.blueprint.functional_completeness import authoring_findings
    findings = authoring_findings({
        "businessRules": [p.body for p in proposals],
        "workflows": [],
        "data": (doc or {}).get("data") or {},
    })
    problems = [f["detail"] for f in findings[:8]]
    problems += [f"{p.body.get('name') or p.natural_key}: {e}"
                 for p in proposals for e in prerequisite_findings(p.body, doc or {})]
    if problems:
        def settle() -> list[str]:
            # KEPT AS WRITTEN POLICY, SAID AS NOT ENFORCED. A rule the engine
            # cannot evaluate cannot be run either way; shipped closed it would
            # refuse every save of its record type, which no person meant. It
            # is listed as a stated rule not enforced — the Business Rules tab
            # and the person see it so — and the after-build fixing makes it
            # one the engine can run (`settled.json`).
            said = []
            for p in proposals:
                body = p.body if isinstance(p.body, dict) else {}
                name = str(body.get("name") or p.natural_key)
                if not any(m.startswith(name) or name in m for m in problems):
                    continue
                if body.get("kind") == "prerequisite":
                    body["enabled"] = False
                else:
                    body["kind"] = "statement"
                    body["statement"] = str(body.get("statement") or body.get("name") or name)
                    for k in ("when", "then", "otherwise", "expression", "table", "scope"):
                        body.pop(k, None)
                said.append(f"the rule “{name}” is written down but NOT ENFORCED yet: as written, the app "
                            "could not check it")
            if not said:                       # no rule owns a fault: every rule of the reply
                for p in proposals:
                    body = p.body if isinstance(p.body, dict) else {}
                    body["kind"], name = "statement", str(body.get("name") or p.natural_key)
                    body["statement"] = str(body.get("statement") or name)
                    for k in ("when", "then", "otherwise", "expression", "table", "scope", "gates", "requires"):
                        body.pop(k, None)
                    said.append(f"the rule “{name}” is written down but NOT ENFORCED yet")
            settle_check(result, "check_business_rules")
            return said
        raise InvalidBusinessRule("; ".join(problems), settle=settle)


def prerequisite_findings(rule: dict, doc: dict) -> list[str]:
    """A prerequisite gates workflows the application has, is satisfied by a
    record of an entity it has — tied to the acting account by a field that
    entity has — and says what the person is told. Checked at the author, so
    a gate that could never be met, or never be checked, is re-asked."""
    if rule.get("kind") != "prerequisite":
        return []
    out: list[str] = []
    live = lambda rows: [r for r in rows or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]
    flows = {str(w.get("id")) for w in live(doc.get("workflows"))}
    gates = [str(g) for g in rule.get("gates") or []]
    if not gates:
        out.append("a prerequisite gates at least one workflow — name them in `gates`")
    out += [f"`gates` names {g}, which is not a workflow of this application" for g in gates if flows and g not in flows]
    req = rule.get("requires") or {}
    ents = {str(e.get("id")): e for e in live((doc.get("data") or {}).get("entities"))}
    roles = {str(r.get("id")) for r in live(doc.get("roles"))} | {str(r.get("name")) for r in live(doc.get("roles"))}
    wanted_roles = [str(r) for r in req.get("roles") or []]
    out += [f"`requires.roles` names {r}, which is not a role of this application" for r in wanted_roles
            if roles and r not in roles]
    ent = ents.get(str(req.get("entity") or "")) if req.get("entity") else None
    if req.get("entity") and ent is None:
        out.append("`requires.entity` must name the entity whose record satisfies it")
    elif ent is None and not wanted_roles:
        out.append("`requires` names the record that satisfies it (`entity`, `account`, `where`), the "
                   "`roles` the signed-in person must hold, or both")
    if ent is not None:
        cols = {str(f.get("name")) for f in ent.get("fields") or []}
        acct = str(req.get("account") or "")
        if acct not in cols:
            out.append(f"`requires.account` must be the field of {ent.get('name')} holding the person's "
                       f"account id (one of: {', '.join(sorted(cols)) or 'none'})")
        else:
            # A RECORD'S OWN ID IS AN ACCOUNT'S ID ONLY WHEN THE RECORD IS THE
            # ACCOUNT. Data Collector 4 required an AdminUser whose id was the
            # signed-in account's: no account ever had one, and every staff
            # process refused every member of staff (60v142ju, 2026-10-12).
            from services.blueprint.account_model import account_entity
            keys = {str(f.get("name")) for f in ent.get("fields") or [] if f.get("primaryKey")} or {"id"}
            signs_in = account_entity(doc) or {}
            if acct in keys and str(signs_in.get("id")) != str(ent.get("id")):
                out.append(f"`requires.account` is {ent.get('name')}'s own `{acct}`, but people do not sign in as "
                           f"{ent.get('name')} records, so no signed-in account ever has one. Name the field of "
                           f"{ent.get('name')} that holds the account's id, or — when the gate is about who the "
                           f"person is (staff, administrators) — give `requires.roles` instead")
        out += [f"`requires.where` names {k}, which {ent.get('name')} does not have"
                for k in (req.get("where") or {}) if cols and k not in cols]
    if not str(rule.get("message") or "").strip():
        out.append("a prerequisite says in `message` what the person must do first")
    pages = {str(pg.get("id")) for pg in live(doc.get("pages"))}
    if rule.get("page") and pages and str(rule["page"]) not in pages:
        out.append(f"`page` names {rule['page']}, which is not a page of this application")
    return out


class InvalidPatternTemplate(AuthorRefusal):
    """A2UI proposed a template the component registry cannot render."""


#: The engine's whole-value sentinels: written bare (`"$now"`), never in braces.
SENTINELS = frozenset({"$now", "$today", "$user.id", "$uuid", "$guest"})
_SENTINEL_IN_BRACES = re.compile(r"^\s*\{\{\s*(\$[A-Za-z_][\w.]*)\s*\}\}\s*$")
#: The timestamps a new record always takes at the moment it is made.
_STAMPS = {"createdat", "updatedat"}


def mend_mechanics(result: "AgentResult", doc: dict | None) -> list[str]:
    """Mend, in the processes a reply proposes, what has exactly one right
    answer the platform already knows — before any check reads them, so a
    reply is never sent back for it. Each was a refusal that cost a retry, and
    sometimes the strongest model (Refund And Chargeback, pah7lhfz, forge-v3
    2026-10-20, about ten retries and one process shipped switched off):

    - A SENTINEL IN BRACES. `"{{$user.id}}"` where the engine reads the whole
      value `"$user.id"` (also `$now`, `$today`, `$uuid`, `$guest`). Only when
      the sentinel IS the whole value; inside a sentence it is the author's.
    - A NEW RECORD'S TIMESTAMPS. A `db_insert` that leaves out a required
      `createdAt` / `updatedAt` time gets `$now`: a record is made and last
      changed at the moment it is made.
    - A START STEP'S TRIGGER. A `trigger` step with no `config.type` gets the
      kind its workflow declares (`trigger.kind`), when that is a catalog one.
    - PUSH WHERE THERE IS NONE. A notification sending by `push` in an app
      that does not send push sends in the app instead.

    Returns what was mended, a line each. Never anything that needs judging:
    the author is still asked about everything else."""
    doc = doc or {}
    said: list[str] = []
    try:
        from services.catalog import workflow_nodes
        catalog = workflow_nodes()
        trigger_kinds = set(catalog.variants("trigger") or [])
    except Exception:  # noqa: BLE001 — without the catalog, that mend is skipped
        trigger_kinds = set()
    mobile = doc.get("mobile") if isinstance(doc.get("mobile"), dict) else {}
    push_on = mobile.get("push") is True or any(
        p.section == "mobile" and isinstance(p.body, dict) and p.body.get("push") is True for p in result.proposals)
    entities = [e for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)]

    def entity_for(table: Any) -> dict | None:
        t = str(table or "").strip().lower()
        return next((e for e in entities if t and t in (str(e.get("table") or "").lower(),
                                                         str(e.get("name") or "").lower())), None)

    def unbrace(node: Any, where: str) -> Any:
        if isinstance(node, str):
            m = _SENTINEL_IN_BRACES.match(node)
            if m and m.group(1) in SENTINELS:
                said.append(f"{where}: {node.strip()} is {m.group(1)}")
                return m.group(1)
            return node
        if isinstance(node, dict):
            return {k: unbrace(v, where) for k, v in node.items()}
        if isinstance(node, list):
            return [unbrace(v, where) for v in node]
        return node

    def mend_steps(steps: list, name: str, trigger: dict) -> None:
        for st in steps or []:
            if not isinstance(st, dict):
                continue
            where = f"{name}/{st.get('key') or st.get('id')}"
            cfg = st.get("config") if isinstance(st.get("config"), dict) else None
            if cfg is not None:
                st["config"] = cfg = unbrace(cfg, where)
            if st.get("type") == "trigger" and trigger_kinds:
                cfg = st.setdefault("config", {}) if cfg is None else cfg
                kind = str(trigger.get("kind") or "")
                if not cfg.get("type") and kind in trigger_kinds:
                    cfg["type"] = kind
                    said.append(f"{where}: starts on its workflow's {kind} trigger")
                if cfg.get("type") == kind:
                    for k in ("cron", "event", "timezone", "on"):  # what that trigger already says
                        if trigger.get(k) and not cfg.get(k):
                            cfg[k] = trigger[k]
                    # A record-change start names the record type's table; the
                    # trigger names the record type.
                    if kind == "db_change" and not (cfg.get("table") or cfg.get("model")) and trigger.get("entity"):
                        ent = next((e for e in entities if str(e.get("id")) == str(trigger["entity"])), None)
                        if ent and (ent.get("table") or ent.get("name")):
                            cfg["table"] = str(ent.get("table") or ent.get("name"))
                            said.append(f"{where}: watches {cfg['table']}, the record type its trigger names")
            if cfg is None:
                continue
            if cfg.get("actionType") == "db_insert" and isinstance(cfg.get("values"), dict):
                ent = entity_for(cfg.get("table"))
                for f in (ent or {}).get("fields") or []:
                    fname = str(f.get("name") or "")
                    ftype = str(f.get("type") or "").lower()
                    if (f.get("required") and _norm_name(fname) in _STAMPS and fname not in cfg["values"]
                            and ("date" in ftype or "time" in ftype)):
                        cfg["values"][fname] = "$now"
                        said.append(f"{where}: {fname} is $now")
            channels = cfg.get("channels")
            if not push_on and isinstance(channels, list) and "push" in [str(c) for c in channels]:
                rest = [c for c in channels if str(c) != "push"]
                cfg["channels"] = rest or ["in_app"]
                said.append(f"{where}: sends in the app, not by push (the app does not send push)")
            if cfg.get("actionType") == "for_each" and isinstance(cfg.get("steps"), list):
                mend_steps(cfg["steps"], name, trigger)

    for p in result.proposals:
        if p.section == "workflows" and isinstance(p.body, dict):
            name = str(p.body.get("name") or p.natural_key)
            trigger = p.body.get("trigger") if isinstance(p.body.get("trigger"), dict) else {}
            mend_steps(p.body.get("steps") or [], name, trigger)
            said += _record_fields_by_entity(p.body, doc, name)
    return said


_TEMPLATE_INNER = re.compile(r"\{\{(.*?)\}\}")
_BARE_NAME = re.compile(r"^\s*([A-Za-z_]\w*)((?:\.[\w\[\]]+)*)\s*$")


def _record_fields_by_entity(body: dict, doc: dict, name: str) -> list[str]:
    """In a process a record change starts, `{{guestName}}` — a field of the
    record that changed, and no input, step or variable of the process — is
    `{{entity.guestName}}`: the engine holds the record under `entity` and
    nothing under the bare name (pah7lhfz's case hand-off, sixteen refusals,
    2026-10-20). A name that is also anything else is left for the author."""
    from services.blueprint.functional_completeness import RECORD_EVENT_ROOTS, record_event
    roots, changed = record_event(doc, body)
    if changed is None:
        return []
    fields = {str(f.get("name")) for f in changed.get("fields") or [] if isinstance(f, dict) and f.get("name")}
    fields |= {"id"}
    steps = [st for st in body.get("steps") or [] if isinstance(st, dict)]
    taken = ({str(i.get("name")) for i in body.get("inputs") or [] if isinstance(i, dict)}
             | {str(st.get("key") or st.get("id")) for st in steps}
             | {str((st.get("config") or {}).get("variableName")) for st in steps if isinstance(st.get("config"), dict)}
             | set(roots) | set(RECORD_EVENT_ROOTS))
    said: list[str] = []

    def side(text: str) -> str:
        m = _BARE_NAME.match(text)
        if not m or m.group(1) not in fields or m.group(1) in taken:
            return text
        said.append(f"{name}: {{{{{m.group(1)}}}}} is the changed record's {{{{entity.{m.group(1)}}}}}")
        return text.replace(m.group(1), f"entity.{m.group(1)}", 1)

    def fix(node: Any) -> Any:
        if isinstance(node, str):
            return _TEMPLATE_INNER.sub(lambda m: "{{" + "??".join(side(x) for x in m.group(1).split("??")) + "}}", node)
        if isinstance(node, dict):
            return {k: fix(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node

    for st in steps:
        if isinstance(st.get("config"), dict):
            st["config"] = fix(st["config"])
    return list(dict.fromkeys(said))


#: An id the contract asks for, by its prefix: `^ROLE-\d{3,}$` -> ROLE.
_ID_PATTERN = re.compile(r"^\^([A-Z]+)-\\d")


def _norm_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _names_to_ids(doc: dict) -> dict[str, dict[str, str]]:
    """Prefix -> every spelling of an artifact's name (name, route, table,
    natural key; case and spacing ignored) -> its id."""
    from services.blueprint.service import ARTIFACT_SECTIONS
    out: dict[str, dict[str, str]] = {}
    rows = [("ENTITY", e) for e in (doc.get("data") or {}).get("entities") or []]
    rows += [(prefix, a) for section, prefix in ARTIFACT_SECTIONS.items() for a in doc.get(section) or []]
    for prefix, a in rows:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        for k in ("name", "route", "table", "naturalKey", "title"):
            if a.get(k):
                out.setdefault(prefix, {}).setdefault(_norm_name(a[k]), str(a["id"]))
    return out


def tidy_for_contract(doc: dict, sections: set[str]) -> list[str]:
    """Mend, in the sections a reply wrote, what is the platform's to mend
    rather than the author's to be asked again about:

    - A FIELD THE CONTRACT DOES NOT HAVE is taken off. `confidence` and
      `status` on the security section, `issues` on a requirement: bookkeeping
      the author added, which nothing reads, and which refused a whole reply
      each time (f7kxusg6: five minutes of requirements, then the access step,
      2026-10-20).
    - AN ID ASKED FOR BY NAME is the id of the artifact with that name. A
      reply that creates the roles cannot name them by id — ids are given
      when the reply is filed — so its sign-in role map named them, and was
      refused for it on the strongest model's last try.

    Never anything else: a value that matches no artifact is left as it was,
    and the contract refuses it as before. Returns what was mended."""
    from services.blueprint.service import _load_validator
    validator = _load_validator()
    said: list[str] = []
    for _ in range(3):
        names = _names_to_ids(doc)
        changed = False
        for e in list(validator.iter_errors(doc)):
            path = list(e.path)
            if not path or str(path[0]) not in sections:
                continue
            where = "/".join(str(x) for x in path) or "<root>"
            if e.validator == "additionalProperties" and isinstance(e.instance, dict):
                props = set((e.schema or {}).get("properties") or {})
                pats = list(((e.schema or {}).get("patternProperties") or {}).keys())
                extra = [k for k in list(e.instance) if k not in props and not any(re.search(pt, k) for pt in pats)]
                for k in extra:
                    e.instance.pop(k, None)
                if extra:
                    said.append(f"{where}: left out {', '.join(extra)}")
                    changed = True
            elif e.validator == "pattern" and isinstance(e.instance, str):
                m = _ID_PATTERN.match(str(e.validator_value))
                found = names.get(m.group(1), {}).get(_norm_name(e.instance)) if m else None
                if found:
                    parent: Any = doc
                    for step in path[:-1]:
                        parent = parent[step]
                    parent[path[-1]] = found
                    said.append(f"{where}: {e.instance!r} is {found}")
                    changed = True
        if not changed:
            break
    return said


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
    if not proposals or _settled(result, "check_pattern_templates"):
        return
    bad: list = []

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
            bad.append(proposal)
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
            page_findings, ADVISORY_PAGE_RULES,
        )

        pages = {p.get("id"): p for p in (doc.get("pages") or [])}
        for proposal in proposals:
            page_id = proposal.body.get("page")
            # EVERY PAGE IS CONTEXT, ONE PAGE IS JUDGED. The rules read the
            # other pages to decide what THIS one owes — is there a form page
            # an Edit can go to, a record page a View can open, an id route
            # that puts a record in scope. Handing them this page alone made
            # the contract weaker than the observer's full-document check:
            # a list page without Edit was accepted here and flagged there.
            # So the page list is complete, and the findings are the page's.
            all_pages = [pages.get(page_id) or {"id": page_id, "route": page_id}] + [
                p for pid, p in pages.items() if pid != page_id]
            findings = page_findings({
                "pages": all_pages,
                "workflows": doc.get("workflows") or [],
                "data": doc.get("data") or {},
                # `security` carries the ownershipRules that mark inputs the
                # runtime fills from the session (organisationId, createdBy…).
                # Without it here the completeness check saw an empty manifest
                # and demanded a Form field for the caller's own tenant, so a
                # composed create page was refused for not collecting it.
                "security": doc.get("security") or {},
                "businessRules": [],
                "pageLayouts": [proposal.body],
            })
            # Advisory findings are surfaced but never REFUSE a composition — the
            # composer cannot fix an upstream/degradable cause, so blocking on
            # them only loops (see ADVISORY_PAGE_RULES).
            mine = [f["detail"] for f in findings
                    if f.get("rule") not in ADVISORY_PAGE_RULES and str(f.get("page")) == str(page_id)]
            problems.extend(mine)
            if mine and proposal not in bad:
                bad.append(proposal)

    if problems:
        def settle() -> list[str]:
            # A SCREEN THAT WILL NOT RENDER IS NOT SHIPPED, AND IS WRITTEN AFTER.
            # Its layout is left out, so the screen counts as unbuilt, and the
            # page repair that follows every build writes it (`page_repair`).
            gone = bad or proposals
            result.proposals = [p for p in result.proposals if p not in gone]
            settle_check(result, "check_pattern_templates")
            names = {str(pg.get("id")): str(pg.get("route") or pg.get("name")) for pg in (doc or {}).get("pages") or []
                     if isinstance(pg, dict)}
            return [f"{names.get(str(p.body.get('page')), p.body.get('page'))} is written after the build: its "
                    "layout could not be composed" for p in gone]
        raise InvalidPatternTemplate(_all_of(problems), settle=settle)


#: EVERY FAULT IN ONE REPLY, NOT THE FIRST FEW.
#:
#: A composer fixes what it is told about and re-authors the rest, so a fault
#: held back is a fault discovered on the next attempt — at the price of a
#: whole composition. The checks themselves have always accumulated; the joins
#: below then kept six of them and dropped the rest silently, which is the
#: same waste with a narrower window.
#:
#: Capped rather than unbounded because a reply is read by a model with a
#: context budget, and a page emitting forty faults has one cause rather than
#: forty. The cap says so out loud when it bites.
MAX_REPORTED_FAULTS = 40


def _all_of(problems: list[str], limit: int = MAX_REPORTED_FAULTS) -> str:
    """Every fault, joined, saying how many were held back if any were."""
    shown = "; ".join(problems[:limit])
    extra = len(problems) - limit
    return f"{shown}; (and {extra} more)" if extra > 0 else shown


def _canonical_key(alloc: Any, section: str, body: Mapping[str, Any],
                   model_key: str, page_routes: Mapping[str, str]) -> str:
    """The registry's key for this proposal.

    ``natural_key_for`` derives it from the body (route, name, prose). Where
    no scheme applies the model's key stands. Where the model's exact key is
    already bound and the canonical one is not — a document written before
    keys were canonicalised, resumed — the existing binding is kept, so an
    id never moves under a running application.
    """
    from services.blueprint.ids import natural_key_for

    canon = natural_key_for(section, body, page_routes=page_routes)
    if not canon or canon == model_key:
        return model_key
    if alloc.lookup(model_key) and not alloc.lookup(canon):
        return model_key
    return canon


def one_login(svc: BlueprintService) -> list[str]:
    """One entity is the person behind a login. When the document holds more
    than one marked `account: true` — a marketplace's Shopper and
    VendorAccount (7ttp60zi, 2026-10-11) — the first keeps it and the rest
    lose it, here, deterministically: the field author may not move the flag
    and a refusal it cannot satisfy stopped the build at the data model
    twice. Returns the names the flag was taken off."""
    live = [e for e in ((svc.doc.get("data") or {}).get("entities") or [])
            if isinstance(e, dict) and e.get("status") != "DEPRECATED" and e.get("account")]
    if len(live) < 2:
        return []
    keep, rest = live[0], live[1:]
    for e in rest:
        e.pop("account", None)
        note = (f"not the login — {keep.get('name')} is; a {e.get('name')} is a {keep.get('name')} with its own "
                "role, and this record holds what they have beyond the login")
        e["syncNote"] = note
    names = [str(e.get("name")) for e in rest]
    import logging
    logging.getLogger(__name__).warning("[one-login] %s is the login; `account` taken off %s",
                                        keep.get("name"), ", ".join(names))
    return names


def record_declines(svc: BlueprintService, result: AgentResult) -> list[dict]:
    """Change requests to `domainReference` carrying `proposed.declined`
    become declines by this agent; everything else is left as it was."""
    from services.blueprint.reference_coverage import record_declines as _record
    added: list[dict] = []
    for cr in result.change_requests or []:
        if getattr(cr, "section", "") != "domainReference":
            continue
        declines = (cr.proposed or {}).get("declined") if isinstance(cr.proposed, dict) else None
        if not isinstance(declines, list):
            continue
        for d in declines:
            if isinstance(d, dict) and not d.get("reason") and cr.reason:
                d = {**d, "reason": cr.reason}
            added += _record(svc, [d], by=result.agent)
    if added:
        svc.save()
    return added


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
    # A REFERENCE ITEM THIS PRODUCT DOES NOT NEED, SAID WITH A REASON. An agent
    # may not write `domainReference`; it returns a change request addressed
    # to it (§30), and this deterministic step records the decline, by name,
    # so the coverage check stops asking and the person sees who declined
    # what at the model gate.
    record_declines(svc, result)
    # THE COMPOSERS' WORDS INTO THE CONTRACT'S, BEFORE THE CONTRACT READS THEM.
    from services.blueprint.layout_vocabulary import translate_layout_vocabulary
    translate_layout_vocabulary(result, svc.doc)
    # EVERY CHECK, EVERY TIME, AND EVERY REFUSAL AT ONCE. The first refusal
    # used to end the checking, so the author heard one fault per attempt,
    # fixed it, and met the next: the access step of f7kxusg6 was refused for
    # its audit, then its sign-in, then its format — three attempts, three
    # different faults, a stopped build (2026-10-20).
    refusals: list[AuthorRefusal] = []

    def run(check: Callable[..., None], *args: Any) -> None:
        try:
            check(*args)
        except AuthorRefusal as exc:
            refusals.append(exc)

    mended = mend_mechanics(result, svc.doc)
    if mended:
        logger.info("[contract] mended before checking: %s", "; ".join(mended[:12]))
    from services.blueprint.mcp_catalog import load as _mcp_servers
    from services.blueprint.api_reference import load as _api_refs
    run(check_pattern_templates, result, svc.doc)
    run(check_workflow_steps, result, svc.doc, _mcp_servers(getattr(svc, "output_dir", None)),
        _api_refs(getattr(svc, "output_dir", None)))
    for check in (check_workflow_triggers, check_integrations, check_audit, check_tenancy, check_sign_in,
                  check_mobile, check_requirements, check_business_rules, check_entity_fields,
                  check_page_content, check_page_access, check_role_doors, check_navigation,
                  check_analytics, check_flows, check_security, check_design_modules,
                  check_drawn_routes):
        run(check, result, svc.doc)
    if refusals:
        raise refusals[0] if len(refusals) == 1 else SeveralRefusals(refusals)

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
    from services.blueprint.ids import IdAllocator, parse_id

    # WHAT THE DOCUMENT ALREADY HOLDS CAN BE NAMED TOO. The resolver used to
    # see only this batch: an author writing one entity's fields and stating
    # a foreign key to an entity declared by an earlier node had no way to
    # point at it but by its id, which it is forbidden to invent. The batch
    # outranks the document on a clash, so nothing an agent proposes is ever
    # redirected to something older.
    allocated: dict[str, str] = {}
    for existing in (svc.doc.get("data") or {}).get("entities") or []:
        if not isinstance(existing, dict) or not existing.get("id"):
            continue
        for alias in (existing.get("name"), existing.get("table")):
            if isinstance(alias, str) and alias:
                allocated.setdefault(alias, str(existing["id"]))
    page_routes = {
        page["id"]: page.get("route") or ""
        for page in (svc.doc.get("pages") or [])
        if isinstance(page, dict) and page.get("id")
    }
    with IdAllocator.session(output_dir=svc.output_dir) as alloc:
        for p in result.proposals:
            prefix = (
                "ENTITY" if p.section == "data.entities"
                else ARTIFACT_SECTIONS.get(p.section)
            )
            if not prefix:
                continue
            # IDENTITY IS READ OFF THE ARTIFACT, NOT TAKEN FROM THE MODEL.
            # Smith's change path has restated keys through `natural_key_for`
            # since §12 was wired; the agent path took the model's string as
            # given. Measured on a live build: "A member can see all of their
            # notes in one list." existed as six requirements under six
            # model-spelled keys, two of them still live — and a repair that
            # rephrased a key was an insert, not an update. The same route,
            # name or prose is the same artifact whatever the model called it.
            model_key = p.natural_key
            p.natural_key = _canonical_key(
                alloc, p.section, p.body, p.natural_key, page_routes)
            # A body id is honoured ONLY when it belongs to this section — a
            # resumed proposal carrying its own TEST-007 keeps it, and the batch
            # stays idempotent. But identity is assigned, not authored
            # (§12/§116): the testing agent cited the requirement it verifies
            # (`RULE-005`, `REQ-010`) in the id field, and honouring that put a
            # rule's id on a test, which the `^TEST-` contract refused — and,
            # once written, made every later write to the document fail. A
            # wrong-prefix id is dropped and a real one allocated.
            body_id = p.body.get("id")
            try:
                keep = bool(body_id) and parse_id(str(body_id))[0] == prefix
            except Exception:  # noqa: BLE001 — an unparseable id is not ours to keep
                keep = False
            artifact_id = str(body_id) if keep else alloc.allocate(prefix, p.natural_key)
            allocated[p.natural_key] = artifact_id
            # THE KEY THE MODEL CHOSE STAYS CITABLE. A role in the same batch
            # cites its permissions by the keys the agent gave them
            # ("PERM-create-note"); restating the key above and then mapping
            # only the restated one left every such citation unresolved, and
            # `security` failed the contract twice on a live build — a
            # regression the canonicalisation introduced the same morning.
            if model_key and model_key != p.natural_key:
                allocated.setdefault(model_key, artifact_id)
            if not keep and body_id:
                # ACTUALLY drop it — do not just allocate beside it. The
                # comment above promised a wrong-prefix id is dropped, but the
                # body kept it, and `upsert` honours a body id unless another
                # artifact already owns it. So a role carrying an entity id
                # (`roles/9/id: ENTITY-007`) reached the document and failed
                # CONTRACT validation, sinking the whole `security` node and
                # cascading to the app. Write the allocated id onto the body so
                # the artifact is KEPT with a valid identity rather than lost.
                p.body["id"] = artifact_id
            # Agents cite each other by the human name far more often than by
            # the natural key, so accept both.
            for alias in (p.body.get("name"), p.body.get("route"),
                          p.body.get("table")):
                if isinstance(alias, str) and alias:
                    allocated[alias] = artifact_id  # the batch outranks the document

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

        # THE MENU FOLLOWS THE SCREENS. Pages name the menu entry they answer
        # (`menuEntry`); the entry is linked here, when they land, so the
        # rail never holds labels that go nowhere (`menu_binding`).
        if any(p.section == "pages" for p in result.proposals):
            from services.blueprint.menu_binding import bind_menu
            bind_menu(svc.doc)

        # §17 middle band: proceed, but the assumption must be on the record.
        recorded: list[str] = []
        if result.confidence < AUTO_DECIDE and result.assumptions:
            recorded = list(result.assumptions)

        tidied = tidy_for_contract(svc.doc, {p.section.split(".", 1)[0] for p in result.proposals})
        if tidied:
            logger.info("[contract] tidied before validation: %s", "; ".join(tidied[:12]))
        svc.validate()
    except Exception as exc:
        # Restored in place: callers and the orchestrator hold this dict, so
        # rebinding the attribute would leave them on the poisoned copy.
        svc.doc.clear()
        svc.doc.update(snapshot)
        raise _blamed(exc, svc) from exc

    if any(p.section == "data.entities" for p in result.proposals):
        one_login(svc)

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
