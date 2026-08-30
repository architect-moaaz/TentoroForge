"""Cross-agent verification matrix (PRD §73–§76).

§75 lists ten relationships that must hold across a generated application:

    Page ↔ API            API ↔ Database        Page ↔ Permission
    API ↔ Permission      Workflow ↔ Rule       Workflow ↔ API
    Design ↔ Design System                      Requirement ↔ Code
    Requirement ↔ Test                          Blueprint ↔ Implementation

The old platform checked most of these too — scattered across
``contract_validator``, ``read_binding_guard``, ``action_contract_guard``,
``fk_source_guard`` and a few dozen more, each discovered by a UAT bug and each
followed immediately by a repair. This module keeps the checking and drops the
repairing.

The difference is §76: *"out-of-sync artifacts must be flagged"*. A finding here
becomes an ``OUT_OF_SYNC`` status on a named artifact (§22) plus a repair task
addressed to the agent that owns it (§74). It never edits the artifact. An
inconsistency the platform silently fixes is an inconsistency nobody ever
designs away, which is how 151 sequential passes happen.

Scope, honestly stated
----------------------
Every check here reads the Blueprint. The two edges that reach past it —
``Requirement ↔ Code`` and ``Blueprint ↔ Implementation`` — are verified
against ``codeMap`` (§21), which is the Blueprint's own record of where things
live. Confirming that ``codeMap`` matches files actually on disk is a separate
pass that needs the generated application; :func:`verify` does not claim to do
it, and :data:`UNVERIFIED_HERE` says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.blueprint.agent_contract import AGENT_REGISTRY, capability_for
from services.blueprint.service import BlueprintService

#: §75's ten relationships, verbatim in order.
EDGES: tuple[str, ...] = (
    "Page↔API",
    "API↔Database",
    "Page↔Permission",
    "API↔Permission",
    "Workflow↔BusinessRule",
    "Workflow↔API",
    "Design↔DesignSystem",
    "Requirement↔Code",
    "Requirement↔Test",
    "Blueprint↔Implementation",
    # Added by the migration ledger: each collapses a cluster of passes from
    # the old repair chain that the PRD's ten edges do not cover.
    "Navigation↔Page",
    "Page↔Precondition",
    "Page↔Workflow",
    "Widget↔DataSource",
    "Page↔Layout",
    # §73 — every other edge asks whether the Blueprint is coherent. This asks
    # whether what it describes would do anything.
    "Page↔Function",
)

#: What this module does *not* establish, so nobody mistakes a green report for
#: more than it is.
UNVERIFIED_HERE = (
    "codeMap entries are not checked against files on disk; "
    "runtime behaviour is not exercised (§66 preview and §77 tests cover that)"
)

#: Which agent owns each Blueprint section, for §74 repair-task routing.
#: Several agents may *write* a section (``apis`` is writable by both ``api``
#: and ``backend``); ownership has to be a decision, not a scan.
SECTION_OWNER: dict[str, str] = {
    "requirements": "requirement",
    "product": "product_analysis",
    "modules": "solution_architecture",
    "navigation": "solution_architecture",
    "pages": "page_design",
    # §34 — A2UI is the composition authority, so a composed page that is
    # wrong is its to author again. The section was already reachable as a
    # finding's `section` through the Page↔Layout edge and had no owner, so
    # every one of those repair tasks was addressed to "unassigned".
    "pageLayouts": "a2ui_pages",
    "components": "frontend",
    "widgets": "page_design",
    "designSystem": "accessibility",
    "data.entities": "data_model",
    "data.relationships": "data_model",
    "data.constraints": "data_model",
    "database": "data_model",
    "apis": "api",
    "workflows": "workflow",
    "businessRules": "business_rules",
    "integrations": "integration",
    "security": "security",
    "roles": "security",
    "permissions": "security",
    "tests": "testing",
    "runtime": "build",
    "deployment": "deployment",
    "codeMap": "backend",
}

#: Methods that change state and therefore need an explicit permission (§100).
MUTATING = ("POST", "PUT", "PATCH", "DELETE")

#: Page actions that imply a backing endpoint, and the method each needs.
ACTION_METHOD = {"create": "POST", "edit": "PUT", "update": "PUT", "delete": "DELETE"}


@dataclass(frozen=True)
class Finding:
    """One violated relationship."""

    edge: str
    detail: str
    artifact_id: str | None = None
    section: str | None = None

    @property
    def responsible_agent(self) -> str | None:
        """§74 — 'the responsible agent receives a repair task'."""
        return SECTION_OWNER.get(self.section or "")

    def __str__(self) -> str:  # pragma: no cover - diagnostics
        who = self.artifact_id or self.section or "<blueprint>"
        return f"[{self.edge}] {who}: {self.detail}"


@dataclass
class VerificationReport:
    findings: list[Finding] = field(default_factory=list)
    checked_edges: tuple[str, ...] = EDGES

    @property
    def passed(self) -> bool:
        return not self.findings

    def by_edge(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.edge, []).append(f)
        return out

    def repair_tasks(self) -> dict[str, list[Finding]]:
        """§74 — findings grouped by the agent that must fix them."""
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.responsible_agent or "unassigned", []).append(f)
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": len(self.findings),
            "edges": {e: len(v) for e, v in sorted(self.by_edge().items())},
            "agents": {a: len(v) for a, v in sorted(self.repair_tasks().items())},
            "unverified": UNVERIFIED_HERE,
        }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ids(items: list[dict] | None) -> set[str]:
    return {i.get("id") for i in (items or []) if i.get("id")}


def _entities(doc: dict) -> list[dict]:
    return doc.get("data", {}).get("entities", []) or []


def _live(items: list[dict] | None) -> list[dict]:
    """Deprecated artifacts are excluded — §22 keeps them for history, not
    as obligations."""
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


# ---------------------------------------------------------------------------
# checks — one per §75 edge
# ---------------------------------------------------------------------------

def check_page_api(doc: dict) -> list[Finding]:
    """Every action a page offers needs an endpoint behind it."""
    out: list[Finding] = []
    apis = _live(doc.get("apis"))
    for page in _live(doc.get("pages")):
        entity = (page.get("data") or {}).get("primaryEntity")
        if not entity:
            continue
        for action in page.get("actions") or []:
            method = ACTION_METHOD.get(str(action).lower())
            if not method:
                continue
            if not any(a.get("entity") == entity and a.get("method") == method for a in apis):
                out.append(Finding(
                    "Page↔API", section="pages", artifact_id=page.get("id"),
                    detail=f"action {action!r} on {entity} has no {method} endpoint",
                ))
    return out


def check_api_database(doc: dict) -> list[Finding]:
    """The data layer must hang together: endpoints, relationships and
    constraints may only reference entities and columns that exist.

    The relationship half is what ``fk_type_guard`` and ``fk_source_guard``
    used to repair by rewriting the offending column. Declared relationships
    make the mismatch visible instead.
    """
    entities = {e.get("id"): e for e in _entities(doc)}
    known = set(entities)
    out: list[Finding] = []

    for api in _live(doc.get("apis")):
        if api.get("entity") and api["entity"] not in known:
            out.append(Finding(
                "API↔Database", section="apis", artifact_id=api.get("id"),
                detail=f"references unknown entity {api['entity']}",
            ))

    data = doc.get("data", {}) or {}
    for rel in data.get("relationships") or []:
        for end in ("from", "to"):
            target = rel.get(end)
            if target and target not in known:
                out.append(Finding(
                    "API↔Database", section="data.relationships",
                    artifact_id=target,
                    detail=(f"relationship {rel.get('from')}->{rel.get('to')} "
                            f"({rel.get('kind')}) names unknown entity {target}"),
                ))
        # A named end-field must be a real column on that end's entity.
        for end, field_key in (("from", "fromField"), ("to", "toField")):
            col, ent = rel.get(field_key), entities.get(rel.get(end))
            if not col or ent is None:
                continue
            cols = {f.get("name") for f in ent.get("fields") or []}
            if cols and col not in cols:
                out.append(Finding(
                    "API↔Database", section="data.relationships",
                    artifact_id=rel.get(end),
                    detail=f"{field_key} {col!r} is not a column on {ent.get('name')}",
                ))

    for con in data.get("constraints") or []:
        if con.get("entity") and con["entity"] not in known:
            out.append(Finding(
                "API↔Database", section="data.constraints",
                artifact_id=con.get("entity"),
                detail=f"constraint names unknown entity {con['entity']}",
            ))
    return out


def check_page_permission(doc: dict) -> list[Finding]:
    """A page addressed to a role that does not exist is unreachable."""
    roles = _ids(doc.get("roles"))
    out: list[Finding] = []
    for page in _live(doc.get("pages")):
        for role in page.get("users") or []:
            if role not in roles:
                out.append(Finding(
                    "Page↔Permission", section="pages", artifact_id=page.get("id"),
                    detail=f"addressed to unknown role {role}",
                ))
    return out


def check_page_layout(doc: dict) -> list[Finding]:
    """A page can only be rendered if something composed a tree for it.

    Two ways this breaks, and both are silent without the edge. A page that
    nothing composed projects to nothing — and eleven pages out of eighteen
    looks exactly like success. Or a composed tree names a component the
    registry does not have, which only surfaces when something tries to
    render it.

    Used to read `patternTemplates`, one template per pattern, and ask whether
    each page's pattern had one. Both the section and the agent that authored
    it are gone: A2UI composes per page, so the question is now asked of the
    page itself.
    """
    from services.blueprint.page_planner import load_catalog, validate_template

    authored = {l.get("page"): l for l in _live(doc.get("pageLayouts"))}
    out: list[Finding] = []

    for page in _live(doc.get("pages")):
        if page.get("id") not in authored:
            out.append(Finding(
                "Page↔Layout", section="pages",
                artifact_id=page.get("id"),
                detail="no composed tree, so the page cannot be projected",
            ))

    if authored:
        catalog = load_catalog()
        for page_id, layout in sorted(authored.items()):
            for error in validate_template(layout, catalog):
                out.append(Finding(
                    "Page↔Layout", section="pageLayouts",
                    artifact_id=page_id, detail=error,
                ))
    return out


def check_api_permission(doc: dict) -> list[Finding]:
    """State-changing endpoints need an explicit permission (§100)."""
    perms = _ids(doc.get("permissions"))
    out: list[Finding] = []
    for api in _live(doc.get("apis")):
        perm = api.get("permission")
        if perm and perm not in perms:
            out.append(Finding(
                "API↔Permission", section="apis", artifact_id=api.get("id"),
                detail=f"references unknown permission {perm}",
            ))
        elif not perm and api.get("method") in MUTATING:
            out.append(Finding(
                "API↔Permission", section="apis", artifact_id=api.get("id"),
                detail=f"{api.get('method')} {api.get('path')} has no permission",
            ))
    return out


def check_workflow_rule(doc: dict) -> list[Finding]:
    """A rule may not govern an artifact that isn't there."""
    everything = (
        _ids(doc.get("pages")) | _ids(doc.get("apis")) | _ids(doc.get("workflows"))
        | _ids(_entities(doc)) | _ids(doc.get("roles")) | _ids(doc.get("permissions"))
    )
    out: list[Finding] = []
    for rule in _live(doc.get("businessRules")):
        for target in rule.get("appliesTo") or []:
            if target not in everything:
                out.append(Finding(
                    "Workflow↔BusinessRule", section="businessRules",
                    artifact_id=rule.get("id"),
                    detail=f"applies to unknown artifact {target}",
                ))
    return out


