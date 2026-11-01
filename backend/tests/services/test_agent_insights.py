"""The cost and quality numbers for an agent in the connected development app, the platform's side (services/agent_insights.py).

What is pinned: the price maths (by model-name prefix, an unlisted model is never priced or guessed, FORGE_MODEL_PRICES overrides);
every tip appears when its rule is met and stays quiet when it is not, and none blames a person; whatever the app sends is tamed
(wrong types, huge lists, control characters, impossible counts) and never crashes; and every way the app can be unreachable comes
back as one plain sentence: not paired, tunnel down, nothing behind it, wrong key, too old to record insights, an address that
is not on this computer.
"""
from __future__ import annotations

import base64
import copy
import json

import httpx
import pytest

from services import agent_debug, agent_insights, agent_tunnel
from services.agent_debug import DebugError
from services.agent_insights import enrich, fetch, price_for

PID = "11111111-2222-3333-4444-555555555555"
SECRET = "s" * 43
REAL_CLIENT = httpx.AsyncClient


def good() -> dict:
    """What a healthy app sends: 40 turns over 12 chats, mostly Sonnet."""
    return {
        "generatedAt": "2026-10-22T10:00:00.000Z", "days": 7, "agentId": "support", "since": "2026-10-15T10:00:00.000Z",
        "firstTurnAt": "2026-10-16T08:00:00.000Z",
        "totals": {"conversations": 12, "turns": 40, "users": 5, "inputTokens": 400_000, "outputTokens": 100_000, "toolCalls": 30,
                   "toolErrors": 1, "blocked": 1, "errors": 1, "handedOff": 4, "rated": 10, "up": 8, "down": 2},
        "latencyMs": {"p50": 2100, "p95": 9000, "avg": 3000},
        "byDay": [{"day": "2026-10-20", "turns": 10, "inputTokens": 100_000, "outputTokens": 25_000, "errors": 0, "up": 2, "down": 0},
                  {"day": "2026-10-21", "turns": 30, "inputTokens": 300_000, "outputTokens": 75_000, "errors": 1, "up": 6, "down": 2}],
        "byModel": [{"model": "claude-sonnet-4-5-20250929", "turns": 40, "inputTokens": 400_000, "outputTokens": 100_000}],
        "tools": [{"name": "lookup_order", "calls": 30, "errors": 1, "avgMs": 420.4}],
        "problems": [{"conversationId": "c1", "at": "2026-10-21T09:00:00Z", "message": "Where is my order?", "reason": "tool_failed", "detail": "timeout"},
                     {"conversationId": "c2", "at": "2026-10-21T11:00:00Z", "message": "Hi", "reason": "thumbs_down", "detail": ""}],
        "handoffs": {"total": 4, "open": 1, "claimed": 1, "resolved": 2, "avgResolveMinutes": 12.5},
    }


def tip_ids(out) -> list[str]:
    return [t["id"] for t in out["tips"]]


# ── prices ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model,expected", [
    ("claude-sonnet-4-5-20250929", (3, 15)), ("claude-sonnet-5", (3, 15)),
    ("claude-haiku-4-5", (1, 5)), ("claude-haiku-5-0", (1, 5)),
    ("claude-opus-4-5-20251101", (5, 25)), ("claude-opus-5", (5, 25)),
    ("claude-opus-4-1-20250805", (15, 75)), ("claude-opus-4-0", (15, 75)), ("claude-opus-4-20250514", (15, 75)), ("claude-opus-4", (15, 75)),
])
def test_known_models_are_priced_by_the_start_of_their_name(model, expected):
    assert price_for(model) == expected


@pytest.mark.parametrize("model", ["gpt-4o", "gemini-2.5-pro", "", "claude-opus-4-6", "claude-3-5-sonnet-20241022", "my-own-model"])
def test_a_model_not_in_the_table_is_never_priced(model):
    assert price_for(model) is None


