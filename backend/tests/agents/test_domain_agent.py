"""Tests for backend/agents/domain_agent.py.

These tests cover everything that doesn't require a live LLM call:
  - The Pydantic DiscoveryOutput schema (shape, defaults, validation)
  - The JSON extractor (clean, noisy, malformed input)
  - The compliance coercion (filtering invalid values, default fallback)
  - The plan section builder
  - The retry-on-parse-failure behavior (with a mocked Anthropic client)
  - The web-search tool attachment (with a mocked client)

The actual LLM call is covered by an integration test gated on
ANTHROPIC_API_KEY presence (kept out of CI by default).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.domain_agent import (
    DesignPattern,
    DiscoveryOutput,
    EntitySuggestion,
    FormPattern,
    Personas,
    VisualLanguage,
    _build_plan_section,
    _coerce_compliance,
    _extract_json_object,
    run_domain_discovery,
)


# ── Schema ──────────────────────────────────────────────────────────────────


def test_discovery_output_defaults():
    """A DiscoveryOutput with only required fields populates sensible defaults
    for everything else. Important because if validation fails mid-pipeline
    we want to fall back to a minimum-viable output, not crash."""
    out = DiscoveryOutput(domain="Hospitality")
    d = out.model_dump()
    assert d["domain"] == "Hospitality"
    assert d["domainAliases"] == []
    assert d["confidence"] == 0.0
    assert d["personas"]["page_assembler"] == ""
    assert d["personas"]["schema_designer"] == ""
    assert d["personas"]["auth_agent"] == ""
    assert d["designPatterns"] == []
    assert d["visualLanguage"]["paletteCharacter"] == "neutral"
    assert d["complianceNotes"] == []
    assert d["source"] == "domain_agent"


def test_discovery_output_full_roundtrip():
    """A complete output should serialise + deserialise without loss."""
    src = {
        "domain": "Hospitality",
        "domainAliases": ["hotel", "travel"],
        "confidence": 0.92,
        "description": "Boutique hotel booking app",
        "personas": {
            "planner": "p1", "contract_writer": "p2", "schema_designer": "p3",
            "auth_agent": "p4", "api_generator": "p5", "business_logic": "p6",
            "component_builder": "p7", "page_assembler": "p8", "qa_tester": "p9",
            "design": "p10", "shell": "p11", "default": "p12",
        },
        "designPatterns": [{
            "name": "Date-range hero",
            "description": "Search calendar above the fold.",
            "evidence": ["https://booking.com", "training_data"],
        }],
        "visualLanguage": {
            "paletteCharacter": "warm",
            "typographyTone": "editorial",
            "densityPreference": "comfortable",
        },
        "entitySuggestions": [
            {"name": "Reservation", "likelyFields": ["startDate", "endDate", "guestCount"]},
        ],
        "formPatterns": [{"pattern": "date-range + guest-count", "contexts": ["search hero"]}],
        "complianceNotes": ["pci", "gdpr"],
        "commonPitfalls": ["Forgetting timezone handling"],
        "uncertainAreas": ["Loyalty programs are out of scope per the description"],
    }
    out = DiscoveryOutput(**src)
    assert out.model_dump()["domain"] == "Hospitality"
    assert out.personas.schema_designer == "p3"
    assert out.personas.auth_agent == "p4"
    assert out.personas.qa_tester == "p9"
    assert out.designPatterns[0].evidence == ["https://booking.com", "training_data"]
    assert out.complianceNotes == ["pci", "gdpr"]


def test_personas_keys_match_downstream_consumers():
    """The Personas model's field set must include every role that
    backend/agents/*.py calls `get_agent_persona(ctx, role)` with.
    Adding new fields is safe; missing ones cascade to empty personas in
    downstream agents and silently degrade output quality.

    The reference set comes from `grep -h 'get_agent_persona' backend/agents/*.py`.
    Keep this assertion in sync when adding a new role consumer.
    """
    required_roles = {
        "planner", "contract_writer", "schema_designer", "auth_agent",
        "api_generator", "business_logic", "component_builder",
        "page_assembler", "qa_tester",
    }
    personas_fields = set(Personas.model_fields.keys())
    missing = required_roles - personas_fields
    assert not missing, f"Personas missing required fields: {missing}"


# ── JSON extraction ─────────────────────────────────────────────────────────


def test_extract_clean_json():
    assert _extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_noisy_json_with_prose():
    """The model sometimes adds prose despite the no-prose instruction;
    the extractor recovers the JSON object."""
    text = "Here's the dossier:\n\n{\"a\": 1, \"b\": 2}\n\nLet me know if you need more detail."
    assert _extract_json_object(text) == {"a": 1, "b": 2}


def test_extract_json_with_code_fence():
    """When the model wraps in ```json ... ``` despite the instruction,
    the regex still finds the object inside."""
    text = "```json\n{\"x\": [1,2,3]}\n```"
    assert _extract_json_object(text) == {"x": [1, 2, 3]}


def test_extract_returns_none_on_garbage():
    assert _extract_json_object("no json here at all") is None


def test_extract_handles_nested_objects():
    text = 'prefix {"outer": {"inner": [1,2]}, "z": "a"} suffix'
    parsed = _extract_json_object(text)
    assert parsed == {"outer": {"inner": [1, 2]}, "z": "a"}


# ── Compliance coercion ─────────────────────────────────────────────────────


def test_coerce_compliance_filters_unknown():
    """A hallucinated compliance regime ('ferpa_lite') gets dropped silently.
    Real values pass through. This is what prevents a stray invented regime
    from tanking the whole pipeline at the validation step."""
    assert _coerce_compliance(["hipaa", "pci", "ferpa_lite", "made_up"]) == ["hipaa", "pci"]


def test_coerce_compliance_lowercases():
    """The model sometimes title-cases. Coerce to lower for canonical form."""
    assert _coerce_compliance(["HIPAA", "Pci"]) == ["hipaa", "pci"]


def test_coerce_compliance_empty_returns_none_marker():
    """Empty / all-invalid input returns ['none'] so downstream agents can
    distinguish 'no compliance regimes apply' from 'compliance not yet
    determined' — both render as the same persona content, but the
    explicit 'none' marker is the contract."""
    assert _coerce_compliance([]) == ["none"]
    assert _coerce_compliance(["fake1", "fake2"]) == ["none"]


def test_coerce_compliance_dedupes_via_iteration():
    """Duplicate inputs may show up — model emits the same regime twice.
    Today this isn't deduped (preserves order); test documents current
    behavior so future change is intentional."""
    out = _coerce_compliance(["hipaa", "hipaa", "pci"])
    assert out == ["hipaa", "hipaa", "pci"]


# ── Plan section ────────────────────────────────────────────────────────────


def test_plan_section_empty_plan_returns_empty():
    assert _build_plan_section(None) == ""
    assert _build_plan_section({}) == ""
    assert _build_plan_section({"pages": [], "entities": {}}) == ""


def test_plan_section_with_pages_and_entities():
    section = _build_plan_section({
        "pages": [{"id": "home"}, {"id": "bookings"}, {"id": "rooms"}],
        "entities": {"Reservation": {}, "Guest": {}, "Room": {}},
    })
    assert "home, bookings, rooms" in section
    assert "Reservation, Guest, Room" in section


def test_plan_section_with_entity_list_form():
    """Some planners emit entities as a list of {name: ...}, not a dict."""
    section = _build_plan_section({
        "pages": [{"id": "home"}],
        "entities": [{"name": "User"}, {"name": "Post"}],
    })
    assert "User, Post" in section


def test_plan_section_truncates_long_lists():
    """Pages > 10 are truncated to keep prompt size bounded."""
    pages = [{"id": f"page{i}"} for i in range(15)]
    section = _build_plan_section({"pages": pages})
    assert "page0" in section
    assert "page9" in section
    # Truncates AT 10, so page10 should not appear
    assert "page14" not in section


# ── Live-call shape (mocked) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_domain_discovery_happy_path(monkeypatch):
    """End-to-end with a mocked Anthropic client.

    Asserts:
      - The client is called once on a clean parse (no retry).
      - Web search tool is attached when enable_web_search=True.
      - Provenance fields (source, model, searchedWeb) are populated.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    payload = {
        "domain": "Hospitality",
        "domainAliases": ["hotel"],
        "confidence": 0.9,
        "description": "Hotel booking app",
        "personas": {
            "planner": "P", "contract_writer": "Cw", "schema_designer": "Sd",
            "auth_agent": "Au", "api_generator": "Ag", "business_logic": "Bl",
            "component_builder": "Cb", "page_assembler": "Pa", "qa_tester": "Qt",
            "design": "D", "shell": "Sh", "default": "Df",
        },
        "designPatterns": [
            {"name": "Date-range hero", "description": "X", "evidence": ["https://example.com"]},
        ],
        "visualLanguage": {"paletteCharacter": "warm", "typographyTone": "editorial", "densityPreference": "comfortable"},
        "entitySuggestions": [{"name": "Reservation", "likelyFields": ["startDate"]}],
        "formPatterns": [{"pattern": "search hero", "contexts": ["home"]}],
        "complianceNotes": ["pci"],
        "commonPitfalls": ["timezone"],
        "uncertainAreas": [],
    }

    fake_response = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps(payload)
    fake_response.content = [text_block]

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=fake_client))

    out = await run_domain_discovery(
        "build me a hotel booking app",
        plan={"pages": [{"id": "home"}], "entities": {"Reservation": {}}},
        enable_web_search=True,
        timeout_seconds=5.0,
    )

    assert out["domain"] == "Hospitality"
    assert out["personas"]["page_assembler"] == "Pa"
    assert out["personas"]["schema_designer"] == "Sd"
    assert out["source"] == "domain_agent"
    assert out["searchedWeb"] is True
    assert out["model"]  # populated with model id
    assert out["elapsedSeconds"] >= 0

    # The first (and only) call should have web_search attached.
    call_args = fake_client.messages.create.await_args
    assert "tools" in call_args.kwargs
    tools = call_args.kwargs["tools"]
    assert tools[0]["type"] == "web_search_20250305"
    assert tools[0]["name"] == "web_search"
    # Called exactly once — no parse retry.
    assert fake_client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_run_domain_discovery_retries_on_parse_failure(monkeypatch):
    """When the first response can't be parsed, the agent issues ONE retry
    with a sharper fixup prompt. The second response succeeds and the result
    is returned. Important guarantee: bounded retry, no infinite loop."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make_response(text):
        r = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = text
        r.content = [block]
        return r

    bad_response = make_response("I cannot help with that. Here's some prose instead.")
    good_payload = {"domain": "Generic", "confidence": 0.5, "personas": {}}
    good_response = make_response(json.dumps(good_payload))

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(side_effect=[bad_response, good_response])

    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=fake_client))

    out = await run_domain_discovery("vague prompt", enable_web_search=False)

    assert out["domain"] == "Generic"
    assert fake_client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_run_domain_discovery_falls_back_after_double_failure(monkeypatch):
    """If even the retry fails to produce parseable JSON, DON'T raise — discovery is
    the first pipeline step and raising dead-ends the whole generation. Instead return
    a valid fallback dossier (keyword-classified domain) so planning still proceeds."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def make_response(text):
        r = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = text
        r.content = [block]
        return r

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(
        side_effect=[make_response("garbage 1"), make_response("garbage 2")]
    )

    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=fake_client))

    out = await run_domain_discovery(
        "An HVAC field service app for technicians and work orders",
        enable_web_search=False,
    )
    assert out["source"] == "fallback_keyword_classifier"
    assert out["domain"]
    assert out.get("_fallbackReason")


@pytest.mark.asyncio
async def test_run_domain_discovery_strips_invalid_compliance(monkeypatch):
    """Hallucinated compliance regimes get filtered out at validation, not
    rejected outright. The output still ships, with only valid regimes."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    payload = {
        "domain": "Hospitality",
        "personas": {},
        "complianceNotes": ["pci", "FAKE_LAW", "made_up_regime", "gdpr"],
    }
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    fake_response.content = [block]

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=fake_client))

    out = await run_domain_discovery("desc", enable_web_search=False)
    assert out["complianceNotes"] == ["pci", "gdpr"]


@pytest.mark.asyncio
async def test_run_domain_discovery_skips_web_search_when_disabled(monkeypatch):
    """enable_web_search=False omits the tools kwarg entirely, so the call
    runs in pure-LLM mode (faster, cheaper, less grounded)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    payload = {"domain": "Generic", "personas": {}}
    fake_response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    fake_response.content = [block]

    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)

    from services import llm_client
    monkeypatch.setattr(llm_client, "AsyncAnthropic", MagicMock(return_value=fake_client))

    out = await run_domain_discovery("desc", enable_web_search=False)
    call_args = fake_client.messages.create.await_args
    assert "tools" not in call_args.kwargs
    assert out["searchedWeb"] is False


@pytest.mark.asyncio
async def test_run_domain_discovery_requires_api_key(monkeypatch):
    """No ANTHROPIC_API_KEY → clear error before any LLM call.
    Prevents silent failures or confusing downstream errors."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await run_domain_discovery("desc")


# ── persist_discovery helper ───────────────────────────────────────────────


def test_persist_discovery_writes_to_contracts_dir(tmp_path):
    """persist_discovery writes to src/contracts/discovery.json + creates
    parent dirs. Returns the path. Pretty-printed JSON for diffability."""
    from agents.domain_agent import persist_discovery
    payload = {"domain": "Hospitality", "confidence": 0.9, "personas": {}}
    path = persist_discovery(str(tmp_path), payload)
    assert "src/contracts/discovery.json" in path

    written = (tmp_path / "src" / "contracts" / "discovery.json").read_text(encoding="utf-8")
    assert '"domain": "Hospitality"' in written
    assert '"confidence": 0.9' in written
    # Sorted keys make diffs deterministic across regens
    parsed = json.loads(written)
    assert parsed["domain"] == "Hospitality"



def test_over_length_common_pitfalls_are_trimmed_not_fatal():
    """Regression: a discovery pass that returns 10 commonPitfalls when the
    schema caps them at 8 used to raise `too_long` and dead-end the entire
    generation (seen live on the 'invoice software' build, 2026-07-28). The
    list must be trimmed to the cap — highest-signal-first — not rejected.
    """
    from agents.domain_agent import _clamp_capped_list_fields, DiscoveryOutput

    raw = {
        "domain": "Invoicing",
        "description": "invoice software",
        "commonPitfalls": [f"pitfall {i}" for i in range(10)],
    }
    trimmed = _clamp_capped_list_fields(raw)
    assert trimmed == ["commonPitfalls 10->8"]
    # validates cleanly now, and keeps the first 8 (emitted highest-signal-first)
    out = DiscoveryOutput(**raw)
    assert out.commonPitfalls == [f"pitfall {i}" for i in range(8)]


def test_clamp_leaves_within_cap_lists_untouched():
    from agents.domain_agent import _clamp_capped_list_fields

    for n in (0, 3, 8):
        raw = {"domain": "X", "commonPitfalls": [f"p{i}" for i in range(n)]}
        assert _clamp_capped_list_fields(raw) == []
        assert len(raw["commonPitfalls"]) == n
    # missing / non-list are no-ops, never raise
    r1 = {"domain": "X"}
    assert _clamp_capped_list_fields(r1) == []
    r2 = {"domain": "X", "commonPitfalls": "not a list"}
    assert _clamp_capped_list_fields(r2) == []