def check_workflow_api(doc: dict) -> list[Finding]:
    """A workflow step that mutates an entity needs an endpoint, and a
    workflow launched from a page needs that page to exist."""
    known_entities = _ids(_entities(doc))
    pages = _ids(doc.get("pages"))
    apis = _live(doc.get("apis"))
    out: list[Finding] = []
    for wf in _live(doc.get("workflows")):
        for page_id in wf.get("launchedFrom") or []:
            if page_id not in pages:
                out.append(Finding(
                    "Workflow↔API", section="workflows", artifact_id=wf.get("id"),
                    detail=f"launched from unknown page {page_id}",
                ))
        for step in wf.get("steps") or []:
            entity = step.get("entity")
            if not entity:
                continue
            if entity not in known_entities:
                out.append(Finding(
                    "Workflow↔API", section="workflows", artifact_id=wf.get("id"),
                    detail=f"step {step.get('key')!r} mutates unknown entity {entity}",
                ))
            elif not any(a.get("entity") == entity and a.get("method") in MUTATING
                         for a in apis):
                out.append(Finding(
                    "Workflow↔API", section="workflows", artifact_id=wf.get("id"),
                    detail=f"step {step.get('key')!r} mutates {entity} with no write endpoint",
                ))
    return out


def check_page_function(doc: dict) -> list[Finding]:
    """§73 — would this application actually work?

    Controls that declare no action, actions naming workflows that do not
    exist, bindings with no source, pages nothing composed. Each was found by
    somebody using the generated app; none needed it running to find.
    """
    from services.blueprint.functional_completeness import functional_findings

    return [
        Finding("Page↔Function", section="pageLayouts",
                artifact_id=f["page"], detail=f["detail"])
        for f in functional_findings(doc)
    ]


