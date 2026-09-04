"""Prompt-to-change (PRD §69, §70, §71, §72, §114).

§114 renames maintenance: *"Application maintenance becomes Prompt-to-Change."*
Twelve numbered steps, of which this module owns three — identify affected
artifacts, update the Blueprint, create the incremental DAG — and sequences the
rest.

§69 supplies the referent
-------------------------
The user clicks a table in Preview and says *"make this more compact."* Smith
should receive the page, the selected component, its type, its entity, its
implementation and its requirements — so that "this" resolves without the user
describing what they just clicked.

:class:`PreviewContext` is that payload, and :func:`resolve_preview` fills in
every field §69 lists from the Blueprint. None of it is inferred; it is all
already recorded, and a request that arrives with a selection is the one case
where Smith has certainty about what is being talked about.

§71 is the part that does not exist yet
---------------------------------------
Impact analysis is *"mandatory for significant changes"*, and §71's example
splits its answer in two::

    NEW:       Manager Approval Workflow, Approval Status, Manager Inbox, …
    MODIFIED:  Vehicle Entity, Gate Workflow, Gate Rule, Dashboard, Tests

``orchestrator.impacted_artifacts`` computes the second half. Nothing computed
the first, and the omission is not cosmetic: a change that only *adds* things
has no impacted artifacts at all, so ``incremental_plan`` selects an empty plan
and the change is silently a no-op.

The split is decided by the ID allocator, not by asking. A proposal whose
natural key is already bound names an artifact that exists — MODIFIED. An
unbound key is something new. That is a lookup, not a judgement, which is why
it belongs here rather than in a prompt.

Order matters (§13)
-------------------
*"When the user modifies the application, the Blueprint must be updated
first."* So :func:`apply_change` commits through :class:`BlueprintService`
before a single agent runs, and the version it creates is what the incremental
DAG then regenerates against. Running agents first and reconciling after is the
architecture §115 exists to forbid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from services.blueprint.agent_contract import ArtifactProposal
from services.blueprint.ids import (
    IdAllocator,
    is_valid_id,
    natural_key_for,
    parse_id,
)
from services.blueprint.orchestrator import (
    DAG,
    RunReport,
    impacted_artifacts,
    incremental_plan,
    sections_of,
)
from services.blueprint.service import ARTIFACT_SECTIONS, BlueprintService
from services.smith.code_intel import where

#: §71's own vocabulary.
NEW = "NEW"
MODIFIED = "MODIFIED"

#: How far impact analysis walks for §71's report.
#:
#: Two hops covers §71's own example — changing the Vehicle entity reaches the
#: Gate Workflow and Gate Rule that cite it (one hop) and the Tests that cover
#: those (two). Unbounded returns the whole application from any starting point
#: and so distinguishes nothing; see ``impacted_artifacts``.
IMPACT_DEPTH = 2


@dataclass(frozen=True)
class PreviewContext:
    """§69 — what Smith receives when the user points at something.

    Every field is one of §69's bullets. ``requirements`` and ``implementation``
    are resolved rather than supplied: the preview knows which component was
    clicked, and the Blueprint knows the rest.
    """

    page: str = ""
    component: str = ""
    component_type: str = ""
    entity: str = ""
    implementation: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()

    @property
    def anchors(self) -> tuple[str, ...]:
        """What the context resolver should treat as certain.

        Includes the entity, because §69 lists it among what Smith receives in
        order to *understand* the selection.
        """
        return tuple(a for a in (self.component, self.page, self.entity) if a)

    @property
    def subject(self) -> tuple[str, ...]:
        """What the user actually pointed at — the seed for impact analysis.

        Deliberately narrower than :attr:`anchors`. §69 supplies the associated
        entity as context, not as a thing being changed, and seeding impact
        analysis with it says the opposite: "make this table more compact"
        becomes a change to the Candidate entity, which reaches every page,
        workflow and rule in the application. Context wants breadth; impact
        wants to be right.
        """
        return tuple(a for a in (self.component, self.page) if a)

    @property
    def empty(self) -> bool:
        return not (self.page or self.component)

    def describe(self) -> str:
        """One line naming what "this" refers to, for a prompt."""
        if self.empty:
            return "(no preview selection — the request must name its own subject)"
        bits = []
        if self.component:
            bits.append(f"component {self.component}"
                        + (f" ({self.component_type})" if self.component_type else ""))
        if self.page:
            bits.append(f"on page {self.page}")
        if self.entity:
            bits.append(f"bound to {self.entity}")
        if self.requirements:
            bits.append(f"serving {', '.join(self.requirements)}")
        return "; ".join(bits)


def resolve_preview(
    doc: dict, *, page: str = "", component: str = "", **_ignored: Any
) -> PreviewContext:
    """Fill in §69's payload from a page id and a selected component id."""
    pages = {p.get("id"): p for p in (doc.get("pages") or [])}
    components = {c.get("id"): c for c in (doc.get("components") or [])}

    page_art = pages.get(page) or {}
    cmp_art = components.get(component) or {}

    entity = cmp_art.get("entity") or ""
    if not entity:
        data = page_art.get("data")
        if isinstance(data, dict):
            entity = data.get("primaryEntity") or ""

    requirements: list[str] = []
    for art in (cmp_art, page_art):
        for req in art.get("requirements") or []:
            if req not in requirements:
                requirements.append(req)

    files: list[str] = []
    for artifact_id in (component, page, entity):
        if artifact_id:
            files.extend(where(doc, artifact_id).files)

    return PreviewContext(
        page=page if page in pages else "",
        component=component if component in components else "",
        component_type=str(cmp_art.get("type") or cmp_art.get("name") or ""),
        entity=entity,
        implementation=tuple(dict.fromkeys(files)),
        requirements=tuple(requirements),
    )


