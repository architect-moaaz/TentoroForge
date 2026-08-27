"""Agent orchestration (PRD §26, §28, §71, §72, §94, §102, §103).

§28 is blunt about the failure mode: *"Agents shall not operate in an
uncontrolled swarm."* The plan is a dependency graph, independent work runs
concurrently, and everything else waits its turn.

This module owns the graph and the schedule. It does not call a model — agents
are injected as a callable, so the orchestration logic is deterministic and
testable without a single LLM round-trip. That is §116 applied to control flow:
the model decides *what* an artifact should be, this decides *when* it is built
and *whether* the result is allowed in.

Four responsibilities
---------------------
* **The DAG** (§28) — declared node dependencies, resolved into concurrency
  levels. A cycle is a startup error, not a hang.
* **The state machine** (§94) — *"the orchestration engine controls allowed
  state transitions"*. Illegal transitions raise.
* **Impact analysis** (§71) — given what changed, which artifacts are affected.
  Walks the same reference edges the verification matrix checks, because the
  Application Knowledge Graph (§19) is derived from artifact references rather
  than stored separately.
* **Incremental runs** (§72) — *"avoid rebuilding the entire application for
  every user request"*. Impacted artifacts select a sub-DAG.

Every agent result is committed through :func:`apply_agent_result`, so §30
capability boundaries are enforced here by construction: an orchestrator cannot
route work to an agent in a way that lets it write outside its domain.

On §28's diagram
----------------
The PRD's graph names tiers (Data Model, UX Architecture, Backend, Frontend…)
rather than all eighteen agents of §27. Workflow, business-rules and security
agents appear in §107 step 16 but not in the §28 picture. The DAG below keeps
§28's shape and slots the missing agents into the tier §107 puts them in; those
placements are marked and are the parts to argue with.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from services.blueprint.agent_contract import (
    AgentResult,
    InvalidPatternTemplate,
    apply_agent_result,
    capability_for,
)
from services.blueprint.service import BlueprintInvalid, BlueprintService

# ---------------------------------------------------------------------------
# §94 — application state machine
# ---------------------------------------------------------------------------

STATES: tuple[str, ...] = (
    "DISCOVERY", "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW", "PLANNING",
    "PLAN_REVIEW", "IMPLEMENTATION", "DATABASE_PROVISIONING", "BUILD",
    "VERIFICATION", "PREVIEW", "ITERATION", "READY", "EXPORT_DEPLOY",
    "MAINTENANCE",
)

#: Legal transitions. The forward path is §94's sequence; the extra edges are
#: the loops the rest of the document requires — §73's verify→repair→verify,
#: §70's preview→change→rebuild, and §114's maintenance-time modification.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERY": frozenset({"CLARIFICATION"}),
    "CLARIFICATION": frozenset({"DEFINITION", "DISCOVERY"}),
    "DEFINITION": frozenset({"BLUEPRINT_REVIEW", "CLARIFICATION"}),
    "BLUEPRINT_REVIEW": frozenset({"PLANNING", "DEFINITION"}),
    "PLANNING": frozenset({"PLAN_REVIEW"}),
    "PLAN_REVIEW": frozenset({"IMPLEMENTATION", "PLANNING"}),
    "IMPLEMENTATION": frozenset({"DATABASE_PROVISIONING"}),
    "DATABASE_PROVISIONING": frozenset({"BUILD"}),
    "BUILD": frozenset({"VERIFICATION", "IMPLEMENTATION"}),   # §102 build failure
    "VERIFICATION": frozenset({"PREVIEW", "IMPLEMENTATION"}),  # §73 repair loop
    "PREVIEW": frozenset({"ITERATION", "READY"}),
    "ITERATION": frozenset({"IMPLEMENTATION", "PREVIEW", "READY"}),
    "READY": frozenset({"EXPORT_DEPLOY", "ITERATION"}),
    "EXPORT_DEPLOY": frozenset({"MAINTENANCE", "READY"}),
    "MAINTENANCE": frozenset({"ITERATION"}),                   # §114
}


class IllegalTransition(ValueError):
    """§94 — the orchestration engine controls allowed state transitions."""


def can_transition(src: str, dst: str) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, frozenset())


def transition(svc: BlueprintService, dst: str) -> str:
    """Move the application to ``dst``, or refuse."""
    src = svc.doc.get("state", "DISCOVERY")
    if dst not in STATES:
        raise IllegalTransition(f"{dst!r} is not a §94 state")
    if src == dst:
        return dst
    if not can_transition(src, dst):
        raise IllegalTransition(
            f"{src} → {dst} is not permitted; from {src} you may go to "
            f"{', '.join(sorted(ALLOWED_TRANSITIONS.get(src, ()))) or '<nowhere>'}"
        )
    svc.doc["state"] = dst
    svc.save()
    return dst


# ---------------------------------------------------------------------------
# §28 — the agent dependency DAG
# ---------------------------------------------------------------------------

#: What actually performs a node's work.
#:
#: ``agent``     — a model call through the executor.
#: ``service``   — deterministic platform code. Verification is the §75 matrix,
#:                 not an opinion; routing it through a model would be a
#:                 category error, and its agent writes nothing so any proposal
#:                 it made would be refused anyway.
#: ``projection`` — writes the Blueprint out as artifacts a fixed runtime
#:                 reads. The generated app is not bespoke source: it is a
#:                 scaffold plus vendored engines (data, workflow, UI
#:                 rendering) that interpret Blueprint-derived files at run
#:                 time. So these nodes emit *data* — page schemas, workflow
#:                 definitions, an ORM schema, design tokens, nav flow — not
#:                 code. That makes them deterministic, like every other
#:                 service node; nothing here needs a model.
#:
#:                 The projection is not ported into this package yet, so they
#:                 report blocked. What they are blocked on is porting, not
#:                 inventing a code generator.
NODE_KINDS = ("agent", "service", "projection")


#: What each projection node writes, and which engine consumes it. Grounded in
#: the existing stack: ``services/app_emitter.py`` vendors these packages into
#: ``vendor/@tentoroforge/`` and the scaffold reads their output at runtime.
PROJECTIONS: dict[str, tuple[str, str]] = {
    "backend": ("data.entities + relationships + constraints -> ORM schema, "
                "migrations, seed", "data engine"),
    "frontend": ("pages + components + widgets -> page schemas; navigation -> "
                 "nav-flow.json; designSystem -> tokens", "@tentoroforge/engine"),
    "integration": ("workflows + businessRules -> workflow definitions and "
                    "route wiring", "workflow engine"),
    "preview": ("runtime config + a running container", "build/preview service"),
}


@dataclass(frozen=True)
class DagNode:
    key: str
    agent: str
    depends_on: frozenset[str] = frozenset()
    #: Blueprint sections this node is responsible for producing. Used by §72
    #: to decide which nodes an incremental change needs to re-run.
    produces: frozenset[str] = frozenset()
    note: str = ""
    kind: str = "agent"
    #: Author one artifact per subject instead of one for the whole app.
    #: Names a key in :data:`FANOUT`, which resolves the subjects from the
    #: Blueprint. A node without it runs exactly once, as before.
    fanout: str = ""


def _n(key, agent, depends_on=(), produces=(), note="", kind="agent",
       fanout="") -> DagNode:
    return DagNode(key, agent, frozenset(depends_on), frozenset(produces),
                   note, kind, fanout)


#: §28's graph. Tier names follow the PRD's diagram.
DAG: dict[str, DagNode] = {n.key: n for n in (
    _n("requirements", "requirement", (), ("requirements",)),
    _n("application_model", "product_analysis", ("requirements",), ("product",)),

    # left branch — data
    _n("data_model", "data_model", ("application_model",), ("data.entities",)),
    _n("database", "data_model", ("data_model",), ("database",)),
    # Derived, not authored: mutations from workflows, reads from the data
    # engine, analytics from widgets. See services.blueprint.api_derivation.
    _n("apis", "api", ("database", "workflows", "page_contracts"), ("apis",),
       kind="service",
       note="endpoints are implied by entities + workflows + widgets"),
    _n("backend", "backend", ("apis",), ("codeMap",), kind="projection"),

    # right branch — experience
    _n("ux_architecture", "solution_architecture", ("application_model",),
       ("modules", "navigation")),
    # §37 — the design language, authored before anything composes against it.
    # It had owners (accessibility, figma_intelligence) but no node, so nobody
    # ever invoked them and `designSystem` stayed empty through every run —
    # which is also what blocks the theme-token projection.
    _n("design_system", "accessibility", ("application_model",), ("designSystem",),
       note="§37; must precede page design so composition has a language"),
    _n("page_contracts", "page_design", ("ux_architecture", "data_model"), ("pages",)),
    _n("page_designs", "page_design", ("page_contracts",), ("components", "uiRegistry")),
    # §34 — one template per pattern the pages actually use, so the model call
    # count follows the pattern vocabulary rather than the page count.
    _n("patterns", "a2ui_patterns", ("page_contracts", "page_designs", "design_system"),
       ("patternTemplates",),
       note="§34; structure per pattern, instantiated per page by the planner"),
    # One call per page. Runs after `patterns` so a page that nobody authors
    # individually still has a template to fall back on — the two coexist, and
    # the projection prefers the authored tree where one exists.
    _n("page_layouts", "a2ui_pages", ("patterns",), ("pageLayouts",),
       fanout="pages",
       note="§34; one authored tree per page, gated on the same catalog"),
    _n("frontend", "frontend", ("page_layouts",), ("codeMap",), kind="projection",
       note="pattern templates + page contracts -> engine page schemas"),

    # §107 step 16 places workflow and rules alongside backend/API generation;
    # §28's diagram folds them into "Backend". Split out so each agent keeps
    # its own §30 boundary.
    # These depend on the data model, not on endpoints. The original edge ran
    # the other way, which became a cycle the moment endpoints were derived
    # *from* workflows — and the derivation is the correct direction: a
    # workflow describes what the business does, an endpoint is how it is
    # reached.
    _n("workflows", "workflow", ("data_model", "page_contracts"), ("workflows",),
       note="§107 step 16; not a distinct box in §28"),
    _n("business_rules", "business_rules", ("data_model",), ("businessRules",),
       note="§107 step 16; not a distinct box in §28"),
    _n("security", "security", ("data_model",), ("security", "roles", "permissions"),
       note="§100; placed after the data model because permissions guard entities"),
    _n("integrations", "integration", ("application_model",), ("integrations",)),

    # join
    _n("integration", "backend",
       ("backend", "frontend", "workflows", "business_rules", "security", "integrations"),
       (), kind="projection"),
    _n("testing", "testing", ("integration",), ("tests",)),
    # §20 + §23 — both read off what the Blueprint already carries, so neither
    # is an agent. Placed after authoring and before verification, so the
    # verification report is made against a document that knows what it assumed.
    _n("memory", "memory", ("testing",), ("decisions", "completeness"),
       kind="service",
       note="§20 decision memory + §23 completeness, both derived"),
    _n("verification", "verification", ("memory",), (), kind="service"),
    _n("preview", "build", ("verification",), ("runtime",), kind="projection"),
)}


#: How a fanning-out node finds its subjects. Kept here rather than in the node
#: so the DAG stays a description of shape, not a place where documents are
#: read.
FANOUT: dict[str, Any] = {
    "pages": lambda doc: [
        p["id"] for p in (doc.get("pages") or [])
        if p.get("id") and p.get("status") != "DEPRECATED"
    ],
}


def subjects_for(node: "DagNode", doc: dict) -> list[str]:
    """The subjects a node authors for. ``[""]`` means "once, for the app"."""
    if not node.fanout:
        return [""]
    resolve = FANOUT.get(node.fanout)
    if resolve is None:
        raise KeyError(f"node {node.key!r} declares unknown fanout {node.fanout!r}")
    return resolve(doc) or []


class CyclicDag(ValueError):
    pass


def levels(nodes: dict[str, DagNode] = DAG) -> list[list[str]]:
    """Topological generations — each list may execute concurrently (§28).

    Raises rather than looping forever: a cycle in the build plan is a
    programming error that should surface at startup, not at 3am.
    """
    remaining = {k: set(v.depends_on) & set(nodes) for k, v in nodes.items()}
    out: list[list[str]] = []
    while remaining:
        ready = sorted(k for k, deps in remaining.items() if not deps)
        if not ready:
            raise CyclicDag(f"cycle among: {', '.join(sorted(remaining))}")
        out.append(ready)
        for k in ready:
            del remaining[k]
        for deps in remaining.values():
            deps.difference_update(ready)
    return out


def descendants(key: str, nodes: dict[str, DagNode] = DAG) -> set[str]:
    """Every node that transitively depends on ``key``."""
    found: set[str] = set()
    frontier = {key}
    while frontier:
        nxt = {k for k, n in nodes.items()
               if n.depends_on & frontier and k not in found}
        found |= nxt
        frontier = nxt
    return found


# ---------------------------------------------------------------------------
# §71 — impact analysis
# ---------------------------------------------------------------------------

def _entities(doc: dict) -> list[dict]:
    return doc.get("data", {}).get("entities", []) or []


#: Sections whose artifacts participate in the §19 Application Knowledge Graph.
GRAPH_SECTIONS: tuple[str, ...] = (
    "pages", "apis", "workflows", "businessRules", "components", "widgets",
    "tests", "roles", "permissions", "modules", "integrations", "requirements",
    "codeMap",
)


def refs_of(art: dict) -> set[str]:
    """The artifact IDs one artifact points at — one edge set, §19's graph.

    Deliberately module-level rather than a closure inside impact analysis.
    Traceability (§18) asks "what does REQ-034 reach" and impact analysis (§71)
    asks "what does changing ENTITY-008 disturb"; those are two directions
    through *the same* graph. Two copies of this function would let the two
    answers drift apart, and the drift would be invisible — impact analysis
    would skip regenerating something traceability still claimed was covered.
    """
    out: set[str] = set()
    for key in ("requirements", "decisions", "appliesTo", "verifies",
                "launchedFrom", "supportingEntities", "components", "pages",
                "permissions", "users"):
        out.update(art.get(key) or [])
    for key in ("entity", "permission", "module", "primaryEntity", "artifact"):
        val = art.get(key)
        if isinstance(val, str):
            out.add(val)
    data = art.get("data")
    if isinstance(data, dict):
        for key in ("primaryEntity",):
            if isinstance(data.get(key), str):
                out.add(data[key])
        out.update(data.get("supportingEntities") or [])
    for step in art.get("steps") or []:
        if isinstance(step, dict) and isinstance(step.get("entity"), str):
            out.add(step["entity"])
    return out


def graph_pool(doc: dict) -> list[tuple[str, dict]]:
    """Every graph-participating artifact as ``(section, artifact)``."""
    pool = [(s, a) for s in GRAPH_SECTIONS for a in (doc.get(s) or [])]
    pool += [("data.entities", e) for e in _entities(doc)]
    return pool


def impacted_artifacts(
    doc: dict, changed: Iterable[str], *, depth: int | None = None,
) -> set[str]:
    """Artifacts affected by a change, per §71.

    Walks reference edges, so a change to an entity reaches the endpoints that
    serve it, the pages that display it, the workflows that mutate it and the
    tests that cover them.

    ``depth`` bounds how many hops out it goes. ``None`` runs to a fixed point,
    which is the conservative answer and the default — for deciding what to
    *re-verify*, reaching too far only costs time.

    For deciding what to *show the user* and what to regenerate, the fixed
    point is useless. Measured on the ATS fixture: one entity reaches 100+
    artifacts, because every page belongs to a module and every module contains
    every other page, so the closure is nearly the whole application whatever
    you start from. §71's own example is five artifacts, and §72 exists to
    "avoid rebuilding the entire application for every user request" — an
    unbounded answer silently rebuilds it. Callers that need §71's shape pass a
    small depth.
    """
    affected = set(changed)
    frontier = set(affected)
    hops = 0

    while frontier and (depth is None or hops < depth):
        hops += 1
        nxt: set[str] = set()
        for _section, art in graph_pool(doc):
            art_id = art.get("id") or art.get("artifact")
            if not art_id or art_id in affected:
                continue
            if refs_of(art) & frontier:
                nxt.add(art_id)
        affected |= nxt
        frontier = nxt
    return affected


def sections_of(doc: dict, artifact_ids: Iterable[str]) -> set[str]:
    """Which Blueprint sections a set of artifacts lives in.

    Walks the same pool the graph does. Iterating a private list here instead
    would let a section be reachable by impact analysis but never selected for
    regeneration — the artifact would be reported as affected and then quietly
    not rebuilt.
    """
    wanted = set(artifact_ids)
    out: set[str] = set()
    for section, art in graph_pool(doc):
        if section == "codeMap":
            # Not authored by any node; it is what the projections emit.
            continue
        if art.get("id") in wanted:
            out.add(section)
    return out


# ---------------------------------------------------------------------------
# §72 — incremental DAG
# ---------------------------------------------------------------------------

#: §72's own enumeration of what an incremental change affects:
#:
#:     affected requirements, pages, components, entities, APIs, workflows,
#:     rules, tests, source files, database migrations
#:
#: plus the permissions §71's worked example lists under NEW, and the runtime
#: §70 rebuilds at the end of the pipeline.
#:
#: What it leaves out is the interesting part. ``product``, ``designSystem``,
#: ``modules``, ``navigation`` and ``integrations`` are the application's
#: *frame* — what it is, what it looks like, how it is organised, what it talks
#: to. §72 does not list them because adding a business rule does not change
#: any of them.
INCREMENTAL_SECTIONS: frozenset[str] = frozenset({
    "requirements", "pages", "components", "widgets", "pageLayouts",
    "patternTemplates", "data.entities", "data.relationships",
    "data.constraints", "apis", "workflows", "businessRules", "tests",
    "codeMap", "database", "runtime", "roles", "permissions", "security",
})


def is_foundational(node: DagNode) -> bool:
    """True when re-running this node would re-author the application's frame.

    Derived from what the node produces rather than listed by name, so a node
    added to the DAG later classifies itself. ``patternTemplates`` counts as
    incremental — §72 says "components", and a pattern template is a
    composition of them.

    Only meaningful for agent nodes; service and projection nodes are
    deterministic and cheap, and a projection that does not run leaves the
    application unbuilt.
    """
    return (
        node.kind == "agent"
        and bool(node.produces)
        and not (node.produces & INCREMENTAL_SECTIONS)
    )


def incremental_plan(
    doc: dict, changed: Iterable[str], *,
    also_sections: Iterable[str] = (),
    already_written: Iterable[str] = (),
) -> list[str]:
    """The sub-DAG needed for a change — §72's 'only affected artifacts'.

    Nodes producing an impacted section are re-run, plus everything downstream
    of them. Verification is always included: a change that skipped
    re-verification would leave the §75 matrix asserting a state that no longer
    holds.

    ``also_sections`` covers what §71 calls NEW. An artifact that does not exist
    yet has no section membership to discover, so a change that only *adds*
    things — "add a manager approval step" — would otherwise select an empty
    plan and regenerate nothing. The caller names the sections the new work
    lands in and they seed the plan alongside the impacted ones.

    Foundational nodes (:func:`is_foundational`) are reached only by being
    seeded — never by propagation. Without that, ``descendants`` makes every
    plan the whole DAG, because the graph is a chain::

        requirements -> application_model -> {design_system, integrations,
                                              ux_architecture} -> everything

    so adding one business rule re-authored the design language and the
    integrations list. Measured on ats-live: 19 of 22 nodes for a change that
    added two rules and a field.

    The cut is safe in this DAG's shape, not merely cheap. ``ux_architecture``
    produces ``navigation`` and runs *before* ``page_contracts`` — re-running
    it after a page changed would not see the new page anyway, because
    navigation is authored upstream of pages by construction. And when the
    frame really does move, Smith writes to those sections and the node is
    seeded directly.

    What this gives up is caught rather than lost: a gap between the frame and
    the artifacts is what the §75 matrix is for, and ``verification`` always
    re-runs. §76 flags it instead of a rebuild hiding it.

    ``already_written`` names sections this change has *just authored*. Their
    producing nodes are dropped from the plan; everything downstream stays,
    because downstream genuinely has to consume the new artifacts.

    This is a correctness rule, not an optimisation. When Smith writes a
    business rule from the user's own words (§20), re-running the
    ``business_rules`` agent over the same Blueprint has it re-author that
    section — and §20 is explicit that "future agents must respect accepted
    decisions unless deliberately changed". Regeneration is not a deliberate
    change. Without this, answering a question and having the answer quietly
    overwritten is a single turn away.
    """
    written = set(also_sections)
    # Seeded from what actually changed, NOT from the impact closure.
    #
    # `impacted_artifacts` answers "what might be affected" — the question §71
    # reports to the user. Seeding the plan from it conflates that with "this
    # section's owner must re-author its catalogue", and the two are different
    # claims. On ats-live, changing one component closes over to
    # {businessRules, components, modules, pages, tests, workflows}: a rule is
    # in there because it references a page that contains the component. That
    # made `business_rules` re-author the rule catalogue because a table was
    # made more compact — and `business_rules` depends only on `data_model`, so
    # a component is not one of its inputs at all.
    #
    # Directly: {components, pages}. Propagation to the nodes that really do
    # read those is what `descendants` is for.
    touched_sections = sections_of(doc, set(changed)) | written

    # Two seed rules, because "disturbed by" and "needs re-authoring" are not
    # the same claim.
    #
    # An incremental node is seeded by either: a page whose component changed
    # has to be re-contracted.
    #
    # A foundational node is seeded only by what the change *writes*. Impact
    # analysis reaches a MODULE because that module contains the page that
    # changed — a containment edge, not a dependency — and `sections_of` then
    # reports `modules` as touched. Seeding `ux_architecture` off that has it
    # re-author the module and navigation structure because a table was made
    # more compact. When the frame genuinely moves, Smith writes `modules` and
    # the node is seeded properly.
    seeds = {
        k for k, n in DAG.items()
        if n.produces & (written if is_foundational(n) else touched_sections)
    }
    plan: set[str] = set(seeds)
    for s in seeds:
        plan |= descendants(s)
    plan |= {"verification"} | descendants("verification")

    # Foundational nodes ride in only on their own seed, never on a descendant
    # edge. Filtering after the closure rather than during it keeps every other
    # node reachable *through* them — dropping `design_system` must not hide
    # `patterns`, which sits behind it.
    plan -= {k for k in plan - seeds if is_foundational(DAG[k])}

    # Drop the nodes whose entire output this change already wrote. Their
    # descendants were added above and stay.
    authored = set(already_written)
    if authored:
        plan -= {
            k for k, n in DAG.items()
            if n.produces and n.produces <= authored and n.kind == "agent"
        }

    order = [k for lvl in levels() for k in lvl]
    return [k for k in order if k in plan]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class TaskSpec:
    """One unit of work handed to an agent."""

    task_id: str
    node: str
    agent: str
    attempt: int = 1
    #: The artifact this call is for, when the node fans out. ``build_prompt``
    #: narrows the context to it, so a per-page call carries one page rather
    #: than eighteen.
    subject: str = ""
    #: Why the previous attempt was rejected. Rejecting a proposal only
    #: improves the next one if the next one is told what was wrong —
    #: otherwise a retry re-runs an identical prompt and reproduces the
    #: identical mistake, which is exactly what it did.
    feedback: str = ""


@dataclass
class RunReport:
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    #: Skipped node -> the dependencies that never completed. Kept beside
    #: ``skipped`` rather than folded into it so the list stays node keys a
    #: caller can test membership against.
    skipped_because: dict[str, str] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    change_requests: list = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.blocked


Executor = Callable[[TaskSpec], AgentResult]


def run(
    svc: BlueprintService,
    executor: Executor,
    *,
    plan: Sequence[str] | None = None,
    max_attempts: int = 2,
    commit: bool = False,
    user_request: str = "",
    app_root: str | None = None,
) -> RunReport:
    """Execute a plan in dependency order.

    ``executor`` performs the actual agent call — injected so this module never
    depends on an LLM. Retries are bounded by ``max_attempts`` (§103: tasks must
    be retryable) and are safe because agent results are idempotent by natural
    key (§29 + the ID allocator).

    A node whose dependencies did not complete is **skipped**, not attempted.
    §28's whole point is that running downstream work on missing inputs is how
    a swarm produces confident nonsense.
    """
    order = list(plan) if plan is not None else [k for lvl in levels() for k in lvl]
    report = RunReport()
    done: set[str] = set()

    for key in order:
        node = DAG[key]
        unmet = {d for d in node.depends_on if d in order and d not in done}
        if unmet:
            # Say which dependency stopped it. A plan that quietly drops eight
            # of eighteen nodes reads exactly like one that ran them: the
            # `apis` node was skipped for an unmet dependency during an
            # incremental change and the Blueprint simply kept the endpoints it
            # already had, with nothing to indicate the derivation never ran.
            report.skipped.append(key)
            report.skipped_because[key] = ", ".join(sorted(unmet))
            continue

        capability_for(node.agent)  # §28: no unregistered agents

        if node.kind == "service":
            handler = SERVICE_HANDLERS.get(key)
            if handler is None:
                report.blocked.append(key)
                continue
            handler(svc)
            report.completed.append(key)
            done.add(key)
            continue

        if node.kind == "projection":
            projector = PROJECTION_HANDLERS.get(key)
            if projector is not None and app_root:
                projector(svc, app_root)
                report.completed.append(key)
                done.add(key)
                continue
            # Deterministic, but not ported into this package yet. Blocked
            # rather than handed to a model: a model asked to fill codeMap
            # would invent plausible paths that pass validation, and
            # Blueprint<->Implementation would go green against files nobody
            # wrote.
            report.blocked.append(key)
            continue

        # A fanning-out node authors one artifact per subject. Each subject is
        # its own call with its own retries, and one failing subject fails the
        # node rather than quietly leaving a hole — seventeen pages out of
        # eighteen looks exactly like success.
        subjects = subjects_for(node, svc.doc)
        if not subjects:
            report.completed.append(key)
            done.add(key)
            continue

        node_failed = False
        for subject in subjects:
            outcome = _run_agent_subject(
                svc, executor, key, node, subject,
                max_attempts=max_attempts, commit=commit,
                user_request=user_request, report=report,
            )
            if outcome is None:
                node_failed = True
                break
        if node_failed:
            continue
        report.completed.append(key)
        done.add(key)
        continue

    return report


def _run_agent_subject(
    svc: BlueprintService,
    executor: Executor,
    key: str,
    node: DagNode,
    subject: str,
    *,
    max_attempts: int,
    commit: bool,
    user_request: str,
    report: RunReport,
) -> str | None:
    """One agent call (with retries) for one subject.

    Returns ``"completed"`` or ``None``; a ``None`` means the caller must stop,
    because the node cannot be considered done. Retries are bounded by
    ``max_attempts`` (§103) and are safe because agent results are idempotent by
    natural key, so a retry updates the same artifact rather than adding one.
    """
    label = f"{key}:{subject}" if subject else key
    feedback = ""
    for attempt in range(1, max_attempts + 1):
        spec = TaskSpec(
            task_id=f"TASK-{label}-{attempt}", node=key,
            agent=node.agent, attempt=attempt, subject=subject,
            feedback=feedback,
        )
        try:
            result = executor(spec)
        except Exception as exc:  # §102 — one classified outcome, not a crash
            # Carried into the next attempt for the same reason an apply
            # rejection is: a retry that is not told what went wrong is just
            # the same request again.
            feedback = str(exc)
            if attempt == max_attempts:
                report.failed.append(label)
                return None
            continue

        try:
            application = apply_agent_result(
                svc, result, commit=commit, user_request=user_request,
            )
        except (BlueprintInvalid, InvalidPatternTemplate) as exc:
            feedback = str(exc)
            # A rejected proposal is an outcome, not a crash. This used to
            # escape and kill the whole run: one page whose tree failed
            # contract validation took the other seventeen with it, and the
            # traceback surfaced instead of a report. Nothing was written —
            # apply validates before it commits — so a retry is clean.
            if attempt == max_attempts:
                report.failed.append(label)
                return None
            continue
        if application.applied:
            report.artifacts.extend(application.artifacts)
            report.change_requests.extend(application.change_requests)
            return "completed"
        if application.needs_clarification or result.status == "blocked":
            report.blocked.append(label)
            report.change_requests.extend(application.change_requests)
            return None
        if attempt == max_attempts:
            report.failed.append(label)
            return None
    return None


def _run_verification(svc: BlueprintService) -> None:
    """The §75 matrix, flagging what it finds (§76). Repairs nothing."""
    from services.blueprint.verification import apply_findings, verify

    apply_findings(svc, verify(svc.doc))


def _project_data_layer(svc: BlueprintService, app_root: str) -> None:
    """Entities -> Drizzle modules, plus the mask manifest the engine reads."""
    from services.blueprint.projection import (
        apply_data_projection, project_searchable_columns,
        project_sensitive_columns,
    )

    apply_data_projection(svc, app_root)
    project_sensitive_columns(svc.doc, app_root)
    project_searchable_columns(svc.doc, app_root)


def _project_frontend(svc: BlueprintService, app_root: str) -> None:
    """Everything the browser reads: page schemas, the route graph, the tokens."""
    from services.blueprint.projection import (
        apply_frontend_projection, project_design_tokens, project_middleware,
        project_nav_flow, project_root_route,
    )

    apply_frontend_projection(svc, app_root)
    project_nav_flow(svc.doc, app_root)
    project_design_tokens(svc.doc, app_root)
    project_middleware(svc.doc, app_root)
    project_root_route(svc.doc, app_root)


def _project_integration(svc: BlueprintService, app_root: str) -> None:
    """Everything the server reads: workflow definitions and seed rows."""
    from services.blueprint.projection import project_seed, project_workflows

    result = project_workflows(svc.doc, app_root)
    for entry in result["codeMap"]:
        svc.upsert("codeMap", entry, natural_key=entry["artifact"])
    project_seed(svc.doc, app_root)
    svc.save()


#: Projection handlers, by node key. A node with no handler stays blocked —
#: which is the honest state for the projections not yet ported.
def _project_preview(svc: BlueprintService, app_root: str) -> None:
    """Assemble the scaffold and engines around the projected application.

    Deliberately does not run ``app_emitter``'s repair cascade — see
    ``assembly.SUPERSEDED_REPAIRS`` for what each of those repaired and which
    projection makes it unnecessary.
    """
    from services.blueprint.assembly import apply_assembly

    apply_assembly(svc, app_root,
                   project_short_id=(svc.doc.get("application") or {}).get("id", "forge"))


PROJECTION_HANDLERS: dict[str, Any] = {
    "backend": _project_data_layer,
    "frontend": _project_frontend,
    "integration": _project_integration,
    "preview": _project_preview,
}


def _derive_apis(svc: BlueprintService) -> None:
    """The API surface follows from the Blueprint; it is not a design task."""
    from services.blueprint.api_derivation import apply_derived_apis

    apply_derived_apis(svc)


#: Deterministic node handlers, by node key.
def _record_memory(svc: BlueprintService) -> None:
    """§20 assumptions and §23 completeness, both derived from the document."""
    from services.blueprint.completeness import apply_completeness
    from services.blueprint.decision_memory import apply_decision_memory

    apply_decision_memory(svc)
    apply_completeness(svc)


SERVICE_HANDLERS: dict[str, Any] = {
    "verification": _run_verification,
    "apis": _derive_apis,
    "memory": _record_memory,
}


def build_plan_summary(doc: dict) -> dict[str, int]:
    """§26 — the countable shape of the build plan, for the user-facing plan
    review gate (§95 Gate 3)."""
    return {
        "pages": len(doc.get("pages") or []),
        "entities": len(_entities(doc)),
        "workflows": len(doc.get("workflows") or []),
        "businessRules": len(doc.get("businessRules") or []),
        "apis": len(doc.get("apis") or []),
        "roles": len(doc.get("roles") or []),
        "integrations": len(doc.get("integrations") or []),
        "tests": len(doc.get("tests") or []),
    }
