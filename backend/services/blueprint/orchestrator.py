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

from services.blueprint import approval
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


#: §95 — the transitions a user must have authorised, and the gate that
#: authorises each. Only the two edges the PRD puts a gate on: entering
#: implementation (Gate 3) and deploying (Gate 4). Everything else moves on
#: engineering grounds, because §95 is explicit that *"small engineering
#: decisions should not continuously interrupt the user."*
GATED_TRANSITIONS: dict[tuple[str, str], str] = {
    ("PLAN_REVIEW", "IMPLEMENTATION"): "plan",
    ("READY", "EXPORT_DEPLOY"): "deployment",
}


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
    gate = GATED_TRANSITIONS.get((src, dst))
    if gate:
        # §95's gates are only real if something consults them. A gate nobody
        # checks is a UI step, and this is where Gate 3 stops being one.
        approval.require(svc.doc, gate, doing=f"moving to {dst}")

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
    # §51 puts Figma Intelligence upstream of domain, page, entity, workflow
    # and requirement inference — it is the evidence those work from, so it
    # runs beside `requirements` rather than after them. §48 bounds what it may
    # conclude: a design proves a screen exists, not who may use it, so this
    # node writes requirements *with their Figma evidence and a confidence*,
    # and §17 refuses the ones it cannot stand behind.
    #
    # Fans out over connected designs, so a prompt-only application resolves to
    # no subjects and the stage is absent work discovered from the document
    # rather than a flag asking whether to skip.
    _n("figma_intelligence", "figma_intelligence", (), ("requirements",),
       fanout="design_sources",
       note="§48-§51; design evidence, not design decisions"),
    _n("application_model", "product_analysis",
       ("requirements", "figma_intelligence"), ("product",)),

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
    # §47 — the design language the connected file already states, projected
    # onto the Blueprint. Deterministic (§116): published variables *are* the
    # colour system and type scale, so a model asked to "extract" them can only
    # paraphrase, and every paraphrase is a silent divergence from the design
    # the user is holding us to.
    #
    # After `design_system`, and that ordering is the mechanism rather than a
    # detail: `designSystem` is a singleton section, so the last writer of a
    # key wins, and §40/§53 rank an explicit user design above anything the
    # platform recommends on its own. Precedence by merge order instead of by
    # asking an agent to defer. Before `page_layouts`, so composition sees it.
    _n("figma_design_system", "figma_intelligence", ("design_system",),
       ("designSystem",), kind="service",
       note="§40, §47, §53; explicit design outranks generic recommendation"),
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
       ("page_contracts", "design_system", "figma_design_system", "workflows"),
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
    # §41 — one call per connected design. A prompt-only application has none,
    # which resolves to no subjects and completes the node without invoking
    # anything.
    "design_sources": lambda doc: [
        s["id"] for s in (doc.get("designSources") or []) if s.get("id")
    ],
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
        if not all(_section(doc, path) for path in node.produces):
            continue
        # A FAN-OUT IS COMPLETE WHEN EVERY SUBJECT IS, NOT WHEN ANY IS.
        #
        # "The section has content" is the right test for a node that writes
        # once. For a node that writes once PER SUBJECT it is wrong by exactly
        # the failures: `page_layouts` ended a run with 4 of 15 pages composed
        # and 11 failed, this read the 4 as "pageLayouts has content" and
        # planned the next run without it — so `frontend` was built from a
        # four-page application and the eleven failed pages were never
        # retried. Resume-not-redo became resume-not-finish.
        #
        # Checked against the rows themselves rather than a count, because a
        # deprecated page leaves a layout behind and a count would call that
        # complete too.
        subject_key = _SUBJECT_ROW_KEY.get(node.fanout)
        if node.fanout and subject_key:
            section, field = subject_key
            present = {str(row.get(field) or "")
                       for row in (doc.get(section) or []) if isinstance(row, dict)}
            if any(subject not in present for subject in subjects_for(node, doc)):
                continue
        done.add(key)
    return done


