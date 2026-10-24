"""Receiving events: every way an event or a request is refused, and the plain sentence that says why. No database here."""
from __future__ import annotations

import gzip
import json
from datetime import timedelta

import pytest

from services import agent_insights_ingest as ingest
from services import agent_insights_keys as keys
from tests.insights_stream_helpers import NOW, handoff, rating, turn

N = NOW.timestamp()


def body(events, schema=1) -> bytes:
    return json.dumps({"schema": schema, "events": events}).encode()


def reason_for(event) -> str:
    with pytest.raises(ingest.Reject) as e:
        ingest.normalize_event(event, N)
    return str(e.value)


def good_turn(**kw):
    return turn(1, NOW - timedelta(minutes=1), **kw)


# --- a good event ------------------------------------------------------------------------------------------------

def test_a_good_turn_is_kept_in_its_short_form():
    ev = ingest.normalize_event(good_turn(tools=[{"name": "refund", "ok": False, "ms": 40}], role=None, model=None), N)
    assert ev["t"] == "turn" and ev["r"] == "" and ev["m"] == "" and ev["tl"] == [["refund", 0, 40]] and ev["te"] == 1 and ev["tc"] == 1
    assert ev["at"] == pytest.approx((NOW - timedelta(minutes=1)).timestamp())


def test_a_user_key_is_lower_cased_and_unknown_fields_are_ignored():
    raw = good_turn()
    raw["userKey"] = raw["userKey"].upper()
    raw["somethingNew"] = "ignored"
    assert ingest.normalize_event(raw, N)["u"] == raw["userKey"].lower()


def test_free_text_is_cut_not_refused():
    long = "x" * 500
    ev = ingest.normalize_event(good_turn(problem={"reason": "error", "message": long, "detail": long}), N)
    assert len(ev["p"][1]) == 200 and len(ev["p"][2]) == 200
    assert len(ingest.normalize_event(rating(1, 1, NOW, note=long), N)["nt"]) == 300


# --- every refusal -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mutate, expect", [
    (lambda e: e.update(id="short"), "The 'id' must be 8 to 64 letters, numbers, dashes or underscores."),
    (lambda e: e.update(id="has spaces in it"), "The 'id' must be 8 to 64"),
    (lambda e: e.update(id="x" * 65), "The 'id' must be 8 to 64"),
    (lambda e: e.update(at="yesterday"), "The 'at' must be an ISO-8601 time"),
    (lambda e: e.update(at=12345), "The 'at' must be an ISO-8601 time"),
    (lambda e: e.update(agentId=""), "The 'agentId' must be text of 1 to 80 characters."),
    (lambda e: e.update(agentId="a" * 81), "The 'agentId' is longer than 80 characters."),
    (lambda e: e.update(conversationId=None), "The 'conversationId' must be text of 1 to 64 characters."),
    (lambda e: e.update(userKey="not-hex-at-all-nope"), "The 'userKey' must be 16 to 64 hexadecimal characters"),
    (lambda e: e.update(userKey="abc"), "The 'userKey' must be 16 to 64 hexadecimal characters"),
    (lambda e: e.update(role="r" * 61), "The 'role' is longer than 60 characters."),
    (lambda e: e.update(env="staging"), "The 'env' must be production or development."),
    (lambda e: e.update(model="m" * 101), "The 'model' is longer than 100 characters."),
    (lambda e: e.update(inputTokens=-1), "The 'inputTokens' must be a whole number of 0 or more."),
    (lambda e: e.update(inputTokens="12"), "The 'inputTokens' must be a whole number of 0 or more."),
    (lambda e: e.update(inputTokens=True), "The 'inputTokens' must be a whole number of 0 or more."),
    (lambda e: e.update(outputTokens=1.5), "The 'outputTokens' must be a whole number of 0 or more."),
    (lambda e: e.update(ms=None), "The 'ms' must be a whole number of 0 or more."),
    (lambda e: e.update(ms=10 ** 12), "The 'ms' is too large"),
    (lambda e: e.update(status="done"), "The 'status' must be ok, error or blocked."),
    (lambda e: e.update(toolCalls=1, toolErrors=2), "The 'toolErrors' cannot be more than the 'toolCalls'."),
    (lambda e: e.update(tools="x"), "The 'tools' must be a list."),
    (lambda e: e.update(tools=[{"name": "t", "ok": True, "ms": 1}] * 21), "The 'tools' list can hold at most 20 tools."),
    (lambda e: e.update(tools=[{"name": "t", "ok": "yes", "ms": 1}]), "The 'tools.ok' must be true or false."),
    (lambda e: e.update(tools=["t"]), "Each entry of 'tools' must be an object"),
    (lambda e: e.update(handedOff="no"), "The 'handedOff' must be true or false."),
    (lambda e: e.update(turnNumber=0), "The 'turnNumber' must be a whole number of 1 or more."),
    (lambda e: e.update(problem={"reason": "weird"}), "The 'problem' must be null or have a 'reason' of"),
    (lambda e: e.update(type="nonsense"), "The 'type' must be turn, rating or handoff."),
])
def test_a_bad_turn_is_refused_with_its_reason(mutate, expect):
    ev = good_turn()
    mutate(ev)
    assert expect in reason_for(ev)


