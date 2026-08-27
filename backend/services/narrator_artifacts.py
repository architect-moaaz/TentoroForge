"""Narrator-mode artifact contracts.

Spec: §10.4 of the Smith-as-architect design.

Internal agents (discovery, planner, generator) produce STRUCTURED
JSON. Smith reads the artifact and speaks in his own voice. This
module defines the target shape as dataclasses so agent adapters
have a normalization target and Smith has a stable payload to
summarize from.

Every artifact type exposes:
  * ``from_dict(payload)`` — validates + constructs; raises
    ``NarratorArtifactError`` on structural violations.
  * ``narrator_summary()`` — a deterministic string suitable for
    Smith to relay to the user. Deterministic because the tone is
    architect-owned (this module speaks in Smith's voice); the
    agent's job is data, Smith's job is narration.

Full agent prompt rewrites — teaching discovery/planner/generator
to *only* produce these shapes — land in later slices. This slice
puts the target in place so those prompt rewrites have somewhere
to normalize to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class NarratorArtifactError(ValueError):
    """Raised when a payload can't be normalized into an artifact."""


# --------------------------------------------------------------------------- #
# Common sub-shapes
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ProposedEntity:
    name: str
    why: str = ""


@dataclass(frozen=True)
class ProposedWorkflow:
    name: str
    purpose: str = ""
    trigger: str = ""
    why: str = ""


@dataclass(frozen=True)
class ProposedPage:
    route: str
    schema_path: str
    role: str = ""


@dataclass(frozen=True)
class ProposedEntitySpec:
    name: str
    table: str
    purpose: str
    key_fields: list[str]
    why_shaped_this_way: str


# --------------------------------------------------------------------------- #
# DiscoveryArtifact — output of the discovery agent
# --------------------------------------------------------------------------- #

@dataclass
class DiscoveryArtifact:
    """What discovery returns for Smith to summarize.

    Corresponds to the domain block Smith later writes into the
    Blueprint plus the framing details he uses to introduce the
    plan to the user."""

    domain_name: str
    actors: list[str]
    verbs: list[str]
    distinctive_shape: str = ""
    proposed_entities: list[ProposedEntity] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence: float = 0.7

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiscoveryArtifact":
        if not isinstance(payload, dict):
            raise NarratorArtifactError("discovery payload must be an object")

        name = str(payload.get("domain_name") or "").strip()
        if not name:
            raise NarratorArtifactError("discovery.domain_name is required")

        entities: list[ProposedEntity] = []
        for e in (payload.get("proposed_entities") or []):
            if not isinstance(e, dict):
                continue
            n = str(e.get("name") or "").strip()
            if not n:
                continue
            entities.append(ProposedEntity(name=n, why=str(e.get("why") or "")))

        try:
            conf = float(payload.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7

        return cls(
            domain_name=name,
            actors=[str(a) for a in (payload.get("actors") or []) if a],
            verbs=[str(v) for v in (payload.get("verbs") or []) if v],
            distinctive_shape=str(payload.get("distinctive_shape") or ""),
            proposed_entities=entities,
            open_questions=[str(q) for q in (payload.get("open_questions") or []) if q],
            confidence=max(0.0, min(1.0, conf)),
        )

    def narrator_summary(self) -> str:
        """Architect-voice summary. Deterministic + short."""
        parts = [
            f"Here's what I heard: **{self.domain_name}**.",
        ]
        if self.actors:
            parts.append(
                "The people involved are "
                + ", ".join(self.actors[:-1] + [f"and {self.actors[-1]}"])
                if len(self.actors) > 1
                else f"The primary actor is {self.actors[0]}."
            )
        if self.verbs:
            parts.append(
                "The core moves are " + ", ".join(self.verbs) + "."
            )
        if self.distinctive_shape:
            parts.append(f"I'm going to shape it as a {self.distinctive_shape}.")
        if self.proposed_entities:
            names = ", ".join(e.name for e in self.proposed_entities)
            parts.append(f"Proposed entities: {names}.")
        if self.open_questions:
            parts.append("Before I plan — " + " ".join(self.open_questions))
        return " ".join(parts)


# --------------------------------------------------------------------------- #
# PlannerArtifact — output of the planner agent
# --------------------------------------------------------------------------- #

@dataclass
class PlannerArtifact:
    entities: list[ProposedEntitySpec] = field(default_factory=list)
    workflows: list[ProposedWorkflow] = field(default_factory=list)
    pages: list[ProposedPage] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannerArtifact":
        if not isinstance(payload, dict):
            raise NarratorArtifactError("planner payload must be an object")

        entities: list[ProposedEntitySpec] = []
        for e in (payload.get("entities") or []):
            if not isinstance(e, dict):
                continue
            entities.append(ProposedEntitySpec(
                name=str(e.get("name") or ""),
                table=str(e.get("table") or ""),
                purpose=str(e.get("purpose") or ""),
                key_fields=[str(f) for f in (e.get("key_fields") or [])],
                why_shaped_this_way=str(e.get("why_shaped_this_way") or ""),
            ))

        workflows: list[ProposedWorkflow] = []
        for w in (payload.get("workflows") or []):
            if not isinstance(w, dict):
                continue
            workflows.append(ProposedWorkflow(
                name=str(w.get("name") or ""),
                purpose=str(w.get("purpose") or ""),
                trigger=str(w.get("trigger") or ""),
                why=str(w.get("why") or ""),
            ))

        pages: list[ProposedPage] = []
        for p in (payload.get("pages") or []):
            if not isinstance(p, dict):
                continue
            pages.append(ProposedPage(
                route=str(p.get("route") or ""),
                schema_path=str(p.get("schema_path") or ""),
                role=str(p.get("role") or ""),
            ))

        if not entities and not pages:
            raise NarratorArtifactError(
                "planner artifact needs at least one entity or page"
            )

        return cls(entities=entities, workflows=workflows, pages=pages)

    def narrator_summary(self) -> str:
        parts = ["Plan drafted:"]
        parts.append(_pluralize(len(self.entities), "entity", "entities"))
        parts.append(_pluralize(len(self.workflows), "workflow", "workflows"))
        parts.append(_pluralize(len(self.pages), "page", "pages"))
        return "Plan drafted: " + ", ".join(parts[1:]) + "."


# --------------------------------------------------------------------------- #
# GeneratorArtifact — output of the generator pipeline
# --------------------------------------------------------------------------- #

_GENERATOR_FILE_PREVIEW = 5


@dataclass
class GeneratorArtifact:
    generated_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GeneratorArtifact":
        if not isinstance(payload, dict):
            raise NarratorArtifactError("generator payload must be an object")
        return cls(
            generated_files=[str(f) for f in (payload.get("generated_files") or [])],
            warnings=[str(w) for w in (payload.get("warnings") or [])],
            notes=[str(n) for n in (payload.get("notes") or [])],
        )

    def narrator_summary(self) -> str:
        n = len(self.generated_files)
        head = f"Generated the app: {n} file(s) written."
        if n == 0:
            return head
        preview = ", ".join(f"`{p}`" for p in self.generated_files[:_GENERATOR_FILE_PREVIEW])
        more = "" if n <= _GENERATOR_FILE_PREVIEW else f", plus {n - _GENERATOR_FILE_PREVIEW} more"
        parts = [head, f"Includes: {preview}{more}."]
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s) surfaced during build.")
        return " ".join(parts)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _pluralize(n: int, single: str, plural: str) -> str:
    if n == 0:
        return f"no {plural}"
    if n == 1:
        return f"1 {single}"
    return f"{n} {plural}"