#: For a fan-out node, which produced section names the subject a row was
#: written for, and under which field. Only fan-outs whose rows carry their
#: subject can be judged per subject; one that does not (a design source's
#: requirements carry `evidence`, not a source id) keeps the section-level
#: rule above, which is the behaviour every run had before this existed.
_SUBJECT_ROW_KEY: dict[str, tuple[str, str]] = {
    "pages": ("pageLayouts", "page"),
}


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
    #: Blocked node -> what it is waiting to be told. A node that STOPS TO ASK
    #: recorded only its name, and the question went into `change_requests`
    #: where nothing routed it anywhere.
    #:
    #: Measured: `data_model` returned four proposals at confidence 0.20 and
    #: §17 held them — "confidence 0.20 is below the clarification threshold of
    #: 0.40" — which is the policy working exactly as written. Everything
    #: downstream (database, page_contracts, workflows, page_layouts, frontend)
    #: was skipped, the run ended in 156 seconds, and the only trace anywhere
    #: was the word `data_model` in a list. Reconstructing the reason meant
    #: re-running the agent.
    #:
    #: A run that stops to ask and a run that stops dead must not look the
    #: same, which is this session's defect in its purest form: the system
    #: behaved correctly and said nothing.
    blocked_because: dict[str, str] = field(default_factory=dict)
    change_requests: list = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.blocked


import logging

logger = logging.getLogger(__name__)


def _run_id() -> str:
    """A run's own name. Time-ordered so `runs()` sorts newest-first without
    reading any of them."""
    import time as _t
    import uuid as _u

    return _t.strftime("%Y%m%d-%H%M%S", _t.gmtime()) + "-" + _u.uuid4().hex[:6]


def _note(ledger: Any, method: str, *args: Any) -> None:
    """Record if there is a ledger. Never raise: the ledger describes the run,
    it does not get to end it.

    A bare `except` here hid the ledger's own bug — `node_done` took its second
    argument keyword-only, every call raised TypeError, and the ledger recorded
    plans and failures but never a start or a completion. A programming error
    in the recorder is not the same as the recorder being unavailable, so the
    first is logged and only the second is quiet.
    """
    if ledger is None:
        return
    try:
        getattr(ledger, method)(*args)
    except TypeError as exc:  # a wrong call is OUR bug, not a bad disk
        logger.warning("[ledger] %s(%s) rejected: %s", method,
                       ", ".join(map(repr, args))[:80], exc)
    except Exception:  # noqa: BLE001 — disk full, read-only volume, …
        pass


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
    observer: Callable[[dict], None] | None = None,
) -> RunReport:
    """Execute a plan in dependency order.

    ``executor`` performs the actual agent call — injected so this module never
    depends on an LLM. Retries are bounded by ``max_attempts`` (§103: tasks must
    be retryable) and are safe because agent results are idempotent by natural
    key (§29 + the ID allocator).

    A node whose dependencies did not complete is **skipped**, not attempted.
    §28's whole point is that running downstream work on missing inputs is how
    a swarm produces confident nonsense.

    ``observer`` watches the run's ledger as it is written — every line that
    reaches disk reaches the observer first. That is how the virtual office
    animates: it reads this same account rather than keeping its own, so a node
    outcome recorded here cannot be missing from the picture.
    """
    order = list(plan) if plan is not None else [k for lvl in levels() for k in lvl]
    in_plan = set(order)
    report = RunReport()
    done: set[str] = set()

    # THE ACCOUNT OF THIS RUN, ON DISK, AS IT GOES. `report` is complete and
    # then discarded when this returns, so a run that ends abnormally leaves
    # nothing to read. See services/blueprint/run_ledger.
    from services.blueprint.run_ledger import RunLedger

    ledger = RunLedger(svc.output_dir, _run_id(),
                       phase="build" if commit else "dry", observer=observer)
    ledger.planned(order)

    # §28's graph declares which nodes are independent; running them one after
    # another threw that declaration away. A *wave* is the set of nodes whose
    # in-plan dependencies are all complete — the same shape `levels` computes
    # for the whole DAG, recomputed here because a plan is a subset and because
    # a node that failed must not let its dependents into a later wave.
    remaining = list(order)
    try:
        return _execute(svc, executor, order, in_plan, report, done, ledger,
                        max_attempts=max_attempts, commit=commit,
                        user_request=user_request, app_root=app_root)
    except BaseException as exc:
        # THE LINE THAT WAS MISSING. A run that raises out of here used to
        # leave nothing at all — the report died with the call, the registry
        # forgot it after two minutes, and the only evidence was which
        # Blueprint sections had not been written. Three post-mortems started
        # from there and one of them reached the wrong conclusion.
        ledger.crashed(exc)
        raise