def check_design_system(doc: dict) -> list[Finding]:
    """§38 — the design language every page is composed against must exist.

    Was a registry check: `components` carried a `registryKey` and `uiRegistry`
    listed the keys, so a component could be caught naming a key nobody
    declared. Both sections were authored by `page_designs`, which is gone —
    the registry was a list of names that were never code, and the edge was
    checking one LLM section against another.

    The failure worth catching is upstream of that and was never covered: a
    `designSystem` too thin to compose against. One run produced 174 bytes of
    it, `project_design_tokens` emitted almost no variables, every page was
    composed against a palette that wasn't there, and the app came out
    unstyled. Nothing reported it, because a missing token is not an error
    anywhere downstream — it is just absence.
    """
    design = doc.get("designSystem") or {}
    if not design:
        return [Finding("Design↔DesignSystem", section="designSystem",
                        detail="no design system, so every page is composed "
                               "against a language that does not exist")]

    # The groups `project_design_tokens` reads. A group that is missing does
    # not fail the projection; it silently emits fewer variables.
    return [
        Finding("Design↔DesignSystem", section="designSystem",
                artifact_id=group,
                detail=f"{group!r} is missing, so nothing projects into "
                       f"tokens.css for it")
        for group in ("colors", "spacing", "typography", "radius")
        if not (design.get(group) or {})
    ]


