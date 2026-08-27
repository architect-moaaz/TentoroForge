from agents.domain_agent import _fallback_dossier, DiscoveryOutput


def test_fallback_dossier_is_valid_and_marked():
    out = _fallback_dossier(
        "A field-service management app for an HVAC company — technicians, work orders, "
        "customers, equipment, service contracts, parts inventory, and scheduling.",
        model="claude-sonnet-4-6",
        reason="timeout",
    )
    # Valid against the schema every downstream agent reads.
    DiscoveryOutput(**{k: v for k, v in out.items() if not k.startswith("_")})
    assert out["domain"]  # non-empty (keyword-detected or 'Generic')
    assert out["description"]
    assert out["source"] == "fallback_keyword_classifier"
    assert out["searchedWeb"] is False
    assert out["_fallbackReason"] == "timeout"


def test_fallback_dossier_survives_blank_description():
    out = _fallback_dossier("", model="m", reason="parse")
    assert out["domain"]  # never empty — DiscoveryOutput.domain is required
