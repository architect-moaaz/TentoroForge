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
from typing import Any, Callable, Iterable, Mapping, Sequence

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
    #
    # ONE CALL PER MODULE, not one for the application. This authored every
    # entity in a single reply, so its cost grew with the whole brief while its
    # budget stayed at one response: a twelve-module legislative platform — 42
    # requirements, twenty domain terms to model — never returned, twice, and
    # took the build with it. There is no timeout on the model client and
    # `_gather` waits for the whole wave, so the run simply stopped at 3/18
    # with `data.entities` missing and no error anywhere.
    #
    # `data.entities` is an ID-bearing list keyed by natural_key (the entity's
    # name), so an entity two modules both need is proposed twice and merges
    # rather than duplicating. That is what makes the split safe.
    #
    # Now depends on `ux_architecture`: the subjects ARE the modules, so they
    # have to exist before this node can fan out. It used to run beside it.
    _n("data_model", "data_model", ("application_model", "ux_architecture"),
       ("data.entities",), fanout="modules"),
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
    # §34 — one composed tree per page. There were two nodes ahead of this one
    # and both were residue from the pipeline A2UI replaced.
    #
    # `page_designs` authored `components` and `uiRegistry`: two LLM sections
    # naming components that were never code. `uiRegistry` reached exactly two
    # consumers — pasted into this node's own prompt, and cross-checked against
    # the components the `frontend` projection derives. Neither is worth a
    # model call, and a page composed against invented component names is
    # composed against nothing.
    #
    # `patterns` authored one template per pattern, back when the planner
    # instantiated those templates per page with no model call. That was the
    # primary path; A2UI composing each page made it the fallback, and a full
    # LLM node maintaining a fallback for the exception is the wrong trade.
    # A page nobody composes is now skipped and reported, not silently stubbed
    # from a template that never saw it (§76).
    # `workflows` is a dependency, not an ordering nicety: the composer is told
    # which workflows this page launches so a button can name one, and a
    # workflow that has not been authored yet is a button that cannot exist.
    # Dropping the two nodes that used to sit in front of this one moved it two
    # waves earlier, into the same wave as `workflows` — concurrent with the
    # thing it reads.
    _n("page_layouts", "a2ui_pages",
       ("page_contracts", "design_system", "workflows"),
       ("pageLayouts",),
       fanout="pages",
       note="§34; one composed tree per page, gated on the component catalog"),
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
    "modules": lambda doc: [
        m["id"] for m in (doc.get("modules") or [])
        if m.get("id") and m.get("status") != "DEPRECATED"
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
    "data.entities", "data.relationships",
    "data.constraints", "apis", "workflows", "businessRules", "tests",
    "codeMap", "database", "runtime", "roles", "permissions", "security",
})


def is_foundational(node: DagNode) -> bool:
    """True when re-running this node would re-author the application's frame.

    Derived from what the node produces rather than listed by name, so a node
    added to the DAG later classifies itself. ``pageLayouts`` counts as
    incremental — §72 says "components", and a composed page is a composition
    of them.

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


def _section(doc: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted ``produces`` path such as ``data.entities``."""
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def completed_nodes(
    doc: Mapping[str, Any], nodes: dict[str, DagNode] = DAG,
) -> set[str]:
    """Agent nodes whose every produced section already has content.

    Resume means *continue*, not *redo*. A run that died at `testing` had
    already paid for fourteen agent nodes; re-executing them costs the same
    again, and — because a re-run appends to a section rather than replacing
    it — leaves the Blueprint larger each time rather than converging. One
    resumed run took requirements from 31 to 39 and pages from 30 to 34
    without being asked for a single new thing.

    Only ``agent`` nodes are eligible. Projections and services write files
    from what the Blueprint already says: they cost no tokens, they are
    deterministic, and re-running them is how a fix to a projection reaches
    disk at all. Skipping those would preserve the very output the fix was
    meant to replace.

    A node that declares no ``produces`` cannot be judged and so always runs.
    """
    done: set[str] = set()
    for key, node in nodes.items():
        if node.kind != "agent" or not node.produces:
            continue
        if all(_section(doc, path) for path in node.produces):
            done.add(key)
    return done


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
    #: Failed node -> why. The reason was already being computed and then
    #: thrown away: the exception went into the retry's feedback and the report
    #: recorded only a name, so a rate limit and a malformed envelope looked
    #: identical. Four nodes failed consecutively on one run and there was
    #: nothing in the output to tell a transport fault from a content one.
    failed_because: dict[str, str] = field(default_factory=dict)
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
    in_plan = set(order)
    report = RunReport()
    done: set[str] = set()

    # §28's graph declares which nodes are independent; running them one after
    # another threw that declaration away. A *wave* is the set of nodes whose
    # in-plan dependencies are all complete — the same shape `levels` computes
    # for the whole DAG, recomputed here because a plan is a subset and because
    # a node that failed must not let its dependents into a later wave.
    remaining = list(order)
    while remaining:
        wave = [
            key for key in remaining
            if {d for d in DAG[key].depends_on if d in in_plan} <= done
        ]
        if not wave:
            break
        for key in wave:
            capability_for(DAG[key].agent)  # §28: no unregistered agents
        _run_wave(
            svc, executor, wave, report=report, done=done,
            max_attempts=max_attempts, commit=commit,
            user_request=user_request, app_root=app_root,
        )
        ran = set(wave)
        remaining = [key for key in remaining if key not in ran]

    # Whatever never made a wave is waiting on something that never completed.
    # Say which dependency stopped it. A plan that quietly drops eight of
    # eighteen nodes reads exactly like one that ran them: the `apis` node was
    # skipped for an unmet dependency during an incremental change and the
    # Blueprint simply kept the endpoints it already had, with nothing to
    # indicate the derivation never ran.
    for key in remaining:
        unmet = {d for d in DAG[key].depends_on if d in in_plan and d not in done}
        report.skipped.append(key)
        report.skipped_because[key] = ", ".join(sorted(unmet))

    return report