def test_the_money_is_tokens_times_the_price_per_million():
    out = enrich(good(), 7)
    # 400k in at $3/M = 1.20, 100k out at $15/M = 1.50
    assert out["cost"]["estimatedUsd"] == pytest.approx(2.70)
    assert out["cost"]["perChatUsd"] == pytest.approx(0.225) and out["cost"]["perTurnUsd"] == pytest.approx(0.0675)
    m = out["cost"]["byModel"][0]
    assert m["priced"] is True and m["usd"] == pytest.approx(2.70)
    assert out["cost"]["unpricedModels"] == [] and out["cost"]["partial"] is False
    assert out["cost"]["note"] == "Estimated from list prices; your bill may differ."
    assert [d["usd"] for d in out["cost"]["byDay"]] == [pytest.approx(0.675), pytest.approx(2.025)]


def test_an_unpriced_model_shows_its_tokens_and_is_left_out_of_the_total():
    raw = good()
    raw["byModel"].append({"model": "mystery-model-1", "turns": 5, "inputTokens": 1_000_000, "outputTokens": 1_000_000})
    out = enrich(raw, 7)
    assert out["cost"]["estimatedUsd"] == pytest.approx(2.70), "nothing is added for the model with no price"
    mystery = next(m for m in out["cost"]["byModel"] if m["model"] == "mystery-model-1")
    assert mystery["priced"] is False and mystery["usd"] is None and mystery["inputTokens"] == 1_000_000
    assert out["cost"]["unpricedModels"] == ["mystery-model-1"] and out["cost"]["partial"] is True
    assert all(d["usd"] is None for d in out["cost"]["byDay"]), "a day's cost cannot be told when a model has no price"
    assert "unpriced-models" in tip_ids(out)


def test_a_turn_that_never_reached_a_model_is_not_a_model_to_price():
    # Found in a real run: a message refused for being too long never asked the AI, but the app counted its turn under a model
    # called "unknown" with no tokens, and the dashboard then asked for that model's price.
    raw = good()
    raw["byModel"].append({"model": "unknown", "turns": 1, "inputTokens": 0, "outputTokens": 0})
    raw["byModel"].append({"model": "", "turns": 2, "inputTokens": 0, "outputTokens": 0})
    out = enrich(raw, 7)
    assert [m["model"] for m in out["cost"]["byModel"]] == [m["model"] for m in good()["byModel"]]
    assert out["cost"]["unpricedModels"] == [] and out["cost"]["partial"] is False
    assert "unpriced-models" not in tip_ids(out)
    assert [m["model"] for m in out["byModel"]] == [m["model"] for m in good()["byModel"]]


def test_when_no_model_has_a_price_the_cost_is_unknown_not_zero():
    raw = good()
    raw["byModel"] = [{"model": "gpt-4o", "turns": 40, "inputTokens": 400_000, "outputTokens": 100_000}]
    out = enrich(raw, 7)
    assert out["cost"]["estimatedUsd"] is None and out["cost"]["perChatUsd"] is None and out["cost"]["perTurnUsd"] is None


def test_no_tokens_at_all_costs_nothing():
    out = enrich({"totals": {}}, 7)
    assert out["cost"]["estimatedUsd"] == 0.0 and out["cost"]["perChatUsd"] is None


def test_the_environment_can_add_and_replace_prices(monkeypatch):
    monkeypatch.setenv("FORGE_MODEL_PRICES", json.dumps({"gpt-4o": [2.5, 10], "claude-sonnet-": [6, 30]}))
    assert price_for("gpt-4o-mini") == (2.5, 10.0)
    assert price_for("claude-sonnet-4-5") == (6.0, 30.0), "an override replaces the built-in entry"
    assert enrich(good(), 7)["cost"]["estimatedUsd"] == pytest.approx(5.40)


def test_a_broken_price_override_is_ignored_not_an_error(monkeypatch):
    for bad in ("not json", "[1,2]", json.dumps({"x": [1]}), json.dumps({"x": ["a", 2]}), json.dumps({"x": [-1, 2]}), json.dumps({"x": [True, 2]})):
        monkeypatch.setenv("FORGE_MODEL_PRICES", bad)
        assert price_for("claude-sonnet-4-5") == (3.0, 15.0) and price_for("x") is None


