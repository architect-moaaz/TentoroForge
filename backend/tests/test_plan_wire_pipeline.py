"""plan_wire_pipeline — shared narrative + wire hooks used by both
``routers.generate.produce_plan`` and
``services.smith_agent_adapters.orchestrate_planner``.

The whole point of this module is that the two orchestration paths
can never drift on which hooks run in what order — so these tests
lock down the shape of the shared entry points, not the specific
paths that consume them.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services.plan_wire_pipeline import (
    apply_narrative_expansion,
    apply_plan_wires,
)


# ── apply_narrative_expansion ─────────────────────────────────

def test_narrative_off_returns_prompt_verbatim(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_NARRATIVE_EXPANSION", raising=False)
    result = asyncio.run(apply_narrative_expansion(
        "hi", structured_brief=None, output_dir=tmp_path,
    ))
    assert result == "hi"
    # Also: no narrative file written.
    assert not (tmp_path / "contracts" / "domain-narrative.md").exists()


def test_narrative_on_prepends_block_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_NARRATIVE_EXPANSION", "1")

    # Stub the LLM call inside expand_prompt_to_narrative by patching
    # the client factory the module reaches for.
    from services import discovery_narrative

    class _FakeText:
        def __init__(self, text): self.text = text

    class _FakeMessage:
        def __init__(self, text): self.content = [_FakeText(text)]

    class _FakeMessages:
        async def create(self, **_):
            return _FakeMessage("# Big Domain Doc\n\nCandidate...")

    class _FakeClient:
        messages = _FakeMessages()

    # Patch the async expand call so we don't need an API key.
    async def _fake_expand(prompt, brief=None, **_kw):
        return "# Big Domain Doc\n\nCandidate..."

    monkeypatch.setattr(
        "services.plan_wire_pipeline.expand_prompt_to_narrative"
        if False else "services.discovery_narrative.expand_prompt_to_narrative",
        _fake_expand,
    )

    result = asyncio.run(apply_narrative_expansion(
        "Build an ATS", structured_brief={"actors": ["candidate"]},
        output_dir=tmp_path,
    ))

    # Narrative block prepended
    assert "DOMAIN NARRATIVE" in result
    assert "Big Domain Doc" in result
    assert "Build an ATS" in result
    # Original prompt preserved at the end
    assert result.endswith("Build an ATS")
    # File persisted under contracts/
    assert (tmp_path / "contracts" / "domain-narrative.md").exists()


def test_narrative_llm_failure_falls_back_to_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_NARRATIVE_EXPANSION", "1")

    async def _boom(*_a, **_kw):
        raise RuntimeError("api down")

    monkeypatch.setattr(
        "services.discovery_narrative.expand_prompt_to_narrative", _boom,
    )
    result = asyncio.run(apply_narrative_expansion(
        "hi", structured_brief=None, output_dir=tmp_path,
    ))
    assert result == "hi"
    assert not (tmp_path / "contracts" / "domain-narrative.md").exists()


def test_narrative_accepts_dataclass_brief(monkeypatch, tmp_path):
    """StructuredBrief comes in as a dataclass in the smith-arch path;
    plain dict in the generate.py path. Both must work."""
    monkeypatch.setenv("FORGE_NARRATIVE_EXPANSION", "1")

    captured: dict = {}

    async def _capture(prompt, brief=None, **_kw):
        captured["brief"] = brief
        return "# out"

    monkeypatch.setattr(
        "services.discovery_narrative.expand_prompt_to_narrative", _capture,
    )

    class _Brief:
        def to_dict(self):
            return {"actors": ["Candidate"]}

    asyncio.run(apply_narrative_expansion(
        "hi", structured_brief=_Brief(), output_dir=tmp_path,
    ))
    assert captured["brief"] == {"actors": ["Candidate"]}


# ── apply_plan_wires ──────────────────────────────────────────

def test_apply_plan_wires_all_flags_off_is_noop(monkeypatch):
    for env in ("FORGE_AUDIT_TRAIL", "FORGE_IMMUTABILITY",
                "FORGE_FIELD_VISIBILITY", "FORGE_CAPACITY_CONSTRAINTS",
                "FORGE_WIZARD"):
        monkeypatch.delenv(env, raising=False)
    plan = {"entities": [{"name": "X"}]}
    assert apply_plan_wires(plan) == plan


def test_apply_plan_wires_runs_every_enabled_pass(monkeypatch):
    """Each wire pass gets a chance to see the plan when its flag is on."""
    for env in ("FORGE_AUDIT_TRAIL", "FORGE_IMMUTABILITY",
                "FORGE_FIELD_VISIBILITY", "FORGE_CAPACITY_CONSTRAINTS",
                "FORGE_WIZARD"):
        monkeypatch.setenv(env, "1")

    plan = {
        "audit_trail":  [{"entity": "Feedback", "on": ["create"]}],
        "immutability": [{"entity": "Feedback"}],
        "field_visibility": [
            {"entity": "Feedback", "field": "notes",
             "hide_from_roles": ["candidate"]},
        ],
        "capacity_constraints": [
            {"entity": "Slot", "scope_field": "date", "limit": 3},
        ],
        "wizards": [
            {"name": "w", "route": "/w", "entity": "Feedback",
             "steps": [{"title": "S", "fields": ["notes"]}]},
        ],
        "entities": [{"name": "Feedback", "fields": [{"name": "notes"}]},
                     {"name": "Slot", "fields": []}],
        "pages":    [],
        "workflows": [{"name": "w", "steps": [
            {"id": "t", "type": "trigger"},
            {"id": "i", "type": "db_insert", "entity": "Feedback"},
            {"id": "e", "type": "end"},
        ]}],
    }
    result = apply_plan_wires(plan)

    # Audit-trail materialized: AuditEntry entity added
    ent_names = {e.get("name") for e in result["entities"]}
    assert "AuditEntry" in ent_names
    # Immutability: is_locked column on Feedback
    feedback = next(e for e in result["entities"]
                    if e.get("name") == "Feedback")
    assert any(f["name"] == "is_locked" for f in feedback["fields"])
    # Field visibility: hidden_from_roles on Feedback.notes
    notes = next(f for f in feedback["fields"] if f["name"] == "notes")
    assert "candidate" in notes["hidden_from_roles"]
    # Wizard: page /w added
    assert any(p.get("route") == "/w" for p in result["pages"])


def test_apply_plan_wires_broken_pass_doesnt_break_others(monkeypatch):
    """If one wire pass raises, the pipeline keeps running with the
    previous plan so the others still contribute."""
    monkeypatch.setenv("FORGE_IMMUTABILITY", "1")
    monkeypatch.setenv("FORGE_WIZARD", "1")

    from services import plan_wire_pipeline

    def _boom(_plan):
        raise RuntimeError("boom")

    def _registry():
        return [
            ("immutability", lambda: True, _boom),
            ("wizard",       lambda: True,
             __import__("services.wizard_wire",
                        fromlist=["wire_wizards"]).wire_wizards),
        ]
    monkeypatch.setattr(plan_wire_pipeline, "_plan_wire_registry", _registry)

    plan = {"wizards": [{"name": "w", "route": "/w", "entity": "X",
                         "steps": [{"title": "S", "fields": ["a"]}]}],
            "pages": []}
    result = plan_wire_pipeline.apply_plan_wires(plan)
    # Wizard pass still ran despite immutability crashing.
    assert any(p.get("route") == "/w" for p in result["pages"])


def test_apply_plan_wires_none_plan_pass_through():
    assert apply_plan_wires(None) is None


def test_apply_plan_wires_non_dict_pass_through():
    assert apply_plan_wires("nope") == "nope"