def _execute(
    svc: BlueprintService,
    executor: Executor,
    order: list[str],
    in_plan: set[str],
    report: RunReport,
    done: set[str],
    ledger: Any,
    *,
    max_attempts: int,
    commit: bool,
    user_request: str,
    app_root: str | None,
) -> RunReport:
    """The wave loop. Split from `run` so the ledger can record a crash."""
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
            user_request=user_request, app_root=app_root, ledger=ledger,
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
        ledger.node_skipped(key, ", ".join(sorted(unmet)))

    ledger.finish(report)
    return report


#: How many model calls one fanning-out node keeps in flight. Pages are
#: genuinely independent — each call is given one page's brief and produces one
#: tree, reading nothing another page wrote — and a serial fan-out was the
#: dominant cost of a run: twenty-four pages at roughly seventy-five seconds
#: each is half an hour inside a single node.
#:
#: Raised from 6 on measurement. `page_layouts` averages 102s a page, and a
#: legislative platform declared 44 of them: at 6 wide that is 8 rounds and
#: ~14 minutes, the single largest block in a 40-minute build. At 12 it is 4
#: rounds and ~7.
#:
#: Not raised further, and this is the ceiling worth defending rather than the
#: number: past a dozen in flight the limit stops being this machine and starts
#: being the provider's, and a rate-limited page fails as an UNBUILT ROUTE —
#: `_unbuilt_pages` reports it, the run still succeeds, and the app 404s where
#: a page should be. Trading correctness for minutes is the wrong trade. If
#: several pages start failing at once, lower this: `RunReport.failed_because`
#: Attempts a node gets before the run gives up on it, where two is not enough.
#:
#: `data_model` is BIMODAL, measured over six samples on byte-identical prompts:
#: four produced 18-20 entities at confidence 0.72-0.76, two produced a 900-char
#: two-entity stub at 0.10-0.20. Nothing landed in between, and no change to the
#: prompt moved it — three input variants scored the same.
#:
#: At a one-in-three stub rate the global budget of two clears 89% of the time,
#: and an EMR build lost the coin toss twice in a row: three runs, six of twenty
#: nodes, no application. Four attempts takes that to 98.8%.
#:
#: Per node rather than globally, because raising it for all twenty multiplies
#: the cost of nodes that fail deterministically — where a second attempt is
#: worth having and a fourth is just the same failure twice more.
ATTEMPTS_BY_NODE: dict[str, int] = {
    "data_model": 4,
}


#: names the exception, so the report distinguishes transport from content.
FANOUT_CONCURRENCY = 12