def test_the_longest_matching_name_wins():
    assert price_for("claude-opus-4-5-x", {"claude-opus-4": (1, 1), "claude-opus-4-5": (2, 2)}) == (2, 2)


# ── quality ─────────────────────────────────────────────────────────────────

def test_each_rate_comes_with_its_counts():
    q = enrich(good(), 7)["quality"]
    assert q["answeredWithoutPerson"] == {"pct": 90.0, "count": 36, "of": 40}
    assert q["thumbsUp"] == {"pct": 80.0, "count": 8, "of": 10}
    assert q["errors"] == {"pct": 2.5, "count": 1, "of": 40} and q["blocked"] == {"pct": 2.5, "count": 1, "of": 40}, "errors and blocked are kept apart"
    assert q["toolFailures"] == {"pct": 3.3, "count": 1, "of": 30}
    assert q["speed"] == {"p50Ms": 2100, "p95Ms": 9000, "avgMs": 3000, "slow": False}


def test_nobody_rating_is_null_not_zero_and_no_tool_calls_is_null():
    raw = good()
    raw["totals"].update(rated=0, up=0, down=0, toolCalls=0, toolErrors=0)
    q = enrich(raw, 7)["quality"]
    assert q["thumbsUp"]["pct"] is None and q["thumbsUp"]["of"] == 0
    assert q["toolFailures"]["pct"] is None


def test_slow_is_flagged_only_when_the_slowest_one_in_twenty_is_over_thirty_seconds():
    raw = good()
    raw["latencyMs"]["p95"] = 30_000
    assert enrich(raw, 7)["quality"]["speed"]["slow"] is False
    raw["latencyMs"]["p95"] = 30_001
    assert enrich(raw, 7)["quality"]["speed"]["slow"] is True


# ── tips ────────────────────────────────────────────────────────────────────

def test_a_healthy_agent_gets_no_tips():
    assert enrich(good(), 7)["tips"] == []


def test_no_chats_yet_says_so_and_only_that():
    out = enrich({"totals": {"turns": 0}}, 7)
    assert [t["id"] for t in out["tips"]] == ["no-data"] and "last 7 days" in out["tips"][0]["text"] and out["tips"][0]["severity"] == "info"


def test_a_tool_that_fails_more_than_a_fifth_of_its_calls_is_named():
    raw = good()
    raw["tools"] = [{"name": "refund", "calls": 10, "errors": 3, "avgMs": 10}]
    out = enrich(raw, 7)
    tip = next(t for t in out["tips"] if t["id"] == "tool-failing:refund")
    assert tip["severity"] == "warn"
    assert tip["text"] == "The tool refund failed 3 of 10 times: look at its description or the app route it calls."


@pytest.mark.parametrize("calls,errors", [(10, 2), (4, 4), (5, 1), (100, 20)])
def test_a_tool_tip_stays_quiet_at_exactly_a_fifth_or_with_fewer_than_five_calls(calls, errors):
    raw = good()
    raw["tools"] = [{"name": "refund", "calls": calls, "errors": errors, "avgMs": 10}]
    assert not any(i.startswith("tool-failing") for i in tip_ids(enrich(raw, 7)))


def test_many_thumbs_down_is_a_tip_and_a_few_in_a_big_crowd_is_not():
    raw = good()
    raw["totals"].update(rated=10, up=6, down=4)
    assert "thumbs-down" in tip_ids(enrich(raw, 7))
    raw["totals"].update(rated=40, up=37, down=3)  # 7.5%
    assert "thumbs-down" not in tip_ids(enrich(raw, 7))
    raw["totals"].update(rated=4, up=2, down=2)  # 50% but only two
    assert "thumbs-down" not in tip_ids(enrich(raw, 7))