#: How many model calls one fanning-out node keeps in flight. Pages are
#: genuinely independent — each call is given one page's brief and produces one
#: tree, reading nothing another page wrote — and a serial fan-out was the
#: dominant cost of a run: twenty-four pages at roughly seventy-five seconds
#: each is half an hour inside a single node.
FANOUT_CONCURRENCY = 6

#: How many model calls a whole wave keeps in flight, across every node in it.
#: A wave of four fanning-out nodes would otherwise open twenty-four
#: connections at once, which is how you find the provider's rate limit rather
#: than the machine's. Kept above :data:`FANOUT_CONCURRENCY` so a lone fan-out
#: still runs at full width, and low enough that four nodes share rather than
#: multiply. If a run starts failing several nodes at the same level, lower
#: this: ``RunReport.failed_because`` names the exception, so the report says
#: whether the cause was transport or content.
WAVE_CONCURRENCY = 8


@dataclass
class _NodeRun:
    """One agent node's progress through a wave's retry rounds."""

    #: Every subject the node authors for; ``[""]`` when it does not fan out.
    subjects: list[str]
    #: The subjects still to be called in the next round.
    pending: list[str]
    #: Subject -> why its last attempt was rejected (§102).
    feedback: dict[str, str] = field(default_factory=dict)
    #: Subjects that exhausted their attempts.
    failed: list[str] = field(default_factory=list)


def _run_wave(
    svc: BlueprintService,
    executor: Executor,
    wave: Sequence[str],
    *,
    report: RunReport,
    done: set[str],
    max_attempts: int,
    commit: bool,
    user_request: str,
    app_root: str | None,
) -> None:
    """Run one wave: model calls wide, applies narrow and ordered.

    What runs concurrently is the executor and nothing else. ``apply_agent_result``
    allocates stable ids (§12) into one shared document and saves it, and that
    allocation is order-dependent — so applies stay on this thread, node by node
    in wave order and, inside a node, subject by subject in the order the
    subjects were given.

    A lock around the applies would be safe against corruption and would still
    be wrong: apply order would become whichever thread arrived first, and a
    re-projection that is supposed to be byte-identical would stop being one.
    ``project_frontend`` is idempotent by design and
    ``test_frontend_projection_is_idempotent`` holds it to that.

    Service and projection nodes stay serial throughout. They are deterministic
    and fast, and they mutate the document directly, so there is nothing to win
    and a race to lose.
    """
    import threading

    # Deterministic and cheap; done before the wave's model calls so the long
    # pole is the only thing left to wait on.
    for key in wave:
        node = DAG[key]
        if node.kind == "service":
            handler = SERVICE_HANDLERS.get(key)
            if handler is None:
                report.blocked.append(key)
                continue
            try:
                handler(svc)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                # A derived node that raises used to take the whole run with
                # it: the dispatch was unguarded, so one bad projection lost
                # every node behind it and the report said nothing at all.
                report.failed.append(key)
                report.failed_because[key] = _reason(exc)
                continue
        elif node.kind == "projection":
            projector = PROJECTION_HANDLERS.get(key)
            if projector is None or not app_root:
                # Deterministic, but not ported into this package yet. Blocked
                # rather than handed to a model: a model asked to fill codeMap
                # would invent plausible paths that pass validation, and
                # Blueprint<->Implementation would go green against files
                # nobody wrote.
                report.blocked.append(key)
                continue
            try:
                projector(svc, app_root)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                report.failed.append(key)
                report.failed_because[key] = _reason(exc)
                continue
        else:
            continue
        report.completed.append(key)
        done.add(key)

    # Subjects are resolved once, before anything in the wave applies. Nodes in
    # a wave are independent by construction, so none of them can change
    # another's subject list — resolving up front just makes that explicit.
    runs: dict[str, _NodeRun] = {}
    for key in wave:
        if DAG[key].kind != "agent":
            continue
        subjects = subjects_for(DAG[key], svc.doc)
        runs[key] = _NodeRun(subjects=subjects, pending=list(subjects))

    limits = {key: threading.Semaphore(FANOUT_CONCURRENCY) for key in runs}

    for attempt in range(1, max_attempts + 1):
        specs = _round_specs(wave, runs, attempt)
        if not specs:
            break
        results = _gather(executor, specs, limits=limits)
        for key in wave:  # apply order is wave order, never completion order
            state = runs.get(key)
            if state is None or not state.pending:
                continue
            state.pending = _apply_round(
                svc, key, state, results,
                attempt=attempt, max_attempts=max_attempts, commit=commit,
                user_request=user_request, report=report,
            )

    for key in wave:
        state = runs.get(key)
        if state is None:
            continue
        # Only a node that authored nothing at all has genuinely failed;
        # anything less is a partial result its dependents can still use.
        if state.subjects and len(state.failed) == len(state.subjects):
            continue
        report.completed.append(key)
        done.add(key)


