"""The structured hand-off between discovery and the planner.

Discovery is a conversation; the planner needs structure. This module
defines the contract that sits between them:

    StructuredBrief = {
        overview:        str,
        domain:          str,
        actors:          list[Actor],
        user_journeys:   list[Journey],
        domain_terms:    list[str],
        open_questions:  list[str],
    }

The transformer (services.discovery_transformer) produces one of these
from a discovery session; the planner router (routers.generate) renders
it into the LLM prompt as AUTHORITATIVE INPUTS; the plan validator
(_rule_authoritative_inputs_honored) walks the produced plan and checks
every commitment was kept.

Design notes
------------
* We use plain dataclasses, not pydantic. The brief is small, hand-authored
  at boundaries, and lives long enough that a lightweight shape survives
  refactors better than a fully-typed model. ``StructuredBrief.parse()``
  is the only entry point that touches JSON, and it does explicit
  key-by-key normalization so we control the error messages.

* Actor shape reuses Slice B verbatim (name / role / onboarding /
  responsibilities). Onboarding sources are the same three tokens the
  planner validator already knows about — see
  ``services.plan_validator._VALID_ONBOARDING_SOURCES``.

* Every field is optional-safe: missing lists become ``[]``, missing
  strings become ``""``. That keeps parse failures narrow — only truly
  malformed input (non-dict payload, non-list actors) raises.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


VALID_ONBOARDING_SOURCES = {"self_signup", "invited_by", "platform_org"}


class BriefParseError(ValueError):
    """Raised when the JSON payload isn't a well-formed structured brief."""


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class ActorOnboarding:
    source: str = ""
    invited_by: str | None = None
    gate: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"source": self.source}
        if self.invited_by is not None:
            out["invited_by"] = self.invited_by
        if self.gate is not None:
            out["gate"] = self.gate
        return out


@dataclass
class Actor:
    name: str = ""
    role: str = ""
    onboarding: ActorOnboarding = field(default_factory=ActorOnboarding)
    responsibilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name":             self.name,
            "role":             self.role,
            "onboarding":       self.onboarding.to_dict(),
            "responsibilities": list(self.responsibilities),
        }


@dataclass
class JourneyStep:
    """One step of a user journey.

    Each step must name enough for the plan validator to check the plan
    honored it: an ``actor`` (who does it), an ``action`` (verb+noun),
    a ``page`` (the exact route the user is on), an optional
    ``workflow`` (fired by the action), and an ``outcome`` (what
    changes). The outcome is prose; every other field is verbatim
    identifier."""
    actor:    str = ""
    action:   str = ""
    page:     str = ""
    workflow: str | None = None
    outcome:  str = ""

    def to_dict(self) -> dict:
        out: dict = {
            "actor":   self.actor,
            "action":  self.action,
            "page":    self.page,
            "outcome": self.outcome,
        }
        if self.workflow:
            out["workflow"] = self.workflow
        return out


@dataclass
class JourneyVariation:
    """A branch off the happy path. ``at_step`` is 1-indexed to match how
    users describe them ("at step 2 if there's no fit …")."""
    at_step:   int = 0
    condition: str = ""
    outcome:   str = ""

    def to_dict(self) -> dict:
        return {
            "at_step":   self.at_step,
            "condition": self.condition,
            "outcome":   self.outcome,
        }


@dataclass
class Journey:
    name:          str = ""
    primary_actor: str = ""
    trigger:       str = ""
    steps:         list[JourneyStep] = field(default_factory=list)
    variations:    list[JourneyVariation] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict = {
            "name":          self.name,
            "primary_actor": self.primary_actor,
            "trigger":       self.trigger,
            "steps":         [s.to_dict() for s in self.steps],
        }
        if self.variations:
            out["variations"] = [v.to_dict() for v in self.variations]
        return out