def check_requirement_code(doc: dict) -> list[Finding]:
    """§18/§21 — an approved requirement must be traceable to something built.

    This is §74's question — "has this requirement been implemented?" — asked
    of the Blueprint. A requirement nothing claims is a requirement that was
    approved and then quietly dropped.
    """
    mapped = {e.get("artifact") for e in doc.get("codeMap") or []}
    claims: dict[str, list[str]] = {}
    for section in ("pages", "apis", "workflows", "businessRules", "components"):
        for art in _live(doc.get(section)):
            for req in art.get("requirements") or []:
                claims.setdefault(req, []).append(art.get("id"))
    for ent in _live(_entities(doc)):
        for req in ent.get("requirements") or []:
            claims.setdefault(req, []).append(ent.get("id"))

    out: list[Finding] = []
    for req in _live(doc.get("requirements")):
        if req.get("status") in ("PROPOSED",):
            continue  # not yet approved; nothing owes it an implementation
        owners = claims.get(req.get("id"), [])
        if not owners:
            out.append(Finding(
                "Requirement↔Code", section="requirements", artifact_id=req.get("id"),
                detail="no artifact claims this requirement",
            ))
        elif not any(o in mapped for o in owners):
            out.append(Finding(
                "Requirement↔Code", section="requirements", artifact_id=req.get("id"),
                detail=f"claimed by {', '.join(owners)} but none appear in codeMap",
            ))
    return out


