"""Tests for the chat-approval pause/resume helpers in routers/generate.py.

These cover the file-based pending-discovery store + the edit-parsing /
edit-application pipeline that the /chat handler uses between
[APPROVE_PLAN] (which triggers discovery + pause) and [APPROVE_DISCOVERY]
(which dispatches the actual pipeline with user-approved domain context).

The chat handler endpoint itself is covered by an integration test gated
on ANTHROPIC_API_KEY presence — these unit tests just verify the
deterministic helper logic that sits underneath it.
"""
from __future__ import annotations

import json

import pytest

from routers.generate import (
    _save_pending_discovery,
    _load_pending_discovery,
    _clear_pending_discovery,
    _pending_discovery_path,
    _parse_discovery_edits,
    _apply_discovery_edits,
)


# ── Pending discovery file lifecycle ────────────────────────────────────────


def test_save_then_load_roundtrip(tmp_path):
    payload = {"domain": "Hospitality", "confidence": 0.92, "personas": {}}
    _save_pending_discovery(str(tmp_path), payload)
    assert _load_pending_discovery(str(tmp_path)) == payload


def test_save_creates_parent_dirs(tmp_path):
    """Project dir may not exist yet on first save — helper must mkdir."""
    nested = tmp_path / "missing" / "level"
    _save_pending_discovery(str(nested), {"domain": "X", "personas": {}})
    assert (nested / ".pending_discovery.json").exists()


def test_load_returns_none_when_no_pending(tmp_path):
    assert _load_pending_discovery(str(tmp_path)) is None


def test_load_returns_none_on_corrupt_json(tmp_path):
    """If somebody manually mucks with the file and writes invalid JSON,
    helper returns None rather than raising. Caller treats it as 'no
    pending discovery' which triggers a fresh discovery run."""
    p = _pending_discovery_path(str(tmp_path))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json at all]", encoding="utf-8")
    assert _load_pending_discovery(str(tmp_path)) is None


def test_clear_removes_file(tmp_path):
    _save_pending_discovery(str(tmp_path), {"domain": "X", "personas": {}})
    assert _load_pending_discovery(str(tmp_path)) is not None
    _clear_pending_discovery(str(tmp_path))
    assert _load_pending_discovery(str(tmp_path)) is None


def test_clear_is_idempotent_when_no_file(tmp_path):
    """clear() called twice (or before save) is harmless. Important
    because cleanup may run on errors / retries."""
    _clear_pending_discovery(str(tmp_path))  # nothing exists
    _clear_pending_discovery(str(tmp_path))  # still nothing


def test_save_overwrites_previous(tmp_path):
    """A new discovery run replaces the previous awaiting-approval one.
    User flow: regenerate → discovery v2 supersedes pending v1."""
    _save_pending_discovery(str(tmp_path), {"domain": "Hospitality", "personas": {}})
    _save_pending_discovery(str(tmp_path), {"domain": "Fintech", "personas": {}})
    assert _load_pending_discovery(str(tmp_path))["domain"] == "Fintech"


# ── Edit parsing ────────────────────────────────────────────────────────────


def test_parse_no_edits_for_bare_signal():
    """Plain `[APPROVE_DISCOVERY]` with no body — empty edit dict."""
    assert _parse_discovery_edits("[APPROVE_DISCOVERY]") == {}


def test_parse_no_edits_for_whitespace_tail():
    assert _parse_discovery_edits("[APPROVE_DISCOVERY]   ") == {}


def test_parse_edits_with_json_body():
    """Frontend sends edits as JSON after the signal token."""
    msg = '[APPROVE_DISCOVERY] {"domain": "Hospitality", "complianceNotes": ["pci"]}'
    out = _parse_discovery_edits(msg)
    assert out == {"domain": "Hospitality", "complianceNotes": ["pci"]}


