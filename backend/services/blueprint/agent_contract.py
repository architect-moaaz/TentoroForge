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
       "pageLayouts", "pageCode", "composition", "completeness"}
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
    whole build down."""


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
    # `designSources` because a connected design DRAWS the navigation — its
    # sidebar is the same subtree on every screen — and the agent that authors
    # `navigation.tree` could not see it, so every Figma app got the generic
    # sidebar with the design's own rail rendered inside each page (§48).
    "solution_architecture": {"requirements", "pages", "designSources"},

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

    # The analytics each page carries, over the data the pages show and the
    # processes that move it — the states a workflow changes are what a
    # dashboard counts.
    "analytics": {"requirements", "product", "data", "pages", "roles",
                  "workflows", "security"},

    # §100 — permissions guard entities, pages and workflow execution.
    "security": {"requirements", "data", "pages", "workflows"},

    "integration": {"requirements"},

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
    "domain_intelligence": _cap("domain_intelligence", {"product"}),
    "product_analysis": _cap("product_analysis", {"product", "requirements"}),
    "solution_architecture": _cap("solution_architecture", {"modules", "navigation"}),
    # §30, verbatim: may compose pages, select patterns, define UI interactions,
    # use A2UI MCP, update UI-related Blueprint information. May NOT touch
    # business rules, database schema, security rules or role permissions.
    "page_design": _cap(
        "page_design",
        {"pages", "navigation"},
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


def check_workflow_steps(result: "AgentResult", doc: dict | None = None) -> None:
    """Reject workflows whose steps are not configured catalog nodes.

    The same argument as :func:`check_pattern_templates`: accepting a step
    whose config the engine cannot execute and repairing it later is how the
    old chain grew its regeneration passes. A step is a node from the catalog
    carrying what that node declares it needs; anything else is refused here,
    with the missing keys named, so the agent is asked again.
    """
    proposals = [p for p in result.proposals if p.section == "workflows"]
    if not proposals:
        return

    from services.catalog import workflow_nodes

    catalog = workflow_nodes()
    problems: list[str] = []
    for proposal in proposals:
        name = proposal.body.get("name") or proposal.natural_key
        problems.extend(f"{name}/{e}" for e in catalog.workflow_errors(proposal.body))
    # WOULD THE ENGINE RUN IT. A step whose condition the engine's parser
    # refuses, a function the engine lacks, a template naming what the engine
    # never holds — each is a workflow the author can fix now and nobody can
    # fix later. Checked here, at the author, never at the pages that bind it.
    from services.blueprint.functional_completeness import authoring_findings
    problems.extend(f["detail"] for f in authoring_findings(
        {"workflows": [p.body for p in proposals], "businessRules": [],
         "data": (doc or {}).get("data") or {}}))
    if problems:
        raise InvalidWorkflowStep(_all_of(problems))


class InvalidEntityFields(AuthorRefusal):
    """An entity's fields cannot be stored as proposed."""


#: What a vector field may be taken of: a picture, or words.
EMBEDDABLE_TYPES = frozenset({"image", "string", "text"})


def check_entity_fields(result: "AgentResult", doc: dict | None = None) -> None:
    """A `vector` field names the image or text field of the same entity it is
    taken of. 036farqu: Tool and ConditionEvidence came back with
    `embedding: {of: ""}`, the contract refused the whole document, and the
    retry was told only "'' should be non-empty" — ConditionEvidence ended with
    no columns at all. Refused here instead, naming the fields it could be."""
    problems: list[str] = []
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
    # THE ACCOUNT ENTITY: at most one, and signup must be able to create it —
    # a required reference to another record is a field no one can fill when
    # the account is made.
    live = [e for e in ((doc or {}).get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("status") != "DEPRECATED"]
    for proposal in (p for p in result.proposals if p.section == "data.entities"):
        body = proposal.body if isinstance(proposal.body, dict) else {}
        name = body.get("name") or proposal.natural_key
        same = lambda e: e.get("name") == name or str(e.get("id")) == str(proposal.natural_key)
        # The flag is set with the entity set; the fields arrive per entity
        # later and need not repeat it.
        if not (body.get("account") or any(e.get("account") and same(e) for e in live)):
            continue
        other = next((e for e in live if e.get("account") and not same(e)), None)
        if body.get("account") and other is not None:
            problems.append(f"{name}: `account: true` is already on {other.get('name')} — one entity is the "
                            "person behind a login")
        from services.blueprint.projection import _is_credential_field
        for f in body.get("fields") or []:
            # THE LOGIN HOLDS THE PASSWORD. 0l133sp2's Member carried a required
            # `passwordHash`; signup creates the row without one, so every
            # signup would have been refused by the database.
            if isinstance(f, dict) and _is_credential_field(f.get("name")):
                problems.append(f"{name}.{f.get('name')}: the person's login already holds their password — "
                                "remove this field; the account entity never stores a credential")
            if isinstance(f, dict) and f.get("references") and f.get("required"):
                problems.append(f"{name}.{f.get('name')}: the account entity's row is created at signup, when no "
                                "other record exists to point at — make this reference optional")
    if problems:
        raise InvalidEntityFields(_all_of(problems))


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


class InvalidBusinessRule(AuthorRefusal):
    """A rule the engine could not evaluate as written."""


def check_business_rules(result: "AgentResult", doc: dict | None) -> None:
    """A rule names an entity the data model has, fields that entity has, and
    a condition the engine's parser reads — refused at the author, with the
    fault named, never at the forms that later fire it."""
    proposals = [p for p in result.proposals if p.section == "businessRules"]
    if not proposals:
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
        raise InvalidBusinessRule("; ".join(problems))


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
    ent = ents.get(str(req.get("entity") or ""))
    if ent is None:
        out.append("`requires.entity` must name the entity whose record satisfies it")
    else:
        cols = {str(f.get("name")) for f in ent.get("fields") or []}
        acct = str(req.get("account") or "")
        if acct not in cols:
            out.append(f"`requires.account` must be the field of {ent.get('name')} holding the person's "
                       f"account id (one of: {', '.join(sorted(cols)) or 'none'})")
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
            problems.extend(f["detail"] for f in findings
                            if f.get("rule") not in ADVISORY_PAGE_RULES
                            and str(f.get("page")) == str(page_id))

    if problems:
        raise InvalidPatternTemplate(_all_of(problems))


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
    # THE COMPOSERS' WORDS INTO THE CONTRACT'S, BEFORE THE CONTRACT READS THEM.
    from services.blueprint.layout_vocabulary import translate_layout_vocabulary
    translate_layout_vocabulary(result, svc.doc)
    check_pattern_templates(result, svc.doc)
    check_workflow_steps(result, svc.doc)
    check_business_rules(result, svc.doc)
    check_entity_fields(result, svc.doc)
    check_page_content(result, svc.doc)
    check_navigation(result, svc.doc)

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