def test_an_entry_that_is_not_an_object_is_refused():
    assert "not a JSON object" in reason_for("hello")
    assert "not a JSON object" in reason_for(None)


def test_events_too_old_or_from_the_future_are_refused():
    assert "older than 90 days" in reason_for(turn(1, NOW - timedelta(days=91)))
    ingest.normalize_event(turn(1, NOW - timedelta(days=89)), N)
    assert "5 minutes in the future" in reason_for(turn(1, NOW + timedelta(minutes=6)))
    ingest.normalize_event(turn(1, NOW + timedelta(minutes=4)), N)


def test_a_time_without_a_zone_counts_as_utc_and_an_offset_is_converted():
    a = good_turn()
    a["at"] = "2026-10-22T12:00:00"
    b = good_turn()
    b["at"] = "2026-10-22T17:30:00+05:30"
    assert ingest.normalize_event(a, N)["at"] == ingest.normalize_event(b, N)["at"]


def test_ratings_and_handoffs_are_checked_too():
    assert "must be 1 (thumbs up) or -1" in reason_for({**rating(1, 1, NOW), "rating": 5})
    assert "must be 1 (thumbs up) or -1" in reason_for({**rating(1, 1, NOW), "rating": True})
    assert "'turnId'" in reason_for({**rating(1, 1, NOW), "turnId": "no"})
    assert "open, claimed or resolved" in reason_for({**handoff("c1", "open", NOW), "status": "gone"})
    assert "resolveMinutes" in reason_for({**handoff("c1", "resolved", NOW), "resolveMinutes": -3})
    assert "resolveMinutes" in reason_for({**handoff("c1", "resolved", NOW), "resolveMinutes": "soon"})
    assert ingest.normalize_event(handoff("c1", "resolved", NOW, minutes=4.5), N)["rm"] == 4.5


# --- a whole request ---------------------------------------------------------------------------------------------

def test_one_bad_event_does_not_cost_its_batch():
    bad = good_turn()
    bad["status"] = "nope"
    p = ingest.parse_body(body([turn(1, NOW), bad, turn(2, NOW)]), now=N)
    assert [e["id"] for e in p.events] == ["turn-00000001", "turn-00000002"]
    assert p.rejected == [{"index": 1, "reason": "The 'status' must be ok, error or blocked."}] and p.rejected_count == 1


def test_at_most_twenty_rejections_are_listed_but_all_are_counted():
    p = ingest.parse_body(body([{"type": "turn"}] * 45), now=N)
    assert len(p.rejected) == 20 and p.rejected_count == 45 and p.events == []