@dataclass
class ImpactReport:
    """§71's answer, in §71's shape."""

    request: str
    #: Artifacts that exist and are disturbed by the change.
    modified: list[str] = field(default_factory=list)
    #: The subset of ``modified`` that references the change directly — one hop.
    #: Separated because the two read very differently to a user approving a
    #: change: "CMP-033" is what you touched, and the other sixty-two are what
    #: share it. A single undifferentiated list of sixty-three makes a
    #: presentational tweak look like a rewrite.
    direct: list[str] = field(default_factory=list)
    #: Artifacts the change introduces, as ``(section, natural_key)``. They
    #: have no ids yet — ids are allocated when the proposal is committed.
    new: list[tuple[str, str]] = field(default_factory=list)
    #: natural_key -> a human name for it. Business rules and requirements are
    #: keyed on a digest of their prose (§12: reworded prose is still the same
    #: artifact), so the key is `RULE:190b43a7f8fda257`. §71's report is what a
    #: user approves a change from — its own example reads "Manager Approval
    #: Workflow", not a hash.
    labels: dict[str, str] = field(default_factory=dict)
    #: Blueprint sections the work lands in.
    sections: set[str] = field(default_factory=set)
    #: The sub-DAG, in dependency order (§72).
    plan: list[str] = field(default_factory=list)
    #: True when nothing is affected and nothing is added — the request does
    #: not change the application, and should be answered rather than built.
    empty: bool = False

    def render(self) -> str:
        """§71's two-column summary, for showing the user before building."""
        lines = []
        if self.new:
            lines.append("NEW:")
            lines += [
                f"  {self.labels.get(key, key)}  ({section})"
                for section, key in self.new
            ]
        if self.direct:
            lines.append("MODIFIED (directly):")
            lines += [f"  {a}" for a in self.direct]
        downstream = [a for a in self.modified if a not in set(self.direct)]
        if downstream:
            lines.append(f"MODIFIED (downstream, {len(downstream)}):")
            lines += [f"  {a}" for a in downstream[:12]]
            if len(downstream) > 12:
                lines.append(f"  … and {len(downstream) - 12} more")
        if not lines:
            lines.append("No application artifacts are affected.")
        lines.append(f"\nRe-running {len(self.plan)} of {len(DAG)} nodes: "
                     + (", ".join(self.plan) or "(none)"))
        return "\n".join(lines)


def _prefix_for(section: str) -> str | None:
    return "ENTITY" if section == "data.entities" else ARTIFACT_SECTIONS.get(section)