def test_a_high_handoff_rate_needs_ten_turns_and_more_than_thirty_percent():
    raw = good()
    raw["totals"]["handedOff"] = 13  # 32.5% of 40
    assert "handoff-rate" in tip_ids(enrich(raw, 7))
    raw["totals"]["handedOff"] = 12  # exactly 30%
    assert "handoff-rate" not in tip_ids(enrich(raw, 7))
    raw["totals"].update(turns=9, handedOff=9, conversations=3)
    assert "handoff-rate" not in tip_ids(enrich(raw, 7))


def test_a_slow_slowest_twentieth_is_a_tip():
    raw = good()
    raw["latencyMs"]["p95"] = 45_000
    tip = next(t for t in enrich(raw, 7)["tips"] if t["id"] == "slow")
    assert "45 seconds" in tip["text"] and "p95" not in tip["text"]


def test_input_tokens_far_above_output_say_where_the_cost_goes():
    raw = good()
    raw["totals"].update(inputTokens=1_000_001, outputTokens=100_000)
    tip = next(t for t in enrich(raw, 7)["tips"] if t["id"] == "input-heavy")
    assert "re-reading its instructions and history" in tip["text"] and tip["severity"] == "info"
    raw["totals"].update(inputTokens=1_000_000, outputTokens=100_000)  # exactly ten times
    assert "input-heavy" not in tip_ids(enrich(raw, 7))


def test_errors_and_refusals_are_tips_when_they_are_common():
    raw = good()
    raw["totals"].update(errors=5, blocked=9)
    ids = tip_ids(enrich(raw, 7))
    assert "errors" in ids and "blocked" in ids
    raw["totals"].update(errors=4, blocked=8)
    ids = tip_ids(enrich(raw, 7))
    assert "errors" not in ids and "blocked" not in ids


def test_at_most_five_tips_and_warnings_come_first():
    raw = good()
    raw["totals"].update(errors=20, blocked=20, rated=10, up=2, down=8, handedOff=30, inputTokens=5_000_000)
    raw["latencyMs"]["p95"] = 60_000
    raw["tools"] = [{"name": f"t{i}", "calls": 10, "errors": 9, "avgMs": 1} for i in range(4)]
    raw["byModel"].append({"model": "mystery", "turns": 1, "inputTokens": 1, "outputTokens": 1})
    tips = enrich(raw, 7)["tips"]
    assert len(tips) == agent_insights.MAX_TIPS
    sev = [t["severity"] for t in tips]
    assert sev == sorted(sev, key=lambda s: s != "warn")


def test_no_tip_blames_a_person():
    raw = good()
    raw["totals"].update(errors=20, blocked=20, rated=10, up=2, down=8, handedOff=30, inputTokens=5_000_000)
    raw["latencyMs"]["p95"] = 60_000
    raw["tools"] = [{"name": "x", "calls": 10, "errors": 9, "avgMs": 1}]
    raw["byModel"].append({"model": "mystery", "turns": 1, "inputTokens": 1, "outputTokens": 1})
    text = " ".join(t["text"].lower() for t in enrich(raw, 7)["tips"])
    for word in ("user error", "your fault", "customer's fault", "people are", "stupid", "wrong question", "misuse"):
        assert word not in text


# ── hostile or odd JSON ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [None, [], "text", 5, {}, {"totals": None}, {"totals": []}, {"totals": "x"}])
def test_something_that_is_not_an_insights_answer_is_refused_in_words(raw):
    with pytest.raises(DebugError) as e:
        enrich(raw, 7)
    assert "not one of your apps" in str(e.value)


