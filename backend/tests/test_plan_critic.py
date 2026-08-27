"""Plan-critic parser + normaliser tests. Cover the shapes an
LLM actually returns (fenced JSON, prose-wrapped JSON, malformed
JSON, over-cap gap lists, missing fields, contradictory verdicts)."""
from __future__ import annotations

import asyncio
import json

import pytest

from agents.plan_critic import (
    _normalise,
    _parse_reply,
    critique_plan,
)
from services.plan_critic_prompt import (
    build_actor_retry_prompt,
    build_critic_prompt,
)


# =========================================================================
# Prompt composition
# =========================================================================

_MIN_BRIEF = "Build me a to-do list app."
_MIN_PLAN = {
    "moduleName": "Todos",
    "dataModels": [{"name": "Todo", "fields": []}],
    "pages": [],
    "workflows": [],
}


def test_critic_prompt_carries_brief_and_plan():
    text = build_critic_prompt(user_brief=_MIN_BRIEF, plan=_MIN_PLAN)
    assert "Build me a to-do list app." in text
    assert '"moduleName": "Todos"' in text


def test_critic_prompt_appends_deterministic_violations_when_present():
    text = build_critic_prompt(
        user_brief=_MIN_BRIEF, plan=_MIN_PLAN,
        deterministic_violations=[{"rule": "example", "message": "x"}],
    )
    assert "DETERMINISTIC VALIDATOR OUTPUT" in text
    assert '"rule": "example"' in text


def test_critic_prompt_omits_deterministic_section_when_none():
    text = build_critic_prompt(user_brief=_MIN_BRIEF, plan=_MIN_PLAN,
                                deterministic_violations=[])
    assert "DETERMINISTIC VALIDATOR OUTPUT" not in text


def test_critic_prompt_carries_prior_gaps_on_turn_2():
    text = build_critic_prompt(
        user_brief=_MIN_BRIEF, plan=_MIN_PLAN,
        prior_critic_gaps=[{"suggestion": "add X"}],
    )
    assert "YOUR PRIOR CRITIC GAPS" in text
    assert '"suggestion": "add X"' in text


def test_critic_prompt_contains_five_discipline_layers():
    text = build_critic_prompt(user_brief=_MIN_BRIEF, plan=_MIN_PLAN)
    # Adversarial framing (rule 1)
    assert "OPPOSITE" in text
    # Scope discipline (rule 2)
    assert "USER'S ORIGINAL BRIEF implies" in text or "does NOT imply" in text.upper() or "future_considerations" in text
    # Hard caps (rule 3)
    assert "Max 3" in text and 'blocker' in text
    # Evidence requirement (rule 4)
    assert "cite evidence" in text.lower() or "MUST cite evidence" in text
    # Two lenses (rule 5)
    assert "BUSINESS lens" in text and "ARCHITECTURE lens" in text


def test_critic_prompt_contains_three_enumeration_passes():
    text = build_critic_prompt(user_brief=_MIN_BRIEF, plan=_MIN_PLAN)
    assert "PASS 1 — Entity coverage" in text
    assert "PASS 2 — Workflow reachability" in text
    assert "PASS 3 — Actor journey completeness" in text
    # Examples are clearly labelled as illustrative.
    assert "ILLUSTRATIVE EXAMPLE" in text


def test_actor_retry_prompt_preserves_original_and_lists_gaps():
    text = build_actor_retry_prompt(
        original_brief=_MIN_BRIEF, prior_plan=_MIN_PLAN,
        critic_gaps=[
            {"severity": "blocker", "lens": "architecture",
             "suggestion": "Add PaymentRecord entity.",
             "evidence": "Invoice cannot represent partial payments."},
        ],
    )
    assert _MIN_BRIEF in text
    assert "PaymentRecord" in text
    assert "Invoice cannot represent" in text
    assert "preserve" in text.lower()


def test_actor_retry_returns_original_brief_when_no_gaps():
    text = build_actor_retry_prompt(original_brief=_MIN_BRIEF,
                                     prior_plan=_MIN_PLAN, critic_gaps=[])
    assert text == _MIN_BRIEF


