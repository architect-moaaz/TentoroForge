"""Tests for services.plan_adjust_intent — LLM intent parser.

The LLM is stubbed to keep tests deterministic + offline. The stub
returns whatever JSON the test wants; the module's job is to route
that into the pure ``plan_adjust`` ops correctly.

Coverage anchors:
  * Happy path — a well-formed reply lands as ops
  * Response cleanup — fenced markdown, prose prefix, junk after JSON
  * Partial failure — one bad op doesn't kill the whole batch
  * Empty message + LLM error → graceful fallback (no crash)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from services.plan_adjust_intent import (
    AdjustResult,
    adjust_plan_via_llm,
    apply_ops,
)


def _fresh_plan() -> dict:
    return {
        "module_name": "test",
        "description": "sample",
        "data_models": [
            {"name": "Member", "fields": [{"name": "id", "type": "uuid"}], "indexes": []},
        ],
        "pages": [
            {"route": "/members", "name": "MembersPage", "entity": "Member",
             "archetype": "list", "features": [], "description": "", "actions": []},
        ],
        "workflows": [],
        "actors": [],
        "relations": [],
        "features": [],
    }


def _stub(reply: str):
    async def q(system, user):
        return reply
    return q


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------------- #
# adjust_plan_via_llm — happy paths                                          #
# ------------------------------------------------------------------------- #

class TestHappyPath:
    def test_add_entity_and_page(self):
        reply = json.dumps({
            "ops": [
                {"op": "add_entity", "args": {"name": "Booking"}},
                {"op": "add_page", "args": {
                    "name": "BookingsPage", "entity": "Booking", "archetype": "list",
                }},
            ],
            "narrative": "Added Booking + list page.",
        })
        p = _fresh_plan()
        r = _run(adjust_plan_via_llm(p, "add bookings", query_fn=_stub(reply)))
        assert r.error is None
        assert any(e["name"] == "Booking" for e in r.new_plan["data_models"])
        assert any(pg["route"] == "/bookings" for pg in r.new_plan["pages"])
        assert r.diff.entities_added == ["Booking"]
        assert r.diff.pages_added == ["/bookings"]
        assert "Booking" in r.narrative

    def test_toggle_feature(self):
        reply = json.dumps({
            "ops": [{"op": "toggle_feature", "args": {"feature": "commerce", "on": True}}],
            "narrative": "Turned on commerce.",
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "add cart",
                                     query_fn=_stub(reply)))
        assert r.error is None
        assert "commerce" in r.new_plan["features"]
        assert r.diff.features_added == ["commerce"]

    def test_multiple_ops_in_one_turn(self):
        reply = json.dumps({
            "ops": [
                {"op": "add_actor", "args": {"name": "Reviewer", "role": "reviewer"}},
                {"op": "add_workflow", "args": {
                    "name": "Review", "trigger": "POST /api/review",
                }},
            ],
            "narrative": "Added Reviewer + Review workflow.",
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "let reviewers review",
                                     query_fn=_stub(reply)))
        assert r.error is None
        assert any(a["name"] == "Reviewer" for a in r.new_plan["actors"])
        assert any(w["name"] == "Review" for w in r.new_plan["workflows"])
        assert len(r.applied_ops) == 2


# ------------------------------------------------------------------------- #
# Response cleanup                                                           #
# ------------------------------------------------------------------------- #

class TestResponseParsing:
    def test_strips_json_markdown_fence(self):
        reply = "```json\n" + json.dumps({
            "ops": [{"op": "add_entity", "args": {"name": "X"}}],
            "narrative": "ok",
        }) + "\n```"
        r = _run(adjust_plan_via_llm(_fresh_plan(), "add X", query_fn=_stub(reply)))
        assert r.error is None
        assert any(e["name"] == "X" for e in r.new_plan["data_models"])

    def test_strips_plain_code_fence(self):
        reply = "```\n" + json.dumps({
            "ops": [{"op": "add_entity", "args": {"name": "Y"}}],
        }) + "\n```"
        r = _run(adjust_plan_via_llm(_fresh_plan(), "add Y", query_fn=_stub(reply)))
        assert r.error is None
        assert any(e["name"] == "Y" for e in r.new_plan["data_models"])

    def test_extracts_json_from_prose_prefix(self):
        # Some models occasionally emit "Sure, here's the JSON: {...}"
        reply = "Sure, here's the JSON:\n" + json.dumps({
            "ops": [{"op": "add_entity", "args": {"name": "Z"}}],
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "add Z", query_fn=_stub(reply)))
        assert r.error is None
        assert any(e["name"] == "Z" for e in r.new_plan["data_models"])

    def test_empty_reply_returns_error(self):
        r = _run(adjust_plan_via_llm(_fresh_plan(), "something",
                                     query_fn=_stub("")))
        assert r.error == "empty_response"
        assert r.new_plan == _fresh_plan()  # plan preserved

    def test_no_json_in_reply_returns_error(self):
        r = _run(adjust_plan_via_llm(_fresh_plan(), "something",
                                     query_fn=_stub("I don't understand.")))
        assert r.error == "no_json_in_response"


# ------------------------------------------------------------------------- #
# Partial failure                                                            #
# ------------------------------------------------------------------------- #

class TestPartialFailure:
    def test_one_bad_op_doesnt_kill_batch(self):
        reply = json.dumps({
            "ops": [
                {"op": "add_entity", "args": {"name": "Good"}},
                {"op": "add_page", "args": {
                    "name": "OrphanPage",
                    "entity": "DoesNotExist",  # will trigger PlanAdjustError
                    "archetype": "list",
                }},
                {"op": "add_workflow", "args": {"name": "Also", "trigger": "POST /x"}},
            ],
            "narrative": "Two ops good, one bad.",
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "batch",
                                     query_fn=_stub(reply)))
        assert r.error is None
        # Good ops landed
        assert any(e["name"] == "Good" for e in r.new_plan["data_models"])
        assert any(w["name"] == "Also" for w in r.new_plan["workflows"])
        # Warning captured for the bad one
        assert any("DoesNotExist" in w for w in r.warnings)

    def test_unknown_op_captured_as_warning(self):
        reply = json.dumps({
            "ops": [{"op": "teleport_entity", "args": {"name": "X"}}],
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "…",
                                     query_fn=_stub(reply)))
        assert r.error is None
        assert any("teleport_entity" in w for w in r.warnings)

    def test_malformed_op_entry_skipped(self):
        reply = json.dumps({
            "ops": ["not-a-dict"],
        })
        r = _run(adjust_plan_via_llm(_fresh_plan(), "…", query_fn=_stub(reply)))
        assert r.error is None
        assert any("malformed" in w.lower() for w in r.warnings)


# ------------------------------------------------------------------------- #
# Empty message + LLM error                                                  #
# ------------------------------------------------------------------------- #

class TestGracefulFallback:
    def test_empty_user_message_no_op(self):
        r = _run(adjust_plan_via_llm(_fresh_plan(), "  ", query_fn=_stub("{}")))
        assert r.error == "empty_message"
        assert r.new_plan == _fresh_plan()

    def test_llm_exception_becomes_error_field(self):
        async def raiser(system, user):
            raise RuntimeError("boom")
        r = _run(adjust_plan_via_llm(_fresh_plan(), "hi", query_fn=raiser))
        assert r.error is not None
        assert "RuntimeError" in r.error
        assert r.new_plan == _fresh_plan()


# ------------------------------------------------------------------------- #
# apply_ops directly (undo/replay path)                                      #
# ------------------------------------------------------------------------- #

class TestApplyOpsDirect:
    def test_apply_ops_deterministic_no_llm(self):
        p = _fresh_plan()
        r = apply_ops(p, [
            {"op": "add_entity", "args": {"name": "Booking"}},
            {"op": "add_page", "args": {
                "name": "BookingsPage", "entity": "Booking", "archetype": "list",
            }},
        ], narrative="replay")
        assert r.error is None
        assert any(e["name"] == "Booking" for e in r.new_plan["data_models"])
        assert r.narrative == "replay"

    def test_default_narrative_when_none_given(self):
        r = apply_ops(_fresh_plan(), [
            {"op": "add_entity", "args": {"name": "Booking"}},
        ])
        assert "Booking" in r.narrative


# ------------------------------------------------------------------------- #
# Multi-turn conversation (uses prior_turns)                                 #
# ------------------------------------------------------------------------- #

class TestMultiTurn:
    def test_prior_turns_passed_through_in_prompt(self):
        seen: dict = {}
        async def q(system, user):
            seen["user"] = user
            return json.dumps({"ops": [], "narrative": "noop"})
        _run(adjust_plan_via_llm(
            _fresh_plan(), "and also add cart",
            query_fn=q,
            prior_turns=[
                {"role": "user", "content": "add Booking entity"},
                {"role": "assistant", "content": "Added Booking."},
            ],
        ))
        assert "add Booking entity" in seen["user"]
        assert "Added Booking." in seen["user"]