def _round_specs(
    wave: Sequence[str], runs: dict[str, _NodeRun], attempt: int,
) -> list[TaskSpec]:
    """This round's calls, interleaved across the wave's nodes.

    Round-robin rather than node-by-node so :data:`WAVE_CONCURRENCY` is shared
    out instead of being spent entirely on whichever node happens to be first.
    Ordering here decides only who gets a slot; it decides nothing about the
    document, because applies are re-ordered by :func:`_run_wave`.
    """
    queues = [(key, list(runs[key].pending)) for key in wave if key in runs]
    specs: list[TaskSpec] = []
    for i in range(max((len(q) for _, q in queues), default=0)):
        for key, pending in queues:
            if i >= len(pending):
                continue
            subject = pending[i]
            state = runs[key]
            specs.append(TaskSpec(
                task_id=f"TASK-{key}{':' + subject if subject else ''}-{attempt}",
                node=key,
                agent=DAG[key].agent,
                attempt=attempt,
                subject=subject,
                feedback=state.feedback.get(subject, ""),
            ))
    return specs


def _gather(
    executor: Executor,
    specs: Sequence[TaskSpec],
    *,
    limits: dict[str, Any],
) -> dict[tuple[str, str], Any]:
    """Call the executor for every spec concurrently. Calls, and nothing else.

    No applies happen here and no report is touched, which is what makes it
    safe to run this wide: the half that is network I/O is the half that
    parallelises, and the half that mutates the Blueprint stays on one thread.

    ``limits`` caps each node at :data:`FANOUT_CONCURRENCY` while the pool caps
    the wave at :data:`WAVE_CONCURRENCY`, so one node cannot spend the whole
    budget.

    Returns ``{(node, subject): AgentResult | Exception}``. An exception is a
    classified outcome (§102), not a crash; the caller decides whether it is a
    retry or a failure.
    """
    from concurrent.futures import ThreadPoolExecutor

    def call(spec: TaskSpec) -> tuple[tuple[str, str], Any]:
        key = (spec.node, spec.subject)
        with limits[spec.node]:
            try:
                return key, executor(spec)
            except Exception as exc:  # §102 — a classified outcome, not a crash
                return key, exc

    workers = max(1, min(WAVE_CONCURRENCY, len(specs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(call, specs))


def _apply_round(
    svc: BlueprintService,
    key: str,
    state: _NodeRun,
    results: dict[tuple[str, str], Any],
    *,
    attempt: int,
    max_attempts: int,
    commit: bool,
    user_request: str,
    report: RunReport,
) -> list[str]:
    """Commit one round's results for one node, in the order its subjects were given.

    Records the report entries and returns the subjects to retry, each left in
    ``state.feedback`` with the reason it was rejected. §102: a retry that is
    not told what went wrong is just the same request again.
    """
    retry: list[str] = []
    for subject in state.pending:  # given order, not completion order
        # A node that does not fan out has one empty subject, and its label is
        # just the node key — callers test membership by it.
        label = f"{key}:{subject}" if subject else key
        outcome = results.get((key, subject))

        if isinstance(outcome, Exception):
            state.feedback[subject] = _reason(outcome)
            if attempt == max_attempts:
                report.failed.append(label)
                report.failed_because[label] = _reason(outcome)
                state.failed.append(subject)
            else:
                retry.append(subject)
            continue

        try:
            application = apply_agent_result(
                svc, outcome, commit=commit, user_request=user_request,
            )
        except (BlueprintInvalid, InvalidPatternTemplate) as exc:
            state.feedback[subject] = _reason(exc)
            if attempt == max_attempts:
                report.failed.append(label)
                report.failed_because[label] = _reason(exc)
                state.failed.append(subject)
            else:
                retry.append(subject)
            continue

        if application.applied:
            report.artifacts.extend(application.artifacts)
            report.change_requests.extend(application.change_requests)
            continue
        if application.needs_clarification or outcome.status == "blocked":
            report.blocked.append(label)
            report.change_requests.extend(application.change_requests)
            state.failed.append(subject)
            continue
        if attempt == max_attempts:
            report.failed.append(label)
            report.failed_because.setdefault(
                label, "the agent returned a result that could not be applied")
            state.failed.append(subject)
        else:
            retry.append(subject)

    return retry


def _reason(exc: Exception) -> str:
    """One line naming what went wrong, kept short enough to read in a report."""
    return f"{type(exc).__name__}: {exc}".replace("\n", " ")[:400]


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
                report.failed_because[label] = _reason(exc)
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
                report.failed_because[label] = _reason(exc)
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
            report.failed_because.setdefault(
                label, "the agent returned a result that could not be applied")
            return None
    return None


def _run_verification(svc: BlueprintService) -> None:
    """The §75 matrix, flagging what it finds (§76). Repairs nothing."""
    from services.blueprint.verification import apply_findings, verify

    apply_findings(svc, verify(svc.doc))


def _project_data_layer(svc: BlueprintService, app_root: str) -> None:
    """Entities -> Drizzle modules, plus the mask manifest the engine reads."""
    from services.blueprint.projection import (
        apply_data_projection, project_append_only_entities,
        project_searchable_columns, project_sensitive_columns,
    )

    apply_data_projection(svc, app_root)
    project_sensitive_columns(svc.doc, app_root)
    project_searchable_columns(svc.doc, app_root)
    project_append_only_entities(svc.doc, app_root)


def _project_frontend(svc: BlueprintService, app_root: str) -> None:
    """Everything the browser reads: page schemas, the route graph, the tokens."""
    from services.blueprint.page_planner import PlanError
    from services.blueprint.projection import (
        apply_frontend_projection, project_design_tokens, project_middleware,
        project_public_resources,
        project_nav_flow, project_root_route,
    )

    result = apply_frontend_projection(svc, app_root)
    # A page A2UI authored and the planner cannot render is a defect, not an
    # acceptable loss. This projection wrote 23 schemas from 30 authored trees
    # and reported success: every collection page — /jobs, /customers, /bikes,
    # /parts, /invoices, /staff — failed on one bad prop and vanished. The app
    # built, deployed, and had no lists in it. plan_pages recorded every
    # reason; nothing between it and here ever read them.
    if result.get("failed"):
        raise PlanError(
            f"{len(result['failed'])} page(s) authored but could not be "
            "planned:\n" + "\n".join(
                f"  {f['page']}: {f['reason'][:200]}" for f in result["failed"]
            )
        )
    project_nav_flow(svc.doc, app_root)
    project_design_tokens(svc.doc, app_root)
    project_middleware(svc.doc, app_root)
    # The data route needs the same list the matcher was built from.
    project_public_resources(svc.doc, app_root)
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
    from services.blueprint.assembly import apply_assembly, verify_build

    assembled = apply_assembly(
        svc, app_root,
        project_short_id=(svc.doc.get("application") or {}).get("id", "forge"))
    # Assembly writes a tree; the build is what makes it an application. Kept
    # inside the node so a run that cannot compile fails here, where the reason
    # is a compiler error, rather than later when someone opens the directory.
    result = verify_build(app_root)
    runtime = dict(svc.doc.get("runtime") or {})
    runtime["build"] = {"install": result["install"], "build": result["build"],
                        "status": "passed"}
    # An unsubstituted placeholder does fail the build above — but as a
    # prerender error in a file nobody edited, which reads as a compiler
    # problem rather than as a substitution pass that did not run. Recorded
    # here so the run names the cause. Always written, empty included: a
    # missing key would mean the guard did not run, which is a different fact.
    runtime["placeholders"] = assembled.get("residualPlaceholders") or []
    svc.doc["runtime"] = runtime
    svc.save()


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
