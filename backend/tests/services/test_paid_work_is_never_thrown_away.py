"""Paid work is never thrown away.

Of the 73 builds on this machine that finished between 2026-09-15 and
2026-09-22, 34 ended with something failed or left flagged, and every
failure was paid for before it was found. Three shapes of waste, and what
each is replaced with:

* a reply the contract refused was WRITTEN AGAIN from nothing — 31 full
  rewrites. The retry now edits the refused proposals in place;
* a reply cut off at `max_tokens` was retried as "malformed" — same
  question, same budget, often the same cut. It is now told it was cut off,
  and asked again with the least effort and the most room;
* the API's own failures were charged to the author: a low balance FAILED a
  page (HippieKit, 2026-09-22), and a busy API burned attempts. A busy API is
  re-sent after a pause without counting; an account that cannot pay pauses
  the run with nothing lost, and is refused before the run spends at all.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from services.blueprint import orchestrator
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.artifact_patch import PATCH_SCHEMA
from services.blueprint.executors import (
    BuildCannotStart, ModelReply, Truncated, Usage, api_outage, make_executor, preflight,
)
from services.blueprint.orchestrator import TaskSpec, run
from services.blueprint.run_ledger import read, runs
from services.blueprint.service import BlueprintService


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="lab", name="Lab", domain="health")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "One borrower per rental"}]
    # Declared through the service, so the allocator knows each entity's id
    # and a later proposal by name updates that row rather than the next id.
    for i in range(1, 4):
        s.upsert("data.entities", {"name": f"E{i}", "table": f"e{i}"}, natural_key=f"E{i}")
    s.save()
    return s


def _events(svc):
    return read(svc.output_dir, runs(svc.output_dir)[0])


def _last_end(svc):
    return [e for e in _events(svc) if e["event"] == "run:end"][-1]


# --- 1. a refused reply is edited, not rewritten -------------------------------

def _envelope(*proposals: dict) -> str:
    return json.dumps({"proposals": [{"section": p["section"], "natural_key": p["natural_key"],
                                      "body": json.dumps(p["body"])} for p in proposals],
                       "confidence": 0.9, "assumptions": [], "issues": [], "change_requests": []})


class _RefusedThenEdits:
    """Writes a rule the contract refuses (no `statement`), then, asked to
    EDIT, adds the one field."""

    enforces_schema = True

    def __init__(self):
        self.calls: list[tuple[str, str]] = []      # (kind, user prompt)

    def __call__(self, *, system, user, schema, **_):
        if schema is PATCH_SCHEMA:
            self.calls.append(("edit", system + "\n" + user))
            return json.dumps({"edits": [{"op": "add", "path": "/artifacts/0/body/statement",
                                          "value": json.dumps("Every rental has one borrower.")}],
                               "note": ""})
        self.calls.append(("write", user))
        return _envelope({"section": "businessRules", "natural_key": "One borrower",
                          "body": {"name": "One borrower", "requirements": ["REQ-001"]}})


def test_a_reply_the_contract_refused_is_edited_on_the_retry(svc):
    client = _RefusedThenEdits()
    report = run(svc, make_executor(svc, client), plan=["business_rules"], commit=True)
    assert [k for k, _ in client.calls] == ["write", "edit"], client.calls
    _, edit_prompt = client.calls[1]
    assert "REFUSED" in edit_prompt and "statement" in edit_prompt
    assert "business_rules" in report.completed and not report.failed
    rule = next(r for r in svc.doc["businessRules"] if r["name"] == "One borrower")
    assert rule["statement"] == "Every rental has one borrower."


def test_the_retry_spec_carries_what_was_refused(svc):
    """The scheduler hands the refused proposals to the retry as `current`,
    and marks it a retry (not an observer repair), so it keeps its effort."""
    seen: list[TaskSpec] = []

    def author(spec):
        seen.append(spec)
        body = {"name": "R", "requirements": ["REQ-001"]}
        if spec.attempt == 2:
            body["statement"] = "fixed"
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="businessRules", natural_key="R", body=body)])

    run(svc, author, plan=["business_rules"], commit=True)
    assert [s.attempt for s in seen] == [1, 2]
    assert seen[0].current == ()
    assert [a["natural_key"] for a in seen[1].current] == ["R"] and seen[1].repair is False


# --- 2. a reply cut off at the budget is asked again with room -----------------

@dataclasses.dataclass
class _CutOffThenWhole:
    effort: str = "high"
    max_tokens: int = 24000
    enforces_schema: bool = True
    log: list = dataclasses.field(default_factory=list)

    def __call__(self, *, system, user, schema, **_):
        self.log.append((self.effort, self.max_tokens, user))
        if len(self.log) == 1:
            return ModelReply(text='{"proposals": [{"section": "businessRules", "natural_key": "x", "body": "{\\"name\\": \\"Unfini',
                              usage=Usage(model="m", output_tokens=24000), stop_reason="max_tokens")
        return ModelReply(text=_envelope({"section": "businessRules", "natural_key": "R",
                                          "body": {"name": "R", "statement": "s", "requirements": ["REQ-001"]}}),
                          usage=Usage(model="m", output_tokens=900), stop_reason="end_turn")


def test_a_cut_off_reply_is_retried_with_the_least_effort_and_the_most_room(svc):
    client = _CutOffThenWhole()
    report = run(svc, make_executor(svc, client), plan=["business_rules"], commit=True)
    assert [(e, m) for e, m, _ in client.log] == [("high", 24000), ("low", 64000)]
    assert "CUT OFF" in client.log[1][2] and "rejected" not in client.log[1][2]
    assert "business_rules" in report.completed


def test_a_reply_still_cut_off_after_that_surfaces_as_truncated(svc):
    @dataclasses.dataclass
    class Always:
        effort: str = "high"
        max_tokens: int = 24000
        enforces_schema: bool = True

        def __call__(self, *, system, user, schema, **_):
            return ModelReply(text='{"proposals": [{"section": "businessRules"',
                              usage=Usage(model="m", output_tokens=24000), stop_reason="max_tokens")

    with pytest.raises(Truncated, match="cut off"):
        make_executor(svc, Always())(TaskSpec(task_id="T", node="business_rules", agent="business_rules"))


# --- 3. the API's failure is not the author's attempt --------------------------

def _fields(svc, spec):
    entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
    body = {"name": entity["name"], "table": entity["table"],
            "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}
    return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                       proposals=[ArtifactProposal(section="data.entities", natural_key=entity["name"], body=body)])


def test_what_an_outage_is():
    assert api_outage(RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API")) == "credit"
    assert api_outage(RuntimeError("Error code: 529 - overloaded_error: Overloaded")) == "transient"
    assert api_outage(RuntimeError("InvalidPageContent: /home: 'x' ...")) is None
    # A free word is not the API: a composer that "timed out" is its own fault.
    assert api_outage(RuntimeError("a2ui composition timed out")) is None
    assert api_outage(RuntimeError("connection refused")) is None
    import anthropic
    import httpx
    req = httpx.Request("POST", "https://x")
    assert api_outage(anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)) == "transient"
    assert api_outage(anthropic.APITimeoutError(request=req)) == "transient"
    assert api_outage(anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)) == "credit"


def test_a_busy_api_is_re_sent_without_counting_an_attempt(svc, monkeypatch):
    monkeypatch.setattr(orchestrator, "OUTAGE_BACKOFF_S", 0.0)
    calls: list[tuple[str, int]] = []

    def author(spec):
        calls.append((spec.subject, spec.attempt))
        if spec.subject == "ENTITY-002" and calls.count(("ENTITY-002", 1)) == 1:
            raise RuntimeError("Error code: 529 - {'type': 'overloaded_error'}")
        return _fields(svc, spec)

    report = run(svc, author, plan=["entity_fields"], commit=True, max_attempts=1)
    assert not report.failed and "entity_fields" in report.completed
    assert calls.count(("ENTITY-002", 1)) == 2, "the re-send is attempt 1 again"
    assert any(e["event"] == "node:stalled" for e in _events(svc))


def test_an_outage_that_outlasts_the_wait_fails_with_the_apis_words(svc, monkeypatch):
    monkeypatch.setattr(orchestrator, "OUTAGE_BACKOFF_S", 0.0)

    def author(spec):
        if spec.subject == "ENTITY-002":
            raise RuntimeError("Error code: 529 - overloaded")
        return _fields(svc, spec)

    report = run(svc, author, plan=["entity_fields"], commit=True, max_attempts=1)
    assert report.failed == ["entity_fields:ENTITY-002"]
    assert "failed this call 4 times" in report.failed_because["entity_fields:ENTITY-002"]
    assert not report.paused_because


def test_an_account_that_cannot_pay_pauses_the_run_and_the_next_run_continues(svc):
    order: list[str] = []
    broke = ["ENTITY-002"]

    def author(spec):
        order.append(spec.subject)
        if spec.subject in broke:
            raise RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
        return _fields(svc, spec)

    report = run(svc, author, plan=["entity_fields", "security"], commit=True)
    assert "credit balance" in report.paused_because
    assert report.failed == [] and report.ok is False
    assert "entity_fields" in report.skipped and report.skipped_because["entity_fields"].startswith("paused:")
    assert "1 of 3 subjects still to author" in report.skipped_because["entity_fields"]
    assert "security" in report.skipped
    end = _last_end(svc)
    assert "credit balance" in end["pausedBecause"] and end["failed"] == []
    assert any(e["event"] == "run:paused" for e in _events(svc))
    # What landed is in the Blueprint.
    fields = {e["name"]: bool(e.get("fields")) for e in svc.doc["data"]["entities"]}
    assert fields == {"E1": True, "E2": False, "E3": True}

    # Topped up: the next run authors only what is still to do.
    broke.clear()
    order.clear()
    again = run(svc, author, plan=["entity_fields"], commit=True)
    assert order == ["ENTITY-002"] and again.ok


def test_nothing_is_spent_on_an_api_that_cannot_be_paid(svc):
    """The first call is the preflight: refused for a low balance, it is not
    billed, and nothing is sent after it."""
    called = []

    def author(spec):
        called.append(spec.subject)
        raise RuntimeError("Error code: 400 - Your credit balance is too low to access the Anthropic API.")

    report = run(svc, author, plan=["entity_fields", "security"], commit=True)
    # The fan-out had already handed every subject to the pool; each one
    # was refused unbilled. Nothing was sent once the first refusal landed.
    assert set(called) <= {"ENTITY-001", "ENTITY-002", "ENTITY-003"}
    assert report.ok is False and report.failed == []
    assert sorted(report.skipped) == ["entity_fields", "security"]
    assert "credit balance" in _last_end(svc)["pausedBecause"]


def test_the_preflight_lets_a_busy_api_through_and_stops_an_unpaid_one():
    class Busy:
        def preflight(self):
            raise RuntimeError("Error code: 529 - overloaded")

    class Unpaid:
        def preflight(self):
            raise RuntimeError("Error code: 400 - Your credit balance is too low")

    preflight(Busy())                      # the run handles that as it happens
    preflight(object())                    # nothing to check with
    with pytest.raises(BuildCannotStart):
        preflight(Unpaid())


def test_the_real_client_has_a_one_token_preflight():
    from services.blueprint.executors import AnthropicModel
    assert callable(getattr(AnthropicModel(), "preflight", None))


def test_an_outage_during_a_repair_gives_the_round_back(svc, monkeypatch):
    from services.blueprint.observer import Observer

    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "entity_fields", raising=False)

    def author(spec):
        if spec.repair:
            raise RuntimeError("Error code: 400 - Your credit balance is too low")
        return _fields(svc, spec)

    class Critic:
        enforces_schema = True

        def __call__(self, *, system, user, schema):
            subject = json.loads(user)["subject"]
            if subject == "ENTITY-001":
                return json.dumps({"verdict": "fail", "findings": [{
                    "section": "data.entities", "artifact": subject, "detail": "no created-at"}]})
            return json.dumps({"verdict": "pass", "findings": []})

    report = run(svc, author, plan=["entity_fields"], commit=True,
                 observer_agent=Observer(critic=Critic(), rounds=2))
    assert report.paused_because and report.unrepaired == {} and report.failed == []
    entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == "ENTITY-001")
    assert entity.get("status") != "OUT_OF_SYNC", "nothing judged the repair; the API never ran it"


# --- the reply schema mirrors the contract, key for key ------------------------

def test_the_data_model_reply_schema_cannot_say_what_the_contract_refuses():
    """Rule 2 at the one node whose reply is typed: every key the reply schema
    lets the model write is a key the contract accepts, everything the
    contract requires the reply requires, and no `enum` is looser."""
    from services.blueprint.executors import DATA_MODEL_SCHEMA

    contract = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json").read_text())
    c_entity = contract["properties"]["data"]["properties"]["entities"]["items"]
    r_entity = DATA_MODEL_SCHEMA["properties"]["entities"]["items"]
    assert set(r_entity["properties"]) <= set(c_entity["properties"]), \
        set(r_entity["properties"]) - set(c_entity["properties"])
    assert set(c_entity["required"]) - {"id"} <= set(r_entity["required"])
    c_field = c_entity["properties"]["fields"]["items"]
    r_field = r_entity["properties"]["fields"]["items"]
    assert set(r_field["properties"]) <= set(c_field["properties"])
    assert set(c_field["required"]) <= set(r_field["required"])
    assert r_field["additionalProperties"] is False
    for name, shape in c_field["properties"].items():
        if "enum" in shape:
            assert r_field["properties"][name].get("enum") == shape["enum"], name