def check_requirement_test(doc: dict) -> list[Finding]:
    """§75 Requirement↔Test — an unverified requirement is an assertion."""
    verified: set[str] = set()
    for t in _live(doc.get("tests")):
        verified.update(t.get("verifies") or [])
    return [
        Finding("Requirement↔Test", section="requirements", artifact_id=r.get("id"),
                detail="no test verifies this requirement")
        for r in _live(doc.get("requirements"))
        if r.get("status") not in ("PROPOSED",) and r.get("id") not in verified
    ]


def check_blueprint_implementation(doc: dict) -> list[Finding]:
    """§76 — anything claiming to be built must say where it lives."""
    mapped = {e.get("artifact") for e in doc.get("codeMap") or []}
    built = ("IMPLEMENTED", "VERIFYING", "VERIFIED")
    out: list[Finding] = []
    for section in ("pages", "apis", "workflows", "components"):
        for art in _live(doc.get(section)):
            if art.get("status") in built and art.get("id") not in mapped:
                out.append(Finding(
                    "Blueprint↔Implementation", section=section, artifact_id=art.get("id"),
                    detail=f"status {art['status']} but no codeMap entry",
                ))
    return out



def check_navigation_page(doc: dict) -> list[Finding]:
    """Navigation must point at pages that exist, and pages should be reachable.

    Migrated from ``nav_route_reconcile_guard``, ``navigate_target_guard`` and
    ``table_row_nav_guard`` — the dead "View details" button class. Those passes
    repaired the href to a nearest-prefix guess or stamped
    ``data-nav-warn="broken"``; this reports it and leaves the target alone.
    """
    pages = _ids(doc.get("pages"))
    out: list[Finding] = []

    def walk(nodes: list[dict], trail: str = "") -> None:
        for node in nodes or []:
            label = node.get("label") or "?"
            target = node.get("page")
            if target and target not in pages:
                out.append(Finding(
                    "Navigation↔Page", section="navigation", artifact_id=target,
                    detail=f"nav entry {trail}{label!r} points at missing page {target}",
                ))
            walk(node.get("children") or [], f"{trail}{label}/")

    walk(doc.get("navigation", {}).get("tree") or [])

    # An unreachable page is not an error on its own — detail routes are reached
    # from their list — but a top-level pattern with no nav entry usually is.
    linked: set[str] = set()

    def collect(nodes: list[dict]) -> None:
        for n in nodes or []:
            if n.get("page"):
                linked.add(n["page"])
            collect(n.get("children") or [])

    collect(doc.get("navigation", {}).get("tree") or [])
    for page in _live(doc.get("pages")):
        if page.get("pattern") in ("entity_list", "dashboard") and page.get("id") not in linked:
            out.append(Finding(
                "Navigation↔Page", section="pages", artifact_id=page.get("id"),
                detail=f"{page.get('pattern')} page is not reachable from navigation",
            ))
    return out


def check_page_workflow(doc: dict) -> list[Finding]:
    """Every launcher needs a workflow, and every manual workflow needs a launcher.

    Migrated from ``submit_authority_guards``, ``orphan_wiring_pass``,
    ``action_contract_guard``, ``detail_action_guard`` and
    ``workflow_trigger_button_guard`` — five passes that between them wired
    orphan workflows to invented forms, backfilled button arguments and
    neutralised buttons pointing at event-only workflows.
    """
    workflows = _live(doc.get("workflows"))
    pages = _ids(doc.get("pages"))
    out: list[Finding] = []

    for wf in workflows:
        launched = [p for p in (wf.get("launchedFrom") or []) if p in pages]
        kind = (wf.get("trigger") or {}).get("kind")
        if kind == "manual" and not launched:
            out.append(Finding(
                "Page↔Workflow", section="workflows", artifact_id=wf.get("id"),
                detail="manual workflow has no page that launches it",
            ))

    launchable = {w.get("id") for w in workflows}
    for page in _live(doc.get("pages")):
        for action in page.get("actions") or []:
            if isinstance(action, str) and action.upper().startswith("FLOW-"):
                if action not in launchable:
                    out.append(Finding(
                        "Page↔Workflow", section="pages", artifact_id=page.get("id"),
                        detail=f"action targets missing workflow {action}",
                    ))
    return out