def canonicalise(
    proposals: Sequence[ArtifactProposal], doc: dict,
) -> list[ArtifactProposal]:
    """Restate each proposal's natural key in the registry's own scheme.

    A model states identity in its own terms — "Sign In", or "/sign-in" — and
    the registry keys pages as ``PAGE:/sign-in``. Those are the same page, and
    nothing but the deterministic layer can say so: ``natural_key_for`` derives
    the canonical key from the artifact's own fields, which is what it exists
    for.

    This is not a repair of bad output. The model is not being corrected; it is
    being *read*, by the one component that owns identity (§12/§116). Skipping
    it has two failure modes and both are silent-ish: the NEW/MODIFIED split
    calls an existing page new, and the upsert then allocates a second id for
    it — which is now an ``IdentityCollision``, so the change is refused rather
    than corrupting anything, but it is refused for a reason the user cannot
    act on.

    Where no scheme applies the model's own key stands.
    """
    page_routes = {
        page["id"]: page.get("route") or ""
        for page in (doc.get("pages") or [])
        if page.get("id")
    }
    out: list[ArtifactProposal] = []
    for p in proposals:
        key = natural_key_for(p.section, p.body, page_routes=page_routes)
        out.append(
            ArtifactProposal(p.section, key, p.body) if key else p
        )
    return out


def analyse(
    svc: BlueprintService,
    request: str,
    *,
    anchors: Sequence[str] = (),
    proposals: Sequence[ArtifactProposal] = (),
    depth: int | None = IMPACT_DEPTH,
) -> ImpactReport:
    """§71 — what this change touches, before anything is written.

    Read-only. Allocates nothing: the NEW/MODIFIED split uses
    :meth:`IdAllocator.lookup`, which answers whether a natural key is already
    bound without binding it. Impact analysis that had side effects could not
    be shown to the user for approval, which §114 step 4 requires.
    """
    doc = svc.doc
    alloc = IdAllocator.load(output_dir=svc.output_dir)

    known = {
        a.get("id")
        for section in list(ARTIFACT_SECTIONS)
        for a in (doc.get(section) or [])
    } | {e.get("id") for e in (doc.get("data") or {}).get("entities") or []}

    seeds = {a for a in anchors if a in known}

    proposals = canonicalise(proposals, doc)

    new: list[tuple[str, str]] = []
    labels: dict[str, str] = {}
    new_sections: set[str] = set()
    for p in proposals:
        prefix = _prefix_for(p.section)
        if prefix is None:
            # A singleton section (security, navigation, …). It has no id to
            # be new or modified; it is simply written, and its section still
            # has to seed the plan.
            new_sections.add(p.section)
            continue
        bound = alloc.lookup(p.natural_key)
        if bound and bound in known:
            seeds.add(bound)
        else:
            new.append((p.section, p.natural_key))
            label = (p.body.get("name") or p.body.get("route")
                     or p.body.get("description") or "")
            if label:
                labels[p.natural_key] = str(label)[:80]
        new_sections.add(p.section)

    def _sorted(ids: Any) -> list[str]:
        return sorted(
            (a for a in ids if is_valid_id(a)),
            key=lambda i: (parse_id(i)[0], parse_id(i)[1]),
        )

    affected = impacted_artifacts(doc, seeds, depth=depth) if seeds else set()
    direct = impacted_artifacts(doc, seeds, depth=1) if seeds else set()
    modified = _sorted(affected)

    sections = sections_of(doc, affected) | new_sections
    # The plan is computed from the *bounded* impact set rather than from the
    # seeds, so what gets regenerated is what the user was shown. A plan drawn
    # from the unbounded closure would quietly rebuild more than the report
    # said, which makes the report a lie rather than a summary.
    plan = (
        incremental_plan(doc, seeds, also_sections=new_sections)
        if (seeds or new_sections) else []
    )

    return ImpactReport(
        request=request,
        modified=modified,
        direct=_sorted(direct),
        new=sorted(new),
        labels=labels,
        sections=sections,
        plan=plan,
        empty=not modified and not new and not new_sections,
    )


@dataclass
class ChangeResult:
    """What one prompt-to-change turn actually did."""

    impact: ImpactReport
    version: int = 0
    committed: list[str] = field(default_factory=list)
    run: RunReport | None = None
    applied: bool = False
    reason: str = ""


