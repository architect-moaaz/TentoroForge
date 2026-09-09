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

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from services.blueprint import approval
from services.blueprint.agent_contract import (
    AgentResult,
    InvalidPatternTemplate,
    InvalidWorkflowStep, InvalidBusinessRule,
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
    "install": ("scaffold + vendored engines -> node_modules", "npm"),
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
    #: A node the application can ship without. Its failure is recorded but
    #: does not fail the run or block its dependents — the built app is not
    #: held in `draft` over an artifact that is not the running app itself
    #: (e.g. `testing`, which is verification, and is the last node to spend
    #: the API — so a low credit balance there should not sink a ready build).
    optional: bool = False


def _n(key, agent, depends_on=(), produces=(), note="", kind="agent",
       fanout="", optional=False) -> DagNode:
    return DagNode(key, agent, frozenset(depends_on), frozenset(produces),
                   note, kind, fanout, optional)


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
    # ENTITIES ARE NAMED ONCE AND DETAILED ONE AT A TIME. This node names the
    # entities and states the relationships between them — the part that
    # needs every entity in view — and no fields. Measured, the single call
    # that also wrote every field was 88s median and 276s with 28k output
    # tokens on a 21-entity model, and it is the second node on the critical
    # path: everything about data waits on it.
    _n("data_model", "data_model", ("application_model",), ("data.entities",),
       note="the entity set and its relationships; fields come per entity"),
    # One call per declared entity, in parallel, each given the whole entity
    # set by name so a foreign key can name what it points at.
    _n("entity_fields", "data_model", ("data_model",), ("data.entities",),
       fanout="entities",
       note="fields, keys, enums, sensitivity and constraints, per entity"),
    _n("database", "data_model", ("entity_fields",), ("database",)),
    # Derived, not authored: mutations from workflows, reads from the data
    # engine, analytics from widgets. See services.blueprint.api_derivation.
    _n("apis", "api", ("database", "workflow_steps", "page_details"), ("apis",),
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
    # THE PAGE SET IS DECIDED ONCE AND THE CONTRACTS ARE WRITTEN PER FEATURE.
    # This node answers the slot question — which features exist, which are
    # declined, and for each page its route, pattern, module and entity —
    # and nothing more. Measured, the single call that also wrote every
    # contract was the longest declaration of a build (120s median, 486s and
    # 52k output tokens on a 53-page app), and everything after it waited.
    # A workflow needs a page's id and route to say where it launches; a
    # contract's tasks and states it never reads. So `workflows` depends on
    # this node and runs beside `page_details`.
    _n("page_contracts", "page_design", ("ux_architecture", "entity_fields"), ("pages",),
       note="the page set: filled or declined per feature, routes decided"),
    # One call per feature — an entity's pages together, so a list and its
    # detail are written as one flow — each given the declared page set so
    # `navigatesTo` can name any page by an id that already exists.
    # Produces `pages`, as the single node did; it writes widgets too, but a
    # produced section is what resume and impact analysis read, and an
    # application with no dashboard has none.
    _n("page_details", "page_design", ("page_contracts",), ("pages",),
       fanout="page_features",
       note="the contracts: tasks, states, views, actions, widgets, per feature"),
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
       ("page_details", "design_system", "figma_design_system", "workflows"),
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
    # WORKFLOWS ARE DECLARED ONCE AND AUTHORED ONE AT A TIME. This node names
    # them — id, trigger, the page that launches each, the inputs it needs —
    # and nothing else. Measured, the single call that also wrote every step
    # was the longest node of a build (106s median, 576s worst, 42k output
    # tokens on a 35-workflow app) and sat on the critical path twice: pages
    # could not compose until it returned, and it could not start until
    # everything at its level had. A page needs a workflow's identity and
    # contract to wire a button, never its steps; `page_layouts` depends on
    # this node and not on `workflow_steps` for exactly that reason.
    _n("workflows", "workflow", ("entity_fields", "page_contracts"), ("workflows",),
       note="§107 step 16; declares each workflow's identity and contract"),
    # One call per declared workflow, in parallel, each given the node
    # catalog and one workflow to fill in. A step is a catalog node carrying
    # what that node declares it needs, refused at apply otherwise — the same
    # gate as before, now per workflow, so one refused workflow re-asks for
    # one workflow rather than for all thirty-five.
    _n("workflow_steps", "workflow", ("workflows",), ("workflows",),
       fanout="workflows",
       note="§107 step 16; one authored step graph per declared workflow"),
    _n("business_rules", "business_rules", ("entity_fields",), ("businessRules",),
       note="§107 step 16; not a distinct box in §28"),
    _n("security", "security", ("entity_fields",), ("security", "roles", "permissions"),
       note="§100; placed after the data model because permissions guard entities"),
    _n("integrations", "integration", ("application_model",), ("integrations",)),

    # join
    _n("integration", "backend",
       ("backend", "frontend", "workflow_steps", "business_rules", "security", "integrations"),
       (), kind="projection"),
    # Reads requirements, data, pages, apis, workflows and rules — never a
    # projected file — so it waits for the producers of those and runs beside
    # the projections instead of behind them. `apis` carries the data model
    # and the pages transitively; the other two are named because nothing
    # between them and this node would.
    _n("testing", "testing", ("apis", "workflow_steps", "business_rules"),
       ("tests",), optional=True),
    # §20 + §23 — both read off what the Blueprint already carries, so neither
    # is an agent. Placed after authoring and before verification, so the
    # verification report is made against a document that knows what it assumed.
    _n("memory", "memory", ("testing",), ("decisions", "completeness"),
       kind="service",
       note="§20 decision memory + §23 completeness, both derived"),
    _n("verification", "verification", ("memory",), (), kind="service"),
    # `npm install` reads the scaffold's package.json and the vendored
    # engines, which are the same for every application: it needs nothing an
    # agent writes. With no dependencies it starts with `requirements` and is
    # finished long before there is anything to compile. Measured at one to
    # three minutes, all of which used to sit at the end of the build.
    _n("install", "build", (), (), kind="projection",
       note="scaffold + engines + node_modules, before any agent replies"),
    # The build waits for the join and the install, and for nothing else.
    # `testing`, `memory` and `verification` write to the Blueprint, not to
    # the tree being compiled, so a compile that waited for them was waiting
    # for a report it does not read. §94's state walk still gates PREVIEW on
    # `verification` having run — see `smith.BUILD_WALK`.
    _n("preview", "build", ("integration", "install"), ("runtime",),
       kind="projection"),
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
    # §107 step 16 — one call per declared workflow.
    "workflows": lambda doc: [
        w["id"] for w in (doc.get("workflows") or [])
        if w.get("id") and w.get("status") != "DEPRECATED"
    ],
    # One call per declared entity.
    "entities": lambda doc: [
        e["id"] for e in ((doc.get("data") or {}).get("entities") or [])
        if isinstance(e, dict) and e.get("id") and e.get("status") != "DEPRECATED"
    ],
    # One call per feature: an entity's pages together, and a page that
    # belongs to no entity (a dashboard, a sign-in, a drawn screen with no
    # primary record) on its own.
    "page_features": lambda doc: page_features(doc),
}


def page_features(doc: Mapping[str, Any]) -> list[str]:
    """The subjects `page_details` fans out over, in first-seen order."""
    seen: list[str] = []
    for page in doc.get("pages") or []:
        if not isinstance(page, dict) or not page.get("id") \
                or page.get("status") == "DEPRECATED":
            continue
        subject = str((page.get("data") or {}).get("primaryEntity") or "") \
            or str(page["id"])
        if subject not in seen:
            seen.append(subject)
    return seen


def feature_pages(doc: Mapping[str, Any], subject: str) -> list[dict]:
    """The declared pages one `page_details` subject is asked to write."""
    return [
        p for p in doc.get("pages") or []
        if isinstance(p, dict) and p.get("status") != "DEPRECATED"
        and ((str((p.get("data") or {}).get("primaryEntity") or "") or str(p.get("id")))
             == subject)
    ]


def subjects_for(node: "DagNode", doc: dict) -> list[str]:
    """The subjects a node authors for. ``[""]`` means "once, for the app"."""
    if not node.fanout:
        return [""]
    resolve = FANOUT.get(node.fanout)
    if resolve is None:
        raise KeyError(f"node {node.key!r} declares unknown fanout {node.fanout!r}")
    return resolve(doc) or []


def pending_subjects(node: "DagNode", doc: dict) -> list[str]:
    """The subjects a fan-out node still has to author — resume is *continue*,
    not *redo*, at the subject grain too.

    A subject already present in the node's output section (a page with a
    composed ``pageLayouts`` row) is not re-run, so resuming a run that
    dropped-and-continued composes exactly the pages that failed, without
    re-spending on — or re-composing, and possibly changing — the ones that
    already succeeded. `page_layouts` is the dominant cost of a run and this is
    where re-running "the missing pages" stops meaning "all of them". A `fresh`
    run starts from an empty document, so nothing is present and every subject
    runs; a node that writes once (no per-subject row key) is unaffected."""
    subjects = subjects_for(node, doc)
    authored = _SUBJECT_AUTHORED.get(node.fanout)
    if authored is None:
        return subjects
    return [s for s in subjects if not authored(doc, s)]


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
        authored = _SUBJECT_AUTHORED.get(node.fanout)
        if node.fanout and authored is not None:
            if any(not authored(doc, subject) for subject in subjects_for(node, doc)):
                continue
        done.add(key)
    return done


def _layout_present(doc: Mapping[str, Any], page_id: str) -> bool:
    return any(isinstance(row, dict) and str(row.get("page") or "") == page_id
               for row in doc.get("pageLayouts") or [])


def _fields_present(doc: Mapping[str, Any], entity_id: str) -> bool:
    """A named entity is detailed once it carries fields. `data_model` and
    `entity_fields` both write `data.entities`; the declaration names and
    relates, the author fills in, and an entity with no fields is one the
    author has not reached."""
    return any(isinstance(e, dict) and e.get("id") == entity_id and bool(e.get("fields"))
               for e in (doc.get("data") or {}).get("entities") or [])


def _contracts_present(doc: Mapping[str, Any], subject: str) -> bool:
    """A declared page is authored once it carries its `states`: the
    declaration decides that a page exists and where, the contract says what
    it must handle, and `states` is the one field every contract declares
    ("empty and error states up front") that no declaration writes."""
    pages = feature_pages(doc, subject)
    return bool(pages) and all(bool(p.get("states")) for p in pages)


def _steps_present(doc: Mapping[str, Any], workflow_id: str) -> bool:
    """A declared workflow is authored once it carries steps. `workflows`
    and `workflow_steps` both write the `workflows` section, so "the section
    has content" is true the moment the first has run; what the second owes
    is the step graph, and that is what is checked."""
    return any(isinstance(row, dict) and row.get("id") == workflow_id
               and bool(row.get("steps"))
               for row in doc.get("workflows") or [])


#: For a fan-out node, whether one subject's artifact has been authored. Only
#: fan-outs that can be judged per subject are listed; one that cannot (a
#: design source's requirements carry `evidence`, not a source id) keeps the
#: section-level rule above, which is the behaviour every run had before this
#: existed.
_SUBJECT_AUTHORED: dict[str, Callable[[Mapping[str, Any], str], bool]] = {
    "pages": _layout_present,
    "workflows": _steps_present,
    "page_features": _contracts_present,
    "entities": _fields_present,
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
    #: Optional node -> why it failed, having been allowed through. The app
    #: SHIPPED WITHOUT IT: `testing` is verification, not the running app, so a
    #: failure there (a low credit balance, a transient fault) is recorded here
    #: rather than in `failed`, and does not hold a built application in `draft`.
    degraded: dict[str, str] = field(default_factory=dict)
    #: Node -> the observer's verdict on it (§73, closed at the node). Every
    #: agent node the observer watched has an entry, passing or not, so a
    #: report can be read for what was judged and not only for what failed.
    observed: dict[str, dict] = field(default_factory=dict)
    #: Labels the observer sent back to their author and then passed.
    repaired: list[str] = field(default_factory=list)
    #: Label -> what stayed wrong after every repair round. The artifact is
    #: flagged OUT_OF_SYNC (§76) and left as its author last wrote it; it is
    #: not a failure of the run, because nothing was lost — it is a divergence
    #: the report names rather than a repair the platform hid.
    unrepaired: dict[str, str] = field(default_factory=dict)

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
    observer_agent: Any = None,
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

    ``observer_agent`` is a :class:`services.blueprint.observer.Observer`, or
    nothing. With one, every agent node's outcome is judged the moment its
    last subject lands — on a worker, while the rest of the graph carries on —
    and a node the observer fails is sent back to its author with the findings
    before anything downstream starts (§73). Injected for the same reason the
    executor is: with no critic it costs nothing and calls no model, so the
    loop is testable; with one it is the same loop with a judgement in it.
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

    # §28's graph declares which nodes are independent; `_execute` starts a
    # node the moment its in-plan dependencies are complete, recomputed there
    # because a plan is a subset and because a node that failed must never
    # release its dependents.
    try:
        return _execute(svc, executor, order, in_plan, report, done, ledger,
                        max_attempts=max_attempts, commit=commit,
                        user_request=user_request, app_root=app_root,
                        observer_agent=observer_agent)
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
    observer_agent: Any = None,
) -> RunReport:
    """The scheduler. Split from `run` so the ledger can record a crash.

    EVENT-DRIVEN, NOT WAVES. A node starts the moment its own in-plan
    dependencies are done, and a subject goes round again the moment its
    proposal is rejected. The wave loop this replaces grouped nodes into
    topological levels and waited for the slowest call in a level before
    anything in the next level began — and, inside a level, held every retry
    until every first attempt had returned. Measured on a 23-page build, that
    left `page_layouts` at one to four calls in flight for the last 400 of its
    727 seconds: the width was 12, the shape of the loop spent it.

    Two things stay exactly as they were. Calls run on worker threads and
    NOTHING ELSE does: every apply, and every deterministic node, runs on this
    thread under the document's lock, so the Blueprint has one writer. And a
    node whose dependency did not complete is skipped, never attempted (§28).

    What changes is apply ORDER: results apply as they arrive. Ids come from
    natural keys (§12), so a re-run returns the same id whatever the order;
    what a fresh document numbers first is now whichever proposal landed
    first. The one place order still carries meaning is two nodes writing the
    same section — `requirements` and `figma_intelligence` both write
    `requirements` — and for those, :func:`_yields_to` holds the later node's
    results until the earlier one has finished, so their numbering is the
    plan's, not the network's.

    THE OBSERVER SITS BETWEEN "FINISHED" AND "DONE". A node whose calls have
    all landed is *finished*; with an observer it is not *done* — nothing
    downstream may start — until the observer has judged it and every
    subject it failed has been re-authored and judged again, or the rounds
    are spent and what is left is flagged. The judgement runs on a worker
    like any call, so the rest of the graph keeps moving; only the node's
    own dependents wait, which is exactly §28's rule. A declaration node
    whose section a later node is still authoring (`data_model` before
    `entity_fields`) is not judged on its own — the author is.
    """
    from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

    from services.blueprint.observer import (
        OBSERVER_AGENT, RepairTask, flag_unrepaired,
    )

    started: set[str] = set()
    finished: set[str] = set()
    runs: dict[str, _NodeRun] = {}
    futures: dict[Future, TaskSpec] = {}
    #: Results held back by :func:`_yields_to`, in arrival order.
    deferred: list[tuple[TaskSpec, Any]] = []
    #: Future -> "observe" | "repair" for the observer's own traffic; a
    #: future absent here is an ordinary call.
    kinds: dict[Future, str] = {}
    watches: dict[str, _Watch] = {}
    rounds = int(getattr(observer_agent, "rounds", 1) or 1)

    def ready() -> list[str]:
        return [
            key for key in order
            if key not in started
            and {d for d in DAG[key].depends_on if d in in_plan} <= done
        ]

    def settle_optional(key: str) -> None:
        # AN OPTIONAL NODE NEVER HOLDS THE APPLICATION IN DRAFT. If it failed,
        # count it done anyway — its dependents (the deterministic tail:
        # memory, verification, preview) run, the run stays `ok`, and the
        # built app reaches `ready`. The failure is not hidden: it moves to
        # `degraded`, which the report still carries. `testing` is the case
        # that matters — verification, not the running app, and the last node
        # to spend the API.
        if not DAG[key].optional or key in done:
            return
        labels = [key] + [
            lbl for lbl in list(report.failed) if lbl.startswith(f"{key}:")
        ]
        for lbl in labels:
            if lbl in report.failed:
                report.failed.remove(lbl)
                report.degraded[lbl] = report.failed_because.pop(lbl, "")
        done.add(key)
        logger.warning(
            "[%s] optional node failed and was shipped without: %s",
            key, "; ".join(report.degraded.get(lbl, "") for lbl in labels)[:200],
        )

    def finish(pool: ThreadPoolExecutor, key: str) -> None:
        state = runs[key]
        finished.add(key)
        if observer_agent is not None and _watchable(key, state, order, in_plan,
                                                    finished):
            observe(pool, key, _applied(state))
            return
        complete(key)

    def complete(key: str) -> None:
        state = runs[key]
        # Only a node that authored nothing at all has genuinely failed;
        # anything less is a partial result its dependents can still use.
        if state.subjects and len(state.failed) == len(state.subjects):
            # Every subject failed: the node authored nothing. Recorded with
            # the reasons, because "which of the eighteen stopped it, and why"
            # is the question the ledger exists to answer.
            reasons = [
                report.failed_because.get(f"{key}:{s}" if s else key, "")
                for s in state.failed
            ]
            _note(ledger, "node_failed", key,
                  "; ".join(r for r in reasons if r)[:600]
                  or f"all {len(state.subjects)} subjects failed")
        else:
            report.completed.append(key)
            _note(ledger, "node_done", key, len(state.subjects or []))
            done.add(key)
        settle_optional(key)

    def pump(pool: ThreadPoolExecutor, key: str) -> None:
        """Submit queued subjects up to the node's own width."""
        state = runs[key]
        while state.queue and len(state.in_flight) < FANOUT_CONCURRENCY:
            subject = state.queue.pop(0)
            attempt = state.attempts.get(subject, 0) + 1
            state.attempts[subject] = attempt
            state.in_flight.add(subject)
            spec = TaskSpec(
                task_id=f"TASK-{key}{':' + subject if subject else ''}-{attempt}",
                node=key,
                agent=DAG[key].agent,
                attempt=attempt,
                subject=subject,
                feedback=state.feedback.get(subject, ""),
            )
            futures[pool.submit(_call, executor, spec)] = spec

    def start(pool: ThreadPoolExecutor, key: str) -> None:
        started.add(key)
        capability_for(DAG[key].agent)  # §28: no unregistered agents
        node = DAG[key]
        if node.kind in ("service", "projection"):
            # Deterministic, and it mutates the document directly: run here,
            # on the one writing thread, never on a worker. A handler whose
            # work is a process rather than a computation hands back a future
            # (`install`), and the node is in flight until it lands.
            with svc.lock:
                pending = _run_deterministic(
                    svc, key, node, report=report, done=done,
                    app_root=app_root, ledger=ledger)
            if pending is not None:
                futures[pending] = TaskSpec(task_id=f"TASK-{key}", node=key,
                                            agent=node.agent)
                return
            finished.add(key)
            settle_optional(key)
            return
        # Only the subjects not already authored — a resume finishes the pages
        # a prior run dropped, not the ones it composed (see pending_subjects).
        subjects = pending_subjects(node, svc.doc)
        _note(ledger, "node_start", key, len(subjects))
        runs[key] = _NodeRun(subjects=subjects, pending=list(subjects),
                             queue=list(subjects))
        if not subjects:
            finish(pool, key)
            return
        pump(pool, key)

    def settle_deterministic(key: str, outcome: Any) -> None:
        finished.add(key)
        if isinstance(outcome, Exception):
            report.failed.append(key)
            report.failed_because[key] = _reason(outcome)
            _note(ledger, "node_failed", key, _reason(outcome))
        else:
            report.completed.append(key)
            _note(ledger, "node_done", key)
            done.add(key)
        settle_optional(key)

    def settle(pool: ThreadPoolExecutor, spec: TaskSpec, outcome: Any) -> None:
        key = spec.node
        if DAG[key].kind != "agent":
            settle_deterministic(key, outcome)
            return
        state = runs[key]
        with svc.lock:
            verdict = _apply_subject(
                svc, key, state, spec.subject, outcome,
                attempt=spec.attempt,
                max_attempts=ATTEMPTS_BY_NODE.get(key, max_attempts),
                commit=commit, user_request=user_request,
                report=report, ledger=ledger,
            )
        state.in_flight.discard(spec.subject)
        if verdict == "retry":
            state.queue.append(spec.subject)
        pump(pool, key)
        if not state.in_flight and not state.queue:
            finish(pool, key)

    # -- the observer's half ------------------------------------------------

    def observe(pool: ThreadPoolExecutor, key: str, subjects: list[str]) -> None:
        """Judge ``subjects`` of ``key`` on a worker, against the document as
        it is right now. The snapshot is taken here, under the lock, so the
        observer reads what the node finished with and not what the next
        apply writes."""
        watches.setdefault(key, _Watch(
            subjects=list(subjects),
            authored={k: set(v) for k, v in runs[key].authored.items()},
        ))
        with svc.lock:
            snapshot = copy.deepcopy(svc.doc)
        fut = pool.submit(
            observer_agent.observe, key, agent=DAG[key].agent,
            subjects=list(subjects), doc=snapshot,
            pending=_pending_sections(in_plan, finished),
            planned=_planned_sections(in_plan), user_request=user_request,
            subject_of=_subject_resolver(DAG[key], snapshot),
        )
        futures[fut] = TaskSpec(task_id=f"OBSERVE-{key}", node=key,
                                agent=OBSERVER_AGENT)
        kinds[fut] = "observe"

    def settle_observation(pool: ThreadPoolExecutor, key: str, obs: Any) -> None:
        w = watches[key]
        if isinstance(obs, Exception):
            # The observer's own failure is not the node's. Recorded, and the
            # node completes as its author left it.
            logger.warning("[%s] observer failed: %s", key, _reason(obs))
            report.observed[key] = {"node": key, "ok": None,
                                    "error": _reason(obs)}
            complete(key)
            return
        _record_observation(report, ledger, obs)
        for subject in obs.subjects:
            label = f"{key}:{subject}" if subject else key
            if obs.findings.get(subject):
                w.open[subject] = RepairTask(
                    node=key, agent=DAG[key].agent, subject=subject,
                    feedback=obs.brief(subject),
                )
                w.last[subject] = obs
            elif subject in w.open:
                w.open.pop(subject)
                report.repaired.append(label)
        advance(pool, key)

    def advance(pool: ThreadPoolExecutor, key: str) -> None:
        """Repair what is open, or flag it once the rounds are spent."""
        w = watches[key]
        if not w.open:
            complete(key)
            return
        if w.round >= rounds:
            for subject, task in w.open.items():
                obs = w.last[subject]
                with svc.lock:
                    flag_unrepaired(svc, obs, subject)
                why = "; ".join(
                    f"{f.edge}: {f.detail}" for f in obs.findings.get(subject, [])
                )[:600]
                report.unrepaired[task.label] = why
                _note(ledger, "unrepaired", key, subject, why)
            complete(key)
            return
        w.round += 1
        for subject, task in w.open.items():
            spec = TaskSpec(
                task_id=f"TASK-{task.label}-observer{w.round}",
                node=key, agent=task.agent, attempt=w.round,
                subject=subject, feedback=task.feedback,
            )
            _note(ledger, "repair", key, subject, w.round, rounds, task.feedback)
            fut = pool.submit(_call, executor, spec)
            futures[fut] = spec
            kinds[fut] = "repair"
            w.awaiting.add(subject)

    def settle_repair(pool: ThreadPoolExecutor, spec: TaskSpec, outcome: Any) -> None:
        key = spec.node
        w = watches[key]
        w.awaiting.discard(spec.subject)
        with svc.lock:
            refused, application = _repair_apply(
                svc, outcome, commit=commit, user_request=user_request)
            if refused is None:
                # A REPAIR IS THE WHOLE ANSWER, NOT AN ADDENDUM. Ids come
                # from natural keys, so a re-authoring that renames a module
                # or re-spells a constraint's expression is a new artifact
                # beside the old one — measured live: three "Notes" modules
                # and every index constraint twice, which the observer then
                # rightly flagged and could not repair. What the subject
                # authored before and did not re-propose is retired here.
                now = _proposed_identities(outcome, application)
                stale = w.authored.get(spec.subject, set()) - now
                if stale:
                    _retire(svc, stale,
                            note=f"superseded by the observer's repair of "
                                 f"{spec.task_id}")
                w.authored[spec.subject] = now
        if refused is not None:
            # The author's repair was refused; the original stands, and the
            # next round is told why. Nothing half-applied: apply validates
            # before it commits.
            task = w.open[spec.subject]
            w.open[spec.subject] = RepairTask(
                node=key, agent=task.agent, subject=spec.subject,
                feedback=f"{task.feedback}\n\nYour previous repair was "
                         f"rejected: {refused}",
            )
        else:
            w.landed.append(spec.subject)
        if w.awaiting:
            return
        landed, w.landed = w.landed, []
        if landed:
            # Verify again — the half of the loop that decides.
            observe(pool, key, landed)
        else:
            advance(pool, key)

    def flush(pool: ThreadPoolExecutor) -> None:
        """Apply what arrived, holding back what must wait its turn."""
        nonlocal deferred
        again: list[tuple[TaskSpec, Any]] = []
        for spec, outcome in deferred:
            if _yields_to(spec.node, order, started, finished):
                again.append((spec, outcome))
            else:
                settle(pool, spec, outcome)
        deferred = again

    pool = ThreadPoolExecutor(max_workers=WAVE_CONCURRENCY)
    try:
        while True:
            # Start everything that can start, to a fixpoint: a service node
            # completes inline and may have readied its dependents.
            while True:
                due = ready()
                if not due:
                    break
                for key in due:
                    start(pool, key)
            flush(pool)
            if not futures:
                break
            landed, _ = wait(list(futures), return_when=FIRST_COMPLETED)
            for fut in landed:
                spec = futures.pop(fut)
                try:
                    outcome = fut.result()
                except Exception as exc:  # noqa: BLE001 — a deterministic node's own failure
                    outcome = exc
                kind = kinds.pop(fut, None)
                if kind == "observe":
                    settle_observation(pool, spec.node, outcome)
                    continue
                if kind == "repair":
                    settle_repair(pool, spec, outcome)
                    continue
                deferred.append((spec, outcome))
            flush(pool)
    except BaseException:
        # A crash on this thread (a CapabilityViolation is the one that
        # surfaces by design) must not sit behind a dozen model calls still
        # in flight before `run` can record it: drop what is queued, leave
        # what is running to finish on its own, and let the ledger speak.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)

    # Whatever never started is waiting on something that never completed.
    # Say which dependency stopped it. A plan that quietly drops eight of
    # eighteen nodes reads exactly like one that ran them: the `apis` node was
    # skipped for an unmet dependency during an incremental change and the
    # Blueprint simply kept the endpoints it already had, with nothing to
    # indicate the derivation never ran.
    for key in order:
        if key in started:
            continue
        unmet = {d for d in DAG[key].depends_on if d in in_plan and d not in done}
        report.skipped.append(key)
        report.skipped_because[key] = ", ".join(sorted(unmet))
        ledger.node_skipped(key, ", ".join(sorted(unmet)))

    ledger.finish(report)
    return report


@dataclass
class _Watch:
    """One node's passage through the observer: what is open, what round."""

    subjects: list[str]
    round: int = 0
    #: Subject -> the repair task it is waiting on (or about to be given).
    open: dict[str, Any] = field(default_factory=dict)
    #: Subject -> the observation that last failed it.
    last: dict[str, Any] = field(default_factory=dict)
    #: Repair calls out on a worker this round.
    awaiting: set[str] = field(default_factory=set)
    #: Repairs applied this round, to be judged again together.
    landed: list[str] = field(default_factory=list)
    #: Subject -> identities the node's current answer for it consists of.
    authored: dict[str, set[tuple]] = field(default_factory=dict)


def _applied(state: _NodeRun) -> list[str]:
    """The subjects a node actually authored: given, not failed. A blocked
    subject is in ``failed`` too."""
    return [s for s in state.subjects if s not in state.failed]


def _watchable(key: str, state: _NodeRun, order: Sequence[str],
               in_plan: set[str], finished: set[str]) -> bool:
    """Whether the observer judges this node now.

    Not if it authored nothing this run — there is no outcome to judge. And
    not if a later node in the plan is still to write a section this one
    produces: `data_model` names the entities and `entity_fields` details
    them, and a declaration judged on its own would be sent back for the
    fields its author has not written yet. The author is judged instead, and
    its findings route to the same agent.
    """
    if not _applied(state):
        return False
    mine = set(DAG[key].produces)
    return not any(
        other != key and other in in_plan and other not in finished
        and DAG[other].produces & mine
        for other in order
    )


def _pending_sections(in_plan: set[str], settled: set[str]) -> set[str]:
    """Sections a node still to run in this plan will write."""
    return {s for k in in_plan if k not in settled for s in DAG[k].produces}


def _planned_sections(in_plan: set[str]) -> set[str]:
    return {s for k in in_plan for s in DAG[k].produces}


def _subject_resolver(node: DagNode, doc: Mapping[str, Any]) -> Any:
    """For a fan-out whose subject is not the artifact's own id, how a finding
    on an artifact finds the subject to re-author. `page_details` fans out
    per feature — an entity's pages together — so a finding on PAGE-004 is
    the feature that page belongs to."""
    if node.fanout != "page_features":
        return None
    by_page = {
        p["id"]: (str((p.get("data") or {}).get("primaryEntity") or "") or p["id"])
        for p in doc.get("pages") or []
        if isinstance(p, dict) and p.get("id")
    }
    return by_page.get


def _record_observation(report: RunReport, ledger: Any, obs: Any) -> None:
    report.observed[obs.node] = obs.summary()
    for subject in obs.subjects:
        hits = obs.findings.get(subject, [])
        _note(ledger, "observed", obs.node, subject, not hits, len(hits),
              obs.critic)


def _repair_apply(
    svc: BlueprintService, outcome: Any, *, commit: bool, user_request: str,
) -> tuple[str | None, Any]:
    """Apply one repair. ``(None, application)`` when it landed; otherwise
    ``(why it was refused, None)``.

    A refused repair leaves the original artifact exactly as it was — apply
    validates before it commits — so what the observer then flags is the
    author's last accepted answer, never a half-applied fix.
    """
    if isinstance(outcome, Exception):
        return _reason(outcome), None
    if outcome is None:
        return "the executor returned nothing", None
    try:
        application = apply_agent_result(
            svc, outcome, commit=commit, user_request=user_request,
        )
    except (BlueprintInvalid, InvalidPatternTemplate, InvalidWorkflowStep,
            InvalidBusinessRule) as exc:
        return _reason(exc), None
    if application.applied:
        return None, application
    return _asked(application), None


def _proposed_identities(result: Any, application: Any) -> set[tuple]:
    """What one accepted result consists of, as identities the document keeps.

    An id-bearing artifact is ``("id", section, id)``; a keyed-list row
    (a constraint, a relationship, a layout) is ``("keyed", section, key)``
    with the key the section is deduplicated on. Singletons merge and have
    no identity. Ids are read off ``application.artifacts``, which
    :func:`apply_agent_result` fills one per id-bearing proposal, in order.
    """
    from services.blueprint.service import KEYED_LIST_SECTIONS, SINGLETON_SECTIONS

    out: set[tuple] = set()
    ids = list(getattr(application, "artifacts", None) or [])
    i = 0
    for p in getattr(result, "proposals", None) or []:
        section = p.section
        if section in KEYED_LIST_SECTIONS:
            keys = KEYED_LIST_SECTIONS[section]
            out.add(("keyed", section, tuple(p.body.get(k) for k in keys)))
        elif section in SINGLETON_SECTIONS:
            continue
        else:
            if i < len(ids):
                out.add(("id", section, ids[i]))
            i += 1
    return out


def _retire(svc: BlueprintService, identities: set[tuple], *, note: str) -> None:
    """Take a subject's superseded artifacts out of play.

    An id-bearing artifact is marked ``DEPRECATED`` with the note — every
    consumer already skips that status, and §22 lets it be revived. A keyed
    row has no status to carry, so it is removed. Saved once.
    """
    from services.blueprint.service import KEYED_LIST_SECTIONS

    for ident in identities:
        kind, section, key = ident
        if kind == "id":
            try:
                svc.set_status(str(key), "DEPRECATED", note=note)
            except Exception:  # noqa: BLE001 — already gone is already retired
                continue
        elif kind == "keyed":
            keys = KEYED_LIST_SECTIONS[section]
            if "." in section:
                parent, child = section.split(".", 1)
                bucket = (svc.doc.get(parent) or {}).get(child)
            else:
                bucket = svc.doc.get(section)
            if isinstance(bucket, list):
                bucket[:] = [
                    row for row in bucket
                    if not (isinstance(row, dict)
                            and tuple(row.get(k) for k in keys) == key)
                ]
    svc.save()


def _call(executor: Executor, spec: TaskSpec) -> Any:
    """One executor call on a worker thread. Calls, and nothing else.

    No apply happens here and no report is touched, which is what makes it
    safe to run this wide: the half that is network I/O is the half that
    parallelises, and the half that mutates the Blueprint stays on the
    scheduler's thread. An exception is a classified outcome (§102), not a
    crash; the scheduler decides whether it is a retry or a failure.
    """
    try:
        return executor(spec)
    except Exception as exc:  # §102 — a classified outcome, not a crash
        return exc


def _sections(node: DagNode) -> set[str]:
    """Top-level sections a node writes — `data.entities` is `data`."""
    return {p.split(".")[0] for p in node.produces}


def _yields_to(key: str, order: Sequence[str], started: set[str],
               finished: set[str]) -> bool:
    """Whether ``key``'s results must wait for an earlier node still running.

    Applies land in arrival order except between nodes that write the same
    section: there the plan's order is kept, because the id allocator numbers
    a fresh document's artifacts in the order proposals arrive, and two
    producers of `requirements` interleaving by network latency would number
    REQ-001 differently on every build. Only the earlier node in plan order
    holds the later one; a node never waits on something behind it, so this
    cannot deadlock.
    """
    mine = _sections(DAG[key])
    if not mine:
        return False
    for other in order:
        if other == key:
            return False
        if other in started and other not in finished \
                and _sections(DAG[other]) & mine:
            return True
    return False


def _run_deterministic(
    svc: BlueprintService,
    key: str,
    node: DagNode,
    *,
    report: RunReport,
    done: set[str],
    app_root: str | None,
    ledger: Any,
) -> "Any":
    """A service or projection node: deterministic, inline, one writer.

    Returns a :class:`concurrent.futures.Future` when the handler handed one
    back — its work is still running and the caller must wait for it before
    the node counts — and None otherwise."""
    # EVERY KIND OF NODE STARTS, not just the ones that call a model.
    # `node:start` was emitted for agent nodes only, so a service or
    # projection node that ran appeared in `done` and never in `started` —
    # and `explain` therefore listed it as still pending. A node that ran
    # reading as one that never began is the exact misreading this ledger
    # exists to prevent.
    _note(ledger, "node_start", key, 1)
    if node.kind == "service":
        handler = SERVICE_HANDLERS.get(key)
        if handler is None:
            report.blocked.append(key)
            _note(ledger, "node_blocked", key, "no service handler")
            return
        try:
            handler(svc)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            # A derived node that raises used to take the whole run with
            # it: the dispatch was unguarded, so one bad projection lost
            # every node behind it and the report said nothing at all.
            report.failed.append(key)
            report.failed_because[key] = _reason(exc)
            _note(ledger, "node_failed", key, _reason(exc))
            return
    else:
        projector = PROJECTION_HANDLERS.get(key)
        if projector is None or not app_root:
            # Deterministic, but not ported into this package yet. Blocked
            # rather than handed to a model: a model asked to fill codeMap
            # would invent plausible paths that pass validation, and
            # Blueprint<->Implementation would go green against files
            # nobody wrote.
            report.blocked.append(key)
            _note(ledger, "node_blocked", key, "no projection handler or app_root")
            return
        try:
            pending = projector(svc, app_root)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            report.failed.append(key)
            report.failed_because[key] = _reason(exc)
            _note(ledger, "node_failed", key, _reason(exc))
            return None
        from concurrent.futures import Future

        if isinstance(pending, Future):
            return pending
    report.completed.append(key)
    _note(ledger, "node_done", key)
    done.add(key)
    return None


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
#: names the exception, so the report distinguishes transport from content.
#:
#: Enforced by submission, not by a semaphore: the scheduler hands a node its
#: next subject only when fewer than this many are in flight, so a waiting
#: subject waits in the node's own queue and never occupies one of the run's
#: worker threads doing nothing.
FANOUT_CONCURRENCY = 12

#: How many model calls the whole run keeps in flight, across every node that
#: is ready at once. Four fanning-out nodes would otherwise open forty-eight
#: connections, which is how you find the provider's rate limit rather than
#: the machine's. Kept above :data:`FANOUT_CONCURRENCY` so a lone fan-out
#: still runs at full width, and low enough that several nodes share rather
#: than multiply. If a run starts failing several nodes at once, lower this:
#: ``RunReport.failed_because`` names the exception, so the report says
#: whether the cause was transport or content.
#:
#: The name predates the event-driven scheduler: there are no waves now, and
#: this is the size of the run's worker pool. Kept because callers and tests
#: import it by this name.
WAVE_CONCURRENCY = 14


@dataclass
class _NodeRun:
    """One agent node's progress: which subjects are queued, in flight, done."""

    #: Every subject the node authors for; ``[""]`` when it does not fan out.
    subjects: list[str]
    #: The subjects still to be called in the next round. Kept for
    #: :func:`_apply_round`, which applies one round in the given order.
    pending: list[str]
    #: Subject -> why its last attempt was rejected (§102).
    feedback: dict[str, str] = field(default_factory=dict)
    #: Subjects that exhausted their attempts.
    failed: list[str] = field(default_factory=list)
    #: Subjects waiting for a slot — first attempts and retries alike.
    queue: list[str] = field(default_factory=list)
    #: Subjects whose call is out on a worker thread.
    in_flight: set[str] = field(default_factory=set)
    #: Subject -> attempts made so far.
    attempts: dict[str, int] = field(default_factory=dict)
    #: Subject -> the identities its accepted proposals wrote (see
    #: :func:`_proposed_identities`). What a repair of that subject is
    #: measured against: anything here the repair does not re-propose is
    #: retired, because a repair is the subject's whole answer.
    authored: dict[str, set[tuple]] = field(default_factory=dict)


def _apply_subject(
    svc: BlueprintService,
    key: str,
    state: _NodeRun,
    subject: str,
    outcome: Any,
    *,
    attempt: int,
    max_attempts: int,
    commit: bool,
    user_request: str,
    report: RunReport,
    ledger: Any = None,
) -> str:
    """Commit one subject's result. Returns ``"applied"``, ``"retry"``,
    ``"failed"`` or ``"blocked"``.

    A retry is left in ``state.feedback`` with the reason it was rejected.
    §102: a retry that is not told what went wrong is just the same request
    again.
    """
    total = len(state.subjects or [""])
    # A node that does not fan out has one empty subject, and its label is
    # just the node key — callers test membership by it.
    label = f"{key}:{subject}" if subject else key

    def _at() -> int:
        """One-based position in the node's subject list, for the record."""
        try:
            return (state.subjects or []).index(subject) + 1
        except ValueError:  # pragma: no cover — a subject not in its own list
            return 0

    def _rejected(reason: str) -> str:
        """The proposal was refused. Either it goes round again (§103) or
        this was the last attempt and the subject is lost."""
        state.feedback[subject] = reason
        if attempt >= max_attempts:
            report.failed.append(label)
            report.failed_because[label] = reason
            state.failed.append(subject)
            _note(ledger, "node_subject", key, subject, _at(), total, False)
            return "failed"
        _note(ledger, "node_retry", key, subject, attempt + 1, max_attempts, reason)
        return "retry"

    if isinstance(outcome, Exception):
        return _rejected(_reason(outcome))

    try:
        application = apply_agent_result(
            svc, outcome, commit=commit, user_request=user_request,
        )
    except (BlueprintInvalid, InvalidPatternTemplate, InvalidWorkflowStep, InvalidBusinessRule) as exc:
        # The author's refusals are outcomes here too. InvalidBusinessRule
        # escaped this path on 2026-09-06 and took a whole build down with
        # no end event written.
        return _rejected(_reason(exc))

    if application.applied:
        report.artifacts.extend(application.artifacts)
        report.change_requests.extend(application.change_requests)
        state.authored.setdefault(subject, set()).update(
            _proposed_identities(outcome, application))
        _note(ledger, "node_subject", key, subject, _at(), total, True)
        return "applied"
    if application.needs_clarification or outcome.status == "blocked":
        if attempt < max_attempts:
            return _rejected(_asked(application))
        report.blocked.append(label)
        report.blocked_because[label] = _asked(application)
        report.change_requests.extend(application.change_requests)
        _note(ledger, "node_blocked", key, _asked(application))
        state.failed.append(subject)
        return "blocked"
    if attempt >= max_attempts:
        report.failed.append(label)
        report.failed_because.setdefault(
            label, "the agent returned a result that could not be applied")
        state.failed.append(subject)
        return "failed"
    return "retry"


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

    The scheduler applies subject by subject as results arrive; this applies a
    whole round at once and returns the subjects to retry. Kept for callers
    that have a round in hand rather than a stream.
    """
    retry: list[str] = []
    for subject in state.pending:  # given order, not completion order
        verdict = _apply_subject(
            svc, key, state, subject, results.get((key, subject)),
            attempt=attempt, max_attempts=max_attempts, commit=commit,
            user_request=user_request, report=report, ledger=ledger,
        )
        if verdict == "retry":
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
        except (BlueprintInvalid, InvalidPatternTemplate, InvalidWorkflowStep, InvalidBusinessRule) as exc:
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
    from services.blueprint.projection import project_business_rules
    project_business_rules(svc.doc, app_root)
    project_sensitive_columns(svc.doc, app_root)
    project_searchable_columns(svc.doc, app_root)
    project_append_only_entities(svc.doc, app_root)
    project_ownership_rules(svc.doc, app_root)


def _project_frontend(svc: BlueprintService, app_root: str) -> None:
    """Everything the browser reads: page schemas, the route graph, the tokens."""
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

    # DROP-AND-CONTINUE, NOT DROP-THE-APPLICATION. A page whose authored tree
    # the planner cannot render is dropped — its route 404s — which is exactly
    # the outcome `_unbuilt_pages` already gives a page that never composed (see
    # the fan-out note: "the run still succeeds, and the app 404s where a page
    # should be"). Raising here instead failed the whole `frontend` node,
    # cascaded to `integration`/`testing`, and held the project in `draft` — no
    # Publish — over a handful of imperfect pages while forty others were ready
    # to ship. A frontend retry cannot fix these anyway: the tree is authored by
    # `page_layouts`, and re-planning the same tree fails the same way. Record
    # what was dropped so the run and the UI still name it, and let the node
    # succeed with the pages that DID plan.
    # A dropped page writes no schema, so it is already accounted for where a
    # never-composed page is: `runtime["pages"]` (the preview node's page_funnel
    # counts it as planned-but-not-served) and `_unbuilt_pages`, which is what
    # the run panel's "N pages did not build" is read from. Nothing new is
    # written to the closed Blueprint here — only a log line naming the reason,
    # which page_funnel does not carry.
    if result.get("failed"):
        logger.warning(
            "[frontend] %d authored page(s) could not be planned and were "
            "dropped (their routes 404): %s",
            len(result["failed"]),
            "; ".join(f"{f['page']}: {str(f['reason'])[:120]}"
                      for f in result["failed"][:6]),
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
def _project_install(svc: BlueprintService, app_root: str) -> Any:
    """Lay down the scaffold and engines and install against them — on its
    own thread, handed back as a future, because this is minutes of `npm`
    and the scheduler thread is the document's one writer.

    Reads the document once, here, under the lock the scheduler holds; the
    thread touches files only.
    """
    from concurrent.futures import ThreadPoolExecutor

    from services.blueprint.assembly import install_dependencies, prepare_app_root

    short_id = (svc.doc.get("application") or {}).get("id", "forge")

    def work() -> int:
        prepare_app_root(app_root, project_short_id=short_id)
        return install_dependencies(app_root)

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge-install")
    future = pool.submit(work)
    pool.shutdown(wait=False)  # the worker finishes the job; nobody blocks here
    return future


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
    # The `install` node already installed when `node_modules` is there; a
    # missing directory means it did not run (no app_root at the time, a
    # resumed plan without it) and the build installs for itself.
    from pathlib import Path as _P

    result = verify_build(app_root, install=not (_P(app_root) / "node_modules").is_dir())
    result.setdefault("install", 0)
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
    "install": _project_install,
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