def test_parse_edits_ignores_non_whitelisted_keys():
    """Stray fields (e.g. `personas` or hallucinated keys) are silently
    dropped — only the whitelist (`domain`, `complianceNotes`) survives.
    This limits the blast radius of malformed or malicious edits."""
    msg = '[APPROVE_DISCOVERY] {"domain": "X", "personas": {"page": "evil"}, "uncertainAreas": ["x"]}'
    out = _parse_discovery_edits(msg)
    assert out == {"domain": "X"}


def test_parse_edits_returns_empty_when_not_signal():
    """Helper is only meant for [APPROVE_DISCOVERY] messages. Other
    messages (clarifications, refinements) should not be parsed as edits."""
    assert _parse_discovery_edits("regenerate with healthcare focus") == {}
    assert _parse_discovery_edits("[APPROVE_PLAN]") == {}


def test_parse_edits_tolerates_prose_around_json():
    """The frontend SHOULD send clean JSON, but the helper tolerates
    surrounding prose by extracting the first {...} balanced block."""
    msg = '[APPROVE_DISCOVERY] looks good! {"domain": "Hospitality"}'
    out = _parse_discovery_edits(msg)
    assert out == {"domain": "Hospitality"}


def test_parse_edits_returns_empty_on_malformed_json():
    """Garbage JSON tail = no edits applied. The approval still proceeds
    with the original pending discovery."""
    msg = '[APPROVE_DISCOVERY] {domain: not valid json}'
    assert _parse_discovery_edits(msg) == {}


# ── Edit application ────────────────────────────────────────────────────────


def test_apply_no_edits_returns_copy_of_discovery():
    """No edits → unchanged copy. Doesn't mutate the input dict."""
    src = {"domain": "X", "personas": {"page_assembler": "..."}}
    out = _apply_discovery_edits(src, {})
    assert out == src
    assert out is not src  # new dict


def test_apply_overrides_domain():
    src = {"domain": "Hospitality", "personas": {}}
    out = _apply_discovery_edits(src, {"domain": "Boutique Hotels"})
    assert out["domain"] == "Boutique Hotels"
    # Original not mutated
    assert src["domain"] == "Hospitality"


def test_apply_strips_whitespace_on_domain():
    src = {"domain": "X", "personas": {}}
    out = _apply_discovery_edits(src, {"domain": "  Hospitality  "})
    assert out["domain"] == "Hospitality"


def test_apply_ignores_empty_domain_string():
    """Empty / whitespace-only domain edit is ignored — keeps the
    original. Prevents the user from accidentally wiping the label."""
    src = {"domain": "Hospitality", "personas": {}}
    out = _apply_discovery_edits(src, {"domain": "   "})
    assert out["domain"] == "Hospitality"


def test_apply_overrides_compliance_notes():
    src = {"domain": "X", "complianceNotes": ["pci"], "personas": {}}
    out = _apply_discovery_edits(src, {"complianceNotes": ["pci", "gdpr"]})
    assert out["complianceNotes"] == ["pci", "gdpr"]


def test_apply_coerces_invalid_compliance_via_domain_agent_enum():
    """User edit of complianceNotes goes through the same _coerce_compliance
    filter as discovery-agent output. So hallucinated regimes from the user
    (or a malicious client) get dropped, not smuggled in via the edit path."""
    src = {"domain": "X", "complianceNotes": ["none"], "personas": {}}
    out = _apply_discovery_edits(src, {
        "complianceNotes": ["hipaa", "FAKE_REGIME", "pci"],
    })
    assert out["complianceNotes"] == ["hipaa", "pci"]


def test_apply_ignores_non_list_compliance():
    """If the user sends complianceNotes as a string (not a list), ignore
    it — the discovery agent's enum coerce only accepts lists."""
    src = {"domain": "X", "complianceNotes": ["pci"], "personas": {}}
    out = _apply_discovery_edits(src, {"complianceNotes": "pci"})
    # Original preserved
    assert out["complianceNotes"] == ["pci"]


def test_apply_does_not_mutate_input():
    """Defensive copy — edits never reach back through the caller's dict."""
    src = {"domain": "X", "personas": {"page_assembler": "P"}}
    edits = {"domain": "Y"}
    _apply_discovery_edits(src, edits)
    assert src["domain"] == "X"