def test_actor_retry_carries_detection_phrases_the_planner_looks_for():
    """The planner's REVISE MODE section in _ONESHOT_SYSTEM_PROMPT
    activates when it sees TWO exact phrases in the user message:
    "GAPS TO FIX:" and "Prior plan (for reference — apply the gaps
    ABOVE to this):". If build_actor_retry_prompt ever drifts from
    these phrases, revise mode silently stops firing and the planner
    treats retries as authoring — losing the "preserve what wasn't
    flagged" instruction and dramatically increasing regression rate.

    Both sides must move together. This test is the interlock."""
    text = build_actor_retry_prompt(
        original_brief=_MIN_BRIEF, prior_plan=_MIN_PLAN,
        critic_gaps=[{"severity": "blocker", "lens": "architecture",
                       "suggestion": "add X", "evidence": "Y is broken"}],
    )
    assert "GAPS TO FIX:" in text, (
        "planner detects revise mode by literal 'GAPS TO FIX:' — "
        "if you rename this here, update _ONESHOT_SYSTEM_PROMPT to match"
    )
    assert "Prior plan (for reference — apply the gaps ABOVE to this):" in text, (
        "planner detects revise mode by the literal 'Prior plan (for reference'"
        " — if you rename this here, update _ONESHOT_SYSTEM_PROMPT to match"
    )


def test_planner_oneshot_system_prompt_contains_revise_mode_section():
    """The planner's system prompt must have REVISE MODE wired in —
    without this, retries fall through as authoring calls and the
    Actor-Critic loop loses its core value proposition."""
    from agents.planner import _ONESHOT_SYSTEM_PROMPT
    assert "REVISE MODE" in _ONESHOT_SYSTEM_PROMPT
    # Detection phrases the planner uses to flip into revise mode:
    assert "GAPS TO FIX:" in _ONESHOT_SYSTEM_PROMPT
    assert "Prior plan (for reference — apply the gaps ABOVE to this):" in _ONESHOT_SYSTEM_PROMPT
    # Load-bearing preserve instruction:
    assert "PRESERVE EVERYTHING ELSE" in _ONESHOT_SYSTEM_PROMPT


# =========================================================================
# Reply parsing — tolerant of common LLM output shapes
# =========================================================================

def test_parse_straight_json():
    out = _parse_reply('{"verdict": "approve"}')
    assert out == {"verdict": "approve"}


def test_parse_fenced_json():
    out = _parse_reply('```json\n{"verdict": "approve"}\n```')
    assert out == {"verdict": "approve"}


def test_parse_json_with_prose_prefix():
    out = _parse_reply(
        "Here's my critique of the plan:\n\n"
        '{"verdict": "revise", "gaps": []}'
    )
    assert out == {"verdict": "revise", "gaps": []}


def test_parse_returns_none_for_empty_or_garbage():
    assert _parse_reply("") is None
    assert _parse_reply(None) is None  # type: ignore[arg-type]
    assert _parse_reply("this has no braces at all") is None
    # Malformed JSON
    assert _parse_reply('{"verdict": broken}') is None


def test_parse_finds_object_in_middle_of_wrapping():
    out = _parse_reply(
        'Sure! {"verdict": "reject", "gaps": []} that\'s my read.'
    )
    assert out == {"verdict": "reject", "gaps": []}


# =========================================================================
# Normalisation — verdict, scores, gaps, caps, evidence gate
# =========================================================================

def test_normalise_fills_defaults_when_fields_missing():
    out = _normalise({})
    assert out["verdict"] == "revise"
    assert out["scores"] == {k: 5 for k in
        ("entities", "relationships", "workflows",
         "user_journeys", "data_integrity")}
    assert out["gaps"] == []
    assert out["inferred_confidence"] == 0.5


def test_normalise_clamps_scores_to_0_10():
    out = _normalise({"scores": {"entities": 42, "relationships": -3,
                                   "workflows": 7.7}})
    assert out["scores"]["entities"] == 10
    assert out["scores"]["relationships"] == 0
    assert out["scores"]["workflows"] == 7


def test_normalise_rejects_unknown_verdict_defaults_to_revise():
    assert _normalise({"verdict": "yeah probably"})["verdict"] == "revise"
    assert _normalise({"verdict": "APPROVE"})["verdict"] == "approve"


def test_normalise_drops_gaps_without_evidence():
    """Rule 4 — an LLM sometimes emits gaps with empty evidence.
    Enforce silently rather than surface bogus gaps."""
    out = _normalise({"gaps": [
        {"severity": "blocker", "suggestion": "add X"},  # no evidence — drop
        {"severity": "blocker", "suggestion": "add Y", "evidence": "z"},  # keep
    ]})
    assert len(out["gaps"]) == 1
    assert out["gaps"][0]["suggestion"] == "add Y"