def test_wrong_types_become_zeros_and_nulls_and_nothing_crashes():
    raw = {"totals": {"turns": "40", "inputTokens": True, "outputTokens": float("nan"), "toolCalls": -5, "up": [1], "rated": {"a": 1},
                      "conversations": 1e30},
           "latencyMs": {"p50": "fast", "p95": float("inf"), "avg": None}, "byDay": "nope", "byModel": {"a": 1}, "tools": 7,
           "problems": [1, "x", None, {"reason": 7, "at": 5, "message": ["a"]}], "handoffs": [], "days": "seven", "agentId": {"x": 1},
           "warning": 5, "since": 12, "unknownKey": {"evil": "<script>"}}
    out = enrich(raw, 30)
    t = out["totals"]
    assert t["turns"] == 0 and t["inputTokens"] == 0 and t["outputTokens"] == 0 and t["toolCalls"] == 0 and t["rated"] == 0
    assert out["latencyMs"] == {"p50": None, "p95": None, "avg": None}
    assert out["byDay"] == [] and out["byModel"] == [] and out["tools"] == [] and out["days"] == 30 and out["agentId"] is None
    assert out["problems"] == [{"conversationId": "", "at": None, "message": "", "reason": "other", "detail": ""}]
    assert out["handoffs"] == {"total": 0, "open": 0, "claimed": 0, "resolved": 0, "avgResolveMinutes": None}
    assert "warning" not in out and out["since"] is None and "unknownKey" not in out
    json.dumps(out)  # and it can be sent as JSON


def test_huge_lists_are_capped_and_long_text_is_cut():
    raw = good()
    raw["tools"] = [{"name": f"t{i}", "calls": 1, "errors": 0, "avgMs": 1} for i in range(500)]
    raw["byDay"] = [{"day": f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}", "turns": 1} for i in range(1000)]
    raw["byModel"] = [{"model": f"m{i}", "turns": 1, "inputTokens": 1, "outputTokens": 1} for i in range(500)]
    raw["problems"] = [{"conversationId": "c", "at": "2026-10-21T09:00:00Z", "message": "x" * 5000, "reason": "error", "detail": "y" * 5000} for _ in range(500)]
    raw["warning"] = "w" * 5000
    out = enrich(raw, 7)
    assert len(out["tools"]) == agent_insights.MAX_TOOLS and len(out["byDay"]) <= agent_insights.MAX_DAYS
    assert len(out["byModel"]) == agent_insights.MAX_MODELS and len(out["problems"]) == agent_insights.MAX_PROBLEMS
    assert len(out["problems"][0]["message"]) <= 300 and len(out["problems"][0]["detail"]) <= 300 and len(out["warning"]) <= 300


def test_control_characters_and_html_are_not_carried_as_markup_and_lines_are_flattened():
    raw = good()
    raw["problems"][0]["message"] = "line one\n\x00line two\x1b[31m <b>hi</b>"
    msg = next(p for p in enrich(raw, 7)["problems"] if p["conversationId"] == "c1")["message"]
    assert "\n" not in msg and "\x00" not in msg and "\x1b" not in msg


def test_impossible_counts_are_pulled_back_to_what_they_can_be():
    raw = good()
    raw["totals"].update(turns=10, errors=999, blocked=999, handedOff=999, toolCalls=5, toolErrors=50, conversations=50, rated=1, up=9, down=9)
    raw["tools"] = [{"name": "t", "calls": 3, "errors": 30, "avgMs": -5}]
    out = enrich(raw, 7)
    t = out["totals"]
    assert t["errors"] == 10 and t["blocked"] == 10 and t["handedOff"] == 10 and t["toolErrors"] == 5 and t["conversations"] == 10
    assert t["rated"] >= t["up"] + t["down"]
    assert out["tools"][0]["errors"] == 3 and out["tools"][0]["avgMs"] == 0
    for r in out["quality"].values():
        if "pct" in r:
            assert r["pct"] is None or 0 <= r["pct"] <= 100


def test_days_are_kept_in_order_and_a_bad_day_is_dropped():
    raw = good()
    raw["byDay"] = [{"day": "2026-10-21", "turns": 2}, {"day": "yesterday", "turns": 9}, {"day": "2026-10-20", "turns": 1}, {"day": 5}]
    assert [d["day"] for d in enrich(raw, 7)["byDay"]] == ["2026-10-20", "2026-10-21"]


def test_problems_come_newest_first_and_an_unknown_reason_is_other():
    out = enrich(good(), 7)
    assert [p["conversationId"] for p in out["problems"]] == ["c2", "c1"]
    raw = good()
    raw["problems"][0]["reason"] = "<img src=x>"
    assert enrich(raw, 7)["problems"][-1]["reason"] == "other"


def test_the_apps_warning_is_passed_on_and_the_same_model_twice_is_added_up():
    raw = good()
    raw["warning"] = "The turns table is missing."
    raw["byModel"].append(copy.deepcopy(raw["byModel"][0]))
    out = enrich(raw, 7)
    assert out["warning"] == "The turns table is missing."
    assert len(out["byModel"]) == 1 and out["byModel"][0]["inputTokens"] == 800_000


# ── asking the app ──────────────────────────────────────────────────────────

def fake_app(monkeypatch, handler):
    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*a, **kw)

    monkeypatch.setattr(agent_debug.httpx, "AsyncClient", factory)


