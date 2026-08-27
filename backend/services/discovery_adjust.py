"""Deterministic dossier-mutation operations for Discovery's Adjust flow.

Mirrors :mod:`services.plan_adjust` for the *discovery* stage. When the
user chats with Smith on the DiscoveryCard, the LLM only PICKS which
of these ops to call — it never authors JSON directly. Every op is
pure, idempotent, and refuses invalid input with
:class:`DossierAdjustError`.

The dossier is the domain-discovery blob produced by
:func:`agents.domain_agent.run_domain_discovery`. Shape (mirrors what
DiscoveryCard renders):

    {
        "domain":            str,
        "domainAliases":     [str],
        "description":       str,
        "confidence":        float,
        "complianceNotes":   [str],   # from COMPLIANCE_OPTIONS
        "designPatterns":    [{name, description, evidence?: [str]}],
        "entitySuggestions": [{name, likelyFields?: [str]}],
        "commonPitfalls":    [str],
        "uncertainAreas":    [str],
        "visualLanguage":    {
            "paletteCharacter":   str,
            "typographyTone":     str,
            "densityPreference":  str,
        },
    }

Downstream:
  * :func:`compute_diff` — structured added/removed lists for the UI
  * :func:`validate_dossier_shape` — sanity-check compliance regimes
    stay inside the whitelist

No LLM in this module. The intent parser lives in
``discovery_adjust_intent.py``.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Optional


class DossierAdjustError(ValueError):
    """Raised when a mutation op can't apply — missing target, invalid
    arg, name collision, etc."""


# --------------------------------------------------------------------------- #
# Whitelists mirroring the frontend                                            #
# --------------------------------------------------------------------------- #

# Kept aligned with DiscoveryCard.tsx `COMPLIANCE_OPTIONS`. If we add
# a regime here, the frontend still has to render it — the round-trip
# should not accept a value the UI can't paint.
_COMPLIANCE_REGIMES = {
    "none", "hipaa", "pci", "gdpr", "sox", "fda", "ferpa", "ada-wcag",
}


# Loose display-name pattern for suggestions / patterns. Discovery-side
# names are much freer than plan-side (which uses PascalCase entities) —
# patterns like "Kanban board" or "Split-pane detail" are legitimate.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-/]*$")


def _norm_name(value: str, *, kind: str = "name") -> str:
    if not isinstance(value, str):
        raise DossierAdjustError(
            f"{kind} must be a string, got {type(value).__name__}"
        )
    v = value.strip()
    if not v or not _NAME_RE.match(v):
        raise DossierAdjustError(
            f"{kind} must start with a letter and contain "
            f"letters/digits/spaces/dashes, got {value!r}"
        )
    return v


def _norm_text(value: str, *, kind: str = "text") -> str:
    if not isinstance(value, str):
        raise DossierAdjustError(
            f"{kind} must be a string, got {type(value).__name__}"
        )
    return value.strip()


# --------------------------------------------------------------------------- #
# Scalar / text ops                                                            #
# --------------------------------------------------------------------------- #

def set_domain(dossier: dict, *, text: str) -> dict:
    """Replace the domain label ('Hospitality', 'Recruitment', …)."""
    v = _norm_text(text, kind="domain")
    if not v:
        raise DossierAdjustError("domain cannot be empty")
    new = copy.deepcopy(dossier)
    new["domain"] = v
    return new


def set_description(dossier: dict, *, text: str) -> dict:
    """Replace the free-form description. Empty string clears it."""
    new = copy.deepcopy(dossier)
    new["description"] = _norm_text(text, kind="description")
    return new


# --------------------------------------------------------------------------- #
# Compliance ops                                                               #
# --------------------------------------------------------------------------- #

def _norm_regime(value: str) -> str:
    if not isinstance(value, str):
        raise DossierAdjustError(
            f"compliance regime must be a string, got {type(value).__name__}"
        )
    v = value.strip().lower()
    if v not in _COMPLIANCE_REGIMES:
        raise DossierAdjustError(
            f"compliance regime must be one of "
            f"{sorted(_COMPLIANCE_REGIMES)}, got {value!r}"
        )
    return v


def add_compliance(dossier: dict, *, regime: str) -> dict:
    """Append a compliance regime. Idempotent — duplicates dropped."""
    r = _norm_regime(regime)
    new = copy.deepcopy(dossier)
    existing = list(new.get("complianceNotes") or [])
    if r not in existing:
        existing.append(r)
    new["complianceNotes"] = existing
    return new


def remove_compliance(dossier: dict, *, regime: str) -> dict:
    """Drop a compliance regime. Idempotent."""
    r = _norm_regime(regime)
    new = copy.deepcopy(dossier)
    existing = list(new.get("complianceNotes") or [])
    new["complianceNotes"] = [x for x in existing if x != r]
    return new


# --------------------------------------------------------------------------- #
# Entity-suggestion ops                                                        #
# --------------------------------------------------------------------------- #

def add_entity_suggestion(
    dossier: dict,
    *,
    name: str,
    likely_fields: Optional[list[str]] = None,
) -> dict:
    """Append an entity suggestion. Idempotent by ``name``."""
    name = _norm_name(name, kind="entity name")
    new = copy.deepcopy(dossier)
    entities = list(new.get("entitySuggestions") or [])
    if any((e.get("name") or "").strip() == name for e in entities):
        return new
    fields = [
        f.strip() for f in (likely_fields or [])
        if isinstance(f, str) and f.strip()
    ]
    entry: dict = {"name": name}
    if fields:
        entry["likelyFields"] = fields
    entities.append(entry)
    new["entitySuggestions"] = entities
    return new


def remove_entity_suggestion(dossier: dict, *, name: str) -> dict:
    """Drop an entity suggestion by name. Idempotent."""
    name = _norm_name(name, kind="entity name")
    new = copy.deepcopy(dossier)
    entities = list(new.get("entitySuggestions") or [])
    new["entitySuggestions"] = [
        e for e in entities if (e.get("name") or "").strip() != name
    ]
    return new


# --------------------------------------------------------------------------- #
# Design-pattern ops                                                           #
# --------------------------------------------------------------------------- #

def add_design_pattern(
    dossier: dict,
    *,
    name: str,
    description: str = "",
    evidence: Optional[list[str]] = None,
) -> dict:
    """Append a design pattern. Idempotent by ``name``."""
    name = _norm_name(name, kind="pattern name")
    new = copy.deepcopy(dossier)
    patterns = list(new.get("designPatterns") or [])
    if any((p.get("name") or "").strip() == name for p in patterns):
        return new
    entry: dict = {"name": name, "description": _norm_text(description)}
    ev = [
        e.strip() for e in (evidence or [])
        if isinstance(e, str) and e.strip()
    ]
    if ev:
        entry["evidence"] = ev
    patterns.append(entry)
    new["designPatterns"] = patterns
    return new


def remove_design_pattern(dossier: dict, *, name: str) -> dict:
    """Drop a design pattern by name. Idempotent."""
    name = _norm_name(name, kind="pattern name")
    new = copy.deepcopy(dossier)
    patterns = list(new.get("designPatterns") or [])
    new["designPatterns"] = [
        p for p in patterns if (p.get("name") or "").strip() != name
    ]
    return new


# --------------------------------------------------------------------------- #
# Pitfall ops                                                                  #
# --------------------------------------------------------------------------- #

def add_pitfall(dossier: dict, *, text: str) -> dict:
    """Append a common pitfall. Idempotent by exact string."""
    t = _norm_text(text, kind="pitfall")
    if not t:
        raise DossierAdjustError("pitfall text cannot be empty")
    new = copy.deepcopy(dossier)
    existing = list(new.get("commonPitfalls") or [])
    if t in existing:
        return new
    existing.append(t)
    new["commonPitfalls"] = existing
    return new


def remove_pitfall(dossier: dict, *, text: str) -> dict:
    """Drop a pitfall by exact string. Idempotent."""
    t = _norm_text(text, kind="pitfall")
    new = copy.deepcopy(dossier)
    existing = list(new.get("commonPitfalls") or [])
    new["commonPitfalls"] = [x for x in existing if x != t]
    return new


# --------------------------------------------------------------------------- #
# Visual-language ops                                                          #
# --------------------------------------------------------------------------- #

def set_visual_language(
    dossier: dict,
    *,
    palette_character: Optional[str] = None,
    typography_tone: Optional[str] = None,
    density_preference: Optional[str] = None,
) -> dict:
    """Update one or more visualLanguage keys. Keys not supplied stay
    put. Passing an explicit empty string clears that key."""
    new = copy.deepcopy(dossier)
    vl = dict(new.get("visualLanguage") or {})
    if palette_character is not None:
        vl["paletteCharacter"] = _norm_text(palette_character)
    if typography_tone is not None:
        vl["typographyTone"] = _norm_text(typography_tone)
    if density_preference is not None:
        vl["densityPreference"] = _norm_text(density_preference)
    new["visualLanguage"] = vl
    return new


# --------------------------------------------------------------------------- #
# Diff + validate                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class DossierDiff:
    """Structured summary of what one op (or a batch) changed. Fed to
    the UI so users see chips like `+ pattern Kanban board`."""

    compliance_added:  list[str] = field(default_factory=list)
    compliance_removed: list[str] = field(default_factory=list)
    entities_added:    list[str] = field(default_factory=list)
    entities_removed:  list[str] = field(default_factory=list)
    patterns_added:    list[str] = field(default_factory=list)
    patterns_removed:  list[str] = field(default_factory=list)
    pitfalls_added:    list[str] = field(default_factory=list)
    pitfalls_removed:  list[str] = field(default_factory=list)
    domain_changed:      bool = False
    description_changed: bool = False
    visual_changed:      bool = False

    def is_empty(self) -> bool:
        return not any([
            self.compliance_added, self.compliance_removed,
            self.entities_added, self.entities_removed,
            self.patterns_added, self.patterns_removed,
            self.pitfalls_added, self.pitfalls_removed,
            self.domain_changed, self.description_changed, self.visual_changed,
        ])

    def to_dict(self) -> dict:
        return {
            "compliance_added":    list(self.compliance_added),
            "compliance_removed":  list(self.compliance_removed),
            "entities_added":      list(self.entities_added),
            "entities_removed":    list(self.entities_removed),
            "patterns_added":      list(self.patterns_added),
            "patterns_removed":    list(self.patterns_removed),
            "pitfalls_added":      list(self.pitfalls_added),
            "pitfalls_removed":    list(self.pitfalls_removed),
            "domain_changed":      self.domain_changed,
            "description_changed": self.description_changed,
            "visual_changed":      self.visual_changed,
        }


def _names(items: Optional[list[dict]], key: str = "name") -> set[str]:
    return {
        (i.get(key) or "").strip()
        for i in (items or [])
        if isinstance(i, dict) and (i.get(key) or "").strip()
    }


def compute_diff(before: dict, after: dict) -> DossierDiff:
    """Named diff between two dossier versions. Used by the API to
    tell the client exactly what changed after each Adjust turn."""
    b_c = set(before.get("complianceNotes") or [])
    a_c = set(after.get("complianceNotes") or [])
    b_e = _names(before.get("entitySuggestions"))
    a_e = _names(after.get("entitySuggestions"))
    b_p = _names(before.get("designPatterns"))
    a_p = _names(after.get("designPatterns"))
    b_pf = set(before.get("commonPitfalls") or [])
    a_pf = set(after.get("commonPitfalls") or [])
    return DossierDiff(
        compliance_added=sorted(a_c - b_c),
        compliance_removed=sorted(b_c - a_c),
        entities_added=sorted(a_e - b_e),
        entities_removed=sorted(b_e - a_e),
        patterns_added=sorted(a_p - b_p),
        patterns_removed=sorted(b_p - a_p),
        pitfalls_added=sorted(a_pf - b_pf),
        pitfalls_removed=sorted(b_pf - a_pf),
        domain_changed=(before.get("domain") or "") != (after.get("domain") or ""),
        description_changed=(before.get("description") or "") != (after.get("description") or ""),
        visual_changed=(before.get("visualLanguage") or {}) != (after.get("visualLanguage") or {}),
    )


def validate_dossier_shape(dossier: dict) -> list[str]:
    """Check for values outside their whitelists. Returns human-readable
    warnings (empty on a clean dossier)."""
    warnings: list[str] = []
    for r in dossier.get("complianceNotes") or []:
        if not isinstance(r, str) or r.strip().lower() not in _COMPLIANCE_REGIMES:
            warnings.append(
                f"unknown compliance regime {r!r} — not in "
                f"{sorted(_COMPLIANCE_REGIMES)}"
            )
    return warnings