def test_normalise_enforces_hard_caps_by_severity():
    """Rule 3 — over-cap emissions get trimmed by severity + confidence."""
    raw_gaps = [
        {"severity": "blocker", "suggestion": f"b{i}", "evidence": "e",
         "confidence": 0.9 - i * 0.1} for i in range(5)
    ]
    raw_gaps += [
        {"severity": "important", "suggestion": f"i{i}", "evidence": "e",
         "confidence": 0.8 - i * 0.05} for i in range(8)
    ]
    raw_gaps += [
        {"severity": "nice", "suggestion": f"n{i}", "evidence": "e",
         "confidence": 0.5} for i in range(6)
    ]
    out = _normalise({"gaps": raw_gaps})
    assert sum(1 for g in out["gaps"] if g["severity"] == "blocker") == 3
    assert sum(1 for g in out["gaps"] if g["severity"] == "important") == 5
    assert sum(1 for g in out["gaps"] if g["severity"] == "nice") == 3
    # Highest-confidence blockers are the ones kept.
    kept_blocker_suggestions = [g["suggestion"] for g in out["gaps"]
                                 if g["severity"] == "blocker"]
    assert kept_blocker_suggestions == ["b0", "b1", "b2"]


def test_normalise_overrides_approve_when_blockers_exist():
    """LLM sometimes says verdict=approve while ALSO listing blockers.
    Prefer the safer read — revise."""
    out = _normalise({
        "verdict": "approve",
        "gaps": [{"severity": "blocker", "suggestion": "add X",
                  "evidence": "why"}],
    })
    assert out["verdict"] == "revise"


def test_normalise_drops_unknown_severity_gaps():
    out = _normalise({"gaps": [
        {"severity": "critical", "suggestion": "x", "evidence": "y"},
    ]})
    assert out["gaps"] == []


def test_normalise_defaults_lens_and_dimension_when_missing():
    out = _normalise({"gaps": [
        {"severity": "important", "suggestion": "x", "evidence": "y"},
    ]})
    assert out["gaps"][0]["lens"] == "business"
    assert out["gaps"][0]["dimension"] == "entities"


def test_normalise_caps_future_considerations_and_kept_at_3():
    out = _normalise({
        "future_considerations": [f"f{i}" for i in range(10)],
        "kept": [f"k{i}" for i in range(10)],
    })
    assert len(out["future_considerations"]) == 3
    assert len(out["kept"]) == 3


# =========================================================================
# End-to-end — critique_plan with injected LLM boundary
# =========================================================================

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_critique_plan_approves_when_reply_is_approve():
    reply = json.dumps({
        "inferred_domain": "todos", "inferred_confidence": 0.9,
        "scores": {"entities": 8, "relationships": 8, "workflows": 8,
                    "user_journeys": 8, "data_integrity": 8},
        "verdict": "approve",
        "gaps": [], "future_considerations": [],
        "kept": ["clean CRUD"],
    })

    async def fake_query(sys_prompt, user_msg):
        return reply

    out = _run(critique_plan(
        plan=_MIN_PLAN, user_brief=_MIN_BRIEF, query_fn=fake_query,
    ))
    assert out["verdict"] == "approve"
    assert out["inferred_domain"] == "todos"
    assert out["kept"] == ["clean CRUD"]


def test_critique_plan_survives_llm_error():
    async def broken_query(sys_prompt, user_msg):
        raise RuntimeError("SDK exploded")

    out = _run(critique_plan(
        plan=_MIN_PLAN, user_brief=_MIN_BRIEF, query_fn=broken_query,
    ))
    assert out["verdict"] == "approve"
    assert "critic-skipped" in out["kept"][0]


def test_critique_plan_survives_unparseable_reply():
    async def prose_query(sys_prompt, user_msg):
        return "I don't feel like emitting JSON today."

    out = _run(critique_plan(
        plan=_MIN_PLAN, user_brief=_MIN_BRIEF, query_fn=prose_query,
    ))
    assert out["verdict"] == "approve"
    assert "critic-skipped" in out["kept"][0]


def test_critique_plan_returns_revise_with_gaps_from_llm():
    reply = "```json\n" + json.dumps({
        "inferred_domain": "vet clinic", "inferred_confidence": 0.9,
        "scores": {"entities": 6, "relationships": 5, "workflows": 6,
                    "user_journeys": 6, "data_integrity": 4},
        "verdict": "revise",
        "gaps": [
            {"severity": "blocker", "lens": "architecture",
             "dimension": "entities",
             "suggestion": "Add ServiceCatalog entity.",
             "evidence": "InvoiceLineItem references nothing.",
             "confidence": 0.9},
        ],
        "future_considerations": ["Rabies certificate generation"],
        "kept": ["SOAP separation from Appointment"],
    }) + "\n```"

    async def fake_query(sys_prompt, user_msg):
        return reply

    out = _run(critique_plan(
        plan=_MIN_PLAN, user_brief=_MIN_BRIEF, query_fn=fake_query,
    ))
    assert out["verdict"] == "revise"
    assert len(out["gaps"]) == 1
    assert out["gaps"][0]["dimension"] == "entities"
    assert "ServiceCatalog" in out["gaps"][0]["suggestion"]
