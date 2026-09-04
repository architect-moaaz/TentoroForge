"""§24 — the Application Definition, and what it is honest about.

§107 puts this at step 6: after Smith analyses the input and asks its
clarification questions, and before the user accepts. It is the artifact the
§95 Gate 1 question is asked *about* — "is this what you want to build?" —
which means its job is to be checkable by someone who has not read a Blueprint.

Derived, not authored
---------------------
§24 lists seventeen things a definition shall include, and sixteen of them are
already in the Blueprint: roles, capabilities, modules, pages, workflows,
business rules, entities, integrations, security. Asking a model to "generate
the Application Definition" would have it restate the document from a summary
of the document, and every restatement is a chance to drop a module or invent
a role that nobody can then find. So the enumeration is counted (§116).

The seventeenth is prose — a paragraph a person can read. That is not here
either: :func:`services.smith.smith.domain_summary` already derives one, and a
second summariser in this module would be a second answer to the same question.
Nothing in here calls a model, which is what makes a definition renderable at
any moment, including while a run is failing.

What it says about what is missing
----------------------------------
A definition that lists nine modules and stays quiet about having no security
model reads as complete. §15 scores completeness per dimension and §102 wants
absence distinguished from failure, so :attr:`ApplicationDefinition.thin` names
the dimensions the document cannot yet stand behind, and :attr:`open_questions`
carries what Smith would still ask. The user approves the whole picture,
including its holes, or they are not approving anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from services.blueprint.approval import product_digest
from services.blueprint.completeness import score as completeness_score
from services.smith import clarification

#: Dimensions below this are named as thin. §17's clarification threshold —
#: the point the PRD says behaviour must not be implemented without asking.
THIN_BELOW = 0.40


@dataclass(frozen=True)
class Named:
    """One listed thing, with the id that makes it findable (§12)."""

    id: str
    name: str
    detail: str = ""


@dataclass
class ApplicationDefinition:
    """§24's seventeen items, counted from the Blueprint."""

    name: str = ""
    description: str = ""
    domain: str = ""
    objectives: list[str] = field(default_factory=list)
    users: list[Named] = field(default_factory=list)          # personas
    roles: list[Named] = field(default_factory=list)
    permissions: list[Named] = field(default_factory=list)
    capabilities: list[Named] = field(default_factory=list)
    modules: list[Named] = field(default_factory=list)
    pages: list[Named] = field(default_factory=list)
    workflows: list[Named] = field(default_factory=list)
    business_rules: list[Named] = field(default_factory=list)
    entities: list[Named] = field(default_factory=list)
    integrations: list[Named] = field(default_factory=list)
    reports: list[Named] = field(default_factory=list)         # §24 "reports"
    security: dict[str, Any] = field(default_factory=dict)
    design_direction: dict[str, Any] = field(default_factory=dict)

    #: Where the understanding came from — §14's evidence, rolled up. A
    #: definition built mostly from Smith's own inference is a different thing
    #: to approve than one built from a document the user wrote.
    evidence: dict[str, int] = field(default_factory=dict)
    #: §15 dimensions the document cannot stand behind yet.
    thin: list[str] = field(default_factory=list)
    #: §76 — fingerprint of the document this was derived from. See
    #: :func:`services.blueprint.approval.product_digest`.
    digest: str = ""
    #: §16 — the subjects Smith would still ask about, and why they were
    #: selected. Deliberately not the *phrased* questions: wording them is a
    #: model call (``turn.phrase``), and a definition that could not be
    #: rendered without one would make the gate depend on a summariser.
    open_questions: list[str] = field(default_factory=list)
    version: int = 1

    def counts(self) -> dict[str, int]:
        return {
            "objectives": len(self.objectives),
            "users": len(self.users),
            "roles": len(self.roles),
            "permissions": len(self.permissions),
            "capabilities": len(self.capabilities),
            "modules": len(self.modules),
            "pages": len(self.pages),
            "workflows": len(self.workflows),
            "businessRules": len(self.business_rules),
            "entities": len(self.entities),
            "integrations": len(self.integrations),
            "reports": len(self.reports),
        }


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict)
            and i.get("status") != "DEPRECATED"]


def _named(items: Any, detail_key: str = "description") -> list[Named]:
    return [
        Named(
            id=str(i.get("id") or ""),
            name=str(i.get("name") or i.get("decision") or i.get("route") or ""),
            detail=str(i.get(detail_key) or ""),
        )
        for i in _live(items)
    ]