def test_the_same_event_twice_in_one_request_is_a_duplicate_not_an_event():
    p = ingest.parse_body(body([turn(1, NOW), turn(1, NOW), turn(2, NOW)]), now=N)
    assert len(p.events) == 2 and p.duplicates == 1


@pytest.mark.parametrize("raw, status", [
    (b"{not json", 400),
    (b"[]", 400),
    (json.dumps({"schema": 2, "events": []}).encode(), 400),
    (json.dumps({"events": []}).encode(), 400),
    (json.dumps({"schema": 1, "events": "x"}).encode(), 400),
    (json.dumps({"schema": 1, "events": [{}] * 501}).encode(), 413),
])
def test_a_malformed_or_oversized_request_is_refused_whole(raw, status):
    with pytest.raises(ingest.IngestError) as e:
        ingest.parse_body(raw, now=N)
    assert e.value.status == status and e.value.message.endswith((".", "events)."))


def test_five_hundred_events_are_fine_and_501_are_not():
    assert len(ingest.parse_body(body([turn(i, NOW) for i in range(500)]), now=N).events) == 500
    with pytest.raises(ingest.IngestError) as e:
        ingest.parse_body(body([turn(i, NOW) for i in range(501)]), now=N)
    assert e.value.status == 413 and "at most 500" in e.value.message


def test_a_body_over_one_megabyte_is_refused_plain_or_gzipped():
    big = b" " * (ingest.MAX_BODY_BYTES + 1)
    with pytest.raises(ingest.IngestError) as e:
        ingest.decode_body(big, None)
    assert e.value.status == 413
    # a tiny gzip that expands past the limit is caught while unzipping, not after it has filled memory
    bomb = gzip.compress(b" " * (ingest.MAX_BODY_BYTES + 10))
    assert len(bomb) < 10_000
    with pytest.raises(ingest.IngestError) as e:
        ingest.decode_body(bomb, "gzip")
    assert e.value.status == 413 and "once unzipped" in e.value.message


def test_gzip_is_unzipped_and_a_broken_gzip_is_a_400():
    raw = body([turn(1, NOW)])
    assert ingest.decode_body(gzip.compress(raw), "gzip") == raw
    assert ingest.decode_body(raw, "identity") == raw
    with pytest.raises(ingest.IngestError) as e:
        ingest.decode_body(b"this is not gzip", "gzip")
    assert e.value.status == 400
    with pytest.raises(ingest.IngestError) as e:
        ingest.decode_body(raw, "br")
    assert e.value.status == 400


# --- the rate limit ----------------------------------------------------------------------------------------------

def test_the_rate_limit_allows_a_burst_then_the_sustained_rate_and_says_how_long_to_wait():
    t = [0.0]
    limiter = ingest.KeyRateLimiter(rate=200, burst=400, clock=lambda: t[0])
    assert all(limiter.allow("k")[0] for _ in range(400))           # the burst
    ok, wait = limiter.allow("k")
    assert not ok and 0 < wait <= 0.01                              # the 401st at once: a request's worth of time
    t[0] += 1.0                                                     # one second later: 200 more
    assert sum(limiter.allow("k")[0] for _ in range(300)) == 200
    assert limiter.allow("someone-else")[0]                         # keys do not share a bucket


# --- keys --------------------------------------------------------------------------------------------------------

def test_a_key_has_the_documented_shape_and_only_its_hash_is_derived():
    k = keys.generate_key()
    assert k.startswith("fik_") and len(k) == 44 and keys.looks_like_key(k)
    assert keys.generate_key() != k
    assert len(keys.hash_key(k)) == 64 and k not in keys.hash_key(k)
    assert not keys.looks_like_key(k[:-1]) and not keys.looks_like_key("fik_" + "!" * 40) and not keys.looks_like_key("x" + k[1:])