#: How many model calls a whole wave keeps in flight, across every node in it.
#: A wave of four fanning-out nodes would otherwise open twenty-four
#: connections at once, which is how you find the provider's rate limit rather
#: than the machine's. Kept above :data:`FANOUT_CONCURRENCY` so a lone fan-out
#: still runs at full width, and low enough that four nodes share rather than
#: multiply. If a run starts failing several nodes at the same level, lower
#: this: ``RunReport.failed_because`` names the exception, so the report says
#: whether the cause was transport or content.
#:
#: Moved with FANOUT_CONCURRENCY to keep the invariant this comment states —
#: above it, so a lone fan-out still runs at full width. Leaving it at 8 while
#: the fan-out asked for 12 would have capped `page_layouts` at 8 and made the
#: raise half a change.
WAVE_CONCURRENCY = 14


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
    ledger: Any = None,
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
        # EVERY KIND OF NODE STARTS, not just the ones that call a model.
        # `node:start` was emitted for agent nodes only, so a service or
        # projection node that ran appeared in `done` and never in `started` —
        # and `explain` therefore listed it as still pending. A node that ran
        # reading as one that never began is the exact misreading this ledger
        # exists to prevent.
        if node.kind in ("service", "projection"):
            _note(ledger, "node_start", key, 1)
        if node.kind == "service":
            handler = SERVICE_HANDLERS.get(key)
            if handler is None:
                report.blocked.append(key)
                _note(ledger, "node_blocked", key, "no service handler")
                continue
            try:
                handler(svc)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                # A derived node that raises used to take the whole run with
                # it: the dispatch was unguarded, so one bad projection lost
                # every node behind it and the report said nothing at all.
                report.failed.append(key)
                report.failed_because[key] = _reason(exc)
                _note(ledger, "node_failed", key, _reason(exc))
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
                _note(ledger, "node_blocked", key, "no projection handler or app_root")
                continue
            try:
                projector(svc, app_root)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                report.failed.append(key)
                report.failed_because[key] = _reason(exc)
                _note(ledger, "node_failed", key, _reason(exc))
                continue
        else:
            continue
        report.completed.append(key)
        _note(ledger, "node_done", key)
        done.add(key)

    # Subjects are resolved once, before anything in the wave applies. Nodes in
    # a wave are independent by construction, so none of them can change
    # another's subject list — resolving up front just makes that explicit.
    runs: dict[str, _NodeRun] = {}
    for _k in wave:
        if DAG[_k].kind not in ("service", "projection"):
            _note(ledger, "node_start", _k, len(subjects_for(DAG[_k], svc.doc)))
    for key in wave:
        if DAG[key].kind != "agent":
            continue
        subjects = subjects_for(DAG[key], svc.doc)
        runs[key] = _NodeRun(subjects=subjects, pending=list(subjects))

    limits = {key: threading.Semaphore(FANOUT_CONCURRENCY) for key in runs}

    wave_attempts = max(
        (ATTEMPTS_BY_NODE.get(k, max_attempts) for k in wave),
        default=max_attempts,
    )
    for attempt in range(1, wave_attempts + 1):
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
                attempt=attempt,
                max_attempts=ATTEMPTS_BY_NODE.get(key, max_attempts),
                commit=commit,
                user_request=user_request, report=report, ledger=ledger,
            )

    for key in wave:
        state = runs.get(key)
        if state is None:
            continue
        # Only a node that authored nothing at all has genuinely failed;
        # anything less is a partial result its dependents can still use.
        if state.subjects and len(state.failed) == len(state.subjects):
            # Every subject failed: the node authored nothing. Recorded with
            # the reasons, because "which of the eighteen stopped it, and why"
            # is the question the ledger exists to answer.
            _note(ledger, "node_failed", key,
                  "; ".join(sorted(state.failed.values()))[:600]
                  if isinstance(state.failed, dict) else
                  f"all {len(state.subjects)} subjects failed")
            continue
        report.completed.append(key)
        _note(ledger, "node_done", key, len(state.subjects or []))
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
    ledger: Any = None,
) -> list[str]:
    """Commit one round's results for one node, in the order its subjects were given.

    Records the report entries and returns the subjects to retry, each left in
    ``state.feedback`` with the reason it was rejected. §102: a retry that is
    not told what went wrong is just the same request again.
    """
    retry: list[str] = []
    total = len(state.subjects or [""])

    def _at(subject: str) -> int:
        """One-based position in the node's subject list, for the record."""
        try:
            return (state.subjects or []).index(subject) + 1
        except ValueError:  # pragma: no cover — a subject not in its own list
            return 0

    def _rejected(subject: str, label: str, reason: str) -> None:
        """One subject's proposal was refused. Either it goes round again
        (§103) or this was the last attempt and the subject is lost."""
        state.feedback[subject] = reason
        if attempt == max_attempts:
            report.failed.append(label)
            report.failed_because[label] = reason
            state.failed.append(subject)
            _note(ledger, "node_subject", key, subject, _at(subject), total, False)
        else:
            retry.append(subject)
            _note(ledger, "node_retry", key, subject,
                  attempt + 1, max_attempts, reason)

    for subject in state.pending:  # given order, not completion order
        # A node that does not fan out has one empty subject, and its label is
        # just the node key — callers test membership by it.
        label = f"{key}:{subject}" if subject else key
        outcome = results.get((key, subject))

        if isinstance(outcome, Exception):
            _rejected(subject, label, _reason(outcome))
            continue

        try:
            application = apply_agent_result(
                svc, outcome, commit=commit, user_request=user_request,
            )
        except (BlueprintInvalid, InvalidPatternTemplate) as exc:
            _rejected(subject, label, _reason(exc))
            continue

        if application.applied:
            report.artifacts.extend(application.artifacts)
            report.change_requests.extend(application.change_requests)
            _note(ledger, "node_subject", key, subject, _at(subject), total, True)
            continue
        if application.needs_clarification or outcome.status == "blocked":
            if attempt < max_attempts:
                _rejected(subject, label, _asked(application))
                continue
            report.blocked.append(label)
            report.blocked_because[label] = _asked(application)
            report.change_requests.extend(application.change_requests)
            _note(ledger, "node_blocked", key, _asked(application))
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