def _evidence_rollup(doc: dict) -> dict[str, int]:
    """How the requirements are grounded, by §14 evidence type."""
    counts: dict[str, int] = {}
    unevidenced = 0
    for req in _live(doc.get("requirements")):
        entries = req.get("evidence") or []
        if not entries:
            unevidenced += 1
            continue
        for entry in entries:
            kind = str(entry.get("type") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
    if unevidenced:
        counts["none"] = unevidenced
    return dict(sorted(counts.items()))


def derive(doc: dict, *, conversation: Any = None) -> ApplicationDefinition:
    """§24, counted from the Blueprint. Pure: reads, writes nothing."""
    application = doc.get("application") or {}
    product = doc.get("product") or {}
    data = doc.get("data") or {}
    design = doc.get("designSystem") or {}

    scores = completeness_score(doc)
    questions = clarification.select(doc, conversation=conversation, limit=5)

    return ApplicationDefinition(
        name=str(application.get("name") or ""),
        description=str(application.get("description")
                        or product.get("description") or ""),
        domain=str(application.get("domain") or ""),
        objectives=[str(o) for o in (product.get("objectives") or [])],
        users=[
            Named(id="", name=str(p.get("name") or ""),
                  detail=str(p.get("description") or ""))
            for p in (product.get("personas") or []) if isinstance(p, dict)
        ],
        roles=_named(doc.get("roles")),
        permissions=_named(doc.get("permissions")),
        capabilities=_named(product.get("capabilities")),
        modules=_named(doc.get("modules")),
        pages=_named(doc.get("pages"), detail_key="purpose"),
        workflows=_named(doc.get("workflows")),
        business_rules=_named(doc.get("businessRules")),
        entities=_named(data.get("entities")),
        integrations=_named(doc.get("integrations")),
        reports=_named(doc.get("widgets")),
        security={
            k: v for k, v in (doc.get("security") or {}).items() if v
        },
        design_direction={
            "visualPersonality": design.get("visualPersonality") or "",
            "navigationApproach": design.get("navigationApproach") or "",
            "informationDensity": design.get("informationDensity") or "",
            "derivedFromFigma": bool(design.get("derivedFromFigma")),
            "sources": [
                s.get("id") for s in (doc.get("designSources") or []) if s.get("id")
            ],
        },
        evidence=_evidence_rollup(doc),
        thin=[d for d, v in sorted(scores.items(), key=lambda kv: kv[1])
              if v < THIN_BELOW],
        open_questions=[
            f"{q.label} ({q.section}) — {q.why}" for q in questions
        ],
        digest=product_digest(doc),
        version=int(doc.get("version") or 1),
    )


# ---------------------------------------------------------------------------
# Identity of what was shown (§25, §76)
# ---------------------------------------------------------------------------

def digest(definition: ApplicationDefinition) -> str:
    """The fingerprint of the document this definition was derived from.

    Computed by :func:`services.blueprint.approval.product_digest` and carried
    on the definition, rather than recomputed from the definition object. One
    definition of it, in the layer that owns the sections it hashes — the
    orchestrator has to check the same fingerprint before it builds, and it
    cannot import Smith.
    """
    return definition.digest


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _section(title: str, items: Sequence[Named], limit: int = 12) -> list[str]:
    if not items:
        return []
    lines = [f"{title} ({len(items)})"]
    for item in items[:limit]:
        detail = f" — {item.detail}" if item.detail else ""
        lines.append(f"  {item.name}{detail}"[:110])
    if len(items) > limit:
        lines.append(f"  … and {len(items) - limit} more")
    return lines + [""]


def render(definition: ApplicationDefinition) -> str:
    """§24 as something a person can check. Reads top-down, widest first."""
    out: list[str] = [definition.name or "(unnamed application)"]
    if definition.domain:
        out.append(f"{definition.domain} · version {definition.version}")
    out.append("")
    if definition.description:
        out += [definition.description, ""]
    if definition.objectives:
        out.append("Objectives")
        out += [f"  - {o}" for o in definition.objectives]
        out.append("")

    for title, items in (
        ("Users", definition.users),
        ("Roles", definition.roles),
        ("Capabilities", definition.capabilities),
        ("Modules", definition.modules),
        ("Pages", definition.pages),
        ("Workflows", definition.workflows),
        ("Business rules", definition.business_rules),
        ("Data", definition.entities),
        ("Integrations", definition.integrations),
        ("Reports", definition.reports),
    ):
        out += _section(title, items)

    if definition.security:
        out.append("Security")
        out += [f"  {k}: {v}" for k, v in definition.security.items()]
        out.append("")

    design = definition.design_direction
    if any(design.get(k) for k in ("visualPersonality", "navigationApproach")):
        out.append("Design direction")
        for key in ("visualPersonality", "navigationApproach", "informationDensity"):
            if design.get(key):
                out.append(f"  {key}: {design[key]}")
        if design.get("derivedFromFigma"):
            sources = ", ".join(design.get("sources") or []) or "a connected file"
            out.append(f"  extracted from Figma ({sources})")
        out.append("")

    if definition.evidence:
        out.append("Grounded in")
        out += [f"  {k}: {v}" for k, v in definition.evidence.items()]
        out.append("")

    # Last, and never omitted when present. A definition that lists nine
    # modules and stays quiet about having no security model reads complete.
    if definition.thin:
        out.append("Not yet established")
        out += [f"  - {d}" for d in definition.thin]
        out.append("")
    if definition.open_questions:
        out.append("Smith would still ask")
        out += [f"  {i}. {q}" for i, q in enumerate(definition.open_questions, 1)]
        out.append("")

    return "\n".join(out).rstrip() + "\n"