#: Aggregations producing a magnitude rather than a ratio. Mirrors
#: MAGNITUDE_AGGREGATIONS in packages/schema/src/blueprint/blueprint.ts.
MAGNITUDE_AGGREGATIONS = ("count", "sum", "min", "max")


def check_widget_datasource(doc: dict) -> list[Finding]:
    """A widget may not display a number its own data cannot produce.

    Migrated from ``kpi_format_honesty``, ``widget_data_contract`` and
    ``binding_smoke``. The schema already makes a source-less widget and a
    grouping-less series unrepresentable; what is left is the cross-artifact
    part — does the entity exist, do the named columns exist on it, and is the
    display unit honest about the aggregation behind it.

    The honesty rule is a type statement, not a heuristic: count / sum / min /
    max produce a magnitude, and a magnitude rendered as a percent is a
    fabricated number. That was the tile reporting 1,000% utilisation.
    """
    entities = {e.get("id"): e for e in _entities(doc)}
    pages = _ids(doc.get("pages"))
    out: list[Finding] = []

    for w in _live(doc.get("widgets")):
        wid = w.get("id")
        src = w.get("dataSource") or {}
        entity_id = src.get("entity")

        if w.get("page") and w["page"] not in pages:
            out.append(Finding(
                "Widget↔DataSource", section="widgets", artifact_id=wid,
                detail=f"sits on missing page {w['page']}",
            ))

        entity = entities.get(entity_id)
        if entity is None:
            out.append(Finding(
                "Widget↔DataSource", section="widgets", artifact_id=wid,
                detail=f"bound to unknown entity {entity_id}",
            ))
            continue

        columns = {f.get("name") for f in entity.get("fields") or []}
        for key in ("field", "groupBy", "sort"):
            col = src.get(key)
            if col and columns and col not in columns:
                out.append(Finding(
                    "Widget↔DataSource", section="widgets", artifact_id=wid,
                    detail=f"{key} {col!r} is not a column on {entity.get('name')}",
                ))
        for col in src.get("fields") or []:
            if columns and col not in columns:
                out.append(Finding(
                    "Widget↔DataSource", section="widgets", artifact_id=wid,
                    detail=f"displays {col!r}, not a column on {entity.get('name')}",
                ))

        agg = src.get("aggregation")
        if w.get("unit") == "percent" and agg in MAGNITUDE_AGGREGATIONS:
            out.append(Finding(
                "Widget↔DataSource", section="widgets", artifact_id=wid,
                detail=(f"unit 'percent' over a {agg!r} — a magnitude shown as a "
                        "ratio is a fabricated number"),
            ))
        if agg and agg != "count" and not src.get("field"):
            out.append(Finding(
                "Widget↔DataSource", section="widgets", artifact_id=wid,
                detail=f"{agg!r} needs a field to aggregate over",
            ))
    return out


def check_page_precondition(doc: dict) -> list[Finding]:
    """§75 — a page that declares a precondition nothing can satisfy.

    `requires` exists so an approval screen can say it needs a submitted
    record rather than leave every reviewer looking at a correct rendering of
    nothing. Said, it has to be true: a state the entity does not declare can
    never be reached, and a `producedBy` naming a workflow that does not exist
    is a promise the application cannot keep.

    Checked here rather than in the preview sweep because it is a fact about
    the document. A sweep would notice it as "no record in that state", which
    is the same complaint whether the state is unreachable or merely
    unseeded — and those want different fixes from different people.
    """
    from services.blueprint.page_planner import enum_values

    out: list[Finding] = []
    entities = {e.get("id"): e for e in _live(_entities(doc))}
    flows = _ids(_live(doc.get("workflows")))

    for page in _live(doc.get("pages")):
        needs = page.get("requires")
        if not isinstance(needs, dict):
            continue
        page_id = page.get("id")
        entity_id = needs.get("entity")
        state = str(needs.get("state") or "")

        entity = entities.get(entity_id)
        if entity is None:
            out.append(Finding(
                "Page↔Precondition", section="pages", artifact_id=page_id,
                detail=f"requires a record of {entity_id}, which is not an "
                       "entity this application has",
            ))
            continue

        declared = {v for f in (entity.get("fields") or [])
                    if isinstance(f, dict) for v in enum_values(f)}
        if declared and state not in declared:
            out.append(Finding(
                "Page↔Precondition", section="pages", artifact_id=page_id,
                detail=f"requires {entity.get('name') or entity_id} in state "
                       f"{state!r}, which is not one of its declared values "
                       f"({', '.join(sorted(declared))})",
            ))
        elif not declared:
            out.append(Finding(
                "Page↔Precondition", section="pages", artifact_id=page_id,
                detail=f"requires {entity.get('name') or entity_id} in state "
                       f"{state!r}, but that entity declares no states at all "
                       "— no field of it carries enumValues",
            ))

        produced_by = needs.get("producedBy")
        if produced_by and produced_by not in flows:
            out.append(Finding(
                "Page↔Precondition", section="pages", artifact_id=page_id,
                detail=f"names {produced_by} as what produces that state, and "
                       "no such workflow exists",
            ))

    return out


