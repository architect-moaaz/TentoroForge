"""Tests for the confidence-floor post-validation step (B-003).

Failure mode: the discovery LLM sometimes emits `confidence: 0.0`
even when it clearly understood the domain (dossier has real design
patterns, entity suggestions, a real domain name). Downstream agents
throttle their creativity on that number, so 0 is corrosive. The
post-validation floor bumps it to 0.5 when the dossier is populated.
"""

from __future__ import annotations

from agents.domain_agent import DiscoveryOutput, DesignPattern, EntitySuggestion


def _floor(d: DiscoveryOutput) -> DiscoveryOutput:
    """Mirror the exact floor logic from `run_domain_discovery`.

    Kept as a pure helper so the test doesn't have to spin up the
    Anthropic client. If the module ever refactors the check into a
    standalone function, replace this with a direct import.
    """
    if d.source == "domain_agent" and d.confidence < 0.2:
        has_content = (
            bool(d.designPatterns)
            or bool(d.entitySuggestions)
            or (d.domain and d.domain.lower() not in ("generic", "unknown", ""))
        )
        if has_content:
            d.confidence = 0.5
    return d


class TestConfidenceFloor:
    def test_populated_dossier_with_zero_gets_floored(self):
        d = DiscoveryOutput(
            domain="Hospitality",
            confidence=0.0,
            designPatterns=[
                DesignPattern(name="Booking calendar", description="...", evidence=["training_data"]),
            ],
            source="domain_agent",
        )
        assert _floor(d).confidence == 0.5

    def test_populated_dossier_with_entity_suggestions_gets_floored(self):
        d = DiscoveryOutput(
            domain="Healthcare",
            confidence=0.05,
            entitySuggestions=[
                EntitySuggestion(name="Patient", likelyFields=["dob", "mrn"]),
            ],
            source="domain_agent",
        )
        assert _floor(d).confidence == 0.5

    def test_generic_empty_dossier_keeps_low_confidence(self):
        d = DiscoveryOutput(
            domain="Generic",
            confidence=0.0,
            source="domain_agent",
        )
        # No designPatterns, no entities, generic domain — floor does NOT fire.
        assert _floor(d).confidence == 0.0

    def test_high_confidence_untouched(self):
        d = DiscoveryOutput(
            domain="Hospitality",
            confidence=0.85,
            designPatterns=[
                DesignPattern(name="Booking calendar", description="...", evidence=["training_data"]),
            ],
            source="domain_agent",
        )
        assert _floor(d).confidence == 0.85

    def test_salvage_source_untouched(self):
        d = DiscoveryOutput(
            domain="Hospitality",
            confidence=0.0,
            designPatterns=[
                DesignPattern(name="X", description="...", evidence=["training_data"]),
            ],
            source="validation_salvage",
        )
        # Validation salvage means the LLM emitted a broken response;
        # the low confidence is intentional and should stick.
        assert _floor(d).confidence == 0.0