def key(seed: int = 1) -> str:
    return "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([seed]) * 32).decode()


@pytest.fixture()
def tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TUNNEL_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_TUNNEL_PUBLIC_HOST", "13.212.213.53")
    monkeypatch.setenv("FORGE_TUNNEL_HOST", "127.0.0.1")
    (tmp_path / "host_key.pub").write_text(key(9) + " root@tunnel\n", encoding="utf-8")
    agent_tunnel._bad.clear()
    return tmp_path


@pytest.fixture()
def paired(tunnel, monkeypatch):
    agent_tunnel.pair(agent_tunnel.new_pairing(PID)["code"], key(), 3001, SECRET, client_ip="1.2.3.4", label="laptop")
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda port, timeout=1.5: True)


@pytest.mark.asyncio
async def test_through_the_tunnel_the_platforms_address_and_the_connectors_secret_are_used_and_the_answer_is_enriched(paired, monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, dict(req.url.params), req.headers.get("x-forge-debug-secret")))
        return httpx.Response(200, json=good())

    fake_app(monkeypatch, handler)
    out = await fetch(PID, "tunnel", None, 30, "support")
    port = agent_tunnel.get(PID)["port"]
    assert out["ok"] is True and out["insights"]["cost"]["estimatedUsd"] == pytest.approx(2.70)
    assert seen == [("/api/agent/insights", {"days": "30", "agent": "support"}, SECRET)]
    assert agent_tunnel.target_url(PID) == f"http://127.0.0.1:{port}" and SECRET not in json.dumps(out)


@pytest.mark.asyncio
async def test_without_an_agent_none_is_asked_for_and_days_are_kept_between_one_and_ninety(paired, monkeypatch):
    seen = []
    fake_app(monkeypatch, lambda req: (seen.append(dict(req.url.params)), httpx.Response(200, json=good()))[1])
    await fetch(PID, "Tunnel", None, 7, "  ")
    await fetch(PID, "tunnel", None, 9999, None)
    await fetch(PID, "tunnel", None, -3, None)
    assert seen == [{"days": "7"}, {"days": "90"}, {"days": "1"}]


@pytest.mark.asyncio
async def test_a_typed_localhost_address_is_sent_the_projects_own_secret(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url).split("?")[0], req.headers.get("x-forge-debug-secret")))
        return httpx.Response(200, json=good())

    fake_app(monkeypatch, handler)
    out = await fetch(PID, "http://localhost:3000", "mine", 7, None)
    assert out["ok"] is True and seen == [("http://localhost:3000/api/agent/insights", "mine")]


@pytest.mark.asyncio
async def test_an_address_that_is_not_this_computer_is_refused_and_nothing_is_sent(monkeypatch):
    def handler(req):
        raise AssertionError("must not be called")

    fake_app(monkeypatch, handler)
    out = await fetch(PID, "http://example.com", "mine", 7, None)
    assert out == {"ok": False, "reason": "The live run only talks to an app running on this computer (localhost)."}
    out = await fetch(PID, "not an address", "mine", 7, None)
    assert out["ok"] is False and "Enter the app's address" in out["reason"]


@pytest.mark.asyncio
async def test_no_key_yet_says_how_to_get_one(monkeypatch):
    out = await fetch(PID, "http://localhost:3000", None, 7, None)
    assert out["ok"] is False and "Apply the agent once" in out["reason"]


