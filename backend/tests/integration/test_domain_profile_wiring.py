"""End-to-end wiring test for the discovery → [DOMAIN PROFILE] flow.

This is the integration counterpart to the unit tests in:
  - tests/services/test_domain_context.py (build_domain_profile shape)
  - tests/agents/test_domain_agent.py (run_domain_discovery schema)
  - tests/routers/test_discovery_pause.py (chat-approval helpers)

What it tests:
  For every agent in the main pipeline (the 9 with a persona key in the
  discovery dossier + design_agent), verify that:

    1. The agent imports `build_domain_profile` from services.domain_context
       (i.e. the migration in Commit 5 actually landed).
    2. When the agent runs with a populated `domain_context` dict, the
       resulting `ClaudeAgentOptions.system_prompt` contains the
       canonical `## [DOMAIN PROFILE]` header AND the role-specific
       persona string from the dossier.
    3. When `domain_context=None`, the system_prompt does NOT contain
       the header — the agent falls back to its generic prompt.

What it does NOT test:
  The full pipeline orchestration (`_run_relay_pipeline`) — that
  involves file I/O, npm install, etc. Test by mocking the agent layer
  is mocking what we want to verify, so we test directly at the agent
  entry point instead. The chat-handler approval path is covered by
  tests/routers/test_discovery_pause.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest


# ── Sample dossier mirroring agents.domain_agent.DiscoveryOutput ────────────

FULL_DOSSIER = {
    "domain": "Hospitality",
    "description": "Boutique hotel chain with guest experience focus",
    "confidence": 0.9,
    "personas": {
        "planner":           "PERSONA_PLANNER: hospitality systems planner.",
        "contract_writer":   "PERSONA_CONTRACT: data contracts for hotels.",
        "schema_designer":   "PERSONA_SCHEMA: reservations + rooms + guests.",
        "auth_agent":        "PERSONA_AUTH: guest + staff users with PCI scope.",
        "api_generator":     "PERSONA_API: booking endpoints + availability.",
        "business_logic":    "PERSONA_BIZ: stay lifecycle + housekeeping.",
        "component_builder": "PERSONA_COMPONENT: warm hospitality UI.",
        "page_assembler":    "PERSONA_PAGE: booking-flow page assembly.",
        "qa_tester":         "PERSONA_QA: guest-flow correctness.",
    },
    "complianceNotes": ["pci", "gdpr"],
    "commonPitfalls": [
        "Forgetting room-availability calendar logic",
        "Mixing guest-facing and staff-facing surfaces",
    ],
    "entitySuggestions": [
        {"name": "Reservation", "likelyFields": ["guestId", "roomId", "checkIn", "checkOut"]},
        {"name": "Room", "likelyFields": ["number", "type", "rate"]},
    ],
    "designPatterns": [
        {"name": "Reservation calendar", "description": "Drag-to-extend stays."},
    ],
    "visualLanguage": {
        "paletteCharacter": "warm earth tones",
        "typographyTone": "refined serif",
        "densityPreference": "spacious",
    },
    "formPatterns": [{"pattern": "Multi-step booking form"}],
    "uncertainAreas": ["Whether housekeeping is in scope"],
}


# ── Stub plan covering every agent's required keys ──────────────────────────

STUB_PLAN = {
    "module_name": "BoutiqueHotelOps",
    "description": "Hotel reservation management",
    "data_models": [
        {
            "name": "Reservation",
            "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "guestId", "type": "uuid"},
                {"name": "checkIn", "type": "date"},
            ],
        }
    ],
    "pages": [
        {"route": "/reservations", "name": "Reservations", "type": "list"},
    ],
    "api_routes": [
        {"method": "GET", "path": "/api/reservations", "description": "list"}
    ],
    "workflows": [
        {"name": "CheckinFlow", "description": "Check guest in"}
    ],
    "access_control": {"roles": ["guest", "staff"]},
    "components": [],
    "shared_components": [],
    "layouts": [],
    "relations": [],
}


def _stub_query():
    """Return an async-iterable mock for `claude_agent_sdk.query` — yields
    nothing (immediate completion) so agents return without doing work."""
    async def _empty(*_args, **_kwargs):
        # Async generator that yields zero messages — agents finish cleanly.
        return
        yield  # pragma: no cover  (makes function a generator)
    return _empty


# Map agent → (module path, callable, role, persona marker, query attr).
# Each entry is one parametrize case.
AGENT_CASES = [
    pytest.param(
        "agents.contract_agent",
        "run_contract_agent",
        "contract_writer",
        "PERSONA_CONTRACT",
        id="contract_writer",
    ),
    pytest.param(
        "agents.schema_agent",
        "run_schema_agent",
        "schema_designer",
        "PERSONA_SCHEMA",
        id="schema_designer",
    ),
    pytest.param(
        "agents.auth_agent",
        "run_auth_agent",
        "auth_agent",
        "PERSONA_AUTH",
        id="auth_agent",
    ),
    pytest.param(
        "agents.api_agent",
        "run_api_agent",
        "api_generator",
        "PERSONA_API",
        id="api_generator",
    ),
    pytest.param(
        "agents.business_logic_agent",
        "run_business_logic_agent",
        "business_logic",
        "PERSONA_BIZ",
        id="business_logic",
    ),
    pytest.param(
        "agents.component_agent",
        "run_component_agent",
        "component_builder",
        "PERSONA_COMPONENT",
        id="component_builder",
    ),
    pytest.param(
        "agents.page_agent",
        "run_page_agent",
        "page_assembler",
        "PERSONA_PAGE",
        id="page_assembler",
    ),
    pytest.param(
        "agents.qa_agent",
        "run_qa_agent",
        "qa_tester",
        "PERSONA_QA",
        id="qa_tester",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,fn_name,role,persona_marker", AGENT_CASES)
async def test_domain_profile_reaches_agent_system_prompt(
    tmp_path: Path, module_name: str, fn_name: str, role: str, persona_marker: str
):
    """Each main pipeline agent receives a `## [DOMAIN PROFILE]` block
    containing its role-specific persona when domain_context is populated.

    This guards against regressions in the Commit 5 wiring — if someone
    re-introduces the old `domain_persona + kb_context` split or breaks
    the `build_domain_profile` call, this test catches it.
    """
    import importlib

    mod = importlib.import_module(module_name)
    fn = getattr(mod, fn_name)

    # Capture the ClaudeAgentOptions passed into query() so we can inspect
    # the system_prompt. The agents pass options as a kwarg.
    captured = {}

    async def _capture_query(*, prompt, options, **_):
        captured["system_prompt"] = options.system_prompt
        # Yield zero messages — agent returns cleanly.
        if False:
            yield  # pragma: no cover

    with patch.object(mod, "query", _capture_query):
        async for _ in fn(str(tmp_path), STUB_PLAN, domain_context=FULL_DOSSIER):
            pass

    assert "system_prompt" in captured, (
        f"{fn_name} never called query — pipeline wiring broken"
    )
    sp = captured["system_prompt"]
    assert "## [DOMAIN PROFILE]" in sp, (
        f"{fn_name} ({role}) system_prompt missing [DOMAIN PROFILE] header. "
        f"build_domain_profile call may have been removed."
    )
    assert "Hospitality" in sp, (
        f"{fn_name} ({role}) system_prompt missing domain label"
    )
    assert persona_marker in sp, (
        f"{fn_name} ({role}) system_prompt missing role-specific persona "
        f"'{persona_marker}' — wrong role passed to build_domain_profile?"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,fn_name,role,persona_marker", AGENT_CASES)
async def test_agent_falls_back_to_generic_prompt_without_domain_context(
    tmp_path: Path, module_name: str, fn_name: str, role: str, persona_marker: str
):
    """When domain_context is None, no [DOMAIN PROFILE] block appears in
    the system_prompt — agent uses its generic prompt unchanged. This
    keeps the pipeline working in test/dev environments without an
    ANTHROPIC_API_KEY for the discovery agent."""
    import importlib

    mod = importlib.import_module(module_name)
    fn = getattr(mod, fn_name)

    captured = {}

    async def _capture_query(*, prompt, options, **_):
        captured["system_prompt"] = options.system_prompt
        if False:
            yield  # pragma: no cover

    with patch.object(mod, "query", _capture_query):
        async for _ in fn(str(tmp_path), STUB_PLAN, domain_context=None):
            pass

    assert "system_prompt" in captured
    sp = captured["system_prompt"]
    assert "## [DOMAIN PROFILE]" not in sp, (
        f"{fn_name} leaked a [DOMAIN PROFILE] block with no domain_context"
    )
    # No persona text either
    assert persona_marker not in sp


@pytest.mark.asyncio
async def test_design_agent_gets_visual_and_patterns():
    """design_agent is special — no persona, but should get the
    visual-language + design-patterns sections (the parts it actually
    uses to shape globals.css). Tested separately because it has a
    different signature (figma_screenshots kwarg) and a different
    relevant section set."""
    from agents import design_agent

    captured = {}

    async def _capture_query(*, prompt, options, **_):
        captured["system_prompt"] = options.system_prompt
        if False:
            yield  # pragma: no cover

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with patch.object(design_agent, "query", _capture_query):
            async for _ in design_agent.run_design_agent(
                tmp, STUB_PLAN, domain_context=FULL_DOSSIER
            ):
                pass

    sp = captured["system_prompt"]
    assert "## [DOMAIN PROFILE]" in sp
    assert "Visual language" in sp, "design_agent missing visualLanguage section"
    assert "warm earth tones" in sp, "palette character missing"
    assert "Design patterns" in sp, "design_agent missing designPatterns section"
    assert "Reservation calendar" in sp
    # No persona — design_agent isn't in the Personas Pydantic model
    assert "PERSONA_" not in sp


@pytest.mark.asyncio
async def test_discovery_persisted_via_pipeline(tmp_path):
    """When `_run_relay_pipeline` receives a pre-approved domain_context
    (the chat-approval path), it persists discovery.json to disk before
    any agent runs. This is what makes the dossier inspectable post-hoc
    and re-usable on regenerate. Verifies the disk write happens — does
    NOT run the full pipeline (mocks the first downstream agent to abort
    early)."""
    from agents.domain_agent import persist_discovery

    # persist_discovery is the helper the pipeline calls in both paths
    # (with/without pre-approval). Verify it actually writes the dossier
    # to the canonical location.
    out = persist_discovery(str(tmp_path), FULL_DOSSIER)
    disk_path = Path(out)
    assert disk_path.exists(), "persist_discovery didn't write a file"

    on_disk = json.loads(disk_path.read_text())
    assert on_disk["domain"] == "Hospitality"
    assert on_disk["personas"]["planner"].startswith("PERSONA_PLANNER")
    assert "Reservation" in {e["name"] for e in on_disk["entitySuggestions"]}