def _asked(application: Any) -> str:
    """What a blocked node is waiting to be told, in one line.

    `apply_agent_result` already computes a precise reason — "confidence 0.20
    is below the §17 clarification threshold of 0.40" — and any questions the
    agent raised are in `change_requests`. Both were discarded: the report kept
    the node's name and nothing else, so the only way to learn why a run had
    stopped was to run the agent again and look.
    """
    reason = str(getattr(application, "reason", "") or "").strip()
    asks: list[str] = []
    for cr in getattr(application, "change_requests", None) or []:
        text = (cr.get("question") or cr.get("detail") or cr.get("summary")
                if isinstance(cr, dict) else str(cr))
        if text:
            asks.append(str(text))
    if asks:
        reason = f"{reason} — asks: {'; '.join(asks[:3])}" if reason else \
                 "; ".join(asks[:3])
    return (reason or "the agent declined without giving a reason")[:600]


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
            # RETRY BEFORE BLOCKING. `data_model` is bimodal on one real
            # Blueprint — six samples, byte-identical prompts: four gave
            # 18-20 entities at confidence 0.72-0.76, two gave a 900-char
            # two-entity stub at 0.10-0.20, nothing in between. Blocking on
            # the first low-confidence reply killed an EMR build and skipped
            # thirteen nodes when asking again had a two-in-three chance.
            #
            # No heuristic decides which it was: a stub asked to be re-run
            # in its own `change_requests` ("Re-run this stage with a clean
            # emission"), so "raised a question" does not separate them. A
            # real clarification survives the retry and blocks on the last
            # attempt carrying the same question; a stub usually does not.
            if attempt < max_attempts:
                feedback = _asked(application)
                continue
            report.blocked.append(label)
            report.blocked_because[label] = _asked(application)
            report.change_requests.extend(application.change_requests)
            _note(ledger, "node_blocked", key, _asked(application))
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
    """Entities -> Drizzle modules, plus the manifests the engine reads.

    The mask manifest says which columns come back redacted, the append-only
    manifest which entities refuse a rewrite, and the ownership manifest which
    *rows* the actor may reach at all. They are projected together because the
    data engine reads all three, and it is the one place every read passes
    through — the API route and the server render call it directly, so a
    control that lived in the route would not cover the SSR path.
    """
    from services.blueprint.projection import (
        apply_data_projection, project_append_only_entities,
        project_ownership_rules, project_searchable_columns,
        project_sensitive_columns,
    )

    apply_data_projection(svc, app_root)
    project_sensitive_columns(svc.doc, app_root)
    project_searchable_columns(svc.doc, app_root)
    project_append_only_entities(svc.doc, app_root)
    project_ownership_rules(svc.doc, app_root)