CHECKS: dict[str, Callable[[dict], list[Finding]]] = {
    "Page↔API": check_page_api,
    "API↔Database": check_api_database,
    "Page↔Permission": check_page_permission,
    "API↔Permission": check_api_permission,
    "Workflow↔BusinessRule": check_workflow_rule,
    "Workflow↔API": check_workflow_api,
    "Page↔Function": check_page_function,
    "Design↔DesignSystem": check_design_system,
    "Requirement↔Code": check_requirement_code,
    "Requirement↔Test": check_requirement_test,
    "Blueprint↔Implementation": check_blueprint_implementation,
    "Navigation↔Page": check_navigation_page,
    "Page↔Precondition": check_page_precondition,
    "Page↔Workflow": check_page_workflow,
    "Page↔Layout": check_page_layout,
    "Widget↔DataSource": check_widget_datasource,
}


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def verify(doc: dict, *, edges: tuple[str, ...] = EDGES) -> VerificationReport:
    """Run the matrix. Pure — reads the Blueprint, changes nothing."""
    findings: list[Finding] = []
    for edge in edges:
        findings.extend(CHECKS[edge](doc))
    return VerificationReport(findings=findings, checked_edges=edges)


def apply_findings(svc: BlueprintService, report: VerificationReport) -> list[str]:
    """§76 — flag every implicated artifact ``OUT_OF_SYNC``. Repairs nothing.

    The verification agent's §30 capability is exactly this: it writes no
    section but may set status. Anything more would be an agent fixing another
    agent's domain, which is the boundary violation this architecture exists to
    prevent.
    """
    cap = capability_for("verification")
    assert cap.may_set_status and not cap.writes, (
        "the verification agent must be able to flag and nothing else"
    )

    marked: list[str] = []
    grouped: dict[str, list[Finding]] = {}
    for f in report.findings:
        if f.artifact_id:
            grouped.setdefault(f.artifact_id, []).append(f)

    for artifact_id, items in grouped.items():
        try:
            svc.mark_out_of_sync(
                artifact_id,
                "; ".join(f"{i.edge}: {i.detail}" for i in items),
            )
            marked.append(artifact_id)
        except KeyError:
            # The finding named an artifact that is not in the Blueprint. That
            # is itself a defect, but not one to fix by inventing the artifact.
            continue
    if marked:
        svc.save()
    return marked


def requirement_verdict(doc: dict, requirement_id: str) -> dict[str, Any]:
    """§74 — the per-requirement rollup, in the PRD's own shape.

    Returns each facet's state and an overall PASSED/FAILED, so Smith can
    answer "has this requirement been implemented?" with evidence rather than
    an opinion.
    """
    facets = {
        "Requirement↔Code": check_requirement_code,
        "Requirement↔Test": check_requirement_test,
    }
    detail: dict[str, Any] = {}
    failed = False
    for name, fn in facets.items():
        hits = [f for f in fn(doc) if f.artifact_id == requirement_id]
        detail[name] = {"ok": not hits, "notes": [h.detail for h in hits]}
        failed = failed or bool(hits)
    return {
        "requirement": requirement_id,
        "result": "FAILED" if failed else "PASSED",
        "facets": detail,
    }
