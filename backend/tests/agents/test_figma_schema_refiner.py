"""Tests for the Figma Schema Refiner.

The LLM call and the Node Zod validator are monkeypatched so these run fast and
hermetically. Coverage: content-preservation guard, structural guard, prompt
assembly (image + descriptor + schema), and the validate-or-fallback contract.
"""
import asyncio
import json
from pathlib import Path

import pytest

from agents import figma_schema_refiner as mod

# ── small synthetic deterministic schema (fixed-width, content-faithful) ──
SRC = {
    "schemaVersion": "2.0",
    "id": "gate",
    "dataSources": [],
    "children": [
        {"type": "Stack", "props": {"className": "w-[1271px] min-h-[121px] bg-[#fff]"}, "children": [
            {"type": "Heading", "props": {"content": "Gate Control", "className": "w-[200px]"}},
            {"type": "Text", "props": {"content": "DXB-T-12345"}},
            {"type": "Text", "props": {"content": "784-1990-1234567-1"}},
            {"type": "Text", "props": {"content": "Approve Entry"}},
            {"type": "Text", "props": {"content": "Valid RFID"}},
            {"type": "Text", "props": {"content": "{{item.status}}"}},
            {"type": "Avatar", "props": {"photoUrl": "/static/truck.png"}},
        ]},
    ],
}

# Responsive output that preserves all content.
GOOD = {
    "schemaVersion": "2.0",
    "id": "gate",
    "dataSources": [],
    "children": [
        {"type": "Card", "props": {"className": "w-full max-w-[1271px] mx-auto flex flex-col gap-4 md:flex-row md:flex-wrap min-w-0"}, "children": [
            {"type": "Heading", "props": {"content": "Gate Control"}},
            {"type": "Text", "props": {"content": "DXB-T-12345"}},
            {"type": "Text", "props": {"content": "784-1990-1234567-1"}},
            {"type": "Text", "props": {"content": "Approve Entry"}},
            {"type": "Text", "props": {"content": "Valid RFID"}},
            {"type": "Text", "props": {"content": "{{item.status}}"}},
            {"type": "Avatar", "props": {"photoUrl": "/static/truck.png"}},
        ]},
    ],
}

DESCRIPTOR = "Available components:\n  - Card\n  - Stack\n  - Heading\n  - Text\n  - Avatar"


def _mock_llm(returns):
    async def _fake(system, blocks, timeout_s, model):
        if isinstance(returns, Exception):
            raise returns
        return returns
    return _fake


def _run(src=SRC, screenshot=None):
    return asyncio.run(mod.run_figma_schema_refiner(src, screenshot, DESCRIPTOR))


# ── content-preservation guard ──────────────────────────────────────────
def test_preserves_content_true_for_faithful_output():
    assert mod._preserves_content(SRC, GOOD) is True


def test_preserves_content_false_when_binding_dropped():
    out = json.loads(json.dumps(GOOD))
    # remove the {{item.status}} node
    out["children"][0]["children"] = [c for c in out["children"][0]["children"]
                                      if c["props"].get("content") != "{{item.status}}"]
    assert mod._preserves_content(SRC, out) is False


def test_preserves_content_false_when_image_url_dropped():
    out = json.loads(json.dumps(GOOD))
    out["children"][0]["children"] = [c for c in out["children"][0]["children"]
                                      if "photoUrl" not in c["props"]]
    assert mod._preserves_content(SRC, out) is False


def test_preserves_content_false_when_text_content_lost():
    out = json.loads(json.dumps(GOOD))
    # drop several real labels (plate, EID, validation) → below threshold
    drop = {"DXB-T-12345", "784-1990-1234567-1", "Valid RFID", "Approve Entry"}
    out["children"][0]["children"] = [c for c in out["children"][0]["children"]
                                      if c["props"].get("content") not in drop]
    assert mod._preserves_content(SRC, out) is False


# ── structural guard ────────────────────────────────────────────────────
def test_structurally_valid_accepts_children_root():
    assert mod._structurally_valid(GOOD) is True


def test_structurally_invalid_for_non_dict_or_missing_root():
    assert mod._structurally_valid([1, 2, 3]) is False
    assert mod._structurally_valid({"schemaVersion": "2.0", "id": "x"}) is False


def test_structurally_invalid_for_non_string_type():
    bad = {"children": [{"type": 123, "props": {}}]}
    assert mod._structurally_valid(bad) is False


# ── prompt assembly ─────────────────────────────────────────────────────
def test_content_blocks_text_only_without_screenshot():
    blocks = mod._build_content_blocks(SRC, None, DESCRIPTOR)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert "Available components" in blocks[0]["text"]
    assert "DXB-T-12345" in blocks[0]["text"]  # the schema JSON is embedded


def test_content_blocks_include_image_when_screenshot_present(tmp_path):
    png = tmp_path / "frame.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nFAKEPNGDATA")
    blocks = mod._build_content_blocks(SRC, str(png), DESCRIPTOR)
    assert len(blocks) == 2
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[1]["type"] == "text"