def apply_change(
    svc: BlueprintService,
    request: str,
    *,
    proposals: Sequence[ArtifactProposal] = (),
    anchors: Sequence[str] = (),
    interpretation: str = "",
    agent: str = "smith",
    executor: Callable[[Any], Any] | None = None,
    app_root: str | None = None,
    run_agents: bool = True,
    regenerate: bool = True,
    observer: Callable[[dict], None] | None = None,
) -> ChangeResult:
    """§114 steps 3–7: analyse, update the Blueprint, then run the sub-DAG.

    The Blueprint is committed *before* any agent runs (§13), so the version
    the agents regenerate against is the one that already contains the change.
    If the commit fails the run does not happen at all — a half-applied change
    is worse than a refused one, because the next impact analysis is computed
    against a document nobody believes.

    ``regenerate`` is False while the application is still being defined. §72's
    incremental plan answers "what must be rebuilt", and before there is a
    definition the answer is nothing — the requirements have just been written
    and the authoring pass has not run yet, so a plan computed here would
    re-run seventeen nodes to regenerate an application that does not exist.
    The write still goes through the Blueprint and is still versioned; only the
    regeneration is skipped.

    ``executor`` is injected, exactly as :func:`orchestrator.run` takes it, so
    this is testable without a model. With ``run_agents=False`` the change lands
    in the Blueprint and the plan is reported but not executed — which is what
    §114 step 4 ("proposes change if necessary") needs in order to ask first.

    ``observer`` is passed to the run's ledger, so a caller with somewhere to
    show progress — the virtual office — sees the sub-DAG unfold live instead
    of waiting for one report at the end.
    """
    from services.blueprint.agent_contract import AgentResult, apply_agent_result

    proposals = canonicalise(proposals, svc.doc)
    impact = analyse(svc, request, anchors=anchors, proposals=proposals)
    if impact.empty:
        return ChangeResult(
            impact=impact, version=svc.doc.get("version", 1),
            reason="the request does not affect any application artifact",
        )

    before = svc.snapshot()

    committed: list[str] = []
    if proposals:
        result = AgentResult(
            task_id=f"TASK-smith-change-{svc.doc.get('version', 1)}",
            agent=agent,
            proposals=list(proposals),
            confidence=1.0,
        )
        # Through the same gate as every agent (§30, §120). Smith's boundary is
        # declared in AGENT_REGISTRY and enforced here, not assumed.
        application = apply_agent_result(svc, result, commit=False)
        if not application.applied:
            return ChangeResult(
                impact=impact, version=svc.doc.get("version", 1),
                reason=application.reason or "the proposed change was refused",
            )
        committed = list(application.artifacts)

    if committed:
        record = svc.commit(
            user_request=request,
            smith_interpretation=interpretation,
            before=before,
            affected=sorted(set(impact.modified) | set(committed)),
        )
        version = record["version"]
    else:
        # Nothing was written, so there is nothing to version. §91 versions an
        # *accepted change*; an empty diff with a bumped number is history
        # nobody can read — and it would make §93 rollback offer a version
        # identical to the one before it.
        #
        # This is still a legitimate turn: regenerating from an unchanged
        # Blueprint is what you do after fixing a projection, and §115 is
        # satisfied because the definition did not move.
        version = svc.doc.get("version", 1)

    # Newly-created artifacts change the graph, so the plan is recomputed
    # against the committed document. Computing it once before the write would
    # plan against a Blueprint that did not yet contain the change.
    if not regenerate:
        impact.plan = []
        return ChangeResult(
            impact=impact, version=version, committed=committed, applied=True,
        )

    written = {p.section for p in proposals}
    impact.plan = incremental_plan(
        svc.doc,
        # What was actually written plus what the user pointed at — not the
        # impact closure, which is the §71 report's question, not the plan's.
        set(committed) | set(anchors),
        also_sections={section for section, _key in impact.new} | written,
        # Smith authored these this turn, from what the user said. Re-running
        # the agent that owns them would re-author them (§20).
        already_written=written,
    )

    report = None
    if run_agents and executor is not None:
        from services.blueprint.orchestrator import run as run_dag

        report = run_dag(
            svc, executor, plan=impact.plan, commit=False,
            user_request=request, app_root=app_root, observer=observer,
        )

    return ChangeResult(
        impact=impact,
        version=version,
        committed=committed,
        run=report,
        applied=True,
    )