@pytest.mark.asyncio
async def test_an_old_app_with_no_insights_route_gets_the_apply_again_sentence(monkeypatch):
    def handler(req: httpx.Request):
        if req.url.path == "/api/agent/insights":
            return httpx.Response(404, json={"error": "Not found."})
        return httpx.Response(200, json={"agents": []})  # the debug route knows the key

    fake_app(monkeypatch, handler)
    out = await fetch(PID, "http://localhost:3000", "k", 7, None)
    assert out == {"ok": False, "reason": agent_debug.NO_INSIGHTS}
    assert "does not record insights yet" in out["reason"] and "apply the agent again" in out["reason"] and "push the database changes" in out["reason"]


@pytest.mark.asyncio
async def test_a_wrong_key_is_not_mistaken_for_an_old_app(paired, monkeypatch):
    fake_app(monkeypatch, lambda req: httpx.Response(404, json={"error": "Not found."}))
    assert (await fetch(PID, "tunnel", None, 7, None))["reason"] == agent_debug.WRONG_KEY
    out = await fetch(PID, "http://localhost:3000", "k", 7, None)
    assert "did not accept the live run" in out["reason"] and "does not record" not in out["reason"]


@pytest.mark.asyncio
async def test_each_way_the_tunnel_can_fail_is_its_own_sentence(tunnel, monkeypatch):
    assert (await fetch(PID, "tunnel", None, 7, None))["reason"] == agent_debug.NOT_PAIRED
    agent_tunnel.pair(agent_tunnel.new_pairing(PID)["code"], key(), 3001, SECRET, client_ip="1.2.3.4")
    assert (await fetch(PID, "tunnel", None, 7, None))["reason"] == agent_debug.TUNNEL_DOWN
    monkeypatch.setattr(agent_tunnel, "listener_open", lambda port, timeout=1.5: True)

    def gone(req):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    fake_app(monkeypatch, gone)
    assert "connected, but nothing answered on port 3001" in (await fetch(PID, "tunnel", None, 7, None))["reason"]

    def refused(req):
        raise httpx.ConnectError("refused")

    fake_app(monkeypatch, refused)
    assert (await fetch(PID, "tunnel", None, 7, None))["reason"] == agent_debug.TUNNEL_DOWN

    def slow(req):
        raise httpx.ReadTimeout("slow")

    fake_app(monkeypatch, slow)
    assert "took too long" in (await fetch(PID, "tunnel", None, 7, None))["reason"]


@pytest.mark.asyncio
async def test_a_platform_on_the_builders_own_computer_has_no_tunnel(monkeypatch):
    monkeypatch.delenv("FORGE_TUNNEL_DIR", raising=False)
    out = await fetch(PID, "tunnel", None, 7, None)
    assert out["ok"] is False and "runs on your own computer" in out["reason"]


@pytest.mark.asyncio
async def test_a_stopped_local_app_and_a_server_error_and_a_page_that_is_not_json_are_plain_sentences(monkeypatch):
    def refused(req):
        raise httpx.ConnectError("no")

    fake_app(monkeypatch, refused)
    assert "Could not reach the app at http://localhost:3000. Is it running?" == (await fetch(PID, "http://localhost:3000", "k", 7, None))["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    assert "answered with an error (500)" in (await fetch(PID, "http://localhost:3000", "k", 7, None))["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(200, text="<html>a page</html>"))
    assert "not one of your apps" in (await fetch(PID, "http://localhost:3000", "k", 7, None))["reason"]
    fake_app(monkeypatch, lambda req: httpx.Response(200, json={"hello": "world"}))
    assert "not one of your apps" in (await fetch(PID, "http://localhost:3000", "k", 7, None))["reason"]


@pytest.mark.asyncio
async def test_an_answer_far_bigger_than_an_insights_page_is_refused(monkeypatch):
    fake_app(monkeypatch, lambda req: httpx.Response(200, content=b"[" + b"1," * 1_500_000 + b"1]"))
    out = await fetch(PID, "http://localhost:3000", "k", 7, None)
    assert out["ok"] is False and "far more than an insights page holds" in out["reason"]