@dataclass
class StructuredBrief:
    overview:       str = ""
    domain:         str = ""
    actors:         list[Actor] = field(default_factory=list)
    user_journeys:  list[Journey] = field(default_factory=list)
    domain_terms:   list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overview":       self.overview,
            "domain":         self.domain,
            "actors":         [a.to_dict() for a in self.actors],
            "user_journeys":  [j.to_dict() for j in self.user_journeys],
            "domain_terms":   list(self.domain_terms),
            "open_questions": list(self.open_questions),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def is_empty(self) -> bool:
        """A brief with no actors AND no journeys is empty — the planner
        should ignore it and fall back to auto-derivation. Used by the
        planner router to decide whether to render an AUTHORITATIVE
        INPUTS block at all."""
        return not self.actors and not self.user_journeys

    # ------------------------------------------------------------------ #
    # Parsers — the only place JSON meets our shape
    # ------------------------------------------------------------------ #

    @classmethod
    def parse(cls, payload: Any) -> "StructuredBrief":
        """Parse a dict or JSON string into a StructuredBrief.

        Raises ``BriefParseError`` for truly malformed input (non-dict
        payload, non-list actors/journeys). Missing keys default to
        their zero value — a discovery that produced only actors and no
        journeys still parses fine, and the planner falls back to
        auto-deriving journeys."""
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise BriefParseError(f"payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise BriefParseError(
                f"payload must be a JSON object, got {type(payload).__name__}"
            )

        actors = _parse_actors(payload.get("actors"))
        journeys = _parse_journeys(payload.get("user_journeys"))

        return cls(
            overview=       _str(payload.get("overview")),
            domain=         _str(payload.get("domain")),
            actors=         actors,
            user_journeys=  journeys,
            domain_terms=   _string_list(payload.get("domain_terms")),
            open_questions= _string_list(payload.get("open_questions")),
        )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _parse_actors(raw: Any) -> list[Actor]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BriefParseError(
            f"`actors` must be a list, got {type(raw).__name__}"
        )
    out: list[Actor] = []
    for i, a in enumerate(raw):
        if not isinstance(a, dict):
            raise BriefParseError(
                f"`actors[{i}]` must be an object, got {type(a).__name__}"
            )
        ob_raw = a.get("onboarding") or {}
        if not isinstance(ob_raw, dict):
            raise BriefParseError(
                f"`actors[{i}].onboarding` must be an object"
            )
        out.append(Actor(
            name= _str(a.get("name")),
            role= _str(a.get("role")),
            onboarding= ActorOnboarding(
                source=     _str(ob_raw.get("source")),
                invited_by= _opt_str(ob_raw.get("invited_by")),
                gate=       _opt_str(ob_raw.get("gate")),
            ),
            responsibilities= _string_list(a.get("responsibilities")),
        ))
    return out


def _parse_journeys(raw: Any) -> list[Journey]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BriefParseError(
            f"`user_journeys` must be a list, got {type(raw).__name__}"
        )
    out: list[Journey] = []
    for i, j in enumerate(raw):
        if not isinstance(j, dict):
            raise BriefParseError(
                f"`user_journeys[{i}]` must be an object, got {type(j).__name__}"
            )
        out.append(Journey(
            name=          _str(j.get("name")),
            primary_actor= _str(j.get("primary_actor")),
            trigger=       _str(j.get("trigger")),
            steps=         _parse_steps(j.get("steps"), path=f"user_journeys[{i}].steps"),
            variations=    _parse_variations(j.get("variations"), path=f"user_journeys[{i}].variations"),
        ))
    return out


def _parse_steps(raw: Any, *, path: str) -> list[JourneyStep]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BriefParseError(f"`{path}` must be a list")
    out: list[JourneyStep] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise BriefParseError(f"`{path}[{i}]` must be an object")
        wf = s.get("workflow")
        out.append(JourneyStep(
            actor=    _str(s.get("actor")),
            action=   _str(s.get("action")),
            page=     _str(s.get("page")),
            workflow= _opt_str(wf) if wf is not None else None,
            outcome=  _str(s.get("outcome")),
        ))
    return out


def _parse_variations(raw: Any, *, path: str) -> list[JourneyVariation]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BriefParseError(f"`{path}` must be a list")
    out: list[JourneyVariation] = []
    for i, v in enumerate(raw):
        if not isinstance(v, dict):
            raise BriefParseError(f"`{path}[{i}]` must be an object")
        at_step = v.get("at_step")
        try:
            at_step_int = int(at_step) if at_step is not None else 0
        except (TypeError, ValueError):
            at_step_int = 0
        out.append(JourneyVariation(
            at_step=   at_step_int,
            condition= _str(v.get("condition")),
            outcome=   _str(v.get("outcome")),
        ))
    return out


def _str(v: Any) -> str:
    """Coerce a value to a string, stripping whitespace. None/empty →
    empty string. Numbers are stringified so the transformer can emit
    step numbers as ints without breaking parse."""
    if v is None:
        return ""
    return str(v).strip()


def _opt_str(v: Any) -> str | None:
    s = _str(v)
    return s if s else None


def _string_list(v: Any) -> list[str]:
    """Coerce to a list of non-empty stripped strings. Non-list input
    (or missing) returns an empty list — this is a soft field, not a
    contract."""
    if not isinstance(v, list):
        return []
    return [_str(x) for x in v if _str(x)]