# ── run_figma_schema_refiner: validate-or-fallback contract ──────────────
def test_valid_refine_is_used(monkeypatch):
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps(GOOD)))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    res = _run()
    assert res is not None
    blob = "\n".join(mod._walk_content_strings(res))
    assert "DXB-T-12345" in blob and "{{item.status}}" in blob
    # responsive markers present
    cn = json.dumps(res)
    assert "w-full" in cn and "max-w-[" in cn and "flex-wrap" in cn


def test_unparseable_output_falls_back(monkeypatch):
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm("not json at all"))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is None


def test_structurally_invalid_output_falls_back(monkeypatch):
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps({"schemaVersion": "2.0", "id": "x"})))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is None


def test_content_loss_falls_back(monkeypatch):
    lossy = json.loads(json.dumps(GOOD))
    lossy["children"][0]["children"] = [c for c in lossy["children"][0]["children"]
                                        if c["props"].get("content") != "{{item.status}}"]
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps(lossy)))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is None


def test_zod_validation_failure_falls_back(monkeypatch):
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps(GOOD)))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: "FAIL: bad node")
    assert _run() is None


def _lossy():
    """A 'refined' output that drops the {{item.status}} binding (recoverable)."""
    out = json.loads(json.dumps(GOOD))
    out["children"][0]["children"] = [c for c in out["children"][0]["children"]
                                      if c["props"].get("content") != "{{item.status}}"]
    return out


def _seq_mock(values):
    """LLM mock that returns each value in turn (last repeats), recording the
    content blocks it was called with."""
    state = {"n": 0, "calls": []}

    async def _fake(system, blocks, timeout_s, model):
        state["calls"].append(blocks)
        v = values[min(state["n"], len(values) - 1)]
        state["n"] += 1
        if isinstance(v, Exception):
            raise v
        return v

    return _fake, state


# ── retry-on-content-loss (option A) ─────────────────────────────────────
def test_retries_on_content_loss_then_succeeds(monkeypatch):
    fake, state = _seq_mock([json.dumps(_lossy()), json.dumps(GOOD)])
    monkeypatch.setattr(mod, "_call_refiner_llm", fake)
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    res = _run()
    assert res is not None
    assert state["n"] == 2  # retried once, then succeeded
    assert "{{item.status}}" in "\n".join(mod._walk_content_strings(res))


def test_retry_feedback_lists_the_missing_token(monkeypatch):
    fake, state = _seq_mock([json.dumps(_lossy()), json.dumps(GOOD)])
    monkeypatch.setattr(mod, "_call_refiner_llm", fake)
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    _run()
    # the 2nd call must carry a corrective feedback block naming the dropped binding
    second_call_blocks = state["calls"][1]
    feedback_text = " ".join(b.get("text", "") for b in second_call_blocks if b["type"] == "text")
    assert "{{item.status}}" in feedback_text
    assert "DROPPED" in feedback_text or "missing" in feedback_text.lower()


def test_all_attempts_exhausted_falls_back(monkeypatch):
    fake, state = _seq_mock([json.dumps(_lossy())])  # always lossy
    monkeypatch.setattr(mod, "_call_refiner_llm", fake)
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    res = asyncio.run(mod.run_figma_schema_refiner(SRC, None, DESCRIPTOR, max_attempts=3))
    assert res is None
    assert state["n"] == 3  # tried the full budget


def test_success_first_attempt_is_single_call(monkeypatch):
    fake, state = _seq_mock([json.dumps(GOOD)])
    monkeypatch.setattr(mod, "_call_refiner_llm", fake)
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is not None
    assert state["n"] == 1  # no wasted retry


def test_api_error_is_not_retried(monkeypatch):
    fake, state = _seq_mock([RuntimeError("boom"), json.dumps(GOOD)])
    monkeypatch.setattr(mod, "_call_refiner_llm", fake)
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is None
    assert state["n"] == 1  # API error → immediate fallback, no retry


def test_validator_toolchain_noise_is_advisory(monkeypatch):
    """A non-FAIL validator error (module resolution / pnpm warning) is a
    toolchain issue, not a schema rejection — the refine is still accepted."""
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps(GOOD)))
    monkeypatch.setattr(mod, "_validate_schema_json",
                        lambda d: "ERR_MODULE_NOT_FOUND: cannot find .../dist/tokens")
    assert _run() is not None


def test_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(asyncio.TimeoutError()))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    assert _run() is None


def test_real_deterministic_fixture_content_round_trips(monkeypatch):
    """Using the real Gate Control deterministic schema as input, a faithful
    echo (same content, responsive wrapper) passes the guards."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "gate_control_deterministic.json"
    src = json.loads(fixture.read_text())
    # Build a 'responsive' output by wrapping the real children and adding markers.
    out = {
        "schemaVersion": src.get("schemaVersion", "2.0"),
        "id": src.get("id", "gate"),
        "dataSources": src.get("dataSources", []),
        "children": [{"type": "Card", "props": {"className": "w-full max-w-[1271px] mx-auto flex flex-wrap"},
                      "children": src.get("children", [])}],
    }
    monkeypatch.setattr(mod, "_call_refiner_llm", _mock_llm(json.dumps(out)))
    monkeypatch.setattr(mod, "_validate_schema_json", lambda d: None)
    res = _run(src=src)
    assert res is not None  # content preserved (it's a superset wrap)