def _project_frontend(svc: BlueprintService, app_root: str) -> None:
    """Everything the browser reads: page schemas, the route graph, the tokens."""
    from services.blueprint.page_planner import PlanError
    from services.blueprint.projection import (
        apply_frontend_projection, project_design_tokens, project_middleware,
        project_public_resources,
        project_nav_flow, project_root_route, project_shell,
    )

    # NO SECOND COMPOSER. A landing page whose composition is refused leaves no
    # layout, the projection writes no schema, and `/` 404s — reported by
    # `_unbuilt_pages` like any other missing route.
    #
    # `blueprint/landing_page` used to assemble one here from the navigation
    # tree, on the argument that the page a user ARRIVES on is different in
    # kind from a page they might reach. It ran once against a real Blueprint
    # and emitted props no component has (`text` on a Heading, `href` on a
    # Link), so the page could not render — and the refusal aborted this
    # function before `project_design_tokens`, leaving the whole application
    # unable to compile on a missing tokens.css. It turned one dead route into
    # no application, which is the trade it existed to prevent, reversed.
    #
    # The deeper objection is the one this codebase had already settled when it
    # removed the deterministic pattern stub: a stubbed page and a designed one
    # looking alike is unacceptable, and a second composer is a second answer
    # to "what does this screen look like". An honest 404 on the front door is
    # a defect anyone can see; a tile grid nobody authored is one they cannot.
    result = apply_frontend_projection(svc, app_root)
    # A page A2UI authored and the planner cannot render is a defect, not an
    # acceptable loss. This projection wrote 23 schemas from 30 authored trees
    # and reported success: every collection page — /jobs, /customers, /bikes,
    # /parts, /invoices, /staff — failed on one bad prop and vanished. The app
    # built, deployed, and had no lists in it. plan_pages recorded every
    # reason; nothing between it and here ever read them.
    # THE REST OF THE APPLICATION IS NOT THIS PAGE'S TO LOSE. The raise below
    # used to come first, and these five never ran — so one page failing on one
    # bad prop cost the stylesheet, the route graph, the middleware and the
    # root route. The scaffold's `globals.css` imports `./tokens.css`
    # unconditionally and `project_design_tokens` is the only thing that writes
    # it, so the whole application stopped compiling:
    #
    #     ./src/app/globals.css
    #     Module not found: Can't resolve './tokens.css'
    #     GET / 500
    #
    # Not one broken page — no application at all, and an error naming a CSS
    # import rather than the page that caused it.
    #
    # None of these five reads the planning result. `project_design_tokens`
    # reads `designSystem`; nav_flow and root_route read the Blueprint's own
    # page list, which is unaffected by which of them the planner could render.
    # So they are run first and the refusal is raised after: the node still
    # fails, the retry still happens, and what the failure destroys is now the
    # page that failed rather than everything around it.
    project_nav_flow(svc.doc, app_root)
    # The rail itself, from the same tree the route graph was read from:
    # `shell.json` is what the scaffold's layout builds its sidebar from, and
    # nothing wrote it, so every rail was the flat fallback.
    project_shell(svc.doc, app_root)
    project_design_tokens(svc.doc, app_root)
    project_middleware(svc.doc, app_root)
    # The data route needs the same list the matcher was built from.
    project_public_resources(svc.doc, app_root)
    project_root_route(svc.doc, app_root)

    if result.get("failed"):
        raise PlanError(
            f"{len(result['failed'])} page(s) authored but could not be "
            "planned:\n" + "\n".join(
                f"  {f['page']}: {f['reason'][:200]}" for f in result["failed"]
            )
        )


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
    from services.blueprint.assembly import (
        apply_assembly, page_funnel, verify_build,
    )

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
    # WHAT THE APPLICATION SERVES, AGAINST WHAT WAS PLANNED. `verify_build`
    # proves the tree compiles; it cannot notice that half the pages are not in
    # it. Two real builds went 53 -> 27 and 38 -> 23 and reported success,
    # because every node downstream of composition faithfully projected what
    # survived. Recorded on every run, `complete` included: a missing key would
    # mean the check did not run, which is a different fact from no shortfall.
    runtime["pages"] = page_funnel(svc.doc, app_root)
    if runtime["pages"]["missing"]:
        logger.warning(
            "[preview] %d of %d planned pages are not served: %s",
            len(runtime["pages"]["missing"]), runtime["pages"]["planned"],
            ", ".join(runtime["pages"]["missing"][:8]))
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


def _project_design_reference(svc: BlueprintService) -> None:
    """§47 — the connected design's own tokens. No-op without one."""
    from services.figma.projection import apply_design_reference

    apply_design_reference(svc)


SERVICE_HANDLERS: dict[str, Any] = {
    "figma_design_system": _project_design_reference,
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
